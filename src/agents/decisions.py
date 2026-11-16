"""决策与叙事的提示词（遮蔽设计）+ 解析器 + 规则基线策略。

遮蔽设计要点：
- prompt 中不出现任何马克思主义/政治经济学理论词汇
  （资本、剥削、剩余价值、阶级、劳动价值等一律不用）；
  用中性词：设备、经营、工钱、自营、存货。
- 理论词汇只出现在测量端（量表名、指标名），不进入 agent 的输入。
- 制度结构（谁能雇佣谁）由引擎强制，prompt 只描述处境事实。
"""
from __future__ import annotations

import json
import math
import re

from ..ledger.economy import Agent, World

SYSTEM = "你是一个微型经济社会模拟中的居民。根据处境做决定，只输出一个JSON对象，不要输出别的文字。"


# ---------------- 普通居民决策 ----------------
def build_decision_prompt(ag: Agent, world: World) -> list[dict]:
    p = world.params
    pos_desc = {
        "unemployed": "目前没有固定活计",
        "self": "目前自己干自己的活（自营）",
        "employer": "目前是经营者",
        "member": "目前是生产合作社社员（共同劳动、均分结余）",
    }.get(ag.position, ag.position)
    trend = "收入比上期上升" if ag.income > ag.prev_income * 1.05 else (
        "收入比上期下降" if ag.income < ag.prev_income * 0.95 else "收入与上期差不多")
    offers = world.vacancy_snapshot()[:3]
    offer_txt = "；".join(
        f"机会{i+1}：计件工钱每点技能每期{round(o['wage'],1)}（以你的技能{ag.skill:.2f}预计到手{round(o['wage']*ag.skill,1)}，名额{o['slots']}）"
        for i, o in enumerate(offers)) if offers else "目前没有招工机会"
    coop = world.params.institute == "coop"
    firm_word = "合伙办生产合作社" if coop else "雇人经营"
    work_word = "加入一家生产合作社（共同劳动、均分结余）" if coop else "去找一份受雇的活"
    elig_firm = ag.capital >= 1 and ag.savings >= world._wc_min(1)
    trait_line = f"- 特点：{ag.persona['trait']}，{ag.persona['age']}岁" if ag.persona.get('trait') else "- 特点：（无背景信息）"
    msg = f"""你的情况：
- 身份：{pos_desc}
{trait_line}
- 技能水平：{ag.skill:.2f}（平均1.0）
- 手头积蓄：{ag.savings:.1f}（{trend}）
- 拥有设备：{ag.capital}台（设备可在市场上以{p.P_K}一台购买；拥有设备并有一定积蓄才能雇人经营）
- 市场参考物价：{world.p_ref:.2f}/件
- 可选活计：{offer_txt}

可选决定（action 取其一）：
- "work"：{work_word}（可附 offer_rank: 1-3 表示想要第几个机会）
- "self"：自营（用自己的技能生产出售）
- "firm"：{firm_word}（需要设备>=1台且积蓄够垫工钱{'' if elig_firm else '，目前条件不够'}）
- "capital"：购买1台设备（价格{p.P_K}）
- "idle"：观望一阵

只输出JSON，例如：{{"action":"self"}} 或 {{"action":"work","offer_rank":2}} 或 {{"action":"firm","wage":9.5,"price":5.5}}"""
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": msg}]


def build_employer_prompt(ag: Agent, world: World) -> list[dict]:
    p = world.params
    firm = None
    for f in world.firms.values():
        if f.owner_id == ag.id:
            firm = f
            break
    info = "（本期还没有开张）"
    if firm is not None:
        produced = round(p.A * (1 + p.kappa) * sum(
            next(x for x in world.agents if x.id == w).skill for w in firm.workers), 1) if firm.workers else 0
        info = (f"现有帮工{len(firm.workers)}人（设备可容纳{int(firm.capital)}人），"
                f"上期产出约{produced}件、卖出{firm.sales_units:.0f}件，存货{firm.inventory:.0f}件，"
                f"上期销售额{firm.revenue:.1f}、工钱支出{firm.wage_bill:.1f}，"
                f"现报计件工钱{firm.wage:.2f}、售价{firm.price:.2f}")
    role_word = "合作社（你创办的）" if world.params.institute == "coop" else "铺子"
    msg = f"""你是{role_word}的创办人。你的情况：
- 设备：{ag.capital}台（1台可带1名帮工；设备会磨损）
- 手头积蓄：{ag.savings:.1f}
- 市场参考物价：{world.p_ref:.2f}/件
- {info}
- 招工市面常见计件工钱约每点技能每期 {(p.wage_share_rule * p.A * world.p_ref):.1f}

请定下这一阵的计件工钱（每1点技能每期付多少）、售价（每件），以及用工上限
hire_cap（最多带几个帮工；卖不掉就少雇些，货积压会亏本）。帮工产出与技能成正比：
技能1.0的帮工每期产出约{round(p.A*(1+p.kappa),1)}件。只输出JSON：
{{"action":"operate","wage":数字,"price":数字,"hire_cap":整数}}"""
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": msg}]


