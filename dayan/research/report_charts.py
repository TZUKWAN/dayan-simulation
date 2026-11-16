"""研究报告图表生成：matplotlib 嵌入 DOCX（校准/留出/残差/政策对比4类图）。"""
from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = ROOT / "data" / "collection" / "reports"
CHARTS_DIR = REPORTS_DIR / "charts"


def _setup_style():
    plt.rcParams.update({
        "figure.facecolor": "white", "axes.facecolor": "#f8f9fa",
        "axes.grid": True, "grid.alpha": 0.3,
        "font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9,
    })
    # 中文字体
    try:
        from matplotlib.font_manager import FontProperties
        import matplotlib.font_manager as fm
        for f in fm.fontManager.ttflist:
            if "Microsoft YaHei" in f.name or "SimHei" in f.name:
                plt.rcParams["font.family"] = [f.name]
                break
    except Exception:
        pass


def _save(fig, name: str) -> str:
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    path = CHARTS_DIR / f"{name}.png"
    fig.savefig(str(path), dpi=150, bbox_inches="tight")
    plt.close(fig)
    return str(path)


def calibration_fit_chart(model_fn, params: dict, calibration: list[dict],
                          holdout: list[dict], model_id: str = "") -> str:
    """校准拟合 + 留出验证图（实际点 + 模型线 + 分割线）。"""
    _setup_style()
    fig, ax = plt.subplots(figsize=(8, 4))
    cal_years = [float(r["date"]) for r in calibration]
    cal_vals = [float(r["value"]) for r in calibration]
    hold_years = [float(r["date"]) for r in holdout]
    hold_vals = [float(r["value"]) for r in holdout]
    all_years = cal_years + hold_years
    preds = model_fn(params, all_years)
    ax.scatter(cal_years, cal_vals, c="#0e7c86", s=50, zorder=5, label="校准数据")
    ax.scatter(hold_years, hold_vals, c="#ff6a3a", s=50, marker="s", zorder=5, label="留出数据")
    ax.plot(all_years, preds, "--", color="#8a4fbe", lw=1.5, label="模型拟合")
    split = min(hold_years) - 0.5 if hold_years else None
    if split:
        ax.axvline(split, color="gray", ls=":", lw=1, alpha=0.5)
        ax.text(split, ax.get_ylim()[1] * 0.95, " ←校准 | 留出→ ", ha="center",
                fontsize=8, color="gray")
    ax.set_xlabel("年份")
    ax.set_ylabel("值")
    ax.set_title(f"校准拟合与留出验证 {model_id}")
    ax.legend(loc="best")
    fig.tight_layout()
    return _save(fig, "calibration_fit")


def residual_chart(actual: list[float], predicted: list[float],
                   labels: list[str] | None = None, name: str = "residual") -> str:
    """残差图（残差绝对值柱状 + 正负色分）。"""
    _setup_style()
    residuals = [a - p for a, p in zip(actual, predicted)]
    fig, ax = plt.subplots(figsize=(6, 3.5))
    colors = ["#0e7c86" if r >= 0 else "#b03a3a" for r in residuals]
    x = range(len(residuals))
    ax.bar(x, residuals, color=colors, alpha=0.7)
    ax.axhline(0, color="black", lw=0.5)
    if labels:
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_ylabel("残差")
    ax.set_title("留出验证残差")
    fig.tight_layout()
    return _save(fig, name)


def policy_comparison_chart(baseline_traj: list[dict], arm_trajs: list[dict],
                             value_key: str = "population",
                             year_key: str = "year") -> str:
    """政策对比图（基线实线 + 各臂虚线，标注差异区域）。"""
    _setup_style()
    fig, ax = plt.subplots(figsize=(8, 4.5))
    years_b = [t[year_key] for t in baseline_traj]
    vals_b = [t[value_key] for t in baseline_traj]
    ax.plot(years_b, vals_b, "-o", color="#333", lw=2, markersize=3, label="基线")
    colors = ["#0e7c86", "#8a4fbe", "#c77d1e"]
    for i, arm in enumerate(arm_trajs):
        traj = arm.get("trajectory", [])
        years = [t[year_key] for t in traj]
        vals = [t[value_key] for t in traj]
        label = arm.get("scenario", f"臂{i+1}")
        ax.plot(years, vals, "--", color=colors[i % len(colors)], lw=1.5, label=label)
        # 标注差异区域（仅在基线上方时填充）
        if len(years) == len(years_b):
            ax.fill_between(years, vals_b, vals, alpha=0.1, color=colors[i % len(colors)])
    ax.set_xlabel("年份")
    ax.set_ylabel(value_key)
    ax.set_title("政策方案对比（模型内反事实）")
    ax.legend(loc="best")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x/1e6:.0f}M"))
    fig.tight_layout()
    return _save(fig, "policy_comparison")


