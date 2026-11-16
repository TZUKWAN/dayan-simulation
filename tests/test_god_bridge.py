"""R6-T10 GOD 桥接真适配验收测试（审计 D9/D10 修复验证）。

判据：
- MsimGodSession 完整实现 GOD 路由的调用面（12 方法/属性）
- to_status() 返回带 model_dump() 的快照，字段与 GOD LiveExperimentStatus 对齐
- ask/intervene 接收 GOD 请求形状（.question/.target/.instruction）
- register_session 按 Manager 真实键结构 (workspace, hyp, exp) 三元组预插入
- 用 stub manager 走真实注册路径（非降级路径）：get() 返回鸭子会话
- run_step 真实推进 Kernel 且守恒；_tick 不再脱钩（step_count=kernel.tick_no）
运行：python tests/test_god_bridge.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.kernel import Kernel, KernelConfig  # noqa: E402
from src.kernel.god_bridge import (MsimGodSession, bridge_status,  # noqa: E402
                                   register_session)
import src.packs.polecon as polecon  # noqa: E402
from src.agents.decisions import rule_decision  # noqa: E402


class StubManager:
    """忠实模拟 GOD LiveExperimentManager 的键结构与查找逻辑。"""

    def __init__(self):
        self._sessions: dict[tuple[str, str, str], object] = {}

    def _key(self, workspace_path, hypothesis_id, experiment_id):
        from pathlib import Path as _P
        return (str(_P(workspace_path).resolve()), hypothesis_id, experiment_id)

    def get(self, *, workspace_path, hypothesis_id, experiment_id):
        s = self._sessions.get(
            self._key(workspace_path, hypothesis_id, experiment_id))
        if s is None:
            raise KeyError("Live session not found")
        return s


class StubRequest:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class StubTarget:
    def __init__(self, type="agent", agent_id=None):
        self.type = type
        self.agent_id = agent_id

    def model_dump(self, exclude_none=False):
        return {"type": self.type, "agent_id": self.agent_id}


def _make_kernel(n=16, ticks=3):
    pack = polecon.make_pack(population={"n": n}, institutions={}, seed=7,
                             intervention={})
    kernel = Kernel(pack, KernelConfig(seed=7))
    kernel.init_world()
    for _ in range(ticks):
        for a in kernel.agents:
            pack.action_handler(a, rule_decision(a, pack.world), kernel)
        kernel.step()
    return kernel, pack


def test_full_god_surface():
    kernel, _ = _make_kernel()
    sess = MsimGodSession(kernel, "msim:test", workspace_path=".")
    for attr in ("status", "init", "run_step", "ask", "intervene", "set_auto",
                 "pause", "stop", "sync_agents_from_config", "to_status",
                 "add_subscriber", "remove_subscriber", "broadcast"):
        assert hasattr(sess, attr), f"缺 GOD 调用面成员 {attr}"
    snap = sess.to_status()
    d = snap.model_dump()
    # LiveExperimentStatus 字段对齐
    for f in ("hypothesis_id", "experiment_id", "workspace_path", "status",
              "step_count", "auto_running", "default_tick", "error"):
        assert f in d, f"快照缺 LiveExperimentStatus 字段 {f}"
    print(f"[PASS] GOD 调用面：13 成员 + LiveExperimentStatus 字段对齐"
          f"（step_count={d['step_count']} 与 kernel.tick_no 同步——D10 修复）")


def test_register_real_path():
    kernel, _ = _make_kernel()
    mgr = StubManager()
    sess = register_session(mgr, kernel, "msim:test", workspace_path=".")
    # GOD manager.get() 的真实查找逻辑应命中鸭子会话
    got = mgr.get(workspace_path=".", hypothesis_id="msim", experiment_id="msim:test")
    assert got is sess
    assert got.status not in ("stopped", "failed")
    print("[PASS] 真实注册路径：三元组键预插入，manager.get() 命中鸭子会话"
          "（非降级路径）")


def test_ask_intervene_god_shapes():
    kernel, _ = _make_kernel()
    sess = MsimGodSession(kernel, "msim:test", llm_client=None)
    # ask(AskRequest) 形状
    resp = asyncio.run(sess.ask(StubRequest(
        question="你最近怎么样？", target=StubTarget("agent", 2))))
    d = resp.model_dump()
    assert d["type"] == "ask" and "result" in d and "command_id" in d
    # intervene(InterveneRequest) 形状
    resp2 = asyncio.run(sess.intervene(StubRequest(
        instruction="self", target=StubTarget("agent", 0))))
    d2 = resp2.model_dump()
    assert d2["type"] == "intervene" and '"ok"' in d2["result"]
    print("[PASS] ask/intervene：GOD 请求形状（question/target/instruction）兼容")


def test_run_step_conserves():
    kernel, pack = _make_kernel(ticks=2)
    sess = MsimGodSession(kernel, "msim:test")
    before = kernel.tick_no
    snap = asyncio.run(sess.run_step())
    assert kernel.tick_no == before + 1
    assert kernel.max_invariant_residual() < 1e-6
    assert snap.model_dump()["step_count"] == kernel.tick_no
    print(f"[PASS] run_step：kernel.tick_no {before}→{kernel.tick_no}，"
          f"快照 step_count 同步，守恒 {kernel.max_invariant_residual():.1e}")


def test_degrade_and_status():
    kernel, _ = _make_kernel()
    sess = MsimGodSession(kernel, "msim:x")
    assert asyncio.run(sess.pause()).status == "waiting"
    assert asyncio.run(sess.stop()).status == "stopped"
    st = bridge_status()
    assert st["msim_kernel_ready"] and isinstance(st["god_available"], bool)
    print(f"[PASS] 生命周期与状态报告（GOD available={st['god_available']}）")


if __name__ == "__main__":
    test_full_god_surface()
    test_register_real_path()
    test_ask_intervene_god_shapes()
    test_run_step_conserves()
    test_degrade_and_status()
    print("\n===== R6-T10 GOD 桥接真适配：全部通过 =====")
