"""Real container executions with controlled inputs, not native or empirical studies."""
from copy import deepcopy
import json
import time

import pytest

from dayan import datasets
from dayan.custom_models import register, validate_definition
from dayan.program_models import population_plan
from dayan.runtime import run_model_full, resume_from_checkpoint
from dayan.run_progress import RunProgress, RunPaused
from dayan.solvers.codec import digest
from dayan.solvers.sandbox import SolverError
from test_solver_sandbox import LIVE
from test_structured_inputs import dataset, edge_binding


SOURCE = '''
def initialize(parameters, inputs, rng):
    people=inputs["people"]["columns"]
    return {"ids":people["id"].copy(),"exposure":people["initial"].copy()}
def advance(state, parameters, inputs, rng, time, dt):
    contacts=inputs["contacts"]["columns"]
    index={key:i for i,key in enumerate(state["ids"])}
    for start,source,target in zip(contacts["at"],contacts["source"],contacts["target"]):
        overlap=max(0,min(time+dt,start+20)-max(time,start))
        for person in (source,target):
            state["exposure"][index[person]]+=overlap
    return {"state":state,"events":[]}
def observe(state, parameters, inputs, time):
    return {"exposure_total":sum(state["exposure"]),"persons":len(state["ids"])}
def frame(state, parameters, inputs, time):
    contacts=inputs["contacts"]["columns"]
    return {"populations":[{"id":"people","type":"person","ids":state["ids"],
        "columns":{"exposure":state["exposure"]},"units":{"exposure":"second"}}],
        "relations":[{"id":str(i),"source":"people:"+source,"target":"people:"+target,
                      "valid_from":start,"valid_until":start+20}
            for i,(start,source,target) in enumerate(zip(contacts["at"],contacts["source"],contacts["target"]))
            if start<=time<start+20]}
def validate(state, parameters, inputs, time):
    if any(value<0 for value in state["exposure"]):raise ValueError("negative exposure")
'''


def bindings(perturbed=False):
    people={'dataset_id':dataset([{'id':'001','initial':'0'},
        {'id':'002','initial':'17' if perturbed else '10'}, {'id':'003','initial':'100'}]),
        'port':'people','contract':{'kind':'records','purpose':'initialization','primary_key':['id'],
            'fields':{'id':{'type':'string','unit':'1'},'initial':{'type':'number','unit':'second'}}},
        'columns':{'id':{'field':'id'},'initial':{'field':'initial','source_unit':'second'}}}
    contacts=edge_binding(dataset([{'time':'0','source':'001','target':'003' if perturbed else '002'},
                                   {'time':'20','source':'002','target':'003'}]))
    return [people,contacts]


def definition(bindings):
    return {'kind':'program','name':'逐记录接触累积数值检查','description':'协议夹具，完整行与关系输入扰动验算',
        'time_unit':'second','parameters':{},'input_ports':{b['port']:b['contract'] for b in bindings},
        'source':SOURCE,'solver':{'method':'精确区间交集','description':'逐边累加半开20秒区间交集'},
        'observables':{'exposure_total':{'label':'累计接触人秒','unit':'second','equation':'sum(exposure_i)'},
                       'persons':{'label':'人数','unit':'person','equation':'len(ids)'}},
        'populations':[{'id':'people','label':'匿名人员','type':'person','count':{'input_port':'people'},
            'dynamic':False,'attributes':{'exposure':{'kind':'numeric','unit':'second'}}}],
        'equations':[{'id':'exposure','function':'advance','expression':'E_i += sum_e 1(i in e) * |e intersect [t,t+dt)|',
                      'meaning':'区间交集秒数累加，初值来自同一人员记录'}],
        'mechanisms':['实际关系端点及区间接触累计'],'assumptions':['协议测试规定20秒接触窗口'],
        'limitations':['不模拟传染机制或估计疾病风险']}


