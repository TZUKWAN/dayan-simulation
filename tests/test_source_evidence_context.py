"""Actual append-only state/version contracts, no model execution claimed."""
from copy import deepcopy
import hashlib

import pytest

from dayan.research import model_intents as intents
from test_model_research_intent import arguments
from test_source_evidence import source,binding


def test_evidence_append_keeps_scientific_protocol_and_rejects_foreign_or_forged_changes(tmp_path,monkeypatch):
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    args=arguments()
    prepared=intents.prepare_intent(**args,session_id='evidence-owner')
    ident=prepared['research_intent_id']
    protocol_path=intents.directory(ident)/'protocol.json'
    original=protocol_path.read_bytes()
    data=source();ref=binding(data)
    with pytest.raises(ValueError,match='原文或会话'):
        intents.attach_source_evidence(ident,[ref],args['question'],'other-owner')
    with pytest.raises(ValueError,match='原文或会话'):
        intents.attach_source_evidence(ident,[ref],'different question','evidence-owner')
    first=intents.attach_source_evidence(ident,[ref],args['question'],'evidence-owner')
    assert first['source_evidence_count']==1 and first['next_action']['arguments']['research_intent_id']==ident
    first_context=intents.source_context(intents.load_intent(ident))
    assert intents.attach_source_evidence(ident,[ref],args['question'],'evidence-owner')==first
    second_ref={**ref,'id':'other_actual_field','fields':{'quoted_note':'/a~1b/~0note'}}
    second=intents.attach_source_evidence(ident,[second_ref],args['question'],'evidence-owner')
    assert second['source_evidence_count']==2 and second['context_revision']==2
    assert protocol_path.read_bytes()==original
    record=intents.load_intent(ident)
    current=intents.source_context(record)
    assert current['bindings']==[ref,second_ref]
    base={'research':{'research_intent_id':ident,'source_evidence':first_context},'dt':.5,'parameters':{'flow':1}}
    after=deepcopy(base);after['research']['source_evidence']=current
    allowed=intents.authorize_context_extension(base,after,args['question'],'evidence-owner')
    assert allowed['source_evidence_id']==second['source_evidence_id']
    changed=deepcopy(after);changed['dt']=1.
    with pytest.raises(ValueError,match='执行设置只能追加'):
        intents.authorize_context_extension(base,changed,args['question'],'evidence-owner')
    forged=deepcopy(after);forged['research']['source_evidence']['records'][0]['basis']='forged'
    with pytest.raises(ValueError,match='实际已保存'):
        intents.authorize_context_extension(base,forged,args['question'],'evidence-owner')
    with pytest.raises(ValueError,match='不能替换'):
        intents.attach_source_evidence(ident,[{**ref,'basis':'replace the old claim'}],args['question'],'evidence-owner')
    assert intents.source_context(record)==current and protocol_path.read_bytes()==original


def test_lost_state_write_recovers_same_immutable_evidence_version(tmp_path,monkeypatch):
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    args=arguments();ident=intents.prepare_intent(**args)['research_intent_id']
    ref=binding(source())
    original_write=intents._write
    stopped=[]
    def interrupt(path,value):
        if value.get('source_evidence_id') and not stopped:
            stopped.append(True)
            raise OSError('explicit test interruption after real evidence version publish')
        return original_write(path,value)
    monkeypatch.setattr(intents,'_write',interrupt)
    with pytest.raises(OSError,match='explicit test interruption'):
        intents.attach_source_evidence(ident,[ref],args['question'])
    versions=list((intents.directory(ident)/'source_evidence').glob('*.json'))
    assert len(versions)==1 and 'source_evidence_id' not in intents.load_intent(ident)['state']
    before=hashlib.sha256(versions[0].read_bytes()).hexdigest()
    recovered=intents.attach_source_evidence(ident,[ref],args['question'])
    assert recovered['source_evidence_count']==1
    assert hashlib.sha256(versions[0].read_bytes()).hexdigest()==before
    assert not (tmp_path/'model_designs').exists() and not (tmp_path/'research_runs').exists()
