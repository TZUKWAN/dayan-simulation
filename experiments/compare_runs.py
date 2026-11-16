"""跨组对比报告：把多个 run 的末段均值并排，生成 reports/ 下的对比 markdown。

用法：python experiments/compare_runs.py mvp_rule_s7 mvp_llm_s7 mvp_llm_s7_nopersona mvp_llm_s43
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
COLS = ["gini", "top10", "top1", "pos_worker", "pos_employer", "pos_self",
        "pos_unemployed", "p_ref", "exploitation_rate", "labor_share",
        "unmet_rate", "n_firms"]


def tail_stats(run_dir: Path, k: int = 30) -> dict:
    m = pd.read_csv(run_dir / "metrics.csv").set_index("tick")
    return m[COLS].tail(k).mean().to_dict()


def alien_stats(run_dir: Path) -> pd.DataFrame | None:
    p = run_dir / "alienation.csv"
    if not p.exists():
        return None
    a = pd.read_csv(p)
    dims = ["powerlessness", "meaninglessness", "normlessness",
            "isolation", "self_estrangement", "total"]
    g = a.groupby("position")[dims].mean()
    n = a.groupby("position").size().rename("n")
    return g.join(n)


def main(run_names: list[str]):
    rows = {}
    for name in run_names:
        d = ROOT / "results" / name
        if not (d / "metrics.csv").exists():
            print(f"[跳过] {name}（无 metrics.csv）")
            continue
        rows[name] = tail_stats(d)
    df = pd.DataFrame(rows).T

    lines = [f"# 组间对比：{' vs '.join(run_names)}", "",
             f"> 末 30 期均值；生成于 compare_runs.py", "",
             df.round(3).to_markdown(), ""]

    # 异化对比（仅含 alienation 的组）
    alien_frames = {}
    for name in run_names:
        st = alien_stats(ROOT / "results" / name)
        if st is not None and len(st):
            alien_frames[name] = st
    if alien_frames:
        lines.append("## Seeman 五维组均值（各运行）")
        lines.append("")
        for name, st in alien_frames.items():
            lines.append(f"### {name}")
            lines.append("")
            lines.append(st.round(2).to_markdown())
            lines.append("")

    out = ROOT / "reports" / ("comparison_" + "_vs_".join(n[:18] for n in run_names) + ".md")
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print("对比报告：", out)
    print(df.round(3).to_string())


if __name__ == "__main__":
    names = sys.argv[1:] or ["mvp_rule_s7", "mvp_llm_s7"]
    main(names)
