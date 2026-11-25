"""Controlled provenance fixtures, not a native modelling or science acceptance."""
from copy import deepcopy
import json

import pytest

import native_research_selection as module


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


def fixture(data):
    ident, sid, report = ('MI-'+'1'*24, 'MS-'+'2'*24, 'MR-'+'3'*24)
    protocol = {'question': 'controlled original', 'session_id': 'session-fixture', 'sha256': 'sealed-fixture'}
    baseline = {'run_id': 'baseline-fixture', 'design_id': 'design-fixture',
                'manifest': {'scenario_review': {'research_intent': {
                    'research_intent_id': ident, 'protocol_sha256': protocol['sha256']}}}}
    state = {'research_intent_id': ident, 'study_id': sid, 'status': 'complete',
             'report_id': report, 'baseline_run_id': baseline['run_id'], 'design_id': baseline['design_id'],
             'result_run_id': 'selected-fixture'}
    write(data/'model_research_intents'/ident/'protocol.json', protocol)
    write(data/'model_research_intents'/ident/'state.json', state)
    write(data/'model_studies'/sid/'protocol.json', {'question': protocol['question'], 'baseline': baseline})
    write(data/'model_studies'/sid/'state.json', {'study_id': sid, 'selected_run': {'run_id': 'selected-fixture'}})
    event = {'seq': 8, 'session_id': protocol['session_id'], 'tool': 'research_report', 'ok': True,
             'request_complete': True, 'study_id': sid,
             'file': f'/api/research/studies/{sid}/reports/{report}/files/research.docx'}
    return ident, protocol, state, event


def test_final_lineage_selects_actual_study_with_multiple_same_original_proposals(tmp_path):
    ident, protocol, state, event = fixture(tmp_path)
    for token in ('4', '5', '6'):
        draft = 'MI-'+token*24
        write(tmp_path/'model_research_intents'/draft/'protocol.json', protocol)
        write(tmp_path/'model_research_intents'/draft/'state.json', {'status': 'awaiting_model'})
    result = module.select_result(tmp_path, protocol['question'], protocol['session_id'], [event])
    assert result['intent_path'].parent.name == ident
    assert result['state'] == state


@pytest.mark.parametrize('mutation', ['session', 'question', 'seal', 'baseline', 'selected'])
def test_foreign_or_inconsistent_final_lineage_is_rejected(tmp_path, mutation):
    ident, protocol, state, event = fixture(tmp_path)
    if mutation in ('session', 'question', 'seal'):
        key = {'session': 'session_id', 'question': 'question', 'seal': 'sha256'}[mutation]
        write(tmp_path/'model_research_intents'/ident/'protocol.json', {**protocol, key: 'different'})
    else:
        key = 'baseline_run_id' if mutation == 'baseline' else 'result_run_id'
        write(tmp_path/'model_research_intents'/ident/'state.json', {**state, key: 'different'})
    with pytest.raises(ValueError):
        module.select_result(tmp_path, protocol['question'], protocol['session_id'], [event])


def test_partial_foreign_and_mismatched_report_receipts_cannot_replace_final(tmp_path):
    _, protocol, _, event = fixture(tmp_path)
    foreign = {**event, 'seq': 99, 'session_id': 'other-session', 'study_id': 'MS-'+'9'*24}
    partial = {**event, 'seq': 100, 'request_complete': False}
    result = module.select_result(tmp_path, protocol['question'], protocol['session_id'], [event, foreign, partial])
    assert result['event'] == event
    bad = deepcopy(event)
    bad['file'] = bad['file'].replace('MR-'+'3'*24, 'MR-'+'8'*24)
    with pytest.raises(ValueError, match='report differs'):
        module.select_result(tmp_path, protocol['question'], protocol['session_id'], [bad])
