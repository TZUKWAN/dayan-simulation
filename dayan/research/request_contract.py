"""Conservative natural-language data contracts. Missing scope is never a default dataset."""
from __future__ import annotations

import re

COUNTRIES = {
    "中国": "CHN", "china": "CHN", "德国": "DEU", "germany": "DEU",
    "美国": "USA", "united states": "USA", "印度": "IND", "india": "IND",
    "日本": "JPN", "japan": "JPN", "英国": "GBR", "united kingdom": "GBR",
    "法国": "FRA", "france": "FRA", "巴西": "BRA", "brazil": "BRA",
    "意大利": "ITA", "italy": "ITA", "加拿大": "CAN", "canada": "CAN",
    "澳大利亚": "AUS", "australia": "AUS", "全球": "WLD", "世界": "WLD",
}
# Indicator metadata are definitions, not observations. Statistical meaning is explicit.
INDICATORS = {
    "SP.POP.TOTL": {"concept": "人口总量", "unit": "person", "aliases": ["人口总量", "总人口", "人口", "population"]},
    "SL.UEM.TOTL.ZS": {"concept": "失业率（ILO模型估计，占劳动力百分比）", "unit": "%", "aliases": ["失业率", "unemployment"]},
    "SP.POP.GROW": {"concept": "人口增长率", "unit": "%", "aliases": ["人口增长率", "人口增长"]},
    "SP.URB.TOTL.IN.ZS": {"concept": "城镇人口占比", "unit": "%", "aliases": ["城镇人口占比", "城镇化率"]},
    "SP.POP.65UP.TO.ZS": {"concept": "65岁及以上人口占比", "unit": "%", "aliases": ["老龄化", "65岁及以上人口占比"]},
    "SL.TLF.CACT.ZS": {"concept": "劳动力参与率（15岁及以上，ILO模型估计）", "unit": "%", "aliases": ["劳动力参与率", "劳动力参与"]},
    "NY.GDP.PCAP.CD": {"concept": "人均GDP（现价美元）", "unit": "USD", "aliases": ["人均GDP", "gdp per capita"]},
    "NY.GDP.MKTP.CD": {"concept": "GDP总量（现价美元）", "unit": "USD", "aliases": ["GDP总量"]},
    "SP.DYN.CBRT.IN": {"concept": "粗出生率（每千人）", "unit": "per_1000", "aliases": ["出生率"]},
    "SP.DYN.CDRT.IN": {"concept": "粗死亡率（每千人）", "unit": "per_1000", "aliases": ["死亡率"]},
    "SP.DYN.TFRT.IN": {"concept": "总和生育率（每名女性）", "unit": "births_per_woman", "aliases": ["总和生育率", "生育率"]},
}


def country_code(scope: str) -> str:
    value = str(scope or "").strip()
    if value.lower() in COUNTRIES:
        return COUNTRIES[value.lower()]
    if re.fullmatch(r"[A-Z]{3}", value):
        return value
    raise ValueError(f"地区未解析：{value or '未提供'}；请指定国家名称或ISO3代码，不会改成中国/全部国家")


def year_range(value: str) -> str:
    text = str(value or "")
    interval = re.search(r"((?:19|20)\d{2})\s*(?:年)?\s*(?:到|至|—|–|-|:|~)\s*((?:19|20)\d{2})", text)
    years = list(interval.groups()) if interval else re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", text)
    if not years or len(years) > 2:
        raise ValueError("请明确一个年份或起止年份；不会采用固定年份")
    a, b = int(years[0]), int(years[-1])
    if a > b:
        raise ValueError("起始年份不得晚于结束年份")
    return f"{a}:{b}"


def parse_data_request(text: str) -> dict:
    """Only complete unambiguous national annual contracts can execute automatically."""
    lower = text.lower()
    errors = []
    countries = {code for alias, code in COUNTRIES.items() if
                 (re.search(r"世界(?!银行)", lower) if alias == "世界" else alias in lower)}
    # Indicator components such as SL.UEM.TOTL.ZS are never ISO country codes.
    for code in set(COUNTRIES.values()):
        if re.search(r"(?<![A-Za-z0-9_.])"+code+r"(?![A-Za-z0-9_.])", text): countries.add(code)
    countries.update(re.findall(r"(?:国家|country|地区|region)\s*[:：=]?\s*([A-Z]{3})(?![A-Za-z_.])", text, re.I))
    countries = sorted(countries)
    if len(countries) != 1:
        errors.append("需要明确一个国家/地区（多地区请分别建立数据需求），不会替换地区")
    hits = []
    for code, meta in INDICATORS.items():
        aliases = [a for a in meta["aliases"] if a.lower() in lower]
        if code.lower() in lower or aliases:
            hits.append((max([len(a) for a in aliases] or [len(code)]), code))
    # Prefer specific meanings such as population growth over its substring population.
    hits.sort(reverse=True)
    selected = hits[0][1] if hits else None
    if not selected:
        errors.append("未解析到受支持的统计指标，请明确指标代码与口径；不能用人口数据代替")
    if selected == "SL.UEM.TOTL.ZS" and re.search(r"登记|调查失业|本国估计|national estimate|registered", text, re.I):
        errors.append("所要求失业统计口径与ILO模型估计不同，须选择对应来源/指标，不能替换口径")
    if len(hits) > 1:
        specific = INDICATORS[selected]["aliases"]
        independent = [code for _, code in hits[1:] if not any(
            a.lower() in b.lower() for a in INDICATORS[code]["aliases"] for b in specific)]
        if independent:
            errors.append("检测到多个指标，请分别建立变量需求以保留全部指标")
    try:
        date = year_range(text)
    except ValueError as exc:
        date = ""
        errors.append(str(exc))
    for pattern, message in ((r"月度|季度|每日|monthly|quarterly", "当前自动路由为国家年度数据，不能替代请求的时间频率"),
                             (r"市级|县级|社区|分省|省级|分性别|男性|女性|青年|15.?24|柏林|慕尼黑|巴黎|纽约|上海|北京|街道|district|city of", "请求含地区/群体细分，须提供对应指标与维度，不能用全国总量替代")):
        if re.search(pattern, text, re.I):
            errors.append(message)
    return {"original_text": text, "country": countries[0] if len(countries) == 1 else None,
            "indicator": selected, "date": date, "frequency": "annual", "geo_level": "national",
            "definition": INDICATORS.get(selected, {}), "errors": errors}


def collection_action(text: str) -> tuple[list, list, dict]:
    contract = parse_data_request(text)
    if contract["errors"]:
        return [], contract["errors"], contract
    start, end = contract["date"].split(":")
    return [{"tool": "run_preset", "args": {"preset_id": "pop_employment_wb", "values": {
        "country": contract["country"], "indicator": contract["indicator"],
        "year_from": start, "year_to": end}, "page_budget": 2}}], [], contract
