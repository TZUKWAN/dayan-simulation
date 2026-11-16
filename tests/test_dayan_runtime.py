"""WP3/WP4/WP5 统一运行层测试：单次初始化、可复现、非整步终点、
参数生效核验、别名、未知参数、检查点诚实降级、sim_t 时间戳、EventQueue 修复。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dayan.core import DayanModel, EventQueue, DomainEvent  # noqa: E402
from dayan.runtime import (run_model_full, validate_params,  # noqa: E402
                           param_contract, resume_from_checkpoint)


class InitCountModel(DayanModel):
    """记录 initialize 次数的小模型（验证单次初始化）。"""
    model_id = "TEST_INITCOUNT"
    clock_type = "fixed_step"

    def __init__(self, n=5):
        self.n = n
        self.n_init = 0
        self.v = 0.0

    def initialize(self, context, parameters, population, topology, rng):
        self.n_init += 1
        self.n = int(parameters.get("n", self.n))

    def step(self, t, dt):
        self.v += dt

    def observe(self):
        return {"v": self.v, "n": self.n, "n_init": self.n_init}


class StochToy(DayanModel):
    """随机玩具模型：每步消耗正态噪声（用于种子流与检查点续算测试）。"""
    model_id = "TEST_STOCH"
    clock_type = "fixed_step"

    def __init__(self):
        self.x = 0.0
        self.rng = None

    def initialize(self, context, parameters, population, topology, rng):
        self.rng = rng
        self.x = 0.0

    def step(self, t, dt):
        self.x += float(self.rng.normal(0, 1)) * 0.1

    def observe(self):
        return {"x": round(self.x, 9)}


class SnapshotToy(DayanModel):
    """实现 snapshot/restore 的确定性玩具模型（检查点 full 通道测试）。"""
    model_id = "TEST_SNAPTOY"
    clock_type = "fixed_step"

    def __init__(self, x0=0.0):
        self.x = float(x0)
        self.t_last = 0.0

    def initialize(self, context, parameters, population, topology, rng):
        self.x = float(parameters.get("x0", 0.0))
        self.t_last = 0.0

    def step(self, t, dt):
        self.x += dt * 2.0
        self.t_last = t

    def observe(self):
        return {"x": self.x}

    def snapshot(self):
        return {"x": self.x, "t_last": self.t_last}

    def restore(self, state):
        self.x = state["x"]
        self.t_last = state["t_last"]


def _reg(mid, cls):
    from dayan.model_index import _FIXED_STEP
    _FIXED_STEP[mid] = cls
    from dayan import model_index as mi
    mi.ALL_INDEX[mid] = cls


_reg("TEST_INITCOUNT", InitCountModel)
_reg("TEST_STOCH", StochToy)
_reg("TEST_SNAPTOY", SnapshotToy)


def run_tests():
    passed, failed = 0, 0

    def check(name, cond, detail=""):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"[PASS] {name}")
        else:
            failed += 1
            print(f"[FAIL] {name} {detail}")

    # --- 1. 单次初始化 ---
    rr = run_model_full("TEST_INITCOUNT", parameters={"n": 7}, ticks=10)
    check("单次初始化（simulate/fixed_step 不再双重 init）",
          rr.observations[-1]["n_init"] == 1,
          f"n_init={rr.observations[-1]['n_init']}")
    check("构造期参数生效（n=7）", rr.observations[-1]["n"] == 7)

    # --- 2. 同种子可复现 ---
    a = run_model_full("TEST_STOCH", ticks=30, seed=123)
    b = run_model_full("TEST_STOCH", ticks=30, seed=123)
    check("同种子复现（随机模型轨迹逐条一致）",
          [o["x"] for o in a.observations] == [o["x"] for o in b.observations])
    c = run_model_full("TEST_STOCH", ticks=30, seed=124)
    check("不同种子轨迹不同",
          [o["x"] for o in a.observations] != [o["x"] for o in c.observations])

    # --- 3. 非整步终点 ---
    rr13 = run_model_full("TEST_INITCOUNT", ticks=13, dt=0.1)
    check("非整步终点 final_t 精确（13×0.1=1.3 不越界）",
          abs(rr13.manifest["actual"]["final_t"] - 1.3) < 1e-9,
          f"final_t={rr13.manifest['actual']['final_t']}")
    check("非整步终点观测数 = ticks+1", len(rr13.observations) == 14)

    # --- 4. sim_t 时间戳 ---
    rr5 = run_model_full("TEST_INITCOUNT", ticks=5, dt=0.1)
    ts = [o["sim_t"] for o in rr5.observations]
    check("观测带单调 sim_t", ts == sorted(ts) and ts[0] == 0.0
          and abs(ts[-1] - 0.5) < 1e-9, f"ts={ts}")

    # --- 5. 参数生效核验 ---
    eff = rr.manifest["param_effect"]
    check("生效核验 applied=True", eff.get("n", {}).get("applied") is True,
          f"effect={eff}")

    # --- 6. 别名映射 ---
    clean, issues = validate_params("TEST_INITCOUNT", {"n_agents": 9})
    check("别名 n_agents→n", clean.get("n") == 9 and
          any(i.kind == "alias" for i in issues),
          f"clean={clean} issues={[i.kind for i in issues]}")

    # --- 7. 未知参数：宽松留痕 / 严格拒绝 ---
    clean2, issues2 = validate_params("TEST_INITCOUNT", {"bogus_param": 1})
    check("未知参数宽松模式留痕", any(i.kind == "unknown" for i in issues2)
          and "bogus_param" not in clean2)
    try:
        validate_params("TEST_INITCOUNT", {"bogus_param": 1}, strict=True)
        check("未知参数严格模式拒绝", False, "未抛出")
    except ValueError:
        check("未知参数严格模式拒绝", True)

    # --- 8. 类型改写留痕 ---
    clean3, issues3 = validate_params("TEST_INITCOUNT", {"n": 10.7})
    check("float→int 改写留痕", clean3.get("n") == 11 and
          any(i.kind == "coerced" for i in issues3),
          f"clean3={clean3}")

    # --- 9. 检查点诚实降级 ---
    rr_chk = run_model_full("TEST_INITCOUNT", ticks=10,
                            checkpoint_at=5)
    check("无 snapshot 模型检查点 partial 如实标注",
          rr_chk.manifest["checkpoint"]["state_fidelity"] == "partial"
          and rr_chk.manifest["checkpoint"]["resumable"] is False)
    # 构造一个 partial 检查点并尝试续算 → 必须明确报错而不是假装恢复
    partial_chk = {"model_id": "TEST_INITCOUNT", "protocol": "fixed_step",
                   "t": 0.5, "rng_state": np.random.default_rng(0)
                   .bit_generator.state, "parameters": {},
                   "model_snapshot": {}, "state_fidelity": "partial",
                   "resumable": False}
    try:
        resume_from_checkpoint(partial_chk, 5, 0.1)
        check("partial 检查点续算被拒绝", False, "未抛出")
    except ValueError as e:
        check("partial 检查点续算被拒绝", "不可续算" in str(e))

    # --- 10. full 检查点续算 ≈ 不中断运行 ---
    whole = run_model_full("TEST_SNAPTOY", ticks=20, dt=0.1,
                           parameters={"x0": 1.0})
    part1 = run_model_full("TEST_SNAPTOY", ticks=10, dt=0.1,
                           parameters={"x0": 1.0}, checkpoint_at=10)
    # 手工取 full 检查点（save 后续算）
    from dayan.runtime import save_checkpoint
    from dayan.model_index import resolve
    _, factory = resolve("TEST_SNAPTOY")
    m = factory()
    m.initialize({}, {"x0": 1.0}, None, None, np.random.default_rng(0))
    rng2 = np.random.default_rng(0)
    for _ in range(10):
        m.step(0.0, 0.1)
    chk = save_checkpoint(m, 1.0, rng2, {"x0": 1.0}, "fixed_step")
    cont = resume_from_checkpoint(chk, 10, 0.1)
    check("full 检查点续算终值 = 不中断运行终值",
          abs(cont.observations[-1]["x"] -
              whole.observations[-1]["x"]) < 1e-9,
          f"resumed={cont.observations[-1]['x']} "
          f"whole={whole.observations[-1]['x']}")

    # --- 11. EventQueue 零时间死循环 → RuntimeError（修复 AttributeError）---
    eq = EventQueue(max_zero_time_loop=3)
    for i in range(6):
        eq.push(DomainEvent(time=1.0, etype="zero", seq=i))
    raised = None
    try:
        for _ in range(10):
            eq.pop(1.0)
    except RuntimeError as e:
        raised = str(e)
    except AttributeError as e:
        raised = f"AttributeError(未修复): {e}"
    check("EventQueue 零时间死循环抛 RuntimeError",
          raised is not None and "AttributeError" not in raised,
          f"raised={raised}")

    # --- 12. 参数合同接口 ---
    pc = param_contract("TEST_INITCOUNT")
    check("param_contract 暴露形参", "n" in pc["params"])

    # --- 13. run_model 兼容入口跨协议 ---
    from dayan.model_index import run_model as compat_run
    obs = compat_run("TEST_INITCOUNT", parameters={"n": 3}, ticks=4)
    check("run_model 兼容入口返回 list", isinstance(obs, list)
          and len(obs) == 5 and obs[-1]["n"] == 3)
    # met_demo / rl_demo / jump_sim 协议各抽一个
    from dayan.model_index import resolve
    demo_met = next(m for m in ["MET001", "MET002", "MET003"]
                    if resolve(m)[0] is not None) if resolve("MET001")[
        0] else None
    if demo_met:
        o2 = compat_run(demo_met, ticks=3)
        check(f"met_demo 兼容运行 {demo_met}", isinstance(o2, list)
              and len(o2) >= 1)
    o3 = compat_run("NET052", ticks=5)
    check("ODE(SIS) 兼容运行", len(o3) == 6)
    o4 = compat_run("NET107", ticks=5)   # BML fixed_step
    check("fixed_step(BML) 兼容运行", len(o4) == 6)
    o5 = compat_run("BEH112", ticks=1)   # rl_demo
    check("rl_demo 兼容运行", isinstance(o5, list) and len(o5) >= 1)

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run_tests())
