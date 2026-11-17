"""统一运行层（WP3 参数合同 / WP4 时间与随机性 / WP5 RunManifest）。

run_model_full() 是唯一权威运行入口；run_model() 为兼容包装。

参数合同（WP3）：
  解析 → schema 校验（类型/别名/未知值）→ 构造期注入（__init__ 形参真实传参）
  → 单次初始化 → 生效核验 → 写入 manifest

时间与随机性（WP4）：
  观测带 sim_t 仿真时间；非整步终点收缩最后一步（core.simulate 已修）；
  RngStreams 派生流（同 seed+model_id 复现，新增模块不污染既有流）；
  检查点区分 full/partial——模型未实现 snapshot 时如实标注"仅回放，不可续算"。

RunManifest（WP5）：
  run_id、请求值 vs 实际值、类型改写记录、生效核验、时钟、随机流、警告、时长。
"""
from __future__ import annotations

import hashlib
import copy
import inspect
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid

import numpy as np

from .core import RngStreams
from .source_version import source_fingerprint
_PROCESS_SOURCE_FINGERPRINT=source_fingerprint()


def assert_loaded_source():
    if source_fingerprint()!=_PROCESS_SOURCE_FINGERPRINT:
        raise ValueError('执行进程加载后源码已变化，请使用新工作进程；禁止将新磁盘源码冒充本次执行版本')
    return _PROCESS_SOURCE_FINGERPRINT

# 已知参数别名（仅映射到目标模型真实形参名才生效；宁缺勿猜）
PARAM_ALIASES: dict[str, tuple[str, ...]] = {
    "n": ("n_agents", "num_agents", "agent_count", "population", "n_pop"),
    "steps": ("ticks", "n_steps"),
}

RUNTIME_KEYS = {"ticks", "dt", "seed"}     # 运行参数，不进模型合同


def validate_run_arguments(ticks: int, dt: float, seed: int) -> None:
    """Reject invalid execution lengths before constructing or initializing a model."""
    if isinstance(ticks, (bool, np.bool_)) or not isinstance(ticks, (int, np.integer)):
        raise ValueError("ticks 必须是非负整数")
    if not 0 <= int(ticks) <= 500_000:
        raise ValueError("ticks 必须在 0–500000 之间")
    if isinstance(dt, (bool, np.bool_)) or not isinstance(dt, (int, float, np.number)) \
            or not math.isfinite(float(dt)) or float(dt) <= 0:
        raise ValueError("dt 必须是有限正数")
    if isinstance(seed, (bool, np.bool_)) or not isinstance(seed, (int, np.integer)) \
            or not 0 <= int(seed) < 2 ** 64:
        raise ValueError("seed 必须是 0–2^64-1 范围内的整数")


@dataclass
class ParamIssue:
    kind: str            # unknown | alias | coerced | type_error | runtime_key
    param: str
    requested: Any
    actual: Any = None
    message: str = ""

    def as_dict(self) -> dict:
        return {"kind": self.kind, "param": self.param,
                "requested": _jsonable(self.requested),
                "actual": _jsonable(self.actual), "message": self.message}


@dataclass
class RunResult:
    model_id: str
    observations: list
    manifest: dict
    issues: list[ParamIssue] = field(default_factory=list)
    state_frames: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    checkpoint: dict | None = None

    @property
    def ok(self) -> bool:
        return bool(self.observations)


def _jsonable(v: Any) -> Any:
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, np.ndarray):
        return _jsonable(v.tolist())
    if isinstance(v, dict):
        return {str(k): _jsonable(value) for k, value in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(value) for value in v]
    if isinstance(v, (bool, int, float, str)) or v is None:
        return v
    return str(v)


