"""Extract explicit user constraints before a planner can rewrite them.

This is a deterministic contract parser, not a source of simulated measurements.
"""
from __future__ import annotations

import json
import re
from ..scene_contract import scene_requirements

NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
TIME_MARKER = re.compile(r"第\s*(?P<step_or_time>"+NUMBER+r")\s*(?P<unit>秒|分钟|小时|(?:蒙特卡洛)?步)|"
                         r"(?<![A-Za-z0-9_])t\s*=\s*(?P<model_time>"+NUMBER+r")")
RUN_OPTIONS = {"ticks", "steps", "dt", "seed", "seeds", "analysis_window", "warmup_ticks"}
MODEL_IDS = re.compile(r"(?<![A-Za-z0-9_])((?:BEH|NET|ECO|SYS|MET|APP|CPL)\d{3}|MET-MM1|USR[0-9A-F]{12})(?![A-Za-z0-9_])", re.I)
MECHANISMS = {
    "疾病传播": r"疫情|传染病|感染|病毒|流行病|防疫|\bSIS\b|\bSIR\b|\bSEIR\b",
    "信息传播": r"谣言|信息传播|观点|舆论|意见|共识|极化|宣传",
    "人群疏散": r"疏散|逃生|撤离|人群拥挤|踩踏|安置点",
    "倒地处置": r"踩踏(?:事件|事故)|倒地救助|倒地处置|跌倒救助|演练.{0,24}(?:跌倒|倒地)|(?:预定|预设)倒地",
    "交通流": r"NaSch|交通|堵车|道路拥堵|车流|环形.*车道|单车道",
    "居住分异": r"居住分异|居住隔离|社区分选|Schelling",
    "就业劳动": r"就业|失业|劳动力|工资|雇佣|招聘|Goodwin",
    "排队资源": r"排队|等待时间|服务台|挂号|呼叫中心|M/M/1(?!\d)",
    "OU均值回复": r"Ornstein[– -]Uhlenbeck|OU过程|OU\s*均值回复|均值回复的?随机微分方程",
    "老年行动差异": r"老人|老年|行动不便|弱势群体",
    "接驳运力": r"接驳|公交|运力",
    "积水影响": r"暴雨|洪水|积水|内涝",
    "年龄接触差异": r"年龄接触|年龄分层",
    "集体行动": r"集体行动|参与阈值|Granovetter",
    "公民暴力": r"公民暴力|警民|Epstein|合法性",
    "演化博弈": r"复制子|演化博弈|replicator",
    "农业补贴审计": r"绿色补贴|涉农.{0,12}审计|农[业户].{0,20}绿色欺诈",
    "网格局部交互": r"元胞自动机|局部邻域|冯[·・.]?诺依曼邻域|摩尔邻域|网格局部|(?<![A-Za-z])CA(?![A-Za-z])",
    "投入产出": r"投入产出|产业关联|Leontief",
    "经济增长": r"经济增长|Solow|索洛|Ramsey|拉姆齐",
    "城乡迁移": r"城乡迁移|Todaro",
    "交通分配": r"Wardrop|用户均衡|系统最优|路径分配",
    "半马尔可夫": r"半马尔可夫|semi.Markov",
}
PARAM_ALIASES = {"传播率": "beta", "传播率beta": "beta", "恢复率": "gamma",
                 "随机慢化概率": "p", "慢化概率": "p", "密度": "density",
                 "容忍阈值": "threshold", "最高速度": "vmax", "公交运力": "bus_capacity", "接驳运力": "bus_capacity"}


def _continues_expression(tail):
    """A numeric prefix of a formula/range is not a scalar parameter value."""
    return bool(re.match(r'\s*(?:[+*/^%×÷−(（]|-(?!\s*(?:[,，。；;]|$))|到|至|\.\.|\b(?:if|else|mod)\b|模)',tail))


