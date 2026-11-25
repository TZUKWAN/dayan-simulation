"""Measured model probes and verified capacity, separate from scientific runs."""
from copy import deepcopy
import json
import math
import threading
import time
import psutil

from ..access import data_root
from ..collection.storage import atomic_json,read_json,file_lock
from ..limits import limits
from ..solvers.codec import digest


def measure(context,parameters,steps,seed,query,*,progress=None):
    from ..runtime import run_model_full
    from ..run_store import get_store
    process=psutil.Process();peak=[process.memory_info().rss];stop=threading.Event()
    def observe():
        while not stop.wait(.01):peak[0]=max(peak[0],process.memory_info().rss)
    watcher=threading.Thread(target=observe,daemon=True);watcher.start()
    before=process.cpu_times();started=time.perf_counter()
    try:
        rr=run_model_full(context['proof']['model_id'],**{**context['options'],'parameters':parameters,'ticks':steps},
            seed=seed,capture_state=True,full_frames=True,_progress=progress)
    finally:
        stop.set();watcher.join(1)
    elapsed=max(time.perf_counter()-started,float(rr.manifest.get('duration_s',0)));after=process.cpu_times()
    segments=rr.manifest.get('solver_segments',[])
    usage=[s['resource_usage'] for s in segments if s.get('resource_usage')]
    rr.manifest['capacity_probe']={'baseline_run_id':context['proof']['run_id'],'diagnostic':True,
        'scope':'实际同代码探针；人数或时长可不同，仅用于容量测量，不移植原需求数值/科学验收'}
    store=get_store();rid=rr.manifest['run_id']
    if store._path(rid).exists():
        saved=store.load(rid)
        if saved['manifest'].get('capacity_probe')!=rr.manifest['capacity_probe'] or saved['observations']!=rr.observations:raise ValueError('容量探针既存归档与恢复结果不符')
    else:store.save_run(rr,source='capacity_probe',request_text=query)
    return {'run_id':rid,'model_id':rr.model_id,'parameters':deepcopy(parameters),'steps':steps,
        'entities':rr.manifest['actual'].get('entities'),'wall_seconds':elapsed,
        'cpu_seconds':sum(s['cpu_seconds'] for s in usage) if usage else after.user+after.system-before.user-before.system,
        'peak_worker_rss_bytes':max(s['peak_worker_rss_bytes'] for s in usage) if usage else None,
        'peak_host_rss_bytes':peak[0],'resource_source':'trusted_container_worker' if usage else 'host_process_sample_10ms; shared-process peak, not isolated model-only memory',
        'cpu_scope':'all_completed_solver_segments' if usage else 'current_recovery_attempt' if rr.manifest.get('execution_recovery',{}).get('resumed') else 'current_host_full_run',
        'archive_bytes':sum(p.stat().st_size for p in store._path(rid).iterdir() if p.is_file()),
        'wire_bytes':sum(s.get('request_bytes',0)+s.get('response_bytes',0) for s in segments),
        'frames':len(rr.state_frames),'observations':len(rr.observations),
        'llm_calls':len(rr.manifest.get('llm_calls',[])),
        'llm_tokens':sum(c.get('usage',{}).get('total_tokens',0) for c in rr.manifest.get('llm_calls',[]))}


def predict(probes,value,steps,axis):
    x0,x1=[p['axis_value'] for p in probes]
    def estimate(field):
        a,b=[p.get(field) for p in probes]
        if a is None or b is None:return None
        exponent=max(0.,math.log(max(b,1e-12)/max(a,1e-12))/math.log(x1/x0))
        result=max(a,b)*(value/x1)**exponent
        if axis!='ticks' and field in ('wall_seconds','cpu_seconds','archive_bytes','wire_bytes','llm_calls','llm_tokens'):
            result*=steps/probes[-1]['steps']
        return result
    return {key:estimate(key) for key in ('wall_seconds','cpu_seconds','peak_worker_rss_bytes','peak_host_rss_bytes','archive_bytes','wire_bytes','llm_calls','llm_tokens')}