# ================= 参数合同 =================
def _init_signature(mid: str) -> dict[str, dict]:
    """模型 __init__ 形参 → {name: {default, type}}。"""
    from .model_index import resolve
    _, factory = resolve(mid)
    if factory is None:
        return {}
    cls = factory[1] if isinstance(factory, tuple) else factory
    if isinstance(getattr(cls, "parameter_schema", None), dict):
        return copy.deepcopy(cls.parameter_schema)
    try:
        sig = inspect.signature(cls.__init__)
    except (ValueError, TypeError):
        return {}
    out = {}
    for name, p in sig.parameters.items():
        if name == "self" or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        if p.default is inspect._empty:
            out[name] = {"default": None, "type": "unknown", "required": True}
        else:
            out[name] = {"default": _jsonable(p.default),
                         "type": _type_of(p.default), "required": False}
    return out


def _type_of(default: Any) -> str:
    if isinstance(default, bool):
        return "bool"
    if isinstance(default, (int, np.integer)):
        return "int"
    if isinstance(default, (float, np.floating)):
        return "float"
    if isinstance(default, str):
        return "str"
    if isinstance(default, (list, tuple, np.ndarray)):
        return "array"
    return "any"


def param_contract(mid: str) -> dict:
    """模型参数合同：__init__ 形参 + 类型 + 默认值（供 UI/Agent/校验共用）。"""
    sig = _init_signature(mid)
    from .policies import intervention_contract
    policies = intervention_contract(mid)
    mutable = {c["param"] for c in policies}
    for name, meta in sig.items():
        meta["mutable_at_runtime"] = name in mutable
    return {"model_id": mid, "params": sig, "policies": policies,
            "n_params": len(sig)}


def validate_params(mid: str, parameters: dict | None,
                    strict: bool = False) -> tuple[dict, list[ParamIssue]]:
    """参数校验与清洗。

    strict=True：未知参数直接 ValueError（正式实验用）。
    strict=False：未知参数记 issue 但继续（交互演示用，manifest 留痕）。
    """
    params = dict(parameters or {})
    sig = _init_signature(mid)
    known = set(sig.keys())
    issues: list[ParamIssue] = []
    clean: dict = {}

    for key, val in params.items():
        k = str(key)
        if k in RUNTIME_KEYS and k not in known:
            issues.append(ParamIssue("runtime_key", k, val,
                                     message="运行参数由 ticks/dt/seed 单独传递，不进模型"))
            continue
        target = k
        if k not in known:
            alias_hit = None
            for canon, aliases in PARAM_ALIASES.items():
                if k in aliases and canon in known:
                    alias_hit = canon
                    break
            if alias_hit:
                target = alias_hit
                issues.append(ParamIssue(
                    "alias", k, val, alias_hit,
                    message=f"别名映射 {k} → {alias_hit}"))
            else:
                issues.append(ParamIssue(
                    "unknown", k, val,
                    message="模型无此参数（不在 __init__ 形参中）"
                            + ("；strict 模式拒绝" if strict else "；已忽略")))
                if strict:
                    raise ValueError(
                        f"{mid}: 未知参数 {k}={val!r}（可用参数：{sorted(known)}）")
                continue
        expected = sig.get(target, {}).get("type", "any")
        if val is None and sig.get(target, {}).get("default") is None \
                and not sig.get(target, {}).get("required"):
            issues.append(ParamIssue("default", k, None, None,
                                     "null 使用构造器默认值，不覆盖派生状态"))
            continue
        v2 = _coerce_type(target, val, expected, issues)
        if isinstance(v2, (int, float, np.number)) and not np.isfinite(v2):
            raise ValueError(f"参数 {k} 必须是有限数值")
        clean[target] = v2
    return clean, issues


