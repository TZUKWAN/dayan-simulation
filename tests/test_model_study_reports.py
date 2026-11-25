"""Reports over actual numerical study trials; these are not empirical claims."""
from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from docx import Document
import pytest

from dayan.research.model_studies import create_study,advance_study,directory
from dayan.research.model_study_reports import generate_report
from dayan.solvers.codec import digest
from test_model_diagnostics import evaluation,specs,refinement,rk4


def make(tmp_path,monkeypatch,diagnostics):
    c=evaluation(tmp_path,monkeypatch)
    result=create_study('明确的解析衰减数值夹具 不代表经验研究',c,param_grid={'rate':[-2.,-1.]},
        seeds=[7],selection_top=2,max_loss={role:1e-3 for role in ('training','validation','holdout')},
        diagnostics=diagnostics)
    return c,result['study_id']


def test_report_uses_actual_trials_graph_data_originals_and_unchanged_protocol(tmp_path,monkeypatch):
    c,sid=make(tmp_path,monkeypatch,specs())
    with pytest.raises(ValueError,match='尚未完成'):generate_report(sid)
    assert advance_study(sid,max_evaluations=20)['conclusion']=='passed_declared_checks'
    receipt=generate_report(sid)
    folder=Path(receipt['path']).parent
    assert receipt['figure_count']==6
    doc=Document(receipt['path'])
    text='\n'.join(p.text for p in doc.paragraphs)
    assert doc.paragraphs[0].style.name=='Title'
    assert len(doc.inline_shapes)==6 and '通过本协议声明的有限检查' in text
    assert '未通过' not in text and '不代表经验研究' in text
    assert '按事前确定性协议完成单次求值' in text
    assert '重复数量不足或有失败' not in text
    assert len(doc.element.xpath('//m:oMath'))>=3
    assert len(doc.element.xpath('//m:sSub'))>=12  # archived RK4 indices use real editable subscripts
    facts=json.loads((folder/'research.facts.json').read_text(encoding='utf-8'))
    assert digest({k:v for k,v in facts.items() if k not in ('evidence_sha256','figures','presentation')})==facts['evidence_sha256']
    assert facts['protocol']['sha256']==receipt['protocol_sha256']
    assert facts['summary']['study_id']==sid
    assert facts['state']['selection']['parameters']=={'rate':-1.}
    assert facts['presentation']['actual_parameters']['values']['rate']==-1.
    analysis=facts['presentation']['analysis']
    assert {row['role'] for row in analysis['residuals']}=={'training','validation','holdout'}
    for row in analysis['residuals']:
        actual=[point for point in facts['selected_predictions'] if point['role']==row['role']]
        residuals=[point['predicted']-point['value'] for point in actual]
        assert row['mean_error']==pytest.approx(sum(residuals)/len(residuals),abs=1e-14)
        assert row['rmse']==pytest.approx((sum(r*r for r in residuals)/len(residuals))**.5,abs=1e-14)
    evaluations=next(table for table in doc.tables if table.rows[0].cells[0].text=='候选')
    assert len(evaluations.rows)==len(facts['trials'])+1
    for row,trial in zip(evaluations.rows[1:],facts['trials']):
        assert row.cells[0].text==str(trial['candidate']) and row.cells[3].text==str(trial['seed'])
        assert str(trial['receipt']['parameters']['rate']) in row.cells[1].text or 'rate = '+format(trial['receipt']['parameters']['rate'],'.10g')==row.cells[1].text
    assert text.index('主要发现')<text.index('建模方案与实际数学规则')<text.index('附录 原始研究需求全文')
    assert doc.paragraphs[-1].text==facts['protocol']['question']
    assert '偏差均值' in text and '原始研究需求全文保留在附录' in text
    for point in facts['selected_predictions']:
        assert point['predicted']==pytest.approx(rk4(-1,.5,point['time']),abs=1e-12)
    assert {p['role'] for p in facts['selected_predictions']}=={'training','validation','holdout'}
    for fig in facts['figures']:
        assert digest(fig['data'])==fig['data_sha256']
        assert (folder/fig['file']).stat().st_size>1000
    with (folder/'predictions.csv').open(encoding='utf-8-sig') as handle:
        points=list(csv.DictReader(handle))
    assert len(points)==3 and float(points[-1]['predicted'])==pytest.approx(rk4(-1,.5,2))
    with ZipFile(folder/'reproducibility.zip') as pack:
        assert json.loads(pack.read('protocol.json'))==facts['protocol']
        data_id=c['targets']['bindings'][0]['dataset_id']
        from dayan import datasets
        assert pack.read('datasets/'+data_id+'/original')==(datasets.dataset_dir()/data_id/'original').read_bytes()
        assert sum(name.endswith('/manifest.json') for name in pack.namelist())==10
        assert all(not any(secret in name.lower() for secret in ('config.json','profile.patch','token','api_key')) for name in pack.namelist())
    for name,sha in receipt['files'].items():assert hashlib.sha256((folder/name).read_bytes()).hexdigest()==sha
    assert generate_report(sid)==receipt
    (folder/'predictions.csv').write_text('fabricated',encoding='utf-8')
    with pytest.raises(ValueError,match='哈希不一致'):generate_report(sid)


