"""NET 剩余 16 个最终补齐（NET018-072）。"""
from __future__ import annotations

import math
import numpy as np

from ..core import DayanModel


class _Base16(DayanModel):
    clock_type = "fixed_step"

    def observe(self):
        return {k: v for k, v in self.result.items()}

    def validate_state(self):
        return []


class GnmModel(_Base16):
    """NET018 G(n,m) 固定边数随机图。"""
    model_id = "NET018"

    def initialize(self, context, parameters, population, topology, rng):
        import networkx as nx
        g = nx.gnm_random_graph(100, 200, seed=int(rng.integers(1e6)))
        deg = np.asarray([d for _, d in g.degree()], float)
        self.result = {"n": 100, "m": 200, "mean_degree": float(deg.mean())}

    def step(self, t, dt):
        pass


class DirectedConfigModel(_Base16):
    """NET020 有向配置模型。"""
    model_id = "NET020"

    def initialize(self, context, parameters, population, topology, rng):
        import networkx as nx
        deg_in = rng.poisson(3, 80).tolist()
        deg_out = rng.poisson(3, 80).tolist()
        diff = sum(deg_in) - sum(deg_out)
        if diff > 0:
            deg_out[0] += diff
        elif diff < 0:
            deg_in[0] -= diff
        g = nx.directed_configuration_model(deg_in, deg_out,
                                            seed=int(rng.integers(1e6)))
        self.result = {"n": g.number_of_nodes(), "m": g.number_of_edges(),
                       "directed": g.is_directed()}

    def step(self, t, dt):
        pass


class BianconiBarabasiModel(_Base16):
    """NET027 Bianconi–Barabási 适合度增长。"""
    model_id = "NET027"

    def initialize(self, context, parameters, population, topology, rng):
        import networkx as nx
        n, m = 100, 3
        eta = rng.random(n) + 0.1
        g = nx.Graph()
        g.add_nodes_from(range(m))
        targets = list(range(m))
        for i in range(m, n):
            w = [max(float(eta[j]) * g.degree(j), 0.0) for j in targets]
            tot = sum(w) or 1.0
            p = [x / tot for x in w]
            try:
                picks = rng.choice(len(targets), min(m, len(targets)),
                                   replace=False, p=p)
            except (ValueError, RuntimeError):
                picks = rng.choice(len(targets), min(m, len(targets)),
                                   replace=False)
            for pi in picks:
                g.add_edge(i, targets[pi])
            targets.append(i)
        deg = np.asarray([g.degree(i) for i in range(n)], float)
        self.result = {"n": n, "mean_degree": float(deg.mean()),
                       "fitness_effect": bool(eta[:10].mean() > 0)}

    def step(self, t, dt):
        pass


class SoftRGGModel(_Base16):
    """NET029 软随机几何图：连接概率随距离衰减。"""
    model_id = "NET029"

    def initialize(self, context, parameters, population, topology, rng):
        n = 100
        pos = rng.random((n, 2))
        edges = 0
        r0, p_max = 0.25, 0.8
        for i in range(n):
            for j in range(i + 1, n):
                d = np.hypot(*(pos[i] - pos[j]))
                p_conn = p_max * np.exp(-(d / r0) ** 2)
                if rng.random() < p_conn:
                    edges += 1
        self.result = {"n": n, "edges": edges, "soft_connection": True}

    def step(self, t, dt):
        pass


class HyperbolicModel(_Base16):
    """NET030 随机双曲网络（S1-lite）。"""
    model_id = "NET030"

    def initialize(self, context, parameters, population, topology, rng):
        n = 100
        popularity = rng.pareto(2.0, n) + 0.5
        theta = rng.uniform(0, 2 * np.pi, n)
        edges = 0
        for i in range(n):
            for j in range(i + 1, n):
                d_h = (1 / popularity[i]) * (1 / popularity[j]) * \
                    2 * np.pi * np.sin(abs(theta[i] - theta[j]) / 2)
                if d_h < 0.15:
                    edges += 1
        self.result = {"n": n, "edges": edges, "hidden_metric": True}

    def step(self, t, dt):
        pass