def _coerce_type(name: str, val: Any, expected: str,
                 issues: list[ParamIssue]) -> Any:
    """类型适配；任何改写都记录（requested → actual）。"""
    if expected == "int":
        if isinstance(val, bool):
            issues.append(ParamIssue("coerced", name, val, int(val),
                                     "bool→int"))
            return int(val)
        if isinstance(val, (int, np.integer)):
            return int(val)
        if isinstance(val, (float, np.floating)):
            iv = int(round(float(val)))
            if iv != float(val):
                issues.append(ParamIssue("coerced", name, float(val), iv,
                                         "float→int 四舍五入"))
            else:
                issues.append(ParamIssue("coerced", name, float(val), iv,
                                         "float→int"))
            return iv
        try:
            iv = int(round(float(val)))
            issues.append(ParamIssue("coerced", name, val, iv, "str→int"))
            return iv
        except (TypeError, ValueError):
            issues.append(ParamIssue("type_error", name, val, None,
                                     f"无法转 int"))
            raise ValueError(f"参数 {name}={val!r} 无法转为 int")
    if expected == "float":
        if isinstance(val, bool):
            return int(val)
        if isinstance(val, (int, float, np.integer, np.floating)):
            return float(val)
        try:
            fv = float(val)
            issues.append(ParamIssue("coerced", name, val, fv, "str→float"))
            return fv
        except (TypeError, ValueError):
            raise ValueError(f"参数 {name}={val!r} 无法转为 float")
    if expected == "bool":
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, np.integer)):
            issues.append(ParamIssue("coerced", name, val, bool(val),
                                     "int→bool"))
            return bool(val)
    if expected == "str":
        if not isinstance(val, str):
            issues.append(ParamIssue("coerced", name, val, str(val),
                                     "→str"))
            return str(val)
    return val


def _effect_probe(model: Any, applied: dict) -> dict:
    """生效核验：初始化后逐参数比对属性实际值。"""
    probe = {}
    for name, val in applied.items():
        if not isinstance(val, (int, float, str, bool)):
            continue
        actual = getattr(model, name, "__missing__")
        probe[name] = {
            "requested": _jsonable(val),
            "actual": None if actual == "__missing__" else _jsonable(actual),
            "applied": actual != "__missing__" and
                       (str(actual) == str(val) or actual == val),
        }
    return probe


# ================= 检查点（WP4） =================
def save_checkpoint(model: Any, t: float, rng: np.random.Generator,
                    params: dict, protocol: str) -> dict:
    snap = model.snapshot() if hasattr(model, "snapshot") else {}
    full = bool(snap)
    chk = {
        "model_id": getattr(model, "model_id", "?"),
        "protocol": protocol,
        "t": round(float(t), 9),
        "rng_state": rng.bit_generator.state,
        "parameters": params,
        "model_snapshot": _jsonable(snap),
        "state_fidelity": "full" if full else "partial",
        "resumable": full and protocol == "fixed_step",
    }
    if not full:
        chk["note"] = ("模型未实现 snapshot()，检查点仅含随机流与时间——"
                       "只能做同种子重放，不能从状态续算（如实降级，不冒充恢复）")
    return chk


