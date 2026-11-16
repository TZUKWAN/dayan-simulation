"""层1：确定性经济内核（toy capitalism v0）。

设计原则（见 docs/实验设计书_toy_capitalism_v0.md）：
- 所有账目（工资、利润、储蓄、设备）由本模块确定性记账，LLM 不做任何算术。
- 本模块不 import 任何 LLM 相关代码；决策通过 `apply_decisions` 注入，
  决策产生自 LLM 语义层或规则基线（由编排器决定）。
- 制度结构（谁能雇佣谁、设备不可自给须购买、工资由经营者支付）由引擎强制，
  不留给决策层"领悟"——这是遮蔽设计的机制面。

经济结构：
- 单一消费品 + 一种资本品（设备，固定价格 P_K，从"设备部门"购买，货币流出）。
- 经营者（持有设备者）可雇佣劳动者：1 个劳动者占用 1 台设备；
  产出 = A × Σ技能；设备按 δ 折旧（按实际用人）。
- 自营者用自己的技能生产（无设备），产出按市场参考价即时出售（易腐，未售即废）。
- 消费品市场：买方按 id 顺序、卖方按报价从低到高撮合（确定性）。
- 市场参考价 p_ref 按供需比缓慢调整（有上下限）。

tick 内阶段顺序（全部确定性）：
  1 开办企业 → 2 劳动力市场 → 3 生产 → 4 工资支付（经营者储蓄→劳动者）
  → 5 消费品市场（含 p_ref 更新） → 6 企业结算（利润→经营者）
  → 7 设备购买（货币流入设备部门，退出流通）

金钱守恒不变量：Σsavings(t) = Σsavings(t-1) − 设备购买支出。
折旧是设备实物损耗，不是货币流。层4 单元测试将逐 tick 检验该守恒式。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional


@dataclass
class Params:
    # 生产
    A: float = 2.0                 # 每单位技能每 tick 的产出
    kappa: float = 0.6             # 设备生产率加成：企业产出 = A×(1+κ)×Σ技能
    P_K: float = 8.0               # 设备固定价格
    delta: float = 0.10            # 每劳动者槽位每 tick 设备折旧率
    # 价格
    p0: float = 5.0                # 初始参考价
    price_adj: float = 0.10        # 供需失衡调整速度
    price_lo: float = 0.55         # p_ref 下限（×p0）
    price_hi: float = 3.0          # p_ref 上限（×p0）
    # 消费
    subsist: float = 1.5           # 维生消费（单位/ tick）
    excess_buf: float = 15.0       # 超过此财富额的部分按 MPC 消费
    mpc_excess: float = 0.75       # 超额储蓄的边际消费倾向（过低会货币沉淀→流通枯竭）
    # 制度参数（规则基线用）
    wage_share_rule: float = 1.00  # 计件工资率 = wage_share × A × p_ref（须≥维生线 1.5/A）
    markup_rule: float = 0.08      # 规则经营者报价加成（相对参考价的售价下浮对冲）
    scrap: float = 0.5             # 歇业时设备残值率
    max_firms: int = 20            # 经营者数量上限
    wc_multiplier: float = 2.0     # 开业垫付工资缓冲（×槽位×工资估计）
    # 决策周期
    decide_every: int = 4
    # 制度变体（模式C：制度对照实验）
    institute: str = "private"    # private=私有雇佣制 | coop=生产合作社（1人1票均分结余）
    # 组织/劳动过程增量（v2 设计 §3.5 方案A：并入 polecon）
    monitor_intensity: float = 0.0  # 监控强度[0,1]→受雇者无力感加成（经叙事处境传递）
    deskill_rate: float = 0.0       # 去技能化率：受雇 tick 技能退化比例（Braverman）
    # 需求冲击（H7：危机→失业潮→异化）
    shock_tick: int = -1          # 冲击起始 tick（-1=无冲击）
    shock_factor: float = 1.0     # 冲击后消费预算倍率
    friction_shock: float = 0.75  # 冲击期求职摩擦率（每期观望比例）


class Firm:
    __slots__ = ("fid", "owner_id", "capital", "inventory", "price", "wage",
                 "workers", "age", "revenue", "wage_bill", "capital_used",
                 "sales_units", "hire_cap", "is_coop")

    def __init__(self, fid: int, owner_id: int, capital: float,
                 price: float, wage: float):
        self.fid = fid
        self.is_coop = False
        self.owner_id = owner_id
        self.capital = capital
        self.inventory = 0.0
        self.price = price
        self.wage = wage
        self.workers: list[int] = []
        self.age = 0
        self.revenue = 0.0
        self.wage_bill = 0.0
        self.capital_used = 0.0
        self.sales_units = 0.0        # 上期实际售出量（雇佣决策的需求信号）
        self.hire_cap: int = 10 ** 9  # 经营者用工上限（LLM 可设定；规则按销量定）


class Agent:
    __slots__ = ("id", "persona", "skill", "savings", "capital", "position",
                 "employer_id", "firm_id", "income", "prev_income", "consumed",
                 "unmet", "intent", "offer_rank", "wage_post", "price_post",
                 "llm", "dec_offset", "_self_stock", "_self_revenue", "_profit")

    def __init__(self, aid: int, persona: dict, skill: float, savings: float,
                 llm: bool, dec_offset: int = 0):
        self.id = aid
        self.persona = persona
        self.skill = skill
        self.savings = savings
        self.capital = 0                # 设备台数
        self.position = "unemployed"    # unemployed | worker | self | employer
        self.employer_id: Optional[int] = None
        self.firm_id: Optional[int] = None
        self.income = 0.0
        self.prev_income = 0.0
        self.consumed = 0.0
        self.unmet = 0.0
        self.intent = "seek_work"       # seek_work|self|firm|buy_capital|idle|operate
        self.offer_rank = 1
        self.wage_post = 0.0
        self.price_post = 0.0
        self.llm = llm
        self.dec_offset = dec_offset
        self._self_stock = 0.0
        self._self_revenue = 0.0
        self._profit = 0.0

    def wealth(self, p_k: float) -> float:
        return self.savings + self.capital * p_k


class World:
    """确定性经济世界。决策（LLM 或规则）由外部注入，本类不做任何随机性。"""

    def __init__(self, params: Params, agents: list[Agent], rng=None):
        import random as _random
        self.params = params
        self.agents = agents
        self.rng = rng if rng is not None else _random.Random(0)
        self.firms: dict[int, Firm] = {}
        self.next_fid = 1
        self.p_ref = params.p0
        self.tick_no = 0
        self.ledger_last: dict = {}
        self.closed_events: list[dict] = []
        self.last_sold_units = 0.0    # 上期全市场实际售出（需求信号）
        self.last_unmet_units = 0.0   # 上期全市场未被满足的维生需求

    def agent(self, aid: int) -> Agent:
        return self.agents[aid]

    # ---------- 决策注入 ----------
    def collect_decision_requests(self, t: int) -> list[int]:
        """本 tick 需要重新决策的 agent（LLM 抽样、非受雇者）。"""
        D = self.params.decide_every
        return [a.id for a in self.agents
                if a.llm and a.position != "worker" and ((t + a.dec_offset) % D == 0)]

    def apply_decisions(self, decisions: dict[int, dict]):
        """把决策层动作写入意图/报价。数值钳制在制度边界内。"""
        p = self.params
        for aid, d in decisions.items():
            ag = self.agent(aid)
            if ag.position == "worker":
                continue  # 受雇者的动作空间为空（本期不跳槽，制度约束）
            if ag.position == "employer":
                w0 = ag.wage_post if ag.wage_post > 0 else p.wage_share_rule * p.A * self.p_ref
                pr0 = ag.price_post if ag.price_post > 0 else self.p_ref * (1 - 0.03)
                ag.wage_post = _clamp(_f(d.get("wage"), w0), 0.2 * self.p_ref, 5.0 * self.p_ref)
                ag.price_post = _clamp(_f(d.get("price"), pr0), 0.5 * self.p_ref, 3.0 * self.p_ref)
                if ag.firm_id in self.firms:
                    f = self.firms[ag.firm_id]
                    # 定价/工资写入企业（此前只更新了经营者 posts，企业账面价格
                    # 冻结在开业值——所有定价决策从未生效的根源）
                    f.price = ag.price_post
                    f.wage = ag.wage_post
                    # 用工上限（经营者可按需求增减雇；受制度上限 60 约束）
                    hc = d.get("hire_cap")
                    if hc is not None:
                        f.hire_cap = int(_clamp(_f(hc, f.hire_cap), 0, 60))
                    # 经营者扩产：增加企业设备（阶段7执行）
                    if str(d.get("expand", "")).lower() in ("true", "1", "yes") \
                            and ag.savings >= p.P_K * 2:
                        ag.intent = "buy_capital"
                continue
            act = str(d.get("action", "idle")).strip().lower()
            rank = int(_clamp(_f(d.get("offer_rank"), 1), 1, 3))
            if act == "work":
                ag.intent = "seek_work"
                ag.offer_rank = rank
            elif act == "self":
                ag.intent = "self"
            elif act == "capital":
                ag.intent = "buy_capital" if ag.savings >= p.P_K else "self"
            elif act == "firm":
                wage_est0 = p.wage_share_rule * p.A * self.p_ref
                if ag.capital >= 1 and ag.savings >= 3 * wage_est0 \
                        and len(self.firms) < p.max_firms:
                    ag.intent = "firm"
                else:
                    ag.intent = "self"
            else:
                ag.intent = "idle" if act == "idle" else "seek_work"

    def _wc_min(self, slots: int) -> float:
        p = self.params
        wage_est = p.wage_share_rule * p.A * self.p_ref
        return p.wc_multiplier * slots * wage_est

    # ---------- 主循环 ----------
    def step(self, t: int) -> dict:
        p = self.params
        ledger = {"tick": t, "wages": 0.0, "profits": 0.0, "revenue": 0.0,
                  "dep_value": 0.0, "capital_buy": 0.0,
                  "sales": 0.0, "cons_value": 0.0, "sum_savings_before": None,
                  "sum_savings_after": None}
        if t == 0:
            ledger["sum_savings_before"] = sum(a.savings for a in self.agents)
        else:
            ledger["sum_savings_before"] = self.ledger_last["sum_savings_after"]
        ledger["sum_savings_prev_capital_buy"] = None

        # 每 tick 重置
        for a in self.agents:
            a.consumed = 0.0
            a.unmet = 0.0
            a.prev_income = a.income
            a.income = 0.0
            a._self_stock = 0.0
            a._self_revenue = 0.0
            a._profit = 0.0
        for f in self.firms.values():
            f.revenue = 0.0
            f.wage_bill = 0.0
            f.capital_used = 0.0
            f.sales_units = 0.0

        self._phase_founding()
        self._phase_labor_market()
        self._phase_role_assignment()
        self._phase_market_production(ledger)
        self._phase_settle(ledger)
        self._phase_capital_purchase(ledger)

        # 组织/劳动过程：受雇者技能退化（去技能化，Braverman）
        if p.deskill_rate > 0:
            for a in self.agents:
                if a.position == "worker":
                    a.skill = max(0.3, a.skill * (1.0 - p.deskill_rate))

        # 收入记账（供决策情境与叙事；工资已在阶段4入储蓄）
        for a in self.agents:
            if a.position == "worker" and a.employer_id is not None:
                f = self.firms.get(a.employer_id)
                a.income = f.wage * a.skill if f is not None else 0.0
            elif a.position == "self":
                a.income = a._self_revenue
            elif a.position == "employer":
                a.income = a._profit

        ledger["sum_savings_after"] = sum(a.savings for a in self.agents)
        ledger["capital_buy"] = ledger.get("capital_buy", 0.0)
        self.ledger_last = ledger
        self.tick_no = t + 1
        return ledger

    # ---------- 阶段 1：开办企业 ----------
    def _phase_founding(self):
        p = self.params
        for a in self.agents:
            if a.position == "employer":
                continue
            if a.intent != "firm":
                continue
            wage_est = p.wage_share_rule * p.A * self.p_ref
            # 自适应开业规模：积蓄够养几个工人就带几台设备（1台保底）
            affordable = max(1, int(a.savings // (3 * wage_est))) if a.savings > 0 else 0
            if a.capital >= 1 and affordable >= 1 and len(self.firms) < p.max_firms:
                slots = min(int(a.capital), affordable)
                a.capital -= slots  # 设备实物移交企业（不得复制：这是歇业残值回路的根源）
                if p.institute == "coop":
                    # 生产合作社：创办者即社员，结余社员均分（1人1票）
                    f = Firm(fid=self.next_fid, owner_id=a.id, capital=float(slots),
                             price=self.p_ref * (1 - 0.03),
                             wage=wage_est)
                    f.is_coop = True
                    f.hire_cap = slots
                    f.workers = [a.id]
                    self.firms[f.fid] = f
                    self.next_fid += 1
                    a.position = "member"
                    a.firm_id = f.fid
                    a.employer_id = f.fid
                    a.intent = "operate"
                    continue
                # 开业默认定价锚定当前参考价（锚定 p0 会在价格下行期开业即滞销→工资违约）
                f = Firm(fid=self.next_fid, owner_id=a.id, capital=float(slots),
                         price=a.price_post if a.price_post > 0 else self.p_ref * (1 - 0.03),
                         wage=a.wage_post if a.wage_post > 0 else wage_est)
                f.hire_cap = slots
                a.price_post, a.wage_post = f.price, f.wage
                self.firms[f.fid] = f
                self.next_fid += 1
                a.position = "employer"
                a.firm_id = f.fid
                a.employer_id = None
                a.intent = "operate"
            else:
                a.intent = "self"  # 资格不足，退回自营

    # ---------- 阶段 2：劳动力市场 ----------
    def _phase_labor_market(self):
        # 先按用工上限裁员（销量下降→解雇：产业后备军的来源之一），保留先入职者
        for f in self.firms.values():
            cap = min(int(f.capital), f.hire_cap)
            if len(f.workers) > cap:
                f.workers = f.workers[:cap]
        # 被裁者与失效雇佣关系落位
        employed = set()
        for f in self.firms.values():
            employed.update(f.workers)
        for a in self.agents:
            if a.position in ("worker", "member") and a.employer_id is not None:
                if a.id not in employed:
                    a.position = "unemployed"
                    a.employer_id = None
                    a.intent = "seek_work"
        vac = []  # [wage, fid, slots]
        for f in self.firms.values():
            slots = min(int(f.capital), f.hire_cap) - len(f.workers)
            if slots > 0:
                vac.append([f.wage, f.fid, slots])
        vac.sort(key=lambda v: (-v[0], v[1]))
        for a in self.agents:
            if a.position not in ("unemployed", "self"):
                continue
            if a.intent != "seek_work" or not vac:
                continue
            k = min(len(vac) - 1, max(0, a.offer_rank - 1))
            chosen = None
            # 从偏好岗向后找第一个空岗，找不到再回看更高工资岗
            for i in list(range(k, len(vac))) + list(range(k - 1, -1, -1)):
                if vac[i][2] > 0:
                    chosen = i
                    break
            if chosen is None:
                continue
            wage, fid, _ = vac[chosen]
            f = self.firms[fid]
            f.workers.append(a.id)
            vac[chosen][2] -= 1
            a.position = "member" if f.is_coop else "worker"
            a.employer_id = fid
            a.intent = "operate"

    # ---------- 阶段 2.5：角色落位 ----------
    def _phase_role_assignment(self):
        """制度假设：自营无门槛。未被雇佣且不打算观望者一律自营。
        求职失败 → 本期自营（下期可再求职）。'idle' 观望者无产出、无收入。
        冲击期求职摩擦：需求收缩时部分求职者本期观望（确定性 hash 排队），
        由此产生真实失业存量（H7 的因变量）。"""
        p = self.params
        shocked = 0 <= p.shock_tick <= self.tick_no
        for a in self.agents:
            if a.position == "unemployed":
                if a.intent == "idle":
                    continue
                if shocked and a.intent == "seek_work":
                    if (a.id * 2654435761 + self.tick_no) % 100 < int(
                            p.friction_shock * 100):
                        continue  # 本期观望：计入失业
                a.position = "self"
                if a.intent == "seek_work":
                    a.intent = "self"

    # ---------- 阶段 3+5：订单制市场与生产（无库存） ----------
    def _phase_market_production(self, ledger):
        """订单制（制度假设：企业按订单生产，无存货——消除库存-雇佣振荡）。
        流程：需求核算 → 卖方（企业=在职工人产能，自营=个人产能）按
        价格偏好×随机扰动排序 → 买方按 id 序购买 → 企业产量=实际销量。"""
        p = self.params
        # 1) 产能与需求核算
        firm_capacity = {}
        for f in self.firms.values():
            ws = sorted(f.workers)[:min(len(f.workers), int(f.capital))]
            cap = p.A * (1 + p.kappa) * sum(self.agent(w).skill for w in ws) if ws else 0.0
            firm_capacity[f.fid] = cap
        self_capacity = {a.id: p.A * a.skill for a in self.agents
                         if a.position == "self"}
        supply = sum(firm_capacity.values()) + sum(self_capacity.values())
        budgets = {b.id: self._budget(b) for b in self.agents}
        demand_units = sum(budgets.values()) / self.p_ref
        if supply > 0 and demand_units > 0:
            ratio = demand_units / supply
            adj = _clamp(1 + p.price_adj * (ratio - 1), 1 - p.price_adj, 1 + p.price_adj)
            self.p_ref = _clamp(self.p_ref * adj, p.p0 * p.price_lo, p.p0 * p.price_hi)

        # 2) 卖方清单与排序（价格越低越靠前，带每期随机扰动避免垄断倾覆）
        sellers = []  # [price, kind, key, capacity_left]
        for f in self.firms.values():
            cap = firm_capacity[f.fid]
            if cap > 1e-9 and f.price > 0:
                sellers.append([f.price, "firm", f.fid, cap])
        for aid, cap in self_capacity.items():
            if cap > 1e-9:
                sellers.append([self.p_ref, "self", aid, cap])
        sellers.sort(key=lambda s: s[0] * (0.85 + 0.30 * self.rng.random()))

        # 3) 买方按 id 序、依同一卖方序购买（预算约束；销量=配额=产量）
        sold_total = 0.0
        unmet_total = 0.0
        for b in self.agents:
            budget = budgets[b.id]
            want_units = budget / self.p_ref
            for s in sellers:
                if budget <= 1e-9 or want_units <= 1e-9:
                    break
                if s[3] <= 1e-9:
                    continue
                qty = min(want_units, budget / s[0], s[3])
                if qty <= 1e-9:
                    continue
                pay = qty * s[0]
                budget -= pay
                b.savings -= pay
                b.consumed += qty
                want_units -= qty
                s[3] -= qty
                sold_total += qty
                ledger["sales"] += pay
                ledger["cons_value"] += pay
                if s[1] == "self":
                    sa = self.agent(s[2])
                    sa.savings += pay
                    sa._self_revenue += pay
                else:
                    f = self.firms[s[2]]
                    f.revenue += pay
                    f.sales_units += qty
            b.unmet = max(0.0, p.subsist - b.consumed)
            unmet_total += b.unmet
        self.last_sold_units = sold_total
        self.last_unmet_units = unmet_total

        # 4) 企业设备折旧（按在岗机位；订单制下无库存结转）
        for f in self.firms.values():
            n_eff = min(len(f.workers), int(f.capital))
            f.capital_used = n_eff
            if n_eff > 0:
                f.capital = max(0.0, f.capital - p.delta * n_eff)

    # ---------- 阶段 6：结算（收入入账 → 发工资 → 利润核算 → 歇业检查） ----------
    def _phase_settle(self, ledger):
        """顺序：销售收入先入账（避免'先垫后收'的现金时序性死亡），
        再以计件率支付工资，再核算经济利润（指标用），最后歇业检查。
        折旧是设备实物损耗（市场阶段已减），不是货币流。"""
        p = self.params
        for f in list(self.firms.values()):
            owner = self.agent(f.owner_id)
            revenue = f.revenue  # 不清零：账目供阶段后测量层读取（下 tick 开头重置）
            ledger["revenue"] += revenue
            dep_value = p.delta * p.P_K * f.capital_used
            if f.is_coop:
                # 合作社结算：先预留设备维护，结余按人头均分给社员（无雇佣剩余）
                need = len(f.workers) - int(f.capital)
                if need > 0 and revenue >= need * p.P_K:
                    revenue -= need * p.P_K
                    f.capital += need
                    ledger["capital_buy"] += need * p.P_K  # 设备部门统一回流
                # 民主积累：卖满产能且预留金充足 → 扩一台设备并开放一个社员名额
                per_worker = p.A * (1 + p.kappa) * 1.1
                sold_out = f.sales_units >= per_worker * max(1, len(f.workers)) * 0.95
                if sold_out and revenue >= p.P_K and len(f.workers) < 60:
                    revenue -= p.P_K
                    f.capital += 1
                    f.hire_cap = len(f.workers) + 1
                    ledger["capital_buy"] += p.P_K
                n = len(f.workers)
                if n > 0 and revenue > 0:
                    share = revenue / n
                    for w in f.workers:
                        self.agent(w).savings += share
                    skill_sum = sum(self.agent(w).skill for w in f.workers)
                    f.wage = share  # 社员预期分成（ vacancies 排序用）
                    f.wage_bill = revenue
                    ledger["wages"] += revenue
                f.revenue = 0.0
                if not f.workers and f.age >= 8 and f.sales_units <= 1e-9:
                    self._close_firm(f, "no_hires", ledger)
                f.age += 1
                continue
            owner.savings += revenue
            if f.workers:
                skill_sum = sum(self.agent(w).skill for w in f.workers)
                bill = f.wage * skill_sum
                if owner.savings >= bill:
                    owner.savings -= bill
                    f.wage_bill = bill
                    ledger["wages"] += bill
                    for w in f.workers:
                        self.agent(w).savings += f.wage * self.agent(w).skill
                else:
                    f.wage_bill = 0.0
                    self._close_firm(f, "wage_default", ledger)
                    continue
            economic_profit = revenue - f.wage_bill - dep_value
            ledger["dep_value"] += dep_value
            if f.workers:
                ledger["profits"] += economic_profit
            owner._profit = economic_profit
            if owner.savings < -2 * p.P_K:
                self._close_firm(f, "owner_insolvent", ledger)
            elif not f.workers and f.age >= 8 and f.sales_units <= 1e-9:
                # 真正死亡：无人受雇且本期零销售（订单制下无库存）
                self._close_firm(f, "no_hires", ledger)
            f.age += 1

    def _close_firm(self, f: Firm, reason: str, ledger: dict):
        """歇业清算：设备实物按残值率归还经营者（个人闲置设备，可再用于开业）；
        不产生货币流（设备不是货币，货币守恒由设备部门回流保证）。"""
        p = self.params
        owner = self.agent(f.owner_id)
        for w in list(f.workers):
            wa = self.agent(w)
            wa.position = "unemployed"
            wa.employer_id = None
            wa.intent = "seek_work"
        f.workers = []
        owner.capital += int(round(f.capital * p.scrap))
        owner.position = "unemployed"
        owner.firm_id = None
        owner.intent = "self"
        owner.wage_post = 0.0
        owner.price_post = 0.0
        self.closed_events.append({"tick": self.tick_no, "fid": f.fid,
                                   "owner": f.owner_id, "reason": reason})
        del self.firms[f.fid]

    def _budget(self, a: Agent) -> float:
        """消费预算 = 维生线 + 超出部分的 MPC，且不超过 6 倍维生线
        （消费平滑：富人不把毕生积蓄一次砸进市场，避免需求剧烈震荡）。
        投资意向（购设备/开业）时只消费维生线（古典"节欲"：储蓄→投资
        的微观通道；否则消费 drain 会在达到开业门槛前抽干积蓄）。"""
        p = self.params
        cash = max(0.0, a.savings) + max(0.0, a.income)
        floor_cost = p.subsist * self.p_ref
        if cash <= floor_cost:
            return cash
        spend = floor_cost + p.mpc_excess * (cash - floor_cost)
        spend = min(spend, 6.0 * floor_cost)
        if a.intent in ("buy_capital", "firm"):
            spend = floor_cost  # 节欲：积累者优先
        if 0 <= p.shock_tick <= self.tick_no:
            spend *= p.shock_factor  # 需求冲击（H7）
        return max(0.0, spend)

    # ---------- 阶段 7：设备部门（购买/维护/回流） ----------
    def _phase_capital_purchase(self, ledger):
        """资本品部门显式化（两大部类结构）：设备购买与维护支出进入设备部门，
        当期作为该部门收入等量回流给全体居民（设备部门工人的消费需求）。
        货币严格守恒：Σsavings 只在阶段内部转移，总量不变。"""
        p = self.params
        receipt = ledger.get("capital_buy", 0.0)  # 含结算阶段合作社维护支出（不得覆盖）
        # 7a 企业设备自动维护（制度性记账：折旧损耗须重置，否则产能归零仍付工资）
        for f in self.firms.values():
            need = len(f.workers) - int(f.capital)
            if need > 0:
                owner = self.agent(f.owner_id)
                n = min(need, int(owner.savings // p.P_K))
                if n > 0:
                    owner.savings -= n * p.P_K
                    f.capital += n
                    receipt += n * p.P_K
        # 7b 意图驱动的购买/扩产
        for a in self.agents:
            if a.intent != "buy_capital" or a.savings < p.P_K:
                continue
            if a.position in ("unemployed", "self"):
                a.savings -= p.P_K
                a.capital += 1
                receipt += p.P_K
                a.intent = "self"
            elif a.position == "employer" and a.firm_id in self.firms:
                # 经营者扩产：设备进入企业，扩大雇佣容量
                a.savings -= p.P_K
                self.firms[a.firm_id].capital += 1.0
                receipt += p.P_K
                a.intent = "operate"
        # 7c 设备部门收入等量回流（人均）
        ledger["capital_buy"] = receipt
        if receipt > 0 and self.agents:
            share = receipt / len(self.agents)
            for a in self.agents:
                a.savings += share

    # ---------- 统计辅助 ----------
    def positions(self) -> dict:
        c = {"unemployed": 0, "worker": 0, "self": 0, "employer": 0, "member": 0}
        for a in self.agents:
            c[a.position] += 1
        return c

    def wealth_vector(self) -> list[float]:
        """财富 = 储蓄 + 自有设备 + 企业设备份额。
        私有企业：设备全记创办人名下；合作社：设备按社员均摊（集体 equity），
        记在创办人一人名下会虚增不平等（口径错误）。"""
        p = self.params
        firm_cap: dict[int, float] = {}
        coop_member_share: dict[int, float] = {}
        for f in self.firms.values():
            if f.is_coop and f.workers:
                share = f.capital * p.P_K / len(f.workers)
                for w in f.workers:
                    coop_member_share[w] = coop_member_share.get(w, 0.0) + share
            else:
                firm_cap[f.owner_id] = firm_cap.get(f.owner_id, 0.0) + f.capital
        out = []
        for a in self.agents:
            w = a.savings + (a.capital + firm_cap.get(a.id, 0.0)) * p.P_K                 + coop_member_share.get(a.id, 0.0)
            out.append(w)
        return out

    def vacancy_snapshot(self) -> list[dict]:
        out = []
        for f in self.firms.values():
            slots = int(f.capital) - len(f.workers)
            if slots > 0 and f.wage > 0:
                out.append({"fid": f.fid, "wage": f.wage, "slots": slots})
        out.sort(key=lambda d: (-d["wage"], d["fid"]))
        return out


def _clamp(x, lo, hi):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return lo
    if math.isnan(x) or math.isinf(x):
        return lo
    return max(lo, min(hi, x))


def _f(x, default):
    try:
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except (TypeError, ValueError):
        return default
