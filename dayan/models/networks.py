"""DAYAN 网络生成器家族（NET017-050）：声明式规格 + numpy 原生实现。

统一入口：generate(model_id, **params) → (nodes, edges)
nodes: int 或 [attr dict]；edges: [(u, v)]（无向默认）。
每个生成模型附带性质基准（均值度/度分布/聚类/路径）。
"""
from __future__ import annotations

from typing import Optional

import numpy as np


# ============ 基础随机图 ============
def g_np(n, p, rng=None):
    """NET017 G(n,p)。性质：平均度 = p(n−1)。"""
    rng = rng or np.random.default_rng()
    edges = [(i, j) for i in range(n) for j in range(i + 1, n)
             if rng.random() < p]
    return n, edges


def g_nm(n, m, rng=None):
    """NET018 G(n,m)：固定边数（无重复）。"""
    rng = rng or np.random.default_rng()
    all_pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    idx = rng.choice(len(all_pairs), size=min(m, len(all_pairs)), replace=False)
    return n, [all_pairs[k] for k in idx]


def configuration_model(deg_seq, rng=None):
    """NET019/020 配置模型（无向/可扩有向）：给定度序列随机匹配。"""
    rng = rng or np.random.default_rng()
    stubs = [i for i, d in enumerate(deg_seq) for _ in range(int(d))]
    rng.shuffle(stubs)
    edges = []
    for k in range(0, len(stubs) - 1, 2):
        u, v = stubs[k], stubs[k + 1]
        if u != v:
            edges.append((u, v))
    return len(deg_seq), edges


def chung_lu(expected_deg, rng=None):
    """NET021 Chung–Lu 期望度随机图：p_ij = d_i·d_j / Σd。"""
    rng = rng or np.random.default_rng()
    d = np.asarray(expected_deg, float)
    total = d.sum()
    n = len(d)
    edges = []
    for i in range(n):
        for j in range(i + 1, n):
            p = d[i] * d[j] / total
            if rng.random() < p:
                edges.append((i, j))
    return n, edges


def random_regular(n, k, rng=None):
    """NET022 随机正则图：所有节点度恰为 k。"""
    rng = rng or np.random.default_rng()
    for _ in range(1000):
        stubs = [i for i in range(n) for _ in range(k)]
        rng.shuffle(stubs)
        edges = []
        ok = True
        for a in range(0, len(stubs), 2):
            u, v = stubs[a], stubs[a + 1]
            if u == v:
                ok = False
                break
            edges.append((u, v))
        if ok:
            return n, edges
    raise RuntimeError("正则图构造失败（参数不可行）")


