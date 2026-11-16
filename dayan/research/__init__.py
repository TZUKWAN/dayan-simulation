"""DAYAN 研究层（WP6 研究问题编译 / WP8 统一实验）。

子模块：
- specs:      ResearchSpec / ExperimentSpec 数据合同（版本化、可序列化）
- compiler:   自然语言需求 → ResearchSpec → 候选模型（含忠实度）→ ExperimentSpec
- experiment: 配对种子对照实验、时点干预、程序先行的统计分析
"""
from .specs import ResearchSpec, ExperimentSpec, InterventionSpec, SPEC_VERSION
from .compiler import compile_research, CompileResult
from .experiment import run_experiment, ExperimentResult, analyze_observations

__all__ = ["ResearchSpec", "ExperimentSpec", "InterventionSpec",
           "SPEC_VERSION", "compile_research", "CompileResult",
           "run_experiment", "ExperimentResult", "analyze_observations"]
