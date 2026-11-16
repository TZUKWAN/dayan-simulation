"""大衍 DAYAN · 社会仿真平台内核（P0 内核与合同）。

实现 DAYAN 规范第二章：
- 2.1 模型登记表：10 字段组合同 + 六级实现状态（仅登记→原型可跑→基准通过→
  数据校准→留出验证→生产可用）
- 2.2 统一执行接口：initialize/validate_state/observe/intervene/snapshot/restore；
  推进语义按型分派：FixedStep(step)/DES(next_event_time+handle_event)/
  ODE(derivatives)/SDE(drift+diffusion)/Jump(event_intensities+apply_jump)
- 2.3 四时钟 + 派生随机流 + 事件优先级键（仿真时间, 语义优先级, 稳定序号）
- StateDelta / DomainEvent 两种调用结果；转移事务化（约束失败即拒绝）

本模块学科中立：不含任何具体社会机制；模型通过注册表合同接入。
"""
from __future__ import annotations

import hashlib
import copy
import heapq
import itertools
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np

# ================= 常量 =================
STATUS_LEVELS = ["仅登记", "原型可跑", "基准通过", "数据校准", "留出验证", "生产可用"]
FIELD_GROUPS = ["身份与证据", "适用范围", "状态", "时间", "输入与参数",
                "行动与干预", "输出与观测", "随机性", "执行与恢复", "验证与发布"]

# ================= 登记表 =================
@dataclass
class ModelRecord:
    """模型登记表（规范 2.1 最小必填字段的机器合同）。"""
    # 身份与证据
    model_id: str
    name: str
    kind: str = "未分类"
    version: str = "0.1"
    parent_model: Optional[str] = None
    source_refs: list = field(default_factory=list)
    license: Optional[str] = None
    # 适用范围
    question: str = ""
    population: str = ""
    space_scope: str = ""
    time_scope: str = ""
    assumptions: list = field(default_factory=list)
    known_failures: list = field(default_factory=list)
    # 状态
    entity_types: list = field(default_factory=list)
    state_schema: dict = field(default_factory=dict)
    units: dict = field(default_factory=dict)
    bounds: dict = field(default_factory=dict)
    conserved_quantities: list = field(default_factory=list)
    # 时间
    clock_type: str = "fixed_step"   # fixed_step|des|ode|sde|jump
    time_unit: str = "tick"
    activation: str = "synchronous"  # synchronous|async_shuffled|async_fixed|poisson|edge
    event_priority: str = "time>priority>seq"
    simultaneous_policy: str = "read_old_commit_new"
    # 输入与参数
    parameter_schema: dict = field(default_factory=dict)
    defaults: dict = field(default_factory=dict)
    valid_ranges: dict = field(default_factory=dict)
    priors: dict = field(default_factory=dict)
    # 行动与干预
    action_schema: dict = field(default_factory=dict)
    intervention_targets: list = field(default_factory=list)
    # 输出与观测
    observation_schema: dict = field(default_factory=dict)
    metrics: list = field(default_factory=list)
    # 随机性
    rng_algorithm: str = "pcg64(numpy.default_rng)"
    seed_policy: str = "derived_streams"
    stream_keys: list = field(default_factory=list)
    stochastic_components: list = field(default_factory=list)
    # 执行与恢复
    backend: str = "native-python"
    # 验证与发布
    invariants: list = field(default_factory=list)
    reference_cases: list = field(default_factory=list)
    calibration_data: Optional[str] = None
    holdout_data: Optional[str] = None
    tolerances: dict = field(default_factory=dict)
    # 平台管理
    status: str = "仅登记"           # STATUS_LEVELS 之一
    paradigm: str = "abm"            # abm|sd|game|or|des|hybrid
    factory: Optional[Callable] = None
    notes: str = ""

    def status_index(self) -> int:
        return STATUS_LEVELS.index(self.status)

    def contract_issues(self) -> list[str]:
        """按规范 2.1 检查登记合同的缺失字段（返回问题清单，空=合同完整）。"""
        issues = []
        if not self.model_id or not self.name:
            issues.append("缺 model_id/name")
        if self.status in ("原型可跑", "基准通过", "数据校准", "留出验证", "生产可用"):
            if not self.state_schema:
                issues.append("状态 schema 未声明")
            if not self.time_unit:
                issues.append("时间单位未声明")
            if self.clock_type not in ("fixed_step", "des", "ode", "sde", "jump"):
                issues.append(f"clock_type 非法: {self.clock_type}")
        if self.status in ("基准通过", "数据校准", "留出验证", "生产可用") \
                and not self.reference_cases:
            issues.append("基准通过及以上状态必须登记 reference_cases")
        if self.status in ("数据校准", "留出验证", "生产可用") \
                and not self.calibration_data:
            issues.append("数据校准及以上必须登记 calibration_data")
        if self.status == "留出验证" and not self.holdout_data:
            issues.append("留出验证必须登记 holdout_data")
        return issues


