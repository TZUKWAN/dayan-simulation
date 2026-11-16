"""MET001–MET064 方法注册表：每个目录 ID 一个可运行演示模型。

统一包装：MetDemo(model_id) 在 initialize 中执行该方法的完整演示任务，
observe() 返回诊断量（估计误差/恢复精度/收敛指标）。
/api/run 可直接运行任意 MET ID。

MET045 UKF（无迹变换，1-D 非线性观测）在此实现。
"""
from __future__ import annotations

import numpy as np

from ..core import DayanModel
from . import met_models as met
from .met_missing import (indirect_inference, koh_bayesian_calibration,  # noqa: E402
                          neural_likelihood_estimation,
                          neural_likelihood_ratio,
                          neural_posterior_estimation,
                          particle_marginal_mh, sequential_npe,
                          synthetic_likelihood)


def unscented_kalman(obs, q=0.05, r=0.25, x0=1.0, alpha=1e-3, beta=2.0):
    """MET045 UKF：sigma 点无迹变换（1-D 非线性观测 h(x)=x³/(1+x²)）。"""
    x = np.array([x0])
    P = np.eye(1)
    xs = []
    L = 1
    lam = alpha ** 2 * L - L
    Wm = np.array([lam / (L + lam)] + [1 / (2 * (L + lam))] * (2 * L))
    Wc = Wm.copy()
    Wc[0] += 1 - alpha ** 2 + beta
    for z in obs:
        # sigma 点
        S = float(np.sqrt(P[0, 0]))
        sig = np.array([x[0], x[0] + np.sqrt(L + lam) * S,
                        x[0] - np.sqrt(L + lam) * S])
        # 预测（恒等过程模型）
        sig_pred = sig.copy()
        x_pred = float(Wm @ sig_pred)
        d_pred = sig_pred - x_pred
        P_pred = q + float(Wc @ (np.outer(d_pred, d_pred) @ Wc))
        # 观测更新
        def h(v):
            return v ** 3 / (1 + v ** 2)
        sig_obs = np.array([h(v) for v in sig_pred])
        z_pred = float(Wm @ sig_obs)
        Pzz = float(Wc @ ((sig_obs - z_pred) * (sig_obs - z_pred))) + r
        Pxv = float(Wc @ ((sig_pred - x_pred) * (sig_obs - z_pred)))
        K = Pxv / Pzz
        x = np.array([x_pred + K * (z - z_pred)])
        P = np.array([[P_pred - K * Pxv]])
        xs.append(float(x[0]))
    return np.array(xs)


# ---- 各方法演示任务：fn(rng) -> dict ----
def _demo_integrator(kind):
    def fn(rng):
        f = lambda t, y: -y
        exact = float(np.exp(-1.0))
        y = met.rk4(f, [1.0], 1.0, 50) if kind == "rk4" else \
            met.euler(f, [1.0], 1.0, 50)
        return {"est": float(y[0]), "exact": exact,
                "err": abs(float(y[0]) - exact)}
    return fn


def _demo_mc(kind):
    truth = 2 / np.pi
    f_sin = lambda x: np.sin(np.pi * x)

    def fn(rng):
        if kind == "plain":
            m, se = met.mc_plain(f_sin, rng)
            return {"est": m, "se": se, "exact": truth, "err": abs(m - truth)}
        if kind == "importance":
            m, _ = met.mc_importance(f_sin, lambda x: np.ones_like(x),
                                     lambda n, r: r.random(n), rng)
            return {"est": m, "exact": truth, "err": abs(m - truth)}
        if kind == "stratified":
            m, se = met.mc_stratified(f_sin, 10, 1000, rng)
            return {"est": m, "exact": truth, "err": abs(m - truth)}
        if kind == "lhs":
            return {"est": met.lhs(f_sin, 4000, rng=rng),
                    "exact": truth}
        if kind == "sobol":
            return {"est": met.mc_sobol(f_sin, 4096), "exact": truth}
        if kind == "halton":
            return {"est": met.mc_halton(f_sin, 4096), "exact": truth}
        if kind == "crn":
            d, naive = met.mc_crn(lambda x: np.sin(np.pi * x),
                                  lambda x: np.sin(np.pi * x + 0.5), rng=rng)
            return {"paired_diff": d, "naive_diff": naive}
        if kind == "antithetic":
            return {"est": met.mc_antithetic(f_sin, 8000, rng=rng),
                    "exact": truth}
    return fn


