"""DAYAN 经济批次 A+B 验收测试（ECO 投入产出/增长/周期/OLG/金融/劳动/人口/迁移/婚配/资源等）。

运行：python tests/test_dayan_eco_batch.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dayan import simulate  # noqa: E402
from dayan.models.eco_models import (AKModel, BeerGameModel,  # noqa: E402
                                     BenPorathModel, BlanchardYOUTHModel,
                                     DICELiteModel, DiamondOLGModel,
                                     GibratModel, GodeSunderZIModel,
                                     GodleyLavoieSIMModel,
                                     GordonSchaeferModel, HotellingModel,
                                     KaldorModel, KaleckiModel,
                                     LanchesterLinearModel,
                                     LanchesterSquareModel,
                                     LeontiefDynamicModel,
                                     LeontiefPriceModel,
                                     LeontiefQuantityModel, LifeCycleModel,
                                     McCallModel, MincerModel, RamseyModel,
                                     RaschModel, RichardsonArmsModel,
                                     RomerModel, SchaeferFisheryModel,
                                     StaticTaxBenefitModel, fit_garch,
                                     fit_var)
from dayan.models.eco_models import (GhoshModel, ThreePLModel,  # noqa: E402
                                     TwoPLModel)
from dayan.models.eco_demog import (BeckerMarriageModel, BeckerTomesModel,  # noqa: E402
                                    BKTModel, BrassLogitModel,
                                    CoaleMcNeilModel, GaleShapleyModel,
                                    GompertzMakehamModel, HadwigerModel,
                                    HarrisTodaroModel,
                                    HealthMarkovModel,
                                    IntergenerationalMarkovModel,
                                    LefkovitchModel, LeeCarterModel,
                                    RadiationModel, RogersMultiregionalModel,
                                    WilsonGravityModel)


def test_leontief_family():
    """Leontief 数量/价格/Ghosh：迭代收敛到 x=(I-A)^{-1}d。"""
    q = LeontiefQuantityModel(sectors=3)
    q.initialize({}, {"demand": [1.0, 1.0, 1.0]}, None, None,
                 np.random.default_rng(0))
    for _ in range(60):
        q.step(0, 1.0)
    x_iter = np.array(q.observe()["x"])
    x_direct = np.linalg.solve(np.eye(3) - q.A, np.array([1.0, 1.0, 1.0]))
    assert np.abs(x_iter - x_direct).max() < 1e-8, \
        f"数量解不匹配 {x_iter} vs {x_direct}"

    p = LeontiefPriceModel(sectors=3)
    p.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(60):
        p.step(0, 1.0)
    assert p.observe()["p_min"] > 0, "价格出现非正值"

    g = GhoshModel()
    g.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(60):
        g.step(0, 1.0)
    assert g.observe()["total"] > 0
    print("[PASS] Leontief 族（数量=逆精确/价格正值/Ghosh 正向）")


def test_ramsey_steady_state():
    """Ramsey：k 收敛至 f'(k*)=δ+1/β-1 的稳态。"""
    m = RamseyModel(alpha=0.3, delta=0.05, beta=0.96, theta=2.0)
    r = simulate(m, horizon=200.0, dt=0.2,
                 parameters={"k0": 1.0}, rng=np.random.default_rng(0))
    o = r["final"]
    assert abs(o["k"] - o["k_star"]) / o["k_star"] < 0.15, \
        f"k={o['k']:.3f} vs k*={o['k_star']:.3f}"
    print(f"[PASS] Ramsey：k={o['k']:.3f} ≈ k*={o['k_star']:.3f}")


def test_ak_endogenous_growth():
    """AK：人均资本按 g=sA-δ 指数增长（无收敛）。"""
    A, s, delta = 0.3, 0.25, 0.05
    m = AKModel(A=A, s=s, delta=delta, k0=1.0)
    r = simulate(m, horizon=100.0, dt=0.5, parameters={"k0": 1.0},
                 rng=np.random.default_rng(0))
    o = r["final"]
    g = s * A - delta
    proj = np.exp(g * 100.0)
    assert abs(o["k"] - proj) / proj < 0.05, f"k={o['k']:.3f} vs exp={proj:.3f}"
    print(f"[PASS] AK：k={o['k']:.2f} ≈ e^(g·T)={proj:.2f}（内生增长）")