class ModelRegistry:
    """DAYAN 模型注册表（按 model_id 键；登记/检索/合同校验/状态升级）。"""

    def __init__(self):
        self._records: dict[str, ModelRecord] = {}

    def register(self, record: ModelRecord) -> ModelRecord:
        if record.model_id in self._records:
            existing = self._records[record.model_id]
            if existing is record:
                return existing
        self._records[record.model_id] = record
        return record

    def get(self, model_id: str) -> ModelRecord:
        return self._records[model_id]

    def find(self, kind: str | None = None, paradigm: str | None = None,
             status: str | None = None, keyword: str | None = None) -> list[ModelRecord]:
        out = [r for r in self._records.values()
               if (kind is None or r.kind == kind)
               and (paradigm is None or r.paradigm == paradigm)
               and (status is None or r.status == status)
               and (keyword is None or keyword in r.name
                    or keyword in r.question or keyword in r.notes)]
        return sorted(out, key=lambda r: r.model_id)

    def all(self) -> list[ModelRecord]:
        return sorted(self._records.values(), key=lambda r: r.model_id)

    def __len__(self):
        return len(self._records)

    def promote(self, model_id: str, to_status: str) -> list[str]:
        """状态升级（只允许沿六级前进），返回合同问题清单（空=升级合法）。"""
        rec = self._records[model_id]
        cur, tgt = rec.status_index(), STATUS_LEVELS.index(to_status)
        if tgt < cur:
            raise ValueError(f"{model_id}: 状态不可回退 {rec.status} → {to_status}")
        rec.status = to_status
        return rec.contract_issues()


# 全局注册表
_REGISTRY = ModelRegistry()


def get_registry() -> ModelRegistry:
    return _REGISTRY


# ================= 四时钟 =================
@dataclass
class Clocks:
    """规范 2.3：四个时钟必须分别记录（仿真时间、优化迭代、LLM墙钟、批次）。"""
    sim_time: float = 0.0          # 仿真时间（模型时间单位）
    optim_iter: int = 0            # 优化/求解迭代计数
    llm_wall_seconds: float = 0.0  # LLM 推理墙钟时间
    batch: int = 0                 # 实验批次编号


# ================= 派生随机流 =================
class RngStreams:
    """规范 2.3：随机数按 (实验, 模型, 实体/事件类型) 派生独立流。

    实现：种子 = SHA256(base_seed, *path) → numpy default_rng。
    新增无关模块不改既有流（避免全局流污染基准轨迹）。
    """

    def __init__(self, base_seed: int, experiment: str = "exp0"):
        self.base_seed = int(base_seed)
        self.experiment = str(experiment)
        self._cache: dict[tuple, np.random.Generator] = {}

    def _seed(self, *path) -> int:
        blob = json.dumps([self.base_seed, self.experiment, *path],
                          ensure_ascii=False, sort_keys=True, default=str)
        return int.from_bytes(
            hashlib.sha256(blob.encode("utf-8")).digest()[:8], "little")

    def stream(self, *path) -> np.random.Generator:
        key = tuple(str(x) for x in path)
        if key not in self._cache:
            self._cache[key] = np.random.default_rng(self._seed(*key))
        return self._cache[key]

    def stream_state(self, *path) -> Any:
        """流状态（供快照/恢复）。"""
        g = self.stream(*path)
        return g.bit_generator.state


# ================= 事件与增量 =================
@dataclass(order=True)
class DomainEvent:
    """带时间戳领域事件（排序键：时间 → 语义优先级 → 稳定序号）。"""
    sort_key: tuple = field(init=False, repr=False)
    time: float = field(compare=False)
    etype: str = field(compare=False)
    priority: int = 0                # 语义优先级（小=先）
    seq: int = field(compare=False, default=0)
    payload: dict = field(default_factory=dict, compare=False)

    def __post_init__(self):
        self.sort_key = (self.time, self.priority, self.seq)

    def __repr__(self):
        return f"DomainEvent(t={self.time}, type={self.etype}, seq={self.seq})"


