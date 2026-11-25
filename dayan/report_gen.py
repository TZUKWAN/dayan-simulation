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
    series = {}
    for observation in observations:
        for key, value in observation.items():
            if not skip.search(key) and isinstance(value, (int, float)) and not isinstance(value, bool) and np.isfinite(value):
                series.setdefault(key, []).append(value)
    for k, vals in series.items():
        out[k] = {
            "increases": int(np.count_nonzero(np.diff(vals) > 1e-12)),
            "decreases": int(np.count_nonzero(np.diff(vals) < -1e-12)),
            "unchanged": int(np.count_nonzero(np.abs(np.diff(vals)) <= 1e-12)),
            "first": round(float(vals[0]), 6),
            "last": round(float(vals[-1]), 6),
            "min": round(float(min(vals)), 6),
            "max": round(float(max(vals)), 6),
            "mean": round(float(np.mean(vals)), 6),
            "n_valid": len(vals),
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
    if analysis.get('kind')=='global_sensitivity':
        protocol=analysis['protocol']
        lines.append(f'全局敏感性：{protocol["statistic"]}({metric})；独立分布{json.dumps(protocol["distributions"],ensure_ascii=False)}；n={protocol["n"]}，种子面板{protocol["seeds"]}。')
        lines.append('Saltelli pick-freeze：S_i=E[f(B)(f(A_B^i)-f(A))]/Var(Y)，ST_i=E[(f(A)-f(A_B^i))²]/(2 Var(Y))；先按A/B共同均值中心化。95%区间为配对行bootstrap。')
        for row in analysis['indices']:
            lines.append(f'{row["parameter"]}：一阶{row["first_order"]}，区间{row["first_interval"]}；总效应{row["total_order"]}，区间{row["total_interval"]}。')
        lines.append('估计状态：'+analysis['status']+'；点内种子方差均值：'+str(analysis['mean_within_point_seed_variance'])+'。'+analysis['replicate_note'])
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
    review = manifest.get('scenario_review') or {}
    if review.get('model_design'):
        lines.append('方案编号 '+review['model_design']['design_id'])
    scope = review.get('coverage') or {}
    if scope.get('status')=='partial':
        lines.append('原始需求仅部分覆盖。未计算：'+'；'.join(scope['gaps']))
    for item in manifest.get('data_bindings') or []:
        if 'port' in item:
            lines.append(f"结构数据 {item['dataset_id']} → {item['port']}，保留 {item['records_used']} 条联合记录；"
                         f"输入 SHA-256 {item['input_sha256']}。传入求解器不等于已校准或已证明因果有效。")
            continue
        if 'parameter' not in item or 'resolved_value' not in item:
            continue
        lines.append(f"实测数据 {item['dataset_id']}，字段 {item['field']}，{item.get('aggregate','last')} 聚合后绑定 "
                     f"{item['parameter']}={item['resolved_value']} {item.get('target_unit') or ''}。"
                     f"来源 {item.get('reference') or item.get('source','')}，SHA-256 {item.get('sha256','')}。")
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
        valid = f"，{stat['n_valid']} 个时点有值" if stat['n_valid']!=n_obs else ""
        descriptions.append(f"{name}：首个有效值 {stat['first']}，最后有效值 {stat['last']}，均值 {stat['mean']}{valid}；"
                            f"相邻观测上升 {stat['increases']} 次、下降 {stat['decreases']} 次、持平 {stat['unchanged']} 次，{shape}。")
    return {"title": f"{model_id} 仿真实验事实报告",
            "abstract": count + "。结果与图表使用相同运行的完整观测，不根据首末值推断单调性。",
            "background": meta.get("intent") or "记录本次模型运行的实际配置与数值结果。",
            "method": "模型名称：" + cat.get("name", model_id) + "。本报告记录计算结果，模型的理论适用性须结合原研究问题判断。",
            "design": "实际配置与执行结果列于下方清单。" if manifest else "未提供完整运行清单，无法核验配置和计算过程。",
            "analysis": "\n".join(descriptions) or "本次运行没有可统计的数值观测量。",
            "conclusion": "本次输出支持上述运行内的数值描述。" + ("实验比较结果见下表。" if meta.get("analysis") else "单次运行不支持稳健性或现实预测结论。"),
            "limitations": "统计不自动证明收敛、周期性、显著性或现实因果关系。观测字段的量纲未在模型合同中定义时按原字段展示，不把模型时间擅自称为现实秒或小时。"}


def report_facts(model_id, observations, meta=None, *, include_figures=False):
    """The read-only report and the downloaded document use the same archive facts."""
    meta = dict(meta or {})
    raw_count = len(observations)
    time_quality = meta.get("time_quality", [])
    if meta.get("view_analysis"):
        from .view_analysis import analysis_time_series
        observations = analysis_time_series(observations)
    meta['n_observations'] = len(observations)
    stats = _stats(observations)
    cat = _catalog_info(model_id)
    content = _fact_report(model_id, meta, stats, cat)
    if meta.get('view_analysis'):
        content['title'] = f'{model_id} 仿真结果分析报告'
    scope = (meta.get('manifest', {}).get('scenario_review') or {}).get('coverage') or {}
    scope = scope if isinstance(scope,dict) else {}
    if scope.get('status') == 'partial':
        content['title'] = f'{model_id} 仿真诊断报告 · 原需求部分覆盖'
        content['abstract'] += ' 本次诊断的未覆盖机制：' + '、'.join(scope['gaps']) + '。'
    from .report_evidence import report_evidence
    evidence = report_evidence(model_id, observations, meta)
    if evidence["model_method"] and scope.get("status") != "partial":
        method_name = evidence["model_method"].get("name") or cat.get("name")
        if method_name:
            content["title"] = method_name + "仿真研究报告"
    if scope.get("status") == "exercise":
        verification = (meta.get("manifest", {}).get("scenario_review", {}).get("runtime_checks") or {}).get("verification")
        if not verification:
            content["title"] = "景区步道人群疏散演练的历史运行复核"
            content["abstract"] += " 归档记录了虚拟演练的数值过程，未达到对原始事故发生机制的覆盖。"
        else:
            content["abstract"] += " 本次计算的范围为用户选定的虚拟疏散演练。"
    repeated = raw_count - len(observations)
    if repeated:
        content["abstract"] = (f"历史归档有 {raw_count} 行原始观测，其中 {repeated} 行与前一行同刻且逐字段一致。"
                               f"统计和图表采用 {len(observations)} 个不同的保存时点，原始归档可供核对。 "
                               + ("单次运行的证据范围见验证与适用范围。" if repeated else ""))
    view = meta.get("view_analysis")
    if view and include_figures:
        from .research_charts import build_charts

        view = {**view, "figures": build_charts(meta["view_records"], view, REPORTS_DIR)}
    return {'run_id': (meta.get('manifest') or {}).get('run_id'), 'model_id': model_id,
            'n_observations': len(observations), 'raw_observations': raw_count, 'time_quality': time_quality,
            'stats': stats, 'analysis': meta.get('analysis', {}),
            'manifest': meta.get('manifest', {}), 'content': content, 'view_analysis': view,
            'research_evidence': evidence,
            'generator': 'program-computed-facts'}


def generate_report(model_id, observations, meta=None):
    import hashlib
    import uuid
    meta = dict(meta or {})
    if not observations:
        return {"ok": False, "error": "没有实际观测，不能生成完成报告"}
    meta["n_observations"] = len(observations)
    run_tag = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:10]
    fname = f"report_{model_id}_{run_tag}.docx"
    path = REPORTS_DIR / fname
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        facts = report_facts(model_id, observations, meta, include_figures=True)
        stats, content = facts['stats'], facts['content']
        if meta.get("view_analysis"):
            meta["view_analysis"] = facts["view_analysis"]
            _build_research_docx(path, model_id, meta, stats, content, facts["research_evidence"])
        else:
            _build_docx(path, model_id, meta, _catalog_info(model_id), _capability(model_id), stats, observations, content, run_tag)
    except Exception as exc:
        return {"ok": False, "error": f"docx 生成失败: {exc}"}
    facts['docx_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix(".json").write_text(json.dumps(facts, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return {"ok": True, "path": str(path), "url": f"/reports/{fname}",
            "title": content["title"], "facts_url": f"/reports/{path.stem}.json",
            "run_id": facts["run_id"], "generation": "program-computed-facts",
            "scope": (facts["manifest"].get("scenario_review") or {}).get("coverage"),
            "mathematics": bool(facts["research_evidence"]["model_method"]),
            "figure_count": len((facts.get("view_analysis") or {}).get("figures",[])),
            "findings": facts["research_evidence"]["findings"]}