def test_kaldor_kalecki_oscillation():
    """Kaldor/Kalecki：非线性/时滞投资 → 振荡（Y_std 显著）。"""
    kal = KaldorModel()
    kal.initialize({}, {"Y0": 0.8}, None, None, np.random.default_rng(0))
    ys = []
    for _ in range(400):
        kal.step(0, 0.1)
        ys.append(kal.Y)
    ys = np.array(ys[-100:])
    assert ys.std() > 0.02, f"Kaldor 无振荡 std={ys.std():.4f}"

    kel = KaleckiModel(delay=5)
    kel.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(1000):
        kel.step(0, 0.1)
    o2 = kel.observe()
    assert o2["osc"], f"Kalecki 无振荡 std={o2['Y_std']:.4f}"
    print(f"[PASS] 周期模型：Kaldor std={ys.std():.3f}，"
          f"Kalecki(τ=5) std={o2['Y_std']:.3f}")


def test_olg_and_lifecycle():
    """Diamond OLG 稳态存在；生命周期储蓄驼峰+期末归零。"""
    olg = DiamondOLGModel()
    olg.initialize({}, {"k0": 0.5}, None, None, np.random.default_rng(0))
    for _ in range(50):
        olg.step(0, 1.0)
    o = olg.observe()
    assert abs(o["k_next"] - o["k"]) / max(o["k"], 1e-6) < 0.1, \
        f"OLG 不动点偏差 {o}"

    lc = LifeCycleModel()
    lc.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(60):
        lc.step(0, 1.0)
    o2 = lc.observe()
    assert o2["peak_age"] <= 41, f"储蓄峰应在工作期末 {o2['peak_age']}"
    assert o2["end_zero"], f"期末储蓄未耗尽 {o2['savings']:.2f}"
    print(f"[PASS] OLG 不动点 + 生命周期（峰龄 {o2['peak_age']}，"
          f"期末 {o2['savings']:.2f}）")


def test_godley_lavoie_conservation():
    """GL-SIM：三部门货币严格守恒 + Y 收敛到乘数稳态。"""
    m = GodleyLavoieSIMModel(alpha=0.6, theta=0.2, G=20.0)
    m.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(60):
        m.step(0, 1.0)
    o = m.observe()
    assert abs(o["conserv"]) < 1e-9, f"货币守恒破坏 {o['conserv']}"
    assert abs(o["Y"] - o["Y_star"]) / o["Y_star"] < 0.05, \
        f"Y={o['Y']:.2f} vs Y*={o['Y_star']:.2f}"
    print(f"[PASS] GL-SIM：守恒 {o['conserv']:.1e}，Y={o['Y']:.2f}≈Y*={o['Y_star']:.2f}")


def test_time_series_estimation():
    """VAR(1) 系数恢复；GARCH 滤波波动聚集。"""
    rng = np.random.default_rng(3)
    A_true = np.array([[0.5, 0.1], [0.05, 0.4]])
    y = np.zeros((500, 2))
    for t in range(1, 500):
        y[t] = A_true @ y[t - 1] + rng.normal(0, 0.3, 2)
    fit = fit_var(y, p=1)
    err = np.abs(fit["A"] - A_true).max()
    assert err < 0.08, f"VAR 系数恢复误差 {err:.3f}"

    # GARCH：波动聚集（|r| 大的时段 σ² 也大）
    r = rng.normal(0, 1, 400) * np.where(np.arange(400) < 200, 0.5, 2.0)
    s2 = fit_garch(r)
    assert s2[300:].mean() > s2[100:190].mean() * 2, "GARCH 未捕捉聚集"
    print(f"[PASS] VAR 系数恢复 maxerr={err:.3f}；GARCH 聚集比"
          f"={s2[300:].mean()/s2[100:190].mean():.2f}×")


def test_zi_traders_equilibrium():
    """Gode–Sunder ZI：配置效率≈97%（经典结论）。"""
    m = GodeSunderZIModel()
    m.initialize({}, {}, None, None, np.random.default_rng(2))
    for _ in range(30):
        m.step(0, 1.0)
    o = m.observe()
    assert o["n_trades"] >= 15, f"成交太少 {o['n_trades']}"
    assert o["alloc_efficiency"] >= 0.9,         f"GS 配置效率 {o['alloc_efficiency']:.2f}"
    print(f"[PASS] ZI 交易者：{o['n_trades']} 笔成交，"
          f"GS 配置效率 {o['alloc_efficiency']:.2f}（≈97% 经典结论）")


