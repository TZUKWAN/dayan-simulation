"""GOD 控制室桥接（v2 设计 §7 R6；审计 T10 真适配版）。

GOD 后端（agentsociety2.backend.routers.live_experiments）的会话管理：
- `manager = LiveExperimentManager()` 模块级单例
- `manager._sessions: dict[(workspace_path, hypothesis_id, experiment_id), LiveExperimentSession]`
- `manager.get(...)` 仅做字典查找（无类型检查）→ **预插入鸭子会话即可零侵入注入**
- 路由对 session 的调用面（已从源码提取）：
  status / init() / run_step(tick) / ask(AskRequest) / intervene(InterveneRequest)
  / set_auto(AutoRequest) / pause() / stop() / sync_agents_from_config()
  / to_status().model_dump() / add_subscriber(ws) / remove_subscriber(ws) / broadcast(payload)

MsimGodSession 实现该鸭子接口，内部驱动 msim Kernel。
GOD 未安装时本模块照常导入（会话工厂模式）；安装后一行注册：
  register_session(manager, kernel, "msim:demo", workspace, hyp, client)
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.kernel import Kernel, KernelConfig  # noqa: E402

# GOD 会话状态（LiveStatus 字面量集）
WAITING = "waiting"
RUNNING = "running_step"
ASKING = "asking"
INTERVENING = "intervening"
STOPPED = "stopped"


class _StatusSnapshot:
    """LiveExperimentStatus 兼容快照（duck pydantic：提供 model_dump）。"""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self, exclude_none: bool = False):
        return {k: v for k, v in self.__dict__.items()
                if not (exclude_none and v is None)}


class _CmdResponse:
    """CommandResponse 兼容（duck）。"""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self, exclude_none: bool = False):
        return {k: v for k, v in self.__dict__.items()
                if not (exclude_none and v is None)}


class MsimGodSession:
    """msim Kernel → GOD 控制室会话（鸭子实现 GOD 调用面）。"""

    def __init__(self, kernel: Kernel, experiment_id: str,
                 workspace_path: str = ".", hypothesis_id: str = "msim",
                 llm_client=None, default_tick: int = 1):
        self.kernel = kernel
        self.experiment_id = experiment_id
        self.workspace_path = str(workspace_path)
        self.hypothesis_id = hypothesis_id
        self.llm_client = llm_client
        self.default_tick = default_tick
        self._status = WAITING
        self._auto_running = False
        self._error: Optional[str] = None
        self._subscribers: list[Any] = []

    # ---- status 属性（路由检查 status in ("stopped","failed")）----
    @property
    def status(self) -> str:
        return self._status

    @property
    def step_count(self) -> int:
        return self.kernel.tick_no

    # ---- 生命周期 ----
    async def init(self) -> None:
        self._status = WAITING  # no-op：msim 世界已在 kernel.init_world 就绪

    async def pause(self) -> "_StatusSnapshot":
        self._status = WAITING
        return self.to_status()

    async def stop(self) -> "_StatusSnapshot":
        self._status = STOPPED
        return self.to_status()

    async def sync_agents_from_config(self) -> _StatusSnapshot:
        return self.to_status()

    async def set_auto(self, request: Any) -> "_StatusSnapshot":
        """自动执行模式（AutoRequest.running/auto bool）。"""
        running = bool(getattr(request, "running",
                               getattr(request, "auto", False)))
        self._auto_running = running
        return self.to_status()

    # ---- 核心三键 ----
    async def run_step(self, tick: Optional[int] = None) -> "_StatusSnapshot":
        """推进一步：LLM 意向收集 + 规则填充 + action_handler + kernel.step。"""
        self._status = RUNNING
        try:
            pack = self.kernel.pack
            # T17: 决策循环走包钩子（与 run_spec 同一协议，无拷贝）
            decisions: dict[int, dict] = {}
            if self.llm_client is not None and hasattr(pack, "collect_llm_requests"):
                from src.agents.decisions import LLMBatchDecider
                decider = getattr(self, "_decider", None)
                if decider is None:
                    decider = LLMBatchDecider(self.llm_client)
                    self._decider = decider
                reqs = pack.collect_llm_requests(self.kernel.tick_no)
                if reqs:
                    decisions.update(decider.decide_batch(reqs, pack=pack))
            if hasattr(pack, "world") and hasattr(pack, "rule_decision"):
                for a in self.kernel.agents:
                    if not getattr(a, "llm", False) or a.id not in decisions:
                        decisions[a.id] = pack.rule_decision(a)
            for aid, d in decisions.items():
                pack.action_handler(self.kernel.agents[aid], d, self.kernel)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.kernel.step)
            await self.broadcast({"event": "step", "tick": self.kernel.tick_no})
        except Exception as e:  # noqa: BLE001
            self._error = str(e)
            self._status = "failed"
            raise
        self._status = WAITING
        return self.to_status()

    async def ask(self, request: Any) -> "_CmdResponse":
        """向单个/all agent 提问（request.question/.target.type/.target.agent_id）。"""
        self._status = ASKING
        target = getattr(request, "target", None)
        ttype = getattr(target, "type", "agent") if target else "agent"
        agent_id = getattr(target, "agent_id", None) if target else None
        question = request.question
        if self.llm_client is None:
            result = "[msim] 未配置 LLM 客户端"
        else:
            if ttype == "all_agents":
                agent = self.kernel.agents[0]
            else:
                agent = self.kernel.agents[int(agent_id or 0)]
            pos = getattr(agent, "position", "?")
            msgs = [{"role": "system",
                     "content": "你是微型社会中的居民，简要回答。"},
                    {"role": "user",
                     "content": f"你目前是{pos}。{question} 一两句话。"}]
            result = self.llm_client.chat(msgs, temperature=0.3, max_tokens=200) \
                or "[无响应]"
        self._status = WAITING
        return _CmdResponse(command_id=str(uuid.uuid4()), type="ask",
                            result=result, status=self._status,
                            step_count=self.step_count, target=None)

    async def intervene(self, request: Any) -> "_CmdResponse":
        """干预：request.instruction 映射为决策，经 action_handler 裁决。"""
        self._status = INTERVENING
        target = getattr(request, "target", None)
        agent_id = int(getattr(target, "agent_id", 0) or 0) if target else 0
        instruction = str(request.instruction).strip().lower()
        pack = self.kernel.pack
        decision = {"action": instruction}
        ok = True
        if hasattr(pack, "action_handler"):
            pack.action_handler(self.kernel.agents[agent_id], decision,
                                self.kernel)
        else:
            ok = False
        self._status = WAITING
        return _CmdResponse(command_id=str(uuid.uuid4()), type="intervene",
                            result=json.dumps({"ok": ok,
                                               "decision": decision},
                                              ensure_ascii=False),
                            status=self._status, step_count=self.step_count)

    # ---- 状态快照 ----
    def to_status(self) -> "_StatusSnapshot":
        pack = self.kernel.pack
        agents_summary = []
        for a in self.kernel.agents[:20]:
            agents_summary.append({
                "id": getattr(a, "id", -1),
                "position": getattr(a, "position", "?"),
                "savings": round(float(getattr(a, "savings", 0.0)), 1),
            })
        metrics = {}
        for k, fn in getattr(pack, "measure_hooks", {}).items():
            if fn is None:
                continue
            try:
                metrics[k] = round(float(fn(self.kernel)), 4)
            except Exception:
                continue
        return _StatusSnapshot(
            hypothesis_id=self.hypothesis_id,
            experiment_id=self.experiment_id,
            workspace_path=self.workspace_path,
            status=self._status,
            step_count=self.step_count,
            simulation_time=None,
            auto_running=self._auto_running,
            default_tick=self.default_tick,
            current_command=None,
            error=self._error,
            n_agents=len(self.kernel.agents),
            agents=agents_summary,
            metrics=metrics,
            invariant_residual=self.kernel.max_invariant_residual(),
        )

    # ---- 广播 ----
    def add_subscriber(self, ws) -> None:
        self._subscribers.append(ws)

    def remove_subscriber(self, ws) -> None:
        if ws in self._subscribers:
            self._subscribers.remove(ws)

    async def broadcast(self, payload: dict) -> None:
        for ws in list(self._subscribers):
            try:
                await ws.send_text(json.dumps(payload, ensure_ascii=False))
            except Exception:
                self._subscribers.remove(ws)


def register_session(manager: Any, kernel: Kernel, experiment_id: str,
                     workspace_path: str = ".", hypothesis_id: str = "msim",
                     llm_client=None) -> MsimGodSession:
    """把 msim 会话按 GOD 的真实键结构预插入 manager._sessions。

    manager.get()/get_or_create() 仅做字典查找，预插入的鸭子会话即被
    控制室使用（零 GOD 源码改动）。experiment_id 建议以 "msim" 开头。
    """
    session = MsimGodSession(kernel, experiment_id,
                             workspace_path=workspace_path,
                             hypothesis_id=hypothesis_id,
                             llm_client=llm_client)
    key = (str(Path(workspace_path).resolve()), hypothesis_id, experiment_id)
    if hasattr(manager, "_sessions") and isinstance(manager._sessions, dict):
        manager._sessions[key] = session
    else:
        raise AttributeError("manager 缺少 _sessions 字典（GOD 版本不兼容）")
    return session


def bridge_status() -> dict:
    god_available = False
    try:
        import agentsociety2  # noqa: F401
        god_available = True
    except ImportError:
        pass
    return {"msim_kernel_ready": True, "god_available": god_available,
            "bridge": "src/kernel/god_bridge.py",
            "key_structure": "(workspace_path, hypothesis_id, experiment_id)",
            "note": "GOD 未安装时本模块照常导入；装后 register_session 注入"}


if __name__ == "__main__":
    import random

    print(json.dumps(bridge_status(), ensure_ascii=False, indent=2))
    import src.packs.polecon as polecon
    from src.agents.decisions import rule_decision
    pack = polecon.make_pack(population={"n": 12}, institutions={}, seed=7,
                             intervention={})
    k = Kernel(pack, KernelConfig(seed=7))
    k.init_world()
    for _ in range(3):
        for a in k.agents:
            pack.action_handler(a, rule_decision(a, pack.world), k)
        k.step()
    sess = MsimGodSession(k, "msim:demo")
    snap = sess.to_status()
    print("\n=== to_status().model_dump()（GOD 前端格式）===")
    d = snap.model_dump()
    print(json.dumps({k2: v for k2, v in d.items() if k2 != "agents"},
                     ensure_ascii=False, indent=2))
    print("agents[0]:", d["agents"][0])
