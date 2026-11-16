"""大衍 DAYAN · 一站式社会仿真平台。

多范式（ABM/SD/CA/博弈/DES/ODE/SDE/微观仿真）× 多学科（482 具名模型目录）
× LLM 语义层（本地 Qwen3.5-4B，遮蔽设计）。基于 DAYAN 规范第二章平台实现规范。
"""
from .core import (Clocks, DayanModel, DomainEvent, EventQueue,  # noqa: F401
                   BalancedLedger, ModelRecord, ModelRegistry, RngStreams,
                   StateDelta, STATUS_LEVELS, get_registry, simulate)
