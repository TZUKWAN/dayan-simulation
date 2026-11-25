"""Discover papers online; retain bounded, source-linked evidence for recovery."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import quote, urlencode, urlsplit
from xml.etree import ElementTree

from ..collection.connectors import _get, crossref, openalex
from ..collection.storage import file_lock
from .article_reader import clean, doi_key, https_url, read_online, title_key

TARGET = 5
MAX_PAPERS = 10
_LISTS = {"cwts-core": "CWTS Core", "anvur-class-a": "ANVUR Class A", "norway-2": "Norwegian Level 2"}
_RESEARCH = re.compile(r"文献|论文|期刊|arxiv|课题|研究计划|实证研究|政策(?:模拟|仿真|评估|效果|对照)|"
                       r"科研|(?:\b(?:literature|papers?|journals?|policy (?:simulation|evaluation)|research study)\b)", re.I)
_SKIP = re.compile(r"(?:无需|不用|不要|跳过|不必|不需要)"
                   r"(?:[^，,。；;！？!?\n但]{1,50}(?:或|和|及|、))?"
                   r"(?:主动|再|进行|查找|查阅|查|检索|引用|纳入|读|阅读|搜索|参考|收集)*"
                   r"(?:学术|外部)?(?:论文|文献)|"
                   r"\b(?:skip|without|no) (?:(?:(?!\bbut\b)[^,.;!?\n]){1,60}(?:or|and) )?"
                   r"(?:the )?(?:literature|paper search)\b", re.I)
_DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:0-9A-Z]+", re.I)


def requested(source):
    """Explicit evidence requirements take precedence over concept defaults."""
    if _SKIP.search(source):
        return "skip"
    return "required" if _RESEARCH.search(source) or _DOI.search(source) else "auto"


def queries_from(value, *, mode):
    if mode == "skip":
        return {}
    if not value and mode == "auto":
        return {}
    if not isinstance(value, dict) or set(value) != {"zh", "en"}:
        raise ValueError('literature_queries 需要 zh 和 en 两个关键词数组。')
    queries = {}
    for lane, rows in value.items():
        if not isinstance(rows, list) or not 1 <= len(rows) <= 2:
            raise ValueError("各语言须提供 1 至 2 组可直接使用的学术关键词。")
        terms = [clean(row) for row in rows if isinstance(row, str)]
        if len(terms) != len(rows) or any(not 3 <= len(term) <= 140 or re.search(r"[@/:\\]", term) for term in terms):
            raise ValueError("检索词长度为 3 至 140 字符，以通用学术短语表达，省略网址和私人信息。")
        if lane == "zh" and any(not re.search(r"[\u3400-\u9fff]", term) for term in terms):
            raise ValueError("zh 需要中文学术检索词。")
        if lane == "en" and any(not re.search(r"[A-Za-z]{3}", term) or re.search(r"[\u3400-\u9fff]", term) for term in terms):
            raise ValueError("en 需要英文的学术检索词。")
        queries[lane] = list(dict.fromkeys(terms))
    return queries


def _openalex(row):
    primary = row.get("primary_location") or {}
    locations = [primary, row.get("best_oa_location") or {}, *(row.get("locations") or [])]
    journal = next((location["source"] for location in locations
                    if (location.get("source") or {}).get("type") == "journal"), {})
    if not journal:
        return None
    source_id = https_url(journal.get("id"))
    indexes = [{"name": label, "source": "openalex_source_list", "url": source_id}
               for key, label in _LISTS.items() if source_id and key in (journal.get("listed_in") or [])]
    links = []
    versions = {"publishedVersion": "published", "acceptedVersion": "accepted", "submittedVersion": "submitted"}
    for location in locations:
        if not location.get("is_oa") and location is not primary:
            continue
        version = versions.get(location.get("version"), "unknown")
        for key in ("landing_page_url", "pdf_url"):
            if url := https_url(location.get(key)):
                links.append({"url": url, "version": version})
    return {
        "title": clean(row.get("display_name") or row.get("title")), "doi": doi_key(row.get("doi")),
        "journal": clean(journal.get("display_name")), "year": row.get("publication_year"),
        "authors": [clean((item.get("author") or {}).get("display_name")) for item in row.get("authorships", [])[:8]],
        "issn": list(journal.get("issn") or []), "indexes": indexes, "locations": links,
        "openalex_url": https_url(row.get("id")), "retracted": bool(row.get("is_retracted")),
        "language": row.get("language"), "open_access": bool((row.get("open_access") or {}).get("is_oa")),
    }


def _crossref(row):
    if row.get("type") != "journal-article":
        return None
    doi = doi_key(row.get("DOI"))
    links = [(row.get("resource") or {}).get("primary", {}).get("URL"), row.get("URL")]
    links.extend(item.get("URL") for item in row.get("link", [])
                 if item.get("content-type") in ("text/html", "application/pdf", "application/xhtml+xml"))
    return {
        "title": clean(next(iter(row.get("title") or []), "")), "doi": doi,
        "journal": clean(next(iter(row.get("container-title") or []), "")),
        "year": ((row.get("issued") or {}).get("date-parts") or [[None]])[0][0],
        "authors": [clean(f"{author.get('given', '')} {author.get('family', '')}")
                    for author in row.get("author", [])[:8]],
        "issn": row.get("ISSN") or [], "language": row.get("language"),
        "indexes": [], "locations": [{"url": url, "version": "published"}
                                      for value in links if (url := https_url(value))],
        "retracted": any("retract" in clean(item.get("type")).lower() for item in row.get("update-to", [])),
        "open_access": False,
    }


def _arxiv(query, deadline):
    generic = {"the", "and", "for", "with", "through", "using", "review", "model", "simulation", "approach"}
    terms = list(dict.fromkeys(term.lower() for term in re.findall(r"[A-Za-z0-9][A-Za-z0-9-]{2,}", query)
                               if term.lower() not in generic))[:5]
    if not terms:
        return []
    # arXiv's metadata API allows one connection and one request per three seconds.
    clock = Path(tempfile.gettempdir()) / "dayan-arxiv-api-last-call"
    remaining = deadline - time.monotonic()
    if remaining <= .5:
        raise TimeoutError("arXiv 检索预算已用完")
    with file_lock(clock.with_suffix(".lock"), timeout=min(5, remaining)):
        delay = 0
        if clock.is_file():
            delay = min(3.1, max(0, float(clock.read_text(encoding="ascii")) + 3.1 - time.time()))
        if deadline - time.monotonic() < delay + .5:
            raise TimeoutError("arXiv 请求间隔超过剩余检索预算")
        if delay:
            time.sleep(delay)
        clock.write_text(str(time.time()), encoding="ascii")
        args = urlencode({"search_query": " AND ".join(f'all:"{term}"' for term in terms),
                          "start": 0, "max_results": 10, "sortBy": "relevance"})
        raw, _ = _get(f"https://export.arxiv.org/api/query?{args}", timeout=min(5.5, deadline-time.monotonic()),
                      accept="application/atom+xml", cap=600_000)
    if b"<!DOCTYPE" in raw.upper():
        raise ValueError("arXiv 返回非标准 Atom 提要")
    entries = ElementTree.fromstring(raw).findall("{*}entry")
    papers = []
    for entry in entries:
        ident = urlsplit(entry.findtext("{*}id", "")).path.removeprefix("/abs/")
        if not re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-z.-]+/\d{7})v\d+", ident, re.I):
            continue
        title = clean(entry.findtext("{*}title"))
        if re.match(r"^\s*(?:withdrawn|retracted)\b", title, re.I):
            continue
        papers.append({
            "doi": "", "arxiv_id": ident, "title": title, "journal": "arXiv",
            "year": int(entry.findtext("{*}published", "0000")[:4]) or None,
            "authors": [clean(author.findtext("{*}name")) for author in entry.findall("{*}author")[:8]],
            "issn": [], "language": "en", "indexes": [], "open_access": True, "retracted": False,
            "publication_doi": doi_key(entry.findtext("{*}doi")),
            "locations": [{"url": f"https://arxiv.org/{kind}/{ident}", "version": "preprint"}
                          for kind in ("html", "pdf")],
        })
    return papers


def _search(provider, lane, query, deadline):
    info = {"provider": provider, "lane": lane, "query": query}
    timeout = min(5.5, deadline - time.monotonic())
    if timeout <= .2:
        return {**info, "status": "timed_out", "hits": 0}, []
    try:
        if provider == "arXiv":
            hits = _arxiv(query, deadline)
        elif provider == "Crossref":
            page = next(crossref({"query": query, "rows": 15, "filter": "type:journal-article"}, 1, timeout=timeout))
            hits = [_crossref(row) for row in json.loads(page.raw)["message"]["items"]]
        elif provider == "OpenAlex DOI":
            raw, _ = _get("https://api.openalex.org/works/https://doi.org/" + quote(query, safe="/"), timeout=timeout)
            hits = [_openalex(json.loads(raw))]
        else:
            filters = "type:article,is_retracted:false,language:" + lane
            if lane == "en":
                filters += ",is_oa:true"
            page = next(openalex({"search": query, "per_page": 18, "filter": filters}, 1, timeout=timeout))
            hits = [_openalex(row) for row in json.loads(page.raw)["results"]]
        hits = [hit for hit in hits if hit and hit["title"] and hit["journal"]]
        return {**info, "status": "ok", "hits": len(hits)}, hits
    except (OSError, ValueError, KeyError, TypeError, ElementTree.ParseError, StopIteration) as exc:
        code = getattr(exc, "code", None)
        return {**info, "status": "unavailable", "hits": 0,
                "reason": f"HTTP {code}" if code else type(exc).__name__}, []


def _merge_search(results):
    found = {}
    retracted = set()
    for query, rows in results:
        for rank, row in enumerate(rows, 1):
            ident = row["doi"] or title_key(row["title"])
            if row["retracted"]:
                retracted.add(ident)
                continue
            lane = row["language"]
            if lane not in ("zh", "en"):
                lane = "zh" if re.search(r"^[\W_]*[\u3400-\u9fff]", row["title"]) else "en"
            if ident not in found:
                found[ident] = {**row, "lane": lane, "score": 0.0, "pinned": False, "providers": [],
                                "locations": [], "indexes": []}
            paper = found[ident]
            paper["score"] += 1 / (8 + rank)
            paper["open_access"] |= row["open_access"]
            paper["pinned"] |= query["provider"] == "OpenAlex DOI"
            paper["providers"].append(query["provider"])
            paper["locations"].extend(row["locations"])
            paper["indexes"].extend(row["indexes"])
            if row.get("openalex_url"):
                paper["openalex_url"] = row["openalex_url"]
    merged = []
    titles = set()
    for ident, paper in sorted(found.items(), key=lambda pair: (
            not pair[1]["pinned"], -(pair[1]["score"] + .07 * pair[1]["open_access"] + .055 * bool(pair[1]["indexes"])))):
        title = title_key(paper["title"])
        if ident in retracted or title in titles:
            continue
        titles.add(title)
        if paper["doi"]:
            paper["locations"].append({"url": "https://doi.org/" + quote(paper["doi"], safe="/"), "version": "published"})
        unique = {location["url"]: location for location in paper["locations"]}
        paper["locations"] = sorted(unique.values(), key=lambda item: (
            item["version"] == "submitted", url_is_pdf(item["url"]), "doi.org/" in item["url"]))
        paper["indexes"] = list({(row["name"], row["url"]): row for row in paper["indexes"]}.values())
        paper["providers"] = list(dict.fromkeys(paper["providers"]))
        merged.append(paper)
    return merged


def url_is_pdf(url):
    return "/pdf/" in url.lower() or url.lower().split("?")[0].endswith(".pdf")


def _search_tasks(queries, source):
    calls = [("OpenAlex", lane, query) for lane, terms in queries.items() for query in terms]
    calls.extend(("Crossref", lane, terms[0]) for lane, terms in queries.items())
    dois = list(dict.fromkeys(doi_key(value) for value in _DOI.findall(source)))[:3]
    calls.extend(("OpenAlex DOI", "doi", doi) for doi in dois if doi)
    calls.append(("arXiv", "en", queries["en"][0]))
    return calls


def _reading_order(results):
    candidates = _merge_search([(receipt, hits) for receipt, hits in results if receipt["provider"] != "arXiv"])
    preprints = _merge_search([(receipt, hits) for receipt, hits in results if receipt["provider"] == "arXiv"])
    indexed_dois = {row["doi"] for row in candidates if row["doi"]}
    indexed_titles = {title_key(row["title"]) for row in candidates}
    preprints = [row for row in preprints if row["publication_doi"] not in indexed_dois
                 and title_key(row["title"]) not in indexed_titles]
    preferred = [row for row in candidates if row["pinned"]]
    lanes = {lane: iter([row for row in candidates if row["lane"] == lane and not row["pinned"]])
             for lane in ("zh", "en")}
    for _ in range(9):
        for lane in ("zh", "en"):
            if paper := next(lanes[lane], None):
                preferred.append(paper)
    preferred[4:4] = preprints[:4]
    return preferred, len(candidates) + len(preprints)


def _collected(results, preferred, reads, discovered):
    screened = []
    evidence = []
    for candidate, reading in zip(preferred, reads):
        metadata = {key: candidate[key] for key in ("title", "doi", "journal", "year", "authors", "issn", "lane", "providers")}
        metadata["publication_type"] = "preprint" if candidate.get("arxiv_id") else "journal"
        if metadata["publication_type"] == "preprint":
            metadata.update(arxiv_id=candidate["arxiv_id"], publication_doi=candidate["publication_doi"])
        result = {**metadata, **reading}
        screened.append({key: result[key] for key in result if key != "sections"})
        if reading["access"] == "full_text" and len(evidence) < 14:
            evidence.append({"id": f"P{len(evidence)+1}", **result})
    return {"target": TARGET, "maximum": MAX_PAPERS, "search": [receipt for receipt, _ in results],
            "discovered": discovered, "screened": screened, "cards": []}, evidence


def collect(queries, source, *, deadline, checkpoint=None):
    """Online discovery with independently durable provider/paper operations.

    Raw HTML/PDF remains transient. Extracted complete text and its source hashes
    enter the design checkpoints; reading is grouped by provider context. A pause never commits a
    partial batch as completed, and accepted operations are not fetched again.
    """
    tasks = _search_tasks(queries, source)
    if checkpoint is None:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda args: _search(*args, deadline), tasks))
            preferred, discovered = _reading_order(results)
            reads = list(pool.map(lambda row: read_online(row, deadline), preferred))
        return _collected(results, preferred, reads, discovered)

    progress = {'version': 'dayan-online-literature-progress-v1', 'phase': 'search',
                'searches_total': len(tasks), 'searches_completed': 0,
                'articles_completed': 0, 'readable_articles': 0}
    checkpoint.record['literature_progress'] = progress
    results = []
    for provider, lane, query in tasks:
        result = checkpoint.operation(
            'literature_lookup', {'provider': provider, 'lane': lane, 'query': query},
            lambda end, p=provider, l=lane, q=query: _search(p, l, q, end),
            seconds=min(12.0, checkpoint.stage_seconds))
        results.append(result)
        progress['searches_completed'] = len(results)
        checkpoint.save()
    preferred, discovered = _reading_order(results)
    progress.update(phase='articles', articles_total=len(preferred), discovered=discovered)
    reads = []
    for candidate in preferred:
        reading = checkpoint.operation(
            'literature_article', {'candidate': candidate},
            lambda end, row=candidate: read_online(row, end),
            seconds=min(24.0, checkpoint.stage_seconds))
        reads.append(reading)
        progress.update(articles_completed=len(reads),
                        readable_articles=sum(row['access'] == 'full_text' for row in reads))
        checkpoint.save()
    result = _collected(results, preferred, reads, discovered)
    progress.update(phase='collected', status='awaiting_paper_review')
    checkpoint.save()
    return result


def summary(record):
    cards = record["cards"]
    journals = [card for card in cards if card["publication_type"] == "journal"]
    return {"status": record.get("status"), "target": record["target"], "reviewed": len(cards),
            "journals": len(journals), "indexed_journals": sum(bool(card["indexes"]) for card in journals),
            "preprints": len(cards) - len(journals)}
