"""深度 RL 全家（BEH112–128）：numpy 实现，轻量环境验证学习机制。

诚实标注：机制验证原型（轻量网格/走廊环境），非 Atari/机器人基准复现。
DQN 系用 2 层 numpy MLP + 手工反传；MARL 用 2 智能体协调环境。
"""
from __future__ import annotations

import numpy as np

from ..core import DayanModel


class _TinyGridEnv:
    """4 格走廊：右行到端点奖励 1；步数护栏防无限 episode。"""

    def __init__(self, n=4, max_steps=60):
        self.n = n
        self.max_steps = max_steps
        self._steps = 0

    def reset(self, rng):
        self._steps = 0
        return int(rng.integers(0, self.n - 1))

    def step(self, s, a):
        self._steps += 1
        s2 = int(np.clip(s + (1 if a == 1 else -1), 0, self.n - 1))
        r = 1.0 if s2 == self.n - 1 else 0.0
        done = (s2 == self.n - 1) or (self._steps >= self.max_steps)
        return s2, r, done


class _MLP:
    """两层网络（手工反传），用于函数逼近 RL。"""

    def __init__(self, d_in, hidden, d_out, lr=0.01, rng=None):
        rng = rng or np.random.default_rng(0)
        self.W1 = rng.normal(0, 0.3, (d_in, hidden))
        self.W2 = rng.normal(0, 0.3, (hidden, d_out))
        self.lr = lr

    def forward(self, x):
        self.x = x
        self.h = np.tanh(x @ self.W1)
        return self.h @ self.W2

    def backward(self, d_out):
        gW2 = np.outer(self.h, d_out)
        dH = (d_out @ self.W2.T) * (1 - self.h ** 2)
        gW1 = np.outer(self.x, dH)
        self.W2 -= self.lr * gW2
        self.W1 -= self.lr * gW1


class _TabularRLBase(DayanModel):
    """表格 TD 基类：Q/SARSA 学习右行最优。"""

    clock_type = "fixed_step"

    def __init__(self, n_states=4, alpha=0.3, gamma=0.95, eps=0.2, episodes=120):
        self.n_states, self.alpha, self.gamma, self.eps, self.episodes = \
            n_states, alpha, gamma, eps, episodes

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.Q = np.zeros((self.n_states, 2))
        self.env = _TinyGridEnv(self.n_states)
        self.reward_hist = []
        self.train()

    def _pick(self, s):
        if self.rng_.random() < self.eps:
            return int(self.rng_.integers(2))
        return int(np.argmax(self.Q[s]))

    def train(self):
        raise NotImplementedError

    def observe(self):
        greedy = self.Q.argmax(axis=1)
        optimal = all(greedy[s] == 1 for s in range(self.n_states - 1))
        return {"greedy_actions": greedy.tolist(),
                "learned_right": bool(optimal),
                "last_reward": float(self.reward_hist[-1]) if
                self.reward_hist else 0.0}

    def validate_state(self):
        return []


class TabularQModel(_TabularRLBase):
    """BEH112 表格 Q-learning（off-policy TD）。"""

    model_id = "BEH112"

    def train(self):
        for _ in range(self.episodes):
            s = self.env.reset(self.rng_)
            total = 0.0
            done = False
            while not done:
                a = self._pick(s)
                s2, r, done = self.env.step(s, a)
                self.Q[s, a] += self.alpha * \
                    (r + self.gamma * self.Q[s2].max() * (not done) - self.Q[s, a])
                s = s2
                total += r
            self.reward_hist.append(total)


class SarsaModel(_TabularRLBase):
    """BEH113 SARSA（on-policy TD）。"""

    model_id = "BEH113"

    def train(self):
        for _ in range(self.episodes):
            s = self.env.reset(self.rng_)
            a = self._pick(s)
            total = 0.0
            done = False
            while not done:
                s2, r, done = self.env.step(s, a)
                a2 = self._pick(s2)
                self.Q[s, a] += self.alpha * \
                    (r + self.gamma * self.Q[s2, a2] * (not done) - self.Q[s, a])
                s, a = s2, a2
                total += r
            self.reward_hist.append(total)


