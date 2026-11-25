"""主题采集预设：自然语言可驱动的参数模板（任务书 §3.1/§C0）。

每个预设：preset_id、主题、默认连接器+参数模板、占位符说明、地区/时间映射。
用户给主题+地区+时间即可运行，不需要懂 URL/API。
"""
from __future__ import annotations

# 地区常见别名 → 连接器参数（渐进扩充；不代表穷尽）
REGION_MAP = {
    "worldbank": {"中国": "CHN", "美国": "USA", "欧盟": "EUU", "印度": "IND", "加拿大": "CAN",
                  "日本": "JPN", "德国": "DEU", "英国": "GBR", "巴西": "BRA"},
    "unsdg": {"中国": "CHN", "美国": "USA", "印度": "IND"},
    "eurostat": {"欧盟": "EU27_2020", "德国": "DE", "法国": "FR", "意大利": "IT"},
    "us_census": {"美国": "state:*"},
    "ilostat_bulk": {"中国": "CHN", "美国": "USA"},
    "oecd_sdmx": {"中国": "CHN", "美国": "USA", "欧盟": "OECD"},
}

PRESETS = [
    {"preset_id":"park_visit_speeds", "theme":"旅游景区步行",
     "title":"开放实测 · 景区日常游客步速", "connector":"park_visit_speeds", "params_template":{},
     "placeholders":{}, "topics":["景区", "游客", "旅游", "踩踏", "步速"],
     "evidence":{"reference":"https://doi.org/10.5281/zenodo.20748587", "field":"avg_speed_mps", "unit":"m/s",
                 "input_role":"input", "reference_aggregate":"mean",
                 "use":"日常访问平均步速可用于疏散模型的目标步速参考，事故行为和场地仍须独立核验"},
     "acceptance":"核对发布哈希、已分析样本与步速口径"},
    {"preset_id": "pop_employment_wb", "theme": "人口与就业",
     "title": "世界银行 人口/就业指标（国家级，年度）",
     "connector": "worldbank",
     "params_template": {"indicator": "{indicator}", "country": "{country}",
                          "date": "{year_from}:{year_to}"},
     "indicator_options": {
         "人口总量": "SP.POP.TOTL", "人口增长": "SP.POP.GROW",
         "城镇人口占比": "SP.URB.TOTL.IN.ZS", "老龄化(65+)": "SP.POP.65UP.TO.ZS",
         "失业率ILO": "SL.UEM.TOTL.ZS", "劳动力参与": "SL.TLF.CACT.ZS",
         "人均GDP": "NY.GDP.PCAP.CD", "出生率": "SP.DYN.CBRT.IN",
         "死亡率": "SP.DYN.CDRT.IN", "生育率": "SP.DYN.TFRT.IN"},
     "placeholders": {"country": "国家（如 中国→CHN）", "year_from": "起始年",
                       "year_to": "结束年", "indicator": "指标（见 indicator_options）"},
     "region_map": "worldbank",
     "acceptance": "分页完整性由 meta.total 核验"},
    {"preset_id": "employment_data360", "theme": "人口与就业",
     "title": "世界银行 Data360 · WDI 年度失业率",
     "connector": "worldbank_data360",
     "params_template": {"indicator": "SL.UEM.TOTL.ZS","country": "{country}","date": "{year_from}:{year_to}"},
     "placeholders": {"country": "国家 ISO3（如 CAN）","year_from": "起始年","year_to": "结束年"},
     "region_map":"worldbank","acceptance":"同一 WDI 指标，核对返回总数、总体、年度和占劳动力百分比"},
    {"preset_id": "sdg_indicator", "theme": "SDG 可持续发展指标",
     "title": "UN SDG 指标数据（国家级，年度）",
     "connector": "unsdg",
     "params_template": {"indicator": "{indicator}", "page_size": 500},
     "indicator_options": {
         "贫困率": "1-1-1", "饥饿": "2-1-1", "孕产妇死亡": "3-1-1",
         "教育入学": "4-1-1", "性别平等": "5-5-1", "饮水安全": "6-1-1",
         "失业率SDG": "8-5-2"},
     "placeholders": {"indicator": "SDG 指标编号（如 8-5-2）"},
     "region_map": "unsdg",
     "acceptance": "pageSize 分页，pages 字段核验"},
    {"preset_id": "eurostat_regional", "theme": "欧洲区域统计",
     "title": "Eurostat 数据集（国家/NUTS，JSON-stat）",
     "connector": "eurostat_jsonstat",
     "params_template": {"dataset": "{dataset}",
                          "dims": {"time": "{year}", "geo": "{geo}"}},
     "indicator_options": {
         "人口": "demo_pjan", "失业率月度": "une_rt_m",
         "失业率年度": "une_rt_a", "就业率": "lfsi_emp_a",
         "初等教育师生比": "educ_uoe_enrl1s"},
     "placeholders": {"dataset": "数据集代码", "geo": "地区码", "year": "年份"},
     "region_map": "eurostat",
     "acceptance": "record_cap 防笛卡尔爆炸；总量=展平非空值数"},
    {"preset_id": "ilostat_employment", "theme": "劳动与就业",
     "title": "ILOSTAT 指标 CSV（国家级）",
     "connector": "ilostat_bulk",
     "params_template": {"indicator": "{indicator}", "ref_area": "{country}"},
     "indicator_options": {
         "就业人数": "EMP_TEMP_SEX_STE_IFES_NB_A",
         "失业人数": "UNEMP_TEMP_SEX_AGE_STE_NB_A",
         "劳动参与率": "LFPR_15P64_SEX_RT_A"},
     "placeholders": {"indicator": "ILO 指标代码", "country": "ISO3 国家码"},
     "region_map": "ilostat_bulk",
     "acceptance": "CSV 流解析，行数=记录数"},
    {"preset_id": "health_who", "theme": "公共卫生",
     "title": "WHO GHO 指标（OData）",
     "connector": "who_gho",
     "params_template": {"code": "{indicator}"},
     "indicator_options": {
         "人均预期寿命": "WHOSIS_000001", "五岁以下死亡率": "MORT_1",
         "医务人员密度": "HWFH_6", "卫生总支出占比": "GHED_CHEXP1"},
     "placeholders": {"indicator": "GHO 指标代码"},
     "acceptance": "OData next 链接续采"},
    {"preset_id": "education_uis", "theme": "教育",
     "title": "UNESCO UIS 教育统计",
     "connector": "unesco_uis",
     "params_template": {"data_id": "{data_id}", "countries": "{country}",
                          "years": "{year_from}..{year_to}"},
     "indicator_options": {
         "入学率": "XGDP_F_GPI?indicator=SESEC", "识字率": "XGDP_LIT"},
     "placeholders": {"data_id": "UIS data_id", "country": "ISO3"},
     "acceptance": "返回数组行数"},
    {"preset_id": "literature_crossref", "theme": "学术文献",
     "title": "Crossref 文献检索（主题+年份过滤）",
     "connector": "crossref",
     "params_template": {"query": "{query}", "rows": 50,
                          "filter": "{filter}"},
     "placeholders": {"query": "检索词", "filter": "如 from-pub-date:2020-01-01"},
     "acceptance": "total-results 与已取条数比对，partial 如实标记"},
    {"preset_id": "literature_openalex", "theme": "学术文献（开放版）",
     "title": "OpenAlex 主题文献",
     "connector": "openalex",
     "params_template": {"search": "{query}", "per_page": 50},
     "placeholders": {"query": "检索词"},
     "acceptance": "meta.count 核验"},
    {"preset_id": "policy_media_gdelt", "theme": "政策与新闻事件",
     "title": "GDELT 新闻文章流（主题词，最近窗口）",
     "connector": "gdelt_doc",
     "params_template": {"query": "{query}", "timespan": "{timespan}"},
     "placeholders": {"query": "检索词（GDELT 语法）", "timespan": "如 1d/1w"},
     "acceptance": "空结果如实返回（非JSON提示）"},
    {"preset_id": "us_public_services", "theme": "公共服务（美国开放平台）",
     "title": "Socrata 城市开放数据集",
     "connector": "socrata",
     "params_template": {"host": "{host}", "resource": "{resource}",
                          "limit": 200},
     "placeholders": {"host": "如 data.cityofnewyork.us",
                       "resource": "4x4 标识"},
     "acceptance": "$limit/$offset 分页"},
    {"preset_id": "portal_search", "theme": "开放门户检索",
     "title": "CKAN/HDX 数据集目录搜索",
     "connector": "ckan_search",
     "params_template": {"instance": "{instance}", "q": "{query}", "rows": 20},
     "placeholders": {"instance": "如 data.humdata.org",
                       "query": "检索词（如 population china）"},
     "acceptance": "result.count 与已取数比对"},
    {"preset_id": "wikidata_history", "theme": "历史与文化",
     "title": "Wikidata SPARQL 实体查询",
     "connector": "wikidata_sparql",
     "params_template": {"query": "{query}"},
     "placeholders": {"query": "SPARQL（须含 LIMIT）"},
     "acceptance": "绑定行数"},
]


