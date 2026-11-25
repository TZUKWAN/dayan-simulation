"""Actual extraction/persistence; controlled semantic provider, not a live paper study."""
import hashlib
import io
import json
import time
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from dayan.agent import design_checkpoint, paper_reading
from dayan.agent.design_checkpoint import PendingStage
from dayan.agent.literature_review import READ_PROMPT, cards_for
from dayan.research.article_reader import _compact, _read_pdf, _sections
from test_literature_recovery import _checkpoint


def test_extracted_middle_equations_late_sections_and_appendices_are_preserved():
    formula = 'Transition probability p = 1 / (1 + exp(-beta * delta_payoff)); eta = 0.37.'
    body = ('<article><h2>Methods</h2><p>' + 'Method context. ' * 300 + formula + ' More context.' * 200 + '</p>')
    body += ''.join(f'<h3>Model component {i}</h3><p>Actual model component {i} and parameter definition.</p>' for i in range(18))
    body += '<h2>Results</h2><p>Observed validation error is 0.012 in this extraction fixture.</p>'
    body += '<h2>References</h2><p>This reference list is not article evidence.</p>'
    body += '<h2>Appendix A</h2><p>Appendix derivation states boundary flux equals zero.</p></article>'
    extracted = _compact(_sections(BeautifulSoup(body, 'html.parser')))
    assert len(extracted) > 16
    assert formula in extracted[0]['text']
    assert any('boundary flux equals zero' in section['text'] for section in extracted)
    assert not any('reference list is not' in section['text'] for section in extracted)
    assert extracted[0]['sha256'] == hashlib.sha256(extracted[0]['text'].encode()).hexdigest()


def test_pdf_middle_pages_are_read_without_old_first_twelve_last_four_gap():
    stream = io.BytesIO()
    document = PdfWriter()
    for page in range(1, 21):
        target = document.add_blank_page(width=595, height=842)
        target[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({
            NameObject('/F1'): DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})})})
        lines = ['Verified long extraction fixture', f'Page {page}: Methods, model validation and results are explicit.']
        lines += [f'Independent page evidence {page}; model parameter alpha = {page}.' for _ in range(8)]
        content = DecodedStreamObject()
        content.set_data(('BT /F1 10 Tf 25 800 Td ' + ' 0 -20 Td '.join('(' + line + ') Tj' for line in lines) + ' ET').encode('ascii'))
        target[NameObject('/Contents')] = content
    document.write(stream)
    sections = _read_pdf(stream.getvalue(), {'title': 'Verified long extraction fixture', 'doi': ''}, time.monotonic() + 15)
    assert len(sections) == 20
    assert 'model parameter alpha = 13' in sections[12]['text']
    assert 'model parameter alpha = 20' in sections[19]['text']


def test_long_paper_resumes_each_real_passage_and_keeps_middle_formula_evidence(monkeypatch, tmp_path):
    monkeypatch.setattr(paper_reading, 'context_bytes', lambda: 12000)
    clock = SimpleNamespace(now=0.)
    monkeypatch.setattr(design_checkpoint, 'time', SimpleNamespace(monotonic=lambda: clock.now))
    formula = 'eta = 0.37; p = 1 / (1 + exp(-beta * delta_payoff)).'
    article = {'id': 'P1', 'title': 'Controlled deep reading protocol fixture', 'doi': '10.0000/deep-fixture',
        'sections': [{'id': 'S1', 'locator': 'Methods', 'text': 'Method explanation. ' * 600 + formula + ' Local condition.' * 600},
                     {'id': 'S2', 'locator': 'Results', 'text': 'Validation evidence. ' * 600}]}
    prepared, groups = paper_reading.prepare(article)
    assert len(groups) > 1
    assert ''.join(row['text'] for row in prepared['sections'] if row['source_section_id'] == 'S1') == article['sections'][0]['text']
    calls, received = [], []

    def complete(messages, *, purpose, audit, **options):
        data = json.loads(messages[1]['content'])
        clock.now += 50
        audit.append({'call_id': 'controlled-deep-' + str(len(calls)), 'purpose': purpose, 'ok': True})
        if purpose == 'model-design-literature_passages':
            calls.append(data['batch'])
            findings = []
            for section in data['passages']:
                received.append(section['text'])
                quote = formula if formula in section['text'] else section['text'][:100]
                findings.append({'aspect': 'parameters' if formula in section['text'] else 'method',
                    'section': section['id'], 'basis': 'reported', 'quote': quote,
                    'text': 'Actual middle formula eta=0.37' if formula in section['text'] else 'Actual passage from the protocol fixture'})
            return json.dumps({'findings': findings})
        calls.append('card')
        sections = data['articles'][0]['sections']
        selected = next(section for section in sections if formula in section['text'])
        findings = {key: {'basis': 'unavailable', 'section': None, 'text': 'No independent scientific evidence in fixture'}
                    for key in ('rationale', 'validation', 'limitations')}
        findings['method'] = {'basis': 'reported', 'section': selected['id'], 'text': 'Model formula eta=0.37; conditions remain explicit.'}
        return json.dumps({'cards': [{'id': 'P1', 'relevance': 'Extraction protocol only', 'findings': findings}], 'synthesis': 'Actual middle text was available'})

    result = None
    for _ in range(len(groups) + 1):
        checkpoint = _checkpoint(tmp_path / 'reading.json', clock.now + 240)
        def stage(key, label, inputs, validate, prompt=None):
            return checkpoint.call(key, [{'role': 'system', 'content': prompt},
                {'role': 'user', 'content': json.dumps(inputs)}], validate, complete)
        try:
            result = paper_reading.read_article(article, stage, READ_PROMPT, cards_for)
            break
        except PendingStage:
            assert not any(row.get('reading_coverage', {}).get('complete') for row in checkpoint.record.get('cards', []))
    assert result is not None
    assert calls == list(range(1, len(groups) + 1)) + ['card']
    card, = result['cards']
    assert card['reading_coverage']['complete'] and card['reading_coverage']['batches'] == len(groups)
    assert formula in ''.join(received)
    finding = card['findings']['method']
    actual = next(section for section in prepared['sections'] if section['id'] == finding['section'])
    assert finding['section_sha256'] == hashlib.sha256(actual['text'].encode()).hexdigest()
    with pytest.raises(ValueError, match='逐字对应'):
        paper_reading.notes_for({'findings': [{'aspect': 'parameters', 'basis': 'reported', 'section': actual['id'],
            'text': 'Invented number', 'quote': 'The parameter eta equals 0.99.'}]}, [actual])