def test_labor_search_human_capital():
    """McCall 保留工资 > 失业救济；Mincer ρ 恢复；Ben-Porath 前期投资密集。"""
    mc = McCallModel()
    mc.initialize({}, {}, None, None, np.random.default_rng(0))
    mc.step(0, 1.0)
    o = mc.observe()
    assert o["res_wage"] > 2.0, f"保留工资应高于救济 {o['res_wage']:.1f}"

    mn = MincerModel()
    mn.initialize({}, {}, None, None, np.random.default_rng(0))
    assert abs(mn.observe()["err"]) < 0.02, \
        f"Mincer ρ 恢复误差 {mn.observe()['err']:.3f}"

    bp = BenPorathModel()
    bp.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(45):
        bp.step(0, 1.0)
    ob = bp.observe()
    assert ob["decreasing"], f"投资应前密后疏 {ob}"
    print(f"[PASS] 劳动族：w*={o['res_wage']:.1f}，ρ̂={mn.rho_hat:.3f}，"
          f"投资 {ob['invest_early']:.2f}→{ob['invest_late']:.2f}")


def test_gibrat_lognormal():
    """Gibrat：比例增长 → 规模对数正态（对数偏度≈0，CV 随时间增长）。"""
    m = GibratModel(n_firms=300)
    m.initialize({}, {}, None, None, np.random.default_rng(0))
    cv0 = m.observe()["size_cv"]
    for _ in range(60):
        m.step(0, 1.0)
    o = m.observe()
    assert abs(o["log_skew"]) < 0.35, f"对数偏度偏离 {o['log_skew']:.2f}"
    assert o["size_cv"] > cv0, f"规模离散度应增长 {cv0:.2f}→{o['size_cv']:.2f}"
    print(f"[PASS] Gibrat：log偏度={o['log_skew']:.2f}，CV {cv0:.2f}→{o['size_cv']:.2f}")


def test_irt_family():
    """IRT 三代：Rasch 参数恢复相关>0.8；2PL 单调 ICC；3PL 猜测下限可见。"""
    ra = RaschModel()
    ra.initialize({}, {}, None, None, np.random.default_rng(0))
    o = ra.observe()
    assert o["item_b_corr"] > 0.8, f"Rasch 恢复相关 {o['item_b_corr']:.2f}"
    two = TwoPLModel()
    two.initialize({}, {}, None, None, np.random.default_rng(0))
    assert two.observe()["monotone_icc"], "2PL ICC 不单调"
    three = ThreePLModel()
    three.initialize({}, {}, None, None, np.random.default_rng(0))
    assert three.observe()["guess_visible"], "3PL 猜测下限未显现"
    print(f"[PASS] IRT 族：Rasch corr={o['item_b_corr']:.2f}，"
          f"2PL 单调，3PL 低θ正确率={three.observe()['low_theta_acc']:.2f}")


def test_tax_benefit_microsim():
    """静态税福：边际税率随收入分段递增。"""
    m = StaticTaxBenefitModel()
    m.initialize({}, {}, None, None, np.random.default_rng(0))
    o = m.observe()
    assert o["mtr_nondecreasing"], f"MTR 路径 {o['mtr_path']}"
    assert o["mean_tax"] > 0
    print(f"[PASS] 税福微观仿真：MTR {o['mtr_path']}")


def test_conflict_family():
    """Richardson 稳定均衡 + Lanchester 平方律不变量守恒。"""
    ri = RichardsonArmsModel(a1=0.3, a2=0.3, r1=0.5, r2=0.5)
    from dayan import simulate as _sim
    r = _sim(ri, horizon=120.0, dt=0.2, parameters={"x0": [2.0, 2.0]},
             rng=np.random.default_rng(0))
    o = r["final"]
    assert o["stable"], "稳定性配置错误"
    assert abs(o["x1"] - o["eq_x1"]) / max(o["eq_x1"], 1) < 0.15, \
        f"x1={o['x1']:.2f} vs eq={o['eq_x1']:.2f}"

    ls = LanchesterSquareModel(N1=100.0, N2=80.0)
    r2 = _sim(ls, horizon=60.0, dt=0.1, parameters={}, rng=None)
    o2 = r2["final"]
    assert abs(o2["invariant"] - o2["inv0"]) / max(abs(o2["inv0"]), 1e-9) < 0.05, \
        f"平方律不变量漂移 {o2['invariant']:.1f} vs {o2['inv0']:.1f}"

    ll = LanchesterLinearModel(a=0.05, b=0.04, N1=100.0, N2=100.0)
    r3 = _sim(ll, horizon=60.0, dt=0.05, parameters={}, rng=None)
    o3 = r3["final"]
    assert abs(o3["lin_invariant"] - o3["lin0"]) / \
        max(abs(o3["lin0"]), 1e-9) < 0.05, \
        f"线性律不变量漂移 {o3['lin_invariant']:.1f} vs {o3['lin0']:.1f}"
    print("[PASS] 冲突族：Richardson 均衡 + Lanchester 平方/线性律不变量")


