"""大衍 DAYAN 仿真实验报告生成器。

输入模型实际运行结果 → 程序计算事实与形态 → python-docx 渲染 Word
（含数值统计表 + matplotlib 结果图）。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
import os
REPORTS_DIR = Path(os.environ.get("DAYAN_REPORTS_DIR", ROOT / "reports"))
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

CAT_PATH = ROOT / "data" / "dayan_catalog.json"
CAP_PATH = ROOT / "data" / "model_capabilities.json"


def _catalog_info(model_id: str) -> dict:
    try:
        data = json.loads(CAT_PATH.read_text(encoding="utf-8"))
        for m in data.get("models", []):
            if m["model_id"] == model_id:
                return {"name": m.get("name", ""), "kind": m.get("kind", ""),
                        "domain": m.get("domain", ""), "status": m.get("status", "")}
    except Exception:                                  # noqa: BLE001
        pass
    return {}


def _capability(model_id: str) -> dict:
    try:
        caps = json.loads(CAP_PATH.read_text(encoding="utf-8"))
        for c in caps:
            if c["model_id"] == model_id:
                return c
    except Exception:                                  # noqa: BLE001
        pass
    return {}


def _stats(observations: list) -> dict:
    """每个数值观测量的统计（首/末/最小/最大/均值）。sim_t 为时间轴不进统计。"""
    if not observations:
        return {}
    skip = re.compile(r"^sim_t$")
    out = {}
    keys = [k for k in observations[-1]
            if not skip.search(k)
            and isinstance(observations[-1][k], (int, float))
            and not isinstance(observations[-1][k], bool)]
    for k in keys:
        vals = [o[k] for o in observations
                if isinstance(o.get(k), (int, float)) and np.isfinite(o.get(k))]
        if not vals:
            continue
        out[k] = {
            "increases": int(np.count_nonzero(np.diff(vals) > 1e-12)),
            "decreases": int(np.count_nonzero(np.diff(vals) < -1e-12)),
            "unchanged": int(np.count_nonzero(np.abs(np.diff(vals)) <= 1e-12)),
            "first": round(float(vals[0]), 6),
            "last": round(float(vals[-1]), 6),
            "min": round(float(min(vals)), 6),
            "max": round(float(max(vals)), 6),
            "mean": round(float(np.mean(vals)), 6),
        }
    return out


def _chart_png(model_id: str, observations: list, run_tag: str) -> Path | None:
    """结果图：数值序列曲线。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    stats = _stats(observations)
    if not stats:
        return None
    from .fonts import configure_matplotlib
    configure_matplotlib()
    fields = list(stats)[:6]
    rows = (len(fields) + 1) // 2
    fig, axes = plt.subplots(rows, 2, figsize=(7.2, 2.0 * rows), dpi=130, squeeze=False)
    fig.patch.set_facecolor("white")
    n = len(observations)
    palette = ["#0e7c86", "#8a4fbe", "#c77d1e", "#b03a3a", "#3a6ea5", "#4d8a3a"]
    for i, k in enumerate(fields):
        ax = axes.flat[i]
        pairs = [(o.get("sim_t", j), o[k]) for j, o in enumerate(observations)
                 if isinstance(o.get(k), (int, float)) and np.isfinite(o.get(k))]
        ax.plot([t for t, _ in pairs], [v for _, v in pairs], label=k,
                color=palette[i % len(palette)], lw=1.6)
        ax.set_ylabel(k, fontsize=8)
        ax.set_xlabel("sim_t（模型时间）", fontsize=8)
        ax.grid(alpha=0.3)
    for ax in list(axes.flat)[len(fields):]:
        ax.axis("off")
    fig.suptitle(f"{model_id} 观测时间序列（各字段独立纵轴）", fontsize=11)
    fig.tight_layout()
    path = REPORTS_DIR / f"chart_{run_tag}.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def _fidelity_info(model_id: str) -> dict:
    """WP1 忠实度记录（分级/依据/证据），报告如实披露实现等级。"""
    try:
        from .fidelity import load_reviews, FIDELITY_ZH
        rec = dict(load_reviews().get(model_id) or {})
        rec["fidelity_zh"] = FIDELITY_ZH.get(rec.get("fidelity"), "未审查")
        if rec:
            return {"fidelity_zh": rec.get("fidelity_zh", ""),
                    "basis": rec.get("basis", ""),
                    "test_refs": rec.get("test_refs", []),
                    "reviewed": rec.get("reviewed", False)}
    except Exception:                                  # noqa: BLE001
        pass
    return {}


