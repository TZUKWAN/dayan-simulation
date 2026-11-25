"""Runs ONLY inside the isolated solver image, after the supervisor drops privileges."""
import contextlib
import importlib.metadata
import json
import math
import sys
import traceback

import numpy as np

sys.path.insert(0, "/opt/dayan")
from codec import decode, digest, dumps, encode
from decisions import describe, verify_bundle

PROTOCOL = "dayan-solver-segment-v1"
METHODS = ("initialize", "advance", "observe", "frame", "validate")


def segment(request):
    if request["protocol"] != PROTOCOL:
        raise ValueError("求解器协议不匹配")
    identity_fields={key: request[key] for key in ("protocol", "source", "parameters", "inputs", "seed", "dt", "ticks",'interventions')}
    policy=request.get('decision_policy')
    if policy is not None:identity_fields['decision_policy']=policy
    identity = digest(identity_fields)
    params, inputs = decode(request["parameters"]), decode(request["inputs"])
    input_hash = digest(encode({"parameters": params, "inputs": inputs}))
    rng = np.random.default_rng(request["seed"])
    namespace = {"__name__": "dayan_user_model", "__file__": "<reviewed-model>"}
    exec(compile(request["source"], "<reviewed-model>", "exec"), namespace)
    if any(not callable(namespace.get(name)) for name in METHODS):
        raise ValueError("模型必须实现initialize/advance/observe/frame/validate五个函数")
    if policy is not None and not callable(namespace.get('decision_requests')):
        raise ValueError('LLM程序必须实现纯读decision_requests')
    prior = request.get("checkpoint")
    if prior:
        if prior["protocol"] != PROTOCOL or prior["identity"] != identity:
            raise ValueError("求解器检查点的源码、数据或原始执行设置已变化")
        step = prior["step"]
        if type(step) is not int or not 0 <= step <= request["ticks"] or prior["time"] != step * request["dt"]:
            raise ValueError("求解器检查点时钟不一致")
        state = decode(prior["state"])
        rng.bit_generator.state = decode(prior["rng"])
        cursor=prior['intervention_cursor']
        if (type(cursor) is not int or not 0<=cursor<=len(request['interventions'])
                or cursor!=sum(rule['at_t']<=prior['time'] for rule in request['interventions'])):
            raise ValueError('检查点干预游标与实际时钟不一致')
        expected_params=dict(params)
        for change in request['interventions'][:cursor]:expected_params.update(change['params'])
        params=decode(prior['parameters'])
        if params!=expected_params:raise ValueError('检查点实际参数与干预历史不一致')
        input_hash=digest(encode({'parameters':params,'inputs':inputs}))
    else:
        step = 0
        cursor = 0
        state = namespace["initialize"](params, inputs, rng)
    start = step
    records = []

    def capture(events):
        if not isinstance(state, dict):
            raise ValueError("initialize/advance返回的state必须是结构化对象")
        t = step * request["dt"]
        before = encode(state)
        state_hash = digest(before)
        rng_hash = digest(encode(rng.bit_generator.state))
        issues = namespace["validate"](state, params, inputs, t)
        if issues not in (None, []):
            raise ValueError("实际状态验证失败：" + str(issues))
        values = encode(namespace["observe"](state, params, inputs, t))
        if (not isinstance(values, dict) or not values or any(not isinstance(key, str) or not key
                or type(value) not in (int, float) or not math.isfinite(value) for key, value in values.items())):
            raise ValueError("observe必须返回非空、有限的数值观测对象")
        frame = encode(namespace["frame"](state, params, inputs, t))
        if not isinstance(frame, dict) or not frame:
            raise ValueError("frame必须返回实际状态对象")
        if "sim_t" in frame and frame["sim_t"] != t:
            raise ValueError("状态帧时刻与实际求解时钟不符")
        frame["sim_t"] = t
        if (digest(encode(state)) != state_hash or digest(encode(rng.bit_generator.state)) != rng_hash
                or digest(encode({"parameters": params, "inputs": inputs})) != input_hash):
            raise ValueError("观测/验证/渲染修改了实际状态或随机流，或模型修改了只读输入")
        records.append({"step": step, "time": t, "observations": values, "frame": frame, "events": encode(events)})
        return before

    def apply_at(t):
        nonlocal cursor,input_hash
        if digest(encode({'parameters':params,'inputs':inputs}))!=input_hash:
            raise ValueError('模型修改了只读参数或输入')
        changes=[]
        while cursor<len(request['interventions']) and request['interventions'][cursor]['at_t']<=t:
            rule=request['interventions'][cursor]
            params.update(rule['params'])
            changes.append({'time':rule['at_t'],'type':'intervention','requested_t':rule['requested_t'],
                            'actual_t':rule['at_t'],'params':rule['params'],'label':rule['label'],
                            'order':rule['order'],'applied':True})
            cursor+=1
        input_hash=digest(encode({'parameters':params,'inputs':inputs}))
        return changes

    snapshot = capture(apply_at(0.)) if not prior else (capture([]) if request.get('capture_initial') else encode(state))
    initial_checkpoint = ({'protocol':PROTOCOL,'identity':identity,'step':0,'time':0.,
                           'state':snapshot,'rng':encode(rng.bit_generator.state),
                           'parameters':encode(params),'intervention_cursor':cursor}
                          if not prior and request.get('initial_checkpoint') else None)
    # The public state is a value tree. Normalize at every boundary so array
    # aliasing cannot behave differently in uninterrupted vs resumed segments.
    state = decode(snapshot)
    endpoint = min(request["ticks"], start + request["segment_steps"])
    while step < endpoint:
        t = step * request["dt"]
        decisions=None
        if policy is not None:
            descriptor=describe(namespace['decision_requests'],state,params,inputs,rng,step,request['dt'],policy)
            if step==start:
                decisions=verify_bundle(request.get('decision_bundle'),descriptor)
            elif descriptor['requests']:
                break  # Return this exact state before any new external decision is needed.
            else:
                decisions={}
        end=(step+1)*request['dt']
        events=apply_at(t)
        while t<end:
            next_change=request['interventions'][cursor]['at_t'] if cursor<len(request['interventions']) else end
            target=min(end,next_change)
            outcome = (namespace["advance"](state, params, inputs, rng, t, target-t, decisions) if policy is not None
                       else namespace["advance"](state, params, inputs, rng, t, target-t))
            if not isinstance(outcome, dict) or set(outcome) != {"state", "events"} or not isinstance(outcome["events"], list):
                raise ValueError("advance必须返回state和events，事件须为列表")
            state = outcome["state"]
            for event in outcome["events"]:
                if (not isinstance(event, dict) or type(event.get("time")) not in (int, float)
                        or not math.isfinite(event["time"]) or not t - 1e-12 <= event["time"] <= target + 1e-12
                        or not isinstance(event.get("type"), str) or not event["type"] or event['type']=='intervention'):
                    raise ValueError("领域事件须有真实类型及当前推进区间内的时刻；intervention由平台保留")
            events.extend(outcome['events'])
            t=target
            events.extend(apply_at(t))
        step += 1
        snapshot = capture(events)
        state = decode(snapshot)
    checkpoint = {"protocol": PROTOCOL, "identity": identity, "step": step, "time": step * request["dt"],
                  "state": snapshot, "rng": encode(rng.bit_generator.state),
                  'parameters':encode(params),'intervention_cursor':cursor}
    next_decisions=(describe(namespace['decision_requests'],state,params,inputs,rng,step,request['dt'],policy)
                    if policy is not None and step<request['ticks'] else None)
    return {"protocol": PROTOCOL, "identity": identity, "from_step": start, "to_step": step,
            "complete": step == request["ticks"], "records": records, "checkpoint": checkpoint,
            'initial_checkpoint':initial_checkpoint, 'next_decisions':next_decisions}


def main():
    request = json.load(sys.stdin)
    # User print/logging is kept separate from the structured result channel.
    with contextlib.redirect_stdout(sys.stderr):
        result = segment(request)
    sys.stdout.write(dumps(result))


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        traceback.print_exc(file=sys.stderr)
        raise SystemExit(1)
