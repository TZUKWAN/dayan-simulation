"""Intent protocol tests and actual numerical stages with controlled semantics.

These fixtures are labelled mathematical references, not native/empirical proof.
"""
from copy import deepcopy
import json

import pytest

from dayan import datasets
from dayan.research.model_intents import prepare_intent,load_intent,checked_intent,authoring_contract
from test_design_continuation import provider


QUESTION='新建库存增长模型，初态10件，每小时固定流入flow件。运行4步，步长0.5，随机种子7。使用观测校准模型参数flow，做独立数据验证并生成研究Word报告。明确数学基准，跳过文献检索。'


def arguments():
    data=datasets.ingest(json.dumps([{'time':0,'stock':10},{'time':1,'stock':12},{'time':2,'stock':14}]).encode(),
        name='明确的数学观测基准',format='json',source='test-mathematical-reference')
    return {'question':QUESTION,'observables':{'stock':{'unit':'件'}},'time_unit':'小时',
        'target_bindings':[{'id':'stock','dataset_id':data['dataset_id'],'observable':'stock','time_origin':'初态',
            'fields':{'time':{'type':'number','unit':'小时'},'value':{'type':'number','unit':'件'}},
            'columns':{'time':{'field':'time','source_unit':'小时'},'value':{'field':'stock','source_unit':'件'}},
            'time_field':'time','value_field':'value','series_by':[]}],
        'time_origin':'初态','split':{'kind':'forward_time','training_end':0,'validation_end':1},
        'execution':{'parameters':{},'ticks':4,'dt':.5,'seed':7,'time_atol':1e-9,'data_bindings':[]},
        'objectives':{'stock':{'weight':1.,'scale':{'kind':'external','value':1.,'unit':'件','basis':'数学单位尺度'}}},
        'param_grid':{'flow':[1.,2.]},'seeds':[7],'selection_top':2,
        'max_loss':{'training':0.,'validation':0.,'holdout':0.},'diagnostics':[],
        'availability':[],'information_mode':'retrospective_conditioning'}


def test_intent_is_frozen_reusable_and_only_training_values_enter_authoring(tmp_path,monkeypatch):
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    args=arguments()
    first=prepare_intent(**args,session_id='owner')
    ident=first['research_intent_id']
    assert first['status']=='awaiting_model' and not first['request_complete']
    assert prepare_intent(**args,session_id='owner')['research_intent_id']==ident
    p=load_intent(ident)['protocol']
    assert p['targets']['roles']['holdout'][0]['value']==14
    action=first['next_action']['arguments']
    safe=authoring_contract(ident,QUESTION,'owner',action,[],None)
    assert safe['training_points']==[{'observable':'stock','time':0.,'value':10.,'unit':'件'}]
    assert 'holdout' not in safe or isinstance(safe['holdout'],str)
    assert 'roles' not in json.dumps(safe)
    assert safe['target_counts']=={'training':1,'validation':1,'holdout':1}
    assert safe['input_availability']==p['availability'] and safe['input_usage_audit']==p['input_audit']
    from dayan import datasets
    actual_source=datasets.load(p['targets']['sources'][0]['dataset_id'])
    assert safe['target_sources'][0]['retrieved_at']==actual_source['retrieved_at']
    assert safe['target_sources'][0]['release_time_status']=='not_established_by_collection_timestamp'
    assert {k:v for k,v in safe['target_sources'][0].items() if k not in
        ('retrieved_at','collection_time_basis','release_time_status')}==p['targets']['sources'][0]
    integrity=safe['target_integrity']
    assert integrity['targets_sha256']==p['targets']['sha256']
    assert integrity['series']==[{'binding_id':'stock','observable':'stock','series':{},'unit':'件',
        'count':3,'first_time':0.,'last_time':2.,'minimum_interval':1.,'maximum_interval':1.,
        'partition_counts':{'training':1,'validation':1,'holdout':1}}]
    assert 'value' not in integrity['series'][0] and 'points' not in integrity
    assert safe['execution_rules']['diagnostics']['comparison_rule']=='all_refinements_vs_baseline_v2'
    assert 'does not score holdout again' in safe['execution_rules']['finalize']
    with pytest.raises(ValueError,match='原文或会话'):checked_intent(ident,QUESTION,'other')
    with pytest.raises(ValueError,match='原文或会话'):checked_intent(ident,'被改写的问题','owner')
    with pytest.raises(ValueError,match='冻结的研究意图'):
        authoring_contract(ident,QUESTION,'owner',{**action,'ticks':2},[],None)
    bad=deepcopy(args);bad['execution']['ticks']=3
    with pytest.raises(ValueError,match='用户原文冲突：ticks'):prepare_intent(**bad,session_id='owner')
    bad['question']=bad['question'].replace('运行4步，','')
    with pytest.raises(ValueError,match='目标时点'):prepare_intent(**bad,session_id='owner')
    import dayan.runtime
    with monkeypatch.context() as patch:
        patch.setattr(dayan.runtime,'assert_loaded_source',lambda:'changed')
        with pytest.raises(ValueError,match='平台版本已变化'):checked_intent(ident,QUESTION,'owner')