def test_runtime_text_presentation_rechecks_actual_frozen_single_record_source(tmp_path,monkeypatch):
    """Real DS/parser hashes; this controlled text fixture is not a model run."""
    from dayan import datasets
    from dayan.structured_inputs import prepare_structured
    from dayan.research.model_study_reports import _runtime_text_inputs
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    body=[{'definition':'明确测试字典：计量的是期末库存，不是累计流量。','origin':'controlled test dictionary'}]
    record=datasets.ingest(json.dumps(body,ensure_ascii=False).encode(),name='明确测试字典',
        format='json',source='test-runtime-text-evidence')
    contract={'kind':'records','purpose':'mechanism_estimation','primary_key':['definition'],
        'fields':{name:{'type':'string','unit':'1'} for name in body[0]}}
    binding={'dataset_id':record['dataset_id'],'port':'dictionary','contract':contract,
        'columns':{name:{'field':name,'source_unit':'1'} for name in body[0]}}
    _,frozen=prepare_structured([binding],{'dictionary':contract})
    result=_runtime_text_inputs({'input_evidence':frozen})
    assert result[0]['fields']['definition']=={'text':body[0]['definition'],'source_field':'definition'}
    assert result[0]['sha256']==record['sha256'] and result[0]['source_row_index']==0
    changed=deepcopy(frozen);changed[0]['input_sha256']='0'*64
    with pytest.raises(ValueError,match='实际研究版本不一致'):
        _runtime_text_inputs({'input_evidence':changed})
    original=datasets.dataset_dir()/record['dataset_id']/'original'
    saved=original.read_bytes()
    try:
        original.write_bytes(b'changed source bytes')
        with pytest.raises(ValueError,match='原始文件哈希'):
            _runtime_text_inputs({'input_evidence':frozen})
    finally:
        original.write_bytes(saved)


def test_legacy_summary_compatibility_keeps_all_scientific_evidence_in_identity():
    """Controlled summary migration; no fabricated simulation result is used."""
    from dayan.research.model_diagnostics import LEGACY_COMPARISON_RULE,CURRENT_COMPARISON_RULE
    from dayan.research.model_study_reports import _compatible_evidence_ids
    scope='已事前声明，完整试验和比较保存在同研究diagnostics目录'
    old={'protocol':{'param_grid':{'rate':[-1.,0.]}},
         'summary':{'diagnostic_scope':scope},'trials':[{'sha256':'controlled-receipt-anchor'}]}
    archived=digest(old)
    current=deepcopy(old)
    current['summary'].update(diagnostic_comparison_rule=LEGACY_COMPARISON_RULE,
        diagnostic_scope=scope+'；历史旧规则仅以最细档对基线判定，不能证明中间细化档通过；原记录保留，未冒充新版检查')
    current['evidence_sha256']=digest(current)
    assert archived in _compatible_evidence_ids(current)
    for key,value in [('param_grid',{'rate':[-2.,0.]}),('diagnostic_comparison_rule',CURRENT_COMPARISON_RULE)]:
        changed=deepcopy(current);changed['protocol'][key]=value
        assert archived not in _compatible_evidence_ids(changed)
    changed=deepcopy(current);changed['trials'][0]['sha256']='changed-real-evidence-anchor'
    assert archived not in _compatible_evidence_ids(changed)


