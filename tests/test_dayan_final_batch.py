"""终批验收：beh_abm/beh_mind/beh_rl/net_extended/landuse_ca/eco_final/app_final。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dayan import simulate  # noqa: E402
from dayan.models import beh_abm, beh_mind, beh_rl  # noqa: E402
from dayan.models import eco_final, landuse_ca, net_extended  # noqa: E402
from dayan.models.app_final import (ALL_APP_FINAL,  # noqa: E402
                                    build_all_app_final)


def _smoke_module(module, skip=("_Base", "_LandBase", "per_comm_rounded",
                                "_TinyGridEnv", "_MLP", "_ContBandit",
                                "_MatrixGameEnv", "_PolicyGradBase",
                                "_DQNBase", "_TabularRLBase",
                                "_ContActorCriticBase", "_MARLBase",
                                "_StrategyDuel", "_ABMBase", "_GameEvolModel",
                                "_NormSimBase", "_LLMAdapterStub", "rng_deg")):
    bad = []
    n = 0
    rng = np.random.default_rng(0)
    for name, cls in list(vars(module).items()):
        if name in skip or not isinstance(cls, type):
            continue
        if getattr(cls, "__module__", "") != module.__name__:
            continue
        n += 1
        try:
            m = cls()
            ct = getattr(m, "clock_type", "fixed_step")
            if ct in ("jump", "ode", "sde", "des"):
                horizon = 60.0 if ct == "des" else 20.0
                r = simulate(m, horizon=horizon, dt=0.05, parameters={}, rng=rng)
                if not r["final"]:
                    bad.append((name, "empty"))
            else:
                m.initialize({}, {}, None, None, rng)
                for _ in range(3):
                    m.step(0, 0.1)
                if not m.observe():
                    bad.append((name, "empty"))
        except Exception as e:                             # noqa: BLE001
            bad.append((name, repr(e)[:90]))
    return n, bad


def test_all_modules_runnable():
    """六个新模块全部类可运行（含 RL 训练型）。"""
    total = 0
    all_bad = []
    for mod in (beh_abm, beh_mind, net_extended, landuse_ca, eco_final):
        n, bad = _smoke_module(mod)
        total += n
        all_bad += bad
    assert not all_bad, f"{all_bad}"
    print(f"[PASS] 终批模块：{total} 个类全部可运行")


def test_rl_family_learn():
    """RL 17 模型：训练完成并给出诊断。"""
    d = beh_rl.build_all_rl()
    bad = []
    rng = np.random.default_rng(0)
    for mid, m in d.items():
        m.initialize({}, {}, None, None, rng)
        if not m.observe():
            bad.append(mid)
    assert not bad, f"RL 失败 {bad}"
    # 抽查学习信号：Q-learning 学到右行
    m = d["BEH112"]
    greedy = m.observe()["greedy_actions"]
    assert greedy[:3] == [1, 1, 1], f"Q-learning 未学最优 {greedy}"
    print(f"[PASS] RL 全家：{len(d)} 个训练完成 + 学习信号验证")


def test_mind_architectures():
    """认知/生成式骨架：OCC 情绪、Sigma 消息传递、ReAct 环、GraphRAG 检索。"""
    d = beh_mind.build_all_mind()
    rng = np.random.default_rng(0)
    occ = d["BEH099"]
    occ.initialize({}, {}, None, None, rng)
    occ.step(0, 0.1)
    o = occ.observe()
    assert o["n_emotions"] >= 3, f"OCC 情绪不足 {o}"
    sigma = d["BEH098"]
    sigma.initialize({}, {}, None, None, rng)
    sigma.step(0, 0.1)
    assert "belief_X" in sigma.observe()
    react = d["BEH130"]
    react.initialize({}, {}, None, None, rng)
    # 2026-11-13 重写后思考-行动-观察环由 step 驱动（initialize 仅建骨架）
    react.step(0, 0.1)
    assert react.observe()["actions_executed"] >= 1,         f"ReAct 环未执行 {react.observe()}"
    rag = d["BEH134"]
    rag.initialize({}, {}, None, None, rng)
    rag_o = rag.observe()
    assert any(k in rag_o for k in ("retrieval_2hop", "evidence", "hops")),         f"GraphRAG 检索观测缺失 {list(rag_o)}"
    print(f"[PASS] 认知/生成式骨架：OCC/Sigma/ReAct/GraphRAG 机制验证")


def test_key_net_extended_benchmarks():
    """Eisenberg-Noe 清算可行性 + DebtRank 传染 + Motter-Lai 级联。"""
    from dayan.models.net_extended import (EisenbergNoeModel,  # noqa: E402
                                           DebtRankModel, MotterLaiModel)
    en = EisenbergNoeModel()
    en.initialize({}, {}, None, None, np.random.default_rng(0))
    assert en.observe()["clearing_feasible"]
    dr = DebtRankModel()
    dr.initialize({}, {}, None, None, np.random.default_rng(0))
    assert dr.observe()["contagion"]
    ml = MotterLaiModel()
    ml.initialize({}, {}, None, None, np.random.default_rng(0))
    ml.step(0, 0.1)
    assert ml.observe()["cascade_happened"]
    print("[PASS] 金融级联：清算可行 + DebtRank 传染 + Motter-Lai 级联")


def test_landuse_and_apps():
    """土地利用 CA 族 + APP 终批场景。"""
    rng = np.random.default_rng(0)
    we = landuse_ca.WhiteEngelenModel()
    we.initialize({}, {}, None, None, rng)
    for _ in range(20):
        we.step(0, 1.0)
    o = we.observe()
    assert o["city_frac"] > 0.01, "White-Engelen 城市未增长"

    apps = build_all_app_final()
    bad = []
    for mid, m in apps.items():
        m.initialize({}, {}, None, None, rng)
        for _ in range(3):
            m.step(0, 0.1)
        if not m.observe():
            bad.append(mid)
    assert not bad, f"APP 失败 {bad}"
    print(f"[PASS] 土地利用 CA + APP 终批 {len(apps)} 场景全可运行")


if __name__ == "__main__":
    test_all_modules_runnable()
    test_rl_family_learn()
    test_mind_architectures()
    test_key_net_extended_benchmarks()
    test_landuse_and_apps()
    print("\n===== 终批（认知/RL/NET扩展/土地利用/经济终量/APP）：全部通过 =====")