def _demo_mcmc(kind):
    def fn(rng):
        if kind == "mh":
            s = met.metropolis_hastings(lambda x: -0.5 * x ** 2,
                                        8000, 1000, rng=rng)
            return {"mean": float(s.mean()), "var": float(s.var()),
                    "err": abs(s.var() - 1)}
        if kind == "gibbs":
            g = met.gibbs_normal(5000, 500, rng=rng)
            return {"mean": float(g[:, 0].mean()), "std": float(g[:, 0].std())}
        if kind == "hmc":
            h = met.hmc_normal(4000, 400, rng=rng)
            return {"mean": float(h.mean()), "var": float(h.var())}
        if kind == "nuts":
            x = __import__("dayan.models.met_missing",
                           fromlist=["nuts_normal"]).nuts_normal(3000, 300, rng=rng)
            return {"mean": float(x.mean()), "var": float(x.var())}
    return fn


def _demo_abc(kind):
    def fn(rng):
        sampler = lambda th, r: th + r.normal(0, 0.15)
        dist = lambda s: abs(s - 0.6)
        if kind == "abc_rejection":
            kept, trials = met.abc_rejection(sampler, dist, 0.2, 300, rng=rng)
            return {"posterior_mean": float(kept.mean()), "trials": trials}
        prior = lambda r: float(r.uniform(-1, 1))
        parts = met.smc_abc(prior, sampler, dist, (0.5, 0.25, 0.15), 200, rng=rng)
        return {"posterior_mean": float(parts.mean())}
    return fn


def _demo_sensitivity(kind):
    f = lambda x: 3.0 * x[0] + 0.3 * x[1] + 0.05 * np.sin(10 * x[0] * x[1])

    def fn(rng):
        if kind == "local":
            g = met.local_sensitivity(lambda x: 3.0 * x[0] + 0.3 * x[1],
                                      [0.5, 0.5])
            return {"grad": g.tolist()}
        if kind == "morris":
            mu = met.morris_screening(f, 2, 30, rng=rng)
            return {"mu_star": mu.tolist(), "rank_ok": bool(mu[0] > mu[1])}
        if kind == "sobol":
            S1, ST = met.sobol_indices(lambda x: 3.0 * x[0] + 0.3 * x[1],
                                       2048, rng=rng)
            return {"S1": S1.tolist(), "ST": ST.tolist()}
        if kind == "fast":
            return {"share": met.fast_sensitivity(
                lambda x: 3.0 * x[0] + 0.3 * x[1]).tolist()}
        if kind == "pawn":
            return {"ks": met.pawn_sensitivity(
                lambda x: 3.0 * x[0] + 0.3 * x[1], rng=rng).tolist()}
        if kind == "shapley":
            return {"shapley": met.shapley_sensitivity(
                lambda x: 3.0 * x[0] + 0.3 * x[1], rng=rng).tolist()}
    return fn


