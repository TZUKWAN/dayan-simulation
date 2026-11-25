"""Frozen research requests spanning model authoring and actual study execution.

An intent is not a waiver. It binds a baseline's entire original request to the
later data evaluation. Only training values are sent to authoring prompts; the
protocol retains all original target provenance for evaluation and audit.
"""
from copy import deepcopy
from datetime import datetime,timezone
import math
import re

from ..access import data_root
from ..collection.storage import atomic_json,file_lock,read_json
from ..solvers.codec import digest
from ..structured_inputs import _object,_text,_finite,prepare_bindings
from .model_evaluation import _sealed,objective_contract,parameter_specs
from .model_observations import ROLES,prepare_targets,audit_input_usage


def directory(intent_id):
    if not re.fullmatch(r'MI-[a-f0-9]{24}',str(intent_id)):
        raise ValueError('非法research_intent_id')
    return data_root()/'model_research_intents'/intent_id


def _now():return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _write(path,value):
    value={key:item for key,item in value.items() if key!='sha256'}
    value['sha256']=digest(value)
    atomic_json(path,value)
    return value


def load_intent(intent_id):
    folder=directory(intent_id)
    protocol=read_json(folder/'protocol.json')
    _sealed(protocol,'研究意图协议')
    if 'MI-'+protocol['sha256'][:24]!=intent_id:
        raise ValueError('研究意图ID与固定协议不符')
    state=read_json(folder/'state.json')
    _sealed(state,'研究意图进度')
    if state['research_intent_id']!=intent_id:raise ValueError('研究意图进度归属不符')
    return {'protocol':protocol,'state':state}