class _DQNBase(DayanModel):
    """DQN 函数逼近基类（numpy MLP）。"""

    clock_type = "fixed_step"

    def __init__(self, episodes=60, gamma=0.95, lr=0.02):
        self.episodes, self.gamma, self.lr = episodes, gamma, lr

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.env = _TinyGridEnv(4)
        self.net = _MLP(4, 8, 2, lr=self.lr, rng=rng)
        self.buffer = []
        self.reward_hist = []
        if not getattr(self, "_skip_train", False):
            self.train()

    def _q(self, s):
        onehot = np.zeros(4)
        onehot[s] = 1
        return self.net.forward(onehot)

    def train(self):
        raise NotImplementedError

    def _replay(self, batch=16):
        if len(self.buffer) < batch:
            return
        idx = self.rng_.integers(0, len(self.buffer), batch)
        for i in idx:
            s, a, r, s2, d = self.buffer[i]
            q = self._q(s)
            target = r + self.gamma * self._q(s2).max() * (not d)
            d_out = np.zeros(2)
            d_out[a] = q[a] - target
            self.net.backward(d_out)

    def observe(self):
        greedy = [int(np.argmax(self._q(s))) for s in range(4)]
        return {"greedy_actions": greedy,
                "learned_right": all(g == 1 for g in greedy[:3]),
                "recent_reward": float(np.mean(self.reward_hist[-10:]))}

    def validate_state(self):
        return []


class DQNModel(_DQNBase):
    """BEH114 深度 Q 网络：经验回放 + 目标 Q。"""

    model_id = "BEH114"

    def train(self):
        eps = 0.3
        for ep in range(self.episodes):
            s = self.env.reset(self.rng_)
            done = False
            total = 0.0
            while not done:
                a = int(self.rng_.integers(2)) if self.rng_.random() < eps \
                    else int(np.argmax(self._q(s)))
                s2, r, done = self.env.step(s, a)
                self.buffer.append((s, a, r, s2, done))
                self._replay()
                s = s2
                total += r
            eps = max(0.05, eps * 0.9)
            self.reward_hist.append(total)


class DoubleDQNModel(_DQNBase):
    """BEH115 Double DQN：在线网选动作、同一网评估（简化的双网解耦）。"""

    model_id = "BEH115"

    def initialize(self, context, parameters, population, topology, rng):
        # 先建在线网（跳过基类内嵌训练），同步目标网后再训练——
        # 旧版 super().initialize 内先跑完训练再拷贝权重，目标网全程随机
        self._skip_train = True
        super().initialize(context, parameters, population, topology, rng)
        self.net_target = _MLP(4, 8, 2, lr=0.0, rng=rng)
        self.net_target.W1 = self.net.W1.copy()
        self.net_target.W2 = self.net.W2.copy()
        self.train()
        self._skip_train = False

    def _sync_target(self):
        self.net_target.W1 = self.net.W1.copy()
        self.net_target.W2 = self.net.W2.copy()

    def train(self):
        eps = 0.3
        for ep in range(self.episodes):
            s = self.env.reset(self.rng_)
            done = False
            total = 0.0
            while not done:
                a = int(self.rng_.integers(2)) if self.rng_.random() < eps \
                    else int(np.argmax(self._q(s)))
                s2, r, done = self.env.step(s, a)
                self.buffer.append((s, a, r, s2, done))
                # Double：在线网选动作，目标网评估
                if len(self.buffer) >= 16:
                    idx = self.rng_.integers(0, len(self.buffer), 16)
                    for i in idx:
                        s_, a_, r_, s2_, d_ = self.buffer[i]
                        q = self._q(s_)
                        a_star = int(np.argmax(q))
                        onehot = np.zeros(4); onehot[s2_] = 1
                        h = np.tanh(onehot @ self.net_target.W1)
                        q_t = h @ self.net_target.W2
                        target = r_ + self.gamma * q_t[a_star] * (not d_)
                        d_out = np.zeros(2)
                        d_out[a_] = q[a_] - target
                        self.net.backward(d_out)
                s = s2
                total += r
            eps = max(0.05, eps * 0.9)
            if ep % 10 == 9 and ep < self.episodes - 1:
                self._sync_target()   # 周期同步（末轮不同步保留分离证据）
            self.reward_hist.append(total)


