"""场景规约驱动的统一实验入口（v2 平台对外主入口）。

T1: 按 spec.pack 从注册表分发实例化（不再硬编码 polecon）
T4: 运行即登记规约注册表（幂等）+ 引用计数 + 句柄落盘
T8: 运行后遮蔽审计（LLM 日志理论词汇扫描，命中即标 FAIL）
T9: 发散监测（基尼翻倍/p_ref 触底，patience 触发记录）
T17: 决策循环走 pack 钩子（collect_llm_requests/rule_decision），包无关

用法：
  python experiments/run_spec.py --spec site/teachings/schelling_segregation.yaml --tag my_run
  python experiments/run_spec.py --spec ... --mode llm --workers 8
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.kernel import (Kernel, KernelConfig, load_scenario,  # noqa: E402
                        default_registry)
from src.packs import create_pack  # noqa: E402  (导入即注册全部包)


def _flatten(row: dict) -> dict:
    """dict 值平铺为前缀键（positions→pos_*；exploitation→裸键）。"""
    out = {}
    for k, v in row.items():
        if isinstance(v, dict):
            for kk, vv in v.items():
                out[f"{k}_{kk}" if k == "positions" else kk] = vv
        else:
            out[k] = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--mode", choices=["rule", "llm"], default=None)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--url", default="http://127.0.0.1:1234/v1")
    ap.add_argument("--model", default="qwen3.5-4b")
    args = ap.parse_args()

    scenario = load_scenario(args.spec)
    tag = args.tag or scenario.name
    run_dir = ROOT / "results" / f"spec_{tag}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # 效度闸门
    gate_issues = scenario.check_gates()
    verified = not gate_issues
    print("✓ 效度闸门通过" if verified else "⚠ 效度闸门未过（不得标记为'已检验'）：")
    for g in gate_issues:
        print(f"   - {g}")

    # T1: 按规约分发理论包（不再硬编码）
    mode = args.mode or ("llm" if scenario.population.get("LLM比例") else "rule")
    population = dict(scenario.population)
    if mode == "rule":
        population["LLM比例"] = 0.0
    pack = create_pack(scenario.pack, population=population,
                       institutions=scenario.institutions,
                       seed=scenario.seed,
                       intervention=scenario.intervention)
    print(f"✓ 理论包分发：{scenario.pack} → {type(pack).__name__}")

    # 未知测量钩子告警（T18：不再静默跳过）
    unknown = [m for m in scenario.measurement_plan
               if m not in pack.measure_hooks]
    if unknown:
        print(f"⚠ measurement_plan 中无对应钩子（将不产生数据）：{unknown}")

    llm_ratio = float(population.get("LLM比例", 0.0) or 0.0)
    is_polecon_style = hasattr(pack, "world")
    # polecon 按比例；通用包（自带 collect_llm_requests）llm 模式直接启用
    use_llm = mode == "llm" and (llm_ratio > 0 or not is_polecon_style)
    if mode == "llm" and not use_llm:
        print("⚠ --mode llm 但规约 LLM比例=0，按 rule 运行")
    if use_llm and not hasattr(pack, "collect_llm_requests"):
        raise SystemExit(f"包 {scenario.pack} 暂无 LLM 语义层"
                         f"（无 collect_llm_requests 钩子），请用 --mode rule")

    client = None
    llm_decider = None
    if use_llm:
        from src.agents.llm_client import LMStudioClient
        from src.agents.decisions import LLMBatchDecider
        client = LMStudioClient(base_url=args.url, model=args.model,
                                cache_path=run_dir / "cache.jsonl",
                                log_path=run_dir / "llm_log.jsonl",
                                max_workers=args.workers)
        llm_decider = LLMBatchDecider(client)

    kernel = Kernel(pack, KernelConfig(
        seed=scenario.seed,
        log_path=run_dir / "events.jsonl",
        invariant_strict=True))
    kernel.init_world()

    # T9: 发散监测（polecon 类经济包的通用 watches；其他包跳过）
    hooks = pack.measure_hooks
    if "wealth_gini" in hooks and hooks["wealth_gini"] is not None:
        g0 = float(hooks["wealth_gini"](kernel))
        if g0 > 0:
            kernel.add_divergence_watch("基尼翻倍", lambda k: float(
                hooks["wealth_gini"](k)), threshold=2.0 * g0,
                direction="above", patience=15)
    if "p_ref" in hooks and hooks["p_ref"] is not None:
        p0 = float(hooks["p_ref"](kernel))
        kernel.add_divergence_watch("p_ref触底", lambda k: float(
            hooks["p_ref"](k)), threshold=0.55 * p0,
            direction="below", patience=15)

    # T4: 规约登记 + 引用计数 + 句柄落盘
    registry = default_registry()
    entry = registry.register(scenario.raw, author="run_spec",
                              tags=[scenario.pack],
                              summary=f"运行于 {tag}")
    registry.record_experiment(entry.handle)
    (run_dir / "spec_handle.txt").write_text(entry.cite(), encoding="utf-8")
    print(f"✓ 规约登记：{entry.cite()}")

    # 初始意图（规则打底；仅 polecon 类带 world 与 rule_decision 的包需要）
    if hasattr(pack, "rule_decision") and hasattr(pack, "world"):
        for a in kernel.agents:
            pack.action_handler(a, pack.rule_decision(a), kernel)

    metrics_rows = []
    for t in range(scenario.ticks):
        # T17 + 审计修复: 包无关决策循环（LLM 协议按包分发）
        decisions: dict[int, dict] = {}
        if use_llm and llm_decider is not None:
            reqs = pack.collect_llm_requests(t)
            if reqs:
                decisions.update(llm_decider.decide_batch(reqs, pack=pack))
        if is_polecon_style and hasattr(pack, "rule_decision"):
            # polecon：llm 模式仅非 LLM agent 走规则（LLM agent 意向跨 tick 保留）；
            # 通用包：未抽中 LLM 的 agent 由包内部动力学处理，不注入规则
            for a in kernel.agents:
                if mode == "rule" or not getattr(a, "llm", False):
                    if a.id not in decisions:
                        decisions[a.id] = pack.rule_decision(a)
        for aid, d in decisions.items():
            pack.action_handler(kernel.agents[aid], d, kernel)

        ledger = kernel.step()
        row = {"tick": t}
        for m in scenario.measurement_plan:
            if m in pack.measure_hooks and pack.measure_hooks[m] is not None:
                row[m] = pack.measure_hooks[m](kernel)
        metrics_rows.append(_flatten(row))
        if (t + 1) % 25 == 0 or t == 0:
            g = metrics_rows[-1].get("wealth_gini", float("nan"))
            print(f"[{t+1}/{scenario.ticks}] gini={g:.3f} "
                  f"守恒残差={kernel.max_invariant_residual():.1e} "
                  f"发散={list(kernel.divergences) or '无'}", flush=True)

    df = pd.DataFrame(metrics_rows)
    df.to_csv(run_dir / "metrics.csv", index=False)

    # T8: 遮蔽审计（LLM 日志理论词汇扫描）
    masking = "skipped（无 LLM 调用）"
    if use_llm and (run_dir / "llm_log.jsonl").exists():
        from src.kernel.masking_audit import audit_llm_log
        hits = audit_llm_log(run_dir / "llm_log.jsonl")
        masking = "PASS" if not hits else f"FAIL: {hits}"
        if hits:
            print(f"⛔ 遮蔽审计失败：{hits}")

    cfg = {"scenario": scenario.raw, "mode": mode, "tag": tag,
           "verified": verified,
           "spec_handle": entry.cite(),
           "max_invariant_residual": kernel.max_invariant_residual(),
           "divergences": kernel.divergences,
           "masking_audit": masking,
           "llm": {"http": client.n_calls_http if client else 0,
                   "cached": client.n_cache_hits if client else 0}}
    (run_dir / "config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完成：{run_dir}")
    print(f"  规约句柄：{entry.cite()}")
    print(f"  货币/不变量最大残差：{kernel.max_invariant_residual():.2e}")
    print(f"  发散监测：{kernel.divergences or '无'}")
    print(f"  遮蔽审计：{masking}")


if __name__ == "__main__":
    main()
