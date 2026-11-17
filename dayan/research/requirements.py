"""Extract explicit user constraints before a planner can rewrite them.

This is a deterministic contract parser, not a source of simulated measurements.
"""
from __future__ import annotations

import json
import re
from ..scene_contract import scene_requirements

NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
MODEL_IDS = re.compile(r"(?<![A-Za-z0-9_])((?:BEH|NET|ECO|SYS|MET|APP|CPL)\d{3}|USR[0-9A-F]{12})(?![A-Za-z0-9_])", re.I)
MECHANISMS = {
    "疾病传播": r"疫情|传染病|感染|病毒|流行病|防疫|\bSIS\b|\bSIR\b|\bSEIR\b",
    "信息传播": r"谣言|信息传播|观点|舆论|意见|共识|极化|宣传",
    "人群疏散": r"疏散|逃生|撤离|人群拥挤|踩踏|安置点",
    "交通流": r"NaSch|交通|堵车|道路拥堵|车流|环形.*车道|单车道",
    "居住分异": r"居住分异|居住隔离|社区分选|Schelling",
    "就业劳动": r"就业|失业|劳动力|工资|雇佣|招聘|Goodwin",
    "排队资源": r"排队|等待时间|服务台|挂号|呼叫中心",
    "老年行动差异": r"老人|老年|行动不便|弱势群体",
    "接驳运力": r"接驳|公交|运力",
    "积水影响": r"暴雨|洪水|积水|内涝",
    "年龄接触差异": r"年龄接触|年龄分层",
    "集体行动": r"集体行动|参与阈值|Granovetter",
    "公民暴力": r"公民暴力|警民|Epstein|合法性",
    "演化博弈": r"复制子|演化博弈|replicator",
    "投入产出": r"投入产出|产业关联|Leontief",
    "经济增长": r"经济增长|Solow|索洛|Ramsey|拉姆齐",
    "城乡迁移": r"城乡迁移|Todaro",
    "交通分配": r"Wardrop|用户均衡|系统最优|路径分配",
    "半马尔可夫": r"半马尔可夫|semi.Markov",
}
PARAM_ALIASES = {"传播率": "beta", "传播率beta": "beta", "恢复率": "gamma",
                 "随机慢化概率": "p", "慢化概率": "p", "密度": "density",
                 "容忍阈值": "threshold", "最高速度": "vmax", "公交运力": "bus_capacity", "接驳运力": "bus_capacity"}