def test_target_collection_receipt_keeps_unknown_time_and_rejects_invalid_record_without_rewriting_protocol(tmp_path,monkeypatch):
    from dayan import datasets
    from dayan.research.model_intents import directory
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    args=arguments();prepared=prepare_intent(**args,session_id='receipt-owner')
    ident=prepared['research_intent_id'];p=load_intent(ident)['protocol']
    path=directory(ident)/'protocol.json';original=path.read_bytes()
    metadata=datasets.dataset_dir()/p['targets']['sources'][0]['dataset_id']/'metadata.json'
    saved=metadata.read_bytes();record=json.loads(saved)
    action=prepared['next_action']['arguments']
    try:
        metadata.write_text(json.dumps({k:v for k,v in record.items() if k!='retrieved_at'}),encoding='utf-8')
        safe=authoring_contract(ident,QUESTION,'receipt-owner',action,[],None)
        assert safe['target_sources'][0]['retrieved_at'] is None
        assert safe['target_sources'][0]['collection_time_basis']=='unavailable'
        metadata.write_text(json.dumps({**record,'retrieved_at':'not an actual timestamp'}),encoding='utf-8')
        with pytest.raises(ValueError,match='实际采集时间记录无效'):
            authoring_contract(ident,QUESTION,'receipt-owner',action,[],None)
        metadata.write_text(json.dumps({**record,'retrieved_at':'2026-01-01T00:00:00'}),encoding='utf-8')
        with pytest.raises(ValueError,match='实际采集时间记录无效'):
            authoring_contract(ident,QUESTION,'receipt-owner',action,[],None)
    finally:
        metadata.write_bytes(saved)
    assert path.read_bytes()==original


def test_prepare_schema_exposes_actual_binding_fields_and_origin_can_inherit(tmp_path,monkeypatch):
    import jsonschema
    from dayan.research.model_intents import prepare_schema
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    args=arguments();args['target_bindings'][0].pop('time_origin')
    schema=prepare_schema()
    jsonschema.validate(args,schema)
    assert prepare_intent(**args,session_id='schema-owner')['status']=='awaiting_model'
    bad=deepcopy(args)
    bad['execution']['data_bindings']=[{'dataset_id':args['target_bindings'][0]['dataset_id'],
        'field':'stock','parmeter':'initial'}]
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(bad,schema)


