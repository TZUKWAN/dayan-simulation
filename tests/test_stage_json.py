"""Narrow formatting recovery preserves real source checks and raw evidence."""
import hashlib
import json
import time

import pytest

from dayan.agent.design_checkpoint import DesignCheckpoint
from dayan.agent.literature_review import cards_for
from dayan.agent.stage_json import stage_object
from dayan.collection.storage import read_json


def paper():
    return {'id': 'P1', 'title': 'Explicit source protocol fixture', 'sections': [
        {'id': 'S1', 'locator': 'Methods', 'text': 'Actual method passage fixture'},
        {'id': 'S2', 'locator': 'Validation', 'text': 'Actual validation passage fixture'}]}


def response(section):
    findings = {key: {'basis': 'unavailable', 'section': None, 'text': 'Not in this fixture'}
                for key in ['rationale', 'validation', 'limitations']}
    findings['method'] = {'basis': 'reported', 'section': section, 'text': 'Method supported by the cited passages'}
    value = {'cards': [{'id': 'P1', 'relevance': 'Protocol reference', 'findings': findings}],
             'synthesis': 'P1 contains the protocol method'}
    text = json.dumps(value, separators=(',', ':'))
    # Exactly the observed provider defect: omit the card's final } before ].
    assert '}}}],' in text
    return value, text.replace('}}}],', '}}],', 1)


def test_missing_object_delimiter_recovers_exact_values_and_rejects_other_damaged_inputs():
    value, raw = response(['S1', 'S2'])
    actual, receipt = stage_object(raw)
    assert actual == value and len(receipt['edits']) == 1
    assert receipt['original_sha256'] == hashlib.sha256(raw.encode()).hexdigest()
    assert stage_object('{"text":"literal }], and \\\" quote"}')[1] is None
    for broken in ['{"a":', '{"a":"unterminated', '{"a":[1,2}', 'prefix {"a":[{"x":1]}',
                   '{"a":[{"x":1,"x":2]}', '{"a":[{"x":1,]}']:
        with pytest.raises(ValueError):
            stage_object(broken)


def test_missing_card_close_and_redundant_tail_preserve_all_paper_values():
    expected, raw = response(['S1', 'S2'])
    raw += ']}'
    actual, receipt = stage_object(raw)
    assert actual == expected
    assert receipt['kind'] == 'missing_object_close_before_array_and_redundant_tail'
    assert [edit['delete'] for edit in receipt['edits'] if 'delete' in edit] == [']', '}']
    assert receipt['original_sha256'] == hashlib.sha256(raw.encode()).hexdigest()
    assert cards_for(actual, [paper()])['cards'][0]['findings']['method']['sections'] == ['S1', 'S2']
    for suffix in [']} trailing instruction', ']}{"extra":1}', ']}0', ']}"changed"']:
        with pytest.raises(ValueError):
            stage_object(response(['S1', 'S2'])[1] + suffix)


def test_multiple_verified_sections_are_preserved_with_all_hashes_and_foreign_refs_fail():
    for supplied in [['S1', 'S2'], 'S1, S2']:
        value, _ = response(supplied)
        result = cards_for(value, [paper()])
        finding = result['cards'][0]['findings']['method']
        assert finding['sections'] == ['S1', 'S2']
        assert finding['locator'] == 'Methods；Validation'
        assert [row['sha256'] for row in finding['section_sources']] == [
            hashlib.sha256(s['text'].encode()).hexdigest() for s in paper()['sections']]
    for bad in [['S1', 'S99'], ['P2.S1', 'S2']]:
        value, _ = response(bad)
        with pytest.raises(ValueError, match='无法核对'):
            cards_for(value, [paper()])


def test_durable_stage_keeps_original_format_failure_and_requires_the_same_scientific_validation(tmp_path):
    for semantic_valid in [True, False]:
        expected, raw = response(['S1', 'S2'] if semantic_valid else ['S1', 'S99'])
        path = tmp_path / ('accepted.json' if semantic_valid else 'rejected.json')
        audit, calls = [], []
        checkpoint = DesignCheckpoint({'stages': []}, path, audit, time.monotonic() + 1000)

        def controlled(messages, *, audit, purpose, **kwargs):
            calls.append(purpose)
            audit.append({'call_id': 'controlled-' + str(len(calls)), 'purpose': purpose, 'ok': True})
            return raw

        def run():
            return checkpoint.call('literature_paper', [{'role': 'user', 'content': 'Protocol fixture'}],
                                   lambda value: cards_for(value, [paper()]), controlled)
        if semantic_valid:
            checked = run()
            assert len(calls) == 1 and checked['cards'][0]['findings']['method']['sections'] == ['S1', 'S2']
            assert len(read_json(path)['stages']) == 1
        else:
            with pytest.raises(ValueError, match='仍未通过'):
                run()
            assert len(calls) == 2 and not read_json(path)['stages']
        failures = [f for rows in read_json(path)['stage_failures'].values() for f in rows]
        formats = [f for f in failures if f['kind'] == 'format_normalization']
        assert len(formats) == len(calls) and all(f['response'] == raw for f in formats)
        assert all(call['json_format_recovery']['original_sha256'] == hashlib.sha256(raw.encode()).hexdigest()
                   for call in audit)
