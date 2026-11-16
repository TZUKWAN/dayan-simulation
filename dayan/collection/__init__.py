"""自动真实数据采集底座（任务书阶段A/B）。

registry: 来源注册表 + 证据状态机（§3.1）
connectors: 协议适配器（分页生成器；§3.3）
engine: 采集任务引擎（原始快照/完整性/续采；§3.3）
presets: 主题采集预设（§C0）
"""
from . import registry, connectors, engine, presets  # noqa: F401