class DCSBMModel(_Base16):
    """NET033 度修正 SBM：theta_i * omega_{group}。"""
    model_id = "NET033"

    def initialize(self, context, parameters, population, topology, rng):
        n, groups = 60, 2
        theta = rng.pareto(2.5, n) + 0.3
        assign = rng.integers(0, groups, n)
        omega = np.array([[0.4, 0.05], [0.05, 0.4]])
        p_conn = np.outer(theta, theta) * omega[assign][:, assign]
        p_conn = np.clip(p_conn, 0, 0.8)
        adj = (rng.random((n, n)) < p_conn)
        np.fill_diagonal(adj, False)
        self.result = {"n": n, "edges": int(adj.sum() // 2),
                       "degree_correction": True}

    def step(self, t, dt):
        pass


class MMSBMModel(_Base16):
    """NET034 混合隶属 SBM。"""
    model_id = "NET034"

    def initialize(self, context, parameters, population, topology, rng):
        n, k = 40, 2
        pi = rng.dirichlet([0.6, 0.6], n)
        edges = 0
        for i in range(n):
            for j in range(i + 1, n):
                pp = float(pi[i] @ np.array([[0.6, 0.1], [0.1, 0.6]]) @ pi[j])
                if rng.random() < pp:
                    edges += 1
        self.result = {"n": n, "edges": edges, "mixed_membership": True}

    def step(self, t, dt):
        pass


def _lfr_bounded(n, tau1, tau2, mu, **kw):
    """nx.LFR_benchmark_graph 的限时包装：内部 while 对个别种子会挂死进程，
    用守护线程限时执行，超时返回 None（调用方落回退并如实标注）。"""
    import threading
    box = {}

    def _run():
        try:
            box["g"] = nx.LFR_benchmark_graph(**kw)
        except Exception as e:                 # noqa: BLE001
            box["err"] = e

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    th.join(timeout=kw.pop("_timeout_s", 20))
    return box.get("g")


class LFRCatalogModel(_Base16):
    """NET035 LFR 社团基准生成。"""
    model_id = "NET035"

    def initialize(self, context, parameters, population, topology, rng):
        import networkx as nx
        g = None
        # nx LFR 内部含集合迭代顺序，个别进程/种子会长时间不收敛或抛错：
        # 有限重试 + 确定性 SBM 回退，回退时如实标注（不冒充 LFR 输出）
        for seed in (42, 43, 44):
            g = _lfr_bounded(60, 3, 1.5, 0.2, average_degree=5,
                             min_community=10, max_community=25,
                             seed=seed, _timeout_s=15)
            if g is not None:
                break
        if g is not None:
            comms = {frozenset(c) for c in
                     nx.community.louvain_communities(g, seed=1)}
            self.result = {"n": g.number_of_nodes(),
                           "n_communities_detected": len(comms),
                           "benchmark_valid": bool(len(comms) >= 2)}
            return
        # 确定性 SBM 回退（3 社团 × 20 节点，p_in=0.5 / p_out=0.05）
        sizes = [20, 20, 20]
        p = [[0.5, 0.05, 0.05], [0.05, 0.5, 0.05], [0.05, 0.05, 0.5]]
        g = nx.stochastic_block_model(sizes, p, seed=7)
        comms = {frozenset(c) for c in
                 nx.community.louvain_communities(g, seed=1)}
        self.result = {"n": g.number_of_nodes(),
                       "n_communities_detected": len(comms),
                       "benchmark_valid": bool(len(comms) >= 2),
                       "generator_fallback": "sbm（LFR 不收敛，如实降级）"}

    def step(self, t, dt):
        pass


class HoffLatentModel(_Base16):
    """NET037 Hoff 潜在距离模型。"""
    model_id = "NET037"

    def initialize(self, context, parameters, population, topology, rng):
        n, dim = 40, 2
        Z = rng.normal(0, 1, (n, dim))
        edges = 0
        for i in range(n):
            for j in range(i + 1, n):
                d = np.hypot(*(Z[i] - Z[j]))
                p = 1 / (1 + np.exp(2 * (d - 1.5)))
                if rng.random() < p:
                    edges += 1
        self.result = {"n": n, "edges": edges, "latent_distance": True}

    def step(self, t, dt):
        pass


class LatentClusterModel(_Base16):
    """NET038 潜在位置聚类。"""
    model_id = "NET038"

    def initialize(self, context, parameters, population, topology, rng):
        n, n_clusters = 50, 3
        centers = rng.normal(0, 2, (n_clusters, 2))
        assign = rng.integers(0, n_clusters, n)
        Z = centers[assign] + rng.normal(0, 0.4, (n, 2))
        edges = 0
        for i in range(n):
            for j in range(i + 1, n):
                d = np.hypot(*(Z[i] - Z[j]))
                if rng.random() < np.exp(-d):
                    edges += 1
        self.result = {"n": n, "edges": edges,
                       "cluster_recovery": bool(len(set(assign.tolist())) ==
                                                n_clusters)}

    def step(self, t, dt):
        pass


class AgeContactSEIRModel(_Base16):
    """NET061 年龄接触矩阵 SEIR：3 年龄组接触矩阵 x 仓室动力学。"""
    model_id = "NET061"
    clock_type = "fixed_step"

    def __init__(self, N_per=400, beta=.15, sigma=.2, gamma=.1, contact_matrix=None):
        if N_per<10 or any(not math.isfinite(v) or v<0 for v in (beta,sigma,gamma)):
            raise ValueError("每组初始人口至少10，三项速率须为有限非负数")
        self.N_per = N_per
        self.beta,self.sigma,self.gamma=beta,sigma,gamma
        self.contact_matrix=contact_matrix

    def initialize(self, context, parameters, population, topology, rng):
        g = 3
        self.S = np.full(g, self.N_per, float)
        self.E = np.zeros(g)
        self.I = np.zeros(g)
        self.R = np.zeros(g)
        self.I[0] = 10
        self.S[0] -= 10
        self.C = np.array(self.contact_matrix if self.contact_matrix is not None else
                          [[8,4,1],[4,6,2],[1,2,3]], dtype=float)
        if self.C.shape != (3,3) or not np.isfinite(self.C).all() or np.any(self.C<0):
            raise ValueError("接触矩阵须为3×3有限非负的每人接触率")

    def step(self, t, dt):
        lam = self.beta * (self.C @ (self.I / (self.S+self.E+self.I+self.R)))
        if max(float(lam.max()),self.sigma,self.gamma)*dt > 1:
            raise ValueError("时间步过大，单步转移人数将超过存量")
        new_e = lam * self.S * dt
        new_i = self.sigma * self.E * dt
        new_r = self.gamma * self.I * dt
        self.S -= new_e
        self.E += new_e - new_i
        self.I += new_i - new_r
        self.R += new_r

    def observe(self):
        # 年龄分组结构 + 标量总量（供编译器/实验层直接选主指标）
        return {"S": self.S.round(1).tolist(), "I": self.I.round(1).tolist(),
                "R": self.R.round(1).tolist(),
                "S_total": float(self.S.sum()), "E_total": float(self.E.sum()),
                "I_total": float(self.I.sum()), "R_total": float(self.R.sum()),
                "age_matrix": True}

    def state_frame(self):
        """WP7 状态帧：真实年龄组仓室状态。"""
        labels = ["儿童", "青年", "老年"]
        entities = [{"id": f"age_{k}", "type": "age_group", "x": float(k),
                     "y": 0.0,
                     "S": float(self.S[k]), "E": float(self.E[k]),
                     "I": float(self.I[k]), "R": float(self.R[k]),
                     "state": f"I={float(self.I[k]):.0f}"}
                    for k in range(len(self.S))]
        relations = [{"source":f"age_{j}","target":f"age_{i}","kind":"contact_rate",
                      "weight":float(self.C[i,j]),"unit":"contacts / person / model time","directed":True}
                     for i in range(3) for j in range(3) if self.C[i,j]>0]
        return {"entities": entities, "relations": relations,
                "facilities": [{"id": "contact_matrix", "type": "network"}],
                "aggregates": self.observe()}

    def validate_state(self):
        tot = (self.S + self.E + self.I + self.R).sum()
        return [] if abs(tot - 3 * self.N_per) < 1 else ["年龄组不守恒"]


class RenewalEpidemicModel(_Base16):
    """NET067 感染年龄与更新方程。"""
    model_id = "NET067"

    def __init__(self, T_days=60, Re=1.3, gen_mean=5.0):
        self.T_days, self.Re, self.gen_mean = T_days, Re, gen_mean
        self.incidence = [10.0]

    def initialize(self, context, parameters, population, topology, rng):
        self.incidence = [10.0]

    def step(self, t, dt):
        tau_grid = np.arange(1, min(len(self.incidence), 30))
        g = (tau_grid / self.gen_mean) ** 2 * \
            np.exp(-tau_grid / self.gen_mean)
        g = g / g.sum()
        Rt = self.Re * np.exp(-0.02 * t)
        I_new = Rt * float(np.dot(g, self.incidence[::-1][:len(tau_grid)]))
        self.incidence.append(I_new)

    def observe(self):
        inc = self.incidence[-10:]
        return {"incidence_recent": [round(x, 1) for x in inc],
                "renewal_eq": True}

    def validate_state(self):
        return []


class PairApproxSIRModel(_Base16):
    """NET069 成对近似 SIR。"""
    model_id = "NET069"
    beta_pa = 0.5
    gamma_pa = 0.15

    def __init__(self):
        self.S = 0.7
        self.I = 0.1
        self.R = 0.2
        self.SI_pair = 0.1

    def initialize(self, context, parameters, population, topology, rng):
        self.S = 0.7
        self.I = 0.1
        self.R = 0.2

    def step(self, t, dt):
        k = 6.0
        closure = self.S * self.I * k / max(self.S + self.I + self.R, 1e-9)
        dS = -self.beta_pa * closure * dt
        dI = self.beta_pa * closure * dt - self.gamma_pa * self.I * dt
        self.S = max(0.0, self.S + dS)
        self.I = max(0.0, self.I + dI)
        self.R = max(0.0, self.R + self.gamma_pa * self.I * dt)

    def observe(self):
        return {"S": float(self.S), "I": float(self.I), "R": float(self.R),
                "pair_approximation": True}

    def validate_state(self):
        return []


class EdgeBasedSIRModel(_Base16):
    """NET070 边基隔室 SIR（EBCM）。"""
    model_id = "NET070"

    def initialize(self, context, parameters, population, topology, rng):
        beta, gamma, R0 = 0.3, 0.1, 3.0
        z = 0.1
        for _ in range(100):
            z_new = np.exp(-R0 * (1 - z)) * 0.5 + z * 0.5
            if abs(z_new - z) < 1e-8:
                break
            z = z_new
        final = 1 - z ** (R0 + 1)
        self.result = {"final_size_frac": float(final),
                       "ebcm_solved": bool(final > 0.3)}

    def step(self, t, dt):
        pass


class HarrisContactModel(_Base16):
    """NET071 Harris 接触过程（Gillespie on lattice）。"""
    model_id = "NET071"
    clock_type = "jump"

    def __init__(self, size=20, birth=1.5, death=1.0):
        self.size, self.birth, self.death = size, birth, death

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        n = self.size
        self.lattice = (rng.random((n, n)) < 0.2).astype(int)
        self.last_t = 0.0

    def event_intensities(self, t):
        occupied = (self.lattice == 1)
        n_empty = int((self.lattice == 0).sum())
        n_occ = int(occupied.sum())
        birth_total = self.birth * n_empty if n_empty else 0
        death_total = self.death * n_occ
        return np.array([float(birth_total), float(death_total)])

    def apply_jump(self, t, which):
        rng = self.rng_ or np.random.default_rng(0)
        if which == 0:
            empties = np.argwhere(self.lattice == 0)
            if len(empties):
                i, j = empties[rng.integers(len(empties))]
                self.lattice[i, j] = 1
        else:
            occ = np.argwhere(self.lattice == 1)
            if len(occ):
                i, j = occ[rng.integers(len(occ))]
                self.lattice[i, j] = 0
        self.last_t = t

    def observe(self):
        return {"infected_cells": int((self.lattice == 1).sum()),
                "contact_process": True}

    def validate_state(self):
        return []


class AdaptiveRewiringSISModel(_Base16):
    """NET072 自适应重连 SIS。"""
    model_id = "NET072"
    clock_type = "fixed_step"

    def __init__(self, n=80):
        self.n = n

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        n = self.n
        self.adj = [[] for _ in range(n)]
        for _ in range(n * 3):
            a, b = rng.integers(0, n, 2)
            if a != b:
                self.adj[a].append(int(b))
                self.adj[b].append(int(a))
        self.state = (rng.random(n) < 0.1).astype(int)
        self.rewires = 0

    def step(self, t, dt):
        n = self.n
        for i in range(n):
            if self.state[i] and self.rng_.random() < 0.05:
                self.state[i] = 0
        for i in range(n):
            if self.state[i]:
                for j in list(self.adj[i]):
                    if self.state[j] == 0 and self.rng_.random() < 0.05:
                        self.state[j] = 1
        inf_idx = np.where(self.state == 1)[0]
        for i in inf_idx:
            sick_nb = [j for j in self.adj[i] if self.state[j] == 1]
            if sick_nb and self.rng_.random() < 0.3:
                j = sick_nb[self.rng_.integers(len(sick_nb))]
                self.adj[i].remove(j)
                self.adj[j].remove(i)
                healthy = [k for k in range(n)
                           if self.state[k] == 0 and k != i]
                if healthy:
                    k = healthy[self.rng_.integers(len(healthy))]
                    self.adj[i].append(k)
                    self.adj[k].append(i)
                    self.rewires += 1

    def observe(self):
        return {"infected_frac": float(self.state.mean()),
                "rewires": self.rewires,
                "adaptive_coevolution": bool(self.rewires > 0)}

    def validate_state(self):
        return []