def plan(*,query=None,baseline_run_id=None,scale_parameter=None,probe_values=None,probe_steps=None,
         target_value=None,capacity_id=None,max_probes=1):
    from .baseline_context import restore
    from .quantity_contract import quantity_contract
    from ..run_progress import RunProgress,RunPaused
    if type(max_probes)!=int or max_probes<1:raise ValueError('max_probes须为正整数')
    if capacity_id:
        import re
        if not re.fullmatch(r'CP-[a-f0-9]{32}',capacity_id):raise ValueError('容量编号无效')
        if any(v is not None for v in (query,baseline_run_id,scale_parameter,probe_values,probe_steps,target_value)):
            raise ValueError('续接仅传capacity_id/max_probes，不能改变原探针协议')
        directory=data_root()/'capacity_plans'/capacity_id
        protocol=read_json(directory/'protocol.json')
        if capacity_id!='CP-'+digest(protocol)[:32]:raise ValueError('容量协议摘要不一致')
        context=restore(protocol['baseline_run_id'])
    else:
        context=restore(baseline_run_id)
        if not isinstance(query,str) or not query.strip():raise ValueError('容量规划须保留本轮原文')
        parameters=context['parameters'];definition=context['definition'];steps=context['options']['ticks']
        candidates={g['count'] for g in definition.get('populations',[]) if isinstance(g['count'],str)}
        if scale_parameter is None:scale_parameter=next(iter(candidates)) if len(candidates)==1 else 'ticks'
        if scale_parameter=='ticks':base=steps;minimum=1;maximum=limits().ticks
        else:
            spec=definition.get('parameters',{}).get(scale_parameter)
            if not spec or spec['type']!='int' or scale_parameter in context['bound']:
                raise ValueError('规模轴须为实际未被数据固定的整数参数，或ticks；不能复制真实人口冒充扩容')
            base=parameters[scale_parameter];minimum=max(1,spec.get('minimum',1));maximum=min(spec.get('maximum',limits().array_entities),limits().array_entities)
        if base<1:raise ValueError('零时长基线不能估计容量；先完成非零实际运行')
        values=probe_values if probe_values is not None else sorted({max(minimum,base//2),base})
        if not isinstance(values,list) or len(values)!=2 or any(type(v)!=int or not minimum<=v<=maximum for v in values) or values[0]>=values[1]:
            raise ValueError('须提供两档递增且在真实边界内的整数probe_values；很小的基线请显式给可区分探针')
        prefix=min(steps,8) if probe_steps is None else probe_steps
        if type(prefix)!=int or not 1<=prefix<=steps:raise ValueError('probe_steps须为1至原步数的整数；不改变正式时钟')
        constraints=quantity_contract(query)
        fixed=bool(constraints.get('entities') or constraints.get('grid'))
        # Only a freely chosen population is a candidate for automatic expansion.
        target=target_value if target_value is not None else min(maximum,values[-1]*2) if constraints.get('maximize') and not fixed and scale_parameter!='ticks' else base
        if type(target)!=int or not minimum<=target<=maximum:raise ValueError('target_value须在真实整数边界内')
        if fixed and scale_parameter!='ticks' and target!=base:raise ValueError('原文固定人数/网格，容量规划不能替换正式规模')
        protocol={'query':query,'baseline_run_id':baseline_run_id,'source_fingerprint':context['proof']['source_fingerprint'],
            'definition_sha256':digest(definition),'axis':scale_parameter,'probe_values':values,'probe_steps':prefix,
            'base_value':base,'target_value':target,'formal_steps':steps,'user_fixed_population':fixed,
            'formal_parameters':deepcopy(parameters),'seed':context['proof']['manifest']['rng']['seed']}
        capacity_id='CP-'+digest(protocol)[:32];directory=data_root()/'capacity_plans'/capacity_id
        directory.mkdir(parents=True,exist_ok=True)
        if not (directory/'protocol.json').exists():atomic_json(directory/'protocol.json',protocol)
    if digest(context['definition'])!=protocol['definition_sha256']:raise ValueError('实际模型定义与探针协议不符')
    with file_lock(directory/'work.lock',timeout=.1):
        call_deadline=time.monotonic()+limits().wall_seconds-10
        state=read_json(directory/'state.json') if (directory/'state.json').exists() else {'probes':[]}
        if state.get('complete'):return state['payload']
        for _ in range(min(max_probes,3-len(state['probes']))):
            index=len(state['probes']);target=index==2
            value=protocol['target_value'] if target else protocol['probe_values'][index]
            steps=value if protocol['axis']=='ticks' else protocol['formal_steps'] if target else protocol['probe_steps']
            parameters={**context['parameters'],**({protocol['axis']:value} if protocol['axis']!='ticks' else {})}
            if target:
                state['prediction']=predict(state['probes'],value,steps,protocol['axis'])
                atomic_json(directory/'state.json',state)
            progress=RunProgress(directory/'evaluations'/str(index),call_deadline)
            try:actual=measure(context,parameters,steps,protocol['seed'],protocol['query'],progress=progress)
            except RunPaused as exc:
                return {'status':'pending','capacity_id':capacity_id,'completed_probes':len(state['probes']),
                    'solver_progress':{'probe':index,'reason':str(exc),'checkpoint_saved':progress.record is not None},
                    'next_action':{'action':'plan_capacity','arguments':{'capacity_id':capacity_id,'max_probes':max_probes}}}
            state['probes'].append({**actual,'axis_value':value,'role':'target_verification' if target else 'measurement'})
            atomic_json(directory/'state.json',state)
        if len(state['probes'])<3:return {'status':'pending','capacity_id':capacity_id,'completed_probes':len(state['probes']),
            'next_action':{'action':'plan_capacity','arguments':{'capacity_id':capacity_id,'max_probes':max_probes}}}
        measured=state['probes'][-1];prediction=state['prediction'];cap=limits()
        relative_error={k:(measured[k]-v)/v for k,v in prediction.items() if v and measured.get(k) is not None}
        memory=measured['peak_worker_rss_bytes'] or measured['peak_host_rss_bytes']
        feasible=measured['wall_seconds']<=cap.wall_seconds and measured['cpu_seconds']<=cap.cpu_seconds and memory<=cap.memory_bytes and measured['archive_bytes']<=cap.run_bytes
        payload={'status':'completed','capacity_id':capacity_id,'baseline_run_id':protocol['baseline_run_id'],
            'protocol':protocol,'measurements':state['probes'],'predicted_target':prediction,'relative_error':relative_error,
            'verified_target_feasible':feasible,'verified_axis_value':measured['axis_value'],
            'recommendation':{'parameters':measured['parameters'] if feasible else protocol['formal_parameters'],
                'ticks':protocol['formal_steps'],'applied_to_baseline':False,
                'archive':'保留原逐步观测与完整检查点；如原文允许可显式调state_every，容量规划本身未修改保存策略',
                'chunking':'受管运行按实际序列化体积分段；已接受外部决策持久化后续接，不能通过降人数/换模型省成本'},
            'scope':'三个实际同代码运行；两档探针外推及目标实测误差。仅目标档已核实，不把外推称为最大可运行规模，也不继承原基线科学验收。'}
        state.update(complete=True,payload=payload);atomic_json(directory/'state.json',state)
        return payload


def tool_plan_capacity(**kwargs):
    try:return {'ok':True,'payload':plan(**kwargs)}
    except Exception as exc:return {'ok':False,'error':f'{type(exc).__name__}: {exc}'}


def schema():
    properties={'query':{'type':'string'},'baseline_run_id':{'type':'string'},'capacity_id':{'type':'string'},
        'scale_parameter':{'type':'string','description':'实际整数人口参数；省略优先人口count参数，否则ticks。真实数据固定人数不能伪造扩容。'},
        'probe_values':{'type':'array','items':{'type':'integer','minimum':1},'minItems':2,'maxItems':2},
        'probe_steps':{'type':'integer','minimum':1},'target_value':{'type':'integer','minimum':1},
        'max_probes':{'type':'integer','minimum':1,'default':1}}
    return {'type':'object','additionalProperties':False,'properties':properties,'oneOf':[
        {'required':['query','baseline_run_id'],'not':{'required':['capacity_id']}},
        {'required':['capacity_id'],'not':{'anyOf':[{'required':[k]} for k in properties if k not in ('capacity_id','max_probes')]}}]}
