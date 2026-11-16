"""WP7 状态帧层测试：实体级导出、聚合降级、状态流采样、HUD 数据来源。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dayan.stateframe import (collect_state_stream,  # noqa: E402
                              state_frame_of)
from dayan.model_index import resolve  # noqa: E402


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

    # ---- 1. 实体级：NET106 交通 CA ----
    s = collect_state_stream("NET106", {"density": 0.3}, ticks=40,
                             sample_every=4)
    check("NET106 provenance=entity", s["provenance"] == "entity")
    check("NET106 采样帧包含初态和末态", s["n_frames"] == 11
          and s["frames"][0]["sim_t"] == 0 and s["frames"][-1]["sim_t"] == 4,
          f"n={s['n_frames']}")
    fr = s["frames"][5]
    cars = [e for e in fr["entities"] if e["type"] == "car"]
    check("NET106 帧含真实车辆实体", len(cars) == len(fr["entities"])
          and len(cars) > 0)
    check("车辆带位置与速度", all("x" in c and "speed" in c for c in cars[:5]))
    check("汇总与帧一致（n_cars）",
          fr["aggregates"].get("n_cars") == len(cars))
    check("provenance_note 披露真实来源",
          "模型真实计算" in s["provenance_note"])

    # ---- 2. 实体级：NET113 行人 / BEH001 居民 / SYS002 服务台 ----
    s2 = collect_state_stream("NET113", {}, ticks=20, sample_every=4)
    check("NET113 provenance=entity", s2["provenance"] == "entity")
    fr2 = s2["frames"][-1]
    peds = [e for e in fr2["entities"] if e["type"] == "pedestrian"]
    check("行人实体带状态(moving/exited)",
          all(e["state"] in ("moving", "exited") for e in peds))
    s3 = collect_state_stream("BEH001", {}, ticks=20, sample_every=4)
    check("BEH001 provenance=entity", s3["provenance"] == "entity")
    residents = [e for e in s3["frames"][-1]["entities"]
                 if e["type"] == "resident"]
    check("居民实体带类型状态",
          all(e["state"] in ("type_1", "type_2") for e in residents[:10]))
    s4 = collect_state_stream("SYS002", {}, ticks=40, sample_every=4)
    servers = [e for e in s4["frames"][-1]["entities"]
               if e["type"] == "server"]
    check("SYS002 服务台实体", len(servers) == 3
          and all(e["state"] in ("busy", "idle") for e in servers))

    # ---- 3. 聚合降级：NET052（无个体导出）----
    s5 = collect_state_stream("NET052", {}, ticks=20, sample_every=4)
    check("NET052 provenance=aggregate（诚实降级）",
          s5["provenance"] == "aggregate")
    check("聚合帧带汇总指标",
          isinstance(s5["frames"][3]["aggregates"], dict)
          and "I" in s5["frames"][3]["aggregates"])
    check("聚合标注'示意动画'",
          "示意动画" in s5["provenance_note"])

    # ---- 4. 事件通道：干预进入事件流 ----
    s6 = collect_state_stream("NET052", {}, ticks=30, sample_every=3,
                              )
    # 直接以 run_model_full 干预验证事件装配
    from dayan.runtime import run_model_full
    rr = run_model_full("NET052", ticks=20,
                        interventions=[{"at_t": 1.0, "label": "测试干预",
                                        "params": {"beta": "*0.5"}}])
    ivs = rr.manifest["interventions"]
    check("干预事件进入 manifest（事件流数据源）",
          ivs and ivs[0]["applied"] and ivs[0]["actual_t"] >= 0.9)

    # ---- 5. state_frame 合同异常安全 ----
    _, factory = resolve("NET106")
    m = factory()
    fr106 = state_frame_of(m, 0.0)   # 未 initialize：不得抛异常给调用方
    check("未初始化模型状态帧安全降级", fr106 is None
          or isinstance(fr106, dict))

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run_tests())