def _pairs(text):
    result = {}
    # Coordinates belong to the named facility, not each agent's x/y state.
    # Preserve ordinary equation parameters named x/y outside these blocks.
    coordinate_blocks=[]
    labels={'出口':'exit','目的地':'target','目标':'target','起点':'start','初始位置':'start'}
    for block in re.finditer(r'(出口|目的地|目标|起点|初始位置)\s*[（(]([^）)\n。]{1,160})[）)]',text):
        coordinate_blocks.append((block.start(2),block.end(2),labels[block.group(1)]))
    for match in re.finditer(r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\s*(?:[=:＝]|改成|改为|设为)\s*", text):
        tail = text[match.end():match.end()+4096]
        try:
            if re.match(NUMBER, tail):
                token = re.match(NUMBER, tail).group()
                value = float(token) if any(c in token for c in ".eE") else int(token)
            else:
                value, _ = json.JSONDecoder().raw_decode(tail)
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
    reuse = bool(re.search(r"沿用|保持|刚才|上次|只把|其余.*不变|其他.*不变", text))
    ids = list(dict.fromkeys(m.upper() for m in MODEL_IDS.findall(text)))
    continuing=bool(re.search(r'继续(?:运行|模拟|跑|迭代|演化|计算)|接着(?:运行|模拟|跑)|从检查点',text))
    if continuing:reuse=True
    if previous.get("model_id") and (not ids or ids==[previous["model_id"]]) and re.search(r"改为|改成|设为|调整为|减半|翻倍",text) and not re.search(r"创建|新建|另一个|重新建模",text):
        reuse=True
    if reuse and not ids and previous.get("model_id"):
        ids = [previous["model_id"]]
    options, explicit = {}, _pairs(text)
    for name in ("ticks", "steps", "dt", "seed", "seeds", "analysis_window", "warmup_ticks"):
        if name in explicit:
            options["ticks" if name == "steps" else name] = explicit.pop(name)
    tick = re.search(r"(?:运行|跑|迭代)\s*("+NUMBER+r")\s*(?:步|tick)", text, re.I)
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
    event_time = re.search(r"第\s*("+NUMBER+r")\s*(秒|分钟|小时|步)|\bt\s*=\s*("+NUMBER+r")", text)
    event_changes = {}
    time_value = None
    if event_time:
        time_value = float(event_time.group(1) or event_time.group(3))
        unit = event_time.group(2) or "model"
        minute_model = "CPL001" in ids or ("疏散" in text and bool(re.search(r"谣言|老人|接驳|公交|暴雨|洪水", text)))
        if unit == "步":
            time_value *= float(options.get("dt", previous.get("dt", .1)))
        elif unit == "秒" and minute_model:
            time_value /= 60
        elif unit == "分钟" and not minute_model:
            time_value *= 60
        elif unit == "小时":
            time_value *= 60 if minute_model else 3600
        before, after = text[:event_time.start()], text[event_time.end():]
        event_changes.update({k: v for k, v in _pairs(after).items() if k not in ("ticks", "seed", "seeds", "dt", "steps")})
        explicit = {k: v for k, v in _pairs(before).items() if k not in ("ticks", "seed", "seeds", "dt", "steps")}
    recognized_changes=set()
    for token, name in PARAM_ALIASES.items():
        direct = re.search(re.escape(token)+r"\s*(?:改为|改成|设为|为|[=:：])?\s*("+NUMBER+r")", text)
        if direct:
            target=event_changes if event_time and direct.start()>event_time.end() else explicit
            target[name]=float(direct.group(1));recognized_changes.add(token)
        relative = re.search(r"(?:"+re.escape(token)+"|"+name+r")\s*(减半|翻倍|(?:降低|减少|增加|提高)\s*\d+(?:\.\d+)?\s*[%％])", text)
        if relative:
            recognized_changes.add(token)
            op = relative.group(1)
            if op == "减半":
                event_changes[name] = "*0.5"
            elif op == "翻倍":
                event_changes[name] = "*2"
            else:
                amount = float(re.search(NUMBER, op).group())/100
                event_changes[name] = "*"+str(1-amount if re.search(r"降低|减少", op) else 1+amount)
    cells = re.search(r"(\d+)\s*格(?:的|环形|单车道|路|道路|元胞)?", text)
    if cells and re.search(MECHANISMS["交通流"], text, re.I):
        explicit["cells"] = int(cells.group(1))
    agents = re.search(r"(\d+)\s*(?:名|个)\s*(行人|居民|主体|智能体)", text)
    if agents:
        explicit["n"] = int(agents.group(1))
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
            target=event_changes if event_time and match.start()>event_time.end() else explicit
            recognized_changes.add(label)
            if relative:
                op=relative.group(1)
                factor=.5 if op=='减半' else 2 if op=='翻倍' else 1+(-1 if re.search('降低|减少',op) else 1)*float(re.search(NUMBER,op).group())/100
                target[keys[0]]='*'+str(factor) if target is event_changes else base[keys[0]]*factor
            else:
                token=match.group(1);target[keys[0]]=float(token) if any(c in token for c in '.eE') else int(token)
        suffixes=set(explicit)|set(event_changes)|set(options)|recognized_changes
        for change in re.finditer(r'([^，,。；;]{1,40}?)(?:改为|改成|设为|调整为)\s*'+NUMBER,text):
            subject=change.group(1).strip()
            if not any(subject.endswith(name) for name in suffixes):unresolved.append('未识别这项修改的对象：'+subject)
        if time_value is None:
            for key,op in list(event_changes.items()):
                if isinstance(op,str) and op.startswith('*') and key in base:
                    explicit[key]=base[key]*float(op[1:]);event_changes.pop(key)
        if re.search(r'改为|改成|设为|调整为|减半|翻倍',text) and not explicit and not event_changes:
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
    real_data = bool(re.search(r"真实(?:道路|路网|人口|数据|建筑|地区)|采集|现实数据|实际数据|导入|读取.*(?:CSV|csv|数据)", data_text))
    llm_agents = bool(re.search(r"生成式(?:主体|智能体|代理)|真实\s*LLM|LLM驱动|大模型.{0,12}(?:主体|行动)|ReAct|Reflexion|Voyager|Concordia", text, re.I))
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
    if event_changes:
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
            "explicit_parameters": explicit, "parameters": {**base, **explicit},
            "options": options, "mechanisms": mechanisms, "requires_real_data": real_data,
            "excluded_mechanisms":excluded_mechanisms,"positive_text":positive_text,
            "population":populations,"space_scope":regions,"time_scope":periods,
            "reuse": reuse, "missing_context": reuse and not previous,
            "interventions": ([{"label": "用户指定干预", "at_t": time_value, "params": event_changes}]
                              if event_changes else []),
            "sweep_param": sweep_param, "values": values, "metric": metric,
            "url": url.group() if url else None, "dataset_id": dataset.group() if dataset else None,
            "requires_llm_agents": llm_agents, "scene_requirements":scene_requirements(text),
            "agent_count_label":agents.group(2) if agents else None,"unresolved_constraints":unresolved}


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