def _analysis_lines(analysis: dict) -> list[str]:
    """程序先行分析 → 报告可引用的要点行（不是 LLM 自己看图猜）。"""
    lines: list[str] = []
    if not analysis:
        return lines
    metric = analysis.get("metric", "")
    b = analysis.get("baseline") or {}
    wm = b.get("window_mean") or {}
    if wm.get("mean") is not None:
        lines.append(f"基线 {metric} 窗口均值 {wm['mean']:.4g}"
                     f"（±{wm.get('std', 0):.4g}，n={wm.get('per_seed') and len(wm['per_seed'])}种子）")
    pk = b.get("peak") or {}
    if pk.get("mean") is not None:
        pt = (b.get("peak_t") or {}).get("mean")
        lines.append(f"基线峰值 {pk['mean']:.4g}" +
                     (f"（时刻 {pt:.3g}）" if isinstance(pt, (int, float)) else ""))
    for lbl, s in (analysis.get("arms") or {}).items():
        pd = s.get("paired_diff") or {}
        if pd.get("mean") is not None:
            rel = s.get("effect_rel")
            lines.append(f"臂「{lbl}」配对差 Δ={pd['mean']:.4g}"
                         + (f"（相对 {rel:+.2%}）" if isinstance(rel, (int, float)) else "")
                         + (f"，Cohen's d={s['cohens_d']:.2f}"
                            if isinstance(s.get("cohens_d"), (int, float)) else ""))
    if analysis.get("causality_note"):
        lines.append(f"边界声明：{analysis['causality_note']}")
    return lines


def _manifest_lines(manifest: dict) -> list[str]:
    """实际执行事实行（报告的'实验设计'必须用这些，不用默认值叙事）。"""
    if not manifest:
        return []
    act = manifest.get("actual") or {}
    req = manifest.get("requested") or {}
    lines = [f"run_id {manifest.get('run_id', '?')}；协议 {manifest.get('protocol', '?')}；"
             f"种子 {req.get('seed')}；实际步数 {act.get('n_steps')}；"
             f"终点 sim_t={act.get('final_t')}"]
    params = act.get("effective_parameters") or act.get("parameters") or {}
    if params:
        lines.append("实际参数：" + "；".join(f"{k}={v}" for k, v in
                                             list(params.items())))
    req_params = req.get("parameters") or {}
    if req_params and req_params != params:
        lines.append("请求参数：" + "；".join(f"{k}={v}" for k, v in
                                              list(req_params.items())[:10]))
    for w in (manifest.get("warnings") or [])[:5]:
        lines.append(f"警告：{w}")
    ivs = manifest.get("interventions") or []
    for iv in ivs[:4]:
        if iv.get("applied"):
            lines.append(f"时点干预「{iv.get('label')}」于 sim_t={iv.get('actual_t')} "
                         f"生效：{iv.get('params')}")
        else:
            lines.append(f"时点干预「{iv.get('label')}」未生效：{iv.get('error')}")
    return lines


