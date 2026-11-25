"""Regression for the diagnostic mismatch observed in real DSH research02.

Only the protocol boundary is tested here. Existing diagnostic tests independently
execute the real equations and stochastic solver; these data are labelled math.
"""
from copy import deepcopy

import jsonschema
import pytest

from dayan.research.model_intents import prepare_intent,load_intent,check_model,prepare_schema
from dayan.research.model_study_entry import tool_schema
from test_model_research_intent import arguments


def diagnostics():
    outputs={'stock':{'unit':'件','scale':1.}}
    return [
        {'id':'refine','kind':'time_refinement','basis':'核对固定流入数学基准的时间分辨率',
         'outputs':outputs,'dts':[.5,.25,.125],'dynamics':'deterministic','max_scaled_change':1e-9},
        {'id':'response','kind':'parameter_sweep','basis':'同一方程的事前流入量响应',
         'outputs':outputs,'parameter':'flow','values':[0.,1.,2.]},
        {'id':'disable_flow','kind':'ablation','basis':'实际流入参数置零，保留真实方程以核对机制',
         'outputs':outputs,'parameters':{'flow':0.},'mechanism':'关闭固定流入','rule_refs':['rates.stock']}
    ]


def late_ablation():
    spec=deepcopy(diagnostics()[2]);spec.pop('rule_refs')
    return {**spec,'binding':{'kind':'approved_plan'}}


def test_late_bound_ablation_preserves_one_scientific_intent_across_dsl_and_program_paths(tmp_path,monkeypatch):
    from dayan.research.diagnostic_bindings import resolve_bindings
    from test_program_harness import stock_program
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    args={**arguments(),'diagnostics':[late_ablation()]}
    ident=prepare_intent(**args,session_id='late-binding-owner')['research_intent_id']
    before=load_intent(ident)['protocol']
    parameter={'type':'float','default':1.,'minimum':0.,'maximum':4.,'unit':'件/小时'}
    definition={'kind':'stocks','time_unit':'小时','parameters':{'flow':parameter},
        'rates':{'stock':'flow'},'observables':{'stock':'stock'},'observable_units':{'stock':'件'}}
    def plan(kind,path):
        return {'kind':kind,'rule_refs':[{'mechanism':'固定流入','paths':[path]}],
            'diagnostic_bindings':[{'id':'disable_flow','rule_refs':[path],
                'reason':'flow置零切断库存流入，实际stock读取累计状态'}]}
    with pytest.raises(ValueError,match='先取得.*获审方案'):check_model(ident,definition)
    dsl=plan('stocks','rates.stock');check_model(ident,definition,dsl)
    resolved,mappings=resolve_bindings(args['diagnostics'],dsl,definition)
    assert resolved==[{**diagnostics()[2]}] and mappings==dsl['diagnostic_bindings']
    program=stock_program();program['parameters']={'flow':parameter}
    program['source']=program['source'].replace('2.*dt','parameters["flow"]*dt')
    program['equations'][0]['expression']='dS/dt=flow; S(0)=10'
    check_model(ident,program,plan('program','source.advance'))
    assert load_intent(ident)['protocol']==before
    assert before['diagnostics']==[late_ablation()]
    assert not (tmp_path/'model_studies').exists()  # no pretend calibration


def test_late_binding_rejects_ambiguous_declarations_and_unreviewed_or_unreachable_paths(tmp_path,monkeypatch):
    from dayan.research.diagnostic_bindings import plan_bindings,resolve_bindings
    from test_program_harness import stock_program
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    args=arguments();late=late_ablation()
    for spec in ({**late,'rule_refs':['rates.stock']},
                 {k:v for k,v in late.items() if k!='binding'},
                 {**late,'binding':{'kind':'guess_from_parameter'}},
                 {**late,'binding':{'kind':'approved_plan','rule_refs':['rates.stock']}}):
        with pytest.raises(ValueError):prepare_intent(**{**args,'diagnostics':[spec]},session_id='bad-binding')
    assert not (tmp_path/'model_research_intents').exists()
    plan={'kind':'program','rule_refs':[{'mechanism':'流入','paths':['source.advance','source.unused']}]}
    row={'id':'disable_flow','rule_refs':['source.advance'],'reason':'流入置零的事前数学对照'}
    for provided in (None,[],[row,row],[{**row,'id':'other'}],
                     [{**row,'rule_refs':['source.frame']}],[{**row,'rule_refs':['parameters.flow']}],
                     [{**row,'rule_refs':['source.missing']}],[{**row,'rule_refs':['source.advance','source.advance']}]):
        with pytest.raises(ValueError):plan_bindings([late],plan,provided)
    program=stock_program();program['source']+='\ndef unused(state):\n    return state["stock"]\n'
    plan['diagnostic_bindings']=[{**row,'rule_refs':['source.unused']}]
    with pytest.raises(ValueError,match='实际advance可达'):resolve_bindings([late],plan,program)