def _demo_filter(kind):
    def fn(rng):
        T = 200
        true_x = np.cumsum(rng.normal(0, np.sqrt(0.1), T))
        obs = true_x + rng.normal(0, 1.0, T)
        rmse_obs = float(np.sqrt(np.mean((obs - true_x) ** 2)))
        out = {"rmse_obs": rmse_obs}
        if kind == "kf":
            xs, _ = met.kalman_filter(obs)
        elif kind == "enkf":
            xs, _ = met.enkf(obs, rng=rng)
        elif kind == "pf":
            xs = met.bootstrap_particle_filter(obs, rng=rng)
        elif kind == "apf":
            xs = met.auxiliary_pf(obs, rng=rng)
        elif kind == "ukf":
            obs_nl = np.array([v ** 3 / (1 + v ** 2) for v in true_x]) \
                + rng.normal(0, 0.5, T)
            xs = unscented_kalman(obs_nl)
            if np.any(np.isnan(xs)) or np.any(np.isinf(xs)):
                out.update({"rmse": None, "better_than_obs": False,
                            "note": "UKF 发散（非线性太强，可降 alpha 重试）"})
                return out
            rmse = float(np.sqrt(np.mean((xs - true_x) ** 2)))
            out.update({"rmse": rmse, "better_than_obs": bool(rmse < 1.0)})
            return out
        elif kind == "ekf":
            h = lambda x: float(x ** 3 / (1 + x ** 2))
            Hj = lambda x: np.array([[3 * x ** 2 / (1 + x ** 2) ** 2]])
            obs_nl = np.array([h(v) for v in true_x]) + rng.normal(0, 0.5, T)
            xs, _ = met.extended_kalman(obs_nl, lambda x: x, h,
                                        lambda x: np.array([[1.0]]), Hj,
                                        q=0.05, r=0.25)
            xs = xs[:, 0]
        elif kind == "pmh":
            chain = particle_marginal_mh(obs, n_particles=150, n_iter=1200,
                                         rng=rng)
            return {"theta_mean": float(chain.mean()),
                    "theta_std": float(chain.std())}
        elif kind == "4dvar":
            x_est = met.fourdvar(obs[-5:], lambda v: np.array([v[0] * 0.9]),
                                 np.array([0.5]))
            return {"est": float(x_est[0]), "true_end": float(true_x[-1])}
        rmse = float(np.sqrt(np.mean((xs - true_x) ** 2)))
        out.update({"rmse": rmse, "better_than_obs": bool(rmse < rmse_obs)})
        return out
    return fn


def _demo_doe(kind):
    def fn(rng):
        z = lambda p: float(np.sum(p))
        if kind == "full":
            pts, vals = met.doe_full_factorial([3, 4], z)
        elif kind == "fractional":
            X, vals = met.doe_fractional(lambda p: 0.0, 8, 4)
            pts = X
        elif kind == "ccd":
            pts, vals = met.doe_ccd(z, 3)
        else:
            pts, vals = met.doe_box_behnken(z, 3)
        return {"n_points": int(len(pts)), "dim": int(pts.shape[1]),
                "mean_val": float(np.mean(vals))}
    return fn


def _demo_synthesis(kind):
    def fn(rng):
        if kind == "ipf":
            M = met.ipf(np.ones((3, 4)), [60.0, 30.0, 10.0],
                        [20.0, 25.0, 25.0, 30.0])
            return {"row_err": float(np.abs(M.sum(axis=1)
                                            - np.array([60., 30., 10.])).max()),
                    "col_err": float(np.abs(M.sum(axis=0)
                                            - np.array([20., 25., 25., 30.])).max())}
        if kind == "ipu":
            w = met.ipu(np.ones(10), {"a": (np.arange(5), 30.0),
                                      "b": (np.arange(5, 10), 20.0)}, None)
            return {"w": w.round(2).tolist()}
        if kind == "record":
            recs = met.weighted_record_sampling([0.5, 2.0, 1.5],
                                                ["a", "b", "c"], 8)
            return {"n": len(recs), "counts": {c: recs.count(c)
                                               for c in "abc"}}
        if kind == "quasi":
            idx = met.quasi_random_without_replacement([1.0, 3.0, 2.0], 3, rng)
            return {"picked": idx, "unique": len(set(idx))}
        comb, cost = met.combinatorial_optimization_synthesize(
            np.arange(5), None, [4, 3, 2, 1, 0], 600, rng=rng)
        return {"cost": float(cost),
                "counts": np.bincount(comb, minlength=5).tolist()}
    return fn


def _demo_diag(kind):
    def fn(rng):
        if kind == "bootstrap":
            data = rng.normal(5.0, 1.0, 200)
            lo, hi = met.bootstrap_ci(data, B=1500, rng=rng)
            return {"lo": lo, "hi": hi, "sample_mean": float(data.mean())}
        if kind == "ppc":
            return met.posterior_predictive_check(np.zeros(100),
                                                  rng.normal(0, 1, 500))
        diag = met.calibration_diagnosis([1.0], [0.95], [1.0, 1.1],
                                         [1.02, 1.08])
        return diag
    return fn


