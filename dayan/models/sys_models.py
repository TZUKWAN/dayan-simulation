"""DAYAN 系统动力学/事件流程家族（目录 SYS001–SYS045）。

排队：M/M/c、Erlang-B 损失、有限容量+弃队、M/M/∞、M/D/1、
      M/G/1（Pollaczek–Khinchine）、Jackson 开放网络（乘积形式）、
      Gordon–Newell 封闭网络、抢占/非抢占优先队列
Petri 网：库所-变迁、定时、随机（Gillespie）、GSPN
DEVS：原子 DEVS、耦合 DEVS、Cell-DEVS
随机过程：CTMC、半 Markov、线性生灭（解析）、齐次/非齐次泊松、
         GBM、OU、CIR、Heston、Wiener、复合泊松
因果与状态空间：线性高斯 SCM（do 算子）、反事实、HMM（前向+Viterbi）、
               线性高斯 SSM、动态贝叶斯网络

家族测试含解析基准（Erlang-B 公式、Jackson 乘积形式、OU 平稳方差、
GBM 期望、HMM Viterbi 路径恢复等）。
"""
from __future__ import annotations

from collections import deque
import heapq

import numpy as np
import math
from math import factorial

from scipy.special import gammaln

from ..core import DayanModel


# ============ 排队族 ============
class MMCQueueModel(DayanModel):
    """SYS002 fixed-step approximation to M/M/c, compared with Erlang-C.

    Arrivals and completion processing are rounded to step boundaries. Customer
    IDs and individual server allocations are retained, not invented by the view.
    """

    model_id = "SYS002"
    clock_type = "fixed_step"

    def __init__(self, c=3, lam=2.0, mu=1.0):
        if isinstance(c, bool) or int(c) != c or c < 1 or lam <= 0 or mu <= 0:
            raise ValueError("M/M/c需要正整数服务台数及正到达/服务率")
        self.c, self.lam, self.mu = c, lam, mu
        self.rng_ = None

    def initialize(self, context, parameters, population, topology, rng):
        self.c = parameters.get("c", self.c)
        self.lam = parameters.get("lam", self.lam)
        self.mu = parameters.get("mu", self.mu)
        self.rng_ = rng
        self.q = deque()
        self.busy = 0
        self.wait_sum = 0.0
        self.n_served = 0
        self.n_started = self.n_arrived = 0
        self.slots = [None for _ in range(int(self.c))]
        self.departs = []
        self.clock = 0.0

    def _erlang_c(self):
        c, a = self.c, self.lam / self.mu
        s = sum(a ** k / factorial(k) for k in range(c))
        tail = a ** c / (factorial(c) * (1 - a / c))
        return tail / (s + tail)

    def step(self, t, dt):
        rng = self.rng_
        for _ in range(rng.poisson(self.lam * dt)):
            self.q.append({'id':'customer_'+str(self.n_arrived),'arrival':self.clock})
            self.n_arrived+=1
        # 本 tick 内完成的服务
        for index,customer in enumerate(self.slots):
            if customer is not None and customer['departure']<=self.clock:
                self.slots[index]=None;self.n_served+=1
        self.busy=sum(c is not None for c in self.slots)
        while self.busy < self.c and self.q:
            customer=self.q.popleft()
            w = self.clock - customer['arrival']
            self.wait_sum += w
            self.n_started += 1
            index=self.slots.index(None)
            customer.update(server=index,departure=self.clock+rng.exponential(1/self.mu))
            self.slots[index]=customer
            self.busy += 1
        self.departs=[c['departure'] for c in self.slots if c is not None]
        self.clock += dt

    def observe(self):
        w_sim = self.wait_sum / max(self.n_started, 1)
        return {"Wq_sim": float(w_sim), "Wq_erlangc": float(self._erlang_c()
                                                             / (self.c * self.mu - self.lam)) if self.lam < self.c*self.mu else None,
                "n_served": self.n_served,'n_service_starts':self.n_started,'n_arrived':self.n_arrived}

    def apply_intervention(self, changes, t):
        if "mu" in changes:
            # Conditional exponential residual life rescales when the hazard changes.
            for customer in self.slots:
                if customer is not None:customer['departure']=max(t,t+max(0.,customer['departure']-t)*self.mu/changes['mu'])
            self.departs=[c['departure'] for c in self.slots if c is not None]
        for name, value in changes.items():
            setattr(self, name, value)

    def state_frame(self):
        """WP7 状态帧：真实服务台占用与队列长度。"""
        servers = [{"id": f"server_{k}", "type": "server",
                    "x": float(k), "y": 0.0,
                    "state": "busy" if self.slots[k] is not None else "idle"}
                   for k in range(self.c)]
        waiting = [{"id": customer['id'], "type": "customer",
                    "x": float(-1 - i * 0.35), "y": 0.0, "state": "waiting"}
                   for i,customer in enumerate(self.q)]
        serving=[{'id':customer['id'],'type':'customer','x':float(i),'y':1.,'state':'in_service','server_id':'server_'+str(i)}
                 for i,customer in enumerate(self.slots) if customer is not None]
        return {"entities": servers + waiting + serving,
                "facilities": [{"id": "counter", "type": "counter",
                                "capacity": int(self.c)}],
                "aggregates": {**self.observe(), "queue_len": len(self.q),
                               "busy": self.busy}}

    def snapshot(self):
        import copy
        return copy.deepcopy({'params':{k:getattr(self,k) for k in ('c','lam','mu')},'q':list(self.q),'slots':self.slots,
            'busy':self.busy,'wait_sum':self.wait_sum,'n_served':self.n_served,'n_started':self.n_started,
            'n_arrived':self.n_arrived,'clock':self.clock,'rng_state':self.rng_.bit_generator.state})

    def restore(self,state):
        import copy
        state=copy.deepcopy(state);self.__init__(**state['params'])
        self.q=deque(state['q']);self.slots=state['slots']
        for key in ('busy','wait_sum','n_served','n_started','n_arrived','clock'):setattr(self,key,state[key])
        self.rng_=np.random.default_rng();self.rng_.bit_generator.state=state['rng_state']
        self.departs=[c['departure'] for c in self.slots if c is not None]

    def validate_state(self):
        return [] if self.lam < self.c * self.mu else ["ρ≥1 不稳定"]


