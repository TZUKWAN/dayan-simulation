"""Admission, scale intent and full-state retention for large declarative runs."""
from __future__ import annotations

import ast
import math

import psutil

from .limits import BudgetExceeded, limits

LEGACY_AGENTS = 2000
ARRAY_KERNEL = "numpy-synchronous-v1"
_MB = 1024 * 1024
def scale_intent(source):
    from .research.quantity_contract import quantity_contract
    return quantity_contract(source)


def check_scale(request, compiled):
    if request.get("conflict"):
        raise ValueError(request["conflict"])
    if request.get("grid") and compiled["grid"] != request["grid"]:
        raise ValueError(f"原文网格 {request['grid']} 与实际定义 {compiled['grid']} 不一致")
    if request.get("grid_degree") and compiled.get("grid_degree") != request["grid_degree"]:
        raise ValueError(f"原文要求{request['grid_degree']}邻域，实际定义为{compiled.get('grid_degree')}邻域")
    if compiled.get("grid_degree") in request.get("excluded_grid_degrees", []):
        raise ValueError("实际定义使用了原文明确排除的邻域阶数")
    if request.get("boundary") and compiled.get("grid"):
        actual = compiled.get("boundary", "periodic")
        expected = request["boundary"]
        if (expected == "nonperiodic" and actual == "periodic") or (expected != "nonperiodic" and actual != expected):
            raise ValueError(f"原文边界 {expected} 与实际定义 {actual} 不一致")
    if request.get("granularity") == "individual" and compiled["kernel"] == "stock":
        raise ValueError("原文要求逐主体计算与状态，纯存量模型没有实际个体，不能替代")
    aggregate_population = compiled["kernel"] == "stock" and not request.get("grid") and request.get("granularity") != "individual" and request.get("population_role") not in (
        None, "主体", "智能体", "个体", "代理")
    if not aggregate_population and request.get("entities") is not None and request["entities"] != compiled["entities"]:
        raise ValueError(f"原文及已审查方案要求 {request['entities']:,} 个主体，实际定义为 {compiled['entities']:,}")
    populations = request.get("populations", {})
    if len(populations) > 1:
        actual = compiled.get("populations", {})
        if isinstance(actual,list):
            by_role={}
            for group in actual:
                label=group['label']
                by_role[label]=by_role.get(label,0)+group['count']
            actual=by_role
        if any(actual.get(role) != count for role, count in populations.items()):
            raise ValueError("各类主体实际数量与原文不一致，须提供可执行的人口分组：" + str(populations))


