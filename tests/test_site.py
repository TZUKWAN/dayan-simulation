"""R6 文档站+教学场景包验收测试。

判据：
- 3 个教学规约 YAML 可加载且过效度闸门
- build_site.py 生成 4 个 HTML 且含关键内容
- 教学规约已登记入注册表（R5 联动）
运行：python tests/test_site.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.kernel.spec import load_scenario  # noqa: E402
from src.kernel.registry import default_registry  # noqa: E402

SITE = ROOT / "site"
TEACHINGS = SITE / "teachings"


def test_teaching_specs_load():
    yamls = sorted(TEACHINGS.glob("*.yaml"))
    assert len(yamls) == 3, f"教学规约数 {len(yamls)} ≠ 3"
    for yf in yamls:
        s = load_scenario(yf)
        assert not s.check_gates(), f"{yf.name} 闸门未过：{s.check_gates()}"
        assert s.raw.get("教学要点"), f"{yf.name} 缺教学要点"
    print(f"[PASS] 教学场景包：{len(yamls)} 个规约全部加载且过闸门，含教学要点")


def test_site_built():
    import subprocess
    subprocess.run([sys.executable, str(ROOT / "experiments" / "build_site.py")],
                   check=True, capture_output=True)
    for f in ["index.html", "packs.html", "teachings/index.html", "roadmap.html"]:
        p = SITE / f
        assert p.exists() and p.stat().st_size > 500, f"{f} 缺失或过小"
    idx = (SITE / "index.html").read_text(encoding="utf-8")
    assert "五层架构" in idx and "理论包" in idx
    assert "35/35" in idx or "测试通过" in idx
    road = (SITE / "roadmap.html").read_text(encoding="utf-8")
    assert "R0" in road and "R6" in road
    teach = (SITE / "teachings" / "index.html").read_text(encoding="utf-8")
    assert "Schelling" in teach and "Downs" in teach and "假新闻" in teach
    print("[PASS] 文档站：4 页生成（index/packs/teachings/roadmap），内容含架构+包+教学+路线图")


def test_registry_integration():
    """R5 联动：教学规约登记入注册表，可检索可引用。"""
    reg = default_registry()
    teaching = reg.find(keyword="教学")
    assert len(teaching) >= 3, f"教学规约登记数 {len(teaching)} < 3"
    e = teaching[0]
    assert reg.cite(e.handle).startswith("msim://spec/")
    print(f"[PASS] R5 联动：{len(teaching)} 个教学规约已登记，"
          f"引用句柄示例 {reg.cite(e.handle)}")


if __name__ == "__main__":
    test_teaching_specs_load()
    test_site_built()
    test_registry_integration()
    print("\n===== R6 教学场景包+文档站：全部通过 =====")