def configure_provider(provider,monkeypatch):
    import test_design_continuation
    from dayan.agent import model_tools,model_design
    from dayan import llm_client
    monkeypatch.setattr(test_design_continuation,'SOURCE',QUESTION)
    original=provider.complete
    def complete(*args,**kwargs):
        value=json.loads(original(*args,**kwargs))
        if kwargs['purpose']=='model-design-plan':
            value['criteria'][1].update(target=12.,reason='基线默认flow=1件/小时，2小时净增2件')
            value['assumptions']=['基线默认flow=1件/小时，仅为后续实际校准的起始设置']
            for row in value['coverage']:
                from dayan.agent.model_design import _requirement_index
                quote=_requirement_index(QUESTION)[row['requirement_id']]
                if '校准' in quote:row.update(role='research',implementation='同一研究意图校准/验证/报告',criteria=[])
            sent=json.loads(args[0][1]['content'])
            pending=[spec for spec in sent['execution'].get('research',{}).get('diagnostics',[]) if 'binding' in spec]
            if pending:
                value['diagnostic_bindings']=[{'id':spec['id'],'rule_refs':['rates.stock'],
                    'reason':'flow置零切断恒定流入，stock真实读取累计库存'} for spec in pending]
        if kwargs['purpose']=='build-model':
            from dayan.research.requirements import extract_request
            value.update(parameters={'flow':{'type':'float','default':1.,'minimum':0.,'maximum':4.,'unit':'件/小时'}},
                         rates={'stock':'flow'},observable_units={'stock':'件'},
                         mechanisms=extract_request(QUESTION)['mechanisms'])
        if kwargs['purpose']=='model-design-review':
            sent=json.loads(args[0][1]['content'])
            mappings=sent['plan'].get('diagnostic_bindings',[])
            if mappings:
                value['diagnostic_checks']=[{'id':row['id'],'verdict':'grounded',
                    'evidence':'受控语义夹具：flow置零切断rates.stock，stock观测读取实际库存；数值另行真实执行'} for row in mappings]
        if kwargs['purpose']=='scene-semantic-review':
            for row in value['checks']:
                if '校准' in row['quote']:row['refs']=['execution.research']
        return json.dumps(value,ensure_ascii=False)
    monkeypatch.setattr(model_tools,'complete',complete)
    monkeypatch.setattr(model_design,'complete',complete)
    monkeypatch.setattr(llm_client,'complete',complete)


def test_blocked_research_plan_revises_under_same_intent_and_scientific_protocol(provider,monkeypatch):
    from dayan.agent import model_tools,model_design
    from dayan import llm_client
    configure_provider(provider,monkeypatch)
    original=model_design.complete
    def complete(messages,**kwargs):
        response=json.loads(original(messages,**kwargs))
        sent=json.loads(messages[1]['content'])
        if kwargs['purpose']=='model-design-plan' and not sent.get('implementation_feedback'):
            response['criteria'][1]['target']=13.
        if kwargs['purpose']=='model-design-review' and sent['plan']['criteria'][1]['target']==13.:
            response.update(approved=False,issues=['默认flow1、初态10、2小时末值12，不能用13验基线'])
            response['criteria'][1]['verdict']='insufficient'
        if kwargs['purpose']=='model-design-revision' and sent.get('implementation_feedback'):
            response['resolutions']=[{'id':row['id'],'change':'只修默认flow1基线终点12，保留后续flow校准的冻结协议',
                                     'status':'resolved'} for row in sent['critique']]
        return json.dumps(response,ensure_ascii=False)
    for module in (model_tools,model_design,llm_client):monkeypatch.setattr(module,'complete',complete)
    prepared=prepare_intent(**arguments(),session_id='research-revision-owner')
    ident=prepared['research_intent_id']
    before=load_intent(ident)['protocol']
    action=prepared['next_action']
    denied=model_tools.call_native_model(action['action'],action['arguments'],QUESTION,'research-revision-owner')
    assert not denied['ok'] and denied['payload']['status']=='blocked',denied
    status=__import__('dayan.research.model_intents',fromlist=['intent_summary']).intent_summary(ident)
    action=status['next_action']
    assert action['arguments']['research_intent_id']==ident and action['arguments']['revise_from']==denied['design_id']
    corrected=model_tools.call_native_model(action['action'],action['arguments'],QUESTION,'research-revision-owner')
    assert corrected['ok'] and corrected['payload']['status']=='approved',corrected
    child=corrected['payload']
    assert child['revision_of']==denied['design_id']
    assert load_intent(ident)['state']['design_id']==child['design_id']
    assert load_intent(ident)['protocol']==before
    from dayan.agent.model_continuation import restore
    next_step=child['next_action']
    restored,source,_=restore(next_step['action'],next_step['arguments']['continuation_token'],
                              next_step['arguments'],QUESTION,'research-revision-owner')
    assert restored['research_intent_id']==ident and source==QUESTION
    assert child['plan']['criteria'][1]['target']==12.


