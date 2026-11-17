"""协议连接器：每个连接器是 pages() 生成器，产出 (url, raw_bytes, records, meta)。

安全边界（复用 datasets._public_url）：
- 仅公网 HTTPS、无凭据、内网/保留地址拦截、重定向复检；
- 单页大小上限 16MiB（可按来源配置），下载内容只作数据不执行；
- 记录解析失败如实抛错，不静默截断。

分页完整性：meta 须带 total（源端声称总量）或 has_more；engine 据此判 partial。
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Iterator

from ..datasets import _public_url, public_opener

UA_DAYAN = "DAYAN-Research-Workbench/2.4 (research data collection; contact: local-workbench)"
UA_BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
UA = UA_DAYAN                  # 默认礼貌标识
UA_PER_SOURCE = {"wb_indicators": UA_BROWSER, "ilostat_bulk": UA_BROWSER}
DEFAULT_PAGE_CAP = 16 * 1024 * 1024


@dataclass
class Page:
    url: str
    raw: bytes
    records: list[dict] = field(default_factory=list)
    meta: dict = field(default_factory=dict)   # total/has_more/page/next ...
    notes: str = ""


def _get(url: str, *, accept="application/json,text/csv,*/*", timeout=75,
         cap: int = DEFAULT_PAGE_CAP, headers: dict | None = None,
         source_id: str | None = None) -> tuple[bytes, str]:
    _public_url(url)
    ua = UA_PER_SOURCE.get(source_id, UA)
    h = {"User-Agent": ua, "Accept": accept, "Accept-Encoding": "gzip"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with public_opener().open(req, timeout=timeout) as resp:
        data = resp.read(cap + 1)
        if len(data) > cap:
            raise ValueError(f"单页超过 {cap} 字节上限（可调小查询范围或分页）")
        final = resp.geturl()
        if resp.headers.get("Content-Encoding") == "gzip" or data[:2] == b"\x1f\x8b":
            data = gzip.GzipFile(fileobj=io.BytesIO(data)).read(cap + 1)
            if len(data) > cap:
                raise ValueError("解压后内容超过大小上限")
        return data, final


# ============ 结构化统计接口 ============
def worldbank(params: dict, budget: int) -> Iterator[Page]:
    """World Bank Indicators v2：?format=json 分页 [meta, records]。
    注：api.worldbank.org 对默认库 UA 限读，实测需浏览器 UA。"""
    indicator = str(params["indicator"])
    country = str(params.get("country", "all"))
    date = params.get("date", "2015:2024")
    per_page = int(params.get("per_page", 500))
    page = int((params.get("_cursor") or {}).get("page", params.get("page", 1)))
    total = None
    end_page = page + budget
    while page < end_page:
        url = (f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}"
               f"?format=json&date={urllib.parse.quote(date)}&per_page={per_page}&page={page}")
        raw, _ = _get(url, timeout=120, source_id="wb_indicators")
        arr = json.loads(raw)
        meta, rows = (arr if isinstance(arr, list) and len(arr) == 2 else [{}, arr or []])
        total = meta.get("total") if isinstance(meta, dict) else None
        records = [{"country": r.get("country", {}).get("value") if isinstance(r.get("country"), dict) else r.get("country"),
                    "country_id": r.get("countryiso3code"),
                    "date": r.get("date"), "value": r.get("value"),
                    "unit": __import__("dayan.research.request_contract", fromlist=["INDICATORS"]).INDICATORS.get(indicator, {}).get("unit", r.get("unit")),
                    "indicator_label": (r.get("indicator") or {}).get("value") if isinstance(r.get("indicator"), dict) else None,
                    "indicator": indicator} for r in (rows or [])]
        yield Page(url=url, raw=raw, records=records,
                   meta={"total": total, "page": page, "pages": meta.get("pages") if isinstance(meta, dict) else None,
                         "has_more": page < int(meta.get("pages") or 1), "cursor": {"page": page + 1}})
        if total is not None and per_page * page >= total:
            return
        page += 1


def eurostat_jsonstat(params: dict, budget: int) -> Iterator[Page]:
    """Eurostat API v1 JSON-stat：维度过滤 + 展平（含总量上限，防笛卡尔爆炸）。"""
    dataset = str(params["dataset"])
    dims = {k: str(v) for k, v in (params.get("dims") or {}).items()}
    limit = int(params.get("record_cap", 20000))
    q = {"format": "JSON", "lang": "EN"}
    q.update(dims)
    url = ("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
           + urllib.parse.quote(dataset) + "?" + urllib.parse.urlencode(q))
    raw, _ = _get(url)
    data = json.loads(raw)
    ids = data.get("id") or []
    sizes = data.get("size") or []
    values = data.get("value") or {}
    dims_names = [data.get("dimension", {}).get(i, {}).get("label", i) for i in ids]
    cats = [data.get("dimension", {}).get(i, {}).get("category", {}).get("index", {}) or {} for i in ids]
    n = 1
    for s in sizes:
        n *= s
    if n > limit * 10:
        raise ValueError(f"笛卡尔积 {n} 超上限，请加维度过滤（如 time/geo）")
    # 行主序展开
    records = []
    for idx in range(n):
        v = values.get(str(idx))
        if v is None:
            continue
        rem, coords = idx, {}
        for pos in range(len(ids) - 1, -1, -1):
            s = sizes[pos] or 1
            coords[ids[pos]] = list(cats[pos].keys())[rem % s] if cats[pos] else rem % s
            rem //= s
        rec = {dims_names[pos]: coords.get(ids[pos]) for pos in range(len(ids))}
        rec["value"] = v
        rec["dataset"] = dataset
        rec["units"] = (data.get("dimension", {}).get(ids[0], {}).get("category", {})
                        .get("unit") if ids else None)
        records.append(rec)
        if len(records) >= limit:
            yield Page(url=url, raw=raw, records=records,
                       meta={"total": n, "has_more": True,
                             "note": f"record_cap={limit} 截断"}, notes="partial-cap")
            return
    yield Page(url=url, raw=raw, records=records, meta={"total": len(records), "has_more": False})


def unsdg(params: dict, budget: int) -> Iterator[Page]:
    """UN SDG API：indicator 数据分页。"""
    code = str(params["indicator"])
    page = int((params.get("_cursor") or {}).get("page", params.get("page", 1)))
    page_size = int(params.get("page_size", 30))   # >100 会触发服务端500（实测）
    end_page = page + budget
    while page < end_page:
        url = ("https://unstats.un.org/SDGAPI/v1/sdg/Indicator/Data?"
               + urllib.parse.urlencode({"indicatorCode": code, "page": page,
                                         "pageSize": page_size}))
        raw, _ = _get(url)
        data = json.loads(raw)
        rows = data.get("data") or []
        records = [{
            "indicator": code,
            "area": r.get("geoAreaName"), "area_code": r.get("geoAreaCode"),
            "year": r.get("timePeriodStart"), "value": r.get("value"),
            "unit": (r.get("attributes") or {}).get("_units", {}).get("label_display")
            or r.get("unit") or None,
            "series": r.get("series"), "sex": (r.get("dimensions") or {}).get("Sex"),
        } for r in rows]
        yield Page(url=url, raw=raw, records=records,
                   meta={"total": data.get("total"), "page": page,
                         "pages": data.get("pages"), "has_more": page < (data.get("pages") or 1),
                         "cursor": {"page": page + 1}})
        if page >= (data.get("pages") or 1):
            return
        page += 1


def who_gho(params: dict, budget: int) -> Iterator[Page]:
    """WHO GHO OData：/api/{CODE}，OData next 链接。"""
    code = str(params["code"])
    base = f"https://ghoapi.azureedge.net/api/{urllib.parse.quote(code)}"
    url = base + (f"?$filter={urllib.parse.quote(params['filter'])}" if params.get("filter") else "")
    url = (params.get("_cursor") or {}).get("next") or url
    for _ in range(budget):
        raw, _ = _get(url)
        data = json.loads(raw)
        rows = data.get("value") or []
        records = [{"indicator": r.get("IndicatorCode"), "area": r.get("SpatialDim"),
                    "year": r.get("TimeDim"), "value": r.get("NumericValue"),
                    "dim": r.get("Dim1"), "dim_type": r.get("Dim1Type")} for r in rows]
        next_link = data.get("@odata.nextLink")
        yield Page(url=url, raw=raw, records=records,
                   meta={"has_more": bool(next_link), "next": next_link,
                         "total": None, "cursor": {"next": next_link}})
        if not next_link:
            return
        url = next_link


def unesco_uis(params: dict, budget: int) -> Iterator[Page]:
    """UNESCO UIS：/api/public/data/statistics/{data_id}?countries=&years="""
    data_id = str(params["data_id"])
    q = {}
    if params.get("countries"):
        q["countries"] = params["countries"]
    if params.get("years"):
        q["years"] = params["years"]
    url = ("https://api.uis.unesco.org/api/public/data/statistics/"
           + urllib.parse.quote(data_id) + ("?" + urllib.parse.urlencode(q) if q else ""))
    raw, _ = _get(url)
    rows = json.loads(raw)
    records = [{**r, "data_id": data_id} for r in (rows if isinstance(rows, list) else [])]
    yield Page(url=url, raw=raw, records=records,
               meta={"total": len(records), "has_more": False})


def us_census(params: dict, budget: int) -> Iterator[Page]:
    """US Census API：小查询免key。"""
    year = str(params.get("year", "2022"))
    ds = str(params.get("dataset", "acs/acs5"))
    gets = params["get"]
    where = params["for"]
    if params.get("in"):
        where = params["in"] + "&" + where
    url = (f"https://api.census.gov/data/{year}/{ds}?"
           + urllib.parse.urlencode({"get": gets, "for": where})
           + (f"&key={params['key']}" if params.get("key") else ""))
    raw, _ = _get(url)
    rows = json.loads(raw)
    header, body = rows[0], rows[1:]
    records = [dict(zip(header, r)) for r in body]
    yield Page(url=url, raw=raw, records=records,
               meta={"total": len(records), "has_more": False})


def oecd_sdmx(params: dict, budget: int) -> Iterator[Page]:
    """OECD SDMX：dataflow 数据 CSV 输出（结构数据返回则由调用方核对）。"""
    flow = str(params["dataflow"])
    key = urllib.parse.quote(params.get("key", "all"), safe="")
    fmt = params.get("format", "csvfilewithlabels")
    start, end = params.get("startPeriod", "2018"), params.get("endPeriod", "2024")
    url = (f"https://sdmx.oecd.org/public/rest/data/{flow}/{key}/{start}/{end}"
           f"?format={fmt}&detail=dataonly")
    raw, _ = _get(url, accept="text/csv")
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    yield Page(url=url, raw=raw, records=rows,
               meta={"total": len(rows), "has_more": False})


# ============ 批量文件 ============
def ilostat_bulk(params: dict, budget: int) -> Iterator[Page]:
    """ILOSTAT SDMX（官方 sdmx.ilo.org）：维度元数据发现 → 自动拼键 → CSV。

    流程（任务书 §3.3 结构化接口：字段/码表/维度元数据发现）：
    1. dataflow 列表按名称模糊定位（如 employment→DF_EMP_TEMP*）；
    2. 取该 flow 引用的 DSD，学维度顺序；
    3. FREQ=A、REF_AREA=CHN 定位，其余维度通配，CSV 输出。
    """
    indicator = str(params.get("indicator", ""))     # 用户可给 flow id 或关键词
    ref = str(params.get("ref_area", "CHN"))
    raw, _ = _get("https://sdmx.ilo.org/rest/dataflow/ILO/all?format=json",
                  timeout=90, source_id="ilostat_bulk")
    refs = json.loads(raw).get("references", {})
    flows = {v["id"]: v for v in refs.values()}
    target = indicator if indicator in flows else None
    if target is None:
        kw = (indicator or "EMP_TEMP").upper()
        cands = sorted(i for i in flows if kw in i)
        if not cands:
            raise ValueError(f"ILO 无匹配 dataflow {kw!r}；样例: {sorted(flows)[:8]}")
        target = cands[0]
    # DSD 维度发现
    flow_ref = flows[target].get("urn", "")
    dsd_urn = ""
    for urn, obj in refs.items():
        pass
    dsd_url = (f"https://sdmx.ilo.org/rest/dataflow/ILO,{target}/"
               "?format=json&references=all")
    raw2, _ = _get(dsd_url, timeout=90, source_id="ilostat_bulk")
    refs2 = json.loads(raw2).get("references", {})
    dsd_ids = [v["id"] for v in refs2.values()
               if "DataStructure" in v.get("urn", "")]
    if not dsd_ids:
        raise ValueError(f"{target} 未返回 DSD 引用")
    dsd_url2 = f"https://sdmx.ilo.org/rest/datastructure/ILO,{dsd_ids[0]}/?format=json"
    raw3, _ = _get(dsd_url2, timeout=90, source_id="ilostat_bulk")
    dsd = json.loads(raw3)
    dims = []
    for obj in dsd.get("references", {}).values():
        if "DimensionList" in obj.get("urn", ""):
            dims = [d_["id"] for d_ in obj.get("dimensions", [])]
            break
    if not dims:
        raise ValueError(f"DSD {dsd_ids[0]} 无维度列表")
    # 组键：FREQ=A；REF_AREA 在其位；其余通配
    key_parts = []
    for dim in dims:
        if dim.upper() == "FREQ":
            key_parts.append("A")
        elif dim.upper() in ("REF_AREA", "COUNTRY", "REPORTING_AREA"):
            key_parts.append(ref)
        else:
            key_parts.append("")
    url = (f"https://sdmx.ilo.org/rest/data/ILO,{target}/"
           + urllib.parse.quote(".".join(key_parts), safe="._")
           + f"?format=csv&detail=dataonly&startPeriod={params.get('startPeriod', '2018')}")
    raw4, _ = _get(url, timeout=120, accept="text/csv,*/*", source_id="ilostat_bulk")
    rows = list(csv.DictReader(io.StringIO(raw4.decode("utf-8-sig"))))
    yield Page(url=url, raw=raw4, records=rows,
               meta={"total": len(rows), "has_more": False,
                     "flow": target, "dims": dims})


# ============ 文献 / 事件 / 文本 ============
def crossref(params: dict, budget: int) -> Iterator[Page]:
    """Crossref works 检索（polite pool 带 mailto）。"""
    q = {"query": params["query"], "rows": str(params.get("rows", 50)),
         "offset": str((params.get("_cursor") or {}).get("offset", 0))}
    if params.get("mailto"):
        q["mailto"] = params["mailto"]
    if params.get("filter"):
        q["filter"] = params["filter"]
    base = "https://api.crossref.org/works?"
    total = None
    while budget > 0:
        url = base + urllib.parse.urlencode(q)
        raw, _ = _get(url)
        data = json.loads(raw).get("message", {})
        items = data.get("items") or []
        total = data.get("total-results")
        records = [{
            "doi": it.get("DOI"), "title": (it.get("title") or [None])[0],
            "author": [(a.get("given", "") + " " + a.get("family", "")).strip()
                       for a in it.get("author", [])][:5],
            "year": ((it.get("issued") or {}).get("date-parts") or [[None]])[0][0],
            "container": (it.get("container-title") or [None])[0],
            "type": it.get("type"), "publisher": it.get("publisher"),
            "url": it.get("URL")} for it in items]
        yield Page(url=url, raw=raw, records=records,
                   meta={"total": total, "has_more":
                         bool(total and int(q["offset"]) + int(q["rows"]) < total),
                         "cursor": {"offset": int(q["offset"]) + int(q["rows"])}})
        if total is None or int(q["offset"]) + int(q["rows"]) >= (total or 0):
            return
        q["offset"] = str(int(q["offset"]) + int(q["rows"]))
        budget -= 1


def openalex(params: dict, budget: int) -> Iterator[Page]:
    """OpenAlex works 检索（mailto polite pool）。"""
    q = {"search": params["search"], "per-page": str(params.get("per_page", 50))}
    if params.get("mailto"):
        q["mailto"] = params["mailto"]
    if params.get("filter"):
        q["filter"] = params["filter"]
    base = "https://api.openalex.org/works?"
    page = int((params.get("_cursor") or {}).get("page", params.get("page", 1)))
    total = None
    end_page = page + budget
    while page < end_page:
        url = base + urllib.parse.urlencode(q) + f"&page={page}"
        raw, _ = _get(url)
        data = json.loads(raw)
        total = data.get("meta", {}).get("count")
        records = [{
            "id": it.get("id"), "doi": it.get("doi"),
            "title": it.get("display_name"),
            "year": it.get("publication_year"),
            "cited_by": it.get("cited_by_count"),
            "authors": [a.get("author", {}).get("display_name")
                        for a in it.get("authorships", [])][:5],
            "venue": (it.get("primary_location") or {}).get("source", {}).get("display_name")
            if isinstance((it.get("primary_location") or {}).get("source"), dict) else None,
        } for it in data.get("results", [])]
        yield Page(url=url, raw=raw, records=records,
                   meta={"total": total, "page": page,
                         "has_more": total is not None and page * int(q["per-page"]) < total,
                         "cursor": {"page": page + 1}})
        if total is not None and page * int(q["per-page"]) >= total:
            return
        page += 1


def huggingface_datasets(params: dict, budget: int) -> Iterator[Page]:
    """Hugging Face Datasets API：公开仓库检索（免key；部分数据集需gate同意）。"""
    if params.get("repo_id"):
        repo=str(params["repo_id"])
        import re
        if not re.fullmatch(r"[\w.-]+/[\w.-]+",repo):raise ValueError("非法公开仓库ID")
        url="https://huggingface.co/api/datasets/"+repo
        raw,_=_get(url);info=json.loads(raw)
        records=[{"repo_id":repo,"filename":f["rfilename"],"revision":info.get("sha"),
                  "gated":info.get("gated"),"private":info.get("private"),
                  "license":(info.get("cardData") or {}).get("license","unknown")} for f in info.get("siblings",[])]
        yield Page(url=url,raw=raw,records=records,meta={"total":len(records),"has_more":False,
                   "artifact_role":"catalog_only","scope":"repository file inventory, not downloaded observations"})
        return
    q = {"search": params["search"], "limit": str(params.get("limit", 20))}
    url = "https://huggingface.co/api/datasets?" + urllib.parse.urlencode(q)
    raw, _ = _get(url, source_id="huggingface")
    rows = json.loads(raw)
    records = [{"id": r.get("id"), "author": (r.get("author") or ""),
                "downloads": r.get("downloads"), "likes": r.get("likes"),
                "tags": (r.get("tags") or [])[:8],
                "license": next((t.split(":")[1] for t in (r.get("tags") or [])
                                 if t.startswith("license:")), None),
                "gated": r.get("gated"), "private": r.get("private")} for r in rows]
    yield Page(url=url, raw=raw, records=records,
               meta={"total": None, "has_more": len(records)>=int(q["limit"]),
                     "artifact_role":"catalog_only", "scope":"bounded public search, not exhaustive; narrow search or use repo_id"})


class _HTMLExtract:
    """stdlib HTML 解析：提取标题、含数字的统计段落与链接（不做猜测补表）。"""
    def __init__(self):
        from html.parser import HTMLParser
        class P(HTMLParser):
            def __init__(self2):
                super().__init__()
                self2.title = ""
                self2._in_title = False
                self2.text = []
                self2.links = []
                self2._skip = 0
            def handle_starttag(self2, tag, attrs):
                if tag in ("script", "style"):
                    self2._skip += 1
                if tag == "title":
                    self2._in_title = True
                if tag == "a":
                    for k, v in attrs:
                        if k == "href" and v:
                            self2.links.append(v)
            def handle_endtag(self2, tag):
                if tag in ("script", "style") and self2._skip:
                    self2._skip -= 1
                if tag == "title":
                    self2._in_title = False
            def handle_data(self2, data):
                if self2._in_title:
                    self2.title += data
                if not self2._skip and data.strip():
                    self2.text.append(data.strip())
        self.parser = P()

    def run(self, raw: bytes):
        try:
            self.parser.feed(raw.decode("utf-8"))
        except UnicodeDecodeError:
            self.parser.feed(raw.decode("gb18030", errors="replace"))
        return self.parser

    def paragraphs(self, min_len: int = 30) -> list[str]:
        """将碎片化 text 段合并为连贯段落（按句子终止符/长度切分）。

        NBS 等政府网站将数字和文字放在不同 <span>/<td> 中，HTMLParser
        按元素逐段产出导致「教育 5.6」变成两段。本方法将相邻段合并到
        句号/分号/段落边界，恢复可分析的完整句子。"""
        result = []
        buf = []
        for t in self.parser.text:
            buf.append(t)
            joined = "".join(buf)
            # 句子终止：中文句号、长段落后段落边界
            if any(joined.rstrip().endswith(c) for c in ("。", "；", "！")) and len(joined) >= min_len:
                result.append(joined)
                buf = []
            elif len(joined) > 200:   # 长段落也切（防止整页合并成一段）
                result.append(joined)
                buf = []
        if buf:
            tail = "".join(buf)
            if len(tail) >= min_len // 2:
                result.append(tail)
        return result


def web_page(params: dict, budget: int) -> Iterator[Page]:
    """公开 HTML 页面采集：统计公报/栏目。产出三类记录：
    numeric_stat：含"数字+单位(万人/％/亿元等)"的文本段（保留原句，不做表格猜测）；
    link：文章链接列表（栏目页→正文页发现）；
    doc：正文文本块（文本证据用）。"""
    import re as _re
    url = str(params["url"])
    extract_links = bool(params.get("extract_links", False))
    min_len = int(params.get("min_text_len", 20))
    raw, _ = _get(url, accept="text/html,*/*", timeout=60,
                  headers={"Accept": "text/html"}, source_id=params.get("source_id"))
    ex = _HTMLExtract(); ex.run(raw)
    # 使用合并段落（碎片化元素恢复为完整句子）
    paras = ex.paragraphs(min_len=min_len)
    num_pat = _re.compile(r"[-+]?\d+(?:\.\d+)?\s*(?:万人|亿人|万人|%|％|亿元|万亿元|万个|万所|人次|万公里的?|千亿美元|亿美元|万亿美元)")
    pop_context = _re.compile(r"人口|就业|出生|死亡|城镇化|劳动力|失业|增长|GDP|收入", _re.I)
    records = []
    for para in paras:
        if num_pat.search(para):
            records.append({"type": "numeric_stat", "text": para[:400], "url": url,
                             "has_pop_context": bool(pop_context.search(para))})
    if extract_links:
        for lnk in ex.parser.links:
            if _re.search(r"t\d{8}_\d+\.html|/\d{4}[-/]\d{2}[-/]\d+|tjgb", lnk):
                records.append({"type": "link", "url": urllib.parse.urljoin(url, lnk)})
    if params.get("full_text") and records:
        # 全文分块（每块8段、最多80块，覆盖完整公报正文）
        blocks = [" ".join(ex.parser.text[i:i+8]) for i in range(0, len(ex.parser.text), 8)]
        records.append({"type": "doc", "title": ex.parser.title[:100],
                        "text": chr(10).join(b[:500] for b in blocks[:80]), "url": url})
    # 主题提取：按参数 keywords 过滤包含关键词的数值段
    keywords = params.get("keywords") or []
    if keywords:
        for para in ex.parser.text:
            if num_pat.search(para) and any(kw in para for kw in keywords):
                records.append({"type": "topic_stat",
                                "text": para[:400], "url": url,
                                "keywords": [kw for kw in keywords if kw in para]})
    if not records:
        records.append({"type": "doc", "title": ex.parser.title[:100],
                        "text": " ".join(ex.parser.text)[:600], "url": url})
    yield Page(url=url, raw=raw, records=records,
               meta={"total": len(records), "has_more": False,
                     "page_title": ex.parser.title[:80]})


def gdelt_doc(params: dict, budget: int) -> Iterator[Page]:
    """GDELT 2.0 文档 API：artlist JSON，15分钟窗+timespan。"""
    q = {"query": params["query"], "mode": params.get("mode", "artlist"),
         "format": "json", "maxrecords": str(params.get("maxrecords", 75)),
         "timespan": params.get("timespan", "1d")}
    if params.get("sourcelang"):
        q["sourcelang"] = params["sourcelang"]
    url = "https://api.gdeltproject.org/api/v2/doc/doc?" + urllib.parse.urlencode(q)
    raw, _ = _get(url, accept="application/json")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        yield Page(url=url, raw=raw, records=[],
                   meta={"total": 0, "has_more": False}, notes="非JSON响应（通常为空结果提示）")
        return
    records = [{"title": a.get("title"), "url": a.get("url"),
                "domain": a.get("domain"), "lang": a.get("sourcecountry"),
                "seendate": a.get("seendate")} for a in data.get("articles", [])]
    yield Page(url=url, raw=raw, records=records,
               meta={"total": len(records), "has_more": False})


def wikidata_sparql(params: dict, budget: int) -> Iterator[Page]:
    """Wikidata SPARQL：UA 必须，结果 SPARQL-JSON 展平。"""
    query = params["query"]
    url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": query, "format": "json"})
    raw, _ = _get(url, accept="application/sparql-results+json")
    data = json.loads(raw)
    binds = data.get("results", {}).get("bindings", [])
    records = [{k: v.get("value") for k, v in b.items()} for b in binds]
    yield Page(url=url, raw=raw, records=records,
               meta={"total": len(records), "has_more": False})


# ============ 开放门户 ============
def socrata(params: dict, budget: int) -> Iterator[Page]:
    """Socrata：resource 端点 + $limit/$offset（X-Total-Count 完整性）。"""
    host = str(params["host"]).rstrip("/")
    resource = str(params["resource"])
    limit = int(params.get("limit", 100))
    offset = int((params.get("_cursor") or {}).get("offset", params.get("offset", 0)))
    soql = params.get("soql") or ""
    while budget > 0:
        host = host if host.startswith("http") else "https://" + host.split("/")[0] if "/" in host else "https://" + host
        url = f"https://{host.split('//')[-1]}/resource/{resource}.json?$limit={limit}&$offset={offset}"
        if soql:
            url += "&" + soql if soql.startswith("$") else "&" + urllib.parse.urlencode({"$where": soql})
        raw, _ = _get(url)
        rows = json.loads(raw)
        yield Page(url=url, raw=raw, records=rows, meta={"has_more": len(rows) == limit,
                                                         "total": None, "cursor": {"offset": offset + limit}})
        if len(rows) < limit:
            return
        offset += limit
        budget -= 1


def ckan_search(params: dict, budget: int) -> Iterator[Page]:
    """CKAN：package_search 目录检索（数据集级；资源下载走 fetch_url）。"""
    instance = str(params["instance"]).rstrip("/")
    if not instance.startswith("http"):
        instance = "https://" + instance       # 允许裸域名，规范化为 HTTPS
    q = {"q": params["q"], "rows": str(params.get("rows", 20)), "start": str((params.get("_cursor") or {}).get("start", 0))}
    total = None
    while budget > 0:
        url = instance + "/api/3/action/package_search?" + urllib.parse.urlencode(q)
        raw, _ = _get(url)
        data = json.loads(raw).get("result", {})
        total = data.get("count")
        records = [{"id": p.get("id"), "name": p.get("name"), "title": p.get("title"),
                    "organization": (p.get("organization") or {}).get("title"),
                    "notes": (p.get("notes") or "")[:300],
                    "license": p.get("license_title"),
                    "resources": [{"url": r.get("url"), "format": r.get("format"), "resource_id": r.get("id"),
                                   "name": r.get("name")} for r in p.get("resources", [])][:200],
                    "resources_truncated": len(p.get("resources", [])) > 200,
                    "num_resources": p.get("num_resources")} for p in data.get("results", [])]
        yield Page(url=url, raw=raw, records=records,
                   meta={"total": total, "has_more": int(q["start"]) + int(q["rows"]) < (total or 0),
                         "cursor": {"start": int(q["start"]) + int(q["rows"])}})
        if int(q["start"]) + int(q["rows"]) >= (total or 0):
            return
        q["start"] = str(int(q["start"]) + int(q["rows"]))
        budget -= 1


def _file_page(url, format, *, provenance=None, archive_member=None):
    raw, final = _get(url)
    format = str(format).lower().removesuffix(".zip")
    payload = raw
    provenance = dict(provenance or {})
    if raw.startswith(b"PK\x03\x04"):
        import zipfile
        import hashlib
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members=archive.infolist()
            if len(members)>200: raise ValueError("压缩包条目超过200，须缩小资源")
            candidates=[m for m in members if not m.is_dir() and m.filename.lower().endswith("."+format)]
            if archive_member:
                candidates=[m for m in candidates if m.filename==archive_member]
            if len(candidates)!=1:
                raise ValueError("压缩包须明确唯一数据文件archive_member；可选："+str([m.filename for m in candidates[:12]]))
            member=candidates[0]
            if member.flag_bits & 1 or member.file_size>DEFAULT_PAGE_CAP or ".." in member.filename.replace("\\", "/").split("/"):
                raise ValueError("压缩成员加密、路径非法或解压大小超过16MiB")
            with archive.open(member) as f: payload=f.read(DEFAULT_PAGE_CAP+1)
            if len(payload)>DEFAULT_PAGE_CAP: raise ValueError("解压数据超过16MiB")
            provenance.update(archive_member=member.filename,payload_sha256=hashlib.sha256(payload).hexdigest(),
                              archive_note="仅内存读取指定表格；不提取文件，不执行内容")
    if payload.lstrip().lower().startswith((b"<!doctype html", b"<html")):
        raise ValueError("实际返回HTML，不能将门户/登录页当表格资源")
    if format == "csv":
        reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError("CSV缺少唯一字段标题")
        records = list(reader)
        if any(None in r for r in records):
            raise ValueError("CSV列数不一致")
    elif format in ("json", "geojson", "jsonl"):
        if format == "jsonl":
            records = [json.loads(line) for line in payload.decode("utf-8-sig").splitlines() if line.strip()]
        else:
            data = json.loads(payload)
            if isinstance(data, list):
                records = data
            elif isinstance(data, dict) and data.get("type") == "FeatureCollection":
                records = [{**f.get("properties", {}), "geometry": f.get("geometry")} for f in data["features"]]
            else:
                records = data.get("data") if isinstance(data, dict) else None
    else:
        raise ValueError("仅下载并解析CSV/JSON/JSONL/GeoJSON，不执行脚本或自动解包")
    if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
        raise ValueError("资源必须是可解析的表格记录，目录/HTML/错误响应不能当作数据")
    if len(records) > 100000:
        raise ValueError("记录数超过10万，请缩小资源或通过分页接口获取")
    return Page(url=final, raw=raw, records=records,
                meta={"total": len(records), "has_more": False, "artifact_role": "dataset",
                      "provenance": provenance})


def resource_file(params, budget):
    yield _file_page(params["url"], params["format"], provenance={
        "source_id": params.get("source_id"), "license": params.get("license", "unknown")},archive_member=params.get("archive_member"))


def huggingface_file(params, budget):
    """Explicit repository/file only. Search relevance is never inferred from download counts."""
    import re
    repo, filename = str(params["repo_id"]), str(params["filename"])
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo) or ".." in filename.split("/") or filename.startswith("/"):
        raise ValueError("非法仓库或资源路径")
    meta_url = "https://huggingface.co/api/datasets/" + repo
    raw, _ = _get(meta_url)
    info = json.loads(raw)
    if info.get("private") or info.get("gated"):
        raise ValueError("此数据集需要私有权限/同意授权，未下载；请选择公开可用资源")
    if filename not in {f["rfilename"] for f in info.get("siblings", [])}:
        raise ValueError("文件不存在，请先查看仓库实际文件清单")
    revision = info.get("sha")
    if not revision:
        raise ValueError("仓库未提供不可变版本SHA")
    url = f"https://huggingface.co/datasets/{repo}/resolve/{revision}/" + urllib.parse.quote(filename, safe="/")
    yield _file_page(url, params.get("format") or filename.rsplit(".", 1)[-1], provenance={
        "repo_id": repo, "revision": revision, "filename": filename,
        "license": (info.get("cardData") or {}).get("license", "unknown"), "metadata_url": meta_url},archive_member=params.get("archive_member"))


def ckan_resource(params, budget):
    instance = str(params["instance"]).removeprefix("https://").rstrip("/")
    resource_id = str(params["resource_id"])
    base = "https://" + instance + "/api/3/action/"
    raw, _ = _get(base + "resource_show?" + urllib.parse.urlencode({"id": resource_id}))
    info = json.loads(raw)
    if not info.get("success"):
        raise ValueError("CKAN资源查询失败")
    resource = info["result"]
    raw, _ = _get(base + "package_show?" + urllib.parse.urlencode({"id": resource["package_id"]}))
    package = json.loads(raw).get("result", {})
    if package.get("private"):
        raise ValueError("资源属于私有数据集，未下载")
    yield _file_page(resource["url"], params.get("format") or resource.get("format", ""), provenance={
        "instance": instance, "resource_id": resource_id, "package_id": resource["package_id"],
        "license": package.get("license_id", "unknown"), "last_modified": resource.get("last_modified")},archive_member=params.get("archive_member"))


CONNECTORS = {
    "worldbank": worldbank, "eurostat_jsonstat": eurostat_jsonstat,
    "unsdg": unsdg, "who_gho": who_gho, "unesco_uis": unesco_uis,
    "us_census": us_census, "oecd_sdmx": oecd_sdmx,
    "ilostat_bulk": ilostat_bulk,
    "crossref": crossref, "openalex": openalex, "gdelt_doc": gdelt_doc,
    "wikidata_sparql": wikidata_sparql,
    "socrata": socrata, "ckan_search": ckan_search,
    "huggingface_datasets": huggingface_datasets,
    "web_page": web_page,
    "resource_file": resource_file, "huggingface_file": huggingface_file, "ckan_resource": ckan_resource,
}

CONNECTOR_SOURCE = {   # 连接器 → 主要来源（可一对多）
    "huggingface_file": "huggingface",
    "worldbank": "wb_indicators", "eurostat_jsonstat": "eurostat",
    "unsdg": "unsdg", "who_gho": "who_gho", "unesco_uis": "unesco_uis",
    "us_census": "us_census", "oecd_sdmx": "oecd_sdmx",
    "ilostat_bulk": "ilostat_bulk", "crossref": "crossref",
    "openalex": "openalex", "gdelt_doc": "gdelt", "wikidata_sparql": "wikidata",
    "socrata": "socrata", "ckan_search": None,   # instance 参数决定来源
    "huggingface_datasets": "huggingface",
    "web_page": None,   # params.source_id 指定
}
