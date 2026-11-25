"""Public study creation from a completed, reviewed custom-model run.

The baseline establishes model and input provenance, not empirical validity.
The new immutable protocol owns all subsequent candidate evaluations.
"""
from copy import deepcopy
import hashlib

from ..solvers.codec import digest
from .model_evaluation import prepare_evaluation


def baseline_proof(run_id,*,allow_interventions=False):
    from ..run_store import get_store
    from ..agent.model_design import load_design, approved_plan, check_definition
    from ..runtime import assert_loaded_source
    store=get_store()
    meta,manifest=store.load_manifest(run_id)
    # Stream-check all actual artifacts without materializing potentially huge
    # population histories. The immutable input checkpoint is loaded only when
    # structured input provenance needs it below.
    saved=store.load(run_id,exclude=meta['files'])
    for name,expected in meta['files'].items():
        with (store._path(run_id)/name).open('rb') as stream:
            actual=hashlib.file_digest(stream,'sha256').hexdigest()
        if actual!=expected:raise ValueError('运行产物校验失败: '+name)
    if manifest.get('structured_inputs',{}).get('ports'):
        saved=store.load(run_id,exclude=[name for name in meta['files'] if name!='checkpoint.json'])
    review=manifest.get('scenario_review') or {}
    verification=review.get('runtime_checks',{}).get('verification',{})
    link=review.get('model_design',{})
    if (not manifest.get('model_definition') or not review.get('matched') or review.get('missing')
            or review.get('coverage',{}).get('status') not in ('covered','model_ready')
            or verification.get('status')!='passed' or verification.get('issues')
            or not verification.get('criteria') or not all(r.get('passed') for r in verification['criteria'])
            or not link.get('design_id')):
        raise ValueError('研究基线须为已有方案审查、语义复核和实际数值验收的完整自建模型运行')
    if manifest.get('source_fingerprint')!=assert_loaded_source():
        raise ValueError('研究基线的平台版本已变化；请在当前版本重新审查并运行，不能混用旧验收')
    design=load_design(link['design_id'])
    approved_plan(design['design_id'],design['request'],design['execution'],design['session_id'],record=design)
    if link.get('plan_sha256')!=design['plan_sha256'] or meta.get('request_text')!=design['request']:
        raise ValueError('研究基线的原始需求或批准方案与运行归档不一致')
    check_definition(design['plan'],manifest['model_definition'])
    intent=review.get('research_intent')
    context=None
    if review.get('coverage',{}).get('status')=='model_ready' and not intent:
        raise ValueError('未完成研究的基线缺少绑定的真实研究意图')
    if intent:
        from .model_intents import checked_intent,source_context
        record=checked_intent(intent['research_intent_id'],design['request'],design['session_id'])
        if (intent.get('protocol_sha256')!=record['protocol']['sha256']
                or design['execution'].get('research',{}).get('research_intent_id')!=intent['research_intent_id']):
            raise ValueError('基线方案/运行与冻结研究意图不一致')
        context=source_context(record)
        if design['execution'].get('research',{}).get('source_evidence')!=context:
            raise ValueError('基线实际获审来源证据不是同意图的当前固定版本')
    if not allow_interventions and (manifest.get('interventions') or manifest.get('requested',{}).get('interventions')):
        raise ValueError('当前研究求值入口尚未传递外部干预队列；不能静默丢弃基线干预')
    proof={'run_id':run_id,'model_id':manifest['model_id'],'request':design['request'],
           'design_id':design['design_id'],'plan_sha256':design['plan_sha256'],
           'source_fingerprint':manifest['source_fingerprint'],'archive_files':deepcopy(meta['files']),
           'manifest':manifest,'plan':design['plan'],
           'scope':'已审查模型与基线实际运行的来源证据；不表示经验校准或新的研究问题已获科学验证'}
    if context:proof['source_evidence']=deepcopy(context)
    proof['sha256']=digest(proof)
    return proof,saved