def prepare_intent(question,*,observables,time_unit,target_bindings,time_origin,split,execution,
                   objectives,param_grid,seeds,selection_top,max_loss,diagnostics,availability,
                   information_mode,session_id=None,parent_study_id=None):
    from ..runtime import assert_loaded_source,validate_run_arguments
    from ..limits import validate_compute
    _text(question,'完整研究原文')
    _text(time_unit,'模型时间单位')
    if not isinstance(observables,dict) or not observables:
        raise ValueError('须事前声明实际目标观测名和单位observables')
    for name,spec in observables.items():
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,39}',name):raise ValueError('目标observable须为合法字段名')
        _object(spec,('unit',),('unit',),'目标观测')
        _text(spec['unit'],'目标观测单位')
    targets=prepare_targets(target_bindings,observables=observables,time_unit=time_unit,time_origin=time_origin,split=split)
    _object(execution,('parameters','ticks','dt','data_bindings','time_atol','seed'),
            ('parameters','ticks','dt','data_bindings','time_atol'),'建模与研究共同执行设置')
    if not isinstance(execution['parameters'],dict):raise ValueError('parameters须为对象')
    from .requirements import extract_request
    original=extract_request(question)
    execution=deepcopy(execution)
    for key in ('ticks','dt','seed'):
        if key in original['options'] and execution.get(key,original['options'][key])!=original['options'][key]:
            raise ValueError('研究执行设置与用户原文冲突：'+key)
        if key in original['options']:execution[key]=original['options'][key]
    for key,value in original['parameters'].items():
        if key in execution['parameters'] and execution['parameters'][key]!=value:
            raise ValueError('研究参数与用户原文冲突：'+key)
        execution['parameters'][key]=value
    if 'seeds' in original['options'] and list(original['options']['seeds'])!=seeds:
        raise ValueError('研究重复种子与用户原文冲突')
    if not isinstance(seeds,list) or not seeds or len(set(seeds))!=len(seeds):
        raise ValueError('须事前声明不重复的研究seeds')
    for seed in seeds:validate_run_arguments(execution['ticks'],execution['dt'],seed)
    validate_run_arguments(execution['ticks'],execution['dt'],execution.get('seed',seeds[0]))
    validate_compute(execution['ticks'],seeds=len(seeds),array=True)
    atol=_finite(execution['time_atol'],'时间匹配容差')
    if not 0<=atol<execution['dt']/4:raise ValueError('时间匹配容差须非负且小于dt/4')
    for rows in targets['roles'].values():
        for row in rows:
            step=round(row['time']/execution['dt'])
            if step>execution['ticks'] or abs(step*execution['dt']-row['time'])>atol:
                raise ValueError('目标时点须在实际模型终点内且对应实际步，不能静默插值')
    if not isinstance(param_grid,dict) or not param_grid:raise ValueError('须事前声明非空参数网格')
    for name,values in param_grid.items():
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,39}',name) or not isinstance(values,list) or not values:
            raise ValueError('参数网格须为合法参数名到非空列表')
        if len({digest(value) for value in values})!=len(values):raise ValueError('参数候选重复')
    total=math.prod(len(values) for values in param_grid.values())
    if type(selection_top) is not int or not 1<=selection_top<=total:raise ValueError('验证短名单须在1至网格大小内')
    if not isinstance(max_loss,dict) or set(max_loss)!=set(ROLES):raise ValueError('须逐分区声明max_loss')
    for value in max_loss.values():
        if value is not None and _finite(value,'误差阈值')<0:raise ValueError('误差阈值不能为负')
    bound,inputs,evidence=prepare_bindings(execution['data_bindings'])
    if set(bound)&set(param_grid):raise ValueError('待估参数不能覆盖实际数据绑定参数')
    from .model_diagnostics import diagnostic_declarations
    diagnostics=diagnostic_declarations(diagnostics,observables=observables,execution=execution,
                                      seeds=seeds,bound_parameters=bound)
    if not isinstance(availability,list) or len(availability)!=len(execution['data_bindings']):
        raise ValueError('须按每个实际输入的顺序给availability')
    access=[{**item,'binding_sha256':item.get('binding_sha256',digest(binding))}
            for binding,item in zip(execution['data_bindings'],availability)]
    audit=audit_input_usage(targets,execution['data_bindings'],availability=access,
                            information_mode=information_mode,forecast_origin=split['training_end'])
    for key,value in bound.items():
        if key in execution['parameters'] and value!=execution['parameters'][key]:
            raise ValueError('参数与实际输入绑定数值冲突：'+key)
    if parent_study_id:
        from .model_studies import load_study
        load_study(parent_study_id)
    protocol={'version':'dayan-model-research-intent-v1','question':question,'session_id':session_id,
        'source_fingerprint':assert_loaded_source(),'observables':deepcopy(observables),'time_unit':time_unit,
        'targets':targets,'execution':{**deepcopy(execution),'seed':execution.get('seed',seeds[0])},
        'objectives':deepcopy(objectives),'resolved_objectives':objective_contract(objectives,targets),
        'param_grid':deepcopy(param_grid),'seeds':list(seeds),'selection_top':selection_top,
        'max_loss':deepcopy(max_loss),'diagnostics':deepcopy(diagnostics),'availability':access,
        'information_mode':information_mode,'input_sha256':digest(inputs),'input_evidence':evidence,
        'input_audit':audit,'parent_study_id':parent_study_id,
        'stage_rule':'review_and_execute_baseline; actual_training; validation_selection; diagnostics; holdout_score_once; selected_trajectory_reproduction_without_rescoring; same_study_report'}
    ident='MI-'+digest(protocol)[:24]
    folder=directory(ident)
    with file_lock(folder/'intent.lock',timeout=.1):
        if (folder/'protocol.json').exists():
            old=read_json(folder/'protocol.json')
            _sealed(old,'研究意图协议')
            if old['sha256']!=digest(protocol):raise ValueError('研究意图内容标识冲突')
        else:_write(folder/'protocol.json',protocol)
        if not (folder/'state.json').exists():
            _write(folder/'state.json',{'research_intent_id':ident,'status':'awaiting_model','created_at':_now()})
    return intent_summary(ident)


def checked_intent(intent_id,question,session_id):
    from ..runtime import assert_loaded_source
    record=load_intent(intent_id)
    p=record['protocol']
    if p['question']!=question or p['session_id']!=session_id:
        raise ValueError('研究意图的原文或会话不一致；不能删改要求或跨会话替换')
    if p['source_fingerprint']!=assert_loaded_source():raise ValueError('研究意图平台版本已变化，须重新制定并审查')
    refreshed=prepare_targets(p['targets']['bindings'],observables=p['observables'],time_unit=p['time_unit'],
                              time_origin=p['targets']['time_origin'],split=p['targets']['split'])
    _,inputs,evidence=prepare_bindings(p['execution']['data_bindings'])
    if refreshed['sha256']!=p['targets']['sha256'] or digest(inputs)!=p['input_sha256'] or evidence!=p['input_evidence']:
        raise ValueError('研究意图实际目标数据或输入版本已变化')
    source_context(record)
    return record


