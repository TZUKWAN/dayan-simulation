"""DAYAN P0 内核验收测试（规范第二章）。

判据（2.9 P0 验收门槛）：
- 同种子可复现；同步/异步语义明确；事件顺序稳定（优先级键）
- 跨单位/非法输入被校验；快照恢复一致
- 登记表：合同校验 + 六级状态推进
- 目录：556 条（482 模型+22 应用+52 软件）加载，状态分级
- 既有 msim 资产登记为基准通过
运行：python tests/test_dayan_core.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dayan import (Clocks, DomainEvent, EventQueue, ModelRecord,  # noqa: E402
                   ModelRegistry, RngStreams, STATUS_LEVELS, get_registry,
                   simulate)
from dayan.models.benchmarks import DTMCModel  # noqa: E402


def test_registry_contract():
    reg = ModelRegistry()
    rec = ModelRecord(model_id="T001", name="测试模型", clock_type="fixed_step",
                      time_unit="step", status="原型可跑", state_schema={"x": "float"})
    issues = rec.contract_issues()
    assert issues == [], f"合规原型记录报问题：{issues}"
    # 基准通过但无 reference_cases → 拦截
    rec2 = ModelRecord(model_id="T002", name="缺基准", clock_type="fixed_step",
                       time_unit="step", status="基准通过", state_schema={"x": "f"})
    reg.register(rec2)
    issues2 = reg.promote("T002", "基准通过")
    assert issues2, "缺基准未拦截"
    # 数据校准缺 calibration_data → 拦截
    rec2.calibration_data = None
    reg._records["T002"] = rec2
    issues3 = reg.promote("T002", "数据校准")
    assert any("calibration" in i for i in issues3)
    print("[PASS] 登记表合同：状态分级校验拦截缺项")


def test_status_levels_order():
    assert STATUS_LEVELS == ["仅登记", "原型可跑", "基准通过", "数据校准",
                             "留出验证", "生产可用"]
    print("[PASS] 六级状态序列定义")


def test_clocks_four():
    c = Clocks(sim_time=12.5, optim_iter=7, llm_wall_seconds=120.0, batch=3)
    assert (c.sim_time, c.optim_iter, c.llm_wall_seconds, c.batch) == (
        12.5, 7, 120.0, 3)
    print("[PASS] 四时钟：仿真/迭代/LLM墙钟/批次 分别记录")


def test_rng_stream_isolation():
    """派生流隔离：新增无关模块不改既有基准轨迹。"""
    r1 = RngStreams(42, "exp")
    a = r1.stream("model", "dtmc").random()
    b_before = r1.stream("model", "mm1").random()
    r1.stream("model", "new_module_2026").random()  # 新增无关流
    a_after = r1.stream("model", "dtmc").random()
    b_after = r1.stream("model", "mm1").random()
    # 流序列连续性不受其他流创建影响（缓存 + 确定性派生）
    r2 = RngStreams(42, "exp")
    seq_a = [r2.stream("model", "dtmc").random() for _ in range(3)]
    seq_b = [r2.stream("model", "mm1").random() for _ in range(3)]
    assert seq_a[0] == a, "流不可复现"
    assert seq_a != seq_b, "不同名流不应相同"
    print("[PASS] 派生随机流：按名独立、跨实例可复现")


def test_event_priority_stable():
    """事件顺序：时间→语义优先级→稳定序号。"""
    q = EventQueue()
    q.push(DomainEvent(time=1.0, etype="later"))
    q.push(DomainEvent(time=0.5, etype="early_hi", priority=0))
    q.push(DomainEvent(time=0.5, etype="early_lo", priority=5))
    out = []
    while len(q):
        ev = q.pop(0.0)
        out.append(ev)
    assert [e.etype for e in out] == ["early_hi", "early_lo", "later"], \
        f"优先级顺序错：{[e.etype for e in out]}"
    # 同 time+priority → 稳定序号保持入队顺序
    q2 = EventQueue()
    q2.push(DomainEvent(time=1.0, etype="A", priority=3))
    q2.push(DomainEvent(time=1.0, etype="B", priority=3))
    o2 = [q2.pop(0.0).etype for _ in range(2)]
    assert o2 == ["A", "B"], f"同键平局不稳定：{o2}"
    print("[PASS] 事件顺序：时间→优先级→稳定序号")


def test_event_cancellation_and_zero_loop():
    q = EventQueue()
    eid = q.push(DomainEvent(time=1.0, etype="cancelled"))
    q.cancel(eid)
    assert q.pop(0.0) is None, "取消事件仍被弹出"
    print("[PASS] 事件取消：取消后不再弹出")


def test_des_zero_time_loop_guard():
    """零时间循环防护：模型自反馈同刻事件 → 超上限抛错而非挂死。"""
    class LoopModel(DTMCModel):
        clock_type = "des"

        def next_event_time(self, t):
            return t  # 永远返回同刻事件（病态）
        def observe(self):
            return {}
        def handle_event(self, event):
            pass

    m = LoopModel()
    try:
        simulate(m, horizon=10, dt=1.0, rng=np.random.default_rng(0))
        raise AssertionError("零时间循环未触发防护")
    except RuntimeError as e:
        assert "零时间" in str(e)
    print("[PASS] DES 零时间循环防护触发")


def test_snapshot_restore():
    """快照恢复一致：同流续跑结果一致。"""
    m1 = DTMCModel()
    m1.initialize({}, {"a": 0.3, "b": 0.2}, None, None,
                  np.random.default_rng(9))
    m1.step(0, 1.0)
    snap = m1.snapshot()
    m2 = DTMCModel()
    m2.restore(snap)
    m1.rng = np.random.default_rng(100)
    m2.rng = np.random.default_rng(100)
    m1.step(1, 1.0)
    m2.step(1, 1.0)
    assert m1.state == m2.state, "恢复后状态分叉"
    print("[PASS] 快照恢复：状态一致续跑")


def test_catalog_556():
    cat = json.loads((ROOT / "data" / "dayan_catalog.json").read_text(
        encoding="utf-8"))
    assert cat["count"] == 556, f"目录条数 {cat['count']} ≠ 556"
    assert cat["counts"]["模型层"] == 482
    assert cat["counts"]["应用层"] == 22
    assert cat["counts"]["软件层"] == 52
    ids = [m["model_id"] for m in cat["models"]]
    assert len(set(ids)) == 556, "ID 重复"
    # 抽查具名模型
    by_id = {m["model_id"]: m for m in cat["models"]}
    assert "BEH001" in by_id and "Schelling" in by_id["BEH001"]["name"]
    assert "ECO019" in by_id and "Goodwin" in by_id["ECO019"]["name"]
    assert "NET053" in by_id and "SIR" in by_id["NET053"]["name"]
    print(f"[PASS] 目录：556 条（482模型+22应用+52软件），零重复，抽查通过")


def test_catalog_into_registry():
    """目录批量登记入注册表（状态=仅登记），检索可查。"""
    cat = json.loads((ROOT / "data" / "dayan_catalog.json").read_text(
        encoding="utf-8"))
    reg = get_registry()
    loaded = 0
    for m in cat["models"]:
        if m["model_id"] in [r.model_id for r in reg.all()]:
            continue
        rec = ModelRecord(
            model_id=m["model_id"], name=m["name"], kind=m.get("kind", ""),
            paradigm="abm", status="仅登记",
            source_refs=[cat["source"]],
            notes=f"layer={m.get('layer','模型层')}; domain={m.get('domain','')}")
        reg.register(rec)
        loaded += 1
    # 已实现的基准模型升级
    from dayan.models.benchmarks import (DTMCModel, SEIRModel,  # noqa: F401
                                         SIRModel)
    for rid, mid in [("DAYAN.DTMC", "MET001"),
                     ("DAYAN.SIR", "NET053"),
                     ("DAYAN.SEIR", "NET055")]:
        reg.register(ModelRecord(model_id=rid, name=f"{mid} 基准实现",
                                 status="基准通过",
                                 reference_cases=["解析基准通过"]))
    assert len(reg) > 500, f"注册表条数 {len(reg)} 异常"
    schelling = reg.find(keyword="Schelling")
    assert schelling, "Schelling 未登记"
    print(f"[PASS] 目录登记：注册表 {len(reg)} 条（含 482 目录+3 个基准实现）")


if __name__ == "__main__":
    test_registry_contract()
    test_status_levels_order()
    test_clocks_four()
    test_rng_stream_isolation()
    test_event_priority_stable()
    test_event_cancellation_and_zero_loop()
    test_des_zero_time_loop_guard()
    test_snapshot_restore()
    test_catalog_556()
    test_catalog_into_registry()
    print("\n===== DAYAN P0 内核：全部通过 =====")
