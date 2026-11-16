"""自动报告生成：图表 + Markdown + 校准靶对照 + 效度说明。"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from ..measures.fitdist import fit_two_class  # noqa: E402

# 定性校准靶（见 data/calibration_targets.md）
TARGETS = {
    "gini": "真实经济 0.3–0.5；玩具经济低于此属预期（无房产/信贷）",
    "two_class": "财富分布呈下层指数+上尾 Pareto 双形态（Yakovenko 2009）",
    "labor_share": "工资份额 0.5–0.7（真实经济区间）",
}


def _fig_metrics(metrics: pd.DataFrame, outdir: Path, tag: str):
    plots = {}
    # 1) 基尼与 top10 份额
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(metrics.tick, metrics.gini, label="gini")
    ax.plot(metrics.tick, metrics.top10, label="top10 share")
    ax.set_xlabel("tick"); ax.set_ylabel("share"); ax.legend()
    ax.set_title("Wealth inequality trajectory")
    p = outdir / f"{tag}_inequality.png"; fig.tight_layout(); fig.savefig(p, dpi=130); plt.close(fig)
    plots["inequality"] = p.name
    # 2) 阶级位置占比堆叠
    cols = ["pos_unemployed", "pos_worker", "pos_self", "pos_employer"]
    if all(c in metrics.columns for c in cols):
        share = metrics[cols].div(metrics[[c for c in cols]].sum(axis=1), axis=0)
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.stackplot(metrics.tick,
                     share["pos_unemployed"], share["pos_worker"],
                     share["pos_self"], share["pos_employer"],
                     labels=["unemployed", "worker", "self", "employer"])
        ax.set_xlabel("tick"); ax.set_ylabel("share of agents"); ax.legend(loc="lower right")
        ax.set_title("Class position composition")
        p = outdir / f"{tag}_classes.png"; fig.tight_layout(); fig.savefig(p, dpi=130); plt.close(fig)
        plots["classes"] = p.name
    # 3) 剥削率与劳动份额
    if "exploitation_rate" in metrics.columns:
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.plot(metrics.tick, metrics.exploitation_rate, label="exploitation rate (profit_w/wages)")
        ax.plot(metrics.tick, metrics.labor_share, label="labor share")
        ax.axhline(0.6, ls="--", c="gray", lw=0.8)
        ax.set_xlabel("tick"); ax.legend()
        ax.set_title("Surplus accounting (masked wording in prompts)")
        p = outdir / f"{tag}_surplus.png"; fig.tight_layout(); fig.savefig(p, dpi=130); plt.close(fig)
        plots["surplus"] = p.name
    # 4) 参考价
    if "p_ref" in metrics.columns:
        fig, ax = plt.subplots(figsize=(7, 3.5))
        ax.plot(metrics.tick, metrics.p_ref)
        ax.set_xlabel("tick"); ax.set_ylabel("p_ref")
        ax.set_title("Reference price")
        p = outdir / f"{tag}_price.png"; fig.tight_layout(); fig.savefig(p, dpi=130); plt.close(fig)
        plots["price"] = p.name
    return plots


def _fig_wealth_hist(agents: pd.DataFrame, outdir: Path, tag: str):
    w = agents["wealth"].values
    fit = fit_two_class(w.tolist())
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(w, bins=40, density=True, alpha=0.6, label="wealth (final)")
    if fit.get("ok") and not np.isnan(fit.get("exp_scale", np.nan)):
        xs = np.linspace(0.01, fit["xmin"], 100)
        lam = 1.0 / fit["exp_scale"]
        ax.plot(xs, lam * np.exp(-lam * xs), "r--",
                label=f"exp fit (KS={fit['exp_ks']:.2f})")
        if not np.isnan(fit.get("pareto_alpha", np.nan)) and fit["pareto_alpha"] > 0:
            xs2 = np.linspace(fit["xmin"], max(w) * 1.05, 100)
            pdf = fit["pareto_alpha"] * fit["xmin"] ** fit["pareto_alpha"] / xs2 ** (fit["pareto_alpha"] + 1)
            ax.plot(xs2, pdf, "g--", label=f"pareto a={fit['pareto_alpha']:.1f} (KS={fit['pareto_ks']:.2f})")
    ax.set_yscale("log"); ax.set_xlabel("wealth"); ax.set_ylabel("density (log)")
    ax.legend(); ax.set_title("Wealth distribution & two-class fit")
    p = outdir / f"{tag}_wealth_dist.png"; fig.tight_layout(); fig.savefig(p, dpi=130); plt.close(fig)
    return p.name, fit


def _fig_alienation(alien: pd.DataFrame, outdir: Path, tag: str):
    dims = ["powerlessness", "meaninglessness", "normlessness",
            "isolation", "self_estrangement"]
    groups = alien.groupby("position")[dims + ["total"]].mean()
    order = [g for g in ["worker", "self", "employer", "unemployed"] if g in groups.index]
    fig, ax = plt.subplots(figsize=(8, 4))
    x = np.arange(len(dims))
    width = 0.8 / max(1, len(order))
    for i, g in enumerate(order):
        ax.bar(x + i * width, groups.loc[g, dims].values, width, label=f"{g} (n={ (alien.position==g).sum() })")
    ax.set_xticks(x + width * (len(order) - 1) / 2); ax.set_xticklabels(dims, rotation=20)
    ax.set_ylabel("mean score (1-5)"); ax.legend()
    ax.set_title("Seeman five-dimension scores by position (LLM narratives)")
    p = outdir / f"{tag}_alienation.png"; fig.tight_layout(); fig.savefig(p, dpi=130); plt.close(fig)
    return p.name, groups


def generate_report(run_dir: Path, mode: str, seed: int, cfg: dict) -> Path:
    outdir = Path(run_dir)
    metrics = pd.read_csv(outdir / "metrics.csv")
    agents = pd.read_csv(outdir / "agents_final.csv")
    tag = outdir.name
    rep_dir = outdir  # 报告与图放 run 目录内
    lines = [f"# 运行报告：{tag}", "",
             f"- mode: **{mode}**；seed: {seed}；agents: {cfg.get('n_agents')}；ticks: {cfg.get('ticks')}",
             f"- LLM: {cfg.get('llm_desc', 'n/a')}",
             ""]
    plots = _fig_metrics(metrics, rep_dir, tag)
    for k, name in plots.items():
        lines.append(f"![{k}]({name})")
        lines.append("")
    # 最终分布
    hist_name, fit = _fig_wealth_hist(agents, rep_dir, tag)
    lines.append(f"![wealth_dist]({hist_name})"); lines.append("")
    lines.append("## 最终状态")
    w = agents["wealth"].values
    lines.append(f"- 财富：均值 {w.mean():.1f}，中位 {np.median(w):.1f}，"
                 f"最大 {w.max():.1f}，最小 {w.min():.1f}")
    lines.append(f"- 双形态拟合：{json.dumps({k: (round(v,3) if isinstance(v,float) else v) for k,v in fit.items()}, ensure_ascii=False)}")
    lines.append(f"- 校准靶（{TARGETS['two_class']}）→ 见上图")
    lines.append("")
    # 末 tick 指标
    last = metrics.iloc[-1]
    lines.append("## 末 tick 关键指标")
    for k in ["gini", "top10", "top1", "exploitation_rate", "labor_share",
              "unemployment", "p_ref", "n_firms"]:
        if k in metrics.columns:
            v = last[k]
            lines.append(f"- {k}: {v:.3f}" if isinstance(v, float) else f"- {k}: {v}")
    lines.append(f"- 校准参照：{TARGETS['labor_share']}")
    lines.append("")
    # 阶级转移矩阵
    trans_path = outdir / "transitions.json"
    if trans_path.exists():
        import json as _json
        t = _json.loads(trans_path.read_text(encoding="utf-8"))
        keys = ["unemployed", "worker", "self", "employer", "member"]
        rows = ["| 从\到 | " + " | ".join(keys) + " |",
                "|---|" + "---|" * len(keys)]
        for a0 in keys:
            cells = [str(t.get(f"{a0}->{a1}", 0)) for a1 in keys]
            rows.append(f"| {a0} | " + " | ".join(cells) + " |")
        lines += ["## 阶级位置转移矩阵（全期累计）", ""] + rows + [""]
    # 企业生命周期
    firms_path = outdir / "firms.csv"
    if firms_path.exists():
        f = pd.read_csv(firms_path)
        if len(f):
            span = f.groupby("fid").tick.agg(["min", "max", "count"])
            fig, ax = plt.subplots(figsize=(7, 4))
            cmap = plt.cm.tab20(np.linspace(0, 1, min(20, len(span))))
            for i, (fid, r) in enumerate(span.iterrows()):
                sub = f[f.fid == fid]
                ax.step(sub.tick, sub.n_workers, where="post",
                        color=cmap[i % len(cmap)], lw=1.4, label=f"#{fid}")
            ax.set_xlabel("tick"); ax.set_ylabel("在职工人数")
            ax.set_title("Firm lifecycle monitor")
            p = outdir / f"{tag}_firms.png"; fig.tight_layout(); fig.savefig(p, dpi=130); plt.close(fig)
            lines += [f"![firms]({p.name})", "",
                      f"- 企业数（出现过的）: {len(span)}；"
                      f"最长存活 {int(span['count'].max())} tick",
                      f"- 雇佣峰值: {int(f.n_workers.max())}（企业#{int(f.loc[f.n_workers.idxmax(),'fid'])}）",
                      ""]
    # 定量靶检查
    tj = outdir.parents[1] / "data" / "targets.json"
    if tj.exists() and "labor_share" in metrics.columns:
        import json as _json
        tg = _json.loads(tj.read_text(encoding="utf-8"))
        ls = metrics.labor_share.tail(30).mean()
        lo, hi = tg["labor_share_range"]
        ok = "✓在区间内" if lo <= ls <= hi else "✗偏离区间"
        lines += ["## 定量靶对照（data/targets.json）", "",
                  f"- 劳动份额末30期均值 {ls:.3f}，靶区间 [{lo},{hi}] {ok}",
                  f"- 官方口径参照：中国基尼约{tg['gini_cn_official']}（玩具经济结构差异大，仅作量级参照）",
                  ""]
    # 效度记录
    lines.append("## 效度记录")
    lines.append(f"- 金钱守恒最大残差：{metrics.get('conserv_err', pd.Series([float('nan')])).max():.2e}")
    if mode == "rule":
        lines.append("- 异化量表：规则基线不适用（叙事测量仅 LLM 模式），N/A")
    alien_path = outdir / "alienation.csv"
    if alien_path.exists():
        alien = pd.read_csv(alien_path)
        if len(alien):
            name, groups = _fig_alienation(alien, rep_dir, tag)
            lines.append(f"![alienation]({name})"); lines.append("")
            lines.append("### Seeman 五维组均值")
            lines.append(groups.round(2).to_markdown())
            fb = (alien["source"] == "keyword_fallback").mean()
            lines.append("")
            lines.append(f"- 评定来源：LLM-judge {1-fb:.0%} / 关键词回退 {fb:.0%}"
                         f"（4B 模型评定信度有限，需人工复核子样本）")
    lines.append("")
    lines.append("## 主张分级提示")
    lines.append("- 本报告的**趋势/形态主张**（分布形态、组间差异方向）可作为结论；")
    lines.append("- **微观机制主张**需配合规则基线差分与跨模型稳健性（本运行仅本地单模型，跨模型项待补）。")
    rep = rep_dir / "REPORT.md"
    rep.write_text("\n".join(lines), encoding="utf-8")
    return rep
