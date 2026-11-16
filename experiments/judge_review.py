"""judge 人工复核工具（R5：把人工参与压缩到"只打分"）。

两个命令：
  make   — 从 alienation.csv 抽样生成评分表 review_sheet.csv
           （列：narrative + 五维空列；你只需在空列填 1-5）
  score  — 读回填后的评分表，计算人工 vs LLM 一致率
           （逐维 MAE、精确一致率、±1 容差一致率、总分相关）

工作流：
  python experiments/judge_review.py make --run mvp_llm_s7 --n 40
  # → 打开 results/judge_review_<run>/review_sheet.csv，对每条叙事打 1-5 分
  # → 保存后：
  python experiments/judge_review.py score --run mvp_llm_s7
  # → 生成 results/judge_review_<run>/agreement_report.md（可直接引用）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DIMS = ["powerlessness", "meaninglessness", "normlessness", "isolation",
        "self_estrangement"]
DIM_CN = {"powerlessness": "无力感", "meaninglessness": "无意义感",
          "normlessness": "无规范感", "isolation": "孤立感",
          "self_estrangement": "自我疏离"}


def _run_dir(run: str) -> Path:
    d = ROOT / "results" / run
    if not (d / "alienation.csv").exists():
        raise SystemExit(f"未找到 {d}/alienation.csv")
    return d


def make_sheet(run: str, n: int, seed: int):
    d = _run_dir(run)
    a = pd.read_csv(d / "alienation.csv")
    # 分层抽样：各 position 尽量均匀
    rng = np.random.RandomState(seed)
    picked = []
    per = max(1, n // a.position.nunique())
    for pos, grp in a.groupby("position"):
        take = min(per, len(grp))
        picked.append(grp.sample(take, random_state=seed))
    sheet = pd.concat(picked)
    if len(sheet) > n:
        sheet = sheet.sample(n, random_state=seed)
    out_dir = d / f"judge_review_{run}"
    out_dir.mkdir(exist_ok=True)
    out = sheet[["tick", "agent", "position", "narrative",
                 "powerlessness", "meaninglessness", "normlessness",
                 "isolation", "self_estrangement"]].copy()
    for c in DIMS:
        out[f"人工_{c}"] = ""   # 空列：你填 1-5
    out.to_csv(out_dir / "review_sheet.csv", index=False, encoding="utf-8-sig")
    # 说明文件
    guide = f"""# 人工复核评分说明

## 你要做的（唯一一步）
打开 `review_sheet.csv`，阅读每行 narrative（agent 第一人称叙事），
在最右 5 个"人工_*"空列填 1-5 分（1=完全没有，5=非常强）：
- 人工_powerlessness（无力感）：处境不受自己控制、说了不算
- 人工_meaninglessness（无意义感）：干的活没意义、不明白为什么
- 人工_normlessness（无规范感）：没规则可依、各顾各
- 人工_isolation（孤立感）：与人疏远、无归属
- 人工_self_estrangement（自我疏离）：做的不是自己想做的、不像自己

只对 narrative 文本评分（不要看 LLM 已给的分数列，避免锚定）。
填完保存，运行：
  python experiments/judge_review.py score --run {run}

## 抽样
- 来源：{run}/alienation.csv（共 {len(a)} 条）
- 分层：{sheet.position.value_counts().to_dict()}
- 种子：{seed}
"""
    (out_dir / "README.md").write_text(guide, encoding="utf-8")
    print(f"评分表已生成：{out_dir / 'review_sheet.csv'}")
    print(f"说明：{out_dir / 'README.md'}")
    print(f"你只需在 5 个'人工_*'列填 1-5，然后运行 score 命令。")


def score_sheet(run: str):
    d = _run_dir(run)
    out_dir = d / f"judge_review_{run}"
    path = out_dir / "review_sheet.csv"
    if not path.exists():
        raise SystemExit("评分表不存在，先运行 make 命令")
    df = pd.read_csv(path, encoding="utf-8-sig")
    filled = df.dropna(subset=[f"人工_{c}" for c in DIMS], how="any")
    if len(filled) == 0:
        raise SystemExit("评分表没有已填行（人工_* 列全空）")
    lines = ["# judge 人工复核一致性报告", "",
             f"- 来源：{run}", f"- 已复核：{len(filled)}/{len(df)} 条",
             f"- LLM 评定来源：{df.source.iloc[0] if 'source' in df else 'llm_judge'}", ""]
    rows = []
    for c in DIMS:
        human = filled[f"人工_{c}"].astype(float)
        llm = filled[c].astype(float)
        mae = float(np.mean(np.abs(human - llm)))
        exact = float(np.mean(human == llm))
        within1 = float(np.mean(np.abs(human - llm) <= 1))
        rows.append({"维度": DIM_CN[c], "MAE": round(mae, 3),
                     "精确一致率": f"{exact:.0%}", "±1一致率": f"{within1:.0%}",
                     "人工均值": round(human.mean(), 2),
                     "LLM均值": round(llm.mean(), 2)})
    stat = pd.DataFrame(rows)
    lines.append("## 逐维一致率\n")
    lines.append(stat.to_markdown(index=False))
    human_total = filled[[f"人工_{c}" for c in DIMS]].astype(float).sum(axis=1)
    llm_total = filled[DIMS].astype(float).sum(axis=1)
    r = float(np.corrcoef(human_total, llm_total)[0, 1])
    lines += ["", "## 总分\n",
              f"- Pearson r（人工总分 vs LLM 总分）：**{r:.3f}**",
              f"- 总分 MAE：{float(np.mean(np.abs(human_total - llm_total))):.2f}"
              f"（满分 25）", ""]
    # 组间排序保留性（H4 的关键）：人工分下组间排序是否与 LLM 一致
    if "position" in filled.columns:
        g = filled.groupby("position")[[f"人工_{c}" for c in DIMS]].mean()
        lines += ["## 人工评分组间均值（组间排序与 LLM 对照）\n",
                  g.round(2).to_markdown(), ""]
    verdict = ("**通过**（总分 r≥0.6 且逐维 MAE≤1.2）"
               if r >= 0.6 and stat["MAE"].max() <= 1.2
               else "**信度不足**（需在论文中降格 LLM-judge 主张，或扩样复核）")
    lines.append(f"## 结论：{verdict}")
    (out_dir / "agreement_report.md").write_text("\n".join(lines),
                                                 encoding="utf-8")
    print("\n".join(lines))
    print(f"\n报告：{out_dir / 'agreement_report.md'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("--run", required=True)
    m.add_argument("--n", type=int, default=40)
    m.add_argument("--seed", type=int, default=42)
    s = sub.add_parser("score")
    s.add_argument("--run", required=True)
    args = ap.parse_args()
    if args.cmd == "make":
        make_sheet(args.run, args.n, args.seed)
    else:
        score_sheet(args.run)