def _assignment_context(text):
    """Keep phase metadata out of baseline assignments without rewriting a request.

    Offsets are retained for intervention matching. The original text, including
    all diagnostic requirements, is still delivered to design and review; these
    clauses are executed by the separately frozen research protocol.
    """
    masked=list(text)
    for match in re.finditer(r'https?://[^\s<>"，。；;]+',text):
        masked[match.start():match.end()]=' '*(match.end()-match.start())
    diagnostic=(r'数值诊断|时间(?:步)?细化|步长细化|参数响应(?:扫描|曲线)?|参数消融|'
                r'(?:候选|搜索|校准)参数网格|(?:预先|事前|固定).{0,8}候选网格|'
                r'\b(?:diagnostics|param_grid|max_scaled_change|max_scaled_mc_se)\s*[=:：]|'
                r'全局敏感性|敏感性分析|(?<![A-Za-z0-9_])(?:Sobol|Saltelli|global_sensitivity|plan_capacity)(?![A-Za-z0-9_])|容量(?:规划|探针|实测)|'
                r'(?:另(?:外)?(?:做|进行)|后续(?:做|进行)).{0,30}(?:配对对照|对照实验)')
    for clause in re.finditer(r'[^。；;\n]+',text):
        phase=re.search(diagnostic,clause.group(),re.I)
        if phase:
            start=clause.start()+phase.start()
            masked[start:clause.end()]=' '*(clause.end()-start)
    return ''.join(masked)