def test_input_count_contract_is_bound_before_execution_and_old_model_ids_remain_valid(tmp_path, monkeypatch):
    from test_program_runtime import definition as old_definition
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    data=bindings()
    d=validate_definition(definition(data))
    with pytest.raises(ValueError,match='绑定真实输入'):
        population_plan(d)
    assert population_plan(d,allow_unbound=True)['entities'] is None
    old=register(old_definition())
    assert 'input_ports' not in old['definition']
    mid=register(d)['model_id']
    with pytest.raises(ValueError,match='input_ports'):
        run_model_full(mid,ticks=2,dt=20)
    assert not (tmp_path/'solver_jobs').exists()


def test_agent_preflight_enforces_actual_input_ports_and_exposes_contract(tmp_path, monkeypatch):
    from dayan.agent.model_tools import validate_model
    from dayan.agent.tools import TOOL_SPECS
    from dayan.agent.model_design import _equation_refs
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    data=bindings()
    d=definition(data)
    result=validate_model(d,data_bindings=data,ticks=2,dt=20)
    assert result['ok'],result
    assert result['payload']['execution_scale']['entities']==3
    missing=deepcopy(d)
    missing.pop('input_ports')
    missing['populations'][0]['count']=3
    result=validate_model(missing,data_bindings=data,ticks=2,dt=20)
    assert not result['ok'] and 'input_ports' in result['error']
    changed=deepcopy(d)
    changed['input_ports']['people']['fields']['initial']['unit']='minute'
    result=validate_model(changed,data_bindings=data,ticks=2,dt=20)
    assert not result['ok']
    assert 'input_ports.people.fields.initial.unit' in result['error']
    assert '"expected": "second"' in result['error'] and '"actual": "minute"' in result['error']
    assert '不要修改已绑定的data_bindings' in result['error']
    assert data[0]['contract']['fields']['initial']['unit']=='second'
    spec=next(s for s in TOOL_SPECS if s['name']=='build_model')
    schema=spec['parameters']['properties']['data_bindings']['items']
    import jsonschema
    for binding in data:
        jsonschema.validate(binding,schema)
    invalid=deepcopy(data[0])
    invalid['columns']['initial']['execute']='forbidden'
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(invalid,schema)
    assert 'inputs[端口]' in spec['instructions'] and 'count={input_port:' in spec['instructions']
    _equation_refs([{'mechanism':'真实接触驱动','paths':['source.advance','input_ports.contacts','execution.structured_inputs']}],kind='program')


def test_native_population_count_is_not_an_invented_parameter_requirement(tmp_path,monkeypatch):
    from dayan.agent.model_tools import call_native_model
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    data=bindings()
    args={'definition':definition(data),'data_bindings':data,'ticks':2,'dt':20,'seed':7}
    source='实际使用全部3人，每步保留完整状态，运行2步，步长20。'
    result=call_native_model('validate_model',args,source,'population-port-preflight')
    assert result['ok'],result
    assert result['payload']['execution_scale']['entities']==3
    assert result['payload']['execution']['parameters']=={}
    wrong=call_native_model('validate_model',args,source.replace('3人','4人'),'population-port-preflight')
    assert not wrong['ok'] and '4' in wrong['error']
    named=call_native_model('validate_model',args,source+'参数n=3。','population-port-preflight')
    assert not named['ok'] and '同名参数：n' in named['error']
    reserved=deepcopy(args)
    reserved['definition']['populations'][0]['attributes']['id']={'kind':'numeric','unit':'1'}
    bad=call_native_model('validate_model',reserved,source,'population-port-preflight')
    assert not bad['ok'] and 'attributes.id' in bad['error'] and '保留字段' in bad['error']


def test_guide_routes_known_public_files_and_unknown_connector_is_repairable():
    from dayan.agent.tools import call_tool, TOOL_SPECS
    from dayan.collection.connectors import CONNECTORS
    guide=call_tool('modeling_guide',request='请采集真实接触数据https://example.org/contacts.dat.zip用于时变网络')['payload']
    assert 'collect_data' in guide['next_tools']['data']
    assert any(tool['name']=='collect_data' for tool in guide['tool_contracts'])
    route=guide['data_routes']['known_public_file']
    assert route['schema']=={'action':'schema','tool':'collect_data'}
    schema=next(s for s in TOOL_SPECS if s['name']=='collect_source')['parameters']
    assert schema['properties']['connector']['enum']==sorted(CONNECTORS)
    # No network or scripted response: invalid connector validation occurs before
    # any collection job. The remedy points to a real, discoverable tool.
    error=call_tool('collect_source',connector='http',params={'url':'https://example.org/file.csv'})
    assert not error['ok'] and error['error_code']=='unknown_connector'
    assert error['next_action']=={'action':'schema','tool':'collect_data'}
    assert 'resource_file' in error['available_connectors']