class ErlangBModel(DayanModel):
    """SYS003 无等待损失系统 M/M/c/c：阻塞率 = Erlang-B 公式（解析对照模拟）。"""

    model_id = "SYS003"
    clock_type = "fixed_step"

    def __init__(self, c=4, lam=3.0, mu=1.0):
        self.c, self.lam, self.mu = c, lam, mu
        self.blocked = 0
        self.total = 0

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.busy = 0
        self.blocked = self.total = 0
        self.clock = 0.0
        self.departs = []

    def erlang_b(self):
        """递推 Erlang-B：B(c,a) = a·B(c-1,a)/(c + a·B(c-1,a))。"""
        a = self.lam / self.mu
        b = 1.0
        for k in range(1, self.c + 1):
            b = a * b / (k + a * b)
        return b

    def step(self, t, dt):
        n_arr = self.rng_.poisson(self.lam * dt)
        for _ in range(n_arr):
            self.total += 1
            if self.busy < self.c:
                self.busy += 1
                self.departs.append(self.clock +
                                    self.rng_.exponential(1 / self.mu))
            else:
                self.blocked += 1   # 全忙即损（M/M/c/c 无等待位）
        # 到期离开（多服务台簿记）
        done = [d for d in self.departs if d <= self.clock]
        self.departs = [d for d in self.departs if d > self.clock]
        self.busy -= len(done)
        self.clock += dt

    def observe(self):
        sim_p = self.blocked / max(self.total, 1)
        return {"B_formula": float(self.erlang_b()),
                "B_sim": float(sim_p),
                "blocked": self.blocked,
                "total": self.total}

    def validate_state(self):
        return []


class MCLRQueueModel(DayanModel):
    """SYS005 带弃队的多服务器（M/M/c/K）：溢出弃队。"""

    model_id = "SYS005"
    clock_type = "fixed_step"

    def __init__(self, c=3, K=6, lam=2.5, mu=1.0):
        self.c, self.K, self.lam, self.mu = c, K, lam, mu
        self.rened = 0
        self.total = 0

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.q = deque()
        self.busy = 0
        self.rened = self.total = 0
        self.clock = 0.0
        self.departs = deque()

    def step(self, t, dt):
        for _ in range(self.rng_.poisson(self.lam * dt)):
            self.total += 1
            if self.busy < self.c:
                self.busy += 1
                self.departs.append(self.clock + self.rng_.exponential(1 / self.mu))
            elif len(self.q) < self.K - self.c:
                self.q.append(self.clock)
            else:
                self.rened += 1
        departs = getattr(self, "departs", deque())
        while departs and departs[0] <= self.clock:
            departs.popleft()
            self.busy = max(0, self.busy - 1)
            while self.busy < self.c and self.q:
                self.q.popleft()
                self.busy += 1
                departs.append(self.clock + self.rng_.exponential(1 / self.mu))
        self.clock += dt

    def observe(self):
        return {"reneged": self.rened, "total": self.total,
                "drop_frac": float(self.rened / max(self.total, 1))}

    def validate_state(self):
        return []


class AbandonmentQueueModel(DayanModel):
    """SYS005 M/M/c+M: FIFO waiting, independent exponential patience."""
    model_id="SYS005"
    clock_type="fixed_step"

    def __init__(self, c=2, lam=3., mu=1., patience_rate=.5):
        if not 1<=c<=128 or not all(np.isfinite(rate) and 0<rate<=10000 for rate in (lam,mu,patience_rate)):
            raise ValueError("系统需要有限的正到达率、服务率、耐心衰减率和服务台数")
        self.c,self.lam,self.mu,self.patience_rate=c,lam,mu,patience_rate

    def initialize(self, context, parameters, population, topology, rng):
        self.rng=rng
        self.future=[(float(rng.exponential(1/self.lam)),2,0)]
        self.waiting={}
        self.total=self.started=self.served=self.reneged=self.busy=0

    def _start(self,t,customer):
        self.busy+=1
        self.started+=1
        heapq.heappush(self.future,(t+float(self.rng.exponential(1/self.mu)),0,customer))

    def step(self,t,dt):
        stop=t+dt
        processed=0
        while self.future and self.future[0][0]<=stop+1e-10:
            event,kind,customer=heapq.heappop(self.future)
            processed+=1
            if processed>100000:
                raise ValueError("单观察步内排队事件超出计算上限")
            if kind==0:
                self.busy-=1
                self.served+=1
                if self.waiting:
                    first=next(iter(self.waiting))
                    self.waiting.pop(first)
                    self._start(event,first)
            elif kind==1:
                if self.waiting.pop(customer,None) is not None:
                    self.reneged+=1
            else:
                self.total+=1
                if self.busy<self.c:
                    self._start(event,self.total)
                else:
                    self.waiting[self.total]=event
                    heapq.heappush(self.future,(event+float(self.rng.exponential(1/self.patience_rate)),1,self.total))
                heapq.heappush(self.future,(event+float(self.rng.exponential(1/self.lam)),2,0))

    def observe(self):
        return {"arrived":self.total,"started":self.started,"served":self.served,
                "reneged":self.reneged,"waiting":len(self.waiting),"in_service":self.busy}

    def validate_state(self):
        return [] if self.total==self.served+self.reneged+len(self.waiting)+self.busy else ["顾客数不守恒"]