@dataclass
class StateDelta:
    """状态差分（一次转移的事务性结果）。"""
    resource_transfers: list = field(default_factory=list)  # [(from,to,resource,amount)]
    relation_changes: list = field(default_factory=list)    # [(a,b,op,detail)]
    lifecycle: list = field(default_factory=list)           # [birth/death/enter/exit]
    rejected_reason: Optional[str] = None                   # 非空=事务被拒绝

    @property
    def committed(self) -> bool:
        return self.rejected_reason is None


class EventQueue:
    """DES 事件队列：稳定优先级键 + 取消 + 零时间循环防护。"""

    def __init__(self, max_zero_time_loop: int = 1_000):
        self._heap: list = []
        self._seq = itertools.count()
        self._cancelled: set[int] = set()
        self._zero_time_run = 0
        self._max_zero_time_loop = max_zero_time_loop

    def push(self, event: DomainEvent, payload_id: Optional[int] = None):
        """入队。event.sort_key 决定顺序；返回取消句柄（事件 id）。"""
        eid = payload_id if payload_id is not None else next(self._seq)
        heapq.heappush(self._heap, (event.sort_key, eid, event))
        return eid

    def cancel(self, eid: int):
        self._cancelled.add(eid)

    def pop(self, now: float) -> Optional[DomainEvent]:
        """弹出下一个有效事件；检测零时间死循环。"""
        while self._heap:
            key, eid, ev = heapq.heappop(self._heap)
            if eid in self._cancelled:
                self._cancelled.discard(eid)
                continue
            if ev.time == now:
                self._zero_time_run += 1
                if self._zero_time_run > self._max_zero_time_loop:
                    raise RuntimeError("零时间事件死循环（超过防护上限）")
            else:
                self._zero_time_run = 0
            return ev
        return None

    def __len__(self):
        return len(self._heap)


# ================= 平衡账本 =================
class BalancedLedger:
    """资金/资源平衡账本（规范 2.4）：任何转移保留来源与去向，总量守恒。"""

    def __init__(self, accounts: dict[str, float] | None = None):
        self.accounts: dict[str, float] = dict(accounts or {})
        self.history: list[dict] = []
        # 建账时各资源总量快照（合法转移应守恒；供 conservation_residual 对照）
        self._initial_totals: dict[str, float] = {}
        for k, v in self.accounts.items():
            res = k.split(".")[0]
            self._initial_totals[res] = self._initial_totals.get(res, 0.0) + v

    def transfer(self, src: str, dst: str, resource: str, amount: float,
                 note: str = "") -> StateDelta:
        if amount < 0:
            d = StateDelta(rejected_reason="负转移被拒绝")
            self.history.append({"src": src, "dst": dst, "resource": resource,
                                 "amount": amount, "rejected": True, "note": note})
            return d
        if self.accounts.get(src, 0.0) < amount - 1e-12:
            d = StateDelta(rejected_reason=f"余额不足: {src}.{resource}")
            self.history.append({"src": src, "dst": dst, "resource": resource,
                                 "amount": amount, "rejected": True, "note": note})
            return d
        self.accounts[src] = self.accounts.get(src, 0.0) - amount
        self.accounts[dst] = self.accounts.get(dst, 0.0) + amount
        self.history.append({"src": src, "dst": dst, "resource": resource,
                             "amount": amount, "rejected": False, "note": note})
        return StateDelta(resource_transfers=[(src, dst, resource, amount)])

    def total(self, resource: str = "money") -> float:
        return float(sum(v for k, v in self.accounts.items()
                         if k.split(".")[0] == resource or resource == "*"))

    def conservation_residual(self) -> float:
        """守恒残差：各资源当前总量与建账时总量之差（合法转移应守恒）。

        注入/外生增减应通过显式方法登记，否则表现为残差——这是设计意图：
        静默增减资金在研究语境下必须可见。"""
        resid = 0.0
        for res, init in self._initial_totals.items():
            resid += abs(self.total(res) - init)
        # 建账后新出现的资源种类也计入（无初始快照 → 全额视为残差）
        for k in self.accounts:
            res = k.split(".")[0]
            if res not in self._initial_totals:
                resid += abs(self.accounts.get(k, 0.0))
        return resid


