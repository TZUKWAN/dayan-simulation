"""Compile explicit requirements without replacing their mechanism or experiment."""
from __future__ import annotations

from dataclasses import dataclass, field

from .specs import ResearchSpec, ExperimentSpec
from .requirements import extract_request, model_mechanisms, coverage_issues

MECHANISM_TABLE = {
    "疾病传播": {"candidates": [("NET052", "SIS 可重复感染"), ("NET053", "SIR 免疫退出")], "metric": "I"},
    "信息传播": {"candidates": [("BEH018", "有界信心连续意见")], "metric": "mean_opinion"},
    "人群疏散": {"candidates": [("NET113", "社会力行人动力学")], "metric": "evacuated"},
    "交通流": {"candidates": [("NET106", "NaSch 环形单车道")], "metric": "flux"},
    "居住分异": {"candidates": [("BEH001", "Schelling 阈值迁移")], "metric": "segregation"},
    "就业劳动": {"candidates": [("ECO019", "Goodwin 就业分配动态")], "metric": "v"},
    "排队资源": {"candidates": [("SYS002", "M/M/c 多服务台排队")], "metric": "queue_length"},
}


@dataclass
class CompileResult:
    research_spec: ResearchSpec
    candidates: list = field(default_factory=list)
    experiment_spec: ExperimentSpec | None = None
    warnings: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def _pick_metric(mid, requested=None):
    from ..agent.metadata import load_capabilities
    obs = next((c.get("observables", []) for c in load_capabilities() if c["model_id"] == mid), [])
    if requested:
        return requested
    for name in ("flux", "I", "I_total", "evacuated", "n_evacuated", "segregation", "mean_opinion", "employment", "v", "queue_length"):
        if name in obs:
            return name
    return next((f for f in obs if f not in ("sim_t", "t", "tick", "step")), "")


def compile_research(text: str, purpose=None, ticks=None, dt=None, seeds=None,
                     research_id="", model_id=None, parameters=None,
                     interventions=None, metric=None, last_run=None) -> CompileResult:
    request = extract_request(text, last_run)
    options = request["options"]
    ticks = options.get("ticks", 200 if ticks is None else ticks)
    dt = options.get("dt", .1 if dt is None else dt)
    seeds = options.get("seeds", [options["seed"]] if "seed" in options else seeds)
    seeds = [0, 1, 2, 3] if seeds is None else list(seeds)
    purpose = request["purpose"] if purpose is None else purpose
    ids = request["model_ids"]
    mid = ids[0] if len(ids) == 1 else model_id
    mechanisms = request["mechanisms"] or list(model_mechanisms(mid))
    research = ResearchSpec(original_request=text, purpose=purpose,
                            mechanisms_required=mechanisms or (["用户指定模型"] if mid else []),
                            research_questions=[text], evidence_requirement="theoretical").finalize()
    if research_id:
        research.research_id = research_id
    if not mid and len(mechanisms) > 1 and set(mechanisms) <= model_mechanisms("CPL001"):
        mid = "CPL001"
    issues = coverage_issues(request, mid)
    if len(ids) > 1:
        issues.append("多模型实验必须明确每个模型的实验规约，不能只运行第一个")
    if not mid and len(mechanisms) == 1:
        choices = MECHANISM_TABLE.get(mechanisms[0], {}).get("candidates", [])
        if choices:
            mid = choices[0][0]
    if not mid:
        issues.append("尚未找到覆盖原始需求的可运行模型")
    from ..model_index import ALL_INDEX
    if mid and mid not in ALL_INDEX:
        issues.append(f"{mid} 无运行工厂")
    issues.extend(research.validate())
    research.unsupported_requirements.extend(issues)
    candidates = []
    if mid in ALL_INDEX:
        from ..fidelity import load_reviews
        review = load_reviews().get(mid, {})
        candidates.append({"model_id": mid, "runnable": True,
                           "mechanism": list(model_mechanisms(mid)),
                           "reason": "原始需求指定" if ids else "机制表匹配",
                           "fidelity": review.get("fidelity", "unreviewed"),
                           "basis": review.get("basis", "未独立审查；可运行不代表已验证")})
    if issues:
        return CompileResult(research, candidates, None, issues, [])
    baseline = {**(parameters or {}), **request["parameters"]}
    ivs = request["interventions"] or interventions or []
    if any(iv.get("at_t") is None for iv in ivs):
        issue = "干预缺少明确时点，不能擅自选择第25%处"
        research.unsupported_requirements.append(issue)
        return CompileResult(research, candidates, None, [issue], [])
    arms = [{"label": "用户指定干预", "params": {}, "interventions": ivs}] if ivs else []
    exp = ExperimentSpec(research_id=research.research_id, model_id=mid,
                         title=text[:100], baseline_params=baseline, arms=arms,
                         ticks=ticks, dt=dt, seeds=seeds,
                         primary_metric=_pick_metric(mid, metric or request["metric"]),
                         purpose=purpose,
                         hypothesis="用户指定干预相对同种子基线的模型内差异" if arms else "基线重复运行").finalize()
    validation = exp.validate()
    return CompileResult(research, candidates, None if validation else exp, validation,
                         ["仅执行原始需求中的干预；未插入固定幅度或时间模板"])
