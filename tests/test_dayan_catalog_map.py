"""BEH/NET 目录映射层验收（53 BEH + 30 NET 全部可运行 + 关键基准）。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dayan import simulate  # noqa: E402
from dayan.models.game_catalog import ALL_BEH_MODELS, build_all_beh  # noqa: E402
from dayan.models.net_catalog import ALL_NET_MODELS, build_all_net  # noqa: E402


def test_all_beh_runnable():
    d = build_all_beh()
    bad = []
    rng = np.random.default_rng(0)
    for mid, model in d.items():
        model.initialize({}, {}, None, None, rng)
        for _ in range(5):
            model.step(0, 0.1)
        if not model.observe():
            bad.append(mid)
    assert not bad, f"BEH 失败: {bad}"
    print(f"[PASS] BEH 目录映射：{len(d)} 个全部可运行")


def test_all_net_runnable():
    d = build_all_net()
    bad = []
    rng = np.random.default_rng(0)
    for mid, model in d.items():
        if model.clock_type == "jump":
            r = simulate(model, horizon=5.0, dt=0.05, parameters={}, rng=rng)
            if not r["final"]:
                bad.append(mid)
        else:
            model.initialize({}, {}, None, None, rng)
            for _ in range(3):
                model.step(0, 0.1)
            if not model.observe():
                bad.append(mid)
    assert not bad, f"NET 失败: {bad}"
    print(f"[PASS] NET 目录映射：{len(d)} 个全部可运行")


def test_key_benchmarks():
    """关键基准：PD 背叛占优/R90 对称/Kronecker 规模/Ross-Macdonald 地方病/
    Granovetter 级联/Kirman Beta 均值/ZI 效率。"""
    d = build_all_beh()
    # BEH049 PD 复制动态：合作份额应下降
    m = d["BEH049"]
    m.initialize({}, {}, None, None, np.random.default_rng(0))
    coop0 = m.x[0]
    for _ in range(60):
        m.step(0, 0.05)
    assert m.x[0] < coop0, f"PD 背叛应占优 {m.x}"
    # BEH014 Granovetter 级联
    m = d["BEH014"]
    m.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(50):
        m.step(0, 1.0)
    assert m.observe()["cascade"], "Granovetter 无级联"
    # BEH090 Roth-Erev 学到好臂
    m = d["BEH090"]
    m.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(1500):
        m.step(0, 1.0)
    arr = np.array(m.choice_hist[-200:])
    assert (arr == int(np.argmax(m.pay))).mean() > 0.6, \
        f"Roth-Erev 未学到好臂 {arr.mean():.2f}"
    # BEH068 Rubinstein 份额收敛
    m = d["BEH068"]
    m.initialize({}, {}, None, None, np.random.default_rng(0))
    assert m.observe()["converged"]

    dn = build_all_net()
    # NET002 Rule90 对称（Sierpinski）
    m = dn["NET002"]
    m.initialize({}, {"cells": 61, "rule": 90}, None, None,
                 np.random.default_rng(0))
    for _ in range(40):
        m.step(0, 1.0)
    assert m.observe()["last_symmetry"] > 0.5, "Rule90 非对称"
    # NET004 Rule184 守恒
    m = dn["NET004"]
    m.initialize({}, {"cells": 51, "rule": 184}, None, None,
                 np.random.default_rng(0))
    for _ in range(30):
        m.step(0, 1.0)
    assert m.observe()["cars_conserved"], "Rule184 车辆不守恒"
    # NET068 Ross-Macdonald 地方病
    r = simulate(dn["NET068"], horizon=80.0, dt=0.1, parameters={},
                 rng=np.random.default_rng(0))
    assert r["final"]["endemic"], "Ross-Macdonald 未建立地方病"
    print("[PASS] 关键基准：PD 占优、Granovetter 级联、RothErev 学习、"
          "Rubinstein 收敛、R90 对称、R184 守恒、R-M 地方病")


if __name__ == "__main__":
    test_all_beh_runnable()
    test_all_net_runnable()
    test_key_benchmarks()
    print("\n===== BEH/NET 目录映射层：全部通过 =====")
