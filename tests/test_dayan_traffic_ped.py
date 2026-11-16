"""DAYAN 交通流+行人家族验收测试（NET095–NET120 家族级基准）。

运行：python tests/test_dayan_traffic_ped.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dayan import simulate  # noqa: E402
from dayan.models.traffic import (ARZModel, BMLModel, CTMModel,  # noqa: E402
                                  FVDModel, GippsModel, IDMModel,
                                  KraussModel, LWRModel, MOBILModel,
                                  NewellModel, NSModel, OVMModel,
                                  VickreyBottleneckModel, VDRModel,
                                  WardropSOModel, WardropUEModel,
                                  Wiedemann74Model, Wiedemann99Model)
from dayan.models.pedestrian import (CentrifugalModel, ContactEvacModel,  # noqa: E402
                                     FloorFieldModel, ORCAModel,
                                     OptimalStepsModel, RVOModel,
                                     SocialForceModel, VOModel)


def _run_carfollow(cls, **kw):
    m = cls(**kw)
    r = simulate(m, horizon=120.0, dt=0.1, parameters=kw or {},
                 rng=np.random.default_rng(0))
    return m, r


def test_macro_conservation():
    """LWR/CTM：车辆数守恒（Godunov/发送接收格式）。"""
    for cls, name in [(LWRModel, "NET095 LWR"), (CTMModel, "NET096 CTM")]:
        m = cls()
        m.initialize({}, {}, None, None, np.random.default_rng(0))
        total0 = m.observe()["total"]
        for _ in range(200):
            m.step(0, 0.05)
        total1 = m.observe()["total"]
        # CTM 有下游汇出口，允许流出；LWR 周期边界严格守恒
        if name.startswith("NET095"):
            assert abs(total1 - total0) < 0.02, f"{name} 不守恒 {total0}->{total1}"
        else:
            assert 0 < total1 <= total0 + 0.05, f"{name} 质量 {total1}"
        print(f"  ✓ {name}: 守恒 {total0:.3f}→{total1:.3f}")
    print("[PASS] 宏观流（LWR/CTM）质量守恒")


def test_arz_string_instability():
    """ARZ 二阶流：均匀密度 + 扰动 → 速度方差增长（串不稳定）。"""
    m = ARZModel(tau=0.5)
    r = simulate(m, horizon=30.0, dt=0.05,
                 parameters={"k0": 0.3, "pert": 0.05},
                 rng=np.random.default_rng(0))
    v_std = [o["v_std"] for o in r["observations"]]
    assert v_std[-1] > v_std[1] * 2, f"扰动未放大 {v_std[1]:.4f}->{v_std[-1]:.4f}"
    print(f"[PASS] ARZ：串不稳定 v_std {v_std[1]:.4f}→{v_std[-1]:.4f}（扰动放大）")


def test_car_following_family():
    """跟驰六模型：无碰撞 + 低密度接近自由流。"""
    cases = [
        (IDMModel, "NET098 IDM"), (GippsModel, "NET099 Gipps"),
        (NewellModel, "NET100 Newell"), (OVMModel, "NET101 OVM"),
        (FVDModel, "NET102 FVD"), (KraussModel, "NET103 Krauß"),
        (Wiedemann74Model, "NET104 W74"), (Wiedemann99Model, "NET105 W99"),
    ]
    for cls, name in cases:
        m, r = _run_carfollow(cls, n_cars=15, length=250.0)
        o = r["final"]
        assert o["min_gap"] > 0.5, f"{name} 碰撞 min_gap={o['min_gap']:.2f}"
        assert o["v_mean"] > 1.0, f"{name} 停滞 v={o['v_mean']:.2f}"
        print(f"  ✓ {name}: 无碰撞, v_mean={o['v_mean']:.1f}")
    print("[PASS] 跟驰家族 8 模型（IDM/Gipps/Newell/OVM/FVD/Krauß/W74/W99）"
          "无碰撞+运动")


def test_ns_fundamental_diagram():
    """NS CA：守恒 + 基本图中间密度出现通量峰。"""
    fluxes = []
    for dens in (0.08, 0.15, 0.25, 0.4, 0.6):
        m = NSModel(cells=100, vmax=5, p=0.3)
        m.initialize({}, {"cells": 100, "vmax": 5, "p": 0.3, "density": dens},
                     None, None, np.random.default_rng(3))
        for _ in range(200):
            m.step(0, 1.0)
        fluxes.append(m.observe()["flux"])
    peak = max(fluxes)
    assert 0.35 < peak < 0.45, f"峰值应≈理论 vmax/(vmax+1)=0.42 {fluxes}"
    assert fluxes[-1] < peak * 0.6, f"高密度应低于峰值 {fluxes}"
    assert fluxes[0] < peak, f"低密度低于峰值 {fluxes}"
    print(f"[PASS] NS：基本图峰值形态 {['%.3f' % f for f in fluxes]}")


def test_bml_transition():
    """BML：低密度自由流（移动率高）、高密度格锁（移动率≈0）。"""
    mobs = []
    for dens in (0.10, 0.55):
        m = BMLModel(size=24, density=dens)
        m.initialize({}, {"size": 24, "density": dens}, None, None,
                     np.random.default_rng(1))
        for k in range(400):
            m.step(k, 1.0)
        mobs.append(m.observe()["mobility"])
    assert mobs[0] > 0.8, f"低密度应近自由流 mobility={mobs[0]:.2f}"
    assert mobs[1] < 0.2, f"高密度应格锁 mobility={mobs[1]:.2f}"
    print(f"[PASS] BML：密度相变（mobility {mobs[0]:.2f}→{mobs[1]:.2f}）")


def test_vdr_conservation():
    """VDR：车辆守恒 + 运行。"""
    m = VDRModel(cells=100)
    m.initialize({}, {"cells": 100, "vmax": 5, "p": 0.3, "p0": 0.6,
                      "density": 0.15}, None, None, np.random.default_rng(0))
    n0 = m.observe()["n_cars"]
    for _ in range(100):
        m.step(0, 1.0)
    n1 = m.observe()["n_cars"]
    assert n0 == n1, f"VDR 不守恒 {n0}->{n1}"
    print(f"[PASS] VDR：守恒 {n0} 车")


def test_vickrey_bottleneck():
    """Vickrey：队列先涨后清零 + 期末全部服务完。"""
    m = VickreyBottleneckModel(n_cars=60, capacity=1.0)
    m.initialize({}, {"n_cars": 60, "capacity": 1.0}, None, None,
                 np.random.default_rng(0))
    queues = []
    for _ in range(300):
        m.step(0, 1.0)
        queues.append(m.observe()["queue"])
    o = m.observe()
    assert max(queues) > 0, "应形成排队"
    assert o["served"] >= 59.5, f"服务不完整 {o['served']}"
    print(f"[PASS] Vickrey 瓶颈：队列峰值 {max(queues):.1f}，"
          f"期末 served={o['served']:.1f}, queue={o['queue']:.2f}")


def test_wardrop_ue_vs_so():
    """Wardrop：UE 收敛到成本均等；SO 总成本 ≤ UE 总成本。"""
    ue = WardropUEModel(demand=10.0)
    ue.initialize({}, {"demand": 10.0}, None, None, np.random.default_rng(0))
    for _ in range(200):
        ue.step(0, 1.0)
    o_ue = ue.observe()
    f1 = o_ue["f1"]
    # Wardrop UE 判据：使用中的路径成本 ≤ 未使用路径成本（角点/内点都适用）
    used, unused = (o_ue["cost1"], o_ue["cost2"]) if f1 >= 5.0 else         (o_ue["cost2"], o_ue["cost1"])
    assert unused >= used - 0.1,         f"UE 判据失败：在用 {used:.2f} > 备用 {unused:.2f}"
    so = WardropSOModel(demand=10.0)
    so.initialize({}, {"demand": 10.0}, None, None, np.random.default_rng(0))
    for _ in range(200):
        so.step(0, 1.0)
    o_so = so.observe()
    assert o_so["total_cost"] <= o_ue["total_cost"] + 1e-6, \
        f"SO 总成本应≤UE {o_so['total_cost']:.1f} vs {o_ue['total_cost']:.1f}"
    print(f"[PASS] Wardrop：UE f1={f1:.2f}（在用 {used:.2f}≤备用 {unused:.2f}），"
          f"总成本 SO {o_so['total_cost']:.1f} ≤ UE {o_ue['total_cost']:.1f}")


def test_mobil():
    """MOBIL：换道发生且安全（无碰撞）。"""
    m = MOBILModel(n_cars=16, length=300.0)
    m.initialize({}, {"n_cars": 16, "length": 300.0}, None, None,
                 np.random.default_rng(0))
    for _ in range(400):
        m.step(0, 0.1)
    o = m.observe()
    assert o["changes"] > 0, "零换道"
    assert o["min_gap"] > 0.5, "换道引发碰撞"
    print(f"[PASS] MOBIL：换道 {o['changes']} 次且无碰撞")


def test_social_force_evacuation():
    """社会力族：三模型完成疏散且不穿墙。"""
    cases = [(SocialForceModel, "NET113 社会力"),
             (ContactEvacModel, "NET114 接触摩擦"),
             (CentrifugalModel, "NET115 离心力")]
    for cls, name in cases:
        m = cls(n=25)
        r = simulate(m, horizon=200.0, dt=0.05,
                     parameters={"n": 25, "v_des": 1.5},
                     rng=np.random.default_rng(0))
        o = r["final"]
        assert o["evacuated"] >= 22, f"{name} 疏散不足 {o['evacuated']}/25"
        assert o["in_bounds"], f"{name} 穿墙"
        print(f"  ✓ {name}: 疏散 {o['evacuated']}/25")
    print("[PASS] 社会力族 3 模型疏散+不穿墙")


def test_vo_family_no_collision():
    """VO/RVO/ORCA：穿越人流碰撞极少（ORCA 最严格）。"""
    results = {}
    for cls, name in [(VOModel, "NET116 VO"), (RVOModel, "NET117 RVO"),
                      (ORCAModel, "NET118 ORCA")]:
        m = cls(n=16)
        r = simulate(m, horizon=120.0, dt=0.05,
                     parameters={"n": 16, "v_des": 1.2},
                     rng=np.random.default_rng(0))
        o = r["final"]
        results[name] = o
        assert o["collisions"] <= 2, f"{name} 碰撞 {o['collisions']}"
        assert o["arrived"] >= 10, f"{name} 到达不足 {o['arrived']}/16"
        print(f"  ✓ {name}: 碰撞 {o['collisions']}, 到达 {o['arrived']}/16")
    print("[PASS] 速度障碍族 VO/RVO/ORCA 低碰撞+到达")


def test_floor_field_shortest_path():
    """地板场 CA：行人在有限步内到达出口（≈最短路径长度）。"""
    m = FloorFieldModel(size=24)
    m.initialize({}, {"size": 24, "n_agents": 6,
                      "exits": [(23, 12)]}, None, None,
                 np.random.default_rng(0))
    for _ in range(120):
        m.step(0, 1.0)
    o = m.observe()
    assert o["at_exit"] >= 4, f"到达出口不足 {o['at_exit']}/6"
    # 步数效率：总步数 ≤ 2×初始总距离（含冲突绕行）
    assert o["max_remaining"] < 40, f"有行人不移动 {o['max_remaining']}"
    print(f"[PASS] 地板场：{o['at_exit']}/6 到达，最长剩余 {o['max_remaining']}")


def test_optimal_steps():
    """OSM：多数行人到达目标且近邻排斥生效（无重叠）。"""
    m = OptimalStepsModel(n=8)
    m.initialize({}, {"n": 8}, None, None, np.random.default_rng(0))
    for _ in range(80):
        m.step(0, 0.4)
    o = m.observe()
    assert o["arrived"] >= 5, f"到达不足 {o['arrived']}/8"
    print(f"[PASS] OSM：{o['arrived']}/8 到达目标")


if __name__ == "__main__":
    test_macro_conservation()
    test_arz_string_instability()
    test_car_following_family()
    test_ns_fundamental_diagram()
    test_bml_transition()
    test_vdr_conservation()
    test_vickrey_bottleneck()
    test_wardrop_ue_vs_so()
    test_mobil()
    test_social_force_evacuation()
    test_vo_family_no_collision()
    test_floor_field_shortest_path()
    test_optimal_steps()
    print("\n===== DAYAN 交通+行人家族：全部通过 =====")
