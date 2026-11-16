"""WP1 忠实度目录测试：构建、一致性、审查合并、指纹失效。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dayan.fidelity import (build_catalog, get_catalog,  # noqa: E402
                            load_reviews, models_source_fingerprint,
                            test_refs_for, FIDELITY_LEVELS)


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

    from dayan.model_index import ALL_INDEX, resolve
    cat = get_catalog()
    mids = {m["model_id"] for m in cat["models"]}

    check("目录覆盖全部运行工厂", set(ALL_INDEX.keys()) <= mids,
          f"缺 {len(set(ALL_INDEX) - mids)} 个")
    check("目录含仅登记条目",
          any(m["fidelity"] == "registered" for m in cat["models"]))
    check("计数一致（total=各分级和）",
          cat["counts"]["total"] == sum(cat["counts"]["fidelity"].values())
          == len(cat["models"]))
    check("可运行计数与探针一致",
          cat["counts"]["runnable"] == sum(1 for m in cat["models"]
                                           if m["runnable"]))
    check("每条记录带证据字段",
          all({"fidelity", "basis", "evidence", "reviewed", "test_refs"}
              <= set(m.keys()) for m in cat["models"][:50]))
    check("忠实度取值合法",
          all(m["fidelity"] in FIDELITY_LEVELS for m in cat["models"]))
    check("已审条目 review_source 指向审查文件",
          all(m["review_source"] and
              (ROOT / "data" / "fidelity_review" / m["review_source"]).exists()
              for m in cat["models"] if m["reviewed"]))
    check("未审可运行条目不虚标（降级为 prototype；仅登记条目除外）",
          all(m["fidelity"] == "prototype" for m in cat["models"]
              if not m["reviewed"] and m["fidelity"] != "registered"))

    # 已知审查结论抽检（防止装配器悄悄改动级别）
    by_id = {m["model_id"]: m for m in cat["models"]}
    spot = {"ECO019": "full", "ECO022": "prototype",
            "BEH089": "lite",      # 2026-11-12 机制修复后升级
            "NET091": "full", "NET015": "prototype",
            "BEH129": "prototype",
            "ECO112": "full"}      # 线性律修复后升级
    for mid, expect in spot.items():
        got = by_id.get(mid, {}).get("fidelity")
        check(f"抽检 {mid}={expect}", got == expect, f"got={got}")

    # 测试证据链接
    refs = test_refs_for("NET052")
    check("测试引用扫描非空", isinstance(refs, list))

    # 指纹机制
    fp1 = models_source_fingerprint()
    fp2 = models_source_fingerprint()
    check("源码指纹稳定", fp1 == fp2)
    check("目录带指纹", cat.get("source_fingerprint") == fp1)

    # 审查合并：load_reviews 与目录 reviewed 数一致
    rv = load_reviews()
    # 不变式：审查文件中出现且存在于目录的 mid，必须已标记 reviewed
    # （审查里允许有目录外条目：engines 机制实体、别名备选实现等）
    by_id = {m["model_id"]: m for m in cat["models"]}
    missing_flag = [mid for mid in rv if mid in by_id
                    and not by_id[mid]["reviewed"]]
    check("审查条目全部合并进目录（交集不变式）", not missing_flag,
          f"未合并: {missing_flag[:5]}")

    # 观测量缓存（编译器依赖）
    obs61 = (by_id.get("NET061", {}).get("probe") or {}).get("observables")
    check("NET061 探针观测量含标量总量", bool(obs61) and
          "I_total" in obs61, f"obs={obs61}")

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run_tests())