def _context_version(record,context_id):
    if not isinstance(context_id,str) or not re.fullmatch(r'[a-f0-9]{64}',context_id):
        raise ValueError('来源证据版本编号无效')
    ident=record['state']['research_intent_id']
    version=read_json(directory(ident)/'source_evidence'/(context_id+'.json'))
    _sealed(version,'来源证据版本')
    if (version.get('protocol_sha256')!=record['protocol']['sha256']
            or version.get('contract',{}).get('sha256')!=context_id):
        raise ValueError('来源证据不属于同一冻结研究意图')
    from .source_evidence import verify_evidence
    verify_evidence(version['contract'],targets=record['protocol']['targets'])
    return version


def source_context(record):
    ident=record['state'].get('source_evidence_id')
    return _context_version(record,ident)['contract'] if ident else None


def attach_source_evidence(intent_id,evidence,question,session_id=None):
    """Append verified text to an unapproved intent without changing its science."""
    from ..agent.model_design import load_design
    from .source_evidence import prepare_evidence
    folder=directory(intent_id)
    with file_lock(folder/'intent.lock',timeout=.1):
        record=checked_intent(intent_id,question,session_id)
        p,state=record['protocol'],record['state']
        previous=source_context(record)
        if not isinstance(evidence,list) or not evidence:raise ValueError('evidence须为实际来源引用的非空列表')
        bindings=deepcopy(previous['bindings']) if previous else []
        known={row['id']:row for row in bindings}
        incoming=set()
        for row in evidence:
            if not isinstance(row,dict) or not isinstance(row.get('id'),str):
                raise ValueError('来源引用须给有效id和实际DS字段')
            if row['id'] in incoming:raise ValueError('同次来源引用id重复')
            incoming.add(row['id'])
            if row['id'] in known and row!=known[row['id']]:raise ValueError('既有来源引用不能替换，须保留旧证据并用新id追加')
            if row['id'] not in known:
                bindings.append(deepcopy(row));known[row['id']]=row
        contract=prepare_evidence(bindings,targets=p['targets'])
        if previous and contract==previous:return intent_summary(intent_id)
        if any(state.get(key) for key in ('baseline_run_id','study_id','report_id')):
            raise ValueError('研究已运行或开始求值，不能事后追加证据改变既有审查；须显式新研究版本')
        if state.get('design_id'):
            design=load_design(state['design_id'],session_id)
            if design['status']!='blocked':
                raise ValueError('来源追加只用于尚未设计或已被否决的方案；进行中或已批准方案不能静默更换上下文')
        context_id=contract['sha256']
        parent=previous['sha256'] if previous else None
        path=folder/'source_evidence'/(context_id+'.json')
        if path.exists():
            saved=_context_version(record,context_id)
            if saved['contract']!=contract or saved.get('parent_id')!=parent:
                raise ValueError('来源证据版本冲突，不能覆盖既有记录')
        else:
            _write(path,{'protocol_sha256':p['sha256'],'parent_id':parent,
                         'created_at':_now(),'contract':contract})
        _write(folder/'state.json',{**state,'source_evidence_id':context_id,
            'context_revision':state.get('context_revision',0)+1,'updated_at':_now()})
    return intent_summary(intent_id)


def authorize_context_extension(parent_execution,execution,question,session_id):
    """Only a recorded append-only evidence version may vary a rejected design."""
    before=deepcopy(parent_execution);after=deepcopy(execution)
    old=before.get('research',{}).pop('source_evidence',None)
    new=after.get('research',{}).pop('source_evidence',None)
    if digest(before)!=digest(after) or not new or old==new:
        raise ValueError('执行设置只能追加平台核验的来源证据，不能改变原文/参数/时钟/输入/检验规则')
    ident=after.get('research',{}).get('research_intent_id')
    record=checked_intent(ident,question,session_id)
    if source_context(record)!=new:raise ValueError('新上下文不是本研究实际已保存的来源证据版本')
    wanted=old['sha256'] if old else None
    cursor=new['sha256'];seen=set()
    while cursor!=wanted:
        if cursor is None or cursor in seen:raise ValueError('来源证据版本不是已审上下文的追加后继')
        seen.add(cursor)
        version=_context_version(record,cursor)
        prior=version.get('parent_id')
        if prior:
            former=_context_version(record,prior)['contract']['bindings']
            current=version['contract']['bindings']
            if current[:len(former)]!=former:raise ValueError('来源证据后继删除或替换了旧引用')
        cursor=prior
    if old and _context_version(record,wanted)['contract']!=old:
        raise ValueError('原方案来源证据与已保存父版本不一致')
    return {'previous_id':wanted,'source_evidence_id':new['sha256']}


