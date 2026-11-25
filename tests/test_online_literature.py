import pytest
from bs4 import BeautifulSoup

from dayan.agent.literature_review import cards_for, decisions_for
from dayan.research.article_reader import _confirmed, _full_sections, _sections
from dayan.research.literature import queries_from, requested


def test_structured_abstract_and_cross_article_metadata_do_not_count_as_full_text():
    abstract = "<div id='abstract'><h2>Methods</h2><p>" + "method " * 150 + "</p>"
    abstract += "<h2>Results</h2><p>" + "result " * 150 + "</p></div>"
    assert not _full_sections(_sections(BeautifulSoup(f"<article>{abstract}</article>", "html.parser")))
    assert not _confirmed({"doi": "10.0000/example-a", "title": "Same title"}, "10.0000/example-b", "Same title")


def test_paper_evidence_must_point_to_a_section_read_in_the_same_article():
    article = {"id": "P1", "sections": [{"id": "S1", "locator": "Methods", "text": "Article method"}]}
    findings = {"method": {"basis": "reported", "section": "S2", "text": "Mechanism"}}
    findings.update({kind: {"basis": "unavailable", "section": None, "text": "Outside the readable sections"}
                     for kind in ("rationale", "validation", "limitations")})
    result = {"cards": [{"id": "P1", "relevance": "Matching mechanism", "findings": findings}], "synthesis": "Comparison"}
    with pytest.raises(ValueError, match="无法核对"):
        cards_for(result, [article])
    findings["method"]["section"] = "S1"
    cards = cards_for(result, [article])
    assert cards["cards"][0]["findings"]["method"]["locator"] == "Methods"
    assert "sections" not in cards["cards"][0]
    plan = {"mechanisms": ["Driven transition"], "criteria": []}
    choice = {"target": "M1", "action": "adapt", "refs": ["P1.validation"], "reason": "Sensitivity",
              "condition": "Same time scale"}
    with pytest.raises(ValueError, match="无法定位"):
        decisions_for({"literature_decisions": [choice]}, plan, cards)
    choice["refs"] = ["P1.method", "E1"]
    result = decisions_for({"literature_decisions": [choice]}, plan, cards)[0]
    assert result["target_label"] == "Driven transition" and result["refs"] == ["E1"]
    declared = [{"mechanism": "Initial conditions"}, {"mechanism": "Driven transition"}]
    choice["target"] = "M2"
    result, = decisions_for({"mechanisms": declared, "literature_decisions": [choice]}, plan, cards)
    assert result["target_label"] == "Driven transition" and result["refs"] == ["E1"]
    result = cards_for({"cards": [{"id": "P1", "relevance": "Matching mechanism", "findings": findings}],
                        "synthesis": "P1 和 P15 的比较。"}, [article])
    assert not result["synthesis"] and result["unselected_synthesis_references"] == ["P15"]


def test_required_research_uses_bilingual_keywords_and_respects_an_explicit_skip():
    mode = requested("仿真前请查阅期刊和 arXiv")
    assert mode == "required"
    with pytest.raises(ValueError, match="zh 和 en"):
        queries_from(None, mode=mode)
    raw = {"zh": ["观点动力学"], "en": ["bounded confidence"]}
    assert queries_from(raw, mode=mode) == raw
    assert queries_from(raw, mode=requested("请跳过文献检索，直接验算")) == {}
    for text in ("无需外部数据或查文献。", "不需要采集数据和阅读论文", "without external data or literature search"):
        assert requested(text) == "skip", text
        assert queries_from(raw, mode=requested(text)) == {}
    for text in ("无需外部数据，但要查文献", "不需要下载论文，直接在线阅读", "no external data but read papers"):
        assert requested(text) == "required", text


def test_publisher_unicode_urls_are_encoded_without_changing_query_separators():
    from urllib.parse import urlsplit, unquote
    from dayan.research.article_reader import https_url

    path = "/download/类C形孔洞四方晶格 PCSEL中Γ₂点.pdf"
    url = https_url("https://example.org" + path + "?file=a%2Fb&name=图 表&ratio=50%#page=2")
    assert url.isascii() and " " not in url
    parsed = urlsplit(url)
    assert unquote(parsed.path) == path
    assert parsed.query == "file=a%2Fb&name=%E5%9B%BE%20%E8%A1%A8&ratio=50%25"
    assert not parsed.fragment and https_url(url) == url
    assert https_url("https://example.org/a\nb") == ""
    assert https_url("https://user:pass@example.org/a") == ""
    assert https_url("file:///private.txt") == ""


def test_one_invalid_remote_response_does_not_abort_other_article_locations(monkeypatch):
    import time
    from http.client import InvalidURL
    from dayan.research import article_reader

    calls = []
    body = ("<article><h1>Verified example title</h1><h2>Methods</h2><p>" + "Mechanism evidence. " * 80
            + "</p><h2>Results</h2><p>" + "Observed results. " * 80 + "</p></article>").encode()

    def controlled_fetch(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            raise InvalidURL("publisher redirect contained an invalid address")
        return body, url

    monkeypatch.setattr(article_reader, "_get", controlled_fetch)
    result = article_reader.read_online({"doi": "", "title": "Verified example title", "indexes": ["fixture"],
        "locations": [{"url": "https://example.org/first", "version": "published"},
                      {"url": "https://example.org/second", "version": "published"}]}, time.monotonic() + 10)
    assert len(calls) == 2 and result["access"] == "full_text" and result["url"].endswith("/second")


def test_one_protected_count_is_verified_at_every_saved_time():
    from dayan.agent.verification import criteria_for_plan, evaluate_criteria

    checks = criteria_for_plan([
        {"id": "V1", "check": "balance", "fields": ["protected_count"], "target": 0,
         "reason": "保护单元全程保持未开发"},
        {"id": "V2", "check": "nondecreasing", "fields": ["developed_share"], "reason": "已开发是吸收状态"},
    ], ["protected_count", "developed_share"])
    rows = [{"protected_count": 0, "developed_share": x} for x in (.1, .2, .3)]
    assert all(row["passed"] for row in evaluate_criteria(checks, rows))
    rows[1]["protected_count"] = 1
    protected, growth = evaluate_criteria(checks, rows)
    assert not protected["passed"] and growth["passed"]


def test_parameter_path_is_compiled_to_an_actual_definition_reference():
    from dayan.agent.model_design import _equation_refs, check_definition

    refs = _equation_refs([{"mechanism": "固定增长", "paths": ["rates.stock", "execution.parameters.growth"]}])
    plan = {"kind": "stocks", "observables": ["stock"], "rule_refs": refs, "coverage": []}
    definition = {"kind": "stocks", "rates": {"stock": "growth"},
                  "initial_state": {"stock": 1}, "observables": {"stock": "stock"}}
    assert refs[0]["paths"] == ["rates.stock", "parameters.growth"]
    with pytest.raises(ValueError, match="parameters.growth"):
        check_definition(plan, definition)
    definition["parameters"] = {"growth": {"default": 2}}
    check_definition(plan, definition)


def test_plan_parser_rejects_a_nested_object_from_a_broken_document():
    from dayan.llm_client import json_object

    with pytest.raises(ValueError, match="完整JSON"):
        json_object('{"cards":[{"id":"P1"}] "synthesis":"text"}', whole=True)
    assert json_object('{"cards":[{"id":"P1"}]}', whole=True) == {"cards": [{"id": "P1"}]}
