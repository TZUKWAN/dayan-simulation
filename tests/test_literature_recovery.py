"""Explicit network/provider protocol fixtures; real persistence and child death.

These tests do not claim online retrieval, actual paper reading or real LLM use.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from dayan.agent import design_checkpoint, model_design
from dayan.agent.design_checkpoint import DesignCheckpoint, PendingStage
from dayan.collection.storage import atomic_json, read_json
from dayan.research import literature


QUERIES = {'zh': ['协议恢复测试'], 'en': ['protocol recovery fixture']}
SOURCE = '文献研究协议测试：库存机制参考；这不是实际论文或现实仿真。'


def _search_fixture(provider, lane, query, deadline):
    hits = []
    if provider == 'OpenAlex' and lane == 'en':
        for i in range(7):
            hits.append({'doi': f'10.0000/protocol-{i}', 'title': f'Protocol fixture paper {i}',
                         'journal': 'Protocol fixture, not a real journal', 'year': 2024,
                         'authors': ['Protocol fixture'], 'issn': [], 'language': 'en',
                         'indexes': [], 'open_access': True, 'retracted': False,
                         'locations': [{'url': f'https://example.org/protocol-{i}', 'version': 'published'}]})
    return {'provider': provider, 'lane': lane, 'query': query, 'status': 'ok', 'hits': len(hits)}, hits


def _article_fixture(candidate, deadline):
    text = 'Explicit source-text protocol fixture for ' + candidate['doi']
    return {'access': 'full_text', 'format': 'html', 'url': candidate['locations'][0]['url'],
            'version': 'published', 'sha256': hashlib.sha256(text.encode()).hexdigest(), 'indexes': [],
            'sections': [{'id': 'S1', 'locator': 'Protocol method', 'anchor': 'method', 'text': text}]}


def _checkpoint(path, deadline):
    record = read_json(path) if path.exists() else {'stages': [], 'llm_calls': []}
    return DesignCheckpoint(record, path, [], deadline)


def test_budget_pause_resumes_each_accepted_lookup_and_article_without_refetch(monkeypatch, tmp_path):
    clock = SimpleNamespace(now=0.)
    monkeypatch.setattr(design_checkpoint, 'time', SimpleNamespace(monotonic=lambda: clock.now))
    searches, reads = [], []

    def search(*args):
        searches.append(args[:3]); clock.now += 2
        return _search_fixture(*args)

    def article(candidate, deadline):
        reads.append(candidate['doi']); clock.now += 8
        return _article_fixture(candidate, deadline)

    monkeypatch.setattr(literature, '_search', search)
    monkeypatch.setattr(literature, 'read_online', article)
    path = tmp_path / 'record.json'
    first = _checkpoint(path, 49.)
    with pytest.raises(PendingStage):
        literature.collect(QUERIES, SOURCE, deadline=49., checkpoint=first)
    frozen = deepcopy(read_json(path)['stages'])
    assert len(searches) == 5 and len(reads) == 2 and len(frozen) == 7
    progress = read_json(path)['literature_progress']
    assert progress['phase'] == 'articles' and progress['readable_articles'] == 2
    assert progress.get('status') != 'awaiting_paper_review'
    resumed = _checkpoint(path, clock.now + 90.)
    record, papers = literature.collect(QUERIES, SOURCE, deadline=clock.now + 90., checkpoint=resumed)
    assert len(searches) == len(set(searches)) == 5
    assert len(reads) == len(set(reads)) == 7
    assert resumed.record['stages'][:len(frozen)] == frozen
    assert len(papers) == 7 and record['cards'] == []
    assert resumed.record['literature_progress']['status'] == 'awaiting_paper_review'
    # Collection success is not falsely presented as reviewed scientific evidence.
    assert all(p['sha256'] and p['sections'] for p in papers)
    record_again, papers_again = literature.collect(QUERIES, SOURCE, deadline=clock.now + 90.,
                                                   checkpoint=_checkpoint(path, clock.now + 90.))
    assert (record_again, papers_again) == (record, papers)
    assert len(searches) == 5 and len(reads) == 7
    broken = read_json(path)
    broken['stages'][0]['output'][0]['hits'] = 999
    atomic_json(path, broken)
    with pytest.raises(ValueError, match='内容校验失败'):
        literature.collect(QUERIES, SOURCE, deadline=clock.now + 90., checkpoint=_checkpoint(path, clock.now + 90.))
    assert len(searches) == 5 and len(reads) == 7


def _child_worker(folder):
    """Pause only this test child after one completed article is on disk."""
    folder = Path(folder)
    literature._search = _search_fixture
    count = 0

    def article(candidate, deadline):
        nonlocal count
        count += 1
        if count == 2:
            saved = read_json(folder / 'record.json')
            assert sum(s['step'] == 'literature_article' for s in saved['stages']) == 1
            (folder / 'published.marker').write_text('first article durably accepted', encoding='utf-8')
            time.sleep(30)
        return _article_fixture(candidate, deadline)

    literature.read_online = article
    end = time.monotonic() + 240
    literature.collect(QUERIES, SOURCE, deadline=end, checkpoint=_checkpoint(folder / 'record.json', end))


def test_real_child_termination_keeps_prior_article_and_resumes_only_unaccepted_work(monkeypatch, tmp_path):
    module_file = str(Path(__file__).resolve())
    script = '''import importlib.util,sys
spec=importlib.util.spec_from_file_location('recovery_fixture',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
module._child_worker(sys.argv[2])
'''
    options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    process = subprocess.Popen([sys.executable, '-c', script, module_file, str(tmp_path)],
                               cwd=Path(__file__).resolve().parents[1], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, **options)
    try:
        end = time.monotonic() + 15
        marker = tmp_path / 'published.marker'
        while not marker.exists() and process.poll() is None and time.monotonic() < end:
            time.sleep(.05)
        assert marker.exists(), process.communicate(timeout=1)
        process.terminate(); process.wait(timeout=5)
        frozen = deepcopy(read_json(tmp_path / 'record.json')['stages'])
        first = next(s for s in frozen if s['step'] == 'literature_article')
        reads = []

        def no_search(*args):
            raise AssertionError('Already accepted search was repeated')

        def article(candidate, deadline):
            reads.append(candidate['doi'])
            return _article_fixture(candidate, deadline)

        monkeypatch.setattr(literature, '_search', no_search)
        monkeypatch.setattr(literature, 'read_online', article)
        end = time.monotonic() + 240
        record, papers = literature.collect(QUERIES, SOURCE, deadline=end,
                                            checkpoint=_checkpoint(tmp_path / 'record.json', end))
        assert len(papers) == 7 and len(reads) == len(set(reads)) == 6
        assert first['output']['sha256'] == papers[0]['sha256']
        assert papers[0]['doi'] not in reads and record['cards'] == []
        assert read_json(tmp_path / 'record.json')['stages'][:len(frozen)] == frozen
    finally:
        if process.poll() is None:
            process.terminate(); process.wait(timeout=5)
        process.communicate(timeout=5)


def test_design_budget_pause_cannot_skip_unfinished_literature_to_approval(monkeypatch, tmp_path):
    monkeypatch.setenv('DAYAN_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('DAYAN_WALL_SECONDS', '240')
    clock = SimpleNamespace(now=0.)
    timer = SimpleNamespace(monotonic=lambda: clock.now)
    monkeypatch.setattr(design_checkpoint, 'time', timer)
    calls = []

    def provider(messages, *, purpose, audit, **options):
        assert purpose == 'model-design-concept', 'Unfinished collection reached a later LLM stage'
        calls.append(purpose); clock.now += 190
        audit.append({'call_id': 'controlled-concept', 'purpose': purpose, 'ok': True})
        return json.dumps({'approach': 'Explicit protocol fixture', 'mechanisms': ['stock growth'],
                           'assumptions': ['Protocol only'], 'risks': ['No actual literature verified'],
                           'alternatives': [{'structure': 'No growth', 'limitation': 'Different mechanism'}],
                           'literature_queries': QUERIES})

    def search(*args):
        clock.now += 2
        return _search_fixture(*args)

    def article(candidate, deadline):
        clock.now += 8
        return _article_fixture(candidate, deadline)

    monkeypatch.setattr(model_design, 'complete', provider)
    monkeypatch.setattr(literature, '_search', search)
    monkeypatch.setattr(literature, 'read_online', article)
    record = model_design.create_design(SOURCE, {}, {}, 'Explicit controlled protocol contract', [],
                                        session_id='literature-protocol-owner', deadline=240.)
    assert record['status'] == 'pending' and record['resume_available'], record.get('error')
    assert record['request'] == SOURCE and 'plan' not in record and 'review' not in record
    assert record['literature_progress']['readable_articles'] == 2
    assert calls == ['model-design-concept']


def _reading_stages(checkpoint, clock, calls, *, reject_first=False):
    """Controlled semantics, real stage JSON validation and durable reuse."""
    def complete(messages, *, purpose, audit, **options):
        inputs = json.loads(messages[1]['content'])
        clock.now += 50
        audit.append({'call_id': 'controlled-reading-' + str(len(calls) + 1), 'purpose': purpose, 'ok': True})
        if purpose == 'model-design-literature_paper':
            assert len(inputs['articles']) == 1
            paper = inputs['articles'][0]
            calls.append(paper['id'])
            if reject_first and paper['id'] == 'P1':
                return json.dumps({'cards': [], 'synthesis': 'P1是已读但偏离本轮机制的协议夹具。'}, ensure_ascii=False)
            findings = {key: {'basis': 'unavailable', 'section': None, 'text': 'No such evidence in the protocol fixture'}
                        for key in ('rationale', 'validation', 'limitations')}
            findings['method'] = {'basis': 'reported', 'section': 'S1', 'text': 'Explicit protocol mechanism fixture'}
            return json.dumps({'cards': [{'id': paper['id'], 'relevance': 'Protocol mechanism', 'findings': findings}],
                               'synthesis': paper['id'] + ' supplies the protocol method only'})
        assert purpose == 'model-design-literature_synthesis'
        calls.append('synthesis')
        evidence = inputs['literature']['evidence']
        return json.dumps({'synthesis': 'Comparison of ' + ' and '.join(row['id'] for row in evidence[:2]),
                           'comparisons': [{'question': 'Which protocol mechanisms are comparable?',
                                            'refs': [row['id'] for row in evidence[:2]], 'agreement': 'not_comparable',
                                            'implication': 'These fixtures provide no actual scientific result'}]})

    def stage(key, label, inputs, validate, prompt=None):
        messages = [{'role': 'system', 'content': prompt},
                    {'role': 'user', 'content': json.dumps(inputs, ensure_ascii=False)}]
        return checkpoint.call(key, messages, validate, complete)
    return stage


def test_per_paper_reading_resumes_and_merges_real_source_identities_without_forcing_irrelevance(monkeypatch, tmp_path):
    from dayan.agent.literature_workflow import review_online
    from dayan.agent.literature_review import synthesis_for
    clock = SimpleNamespace(now=0.)
    monkeypatch.setattr(design_checkpoint, 'time', SimpleNamespace(monotonic=lambda: clock.now))
    monkeypatch.setattr(literature, '_search', _search_fixture)
    monkeypatch.setattr(literature, 'read_online', _article_fixture)
    path, calls = tmp_path / 'reading.json', []
    result = None
    for _ in range(literature.TARGET + 2):  # Five selected papers, one exclusion, one synthesis; one stage may use each call.
        end = clock.now + 240
        checkpoint = _checkpoint(path, end)
        try:
            result = review_online({'literature_queries': QUERIES}, SOURCE, 'required',
                                   _reading_stages(checkpoint, clock, calls, reject_first=True), checkpoint, deadline=end)
            break
        except PendingStage:
            assert checkpoint.record['literature']['status'] != 'complete'
    assert result is not None
    assert calls == ['P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'synthesis']
    assert [card['id'] for card in result['cards']] == ['P2', 'P3', 'P4', 'P5', 'P6']
    assert result['excluded'][0]['paper'] == 'P1' and result['status'] == 'complete'
    assert result['requirement']['target_met'] and result['follow_up'] == []
    evidence = result['evidence']
    assert [row['id'] for row in evidence] == ['E1', 'E2', 'E3', 'E4', 'E5']
    for card, row in zip(result['cards'], evidence):
        finding = card['findings']['method']
        assert row['paper'] == card['id'] and finding['evidence_id'] == row['id']
        expected = 'Explicit source-text protocol fixture for ' + card['doi']
        assert finding['section_sha256'] == hashlib.sha256(expected.encode()).hexdigest()
    assert literature.summary(result)['indexed_journals'] == 0
    wrong = {'synthesis': 'E1 and E2', 'comparisons': [{'question': 'Same source is not cross-paper evidence',
             'refs': ['E1', 'E1'], 'agreement': 'supports', 'implication': 'Must reject'}]}
    with pytest.raises(ValueError, match='两篇不同论文'):
        synthesis_for(wrong, result)
    wrong['comparisons'][0]['refs'] = ['E1', 'E999']
    with pytest.raises(ValueError, match='两篇不同论文'):
        synthesis_for(wrong, result)


def test_short_literature_result_remains_honest_and_can_continue_modeling(monkeypatch, tmp_path):
    from dayan.agent.literature_workflow import review_online
    clock = SimpleNamespace(now=0.)
    monkeypatch.setattr(design_checkpoint, 'time', SimpleNamespace(monotonic=lambda: clock.now))

    def two_papers(*args):
        receipt, hits = _search_fixture(*args)
        return {**receipt, 'hits': min(2, receipt['hits'])}, hits[:2]

    monkeypatch.setattr(literature, '_search', two_papers)
    monkeypatch.setattr(literature, 'read_online', _article_fixture)
    checkpoint = _checkpoint(tmp_path / 'limited.json', 1000.)
    result = review_online({'literature_queries': QUERIES}, SOURCE, 'required',
                           _reading_stages(checkpoint, clock, []), checkpoint, deadline=1000.)
    assert result['status'] == 'limited' and len(result['cards']) == 2
    assert result['requirement']['selected'] == 2 and not result['requirement']['target_met']
    assert result['follow_up'] and result['comparisons']
