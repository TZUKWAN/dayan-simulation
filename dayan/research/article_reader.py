"""Read publicly accessible journal pages and PDF text in memory."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import html
import io
from http.client import HTTPException
import re
import time
import unicodedata
from urllib.parse import parse_qs, quote, unquote, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree

from bs4 import BeautifulSoup
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from ..collection.connectors import _get

_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6", "title")
_BLOCKS = ("p", "li", "table", "figure", "disp-formula", "blockquote", "math")
_END = re.compile(r"^(?:references|bibliography|参考文献|引用文献)\b", re.I)
_BODY_START = re.compile(r"\b(introduction|background|methods?|methodology|model|results?|discussion|conclusions?|materials)\b"
                         r"|appendix|supplementary|引言|绪论|研究背景|模型|方法|数据|结果|讨论|结论|附录|补充", re.I)
_METHOD = re.compile(r"\b(methods?|methodology|model|modeling|simulation|setup|calibration|data)\b|方法|建模|模型|规则|数据|参数", re.I)
_RESULT = re.compile(r"\b(results?|validation|evaluation|discussion|conclusions?|limitations?|findings)\b"
                     r"|验证|精度|评价|结果|讨论|结论|局限|展望", re.I)
_INDEX_LABEL = re.compile(r"^(?:abstracting(?: and indexing)?|indexing|indexation|abstracted and indexed|"
                          r"期刊收录|数据库收录|收录情况|检索收录|期刊索引|期刊介绍)$", re.I)
_FULLTEXT_LABEL = re.compile(r"^(?:html(?:全文)?|(?:read |view )?(?:the )?full[ -]text(?: article)?|"
                             r"全文(?:阅读|浏览)?|(?:查看|在线阅读)?全文|pdf(?:全文)?)$", re.I)
_ACCESS_ERRORS = (OSError, ValueError, HTTPException, PdfReadError, RecursionError, ElementTree.ParseError)
_GEO_JOURNAL_HOSTS = {"www.geog.com.cn", "www.dlyj.ac.cn", "www.progressingeography.com", "www.resci.cn",
                      "www.dqxxkx.cn"}


def clean(value):
    text = html.unescape(html.unescape(str(value or "")))
    return " ".join(unicodedata.normalize("NFKC", text).split())


def doi_key(value):
    value = unquote(clean(value)).lower()
    match = re.search(r"10\.\d{4,9}/[^\s?#]+", value)
    return match.group().rstrip(".,;，。；") if match else ""


def title_key(value):
    return re.sub(r"[\W_]+", "", clean(value).casefold())


def https_url(value, base=""):
    if not isinstance(value, str) or not value or len(value) > 1400 or re.search(r"[\x00-\x1f\x7f]", value):
        return ""
    try:
        url = urlsplit(urljoin(base, value))
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.port not in (None, 443):
            return ""
        if any(char.isspace() for char in url.hostname):
            return ""
        host = url.hostname.encode("idna").decode("ascii")
        netloc = ("[" + host + "]") if ":" in host else host
        if url.port is not None:
            netloc += ":" + str(url.port)
        # Encode publisher filenames/queries without decoding existing escaped separators.
        path = quote(re.sub(r"%(?![0-9A-Fa-f]{2})", "%25", url.path), safe="/%:@!$&'()*+,;=-._~")
        query = quote(re.sub(r"%(?![0-9A-Fa-f]{2})", "%25", url.query), safe="/%?:@!$&'()*+,;=-._~")
        return urlunsplit(("https", netloc, path, query, ""))
    except (ValueError, UnicodeError):
        return ""


def _meta(soup, *names):
    for name in names:
        node = soup.find("meta", attrs={"name": re.compile(f"^{re.escape(name)}$", re.I)})
        if node and node.get("content"):
            return clean(node["content"])
    return ""


def _confirmed(candidate, document_doi, title):
    expected_doi = candidate["doi"]
    if expected_doi and document_doi:
        return expected_doi == document_doi
    a, b = title_key(candidate["title"]), title_key(title)
    return bool(a and b and (a == b or min(len(a), len(b)) > 25 and (a in b or b in a)))


def _sections(soup):
    root = (soup.select_one(".main_content_center_left_zhengwen_bao_zw, #artbody")
            or soup.select_one(".article-body, .article__body, .articleBody, #article-body, #articleBody, #fulltext")
            or soup.find("article") or soup.find("main") or soup.find("body") or soup)
    for node in root.select("script, style, header, footer, nav, aside, form, iframe, [hidden], .ref-list, .references,"
                            " #abstract, .abstract, .article-abstract, [data-section='abstract']"):
        node.decompose()
    sections = []
    current = None
    for node in root.find_all([*_HEADINGS, *_BLOCKS, "div"]):
        if node.find_parent(_BLOCKS):
            continue
        if node.name in _HEADINGS:
            heading = clean(node.get_text(" ", strip=True))
            if _END.search(heading):
                current = None
                continue
            if current is None and not _BODY_START.search(heading):
                continue
            if heading and len(heading) <= 180:
                anchor = node.get("id") or (node.find_parent("section") or {}).get("id")
                current = {"locator": heading, "anchor": anchor, "paragraphs": []}
                sections.append(current)
        elif current is not None:
            if node.name == "div" and ("mag_rich_body_p" not in node.get("class", [])
                                       or node.find(_BLOCKS)):
                continue
            value = clean(node.get_text(" ", strip=True))
            if len(value) >= 18:
                current["paragraphs"].append(value)
    return [section for section in sections if section["paragraphs"]]


def _compact(sections):
    """Retain every extracted passage; model-context grouping happens downstream."""
    excerpts = []
    for section in sections:
        body = "\n".join(section["paragraphs"])
        excerpts.append({"id": f"S{len(excerpts)+1}", "locator": section["locator"],
                         "anchor": section.get("anchor"), "text": body,
                         "paragraph_count": len(section["paragraphs"]),
                         "sha256": hashlib.sha256(body.encode()).hexdigest()})
    return excerpts


def _full_sections(sections):
    return (sum(sum(map(len, row["paragraphs"])) for row in sections) >= 1600
            and len(sections) >= 2
            and any(_METHOD.search(row["locator"]) for row in sections)
            and any(_RESULT.search(row["locator"]) for row in sections))


def _read_pdf(raw, candidate, deadline):
    doc = PdfReader(io.BytesIO(raw))
    if doc.is_encrypted:
        return []
    pages = []
    for index, page in enumerate(doc.pages, 1):
        if time.monotonic() >= deadline:
            return []
        value = clean(page.extract_text())
        title = title_key(candidate["title"])
        if index == 1 and not (title and title in title_key(value[:4200])
                               or candidate["doi"] and candidate["doi"] in value[:4200].lower()):
            return []
        if len(value) >= 200:
            pages.append({"locator": f"PDF 第 {index} 页", "anchor": f"page={index}", "paragraphs": [value]})
    whole = " ".join(row["paragraphs"][0] for row in pages)
    # A citation, cover sheet, or image-only PDF must not be counted as read.
    if len(pages) < 2 or len(whole) < 3200 or not (_METHOD.search(whole) and _RESULT.search(whole)):
        return []
    return _compact(pages)


def _read_jats(raw, candidate):
    if b"<!ENTITY" in raw.upper():
        return []
    article = ElementTree.fromstring(raw)
    front = article.find(".//{*}article-meta")
    body = article.find("{*}body")
    if front is None or body is None:
        return []
    doi = doi_key(front.findtext("{*}article-id[@pub-id-type='doi']"))
    title = front.find(".//{*}article-title")
    if not _confirmed(candidate, doi, "".join(title.itertext()) if title is not None else ""):
        return []
    sections = []
    for node in body.iterfind(".//{*}sec"):
        heading = clean(node.findtext("{*}title"))
        if heading:
            paragraphs = [clean("".join(child.itertext())) for child in node
                          if child.tag.split("}")[-1] in ("p", "table-wrap", "fig", "disp-formula")]
            if paragraphs:
                sections.append({"locator": heading, "anchor": node.get("id"), "paragraphs": paragraphs})
    return _compact(sections) if _full_sections(sections) else []


def _alternate_locations(candidate):
    """Resolve public full-text variants offered on publishers' own platforms."""
    for position in candidate["locations"]:
        url = urlsplit(position["url"])
        if url.hostname in _GEO_JOURNAL_HOSTS and url.path.endswith("/downloadArticleFile.do"):
            ident = parse_qs(url.query).get("id", [""])[0]
            if ident.isdecimal():
                for issn in candidate.get("issn", []):
                    if re.fullmatch(r"\d{4}-[0-9Xx]{4}", issn):
                        yield {"url": f"https://www.geog.com.cn/CN/abstract/article/{issn}/{ident}",
                               "version": position["version"]}
        if url.hostname == "www.mdpi.com":
            number = re.match(r"/[0-9Xx-]+/(\d+)/\d+/(\d+)(?:/|$)", url.path)
            journal = re.match(r"10\.3390/([a-z]+)\d", candidate["doi"])
            if number and journal:
                slug = {"su": "sustainability", "rs": "remotesensing", "en": "energies",
                        "a": "algorithms", "s": "sensors"}.get(journal[1], journal[1])
                asset = f"{slug}-{int(number[1]):02d}-{int(number[2]):05d}"
                yield {"url": f"https://mdpi-res.com/d_attachment/{slug}/{asset}/article_deploy/{asset}.xml",
                       "version": "published"}