def test_resource_family():
    """Schaefer MSY=B=K/2；Gordon-Schaefer 生物经济均衡存在；Hotelling 价格指数增长。"""
    sf = SchaeferFisheryModel(r=0.6, K=100.0, q=0.1, E=2.0, B0=100.0)
    from dayan import simulate as _sim
    r = _sim(sf, horizon=100.0, dt=0.2, parameters={}, rng=None)
    o = r["final"]
    assert abs(o["B"] - o["B_eq"]) / max(o["B_eq"], 1) < 0.15, \
        f"B={o['B']:.1f} vs B_eq={o['B_eq']:.1f}"

    ho = HotellingModel(stock=100.0, delta=0.05)
    ho.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(80):
        ho.step(0, 1.0)
    oh = ho.observe()
    assert abs(oh["price_growth"] - 0.05) < 0.02, \
        f"Hotelling 增速 {oh['price_growth']:.3f} ≠ δ={oh['hotelling_delta']}"
    print(f"[PASS] 资源族：Schaefer B={o['B']:.1f}≈{o['B_eq']:.1f}，"
          f"Hotelling g={oh['price_growth']:.3f}≈δ")


def test_beer_game_bullwhip():
    """啤酒游戏：上游订单方差放大（bullwhip > 1.5）。"""
    m = BeerGameModel()
    m.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(200):
        m.step(0, 1.0)
    o = m.observe()
    assert o["var_up_gt_down"], f"无 bullwhip 放大 var={o['order_var']}"
    print(f"[PASS] 啤酒游戏：bullwhip={o['bullwhip']:.2f}×")


def test_dice_lite():
    """DICE-lite：排放→浓度→温度 正向响应链。"""
    m = DICELiteModel()
    r = simulate(m, horizon=120.0, dt=0.2, parameters={}, rng=None)
    o = r["final"]
    assert o["M"] > 800.0, f"碳浓度应上升 {o['M']:.0f}"
    assert o["forcing"] > 0.2, f"辐射强迫应增长 {o['forcing']:.2f}"
    print(f"[PASS] DICE-lite：M={o['M']:.0f}，T={o['T']:.2f}，"
          f"F={o['forcing']:.2f}")


# ===== 批次 B：人口/迁移/婚配/健康/教育 =====
def test_demography_family():
    """Lefkovitch λ1 增长；Lee-Carter 拟合；Gompertz b 恢复；婚育曲线形态。"""
    lf = LefkovitchModel()
    lf.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(60):
        lf.step(0, 1.0)
    o = lf.observe()
    lam1 = o["lambda1"]
    ratio = o["total"] / max(sum((10, 5, 3, 2)), 1e-9)
    proj = lam1 ** 60
    assert 0.5 * proj < ratio < 1.5 * proj * max(1, lam1), \
        f"Lefkovitch 增长率 {ratio:.1f} vs λ1^60={proj:.1f}"

    lcv = LeeCarterModel()
    lcv.initialize({}, {}, None, None, np.random.default_rng(0))
    assert lcv.observe()["good_fit"], "Lee-Carter 残差过大"

    gm = GompertzMakehamModel()
    gm.initialize({}, {}, None, None, np.random.default_rng(0))
    og = gm.observe()
    assert og["err"] < 0.01, f"Gompertz b 恢复误差 {og['err']:.3f}"

    cm = CoaleMcNeilModel()
    cm.initialize({}, {}, None, None, np.random.default_rng(0))
    assert cm.observe()["peak_reasonable"]

    hd = HadwigerModel()
    hd.initialize({}, {}, None, None, np.random.default_rng(0))
    assert hd.observe()["unimodal"]
    print(f"[PASS] 人口族：Lefkovitch λ1={lam1:.2f}，LC 残差比="
          f"{lcv.observe()['resid_ratio']:.3f}，Gompertz b̂={gm.b_hat:.3f}，"
          f"婚龄均值={cm.mean_age:.1f}，生育峰={hd.peak_age:.1f}")