def sensitivity_tornado_chart(param_names: list[str], impacts: list[float],
                              name: str = "sensitivity") -> str:
    """敏感性 tornado 图（参数扰动对结局的影响幅度排序）。"""
    _setup_style()
    sorted_pairs = sorted(zip(param_names, impacts), key=lambda x: abs(x[1]))
    fig, ax = plt.subplots(figsize=(6, 3.5))
    ax.barh([p for p, _ in sorted_pairs], [v for _, v in sorted_pairs],
            color=["#b03a3a" if v > 0 else "#0e7c86" for _, v in sorted_pairs], alpha=0.7)
    ax.set_xlabel("对结局的影响幅度")
    ax.set_title("参数敏感性（tornado）")
    fig.tight_layout()
    return _save(fig, name)


def source_coverage_heatmap(matrix: list[dict]) -> str:
    """来源覆盖矩阵热图（类别×状态计数）。"""
    _setup_style()
    from dayan.collection.registry import CATS, STATE_ZH
    cats = sorted(CATS.keys())
    states = ["live", "needs_auth", "down", "candidate", "configured", "restricted"]
    state_labels = [STATE_ZH[s] for s in states]
    counts = np.zeros((len(cats), len(states)))
    for m in matrix:
        ci = cats.index(m["cat"]) if m["cat"] in cats else 0
        si = states.index(m["state"]) if m["state"] in states else len(states) - 1
        counts[ci, si] += 1
    fig, ax = plt.subplots(figsize=(8, 4))
    im = ax.imshow(counts, cmap="YlGnBu", aspect="auto")
    ax.set_xticks(range(len(states)))
    ax.set_xticklabels(state_labels, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(cats)))
    ax.set_yticklabels([CATS[c] for c in cats], fontsize=8)
    for i in range(len(cats)):
        for j in range(len(states)):
            if counts[i, j] > 0:
                ax.text(j, i, int(counts[i, j]), ha="center", va="center",
                        color="white" if counts[i, j] > 3 else "black", fontsize=9)
    plt.colorbar(im, ax=ax, label="来源数")
    ax.set_title("数据来源覆盖矩阵（类别×状态）")
    fig.tight_layout()
    return _save(fig, "source_coverage")


def generate_all_charts(usecase1: dict, usecase2: dict, matrix: list[dict]) -> list[str]:
    study_id=usecase1.get("study_id")
    if not study_id:
        raise ValueError("旧图表集合的模型版本未绑定，不能将固定Logistic/旧政策轨迹冒充当前研究")
    from .study_reports import generate_report
    from .studies import directory
    generate_report(study_id,"academic")
    return [str(directory(study_id)/"reports"/"diagnostics.png")]


def _legacy_chart_collection_disabled(usecase1: dict, usecase2: dict, matrix: list[dict]) -> list[str]:
    """生成全部研究图表并返回路径列表。"""
    charts = []
    cal = usecase1.get("calibration", {})
    best = cal.get("best_params", {})
    if best:
        # 校准拟合图
        def logistic(params, years):
            return [params["K"] / (1 + math.exp(-params["r"] * (y - params["t_mid"])))
                    for y in years]
        cal_rec = [{"date": 2018, "value": 1402760000},
                    {"date": 2019, "value": 1407745000},
                    {"date": 2020, "value": 1411100000},
                    {"date": 2021, "value": 1412360000}]
        hold_rec = [{"date": 2022, "value": 1412175000}]
        charts.append(calibration_fit_chart(logistic, best, cal_rec, hold_rec, "NET061"))

        # 残差图
        if cal.get("holdout"):
            h = cal["holdout"]
            charts.append(residual_chart(h["actual"], h["predicted"],
                                          labels=["2022"], name="holdout_residual"))

    # 政策对比图
    p1 = usecase2.get("policy1", {})
    p2 = usecase2.get("policy2", {})
    base = usecase2.get("baseline", {})
    if base.get("trajectory") and p1.get("trajectory"):
        charts.append(policy_comparison_chart(base["trajectory"],
                                               [p1, p2], "population", "year"))

    # 来源覆盖热图
    charts.append(source_coverage_heatmap(matrix))
    return charts


def embed_charts_in_docx(md_path: str, chart_paths: list[str],
                         docx_path: str) -> str:
    """在已生成的 DOCX 报告末尾追加图表。"""
    from docx import Document
    from docx.shared import Inches, Pt
    doc = Document(docx_path)
    doc.add_page_break()
    doc.add_heading("附录：研究图表", level=1)
    chart_labels = ["校准拟合与留出验证", "留出残差", "政策方案对比",
                     "来源覆盖矩阵", "敏感性分析"]
    for i, chart_path in enumerate(chart_paths):
        if not Path(chart_path).exists():
            continue
        doc.add_paragraph("")
        doc.add_picture(chart_path, width=Inches(6.0))
        cap = doc.add_paragraph(
            f"图 {i+1}  {chart_labels[i] if i < len(chart_labels) else chart_path}")
        cap.alignment = 1
        cap.runs[0].font.size = Pt(9)
        doc.add_paragraph(
            f"数据来源：真实采集归档（collection_id 见正文引用）；"
            f"模型版本：Logistic v2；生成时间 {datetime.now().strftime('%Y-%m-%d')}。"
        ).runs[0].font.size = Pt(8)
    doc.save(docx_path)
    return docx_path
