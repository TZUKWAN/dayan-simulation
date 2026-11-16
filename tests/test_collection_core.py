"""采集底座核心离线单元测试：注册表状态机、预设解析、引擎任务账本、
已完成真实采集的盘上证据一致性。真实网络采集证据见 data/collection/。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dayan.collection import registry, presets, engine  # noqa: E402
from dayan.agent.data_tools import search_sources, run_preset  # noqa: E402


def run_tests():
    passed, failed = 0, 0

    def check(name, cond, detail=""):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"[PASS] {name}")
        else:
            failed += 1
            print(f"[FAIL] {name} {detail}")

    # ---- 注册表 ----
    m = registry.matrix()
    check("矩阵≥30源", len(m) >= 30, f"n={len(m)}")
    cats = {r["cat"] for r in m}
    check("8类全覆盖", cats == set(registry.CATS), f"cats={cats}")
    check("状态值合法", all(r["state"] in registry.STATES for r in m))
    live = [r["source_id"] for r in m if r["state"] == "live"]
    check("live≥12源", len(live) >= 12, f"live={live}")
    cn_live = [s for s in live if s.startswith("cn_")]
    check("中国官方live≥2", len(cn_live) >= 2, f"{cn_live}")
    # 非法状态拒绝
    try:
        registry.set_state("__test__", "super_live")
        check("非法状态被拒", False)
    except ValueError:
        check("非法状态被拒", True)

    # ---- 预设 ----
    p = presets.list_presets()
    check("预设≥6", len(p) >= 6, f"n={len(p)}")
    # 占位符缺失报错（不静默）
    pr = presets.get_preset("pop_employment_wb")
    try:
        presets.resolve_params(pr, {})
        check("缺占位符报错", False)
    except ValueError:
        check("缺占位符报错", True)
    # 地区别名映射
    resolved = presets.resolve_params(pr, {"indicator": "SP.POP.TOTL",
                                           "country": "中国",
                                           "year_from": 2019, "year_to": 2024})
    check("地区别名自动映射 中国→CHN", resolved["country"] == "CHN",
          f"country={resolved['country']}")

    # ---- 引擎账本（盘上真实任务） ----
    tasks = engine.list_tasks()
    ok_tasks = [t for t in tasks if t["status"] in ("done", "partial")
                and t.get("n_records", 0) > 0]
    check("盘上成功任务≥12", len(ok_tasks) >= 12, f"n={len(ok_tasks)}")
    themes = {t.get("theme") for t in ok_tasks}
    check("主题≥6", len(themes) >= 6, f"themes={sorted(themes)[:8]}…")
    # partial 如实标记（任务书：预算截断必须partial）
    partials = [t for t in tasks if t.get("partial")]
    check("partial 机制存在且被真实使用", len(partials) >= 1,
          f"n_partial={len(partials)}")
    # 原始快照哈希一致性（抽验1个任务）
    if ok_tasks:
        t0 = ok_tasks[0]
        d = ROOT / "data" / "collections" / t0["collection_id"]
        manifest_ok = (d / "records.jsonl").exists() and \
                      any((d / "originals").glob("page_*.raw"))
        check("原始快照+记录文件在盘", manifest_ok, str(d))
        if manifest_ok:
            first = t0["pages"][0]
            import hashlib
            real = hashlib.sha256((ROOT / "data" / "collections" /
                                   first["raw"]).read_bytes()).hexdigest()
            check("页哈希可复算", real == first["sha256"])

    # ---- Agent 工具链 ----
    r = search_sources("就业")
    check("search_sources 主题检索", r["ok"] and r["payload"]["n_sources"] >= 3)
    r2 = run_preset("pop_employment_wb",
                    {"indicator": "SP.POP.TOTL", "country": "中国",
                     "year_from": "2019", "year_to": "2024"})
    # 已缓存任务幂等返回（同参数同collection_id不重复采集）
    check("同参数幂等复用（不冒称重采）", r2["ok"] and
          r2["payload"].get("status") in ("done", "partial"))

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run_tests())
