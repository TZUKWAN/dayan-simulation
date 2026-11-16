"""R3 政治学包骨架（权力/选举/联盟/合法性）+ Downs/Duverger 基准。

七件套声明（v2 设计·决策3）：
- 实体：选民 agent（政策偏好 x∈[0,1]、投票意向、合法性感知、抗议倾向）
- 制度：选举规则（plurality=多数制/比例制）、政党数、任期限定
- 动作空间：投票给某党、抗议、服从（LLM 意向），引擎裁决计票
- 不变量：席位守恒 + 每 agent 每期最多一票（平台纪律）
- 测量：选举收敛度（Downs）、有效政党数（Laakso-Taagepera）、合法性指数、抗议率
- 校准靶：Duverger 定律、中位选民收敛
- 基准复现：Downs / Duverger（本包自证题）

联合实验（v2 设计 §3.3）：政治经济学包产生"经济基础变量"（需求冲击→失业），
政治学包处理"政治反应变量"（合法性下降→抗议/投票转向）——同一人群跨包。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.kernel import Invariant, Kernel, KernelConfig  # noqa: E402


class Voter:
    __slots__ = ("id", "preference", "party", "legitimacy", "protest",
                 "economic_state")  # economic_state: 联动接口（失业/贫困）

    def __init__(self, aid, preference):
        self.id = aid
        self.preference = preference      # 政策偏好 [0,1]
        self.party = None                 # 本期投票意向（引擎裁决后）
        self.legitimacy = 0.7             # 合法性感知 [0,1]
        self.protest = False              # 是否抗议
        self.economic_state = "employed"  # 联动：employed/unemployed/poor


class PoliticsPack:
    name = "政治学包"
    version = "0.1"
    description = "选举/合法性/抗议包（Downs/Duverger 基准 + 经济基础→政治反应联动）"
    benchmark_reproductions = ["Downs 中位选民收敛", "Duverger 选举规则定律"]

    def __init__(self, n=200, rule="plurality", n_parties=2, seed=7,
                 economic_states: dict | None = None):
        self.n, self.rule, self.n_parties, self.seed = n, rule, n_parties, seed
        self.rng = np.random.RandomState(seed)
        self.agents: list[Voter] = []
        self.economic_states = economic_states or {}
        self.seats = np.zeros(n_parties, dtype=int)
        self.vote_counts = np.zeros(n_parties, dtype=int)
        self.history: list[dict] = []
        self._dyn_positions: np.ndarray | None = None  # Downs 自适应平台

    def init_world(self, kernel):
        rng = self.rng
        self.agents = []
        self._llm_decided: set[int] = set()  # 本 tick LLM 已决者（step 尊重之）
        for i in range(self.n):
            # 偏好双峰分布（模拟选民极化，Downs 收敛的考题）
            p = float(rng.beta(2, 2))
            v = Voter(i, p)
            v.economic_state = self.economic_states.get(i, "employed")
            self.agents.append(v)
        return self.agents

    def _party_positions(self):
        """党派平台：初始等距；Downs 模式下选后向胜方选民均值自适应移动。"""
        if self._dyn_positions is not None:
            return self._dyn_positions
        return np.linspace(0.05, 0.95, self.n_parties)

    def step(self, kernel, ledger):
        rng = self.rng
        positions = self._party_positions()
        prev_votes = self.vote_counts.copy()
        self.vote_counts[:] = 0
        protest_count = 0
        # 策略性投票（Duverger 涌现机制，T13）：多数制下，最近党若上一期
        # 票份不达 viability 门槛 → 选民以高概率背叛到最近的"可行"党。
        # 比例制无背叛激励（每票都有席位）——定律由行为涌现而非记票构造。
        total_prev = max(1, int(prev_votes.sum()))
        shares_prev = prev_votes / total_prev if prev_votes.sum() > 0 else             np.full(self.n_parties, 1.0 / self.n_parties)
        for v in self.agents:
            # 经济性→合法性传导（联动接口：失业侵蚀合法性，且随失业持续加深）
            if v.economic_state == "unemployed":
                v.legitimacy = max(0.05, v.legitimacy - 0.05)
            elif v.economic_state == "employed":
                v.legitimacy = min(1.0, v.legitimacy + 0.008)
            # 抗议：合法性低 → 概率抗议；失业者结构性怨恨（独立于合法性）
            p_protest = 0.0
            if v.legitimacy < 0.45:
                p_protest = max(p_protest, 0.6 - v.legitimacy)
            if v.economic_state == "unemployed":
                p_protest = max(p_protest, 0.35)
            if rng.rand() < p_protest:
                v.protest = True
                protest_count += 1
            else:
                v.protest = False
            # LLM 已决者（本 tick 经 action_handler）尊重其决定
            if v.id in self._llm_decided:
                if v.party is not None:
                    self.vote_counts[v.party] += 1
                continue
            # 投票：就近党派 + 多党多数制下的策略性背叛（Duverger 涌现机制）。
            # 背叛概率与所选党相对领先者的票份差距成正比——弱党选民逐渐
            # "不浪费选票"地向相近大党集中 → 两党化涌现。两党制不背叛
            # （Duverger 定律的对象是多党系），保 Downs 收敛。
            if not v.protest:
                dists = np.abs(positions - v.preference)
                order = np.argsort(dists)
                choice = int(order[0])
                if self.rule == "plurality" and self.n_parties > 2:
                    top2 = np.argsort(shares_prev)[-2:]  # 前两大党（squeeze 目标）
                    if choice not in top2:
                        leader_share = shares_prev.max()
                        p_desert = 0.8 * (1 - shares_prev[choice] / max(1e-9, leader_share))
                        if rng.rand() < p_desert:
                            # 流向前两大党中较近者——经典 Duverger squeeze
                            choice = int(min(top2, key=lambda i: dists[i]))
                v.party = choice
                self.vote_counts[choice] += 1
            else:
                v.party = None
        # 计票（引擎主权）
        if self.rule == "plurality":
            winner = int(np.argmax(self.vote_counts))
            self.seats[:] = 0
            self.seats[winner] = 1
        else:  # 比例制
            total = max(1, self.vote_counts.sum())
            self.seats = np.round(self.vote_counts / total * 100).astype(int)
        ledger["protest_rate"] = protest_count / self.n
        ledger["legitimacy_mean"] = float(np.mean([v.legitimacy for v in self.agents]))
        ledger["turnout"] = 1 - protest_count / self.n
        # Downs 收敛机制：两党多数制下，败方向胜方选民偏好均值移动（经典空间竞争）
        if self.rule == "plurality" and self.n_parties == 2:
            if self._dyn_positions is None:
                self._dyn_positions = self._party_positions().copy()
            winner = int(np.argmax(self.seats))
            loser = 1 - winner
            supporters = [v.preference for v in self.agents if v.party == winner]
            if supporters:
                mean_pref = float(np.mean(supporters))
                self._dyn_positions[loser] = float(np.clip(
                    0.7 * self._dyn_positions[loser] + 0.3 * mean_pref, 0.0, 1.0))
        self.history.append({
            "seats": self.seats.copy().tolist(),
            "votes": self.vote_counts.copy().tolist(),
            "protest": protest_count,
        })

    def action_handler(self, agent, decision: dict, kernel):
        """LLM 意向：vote(投某党) / protest(抗议) / abstain(弃权)。引擎裁决。"""
        act = str(decision.get("action", "")).lower()
        if act == "vote":
            p = int(decision.get("party", 0))
            agent.party = max(0, min(self.n_parties - 1, p))
            agent.protest = False
            self._llm_decided.add(agent.id)
        elif act == "protest":
            agent.protest = True
            agent.party = None
            self._llm_decided.add(agent.id)
        elif act == "abstain":
            # 弃权：不投票不抗议（计入已决，防止 step 内部逻辑代投）
            agent.party = None
            agent.protest = False
            self._llm_decided.add(agent.id)

    # ---- LLM 语义层钩子（D8 升级：政治学包 LLM 在环）----
    LLM_SYSTEM = ("你是微型社会模拟中的选民。根据处境决定本期行为，"
                  "只输出JSON：{\"action\":\"vote\",\"party\":编号} 或 "
                  "{\"action\":\"protest\"} 或 {\"action\":\"abstain\"}。")

    def collect_llm_requests(self, t: int) -> list:
        """每期抽样 1/3 选民走 LLM 决策（控制成本）。"""
        return [a for a in self.agents if hash((a.id, t)) % 3 == 0]

    def llm_decision_prompt(self, agent, kernel=None) -> list[dict]:
        positions = self._party_positions()
        pl = "；".join(f"党{i}（立场{positions[i]:.2f}）"
                      for i in range(self.n_parties))
        econ = {"employed": "有工作", "unemployed": "失业中"}.get(
            agent.economic_state, agent.economic_state)
        msg = f"""你的政策偏好：{agent.preference:.2f}（0=一端，1=另一端）