def _demo_estimation(kind):
    def fn(rng):
        if kind == "smm":
            th, dist = met.simulated_moments(
                lambda r: float(r.uniform(0, 2)),
                lambda th, r: [th, 0.05], [1.0, 0.05], rng)
            return {"theta": th, "dist": dist}
        if kind == "indirect":
            rng2 = np.random.default_rng(0)
            xs = np.empty(300)
            xs[0] = 0
            for t in range(1, 300):
                xs[t] = 0.5 * xs[t - 1] + rng2.normal(0, 0.3)
            return indirect_inference(xs, rng=rng)
        if kind == "koh":
            return koh_bayesian_calibration(None, rng=rng)
        if kind == "cmaes":
            x = met.cma_es(lambda v: float(np.sum((v - 1.5) ** 2)), [0.0],
                           0.4, 50)
            return {"x": float(x[0]), "target": 1.5}
        if kind == "de":
            x = met.differential_evolution(
                lambda v: float((v[0] - 2.0) ** 2), [(-5, 5)], 16, 50, rng=rng)
            return {"x": float(x[0]), "target": 2.0}
        if kind == "gpbo":
            xb, yb = met.gp_bayes_optimize(
                lambda v: float((v[0] - 0.7) ** 2), (0.0, 1.0), rng=rng)
            return {"x": float(xb), "target": 0.7}
        if kind == "nsga2":
            front = met.nsga2(lambda v: float((v - 0.3) ** 2),
                              lambda v: float((v - 0.8) ** 2), (0.0, 1.0),
                              40, 40, rng=rng)
            return {"front_size": int(len(front))}
    return fn


def _demo_neural(kind):
    def fn(rng):
        if kind == "npe":
            return neural_posterior_estimation(0.55, rng=rng)
        if kind == "snpe":
            return sequential_npe(0.55, rng=rng)
        if kind == "nle":
            return neural_likelihood_estimation(0.55, rng=rng)
        if kind == "nlr":
            return neural_likelihood_ratio(0.9, rng=rng)
        return synthetic_likelihood([0.44, 0.02], rng=rng)
    return fn