def _article_links(soup, url):
    links = [_meta(soup, "citation_fulltext_html_url")]
    # Some journal sites link HTML from their article record by ISSN and article ID.
    citation = soup.find("a", href=re.compile(r"/article/getTxtFile\.do\?"))
    issn = _meta(soup, "citation_issn")
    if citation and re.fullmatch(r"\d{4}-[0-9Xx]{4}", issn):
        base, _, query = citation["href"].partition("?")
        ident = parse_qs(query).get("id", [""])[0]
        if ident.isdecimal():
            links.append(f"{base.rsplit('/article/', 1)[0]}/abstract/article/{issn}/{ident}")
    links.extend(node["href"] for node in soup.find_all("a", href=True)
                 if _FULLTEXT_LABEL.fullmatch(clean(node.get_text(" ", strip=True))))
    links.append(_meta(soup, "citation_pdf_url"))
    return list(dict.fromkeys(filter(None, (https_url(link, url) for link in links))))[:4]


def _publisher_index(soup, url, deadline):
    links = sorted(soup.find_all("a", href=True), key=lambda node: clean(node.get_text(" ", strip=True)) == "期刊介绍")
    for node in links:
        if not _INDEX_LABEL.fullmatch(clean(node.get_text(" ", strip=True))):
            continue
        index_url = https_url(node["href"], url)
        parsed = urlsplit(index_url)
        if urlsplit(url).hostname == "www.geog.com.cn" and parsed.hostname in _GEO_JOURNAL_HOSTS:
            index_url = urlunsplit(("https", "www.geog.com.cn", parsed.path, parsed.query, ""))
        if not index_url or urlsplit(index_url).hostname != urlsplit(url).hostname or deadline - time.monotonic() < 1:
            continue
        try:
            raw, final = _get(index_url, accept="text/html", timeout=min(2.5, deadline - time.monotonic()), cap=800_000)
        except _ACCESS_ERRORS:
            continue
        page = BeautifulSoup(raw, "html.parser")
        # Only use an explicitly named indexing page supplied by the journal itself.
        if urlsplit(final).hostname != urlsplit(url).hostname:
            return []
        value = clean((page.find("main") or page.find("body") or page).get_text(" ", strip=True))
        patterns = {
            "CSSCI": r"\bCSSCI\b(?![)）\s]*(?:扩展|extension))|中文社会科学引文索引(?!\s*(?:\(CSSCI\)\s*)?扩展)",
            "CSSCI 扩展版": r"\bCSSCI\b[)）\s]*扩展|中文社会科学引文索引\s*(?:\(CSSCI\)\s*)?扩展",
            "CSCD": r"\bCSCD\b|中国科学引文数据库",
            "北大中文核心": r"中文核心期刊|北京大学图书馆.*核心",
            "SSCI": r"\bSSCI\b|Social Sciences Citation Index",
            "SCIE": r"\bSCIE\b|Science Citation Index Expanded",
            "AHCI": r"A\s*&\s*HCI|Arts (?:&|and) Humanities Citation Index",
        }
        return [{"name": name, "source": "journal_index_page", "url": final}
                for name, pattern in patterns.items()
                if re.search(pattern, value, re.I) and not re.search(
                    r"(?:未被|尚未|not (?:currently )?indexed in)\s*(?:" + pattern + ")", value, re.I)]
    return []