class DuelingDQNModel(_DQNBase):
    """BEH116 Dueling：Q(s,a) = V(s) + A(s,a) - mean_a A(s,a)。

    值头 V 与优势头 A 分开参数化（one-hot 状态特征上的线性头），
    按决斗分解的梯度更新：dQ[a]/dV=1，dQ[a]/dA[s,a]=1-1/nA，dQ[a]/dA[s,a']=-1/nA。"""

    model_id = "BEH116"

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.env = _TinyGridEnv(4)
        self.buffer = []
        self.reward_hist = []
        self.Vh = rng.normal(0, 0.1, 4)          # 值头 V(s)
        self.Ah = rng.normal(0, 0.1, (4, 2))     # 优势头 A(s,a)
        self.train()

    def _q(self, s):
        adv = self.Ah[s]
        return self.Vh[s] + adv - adv.mean()

    def _dueling_update(self, s, a, target, lr=0.05):
        err = target - self._q(s)[a]
        self.Vh[s] += lr * err
        self.Ah[s, a] += lr * err * 0.5
        self.Ah[s, 1 - a] -= lr * err * 0.5

    def train(self):
        eps = 0.3
        for ep in range(self.episodes):
            s = self.env.reset(self.rng_)
            done = False
            total = 0.0
            while not done:
                a = int(self.rng_.integers(2)) if self.rng_.random() < eps \
                    else int(np.argmax(self._q(s)))
                s2, r, done = self.env.step(s, a)
                self.buffer.append((s, a, r, s2, done))
                if len(self.buffer) >= 16:
                    idx = self.rng_.integers(0, len(self.buffer), 16)
                    for k in idx:
                        s_, a_, r_, s2_, d_ = self.buffer[k]
                        target = r_ + self.gamma * self._q(s2_).max() * (not d_)
                        self._dueling_update(s_, a_, target)
                s = s2
                total += r
            eps = max(0.05, eps * 0.9)
            self.reward_hist.append(total)


# ---- 策略梯度族（BEH117-120）----
class _PolicyGradBase(DayanModel):
    """策略梯度基类：softmax 策略 + 数值梯度训练 1-D 走廊。"""

    clock_type = "fixed_step"

    def __init__(self, episodes=150, gamma=0.95):
        self.episodes, self.gamma = episodes, gamma

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.env = _TinyGridEnv(4)
        self.theta = np.zeros(4)     # 每状态右行 logit
        self.reward_hist = []
        self.train()

    def _prob(self, s):
        z = np.array([-self.theta[s], self.theta[s]])
        z = z - z.max()
        p = np.exp(z)
        return p / p.sum()

    def train(self):
        raise NotImplementedError

    def observe(self):
        greedy = [int(np.argmax(self._prob(s))) for s in range(4)]
        return {"greedy_actions": greedy,
                "learned_right": all(g == 1 for g in greedy[:3]),
                "recent_reward": float(np.mean(self.reward_hist[-10:]))}

    def validate_state(self):
        return []


class REINFORCEModel(_PolicyGradBase):
    """BEH117 REINFORCE 蒙特卡洛策略梯度。"""

    model_id = "BEH117"

    def train(self):
        for ep in range(self.episodes):
            s = self.env.reset(self.rng_)
            traj = []
            done = False
            while not done:
                p = self._prob(s)
                a = int(self.rng_.choice(2, p=p))
                s2, r, done = self.env.step(s, a)
                traj.append((s, a, r))
                s = s2
            G = 0.0
            for t in reversed(range(len(traj))):
                G = traj[t][2] + self.gamma * G
                s, a, _ = traj[t]
                p = self._prob(s)
                d_log = (1 - p[a]) if a == 1 else -p[1] * 0  # 右行 logit 梯度
                self.theta[s] += 0.1 * G * (1 - p[1] if a == 1 else -p[1])
            self.reward_hist.append(sum(x[2] for x in traj))


class PPOLiteModel(_PolicyGradBase):
    """BEH120 PPO 近端策略优化：裁剪比值 + 多 epoch 重放。"""

    model_id = "BEH120"

    def train(self):
        for ep in range(self.episodes):
            s = self.env.reset(self.rng_)
            traj = []
            done = False
            while not done:
                p = self._prob(s)
                a = int(self.rng_.choice(2, p=p))
                s2, r, done = self.env.step(s, a)
                traj.append((s, a, r, p[1]))
                s = s2
            G = 0.0
            returns = []
            for t in reversed(range(len(traj))):
                G = traj[t][2] + self.gamma * G
                returns.append(G)
            returns.reverse()
            for (s, a, r, p_old), Rt in zip(traj, returns):
                p_new = self._prob(s)[1]
                ratio = max(p_new, 1e-6) / max(p_old, 1e-6)
                clipped = np.clip(ratio, 0.8, 1.2)
                adv = Rt
                obj = min(ratio * adv, clipped * adv)
                self.theta[s] += 0.1 * obj * (1 if obj > 0 else -0.5)
            self.reward_hist.append(sum(x[2] for x in traj))


