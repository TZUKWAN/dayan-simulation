"""Authoritative managed-program orchestration, using only isolated code execution."""
from copy import deepcopy
from datetime import datetime, timezone
import time
import uuid

from .limits import BudgetExceeded, limits, validate_compute
from .program_frames import state_frame
from .program_models import effective_parameters, population_plan, intervention_schedule
from .run_progress import RunPaused
from .solvers.codec import decode, digest, dumps, encode
from .solvers.sandbox import SandboxBudget, image_contract, run_segment, PROTOCOL


class StepView:
    """Read-only callback view of an actual captured step, not a host model."""
    def __init__(self, row, frame):
        self._row,self._frame=deepcopy(row),deepcopy(frame)

    def observe(self):return deepcopy(self._row)

    def state_frame(self):return deepcopy(self._frame)


def run_program(mid, cls, *, parameters, requested_parameters, ticks, dt, seed, experiment, issues,
                with_time, checkpoint_at, interventions, on_step, capture_state, state_every,
                data_evidence, full_frames, progress, source_version, resume_context=None, with_initial=False,
                prepared_inputs=None):
    from .runtime import RunResult, assert_loaded_source
    from .task_worker import frame_observer
    d=cls.definition
    policy=d.get('decision_policy')
    params=effective_parameters(d,parameters)
    inputs=deepcopy(resume_context['inputs'] if resume_context else prepared_inputs or {})
    from .structured_inputs import port_contracts
    actual_ports={name:asset['contract'] for name,asset in inputs.items()}
    if port_contracts(actual_ports)!=d.get('input_ports',{}):
        raise ValueError('隔离输入与程序input_ports不一致')
    expected=population_plan(d,params,inputs)
    data_evidence=deepcopy(data_evidence)
    origin=resume_context['checkpoint']['step'] if resume_context else 0
    endpoint=resume_context['endpoint'] if resume_context else ticks
    validate_compute(endpoint-origin,parameters=params,array=True)
    schedule=resume_context['interventions'] if resume_context else intervention_schedule(d,params,interventions,ticks,dt)
    if type(state_every) is not int or state_every<1:raise ValueError('state_every须为正整数')
    if checkpoint_at is not None and (type(checkpoint_at) is not int or not 0<=checkpoint_at<=ticks):
        raise ValueError('checkpoint_at须为运行范围内的整数')
    if on_step is not None and not callable(on_step):raise ValueError('on_step须为可调用对象')
    image=image_contract(resume_context['image_id'] if resume_context else None)
    budget=SandboxBudget(memory_bytes=limits().memory_bytes, output_bytes=limits().job_bytes,
                         wall_seconds=min(120,limits().wall_seconds),cpus=1.)
    # Frame retention affects only archival frequency, never the actual population.
    if full_frames:
        stride=1
    elif 'state_every' in d:
        stride=max(state_every,d['state_every'])
        frame_count=(endpoint-origin)//stride+int((endpoint-origin)%stride!=0)+int(not resume_context or with_initial)
        if capture_state and frame_count>limits().frames:
            raise BudgetExceeded(f'声明的state_every={stride}需要{frame_count}帧，超过当前{limits().frames}帧预算；未静默降低归档频率')
    else:
        stride=max(state_every,(endpoint-origin+max(1,limits().frames-2))//max(1,limits().frames-1))
    identity={'model_id':mid,'definition':digest(d),'parameters':params,'inputs':digest(inputs),'ticks':ticks,
              'dt':dt,'seed':seed,'experiment':experiment,'state_every':stride,'capture_state':capture_state,
              'checkpoint_at':checkpoint_at,'full_frames':full_frames,'data_bindings':data_evidence,
              'image':image,'source_version':source_version,'interventions':schedule}
    restored=progress.load(identity) if progress else None
    rows=restored['observations'] if restored else []
    times=restored['times'] if restored else []
    frames=restored['state_frames'] if restored else []
    frame_steps=restored['frame_steps'] if restored else []
    receipts=restored['receipts'] if restored else []
    events=restored['events'] if restored else []
    checkpoint=restored['solver_checkpoint'] if restored else deepcopy(resume_context['checkpoint']) if resume_context else None
    exported=restored['requested_checkpoint'] if restored else None
    step=checkpoint['step'] if checkpoint else 0
    start_step=step
    run_id=restored['run_id'] if restored else 'R'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex
    started_at=restored['started_at'] if restored else datetime.now(timezone.utc).isoformat()
    previous_seconds=restored['elapsed_s'] if restored else 0.
    begin=time.monotonic()
    active_deadline=progress.deadline if progress else begin+limits().wall_seconds-20
    observer=frame_observer(mid,endpoint) if capture_state else None
    counts=restored['population_counts'] if restored else []
    archived_bytes=restored['archived_bytes'] if restored else 0
    chunk_steps=restored['chunk_steps'] if restored else 1
    actor_records=deepcopy(restored.get('actor_records',[])) if restored else []
    next_decisions=deepcopy(restored.get('next_decisions')) if restored else None
    recorded_replay={row['descriptor']['key']:row for row in (resume_context or {}).get('decision_replay',[])}

    def save(finished=False):
        if progress:
            progress.save({'current_checkpoint':{'t':checkpoint['time']},'solver_checkpoint':checkpoint,
                'requested_checkpoint':exported,'receipts':receipts,'events':events,'run_id':run_id,
                'started_at':started_at,'elapsed_s':previous_seconds+time.monotonic()-begin,
                'population_counts':counts,'archived_bytes':archived_bytes,'chunk_steps':chunk_steps,
                'actor_records':actor_records,'next_decisions':next_decisions},
                rows,times,frames,frame_steps,finished=finished)

    while not receipts or step<endpoint:
        remaining=active_deadline-time.monotonic()-30
        if remaining<1:
            if progress and checkpoint:
                save()
                raise RunPaused('受管程序已保存真实检查点，须继续原定终点')
            raise BudgetExceeded('受管计算未在本次预算内结束，未把未完成结果归档为成功')
        take=min(chunk_steps,endpoint-step)
        decision_bundle=used_record=None
        if policy is not None:
            take=0 if next_decisions is None else min(chunk_steps,endpoint-step)
            if next_decisions is not None:
                from .decision_broker import resolve,replay,DecisionBudgetPending
                used_record=next((row for row in actor_records if row['descriptor']['key']==next_decisions['key']),None)
                if used_record is None:
                    if next_decisions['key'] in recorded_replay:
                        used_record=replay(recorded_replay[next_decisions['key']],next_decisions,policy)
                    else:
                        try:
                            bundle,batch_receipts,calls=resolve(policy,next_decisions,
                                {'run_id':run_id,'definition':digest(d),'source_version':source_version},timeout=remaining)
                        except Exception as exc:
                            if progress and (isinstance(exc,TimeoutError) or getattr(exc,'retryable',False)):
                                save()
                                raise RunPaused('真实大模型决策暂未完成，已保存同一状态边界：'+str(exc)) from exc
                            raise
                        used_record={'descriptor':deepcopy(next_decisions),'bundle':bundle,'receipts':batch_receipts,
                                     'llm_calls':calls,'source_run_id':run_id,'replayed':False}
                        used_record['sha256']=digest(used_record)
                    actor_records.append(used_record)
                    if len(dumps(actor_records).encode())+archived_bytes>limits().run_bytes:
                        raise BudgetExceeded('真实主体决策和场景合计超过归档预算，未删减决策证据')
                    save()
                decision_bundle=used_record['bundle']
                remaining=active_deadline-time.monotonic()-30
                if remaining<1:
                    if progress:
                        save()
                        raise RunPaused('真实决策已保存，须继续执行同一状态边界')
                    raise BudgetExceeded('实际决策后计算预算不足，已接受响应保留在决策账本')
        if checkpoint_at is not None and step<checkpoint_at:take=min(take,checkpoint_at-step)
        segment_budget=SandboxBudget(**{**vars(budget),'wall_seconds':min(budget.wall_seconds,max(1,remaining))})
        segment=run_segment(d['source'],parameters=params,inputs=inputs,ticks=ticks,dt=dt,seed=seed,
                            segment_steps=take,checkpoint=checkpoint,budget=segment_budget,image=image['image_id'],
                            initial_checkpoint=checkpoint_at==0,interventions=schedule,
                            capture_initial=bool(resume_context and not receipts),decision_policy=policy,decision_bundle=decision_bundle)
        receipt=segment['receipt']
        if receipts and receipt['environment']!=receipts[0]['environment']:
            raise ValueError('续算段的实际求解环境已变化，未混合执行')
        if used_record is not None:
            for batch in used_record['receipts']:
                events.append({'etype':'llm_decision','type':'llm_decision','time':used_record['descriptor']['time'],
                    'sim_t':used_record['descriptor']['time'],'decision_id':batch['decision_id'],
                    'actor_ids':batch['actor_ids'],'actions':deepcopy(batch['actions']),
                    'response_sha256':batch['response_sha256'],'replayed':used_record['replayed'],
                    'status':'returned_to_solver'})
        for item in segment['records']:
            obs=item['observations']
            if set(obs)!=set(d['observables']):raise ValueError('程序实际观测字段与声明不同，不能接受遗漏或替换')
            fr=state_frame(decode(item['frame']),obs,d,expected,item['step'],item['time'])
            fr['run_id']=run_id
            if policy is not None:
                fr['decision_phase']='before_next_macro_decision' if item['step']<ticks else 'final_after_advance'
            counts.append({'step':item['step'],'count':fr.get('population',{}).get('count',0),
                           'groups':{g['id']:g['count'] for g in fr.get('population',{}).get('groups',[])}})
            if resume_context and item['step']==origin and not with_initial:
                continue
            rows.append({**obs,**({'sim_t':item['time']} if with_time else {})})
            times.append(item['time'])
            for ev in decode(item['events']):
                if ('sim_t' in ev and ev['sim_t']!=ev['time']) or ('etype' in ev and ev['etype']!=ev['type']):
                    raise ValueError('领域事件包含矛盾的类型或时刻')
                events.append({**ev,'etype':ev['type'],'sim_t':ev['time']})
            if capture_state and ((item['step']-origin)%stride==0 or item['step'] in (origin,endpoint)):
                size=len(dumps(fr).encode('utf-8'))
                if archived_bytes+size>limits().run_bytes:
                    raise BudgetExceeded('完整归档超过当前预算；未缩减主体或减少承诺的状态帧')
                archived_bytes+=size
                frames.append(fr)
                frame_steps.append(item['step'])
            if observer:observer(fr,item['step'])
            if on_step:on_step(item['time'],StepView(obs,fr))
        checkpoint=segment['checkpoint']
        next_decisions=segment.get('next_decisions')
        step=checkpoint['step']
        receipts.append(receipt)
        if checkpoint_at is None or checkpoint_at==step or checkpoint_at==0 and segment.get('initial_checkpoint'):
            requested_checkpoint=segment['initial_checkpoint'] if checkpoint_at==0 else checkpoint
            exported={'model_id':mid,'protocol':'managed_program','state_fidelity':'full','resumable':True,
                      'resume_scope':'same_step_clock_new_run','t':requested_checkpoint['time'],'source_fingerprint':source_version,
                      'definition_sha256':digest(d),'image':image,'parameters':params,'inputs':inputs,
                      'seed':seed,'dt':dt,'ticks':ticks,'solver_checkpoint':deepcopy(requested_checkpoint),
                      'interventions':schedule,'data_bindings':deepcopy(data_evidence),
                      'note':'完整状态和随机流；自动恢复沿用原运行，公开续算另建带来源的运行且不改变步长'}
            exported['checkpoint_sha256']=digest(exported)
        # Measured segment bytes bound the next transfer; no model-size reduction.
        per_step=max(1,receipt['response_bytes']/max(1,len(segment['records'])))
        chunk_steps=max(1,min(64,int(budget.output_bytes*.45/per_step)))
        save(finished=step==endpoint)
        if progress and step<endpoint and progress.should_pause():raise RunPaused('受管程序已持久化，须继续原运行')
    if len(rows)!=endpoint-origin+(int(with_initial) if resume_context else 1):
        raise ValueError('程序实际观测没有覆盖完整原定时钟')
    if full_frames and capture_state and len(frames)!=len(rows):raise ValueError('未满足逐步完整状态归档')
    actor_calls={call['call_id']:call for record in actor_records if not record['replayed'] for call in record['llm_calls']}
    if policy is not None:
        exported.update(source_run_id=run_id,decision_replay=deepcopy(actor_records))
        exported['checkpoint_sha256']=digest({key:value for key,value in exported.items() if key!='checkpoint_sha256'})
    for item in data_evidence:
        if 'port' in item:
            if digest(inputs[item['port']])!=item['input_sha256']:
                raise ValueError('实际隔离输入快照与制备证据不一致')
            item['usage_status']='delivered_to_solver; causal_use_requires_independent_verification'
    from .output_contract import output_contract
    from .model_method import model_method
    manifest={'run_id':run_id,'model_id':mid,'source_fingerprint':source_version,'protocol':'managed_program',
        'model_definition':d,'scenario_review':cls.scenario_review,'data_bindings':data_evidence,
        'structured_inputs':{'sha256':digest(inputs),'ports':{
            name:{'sha256':digest(asset),'records':asset['count'],'contract':asset['contract']}
            for name,asset in inputs.items()},'snapshot':'checkpoint.json:inputs',
            'policy':'whole_rows_explicit_conversions; readonly_in_solver; no_automatic_causal_claim'},
        'requested':{'parameters':requested_parameters,'ticks':endpoint-origin,'dt':dt,'seed':seed,'experiment':experiment,'interventions':interventions or []},
        'actual':{'parameters':parameters,'effective_parameters':decode(resume_context['checkpoint']['parameters']) if resume_context else params,
                  'n_steps':endpoint-origin,'dt_used':dt,'final_t':endpoint*dt,
                  'n_obs':len(rows),'time_unit':d['time_unit'],'entities':counts[-1]['count'],
                  'final_effective_parameters':decode(checkpoint['parameters'])},
        'rng':{'seed':seed,'algorithm':'PCG64(numpy.default_rng)','experiment':experiment,'scope':'isolated-program'},
        'clocks':{'sim_time':endpoint*dt,'optim_iter':endpoint-origin,
                  'llm_wall_seconds':sum(call.get('duration_s',0) for call in actor_calls.values()),'batch':0},
        'param_issues':[issue.as_dict() for issue in issues],
        'param_effect':{'status':'inputs_delivered','note':'已传入隔离求解器；因果有效性须由输入扰动/数值验收独立检查'},
        'events_n':len(events),'state_frame_count':len(frames),'state_every':stride if capture_state else None,
        'frame_retention':{'definition_state_every':d.get('state_every'),'actual_state_every':stride if capture_state else None,
                           'all_steps_required':full_frames,'include_initial':not resume_context or with_initial,'include_final':True,
                           'observations':'every computational macrostep; no population or dynamics reduction'},
        'checkpoint':{key:exported[key] for key in ('state_fidelity','resumable','t','resume_scope','note')},
        'interventions':[ev for ev in events if ev['etype']=='intervention'],
        'started_at':started_at,'finished_at':datetime.now(timezone.utc).isoformat(),
        'duration_s':previous_seconds+time.monotonic()-begin,'runtime_version':'2.1-program-v1',
        'scale':{**expected,'population_counts':counts,'kept_state_frames':len(frames),
                 'all_steps_archived':capture_state and len(frames)==len(rows)},
        'execution_recovery':{'protocol':'managed-program-json-chunks-v1','resumed':bool(restored),'from_step':start_step,
                              'original_endpoint':ticks*dt,'previous_active_seconds':previous_seconds},
        'execution_environment':{**receipts[0]['environment'],**image},'solver_segments':receipts,
        'output_contract':output_contract(mid),'model_method':model_method(mid,d),
        'observed_output_types':{key:['number'] for key in d['observables']},
        'fidelity':{'level':'unreviewed','basis':'隔离执行与协议校验通过不等于数学实现、经验校准和外推有效性通过'},
        'warnings':[], 'llm_calls':list(actor_calls.values())}
    if policy is not None:
        manifest['actor_decisions']={'policy':deepcopy(policy),'records':actor_records,
            'batch_count':sum(len(row['receipts']) for row in actor_records),
            'real_call_count':len(actor_calls),'replay_boundaries':sum(row['replayed'] for row in actor_records),
            'action_count':sum(len(batch['actions']) for row in actor_records for batch in row['receipts']),
            'scope':'Real configured host LLM or explicitly recorded replay; no network/credentials inside solver'}
    assert_loaded_source()
    if resume_context:
        manifest['continuation']=deepcopy(resume_context['lineage'])
        manifest['requested'].update(resume_from_t=origin*dt,with_initial=with_initial)
        manifest['rng']['resumed_from_checkpoint']=True
    return RunResult(model_id=mid,observations=rows,manifest=manifest,state_frames=frames,events=events,
                     issues=issues,checkpoint=exported)


def resume_program(chk, steps, dt, *, capture_state, with_initial, source_version):
    """Fork from a verified full boundary; never initialize or replay its past."""
    from .model_index import resolve
    from .runtime import validate_run_arguments
    if not isinstance(chk,dict) or chk.get('protocol')!='managed_program' or chk.get('state_fidelity')!='full' or chk.get('resumable') is not True:
        raise ValueError('程序检查点缺少完整可恢复状态')
    if chk.get('checkpoint_sha256')!=digest({k:v for k,v in chk.items() if k!='checkpoint_sha256'}):
        raise ValueError('程序检查点摘要不一致，不能使用损坏或被改写的状态')
    if chk.get('source_fingerprint')!=source_version:
        raise ValueError('检查点的平台源码版本已变化，须使用归档版本复现')
    protocol,cls=resolve(chk['model_id'])
    if protocol!='managed_program' or digest(cls.definition)!=chk.get('definition_sha256'):
        raise ValueError('检查点的模型定义已变化')
    image=image_contract(chk['image']['image_id'])
    if image!=chk['image']:raise ValueError('检查点的实际求解镜像或协议已变化')
    if dt!=chk['dt']:raise ValueError('程序续算须保持原dt，不能静默改变数值调度')
    validate_run_arguments(chk['ticks'],dt,chk['seed'])
    params=effective_parameters(cls.definition,chk['parameters'])
    if params!=chk['parameters']:raise ValueError('检查点原始参数不完整')
    prior=deepcopy(chk['solver_checkpoint'])
    if (prior.get('protocol')!=PROTOCOL or type(prior.get('step')) is not int
            or not 0<=prior['step']<=chk['ticks'] or prior.get('time')!=prior['step']*dt
            or chk['t']!=prior['time']):raise ValueError('程序检查点的时钟不一致')
    def identity(horizon):
        body={'protocol':PROTOCOL,'source':cls.definition['source'],'parameters':encode(params),
                       'inputs':encode(chk['inputs']),'seed':chk['seed'],'dt':dt,'ticks':horizon,
                       'interventions':chk['interventions']}
        if cls.definition.get('decision_policy') is not None:body['decision_policy']=cls.definition['decision_policy']
        return digest(body)
    if prior.get('identity')!=identity(chk['ticks']):raise ValueError('检查点源码、数据或执行设置不匹配')
    endpoint=prior['step']+steps
    horizon=max(chk['ticks'],endpoint)
    validate_run_arguments(horizon,dt,chk['seed'])
    # Rebind only the explicitly requested new endpoint after validating the
    # original identity. advance() never receives the total requested horizon.
    prior['identity']=identity(horizon)
    context={'checkpoint':prior,'endpoint':endpoint,'inputs':deepcopy(chk['inputs']),'image_id':image['image_id'],
             'interventions':deepcopy(chk['interventions']),
             'decision_replay':deepcopy(chk.get('decision_replay',[])),
             'lineage':{'parent_checkpoint_sha256':chk['checkpoint_sha256'],'from_t':chk['t'],
                        'parent_endpoint':chk['ticks']*dt,'requested_endpoint':endpoint*dt,
                        'extended_endpoint':endpoint>chk['ticks'],'reinitialized':False}}
    return run_program(chk['model_id'],cls,parameters=params,requested_parameters=params,ticks=horizon,dt=dt,
        seed=chk['seed'],experiment=None,issues=[],with_time=True,checkpoint_at=None,
        interventions=deepcopy(chk['interventions']),on_step=None,capture_state=capture_state,state_every=1,
        data_evidence=deepcopy(chk.get('data_bindings',[])),full_frames=False,progress=None,
        source_version=source_version,resume_context=context,with_initial=with_initial)