def _fact_report(model_id, meta, stats, cat):
    manifest = meta.get("manifest") or {}
    actual = manifest.get("actual") or {}
    n_obs = meta["n_observations"]
    n_steps = actual.get("n_steps")
    count = f"实际推进 {n_steps} 步，保存 {n_obs} 条观测（包含初态）" if n_steps is not None else f"提供 {n_obs} 条观测；未提供可核验的步数"
    descriptions = []
    for name, stat in stats.items():
        shape = "保持不变" if stat["increases"] == stat["decreases"] == 0 else "单调不降" if stat["decreases"] == 0 else "单调不升" if stat["increases"] == 0 else "存在双向波动"
        descriptions.append(f"{name}：首值 {stat['first']}，末值 {stat['last']}，均值 {stat['mean']}；"
                            f"相邻观测上升 {stat['increases']} 次、下降 {stat['decreases']} 次、持平 {stat['unchanged']} 次，{shape}。")
    return {"title": f"{model_id} 仿真实验事实报告",
            "abstract": count + "。结果与图表使用相同运行的完整观测，不根据首末值推断单调性。",
            "background": meta.get("intent") or "记录本次模型运行的实际配置与数值结果。",
            "method": "模型名称：" + cat.get("name", model_id) + "。本报告记录计算结果，模型的理论适用性须结合原研究问题判断。",
            "design": "实际配置与执行结果列于下方清单。" if manifest else "未提供完整运行清单，无法核验配置和计算过程。",
            "analysis": "\n".join(descriptions) or "本次运行没有可统计的数值观测量。",
            "conclusion": "本次输出支持上述运行内的数值描述。" + ("实验比较结果见下表。" if meta.get("analysis") else "单次运行不支持稳健性或现实预测结论。"),
            "limitations": "统计不自动证明收敛、周期性、显著性或现实因果关系。观测字段的量纲未在模型合同中定义时按原字段展示，不把模型时间擅自称为现实秒或小时。"}