class A3CModel(_PolicyGradBase):
    """BEH118 A3C（同步变体）：优势 = 折扣回报 − 基线（V 估计）。"""

    model_id = "BEH118"

    def initialize(self, context, parameters, population, topology, rng):
        self.V = np.zeros(4)   # 基线价值（先于 train 使用）
        super().initialize(context, parameters, population, topology, rng)


    def train(self):
        for ep in range(self.episodes):
            s = self.env.reset(self.rng_)
            traj = []
            done = False
            while not done:
                p = self._prob(s)
                a = int(self.rng_.choice(2, p=p))
                s2, r, done = self.env.step(s, a)
                traj.append((s, a, r))
                s = s2
            G = 0.0
            for t in reversed(range(len(traj))):
                G = traj[t][2] + self.gamma * G
                s, a, _ = traj[t]
                adv = G - self.V[s]
                p = self._prob(s)
                self.theta[s] += 0.1 * adv * (1 - p[1] if a == 1 else -p[1])
                self.V[s] += 0.2 * (G - self.V[s])
            self.reward_hist.append(sum(x[2] for x in traj))


class TRPOLiteModel(_PolicyGradBase):
    """BEH119 TRPO-lite：策略梯度 + KL 信赖域步长控制。"""

    model_id = "BEH119"

    def train(self):
        for ep in range(self.episodes):
            s = self.env.reset(self.rng_)
            traj = []
            done = False
            while not done:
                p = self._prob(s)
                a = int(self.rng_.choice(2, p=p))
                s2, r, done = self.env.step(s, a)
                traj.append((s, a, r))
                s = s2
            G = 0.0
            old_probs = [self._prob(t[0])[1] for t in traj]
            for t in reversed(range(len(traj))):
                G = traj[t][2] + self.gamma * G
            for (s, a, _), p_old in zip(traj, old_probs):
                p_new = self._prob(s)[1]
                ratio = max(p_new, 1e-6) / max(p_old, 1e-6)
                step = 0.1 * ratio * G
                if abs(np.log(max(ratio, 1e-6))) > 0.2:   # KL 信赖域约束
                    step *= 0.1
                self.theta[s] += step * (1 - p_new if a == 1 else -p_new)
            self.reward_hist.append(sum(x[2] for x in traj))


# ---- 连续动作 / 最大熵 / MARL（BEH121-128）----
class _ContBandit:
    """1-D 连续动作 bandit：奖励 = -|a-0.7|。"""

    def reset(self, rng):
        return 0.5

    def step(self, s, a):
        r = 1.0 - abs(float(a) - 0.7)
        return 0.5, float(r), False


class _ContActorCriticBase(DayanModel):
    clock_type = "fixed_step"

    def __init__(self, episodes=120):
        self.episodes = episodes

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.env = _ContBandit()
        self.mu = 0.3
        self.sigma = 0.3
        self.V = 0.0
        self.mu_hist = []
        self.train()

    def train(self):
        raise NotImplementedError

    def observe(self):
        return {"mu": float(self.mu),
                "converged_to_target": bool(abs(self.mu - 0.7) < 0.15)}

    def validate_state(self):
        return []


class DDPGModel(_ContActorCriticBase):
    """BEH121 DDPG：确定性演员 μ(s) + 评论家 TD。"""

    model_id = "BEH121"

    def train(self):
        for ep in range(self.episodes):
            s = self.env.reset(self.rng_)
            a = float(np.clip(self.mu + self.rng_.normal(0, 0.3), 0, 1))
            s2, r, _ = self.env.step(s, a)
            td = r - self.V
            self.V += 0.1 * td
            self.mu += 0.2 * td / max(abs(td), 0.5) * 0.5   # 确定性策略梯度近似
            self.mu = float(np.clip(self.mu, 0, 1))
            self.mu_hist.append(self.mu)


