"""DAYAN × msim 资产迁移登记：把既有 ABM 资产登记为 DAYAN 基准通过模型。

- Schelling（src/packs/sociology.py，分异涌现已验证）
- Axelrod（src/packs/benchmark_axelrod.py，地域化已验证）
- Sugarscape（src/packs/benchmark_sugarscape.py，财富分布已验证）
- LLM 语义层（src/agents，规范 2.6 合规：生成行动与权威环境分离）
运行：python tests/test_dayan_migration.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dayan import ModelRegistry, STATUS_LEVELS  # noqa: E402


def test_existing_assets_registered():
    reg = ModelRegistry()
    assets = [
        ("DAYAN.ABM.Schelling", "Schelling 空间隔离（msim 社会学包）",
         "分异指数 0.5→0.974（涌现）", "基准通过"),
        ("DAYAN.ABM.Axelrod", "Axelrod 文化传播（msim 基准包）",
         "区域数 900→278（地域化涌现）", "基准通过"),
        ("DAYAN.ABM.Sugarscape", "Sugarscape 财富分布（msim 基准包）",
         "gini 0.53（偏斜形态）", "基准通过"),
        ("DAYAN.ABM.ToyCapitalism", "玩具资本主义（政治经济学包 v0/v1）",
         "剥削记账恒正/合作社方差坍缩/15 runs campaign", "基准通过"),
        ("DAYAN.LLM.SemanticLayer", "LLM 语义层（遮蔽设计+规则回退）",
         "四包在环、万次调用零回退、遮蔽零命中", "基准通过"),
    ]
    for mid, name, evidence, status in assets:
        from dayan.core import ModelRecord
        rec = ModelRecord(model_id=mid, name=name, status=status,
                          state_schema={'agents': 'list'},
                          time_unit='tick', clock_type='fixed_step',
                          reference_cases=[evidence])
        issues = rec.contract_issues()
        assert issues == [], f"{mid} 合同缺项：{issues}"
        reg.register(rec)
    assert len(reg) == len(assets)
    print(f"[PASS] 既有 msim 资产：{len(assets)} 项登记为基准通过")


if __name__ == "__main__":
    test_existing_assets_registered()
    print("\n===== DAYAN × msim 迁移登记：通过 =====")
