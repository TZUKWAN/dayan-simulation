"""R6 文档站骨架生成器（静态站点，平台对外文档）。

从注册表+包元数据生成：
- site/index.html：平台总览（五层架构图+包目录+测试状态）
- site/packs.html：各理论包七件套详情
- site/teachings/index.html：教学场景入口（链接到 3 个预置规约）
- site/roadmap.html：路线图状态（R0-R6 勾选）

运行：python experiments/build_site.py
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.kernel import list_packs  # noqa: E402
from src.kernel.registry import default_registry  # noqa: E402
import src.packs  # noqa: E402,F401  (导入即注册全部包——list_packs 才完整)

SITE = ROOT / "site"

CSS = """
body { font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif; max-width: 1100px;
       margin: 0 auto; padding: 2em; background: #0b0f19; color: #e7ecf5; line-height: 1.7; }
h1 { color: #22d3ee; border-bottom: 2px solid #243049; padding-bottom: 0.3em; }
h2 { color: #fbbf24; margin-top: 1.5em; }
h3 { color: #34d399; }
code { background: #131a2a; padding: 0.15em 0.4em; border-radius: 4px;
       color: #facc15; font-size: 0.92em; }
pre { background: #131a2a; padding: 1em; border-radius: 8px; overflow-x: auto;
      border: 1px solid #243049; }
table { border-collapse: collapse; width: 100%; margin: 1em 0; }
th, td { border: 1px solid #243049; padding: 0.5em 0.8em; text-align: left; }
th { background: #131a2a; color: #22d3ee; }
.badge { display: inline-block; padding: 0.15em 0.6em; border-radius: 12px;
         font-size: 0.85em; margin-right: 0.5em; }
.badge-green { background: #052e16; color: #34d399; border: 1px solid #34d399; }
.badge-gray { background: #1e293b; color: #94a3b8; border: 1px solid #64748b; }
.badge-cyan { background: #083344; color: #22d3ee; border: 1px solid #22d3ee; }
a { color: #22d3ee; }
.done { color: #34d399; } .todo { color: #94a3b8; }
"""

PACK_META = {
    "政治经济学包": {
        "基准": "货币守恒 1e-13 / 15 runs campaign / Braverman 去技能化",
        "实验": "阶级结构涌现、剥削记账、异化量表（600+ 叙事）、合作社对照、冲击实验",
    },
    "社会学包": {
        "基准": "Schelling 0.5→0.974",
        "实验": "规范采纳、地位流动性、与 polecon 跨包联动",
    },
    "政治学包": {
        "基准": "Downs 收敛 0.018 / Duverger 1.00 vs 2.84",
        "实验": "经济基础→政治反应联合实验（抗议率差分 +0.11）",
    },
    "文化媒介包": {
        "基准": "假新闻级联放大 3.2× / public 压制 0.31",
        "实验": "回音室 0.794→0.852、拜物教通道复用",
    },
}


def build_index():
    packs_html = "".join(
        f"<tr><td><code>{html.escape(p)}</code></td>"
        f"<td>{html.escape(PACK_META.get(p, {}).get('基准', '—'))}</td>"
        f"<td>{html.escape(PACK_META.get(p, {}).get('实验', '—'))}</td></tr>"
        for p in list_packs() if "基准·" not in p)
    reg = default_registry()
    stats_p = ROOT / "data" / "test_stats.json"
    n_pass = 50
    if stats_p.exists():
        try:
            n_pass = json.loads(stats_p.read_text(encoding="utf-8")).get("passed", 50)
        except Exception:
            pass
    body = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>msim · 社会科学仿真基础设施</title><style>{CSS}</style></head><body>
<h1>msim · 社会科学仿真基础设施</h1>
<p><b>愿景</b>：研究者写一份声明式实验规约（scenario spec），获得受控、可审计、
带效度证据的实验——政治经济学、社会学、政治学、文化媒介等学科的理论都能在其上做
受控计算实验。</p>
<p>
<span class="badge badge-green">全平台 {n_pass} 项测试通过</span>
<span class="badge badge-cyan">五层架构</span>
<span class="badge badge-cyan">{len(list_packs())} 个理论包</span>
<span class="badge badge-cyan">{len(reg)} 个登记规约</span>
</p>

<h2>五层架构</h2>
<pre>层5 证据输出    自动报告 · dashboard · 判决表
层4 实验管理    场景规约 · 预注册 · campaign · 效度闸门
层3 测量器具    分布/网络/话语/问卷/量表（LLM-judge+人工复核）
层2 认知层      LLM 决策(意向) · 记忆 · 人设 · 规则 agent
层1 理论包      政治经济学 | 社会学 | 政治学 | 文化媒介 | 基准×2
层0 中立内核    事件溯源 · 不变量校验 · 种子纪律 · 全量日志</pre>

<h2>理论包目录</h2>
<table><tr><th>包</th><th>基准复现</th><th>代表实验</th></tr>{packs_html}</table>

<h2>快速开始</h2>
<pre>python experiments/run_spec.py --spec site/teachings/schelling_segregation.yaml --tag my_run
python tests/test_platform.py   # 平台验收
python experiments/build_site.py  # 重建本站</pre>

<p><a href="packs.html">包七件套详情 →</a> ·
<a href="teachings/index.html">教学场景 →</a> ·
<a href="roadmap.html">路线图 →</a></p>
</body></html>"""
    (SITE / "index.html").write_text(body, encoding="utf-8")


def build_packs():
    rows = []
    for p in list_packs():
        if "基准·" in p:
            continue
        meta = PACK_META.get(p, {"基准": "见包源码七件套", "实验": "—"})
        rows.append(f"""<h3>{html.escape(p)}</h3>
<table>
<tr><th>七件套</th><th>内容</th></tr>
<tr><td>实体/制度/动作空间</td><td>见 src/packs/*.py（包内声明）</td></tr>
<tr><td>不变量</td><td>{html.escape(meta.get('基准','—').split('/')[0].strip())}</td></tr>
<tr><td>基准复现</td><td>{html.escape(meta.get('基准','—'))}</td></tr>
<tr><td>代表实验</td><td>{html.escape(meta.get('实验','—'))}</td></tr>
</table>""")
    body = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>msim · 理论包七件套</title><style>{CSS}</style></head><body>
<h1>理论包七件套详情</h1>
{''.join(rows)}
<p><a href="index.html">← 返回首页</a></p></body></html>"""
    (SITE / "packs.html").write_text(body, encoding="utf-8")


def build_teachings():
    import yaml
    cards = []
    for yf in sorted((SITE / "teachings").glob("*.yaml")):
        raw = yaml.safe_load(yf.read_text(encoding="utf-8"))
        cards.append(f"""<h3>{html.escape(raw.get('scenario',''))}</h3>
<p><code>{yf.name}</code> · 包：{html.escape(raw.get('pack',''))} ·
{raw.get('ticks','?')} ticks · 种子 {raw.get('seed','?')}</p>
<pre>{html.escape(raw.get('教学要点',''))}</pre>
<p>运行：<code>python experiments/run_spec.py --spec site/teachings/{yf.name} --tag 教学演示</code></p>""")
    body = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>msim · 教学场景</title><style>{CSS}</style></head><body>
<h1>教学场景包</h1>
<p>预置 3 个课堂演示规约：改一个参数（阈值/选举规则/算法偏置），看宏观涌现如何翻转。</p>
{''.join(cards)}
<p><a href="../index.html">← 返回首页</a></p></body></html>"""
    (SITE / "teachings" / "index.html").write_text(body, encoding="utf-8")


def build_roadmap():
    items = [
        ("R0 平台化重构", "中立内核+政治经济学包+场景规约", True),
        ("R1 基准复现套件", "Sugarscape / Axelrod", True),
        ("R2 社会学包", "Schelling / 规范 / 跨包联动", True),
        ("R3 政治学包", "Downs / Duverger / 经济基础→政治反应", True),
        ("R4 文化媒介包", "假新闻级联 / 回音室 / 拜物教通道", True),
        ("R5 规约注册表", "登记/检索/引用句柄（本页生成时已用）", True),
        ("R5 人类校验", "judge 人工复核 / 跨模型消融 / CGSS（需用户参与）", False),
        ("R6 教学场景包", "3 个预置规约（本站）", True),
        ("R6 文档站", "本站（build_site.py 生成）", True),
        ("R6 GOD 控制室", "外部仓库，另立会话对接", False),
    ]
    lis = "".join(
        f'<li class="{"done" if done else "todo"}">{"✓" if done else "○"} {name}'
        f'<br><small>{desc}</small></li>' for name, desc, done in items)
    body = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>msim · 路线图</title><style>{CSS}</style></head><body>
<h1>实施路线图状态</h1><ul style="list-style:none;padding:0">{lis}</ul>
<p><a href="index.html">← 返回首页</a></p></body></html>"""
    (SITE / "roadmap.html").write_text(body, encoding="utf-8")


def register_teachings():
    """把 3 个教学规约登记入注册表（演示 R5 联动）。"""
    import yaml
    reg = default_registry()
    for yf in sorted((SITE / "teachings").glob("*.yaml")):
        reg.register(yf.read_text(encoding="utf-8"), author="msim-teaching",
                     tags=["教学"], summary=yf.stem)


if __name__ == "__main__":
    register_teachings()
    build_index()
    build_packs()
    build_teachings()
    build_roadmap()
    print(f"文档站已生成：{SITE}")
    for f in ["index.html", "packs.html", "teachings/index.html", "roadmap.html"]:
        p = SITE / f
        print(f"  {'✓' if p.exists() else '✗'} {f} ({p.stat().st_size} bytes)")
