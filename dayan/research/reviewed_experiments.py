"""Run parameter counterfactuals on an actually reviewed custom-model baseline."""
from copy import deepcopy
from types import SimpleNamespace

from ..solvers.codec import digest


def run_reviewed_experiment(query,baseline_run_id,*,arms,metric,seeds=None,seed=None,
                            ticks=None,dt=None,model_id=None,parameters=None,
                            interventions=None,data_bindings=None,analysis_window=None,purpose=None):
    from .model_study_entry import baseline_proof
    from ..agent.model_design import load_design
    from ..agent.verification import _structured_execution
    from ..custom_models import factory
    from ..structured_inputs import prepare_bindings,binding_schema
    from ..run_store import get_store
    from .specs import ExperimentSpec
    from .experiment import run_experiment,experiment_payload
    from ..agent.tools import _coerce_seeds

    proof,saved=baseline_proof(baseline_run_id,allow_interventions=True)
    manifest=proof['manifest'];review=manifest.get('scenario_review') or {}
    if review.get('research_intent'):
        raise ValueError('该基线属于冻结MI研究，须沿原研究校准/诊断/留出，不能用独立实验改写科研协议')
    if not isinstance(query,str) or not query.strip():raise ValueError('对照实验须保留实际研究问题query')
    if model_id is not None and model_id.upper()!=proof['model_id']:
        raise ValueError('对照实验的模型须与已审基线相同')
    definition=manifest['model_definition']
    if digest(factory(proof['model_id']).definition)!=digest(definition):
        raise ValueError('当前模型方程与已审基线不同')
    execution=load_design(proof['design_id'])['execution']
    bindings=deepcopy(execution.get('data_bindings',[]))
    # The design stores the complete normalized evidence, which can include
    # archive-only fields. Only the original mapping fields go back to runtime.
    mapping_keys=set().union(*(branch['properties'] for branch in binding_schema()['oneOf']))
    bindings=[{key:value for key,value in entry.items() if key in mapping_keys and value is not None} for entry in bindings]
    if data_bindings is not None and data_bindings!=bindings:
        raise ValueError('基线对照须保持同一真实输入映射；不能丢弃或替换真实输入')
    bound,ports,evidence=prepare_bindings(bindings,proof['model_id'],definition.get('input_ports',{}))
    issues,_=_structured_execution(SimpleNamespace(manifest=manifest,checkpoint=saved.get('checkpoint')),{
        'data_bindings':evidence,'structured_inputs':{name:{'contract':port['contract'],'count':port['count']}
                                                   for name,port in ports.items()}})
    expected=[entry for entry in evidence if 'port' not in entry]
    actual=[entry for entry in manifest.get('data_bindings',[]) if 'port' not in entry]
    baseline=deepcopy(manifest['actual']['effective_parameters'])
    if expected!=actual or any(baseline.get(key)!=value for key,value in bound.items()):
        issues.append('真实输入的来源、转换或实际数值已变化')
    if issues:raise ValueError('；'.join(issues))
    for key,value in (parameters or {}).items():
        if key not in baseline or baseline[key]!=value:
            raise ValueError('基线参数保持原值；参数变化明确写在arms[].params：'+key)
    steps=manifest['actual']['n_steps'];step_size=manifest['actual']['dt_used']
    if ticks is not None and (isinstance(ticks,bool) or ticks!=steps):raise ValueError('对照运行须保持基线步数')
    if dt is not None and (isinstance(dt,bool) or dt!=step_size):raise ValueError('对照运行须保持基线步长')
    if metric not in definition['observables']:raise ValueError('metric须为该模型实际观测字段')
    if not isinstance(arms,list) or not arms:raise ValueError('arms须明确给出至少一个实际参数或干预对照')
    for arm in arms:
        if not isinstance(arm,dict) or set(arm)-{'label','params','interventions'}:
            raise ValueError('对照臂只包含label、params、interventions')
        changes=arm.get('params') or {}
        if not isinstance(changes,dict):raise ValueError('arms[].params须为实际取值对象')
        for key in changes:
            if key not in definition.get('parameters',{}):raise ValueError('对照参数不在实际模型中：'+key)
            if key in bound:raise ValueError('该参数由真实输入绑定，不能用params伪覆盖真实输入：'+key)
    baseline_interventions=deepcopy(execution.get('interventions',[]))
    if interventions is not None and interventions!=baseline_interventions:
        raise ValueError('基线干预保持原队列，额外处理写入arms[].interventions')
    if seeds is not None and seed is not None:raise ValueError('seeds和seed只选一项')
    selected_seeds=list(_coerce_seeds(seeds if seeds is not None else seed if seed is not None else manifest['rng']['seed']))
    spec=ExperimentSpec(model_id=proof['model_id'],title=query,baseline_params=baseline,
        baseline_interventions=baseline_interventions,data_bindings=bindings,arms=deepcopy(arms),
        seeds=selected_seeds,ticks=steps,dt=step_size,primary_metric=metric,
        analysis_window=analysis_window or [],purpose=purpose or 'mechanism',
        rng_domain=manifest['requested']['experiment'],
        notes=['同一已审模型的真实配对反事实；效果方向由结果决定，不以假设成立作为模型通过条件。']).finalize()
    problems=spec.validate()
    if problems:raise ValueError('；'.join(problems))
    def attach_context(rr,arm,member_seed):
        rr.manifest['experiment_context']={
            'baseline_run_id':baseline_run_id,'baseline_archive_files':proof['archive_files'],
            'model_origin_request':proof['request'],'analysis_question':query,
            'model_design':{'design_id':proof['design_id'],'plan_sha256':proof['plan_sha256']},
            'model_definition_sha256':digest(definition),'arm':arm['label'],'seed':member_seed,
            'parameter_changes':{} if arm['label']=='基线' else deepcopy(arm['params']),
            'scope':'继承同一方程/来源方案审查；本次为实际参数对照，不把原基线数值验收或现实因果结论移植为变体通过'}
    result=run_experiment(spec,strict=True,persist=True,on_run=attach_context)
    if not result.ok or result.analysis.get('error'):
        raise ValueError('实际对照未完成：'+str(result.analysis.get('error') or result.warnings))
    get_store().save_experiment(result,query)
    return {**experiment_payload(result),'baseline_run_id':baseline_run_id,
            'comparison_scope':'同一已审模型/真实输入、配对种子和声明的参数处理；保留实际负效应或零效应'}
