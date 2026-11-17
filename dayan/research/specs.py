"""研究规约数据合同（方案 §14：ResearchSpec / ExperimentSpec）。

设计约束：
- 每份规约带版本号与创建时间；序列化可回读；
- 假设三分类（confirmed 用户确认 / suggested 系统建议 / pending 待确认）；
- unsupported_requirements 与 open_questions 必须显式存在——
  编译器宁可暴露缺口，不许静默降级。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
import uuid

SPEC_VERSION = "1.0"


@dataclass
class InterventionSpec:
    """时点干预（WP8）：在指定仿真时刻对指定参数施加变化。"""
    label: str = "干预"
    at_t: float = 0.0                      # 仿真时间（tick/物理时间由模型定）
    params: dict = field(default_factory=dict)   # 该时刻改写的模型参数
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ResearchSpec:
    """研究问题规约（§14.1）：用户到底要回答什么。"""
    research_id: str = ""
    version: str = SPEC_VERSION
    created_at: str = ""
    original_request: str = ""
    purpose: str = "mechanism"             # teaching|mechanism|explanatory|policy|prediction
    research_questions: list = field(default_factory=list)
    population: str = ""
    space_scope: str = ""
    time_scope: str = ""
    mechanisms_required: list = field(default_factory=list)
    mechanisms_missing: list = field(default_factory=list)   # 目录中未覆盖的机制
    outcomes: list = field(default_factory=list)
    assumptions: dict = field(default_factory=lambda: {
        "confirmed": [], "suggested": [], "pending": []})
    evidence_requirement: str = "theoretical"  # theoretical|synthetic|calibrated|validated
    unsupported_requirements: list = field(default_factory=list)
    open_questions: list = field(default_factory=list)

    def finalize(self):
        now = datetime.now().isoformat(timespec="seconds")
        if not self.research_id:
            self.research_id = "RS-" + uuid.uuid4().hex[:8]
        if not self.created_at:
            self.created_at = now
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ResearchSpec":
        known = {f for f in cls.__dataclass_fields__}  # noqa: C416
        return cls(**{k: v for k, v in d.items() if k in known})

    def validate(self) -> list[str]:
        issues = []
        if not self.original_request:
            issues.append("缺 original_request")
        if not self.mechanisms_required:
            issues.append("未识别任何必需机制")
        if self.purpose not in ("teaching", "mechanism", "explanatory",
                                "policy", "prediction"):
            issues.append(f"purpose 非法: {self.purpose}")
        if self.purpose == "prediction" and \
                self.evidence_requirement in ("theoretical", "synthetic"):
            issues.append("预测用途要求 calibrated/validated 证据等级，"
                          "当前证据要求不足以支持现实预测")
        return issues


@dataclass
class ExperimentSpec:
    """实验规约（§14.4）：本次怎么比较与判定。"""
    experiment_id: str = ""
    research_id: str = ""
    version: str = SPEC_VERSION
    created_at: str = ""
    model_id: str = ""
    title: str = ""
    baseline_params: dict = field(default_factory=dict)
    baseline_interventions: list = field(default_factory=list)
    data_bindings: list = field(default_factory=list)
    arms: list = field(default_factory=list)          # [{label, interventions:[InterventionSpec], params:{}}]
    seeds: list = field(default_factory=lambda: [0, 1, 2, 3])
    rng_domain: str = "exp0"              # Record identity must not change the random experiment.
    ticks: int = 200
    dt: float = 0.1
    primary_metric: str = ""               # 主要结局指标（观测字段名）
    warmup_ticks: int = 0                  # 预热期（不计入统计）
    analysis_window: list = field(default_factory=lambda: [])  # [t0,t1] 空=全程
    purpose: str = "mechanism"
    hypothesis: str = ""
    notes: list = field(default_factory=list)

    def finalize(self):
        now = datetime.now().isoformat(timespec="seconds")
        if not self.experiment_id:
            self.experiment_id = "EX-" + uuid.uuid4().hex[:8]
        if not self.created_at:
            self.created_at = now
        return self

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ExperimentSpec":
        known = set(cls.__dataclass_fields__)
        if set(d) - known:
            raise ValueError(f"未知实验字段: {sorted(set(d)-known)}")
        spec = cls(**d)
        spec.arms = [
            {**a, "interventions": [iv.to_dict() if isinstance(iv, InterventionSpec) else dict(iv)
                                    for iv in a.get("interventions", [])]}
            for a in spec.arms
        ]
        return spec

    def validate(self) -> list[str]:
        issues = []
        if not self.model_id:
            issues.append("缺 model_id")
        if not self.primary_metric:
            issues.append("缺 primary_metric（主要结局指标必须显式声明）")
        import math
        if isinstance(self.warmup_ticks,bool) or not isinstance(self.warmup_ticks,int) or not 0<=self.warmup_ticks<=self.ticks:
            issues.append('warmup_ticks须为0..ticks整数')
        if self.analysis_window:
            window=self.analysis_window
            if not isinstance(window,list) or len(window)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in window):
                issues.append('analysis_window须为有限数值[t0,t1]')
            elif not 0<=window[0]<=window[1]<=self.ticks*self.dt:
                issues.append('analysis_window须处于实际运行时间范围内')
        from ..limits import validate_compute
        try:
            validate_compute(self.ticks, runs=max(1,len(self.seeds))*(len(self.arms)+1),
                             seeds=len(self.seeds), arms=len(self.arms), parameters=self.baseline_params)
            for arm in self.arms:
                validate_compute(self.ticks, parameters=arm.get('params'))
        except ValueError as exc:
            issues.append(str(exc))
        if not self.seeds:
            issues.append("缺 seeds（单次运行不构成实验）")
        if self.purpose not in ("teaching", "mechanism", "explanatory", "policy", "prediction"):
            issues.append(f"purpose 必须是规定枚举值，不能为任意叙述: {self.purpose}")
        if len(self.seeds) > 50 or len(set(self.seeds)) != len(self.seeds):
            issues.append("种子必须不重复且不超过50个")
        from ..runtime import validate_run_arguments
        for seed in self.seeds:
            try:
                validate_run_arguments(self.ticks, self.dt, seed)
            except ValueError as exc:
                issues.append(str(exc))
        labels = [a.get("label") for a in self.arms]
        if any(not label or label == "基线" for label in labels) or len(set(labels)) != len(labels):
            issues.append("干预臂标签必须非空、不重复，且不能占用“基线”")
        return issues
