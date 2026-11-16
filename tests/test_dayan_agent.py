"""DAYAN Agent 验收：元数据/组合引擎/意图路由/工具合同。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dayan.agent import intent  # noqa: E402
from dayan.agent.agent import DayanAgent  # noqa: E402
from dayan.agent.composer import compare, compose, ensemble, sweep  # noqa: E402
from dayan.agent.metadata import (CAP_PATH, load_capabilities,  # noqa: E402
                                  search_capabilities)
from dayan.agent.tools import TOOL_SPECS, TOOL_IMPL, call_tool, tool_manifest  # noqa: E402


def test_capabilities_complete():
    """能力卡：290 全覆盖，参数/观测量字段齐备。"""
    caps = load_capabilities()
    from dayan.model_index import ALL_INDEX as _ALL_IDX
    # 2026-11-13：自定义模型（custom_models DSL）合法产生索引外的能力卡，
    # 断言改为"运行索引全覆盖"超集检查
    card_ids = {c["model_id"] for c in caps}
    missing = [m for m in _ALL_IDX if m not in card_ids]
    assert not missing, f"运行索引 {len(_ALL_IDX)} 中 {len(missing)} 个无能力卡: {missing[:5]}"
    runnable = [c for c in caps if c["runnable"]]
    assert len(runnable) >= 490, f"仅 {len(runnable)} 可运行（注册 {len(_ALL_IDX)}，未探针通过的部分见 fidelity 目录）"
    with_params = [c for c in caps if c["parameters"]]
    with_obs = [c for c in caps if c["observables"]]
    assert len(with_params) > 210, f"参数卡不足 {len(with_params)}"
    assert len(with_obs) > 350, f"观测量卡不足 {len(with_obs)}"
    print(f"[PASS] 能力卡：456 全覆盖（参数卡 {len(with_params)}，观测量卡 {len(with_obs)}）")


def test_search():
    """能力搜索：按 ID/参数/观测量。"""
    r1 = search_capabilities("NET106")
    assert any(c["model_id"] == "NET106" for c in r1)
    r2 = search_capabilities(observable="flux")
    assert any(c["model_id"].startswith("NET") for c in r2),         "flux 观测量搜索失败"
    r3 = search_capabilities(has_param="alpha")
    assert len(r3) > 5, f"参数搜索 {len(r3)}"
    print(f"[PASS] 能力搜索：NET106 直查 / flux 观测量 {len(r2)} / alpha 参数 {len(r3)}")


def test_composer():
    """四大引擎：sweep 单调/ensemble 稳健/compare 共同字段/compose 流水线。"""
    sw = sweep("NET106", "density", [0.1, 0.3, 0.5], ticks=80)
    f_lo = sw["runs"][0]["final"].get("density", 0)
    f_hi = sw["runs"][2]["final"].get("density", 0)
    assert f_hi > f_lo, f"NS 密度扫描不单调 {f_lo}→{f_hi}"

    en = ensemble("NET106", seeds=(0, 1, 2), ticks=80)
    assert "density" in en["stats"] and en["stats"]["density"]["n_valid"] == 3

    cmp = compare("NET110", "NET111")
    assert cmp["shared_fields"], f"UE/SO 无共同字段 {cmp}"

    cp = compose([["ECO015", {}], ["ECO017", {}]],
                 handoff={"k": "k0"}, ticks=60)
    assert cp["n_stages"] == 2
    assert cp["stages"][1]["params"].get("k0") is not None, \
        "handoff 未注入后级参数"
    print(f"[PASS] 组合引擎：sweep 密度 {f_lo:.2f}→{f_hi:.2f}，ensemble 3 种子，"
          f"compare {len(cmp['shared_fields'])} 字段，compose handoff 生效")


def test_intent_routing():
    """规则路由：运行/扫参/对比/搜索 全部产出正确工具计划。"""
    p1 = intent.plan("运行 NET106")
    assert p1["plan"][0]["tool"] == "run" and \
        p1["plan"][0]["args"]["model_id"] == "NET106"
    p2 = intent.plan("对 NET106 扫参 density 0.1 0.3 0.5")
    assert p2["plan"][0]["tool"] == "sweep" and \
        p2["plan"][0]["args"]["param"] == "density"
    p3 = intent.plan("比较 NET110 和 NET111")
    assert p3["plan"][0]["tool"] == "compare"
    p4 = intent.plan("有哪些 gini 相关的模型")
    assert p4["plan"][0]["tool"] == "search_models"
    print(f"[PASS] 意图路由：run/sweep/compare/search 四类计划正确")


def test_agent_end_to_end():
    """Agent 端到端：fulfill → 执行 → 摘要。"""
    agent = DayanAgent()
    r = agent.fulfill("运行 NET106")
    assert r["ok"] and r["executed"][0]["ok"]
    summary = agent.summarize(r)
    assert any("run NET106" in s for s in summary)

    r2 = agent.fulfill("扫参 NET106 density 0.1 0.4")
    assert r2["ok"] and r2["executed"][0]["ok"]
    print(f"[PASS] Agent 端到端：{summary[0][:60]}")


def test_tool_contract():
    """工具合同：manifest 完整 + call_tool 分发。"""
    manifest = tool_manifest()
    assert "sweep" in manifest and "compose" in manifest
    names = {t['name'] for t in TOOL_SPECS}
    assert names == set(TOOL_IMPL)
    assert {'experiment', 'build_model', 'collect_data', 'analyze_data'} <= names
    assert all(t['parameters']['additionalProperties'] is False for t in TOOL_SPECS)
    r = call_tool("run", model_id="NET095", ticks=30)
    assert r["ok"]
    r_bad = call_tool("不存在")
    assert not r_bad["ok"]
    print(f"[PASS] 工具合同：{len(TOOL_SPECS)} 个工具 + 分发与兜底")


if __name__ == "__main__":
    test_capabilities_complete()
    test_search()
    test_composer()
    test_intent_routing()
    test_agent_end_to_end()
    test_tool_contract()
    print("\n===== DAYAN Agent：全部通过 =====")