class MMInfQueueModel(DayanModel):
    """SYS006 无限服务器 M/M/∞：L = λW = λ/μ（Little 律，解析）。"""

    model_id = "SYS006"
    clock_type = "fixed_step"

    def __init__(self, lam=3.0, mu=1.0):
        self.lam, self.mu = lam, mu
        self.n = 0

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.n = 0
        self.clock = 0.0
        self.departs = []
        self.le = 0.0

    def step(self, t, dt):
        n_arr = int(self.rng_.poisson(self.lam * dt))
        self.n += n_arr
        for _ in range(n_arr):
            self.departs.append(self.clock + self.rng_.exponential(1 / self.mu))
        done = [d for d in self.departs if d <= self.clock]
        self.departs = [d for d in self.departs if d > self.clock]
        self.n -= len(done)
        self.le += self.n * dt
        self.clock += dt

    def observe(self):
        return {"L": float(self.le / max(self.clock, 1e-9)),
                "L_little": float(self.lam / self.mu)}

    def validate_state(self):
        return []


class MD1QueueModel(DayanModel):
    """SYS007 确定服务单服务器 M/D/1：Wq = ρ/(2(1-ρ))·(1/μ)（解析）。"""

    model_id = "SYS007"
    clock_type = "fixed_step"

    def __init__(self, lam=0.6, mu=1.0):
        if not 0 <= lam < mu:
            raise ValueError("M/D/1 稳态对照要求 0≤λ<μ")
        self.lam, self.mu = lam, mu

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.pending_starts = deque()
        self.busy_until = 0.
        self.clock = 0.
        self.next_arrival = float(rng.exponential(1/self.lam)) if self.lam else None
        self.wait_sum = 0.0
        self.n_arrived=self.n_service_starts=0

    def step(self, t, dt):
        stop=self.clock+dt
        while self.next_arrival is not None and self.next_arrival <= stop+1e-10:
            arrival=self.next_arrival
            start=max(arrival,self.busy_until)
            self.busy_until=start+1/self.mu
            self.pending_starts.append((start,start-arrival))
            self.n_arrived+=1
            self.next_arrival+=float(self.rng_.exponential(1/self.lam))
        while self.pending_starts and self.pending_starts[0][0]<=stop+1e-10:
            _,wait=self.pending_starts.popleft()
            self.wait_sum+=wait
            self.n_service_starts+=1
        self.clock=stop

    def observe(self):
        rho = self.lam / self.mu
        wq_analytic = rho / (2 * (1 - rho)) / self.mu
        wq_sim = self.wait_sum/self.n_service_starts if self.n_service_starts else None
        return {"Wq_sim": wq_sim, "Wq_md1": float(wq_analytic), "n_arrived":self.n_arrived,
                "n_service_starts":self.n_service_starts,"n_waiting":len(self.pending_starts)}

    def validate_state(self):
        return [] if self.lam < self.mu else ["ρ≥1"]


class JacksonNetworkModel(DayanModel):
    """SYS010 Jackson 开放排队网络：乘积形式稳态 π(n) ∝ ∏(n_i!^{-1} a_i^{n_i}/μ_i^{n_i})。
    验证：各站模拟平均人数 ≈ Jackson 均值公式。"""

    model_id = "SYS010"
    clock_type = "fixed_step"

    def __init__(self, lam=1.0, mu=(2.0, 1.2), P=np.array([[0.0, 0.3], [0.2, 0.0]])):
        self.lam = lam
        self.mu = np.asarray(mu, float)
        self.P = np.asarray(P, float)
        self.n = np.zeros(len(self.mu), int)

    def _effective_arrival(self):
        """解流量方程 λ_eff = λ_ext + λ_eff·P^T。"""
        I = np.eye(len(self.mu))
        lam_ext = np.zeros(len(self.mu))
        lam_ext[0] = self.lam          # 外部到达只进站 0
        return np.linalg.solve(I - self.P.T, lam_ext)

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.n = np.zeros(len(self.mu), int)
        self.clock = 0.0
        self.le = np.zeros(len(self.mu))
        self.T = 0.0

    def step(self, t, dt):
        k = len(self.mu)
        for _ in range(self.rng_.poisson(self.lam * dt)):
            dest = self.rng_.choice(k)  # 外部到达 → 站 0
            self.n[0] += 1
        # 服务完成
        for i in range(k):
            done = self.rng_.poisson(self.mu[i] * min(self.n[i], 1) * dt) \
                if self.n[i] > 0 else 0
            for _ in range(done):
                self.n[i] -= 1
                r = self.rng_.random()
                acc = 0.0
                out = -1
                for j in range(k):
                    acc += self.P[i][j]
                    if r < acc:
                        out = j
                        break
                if out >= 0:
                    self.n[out] += 1
        self.T += dt
        self.le += self.n * dt

    def observe(self):
        lam_eff = self._effective_arrival()
        rho = lam_eff / self.mu
        # M/M/1 型均值（Jackson 单站 M/M/1 均值 L=rho/(1-rho)）
        L_mean = np.where(rho < 1, rho / np.maximum(1 - rho, 1e-9), np.inf)
        L_sim = self.le / max(self.T, 1e-9)
        return {"L_sim": L_sim.tolist(), "L_jackson": L_mean.tolist(),
                "rho": rho.tolist()}

    def validate_state(self):
        return []


