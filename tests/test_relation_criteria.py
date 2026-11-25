"""Count the real graph, including the native failure of old plus current edges."""
from copy import deepcopy
from zipfile import ZipFile

import pytest

from dayan.agent.verification import criteria_for_plan, evaluate_criteria
from dayan.program_frames import validate_relation_time
from test_solver_sandbox import LIVE


def checks(**changes):
    return criteria_for_plan([
        {'id': 'V1', 'check': 'end', 'fields': ['stock'], 'target': 3, 'reason': '规定的终值'},
        {'id': 'V2', 'check': 'relation_count', 'target': 2, 'observable': 'edges',
         'reason': '每时点恰两条当前有效边', **changes},
    ], ['stock', 'edges'])


def example():
    rows = [{'sim_t': t, 'stock': 1 + t, 'edges': 2} for t in (0, 1, 2)]
    frames = [{'sim_t': t, 'relations': [
        {'id': f'current:{i}', 'source': f'people:{i}', 'target': f'firms:{(i+t)%2}',
         'valid_from': t, 'valid_until': t+1} for i in range(2)]} for t in (0, 1, 2)]
    return rows, frames


def test_count_reads_actual_frames_and_rejects_old_plus_current_despite_correct_self_report():
    rows, frames = example()
    rules = checks()
    assert criteria_for_plan(rules, ['stock', 'edges']) == rules
    assert all(item['passed'] for item in evaluate_criteria(rules, rows, frames=frames))
    mixed = deepcopy(frames)
    for frame in mixed:
        # Exactly the defect: author reports current 2 but archives used 2 + current 2.
        frame['relations'] += [{**edge, 'id': 'old:' + edge['id']} for edge in frame['relations']]
    result = evaluate_criteria(rules, rows, frames=mixed)
    assert result[0]['passed'] and not result[1]['passed']
    assert result[1]['measured']['minimum'] == 4
    assert result[1]['measured']['max_observable_error'] == 2
    assert not evaluate_criteria(rules, rows)[1]['passed']
    for altered in ([*frames, frames[0]], [{**frames[0], 'sim_t': 99}], [{**frames[0], 'relations': '2'}]):
        assert not evaluate_criteria(rules, rows, frames=altered)[1]['passed']
    stale_rows = deepcopy(rows)
    stale_rows[1]['edges'] = 1
    assert not evaluate_criteria(rules, stale_rows, frames=frames)[1]['passed']


def test_dynamic_counts_layers_and_actual_step_never_assume_display_frame_indices():
    rows, frames = example()
    for i, frame in enumerate(frames):
        for edge in frame['relations']:
            edge['type'] = 'payment'
        frame['relations'] += [{'id': 'other', 'source': 'people:0', 'target': 'people:1', 'type': 'friendship'}]
    assert evaluate_criteria(checks(relation_type='payment'), rows, frames=frames)[1]['passed']
    rules = checks(step=2, relation_type='payment')
    assert evaluate_criteria(rules, rows, frames=[frames[2]])[1]['passed']
    assert not evaluate_criteria(rules, rows, frames=[frames[1]])[1]['passed']
    dynamic = checks()
    dynamic[1].pop('target')
    for row, frame in zip(rows, frames):
        row['edges'] = len(frame['relations'])
    assert evaluate_criteria(dynamic, rows, frames=frames)[1]['passed']


def test_relation_criteria_reject_ambiguous_contract_and_temporal_inactive_edges():
    for changes in ({'target': True}, {'target': 1.5}, {'atol': .01}, {'atol': False},
                    {'fields': ['edges']}, {'observable': 'invented'}, {'relation_type': ''},
                    {'step': -1}, {'step': True}, {'time': 1}):
        with pytest.raises(ValueError):
            checks(**changes)
    rows, frames = example()
    for boundary in ({'valid_until': 0}, {'valid_from': 1}, {'valid_from': None}, {'valid_until': float('nan')}):
        wrong = deepcopy(frames)
        wrong[0]['relations'][0].update(boundary)
        with pytest.raises(ValueError):
            validate_relation_time(wrong[0]['relations'][0], 0)
        assert not evaluate_criteria(checks(), rows, frames=wrong)[1]['passed']
    validate_relation_time({'valid_from': 0, 'valid_until': 1}, 0)
    validate_relation_time({}, 0)


