"""全平台回归运行器（WP2 测试可信性版）。

判定规则（不再以 [PASS] 计数代替验收）：
1. 子进程退出码非 0            → 套件失败
2. 超时（默认 900s/套件）       → 套件失败
3. 输出含 [FAIL]               → 套件失败
4. 无任何 [PASS] 且退出码 0     → 失败（空跑不算过）
5. Traceback 出现               → 失败（同时记录摘录）
汇总写 data/test_stats.json；本脚本退出码非 0 当且仅当存在失败套件。
自检：python tests/run_all.py --selftest 构造一个必败套件验证判定链路。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITE_TIMEOUT_S = 900
SUITES = [
    "test_platform", "test_ledger", "test_pipeline", "test_benchmarks",
    "test_sociology", "test_politics", "test_media", "test_orglabor",
    "test_registry", "test_site", "test_god_bridge",
    "test_kernel_facilities", "test_cross_pack",
    "test_dayan_core", "test_dayan_models", "test_dayan_migration",
    "test_dayan_engines", "test_dayan_wave2", "test_dayan_families",
    "test_dayan_traffic_ped", "test_dayan_eco_batch", "test_dayan_sys",
    "test_dayan_met", "test_dayan_met_registry", "test_dayan_sys_extras",
    "test_dayan_eco_flagship", "test_dayan_catalog_map", "test_dayan_coupled",
    "test_dayan_agent", "test_dayan_net_final16", "test_dayan_final_batch",
    "test_dayan_fidelity", "test_dayan_runtime", "test_dayan_manifest",
    "test_dayan_experiment", "test_dayan_scene_state", "test_dayan_mechfix", "test_collection_core", "test_negative_cases", "test_e2e_pipeline",
    "test_repair_execution_inputs", "test_repair_same_run", "test_repair_artifacts",
    "test_repair_policy_contract", "test_repair_parameters", "test_repair_composer",
    "test_repair_requirements", "test_repair_report", "test_repair_datasets",
    "test_repair_custom_models", "test_repair_generative", "test_repair_resume",
    "test_repair_coupled_evacuation",
]


def judge_suite(name: str, returncode: int | None, stdout: str,
                stderr: str, duration_s: float, timed_out: bool = False,
                missing: bool = False) -> dict:
    """纯判定函数：单套件 → 结构化结论。独立出来便于单元测试。"""
    output = (stdout or "") + (stderr or "")
    reasons: list[str] = []
    if missing:
        reasons.append("套件文件不存在")
    if timed_out:
        reasons.append(f"超时>{SUITE_TIMEOUT_S}s")
    if returncode not in (0, None):
        reasons.append(f"退出码={returncode}")
    if "[FAIL]" in output:
        reasons.append("输出含 [FAIL]")
    n_pass = output.count("[PASS]")
    unittest_run = re.search(r"^Ran (\d+) tests? in ", output, re.M)
    unittest_ok = re.search(r"^OK(?: \(skipped=(\d+)\))?\s*$", output, re.M)
    if unittest_run and unittest_ok and returncode == 0:
        n_pass += int(unittest_run.group(1))-int(unittest_ok.group(1) or 0)
    if n_pass == 0 and not reasons:
        reasons.append("无任何 [PASS]（空跑）")
    tb_idx = output.find("Traceback (most recent call last)")
    if tb_idx >= 0:
        reasons.append("输出含 Traceback")
    verdict = "FAIL" if reasons else "PASS"
    excerpt = ""
    if verdict == "FAIL":
        tail = (stderr or "")[-400:] or output[tb_idx:tb_idx + 400] \
            if tb_idx >= 0 else (stderr or output)[-400:]
        excerpt = tail[:400]
    return {
        "suite": name, "verdict": verdict, "reasons": reasons,
        "passed": n_pass, "returncode": returncode,
        "duration_s": round(duration_s, 2), "excerpt": excerpt,
    }


def run_suite(name: str) -> dict:
    path = ROOT / "tests" / f"{name}.py"
    if not path.exists():
        return judge_suite(name, None, "", "", 0.0, missing=True)
    t0 = time.perf_counter()
    try:
        r = subprocess.run(
            [sys.executable, str(path)], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=SUITE_TIMEOUT_S,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            cwd=str(ROOT))
        return judge_suite(name, r.returncode, r.stdout, r.stderr,
                           time.perf_counter() - t0)
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode("utf-8", errors="replace") \
            if isinstance(e.stdout, bytes) else (e.stdout or "")
        err = (e.stderr or b"").decode("utf-8", errors="replace") \
            if isinstance(e.stderr, bytes) else (e.stderr or "")
        return judge_suite(name, None, out, err, SUITE_TIMEOUT_S,
                           timed_out=True)


def _selftest():
    """构造必败/必过样例，验证 judge_suite 判定链路本身可信。"""
    cases = [
        # (描述, judge参数, 期望verdict)
        ("正常通过", dict(returncode=0, stdout="[PASS] a\n[PASS] b",
                          stderr="", duration_s=1.0), "PASS"),
        ("非零退出码", dict(returncode=1, stdout="[PASS] a",
                            stderr="boom", duration_s=1.0), "FAIL"),
        ("超时", dict(returncode=None, stdout="", stderr="",
                      duration_s=900.0, timed_out=True), "FAIL"),
        ("含FAIL标记", dict(returncode=0, stdout="[PASS] a\n[FAIL] b",
                            stderr="", duration_s=1.0), "FAIL"),
        ("空跑", dict(returncode=0, stdout="(无测试)", stderr="",
                      duration_s=0.5), "FAIL"),
        ("Traceback但退出码0", dict(returncode=0,
                                    stdout="Traceback (most recent call last)\n x",
                                    stderr="", duration_s=1.0), "FAIL"),
        ("文件缺失", dict(returncode=None, stdout="", stderr="",
                          duration_s=0.0, missing=True), "FAIL"),
    ]
    bad = 0
    for desc, kw, expect in cases:
        got = judge_suite("selftest", **kw)["verdict"]
        ok = got == expect
        bad += 0 if ok else 1
        print(f"[{'PASS' if ok else 'FAIL'}] selftest {desc}: got={got} expect={expect}")
    print(f"[{'PASS' if bad == 0 else 'FAIL'}] selftest 汇总: {len(cases) - bad}/{len(cases)}")
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return _selftest()
    only = None
    if len(argv) > 1 and not argv[1].startswith("-"):
        only = argv[1]
    stats: dict = {"suites": {}, "passed": 0, "failed_suites": 0}
    suites = [only] if only else SUITES
    for t in suites:
        res = run_suite(t)
        stats["suites"][t] = res
        stats["passed"] += res["passed"]
        if res["verdict"] == "FAIL":
            stats["failed_suites"] += 1
        flag = "✓" if res["verdict"] == "PASS" else "✗"
        print(f"{flag} {t}: {res['passed']} PASS  {res['duration_s']}s"
              + (f"  ← {'; '.join(res['reasons'])}" if res["reasons"] else ""))
    stats["total"] = stats["passed"]
    stats["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    out = ROOT / "data" / "test_stats.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(stats, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"\n合计 {stats['passed']} 项 PASS，{stats['failed_suites']} 个套件失败"
          f" → {out}")
    return 1 if stats["failed_suites"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