def read_online(candidate, deadline):
    seen = set()
    links = [*_alternate_locations(candidate), *candidate["locations"]]
    saw_abstract = False
    last_error = "未找到可直接读取的论文正文"
    journal_indexes = []
    while links and len(seen) < 5 and deadline - time.monotonic() >= .5:
        position = links.pop(0)
        url = https_url(position["url"])
        if not url or url in seen:
            continue
        seen.add(url)
        try:
            raw, final = _get(url, accept="text/html,application/pdf,application/xml,application/xhtml+xml,*/*",
                              timeout=min(4, deadline - time.monotonic()), cap=8_000_000)
            if raw.startswith(b"%PDF-"):
                sections = _read_pdf(raw, candidate, deadline)
                kind = "pdf"
            elif raw.lstrip().startswith(b"<?xml") and b"<article " in raw[:2000]:
                sections = _read_jats(raw, candidate)
                kind = "xml"
            else:
                soup = BeautifulSoup(raw, "html.parser")
                title = _meta(soup, "citation_title", "dc.title") or clean(
                    (soup.find("h1") or soup.find("title") or soup).get_text(" ", strip=True))[:350]
                if not _confirmed(candidate, doi_key(_meta(soup, "citation_doi", "prism.doi", "dc.identifier")), title):
                    last_error = "正文页面的题名或 DOI 未能匹配"
                    continue
                saw_abstract = saw_abstract or bool(_meta(soup, "description", "dc.description")
                                                   or soup.select_one(".abstract, #abstract, [id*='abstract']"))
                full = _sections(soup)
                sections = _compact(full) if _full_sections(full) else []
                if not sections:
                    more = _article_links(soup, final)
                    links = [{"url": link, "version": position["version"]} for link in more if link not in seen] + links
                if not journal_indexes and (sections or saw_abstract) and (
                        not candidate["indexes"] or re.search(r"[\u3400-\u9fff]", title)):
                    journal_indexes = _publisher_index(soup, final, deadline)
                kind = "html"
            if sections:
                version = position["version"]
                if urlsplit(final).hostname in ("arxiv.org", "www.arxiv.org", "export.arxiv.org"):
                    version = "preprint"
                return {"access": "full_text", "format": kind, "url": final,
                        "version": version, "retrieved_at": datetime.now(timezone.utc).isoformat(),
                        "sha256": hashlib.sha256(raw).hexdigest(), "sections": sections,
                        "indexes": candidate["indexes"] + journal_indexes}
        except _ACCESS_ERRORS as exc:
            code = getattr(exc, "code", None)
            last_error = f"HTTP {code}" if code else type(exc).__name__
    return {"access": "abstract_only" if saw_abstract else "unavailable", "reason": last_error,
            "indexes": candidate["indexes"] + journal_indexes}
