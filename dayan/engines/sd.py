"""R7-a EquationEngine：系统动力学（存量-流量 + 因果图）。

声明式规约（实验即数据）：
  spec = {
    "stocks": {"T": {"init": 90.0}},          # 存量（状态变量）
    "flows": [ {"name":"out","expr":"k*(T-Tenv)","from":"T"} ],  # from=流出该存量
    "aux":   {"Tenv": "20"},                   # 辅助变量（每步先算）
    "params":{"k": 0.07},
    "links": [{"from":"T","to":"out","polarity":"-"}],  # 因果图元数据
  }
求导语义：dStock/dt = Σ(流入) − Σ(流出)；辅助变量先求。
实现 DayanModel 的 ODE 协议（derivatives），由统一编排器 RK4 积分。
含因果图 mermaid 渲染（设计文档 §1.1 因果流图）。
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np

from ..core import DayanModel

_SAFE_NS = {
    "abs": abs, "min": min, "max": max, "exp": np.exp, "log": np.log,
    "sqrt": np.sqrt, "sin": np.sin, "cos": np.cos, "pow": np.power,
}


class StockFlowSystem(DayanModel):
    """声明式存量-流量系统（ODE 协议）。"""

    model_id = "SD.system"
    clock_type = "ode"

    def __init__(self, spec: dict, name: str = "SD.system"):
        self.spec = spec
        self.name = name
        self.stock_names: list[str] = list(spec.get("stocks", {}).keys())
        self.params: dict[str, float] = dict(spec.get("params", {}))
        self.aux_exprs: dict[str, str] = dict(spec.get("aux", {}))
        self.flows: list[dict] = list(spec.get("flows", []))
        self.links: list[dict] = list(spec.get("links", []))
        self.nonneg = {k: bool(v.get("nonneg", False))
                       for k, v in spec.get("stocks", {}).items()}
        self.x = np.array([float(v.get("init", 0.0))
                           for v in spec.get("stocks", {}).values()])
        self.inflows: dict[str, list[str]] = {k: [] for k in self.stock_names}
        self.outflows: dict[str, list[str]] = {k: [] for k in self.stock_names}
        for f in self.flows:
            tgt = f.get("into") or f.get("to")
            src = f.get("from")
            if tgt and tgt in self.inflows:
                self.inflows[tgt].append(f["name"])
            if src and src in self.outflows:
                self.outflows[src].append(f["name"])

    # ---- ODE 协议 ----
    def _namespace(self, x: np.ndarray) -> dict:
        ns = dict(_SAFE_NS)
        ns.update(self.params)
        ns.update(dict(zip(self.stock_names, x)))
        for aname, aexpr in self.aux_exprs.items():
            ns[aname] = eval(aexpr, {"__builtins__": {}}, ns)  # noqa: S307（内部规约）
        return ns

    def derivatives(self, t: float, x: np.ndarray) -> np.ndarray:
        # 数值警告全程抑制（宕机教训：eval 空 builtins 环境下 numpy 溢出触发
        # RuntimeWarning → 警告系统内部 __import__ 查询 → KeyError '__import__'。
        # 溢出应优雅传播 inf/nan，由发散监测与 validate_state 兜底）
        with np.errstate(all="ignore"):
            ns = self._namespace(x)
            dx = np.zeros(len(self.stock_names))
            for i, sname in enumerate(self.stock_names):
                d = 0.0
                for fname in self.inflows[sname]:
                    expr = next(f["expr"] for f in self.flows
                                if f["name"] == fname)
                    d += float(eval(expr, {"__builtins__": {}}, dict(ns)))
                for fname in self.outflows[sname]:
                    expr = next(f["expr"] for f in self.flows
                                if f["name"] == fname)
                    d -= float(eval(expr, {"__builtins__": {}}, dict(ns)))
                for f in self.flows:
                    tgt = f.get("net_stock")
                    if tgt == sname:
                        d += float(eval(f["expr"], {"__builtins__": {}},
                                        dict(ns)))
                dx[i] = d
        return dx

    # 供编排器 ODE 分支使用的主状态
    @property
    def x(self) -> np.ndarray:
        return self._x

    @x.setter
    def x(self, v):
        self._x = np.asarray(v, dtype=float)
        # 非负截断（声明 nonneg 的存量）
        for i, s in enumerate(self.stock_names):
            if self.nonneg.get(s) and self._x[i] < 0:
                self._x[i] = 0.0

    def initialize(self, context, parameters, population, topology, rng):
        if parameters:
            self.params.update(parameters)
        self.x = np.array([float(v.get("init", 0.0))
                           for v in self.spec.get("stocks", {}).values()])

    def observe(self) -> dict:
        ns = self._namespace(self.x)
        return {k: round(float(ns[k]), 6) for k in self.stock_names}

    def validate_state(self) -> list[str]:
        errs = []
        for i, s in enumerate(self.stock_names):
            if self.nonneg.get(s) and self._x[i] < 0:
                errs.append(f"存量 {s} 为负")
        return errs

    def intervene(self, action: dict):
        """干预：设置参数或存量（显式，规范 2.2）。"""
        if "set_param" in action:
            self.params[action["set_param"]] = float(action["value"])
        if "set_stock" in action:
            idx = self.stock_names.index(action["set_stock"])
            self._x[idx] = float(action["value"])

    def snapshot(self) -> dict:
        return {"x": self.x.tolist(), "params": dict(self.params)}

    def restore(self, state: dict):
        self.x = np.asarray(state["x"], dtype=float)
        self.params.update(state.get("params", {}))

    # ---- 因果图渲染（设计文档 §1.1）----
    def causal_graph_mermaid(self) -> str:
        lines = ["graph LR"]
        for l in self.links:
            pol = l.get("polarity", "+")
            sign = "+" if pol == "+" else "-"
            lines.append(f"    {l['from']} --{sign}--> {l['to']}")
        return "\n".join(lines)


def teacup_spec(k=0.07, t_env=20.0, t0=90.0) -> dict:
    """茶杯冷却（规范 SD 基准）：dT/dt = -k(T - Tenv)，解析解指数衰减。"""
    return {
        "stocks": {"T": {"init": t0}},
        "flows": [{"name": "cooling", "expr": "k * (T - Tenv)", "from": "T"}],
        "params": {"k": k, "Tenv": t_env},
        "links": [{"from": "T", "to": "cooling", "polarity": "-"}],
    }