def _sensitivity_section(doc,analysis):
    if analysis.get('kind')!='global_sensitivity':return
    doc.add_heading('附录：全局敏感性实验与数学口径',level=1)
    for line in _analysis_lines(analysis):doc.add_paragraph(line)
    doc.add_paragraph('分析编号：'+analysis['analysis_id']+'；所有样本参数、实际运行引用与求值保存在同名JSON的analysis和分析包。常数输出的指数标为未定义；估计不强制落在[0,1]。')


def _actor_decision_section(doc,manifest):
    audit=manifest.get('actor_decisions')
    if not audit:return
    doc.add_heading('附录：主体大模型决策与记录重放',level=1)
    doc.add_paragraph(f"当前场景成员 {manifest.get('run_id','')}：本运行实际服务调用 {audit['real_call_count']} 次，"
        f"返回主体动作 {audit['action_count']} 条，决策批次 {audit['batch_count']}，历史重放边界 {audit['replay_boundaries']}。"
        '历史响应重放没有计作本运行新调用；动作是否正确反映现实行为仍需独立验证。')
    models=sorted({call.get('model','未记录') for call in manifest.get('llm_calls',[]) if call.get('purpose')=='program-actor-decision'})
    if models:doc.add_paragraph('实际决策服务模型：'+'；'.join(models))
    doc.add_paragraph('决策规则与单位：'+audit['policy']['instruction'])
    doc.add_paragraph('动作合同：'+json.dumps(audit['policy']['action_schema'],ensure_ascii=False))
    table=doc.add_table(rows=1,cols=5)
    for cell,text in zip(table.rows[0].cells,['决策时刻','批次','主体','实际动作','来源']):cell.text=text
    shown=0
    for record in audit['records']:
        for receipt in record['receipts']:
            for action in receipt['actions']:
                if shown>=60:continue
                values=[str(receipt['sim_t']),receipt['batch_id'],action['actor_id'],
                        json.dumps(action['action'],ensure_ascii=False),'历史响应重放' if record['replayed'] else '本运行实际响应']
                for cell,text in zip(table.add_row().cells,values):cell.text=text
                shown+=1
    if audit['action_count']>shown:doc.add_paragraph(f'表中显示前{shown}条；全部动作、请求和响应摘要在同源JSON与运行包中。')


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
            p["name"] for p in cap["parameters"][:14] if isinstance(p, dict) and isinstance(p.get("name"), str)))
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

    _actor_decision_section(doc,meta.get('manifest') or {})
    _sensitivity_section(doc,meta.get('analysis') or {})
    doc.save(str(path))