def test_invalid_diagnostics_stop_before_freezing_intent_or_starting_design(tmp_path,monkeypatch):
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    args=arguments()
    wrong_mode={**diagnostics()[0],'dynamics':'population'}  # observed actual native value
    wrong_clock={**diagnostics()[0],'dts':[.25,.125,.0625]}
    wrong_random={**diagnostics()[0],'dynamics':'ensemble_moments','max_scaled_mc_se':.1}
    wrong_path={**diagnostics()[2],'rule_refs':['derivative_zero_growth']}  # observed bare function
    wrong_units={**diagnostics()[0],'outputs':{'stock':{'unit':'kg','scale':1.}}}
    wrong_order={**diagnostics()[1],'values':[0.,2.,1.]}
    for bad,message in [(wrong_mode,'dynamics须为deterministic或ensemble_moments'),
                        (wrong_clock,'当前实际dt'),(wrong_random,'至少两个'),
                        (wrong_path,'实际行为/方程'),(wrong_units,'单位'),(wrong_order,'严格递增')]:
        with pytest.raises(ValueError,match=message):
            prepare_intent(**{**args,'diagnostics':[bad]},session_id='diagnostic-owner')
        assert not (tmp_path/'model_research_intents').exists()
        assert not (tmp_path/'model_designs').exists()


def test_valid_declarations_freeze_exact_protocol_and_random_mode_needs_real_replicates(tmp_path,monkeypatch):
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    args={**arguments(),'diagnostics':diagnostics()}
    before=deepcopy(args)
    created=prepare_intent(**args,session_id='diagnostic-owner')
    assert load_intent(created['research_intent_id'])['protocol']['diagnostics']==diagnostics()
    assert args==before  # no implicit repair, dropped criteria or rewritten user text
    stochastic={**diagnostics()[0],'dynamics':'ensemble_moments','max_scaled_mc_se':.1}
    random=prepare_intent(**{**args,'diagnostics':[stochastic],'seeds':[7,11]},session_id='diagnostic-owner')
    assert load_intent(random['research_intent_id'])['protocol']['diagnostics']==[stochastic]


def test_declaring_a_future_path_does_not_skip_actual_model_checks(tmp_path,monkeypatch):
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    args={**arguments(),'diagnostics':diagnostics()}
    ident=prepare_intent(**args,session_id='diagnostic-owner')['research_intent_id']
    definition={'kind':'stocks','time_unit':'小时','parameters':{
        'flow':{'type':'float','default':1.,'minimum':0.,'maximum':4.,'unit':'件/小时'}},
        'rates':{'stock':'flow'},'observables':{'stock':'stock'},'observable_units':{'stock':'件'}}
    check_model(ident,definition)
    changed=deepcopy(args)
    changed['diagnostics'][2]['rule_refs']=['rates.missing']
    other=prepare_intent(**changed,session_id='diagnostic-owner')['research_intent_id']
    with pytest.raises(ValueError,match='证据引用不存在'):check_model(other,definition)
    changed=deepcopy(args)
    changed['diagnostics'][1]['values']=[0.,1.,9.]
    other=prepare_intent(**changed,session_id='diagnostic-owner')['research_intent_id']
    with pytest.raises(ValueError):check_model(other,definition)  # actual parameter range still enforced


def test_both_public_schemas_expose_exact_diagnostic_modes_and_fields():
    declarations=diagnostics()
    declarations.append({**declarations[0],'dynamics':'ensemble_moments','max_scaled_mc_se':.1})
    declarations.append(late_ablation())
    for schema in (prepare_schema(),tool_schema()):
        items=schema['properties']['diagnostics']['items']
        jsonschema.Draft202012Validator.check_schema(items)
        for spec in declarations:jsonschema.validate(spec,items)
        for bad in ({**declarations[0],'dynamics':'population'},
                    {**declarations[0],'max_scaled_mc_se':.1},
                    {key:value for key,value in declarations[-2].items() if key!='max_scaled_mc_se'},
                    {**late_ablation(),'rule_refs':['rates.stock']}):
            with pytest.raises(jsonschema.ValidationError):jsonschema.validate(bad,items)
