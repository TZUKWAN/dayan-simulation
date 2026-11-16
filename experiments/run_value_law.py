"""价值规律多商品实验（toy_value_law_v1，第一梯队命题1的LLM升级）。

设计（预注册 v0.1 附加）：
- 6 种商品，单位劳动产出 prod_g 不同 → 劳动价值（每件所需劳动小时）L_g = 1/prod_g。
- N 个 agent 每期选择生产哪种商品（LLM 决策或规则），产出 = 技能 × prod_g × A0。
- 消费：预算均分到 6 种商品（等份额偏好，需求与价格成反比 → Cobb-Douglas）。
- 价格动态：p_g' = p_g × (D_g/S_g)^0.25（阻尼），确定性。
- 价值规律判据（Cockshott–Cottrell 传统）：市场均价向量与劳动价值向量的
  Pearson/Spearman 相关随竞争进入而上升 → 价格被拉向劳动时间。

用法：
  python experiments/run_value_law.py --mode rule --ticks 200
  python experiments/run_value_law.py --mode llm --agents 12 --ticks 40 --workers 8
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GOODS = ["粮食", "布匹", "陶器", "铁器", "木器", "纸"]
A0 = 10.0  # 技能1.0每期基础产出

SYSTEM = ("你是微型经济中的独立生产者。根据行市决定本期生产哪种货。"
          "只输出JSON：{\"good\":\"名称\"}，名称必须从列表中选。")


def build_prompt(agent_ctx: str) -> list[dict]:
    msg = f"""六种货：{json.dumps(GOODS, ensure_ascii=False)}
行情（当前市价，每件）：
{agent_ctx}

选一种本期要生产的货。考虑：价高且做的人少的货可能更赚，但大家一起转产会压价。只输出JSON：{{"good":"..."}}"""
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": msg}]


def parse_good(text: str) -> str | None:
    import re
    if not text:
        return None
    m = re.search(r"\{[^{}]*\}", re.sub(r"```(?:json)?", "", text), re.S)
    if not m:
        # 兜底：文本中直接出现商品名
        for g in GOODS:
            if g in text:
                return g
        return None
    try:
        d = json.loads(m.group(0))
        g = str(d.get("good", "")).strip()
        for known in GOODS:
            if known in g:
                return known
    except Exception:
        pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["rule", "llm"], default="rule")
    ap.add_argument("--agents", type=int, default=36)
    ap.add_argument("--ticks", type=int, default=200)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--url", default="http://127.0.0.1:1234/v1")
    ap.add_argument("--model", default="qwen3.5-4b")
    ap.add_argument("--tag", default=None)
    args = ap.parse_args()

    tag = args.tag or f"valuelaw_{args.mode}_n{args.agents}_t{args.ticks}_s{args.seed}"
    outdir = ROOT / "results" / tag
    outdir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)
    # 技术：每种商品的单位劳动产出（对数正态，跨商品差异 ≈ 劳动价值差异）
    prod = np.exp(rng.gauss(0, 0.45) for _ in range(6)) if False else \
        np.array([float(np.exp(rng.gauss(0, 0.45))) for _ in range(6)])
    prod = np.clip(prod, 0.4, 2.5)
    labor_value = 1.0 / (A0 * prod)  # 每件所需劳动当量（技能1.0·期/件）
    skills = np.clip([rng.lognormvariate(0, 0.3) for _ in range(args.agents)], 0.4, 2.5)
    prices = np.ones(6)
    choices = [int(rng.randrange(6)) for _ in range(args.agents)]
    budget = 30.0

    client = None
    if args.mode == "llm":
        from src.agents.llm_client import LMStudioClient
        client = LMStudioClient(base_url=args.url, model=args.model,
                                cache_path=outdir / "cache.jsonl",
                                log_path=outdir / "llm_log.jsonl",
                                max_workers=args.workers, default_max_tokens=120)

    rows = []
    for t in range(args.ticks):
        # 供给
        supply = np.zeros(6)
        for i, g in enumerate(choices):
            supply[g] += A0 * skills[i] * prod[g] * 0.1  # 总量约束（防止爆炸）
        # 需求（等份额预算，价格弹性 -1）
        demand = np.array([budget * args.agents / 6 / max(prices[g], 1e-6)
                           for g in range(6)])
        # 成交量与价格动态（阻尼）
        traded = np.minimum(supply, demand)
        ratio = np.where(supply > 0, demand / np.maximum(supply, 1e-9), 2.0)
        prices = prices * np.clip(ratio, 0.75, 1.33) ** 0.25
        # 记录
        pr = pearsonr(prices, labor_value)[0] if t >= 1 else np.nan
        sr = spearmanr(prices, labor_value)[0] if t >= 1 else np.nan
        rows.append({"tick": t, **{f"p_{g}": round(prices[g], 4) for g in range(6)},
                     "corr_pearson": pr, "corr_spearman": sr,
                     "n_by_good": json.dumps([int((np.array(choices) == g).sum())
                                              for g in range(6)])})
        # 选择更新
        if args.mode == "llm":
            ctx = "\n".join(f"- {GOODS[g]}：{prices[g]:.2f}（本期转产人数{int((np.array(choices)==g).sum())}，"
                             f"劳动价值约{labor_value[g]:.2f}）" for g in range(6))
            jobs = [{"messages": build_prompt(ctx), "temperature": 0.4,
                     "max_tokens": 120} for _ in range(args.agents)]
            outs = client.batch(jobs)
            for i, o in enumerate(outs):
                g = parse_good(o)
                if g is not None:
                    choices[i] = GOODS.index(g)
        else:
            # 规则：向"价格/劳动价值"比率高处流动（套利进入），带随机扰动
            reward = prices / labor_value
            reward = reward * np.array([0.9 + 0.2 * rng.random() for _ in range(6)])
            best = int(np.argmax(reward))
            for i in range(args.agents):
                if rng.random() < 0.35:
                    choices[i] = best if rng.random() < 0.7 else int(rng.randrange(6))

    df = pd.DataFrame(rows)
    df.to_csv(outdir / "metrics.csv", index=False)
    tail = df.tail(50)
    head = df.head(50)
    (outdir / "config.json").write_text(json.dumps(
        {"mode": args.mode, "agents": args.agents, "ticks": args.ticks,
         "seed": args.seed, "prod": prod.tolist(),
         "labor_value": labor_value.tolist()}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    md = ["# 价值规律实验报告（toy_value_law_v1）", "",
          f"- mode={args.mode} agents={args.agents} ticks={args.ticks} seed={args.seed}",
          f"- 劳动价值向量：{dict(zip(GOODS, labor_value.round(3).tolist()))}",
          f"- 末50期 均价-劳动价值 Pearson {tail.corr_pearson.mean():.3f} / "
          f"Spearman {tail.corr_spearman.mean():.3f}",
          f"- 首50期 Pearson {head.corr_pearson.mean():.3f}（对照）",
          "",
          "判据：随套利进入，价格向劳动价值收敛 → 相关应上升并趋于显著为正。",
          "Cockshott–Cottrell（1997）在真实投入产出表上测得 r²≈0.95，为本实验的极限参照。"]
    (outdir / "REPORT.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