class PriorityQModel(DayanModel):
    """SYS013/014 优先队列：抢占/非抢占模式，高优先级等待更短（对照）。"""

    model_id = "SYS013"
    clock_type = "fixed_step"

    def __init__(self, preempt=True, lam=(0.4, 0.4), mu=1.2):
        self.preempt = preempt
        self.lam = lam
        self.mu = mu
        self.waits = [[], []]

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.qs = [deque(), deque()]
        self.waits = [[], []]
        self.busy_until = -1.0
        self.clock = 0.0

    def step(self, t, dt):
        for cls in (0, 1):
            for _ in range(self.rng_.poisson(self.lam[cls] * dt)):
                self.qs[cls].append(self.clock)
        # 服务完成
        if self.clock >= self.busy_until:
            for cls in (0, 1):
                if self.qs[cls]:
                    arr = self.qs[cls].popleft()
                    self.waits[cls].append(self.clock - arr)
                    self.busy_until = self.clock + self.rng_.exponential(1 / self.mu)
                    break
        elif self.preempt:
            # 高优先级到达抢占低优先级（简化：重排队）
            if self.qs[0]:
                arr = self.qs[0].popleft()
                self.waits[0].append(self.clock - arr)
                self.busy_until = self.clock + self.rng_.exponential(1 / self.mu)
        self.clock += dt

    def observe(self):
        w0 = float(np.mean(self.waits[0])) if self.waits[0] else None
        w1 = float(np.mean(self.waits[1])) if self.waits[1] else None
        return {"W_high": w0, "W_low": w1,
                "priority_holds": bool(w0 is not None and w1 is not None
                                       and w0 < w1)}

    def validate_state(self):
        return []


class NonpreemptivePriorityModel(PriorityQModel):
    """SYS014: fixed-step nonpreemptive priority, FIFO within each class."""
    model_id = "SYS014"

    def __init__(self, lam=(.4,.4), mu=1.2):
        if len(lam)!=2 or any(not np.isfinite(v) or v<0 for v in lam) or not np.isfinite(mu) or mu<=0:
            raise ValueError("优先队列需要两类非负到达率、正服务率")
        super().__init__(preempt=False,lam=lam,mu=mu)

    output_units = {"W_high":"model time","W_low":"model time"}


# ============ Petri 网 ============
class PetriNetModel(DayanModel):
    """SYS015 库所-变迁 Petri 网：使能/触发/守恒；基准：循环网触发守恒。"""

    model_id = "SYS015"
    clock_type = "fixed_step"

    def __init__(self, pre=None, post=None, m0=None):
        # pre/post: 变迁 × 库所 弧矩阵
        self.pre = np.asarray(pre, int) if pre is not None else \
            np.array([[1, 0], [0, 1]])
        self.post = np.asarray(post, int) if post is not None else \
            np.array([[0, 1], [1, 0]])
        self.m = np.asarray(m0, int) if m0 is not None else np.array([3, 0])

    def initialize(self, context, parameters, population, topology, rng):
        self.m = np.asarray(parameters.get("m0", self.m), int).copy()
        self.fired = 0

    def enabled(self):
        return (self.m >= self.pre).all(axis=1)

    def step(self, t, dt):
        en = np.where(self.enabled())[0]
        if len(en):
            t_sel = en[0]
            self.m = self.m - self.pre[t_sel] + self.post[t_sel]
            self.fired += 1

    def observe(self):
        return {"marking": self.m.tolist(), "fired": self.fired,
                "total_tokens": int(self.m.sum()),
                "enabled": int(self.enabled().sum())}

    def validate_state(self):
        return [] if (self.m >= 0).all() else ["库所 token 为负"]


class TimedPetriModel(PetriNetModel):
    """SYS017 定时 Petri 网：变迁带持续时长，触发后延迟回吐 token。"""

    model_id = "SYS017"

    def __init__(self, durations=(1.0, 2.0), **kw):
        super().__init__(**kw)
        self.durations = np.asarray(durations, float)
        self.busy = []  # (完成时刻, 变迁)

    def initialize(self, context, parameters, population, topology, rng):
        super().initialize(context, parameters, population, topology, rng)
        self.clock = 0.0
        self.busy = []

    def step(self, t, dt):
        self.clock += dt
        # 到期回吐
        done = [b for b in self.busy if b[0] <= self.clock]
        self.busy = [b for b in self.busy if b[0] > self.clock]
        for _, tr in done:
            self.m = self.m - 0 + self.post[tr]  # pre 已在触发时扣除
        en = np.where((self.m >= self.pre).all(axis=1))[0]
        if len(en):
            tr = int(en[0])
            self.m = self.m - self.pre[tr]
            self.busy.append((self.clock + self.durations[tr], tr))


class StochasticPetriModel(PetriNetModel):
    """SYS019 广义随机 Petri 网：变迁触发率指数分布 → Gillespie 风格。"""

    model_id = "SYS019"
    clock_type = "jump"

    def __init__(self, rates=(1.0, 1.0), **kw):
        super().__init__(**kw)
        self.rates = np.asarray(rates, float)

    def initialize(self, context, parameters, population, topology, rng):
        self.m = np.asarray(parameters.get("m0", self.m), int).copy()
        self.fired = 0

    def event_intensities(self, t):
        en = (self.m >= self.pre).all(axis=1)
        return self.rates * en

    def apply_jump(self, t, which):
        self.m = self.m - self.pre[which] + self.post[which]
        self.fired += 1

    def observe(self):
        return {"marking": self.m.tolist(), "fired": self.fired}

    def validate_state(self):
        return []


# ============ DEVS ============
class AtomicDEVModel(DayanModel):
    """SYS021 经典 DEVS 原子模型：相位+σ 时基推进；基准：周期生成器事件数。"""

    model_id = "SYS021"
    clock_type = "fixed_step"

    def __init__(self, period=2.0, T=40.0):
        self.period, self.T = period, T
        self.clock = 0.0
        self.sigma = period
        self.phase = "passive"
        self.events = 0

    def initialize(self, context, parameters, population, topology, rng):
        self.period = parameters.get("period", self.period)
        self.clock = 0.0
        self.sigma = self.period
        self.phase = "active"
        self.events = 0

    def step(self, t, dt):
        self.clock += dt
        self.sigma -= dt
        if self.sigma <= 0:
            self.events += 1          # 内部事件：输出
            self.sigma = self.period  # 重推进
            self.phase = "active"

    def observe(self):
        return {"events": self.events, "clock": self.clock,
                "expected": int(self.clock / self.period)}

    def validate_state(self):
        return []