def _build_research_docx(path, model_id, meta, stats, content, evidence):
    """Question, comparable results and complementary evidence before technical facts."""
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
    from docx.opc.constants import RELATIONSHIP_TYPE
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from urllib.parse import quote

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

    def paper_link(p, label, url):
        link = OxmlElement("w:hyperlink")
        link.set(qn("r:id"), p.part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True))
        run = p.add_run(label)
        run.underline = True
        link.append(run._r)
        p._p.append(link)

    def add_figure(item):
        title = doc.add_paragraph()
        title.add_run(f"图 {item['number']}  {item['title']}").bold = True
        title.paragraph_format.keep_with_next = True
        title.paragraph_format.space_after = Pt(2)
        picture = doc.add_paragraph()
        picture.alignment = WD_ALIGN_PARAGRAPH.CENTER
        picture.paragraph_format.keep_with_next = True
        picture.paragraph_format.space_after = Pt(2)
        inline = picture.add_run().add_picture(item["path"], width=Inches(6.5))
        inline._inline.docPr.set("descr", item["caption"])
        caption = doc.add_paragraph(item["caption"], style="Caption")
        caption.paragraph_format.space_after = Pt(10)

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
            row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
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
                    p.alignment = WD_ALIGN_PARAGRAPH.LEFT if ci == 0 or len(cell.text)>25 else WD_ALIGN_PARAGRAPH.CENTER
                    for run in p.runs:
                        run.font.size = Pt(10)
        return result

    def val(value, precision=6):
        return f"{value:.{precision}g}" if isinstance(value, (int, float)) else "无有效观测"

    def equation(text):
        if len(text)>86:
            p = paragraph(text)
            for run in p.runs:
                run.font.name = "Cambria Math"
            return
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Inches(.17)
        math = OxmlElement("m:oMath")
        def term(value, *, upright=False):
            run = OxmlElement("m:r")
            if upright:
                properties = OxmlElement("m:rPr")
                properties.append(OxmlElement("m:nor"))
                run.append(properties)
                font_properties = OxmlElement("w:rPr")
                fonts = OxmlElement("w:rFonts")
                for script in ("ascii", "hAnsi", "eastAsia"):
                    fonts.set(qn(f"w:{script}"), "Noto Sans CJK SC")
                font_properties.append(fonts)
                run.append(font_properties)
            node = OxmlElement("m:t")
            node.set(qn("xml:space"),"preserve")
            node.text = value
            run.append(node)
            return run

        subs = "₀₁₂₃₄₅₆₇₈₉ₓᵧᵢⱼₖ₊₋"
        supers = "ˢᶜʷ"
        han = r"\u3400-\u9fff"
        convert = str.maketrans(subs+supers,"0123456789xyijk+-scw")
        tokens = re.finditer(rf"([A-Za-z])([{subs}]+|[{han}]+(?=[(,‖]))([{supers}]*)|([{han}]+)",text)
        end = 0
        for match in tokens:
            if match.start()>end:
                math.append(term(text[end:match.start()]))
            base,index,power,prose = match.groups()
            if prose:
                math.append(term(prose,upright=True))
                end = match.end()
                continue
            span = OxmlElement("m:sSubSup" if power else "m:sSub")
            parts = [("e",base),("sub",index)]
            if power:
                parts.append(("sup",power))
            for tag,value in parts:
                component = OxmlElement("m:"+tag)
                component.append(term(value.translate(convert),upright=bool(re.fullmatch(f"[{han}]+",value))))
                span.append(component)
            math.append(span)
            end = match.end()
        if end<len(text):
            math.append(term(text[end:]))
        p._p.append(math)

    doc.add_paragraph(content["title"], style="Title")
    manifest = meta.get("manifest") or {}
    method, design = evidence["model_method"], evidence["design"]
    review = manifest.get("scenario_review") or {}
    scope = review.get("coverage")
    scope = scope if isinstance(scope,dict) else {}
    checks = review.get("runtime_checks") or {}
    verification = checks.get("verification")
    paragraph(f"大衍工作台  {model_id}   {manifest.get('run_id','')}", small=True)
    if meta.get("intent"):
        doc.add_heading("研究问题",level=1)
        for requirement in meta["intent"].splitlines():
            if requirement.strip():
                paragraph(requirement.strip())
    if manifest.get('experiment_context'):
        paragraph('本组沿用同一已审模型，按声明的参数处理和配对种子重新计算。'
                  '下文保留原建模依据与实际方程，对照效应使用本组真实结果，方向不预设。')
    info, window = view["metric_info"], view["window"]
    paragraph(f"本报告分析{info['name']}，单位为{info['unit']}。分析窗口为 "
              f"{window['from']:g} {'<' if window['exclusive'] else '≤'} sim_t ≤ {window['to']:g}。"
              f"共引用{len(view['run_ids'])}次已保存运行，观察时点为模型时间 {view['requested_time']:g}。")
    if scope.get("status")=="exercise":
        if not verification:
            paragraph("原始问题要求事故情境。实际归档采用预定倒地的疏散演练，实际计算覆盖人群移动、局部降速和离场。"
                      "事故发生机理的覆盖未通过本次复核。")
        paragraph("预定事件及受助时程属于模型输入假设。移动、几何相交和离场由规则计算。"
                  "本文结论只涉及归档中的虚拟情境。")
    doc.add_heading("主要发现", level=1)
    for finding in evidence["findings"]:
        paragraph(finding)
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
        paragraph(f"本次运行在窗口内有{item['n']}个不同的有效观测时点，{info['name']}的时点算术均值为{val(item['mean'])}。"
                  f"窗口首值为{val(item['first'])}，末值为{val(item['last'])}。")
    table(["方案", "运行数", "每次有效时点", "时点算术均值"],
          [[g["name"], g["n"], "/".join(str(n) for n in g["observations_per_run"]), val(g["mean"])] for g in view["groups"]],
          [2.45, .7, 1.35, 1.3])
    paragraph("每次运行内对选定窗口的有效时点等权平均，再按方案汇总。此数值随窗口及采样频率变化。"
              "独立重复的单位是运行或配对种子。", small=True)
    if view["figures"]:
        add_figure(view["figures"][0])
    distribution = view["distribution"]
    departed = view.get("departed_entities", 0)
    if view.get("lattice"):
        grid = view["lattice"]
        if grid.get('preview_only'):
            paragraph(f"sim_t={view['frame_time']:g} 的网格显示预览为 {grid['width']}×{grid['height']}，"
                      f"源网格为 {grid['source_width']}×{grid['source_height']}。"
                      "此图经过聚合与量化，不从预览像素推算原始格值、均值或格点状态数量。")
        else:
            paragraph(f"sim_t={view['frame_time']:g} 保存 {grid['width']}×{grid['height']} 个格点。"
                      "每个图层均来自本次运行保存的逐格状态。")
        if grid.get('preview_only'):
            paragraph('预览图层：'+'、'.join(layer['label'] for layer in grid['layers']), small=True)
        elif grid["layers"] and "count" not in grid["layers"][0]:
            table(["图层", "最小值", "最大值", "均值"],
                  [[layer["label"], val(layer["min"]), val(layer["max"]), val(layer["mean"])] for layer in grid["layers"]],
                  [2.2, 1.45, 1.45, 1.55])
        else:
            table(["图层", "状态", "格数"],
                  [[layer["label"], layer["state"], str(layer["count"])] for layer in grid["layers"]],
                  [2.2, 2.55, 1.9])
    if distribution:
        description = f"所选运行在 sim_t={view['frame_time']:g} 有{view['entity_count']}个已归档主体。"
        if distribution.get("field",'').split('.')[-1] == "speed":
            from .view_analysis import metric_info
            unit = distribution.get('unit') or metric_info(model_id, "speed")["unit"]
            description += f"当前速度属性范围内{distribution.get('zero_count',0)}个主体速度为零，单位为{unit}。"
        if distribution.get('missing') or distribution.get('not_applicable'):
            description += (f"属性{distribution['field']}有{distribution['n']}个有效值，"
                            f"缺失{distribution.get('missing',0)}个，其他组不适用{distribution.get('not_applicable',0)}个；未补零。")
        if departed:
            description += f"{departed}名离场行人已从当前位置和步速统计剔除。"
        paragraph(description)
    elif departed:
        paragraph(f"sim_t={view['frame_time']:g} 已有{departed}名行人离场，当前没有在场行人的位置和步速分布。")
    elif not view.get('lattice'):
        paragraph("所选运行没有可用于主体分布分析的状态，不生成虚构的个体分布或地图。")

    doc.add_heading("建模过程与方案审查", level=1)
    if method:
        paragraph(method["description"])
    if design:
        paragraph(f"方案编号 {design['id']}。系统以分开的模型调用保存思路、缺陷、修订、实施方案和复核意见。"
                  "这些记录用于追溯选型，实证资格见后面的核验表。", small=True)
        if scope.get("status")=="exercise":
            paragraph("场地、出口与事件时点是情境设定。种子决定初始位置及演练对象。"
                      "演练对象暂停、转入受助状态并恢复可移动。周围行人按距离调整目标步速，保持朝同一出口的目标方向。")
        elif design["approach"]:
            paragraph(design["approach"])
        if design["alternatives"]:
            table(["候选结构", "适配性与取舍"],
                  [[item["structure"], item["limitation"]] for item in design["alternatives"]], [2.0,4.65])
        if design["rule_refs"]:
            table(["机制", "实际演化方程"], [[item["mechanism"], "、".join(item["paths"])]
                  for item in design["rule_refs"]], [2.55,4.1])
        if design["issues"]:
            table(["当时的方案审查意见", "当时的拟处理方式"],
                  [[item["problem"],item["response"]] for item in design["issues"]], [3.1,3.55])
        if design["coverage"]:
            doc.add_heading("原需求的逐项对应", level=2)
            table(["原文", "方案记录", "拟用验收依据"],
                  [[item["quote"],item["implementation"],item["test"] +
                    (f"（{', '.join(item['criteria'])}）" if item.get("criteria") else "")]
                   for item in design["coverage"]],
                  [2.05,2.45,2.15])
            if scope.get("incident_physics"):
                paragraph("上表保留当时方案。实际覆盖由归档的事故机制及运行检查记录说明，详见验证与适用范围。", small=True)
    else:
        paragraph("此归档可核对已保存的执行记录。方案审查详页未随该次运行保存。")
    if design and design.get("literature"):
        from .research.literature import summary

        literature = design["literature"]
        counts = summary(literature)
        doc.add_heading("在线文献与建模依据", level=1)
        paragraph(f"在线核查候选 {len(literature['screened'])} 篇，精读 {counts['reviewed']} 篇。"
                  f"其中期刊文章 {counts['journals']} 篇，具有期刊收录来源记录 {counts['indexed_journals']} 篇，"
                  f"预印本 {counts['preprints']} 篇。本轮期刊文献目标为 {counts['target']} 至 {literature['maximum']} 篇。")
        counts_access = {kind: sum(item["access"] == kind for item in literature["screened"])
                         for kind in ("abstract_only", "unavailable")}
        if any(counts_access.values()):
            paragraph(f"候选中仅可核对摘要 {counts_access['abstract_only']} 篇，正文不可读 {counts_access['unavailable']} 篇。")
        errors = [row for row in literature["search"] if row["status"] != "ok"]
        if errors:
            paragraph("部分检索未成功。"+ "；".join(f"{row['provider']} · {row['query']} · {row.get('reason',row['status'])}"
                                                      for row in errors), small=True)
        if literature.get("reading_error"):
            paragraph("精读分析未取得可验证的回执。")
        if design.get("literature_discussion"):
            paragraph(design["literature_discussion"])
        aspects = {"method": "方法", "rationale": "采用理由", "validation": "验证", "limitations": "局限"}
        versions = {"published": "出版版", "accepted": "接受稿", "submitted": "投稿稿",
                    "preprint": "预印本版本", "unknown": "版本待核实"}
        basis = {"reported": "原文陈述", "inferred": "据原文推断", "unavailable": "未核实"}
        for paper in literature["cards"]:
            doc.add_heading(f"{paper['id']}  {paper['title']}", level=2)
            identities = [paper["journal"], str(paper["year"] or ""), *paper["authors"],
                          *(["DOI " + paper["doi"]] if paper["doi"] else []),
                          *([paper["arxiv_id"]] if paper.get("arxiv_id") else []),
                          versions.get(paper["version"], paper["version"])]
            p = paragraph(" · ".join(filter(None, identities)) + "  ")
            paper_link(p, "在线原文", paper["url"])
            if paper["indexes"]:
                p = paragraph("期刊收录来源 ", small=True)
                for index in paper["indexes"]:
                    paper_link(p, index["name"], index["url"])
                    p.add_run(" · ")
                p.add_run("核对访问时的目录或期刊说明。")
            paragraph(paper["relevance"])
            for key, item in paper["findings"].items():
                ident = item.get("evidence_id")
                prefix = f"{ident}  " if ident else ""
                p = paragraph(f"{prefix}{aspects[key]}（{basis[item['basis']]}） {item['text']}")
                if item.get("locator"):
                    p.add_run("  ")
                    url = paper["url"] + ("#" + quote(item["anchor"], safe="=") if item.get("anchor") else "")
                    paper_link(p, item["locator"], url)
        if design["literature_decisions"]:
            doc.add_heading("对本轮模型的影响", level=2)
            actions = {"adopt": "采纳", "adapt": "调整后采用", "compare": "对照",
                       "decline": "舍弃", "assume": "本轮假设", "unlinked": "本轮设计依据"}
            table(["实际模型决定", "依据与取舍", "适用和检验条件"],
                  [[f"{item['target']} {item['target_label']}",
                    f"{actions[item['action']]}  {'、'.join(item['refs'])}  {item['reason']}",
                    item["condition"]] for item in design["literature_decisions"]], [2.0, 2.55, 2.1])
    assumptions = (method or {}).get("assumptions", [])
    if assumptions:
        doc.add_heading("场景与假设", level=2)
        for item in assumptions:
            paragraph(item)
    facilities = evidence["scene"]["facilities"]
    if facilities:
        table(["场地或设施", "中心 x 与 y", "宽 × 深", "角色"],
              [[item.get("label") or item.get("id") or item.get("kind","设施"),f"{val(item.get('x'))} · {val(item.get('y'))}",
                f"{val(item.get('width'))} × {val(item.get('depth'))}",
                "参与模型计算" if item.get("role")=="modeled" else "场景参照"] for item in facilities],
              [2.25,1.45,1.45,1.5])

    doc.add_heading("数学表达与数值方法", level=1)
    if scale := manifest.get("scale"):
        if scale.get("entities"):
            paragraph(f"实际推进 {scale['entities']:,} 个主体，保存 {scale['kept_state_frames']} 个时点的完整主体状态。"
                      f"执行器为 {scale['kernel']}。每一步的数值观测读取全部主体。")
    if method:
        if method.get("historical_description_rechecked"):
            paragraph("已校验该运行的源码压缩包及对应模型文件，以下用复核后的说明表述同一实现。", small=True)
        group = None
        for entry in method["equations"]:
            if entry["group"] != group:
                group = entry["group"]
                doc.add_heading(group, level=2)
            equation(entry["expression"])
            if entry.get("meaning"):
                paragraph(entry["meaning"])
        for item in method["integration"]:
            paragraph(item)
    else:
        paragraph("此运行只归档了实参和观测。完整数学规范在该归档中缺失。")

    doc.add_heading("参数与实测数据口径", level=1)
    config = manifest.get("actual",{}).get("effective_parameters") or {}
    bindings = {item["parameter"]:item for item in manifest.get("data_bindings",[]) if item.get("parameter")}
    if config:
        specs = (method or {}).get("parameters",{})
        table(["参数", "实际值", "单位与含义", "取值依据"],
              [[key,str(value)," ".join(filter(None,(specs.get(key,{}).get("unit"),specs.get(key,{}).get("meaning")))),
                "数据字段 " + bindings[key]["field"] if key in bindings else "执行设定"] for key,value in config.items()],
              [1.3,1.55,2.3,1.5])
    for key, item in bindings.items():
        paragraph(f"数据集 {item['dataset_id']} 的 {item['field']} 经过 "
                  f"{item.get('aggregate','last')} 汇总及比例 {item.get('scale',1):g} 换算，"
                  f"实际绑定 {key}={item['resolved_value']} {item.get('target_unit') or ''}。")
        if item.get("method"):
            paragraph(item["method"])
        use = f"聚合使用 {item['records_used']} 条有效记录。" if item.get("records_used") is not None else ""
        paragraph(f"{use}来源 {item.get('reference') or item.get('source','')}。"
                  f"许可 {item.get('license') or '未声明'}。"
                  f"源范围 {item.get('source_scope') or '未声明'}。SHA-256 {item['sha256']}。", small=True)
    for audit in evidence["data_audit"]:
        if audit["status"] != "recomputed":
            paragraph(f"{audit['parameter']} 的源文件或实际值暂不能相互核验。复现记录保留原归档映射。")
            continue
        paragraph(f"从存档重新计算 {audit['parameter']} 的输入汇总，并与实际引擎参数匹配。"
                  f"有效记录 {audit['n']} 条，源字段的观察范围为 {val(audit['minimum'])} 至 {val(audit['maximum'])}。")
        if audit.get("archive_member") == "kbf/tables/visits.csv":
            paragraph(f"本次使用发布包内单个园区的访问级汇总表。表内共 {audit['published_rows']} 行，"
                      f"按发布者标记纳入 {audit['n']} 行。发布者将该资料界定为非代表性的小样本试点。"
                      "这里只用日常访问均值初始化目标步速，未用来拟合实际疏散时间、人员间距或应急速度。")
            paragraph("Utley 与 Hackl（2026）主题公园访客移动数据 v1.0.0 https://doi.org/10.5281/zenodo.20748587", small=True)
    ports = [item for item in manifest.get('data_bindings',[]) if 'port' in item]
    audits = {item['port']:item for item in evidence.get('structured_data_audit',[])}
    for item in ports:
        spec = item['contract']
        paragraph(f"结构输入端口 {item['port']}：{spec['kind']}，用途 {spec['purpose']}。"
                  f"源记录 {item['source_records']} 条，实际输入 {item['records_used']} 条；各列保留同一记录关联。")
        if spec['fields']:
          table(['实际字段','类型 / 单位','源字段与转换','缺失数'], [
            [name, f"{field['type']} / {field['unit']}",
             f"{item['columns'][name].get('field',item['columns'][name].get('pointer'))}；scale={item['columns'][name]['scale']}，offset={item['columns'][name]['offset']}",
             item['missing'][name]] for name,field in spec['fields'].items()], [1.25,1.6,2.8,1.])
        for name, mapping in item['columns'].items():
            if mapping.get('transformation_note'):
                paragraph(name+' 的转换依据：'+mapping['transformation_note'])
            if mapping.get('value_map') or mapping.get('missing_values'):
                paragraph(name+' 的显式类别/缺失规则：'+json.dumps({
                    key:mapping[key] for key in ('value_map','missing_values') if key in mapping}, ensure_ascii=False))
        if spec.get('clock'):
            paragraph('输入时间合同：'+json.dumps(spec['clock'],ensure_ascii=False))
            if item.get('time_summary'):
                label = '按系列观测时点核对的输入时间范围：' if spec['kind']=='timeseries' else '按声明端点计算的输入时间范围：'
                paragraph(label+json.dumps(item['time_summary'],ensure_ascii=False))
        if spec.get('endpoints'):
            paragraph('实际关系端点：'+json.dumps(spec['endpoints'],ensure_ascii=False))
        if spec.get('geometry'):
            paragraph('原始几何坐标合同：'+json.dumps(spec['geometry'],ensure_ascii=False))
            paragraph('几何读取记录：'+json.dumps(item.get('geometry_summary',{}),ensure_ascii=False))
            paragraph('保留原始几何、属性和Feature身份；没有自动投影，也未据格式检查认定多边形拓扑或空间测量准确。')
        status = audits.get(item['port'],{}).get('status','snapshot_unavailable')
        paragraph('原文件、显式转换、完整输入快照及运行哈希已重新核对一致。' if status=='recomputed' else
                  f'结构输入复核状态：{status}；尚不能宣称源数据与实际输入完整对应。')
        paragraph(f"来源 {item['source']}；许可 {item.get('license') or '未声明'}；角色 {item['role']}。"
                  f"原文件 SHA-256 {item['sha256']}；实际输入 SHA-256 {item['input_sha256']}。", small=True)
        paragraph('输入完整送入计算的证据不能替代输入扰动验算、现实校准或外推有效性检查。')
    if not bindings and not ports:
        paragraph("本次归档的参数均为配置值或模型默认值。")

    if len(view["figures"]) > 1:
        doc.add_heading("补充可视化分析", level=1)
        previous_section = None
        for item in view["figures"][1:]:
            if item["section"] != previous_section:
                doc.add_heading(item["section"], level=2)
                previous_section = item["section"]
            add_figure(item)

    doc.add_heading("详细结果分析", level=1)
    metrics = evidence["metrics"]
    if metrics:
        table(["指标", "有效时点", "首值", "末值", "中位", "最小 · 时刻", "最大 · 时刻"],
              [[f"{item['name']} {item['unit']}",item["n"],val(item["first"],5),val(item["last"],5),
                val(item["median"],5),f"{val(item['minimum'])} · {val(item['min_t'])}",
                f"{val(item['maximum'])} · {val(item['max_t'])}"] for item in metrics.values()],
               [1.58,.58,.72,.72,.72,1.18,1.15])
        for key,item in metrics.items():
            if key == "min_separation" and evidence["pedestrian"]:
                continue
            if item["missing"] or key==view["metric"]:
                paragraph(f"{item['name']}在窗口内有 {item['n']} 个有效观测，"
                          f"缺值 {item['missing']} 个。相邻有效观测上升 {item['increases']} 次，"
                          f"下降 {item['decreases']} 次。首末有效值差为 {item['delta']:+.6g} {item['unit']}。")
    pedestrian = evidence["pedestrian"]
    if pedestrian:
        paragraph(f"最小间距的定义需要至少两名在场者。本窗口有 {pedestrian['undefined_spacing']} 个时点因人数不足而未定义，"
                  f"另有 {pedestrian['unexpected_missing_spacing']} 个本应有值的时点未记录有效值。")
    if evidence["events"]:
        doc.add_heading("实际事件时序", level=2)
        table(["模型时刻", "事件", "主体"],[[val(item["sim_t"]),item["label"],item["entity_id"] or "—"]
              for item in evidence["events"][:40]],[1.3,3.65,1.7])
    if evidence["phases"]:
        doc.add_heading("按演练阶段分析", level=2)
        table(["阶段", "时段", "在场变化", "离场增量", "降速峰值", "相交峰值"],
              [[item["phase"],f"{val(item['from'])}–{val(item['to'])}",
                f"{item['active_at_start']} → {item['active_at_end']}",item["departed"],
                item["peak_avoiding"],item["peak_contacts"]] for item in evidence["phases"]],
              [1.45,1.13,1.2,1.0,1.0,.87])
        maximum = max(evidence["phases"], key=lambda item:item["peak_avoiding"])
        paragraph(f"降速规则作用人数的峰值出现在{maximum['phase']}阶段。几何相交只表示模型圆盘重叠，开场还反映随机初始位置，"
                  "该值需与事件发生后的相交统计分别解释。")
        paragraph("阶段来自本次状态转移。首末在场人数取阶段边界的观测，峰值取右端时刻之前。"
                  "不同时段的变化受在场人数和位置共同影响，不能把阶段间差异归因于协助本身。")
    doc.add_heading("验证与适用范围", level=1)
    if checks:
        paragraph(f"运行后核验了 {len(checks['observables'])} 个实际观测字段和 "
                  f"{len(checks['verified_events'])} 类要求事件。共保存 {checks['state_frames']} 帧状态。")
    if verification:
        labels = {"start":"初值", "end":"终值", "range":"全程范围", "delta":"净变化",
                  "balance":"逐时点守恒", "nondecreasing":"不下降", "nonincreasing":"不上升",
                  "at_step":"指定步", "at_time":"指定时刻", "event_count":"事件次数",
                  "event_time":"事件时刻", "event_value":"事件数值", "relation_count":"实际关系帧数量"}
        rows = []
        for spec in verification["criteria"]:
            measured = spec["measured"]
            target = (f"目标 {val(spec['target'])}" if "target" in spec else
                      f"{val(spec['min'])} 至 {val(spec['max'])}" if "min" in spec else labels[spec["check"]])
            actual_result = (f"最大绝对偏差 {val(measured['max_abs_error'])}" if "max_abs_error" in measured else
                             f"净变化 {val(measured['delta'])}" if "delta" in measured else
                             f"违例 {measured['violations']} 次" if "violations" in measured else
                             f"{val(measured.get('minimum'))} 至 {val(measured.get('maximum'))}")
            label = (f"第 {spec['step']} 步" if spec["check"] == "at_step" else
                     f"模型时刻 {val(spec['time'])}" if spec["check"] == "at_time" else labels[spec["check"]])
            subject = "、".join(spec['fields'])
            if spec['check'] == 'relation_count':
                subject = 'state_frames.relations' + (f" · type={spec['relation_type']}" if 'relation_type' in spec else '')
                label += f"（第 {spec['step']} 步）" if 'step' in spec else '（全部已存帧）'
                if 'observable' in spec:
                    target += f"；同刻对账 {spec['observable']}"
                actual_result += f"；核对 {measured['matched_frames']} 帧"
                if measured['max_observable_error'] is not None:
                    actual_result += f"；与观测最大差 {val(measured['max_observable_error'])}"
            if spec['check'].startswith('event_'):
                subject = spec['event'] + (f" · {spec['field']}" if 'field' in spec else '')
                if 'occurrence' in spec:
                    label += f"（第 {spec['occurrence']} 次）"
                actual_result = f"实际 {val(measured.get('actual'))}；共 {measured['matched_events']} 次"
                if measured.get('selected_event_time') is not None:
                    actual_result += f"；发生时刻 {val(measured['selected_event_time'])}"
            rows.append([spec["id"] + " " + label, subject,
                         f"{target}，容差 {val(spec['atol'])}。{spec['reason']}",
                         actual_result, "通过" if spec["passed"] else "未通过"])
        table(["事前条件", "观测字段或事件", "目标及依据", "运行计算", "判定"], rows,[.95,1.13,2.42,1.42,.73])
    elif scope.get("status") == "exercise":
        paragraph("历史运行只有字段、阶段事件与呈现的执行记录。原方案没有按现行合同冻结并执行数值检验。"
                  "真值校准、独立留出和跨种子稳健性证据缺失。")
    for item in dict.fromkeys([*(scope.get("gaps") or []),*(scope.get("limits") or []),
                              *((method or {}).get("limitations") or [])]):
        paragraph(item)
    if scope.get("incident_physics"):
        table(["事故机制", "模型实际覆盖"],list(scope["incident_physics"].items()),[2.2,4.45])
    for text in view["limitations"]:
        paragraph(text)
    if len({r["model_id"] for r in meta["view_records"]}) > 1:
        paragraph("本报告含跨模型的原字段比较，模型机制与量纲的可比性仍需研究者核对。")
    doc.add_heading("复现记录与参考文献", level=1)
    paragraph(content["abstract"])
    if manifest.get("source_fingerprint"):
        paragraph("实际执行源码指纹 " + manifest["source_fingerprint"], small=True)
    if manifest.get("software"):
        versions = manifest["software"]
        paragraph(f"执行环境 Python {versions.get('python')}，NumPy {versions.get('numpy')}。"
                  f"随机流 {manifest.get('rng',{}).get('algorithm','未归档')}。", small=True)
    for line in _manifest_lines(meta.get("manifest") or {}):
        paragraph(line, small=True)
    paragraph("引用运行：" + "；".join(view["run_ids"]), small=True)
    for item in (method or {}).get("references", []):
        paragraph(item,small=True)
    paragraph("完整数值、分析窗口与图表类型保存在同名 JSON 事实文件中。", small=True)
    _actor_decision_section(doc,manifest)
    _sensitivity_section(doc,meta.get('analysis') or {})
    doc.save(str(path))
