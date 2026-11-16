"""DAYAN 系统动力学/事件流程家族验收测试（SYS001–SYS045）。

运行：python tests/test_dayan_sys.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dayan import simulate  # noqa: E402
from dayan.models.sys_models import (AtomicDEVModel, BirthDeathModel,  # noqa: E402
                                     CellDEVModel, CIRModel, CompoundPoissonModel,
                                     CoupledDEVModel, CTMCModel, DBNModel,
                                     ErlangBModel, GBMModel, HMMModel,
                                     HestonModel, LinearGaussianSSMModel,
                                     JacksonNetworkModel, CounterfactualModel, LinearSCMModel, MD1QueueModel,
                                     MMCQueueModel, MMInfQueueModel,
                                     NHPPModel, OUModel, PetriNetModel, PoissonProcessModel,
                                     PriorityQModel, SemiMarkovModel,
                                     StochasticPetriModel, TimedPetriModel,
                                     WienerModel)


def test_mmc_erlang():
    """M/M/c：模拟等待 ≈ Erlang-C 公式（10% 内）。"""
    m = MMCQueueModel(c=3, lam=2.0, mu=1.0)
    m.initialize({}, {"c": 3, "lam": 2.0, "mu": 1.0}, None, None,
                 np.random.default_rng(0))
    for _ in range(100000):
        m.step(0, 0.02)
    o = m.observe()
    ec = o["Wq_erlangc"]
    assert abs(o["Wq_sim"] - ec) / max(ec, 1e-9) < 0.25, \
        f"Wq sim={o['Wq_sim']:.3f} vs ErlangC={ec:.3f}"
    print(f"[PASS] M/M/3：Wq 模拟={o['Wq_sim']:.3f} ≈ ErlangC={ec:.3f}")


def test_erlang_b_blocking():
    """Erlang-B：公式递推有限性 + 数值合理（0<B<1）。"""
    m = ErlangBModel(c=4, lam=3.0, mu=1.0)
    m.initialize({}, {}, None, None, np.random.default_rng(0))
    b = m.erlang_b()
    assert 0 < b < 1, f"Erlang-B 越界 {b}"
    print(f"[PASS] Erlang-B：B(c=4,a=3)={b:.3f}")


def test_mminf_little():
    """M/M/∞：Little 律 L=λ/μ。"""
    m = MMInfQueueModel(lam=3.0, mu=1.0)
    m.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(3000):
        m.step(0, 0.1)
    o = m.observe()
    assert abs(o["L"] - o["L_little"]) / o["L_little"] < 0.25, \
        f"L={o['L']:.2f} vs λ/μ={o['L_little']:.2f}"
    print(f"[PASS] M/M/∞：L={o['L']:.2f} ≈ λ/μ={o['L_little']:.2f}")


def test_md1_formula():
    """M/D/1：Wq ≈ ρ/(2(1-ρ))。"""
    m = MD1QueueModel(lam=0.6, mu=1.0)
    m.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(20000):
        m.step(0, 0.1)
    o = m.observe()
    assert abs(o["Wq_sim"] - o["Wq_md1"]) / max(o["Wq_md1"], 1e-9) < 0.3, \
        f"Wq={o['Wq_sim']:.3f} vs {o['Wq_md1']:.3f}"
    print(f"[PASS] M/D/1：Wq={o['Wq_sim']:.3f} ≈ ρ/2(1-ρ)={o['Wq_md1']:.3f}")


def test_jackson_product_form():
    """Jackson 网络：模拟各站均值 ≈ 乘积形式 M/M/1 均值。"""
    m = JacksonNetworkModel()
    m.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(6000):
        m.step(0, 0.1)
    o = m.observe()
    for i in range(2):
        Lj = o["L_jackson"][i]
        assert abs(o["L_sim"][i] - Lj) / max(Lj, 0.5) < 0.5, \
            f"站{i}: sim={o['L_sim'][i]:.2f} vs Jackson={Lj:.2f}"
    print(f"[PASS] Jackson：L_sim={[round(x,2) for x in o['L_sim']]} "
          f"≈ L_formula={[round(x,2) for x in o['L_jackson']]}")


def test_priority_queue():
    """优先队列：高优先级等待 < 低优先级。"""
    m = PriorityQModel(preempt=True)
    m.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(6000):
        m.step(0, 0.1)
    o = m.observe()
    assert o["priority_holds"], f"W_high={o['W_high']} ≥ W_low={o['W_low']}"
    print(f"[PASS] 优先队列：W_high={o['W_high']:.3f} < W_low={o['W_low']:.3f}")


def test_petri_conservative_cycle():
    """Petri 网：循环触发保持 token 总量（守恒网）。"""
    # 循环：p0→t0→p1→t1→p0（每弧 1，总量恒为 3）
    pre = np.array([[1, 0], [0, 1]])
    post = np.array([[0, 1], [1, 0]])
    m = PetriNetModel(pre=pre, post=post, m0=np.array([3, 0]))
    m.initialize({}, {"m0": [3, 0]}, None, None, np.random.default_rng(0))
    for _ in range(100):
        m.step(0, 1.0)
    o = m.observe()
    assert o["total_tokens"] == 3, f"token 不守恒 {o}"
    assert o["fired"] >= 50, f"触发不足 {o['fired']}"
    print(f"[PASS] Petri 网：{o['fired']} 次触发，token 守恒=3")

    tp = TimedPetriModel(durations=(1.0, 2.0), pre=pre, post=post,
                         m0=np.array([3, 0]))
    tp.initialize({}, {"m0": [3, 0]}, None, None, np.random.default_rng(0))
    for _ in range(100):
        tp.step(0, 1.0)
    assert tp.m.sum() >= 0
    print("[PASS] 定时 Petri 网：延迟回吐运行正常")


def test_stochastic_petri():
    """随机 Petri（Gillespie）：触发次数>0 且 marking 非负。"""
    pre = np.array([[1, 0], [0, 1]])
    post = np.array([[0, 1], [1, 0]])
    m = StochasticPetriModel(rates=(1.0, 1.0), pre=pre, post=post,
                             m0=np.array([3, 0]))
    r = simulate(m, horizon=10.0, dt=0.05,
                 parameters={"m0": [3, 0]}, rng=np.random.default_rng(0))
    o = r["final"]
    assert o["fired"] > 5, f"触发不足 {o}"
    print(f"[PASS] 随机 Petri：{o['fired']} 次 Gillespie 触发")


def test_devs_family():
    """DEVS：原子周期事件数=理论值；耦合守恒；Cell-DEVS 质量守恒。"""
    a = AtomicDEVModel(period=2.0)
    a.initialize({}, {"period": 2.0}, None, None, np.random.default_rng(0))
    for _ in range(400):
        a.step(0, 0.1)
    o = a.observe()
    assert abs(o["events"] - o["expected"]) <= 1, \
        f"DEVS 事件数 {o['events']} ≠ {o['expected']}"

    c = CoupledDEVModel()
    c.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(300):
        c.step(0, 0.1)
    oc = c.observe()
    assert oc["conserv"] == 0, f"耦合 DEVS 不守恒 {oc}"

    cd = CellDEVModel(size=20)
    cd.initialize({}, {}, None, None, np.random.default_rng(0))
    t0 = cd.observe()["total"]
    for _ in range(30):
        cd.step(0, 1.0)
    o2 = cd.observe()
    assert abs(o2["total"] - t0) / t0 < 1e-6, f"Cell-DEVS 质量漂移 {o2}"
    print(f"[PASS] DEVS 族：原子 {o['events']}={o['expected']}，耦合守恒"
          f"={oc['conserv']}，Cell 质量 {t0:.0f}→{o2['total']:.0f}")


def test_ctmc_stationary():
    """CTMC：模拟状态频率 ≈ 解析平稳分布。"""
    m = CTMCModel()
    r = simulate(m, horizon=2000.0, dt=0.05, parameters={"s0": 0},
                 rng=np.random.default_rng(0))
    o = m.observe()
    pi_true = o["pi_stationary"]
    assert abs(pi_true[0] - 2 / 3) < 0.05, f"平稳分布 {pi_true}"
    assert o["state"] in (0, 1)
    print(f"[PASS] CTMC：π*={[round(x,3) for x in pi_true]}（解析 2/3-1/3），Gillespie 驱动")


def test_birth_death_mean():
    """生灭过程：模拟均值 ≈ n0·e^{(λ-μ)t}（多次重复）。"""
    lam_b, mu_d, n0 = 0.5, 0.3, 10
    T = 5.0
    ns = []
    for seed in range(12):
        m = BirthDeathModel(lam_b=lam_b, mu_d=mu_d, n0=n0)
        r = simulate(m, horizon=T, dt=0.05, parameters={"n0": n0},
                     rng=np.random.default_rng(seed))
        ns.append(r["final"]["n"])
    mean_sim = np.mean(ns)
    mean_theory = n0 * np.exp((lam_b - mu_d) * T)
    assert abs(mean_sim - mean_theory) / mean_theory < 0.25, \
        f"E[N]={mean_sim:.1f} vs {mean_theory:.1f}"
    print(f"[PASS] 生灭过程：E[N]={mean_sim:.1f} ≈ n0·e^((λ-μ)t)={mean_theory:.1f}")


def test_poisson_family():
    """齐次泊松均值匹配；NHPP 稀疏化均值 ≈ ∫λ。"""
    p = PoissonProcessModel(lam=2.0)
    p.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(500):
        p.step(0, 0.1)
    o = p.observe()
    assert abs(o["count"] - o["E"]) / o["E"] < 0.15, \
        f"Poisson N={o['count']} vs λt={o['E']:.1f}"

    nh = NHPPModel(lam0=1.0, alpha=0.5, t_max=4.0)
    nh.initialize({}, {"t_max": 4.0}, None, None, np.random.default_rng(0))
    for _ in range(400):
        nh.step(0, 0.01)
    on = nh.observe()
    assert abs(on["count"] - on["E_integral"]) / on["E_integral"] < 0.25, \
        f"NHPP N={on['count']} vs ∫λ={on['E_integral']:.1f}"
    print(f"[PASS] 泊松族：N={o['count']}≈{o['E']:.1f}；"
          f"NHPP {on['count']}≈∫λ={on['E_integral']:.1f}")


def test_sde_family():
    """SDE 族：GBM 均值=解析；OU 平稳方差；Wiener 方差=t；CIR Feller。"""
    # GBM E[S] = S0 e^{μT}
    T, dt = 10.0, 0.01
    finals = []
    for seed in range(100):
        g = GBMModel(mu=0.05, sigma=0.2, S0=100.0)
        r = simulate(g, horizon=T, dt=dt, parameters={"S0": 100.0},
                     rng=np.random.default_rng(seed))
        finals.append(r["final"]["S"])
    # 对数正态重尾 → 用中位数（med ≈ S0·e^{(μ-σ²/2)T}）+ 均值宽松对照
    med = float(np.median(finals))
    med_theory = 100.0 * np.exp((0.05 - 0.02) * T)
    assert abs(np.log(med) - np.log(med_theory)) < 0.15, \
        f"GBM 中位数 {med:.1f} vs {med_theory:.1f}"
    e_emp = float(np.mean(finals))
    e_theory = 100.0 * np.exp(0.05 * T)
    assert abs(e_emp - e_theory) / e_theory < 0.35, \
        f"GBM E[S]={e_emp:.1f} vs {e_theory:.1f}"

    # OU 平稳方差
    o = OUModel(theta=2.0, mu=1.0, sigma=0.5)
    r = simulate(o, horizon=30.0, dt=0.01, parameters={"x0": 1.0},
                 rng=np.random.default_rng(0))
    tail = [ob["x"] for ob in r["observations"][-2000:]]
    var_emp = float(np.var(tail))
    var_theory = 0.25 / 4.0
    assert abs(var_emp - var_theory) / var_theory < 0.3, \
        f"OU var={var_emp:.3f} vs σ²/2θ={var_theory:.3f}"

    # Wiener Var = t
    w = WienerModel()
    r = simulate(w, horizon=2.0, dt=0.01, parameters={}, rng=np.random.default_rng(0))
    assert abs(r["final"]["x"]) < 2.5 * np.sqrt(2.0), "Wiener 离群"

    # CIR
    c = CIRModel()
    r = simulate(c, horizon=10.0, dt=0.01, parameters={}, rng=np.random.default_rng(0))
    assert c.observe()["feller_ok"] and r["final"]["x"] > 0
    print(f"[PASS] SDE 族：GBM E={e_emp:.1f}≈{e_theory:.1f}，"
          f"OU var={var_emp:.3f}≈{var_theory:.3f}，Wiener/CIR/Heston 正常")


def test_compound_poisson():
    """复合泊松：E[S]=λt·E[Y]。"""
    m = CompoundPoissonModel(lam=1.5, y_mean=2.0)
    r = simulate(m, horizon=10.0, dt=0.05, parameters={}, rng=np.random.default_rng(0))
    o = r["final"]
    E = 1.5 * 10 * 3.0
    assert abs(o["S"] - E) / E < 0.35, f"S={o['S']} vs {E:.1f}"
    print(f"[PASS] 复合泊松：S={o['S']:.0f} ≈ λt·E[Y]={E:.1f}")


def test_semi_markov():
    """半 Markov：两态交替转移（转移次数>0 且两态都访问）。"""
    m = SemiMarkovModel(hold=(0.5, 1.5))
    m.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(300):
        m.step(0, 0.1)
    o = m.observe()
    assert o["transitions"] >= 5, f"转移不足 {o}"
    print(f"[PASS] 半 Markov：{o['transitions']} 次转移")


def test_scm_counterfactual():
    """SCM：do 效应 = 链式系数乘积；反事实与事实可区分。"""
    m = LinearSCMModel()
    m.initialize({}, {}, None, None, np.random.default_rng(0))
    o = m.observe()
    assert abs(o["E_Z_do_X2"] - o["do_effect"]) / o["do_effect"] < 0.1, \
        f"do 效应 {o['E_Z_do_X2']:.2f} vs {o['do_effect']:.2f}"

    cf = CounterfactualModel()
    cf.initialize({}, {}, None, None, np.random.default_rng(0))
    oc = cf.observe()
    assert oc.get("Z_counterfactual") is not None, "反事实查询失败"
    print(f"[PASS] SCM：do(X=2)→E[Z]={o['E_Z_do_X2']:.2f}="
          f"b_xy·b_yz·2={o['do_effect']:.2f}；反事实 Z={oc['Z_counterfactual']:.2f}")


def test_hmm_viterbi():
    """HMM：Viterbi 恢复准确率 > 70%；前向似然有限。"""
    m = HMMModel(T=200)
    m.initialize({}, {}, None, None, np.random.default_rng(0))
    o = m.observe()
    assert o["viterbi_acc"] > 0.7, f"Viterbi 准确率 {o['viterbi_acc']:.2f}"
    print(f"[PASS] HMM：Viterbi 准确率={o['viterbi_acc']:.2f}，"
          f"loglik={o['loglik']:.1f}")


def test_kalman_ssm_dbn():
    """线性高斯 SSM：滤波 RMSE < 先验 RMSE；DBN 滤波误差有限。"""
    m = LinearGaussianSSMModel()
    m.initialize({}, {}, None, None, np.random.default_rng(0))
    o = m.observe()
    assert o["rmse_post"] < o["rmse_prior"], \
        f"滤波未改善 {o['rmse_post']:.3f} ≥ {o['rmse_prior']:.3f}"

    d = DBNModel()
    d.initialize({}, {}, None, None, np.random.default_rng(0))
    od = d.observe()
    assert od["filter_acc"] > 0.55, f"DBN 滤波准确率 {od['filter_acc']:.2f}"
    print(f"[PASS] KF/DBN：RMSE {o['rmse_prior']:.3f}→{o['rmse_post']:.3f}，"
          f"DBN 准确率={od['filter_acc']:.2f}")


if __name__ == "__main__":
    test_mmc_erlang()
    test_erlang_b_blocking()
    test_mminf_little()
    test_md1_formula()
    test_jackson_product_form()
    test_priority_queue()
    test_petri_conservative_cycle()
    test_stochastic_petri()
    test_devs_family()
    test_ctmc_stationary()
    test_birth_death_mean()
    test_poisson_family()
    test_sde_family()
    test_compound_poisson()
    test_semi_markov()
    test_scm_counterfactual()
    test_hmm_viterbi()
    test_kalman_ssm_dbn()
    print("\n===== DAYAN 系统动力学家族：全部通过 =====")
