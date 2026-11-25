"""Actual model runs and public research APIs; semantic provider is controlled.

These mathematical fixtures test dispatch and provenance, not native LLM quality
or empirical validity.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from test_design_continuation import provider,SOURCE
from dayan.agent import model_tools
from dayan.agent.data_tools import research_model_create,research_calibrate
from dayan.research.model_studies import load_study
from dayan.run_store import get_store


def setup_study(provider,monkeypatch,*,with_input=False):
    from dayan import llm_client,datasets
    original=provider.complete
    def complete(*args,**kwargs):
        value=json.loads(original(*args,**kwargs))
        if kwargs['purpose']=='build-model':
            value.update(parameters={'flow':{'type':'float','default':2.,'minimum':0.,'maximum':4.,'unit':'件/小时'}},
                         rates={'stock':'flow'},observable_units={'stock':'件'})
            if with_input:
                value['parameters']['initial']={'type':'float','default':0.,'minimum':0.,'maximum':100.,'unit':'件'}
                value['initial_state']['stock']='initial'
        return json.dumps(value,ensure_ascii=False)
    monkeypatch.setattr(model_tools,'complete',complete)
    monkeypatch.setattr(llm_client,'complete',complete)
    bindings=[]
    if with_input:
        initial=datasets.ingest(b'[{"initial":10}]',name='明确数学初值',format='json',source='test-initial-condition')
        bindings=[{'dataset_id':initial['dataset_id'],'field':'initial','parameter':'initial','source_unit':'件','target_unit':'件'}]
    result=model_tools.call_native_model('build_model',{'data_bindings':bindings},SOURCE,'study-entry-protocol')
    for _ in range(8):
        if result.get('payload',{}).get('status')!='pending':break
        action=result['payload']['next_action']
        result=model_tools.call_native_model(action['action'],action['arguments'],SOURCE,'study-entry-protocol')
    assert result['ok'] and result['payload'].get('run_id'),result
    rid=result['payload']['run_id']
    source=datasets.ingest(json.dumps([{'time':0,'stock':10},{'time':1,'stock':12},{'time':2,'stock':14}]).encode(),
        name='明确数学解析值',format='json',source='test-mathematical-reference')
    args={'question':'对已审基线 '+rid+' 的固定流入模型估计流入率，数学夹具，不代表经验研究。',
        'baseline_run_id':rid,'target_bindings':[{'id':'stock','dataset_id':source['dataset_id'],'observable':'stock',
            'fields':{'time':{'type':'number','unit':'小时'},'value':{'type':'number','unit':'件'}},
            'columns':{'time':{'field':'time','source_unit':'小时'},'value':{'field':'stock','source_unit':'件'}},
            'time_field':'time','value_field':'value','series_by':[],'time_origin':'初态'}],
        'time_origin':'初态','split':{'kind':'forward_time','training_end':0,'validation_end':1},
        'objectives':{'stock':{'weight':1.,'scale':{'kind':'external','value':1.,'unit':'件','basis':'数学单位尺度'}}},
        'param_grid':{'flow':[1.,2.]},'seeds':[7],'selection_top':2,
        'max_loss':{'training':0.,'validation':0.,'holdout':0.},'diagnostics':[],
        'availability':[],'information_mode':'retrospective_conditioning'}
    if with_input:
        args.update(data_bindings=bindings,availability=[{'available_at':0.,'basis':'数学给定初始条件','training_target_use':'none'}])
    return rid,args


def test_public_creation_preserves_approved_baseline_then_runs_real_candidates(provider,monkeypatch):
    from dayan.server import app
    from api_client import local_client
    from dayan.agent.tools import TOOL_SPECS
    rid,args=setup_study(provider,monkeypatch)
    saved=get_store().load(rid)
    baseline_files=deepcopy(saved['files'])
    spec=next(s for s in TOOL_SPECS if s['name']=='research_model_create')
    assert spec['parameters']['properties']['information_mode']['enum']==['retrospective_conditioning','forecast']
    client=local_client(app)
    reply=client.post('/api/tools/research_model_create',json={
        'origin':'dsh','session_id':'study-entry-protocol','original_text':args['question'],
        'arguments':{**args,'question':'Agent改写的问题应该被真实用户原文替换'}})
    assert reply.status_code==200,reply.text
    created=reply.json()
    assert created['ok'] and not created['validation_pass'],created
    sid=created['payload']['study_id']
    study=load_study(sid)
    assert study['protocol']['question']==args['question']
    assert study['protocol']['baseline']['run_id']==rid
    assert study['protocol']['baseline']['manifest']==saved['manifest']
    assert study['protocol']['baseline']['archive_files']==baseline_files
    assert study['state']['trials']==[]
    assert research_model_create(**args)['payload']['study_id']==sid
    done=research_calibrate(sid,max_evaluations=10)
    assert done['ok'] and done['validation_pass'],done
    assert done['payload']['selection']['parameters']=={'flow':2.}
    assert done['payload']['holdout']['loss']==0.
    assert get_store().load(rid)['files']==baseline_files
    assert len(load_study(sid)['state']['trials'])==5
    from dayan.research.model_study_reports import generate_report
    from docx import Document
    from pathlib import Path
    from zipfile import ZipFile
    report=generate_report(sid)
    paragraphs='\n'.join(p.text for p in Document(report['path']).paragraphs)
    assert '模型基线运行：'+rid in paragraphs
    with ZipFile(Path(report['path']).with_name('reproducibility.zip')) as archive:
        protocol=json.loads(archive.read('protocol.json'))
        assert protocol['baseline']['manifest']==saved['manifest']
        assert protocol['baseline']['plan_sha256']==saved['manifest']['scenario_review']['model_design']['plan_sha256']
    from dayan.research.integration_events import append_event
    from dayan.research.native_contract import protect
    append_event('study-entry-protocol','research_model_create',created)
    assert protect('research_report',{'study_id':sid},'继续生成报告','study-entry-protocol')=={'study_id':sid}
    with pytest.raises(ValueError,match='不属于本次原始需求'):
        protect('research_report',{'study_id':sid},'研究农业补贴的三方博弈','study-entry-protocol')
    with pytest.raises(ValueError,match='原文须明确'):
        protect('research_model_create',args,'另一项没有指定基线的研究','study-entry-protocol')


def test_creation_rejects_missing_review_source_changes_units_and_archive_tampering(provider,monkeypatch):
    from dayan.research.model_study_entry import baseline_proof
    from dayan.runtime import run_model_full
    rid,args=setup_study(provider,monkeypatch)
    saved=get_store().load(rid)
    # A real but unreviewed numerical run cannot supply approval.
    from dayan.custom_models import register
    unchecked=register({'kind':'stocks','name':'未审查夹具','description':'只检验拒绝路径','time_unit':'小时',
        'initial_state':{'stock':10},'rates':{'stock':2},'observables':{'stock':'stock'},'observable_units':{'stock':'件'}})
    run=run_model_full(unchecked['model_id'],ticks=4,dt=.5,seed=7)
    bad=get_store().save_run(run)
    with pytest.raises(ValueError,match='方案审查'):baseline_proof(bad)
    import dayan.runtime
    with monkeypatch.context() as patch:
        patch.setattr(dayan.runtime,'assert_loaded_source',lambda:'changed-source')
        with pytest.raises(ValueError,match='平台版本已变化'):baseline_proof(rid)
    wrong=deepcopy(args)
    wrong['target_bindings'][0]['columns']['value']['source_unit']='kg'
    result=research_model_create(**wrong)
    assert not result['ok'] and '单位' in result['error']
    path=get_store()._path(rid)/'observations.json'
    previous=path.read_bytes()
    try:
        path.write_text('[]',encoding='utf-8')
        with pytest.raises(ValueError,match='运行产物校验失败: observations.json'):baseline_proof(rid)
    finally:path.write_bytes(previous)
    assert get_store().load(rid)['manifest']==saved['manifest']


def test_public_creation_preserves_actual_scalar_input_and_rejects_dropping_it(provider,monkeypatch):
    rid,args=setup_study(provider,monkeypatch,with_input=True)
    result=research_model_create(**args)
    assert result['ok'],result
    study=load_study(result['payload']['study_id'])
    assert study['protocol']['evaluation']['bound_parameters']=={'initial':10.}
    assert study['protocol']['evaluation']['input_audit']['inputs'][0]['availability']['available_at']==0.
    done=research_calibrate(result['payload']['study_id'],max_evaluations=10)
    assert done['validation_pass'] and done['payload']['selection']['parameters']=={'flow':2.},done
    from dayan.research.model_study_reports import generate_report
    from docx import Document
    report=generate_report(result['payload']['study_id'])
    text='\n'.join(p.text for p in Document(report['path']).paragraphs)
    assert 'initial：模型默认值 0；本研究实际开始值 10.0' in text
    assert 'flow：模型默认值 2；本研究实际开始值 2.0' in text
    facts=json.loads(Path(report['path']).with_name('research.facts.json').read_text(encoding='utf-8'))
    assert facts['presentation']['actual_parameters']['values']=={'initial':10.,'flow':2.}
    dropped={**args,'data_bindings':[],'availability':[]}
    rejected=research_model_create(**dropped)
    assert not rejected['ok'] and '数据映射须与已运行基线相同' in rejected['error'],rejected


def test_discovery_exposes_study_contract_without_claiming_new_native_workflow(monkeypatch,tmp_path):
    from datetime import datetime,timezone
    from dayan.agent.scenario_tools import modeling_guide
    from dayan.research.native_contract import protect
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    request='构建社会仿真模型，使用真实观测校准模型参数并做独立数据验证。'
    before=datetime.now(timezone.utc)
    guide=modeling_guide(request)['payload']
    assert before<=datetime.fromisoformat(guide['runtime_clock']['observed_at_utc'])<=datetime.now(timezone.utc)
    assert guide['runtime_clock']['basis']=='platform_system_clock'
    names={row['name'] for row in guide['tool_contracts']}
    assert {'research_model_context','research_model_create','research_calibrate','research_report'}<=names
    assert guide['model_research']['prepare_tool']=='research_model_prepare'
    assert guide['model_research']['context_tool']=='research_model_context'
    context_spec=next(row for row in guide['tool_contracts'] if row['name']=='research_model_context')
    assert set(context_spec['parameters']['required'])=={'research_intent_id','evidence'}
    assert 'holdout_and_report' in guide['model_research']['new_empirical_model_workflow']
    assert guide['next_tools']['custom_model'] is None
    with pytest.raises(ValueError,match='缺少用户原文'):
        protect('research_model_create',{},'','native-scope')