@pytest.mark.parametrize('late_binding',[False,True])
def test_same_native_request_continues_review_build_actual_calibration_and_report(provider,monkeypatch,late_binding):
    from dayan.server import app
    from api_client import local_client
    from dayan.run_store import get_store
    from dayan.research.model_studies import load_study
    from dayan.agent.model_design import load_design
    from dayan.agent.tools import TOOL_SPECS
    configure_provider(provider,monkeypatch)
    # Controlled provider hooks are deliberately in this process. Production
    # managed-worker execution and the real native Agent are separate acceptance.
    monkeypatch.setenv('DAYAN_TASK_WORKER','1')
    client=local_client(app)
    def call(tool,args,session='intent-native-owner'):
        response=client.post('/api/tools/'+tool,json={'origin':'dsh','session_id':session,
            'original_text':QUESTION,'arguments':args})
        assert response.status_code==200,response.text
        return response.json()
    args=arguments()
    if late_binding:
        args['diagnostics']=[{'id':'disable_flow','kind':'ablation','basis':'声明固定流入置零的数学对照',
            'outputs':{'stock':{'unit':'件','scale':1.}},'parameters':{'flow':0.},
            'mechanism':'切断恒定流入','binding':{'kind':'approved_plan'}}]
    created=call('research_model_prepare',{**args,'question':'Agent改写的错误需求'})
    assert created['ok'],created
    assert next(s for s in TOOL_SPECS if s['name']=='research_model_prepare')['parameters']['required']
    ident=created['payload']['research_intent_id']
    assert load_intent(ident)['protocol']['question']==QUESTION
    assert load_intent(ident)['protocol']['session_id']=='intent-native-owner'
    action=created['payload']['next_action']
    rejected=call(action['action'],action['arguments'],'other-session')
    assert not rejected['ok'] and '原文或会话' in rejected['error']
    import dayan.research.model_intents as intents
    write=intents._write
    interrupted=[]
    def interrupted_write(path,value):
        if value.get('study_id') and not interrupted:
            interrupted.append(True)
            raise OSError('intentional test interruption after actual study creation')
        return write(path,value)
    monkeypatch.setattr(intents,'_write',interrupted_write)
    provider.cost=70
    first_design=None
    for index in range(8):
        result=call(action['action'],action['arguments'])
        assert result['ok'],result
        payload=result['payload']
        first_design=first_design or payload.get('design_id')
        if payload.get('status')=='research_pending' and payload.get('study_id'):break
        if payload.get('continuation_error'):
            assert payload['execution_complete'] and 'intentional test interruption' in payload['continuation_error']
            action=payload['next_action']
            continue
        assert payload['executed'] is False
        action=payload['next_action']
        actual_arguments=action['arguments']
        if actual_arguments.get('continuation_token'):
            from dayan.agent.model_continuation import restore
            actual_arguments,source,_=restore(action['action'],actual_arguments['continuation_token'],
                                              actual_arguments,QUESTION,'intent-native-owner')
            assert source==QUESTION
        assert actual_arguments['research_intent_id']==ident
        assert actual_arguments['request']==QUESTION
    assert payload['status']=='research_pending' and not result['validation_pass'],result
    assert interrupted==[True]
    assert payload['request_complete'] is False and payload['execution_complete']
    rid=payload['run_id'];sid=payload['study_id']
    archive=get_store().load(rid)
    assert archive['request_text']==QUESTION
    assert archive['manifest']['scenario_review']['coverage']['status']=='model_ready'
    assert archive['observations'][-1]['stock']==12.
    design=load_design(first_design)
    assert design['request']==QUESTION
    assert design['execution']['delivery']['report_tool']=='research_report'
    assert 'research_finalize' in design['execution']['delivery']['replay']['display_run_id']
    assert len(design['stages'])==5
    assert any(row['role']=='research' and row['research_intent_id']==ident for row in design['plan']['coverage'])
    assert load_study(sid)['protocol']['question']==QUESTION
    if late_binding:
        from dayan.solvers.codec import digest
        protocol=load_study(sid)['protocol']
        assert load_intent(ident)['protocol']['diagnostics']==args['diagnostics']
        assert protocol['diagnostic_declarations']==args['diagnostics']
        resolved={k:v for k,v in args['diagnostics'][0].items() if k!='binding'}
        assert protocol['diagnostics']==[{**resolved,'rule_refs':['rates.stock']}]
        mapping=protocol['diagnostic_implementation_binding']
        assert mapping['design_id']==first_design and mapping['plan_sha256']==design['plan_sha256']
        assert mapping['model_definition_sha256']==digest(archive['manifest']['model_definition'])
        assert mapping['declarations_sha256']==digest(args['diagnostics'])
        assert [row['id'] for row in design['review']['diagnostic_checks']]==['disable_flow']
    assert load_study(sid)['state']['trials']==[]
    before=len(provider.calls)
    # A repeat after the accepted baseline reuses both the archive and study.
    repeated=call('build_model',action['arguments'])
    assert repeated['ok'] and repeated['payload']['run_id']==rid and repeated['payload']['study_id']==sid,repeated
    assert len(provider.calls)==before
    wrong=call('report_run',{'run_id':rid})
    assert not wrong['ok'] and '模型基线' in wrong['error']
    build_action=action
    action=payload['next_action']
    for _ in range(7):
        result=call(action['action'],action['arguments'])
        assert result['ok'],result
        action=result['payload']['next_action']
        if action['action']=='research_finalize':break
    assert result['validation_pass'] and result['payload']['selection']['parameters']=={'flow':2.},result
    assert result['payload']['holdout']['loss']==0.
    rejected=call('research_report',{'study_id':sid})
    assert not rejected['ok'] and 'research_finalize' in rejected['error']
    finalized=call(action['action'],action['arguments'])
    assert finalized['ok'],finalized
    selected_id=finalized['payload']['run_id']
    assert selected_id!=rid
    selected=get_store().load(selected_id)
    assert selected['observations'][-1]['stock']==14.
    assert selected['manifest']['actual']['effective_parameters']=={'flow':2.}
    assert selected['manifest']['research_study']['study_id']==sid
    assert selected['state_frames']
    replay_url=design['execution']['delivery']['replay']['state_url'].replace('{display_run_id}',selected_id)
    replay=client.get(replay_url)
    assert replay.status_code==200 and replay.json()['run_id']==selected_id
    assert replay.json()['observations']==selected['observations']
    assert call('research_finalize',{'study_id':sid})['payload']['run_id']==selected_id
    action=finalized['payload']['next_action']
    report=call(action['action'],action['arguments'])
    assert report['ok'] and report['payload']['request_complete'],report
    state=load_intent(ident)['state']
    assert state['status']=='complete' and state['study_id']==sid and state['baseline_run_id']==rid
    assert state['result_run_id']==selected_id
    assert state['report_id']==report['payload']['report_id']
    research_delivery=design['execution']['delivery']['research']
    actual_file_url=research_delivery['file_url'].format(study_id=sid,report_id=state['report_id'],filename='research.docx')
    assert client.get(actual_file_url).content==__import__('pathlib').Path(report['payload']['path']).read_bytes()
    assert client.get(research_delivery['study_url'].format(study_id=sid)).status_code==200
    assert prepare_intent(**args,session_id='intent-native-owner')['next_action'] is None
    repeated=call('build_model',build_action['arguments'])
    assert repeated['ok'] and repeated['validation_pass'] and repeated['payload']['request_complete'],repeated
    assert repeated['payload']['run_id']==rid and repeated['payload']['next_action'] is None
    from pathlib import Path
    from zipfile import ZipFile
    facts=json.loads(Path(report['payload']['path']).with_name('research.facts.json').read_text(encoding='utf-8'))
    assert facts['result_run']['run_id']==selected_id and facts['result_run']['observations']==selected['observations']
    assert any(fig['kind']=='actual_selected_trajectory' and fig['data'][-1]['value']==14. for fig in facts['figures'])
    if late_binding:
        diagnostic=facts['diagnostics']['reports'][0]
        assert diagnostic['id']=='disable_flow'
        assert [profile['points'][-1]['metrics']['stock']['mean'] for profile in diagnostic['profiles']]==[14.,10.]
        assert diagnostic['differences_from_baseline'][0]['points'][-1]['metrics']['stock']['mean']==-4.
    with ZipFile(Path(report['payload']['path']).with_name('reproducibility.zip')) as pack:
        assert json.loads(pack.read('selected_result/manifest.json'))==selected['manifest']
    # Actual inner prompts contain the exact original and no held-out target values.
    for row in provider.calls:
        raw=json.loads(row['messages'][1]['content'])
        execution=raw.get('execution',raw.get('实际执行与数据',{}))
        if execution.get('research'):
            assert execution['research']['training_points']==[{'observable':'stock','time':0.,'value':10.,'unit':'件'}]