def _pairs(text):
    result = {}
    # Coordinates belong to the named facility, not each agent's x/y state.
    # Preserve ordinary equation parameters named x/y outside these blocks.
    coordinate_blocks=[]
    labels={'出口':'exit','目的地':'target','目标':'target','起点':'start','初始位置':'start'}
    for block in re.finditer(r'(出口|目的地|目标|起点|初始位置)\s*[（(]([^）)\n。]{1,160})[）)]',text):
        coordinate_blocks.append((block.start(2),block.end(2),labels[block.group(1)]))
    for match in re.finditer(r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\s*(?:[=:＝]|改成|改为|设为)\s*", text):
        # dX/dt=... and object.x=... are equations/state access, not top-level
        # model input assignments. The complete original text remains available.
        if match.start() and text[match.start()-1] in '/.':continue
        tail = text[match.end():match.end()+4096]
        try:
            if re.match(NUMBER, tail):
                token = re.match(NUMBER, tail).group()
                if _continues_expression(tail[len(token):]):continue
                value = float(token) if any(c in token for c in ".eE") else int(token)
            else:
                value, length = json.JSONDecoder().raw_decode(tail)
                if _continues_expression(tail[length:]):continue
            name=match.group(1)
            if name.lower() in ('x','y'):
                for start,end,prefix in coordinate_blocks:
                    if start<=match.start()<end:
                        name=prefix+'_'+name.lower()
                        break
            result[name] = value
        except (ValueError, TypeError):
            continue
    return result


def _timed_settings(text, options, previous, ids):
    """Read explicit schedule clauses and leave the original wording intact for the Agent."""
    markers = list(TIME_MARKER.finditer(text))
    baseline_text = list(text)
    scheduled = []
    minute_model = "CPL001" in ids or ("疏散" in text and bool(re.search(r"谣言|老人|接驳|公交|暴雨|洪水", text)))
    grid_model = "NET122" in ids or bool(re.search(MECHANISMS["网格局部交互"], text, re.I))
    for i, marker in enumerate(markers):
        begin = marker.end()
        end = markers[i+1].start() if i+1 < len(markers) else len(text)
        clause = text[begin:end]
        stop = re.search(r"[。；;！？\n]|[.!?](?=\s|$)", clause)
        if stop:
            end = begin + stop.start()
            clause = clause[:stop.start()]
        # A clock label is never a model parameter, even when it only describes the initial state.
        baseline_text[marker.start():begin] = " " * (begin-marker.start())
        if re.search(r"从\s*$", text[max(0, marker.start()-8):marker.start()]) and re.match(
                r"[\s，,]*(?:起|开始)?\s*(?:推进|运行|仿真|模拟|迭代|计算)", clause):
            continue
        changes = {k: v for k, v in _pairs(clause).items() if k not in RUN_OPTIONS}
        has_change = bool(re.search(r"改为|改成|设为|调整为|减半|翻倍|(?:降低|减少|增加|提高)\s*\d", clause))
        if not changes and not has_change:
            continue
        time = float(marker["step_or_time"] or marker["model_time"])
        unit = marker["unit"]
        if unit in ("步", "蒙特卡洛步"):
            default_dt = 1.0 if grid_model or unit == "蒙特卡洛步" else .1
            time *= float(options.get("dt", previous.get("dt", default_dt)))
        elif unit == "秒" and minute_model:
            time /= 60
        elif unit == "分钟" and not minute_model:
            time *= 60
        elif unit == "小时":
            time *= 60 if minute_model else 3600
        scheduled.append((begin, end, time, changes))
        baseline_text[begin:end] = " " * (end-begin)
    return {k:v for k,v in _pairs("".join(baseline_text)).items() if k not in RUN_OPTIONS}, scheduled


def mechanism_constraints(text):
    """Scope a negation to the named mechanism, preserving contrast clauses."""
    positive, excluded, spans = [], [], []
    for name, pattern in MECHANISMS.items():
        enabled = False
        for match in re.finditer(pattern, text, re.I):
            prefix = re.split(r"[，,。；;]|但是|但|而是|只考虑|只模拟", text[:match.start()])[-1]
            # Adjacent synonyms and coordinated nouns share the same negation;
            # a relational phrase such as “没有公交的老人” does not negate老人.
            clean_prefix=prefix
            for noun_pattern in MECHANISMS.values():clean_prefix=re.sub(noun_pattern,'',clean_prefix,flags=re.I)
            clean_prefix=re.sub(r'(?:和|与|及|、|机制|影响|传播|\s)+$','',clean_prefix)
            negated = bool(re.search(r"(?:不考虑|不包含|不需要|不使用|不模拟|不涉及|不要|无需|排除|关闭|没有|无)(?:任何|相关|额外)?\s*$", clean_prefix))
            if negated:
                excluded.append(name);spans.append(match.span())
            else:enabled=True
        if enabled:positive.append(name)
    cleaned=text
    for start,end in sorted(spans,reverse=True):cleaned=cleaned[:start]+' '* (end-start)+cleaned[end:]
    return positive,sorted(set(excluded)),cleaned


def extract_request(text, last_run=None):
    text = str(text or "")
    previous = dict(last_run or {})
    reuse = bool(re.search(r"沿用|刚才|上次|保持(?:原有|已有|原来的|此前|其余|其他)|"
                          r"其余[^。；]*不变|其他[^。；]*不变|(?:只把|只将)[^。；]{0,80}(?:改为|改成|调为|调整为|设为)", text))
    ids = list(dict.fromkeys(m.upper() for m in MODEL_IDS.findall(text)))
    continuing=bool(re.search(r'继续(?:运行|模拟|跑|迭代|演化|计算)|接着(?:运行|模拟|跑)|从检查点',text))
    if continuing:reuse=True
    if previous.get("model_id") and (not ids or ids==[previous["model_id"]]) and re.search(r"改为|改成|设为|调整为|减半|翻倍",text) and not re.search(r"创建|新建|另一个|重新建模",text):
        reuse=True
    if reuse and not ids and previous.get("model_id"):
        ids = [previous["model_id"]]
    assignment_text=_assignment_context(text)
    options, explicit = {}, _pairs(assignment_text)
    for name in ("ticks", "steps", "dt", "seed", "seeds", "analysis_window", "warmup_ticks"):
        if name in explicit:
            options["ticks" if name == "steps" else name] = explicit.pop(name)
    tick = re.search(r"(?:运行|推进|仿真|跑|迭代)\s*("+NUMBER+r")\s*(?:步|tick)", text, re.I)
    if tick:
        token = tick.group(1)
        options["ticks"] = float(token) if any(c in token for c in ".eE") else int(token)
    dt = re.search(r"步长\s*[=:：为]?\s*("+NUMBER+r")", text)
    if dt:
        options["dt"] = float(dt.group(1))
    seeds = re.search(r"(?:随机)?种子\s*(?:使用|设为|为|是|[=:：＝])?\s*("+NUMBER+r"(?:\s*[,，、和]\s*"+NUMBER+r")*)", text)
    if seeds:
        values = [float(v) if any(c in v for c in ".eE") else int(v) for v in re.findall(NUMBER, seeds.group(1))]
        if len(values) > 1:
            options["seeds"] = values
        elif values:
            options["seed"] = values[0]
    explicit, scheduled = _timed_settings(assignment_text, options, previous, ids)
    event_changes = {}

    def change_target(match, default):
        return next((changes for begin, end, _, changes in scheduled if begin <= match.start() < end), default)

    recognized_changes=set()
    for token, name in PARAM_ALIASES.items():
        direct = re.search(re.escape(token)+r"\s*(?:改为|改成|设为|为|[=:：])?\s*("+NUMBER+r")", text)
        if direct and not _continues_expression(text[direct.end():]):
            target=change_target(direct, explicit)
            target[name]=float(direct.group(1));recognized_changes.add(token)
        relative = re.search(r"(?:"+re.escape(token)+"|"+name+r")\s*(减半|翻倍|(?:降低|减少|增加|提高)\s*\d+(?:\.\d+)?\s*[%％])", text)
        if relative:
            recognized_changes.add(token)
            target = change_target(relative, event_changes)
            op = relative.group(1)
            if op == "减半":
                target[name] = "*0.5"
            elif op == "翻倍":
                target[name] = "*2"
            else:
                amount = float(re.search(NUMBER, op).group())/100
                target[name] = "*"+str(1-amount if re.search(r"降低|减少", op) else 1+amount)
    cells = re.search(r"(\d+)\s*格(?:的|环形|单车道|路|道路|元胞)?", text)
    if cells and re.search(MECHANISMS["交通流"], text, re.I):
        explicit["cells"] = int(cells.group(1))
    from ..scaling import scale_intent
    population_contract = scale_intent(text)
    exact_population = population_contract.get("explicit_population")
    inferred_population_parameter = None
    if exact_population is not None and len(population_contract.get('populations',{}))<=1:
        if 'n' not in explicit:
            inferred_population_parameter = 'n'
        explicit.setdefault("n", exact_population)
    base = dict(previous.get("params") or previous.get("parameters") or {}) if reuse else {}
    unresolved=[]
    if reuse and base:
        aliases=[('行人速度',('ped_speed','walk_speed','v_des','speed')),('公交速度',('bus_speed',)),
                 ('期望速度',('v_des','speed')),('最高速度',('vmax',)),('移动速度',('speed','v_des')),
                 ('出口横坐标',('exit_x',)),('出口纵坐标',('exit_y',)),
                 ('行人数',('n','n_agents')),('主体数',('n','n_agents')),('人数',('n','N','population')),
                 ('速度',('speed','v_des','vmax'))]
        spans=[]
        for label,candidates in aliases:
            match=re.search(re.escape(label)+r'\s*(?:改为|改成|设为|调整为|为|[=:：])?\s*('+NUMBER+r')',text)
            relative=None
            if not match:
                relative=re.search(re.escape(label)+r'\s*(减半|翻倍|(?:降低|减少|增加|提高)\s*\d+(?:\.\d+)?\s*[%％])',text)
                match=relative
            if not match or any(a<=match.start()<b for a,b in spans):continue
            spans.append(match.span());keys=[key for key in candidates if key in base]
            if len(keys)!=1:
                unresolved.append(label+('对应多个参数，请明确名称：'+str(keys) if keys else '在当前模型没有开放的可调参数'))
                continue
            target=change_target(match, explicit)
            recognized_changes.add(label)
            if relative:
                op=relative.group(1)
                factor=.5 if op=='减半' else 2 if op=='翻倍' else 1+(-1 if re.search('降低|减少',op) else 1)*float(re.search(NUMBER,op).group())/100
                target[keys[0]]=base[keys[0]]*factor if target is explicit else '*'+str(factor)
            else:
                token=match.group(1);target[keys[0]]=float(token) if any(c in token for c in '.eE') else int(token)
        suffixes=set(explicit)|set(event_changes)|set(options)|recognized_changes
        suffixes.update(name for _, _, _, changes in scheduled for name in changes)
        for change in re.finditer(r'([^，,。；;]{1,40}?)(?:改为|改成|设为|调整为)\s*'+NUMBER,text):
            subject=change.group(1).strip()
            if not any(subject.endswith(name) for name in suffixes):unresolved.append('未识别这项修改的对象：'+subject)
        if not scheduled:
            for key,op in list(event_changes.items()):
                if isinstance(op,str) and op.startswith('*') and key in base:
                    explicit[key]=base[key]*float(op[1:]);event_changes.pop(key)
        if (re.search(r'改为|改成|设为|调整为|减半|翻倍',text) and not explicit and not event_changes
                and not any(changes for _, _, _, changes in scheduled)):
            unresolved.append('没有解析出要修改的模型参数；未按原配置重跑来冒充修改')
    if reuse:
        manifest = previous.get("manifest") or {}
        for name in ("ticks", "dt", "seed"):
            value = previous.get(name)
            if value is None:
                value = ((manifest.get("rng") or {}) if name == "seed" else (manifest.get("requested") or {})).get(name)
            if value is not None:
                options.setdefault(name, value)
    mechanisms, excluded_mechanisms, positive_text = mechanism_constraints(text)
    data_text = re.sub(r"(?:不用|不需要|无需|不要|不使用|不是|未使用)(?:采集|导入|接入)?(?:真实|现实|实际)(?:校准)?(?:数据|道路|路网|人口|建筑|地区)", "", text)
    real_data = bool(re.search(r"真实(?:道路|路网|人口|数据|建筑|地区)|采集|现实数据|实际数据|实测数据|导入|读取.*(?:CSV|csv|数据)", data_text))
    real_topology = bool(re.search(r"(?:真实|实测|实际)(?:空间|道路|路网|建筑|场地|地形|布局|地图|地区)", data_text))
    llm_text=re.sub(r'(?:不(?:使用|需要|调用|接入)|无需|不用|不要(?:使用|调用|接入)?)'
                    r'(?:真实|外部|任何|实际|\s)*(?:LLM|大模型)(?:驱动)?(?:主体|智能体|代理)?','',text,flags=re.I)
    llm_agents = bool(re.search(r"生成式(?:主体|智能体|代理)|真实\s*LLM|LLM驱动|LLM(?:主体|智能体|代理)|"
                               r"大模型.{0,12}(?:主体|行动)|(?:主体|智能体|代理).{0,16}(?:调用|接入|使用).{0,8}(?:LLM|大模型)|"
                               r"ReAct|Reflexion|Voyager|Concordia", llm_text, re.I))
    kind = ("experiment" if re.search(r"对照实验|干预效果|政策评估|政策比较|评估.{0,12}效果|做.{0,6}实验", text) else
            "sweep" if re.search(r"扫参|扫描|sweep", text, re.I) else
            "ensemble" if re.search(r"多种子|稳健|集成|ensemble", text, re.I) else
            "compare" if re.search(r"比较|对比|对照", text) else
            "compose" if re.search(r"组合|流水线|compose", text, re.I) else
            "search_sources" if re.search(r"数据源|来源.*检索|搜索.*来源|找.*数据", text) else
            "list_presets" if re.search(r"采集预设|主题采集|预设列表", text) else
            "run_preset" if re.search(r"按预设.*采集|预设.*执行|采集.*数据|收集.*数据", text) else
            "calibrate_model" if re.search(r"校准|calibrat|参数估计|留出验证", text, re.I) else
            "search_models" if re.search(r"找|搜索|有哪些", text) else "run")
    interventions = [{"label": "用户指定干预", "at_t": at, "params": changes}
                     for _, _, at, changes in scheduled if changes]
    if event_changes:
        interventions.append({"label": "用户指定干预", "at_t": None, "params": event_changes})
    if interventions:
        kind = "experiment"
    url = re.search(r'https://[^\s<>"，。；]+', text)
    dataset = re.search(r"DS-[0-9a-f]{24}", text)
    if re.search(r"自定义|新模型|(?:创建|新建|建立|构建).{0,20}模型|根据.{0,30}建模", text):
        kind = "build_model"
    elif dataset and "分析" in text:
        kind = "analyze_data"
    elif url and re.search(r"采集|导入|下载|读取", text) and not re.search(r"仿真|模拟|运行", text):
        kind = "collect_data"
    if re.search(r'^(?:请|帮我)?(?:解释|说明|分析一下为什么|为什么|如何理解|你能做什么|你是谁|你好)|什么意思|怎么理解|支持哪些功能',text.strip()) and not re.search(r'重新运行|重新模拟|创建|新建|构建|(?:并|然后|同时|请|帮我)(?:再)?(?:运行|模拟|执行)',text):
        kind="explain"
    elif continuing:kind="resume"
    initial_state = {}
    if kind == "build_model" and re.search(r"存量|状态初始化", text):
        for match in re.finditer(r"(?:初始存量|状态初值|初始|初值)\s*[：:]?\s*(?=[A-Za-z_])([^，。；;\n]+)", text):
            initial_state.update(_pairs(match[1]))
        for name, value in initial_state.items():
            if explicit.get(name) == value:
                explicit.pop(name)
    purpose = "prediction" if "预测" in text else "policy" if kind == "experiment" else "mechanism"
    metric_match=re.search(r"(?:主要指标|主要结局|primary_metric|metric)\s*[=:：]\s*([A-Za-z_]\w*)",text)
    metric = metric_match.group(1) if metric_match else "flux" if re.search(r"flux|流量", text, re.I) else "I" if re.search(r"感染比例|感染率|感染人数", text) else None
    for key in ('metric','primary_metric'):explicit.pop(key,None)
    populations=list(dict.fromkeys(re.findall(r"老人|老年人|老年|儿童|学生|居民|行人|患者|医生|服务员|司机|企业|劳动者|主体|智能体",positive_text)))
    regions=list(dict.fromkeys(re.findall(r"(?:武汉|北京|上海|广州|深圳|德国|中国|美国|全球)|[\u4e00-\u9fff]{2,6}(?:省|市|县|区)(?=[，,。；;\s]|$)",text)))
    periods=list(dict.fromkeys(re.findall(r"(?:19|20)\d{2}\s*(?:年)?\s*(?:至|到|—|-|:)\s*(?:19|20)\d{2}年?|(?:未来|持续|模拟|运行)\s*\d+(?:\.\d+)?\s*(?:秒|分钟|小时|天|年)",text)))
    values, sweep_param = [], None
    if kind == "sweep":
        for hit in re.finditer(r"\b([A-Za-z_]\w*)\s+([\d.+\-eE\s,，、]+)", text):
            candidates = re.findall(NUMBER, hit.group(2))
            if len(candidates) > 1:
                sweep_param, values = hit.group(1), [float(v) for v in candidates]
                break
    if reuse and kind == "compare" and len(ids) <= 1 and len(explicit) == 1:
        sweep_param = next(iter(explicit))
        if sweep_param in base:
            values = [base[sweep_param], explicit[sweep_param]]
            kind = "sweep"
    return {"original_text": text, "model_ids": ids, "kind": kind, "purpose": purpose,
            "inferred_population_parameter": inferred_population_parameter,
            "explicit_parameters": explicit, "parameters": {**base, **explicit}, "initial_state": initial_state,
            "options": options, "mechanisms": mechanisms, "requires_real_data": real_data,
            "requires_real_topology":real_topology,
            "excluded_mechanisms":excluded_mechanisms,"positive_text":positive_text,
            "population":populations,"space_scope":regions,"time_scope":periods,
            "reuse": reuse, "missing_context": reuse and not previous,
            "interventions": interventions,
            "sweep_param": sweep_param, "values": values, "metric": metric,
            "url": url.group() if url else None, "dataset_id": dataset.group() if dataset else None,
            "requires_llm_agents": llm_agents, "scene_requirements":scene_requirements(text),
            "agent_count_label":population_contract.get("population_role"),"unresolved_constraints":unresolved}


def model_mechanisms(mid):
    from .semantics import registry
    if mid in registry():return set(registry()[mid]['mechanisms'])
    if str(mid).startswith("USR"):
        from ..custom_models import factory
        try:
            return set(factory(mid).definition.get("mechanisms", []))
        except (ValueError, FileNotFoundError):
            return set()
    known = {"NET106": {"交通流"}, "NET052": {"疾病传播"}, "NET053": {"疾病传播"},
             "NET061": {"疾病传播"}, "NET063": {"疾病传播"}, "BEH001": {"居住分异"},
             "ECO019": {"就业劳动"}, "ECO079": {"就业劳动"}, "ECO071": {"就业劳动"},
             "SYS002": {"排队资源"}, "SYS013": {"排队资源"}, "SYS010": {"排队资源"}}
    if mid in known:
        return known[mid]
    if mid in {"NET113", "NET114", "NET115", "NET116", "NET117", "NET118", "NET119", "NET120"}:
        return {"人群疏散"}
    if mid in {"BEH016", "BEH018", "BEH024", "BEH029", "NET080", "NET081"}:
        return {"信息传播"}
    return set()


def coverage_issues(request, mid=None):
    issues = list(request.get("unresolved_constraints",[]))
    if request["missing_context"]:
        issues.append("缺少上一次实际运行上下文，不能猜测要保留的配置")
    if request.get("requires_llm_agents") and mid not in {"BEH129", "BEH130", "BEH131", "BEH132", "BEH133"}:
        issues.append("需求要求真实LLM主体循环；不能用固定脚本、随机评分或普通DSL主体代替")
    if request["requires_real_data"] and not (mid == "CPL001" and request["parameters"].get("roads_dataset_id") and request["parameters"].get("population_dataset_id")):
        issues.append("需要接入并核验真实数据集，不能用内置默认人口或空间冒充")
    if len(request["mechanisms"]) > 1 and not set(request["mechanisms"]) <= model_mechanisms(mid):
        issues.append("需求包含多个机制，必须使用明确耦合的对应模型："+"、".join(request["mechanisms"]))
    if mid and request["mechanisms"]:
        supported = model_mechanisms(mid)
        missing = set(request["mechanisms"]) - supported
        if missing:
            issues.append(f"{mid} 不覆盖所需机制："+"、".join(sorted(missing)))
    text=request.get('positive_text',request.get('original_text',''))
    for variant,allowed in [('SEIR',{'NET055','NET061'}),('SIR',{'NET053','NET-SIR'}),('SIS',{'NET052'})]:
        if mid and re.search(r'(?<![A-Za-z])'+variant+r'(?![A-Za-z])',text,re.I) and mid not in allowed:
            issues.append(f'{mid} 不符合明确指定的{variant}仓室机制')
    if mid and request.get('excluded_mechanisms'):
        disable={'信息传播':('initial_rumor_fraction','rumor_rate'),'接驳运力':('bus_count',),'积水影响':('flood_severity',)}
        for name in set(request['excluded_mechanisms']) & model_mechanisms(mid):
            keys=disable.get(name,()) if mid=='CPL001' else ()
            if not keys or any(request['parameters'].get(key)!=0 for key in keys):
                issues.append(f'{mid}包含已排除机制{name}；必须明确禁用对应参数，不能忽略否定条件')
    return issues


def empirical_validation_requested(request):
    """An input value alone cannot fulfil a request to fit or validate a model."""
    clauses = re.split(r"[。；，\n]", request.get("positive_text", ""))
    for clause in clauses:
        if re.search(r"尚未|未要求|无需|不需要|不做|不用|不要求|不要|说明.{0,12}是否", clause):
            continue
        if re.search(r"留出(?:样本|数据|验证|检验)|独立(?:样本|数据).{0,10}(?:验证|检验)|(?:实测|真实|观测).{0,16}校准|(?:校准|拟合).{0,16}(?:参数|模型)", clause):
            return True
    return False