# ================= 模型接口（按推进语义分型） =================
class DayanModel:
    """DAYAN 统一执行接口（规范 2.2）。子类按 clock_type 实现对应推进族。

    合同方法：initialize/validate_state/observe/intervene/snapshot/restore
    推进族（按 clock_type 实现其一）：
      fixed_step: step(t, dt)
      des:        next_event_time(t) + handle_event(event)
      ode:        derivatives(t, x) -> dx/dt
      sde:        drift(t, x) + diffusion(t, x)
      jump:       event_intensities(t) + apply_jump(t, which)
    """

    model_id: str = "unset"
    clock_type: str = "fixed_step"

    def _apply_parameters(self, parameters: dict):
        """通用参数注入：把 parameters dict 中与 __init__ 签名匹配的键
        设置为实例属性。子类 initialize() 可调用此方法实现参数覆盖。

        类型适配：目标属性当前值为 int 而传入 float 时四舍五入取整
        （LLM 常给 cells=60.7 这类值，numpy 要求整数序列）。"""
        import inspect as _inspect
        try:
            sig = _inspect.signature(self.__init__)
            known = {name for name in sig.parameters
                     if name != 'self' and name not in ('kwargs', 'kw', 'args')}
        except (ValueError, TypeError):
            return
        for key, val in parameters.items():
            if key not in known:
                continue
            cur = getattr(self, key, None)
            if isinstance(cur, int) and not isinstance(cur, bool) \
                    and isinstance(val, float):
                val = int(round(val))
            setattr(self, key, val)

    def initialize(self, context: dict, parameters: dict,
                   population: Any, topology: Any, rng: np.random.Generator):
        raise NotImplementedError

    def validate_state(self) -> list[str]:
        return []

    def observe(self) -> dict:
        return {}

    def intervene(self, action: dict):
        pass

    def snapshot(self) -> dict:
        return {}

    def restore(self, state: dict):
        pass

    # --- fixed_step ---
    def step(self, t: float, dt: float):
        raise NotImplementedError(f"{self.model_id} 未实现 step（fixed_step）")

    # --- des ---
    def next_event_time(self, t: float) -> Optional[float]:
        return None

    def handle_event(self, event: DomainEvent):
        raise NotImplementedError

    # --- ode ---
    def derivatives(self, t: float, x: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    # --- sde ---
    def drift(self, t: float, x: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def diffusion(self, t: float, x: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    # --- jump ---
    def event_intensities(self, t: float) -> np.ndarray:
        raise NotImplementedError

    def apply_jump(self, t: float, which: int):
        raise NotImplementedError


# ================= 统一编排器 =================
def simulate(model: DayanModel, horizon: float = 100.0, dt: float = 1.0,
             context: dict | None = None, parameters: dict | None = None,
             population: Any = None, topology: Any = None,
             rng: np.random.Generator | None = None,
             on_step: Callable | None = None,
             on_initialize: Callable | None = None,
             before_step: Callable | None = None,
             step_limit: Callable | None = None) -> dict:
    """统一编排器：把各类推进语义适配到同一场景时间（规范 2.2）。

    返回 {'clocks': Clocks, 'observations': [...], 'final': observe()}
    """
    rng = rng or np.random.default_rng(0)
    model.initialize(context or {}, parameters or {}, population, topology, rng)
    issues = model.validate_state()
    if issues:
        raise ValueError(f"初态校验失败: {issues}")
    clocks = Clocks()
    if before_step:
        before_step(0.0, model)
    obs = [copy.deepcopy(model.observe())]
    times = [0.0]
    if on_initialize:
        on_initialize(0.0, model)
    ct = model.clock_type

    MAX_OBS = 500_000  # 观测容量护栏（宕机教训：无限增长会吃光内存）

    def emit(t):
        if len(obs) >= MAX_OBS:
            raise RuntimeError("观测数超过容量上限，运行已停止；不产生占位观测")
        obs.append(copy.deepcopy(model.observe()))
        times.append(float(t))
        if on_step:
            on_step(t, model)

    def limited_dt(t):
        amount = min(dt, horizon - t)
        if step_limit:
            amount = min(amount, step_limit(t, amount))
        if amount <= 0:
            raise ValueError("步长必须为正，检查干预时间与终止时间")
        return amount

    if ct == "fixed_step":
        t = 0.0
        while t < horizon - 1e-12:
            # 非整步终点：最后一步收缩到终点，不越过（WP4 时间合同）
            if before_step:
                before_step(t, model)
            step_dt = limited_dt(t)
            model.step(t, step_dt)
            t += step_dt
            clocks.sim_time = t
            clocks.optim_iter += 1
            emit(t)
    elif ct == "ode":
        # RK4 定步积分（内核自带，避免外部依赖）；x 状态由 observe 之外的
        # model.x 提供（ODE 模型以 numpy 向量为主状态）
        t = 0.0
        x = np.asarray(model.x, dtype=float)
        while t < horizon - 1e-12:
            if before_step:
                before_step(t, model)
                x = np.asarray(model.x, dtype=float)
            step_dt = limited_dt(t)
            k1 = model.derivatives(t, x)
            k2 = model.derivatives(t + step_dt / 2, x + step_dt / 2 * k1)
            k3 = model.derivatives(t + step_dt / 2, x + step_dt / 2 * k2)
            k4 = model.derivatives(t + step_dt, x + step_dt * k3)
            x = x + step_dt / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
            model.x = x
            t += step_dt
            clocks.sim_time = t
            clocks.optim_iter += 1
            emit(t)
    elif ct == "sde":
        # Euler–Maruyama
        t = 0.0
        x = np.asarray(model.x, dtype=float)
        while t < horizon - 1e-12:
            if before_step:
                before_step(t, model)
                x = np.asarray(model.x, dtype=float)
            step_dt = limited_dt(t)
            a = model.drift(t, x)
            b = model.diffusion(t, x)
            dW = rng.normal(0.0, 1.0, size=np.shape(x)) * np.sqrt(step_dt)
            x = x + a * step_dt + b * dW
            model.x = x
            t += step_dt
            clocks.sim_time = t
            clocks.optim_iter += 1
            emit(t)
    elif ct == "des":
        # 零时间循环防护在编排器层（不依赖 EventQueue 的使用）。
        # 上限 1000 同刻事件 + 观测列表硬上限——防止内存炸弹拖垮机器（宕机教训）。
        prev_t = None
        consec_same_t = 0
        max_zero_time_loop = 1_000
        MAX_OBS = 200_000
        nt = model.next_event_time(0.0)
        while nt is not None and nt <= horizon:
            if prev_t is not None and nt == prev_t:
                consec_same_t += 1
                if consec_same_t > max_zero_time_loop:
                    raise RuntimeError("零时间事件死循环（超过防护上限）")
            else:
                consec_same_t = 0
            prev_t = nt
            if before_step:
                before_step(nt, model)
            ev = DomainEvent(time=nt, etype="des")
            model.handle_event(ev)
            clocks.sim_time = nt
            clocks.optim_iter += 1
            emit(nt)
            nt = model.next_event_time(nt)
    elif ct == "jump":
        # Gillespie 直接法
        t = 0.0
        while t < horizon - 1e-12:
            if before_step:
                before_step(t, model)
            rates = np.asarray(model.event_intensities(t), dtype=float)
            total = rates.sum()
            if total <= 0:
                bound = min(horizon, t + step_limit(t, horizon - t)) if step_limit else horizon
                if bound > t + 1e-12:
                    t = bound
                    clocks.sim_time = t
                    emit(t)
                    if t < horizon - 1e-12:
                        continue
                break
            tau = rng.exponential(1.0 / total)
            t2 = t + tau
            bound = min(horizon, t + step_limit(t, horizon - t)) if step_limit else horizon
            if t2 > bound:
                t = bound
                clocks.sim_time = t
                emit(t)
                if t >= horizon - 1e-12:
                    break
                continue
            if t2 > horizon:
                break
            which = int(rng.choice(len(rates), p=rates / total))
            model.apply_jump(t2, which)
            t = t2
            clocks.sim_time = t
            clocks.optim_iter += 1
            emit(t)
    else:
        raise ValueError(f"未知 clock_type: {ct}")

    return {"clocks": clocks, "observations": obs, "times": times,
            "final": copy.deepcopy(model.observe())}