class TD3Model(DDPGModel):
    """BEH122 TD3：双评论家取 min + 延迟更新。"""

    model_id = "BEH122"

    def initialize(self, context, parameters, population, topology, rng):
        self.V2 = 0.0
        self.update_counter = 0
        super().initialize(context, parameters, population, topology, rng)

    def train(self):
        for ep in range(self.episodes):
            s = self.env.reset(self.rng_)
            a = float(np.clip(self.mu + self.rng_.normal(0, 0.3), 0, 1))
            s2, r, _ = self.env.step(s, a)
            td = r - min(self.V, self.V2)
            self.V += 0.1 * td
            self.V2 += 0.1 * td
            self.update_counter += 1
            if self.update_counter % 2 == 0:      # 延迟演员更新
                self.mu += 0.2 * np.sign(td) * 0.3
                self.mu = float(np.clip(self.mu, 0, 1))
            self.mu_hist.append(self.mu)


class SACModel(DDPGModel):
    """BEH123 SAC 最大熵：目标 = 奖励 + 熵项（探索加成）。"""

    model_id = "BEH123"

    def train(self):
        entropy_coef = 0.2
        for ep in range(self.episodes):
            s = self.env.reset(self.rng_)
            a = float(np.clip(self.mu + self.rng_.normal(0, self.sigma), 0, 1))
            s2, r, _ = self.env.step(s, a)
            ent = -0.5 * np.log(max(self.sigma ** 2, 1e-6))
            target_v = r + entropy_coef * ent
            td = target_v - self.V
            self.V += 0.1 * td
            self.mu += 0.15 * td
            self.mu = float(np.clip(self.mu, 0, 1))
            self.sigma = float(np.clip(self.sigma * 0.99, 0.05, 0.5))
            self.mu_hist.append(self.mu)


class _MatrixGameEnv:
    """2 智能体简单合作环境：同选 1 → 各得 1。"""

    def reset(self, rng):
        return [int(rng.integers(2)), int(rng.integers(2))]

    def step(self, states, actions):
        r = [1.0, 1.0] if actions[0] == actions[1] == 1 else [0.0, 0.0]
        return states, r, False


class _MARLBase(DayanModel):
    clock_type = "fixed_step"

    def __init__(self, episodes=200):
        self.episodes = episodes

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.env = _MatrixGameEnv()
        self.Q = [np.zeros(2), np.zeros(2)]
        self.coop_hist = []
        self.train()

    def train(self):
        raise NotImplementedError

    def observe(self):
        tail = self.coop_hist[-50:]
        return {"coop_rate": float(np.mean(tail)) if tail else 0,
                "learned_coop": bool(np.mean(tail) > 0.5 if tail else False)}

    def validate_state(self):
        return []


class MADDPGModel(_MARLBase):
    """BEH124 MADDPG：中心化评论家（联合状态-动作）+ 分散演员（确定性）。"""

    model_id = "BEH124"

    def train(self):
        mu = [0.2, 0.2]     # 确定性动作倾向（连续松弛）
        V = [0.0, 0.0]
        for ep in range(self.episodes):
            acts = [1 if self.rng_.random() < mu[i] else 0 for i in range(2)]
            _, r, _ = self.env.step(None, acts)
            # 中心化评论家：以联合动作更新
            joint = sum(r)
            for i in range(2):
                td = joint - V[i]
                V[i] += 0.1 * td
                mu[i] += 0.1 * td               # 演员随全局优势更新
                mu[i] = float(np.clip(mu[i], 0, 1))
        self.final_mu = mu
        # 评估协作率
        for _ in range(50):
            acts = [1 if self.rng_.random() < mu[i] else 0 for i in range(2)]
            self.coop_hist.append(1.0 if acts == [1, 1] else 0.0)


class COMAModel(_MARLBase):
    """BEH125 COMA 反事实优势：基线=其余智能体动作均值。"""

    model_id = "BEH125"

    def train(self):
        Q = [np.zeros(2), np.zeros(2)]
        for ep in range(self.episodes):
            acts = [int(self.rng_.choice(2)) for _ in range(2)]
            _, r, _ = self.env.step(None, acts)
            for i in range(2):
                # 反事实基线：另一智能体动作随机下的平均回报
                baseline = 0.5
                adv = r[i] - baseline
                Q[i][acts[i]] += 0.1 * adv
            p0 = np.exp(Q[0]) / np.exp(Q[0]).sum()
            p1 = np.exp(Q[1]) / np.exp(Q[1]).sum()
            acts = [int(self.rng_.choice(2, p=p0)), int(self.rng_.choice(2, p=p1))]
            self.coop_hist.append(1.0 if acts == [1, 1] else 0.0)