def test_failed_refinement_report_does_not_score_or_plot_holdout(tmp_path,monkeypatch):
    c,sid=make(tmp_path,monkeypatch,[refinement(0.)])
    assert advance_study(sid,max_evaluations=20)['conclusion']=='failed_predeclared_diagnostics'
    receipt=generate_report(sid)
    folder=Path(receipt['path']).parent
    text='\n'.join(p.text for p in Document(receipt['path']).paragraphs)
    assert '未通过事前数值诊断' in text and '留出未评分' in text
    assert '通过本协议声明的有限检查' not in text
    facts=json.loads((folder/'research.facts.json').read_text(encoding='utf-8'))
    assert facts['state']['holdout'] is None and 'exposure' not in facts['state']
    assert all(row['role']!='holdout' for row in facts['presentation']['analysis']['residuals'])
    assert '留出尚未评分，不能据其评价这一选择' in text
    assert all(p['role']!='holdout' for p in facts['selected_predictions'])
    assert all(p['role']!='holdout' for fig in facts['figures'] if fig['kind']=='observed_and_predicted' for p in fig['data'])
    assert receipt['figure_count']==4


def test_descriptive_residual_statistics_keep_replicates_and_unique_targets_distinct():
    """Small, explicitly labelled arithmetic fixture; not a simulated study claim."""
    from dayan.research.model_study_reports import _descriptive_analysis
    points=[]
    for seed,error in [(7,1.),(11,3.)]:
        for time,residual in [(0.,0.),(1.,error)]:
            points.append({'observable':'stock','role':'training','unit':'件','seed':seed,
                'binding_id':'arithmetic_fixture','series':{},'time':time,'value':10.,'predicted':10.+residual,
                'residual_predicted_minus_observed':residual,'provenance':{'content_cell':str(time)}})
    facts={'protocol':{'evaluation':{'model':{'observables':{'stock':{'unit':'件'}}}}},
           'selected_predictions':points,'result_run':None,'diagnostics':None}
    row=_descriptive_analysis(facts)['residuals'][0]
    assert row['observation_count']==2 and row['actual_point_count']==4 and row['seeds']==[7,11]
    assert row['mean_error']==1. and row['mae']==1. and row['rmse']==pytest.approx(2.5**.5)
    assert row['positive']==2 and row['negative']==0 and row['zero']==2
    assert row['max_abs_error']==3. and row['max_error_time']==1. and row['max_error_seed']==11


def test_actual_research_tools_native_scope_and_versioned_download_api(tmp_path,monkeypatch):
    from dayan.agent.data_tools import research_calibrate,research_report,research_status
    from dayan.agent.tools import TOOL_SPECS
    from dayan.research.native_contract import protect
    from dayan.server import app
    from api_client import local_client
    c,sid=make(tmp_path,monkeypatch,[])
    spec=next(s for s in TOOL_SPECS if s['name']=='research_calibrate')
    assert spec['parameters']['properties']['max_evaluations']['type']=='integer'
    one=research_calibrate(sid)
    assert one['ok'] and not one['validation_pass'] and one['payload']['status']=='running'
    assert one['payload']['next_action']=={'action':'research_calibrate','arguments':{'study_id':sid,'max_evaluations':1}}
    with pytest.raises(ValueError,match='不属于本次原始需求'):
        protect('research_calibrate',{'study_id':sid},'另一个完全不同的研究问题','different-session')
    question='明确的解析衰减数值夹具 不代表经验研究'
    assert protect('research_report',{'study_id':sid},question,'same-session')=={'study_id':sid}
    done=research_calibrate(sid,max_evaluations=10)
    assert done['ok'] and done['validation_pass']
    assert research_status(sid)['payload']['selection']['parameters']=={'rate':-1.}
    assert any(s['study_id']==sid for s in research_status()['payload'])
    result=research_report(sid)
    assert result['ok'],result
    receipt=result['payload']
    client=local_client(app)
    details=client.get('/api/research/studies/'+sid)
    assert details.status_code==200,details.text
    assert details.json()['reports'][0]['report_id']==receipt['report_id']
    assert details.json()['reports'][0]['current_renderer'] is True
    assert details.json()['reports'][0]['created_at']==receipt['created_at']
    assert client.get(receipt['file']).content==Path(receipt['path']).read_bytes()
    assert client.get(receipt['facts_url']).json()['study_id']==sid
    assert client.get(receipt['bundle_url']).content==Path(receipt['path']).with_name('reproducibility.zip').read_bytes()
    prefix=receipt['file'].rsplit('/',1)[0]+'/'
    assert client.get(prefix+'receipt.json').status_code==400
    other=receipt['file'].replace(receipt['report_id'],'MR-'+'0'*24)
    assert client.get(other).status_code==400
    Path(receipt['path']).write_bytes(b'changed word document')
    assert client.get(receipt['file']).status_code==400
    details=client.get('/api/research/studies/'+sid).json()
    assert details['reports'][0]['status']=='integrity_failed'
    assert 'file' not in details['reports'][0]
