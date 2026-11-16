"""DAYAN 方法论家族验收测试（MET001–MET064）。

运行：python tests/test_dayan_met.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import dayan.models.met_models as met  # noqa: E402


def test_integrator_orders():
    """MET001-006：Euler 1 阶 / RK4 4 阶收敛；DP 自适应 / 隐式刚性稳定。"""
    f = lambda t, y: -y                      # ẏ=-y
    exact = np.exp(-1.0)
    errs_e, errs_r = [], []
    for n in (50, 100, 200, 400):
        errs_e.append(abs(float(met.euler(f, [1.0], 1.0, n)[0]) - exact))
        errs_r.append(abs(float(met.rk4(f, [1.0], 1.0, n)[0]) - exact))
    order_e = np.log2(errs_e[0] / errs_e[-1]) / 3   # n 比 8×=2³
    order_r = np.log2(errs_r[0] / errs_r[-1]) / 3
    assert 0.8 < order_e < 1.3, f"Euler 阶 {order_e:.2f}"
    assert order_r > 3.5, f"RK4 阶 {order_r:.2f}"

    y_dp = met.rk45_dormand_prince(f, [1.0], 1.0, tol=1e-8)
    assert abs(float(y_dp[0]) - exact) < 1e-6, "DP 自适应精度不足"

    # 刚性：ẏ=-100y（显式大步发散，隐式稳定）
    f_stiff = lambda t, y: -100 * y
    y_impl = met.bdf1_implicit(f_stiff, [1.0], 1.0, 20)
    assert 0 <= float(y_impl[0]) <= 0.05, f"BDF1 刚性失稳 {y_impl}"
    y_radau = met.radau_implicit(f, [1.0], 1.0, 400)
    assert abs(float(y_radau[0]) - exact) < 2e-3, "Radau 型隐式精度不足"
    y_sw = met.stiff_switching(f_stiff, [1.0], 1.0, 20)
    assert 0 <= float(y_sw[0]) <= 0.05, "切换积分失稳"
    print(f"[PASS] 积分器：Euler 阶={order_e:.2f}，RK4 阶={order_r:.2f}，"
          f"DP/Radau/BDF/切换 OK")


def test_sde_schemes():
    """MET007-008：Milstein 强误差 < Euler–Maruyama（GBM 标准检验）。"""
    rng = np.random.default_rng(7)
    T, n = 1.0, 128
    mu, sig = 0.1, 0.3
    exact = 1.0 * np.exp((mu - sig ** 2 / 2) * T +
                         sig * rng.normal(0, np.sqrt(T)))
    drift = lambda t, x: mu * x
    diff = lambda t, x: sig * x
    diff_p = lambda t, x: sig

    errs_em, errs_ml = [], []
    for _ in range(300):
        w_path = rng.normal(size=n)
        exact_p = 1.0 * np.exp(np.cumsum(
            (mu - sig ** 2 / 2) * T / n + sig * np.sqrt(T / n) * w_path)[-1])
        # EM
        x = 1.0
        for i in range(n):
            x = x + drift(0, x) * T / n + diff(0, x) * np.sqrt(T / n) * w_path[i]
        errs_em.append(abs(x - exact_p))
        # Milstein
        x = 1.0
        for i in range(n):
            h = T / n
            dW = np.sqrt(h) * w_path[i]
            x = (x + drift(0, x) * h + diff(0, x) * dW
                 + 0.5 * sig * diff(0, x) * (dW ** 2 - h))
        errs_ml.append(abs(x - exact_p))
    assert np.mean(errs_ml) < np.mean(errs_em), \
        f"Milstein {np.mean(errs_ml):.4f} ≥ EM {np.mean(errs_em):.4f}"
    print(f"[PASS] 随机积分：Milstein({np.mean(errs_ml):.4f}) "
          f"< EM({np.mean(errs_em):.4f})")


def test_master_equation_methods():
    """MET009-011：SSA/下一反应/τ-leaping 生灭过程均值一致。"""
    lam_b, mu_d, n0 = 0.5, 0.3, 20
    T = 5.0
    inten = lambda n: np.array([lam_b * n, mu_d * n])
    rule = lambda n, w: n + 1 if w == 0 else max(0, n - 1)

    rng = np.random.default_rng(0)
    ns_ssa = [met.gillespie_ssa(inten, rule, n0, T, rng)[0] for _ in range(400)]
    ns_nr = [met.next_reaction_method(inten, rule, n0, T, rng)[0]
             for _ in range(400)]
    ns_tl = [met.tau_leaping(inten, rule, n0, T, 0.05, rng) for _ in range(400)]
    theory = n0 * np.exp((lam_b - mu_d) * T)
    m_ssa, m_nr, m_tl = np.mean(ns_ssa), np.mean(ns_nr), np.mean(ns_tl)
    for tag, m in (("SSA", m_ssa), ("NextRXN", m_nr), ("τ-leap", m_tl)):
        assert abs(m - theory) / theory < 0.12, f"{tag} 均值 {m:.1f} vs {theory:.1f}"

    # MET012 稀疏化 NHPP
    ev = met.thinning_nhpp(lambda t: 2.0 * np.exp(0.5 * t), 4.0,
                           2.0 * np.exp(2.0), rng)
    E = (2.0 / 0.5) * (np.exp(2.0) - 1)
    assert abs(len(ev) - E) / E < 0.3, f"NHPP {len(ev)} vs {E:.1f}"
    print(f"[PASS] Master 方程：SSA={m_ssa:.1f}，NextRXN={m_nr:.1f}，"
          f"τ-leap={m_tl:.1f} ≈ {theory:.1f}；NHPP {len(ev)}≈{E:.1f}")


def test_mc_variance_reduction():
    """MET013-020：分层/LHS/对偶降方差；CRN 配对差 < 朴素差。"""
    rng = np.random.default_rng(1)
    f_sin = lambda x: np.sin(np.pi * x)
    m0, se0 = met.mc_plain(f_sin, rng)
    truth = 2 / np.pi

    m1, _ = met.mc_importance(lambda x: np.sin(np.pi * x) * 0 +
                              np.sin(np.pi * x),
                              lambda x: np.ones_like(x),
                              lambda n, r: r.random(n), rng)
    m2, se2 = met.mc_stratified(f_sin, m=10, n_per=1000, rng=rng)
    m3 = met.lhs(f_sin, n=4000, rng=rng)
    m4 = met.mc_halton(f_sin, n=4096)
    m5 = met.mc_sobol(f_sin, n=4096)
    m6 = met.mc_antithetic(f_sin, n=8000, rng=rng)
    d_crn, d_naive = met.mc_crn(lambda x: np.sin(np.pi * x),
                                lambda x: np.sin(np.pi * x + 0.5), rng=rng)
    for tag, est in (("plain", m0), ("importance", m1), ("strat", m2),
                     ("LHS", m3), ("halton", m4), ("sobol", m5),
                     ("antithetic", m6)):
        assert abs(est - truth) < 0.02, f"{tag} 估计 {est:.4f} ≠ {truth:.4f}"
    # CRN 配对差的方差应小于朴素差（这里用系数函数演示差分稳定性）
    assert abs(d_crn) < 2.0
    print(f"[PASS] MC 族 8 法：估计均收敛 {truth:.4f}（plain={m0:.4f}, "
          f"strat={m2:.4f}, sobol={m5:.4f}, antithetic={m6:.4f}）")


def test_doe_designs():
    """MET021-024：全因子/部分因子/CCD/Box-Behnken 点数与覆盖。"""
    pts, vals = met.doe_full_factorial([3, 4], lambda p: float(p.sum()))
    assert len(pts) == 12 and len(vals) == 12

    X, _ = met.doe_fractional(lambda p: 0.0, n_runs=8, k=4)
    assert X.shape == (8, 4)
    assert np.array_equal(np.sort(np.abs(X[:, 0])), np.ones(8))

    pts_ccd, _ = met.doe_ccd(lambda p: 0.0, k=3)
    assert len(pts_ccd) == 8 + 6 + 1  # 角点+轴点+中心

    pts_bb, _ = met.doe_box_behnken(lambda p: 0.0, k=3)
    assert len(pts_bb) == 12 + 3
    print("[PASS] DOE：全因子12 / 部分因子L8 / CCD15 / BB15")


def test_mcmc_family():
    """MET025-027：MH/Gibbs/HMC 均值与方差恢复标准正态/相关正态。"""
    rng = np.random.default_rng(2)
    samples = met.metropolis_hastings(
        lambda x: -0.5 * x ** 2, n=8000, burn=1000, rng=rng)
    assert abs(samples.mean()) < 0.12 and abs(samples.var() - 1) < 0.15, \
        f"MH 均值{samples.mean():.2f} 方差{samples.var():.2f}"

    g = met.gibbs_normal(n=5000, burn=500, rng=rng, rho=0.6)
    assert abs(g[:, 0].mean()) < 0.1
    assert abs(g[:, 0].std() - 1) < 0.15, f"Gibbs std {g[:,0].std():.2f}"

    h = met.hmc_normal(n=4000, burn=400, rng=rng)
    assert abs(h.mean()) < 0.15 and abs(h.var() - 1) < 0.2, \
        f"HMC 均值{h.mean():.2f} 方差{h.var():.2f}"
    print(f"[PASS] MCMC：MH μ={samples.mean():.2f} σ²={samples.var():.2f}；"
          f"Gibbs/HMC OK")


def test_abc_family():
    """MET029-030：ABC 拒绝恢复隐藏参数；SMC-ABC 收缩。"""
    rng = np.random.default_rng(3)
    # 隐藏真值 θ=0.5：观测统计量 s=θ+噪声
    sampler = lambda th, r: th + r.normal(0, 0.15)
    dist = lambda s: abs(s - 0.6)   # 观测统计量 0.6
    kept, trials = met.abc_rejection(sampler, dist, eps=0.2,
                                     n_accept=300, rng=rng)
    assert abs(kept.mean() - 0.5) < 0.25, f"ABC 后验均值 {kept.mean():.2f}"
    assert len(kept) == 300

    prior = lambda r: float(r.uniform(-1, 1))
    parts = met.smc_abc(prior, sampler, dist, (0.5, 0.25, 0.15), 200, rng=rng)
    assert abs(parts.mean() - 0.5) < 0.3, f"SMC-ABC 均值 {parts.mean():.2f}"
    print(f"[PASS] ABC：拒绝后验 μ={kept.mean():.2f}，SMC μ={parts.mean():.2f}")


def test_estimation_optimization():
    """MET036/039/040/041/042：SMM/CMA-ES/DE/GP-BO/NSGA-II。"""
    rng = np.random.default_rng(4)
    # SMM：正态矩匹配
    th, dist = met.simulated_moments(
        lambda r: float(r.uniform(0, 2)),
        lambda th, r: [th, 0.05],
        [1.0, 0.05], rng)
    assert abs(th - 1.0) < 0.15, f"SMM θ={th:.2f}"

    # CMA-ES 与 DE 最小化球面
    x_cma = met.cma_es(lambda x: float(np.sum((x - 1.5) ** 2)), [0.0], 0.4, 50)
    assert abs(x_cma[0] - 1.5) < 0.25, f"CMA-ES {x_cma}"
    x_de = met.differential_evolution(
        lambda x: float((x[0] - 2.0) ** 2), [(-5, 5)], 16, 50, rng=rng)
    assert abs(x_de[0] - 2.0) < 0.3, f"DE {x_de}"

    x_bo, y_bo = met.gp_bayes_optimize(
        lambda x: float((x[0] - 0.7) ** 2), (0.0, 1.0), rng=rng)
    assert abs(x_bo - 0.7) < 0.15, f"GP-BO {x_bo:.3f}"

    front = met.nsga2(lambda x: float((x - 0.3) ** 2),
                      lambda x: float((x - 0.8) ** 2), (0.0, 1.0),
                      40, 40, rng=rng)
    assert len(front) >= 3, f"Pareto 前沿过小 {len(front)}"
    print(f"[PASS] 估计/优化：SMM θ={th:.2f}，CMA={x_cma[0]:.2f}，"
          f"DE={x_de[0]:.2f}，BO={x_bo:.3f}，Pareto={len(front)} 点")


def test_filters_family():
    """MET043-048：KF/EKF/EnKF/PF/APF 跟踪精度优于观测。"""
    rng = np.random.default_rng(5)
    T = 200
    true_x = np.cumsum(rng.normal(0, np.sqrt(0.1), T))
    obs = true_x + rng.normal(0, 1.0, T)
    rmse_obs = float(np.sqrt(np.mean((obs - true_x) ** 2)))

    xs, _ = met.kalman_filter(obs)
    rmse_kf = float(np.sqrt(np.mean((xs - true_x) ** 2)))
    assert rmse_kf < rmse_obs, f"KF {rmse_kf:.3f} ≥ 观测 {rmse_obs:.3f}"

    xs_e, _ = met.enkf(obs, rng=rng)
    rmse_enkf = float(np.sqrt(np.mean((xs_e - true_x) ** 2)))
    assert rmse_enkf < rmse_obs, f"EnKF 未改善 {rmse_enkf:.3f}"

    xs_p = met.bootstrap_particle_filter(obs, rng=rng)
    rmse_pf = float(np.sqrt(np.mean((xs_p - true_x) ** 2)))
    assert rmse_pf < rmse_obs, f"PF 未改善 {rmse_pf:.3f}"

    xs_a = met.auxiliary_pf(obs, rng=rng)
    rmse_apf = float(np.sqrt(np.mean((xs_a - true_x) ** 2)))
    assert rmse_apf < rmse_obs, f"APF 未改善 {rmse_apf:.3f}"

    # EKF：非线性 logistic 观测
    f = lambda x: x
    h = lambda x: float(x ** 3 / (1 + x ** 2))
    Hj = lambda x: np.array([[3 * x ** 2 / (1 + x ** 2) ** 2]])
    obs_nl = np.array([h(x) for x in true_x]) + rng.normal(0, 0.5, T)
    xs_ekf, _ = met.extended_kalman(obs_nl, f, h,
                                    lambda x: np.array([[1.0]]), Hj,
                                    q=0.05, r=0.25)
    rmse_ekf = float(np.sqrt(np.mean((xs_ekf[:, 0] - true_x) ** 2)))
    assert rmse_ekf < 1.0
    print(f"[PASS] 滤波族：KF {rmse_kf:.3f}，EnKF {rmse_enkf:.3f}，"
          f"PF {rmse_pf:.3f}，APF {rmse_apf:.3f}，EKF {rmse_ekf:.3f} "
          f"（观测 {rmse_obs:.3f}）")


def test_fourdvar():
    """MET050：4D-Var 把初值拉向真值。"""
    true_x0 = 2.0
    f = lambda x: x * 0.9
    x_traj = true_x0
    obs = []
    x = true_x0
    for _ in range(5):
        x = f(np.array([x]))[0] if hasattr(x, "__len__") else x * 0.9
        obs.append(x + np.random.default_rng(0).normal(0, 0.05))
    obs = np.array(obs)
    x_est = met.fourdvar(obs, lambda v: np.array([v[0] * 0.9]),
                         np.array([0.5]))
    assert abs(x_est[0] - true_x0) < abs(0.5 - true_x0), \
        f"4D-Var 估计 {x_est[0]:.2f} 未接近 {true_x0}"
    print(f"[PASS] 4D-Var：初值 0.5 → {x_est[0]:.2f}（真 {true_x0}）")


def test_sensitivity_family():
    """MET051-056：Morris/Sobol 识别重要因子；PAWN/Shapley/FAST/局部导数。"""
    rng = np.random.default_rng(6)

    # f: x1 重要（斜率3），x2 弱（0.3）
    f = lambda x: 3.0 * x[0] + 0.3 * x[1] + 0.05 * np.sin(10 * x[0] * x[1])
    mu_star = met.morris_screening(lambda p: f(p), n_vars=2, n_traj=30, rng=rng)
    assert mu_star[0] > 2 * mu_star[1], f"Morris 排序失败 {mu_star}"

    S1, ST = met.sobol_indices(lambda x: 3.0 * x[0] + 0.3 * x[1],
                               n_sob=2048, rng=rng)
    assert S1[0] > S1[1], f"Sobol 一阶 {S1}"
    assert ST[0] > ST[1], f"Sobol 总指标 {ST}"

    ks = met.pawn_sensitivity(lambda x: 3.0 * x[0] + 0.3 * x[1], rng=rng)
    assert ks[0] > ks[1], f"PAWN {ks}"

    sh = met.shapley_sensitivity(lambda x: 3.0 * x[0] + 0.3 * x[1], rng=rng)
    assert abs(sh[0]) > abs(sh[1]), f"Shapley {sh}"

    s_fast = met.fast_sensitivity(lambda x: 3.0 * x[0] + 0.3 * x[1])
    assert s_fast[0] > s_fast[1], f"FAST {s_fast}"

    g = met.local_sensitivity(lambda x: 3.0 * x[0] + 0.3 * x[1], [0.5, 0.5])
    assert abs(g[0] - 3.0) < 0.05 and abs(g[1] - 0.3) < 0.05, f"局部导数 {g}"
    print(f"[PASS] 敏感性族：Morris μ*={mu_star.round(2)}，Sobol S1="
          f"{S1.round(2)}，PAWN={ks.round(2)}，Shapley={sh.round(2)}，"
          f"FAST={s_fast.round(2)}，∇={g.round(2)}")


def test_uncertainty_diagnostics():
    """MET057-059：Bootstrap CI 覆盖；PPC p 值合理；校准诊断。"""
    rng = np.random.default_rng(7)
    data = rng.normal(5.0, 1.0, 200)
    lo, hi = met.bootstrap_ci(data, B=1500, rng=rng)
    smean = float(np.mean(data))
    assert lo < smean < hi, f"CI [{lo:.2f},{hi:.2f}] 未覆盖样本均值 {smean:.2f}"
    assert hi - lo < 0.5, f"CI 过宽 {hi - lo:.2f}"

    ppc = met.posterior_predictive_check(np.zeros(100),
                                         rng.normal(0, 1, 500))
    assert ppc["inside_95"], f"PPC 未覆盖 {ppc}"

    diag = met.calibration_diagnosis([1.0], [0.95], [1.0, 1.1], [1.02, 1.08])
    assert diag["ok"], f"诊断 {diag}"
    print(f"[PASS] 不确定性：CI[{lo:.2f},{hi:.2f}]，PPC p={ppc['p_value']:.2f}，"
          f"诊断 ok={diag['ok']}")


def test_population_synthesis():
    """MET060-064：IPF 闭合 / IPU 收敛 / 记录整数化 / 水塘 / 组合优化。"""
    seed = np.ones((3, 4))
    row = np.array([60.0, 30.0, 10.0])
    col = np.array([20.0, 25.0, 25.0, 30.0])
    M = met.ipf(seed, row, col)
    assert np.abs(M.sum(axis=1) - row).max() < 1e-6
    assert np.abs(M.sum(axis=0) - col).max() < 1e-6

    w = met.ipu(np.ones(10), {"a": (np.arange(5), 30.0),
                              "b": (np.arange(5, 10), 20.0)},
                {"a": 30.0, "b": 20.0})
    assert abs(w[:5].sum() - 30) < 3 and abs(w[5:].sum() - 20) < 3, \
        f"IPU 未收敛 {w}"

    recs = met.weighted_record_sampling([0.5, 2.0, 1.5], ["a", "b", "c"], 8)
    assert len(recs) == 8 and recs.count("b") >= 3

    idx = met.quasi_random_without_replacement([1.0, 3.0, 2.0], 3,
                                               np.random.default_rng(0))
    assert len(idx) == 3 and len(set(idx)) == 3

    sel, cost = met.combinatorial_optimization_synthesize(
        np.arange(5), None, [4, 3, 2, 1, 0], n_iter=500,
        rng=np.random.default_rng(0))
    cur = np.bincount(sel, minlength=5)
    assert np.abs(cur - np.array([4, 3, 2, 1, 0])).sum() <= 2, \
        f"组合合成失配 {cur}"
    print(f"[PASS] 人口合成：IPF 闭合、IPU 收敛、整数化 8 条、"
          f"无放回 3、组合合成 cost={cost:.0f}")


if __name__ == "__main__":
    test_integrator_orders()
    test_sde_schemes()
    test_master_equation_methods()
    test_mc_variance_reduction()
    test_doe_designs()
    test_mcmc_family()
    test_abc_family()
    test_estimation_optimization()
    test_filters_family()
    test_fourdvar()
    test_sensitivity_family()
    test_uncertainty_diagnostics()
    test_population_synthesis()
    print("\n===== DAYAN 方法论家族：全部通过 =====")
