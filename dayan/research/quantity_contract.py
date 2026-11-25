"""Source-anchored population, spatial and retention constraints.

These deterministic constraints complement semantic review. They never invent a
population from a model catalogue, and negation is scoped to its own clause.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
import unicodedata


_CN = '零〇一二两三四五六七八九十百千万亿壹贰叁肆伍陆柒捌玖拾佰仟萬億'
_AMOUNT = rf'(?:\d{{1,3}}(?:,\d{{3}})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?(?:\s*[万亿])?|[0-9{_CN}]+(?:点[零〇一二三四五六七八九0-9]+)?'
_NUMBER = rf'(?:{_AMOUNT})'
_ROLES = ('农业主体', '审计机关', '监管人员', '基层监管人员', '智能体', '主体', '个体', '居民',
          '行人', '游客', '访客', '乘客', '农户', '企业', '车辆', '代理', '家庭', '工人', '劳动者',
          '消费者', '生产者', '农场', '银行', '政府', '老人', '儿童', '学生', '患者', '医生')
_ROLE = '|'.join(sorted(_ROLES, key=len, reverse=True))
_POPULATION = re.compile(rf'(?<![\d.\-{_CN}第])(?P<amount>{_NUMBER})\s*(?:'
                         rf'(?:名|个|位|辆|户|家|所)\s*(?P<role>{_ROLE})|(?P<human>人)(?!民|口))')
_GENERIC = {'主体', '智能体', '个体', '代理'}
_NEGATION = re.compile(r'不使用|不采用|不要求|不需要|不保存|不记录|不导出|不保留|不留存|不归档|无需|不用|不要|不必|排除|避免|不是|而非')
_BREAK = re.compile(r'[。；;、\n]|(?<!\d),|,(?!\d)|，|(?:但是|但仍|然而|而是|改为|改成|调整为|改用)')
_RETENTION = r'(?:保存|导出|记录|保留|留存|归档)'
_EVERY_STEP = r'(?:逐步|每一步|每个时间步|每一个时间步|每步)'
_NOT_SUMMARY = r'(?!的?(?:摘要|统计|汇总|均值|平均|数量|总数))'
_FRAME_CONTENT = (rf'(?:状态|轨迹|帧){_NOT_SUMMARY}|(?:全部|所有|完整|全量)\s*'
                  rf'(?:{_NUMBER})?\s*(?:名|个|位)?\s*(?:{_ROLE}|人|当前关系|关系|网络){_NOT_SUMMARY}')
_IN_CLAUSE = r'[^，,。；;\n]{0,32}'
_FRAME = re.compile(rf'{_EVERY_STEP}{_IN_CLAUSE}{_RETENTION}{_IN_CLAUSE}(?:{_FRAME_CONTENT})'
                    rf'|{_RETENTION}{_IN_CLAUSE}{_EVERY_STEP}{_IN_CLAUSE}(?:{_FRAME_CONTENT})')


def _normalized(source):
    text, indices = [], []
    for index, char in enumerate(source):
        expanded = unicodedata.normalize('NFKC', char)
        text.append(expanded)
        indices.extend([index] * len(expanded))
    return ''.join(text), indices


def amount(value):
    value = re.sub(r'[\s,]', '', value).translate(str.maketrans(
        '零〇一二两三四五六七八九壹贰叁肆伍陆柒捌玖拾佰仟萬億点',
        '001223456789123456789十百千万亿.'))

    def parse(token):
        for unit, multiplier in (('亿', 100_000_000), ('万', 10_000)):
            if unit in token:
                left, right = token.rsplit(unit, 1)
                return parse(left or '1') * multiplier + (parse(right) if right else 0)
        if not any(unit in token for unit in '十百千'):
            return Decimal(token)
        total, digits = Decimal(0), ''
        for char in token:
            if char in '十百千':
                total += Decimal(digits or '1') * {'十':10, '百':100, '千':1000}[char]
                digits = ''
            else:
                digits += char
        return total + Decimal(digits or '0')

    try:
        number = parse(value)
    except (InvalidOperation, ValueError):
        raise ValueError('无法解析明确的仿真数量：' + value) from None
    if not number.is_finite() or number != number.to_integral_value() or number < 1:
        raise ValueError('仿真规模须为正整数')
    return int(number)


def _negative(text, start):
    prefix = _BREAK.split(text[:start])[-1]
    return bool(_NEGATION.search(prefix))


def quantity_contract(source):
    source = source or ''
    text, indices = _normalized(source)
    result, evidence, conflicts = {}, [], []

    def cite(match, field, value, excluded=False):
        start, stop = match.span()
        a, b = indices[start], indices[stop-1]+1
        evidence.append({'field':field, 'value':value, 'excluded':excluded,
                         'start':a, 'end':b, 'quote':source[a:b]})

    def conflict(message):
        if message not in conflicts:
            conflicts.append(message)

    shape_pattern = re.compile(rf'(?<![\d.])({_NUMBER})\s*[×xX*]\s*({_NUMBER})\s*(?:的\s*)?'
                               r'(?:(?:二维|三维|周期|固定|规则|矩形|四邻|八邻)\s*){0,4}(?:网格|元胞|格)')
    for match in shape_pattern.finditer(text):
        shape = {'rows':amount(match[1]), 'columns':amount(match[2])}
        excluded = _negative(text, match.start())
        cite(match, 'grid', shape, excluded)
        if excluded:
            continue
        if result.get('grid') and result['grid'] != shape:
            conflict('原文包含多个不同网格尺寸，须分别声明对应的空间层')
        result['grid'] = shape
        result['entities'] = shape['rows'] * shape['columns']

    counts, previous = {}, {}
    for match in _POPULATION.finditer(text):
        role = match['role'] or '人'
        count = amount(match['amount'])
        excluded = _negative(text, match.start())
        cite(match, 'populations.' + role, count, excluded)
        if excluded:
            continue
        if role in counts and counts[role] != count and not re.search(
                r'改为|改成|调整为|增加到|扩大至|改用', text[previous[role]:match.start()]):
            conflict(f'原文对{role}给出不同数量 {counts[role]} 与 {count}，须明确各自范围')
        counts[role], previous[role] = count, match.end()
    total_matches = list(re.finditer(rf'(?:主体总数|主体数|智能体数|主体规模)\s*(?:为|设为|[=:])\s*({_NUMBER})', text))
    for match in total_matches:
        count = amount(match[1])
        excluded = _negative(text, match.start())
        cite(match, 'entities', count, excluded)
        if not excluded:
            counts['主体'] = count

    # A bare human count can repeat a named human population ("128名行人…
    # 正式128人目标档"). It is a reference to that population, not a new role.
    human_roles={'居民','行人','游客','访客','乘客','监管人员','基层监管人员','老人','儿童','学生','患者','医生','工人','劳动者','消费者','生产者'}
    human_named={role:value for role,value in counts.items() if role in human_roles}
    if '人' in counts and len(human_named)==1 and counts['人']==next(iter(human_named.values())):
        counts.pop('人')
    named = {role:count for role,count in counts.items() if role not in _GENERIC}
    totals = {count for role,count in counts.items() if role in _GENERIC}
    if len(totals) > 1:
        conflict('明确的总体主体数量不一致')
    hierarchical = bool(re.search(r'其中|包括|包含', text))
    if totals:
        count = next(iter(totals))
        role = next(role for role in counts if role in _GENERIC)
        if named and (max(named.values()) > count or len(named) > 1 and not hierarchical and sum(named.values()) != count):
            conflict('各类主体数量与明确的总体数量不一致')
    elif named:
        count = next(iter(named.values())) if hierarchical else sum(named.values())
        role = next(iter(named)) if len(named) == 1 else '主体'
    else:
        count = None
        role = None
    if count is not None:
        result.update(population_role=role, populations=named or {role:count})
        if 'entities' in result and result['entities'] != count:
            conflict('明确的主体数与一格一主体的网格面积不一致')
        else:
            result['entities'] = count
            if 'grid' not in result:
                result['explicit_population'] = count
        if len(named) > 1:
            result['population_structure'] = 'overlapping_groups' if hierarchical else 'separate_populations'

    positive_degrees, excluded_degrees = set(), set()
    for match in re.finditer(r'([四4八8])\s*(?:个\s*)?邻(?:域|居)?', text):
        degree = 4 if match[1] in ('四','4') else 8
        excluded = _negative(text, match.start())
        (excluded_degrees if excluded else positive_degrees).add(degree)
        cite(match, 'grid_degree', degree, excluded)
    if len(positive_degrees) == 1:
        result['grid_degree'] = next(iter(positive_degrees))
    elif len(positive_degrees) > 1:
        conflict('原文要求多个邻域阶数，须分别声明对应的空间层')
    if positive_degrees & excluded_degrees:
        conflict('同一邻域阶数同时被要求与排除')
    if excluded_degrees:
        result['excluded_grid_degrees'] = sorted(excluded_degrees)

    boundaries = {'周期边界':'periodic', '非周期边界':'nonperiodic', '反射边界':'reflecting', '吸收边界':'absorbing'}
    selected_boundaries = set()
    for match in re.finditer('|'.join(sorted(boundaries, key=len, reverse=True)), text):
        excluded = _negative(text, match.start())
        boundary = boundaries[match[0]]
        cite(match, 'boundary', boundary, excluded)
        if not excluded:
            selected_boundaries.add(boundary)
    if len(selected_boundaries) == 1:
        result['boundary'] = next(iter(selected_boundaries))
    elif selected_boundaries:
        result['boundaries'] = sorted(selected_boundaries)

    micro = re.compile(r'每(?:个|一位|位|人|户|家)|逐(?:个|主体|人|户)|独立主体|一人一|微观主体|多主体|多智能体|(?<![A-Za-z])ABM(?![A-Za-z])', re.I)
    individual = bool(totals) or any(not _negative(text, match.start()) for match in micro.finditer(text))
    if individual:
        result['granularity'] = 'individual'

    for match in _FRAME.finditer(text):
        # A verb-first match starts after the "不" in "不保留每步…".
        excluded = (_negative(text, match.start()) or bool(_NEGATION.search(match[0]))
                    or bool(re.search(r'不\s*$', text[:match.start()])))
        cite(match, 'all_frames', True, excluded)
        if not excluded:
            result['all_frames'] = True
    for match in re.finditer(r'越大越好|尽可能.{0,10}(?:大规模|扩大|多主体|规模最大)|最大可运行(?:的)?规模|最大规模|largest feasible', text, re.I):
        if not _negative(text, match.start()):
            result['maximize'] = True
            cite(match, 'maximize', True)
    if conflicts:
        result['conflict'] = '；'.join(conflicts)
    if evidence:
        result['evidence'] = evidence
    return result
