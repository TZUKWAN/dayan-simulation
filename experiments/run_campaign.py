"""预注册 campaign 批量运行器（H7-H9）+ 汇总统计（mean±std, Mann-Whitney U）。

用法：
  python experiments/run_campaign.py --run     # 执行全部条件（顺序，LLM条件较慢）
  python experiments/run_campaign.py --summary # 仅汇总已有结果
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pandas as pd
from scipy.stats import mannwhitneyu

ROOT = Path(__file__).resolve().parents[1]
COLS = ["gini", "top10", "pos_worker", "pos_member", "pos_employer", "pos_self",
        "p_ref", "exploitation_rate", "labor_share", "unmet_rate", "n_firms"]


def conditions():
    return [
        # (tag, mode, seeds, extra_args)
        ("rule", "rule", [7, 43, 101, 202], []),
        ("llm", "llm", [7, 43, 101, 202], ["--llm-ratio", "0.25"]),
        ("llm-nopersona", "llm", [7, 43], ["--llm-ratio", "0.25", "--no-persona"]),
        ("coop-rule", "rule", [7, 43], ["--institute", "coop"]),
        ("coop-llm", "llm", [7, 43], ["--llm-ratio", "0.25", "--institute", "coop"]),
        ("shock-llm", "llm", [7], ["--llm-ratio", "0.25", "--shock-factor", "0.45",
                                   "--shock-tick", "120"]),
    ]


def build_cmd(tag, mode, seed, extra):
    cmd = [sys.executable, str(ROOT / "experiments" / "run_mvp.py"),
           "--mode", mode, "--agents", "200", "--ticks", "200",
           "--seed", str(seed), "--tag", f"camp_{tag}_s{seed}",
           "--narr-every", "8", "--narr-sample", "24", "--workers", "8"]
    cmd += extra
    return cmd


def run_all():
    env_note = "PYTHONIOENCODING=utf-8"
    for tag, mode, seeds, extra in conditions():
        for seed in seeds:
            out = ROOT / "results" / f"camp_{tag}_s{seed}" / "metrics.csv"
            if out.exists():
                print(f"[跳过] camp_{tag}_s{seed} 已存在")
                continue
            print(f"[运行] camp_{tag}_s{seed} ...", flush=True)
            subprocess.run(build_cmd(tag, mode, seed, extra), check=True,
                           cwd=str(ROOT))


def tail_stats(run_dir: Path, k: int = 30) -> dict:
    m = pd.read_csv(run_dir / "metrics.csv").set_index("tick")
    cols = [c for c in COLS if c in m.columns]
    out = m[cols].tail(k).mean().to_dict()
    for c in COLS:
        out.setdefault(c, float("nan"))
    return out


def summarize():
    rows = []
    for tag, mode, seeds, extra in conditions():
        is_coop = "--institute" in extra
        for seed in seeds:
            # 目录名带 run_mvp 追加的后缀（_coop/_nopersona/_shock…），用 glob 匹配
            cands = sorted((ROOT / "results").glob(f"camp_{tag}_s{seed}*"))
            cands = [d for d in cands if (d / "metrics.csv").exists()]
            if not cands:
                continue
            d = cands[0]
            st = tail_stats(d)
            if is_coop:
                # pos_member 回填：coop 条件下 = 企业在职工人数之和（firms.csv）
                fp = d / "firms.csv"
                if fp.exists():
                    f = pd.read_csv(fp)
                    if len(f):
                        per_tick = f.groupby("tick").n_workers.sum()
                        st["pos_member"] = per_tick.tail(30).mean()
            else:
                st["pos_member"] = 0.0  # 私有制/冲击条件无社员位置
            st["condition"] = tag
            st["seed"] = seed
            rows.append(st)
    df = pd.DataFrame(rows)
    if not len(df):
        print("无结果可汇总")
        return
    agg = df.groupby("condition")[COLS].agg(["mean", "std", "count"])
    lines = ["# Campaign 汇总（末30期均值，跨种子 mean±std）", "",
             agg.round(3).to_markdown(), ""]

    # 预注册检验：LLM vs 规则（private 条件）；coop vs private（rule 侧）
    def mwu(ca, cb, col):
        a = df[df.condition == ca][col].dropna()
        b = df[df.condition == cb][col].dropna()
        if len(a) < 2 or len(b) < 2:
            return "n/a"
        try:
            u, p = mannwhitneyu(a, b, alternative="two-sided")
            return f"U={u:.0f}, p={p:.3f}"
        except Exception:
            return "n/a"

    lines += ["## 预注册检验（Mann-Whitney U 双侧）", ""]
    for col in ["gini", "top10", "p_ref", "pos_worker", "exploitation_rate"]:
        lines.append(f"- LLM vs 规则（private）· {col}: {mwu('llm', 'rule', col)}")
    for col in ["gini", "exploitation_rate", "labor_share", "pos_member"]:
        lines.append(f"- coop-rule vs rule · {col}: {mwu('coop-rule', 'rule', col)}")
    lines.append("")
    lines.append(f"- 判据声明：n=3–4/条件，p 值仅辅助；主张以方向一致性+效应量为准（见预注册）。")

    # H7 冲击检查
    shock_dirs = sorted(ROOT.glob("results/camp_shock-llm_s*"))
    if shock_dirs:
        d = shock_dirs[0]
        m = pd.read_csv(d / "metrics.csv").set_index("tick")
        pre = m.loc[100:119]
        post = m.loc[125:199]
        lines += ["", "## H7 冲击（tick120 预算×0.45）", "",
                  f"- 工人数：冲击前均值 {pre.pos_worker.mean():.1f} → 冲击后 {post.pos_worker.mean():.1f}",
                  f"- layoffs 总数：{m.loc[120:, 'layoffs'].sum():.0f}（冲击后）",
                  f"- unmet_rate：{pre.unmet_rate.mean():.2f} → {post.unmet_rate.mean():.2f}"]
        ap = d / "alienation.csv"
        if ap.exists():
            a = pd.read_csv(ap)
            pre_narr = a[a.tick < 120]
            post_narr = a[(a.tick >= 120) & (a.position == "unemployed")]
            lines.append(f"- 冲击后失业者叙事 n={len(post_narr)}（预注册判据 n>20："
                         f"{'满足' if len(post_narr) > 20 else '未满足→H7 inconclusive 如实报告'}）")
            if len(post_narr):
                lines.append(f"- 冲击前叙事总分均值 {pre_narr.total.mean():.2f} → "
                             f"冲击后失业者 {post_narr.total.mean():.2f}")
        sv = d / "survey.csv"
        if sv.exists():
            s = pd.read_csv(sv)
            lines.append(f"- 期末问卷：公平感 by position："
                         f"{s.groupby('position').fairness.mean().round(2).to_dict()}")

    # H9 拜物教（llm 主条件）
    fet = ROOT / "results" / "camp_llm_s7" / "fetishism.csv"
    ali = ROOT / "results" / "camp_llm_s7" / "alienation.csv"
    if fet.exists():
        f = pd.read_csv(fet)
        lines += ["", "## H9b 拜物教话语（指示器）", "",
                  f"- 交易叙事物化评分均值 {f.fetishism.mean():.2f}（n={len(f)}），"
                  f"来源：{f.source.value_counts().to_dict()}"]
    if (ROOT / "results" / "camp_llm_s7" / "survey.csv").exists():
        s = pd.read_csv(ROOT / "results" / "camp_llm_s7" / "survey.csv")
        lines += ["", "## H9a 阶级意识问卷（camp_llm_s7 期末）", "",
                  s.groupby("position")[["fairness", "conflict", "optimism"]]
                  .mean().round(2).to_markdown(), "",
                  "归因分布：" + s.groupby("position").attribution
                  .value_counts().to_string()]

    out = ROOT / "results" / "CAMPAIGN_SUMMARY.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("汇总：", out)
    print(agg.round(3).to_string())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--summary", action="store_true")
    args = ap.parse_args()
    if args.run:
        run_all()
    if args.summary or not args.run:
        summarize()
