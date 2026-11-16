"""理论包集合与场景工厂分发器（v2 设计·决策3/T2）。

导入本包即完成全部理论包注册；create_pack 按注册表分发实例化。
"""
from __future__ import annotations

from typing import Any

# 导入即注册（side effect：register_pack）
from . import polecon  # noqa: F401
from . import sociology  # noqa: F401
from . import politics  # noqa: F401
from . import media  # noqa: F401
from . import benchmark_sugarscape  # noqa: F401
from . import benchmark_axelrod  # noqa: F401

from ..kernel.core import get_pack


def create_pack(name: str, population: dict | None = None,
                institutions: dict | None = None, seed: int = 42,
                intervention: dict | None = None) -> Any:
    """按注册表分发：name → pack 实例（场景规约的包分发入口，T1 依赖）。"""
    tmpl = get_pack(name)
    if tmpl.factory is None:
        raise ValueError(f"包 {name} 未提供场景工厂（factory=None），"
                         f"无法由场景规约实例化")
    return tmpl.factory(population or {}, institutions or {}, seed,
                        intervention or {})