def resume_from_checkpoint(chk, steps, dt, *, capture_state=False, with_initial=False):
    """Continue a supported full fixed-step snapshot; never rerun its earlier history."""
    executing_source=assert_loaded_source()
    validate_run_arguments(steps, dt, 0)
    from .limits import validate_compute,frame_stride
    validate_compute(steps,parameters=chk.get('parameters'))
    sample_stride=frame_stride(steps,1,chk.get('parameters'))
    if not chk.get("resumable") or chk.get("protocol") != "fixed_step":
        raise ValueError("该检查点不可续算：缺少完整模型状态/恢复协议。可回放已保存观测。")
    from .model_index import resolve
    mid = chk["model_id"]
    protocol, cls = resolve(mid)
    if protocol != "fixed_step":
        raise ValueError("该模型协议尚未实现检查点续算")
    model = cls(**(chk.get("parameters") or {}))
    model.restore(copy.deepcopy(chk["model_snapshot"]))
    rng = getattr(model, "rng", None) or getattr(model,'rng_',None)
    if not isinstance(rng, np.random.Generator):
        rng = np.random.default_rng()
        rng.bit_generator.state = chk["rng_state"]
    start = t = float(chk["t"])
    eff_dt = dt * getattr(model, "dt_scale", 1.0)
    horizon = start + steps*eff_dt
    rows, frames, applied = [], [], []
    iterations=0
    pending = copy.deepcopy(chk.get("pending_interventions", []))
    run_id = "R" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex
    initial_parameters = {name: _jsonable(getattr(model, name, meta.get("default"))) for name, meta in _init_signature(mid).items()}
    def capture():
        row = {"sim_t": round(t, 9), **copy.deepcopy(model.observe())}
        rows.append(_jsonable(row))
        if capture_state and (iterations%sample_stride==0 or t>=horizon-1e-12):
            from .stateframe import state_frame_of, _aggregate_frame
            frame = state_frame_of(model, t) or _aggregate_frame(model, t)
            frames.append({**_jsonable(copy.deepcopy(frame)), "run_id": run_id})
    if with_initial:
        capture()
    while t < horizon - 1e-12:
        while pending and float(pending[0]["at_t"]) <= t + 1e-12:
            iv = pending.pop(0)
            from .policies import validate_intervention_value
            changes = {}
            for name, spec in iv["params"].items():
                value = validate_intervention_value(mid, name, _resolve_param_op(model, name, spec))
                changes[name] = value
            apply=getattr(model,'apply_intervention',None)
            if callable(apply):apply(changes,t)
            else:
                for name,value in changes.items():setattr(model,name,value)
            applied.append({"requested_t": iv["at_t"], "actual_t": round(t, 9), "params": changes, "applied": True})
        step_dt = min(eff_dt, horizon-t)
        if pending and t + 1e-12 < float(pending[0]["at_t"]) < t+step_dt-1e-12:
            step_dt = float(pending[0]["at_t"])-t
        model.step(t, step_dt)
        t += step_dt
        iterations += 1
        capture()
    checkpoint = save_checkpoint(model, t, rng, chk.get("parameters") or {}, protocol)
    checkpoint["model_id"] = mid
    checkpoint["pending_interventions"] = pending
    events = [_jsonable(e) for e in getattr(model, "events", []) if isinstance(e, dict) and e.get("sim_t", start) >= start]
    events += [{"etype": "intervention", "sim_t": iv["actual_t"], **iv} for iv in applied]
    manifest = {"run_id": run_id, "model_id": mid, "protocol": protocol,"source_fingerprint":executing_source,
                "requested": {"resume_from_t": start, "ticks": steps, "dt": dt},
                "actual": {"parameters": chk.get("parameters") or {}, "effective_parameters": initial_parameters,
                           "n_steps": iterations, "n_obs": len(rows), "final_t": round(t, 9)},
                "rng": {"resumed_from_checkpoint": True, "algorithm": "restored full RNG state"},
                "clocks": {"sim_time": round(t, 9), "llm_wall_seconds": sum(c.get("duration_s", 0) for c in getattr(model, "llm_audit", []))},
                "checkpoint": {"resumable": True, "state_fidelity": "full", "t": round(t, 9)},
                "interventions": applied, "model_definition": getattr(model, "definition", None),
                "scenario_review": getattr(model,"scenario_review",None),
                "llm_calls": getattr(model, "llm_audit", []), "state_frame_count": len(frames),
                'state_every':sample_stride,
                "runtime_version": "2.1", "warnings": [],
                "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    return RunResult(model_id=mid, observations=rows, manifest=manifest, state_frames=frames,
                     events=events, checkpoint=checkpoint)


# ================= 运行 =================
def _run_steps(model, protocol: str, t0: float, steps: int, dt: float,
               params: dict, seed, rng: np.random.Generator) -> tuple[list, float, list]:
    """统一推进：fixed_step 走本层循环（单次初始化），其余走 core.simulate。

    返回 (observations_with_time, final_t, events_dump)。
    """
    from .core import simulate
    if protocol in ("simulate", "jump_sim", "demo_jump"):
        r = simulate(model, horizon=steps * dt, dt=dt,
                     parameters=params, rng=rng)
        obs = r["observations"]
        times = [i * dt for i in range(len(obs))]
        clocks = r["clocks"]
        final_t = float(clocks.sim_time)
        return obs, final_t, []

    # fixed_step / demo(met|rl)：本地循环
    eff_dt = dt * getattr(model, "dt_scale", 1.0)
    obs = []
    t = t0
    if t0 == 0.0:
        obs.append(model.observe())
        times = [0.0]
    else:
        times = []
    for k in range(int(steps)):
        t += eff_dt
        model.step(t - eff_dt, eff_dt)
        obs.append(model.observe())
        times.append(t)
    events = list(getattr(model, "events", []) or [])
    return obs, times[-1] if times else t0, events