def generate_report(model_id, observations, meta=None):
    import hashlib
    import uuid
    meta = dict(meta or {})
    if not observations:
        return {"ok": False, "error": "没有实际观测，不能生成完成报告"}
    meta["n_observations"] = len(observations)
    cat, cap = _catalog_info(model_id), _capability(model_id)
    stats = _stats(observations)
    content = _fact_report(model_id, meta, stats, cat)
    run_tag = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:10]
    fname = f"report_{model_id}_{run_tag}.docx"
    path = REPORTS_DIR / fname
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if meta.get("view_analysis"):
            from .research_charts import build_charts
            content["title"] = f"{model_id} 仿真结果分析报告"
            meta["view_analysis"]["figures"] = build_charts(meta["view_records"], meta["view_analysis"], REPORTS_DIR, run_tag)
            _build_research_docx(path, model_id, meta, stats, content)
        else:
            _build_docx(path, model_id, meta, cat, cap, stats, observations, content, run_tag)
    except Exception as exc:
        return {"ok": False, "error": f"docx 生成失败: {exc}"}
    facts = {"run_id": (meta.get("manifest") or {}).get("run_id"), "model_id": model_id,
             "n_observations": len(observations), "stats": stats, "analysis": meta.get("analysis", {}),
             "manifest": meta.get("manifest", {}), "content": content, "view_analysis": meta.get("view_analysis"),
             "docx_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "generator": "program-computed-facts"}
    path.with_suffix(".json").write_text(json.dumps(facts, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return {"ok": True, "path": str(path), "url": f"/reports/{fname}",
            "title": content["title"], "facts_url": f"/reports/{path.stem}.json",
            "run_id": facts["run_id"], "generation": "program-computed-facts"}


def _build_docx(path: Path, model_id: str, meta: dict, cat: dict, cap: dict,
                stats: dict, observations: list, content: dict, run_tag: str) -> None:
    from docx import Document
    from docx.shared import Pt, RGBColor, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn

    manifest = meta.get("manifest") or {}
    analysis = meta.get("analysis") or {}
    fid = _fidelity_info(model_id)
    doc = Document()
    # 全局中文字体
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    style.element.rPr.rFonts.set(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsia",
        "Noto Sans CJK SC")
    for style_name in ("Title", "Heading 1", "Heading 2"):
        doc.styles[style_name].font.color.rgb = RGBColor(0, 0, 0)
        doc.styles[style_name].element.get_or_add_rPr().rFonts.set(
            "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsia", "Noto Sans CJK SC")
    for doc_style in doc.styles:
        for border in list(doc_style.element.iter(qn("w:pBdr"))):
            border.getparent().remove(border)

    # 标题
    h = doc.add_heading(content.get("title", f"{model_id} 仿真实验报告"), level=0)
    for run in h.runs:
        run.font.color.rgb = RGBColor(0, 0, 0)
    sub = doc.add_paragraph(
        f"大衍 DAYAN 社会仿真平台 · 模型 {model_id}（{cat.get('name', '未知')}） · "
        f"生成时间 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub.runs[0].font.size = Pt(9)
    sub.runs[0].font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    def para(text):
        p = doc.add_paragraph(text)
        p.paragraph_format.first_line_indent = Pt(21)
        p.paragraph_format.space_after = Pt(6)
        return p

    doc.add_heading("摘要", level=1)
    para(content.get("abstract", ""))
    doc.add_heading("一、实验背景与目的", level=1)
    para(content.get("background", ""))
    doc.add_heading("二、模型与方法", level=1)
    para(content.get("method", ""))
    doc.add_paragraph(
        f"模型族：{cat.get('kind', '未知')}；领域：{cat.get('domain', '未知')}；"
        f"平台验证状态：{cat.get('status', '未知')}；执行协议：{cap.get('protocol', '未知')}。")
    if cap.get("parameters"):
        doc.add_paragraph("可调参数：" + "，".join(
            p["name"] for p in cap["parameters"][:14] if isinstance(p, dict)))
    doc.add_heading("三、实验设计", level=1)
    para(content.get("design", ""))
    # 实际执行事实表（WP5：报告使用实际配置，不用默认值叙事）
    facts = _manifest_lines(manifest)
    if facts:
        doc.add_paragraph("本次实际执行记录（RunManifest 摘要）：")
        for line in facts:
            p = doc.add_paragraph("· " + line)
            p.paragraph_format.first_line_indent = Pt(0)
            p.runs[0].font.size = Pt(9)
    doc.add_paragraph(
        f"实际推进步数：{(manifest.get('actual') or {}).get('n_steps', '未核验')}；观测条数：{len(observations)}（含初态）；"
        f"规划器：{meta.get('planner', 'rule')}；仿真意图：{meta.get('intent', '未注明')}。")
    if fid:
        doc.add_paragraph(
            f"实现忠实度：{fid.get('fidelity_zh')}"
            + (f"（{fid['basis']}）" if fid.get("basis") else "")
            + (f"；覆盖测试：{', '.join(fid['test_refs'][:3])}"
               if fid.get("test_refs") else ""))

    doc.add_heading("四、结果分析", level=1)
    para(content.get("analysis", ""))
    if stats:
        doc.add_paragraph("表 1  观测量统计")
        table = doc.add_table(rows=1, cols=6)
        table.style = "Table Grid"
        hdr = table.rows[0].cells
        for i, t in enumerate(["观测量", "首值", "末值", "最小", "最大", "均值"]):
            hdr[i].text = t
        for k, s in list(stats.items()):
            row = table.add_row().cells
            for i, v in enumerate([k, s["first"], s["last"], s["min"], s["max"], s["mean"]]):
                row[i].text = str(v)
        chart = _chart_png(model_id, observations, run_tag)
        if chart and chart.exists():
            doc.add_paragraph("")
            doc.add_picture(str(chart), width=Inches(6.2))
            cap_p = doc.add_paragraph("图 1  主要观测量时间序列")
            cap_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            cap_p.runs[0].font.size = Pt(9)

    doc.add_heading("五、结论与解读", level=1)
    para(content.get("conclusion", ""))

    # 实验对照分析表（WP8：程序先行计算的效应量，非 LLM 转述）
    an_lines = _analysis_lines(analysis)
    if an_lines:
        doc.add_heading("附：实验对照分析（程序计算）", level=2)
        for line in an_lines:
            p = doc.add_paragraph("· " + line)
            p.paragraph_format.first_line_indent = Pt(0)
            p.runs[0].font.size = Pt(9)
        doc.add_paragraph("注：" + str(analysis.get("causality_note", "")) +
                          "。" + str(analysis.get("significance_note", "")))

    doc.add_heading("六、局限性", level=1)
    para(content.get("limitations", ""))

    doc.add_paragraph("")
    foot = doc.add_paragraph(
        "本报告由大衍 DAYAN 平台按实际观测自动计算生成；统计与趋势计数可在同名JSON事实文件中核对。")
    foot.runs[0].font.size = Pt(8)
    foot.runs[0].font.color.rgb = RGBColor(0x88, 0x88, 0x88)

    doc.save(str(path))


def _build_research_docx(path, model_id, meta, stats, content):
    """Question, comparable results and complementary evidence before technical facts."""
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    view = meta["view_analysis"]
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin = section.bottom_margin = Inches(.7)
    section.left_margin = section.right_margin = Inches(.85)
    for name in ("Normal", "Title", "Heading 1", "Heading 2", "Caption"):
        style = doc.styles[name]
        style.font.name = "Calibri"
        style.font.color.rgb = RGBColor(0, 0, 0)
        style.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Noto Sans CJK SC")
    normal = doc.styles["Normal"]
    normal.font.size = Pt(11)
    normal.paragraph_format.line_spacing = 1.25
    normal.paragraph_format.space_after = Pt(6)
    doc.styles["Title"].font.size = Pt(23)
    doc.styles["Heading 1"].font.size = Pt(14)
    doc.styles["Heading 1"].paragraph_format.space_before = Pt(13)
    doc.styles["Caption"].font.size = Pt(9)
    for style in doc.styles:
        for border in list(style.element.iter(qn("w:pBdr"))):
            border.getparent().remove(border)

    def paragraph(text, small=False):
        p = doc.add_paragraph(text)
        if small:
            for run in p.runs:
                run.font.size = Pt(9)
        return p

    def table(headers, rows, widths):
        result = doc.add_table(rows=1, cols=len(headers))
        result.autofit = False
        for i, width in enumerate(widths):
            result.columns[i].width = Inches(width)
        for i, text in enumerate(headers):
            result.rows[0].cells[i].text = text
        for row in rows:
            cells = result.add_row().cells
            for i, value in enumerate(row):
                cells[i].text = str(value)
        header = OxmlElement("w:tblHeader")
        result.rows[0]._tr.get_or_add_trPr().append(header)
        for ri, row in enumerate(result.rows):
            for ci, cell in enumerate(row.cells):
                cell.width = Inches(widths[ci])
                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                properties = cell._tc.get_or_add_tcPr()
                shade = OxmlElement("w:shd")
                shade.set(qn("w:fill"), "E7EFF4" if ri == 0 else "FFFFFF" if ri % 2 else "F5F8FA")
                properties.append(shade)
                borders = OxmlElement("w:tcBorders")
                for side in ("top", "left", "bottom", "right"):
                    edge = OxmlElement(f"w:{side}")
                    edge.set(qn("w:val"), "single")
                    edge.set(qn("w:sz"), "4")
                    edge.set(qn("w:color"), "D9D9D9")
                    borders.append(edge)
                properties.append(borders)
                margins = OxmlElement("w:tcMar")
                for side in ("top", "bottom", "left", "right"):
                    edge = OxmlElement(f"w:{side}")
                    edge.set(qn("w:w"), "85")
                    edge.set(qn("w:type"), "dxa")
                    margins.append(edge)
                properties.append(margins)
                for p in cell.paragraphs:
                    p.paragraph_format.space_after = Pt(3)
                    p.paragraph_format.space_before = Pt(3)
                    p.alignment = WD_ALIGN_PARAGRAPH.LEFT if ci == 0 else WD_ALIGN_PARAGRAPH.CENTER
                    for run in p.runs:
                        run.font.size = Pt(10)
        return result

    def val(value):
        return f"{value:.6g}" if isinstance(value, (int, float)) else "无有效观测"

    doc.add_paragraph(content["title"], style="Title")
    paragraph("大衍 DAYAN 社会仿真工作台  归档数据分析", small=True)
    if meta.get("intent"):
        paragraph("研究问题：" + meta["intent"])
    info, window = view["metric_info"], view["window"]
    paragraph(f"本报告分析{info['name']}，单位为{info['unit']}。分析窗口为 "
              f"{window['from']:g} {'<' if window['exclusive'] else '≤'} sim_t ≤ {window['to']:g}。"
              f"共引用{len(view['run_ids'])}次已保存运行，观察时点为模型时间 {view['requested_time']:g}。")
    doc.add_heading("主要结果", level=1)
    interventions = []
    for record in meta["view_records"]:
        for iv in record.get("manifest", {}).get("interventions", []):
            if iv.get("applied"):
                description = f"{record.get('view_group',record['model_id'])}在 sim_t={iv['actual_t']:g} 设置 " + ", ".join(f"{k}={v}" for k,v in iv.get("params",{}).items())
                if description not in interventions:
                    interventions.append(description)
    if interventions:
        paragraph("比较设定：" + "；".join(interventions) + "。")
    if view["comparisons"]:
        for comparison in view["comparisons"]:
            relative = f"，相对差异 {comparison['relative']:+.2%}" if comparison["relative"] is not None else "，相对差异无法计算"
            paragraph(f"在所选窗口内，{comparison['group']}相对{comparison['baseline']}的{info['name']}均值差为 "
                      f"{val(comparison['difference'])}{relative}。"
                      + (f"有效配对种子数为{comparison['paired_n']}。" if comparison["paired_n"] else "此项为组均值描述，不冒充配对估计。"))
    else:
        item = next(r for r in view["per_run"] if r["run_id"] == view["selected_run_id"])
        if view["kind"] == "ensemble":
            paragraph(f"本次种子重复包含{len(view['per_run'])}次运行，各次窗口均值的平均为{val(view['groups'][0]['mean'])}。")
        paragraph(f"本次运行在窗口内有{item['n']}个有效观测时点，{info['name']}均值为{val(item['mean'])}。"
                  f"窗口首值为{val(item['first'])}，末值为{val(item['last'])}。")
    table(["方案", "运行数", "每次有效时点", "窗口均值"],
          [[g["name"], g["n"], "/".join(str(n) for n in g["observations_per_run"]), val(g["mean"])] for g in view["groups"]],
          [2.45, .7, 1.35, 1.3])
    paragraph("先对每次运行计算窗口均值，再按方案汇总。观测时点数不是独立重复实验数。", small=True)
    distribution = view["distribution"]
    if distribution:
        description = f"所选运行在 sim_t={view['frame_time']:g} 保存了{view['entity_count']}个主体。"
        if distribution.get("field") == "speed":
            description += f"其中{distribution['zero_count']}个主体速度为零；速度按模型格/步解释。"
        paragraph(description)
    else:
        paragraph("所选运行没有可用于主体分布分析的状态，不生成虚构的个体分布或地图。")

    doc.add_heading("图表证据", level=1)
    for i, figure in enumerate(view["figures"], 1):
        picture = doc.add_paragraph()
        picture.paragraph_format.keep_with_next = True
        picture.paragraph_format.space_after = Pt(2)
        inline = picture.add_run().add_picture(figure["path"], width=Inches(6.15))
        inline._inline.docPr.set("descr", figure["caption"])
        caption = doc.add_paragraph(f"图 {i}  {figure['caption']}", style="Caption")
        caption.paragraph_format.space_after = Pt(10)
        caption.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_heading("解释边界", level=1)
    for text in view["limitations"]:
        paragraph(text)
    if len({r["model_id"] for r in meta["view_records"]}) > 1:
        paragraph("本报告含跨模型的原字段比较，模型机制与量纲的可比性仍需研究者核对。")
    doc.add_heading("执行依据与原始统计", level=1)
    paragraph(content["abstract"])
    for line in _manifest_lines(meta.get("manifest") or {}):
        paragraph(line, small=True)
    paragraph("引用运行：" + "；".join(view["run_ids"]), small=True)
    paragraph("以下为所选运行全程的原始字段统计，用于复查；与前文窗口统计的口径分别标明。", small=True)
    paragraph(content["analysis"], small=True)
    table(["原始字段", "首值", "末值", "全程均值"],
          [[name, val(stat["first"]), val(stat["last"]), val(stat["mean"])] for name, stat in stats.items()],
          [2.45, 1.1, 1.1, 1.15])
    paragraph("完整数值、分析窗口与图表类型保存在同名 JSON 事实文件中。", small=True)
    doc.save(str(path))
