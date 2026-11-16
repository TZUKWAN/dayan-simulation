"""R5-T8/T9 内建件验收测试（遮蔽审计器 + 发散监测器）。

判据：
- 遮蔽审计：理论词汇命中被捕获；polecon 决策/叙事 prompt 全文零命中
- 发散监测：越限持续 patience 期 → 记录 tick；未越限不误报
运行：python tests/test_kernel_facilities.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.kernel import Kernel, KernelConfig  # noqa: E402
from src.kernel.masking_audit import audit_llm_log, audit_texts  # noqa: E402
import src.packs.polecon as polecon  # noqa: E402
from src.agents.decisions import (build_decision_prompt,  # noqa: E402
                                  build_narrative_prompt, rule_decision)


def test_masking_audit_catches():
    hits = audit_texts(["这是关于资本和剥削的讨论", "干净文本"])
    assert "资本" in hits and "剥削" in hits and len(hits) == 2
    clean = audit_texts(["完全干净的居民对话"])
    assert clean == {}
    print("[PASS] 遮蔽审计：理论词汇命中捕获，干净文本零误报")


def test_masking_audit_llm_log():
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "llm_log.jsonl"
    import json
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps({"messages": [
            {"role": "user", "content": "正常的决策处境描述"}]}) + "\n")
        f.write(json.dumps({"messages": [
            {"role": "user", "content": "提到了无产阶级革命"}]}) + "\n")
    hits = audit_llm_log(tmp)
    assert "无产阶级" in hits
    print("[PASS] 遮蔽审计：llm_log.jsonl 全量扫描，第二行命中")


def test_polecon_prompts_clean():
    pack = polecon.make_pack(population={"n": 6}, institutions={}, seed=3,
                             intervention={})
    from src.kernel import Kernel as K
    kernel = K(pack, KernelConfig(seed=3))
    kernel.init_world()
    texts = []
    for a in kernel.agents:
        texts += [m["content"] for m in build_decision_prompt(a, pack.world)]
        texts += [m["content"] for m in build_narrative_prompt(a, pack.world)]
    for a in kernel.agents:
        a.position = "employer"
    for a in kernel.agents:
        texts += [m["content"] for m in build_decision_prompt(a, pack.world)]
    hits = audit_texts(texts)
    assert hits == {}, f"polecon prompt 泄漏理论词汇：{hits}"
    print(f"[PASS] polecon 全 prompt（{len(texts)} 条）遮蔽零命中")


def test_divergence_monitor():
    pack = polecon.make_pack(population={"n": 30}, institutions={}, seed=7,
                             intervention={})
    kernel = Kernel(pack, KernelConfig(seed=7, invariant_strict=True))
    kernel.init_world()
    # 恒触发 watch（threshold=0, above, patience=3）
    kernel.add_divergence_watch("测试越限", lambda k: 1.0, threshold=0.0,
                                direction="above", patience=3)
    for _ in range(2):
        for a in kernel.agents:
            pack.action_handler(a, pack.rule_decision(a), kernel)
        kernel.step()
    assert "测试越限" not in kernel.divergences, "patience=3 未满即触发"
    for a in kernel.agents:
        pack.action_handler(a, pack.rule_decision(a), kernel)
    kernel.step()
    assert "测试越限" in kernel.divergences, "patience=3 满后未记录"
    print("[PASS] 发散监测：patience=3 满后记录触发 tick")


def test_divergence_no_false_positive():
    pack = polecon.make_pack(population={"n": 30}, institutions={}, seed=7,
                             intervention={})
    kernel = Kernel(pack, KernelConfig(seed=7, invariant_strict=True))
    kernel.init_world()
    g0 = pack.measure_hooks["wealth_gini"](kernel)
    kernel.add_divergence_watch("基尼翻倍", lambda k: float(
        pack.measure_hooks["wealth_gini"](k)), threshold=2.0 * g0,
        direction="above", patience=10)
    for _ in range(30):
        for a in kernel.agents:
            pack.action_handler(a, pack.rule_decision(a), kernel)
        kernel.step()
    assert kernel.divergences == {}, f"30 tick 正常经济误报发散：{kernel.divergences}"
    print("[PASS] 发散监测：30 tick 正常经济零误报")


if __name__ == "__main__":
    test_masking_audit_catches()
    test_masking_audit_llm_log()
    test_polecon_prompts_clean()
    test_divergence_monitor()
    test_divergence_no_false_positive()
    print("\n===== T8/T9 内建件：全部通过 =====")