def _target_integrity(targets):
    """Value-free time coverage for host-data checks, never future outcomes."""
    groups={}
    for role,rows in targets['roles'].items():
        for row in rows:
            key=(row['binding_id'],row['observable'],digest(row['series']))
            group=groups.setdefault(key,{'binding_id':row['binding_id'],'observable':row['observable'],
                'series':deepcopy(row['series']),'unit':row['unit'],'times':[],
                'partition_counts':dict.fromkeys(ROLES,0)})
            group['times'].append(row['time'])
            group['partition_counts'][role]+=1
    summaries=[]
    for key in sorted(groups):
        group=groups[key]
        times=sorted(group.pop('times'))
        intervals=[right-left for left,right in zip(times,times[1:])]
        summaries.append({**group,'count':len(times),'first_time':times[0],'last_time':times[-1],
            'minimum_interval':min(intervals) if intervals else None,
            'maximum_interval':max(intervals) if intervals else None})
    return {'targets_sha256':targets['sha256'],'source_hashes':'verified',
        'finite_values_and_unique_observation_keys':'verified','series':summaries,
        'scope':'描述实际选定观测的数量、起止和间隔，不含验证/留出目标值；须按原话另核期望覆盖，不证明源方发布时点或现实有效性。'}


def _target_source_receipts(targets):
    """Expose collection metadata after checked_intent verified raw targets."""
    from ..datasets import dataset_dir
    receipts=[]
    for source in targets['sources']:
        metadata=read_json(dataset_dir()/source['dataset_id']/'metadata.json')
        if any(metadata[key]!=source[key] for key in ('dataset_id','source','sha256','data_sha256')):
            raise ValueError('目标来源记录与已核验的冻结目标不一致')
        retrieved=metadata.get('retrieved_at')
        if retrieved is not None:
            try:
                clock=datetime.fromisoformat(retrieved)
                if clock.utcoffset() is None:raise ValueError('missing timezone')
            except (ValueError,TypeError):
                raise ValueError('目标数据的实际采集时间记录无效，不能猜测或伪造') from None
        receipts.append({**deepcopy(source),'retrieved_at':retrieved,
            'collection_time_basis':'platform_dataset_metadata' if retrieved is not None else 'unavailable',
            'release_time_status':'not_established_by_collection_timestamp'})
    return receipts


def authoring_contract(intent_id,question,session_id,execution,data_bindings,seeds):
    record=checked_intent(intent_id,question,session_id)
    p=record['protocol'];wanted=p['execution']
    if (any(execution.get(k)!=wanted[k] for k in ('parameters','ticks','dt','seed'))
            or (data_bindings or [])!=wanted['data_bindings']
            or seeds is not None and list(seeds)!=p['seeds']):
        raise ValueError('建模设置与冻结的研究意图冲突；须保留原参数/时钟/输入/种子')
    # Target outcome values in validation and holdout never enter inner design,
    # compilation or semantic-review prompts through this contract.
    targets=p['targets']
    from .model_diagnostics import diagnostic_execution_contract
    context=source_context(record)
    return {'research_intent_id':intent_id,'protocol_sha256':p['sha256'],'phase':'baseline_model_only',
        'request_complete':False,'time_unit':p['time_unit'],'observables':p['observables'],
        'param_grid':p['param_grid'],'seeds':p['seeds'],'split':targets['split'],
        'objectives':p['resolved_objectives'],'max_loss':p['max_loss'],'diagnostics':p['diagnostics'],
        'target_sources':_target_source_receipts(targets),
        'input_availability':deepcopy(p['availability']),'input_usage_audit':deepcopy(p['input_audit']),
        'target_counts':{role:len(rows) for role,rows in targets['roles'].items()},
        'target_integrity':_target_integrity(targets),
        'training_points':[{k:deepcopy(row[k]) for k in ('observable','time','value','unit')} for row in targets['roles']['training']],
        'stage_rule':p['stage_rule'],
        'execution_rules':{'diagnostics':diagnostic_execution_contract(),
            'holdout':'Freeze selection and finish diagnostics, then score selected candidate/seed holdout once per predeclared replicate; never reselect using holdout.',
            'finalize':'research_finalize reproduces one selected seed trajectory and checks equality to the saved trial. It does not score holdout again or change selection; report uses the saved study score.'},
        **({'source_evidence':deepcopy(context)} if context else {}),
        'acceptance':'基线只验模型机制/数值/状态与实际输入；校准/独立留出/研究报告由同意图后续MS阶段真实执行。不能在基线声称整题完成。'}


