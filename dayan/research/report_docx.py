"""三类研究报告 DOCX 渲染（python-docx，复用 report_gen 风格）。"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = ROOT / "data" / "collection" / "reports"


def render_md_to_docx(md_path: str, output_name: str = "") -> str:
    """将 Markdown 研究报告渲染为 DOCX（标题/段落/表格/粗体）。"""
    from docx import Document
    from docx.shared import Pt, RGBColor, Inches
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    md_text = Path(md_path).read_text(encoding="utf-8")
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}eastAsia",
        "微软雅黑")

    lines = md_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        # 标题
        heading = re.match(r"^(#{1,3})\s+(.+)", stripped)
        if heading:
            level = len(heading.group(1))
            h = doc.add_heading(heading.group(2), level=min(level, 3))
            for run in h.runs:
                run.font.color.rgb = RGBColor(0x0E, 0x7C, 0x86)
            i += 1
            continue
        # 表格
        if stripped.startswith("|") and i + 1 < len(lines) and \
                lines[i+1].strip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                rows.append(cells)
                i += 1
            if len(rows) >= 2:
                table = doc.add_table(rows=0, cols=len(rows[0]))
                table.style = "Table Grid"
                for ri, row in enumerate(rows):
                    if all(set(c) <= {"-", ":", " "} for c in row):
                        continue  # 跳过分隔行
                    tr = table.add_row()
                    for ci, cell in enumerate(row[:len(rows[0])]):
                        tr.cells[ci].text = cell
                        if ri == 0:
                            for run in tr.cells[ci].paragraphs[0].runs:
                                run.font.bold = True
            continue
        # 列表项
        if stripped.startswith("- ") or stripped.startswith("· "):
            doc.add_paragraph(stripped[2:], style="List Bullet")
            i += 1
            continue
        # 粗体段落
        if stripped.startswith("**") and stripped.endswith("**"):
            p = doc.add_paragraph()
            run = p.add_run(stripped.strip("*"))
            run.font.bold = True
            i += 1
            continue
        # 普通段落
        doc.add_paragraph(stripped)
        i += 1

    # 页脚
    doc.add_paragraph("")
    foot = doc.add_paragraph(
        "本报告由大衍 DAYAN 平台基于真实数据采集与校准结果自动生成；"
        "数值来源见报告内引用的 collection_id 与哈希。"
        + ("（LLM 离线，模板渲染）" if not md_text else ""))
    foot.runs[0].font.size = Pt(8)
    foot.runs[0].font.color.rgb = RGBColor(0x88, 0x88, 0x88)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    fname = output_name or (Path(md_path).stem + ".docx")
    path = REPORTS_DIR / fname
    doc.save(str(path))
    return str(path)


def render_all_reports(study_id=None) -> list[dict]:
    """Only regenerate from a verified study. Legacy MD may describe different model versions."""
    if not study_id:
        raise ValueError("旧模板缺少统一研究版本；请指定study_id，禁止批量覆盖历史DOCX")
    from .study_reports import generate_report
    return [generate_report(study_id, kind) for kind in ("academic", "data_quality", "policy")]


def _legacy_render_all_reports_disabled() -> list[dict]:
    """将 data/collection/reports/ 下所有 .md 报告渲染为 .docx。"""
    results = []
    for md_file in sorted(REPORTS_DIR.glob("report_*.md")):
        docx_name = md_file.stem + ".docx"
        try:
            path = render_md_to_docx(str(md_file), docx_name)
            results.append({"md": str(md_file), "docx": path,
                            "bytes": Path(path).stat().st_size, "ok": True})
        except Exception as e:
            results.append({"md": str(md_file), "ok": False,
                            "error": str(e)[:100]})
    return results


if __name__ == "__main__":
    for r in render_all_reports():
        print(r)