def list_presets() -> list[dict]:
    return PRESETS


def get_preset(preset_id: str) -> dict | None:
    for p in PRESETS:
        if p["preset_id"] == preset_id:
            return p
    return None


def resolve_params(preset: dict, values: dict) -> dict:
    """占位符 → 连接器参数；地区别名按 REGION_MAP 自动映射。"""
    template = preset["params_template"]
    values = dict(values or {})
    import json
    tokens = set(_tokens(json.dumps(template)))
    extra = set(values) - tokens
    if extra:
        raise ValueError(f"预设不接受参数{sorted(extra)}，不会静默忽略；请用对应协议连接器")
    for key in ("country", "geo"):
        if key in values:
            values[key] = REGION_MAP.get(preset.get("region_map"), {}).get(str(values[key]), values[key])
    for key in ("indicator", "dataset"):
        if key in values:
            values[key] = preset.get("indicator_options", {}).get(values[key], values[key])
    if "year_from" in values and "year_to" in values and int(values["year_from"]) > int(values["year_to"]):
        raise ValueError("起始年份不得晚于结束年份")
    def fill(item):
        if isinstance(item, dict): return {k:fill(v) for k,v in item.items()}
        if isinstance(item, list): return [fill(v) for v in item]
        if not isinstance(item, str): return item
        for key in _tokens(item):
            if key not in values or str(values[key]).strip() == "":
                raise ValueError(f"预设 {preset['preset_id']} 缺少参数 {key}")
            item = item.replace("{"+key+"}", str(values[key]))
        return item
    return fill(template)


def _tokens(text: str) -> list[str]:
    import re
    return re.findall(r"\{([a-zA-Z_]+)\}", text)