def _memory():
    cap = limits()
    memory = psutil.virtual_memory()
    rss = psutil.Process().memory_info().rss
    # Workers share the host. Leave headroom for the application and serialization.
    available = max(0, min((memory.available * 3) // 8, cap.memory_bytes - max(rss, 128*_MB) - 64*_MB))
    return cap, memory.available, available


def capacity():
    cap, host, work = _memory()
    return {"kernel": ARRAY_KERNEL, "legacy_dsl_entities": LEGACY_AGENTS,
            "structural_ceiling": cap.array_entities, "worker_memory_bytes": cap.memory_bytes,
            "available_ram_bytes": host, "working_array_bytes": work,
            "reference_one_field_grid": min(cap.array_entities, work // 192),
            "reference_three_field_agents": min(cap.array_entities, work // 216),
            "archive_bytes": cap.run_bytes, "worker_cpu_seconds": cap.cpu_seconds,
            "worker_wall_seconds": cap.wall_seconds, "estimate": True}


def array_profile(spec, count, *, admit=True):
    grid = spec.get("grid")
    fields = len(spec.get("initial", {}))
    rules = (grid or {}).get("reductions", {})
    history = {}
    for rule in rules.values():
        for key in ("field", "by"):
            if key in rule:
                name = rule[key]
                history[name] = max(history.get(name, 0), rule.get("lag", 0) + 1)
    # Each level can retain inputs and masked index buffers while a branch runs.
    def depth(node):
        return 1 + max((depth(child) for child in ast.iter_child_nodes(node)), default=0)

    expressions = [expr for group in ("initial", "update", "measures") for expr in spec.get(group, {}).values()]
    depth_max = max((depth(ast.parse(str(expr), mode="eval")) for expr in expressions), default=0)
    bytes_per_agent = 8 * (2*fields + sum(history.values()) + len(rules) + (3 if grid else 1)
                           + 2*depth_max + 5)
    cap, host, work = _memory()
    feasible = min(cap.array_entities, work // max(1, bytes_per_agent))
    if not 1 <= count <= cap.array_entities:
        raise BudgetExceeded(f"请求 {count:,} 个主体，超过当前数组规模预算 {cap.array_entities:,}")
    if admit and count > feasible:
        raise BudgetExceeded(f"原规模 {count:,} 需要约 {count*bytes_per_agent/_MB:.0f} MiB 工作数组，"
                             f"当前可用预算 {work/_MB:.0f} MiB，可容纳约 {feasible:,} 个同结构主体")
    return {"kernel": ARRAY_KERNEL, "entities": count,
            "grid": {k:grid[k] for k in ("rows", "columns")} if grid else None,
            **({"grid_degree": grid["degree"], 'boundary':grid.get('boundary','periodic')} if grid else {}),
            "state_fields": fields, "local_reductions": len(rules), "history_columns": sum(history.values()),
            "working_bytes_estimate": count*bytes_per_agent, "working_budget_bytes": work,
            "host_available_bytes": host, "estimated_max_for_definition": feasible}


class FrameRetention:
    """Keep exact model states at budgeted times, without reducing population size."""

    def __init__(self, steps, stride, require_all=False):
        self.steps = steps
        self.stride = 1 if require_all else stride
        self.require_all = require_all
        cap = limits()
        self.max_frames = cap.frames
        self.bytes_budget = cap.run_bytes * 2 // 3
        self._entries = []
        self._bytes = 0

    def append(self, frame, step, final=False):
        size = sum(len(col.get("data", "")) for col in frame["population"]["columns"].values())
        size += sum(len(layer.get("values", "")) for layer in (frame.get("lattice") or {}).get("layers", []))
        size += 512*len(frame["entities"]) + 4096
        self._entries.append((step, frame, size))
        self._bytes += size
        if len(self._entries) == 1 and not self.require_all:
            allowed = max(2, min(self.max_frames, self.bytes_budget // size))
            self.stride = max(self.stride, math.ceil(max(0, self.steps)/(allowed-1)))
        if self.require_all and self._bytes > self.bytes_budget:
            raise BudgetExceeded("按原要求保存每一步完整状态超过归档预算，未减少主体或省略时点")
        while self._bytes > self.bytes_budget or (not self.require_all and len(self._entries) > self.max_frames):
            if len(self._entries) <= 2:
                raise BudgetExceeded("完整初末状态超过单次归档可用预算，未以抽样主体替代")
            self.stride *= 2
            kept = [row for row in self._entries if row is self._entries[0] or row[0] % self.stride == 0
                    or row is self._entries[-1] and final]
            self._entries = kept
            self._bytes = sum(row[2] for row in kept)

    def frames(self):
        return [frame for _, frame, _ in self._entries]

    def checkpoint(self):
        return {"steps": self.steps, "stride": self.stride, "require_all": self.require_all,
                "entries": [[step, size] for step, _frame, size in self._entries]}

    def restore(self, saved, frames):
        if saved["steps"] != self.steps or saved["require_all"] != self.require_all or len(saved["entries"]) != len(frames):
            raise ValueError("归档保留策略与计算检查点不一致")
        self.stride = saved["stride"]
        self._entries = [(step, frame, size) for (step, size), frame in zip(saved["entries"], frames)]
        self._bytes = sum(size for _, _, size in self._entries)
        if self._bytes > self.bytes_budget:
            raise BudgetExceeded("当前归档预算不足以恢复已保存的完整帧")
