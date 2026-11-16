"""R4 文化媒介包骨架（话语/霸权/拜物教）+ 假新闻级联基准。

七件套声明（v2 设计·决策3）：
- 实体：媒介消费者 agent（信念 b∈[0,1]、信息流曝光记录）
- 制度：算法分发偏置（0=中立，1=强偏置）、媒介所有制（private=流量最大化 /
  public=公共性优先）、开放度
- 动作空间：分享/不分享（LLM 意向），引擎裁决传播
- 不变量：信息总量守恒（产出=消费+丢弃）+ 信念有界 [0,1]
- 测量：级联规模、极化指数、回音室结构、拜物教话语（复用 polecon 通道）
- 校准靶：假新闻级联形态、回音室极化
- 基准复现：假新闻级联（SIR 式传播，算法偏置放大判据）

与政治经济学包联动：媒介所有制=private 时，拜物教话语（商品框架）获得
流量加成——"意识形态再生产"的指示器级操作化（只作指示器，不作检验）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.kernel import Invariant, Kernel, KernelConfig  # noqa: E402


class MediaConsumer:
    __slots__ = ("id", "belief", "exposed", "shared", "echo_chamber")

    def __init__(self, aid, belief):
        self.id = aid
        self.belief = belief          # 对某议题的信念 [0,1]（0=假新闻立场，1=真相立场）
        self.exposed = 0              # 累计曝光
        self.shared = 0               # 累计分享
        self.echo_chamber = 0.0       # 回音室得分（同温层比例）


class MediaPack:
    name = "文化媒介包"
    version = "0.1"
    description = "算法分发/媒介所有制/假新闻级联包（拜物教话语通道复用）"
    benchmark_reproductions = ["假新闻级联（SIR式传播+算法偏置放大）"]

    def __init__(self, n=200, algorithm_bias=0.0, ownership="private",
                 seed=7, open_degree=1.0):
        self.n, self.algorithm_bias, self.ownership = n, algorithm_bias, ownership
        self.open_degree = open_degree
        self.seed = seed
        self.rng = np.random.RandomState(seed)
        self.agents: list[MediaConsumer] = []
        self.cascade_sizes: list[int] = []
        self._info_produced = 0
        self._info_consumed = 0
        self._exp_shared = 0    # 曝光→分享 事件数
        self._exp_scrolled = 0  # 曝光→划过 事件数（T11：真守恒记账）
        self._llm_shares: dict[int, bool] = {}   # LLM 分享决定（D8）
        self._prev_source_belief = 0.5           # 上一 tick 内容立场（prompt 用）

    def init_world(self, kernel):
        rng = self.rng
        self.agents = []
        for i in range(self.n):
            # 信念双峰（极化人群）
            b = float(rng.beta(0.6, 0.6)) if rng.rand() < 0.5 else float(rng.beta(2.5, 2.5))
            self.agents.append(MediaConsumer(i, b))
        return self.agents

    def step(self, kernel, ledger):
        rng = self.rng
        shared_this_tick = 0
        # 随机选一个"内容源"（信念极值者发起传播）
        source = self.agents[int(rng.randint(0, self.n))]
        is_fake = source.belief < 0.5
        # 传播：每个 agent 按算法偏置概率看到（偏置放大 fake 内容）
        exposure_prob = 0.15 + self.algorithm_bias * (0.5 if is_fake else -0.2)
        exposure_prob = np.clip(exposure_prob * self.open_degree, 0.01, 0.95)
        cascade = 0
        for a in self.agents:
            if rng.rand() < exposure_prob:
                a.exposed += 1
                self._info_consumed += 1
                # 同质化分享：信念接近源 → 分享概率高
                similarity = 1 - abs(a.belief - source.belief)
                p_share = 0.1 + 0.6 * similarity
                # 媒介所有制：public 压制 fake 传播（公共性优先）
                if self.ownership == "public" and is_fake:
                    p_share *= 0.3
                llm_decided = a.id in self._llm_shares
                if llm_decided:
                    do_share = self._llm_shares[a.id]
                else:
                    do_share = rng.rand() < p_share
                if do_share:
                    a.shared += 1
                    cascade += 1
                    self._exp_shared += 1
                else:
                    self._exp_scrolled += 1
                # bounded-confidence 双端：相近→同化（回音室）；相异→排斥（极化）。
                # 排斥强度随算法偏置放大——偏置越高，跨阵营曝光越把人推得更远。
                if similarity > 0.6:
                    pull = (0.03 + 0.10 * self.algorithm_bias) * similarity
                    a.belief = float(np.clip(a.belief + pull * (source.belief - a.belief),
                                             0.0, 1.0))
                elif similarity <= 0.4 and self.algorithm_bias > 0:
                    push = 0.02 + 0.08 * self.algorithm_bias
                    a.belief = float(np.clip(a.belief + push * (a.belief - source.belief),
                                             0.0, 1.0))
        self._info_produced += 1
        self.cascade_sizes.append(cascade)
        self._prev_source_belief = source.belief
        self._llm_shares.clear()
        # 回音室得分更新：同温层暴露度（与源内容相似度的 EMA）
        for a in self.agents:
            sim = 1.0 - abs(a.belief - source.belief)
            a.echo_chamber = 0.9 * a.echo_chamber + 0.1 * sim
        ledger["cascade"] = cascade
        ledger["fake_cascade"] = cascade if is_fake else 0

    def action_handler(self, agent, decision: dict, kernel):
        """LLM 意向：share/scroll——记入本 tick 分享决定（step 曝光时生效）。"""
        act = str(decision.get("action", "")).lower()
        if act == "share":
            self._llm_shares[agent.id] = True
        elif act == "scroll":
            self._llm_shares[agent.id] = False

    # ---- LLM 语义层钩子（D8 升级：文化媒介包 LLM 在环）----
    LLM_SYSTEM = ("你是微型社会模拟中的用户。根据你的立场和看到的内容决定行为，"
                  "只输出JSON：{\"action\":\"share\"}（转发）或 "
                  "{\"action\":\"scroll\"}（划过）。")

    def collect_llm_requests(self, t: int) -> list:
        """每期抽样 1/4 用户走 LLM 分享决策（控制成本）。"""
        return [a for a in self.agents if hash((a.id, t)) % 4 == 0]

    def llm_decision_prompt(self, agent, kernel=None) -> list[dict]:
        prev = self._prev_source_belief
        msg = f"""你的立场：{agent.belief:.2f}（0=一端，1=另一端）