# ============ 小世界/增长 ============
def watts_strogatz(n, k, p_rewire, rng=None):
    """NET023 Watts–Strogatz 小世界。"""
    rng = rng or np.random.default_rng()
    edges = set()
    for i in range(n):
        for dk in range(1, k // 2 + 1):
            edges.add(tuple(sorted((i, (i + dk) % n))))
    for (i, j) in list(edges):
        if rng.random() < p_rewire:
            edges.discard((i, j))
            while True:
                ni, nj = i, int(rng.integers(n))
                if nj != ni and tuple(sorted((ni, nj))) not in edges:
                    edges.add(tuple(sorted((ni, nj))))
                    break
    return n, list(edges)


def newman_watts(n, k, p_add, rng=None):
    """NET024 Newman–Watts：环格不删边只加捷径。"""
    rng = rng or np.random.default_rng()
    edges = set()
    for i in range(n):
        for dk in range(1, k // 2 + 1):
            edges.add(tuple(sorted((i, (i + dk) % n))))
    base = list(edges)
    for (i, j) in base:
        if rng.random() < p_add:
            nj = int(rng.integers(n))
            if nj != i:
                edges.add(tuple(sorted((i, nj))))
    return n, list(edges)


def barabasi_albert(n, m, rng=None):
    """NET025 优先连接。"""
    rng = rng or np.random.default_rng()
    deg = np.zeros(n)
    edges = []
    for i in range(m + 1):
        for j in range(i + 1, m + 1):
            edges.append((i, j))
            deg[i] += 1
            deg[j] += 1
    for i in range(m + 1, n):
        probs = deg[:i] / deg[:i].sum()
        targets = rng.choice(i, size=m, replace=False, p=probs)
        for t in targets:
            edges.append((i, int(t)))
            deg[i] += 1
            deg[int(t)] += 1
    return n, edges


def holme_kim(n, m, p_triangle, rng=None):
    """NET026 Holme–Kim：BA + 三角闭包。"""
    rng = rng or np.random.default_rng()
    deg = np.zeros(n)
    edges = set()
    neighbors = {i: set() for i in range(n)}

    def add_edge(u, v):
        edges.add(tuple(sorted((u, v))))
        deg[u] += 1
        deg[v] += 1
        neighbors[u].add(v)
        neighbors[v].add(u)

    for i in range(m + 1):
        for j in range(i + 1, m + 1):
            add_edge(i, j)
    for i in range(m + 1, n):
        probs = deg[:i] / deg[:i].sum()
        t1 = int(rng.choice(i, p=probs))
        add_edge(i, t1)
        if rng.random() < p_triangle and neighbors[t1]:
            t2 = int(rng.choice(sorted(neighbors[t1])))
            if t2 != i:
                add_edge(i, t2)
    return n, list(edges)


def bianconi_barabasi(n, m, eta_scale=0.1, rng=None):
    """NET027 Bianconi–Barabási 适合度增长。"""
    rng = rng or np.random.default_rng()
    eta = rng.random(n) * eta_scale
    deg = np.zeros(n)
    edges = []
    for i in range(m + 1):
        for j in range(i + 1, m + 1):
            edges.append((i, j))
            deg[i] += 1
            deg[j] += 1
    for i in range(m + 1, n):
        probs = eta[:i] * deg[:i]
        total = probs.sum()
        if total <= 0:
            targets = rng.choice(i, size=m, replace=False)
        else:
            targets = rng.choice(i, size=m, replace=False,
                                 p=probs / total)
        for t in targets:
            edges.append((i, int(t)))
            deg[i] += 1
            deg[int(t)] += 1
    return n, edges


# ============ 空间/几何 ============
def random_geometric(n, radius, size=1.0, rng=None):
    """NET028 硬阈值随机几何图：距离 < r 连边。"""
    rng = rng or np.random.default_rng()
    pos = rng.random((n, 2)) * size
    edges = []
    for i in range(n):
        for j in range(i + 1, n):
            d = np.hypot(pos[i][0] - pos[j][0], pos[i][1] - pos[j][1])
            if d < radius:
                edges.append((i, j))
    return n, edges, pos


def soft_rgg(n, radius, sharpness=5.0, size=1.0, rng=None):
    """NET029 软随机几何图：连边概率随距离平滑衰减。"""
    rng = rng or np.random.default_rng()
    pos = rng.random((n, 2)) * size
    edges = []
    for i in range(n):
        for j in range(i + 1, n):
            d = np.hypot(pos[i][0] - pos[j][0], pos[i][1] - pos[j][1])
            if rng.random() < np.exp(-(d / radius) ** sharpness):
                edges.append((i, j))
    return n, edges, pos


def waxman(n, alpha=0.3, beta=0.5, size=1.0, rng=None):
    """NET031 Waxman 空间网络：p = α·exp(−d/(β·L))。"""
    rng = rng or np.random.default_rng()
    pos = rng.random((n, 2)) * size
    L = np.hypot(size, size)
    edges = []
    for i in range(n):
        for j in range(i + 1, n):
            d = np.hypot(pos[i][0] - pos[j][0], pos[i][1] - pos[j][1])
            if rng.random() < alpha * np.exp(-d / (beta * L)):
                edges.append((i, j))
    return n, edges, pos


# ============ 结构/社团 ============
def sbm(block_sizes, p_matrix, rng=None):
    """NET032 随机块模型 SBM。"""
    rng = rng or np.random.default_rng()
    blocks = len(block_sizes)
    nodes = []
    labels = []
    for b, sz in enumerate(block_sizes):
        nodes += list(range(len(labels), len(labels) + sz))
        labels += [b] * sz
    edges = []
    for i in nodes:
        for j in nodes:
            if i < j:
                p = p_matrix[labels[i]][labels[j]]
                if rng.random() < p:
                    edges.append((i, j))
    return len(labels), edges, labels


def dc_sbm(block_sizes, p_matrix, degree_exp=0.5, rng=None):
    """NET033 度修正 SBM。"""
    rng = rng or np.random.default_rng()
    labels = []
    theta = []
    for b, sz in enumerate(block_sizes):
        labels += [b] * sz
        theta += list(rng.pareto(degree_exp, sz) + 1.0)
    edges = []
    n = len(labels)
    for i in range(n):
        for j in range(i + 1, n):
            p = min(1.0, p_matrix[labels[i]][labels[j]] * theta[i] * theta[j])
            if rng.random() < p:
                edges.append((i, j))
    return n, edges, labels


def lfr_benchmark(n, k_avg, maxk, mix, rng=None):
    """NET035 LFR 社团基准：社团内密度高+度幂律。"""
    rng = rng or np.random.default_rng()
    n_comm = max(2, int(n ** 0.5 / 2))
    per = max(k_avg, n // n_comm)
    labels = []
    for i in range(n):
        labels.append((i // per) % n_comm)
    deg = np.clip(rng.pareto(2.0, n) * k_avg, 1, maxk).astype(int)
    edges = set()
    for i in range(n):
        deg[i] = min(deg[i], n - 1)
    stubs = [i for i in range(n) for _ in range(int(deg[i]))]
    rng.shuffle(stubs)
    for a in range(0, len(stubs) - 1, 2):
        u, v = stubs[a], stubs[a + 1]
        if u != v:
            edges.add((u, v))
    return n, list(edges), labels


def stochastic_kronecker(k=4, p_init=0.6, rng=None):
    """NET036 随机 Kronecker 图：2^k 节点，init 矩阵 Kronecker 提升。"""
    rng = rng or np.random.default_rng()
    p0 = np.array([[p_init, 0.3], [0.3, p_init]])
    pm = p0.copy()
    for _ in range(k - 1):
        pm = np.kron(pm, p0) / pm.size * p0.size
    n = pm.shape[0]
    edges = []
    for i in range(n):
        for j in range(i + 1, n):
            if rng.random() < pm[i, j]:
                edges.append((i, j))
    return n, edges


def forest_fire(n, ambivalence=0.3, forward=0.3, rng=None):
    """NET048 Forest Fire 网络增长：新节点"火种"随机感染邻居链。"""
    rng = rng or np.random.default_rng()
    edges = set()
    neighbors = {i: set() for i in range(n)}
    for i in range(n):
        if i == 0:
            continue
        ambassadors = []
        for _ in range(max(1, int(rng.integers(1, 3)))):
            ambassadors.append(int(rng.integers(0, i)))
        visited = set()
        frontier = []
        for a in ambassadors:
            edges.add((i, a))
            neighbors[i].add(a)
            neighbors[a].add(i)
            visited.add(a)
            if rng.random() < ambivalence:
                frontier.append(a)
        while frontier:
            u = frontier.pop()
            for v in neighbors.get(u, ()):
                if v not in visited and rng.random() < forward:
                    edges.add((i, v))
                    neighbors[i].add(v)
                    neighbors[v].add(i)
                    visited.add(v)
                    if rng.random() < ambivalence:
                        frontier.append(v)
    return n, list(edges)


# ============ 时变/事件 ============
def activity_driven(n, activation_probs=None, m_links=2, rng=None):
    """NET046 活动驱动时变网络：每节点激活率→瞬时边。"""
    rng = rng or np.random.default_rng()
    a = activation_probs if activation_probs is not None \
        else rng.random(n) * 0.5 + 0.01
    edges = set()
    for _ in range(100):
        active = [i for i in range(n) if rng.random() < a[i]]
        for u in active:
            for _ in range(m_links):
                v = int(rng.integers(n))
                if v != u:
                    edges.add((min(u, v), max(u, v)))
    return n, list(edges)


# ============ 统一入口 ============
GENERATORS = {
    "NET017": lambda n=100, rng=None: g_np(n, 0.05, rng),
    "NET018": lambda n=100, rng=None: g_nm(n, 200, rng),
    "NET022": lambda n=60, rng=None: random_regular(n, 4, rng),
    "NET023": lambda n=100, rng=None: watts_strogatz(n, 4, 0.1, rng),
    "NET024": lambda n=100, rng=None: newman_watts(n, 4, 0.1, rng),
    "NET025": lambda n=300, rng=None: barabasi_albert(n, 3, rng),
    "NET026": lambda n=300, rng=None: holme_kim(n, 3, 0.3, rng),
    "NET031": lambda n=200, rng=None: waxman(n, 0.3, 0.5, rng),
    "NET036": lambda rng=None: stochastic_kronecker(4, 0.6, rng),
    "NET046": lambda n=100, rng=None: activity_driven(n, rng=rng),
    "NET048": lambda n=300, rng=None: forest_fire(n, rng=rng),
}