def _resolve_param_op(model: Any, name: str, spec: Any) -> Any:
    """干预参数相对变化："*0.7"=当前值×0.7；"+0.1"=加；"−0.2"=减；否则绝对值。"""
    cur = getattr(model, name, None)
    if isinstance(spec, str):
        s = spec.strip().replace("−", "-")
        if s.startswith("*"):
            if not isinstance(cur, (int, float)):
                raise ValueError(f"干预参数 {name} 当前值不可乘（{cur!r}）")
            return cur * float(s[1:])
        if s.startswith("+") or s.startswith("-"):
            if not isinstance(cur, (int, float)):
                raise ValueError(f"干预参数 {name} 当前值不可加减（{cur!r}）")
            return cur + float(s)
        return float(s)
    return spec


def run_model_full(mid: str, parameters: dict | None = None,
                   ticks: int | None = None, dt: float | None = None, seed: int | None = None,
                   experiment: str = "exp0", strict: bool = False,
                   with_time: bool = True,
                   checkpoint_at: int | None = None,
                   interventions: list[dict] | None = None,
                   on_step=None,
                   capture_state: bool = False,
                   state_every: int = 1,
                   data_bindings: list | None = None) -> RunResult:
    """权威运行入口。返回 RunResult（observations + manifest + issues）。"""
    executing_source=assert_loaded_source()
    from .model_index import resolve
    t_start = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    params_in = dict(parameters or {})
    from .datasets import bind_parameters
    bound, data_evidence = bind_parameters(data_bindings,mid)
    for name, value in bound.items():
        if name in params_in and params_in[name] != value:
            raise ValueError(f"参数 {name} 与数据映射值冲突，不能静默覆盖")
    params_in.update(bound)
    protocol, factory = resolve(mid)
    if protocol is None or factory is None:
        raise KeyError(f"模型 {mid} 无运行工厂")

    sig = _init_signature(mid)
    normalized = dict(params_in)
    options = {"ticks": ticks, "dt": dt, "seed": seed}
    placement = []
    for name, default in (("ticks", 200), ("dt", .1), ("seed", 0)):
        if name in normalized:
            nested = normalized[name]
            if options[name] is not None and options[name] != nested:
                raise ValueError(f"运行选项 {name} 冲突: 顶层={options[name]}，parameters={nested}")
            options[name] = nested
            placement.append(ParamIssue("runtime_bound", name, nested, nested,
                                        f"parameters.{name} 已绑定运行选项，实际值 {nested}"))
            if name not in sig:
                normalized.pop(name)
        if options[name] is None:
            options[name] = default
        if name in sig and name in ("seed", "dt"):
            normalized[name] = options[name]
    ticks, dt, seed = options["ticks"], options["dt"], options["seed"]
    validate_run_arguments(ticks, dt, seed)
    from .limits import validate_compute, frame_stride
    validate_compute(int(ticks), parameters=params_in)
    clean, issues = validate_params(mid, normalized, strict=strict)
    if capture_state:
        defaults = {name: meta.get('default') for name, meta in sig.items()}
        state_every = frame_stride(int(ticks), state_every, {**defaults, **clean})
    issues = placement + issues

    # 构造期注入：__init__ 形参真实传参（结构参数在构造时生效）
    ctor_kwargs = {k: v for k, v in clean.items() if k in sig}
    cls = factory[1] if isinstance(factory, tuple) else factory
    if protocol == "demo" and factory[0] == "met_demo":
        from .models.met_registry import MetDemo
        model = MetDemo(mid)
    else:
        model = cls(**ctor_kwargs)

    # 派生随机流：同 seed+mid 复现；新增模块不污染既有流（WP4）
    streams = RngStreams(seed, experiment=experiment)
    rng = streams.stream("model", mid)

    # 单次初始化 + 推进（core.simulate 内部 initialize；fixed_step 本层一次）
    from .core import simulate as _simulate
    fkind = factory[0] if isinstance(factory, tuple) else "direct"
    n_steps = int(ticks)
    initialized = False
    state_frames: list[dict] = []
    checkpoint = None
    observation_index = 0
    initial_effective = {}
    if not isinstance(state_every, int) or state_every < 1:
        raise ValueError("state_every 必须是正整数")
    if checkpoint_at is not None and (not isinstance(checkpoint_at, int)
                                      or not 0 <= checkpoint_at <= n_steps):
        raise ValueError("checkpoint_at 必须是运行范围内的非负步数")

    # 时点干预队列（按 t 升序；fire 在到达时刻前对参数生效）
    iv_pending = sorted([dict(iv) for iv in (interventions or [])],
                        key=lambda iv: float(iv.get("at_t", iv.get("t", 0.0))))
    for iv in iv_pending:
        at = float(iv.get("at_t", iv.get("t", 0.0)))
        if not math.isfinite(at) or at < 0:
            raise ValueError("干预时间必须为有限非负数")
        horizon = n_steps * dt * (getattr(model, "dt_scale", 1.0) if protocol == "fixed_step" else 1.0)
        if at > horizon + 1e-12:
            raise ValueError(f"干预时刻 {at} 超出运行终点 {horizon}")
        if not isinstance(iv.get("params"), dict) or not iv["params"]:
            raise ValueError("每项干预必须明确声明非空params")
        from .policies import intervention_contract, validate_intervention_value
        allowed = {c["param"] for c in intervention_contract(mid)}
        for name in iv["params"]:
            if name not in allowed:
                raise ValueError(f"{mid}.{name} 是未声明运行中可变的参数；可用：{sorted(allowed)}")
    applied_ivs: list[dict] = []

    def _fire_iv(t_now: float):
        while iv_pending and \
                float(iv_pending[0].get("at_t", iv_pending[0].get("t", 0.0))) \
                <= t_now + 1e-12:
            iv = iv_pending.pop(0)
            at_req = iv.get("at_t", iv.get("t", 0.0))
            chg = {}
            for pname, pspec in (iv.get("params") or {}).items():
                from .policies import validate_intervention_value
                v = validate_intervention_value(mid, pname, _resolve_param_op(model, pname, pspec))
                chg[pname] = _jsonable(v)
            apply = getattr(model, "apply_intervention", None)
            if callable(apply):
                apply(chg, t_now)
            else:
                for pname, value in chg.items():
                    setattr(model, pname, value)
            applied_ivs.append({"label": iv.get("label", ""),
                                "requested_t": at_req,
                                "actual_t": round(float(t_now), 9),
                                "params": chg, "applied": bool(chg)})

    def _capture(t_now: float):
        nonlocal checkpoint
        if checkpoint_at == observation_index:
            checkpoint = copy.deepcopy(save_checkpoint(model, t_now, rng, clean, protocol))
            checkpoint["model_id"] = mid
            checkpoint["pending_interventions"] = copy.deepcopy(iv_pending)
        if capture_state and (observation_index % state_every == 0):
            from .stateframe import state_frame_of, _aggregate_frame
            fr = state_frame_of(model, t_now) or _aggregate_frame(model, t_now)
            state_frames.append(_jsonable(copy.deepcopy(fr)))

    def _initial_hook(t_now: float, _model=None):
        for name, meta in sig.items():
            initial_effective[name] = _jsonable(getattr(model, name, clean.get(name, meta.get("default"))))
        _capture(t_now)

    def _step_hook(t_now: float, _model=None):
        nonlocal observation_index
        observation_index += 1
        _capture(t_now)
        if on_step:
            on_step(t_now, model)

    def _before_step(t_now: float, _model=None):
        _fire_iv(t_now)

    def _step_limit(t_now: float, amount: float):
        upcoming = [float(iv.get("at_t", iv.get("t", 0)))
                    for iv in iv_pending
                    if float(iv.get("at_t", iv.get("t", 0))) > t_now + 1e-12]
        if upcoming:
            distance = min(upcoming) - t_now
            return distance if distance < amount - 1e-12 else amount
        return amount

    if protocol == "simulate" or fkind == "jump_sim":
        r = _simulate(model, horizon=n_steps * dt, dt=dt,
                      parameters=clean, rng=rng,
                      on_step=_step_hook, on_initialize=_initial_hook,
                      before_step=_before_step,
                      step_limit=_step_limit if iv_pending else None)
        obs = r["observations"]
        clocks_obj = r["clocks"]
        final_t = float(clocks_obj.sim_time)
        n_iter = int(clocks_obj.optim_iter)
        times = r["times"]
        initialized = True
    elif fkind in ("met_demo", "rl_demo"):
        if iv_pending:
            applied_ivs.append({"label": iv_pending[0].get("label", ""),
                                "applied": False,
                                "error": "met/rl_demo 单次推断无时间轴，不支持时点干预"})
            iv_pending.clear()
        model.initialize({}, clean, None, None, rng)
        initialized = True
        obs = [copy.deepcopy(model.observe())]
        _initial_hook(0.0)
        times = [0.0]
        final_t = 0.0
        n_iter = 0
    else:
        model.initialize({}, clean, None, None, rng)
        invalid = model.validate_state()
        if invalid:
            raise ValueError(f"初态校验失败: {invalid}")
        initialized = True
        _fire_iv(0.0)
        obs = [copy.deepcopy(model.observe())]
        times = [0.0]
        _initial_hook(0.0)
        eff_dt = dt * getattr(model, "dt_scale", 1.0)
        t = 0.0
        n_iter = 0
        horizon = n_steps * eff_dt
        while t < horizon - 1e-12:
            _fire_iv(t)
            step_dt = _step_limit(t, min(eff_dt, horizon - t))
            t += step_dt
            model.step(t - step_dt, step_dt)
            n_iter += 1
            obs.append(copy.deepcopy(model.observe()))
            times.append(t)
            _step_hook(t, model)
        final_t = t
        if iv_pending:
            for iv in iv_pending:
                applied_ivs.append({"label": iv.get("label", ""),
                                    "requested_t": iv.get("at_t", iv.get("t")),
                                    "applied": False,
                                    "error": "干预时刻超出运行终点，未生效"})
            iv_pending.clear()

    _ev = getattr(model, "events", None)
    try:
        events_dump = (list(_ev) if _ev is not None else [])
    except TypeError:
        events_dump = []

    # ---- 时点干预（WP8）：在指定仿真时刻对参数施加变化，记录实际生效时刻 ----
    # 注意：ODE 模型的状态向量 x 不受干预影响（干预作用于参数属性，如 beta/gamma）；
    # 若干预目标是初值类参数，效果仅在下一时刻由方程使用时体现——manifest 如实记录。

    if with_time:
        obs_out = []
        for tk, o in zip(times, obs):
            if isinstance(o, dict):
                entry = {"sim_t": round(float(tk), 9)}
                entry.update(o)
                obs_out.append(entry)
            else:
                obs_out.append(o)
    else:
        obs_out = obs

    if checkpoint_at is None:
        checkpoint = copy.deepcopy(save_checkpoint(model, final_t, rng, clean, protocol))
        checkpoint["model_id"] = mid
        checkpoint["pending_interventions"] = copy.deepcopy(iv_pending)

    effect = _effect_probe(model, ctor_kwargs)
    duration = time.perf_counter() - t_start
    finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    seed_str = f"{mid}|{seed}|{time.time_ns()}|{uuid.uuid4().hex}"
    run_id = "R" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + \
        "-" + uuid.uuid4().hex

    manifest = {
        "source_fingerprint": executing_source,
        "run_id": run_id,
        "model_id": mid,
        "protocol": protocol,
        "data_bindings": data_evidence + getattr(model, "input_datasets", []),
        "model_definition": getattr(model, "definition", None),
        "scenario_review": getattr(model,"scenario_review",None),
        "implementation_note": getattr(model, "implementation_note", None),
        "llm_calls": getattr(model, "llm_audit", []),
        "requested": {"parameters": params_in, "ticks": ticks,
                      "dt": dt, "seed": seed, "experiment": experiment,
                      "interventions":copy.deepcopy(interventions or [])},
        "actual": {
            "parameters": {k: _jsonable(v) for k, v in clean.items()},
            "effective_parameters": initial_effective,
            "ctor_kwargs": {k: _jsonable(v) for k, v in ctor_kwargs.items()},
            "n_steps": max(0, len(obs_out)-1),
            "dt_used": dt * getattr(model, "dt_scale", 1.0)
            if protocol == "fixed_step" else dt,
            "final_t": round(final_t, 9),
            "n_obs": len(obs_out),
            "time_unit": getattr(model, "time_unit", "模型时间") if protocol != "demo" else "n/a",
        },
        "param_issues": [i.as_dict() for i in issues],
        "param_effect": effect,
        "rng": {"seed": seed, "experiment": experiment,
                "stream_key": ["model", mid],
                "algorithm": "pcg64(numpy.default_rng) via RngStreams"},
        "clocks": {"sim_time": round(final_t, 9), "optim_iter": n_iter,
                   "llm_wall_seconds": sum(c.get("duration_s", 0) for c in getattr(model, "llm_audit", [])), "batch": 0},
        "checkpoint": None if checkpoint is None else
                      {k: v for k, v in checkpoint.items()
                       if k in ("state_fidelity", "resumable", "t", "note")},
        "events_n": len(events_dump),
        "state_frame_count": len(state_frames),
        "state_every": state_every if capture_state else None,
        "interventions": applied_ivs,
        "started_at": started_at, "finished_at": finished_at,
        "duration_s": round(duration, 3),
        "warnings": [i.message for i in issues if i.kind in
                     ("unknown", "alias", "coerced", "type_error", "runtime_key")],
        "runtime_version": "2.1",
    }
    from .output_contract import output_contract
    manifest["output_contract"] = output_contract(mid)
    for binding in data_evidence:
        if binding.get('compatibility_status')!='units_verified' or binding.get('scope_status')!='verified':
            manifest['warnings'].append('数据已数值接入，但单位或地区/主体范围尚未完整声明；不据此认定现实政策适用性：'+binding['parameter'])
    manifest["observed_output_types"] = {
        key: sorted({_type_of(row[key]) for row in obs_out if key in row})
        for key in {k for row in obs_out for k in row}}
    if getattr(model, "implementation_note", None):
        manifest["warnings"].append(model.implementation_note)
    from .fidelity import load_reviews
    review = load_reviews().get(mid, {})
    manifest["fidelity"] = {"level": review.get("fidelity", "unreviewed"),
                            "basis": review.get("basis", "未独立审查；执行成功不等于科学有效性已验证")}
    if manifest["fidelity"]["level"] in ("prototype", "method_demo", "lite", "unreviewed"):
        manifest["warnings"].append("实现级别 " + manifest["fidelity"]["level"] + "：" + manifest["fidelity"]["basis"])
    if getattr(model, "requires_external", False) and getattr(model, "budget_reported", False):
        manifest["warnings"].append("LLM调用预算已用尽，后续时间步复用最后的真实计划，未新增推理调用")
    domain_events = []
    for ev in events_dump:
        if hasattr(ev, "__dict__"):
            ev = vars(ev)
        if isinstance(ev, dict):
            domain_events.append(_jsonable(ev))
    domain_events.extend({"sim_t": iv.get("actual_t", iv.get("requested_t")),
                          "etype": "intervention" if iv.get("applied") else "intervention_failed",
                          **iv} for iv in applied_ivs)
    for fr in state_frames:
        fr["run_id"] = run_id
    assert_loaded_source()
    return RunResult(model_id=mid, observations=obs_out,
                     manifest=manifest, issues=issues, state_frames=state_frames,
                     events=domain_events, checkpoint=checkpoint)


def run_model(mid: str, parameters: dict | None = None,
              ticks: int = 200, dt: float = 0.1, seed: int = 0) -> list:
    """兼容入口：语义与旧签名一致（返回 observations 列表）。
    内部走 run_model_full（单次初始化、参数校验宽松模式、派生随机流）。"""
    rr = run_model_full(mid, parameters=parameters, ticks=ticks, dt=dt,
                        seed=seed, with_time=False)
    return rr.observations