@LIVE
def test_certification_checks_mixed_scalar_ports_originals_and_actual_snapshots(tmp_path,monkeypatch):
    from dayan.agent.verification import verify_execution, certify_run, RunVerificationError
    from dayan.structured_inputs import prepare_bindings
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path/'data'))
    data=bindings()
    d=definition(data)
    d['parameters']={'gain':{'type':'float','default':1.,'minimum':0.,'maximum':3.,'unit':'1'}}
    d['source']=d['source'].replace('people["initial"].copy()',
        '[value*parameters["gain"] for value in people["initial"]]')
    data.append({'dataset_id':dataset([{'gain':2.}]),'field':'gain','parameter':'gain',
                 'source_unit':'1','target_unit':'1'})
    mid=register(d)['model_id']
    params,ports,evidence=prepare_bindings(data,mid,d['input_ports'])
    execution={'ticks':2,'dt':20,'seed':7,'parameters':params,'data_bindings':evidence,
        'structured_inputs':{name:{'contract':asset['contract'],'count':asset['count']}
                             for name,asset in ports.items()}}
    run=run_model_full(mid,data_bindings=data,ticks=2,dt=20,seed=7,capture_state=True,full_frames=True)
    assert [row['exposure_total'] for row in run.observations]==[220,260,300]
    acceptance={'execution':execution,'criteria':[],'observables':['exposure_total','persons'],
                'spatial':False,'events':{}}
    certify_run(run,{'scope':'actual numerical fixture; not native or empirical'},acceptance)
    receipt=run.manifest['scenario_review']['runtime_checks']['verification']
    assert receipt['status']=='passed' and receipt['bindings_checked']==3
    assert [row['status'] for row in receipt['structured_data_audit']]==['recomputed']*2
    for mutation in ('missing_port','duplicate_port','changed_mapping','changed_clock','missing_snapshot',
                     'changed_rows','changed_summary','unexecuted_port','changed_scalar'):
        bad=deepcopy(run)
        item=next(b for b in bad.manifest['data_bindings'] if b.get('port')=='contacts')
        if mutation=='missing_port':bad.manifest['data_bindings'].remove(item)
        elif mutation=='duplicate_port':bad.manifest['data_bindings'].append(deepcopy(item))
        elif mutation=='changed_mapping':item['columns']['at']['offset']=20
        elif mutation=='changed_clock':item['contract']['clock']['anchor']='end'
        elif mutation=='missing_snapshot':bad.checkpoint=None
        elif mutation=='changed_rows':bad.checkpoint['inputs']['contacts']['source_row_indices'].reverse()
        elif mutation=='changed_summary':bad.manifest['structured_inputs']['ports']['contacts']['records']=1
        elif mutation=='unexecuted_port':item['usage_status']='prepared_not_yet_executed'
        elif mutation=='changed_scalar':bad.manifest['actual']['effective_parameters']['gain']=1.
        checked=verify_execution(bad,execution,[])
        assert checked['status']=='failed',(mutation,checked)
        with pytest.raises(RunVerificationError):certify_run(bad,{},acceptance)
    # Even a self-consistently resealed forged snapshot must disagree with the
    # actual originals. Do not accept a hash supplied by the result itself.
    bad=deepcopy(run)
    bad.checkpoint['inputs']['people']['columns']['initial'][0]=999
    bad.checkpoint['checkpoint_sha256']=digest({k:v for k,v in bad.checkpoint.items() if k!='checkpoint_sha256'})
    bad.manifest['structured_inputs']['sha256']=digest(bad.checkpoint['inputs'])
    forged=next(b for b in bad.manifest['data_bindings'] if b.get('port')=='people')
    forged['input_sha256']=digest(bad.checkpoint['inputs']['people'])
    bad.manifest['structured_inputs']['ports']['people']['sha256']=forged['input_sha256']
    assert verify_execution(bad,execution,[])['status']=='failed'
    # Missing originals are a delivery verification failure, not a successful
    # certification with a degraded footnote.
    (datasets.dataset_dir()/data[0]['dataset_id']/'original').rename(tmp_path/'missing-original')
    checked=verify_execution(run,execution,[])
    assert checked['status']=='failed'
    assert checked['structured_data_audit'][0]['status']=='snapshot_verified_source_unavailable'


@LIVE
def test_real_ports_control_states_and_relations_and_survive_recovery(tmp_path, monkeypatch):
    from dayan.population_groups import decode_attribute, group_ids
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path/'data'))
    data=bindings()
    mid=register(definition(data))['model_id']
    options=dict(data_bindings=data,ticks=2,dt=20,seed=7,capture_state=True,full_frames=True,checkpoint_at=1)
    full=run_model_full(mid,**options)
    assert [row['exposure_total'] for row in full.observations]==[110,150,190]
    assert full.manifest['actual']['entities']==3
    group=full.state_frames[-1]['population']['groups'][0]
    assert list(group_ids(group))==['001','002','003']
    assert list(decode_attribute(group['columns']['exposure'],group['count']))==[20,50,120]
    assert [len(frame['relations']) for frame in full.state_frames]==[1,1,0]
    assert full.state_frames[0]['relations'][0]['target']=='people:002'
    assert full.manifest['structured_inputs']['sha256']==digest(full.checkpoint['inputs'])
    assert full.checkpoint['inputs']['people']['columns']['initial']==[0,10,100]
    assert full.manifest['data_bindings'][0]['usage_status'].startswith('delivered_to_solver')
    changed=run_model_full(mid,**{**options,'data_bindings':bindings(True)})
    changed_group=changed.state_frames[-1]['population']['groups'][0]
    assert list(decode_attribute(changed_group['columns']['exposure'],changed_group['count']))==[20,37,140]
    assert changed.state_frames[0]['relations'][0]['target']=='people:003'
    assert changed.manifest['structured_inputs']['sha256']!=full.manifest['structured_inputs']['sha256']
    resumed=resume_from_checkpoint(full.checkpoint,steps=1,dt=20,capture_state=True)
    assert resumed.observations==full.observations[-1:]
    assert resumed.checkpoint['inputs']==full.checkpoint['inputs']
    class Pause(RunProgress):
        def should_pause(self):return self.record is not None
    with pytest.raises(RunPaused):
        run_model_full(mid,**options,_progress=Pause(tmp_path/'progress',time.monotonic()+600))
    restored=run_model_full(mid,**options,_progress=RunProgress(tmp_path/'progress',time.monotonic()+600))
    assert restored.observations==full.observations
    assert restored.checkpoint['solver_checkpoint']==full.checkpoint['solver_checkpoint']
    assert restored.checkpoint['inputs']==full.checkpoint['inputs']
    # The solver receives actual input rows but cannot silently mutate them.
    corrupt=definition(data)
    corrupt['source']=SOURCE.replace('contacts=inputs["contacts"]["columns"]',
        'inputs["people"]["columns"]["initial"][0]=999\n    contacts=inputs["contacts"]["columns"]',1)
    with pytest.raises(SolverError,match='只读'):
        run_model_full(register(corrupt)['model_id'],**options)
    # Durable evidence is deliberately labelled as a protocol/numerical case.
    from dayan.run_store import get_store
    rid=get_store().save_run(full,source='structured_protocol_numerical_case',request_text='协议输入数值验算，非Agent/非实证研究')
    assert get_store().load(rid)['checkpoint']['inputs']==full.checkpoint['inputs']


@LIVE
def test_end_timestamp_clock_drives_actual_state_frames_and_report(tmp_path,monkeypatch):
    from pathlib import Path
    from docx import Document
    from dayan.run_store import get_store
    from dayan.structured_inputs import structured_audit
    from dayan.agent.scenario_tools import report_run
    import dayan.report_gen as report_gen
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path/'data'))
    monkeypatch.setenv('DAYAN_REPORTS_DIR',str(tmp_path/'reports'))
    monkeypatch.setattr(report_gen,'REPORTS_DIR',tmp_path/'reports')
    data=bindings()
    data[1]['dataset_id']=dataset([{'time':'20','source':'001','target':'002'},
                                  {'time':'40','source':'002','target':'003'}])
    data[1]['contract']['clock']['anchor']='end'
    d=definition(data)
    d['source']=SOURCE.replace('contacts=inputs["contacts"]["columns"]','contacts=interval_columns(inputs)')+'''
def interval_columns(inputs):
    raw=inputs["contacts"]["columns"]
    clock=inputs["contacts"]["contract"]["clock"]
    shift=clock["interval"] if clock.get("anchor","start")=="end" else 0
    return {"at":[t-shift for t in raw["at"]],"source":raw["source"],"target":raw["target"]}
'''
    rr=run_model_full(register(d)['model_id'],ticks=2,dt=20,seed=7,data_bindings=data,
                      capture_state=True,full_frames=True)
    assert [row['exposure_total'] for row in rr.observations]==[110,150,190]
    assert [len(frame['relations']) for frame in rr.state_frames]==[1,1,0]
    assert rr.checkpoint['inputs']['contacts']['columns']['at']==[20,40]
    receipt=rr.manifest['data_bindings'][1]['time_summary']
    assert receipt['anchor']=='end' and receipt['first_start']==0 and receipt['last_end']==40
    assert all(item['status']=='recomputed' for item in structured_audit(rr.manifest,rr.checkpoint))
    rid=get_store().save_run(rr,source='end_timestamp_protocol_case',request_text='明确终点时钟的协议验算，非实证研究')
    report=report_run(rid,'exposure_total')
    assert report['ok'],report
    text='\n'.join(p.text for p in Document(Path(report['payload']['path'])).paragraphs)
    assert '按声明端点计算的输入时间范围' in text and '"anchor": "end"' in text


@LIVE
def test_actual_input_snapshots_originals_word_and_bundle_agree(tmp_path, monkeypatch):
    from pathlib import Path
    from zipfile import ZipFile
    from docx import Document
    from dayan.run_store import get_store
    from dayan.structured_inputs import structured_audit
    from dayan.agent.scenario_tools import report_run
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path/'data'))
    monkeypatch.setenv('DAYAN_REPORTS_DIR',str(tmp_path/'reports'))
    # report_gen has an import-time directory; keep this test isolated even if
    # another test imported it before this environment was set.
    import dayan.report_gen as report_gen
    monkeypatch.setattr(report_gen,'REPORTS_DIR',tmp_path/'reports')
    data=bindings()
    mid=register(definition(data))['model_id']
    rr=run_model_full(mid,ticks=2,dt=20,seed=7,data_bindings=data,capture_state=True,full_frames=True)
    rid=get_store().save_run(rr,source='structured_protocol_report_case',request_text='协议证据报告，非现实效度验收')
    audit=structured_audit(rr.manifest,rr.checkpoint)
    assert [row['status'] for row in audit]==['recomputed','recomputed']
    altered=deepcopy(rr.checkpoint)
    altered['inputs']['people']['columns']['initial'][0]=123
    assert all(row['status']=='mismatch' for row in structured_audit(rr.manifest,altered))
    report=report_run(rid,'exposure_total')
    assert report['ok'],report
    path=Path(report['payload']['path'])
    facts=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    assert facts['research_evidence']['structured_data_audit']==audit
    assert facts['manifest']['run_id']==rid
    document=Document(path)
    text='\n'.join(paragraph.text for paragraph in document.paragraphs)
    assert '结构输入端口 people' in text and '结构输入端口 contacts' in text
    assert '原文件、显式转换、完整输入快照及运行哈希已重新核对一致' in text
    assert all(b['dataset_id'] in text or b['dataset_id'] in '\n'.join(facts['content'].values()) for b in data)
    with ZipFile(get_store().prepare_bundle(rid)) as bundle:
        snapshot=json.loads(bundle.read(rid+'/checkpoint.json'))
        assert snapshot['inputs']==rr.checkpoint['inputs']
        for item in data:
            assert bundle.read('datasets/'+item['dataset_id']+'/original')==(
                datasets.dataset_dir()/item['dataset_id']/'original').read_bytes()