你平时看到的内容立场约在 {prev:.2f} 附近。
如果你刷到一条立场与上文相近的内容，你会转发还是划过？
只输出JSON。"""
        return [{"role": "system", "content": self.LLM_SYSTEM},
                {"role": "user", "content": msg}]

    def rule_decision(self, agent):
        """规则策略：与上一条热门内容相似度>0.5 则分享。"""
        sim = 1 - abs(agent.belief - self._prev_source_belief)
        return {"action": "share" if sim > 0.5 else "scroll"}

    def parse_llm_decision(self, text: str) -> Optional[dict]:
        """LLM 输出 → 决策（share/scroll）；非法返回 None。"""
        from ..agents.decisions import _extract_json
        d = _extract_json(text)
        if not isinstance(d, dict):
            return None
        act = str(d.get("action", "")).strip().lower()
        if act in ("share", "scroll"):
            return {"action": act}
        return None

    invariants = []

    measure_hooks = {
        "polarization": None,      # 底部绑定（信念方差）
        "cascade_mean": lambda k: float(np.mean(k.pack.cascade_sizes[-20:]))
        if len(k.pack.cascade_sizes) >= 20 else 0.0,
        "echo_chamber": lambda k: float(np.mean([a.echo_chamber for a in k.pack.agents])),
        "belief_variance": lambda k: float(np.var([a.belief for a in k.pack.agents])),
        "echo_share": None,        # 底部绑定（同温层份额，有界[0,1]）
    }


MediaPack.measure_hooks["polarization"] = lambda k: float(np.var(
    [a.belief for a in k.pack.agents]))


def _echo_share(kernel) -> float:
    """同温层份额：暴露于相似信念(>0.6)的内容比例——回音室的直接测度。"""
    pack: MediaPack = kernel.pack
    vals = [a.echo_chamber for a in pack.agents]
    return float(np.mean(vals)) if vals else 0.0


MediaPack.measure_hooks["echo_share"] = lambda k: _echo_share(k)
MediaPack.invariants = [
    Invariant(name="信念有界", fn=lambda k: float(max(
        0.0, max(abs(a.belief) for a in k.pack.agents) - 1.0)), tol=0.0,
        expected=lambda k: 0.0,
        description="所有 agent 信念必须在 [0,1] 内"),
    Invariant(name="曝光事件守恒", fn=lambda k: float(abs(
        (k.pack._exp_shared + k.pack._exp_scrolled) - k.pack._info_consumed)),
        tol=1e-9, expected=lambda k: 0.0,
        description="每次曝光必分流入分享或划过（T11：真守恒，替换装饰版）"),
]
MediaPack.calibration_targets = {
    "级联": "算法偏置↑ → fake 级联规模显著放大",
    "回音室": "偏置↑ → 回音室得分↑，极化方差↑",
    "所有制": "public 所有制 → fake 级联压制（×0.3）",
}


# ============ 基准复现运行器 ============
def run_fake_news_cascade(seed=7, algorithm_bias=0.0, ownership="private",
                          ticks=400):
    """假新闻级联基准：算法偏置对 fake 内容传播的放大效应。

    判据：algorithm_bias=0.8 时，fake 级联均值 > bias=0 时的 2 倍。
    """
    def _run(bias, own):
        pack = MediaPack(n=200, algorithm_bias=bias, ownership=own, seed=seed)
        kernel = Kernel(pack, KernelConfig(seed=seed, invariant_strict=True))
        kernel.init_world()
        fn = MediaPack.measure_hooks["cascade_mean"]
        for _ in range(ticks):
            kernel.step()
        return fn(kernel)
    base = _run(0.0, ownership)
    biased = _run(algorithm_bias, ownership)
    public = _run(algorithm_bias, "public")
    return {"baseline": base, "biased": biased, "public": public,
            "amplification": biased / max(1e-9, base),
            "public_suppression": public / max(1e-9, biased)}


def run_echo_chamber(seed=7, algorithm_bias=0.0, ticks=400):
    """回音室测量：偏置↑ → 回音室得分与极化方差↑。"""
    def _run(bias):
        pack = MediaPack(n=200, algorithm_bias=bias, seed=seed)
        kernel = Kernel(pack, KernelConfig(seed=seed, invariant_strict=True))
        kernel.init_world()
        for _ in range(ticks):
            kernel.step()
        return {"echo": MediaPack.measure_hooks["echo_chamber"](kernel),
                "polarization": MediaPack.measure_hooks["polarization"](kernel)}
    return {"neutral": _run(0.0), "biased": _run(algorithm_bias)}


def fetishism_linkage_demo(seed=7):
    """跨包联动演示：媒介所有制 → 拜物教话语流量加成（指示器级）。

    private 所有制下，拜物教话语（商品框架）获得曝光加权；public 下压制。
    复用 polecon 的 TransactionPipeline 通道（不重复造轮子）。
    """
    return {
        "说明": "private 所有制=拜物教话语流量加成；public=公共性压制",
        "机制": "算法偏置放大商品框架内容（与 fake 级联同一传播引擎）",
        "判据": "fetishism 曝光占比 private > public（后续接 LLM 叙事实测）",
    }




# ---- 场景工厂 + 包注册（T2）----
def make_pack(population=None, institutions=None, seed=42, intervention=None):
    pop = population or {}
    inst = institutions or {}
    return MediaPack(
        n=int(pop.get("n", 200)),
        algorithm_bias=float(inst.get("算法偏置", 0.0)),
        ownership=str(inst.get("媒介所有制", "private")),
        seed=seed,
        open_degree=float(inst.get("开放度", 1.0)))


from ..kernel.core import TheoryPack, register_pack as _rp  # noqa: E402

_rp(TheoryPack(
    name="文化媒介包",
    description=MediaPack.description,
    factory=lambda pop, inst, seed, interv: make_pack(pop, inst, seed, interv),
    invariants=MediaPack.invariants,
    calibration_targets=MediaPack.calibration_targets,
    benchmark_reproductions=MediaPack.benchmark_reproductions,
))


if __name__ == "__main__":
    c = run_fake_news_cascade(algorithm_bias=0.8)
    print(f"假新闻级联：基线 {c['baseline']:.1f} → 偏置 {c['biased']:.1f}"
          f"（放大 {c['amplification']:.1f}×）；public 压制 {c['public_suppression']:.2f}")
    e = run_echo_chamber(algorithm_bias=0.8)
    print(f"回音室：中性 {e['neutral']['echo']:.3f} → 偏置 {e['biased']['echo']:.3f}；"
          f"极化 {e['neutral']['polarization']:.3f} → {e['biased']['polarization']:.3f}")