各党立场：{pl}
你的处境：{econ}；对当权者的信任度：{agent.legitimacy:.2f}
可选：vote（投某党，附 party 编号）/ protest（上街抗议）/ abstain（不参与）
只输出JSON。"""
        return [{"role": "system", "content": self.LLM_SYSTEM},
                {"role": "user", "content": msg}]

    def rule_decision(self, agent):
        """规则策略：合法性低→抗议，否则投最近党。"""
        if agent.legitimacy < 0.35:
            return {"action": "protest"}
        positions = self._party_positions()
        return {"action": "vote",
                "party": int(np.argmin(np.abs(positions - agent.preference)))}

    def parse_llm_decision(self, text: str) -> Optional[dict]:
        """LLM 输出 → 决策（vote/protest/abstain）；非法返回 None（回退规则）。"""
        from ..agents.decisions import _extract_json
        d = _extract_json(text)
        if not isinstance(d, dict):
            return None
        act = str(d.get("action", "")).strip().lower()
        if act == "vote":
            try:
                p = int(float(d.get("party", 0)))
            except (TypeError, ValueError):
                return None
            return {"action": "vote", "party": p}
        if act in ("protest", "abstain"):
            return {"action": act}
        return None

    invariants = []

    measure_hooks = {
        "effective_parties": None,   # 底部绑定（Laakso-Taagepera）
        "convergence": None,         # 底部绑定（Downs：胜方偏好与中位选民的距）
        "legitimacy": lambda k: float(np.mean([v.legitimacy for v in k.pack.agents])),
        "protest_rate": lambda k: float(np.mean([v.protest for v in k.pack.agents])),
        "turnout": lambda k: float(np.mean([v.party is not None for v in k.pack.agents])),
    }


def _effective_parties(kernel) -> float:
    """Laakso-Taagepera 指数（按**票份**——T13 涌现测量；席位份额由
    记票规则机械决定，不能用于检验 Duverger）。"""
    pack: PoliticsPack = kernel.pack
    s = pack.vote_counts.astype(float)
    total = s.sum()
    if total <= 0:
        return 0.0
    shares = s / total
    return float(1.0 / np.sum(shares ** 2))


def _effective_parties_seats(kernel) -> float:
    """席位版 ENP（对照：多数制下恒=1，机械结果）。"""
    pack: PoliticsPack = kernel.pack
    s = pack.seats.astype(float)
    total = s.sum()
    if total <= 0:
        return 0.0
    shares = s / total
    return float(1.0 / np.sum(shares ** 2))


def _convergence(kernel) -> float:
    """Downs 收敛度：胜方平台与全体选民偏好中位数的 |距|（越小越收敛）。"""
    pack: PoliticsPack = kernel.pack
    if pack.rule != "plurality":
        return float("nan")
    winner = int(np.argmax(pack.seats))
    positions = pack._party_positions()
    median_pref = float(np.median([v.preference for v in pack.agents]))
    return abs(positions[winner] - median_pref)


PoliticsPack.measure_hooks["effective_parties"] = lambda k: _effective_parties(k)
PoliticsPack.measure_hooks["effective_parties_seats"] = lambda k: _effective_parties_seats(k)
PoliticsPack.measure_hooks["convergence"] = lambda k: _convergence(k)
PoliticsPack.calibration_targets = {
    "Duverger": "plurality → 有效政党数→1-2；proportional → >2",
    "Downs": "两党制下胜方平台向中位选民收敛（convergence→小）",
}
PoliticsPack.invariants = [
    Invariant(name="席位守恒", fn=lambda k: float(k.pack.seats.sum()), tol=2.0,
              expected=lambda k: (1.0 if k.pack.rule == "plurality" else 100.0),
              description="多数制总席位=1，比例制=100（四舍五入容差）"),
]


# ============ 基准复现运行器 ============
def run_downs(seed=7, n=200, ticks=30):
    """Downs 基准：两党制多数选举，观察收敛度是否低（中位选民获胜）。"""
    pack = PoliticsPack(n=n, rule="plurality", n_parties=2, seed=seed)
    kernel = Kernel(pack, KernelConfig(seed=seed, invariant_strict=True))
    kernel.init_world()
    conv_fn = PoliticsPack.measure_hooks["convergence"]
    finals = []
    for _ in range(ticks):
        kernel.step()
        finals.append(conv_fn(kernel))
    return {"convergence_tail": float(np.nanmean(finals[-10:])),
            "median": float(np.median([v.preference for v in pack.agents]))}


def run_duverger(seed=7, n=400, ticks=30):
    """Duverger 基准：同一选民，两种选举规则 → 有效政党数分化。"""
    def eff(rule):
        pack = PoliticsPack(n=n, rule=rule, n_parties=4, seed=seed)
        kernel = Kernel(pack, KernelConfig(seed=seed, invariant_strict=True))
        kernel.init_world()
        fn = PoliticsPack.measure_hooks["effective_parties"]
        vals = []
        for _ in range(ticks):
            kernel.step()
            vals.append(fn(kernel))
        return float(np.mean(vals[-10:]))
    return {"plurality": eff("plurality"), "proportional": eff("proportional")}


def run_joint_control(seed=7):
    """对照：无失业注入的政治学基线（同参数）。"""
    pol = PoliticsPack(n=100, rule="plurality", n_parties=2, seed=seed,
                       economic_states={})
    k2 = Kernel(pol, KernelConfig(seed=seed, invariant_strict=True))
    k2.init_world()
    for _ in range(60):
        k2.step()
    return {"protest_rate_final": float(np.mean([v.protest for v in pol.agents])),
            "legitimacy_final": float(np.mean([v.legitimacy for v in pol.agents]))}


def run_joint_econ_politics(seed=7, shock_factor=0.45):
    """【参数注入型传导】联合实验（v2 设计 §3.3）：政治经济学冲击 → 失业 → 政治反应。
    注意：失业→合法性/怨恨为机制装填（非涌现）；差分结果真实但传导机制系预设，
    涌现版本列为后续工作。

    流程：polecon 包跑 200 tick（含 tick100 需求冲击）→ 收集失业 agent
    → 把 economic_states 注入政治学包 → 观察合法性/抗议/投票率变化。
    """
    import src.packs.polecon as polecon
    from src.agents.decisions import rule_decision
    pe = polecon.make_pack(population={"n": 100}, institutions={"制度": "private"},
                           seed=seed,
                           intervention={"shock_tick": 100,
                                         "shock_factor": shock_factor})
    k1 = Kernel(pe, KernelConfig(seed=seed))
    k1.init_world()
    for t in range(200):
        for a in k1.agents:
            pe.action_handler(a, rule_decision(a, pe.world), k1)
        k1.step()
    econ = {}
    for a in k1.agents:
        econ[a.id] = "unemployed" if (a.position == "unemployed"
                                      or a.savings < 5) else "employed"
    n_unemp = sum(1 for v in econ.values() if v == "unemployed")

    # 政治学阶段：同一人群，带经济状态
    pol = PoliticsPack(n=100, rule="plurality", n_parties=2, seed=seed,
                       economic_states=econ)
    k2 = Kernel(pol, KernelConfig(seed=seed, invariant_strict=True))
    k2.init_world()
    # 把合法性初值与经济状态挂钩（失业者初始合法性低）
    for v in pol.agents:
        if v.economic_state == "unemployed":
            v.legitimacy = 0.25  # 低于抗议阈值 0.45：失业者进入抗议轨道
    legit_traj, protest_traj = [], []
    for _ in range(60):
        k2.step()
        legit_traj.append(PoliticsPack.measure_hooks["legitimacy"](k2))
        protest_traj.append(PoliticsPack.measure_hooks["protest_rate"](k2))
    return {"n_unemployed": n_unemp,
            "legitimacy_final": legit_traj[-1],
            "protest_rate_final": protest_traj[-1],
            "protest_rate_max": max(protest_traj),
            "legitimacy_traj": legit_traj[::10]}




# ---- 场景工厂 + 包注册（T2）----
def make_pack(population=None, institutions=None, seed=42, intervention=None):
    pop = population or {}
    inst = institutions or {}
    return PoliticsPack(
        n=int(pop.get("n", 200)),
        rule=str(inst.get("选举规则", "plurality")),
        n_parties=int(pop.get("党派数", inst.get("党派数", 2))),
        seed=seed,
        economic_states=None)


from ..kernel.core import TheoryPack, register_pack as _rp  # noqa: E402

_rp(TheoryPack(
    name="政治学包",
    description=PoliticsPack.description,
    factory=lambda pop, inst, seed, interv: make_pack(pop, inst, seed, interv),
    invariants=PoliticsPack.invariants,
    calibration_targets=PoliticsPack.calibration_targets,
    benchmark_reproductions=PoliticsPack.benchmark_reproductions,
))


if __name__ == "__main__":
    d = run_downs()
    print(f"Downs: 收敛度(胜方-中位)={d['convergence_tail']:.3f}（中位偏好 {d['median']:.2f}）")
    v = run_duverger()
    print(f"Duverger: 多数制有效政党={v['plurality']:.2f}，比例制={v['proportional']:.2f}")
    j = run_joint_econ_politics()
    print(f"联合实验：失业{j['n_unemployed']}人 → 合法性{j['legitimacy_final']:.2f}，"
          f"抗议率峰值{j['protest_rate_max']:.2f}")