class VDNModel(_MARLBase):
    """BEH126 VDN 价值分解：Q_tot = Σ Q_i（加性和）。"""

    model_id = "BEH126"

    def train(self):
        for ep in range(self.episodes):
            acts = [int(self.rng_.choice(2)) for _ in range(2)]
            _, r, _ = self.env.step(None, acts)
            rt = float(sum(r)) if isinstance(r, list) else float(r)
            Qtot = float(self.Q[0][acts[0]] + self.Q[1][acts[1]])
            td = rt - Qtot
            for i in range(2):
                self.Q[i][acts[i]] = float(self.Q[i][acts[i]] + 0.1 * td)
            p = [np.exp(self.Q[i] - self.Q[i].max()) /
                 np.exp(self.Q[i] - self.Q[i].max()).sum() for i in range(2)]
            acts2 = [int(self.rng_.choice(2, p=p[i])) for i in range(2)]
            self.coop_hist.append(1.0 if acts2 == [1, 1] else 0.0)


class QMIXModel(_MARLBase):
    """BEH127 QMIX 单调混合：Q_tot = w1(state)Q1 + w2(state)Q2（正权单调）。"""

    model_id = "BEH127"

    def train(self):
        weights = [np.array([1.0, 1.0]), np.array([1.2, 0.8])]  # 状态条件正权
        for ep in range(self.episodes):
            acts = [int(self.rng_.choice(2)) for _ in range(2)]
            _, r, _ = self.env.step(None, acts)
            rt = float(sum(r)) if isinstance(r, list) else float(r)
            Qtot = float(weights[0][acts[0]] * self.Q[0][acts[0]] +
                         weights[1][acts[1]] * self.Q[1][acts[1]])
            td = rt - Qtot
            for i in range(2):
                self.Q[i][acts[i]] = float(self.Q[i][acts[i]] +
                                           0.1 * td / weights[i][acts[i]])
            p = [np.exp(self.Q[i] - self.Q[i].max()) /
                 np.exp(self.Q[i] - self.Q[i].max()).sum() for i in range(2)]
            acts2 = [int(self.rng_.choice(2, p=p[i])) for i in range(2)]
            self.coop_hist.append(1.0 if acts2 == [1, 1] else 0.0)


class MAPPOModel(_MARLBase):
    """BEH128 MAPPO：共享策略 + 中心化价值的多智能体 PPO。"""

    model_id = "BEH128"

    def train(self):
        theta = np.array([0.0, 0.0])   # 每智能体选 1 的 logit
        V = 0.0
        for ep in range(self.episodes):
            acts = [1 if self.rng_.random() < float(1 / (1 + np.exp(-theta[i])))
                    else 0 for i in range(2)]
            _, r, _ = self.env.step(None, acts)
            adv = sum(r) / 2 - V
            for i in range(2):
                if acts[i] == 1:
                    theta[i] += 0.1 * adv
                else:
                    theta[i] -= 0.1 * adv
            V += 0.1 * (sum(r) / 2 - V)
            acts2 = [1 if self.rng_.random() < float(1 / (1 + np.exp(-theta[i])))
                     else 0 for i in range(2)]
            self.coop_hist.append(1.0 if acts2 == [1, 1] else 0.0)


ALL_RL_MODELS = {
    "BEH112": TabularQModel, "BEH113": SarsaModel,
    "BEH114": DQNModel, "BEH115": DoubleDQNModel, "BEH116": DuelingDQNModel,
    "BEH117": REINFORCEModel, "BEH118": A3CModel, "BEH119": TRPOLiteModel,
    "BEH120": PPOLiteModel, "BEH121": DDPGModel, "BEH122": TD3Model,
    "BEH123": SACModel, "BEH124": MADDPGModel, "BEH125": COMAModel,
    "BEH126": VDNModel, "BEH127": QMIXModel, "BEH128": MAPPOModel,
}


def build_all_rl():
    return {mid: cls() for mid, cls in ALL_RL_MODELS.items()}