def test_program_path_error_guides_program_ids_and_accepts_actual_relation_evidence():
    from dayan.agent.model_design import _equation_refs
    assert _equation_refs([{'mechanism': '当前图', 'paths': ['source.advance', 'state_frames.relations']}], 'program')
    with pytest.raises(ValueError) as exc:
        _equation_refs([{'mechanism': '人口', 'paths': ['populations.居民']}], 'program')
    assert 'populations.英文ID' in str(exc.value) and 'rates.backlog' not in str(exc.value)


@LIVE
def test_real_solver_acceptance_archive_word_and_rejection_use_complete_graph(tmp_path, monkeypatch):
    from dayan.agent.tools import _archive_run
    from dayan.agent.scenario_tools import report_run
    from dayan.custom_models import register
    from dayan.run_store import get_store
    from test_program_runtime import definition
    monkeypatch.setenv('DAYAN_DATA_DIR', str(tmp_path/'data'))
    monkeypatch.setenv('DAYAN_REPORTS_DIR', str(tmp_path/'reports'))
    from dayan import report_gen
    monkeypatch.setattr(report_gen, 'REPORTS_DIR', tmp_path/'reports')
    d = definition()
    rules = criteria_for_plan([
        {'id': 'V1', 'check': 'end', 'fields': ['balance'], 'target': 7.517073481042953,
         'atol': 1e-9, 'reason': '独立解析解10-5exp(-0.7)'},
        {'id': 'V2', 'check': 'relation_count', 'target': 2, 'observable': 'edges',
         'reason': '实际两条当前关系而非自报数量'},
    ], ['balance', 'edges'])
    acceptance = {'criteria': rules, 'observables': ['balance', 'edges'], 'events': {}, 'spatial': True,
                  'execution': {'ticks': 5, 'dt': .2, 'seed': 19, 'parameters': {}}}
    mid = register(d)['model_id']
    result = _archive_run(mid, {}, 5, 19, .2, None, None, review={}, acceptance=acceptance, full_frames=True)
    assert result['ok'], result
    record = get_store().load(result['payload']['run_id'])
    checked = record['manifest']['scenario_review']['runtime_checks']['verification']['criteria'][1]
    assert checked['passed'] and checked['measured']['matched_frames'] == 6
    assert checked['measured']['max_observable_error'] == 0
    assert all(len(fr['relations']) == 2 for fr in record['state_frames'])
    report = report_run(record['run_id'], 'balance')
    assert report['ok'], report
    with ZipFile(next((tmp_path/'reports').glob('*.docx'))) as z:
        xml = z.read('word/document.xml').decode()
    assert '实际关系帧数量（全部已存帧）' in xml and '核对 6 帧' in xml and '同刻对账 edges' in xml
    before = {path.name for path in get_store().directory.glob('R*')}
    bad = deepcopy(d)
    bad['source'] = bad['source'].replace('for i,(a,b) in enumerate(state["edges"].tolist())]',
        'for i,(a,b) in enumerate(state["edges"].tolist()+state["edges"].tolist())]')
    assert bad['source'] != d['source']
    rejected = _archive_run(register(bad)['model_id'], {}, 5, 19, .2, None, None,
                            review={}, acceptance=acceptance, full_frames=True)
    assert not rejected['ok'] and rejected['verification']['criteria'][0]['passed'], rejected
    actual = rejected['verification']['criteria'][1]
    assert not actual['passed'] and actual['measured']['minimum'] == 4
    assert {path.name for path in get_store().directory.glob('R*')} == before
