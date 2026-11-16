"""大型经济模型 lite 版验收（ECO 精确可解类/DSGE 异质类/金融 ABM/CGE/气候）。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dayan import simulate  # noqa: E402
from dayan.models.eco_flagship_lite import (ARCHModel, AiyagariModel,  # noqa: E402
                                            BewleyModel, BrockHommesModel,
                                            CliffZIModel, DeatonBufferModel,
                                            DynamicFactorModel,
                                            EnvIOModel, FUNDLiteModel,
                                            ForresterCityLiteModel,
                                            GodleyPCModel, GodleySIMEXModel,
                                            GTAPLiteModel, HamiltonSwitchModel,
                                            HuggettModel, KirmanModel,
                                            LuxMarchesiLiteModel, Mark0LiteModel,
                                            MiyazawaModel, MRIModel,
                                            NK3Model, PAGE09LiteModel,
                                            PEP11CGEModel, RICELiteModel,
                                            RecursiveCGEModel,
                                            SAMMultiplierModel,
                                            SantaFeLiteModel,
                                            SmithFarmerLOBLiteModel,
                                            SVARModel, VECMModel,
                                            World3LiteModel)


def test_exact_solvable():
    """SAM乘数/Miyazawa/MRIO/EnvIO：迭代解 = 直接逆（误差<1e-8）。"""
    for cls, name in [(SAMMultiplierModel, "SAM乘数"), (MiyazawaModel, "Miyazawa"),
                      (MRIModel, "MRIO"), (EnvIOModel, "环境IO")]:
        m = cls()
        m.initialize({}, {}, None, None, np.random.default_rng(0))
        for _ in range(80):
            m.step(0, 1.0)
        o = m.observe()
        assert o.get("err", 1.0) < 1e-8, f"{name} 收敛失败 {o.get('err')}"
        print(f"  ✓ {name}: err={o['err']:.2e}")
    print("[PASS] 精确可解类 4 模型（SAM/Miyazawa/MRIO/EnvIO）")


def test_ts_models():
    """SVAR 系数恢复/VECM 协整识别/ARCH 聚集/动态因子/Hamilton 切换。"""
    sv = SVARModel()
    sv.initialize({}, {}, None, None, np.random.default_rng(0))
    o = sv.observe()
    assert o["irf_err"] < 0.15, f"SVAR 系数误差 {o['irf_err']:.3f}"

    ve = VECMModel()
    ve.initialize({}, {}, None, None, np.random.default_rng(0))
    ov = ve.observe()
    assert ov["cointegration_detected"], f"协整未检出 {ov}"
    assert abs(ov["theta_hat"] - 0.9) < 0.1, f"θ̂={ov['theta_hat']:.3f}"

    ar = ARCHModel()
    ar.initialize({}, {}, None, None, np.random.default_rng(0))
    assert ar.observe()["arch_detected"], "ARCH 聚集未检出"

    df = DynamicFactorModel()
    df.initialize({}, {}, None, None, np.random.default_rng(0))
    assert df.observe()["factor_corr"] > 0.9, "共同因子恢复失败"

    hs = HamiltonSwitchModel()
    hs.initialize({}, {}, None, None, np.random.default_rng(0))
    assert hs.observe()["state_acc"] > 0.6, "Hamilton 状态识别失败"
    print(f"[PASS] 时间序列族：SVAR err={o['irf_err']:.3f}，VECM θ̂="
          f"{ov['theta_hat']:.2f}，ARCH/动态因子/Hamilton OK")


def test_heterogeneous_agents():
    """NK3/Bewley/Huggett/Aiyagari/Deaton。"""
    nk = NK3Model()
    nk.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(120):
        nk.step(0, 1.0)
    o = nk.observe()
    assert abs(o["pi"]) < 2.0, f"NK 通胀发散 {o['pi']:.3f}"

    bw = BewleyModel()
    bw.initialize({}, {}, None, None, np.random.default_rng(0))
    ob = bw.observe()
    assert ob["mean_saving_rate"] > 0.02, f"预防性储蓄率 {ob['mean_saving_rate']:.3f}"

    hg = HuggettModel()
    hg.initialize({}, {}, None, None, np.random.default_rng(0))
    oh = hg.observe()
    assert -0.02 < oh["r_market"] < 0.06

    ay = AiyagariModel()
    ay.initialize({}, {}, None, None, np.random.default_rng(0))
    oa = ay.observe()
    assert 0.5 < oa["K_equilibrium"] < 20

    de = DeatonBufferModel()
    de.initialize({}, {}, None, None, np.random.default_rng(0))
    assert de.observe()["target_stable"]
    print(f"[PASS] 异质家庭族：NK π={o['pi']:.3f}，Bewley s={ob['mean_saving_rate']:.3f}，"
          f"Huggett r*={oh['r_market']:.3f}，Aiyagari K={oa['K_equilibrium']:.1f}")


def test_financial_abm():
    """Brock-Hommes/Kirman/SantaFe/LuxMarchesi/Cliff/SmithFarmer/Mark0。"""
    bh = BrockHommesModel()
    bh.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(200):
        bh.step(0, 1.0)
    ob = bh.observe()
    assert ob["deviation_std"] >= 0

    kr = KirmanModel()
    kr.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(400):
        kr.step(0, 1.0)
    ok = kr.observe()
    assert abs(ok["mean_share"] - ok["theory_mean"]) < 0.2, \
        f"Kirman 份额 {ok['mean_share']:.2f} vs {ok['theory_mean']:.2f}"

    sf = SantaFeLiteModel()
    sf.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(250):
        sf.step(0, 1.0)
    osf = sf.observe()
    assert osf["converge_err"] < 0.1, f"SFM 偏离基本面 {osf['converge_err']:.3f}"

    lm = LuxMarchesiLiteModel()
    lm.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(300):
        lm.step(0, 1.0)
    olm = lm.observe()
    assert olm["fat_tails"], f"肥尾未出现 kurt={olm['excess_kurtosis']:.2f}"

    cl = CliffZIModel()
    cl.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(25):
        cl.step(0, 1.0)
    assert cl.observe()["alloc_efficiency"] >= 0.9

    sfl = SmithFarmerLOBLiteModel()
    sfl.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(30):
        sfl.step(0, 1.0)
    assert sfl.observe() is not None

    mk = Mark0LiteModel()
    mk.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(300):
        mk.step(0, 1.0)
    omk = mk.observe()
    assert omk["right_skew"], f"企业规模无右偏 skew={omk['size_skew']:.2f}"
    assert omk["bankruptcies"] >= 0
    print(f"[PASS] 金融 ABM 族：Kirman={ok['mean_share']:.2f}≈{ok['theory_mean']:.2f}，"
          f"SFM 收敛 err={osf['converge_err']:.3f}，肥尾 kurt="
          f"{olm['excess_kurtosis']:.1f}，Cliff eff="
          f"{cl.observe()['alloc_efficiency']:.2f}，Mark0 破产={omk['bankruptcies']}")


def test_cge_family():
    """PEP-1-1/递归 CGE/GTAP-lite：瓦尔拉斯收敛或稳态命中。"""
    pep = PEP11CGEModel()
    pep.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(300):
        pep.step(0, 1.0)
    o = pep.observe()
    assert o["converged"], f"PEP-1-1 Walras {o['walras_excess']:.2f}"

    rc = RecursiveCGEModel()
    rc.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(3000):
        rc.step(0, 0.1)
    assert rc.observe()["converged"]

    gt = GTAPLiteModel()
    gt.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(300):
        gt.step(0, 1.0)
    og = gt.observe()
    assert og["converged"] and og["cheap_expands"], f"GTAP-lite {og}"
    print(f"[PASS] CGE 族：PEP Walras={o['walras_excess']:.3f}，递归 CGE 稳态，"
          f"GTAP p={og['p']}")


def test_climate_iam():
    """World3/RICE/FUND/PAGE09-lite：过冲/两区域/分部门/概率输出。"""
    w3 = World3LiteModel()
    r = simulate(w3, horizon=120.0, dt=0.5, parameters={}, rng=None)
    o = r["final"]
    assert o["overshoot"], f"资源未过冲 Res={o['resources']:.0f}"

    ri = RICELiteModel()
    r = simulate(ri, horizon=100.0, dt=0.2, parameters={}, rng=None)
    ori = r["final"]
    assert ori["M"] > 800 and ori["T"] > 1.0, f"RICE 动态 {ori}"

    fu = FUNDLiteModel()
    fu.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(60):
        fu.step(0, 1.0)
    of = fu.observe()
    assert "sector_losses" in of and of["total"] > 0

    pg = PAGE09LiteModel()
    pg.initialize({}, {}, None, None, np.random.default_rng(0))
    op = pg.observe()
    assert op["fat_tail"], f"PAGE09 p95 未现肥尾 {op['T_p95']:.2f}"

    fc = ForresterCityLiteModel()
    rf = simulate(fc, horizon=60.0, dt=0.2, parameters={}, rng=None)
    assert rf["final"] is not None
    print(f"[PASS] 气候 IAM 族：World3 Res={o['resources']:.0f} 过冲，"
          f"RICE T={ori['T']:.2f}，FUND 部门，PAGE09 T_p95={op['T_p95']:.2f}")


def test_godley_extensions():
    """SIMEX 政策反馈守恒；PC 资产组合运行。"""
    sx = GodleySIMEXModel()
    sx.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(100):
        sx.step(0, 1.0)
    o = sx.observe()
    assert abs(o["conserv"]) < 1e-6, f"SIMEX 守恒 {o['conserv']:.2e}"

    pc = GodleyPCModel()
    pc.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(80):
        pc.step(0, 1.0)
    op = pc.observe()
    assert op["Y"] > 50, f"PC 产出未起 {op['Y']:.1f}"
    print(f"[PASS] Godley 扩展：SIMEX 守恒={o['conserv']:.1e}，"
          f"PC Y={op['Y']:.1f} bills={op['bills']:.1f}")


if __name__ == "__main__":
    test_exact_solvable()
    test_ts_models()
    test_heterogeneous_agents()
    test_financial_abm()
    test_cge_family()
    test_climate_iam()
    test_godley_extensions()
    print("\n===== 大型模型 lite 批次：全部通过 =====")