def check_model(intent_id,definition,plan=None):
    from ..program_models import parameter_value
    p=load_intent(intent_id)['protocol']
    units=({name:meta['unit'] for name,meta in definition['observables'].items()}
           if definition['kind']=='program' else definition.get('observable_units',{}))
    if definition['time_unit']!=p['time_unit'] or any(units.get(name)!=spec['unit'] for name,spec in p['observables'].items()):
        raise ValueError('模型须保留研究目标的实际观测名、单位和时间单位')
    params=parameter_specs(definition)
    for name,values in p['param_grid'].items():
        if name not in params:raise ValueError('模型缺少事前待估参数：'+name)
        for value in values:parameter_value(name,value,params[name])
    from .model_diagnostics import diagnostic_contract
    bound,_,_=prepare_bindings(p['execution']['data_bindings'])
    diagnostic={'model':{'definition':definition,'observables':{name:{'unit':unit} for name,unit in units.items()}},
                'execution':p['execution'],'bound_parameters':bound}
    diagnostic['sha256']=digest(diagnostic)
    from .diagnostic_bindings import resolve_bindings
    try:
        resolved,_=resolve_bindings(p['diagnostics'],plan,definition)
        diagnostic_contract(diagnostic,resolved,p['seeds'])
    except ValueError as exc:
        from ..agent.design_revision import ImplementationMismatch
        raise ImplementationMismatch(str(exc),{
            'phase':'research_diagnostic_implementation','research_intent_id':intent_id,
            'scientific_declarations':deepcopy(p['diagnostics']),
            'plan_bindings':deepcopy((plan or {}).get('diagnostic_bindings',[])),
            'instruction':'保留同一MI的原文、消融参数/机制/指标/尺度及全部科学判据；修正真实获审路径或通过反馈修订方案。'
                          '不能重建缩减意图、猜路径或添加伪调用来通过。'},definition) from exc


def study_arguments(intent_id):
    p=load_intent(intent_id)['protocol']
    return {'question':p['question'],'target_bindings':p['targets']['bindings'],
        'time_origin':p['targets']['time_origin'],'split':p['targets']['split'],
        **{k:deepcopy(p[k]) for k in ('objectives','param_grid','seeds','selection_top','max_loss','diagnostics',
                                     'availability','information_mode','parent_study_id')},
        'time_atol':p['execution']['time_atol'],'data_bindings':p['execution']['data_bindings']}


def require_study_contract(intent_id,question,arguments):
    expected=study_arguments(intent_id)
    if question!=expected.pop('question') or digest(arguments)!=digest(expected):
        raise ValueError('研究创建参数偏离原始冻结意图，不能更换目标/输入/划分或放宽阈值')


def complete_baseline(intent_id,run_id):
    from .model_study_entry import create_model_study
    p=load_intent(intent_id)['protocol']
    checked_intent(intent_id,p['question'],p['session_id'])
    result=create_model_study(baseline_run_id=run_id,**study_arguments(intent_id))
    folder=directory(intent_id)
    with file_lock(folder/'intent.lock',timeout=.1):
        state=load_intent(intent_id)['state']
        if state.get('baseline_run_id',run_id)!=run_id or state.get('study_id',result['study_id'])!=result['study_id']:
            raise ValueError('同一研究意图已绑定另一基线或研究；须显式新建版本')
        if not state.get('study_id'):
            _write(folder/'state.json',{**state,'status':'research_pending','baseline_run_id':run_id,
                                       'study_id':result['study_id'],'updated_at':_now()})
    return result


def remember_design(intent_id,design):
    folder=directory(intent_id)
    with file_lock(folder/'intent.lock',timeout=.1):
        state=load_intent(intent_id)['state']
        previous=state.get('design_id')
        if previous and previous!=design['design_id'] and design.get('revision_of')!=previous:
            raise ValueError('研究意图已绑定另一方案，不能另起缩减方案')
        _write(folder/'state.json',{**state,'design_id':design['design_id'],'updated_at':_now()})