def create_model_study(question,baseline_run_id,*,target_bindings,time_origin,split,
                       objectives,param_grid,seeds,selection_top,max_loss,diagnostics,
                       availability,information_mode,time_atol=1e-9,data_bindings=None,
                       parent_study_id=None):
    from ..structured_inputs import prepare_bindings
    from ..agent.verification import _structured_execution
    from types import SimpleNamespace
    from .model_studies import create_study
    proof,saved=baseline_proof(baseline_run_id)
    manifest=proof['manifest']
    intent=(manifest.get('scenario_review') or {}).get('research_intent')
    if intent:
        from .model_intents import require_study_contract
        require_study_contract(intent['research_intent_id'],question,{
            'target_bindings':target_bindings,'time_origin':time_origin,'split':split,'objectives':objectives,
            'param_grid':param_grid,'seeds':seeds,'selection_top':selection_top,'max_loss':max_loss,
            'diagnostics':diagnostics,'availability':availability,'information_mode':information_mode,
            'time_atol':time_atol,'data_bindings':data_bindings or [],'parent_study_id':parent_study_id})
    if data_bindings is not None and not isinstance(data_bindings,list):
        raise ValueError('data_bindings须为实际输入映射列表')
    actual=manifest['actual']
    params=deepcopy(actual['effective_parameters'])
    execution={'parameters':params,'ticks':actual['n_steps'],'dt':actual['dt_used'],
               'experiment':manifest['requested']['experiment'],'time_atol':time_atol,
               'data_bindings':deepcopy(data_bindings or [])}
    if not isinstance(availability,list) or len(availability)!=len(execution['data_bindings']):
        raise ValueError('availability须按data_bindings原顺序逐项声明可用时点及用途')
    availability=[{**item,'binding_sha256':item.get('binding_sha256',digest(binding))}
                  for binding,item in zip(execution['data_bindings'],availability)]
    evaluation=prepare_evaluation(manifest['model_id'],target_bindings=target_bindings,time_origin=time_origin,
        split=split,execution=execution,objectives=objectives,availability=availability,information_mode=information_mode)
    if evaluation['model']['definition']!=manifest['model_definition']:
        raise ValueError('当前注册模型与已验收基线方程不一致')
    bound,ports,evidence=prepare_bindings(execution['data_bindings'],manifest['model_id'],
                                        manifest['model_definition'].get('input_ports',{}))
    issues,_=_structured_execution(SimpleNamespace(manifest=manifest,checkpoint=saved.get('checkpoint')),{
        'data_bindings':evidence,'structured_inputs':{key:{'contract':port['contract'],'count':port['count']}
                                                    for key,port in ports.items()}})
    expected=[row for row in evidence if 'port' not in row]
    received=[row for row in manifest.get('data_bindings',[]) if 'port' not in row]
    if expected!=received or any(params.get(key)!=value for key,value in bound.items()):
        issues.append('研究数据映射须与已运行基线相同，不能丢弃或替换真实输入')
    if issues:raise ValueError('；'.join(issues))
    return create_study(question,evaluation,param_grid=param_grid,seeds=seeds,
        selection_top=selection_top,max_loss=max_loss,diagnostics=diagnostics,
        parent_study_id=parent_study_id,baseline=proof)


def tool_schema():
    string={'type':'string','minLength':1}
    obj={'type':'object'}
    array={'type':'array','items':obj}
    properties={name:dict(string) for name in ('question','baseline_run_id','time_origin','information_mode')}
    properties.update({name:dict(obj) for name in ('split','objectives','param_grid','max_loss')})
    properties.update({name:deepcopy(array) for name in ('target_bindings','diagnostics','availability','data_bindings')})
    properties.update(seeds={'type':'array','minItems':1,'uniqueItems':True,'items':{'type':'integer','minimum':0,'maximum':2**64-1}},
        selection_top={'type':'integer','minimum':1},time_atol={'type':'number','minimum':0,'default':1e-9},
        parent_study_id={'type':['string','null']})
    properties['information_mode']['enum']=['retrospective_conditioning','forecast']
    properties['baseline_run_id']['description']='当前版本通过全部建模审查和实际数值验收的自建模型run_id。研究沿用该模型、步长、终点及实际输入；不会把基线轨迹当候选拟合结果。'
    properties['target_bindings']['description']='真实DS观测合同，逐项含id,dataset_id,observable,time_origin,fields,columns,time_field,value_field,series_by；可用path/filters选择明确系列。数值字段带unit，columns指定原field或pointer、source_unit及显式scale/offset；非零offset须transformation_note。各目标须有训练/验证/留出观测，时点严格对应模型实际步。'
    from .model_observations import target_binding_schema
    properties['target_bindings']['items']=target_binding_schema()
    properties['split'].update(properties={'kind':{'const':'forward_time'},'training_end':{'type':'number','minimum':0},'validation_end':{'type':'number','minimum':0}},required=['kind','training_end','validation_end'],additionalProperties=False)
    properties['objectives']['description']='逐目标 {observable:{weight:正数,scale:{kind:"training_std"}}}，或scale={kind:"external",value:正数,unit:同观测单位,basis:事前依据}；不用留出数据定尺度。'
    properties['param_grid']['description']='已声明且非真实数据绑定的参数名到有限候选值列表。候选范围在建模参数合同内；所有候选均实际运行。'
    properties['max_loss']['description']='事前固定training、validation、holdout三个标准化均方损失阈值；null表示不设通过阈值，不能报告完整验收通过。'
    from .model_diagnostics import diagnostic_schema
    properties['diagnostics']['items']=diagnostic_schema()
    properties['diagnostics']['description']='事前声明数组，[]明确不做数值诊断。每项按oneOf给完整字段。time_refinement.dynamics为deterministic或ensemble_moments；随机矩模式至少2个seed并给max_scaled_mc_se，不声明强收敛。未选择模型时，消融用binding={kind:"approved_plan"}，后续获审方案以diagnostic_bindings按id给真实rule_refs/reason并独立复核；科学参数/机制/指标/判据事前冻结。已确定实现可给rule_refs真实rates/agents.update/source路径，与binding互斥；不填裸函数名。'
    properties['availability']['description']='按data_bindings同一顺序逐输入给 {available_at:模型时间数值,basis:来源可用时间依据,training_target_use:"none"或"initial_condition"或"lagged_observation"}，宿主绑定实际映射hash；无输入用[]。forecast还须target_bindings给available_field及availability_basis，训练观测不得晚于training_end才可获得。不能把验证/留出目标当输入。'
    properties['data_bindings']['description']='与基线相同的实际运行输入原始映射；目标数据只放target_bindings，不能混作输入。'
    required=[name for name in properties if name not in ('time_atol','data_bindings','parent_study_id')]
    return {'type':'object','properties':properties,'required':required,'additionalProperties':False}
