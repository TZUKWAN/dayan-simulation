"""MVP 实验编排：toy_capitalism_v0。

用法示例：
  # 冒烟测试（全 LLM、小规模）
  python experiments/run_mvp.py --mode llm --agents 12 --ticks 6 --llm-ratio 1.0 --tag smoke

  # 正式 LLM 组（混合人口：25% LLM agent + 规则填充）
  python experiments/run_mvp.py --mode llm --agents 200 --ticks 60 --llm-ratio 0.25 --tag mvp_llm

  # 规则基线组（层4基线A，零 LLM 调用）
  python experiments/run_mvp.py --mode rule --agents 200 --ticks 60 --tag mvp_rule

产物（results/<tag>/）：config.json, metrics.csv, firms.csv, agents_final.csv,
narratives.jsonl, transitions.json, REPORT.md, *.png, llm_log.jsonl, cache.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.decisions import RuleDecider, LLMBatchDecider, rule_decision  # noqa: E402
from src.agents.llm_client import LMStudioClient  # noqa: E402
from src.agents.persona import make_personas  # noqa: E402
from src.ledger.economy import Agent, Params, World  # noqa: E402
from src.measures.alienation import AlienationPipeline  # noqa: E402
from src.measures.transaction import SurveyPipeline, TransactionPipeline  # noqa: E402
from src.measures.metrics import (class_matrix, exploitation_stats, gini,  # noqa: E402
                                  top_shares)
from src.validity.report import generate_report  # noqa: E402


def build_population(n: int, llm_ratio: float, rng: random.Random,
                     decide_every: int) -> list[Agent]:
    personas = make_personas(n, rng)
    agents = []
    n_llm = int(round(n * llm_ratio))
    llm_flags = [True] * n_llm + [False] * (n - n_llm)
    rng.shuffle(llm_flags)
    for i in range(n):
        skill = float(np.clip(rng.lognormvariate(0.0, 0.35), 0.4, 2.5))
        savings = float(np.clip(rng.lognormvariate(np.log(15.0), 0.6), 1.0, 200.0))
        agents.append(Agent(i, personas[i], skill, savings,
                            llm=llm_flags[i],
                            dec_offset=rng.randrange(decide_every)))
    return agents


def record_tick(world: World, t: int, ledger: dict, prev_pos: dict,
                cur_pos: dict, trans_acc: dict) -> dict:
    p = world.params
    wv = world.wealth_vector()
    g = gini(wv)
    ts = top_shares(wv)
    pos = world.positions()
    ex = exploitation_stats(world)
    n = len(world.agents)
    conserv = (ledger["sum_savings_after"] - ledger["sum_savings_before"])
    # 位置转移
    cm = class_matrix(prev_pos, cur_pos)
    for k, v in cm.items():
        trans_acc[k] = trans_acc.get(k, 0) + v
    layoffs = cm.get("worker->unemployed", 0) + cm.get("worker->self", 0)         + cm.get("member->unemployed", 0) + cm.get("member->self", 0)
    return {
        "tick": t, "gini": g, **{f"top{k}": ts[f"top{k}"] for k in (10, 1)},
        "bottom50": ts["bottom50"],
        "pos_unemployed": pos["unemployed"], "pos_worker": pos["worker"],
        "pos_self": pos["self"], "pos_employer": pos["employer"],
        "unemployment": pos["unemployed"] / n,
        "p_ref": world.p_ref, "n_firms": len(world.firms),
        "wages": ledger["wages"], "profits": ledger["profits"],
        "exploitation_rate": ex["exploitation_rate"],
        "labor_share": ex["labor_share"],
        "n_firms_with_workers": ex["n_firms_with_workers"],
        "sales": ledger["sales"], "capital_buy": ledger["capital_buy"],
        "conserv_err": conserv,
        "unmet_rate": float(np.mean([a.unmet > 1e-9 for a in world.agents])),
        "layoffs": layoffs,
    }


def sample_narrators(world: World, k: int) -> list[Agent]:
    llm_agents = [a for a in world.agents if a.llm]
    by_pos: dict[str, list[Agent]] = {}
    for a in llm_agents:
        by_pos.setdefault(a.position, []).append(a)
    picked: list[Agent] = []
    per = max(1, k // 4)
    for pos in ("worker", "self", "employer", "unemployed"):
        grp = by_pos.get(pos, [])
        rng = random.Random(1234 + world.tick_no)
        rng.shuffle(grp)
        picked.extend(grp[:per])
    if len(picked) < k:
        rest = [a for a in llm_agents if a not in picked]
        rng = random.Random(777 + world.tick_no)
        rng.shuffle(rest)
        picked.extend(rest[: k - len(picked)])
    return picked[:k]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["llm", "rule", "mixed"], default="llm")
    ap.add_argument("--agents", type=int, default=200)
    ap.add_argument("--ticks", type=int, default=60)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--llm-ratio", type=float, default=0.25)
    ap.add_argument("--decide-every", type=int, default=4)
    ap.add_argument("--narr-every", type=int, default=10)
    ap.add_argument("--narr-sample", type=int, default=18)
    ap.add_argument("--workers", type=int, default=6, help="LLM 并发数")
    ap.add_argument("--max-tokens", type=int, default=200)
    ap.add_argument("--url", default="http://127.0.0.1:1234/v1")
    ap.add_argument("--model", default="qwen3.5-4b")
    ap.add_argument("--tag", default=None)
    ap.add_argument("--no-narrative", action="store_true")
    ap.add_argument("--no-persona", action="store_true", help="消融B：去除人设背景（遮蔽消融）")
    ap.add_argument("--institute", choices=["private", "coop"], default="private",
                    help="制度变体（模式C）：private=私有雇佣 | coop=生产合作社")
    ap.add_argument("--shock-factor", type=float, default=1.0,
                    help="需求冲击倍率（1.0=无冲击）")
    ap.add_argument("--shock-tick", type=int, default=-1, help="冲击起始tick")
    args = ap.parse_args()

    tag = args.tag or f"{args.mode}_n{args.agents}_t{args.ticks}_s{args.seed}"
    if args.no_persona:
        tag += "_nopersona"
    if args.institute != "private":
        tag += f"_{args.institute}"
    if args.shock_factor != 1.0:
        tag += f"_shock{args.shock_factor:g}@t{args.shock_tick}"
    run_dir = ROOT / "results" / tag
    run_dir.mkdir(parents=True, exist_ok=True)

    params = Params(decide_every=args.decide_every, institute=args.institute,
                    shock_tick=args.shock_tick,
                    shock_factor=args.shock_factor)
    rng = random.Random(args.seed)
    agents = build_population(args.agents, args.llm_ratio if args.mode != "rule" else 0.0,
                              rng, args.decide_every)
    if args.no_persona:
        for a in agents:
            a.persona = {"name": a.persona["name"], "age": 0, "trait": ""}
    world = World(params, agents)

    use_llm = args.mode in ("llm", "mixed")
    client = None
    if use_llm:
        client = LMStudioClient(base_url=args.url, model=args.model,
                                cache_path=run_dir / "cache.jsonl",
                                log_path=run_dir / "llm_log.jsonl",
                                max_workers=args.workers,
                                default_max_tokens=args.max_tokens)
    llm_decider = LLMBatchDecider(client) if use_llm else None
    rule_decider = RuleDecider()

    cfg = {
        "n_agents": args.agents, "ticks": args.ticks, "seed": args.seed,
        "mode": args.mode, "llm_ratio": args.llm_ratio if use_llm else 0.0,
        "decide_every": args.decide_every, "narr_every": args.narr_every,
        "narr_sample": args.narr_sample, "url": args.url, "model": args.model,
        "params": vars(params),
        "no_person": args.no_persona,
        "institute": args.institute,
        "shock_factor": args.shock_factor, "shock_tick": args.shock_tick,
        "llm_desc": f"{args.model} @ {args.url}（本地 LM Studio）" if use_llm else "无（纯规则基线）",
    }
    (run_dir / "config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    # 初始意图（规则打底，保证每个 agent 有初始行为）
    world.apply_decisions({a.id: rule_decision(a, world) for a in world.agents})

    metrics_rows, firm_rows = [], []
    trans_acc: dict[str, int] = {}
    prev_pos = {a.id: a.position for a in world.agents}
    alien_rows = []
    fet_rows = []
    t0 = time.time()

    for t in range(args.ticks):
        # --- 决策收集（T17: 走包钩子协议，与 run_spec/god_bridge 同一循环）---
        decisions: dict[int, dict] = {}
        req_ids = world.collect_decision_requests(t)
        if use_llm and req_ids:
            dec = llm_decider.decide_batch([world.agent(i) for i in req_ids], world)
            decisions.update(dec)
        # 规则 agent（以及 rule 模式的全部）每 tick 重算（成本可忽略）
        if args.mode == "rule":
            rule_ids = [a.id for a in world.agents]
        else:
            rule_ids = [a.id for a in world.agents if not a.llm]
        for aid in rule_ids:
            decisions[aid] = rule_decision(world.agent(aid), world)
        world.apply_decisions(decisions)

        # --- 确定性经济步进 ---
        ledger = world.step(t)

        # --- 记录 ---
        cur_pos = {a.id: a.position for a in world.agents}
        metrics_rows.append(record_tick(world, t, ledger, prev_pos, cur_pos, trans_acc))
        prev_pos = cur_pos
        for f in world.firms.values():
            if f.workers:
                firm_rows.append({
                    "tick": t, "fid": f.fid, "owner": f.owner_id,
                    "n_workers": len(f.workers), "capital": round(f.capital, 2),
                    "wage": round(f.wage, 2), "price": round(f.price, 2),
                    "inventory": round(f.inventory, 2),
                    "revenue": round(f.revenue, 2), "wage_bill": round(f.wage_bill, 2),
                    "economic_profit": round(f.revenue - f.wage_bill
                                             - params.delta * params.P_K * f.capital_used, 2),
                })

        # --- 叙事测量（双通道轮替：奇数轮=生活/异化，偶数轮=交易/物化） ---
        if use_llm and not args.no_narrative and (t + 1) % args.narr_every == 0:
            narrators = sample_narrators(world, args.narr_sample)
            rnd = (t + 1) // args.narr_every
            if rnd % 2 == 1:
                alien_rows.extend(AlienationPipeline(client).run_round(narrators, world, t))
            else:
                fet_rows.extend(TransactionPipeline(client).run_round(narrators, world, t))

        if (t + 1) % 10 == 0 or t == 0:
            el = time.time() - t0
            print(f"[tick {t+1}/{args.ticks}] {el:.0f}s  pos={world.positions()}  "
                  f"p_ref={world.p_ref:.2f}  llm(http/cached)={client.n_calls_http if client else 0}/"
                  f"{client.n_cache_hits if client else 0}", flush=True)

    # --- 期末阶级意识问卷（H9a） ---
    if use_llm and not args.no_narrative:
        survey_agents = [a for a in world.agents if a.llm]
        rows = SurveyPipeline(client).run(survey_agents, world, args.ticks - 1)
        if rows:
            pd.DataFrame(rows).to_csv(run_dir / "survey.csv", index=False)
            with open(run_dir / "survey_answers.jsonl", "w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + chr(10))

    # --- 落盘 ---
    pd.DataFrame(metrics_rows).to_csv(run_dir / "metrics.csv", index=False)
    pd.DataFrame(firm_rows).to_csv(run_dir / "firms.csv", index=False)
    pd.DataFrame([{
        "id": a.id, "position": a.position, "skill": round(a.skill, 3),
        "savings": round(a.savings, 2), "capital": a.capital,
        "wealth": round(a.wealth(params.P_K), 2), "income_last": round(a.income, 2),
        "llm": a.llm, "persona": json.dumps(a.persona, ensure_ascii=False),
    } for a in world.agents]).to_csv(run_dir / "agents_final.csv", index=False)
    (run_dir / "transitions.json").write_text(
        json.dumps(trans_acc, ensure_ascii=False, indent=2), encoding="utf-8")
    if fet_rows:
        pd.DataFrame(fet_rows).to_csv(run_dir / "fetishism.csv", index=False)
        with open(run_dir / "transaction_narratives.jsonl", "w", encoding="utf-8") as f:
            for r in fet_rows:
                f.write(json.dumps(r, ensure_ascii=False) + chr(10))
    if alien_rows:
        pd.DataFrame(alien_rows).to_csv(run_dir / "alienation.csv", index=False)
        with open(run_dir / "narratives.jsonl", "w", encoding="utf-8") as f:
            for r in alien_rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    stats = {}
    if client:
        stats = {"http_calls": client.n_calls_http, "cache_hits": client.n_cache_hits,
                 "llm_decisions": llm_decider.stats["llm"],
                 "decision_fallbacks": llm_decider.stats["fallback"],
                 "firms_closed": len(world.closed_events)}
        (run_dir / "llm_stats.json").write_text(
            json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    rep = generate_report(run_dir, args.mode, args.seed, cfg)
    el = time.time() - t0
    print(f"完成：{el:.0f}s  报告：{rep}")
    if stats:
        print("LLM 统计：", stats)


if __name__ == "__main__":
    main()
