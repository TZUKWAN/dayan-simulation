"""R5 规约注册表验收测试。

判据：
- 登记 → 唯一句柄（内容哈希）
- 幂等：同内容重复登记返回同一句柄
- 内容改动 → 句柄变化（内容寻址=审计性）
- 检索：按包名/关键词过滤
- 引用：cite() 生成 msim://spec/<handle>
- 实验引用计数累加
运行：python tests/test_registry.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.kernel.registry import SpecRegistry  # noqa: E402

SPEC_A = """
scenario: 测试实验A
pack: 政治经济学包
population: {n: 50}
measurement_plan: [基尼]
validity_plan: {基线: 规则组, 种子: [7]}
claims_level: {机制主张: 仅探索, 趋势主张: 允许}
"""

SPEC_B = """
scenario: 测试实验B_社会学
pack: 社会学包
population: {n: 100}
measurement_plan: [分异指数]
validity_plan: {基线: 规则组}
claims_level: {机制主张: 仅探索, 趋势主张: 允许}
tags: [规范, 网络]
"""


def _tmp_reg():
    tmp = tempfile.mkdtemp()
    return SpecRegistry(Path(tmp) / "reg.json")


def test_register_and_handle():
    reg = _tmp_reg()
    e = reg.register(SPEC_A, author="tester", tags=["经济学"])
    assert len(e.handle) == 16
    assert e.cite() == f"msim://spec/{e.handle}"
    print(f"[PASS] 登记：句柄 {e.handle}，引用 {e.cite()}")


def test_idempotent():
    reg = _tmp_reg()
    e1 = reg.register(SPEC_A)
    e2 = reg.register(SPEC_A)
    assert e1.handle == e2.handle, "同内容应返回同一句柄"
    assert len(reg) == 1, f"重复登记产生冗余：{len(reg)}"
    print("[PASS] 幂等：同内容重复登记返回既有句柄，注册表不膨胀")


def test_content_addressed():
    reg = _tmp_reg()
    e1 = reg.register(SPEC_A)
    modified = SPEC_A.replace("n: 50", "n: 60")  # 内容改动
    e2 = reg.register(modified)
    assert e1.handle != e2.handle, "内容改动未产生新句柄（审计性丧失）"
    assert len(reg) == 2
    print("[PASS] 内容寻址：规约改动即新句柄（防静默篡改）")


def test_search_and_cite():
    reg = _tmp_reg()
    reg.register(SPEC_A, author="alice", tags=["经济学"])
    reg.register(SPEC_B, author="bob")
    assert len(reg.find(pack="社会学包")) == 1
    assert len(reg.find(keyword="规范")) == 1
    assert len(reg.find(author="alice")) == 1
    e = reg.find(pack="政治经济学包")[0]
    assert reg.cite(e.handle).startswith("msim://spec/")
    print(f"[PASS] 检索：按包/关键词/作者过滤 + 引用句柄生成")


def test_experiment_refcount():
    reg = _tmp_reg()
    e = reg.register(SPEC_A)
    reg.record_experiment(e.handle)
    reg.record_experiment(e.handle)
    assert reg.get(e.handle).n_experiments == 2
    print("[PASS] 实验引用计数：登记运行可累加（实验可引用性）")


def test_persistence(tmp_path=None):
    import tempfile
    tmp = tempfile.mkdtemp()
    db = Path(tmp) / "reg.json"
    reg1 = SpecRegistry(db)
    e = reg1.register(SPEC_A)
    reg2 = SpecRegistry(db)  # 重新加载
    assert reg2.get(e.handle) is not None, "持久化后重新加载丢失"
    print("[PASS] 持久化：注册表落盘可重载")


if __name__ == "__main__":
    test_register_and_handle()
    test_idempotent()
    test_content_addressed()
    test_search_and_cite()
    test_experiment_refcount()
    test_persistence()
    print("\n===== R5 规约注册表：全部通过 =====")