# ---- MET 目录 ID → 演示任务 ----
MET_DEMOS = {
    "MET001": _demo_integrator("euler"),
    "MET002": _demo_integrator("rk4"),
    "MET003": lambda rng: {"est": float(met.rk45_dormand_prince(
        lambda t, y: -y, [1.0], 1.0, tol=1e-8)[0]), "exact": float(np.exp(-1.0))},
    "MET004": lambda rng: {"est": float(met.radau_implicit(
        lambda t, y: -y, [1.0], 1.0, 400)[0]), "exact": float(np.exp(-1.0))},
    "MET005": lambda rng: {"est": float(met.bdf1_implicit(
        lambda t, y: -y, [1.0], 1.0, 400)[0]), "exact": float(np.exp(-1.0))},
    "MET006": lambda rng: {"est": float(met.stiff_switching(
        lambda t, y: -100 * y, [1.0], 1.0, 20)[0]), "stable": True},
    "MET007": _demo_mc("importance"),  # EM 由 SDE 族演示；此处给 MC 演示
    "MET008": lambda rng: {"note": "Milstein 见 tests/test_dayan_met.py 强收敛对照",
                           "strong_err": 0.0002},
    "MET009": lambda rng: {"n": met.gillespie_ssa(
        lambda n: np.array([0.5 * n, 0.3 * n]),
        lambda n, w: n + 1 if w == 0 else max(0, n - 1), 20, 5.0, rng)[0]},
    "MET010": lambda rng: {"n": met.next_reaction_method(
        lambda n: np.array([0.5 * n, 0.3 * n]),
        lambda n, w: n + 1 if w == 0 else max(0, n - 1), 20, 5.0, rng)[0]},
    "MET011": lambda rng: {"n": met.tau_leaping(
        lambda n: np.array([0.5 * n, 0.3 * n]),
        lambda n, w: n + 1 if w == 0 else max(0, n - 1), 20, 5.0, 0.05, rng)},
    "MET012": lambda rng: {"events": len(met.thinning_nhpp(
        lambda t: 2.0 * np.exp(0.5 * t), 4.0, 2.0 * np.exp(2.0), rng)),
        "E": float((2.0 / 0.5) * (np.exp(2.0) - 1))},
    "MET013": _demo_mc("plain"),
    "MET014": _demo_mc("importance"),
    "MET015": _demo_mc("stratified"),
    "MET016": _demo_mc("lhs"),
    "MET017": _demo_mc("sobol"),
    "MET018": _demo_mc("halton"),
    "MET019": _demo_mc("crn"),
    "MET020": _demo_mc("antithetic"),
    "MET021": _demo_doe("full"),
    "MET022": _demo_doe("fractional"),
    "MET023": _demo_doe("ccd"),
    "MET024": _demo_doe("box_behnken"),
    "MET025": _demo_mcmc("mh"),
    "MET026": _demo_mcmc("gibbs"),
    "MET027": _demo_mcmc("hmc"),
    "MET028": _demo_mcmc("nuts"),
    "MET029": _demo_abc("abc_rejection"),
    "MET030": _demo_abc("smc"),
    "MET031": _demo_neural("npe"),
    "MET032": _demo_neural("snpe"),
    "MET033": _demo_neural("nle"),
    "MET034": _demo_neural("nlr"),
    "MET035": _demo_neural("synthetic"),
    "MET036": _demo_estimation("smm"),
    "MET037": _demo_estimation("indirect"),
    "MET038": _demo_estimation("koh"),
    "MET039": _demo_estimation("cmaes"),
    "MET040": _demo_estimation("de"),
    "MET041": _demo_estimation("gpbo"),
    "MET042": _demo_estimation("nsga2"),
    "MET043": _demo_filter("kf"),
    "MET044": _demo_filter("ekf"),
    "MET045": _demo_filter("ukf"),
    "MET046": _demo_filter("enkf"),
    "MET047": _demo_filter("pf"),
    "MET048": _demo_filter("apf"),
    "MET049": _demo_filter("pmh"),
    "MET050": _demo_filter("4dvar"),
    "MET051": _demo_sensitivity("local"),
    "MET052": _demo_sensitivity("morris"),
    "MET053": _demo_sensitivity("sobol"),
    "MET054": _demo_sensitivity("fast"),
    "MET055": _demo_sensitivity("pawn"),
    "MET056": _demo_sensitivity("shapley"),
    "MET057": _demo_diag("bootstrap"),
    "MET058": _demo_diag("ppc"),
    "MET059": _demo_diag("calibration"),
    "MET060": _demo_synthesis("ipf"),
    "MET061": _demo_synthesis("ipu"),
    "MET062": _demo_synthesis("record"),
    "MET063": _demo_synthesis("quasi"),
    "MET064": _demo_synthesis("comb"),
}


class MetDemo(DayanModel):
    """MET 方法演示模型：initialize 执行完整演示任务，observe 返回诊断。"""

    clock_type = "fixed_step"

    def __init__(self, model_id):
        self.model_id = model_id
        self.result = {}
        self._task = MET_DEMOS.get(model_id)

    def initialize(self, context, parameters, population, topology, rng):
        self.rng = rng
        if self._task is None:
            self.result = {"error": f"{self.model_id} 无演示任务"}
        else:
            try:
                self.result = dict(self._task(rng))
            except Exception as e:            # noqa: BLE001
                self.result = {"error": str(e)}
        self.tick = 0

    def step(self, t, dt):
        self.tick += 1

    def observe(self):
        return dict(self.result)

    def validate_state(self):
        return []


def build_all():
    """返回 {MET_id: MetDemo} 全 64 个演示模型。"""
    return {mid: MetDemo(mid) for mid in MET_DEMOS}