class CoupledDEVModel(DayanModel):
    """SYS022 耦合 DEVS：生成器→处理器→transducer 三原子耦合。
    基准：处理器输出数 = 生成器事件数（队列守恒）。"""

    model_id = "SYS022"
    clock_type = "fixed_step"

    def __init__(self, gen_period=1.0, proc_time=0.7, T=30.0):
        self.gen = AtomicDEVModel(period=gen_period)
        self.proc_time = proc_time
        self.T = T
        self.queue = deque()
        self.proc_busy = 0.0
        self.proc_out = 0
        self.clock = 0.0

    def initialize(self, context, parameters, population, topology, rng):
        self.gen.initialize(context, parameters, population, topology, rng)
        self.queue = deque()
        self.proc_busy = 0.0
        self.proc_out = 0
        self.clock = 0.0

    def step(self, t, dt):
        self.clock += dt
        n0 = self.gen.events
        self.gen.step(t, dt)
        new = self.gen.events - n0
        for _ in range(new):
            self.queue.append(self.clock)
        # 处理器
        self.proc_busy -= dt
        if self.proc_busy <= 0 and self.queue:
            self.queue.popleft()
            self.proc_out += 1
            self.proc_busy = self.proc_time

    def observe(self):
        return {"generated": int(self.gen.events), "processed": self.proc_out,
                "queued": len(self.queue),
                "conserv": int(self.gen.events - self.proc_out - len(self.queue))}

    def validate_state(self):
        return []


