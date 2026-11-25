"""Locate a native research result by its actual report and immutable lineage.

Multiple proposals are expected during legitimate revision. Their count is not
a fidelity check; the final study must resolve to the same user and session.
This module never starts services, executes models, or changes stored records.
"""
import json
import re


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _id(value, prefix):
    if not isinstance(value, str) or not re.fullmatch(prefix+r'-[a-f0-9]{24}', value):
        raise ValueError('Invalid '+prefix+' identity in native evidence')
    return value


def select_result(data, request, session, events):
    reports = [row for row in events if row.get('session_id') == session
               and row.get('tool') == 'research_report' and row.get('ok') is True
               and row.get('request_complete') is True]
    if not reports:
        raise ValueError('No actual completed report in the original native session')
    event = max(reports, key=lambda row: row['seq'])
    sid = _id(event.get('study_id'), 'MS')
    study = read(data/'model_studies'/sid/'protocol.json')
    progress = read(data/'model_studies'/sid/'state.json')
    if study.get('question') != request or progress.get('study_id') != sid:
        raise ValueError('Final study differs from the original request or identity')
    link = study.get('baseline', {}).get('manifest', {}).get('scenario_review', {}).get('research_intent', {})
    ident = _id(link.get('research_intent_id'), 'MI')
    intent_path = data/'model_research_intents'/ident/'protocol.json'
    protocol, state = read(intent_path), read(intent_path.with_name('state.json'))
    if (protocol.get('question') != request or protocol.get('session_id') != session
            or protocol.get('sha256') != link.get('protocol_sha256')
            or state.get('research_intent_id') != ident or state.get('study_id') != sid
            or state.get('status') not in ('complete', 'failed')):
        raise ValueError('Final intent lineage differs from its user, session or sealed protocol')
    report_id = _id(state.get('report_id'), 'MR')
    expected = f'/api/research/studies/{sid}/reports/{report_id}/files/research.docx'
    if event.get('file') != expected:
        raise ValueError('Final report differs from the native receipt')
    baseline = study['baseline']
    if (state.get('baseline_run_id') != baseline.get('run_id')
            or state.get('design_id') != baseline.get('design_id')
            or state.get('result_run_id') != progress.get('selected_run', {}).get('run_id')):
        raise ValueError('Final intent differs from actual baseline, design or selected result')
    return {'intent_path': intent_path, 'protocol': protocol, 'state': state,
            'study': study, 'progress': progress, 'event': event}