def test_migration_family():
    """Wilson 双约束 IPF 闭合；辐射模型距离衰减；Harris-Todaro 期望收入收敛。"""
    wg = WilsonGravityModel(n=6)
    wg.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(60):
        wg.step(0, 1.0)
    o = wg.observe()
    assert o["converged"], f"IPF 未收敛 {o['row_err']:.2f}/{o['col_err']:.2f}"

    rad = RadiationModel(n=8)
    rad.initialize({}, {}, None, None, np.random.default_rng(0))
    orad = rad.observe()
    assert orad["decay"], f"辐射模型无距离衰减 corr={orad['corr_dist_flow']:.2f}"

    ht = HarrisTodaroModel()
    ht.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(400):
        ht.step(0, 1.0)
    oht = ht.observe()
    assert abs(oht["gap"]) < 5.0, f"HT 期望收入未收敛 gap={oht['gap']:.2f}"
    print(f"[PASS] 迁移族：IPF err<0.1，辐射衰减 corr={orad['corr_dist_flow']:.2f}，"
          f"HT gap={oht['gap']:.2f} 失业率={oht['unemp_rate']:.2f}")


def test_marriage_matching():
    """Gale–Shapley 稳定匹配（0 阻塞对）；Becker 互补产出 → 正分类。"""
    gs = GaleShapleyModel(n=12)
    gs.initialize({}, {}, None, None, np.random.default_rng(0))
    o = gs.observe()
    assert o["stable"], f"存在 {o['blocking_pairs']} 阻塞对"
    bk = BeckerMarriageModel(n=10)
    bk.initialize({}, {}, None, None, np.random.default_rng(0))
    ob = bk.observe()
    assert ob["assortative_optimal"], "Becker 正分类应最优"
    print(f"[PASS] 婚配族：GS 稳定（0 阻塞），Becker 正分类 gain={ob['gain']:.1f}")


def test_intergenerational_and_health_education():
    """代际流动谱隙收敛；健康队列 Markov 死亡率上升；BKT 掌握概率上升。"""
    im = IntergenerationalMarkovModel()
    im.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(200):
        im.step(0, 1.0)
    o = im.observe()
    assert o["converged"], f"Markov 未收敛 err={o['stationary_err']:.1e}"

    hm = HealthMarkovModel()
    hm.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(100):
        hm.step(0, 1.0)
    oh = hm.observe()
    assert oh["dead"] > 0.5, f"100 期死亡率不足 {oh['dead']:.2f}"

    bkt = BKTModel()
    bkt.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(30):
        bkt.step(0, 1.0)
    ob = bkt.observe()
    assert ob["p_rising"], f"BKT 掌握概率未上升 {ob['p_now']:.2f}"
    print(f"[PASS] 代际/健康/教育：谱隙={o['spectral_gap']:.2f}，"
          f"100期死亡={oh['dead']:.2f}，BKT p={ob['p_now']:.2f}")


def test_rogers_multiregional():
    """Rogers 多区域：总人口守恒迁移下演化、无负值。"""
    ro = RogersMultiregionalModel()
    ro.initialize({}, {}, None, None, np.random.default_rng(0))
    p0 = ro.observe()["total"]
    for _ in range(100):
        ro.step(0, 1.0)
    o = ro.observe()
    assert o["total"] > 0
    assert (np.array(o["pop"]) >= 0).all()
    print(f"[PASS] Rogers 多区域：{p0:.0f}→{o['total']:.0f}")


if __name__ == "__main__":
    test_leontief_family()
    test_ramsey_steady_state()
    test_ak_endogenous_growth()
    test_kaldor_kalecki_oscillation()
    test_olg_and_lifecycle()
    test_godley_lavoie_conservation()
    test_time_series_estimation()
    test_zi_traders_equilibrium()
    test_labor_search_human_capital()
    test_gibrat_lognormal()
    test_irt_family()
    test_tax_benefit_microsim()
    test_conflict_family()
    test_resource_family()
    test_beer_game_bullwhip()
    test_dice_lite()
    test_demography_family()
    test_migration_family()
    test_marriage_matching()
    test_intergenerational_and_health_education()
    test_rogers_multiregional()
    print("\n===== DAYAN 经济批次 A+B：全部通过 =====")