def test_late_bound_diagnostic_cannot_be_approved_without_its_independent_review(provider,monkeypatch):
    from dayan.agent import model_tools,model_design
    from dayan.run_store import get_store
    from test_model_diagnostic_prepare import late_ablation
    configure_provider(provider,monkeypatch)
    original=model_design.complete
    def skip_review(messages,**kwargs):
        response=json.loads(original(messages,**kwargs))
        if kwargs['purpose']=='model-design-review':response.pop('diagnostic_checks',None)
        return json.dumps(response,ensure_ascii=False)
    monkeypatch.setattr(model_design,'complete',skip_review)
    prepared=prepare_intent(**{**arguments(),'diagnostics':[late_ablation()]},session_id='skipped-diagnostic-review')
    ident=prepared['research_intent_id'];before=load_intent(ident)['protocol']
    action=prepared['next_action']
    result=model_tools.call_native_model(action['action'],action['arguments'],QUESTION,'skipped-diagnostic-review')
    assert not result['ok'] and result['payload']['status']=='blocked',result
    assert 'diagnostic_checks' in result['error']
    assert not get_store().history() and load_intent(ident)['protocol']==before
    assert result['payload']['next_action']['arguments']['research_intent_id']==ident


def test_failed_holdout_keeps_same_protocol_and_cannot_claim_research_pass(provider,monkeypatch):
    from dayan.agent.model_tools import call_native_model
    from dayan.agent.data_tools import research_calibrate,research_finalize,research_report
    from dayan.research.model_studies import load_study
    from dayan.research.model_study_runs import verify_selected_run
    from dayan.run_store import get_store
    configure_provider(provider,monkeypatch)
    args=arguments()
    # Deliberately incompatible final observation: validation chooses flow=2,
    # while a zero-tolerance holdout at 14.1 must remain failed.
    source=datasets.ingest(b'[{"time":0,"stock":10},{"time":1,"stock":12},{"time":2,"stock":14.1}]',
        name='明确的留出失败数学夹具',format='json',source='test-deliberate-holdout-mismatch')
    args['target_bindings'][0]['dataset_id']=source['dataset_id']
    prepared=prepare_intent(**args,session_id='failed-study-owner')
    action=prepared['next_action']
    result=call_native_model(action['action'],action['arguments'],QUESTION,'failed-study-owner')
    for _ in range(5):
        if result.get('payload',{}).get('study_id'):break
        assert result['ok'],result
        action=result['payload']['next_action']
        result=call_native_model(action['action'],action['arguments'],QUESTION,'failed-study-owner')
    assert result['ok'] and result['payload'].get('study_id'),result
    sid=result['payload']['study_id']
    done=research_calibrate(sid,max_evaluations=10)
    assert done['ok'] and not done['validation_pass']
    assert done['payload']['conclusion']=='failed_predeclared_tolerance'
    assert done['payload']['holdout']['loss']==pytest.approx(.01)
    assert load_study(sid)['protocol']['max_loss']==args['max_loss']
    final=research_finalize(sid)
    assert final['ok'] and not final['validation_pass']
    report=research_report(sid)
    assert report['ok'] and report['payload']['research_intent']['status']=='failed'
    from docx import Document
    text='\n'.join(p.text for p in Document(report['payload']['path']).paragraphs)
    assert '未通过事前误差阈值' in text and '通过本协议声明的有限检查' not in text
    study=load_study(sid)
    path=get_store()._path(final['payload']['run_id'])/'observations.json'
    saved=path.read_bytes()
    try:
        path.write_text('[]',encoding='utf-8')
        with pytest.raises(ValueError,match='归档文件校验失败'):verify_selected_run(study)
        broken=research_report(sid)
        assert not broken['ok'] and '归档文件校验失败' in broken['error']
    finally:path.write_bytes(saved)