# ---------------- 叙事与评定 ----------------
NARR_SYSTEM = "你是微型社会模拟中的居民。用第一人称写一两句话，描述最近干活与过日子的真实感受。只输出正文，不要任何说明或引号。"


def build_narrative_prompt(ag: Agent, world: World) -> list[dict]:
    p = world.params
    pos_desc = {
        "worker": "在别人铺子里做受雇的活，活计内容由东家安排",
        "self": "自己干自己的活，自己安排、自负盈亏",
        "employer": "雇人经营自己的铺子，安排别人的活计",
        "unemployed": "暂时没有活计",
        "member": "在生产合作社里和社员们共同劳动、一起分享经营结余，大事共同商量",
    }.get(ag.position, ag.position)
    trend = "比上期多点" if ag.income > ag.prev_income * 1.05 else (
        "比上期少点" if ag.income < ag.prev_income * 0.95 else "和上期差不多")
    trait_line = f"- 特点：{ag.persona['trait']}，{ag.persona['age']}岁" if ag.persona.get('trait') else "- 特点：（无背景信息）"
    # 组织/劳动过程（v2 §3.5）：监控强度进入受雇者处境描述（遮蔽措辞，无理论词）
    monitor_line = ""
    mon = getattr(world.params, "monitor_intensity", 0.0)
    if ag.position == "worker" and mon > 0:
        monitor_line = ("- 东家{}查看你的干活记录、计时计数。\n"
                        .format("时时" if mon > 0.5 else "定期"))
    msg = f"""你的近况：
- 身份：{pos_desc}
{trait_line}
- 上期到手：{ag.income:.1f}（{trend}）
{monitor_line}- 手头积蓄：{ag.savings:.1f}
- 家当：设备{ag.capital}台
- 上期够不够买维生口粮：{"够" if ag.unmet <= 1e-9 else "不够（缺" + f"{ag.unmet:.1f}" + "件）"}

请写一两句话第一人称感受。"""
    return [{"role": "system", "content": NARR_SYSTEM},
            {"role": "user", "content": msg}]


JUDGE_SYSTEM = ("你是测评员。根据陈述按1-5分（1=完全没有，5=非常强）评定五个心理方面，"
                "只输出JSON：{\"powerlessness\":n,\"meaninglessness\":n,\"normlessness\":n,"
                "\"isolation\":n,\"self_estrangement\":n}")

DIM_RUBRIC = {
    "powerlessness": "无力感：觉得自己的处境不受自己控制、说了不算",
    "meaninglessness": "无意义感：觉得干的活没什么意义、不明白为什么而做",
    "normlessness": "无规范感：觉得没什么规则可依、只能各顾各",
    "isolation": "孤立感：觉得和周围人疏远、没有归属",
    "self_estrangement": "自我疏离：做的事不像自己想做的、感觉不像自己",
}


def build_judge_prompt(narrative: str) -> list[dict]:
    rubric = "；".join(f"{k}：{v}" for k, v in DIM_RUBRIC.items())
    msg = f"评定标准：{rubric}\n\n陈述：{narrative}\n\n只输出JSON五项打分。"
    return [{"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": msg}]


