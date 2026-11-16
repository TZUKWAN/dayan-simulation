"""场景规约加载器（实验即数据，v2 设计·决策4）。

YAML 声明式规约 → 实验配置。门禁（缺一项即拒绝标记"已检验"）：
- validity_plan 必填（基线/消融/种子至少一项）
- measurement_plan 必填
- claims_level 必填（机制主张需声明微观校准方案）
- 遮蔽审计在实验运行时执行（agents 层）
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Scenario:
    """解析后的场景规约。"""
    name: str
    pack: str
    population: dict
    institutions: dict = field(default_factory=dict)
    measurement_plan: list[str] = field(default_factory=list)
    validity_plan: dict = field(default_factory=dict)
    claims_level: dict = field(default_factory=dict)
    intervention: dict = field(default_factory=dict)
    ticks: int = 200
    seed: int = 42
    raw: dict = field(default_factory=dict)

    def check_gates(self) -> list[str]:
        """返回未通过的效度闸门清单（空=全过）。"""
        issues = []
        if not self.measurement_plan:
            issues.append("measurement_plan 为空")
        vp = self.validity_plan
        if not (vp.get("基线") or vp.get("消融") or vp.get("种子")):
            issues.append("validity_plan 缺少基线/消融/种子至少一项")
        cl = self.claims_level
        if "机制主张" not in cl or "趋势主张" not in cl:
            issues.append("claims_level 必须声明机制主张与趋势主张的等级")
        if cl.get("机制主张") == "需微观校准" and not vp.get("微观校准"):
            issues.append("机制主张声明需微观校准，但 validity_plan 未提供")
        return issues


def load_scenario(path: str | Path) -> Scenario:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "scenario" not in raw:
        raise ValueError("规约必须含顶层 scenario 键")
    s = Scenario(
        name=raw["scenario"],
        pack=raw.get("pack", "政治经济学包"),
        population=raw.get("population", {}),
        institutions=raw.get("institutions", {}),
        measurement_plan=raw.get("measurement_plan", []),
        validity_plan=raw.get("validity_plan", {}),
        claims_level=raw.get("claims_level", {}),
        intervention=raw.get("intervention", {}),
        ticks=int(raw.get("ticks", 200)),
        seed=int(raw.get("seed", 42)),
        raw=raw,
    )
    return s


def load_scenario_from_dict(raw: dict) -> Scenario:
    import tempfile, os
    # 复用 yaml 解析路径的一致性：直接构造
    if not isinstance(raw, dict) or "scenario" not in raw:
        raise ValueError("规约必须含顶层 scenario 键")
    return Scenario(
        name=raw["scenario"],
        pack=raw.get("pack", "政治经济学包"),
        population=raw.get("population", {}),
        institutions=raw.get("institutions", {}),
        measurement_plan=raw.get("measurement_plan", []),
        validity_plan=raw.get("validity_plan", {}),
        claims_level=raw.get("claims_level", {}),
        intervention=raw.get("intervention", {}),
        ticks=int(raw.get("ticks", 200)),
        seed=int(raw.get("seed", 42)),
        raw=raw,
    )