def intent_summary(intent_id):
    record=load_intent(intent_id);p=record['protocol']
    e=p['execution']
    state=record['state']
    action={'action':'design_model','arguments':{
            'request':p['question'],'research_intent_id':intent_id,
            **{k:deepcopy(e[k]) for k in ('parameters','ticks','dt','seed','data_bindings')}}}
    if state.get('design_id'):
        from ..agent.model_design import load_design
        design=load_design(state['design_id'],p['session_id'])
        action['arguments']['design_id']=state['design_id']
        if design['status']=='approved':action['action']='build_model'
        if design['status']=='blocked':
            action['arguments'].pop('design_id')
            action['arguments']['revise_from']=state['design_id']
    if state.get('study_id'):
        from .model_studies import load_study
        from .model_study_runs import next_action
        action=next_action(load_study(state['study_id']))
    if state.get('report_id'):action=None
    context=source_context(record)
    return {**state,'question':p['question'],'protocol_sha256':p['sha256'],
        **({'source_evidence_count':len(context['records'])} if context else {}),
        'request_complete':bool(state.get('report_id')),'next_action':action,
        'limits':['数据可用时点依据须核实；低拟合误差不证明政策因果或参数可识别']}


def sync_study(study_id,report=None):
    from .model_studies import load_study
    study=load_study(study_id)
    link=(study['protocol'].get('baseline',{}).get('manifest',{}).get('scenario_review') or {}).get('research_intent')
    if not link:return None
    ident=link['research_intent_id']
    folder=directory(ident)
    with file_lock(folder/'intent.lock',timeout=.1):
        current=load_intent(ident)
        if current['protocol']['sha256']!=link['protocol_sha256']:
            raise ValueError('研究意图与实际研究版本不一致')
        state=current['state']
        if state.get('study_id')!=study_id:raise ValueError('研究结果未绑定到同一原始意图')
        status=state['status'] if state.get('report_id') else 'research_pending' if study['state']['status']=='running' else 'awaiting_report'
        state.update(status=status,conclusion=study['state'].get('conclusion'),updated_at=_now())
        if report:
            if report['study_id']!=study_id:raise ValueError('报告研究编号不一致')
            state.update(status='complete' if study['state'].get('conclusion')=='passed_declared_checks' else 'failed',
                         report_id=report['report_id'],report_files=report['files'])
        if study['state'].get('selected_run'):state['result_run_id']=study['state']['selected_run']['run_id']
        _write(folder/'state.json',state)
    return intent_summary(ident)


def call_native_prepare(arguments,original_text,session_id):
    args=dict(arguments)
    args['question']=original_text
    try:
        return {'ok':True,'validation_pass':False,'payload':prepare_intent(**args,session_id=session_id)}
    except Exception as exc:return {'ok':False,'error':f'{type(exc).__name__}: {exc}'}


def call_native_context(arguments,original_text,session_id):
    try:
        _object(arguments,('research_intent_id','evidence'),('research_intent_id','evidence'),'来源证据工具')
        result=attach_source_evidence(arguments['research_intent_id'],arguments['evidence'],original_text,session_id)
        return {'ok':True,'validation_pass':False,'payload':result}
    except Exception as exc:return {'ok':False,'error':f'{type(exc).__name__}: {exc}'}


def context_schema():
    from .source_evidence import binding_schema
    return {'type':'object','properties':{
        'research_intent_id':{'type':'string','pattern':r'^MI-[a-f0-9]{24}$'},
        'evidence':{'type':'array','minItems':1,'items':binding_schema()}},
        'required':['research_intent_id','evidence'],'additionalProperties':False}


def prepare_schema():
    from .model_study_entry import tool_schema
    from ..structured_inputs import binding_schema
    schema=tool_schema()
    props=schema['properties']
    for name in ('baseline_run_id','time_atol','data_bindings'):props.pop(name,None)
    props['observables']={'type':'object','minProperties':1,'additionalProperties':{
        'type':'object','properties':{'unit':{'type':'string','minLength':1}},'required':['unit'],'additionalProperties':False},
        'description':'拟构建模型的实际校准目标名和单位；模型必须输出同名同单位字段，不把测量目标作为输入。'}
    props['time_unit']={'type':'string','minLength':1}
    props['execution']={'type':'object','properties':{
        'parameters':{'type':'object'},'ticks':{'type':'integer','minimum':1},'dt':{'type':'number','exclusiveMinimum':0},
        'seed':{'type':'integer','minimum':0,'maximum':2**64-1},'time_atol':{'type':'number','minimum':0},
        'data_bindings':{'type':'array','items':binding_schema()}},
        'required':['parameters','ticks','dt','time_atol','data_bindings'],'additionalProperties':False,
        'description':'与原文一致的建模和研究时钟/终点、基线参数及真实外生/初值输入。无输入给[]；基线seed默认研究seeds[0]。目标数据只放target_bindings。'}
    schema['required']=[name for name in props if name!='parent_study_id']
    return schema