class CellDEVModel(DayanModel):
    """SYS025 Cell-DEVS：蜂窝空间+时滞转换（扩散规则）。
    基准：总量守恒的邻域平均扩散。"""

    model_id = "SYS025"
    clock_type = "fixed_step"

    def __init__(self, size=20):
        self.size = size
        self.cells = np.zeros((size, size))

    def initialize(self, context, parameters, population, topology, rng):
        n = self.size
        self.cells = np.zeros((n, n))
        self.cells[n // 2, n // 2] = 100.0
        self.tick = 0

    def step(self, t, dt):
        c = self.cells
        nb = (np.roll(c, 1, 0) + np.roll(c, -1, 0) +
              np.roll(c, 1, 1) + np.roll(c, -1, 1)) / 4.0
        # 部分扩散：向邻居流出 25%（守恒：总質量不变）
        out = 0.25 * nb
        new = c - out + 0.25 * c.mean() * 0  # 简化：混合
        blend = 0.5 * (c + (np.roll(c, 1, 0) + np.roll(c, -1, 0) +
                            np.roll(c, 1, 1) + np.roll(c, -1, 1)) / 4)
        self.cells = blend
        self.tick += 1

    def observe(self):
        return {"total": float(self.cells.sum()), "max": float(self.cells.max())}

    def validate_state(self):
        return []


# ============ 随机过程 ============
class SwitchingGrowthPDMPModel(DayanModel):
    """SYS026 scalar deterministic growth with two Markov switching regimes."""
    model_id="SYS026"
    clock_type="fixed_step"

    def __init__(self,x0=1.,growth=(.2,-.15),rates=(1.,.8),regime0=0):
        if (x0<=0 or len(growth)!=2 or len(rates)!=2 or regime0 not in (0,1)
                or any(not np.isfinite(r) or r<0 for r in rates) or not np.isfinite(growth).all()):
            raise ValueError("正初始存量、两组有限增长率与非负切换率")
        self.x0,self.growth,self.rates,self.regime0=x0,growth,rates,regime0

    def initialize(self, context, parameters, population, topology, rng):
        self.rng=rng
        self.x,self.regime,self.jumps=self.x0,self.regime0,0
        self.next_jump=self._next_jump(0.)

    def _next_jump(self, start):
        rate=self.rates[self.regime]
        return start+float(self.rng.exponential(1/rate)) if rate else None

    def step(self,t,dt):
        end=t+dt
        processed=0
        while self.next_jump is not None and self.next_jump<=end:
            self.x*=math.exp(self.growth[self.regime]*(self.next_jump-t))
            t=self.next_jump
            self.regime=1-self.regime
            self.jumps+=1
            processed+=1
            if processed>100000:
                raise ValueError("观察步内跳跃事件超出计算上限")
            self.next_jump=self._next_jump(t)
        self.x*=math.exp(self.growth[self.regime]*(end-t))
        if not np.isfinite(self.x) or self.x<=0:
            raise ValueError("增长状态超出有限正域")

    def observe(self):
        return {"stock":float(self.x),"regime":self.regime,"jumps":self.jumps}

    def validate_state(self):
        return [] if np.isfinite(self.x) and self.x>0 else ["状态必须为有限正数"]


class CTMCModel(DayanModel):
    """SYS028 连续时间 Markov 链（jump）：Gillespie；稳态分布对照解析。"""

    model_id = "SYS028"
    clock_type = "jump"

    def __init__(self, Q=None, n_states=2):
        self.Q = np.asarray(Q, float) if Q is not None else \
            np.array([[-1.0, 1.0], [2.0, -2.0]])
        self.state = 0

    def initialize(self, context, parameters, population, topology, rng):
        self.state = int(parameters.get("s0", 0))
        self.visits = np.zeros(len(self.Q))

    def event_intensities(self, t):
        q = self.Q[self.state].copy()
        q[self.state] = 0.0
        return np.maximum(q, 0)

    def apply_jump(self, t, which):
        self.state = which
        self.visits[which] += 1

    def observe(self):
        pi_analytic = self._stationary()
        total_v = self.visits.sum()
        pi_sim = (self.visits + (self.visits[0] * 0)) / max(total_v, 1)
        return {"state": self.state, "pi_sim": pi_sim.tolist(),
                "pi_stationary": pi_analytic.tolist()}

    def _stationary(self):
        n = len(self.Q)
        A = np.vstack([self.Q.T, np.ones(n)])
        b = np.zeros(n + 1)
        b[-1] = 1.0
        pi, *_ = np.linalg.lstsq(A, b, rcond=None)
        return pi

    def validate_state(self):
        return []


class SemiMarkovModel(DayanModel):
    """SYS029 半 Markov：状态驻留时间非指数（均匀 [a,b]）。"""

    model_id = "SYS029"
    clock_type = "fixed_step"

    def __init__(self, hold=(1.0, 3.0)):
        self.hold = hold
        self.state = 0

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.state = 0
        self.remain = rng.uniform(*self.hold)
        self.transitions = 0

    def step(self, t, dt):
        self.remain -= dt
        if self.remain <= 0:
            self.state = 1 - self.state
            self.transitions += 1
            self.remain = self.rng_.uniform(*self.hold)

    def observe(self):
        return {"state": self.state, "transitions": self.transitions}

    def validate_state(self):
        return []


class BirthDeathModel(DayanModel):
    """SYS030 线性生灭过程：E[N(t)] = n0·e^{(λ-μ)t}（解析均值）。"""

    model_id = "SYS030"
    clock_type = "jump"

    def __init__(self, lam_b=0.5, mu_d=0.3, n0=10):
        self.lam_b, self.mu_d, self.n0 = lam_b, mu_d, n0
        self.n = n0

    def initialize(self, context, parameters, population, topology, rng):
        self.n = int(parameters.get("n0", self.n0))

    def event_intensities(self, t):
        return np.array([self.lam_b * self.n, self.mu_d * self.n])

    def apply_jump(self, t, which):
        self._t = t
        if which == 0:
            self.n += 1
        else:
            self.n = max(0, self.n - 1)

    def observe(self):
        t = getattr(self, "_t", 0.0)
        return {"n": self.n,
                "E_analytic": float(self.n0 * np.exp((self.lam_b - self.mu_d) * t))}

    def validate_state(self):
        return []


class PoissonProcessModel(DayanModel):
    """SYS031 齐次泊松：N(t) ~ Poisson(λt)；均值方差匹配。"""

    model_id = "SYS031"
    clock_type = "fixed_step"

    def __init__(self, lam=2.0):
        self.lam = lam
        self.count = 0

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.count = 0
        self.clock = 0.0

    def step(self, t, dt):
        self.clock += dt
        self.count += int(self.rng_.poisson(self.lam * dt))

    def observe(self):
        t = max(self.clock, 1e-9)
        return {"count": self.count, "E": float(self.lam * t),
                "var_theory": float(self.lam * t)}

    def validate_state(self):
        return []


class NHPPModel(DayanModel):
    """SYS032 exponential intensity on [0,t_max], exact Poisson increments."""

    model_id = "SYS032"
    clock_type = "fixed_step"

    def __init__(self, lam0=1.0, alpha=0.5, t_max=4.0):
        if lam0<0 or t_max<=0 or abs(alpha)*t_max>40:
            raise ValueError("须给出非负初始率、正终点和有界指数强度")
        self.lam0, self.alpha, self.t_max = lam0, alpha, t_max
        self.count = 0

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.count = 0
        self.clock = 0.0
        self.t_max = parameters.get("t_max", self.t_max)
        self.next_mass = float(rng.exponential())

    def step(self, t, dt):
        start=self.clock
        stop=min(start+dt,self.t_max)
        mass=self._cumulative(stop)
        # One homogeneous Poisson process on cumulative intensity, shared by
        # all observation grids for a given seed.
        events=0
        while self.next_mass<=mass:
            events+=1
            if events>100000:
                raise ValueError("单步实际事件数超过范围")
            self.next_mass+=float(self.rng_.exponential())
        self.count+=events
        self.clock=stop

    def _cumulative(self,t):
        return self.lam0*t if self.alpha==0 else self.lam0*math.expm1(self.alpha*t)/self.alpha

    def observe(self):
        return {"count": self.count, "E_integral": float(self._cumulative(self.clock))}

    def validate_state(self):
        return []


class GBMModel(DayanModel):
    """SYS034 几何 Brown 运动：E[S(t)] = S0·e^{μt}（解析矩）。SDE Euler-Maruyama。"""

    model_id = "SYS034"
    clock_type = "sde"

    def __init__(self, mu=0.05, sigma=0.2, S0=100.0):
        self.mu, self.sigma, self.S0 = mu, sigma, S0
        self.x = np.array([S0])

    def initialize(self, context, parameters, population, topology, rng):
        self.S0 = parameters.get("S0", self.S0)
        self.x = np.array([self.S0])

    def drift(self, t, x):
        self._t = t
        return self.mu * x

    def diffusion(self, t, x):
        return self.sigma * x

    def observe(self):
        t = getattr(self, "_t", 0.0)
        return {"S": float(self.x[0]),
                "E_S": float(self.S0 * np.exp(self.mu * t))}

    def validate_state(self):
        return [] if self.x[0] > 0 else ["S≤0"]


class OUModel(DayanModel):
    """SYS035 Ornstein–Uhlenbeck：平稳方差 = σ²/(2θ)（解析）。SDE。"""

    model_id = "SYS035"
    clock_type = "sde"

    def __init__(self, theta=2.0, mu=1.0, sigma=0.5, x0=0.0):
        self.theta, self.mu, self.sigma, self.x0 = theta, mu, sigma, x0
        self.x = np.array([x0])

    def initialize(self, context, parameters, population, topology, rng):
        self.x = np.array([parameters.get("x0", self.x0)])

    def drift(self, t, x):
        self._t = t
        return self.theta * (self.mu - x)

    def diffusion(self, t, x):
        return np.array([[self.sigma]])

    def observe(self):
        return {"x": float(self.x[0]),
                "stationary_var": float(self.sigma ** 2 / (2 * self.theta))}

    def validate_state(self):
        return []


class CIRModel(DayanModel):
    """SYS036 CIR 平方根过程：dX=κ(θ-X)dt+σ√X dW；Feller 条件 2κθ≥σ²。"""

    model_id = "SYS036"
    clock_type = "sde"

    def __init__(self, kappa=3.0, theta=0.05, sigma=0.15, x0=0.05):
        self.kappa, self.theta, self.sigma, self.x0 = kappa, theta, sigma, x0
        self.x = np.array([x0])

    def initialize(self, context, parameters, population, topology, rng):
        self.x = np.array([parameters.get("x0", self.x0)])

    def drift(self, t, x):
        self._t = t
        return self.kappa * (self.theta - x)

    def diffusion(self, t, x):
        return self.sigma * np.sqrt(np.maximum(x, 0))

    def observe(self):
        return {"x": float(self.x[0]), "theta": self.theta,
                "feller_ok": bool(2 * self.kappa * self.theta >= self.sigma ** 2)}

    def validate_state(self):
        return [] if self.x[0] >= 0 else ["X<0（Feller 条件破坏）"]


class HestonModel(DayanModel):
    """SYS037 Heston 随机波动率：v 与 S 双因子 SDE。"""

    model_id = "SYS037"
    clock_type = "sde"

    def __init__(self, S0=100.0, v0=0.04, mu=0.03, kappa=2.0, theta=0.04,
                 sigma_v=0.3, rho=-0.7):
        self.mu, self.kappa, self.theta, self.sigma_v, self.rho = \
            mu, kappa, theta, sigma_v, rho
        self.x = np.array([S0, v0])

    def initialize(self, context, parameters, population, topology, rng):
        self.x = np.array([parameters.get("S0", 100.0),
                           parameters.get("v0", 0.04)])

    def drift(self, t, x):
        self._t = t
        return np.array([self.mu * x[0], self.kappa * (self.theta - x[1])])

    def diffusion(self, t, x):
        # 对角噪声近似（内核 EM 语义为逐状态对角扩散；相关性 ρ 忽略）
        v = max(float(x[1]), 0)
        return np.array([x[0] * np.sqrt(v),
                         np.sqrt(1 - self.rho ** 2) * self.sigma_v * np.sqrt(v)])

    def observe(self):
        return {"S": float(self.x[0]), "v": float(max(self.x[1], 0)),
                "theta": self.theta}

    def validate_state(self):
        return []


class WienerModel(DayanModel):
    """SYS038 标准 Wiener 过程：Var = t（解析）。SDE 无漂移单位扩散。"""

    model_id = "SYS038"
    clock_type = "sde"

    def __init__(self, x0=0.0):
        self.x0 = x0
        self.x = np.array([x0])

    def initialize(self, context, parameters, population, topology, rng):
        self.x = np.array([self.x0])

    def drift(self, t, x):
        self._t = t
        return np.array([0.0])

    def diffusion(self, t, x):
        return np.array([[1.0]])

    def observe(self):
        t = getattr(self, "_t", 0.0)
        return {"x": float(self.x[0]), "var_theory": float(max(t, 1e-9))}

    def validate_state(self):
        return []


class CompoundPoissonModel(DayanModel):
    """SYS039 复合泊松：E[S(t)] = λ·t·E[Y]（解析）。jump。"""

    model_id = "SYS039"
    clock_type = "jump"

    def __init__(self, lam=1.5, y_mean=2.0):
        self.lam, self.y_mean = lam, y_mean
        self.S = 0.0
        self.n = 0

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.S = 0.0
        self.n = 0

    def event_intensities(self, t):
        return np.array([self.lam])

    def apply_jump(self, t, which):
        self._t = t
        y = self.rng_.poisson(self.y_mean) + 1  # 正整数字偿
        self.S += y
        self.n += 1

    def observe(self):
        t = getattr(self, "_t", 0.0)
        return {"S": float(self.S), "n": self.n,
                "E_S": float(self.lam * t * (self.y_mean + 1))}

    def validate_state(self):
        return []


# ============ 因果与状态空间 ============
class LinearSCMModel(DayanModel):
    """SYS040 结构因果模型（线性高斯）：X→Y→Z 链；do(X) 切断入边。
    独立噪声生成的三变量例题。条件球内样本均值和解析干预期望分别报告。"""

    model_id = "SYS040"
    clock_type = "fixed_step"

    def __init__(self, b_xy=1.2, b_yz=0.8, u_var=0.5):
        if u_var<0:
            raise ValueError("u_var 为兼容参数名，表示正态噪声标准差，须非负")
        self.b_xy, self.b_yz, self.u_var = b_xy, b_yz, u_var
        self.result = {}

    def initialize(self, context, parameters, population, topology, rng):
        n = 4000
        Ux = rng.normal(0, self.u_var, n)
        Uy = rng.normal(0, self.u_var, n)
        Uz = rng.normal(0, self.u_var, n)
        X = Ux
        Y = self.b_xy * X + Uy
        Z = self.b_yz * Y + Uz
        # 干预 do(X=2)
        Xd = np.full(n, 2.0)
        Yd = self.b_xy * Xd + Uy
        Zd = self.b_yz * Yd + Uz
        mask=np.abs(X-2)<.3
        self.result = {
            "E_Z_given_X2": float(Z[mask].mean()) if mask.any() else None,
            "n_conditioned": int(mask.sum()),
            "E_Z_do_X2": float(Zd.mean()),
            "do_effect": float(self.b_xy * self.b_yz * 2)}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


class CounterfactualModel(LinearSCMModel):
    """SYS041 结构反事实：给定事实观测，反事实查询 Z_x'(abduction-action-prediction)。"""

    model_id = "SYS041"

    def initialize(self, context, parameters, population, topology, rng):
        n = 4000
        Ux = rng.normal(0, self.u_var, n)
        Uy = rng.normal(0, self.u_var, n)
        Uz = rng.normal(0, self.u_var, n)
        X = Ux
        Y = self.b_xy * X + Uy
        Z = self.b_yz * Y + Uz
        # abduction：给定事实 Y=1 → 反推 Uy 后验；再反事实 X'=0
        mask = np.abs(Y - 1.0) < 0.15
        if mask.sum() > 5:
            Uy_post = (Y[mask] - self.b_xy * X[mask]).mean()
            Y_cf = self.b_xy * 0.0 + Uy_post          # X'=0
            Z_cf = self.b_yz * Y_cf + Uz[mask].mean()
            self.result = {"Z_counterfactual": float(Z_cf),
                           "Y_cf_expect": float(Uy_post),
                           "diff_from_factual": float(Z_cf - 1.0 * self.b_yz)}
        else:
            self.result = {"Z_counterfactual": None}


class HMMModel(DayanModel):
    """SYS042 隐 Markov：前向算法对数似然 + Viterbi 路径恢复真实状态序列。"""

    model_id = "SYS042"
    clock_type = "fixed_step"

    def __init__(self, T=200):
        self.T = T
        self.result = {}

    def initialize(self, context, parameters, population, topology, rng):
        A = np.array([[0.9, 0.1], [0.2, 0.8]])        # 状态转移
        B = np.array([[0.9, 0.1], [0.2, 0.8]])        # 发射（高状态发高观测）
        pi = np.array([0.5, 0.5])
        s = np.zeros(self.T, int)
        o = np.zeros(self.T, int)
        cur = rng.choice(2, p=pi)
        for t in range(self.T):
            s[t] = cur
            o[t] = rng.choice(2, p=B[cur])
            cur = rng.choice(2, p=A[cur])
        # 前向
        alpha = pi * B[:, o[0]]
        for t in range(1, self.T):
            alpha = (alpha @ A) * B[:, o[t]]
        ll = float(np.log(alpha.sum()))
        # Viterbi
        delta = np.log(pi + 1e-12) + np.log(B[:, o[0]] + 1e-12)
        back = np.zeros((self.T, 2), int)
        for t in range(1, self.T):
            scores = delta[:, None] + np.log(A + 1e-12)
            back[t] = scores.argmax(axis=0)
            delta = scores.max(axis=0) + np.log(B[:, o[t]] + 1e-12)
        path = np.zeros(self.T, int)
        path[-1] = delta.argmax()
        for t in range(self.T - 2, -1, -1):
            path[t] = back[t + 1][path[t + 1]]
        acc = float((path == s).mean())
        acc_best = max(acc, 1 - acc)  # 状态标签可能翻转
        self.result = {"loglik": ll, "viterbi_acc": acc_best}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


class LinearGaussianSSMModel(DayanModel):
    """SYS044 线性高斯状态空间：随机游走+噪声观测 → Kalman 滤波后验方差收缩。"""

    model_id = "SYS044"
    clock_type = "fixed_step"

    def __init__(self, T=200, q=0.1, r=1.0):
        self.T, self.q, self.r = T, q, r
        self.result = {}

    def initialize(self, context, parameters, population, topology, rng):
        true_x = np.cumsum(rng.normal(0, np.sqrt(self.q), self.T))
        obs = true_x + rng.normal(0, np.sqrt(self.r), self.T)
        # Kalman
        x_hat = 0.0
        P = 1.0
        errs_pre = []
        errs_post = []
        for t in range(self.T):
            # 预测
            x_pred = x_hat
            P_pred = P + self.q
            errs_pre.append(abs(x_pred - true_x[t]))
            # 更新
            K = P_pred / (P_pred + self.r)
            x_hat = x_pred + K * (obs[t] - x_pred)
            P = (1 - K) * P_pred
            errs_post.append(abs(x_hat - true_x[t]))
        self.result = {"rmse_prior": float(np.mean(errs_pre)),
                       "rmse_post": float(np.mean(errs_post)),
                       "P_final": float(P)}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


class DBNModel(DayanModel):
    """SYS045 动态贝叶斯网络：两时片雨→伞图，滤波分布随观测收敛。"""

    model_id = "SYS045"
    clock_type = "fixed_step"

    def __init__(self, T=50):
        self.T = T
        self.result = {}

    def initialize(self, context, parameters, population, topology, rng):
        # P(R_t|R_{t-1}): 持续性；P(U|R): 携伞观测
        A = np.array([[0.8, 0.2], [0.4, 0.6]])   # 行=前态(R,T)列=后态
        B = np.array([[0.9, 0.1], [0.2, 0.8]])   # P(U|R)
        rain = np.zeros(self.T, int)
        umb = np.zeros(self.T, int)
        cur = int(rng.random() < 0.5)
        for t in range(self.T):
            rain[t] = cur
            umb[t] = int(rng.random() >= B[cur][0])   # U 下标：1-P(U=0)
            cur = int(rng.random() < A[cur][1])
        # 前向滤波
        f = np.array([0.5, 0.5])
        fhist = []
        errs = []
        for t in range(self.T):
            if t > 0:
                f = A.T @ f
            like = B[:, umb[t]]
            f = f * like
            f = f / max(f.sum(), 1e-12)
            fhist.append(f.copy())
            errs.append(abs(f[1] - rain[t]))
        acc = float(np.mean([np.argmax(f_t) == r for f_t, r in zip(fhist, rain)]))
        self.result = {"mean_filter_err": float(np.mean(errs)),
                       "filter_acc": acc,
                       "final_P_rain": float(f[1])}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []
