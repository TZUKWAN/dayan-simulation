"""Controlled review provider, actual HTTP/state/model/study/report/source files.

This is a labelled mathematical integration fixture, not a genuine native Agent
or an empirical source claim. Native and official-metadata checks are separate.
"""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from docx import Document
import jsonschema

from dayan.agent import model_tools,model_design
from dayan.research.model_intents import load_intent,directory
from dayan.run_store import get_store
from test_design_continuation import provider
import test_model_research_intent as intent_fixture
from test_source_evidence import source,binding


def test_same_native_intent_adds_background_text_then_reviews_runs_and_archives_real_evidence(provider,monkeypatch):
    from dayan.server import app
    from dayan.agent.tools import TOOL_SPECS
    from dayan import llm_client,datasets
    from dayan.research.model_studies import load_study
    from api_client import local_client
    question=intent_fixture.QUESTION+'另须引用实际来源字典的库存单位定义和原件哈希。'
    monkeypatch.setattr(intent_fixture,'QUESTION',question)
    intent_fixture.configure_provider(provider,monkeypatch)
    monkeypatch.setenv('DAYAN_TASK_WORKER','1')
    data=source();ref=binding(data)
    expected=datasets.load(data['dataset_id'])['data']['definition']
    original=model_design.complete
    def complete(messages,**kwargs):
        response=json.loads(original(messages,**kwargs))
        sent=json.loads(messages[1]['content'])
        purpose=kwargs['purpose']
        if purpose=='model-design-plan':
            for row in response['coverage']:
                quote=model_design._requirement_index(question)[row['requirement_id']]
                if '来源字典' in quote:
                    row.update(role='input',criteria=[],implementation='核对execution.research.source_evidence实际DS/字段原文和hash',
                               test='已保存来源文字确为引用的原字段，原件/hash进入同研究报告与复核包')
        if purpose=='model-design-review':
            context=sent['execution']['research'].get('source_evidence')
            if not context:
                response.update(approved=False,issues=['原话要求来源字典，当前执行合同没有已核验的来源原文/字段/hash'])
                for row in response['checks']:
                    if '来源字典' in model_design._requirement_index(question)[row['requirement_id']]:row['verdict']='gap'
            else:
                assert context['records'][0]['fields']['definition']['text']==expected
                assert context['records'][0]['dataset_id']==data['dataset_id']
        if purpose=='model-design-revision' and sent.get('implementation_feedback'):
            response['resolutions']=[{'id':row['id'],'change':'核对追加的实际来源证据原字段/hash，保持原模型与完整研究协议',
                                     'status':'resolved'} for row in sent['critique']]
        return json.dumps(response,ensure_ascii=False)
    for module in (model_tools,model_design,llm_client):monkeypatch.setattr(module,'complete',complete)
    client=local_client(app)
    owner='source-native-owner'
    def call(tool,args,session=owner,original_text=question):
        response=client.post('/api/tools/'+tool,json={'origin':'dsh','session_id':session,
            'original_text':original_text,'arguments':args})
        assert response.status_code==200,response.text
        return response.json()
    args=intent_fixture.arguments()
    prepared=call('research_model_prepare',args)
    assert prepared['ok'],prepared
    ident=prepared['payload']['research_intent_id']
    original_protocol=(directory(ident)/'protocol.json').read_bytes()
    action=prepared['payload']['next_action']
    denied=call(action['action'],action['arguments'])
    assert not denied['ok'] and denied['payload']['status']=='blocked',denied
    parent=model_design.load_design(denied['design_id'])
    context_args={'research_intent_id':ident,'evidence':[ref]}
    spec=next(row for row in TOOL_SPECS if row['name']=='research_model_context')
    jsonschema.validate(context_args,spec['parameters'])
    assert not call('research_model_context',context_args,session='other-owner')['ok']
    assert not call('research_model_context',context_args,original_text='换成另一个问题')['ok']
    unknown=call('research_model_context',{**context_args,'question':'伪造上下文绑定'})
    assert not unknown['ok'] and '字段' in unknown['error']
    attached=call('research_model_context',context_args)
    assert attached['ok'] and not attached['validation_pass'],attached
    context_id=attached['payload']['source_evidence_id']
    assert attached['payload']['next_action']['arguments']['revise_from']==parent['design_id']
    assert attached['payload']['next_action']['arguments']['research_intent_id']==ident
    assert call('research_model_context',context_args)['payload']==attached['payload']
    assert (directory(ident)/'protocol.json').read_bytes()==original_protocol
    premature=call('build_model',{'design_id':parent['design_id'],'research_intent_id':ident})
    assert not premature['ok'] and premature['payload']['next_action']==attached['payload']['next_action'],premature
    action=attached['payload']['next_action']
    corrected=call(action['action'],action['arguments'])
    assert corrected['ok'] and corrected['payload']['status']=='approved',corrected
    child=corrected['payload']
    assert child['revision_of']==parent['design_id']
    assert child['implementation_feedback']['source_context_extension']['source_evidence_id']==context_id
    assert model_design.load_design(parent['design_id'])==parent
    assert child['execution']['research']['source_evidence']['records'][0]['fields']['definition']['text']==expected
    attempted_extra={'research_intent_id':ident,'evidence':[{**ref,'id':'another_definition'}]}
    reject_approved=call('research_model_context',attempted_extra)
    assert not reject_approved['ok'] and '已批准' in reject_approved['error'],reject_approved
    action=child['next_action']
    baseline=call(action['action'],action['arguments'])
    assert baseline['ok'] and baseline['payload']['status']=='research_pending',baseline
    rid=baseline['payload']['run_id'];sid=baseline['payload']['study_id']
    assert get_store().load(rid)['observations'][-1]['stock']==12.
    study=load_study(sid)
    assert study['protocol']['baseline']['source_evidence']['sha256']==context_id
    assert not study['protocol']['evaluation']['execution']['data_bindings']  # text did not become a numeric input
    reject_running=call('research_model_context',attempted_extra)
    assert not reject_running['ok'] and '已运行' in reject_running['error'],reject_running
    action=baseline['payload']['next_action']
    for _ in range(8):
        result=call(action['action'],action['arguments'])
        assert result['ok'],result
        action=result['payload']['next_action']
        if action['action']=='research_finalize':break
    assert result['payload']['selection']['parameters']=={'flow':2.} and result['payload']['holdout']['loss']==0.
    final=call(action['action'],action['arguments'])
    assert final['ok'],final
    selected=final['payload']['run_id']
    assert get_store().load(selected)['observations'][-1]['stock']==14.
    action=final['payload']['next_action']
    report=call(action['action'],action['arguments'])
    assert report['ok'] and report['payload']['request_complete'],report
    folder=Path(report['payload']['path']).parent
    text='\n'.join(p.text for p in Document(folder/'research.docx').paragraphs)
    assert expected in text and '来源文字证据与计量口径' in text
    facts=json.loads((folder/'research.facts.json').read_text(encoding='utf-8'))
    attached_file=json.loads((folder/'source_evidence.json').read_text(encoding='utf-8'))
    assert attached_file==facts['source_evidence'] and attached_file['sha256']==context_id
    assert facts['result_run']['run_id']==selected
    with ZipFile(folder/'reproducibility.zip') as archive:
        assert archive.read('datasets/'+data['dataset_id']+'/original')==(datasets.dataset_dir()/data['dataset_id']/'original').read_bytes()
        assert json.loads(archive.read('reports/source_evidence.json'))==attached_file
        assert json.loads(archive.read('protocol.json'))['baseline']['source_evidence']==attached_file
    delivery=child['execution']['delivery']['research']
    url=delivery['file_url'].format(study_id=sid,report_id=report['payload']['report_id'],filename='source_evidence.json')
    assert client.get(url).json()==attached_file
    indexed=client.get(delivery['study_url'].format(study_id=sid)).json()['reports']
    entry=next(row for row in indexed if row['report_id']==report['payload']['report_id'])
    assert entry['files']['source_evidence.json']==hashlib.sha256(client.get(url).content).hexdigest()
    assert load_intent(ident)['state']['source_evidence_id']==context_id
    assert (directory(ident)/'protocol.json').read_bytes()==original_protocol
    original_path=datasets.dataset_dir()/data['dataset_id']/'original'
    original_bytes=original_path.read_bytes()
    try:
        original_path.write_bytes(b'explicit test tamper')
        damaged=call('research_report',{'study_id':sid})
        assert not damaged['ok'] and '哈希' in damaged['error'],damaged
    finally:
        original_path.write_bytes(original_bytes)