# ---------------- 解析 ----------------
def _extract_json(text: str):
    if not text:
        return None
    # 去掉思考残留的围栏
    text = re.sub(r"```(?:json)?", "", text)
    m = re.search(r"\{[^{}]*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return None


def parse_decision(text: str) -> dict | None:
    d = _extract_json(text)
    if not isinstance(d, dict):
        return None
    act = str(d.get("action", "")).lower()
    if act not in ("work", "self", "firm", "capital", "idle", "operate"):
        return None
    out = {"action": act}
    for k in ("wage", "price", "offer_rank", "hire_cap"):
        if k in d:
            try:
                v = float(d[k])
                if not (math.isnan(v) or math.isinf(v)):
                    out[k] = v
            except (TypeError, ValueError):
                pass
    return out


def parse_scores(text: str) -> dict | None:
    d = _extract_json(text)
    if not isinstance(d, dict):
        return None
    keys = list(DIM_RUBRIC)
    out = {}
    for k in keys:
        v = d.get(k)
        try:
            v = int(float(v))
        except (TypeError, ValueError):
            return None
        if not 1 <= v <= 5:
            return None
        out[k] = v
    return out


# ---------------- 规则基线策略 ----------------
def rule_decision(ag: Agent, world: World) -> dict:
    """规则基线：与 LLM 同一动作空间、同样的信息可得性（不含理论词）。"""
    p = world.params
    if ag.position == "employer":
        # 确定性价格离散度：设备生产率优势(κ)转化为明显价格优势（机器排挤手工业）
        frac = ((ag.id * 2654435761) % 997) / 997
        price = world.p_ref * (0.78 + 0.12 * frac)
        out = {"action": "operate",
               "wage": p.wage_share_rule * p.A * world.p_ref,
               "price": price}
        firm = world.firms.get(ag.firm_id)
        if firm is not None:
            # 订单制用工：上期销量 ÷ 单人产能（渐进调整 ±3/−2，劳动囤积）
            per_worker = p.A * (1 + p.kappa) * 1.1   # 产/人 ≈ A×(1+κ)×平均技能
            wage_est = p.wage_share_rule * p.A * world.p_ref
            base = max(1, len(firm.workers))
            own_desired = int(firm.sales_units / per_worker + 0.999)
            own_desired = int(min(max(own_desired, base - 2), base + 3))
            own_desired = max(own_desired, 0)
            # 卖满产能 → 允许每期 +1 扩张（否则钳制会把雇佣永久锁死）
            capacity = per_worker * base
            sold_out = firm.sales_units >= capacity * 0.95
            if sold_out:
                own_desired = max(own_desired, base + 1)
            out["hire_cap"] = int(min(max(own_desired, 0), 60))
            if sold_out and ag.savings > 3 * p.P_K + (own_desired + 1) * wage_est:
                out["expand"] = True
        return out
    if ag.position == "worker":
        return {"action": "operate"}
    exp_self = p.A * ag.skill * world.p_ref * 0.35  # 自营期望收入（含售罄率折扣）
    # 积累次序：先设备（买后保住可开业缓冲），后开店（自适应规模，1台保底）
    wage_est = p.wage_share_rule * p.A * world.p_ref
    if ag.capital < 6 and ag.savings >= 3 * wage_est + p.P_K:
        return {"action": "capital"}
    if ag.capital >= 1 and ag.savings >= 3 * wage_est \
            and len(world.firms) < p.max_firms:
        return {"action": "firm"}
    offers = world.vacancy_snapshot()
    best = offers[0]["wage"] if offers else 0.0
    # 储蓄越薄，保留工资越低（生存约束）
    reservation = max(0.3 * world.p_ref, exp_self)
    if ag.savings < p.P_K:
        reservation = max(0.2 * world.p_ref, exp_self * 0.5)
    if best >= reservation and best > 0:
        return {"action": "work", "offer_rank": 1}
    return {"action": "self"}


class RuleDecider:
    """全规则决策器（层4基线A）。"""

    def decide_batch(self, ags: list[Agent], world: World) -> dict[int, dict]:
        return {a.id: rule_decision(a, world) for a in ags}


class LLMBatchDecider:
    """LLM 决策器：批量收集 prompt → 并发调用 → 解析；失败回退规则（记 fallback）。

    决策协议按包分发（审计修复：原版硬编码 polecon 动作集，非 polecon 包的
    LLM 输出会被判解析失败回退规则——三包 LLM 在环实际未通）。
    - pack 提供 llm_decision_prompt + parse_llm_decision → 走包协议
    - 否则 → polecon 遗留路径（build_decision_prompt/employer + parse_decision）
    """

    def __init__(self, client, stats: dict | None = None):
        self.client = client
        self.stats = stats if stats is not None else {"llm": 0, "fallback": 0}

    def decide_batch(self, ags: list, world: World | None = None,
                     pack=None) -> dict[int, dict]:
        if not ags:
            return {}
        if pack is not None and hasattr(pack, "llm_decision_prompt")                 and hasattr(pack, "parse_llm_decision"):
            return self._decide_generic(ags, pack)
        return self._decide_polecon(ags, world)

    def _decide_generic(self, ags: list, pack) -> dict[int, dict]:
        jobs, meta = [], []
        for a in ags:
            jobs.append({"messages": pack.llm_decision_prompt(a),
                         "temperature": 0.2,
                         "max_tokens": self.client.default_max_tokens})
            meta.append(a.id)
        outs = self.client.batch(jobs)
        decisions = {}
        for aid, txt in zip(meta, outs):
            d = pack.parse_llm_decision(txt)
            if d is None:
                self.stats["fallback"] += 1
                d = pack.rule_decision(pack.agents[aid])
            else:
                self.stats["llm"] += 1
            decisions[aid] = d
        return decisions

    def _decide_polecon(self, ags: list[Agent], world: World) -> dict[int, dict]:
        jobs, meta = [], []
        for a in ags:
            if a.position == "employer":
                msgs = build_employer_prompt(a, world)
            else:
                msgs = build_decision_prompt(a, world)
            jobs.append({"messages": msgs, "temperature": 0.2,
                         "max_tokens": self.client.default_max_tokens})
            meta.append(a.id)
        outs = self.client.batch(jobs)
        decisions = {}
        for aid, txt in zip(meta, outs):
            d = parse_decision(txt)
            if d is None:
                self.stats["fallback"] += 1
                d = rule_decision(world.agent(aid), world)
            else:
                self.stats["llm"] += 1
            decisions[aid] = d
        return decisions
