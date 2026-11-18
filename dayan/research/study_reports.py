"""Reports, plots and replication packs generated exclusively from a verified study version."""
from __future__ import annotations
import csv
import hashlib
import io
import json
from pathlib import Path
import zipfile

from . import studies

KINDS = {"academic": "学术研究报告", "data_quality": "数据采集与质量报告", "policy": "政策研究适用性简报"}
FILES = {"academic": "report_B_academic_v2", "data_quality": "report_A_data_quality_v2", "policy": "report_C_policy_brief_v2"}


def report_index(study):
    """Expose only receipts for artifacts that still match this study version."""
    study_id = study['study_id']
    folder = studies.directory(study_id) / 'reports'
    root_url = f'/api/research/studies/{study_id}/files/'
    reports = []
    for kind, stem in FILES.items():
        path = folder / f'{stem}.receipt.json'
        if not path.is_file():
            continue
        item = {'kind': kind, 'label': KINDS[kind]}
        try:
            receipt = json.loads(path.read_text(encoding='utf-8'))
            if receipt['study_sha256'] != study['artifact_sha256'] or receipt['run_id'] != study.get('run_id'):
                raise ValueError('报告与研究版本不一致')
            for name in (f'{stem}.docx', 'replication_pack_v2.zip'):
                if hashlib.sha256((folder / name).read_bytes()).hexdigest() != receipt['files'][name]:
                    raise ValueError('报告哈希核验失败')
            item.update(file=root_url+f'{stem}.docx', bundle_url=root_url+'replication_pack_v2.zip')
        except (OSError, ValueError, KeyError):
            item['error'] = '已保存报告缺失或版本不匹配'
        reports.append(item)
    return reports


def _plots(s, target, kind="academic"):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from ..fonts import configure_matplotlib
    configure_matplotlib()
    fig, axes = plt.subplots(3, 2, figsize=(11.4, 10.2), layout="constrained")
    records, predictions, cal = s["records"], s["predictions"], s["calibration"]
    years, actual = [r["date"] for r in records], [r["value"] for r in records]
    predicted = {r["date"]: r["predicted"] for r in predictions}
    cut = min(r["date"] for r in s["holdout"])
    axes[0,0].plot(years, actual, "o-", color="#087f8c", label="Observed")
    axes[0,0].plot(list(predicted), list(predicted.values()), "s--", color="#ae5c24", label="Model")
    axes[0,0].axvline(cut-.5, color="#777777", linestyle=":", label="Holdout starts")
    axes[0,0].set_title("Observed and actual model run"); axes[0,0].legend(fontsize=8)
    residual = [a-predicted[y] for y,a in zip(years,actual)]
    axes[0,1].bar(years, residual, color=["#087f8c" if y < cut else "#ae5c24" for y in years])
    axes[0,1].axhline(0, color="#777777", linewidth=.7); axes[0,1].set_title("Residuals by year (holdout orange)")
    valid = [e for e in cal["evaluations"] if e["loss"] is not None]
    axes[1,0].scatter([e["combo_id"] for e in valid], [e["loss"] for e in valid], s=14, color="#087f8c")
    axes[1,0].axhline(s["tolerance"], color="#ae5c24", linestyle="--", label="Declared threshold")
    axes[1,0].set_title("Every valid grid evaluation"); axes[1,0].set_xlabel("Evaluation ID"); axes[1,0].legend(fontsize=8)
    hold = cal["holdout"]
    vals = [cal["best_loss"], cal["baseline_mean_rmse"], hold["rmse"], hold["baseline_train_mean_rmse"]]
    axes[1,1].bar(["Train", "Train mean", "Holdout", "Hold mean"], vals, color=["#087f8c", "#b7c2cb", "#ae5c24", "#b7c2cb"])
    axes[1,1].axhline(s["tolerance"], color="#ae5c24", linestyle="--"); axes[1,1].set_title("RMSE vs training-mean baseline")
    axes[2,0].scatter([predicted[y] for y in years], actual, color="#087f8c")
    lo, hi = min(actual + list(predicted.values())), max(actual + list(predicted.values()))
    axes[2,0].plot([lo,hi], [lo,hi], ":", color="#777777"); axes[2,0].set_title("Observed vs predicted"); axes[2,0].set_xlabel("Predicted"); axes[2,0].set_ylabel("Observed")
    axes[2,1].bar(years[1:], [actual[i]-actual[i-1] for i in range(1,len(actual))], color="#087f8c")
    axes[2,1].set_title("Observed annual change"); axes[2,1].set_xlabel("Calendar year")
    for ax in axes.flat:
        ax.grid(axis="y", alpha=.18); ax.set_axisbelow(True)
    if kind == "data_quality":
        for ax in axes.flat: ax.clear(); ax.grid(axis="y",alpha=.18); ax.set_axisbelow(True)
        expected=list(range(int(s["contract"]["date"].split(":")[0]),int(s["contract"]["date"].split(":")[1])+1))
        axes[0,0].bar(expected,[sum(r["date"]==y for r in records) for y in expected],color="#087f8c")
        axes[0,0].set_title("Observed records for each requested year");axes[0,0].set_ylabel("Record count")
        fields=["date","value","country_id","indicator","unit"]
        axes[0,1].bar(fields,[sum(r.get(f) is not None for r in records) for f in fields],color="#087f8c")
        axes[0,1].set_title("Required field coverage");axes[0,1].tick_params(axis="x",labelsize=8)
        axes[1,0].bar(["Training","Holdout"],[len(s["training"]),len(s["holdout"])],color=["#087f8c","#ae5c24"])
        axes[1,0].set_title("Independent time roles, same source batch")
        pages=s["source_pages"]
        axes[1,1].bar([str(p["idx"]) for p in pages],[p["n_records"] for p in pages],color="#087f8c")
        axes[1,1].set_title("Normalized records per immutable source page");axes[1,1].set_xlabel("Page index")
        axes[2,0].hist(actual,bins=min(5,len(actual)),color="#087f8c")
        axes[2,0].set_title("Observed value distribution");axes[2,0].set_xlabel(s["unit"])
        axes[2,1].plot(years,actual,"o-",color="#087f8c");axes[2,1].set_title("Observed series, no imputation")
    fig.suptitle(f"{s['contract']['country']} / {s['contract']['indicator']} / {s['unit']}\n{s['study_id']} / {cal['status']}", fontsize=12)
    fig.savefig(target, dpi=160, facecolor="white"); plt.close(fig)


def generate_report(study_id, kind="academic"):
    from ..collection.storage import file_lock
    with file_lock(studies.directory(study_id) / ".reports.lock", timeout=30):
        return _generate_locked(study_id, kind)


def _generate_locked(study_id, kind="academic"):
    if kind not in KINDS:
        raise ValueError("报告类型须为academic/data_quality/policy")
    s = studies.load(study_id)
    if not s.get("run_id") or not s.get("predictions") or s.get("calibration", {}).get("holdout", {}).get("rmse") is None:
        raise ValueError("研究缺少完整模型运行/留出结果，不能生成完整研究报告")
    folder = studies.directory(study_id) / "reports"
    folder.mkdir(exist_ok=True)
    stem = FILES[kind]
    receipt_path = folder / f"{stem}.receipt.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        for filename, sha in receipt["files"].items():
            if hashlib.sha256((folder / filename).read_bytes()).hexdigest() != sha:
                raise ValueError("已生成报告文件哈希不一致，不能静默覆盖")
        return receipt
    cal, hold = s["calibration"], s["calibration"]["holdout"]
    title = f"{s['contract']['country']} {s['contract']['definition']['concept']} {KINDS[kind]}"
    conclusion = (f"模型为{s['model_family']}描述性趋势。训练RMSE {cal['best_loss']:.9g} {s['unit']}，"
        f"留出RMSE {hold['rmse']:.9g} {s['unit']}，事前阈值{s['tolerance']:.9g} {s['unit']}。"
        f"检验状态为{cal['status']}。" + ("达到此阈值不等于现实政策有效。" if cal['status']=="pass" else "未通过既定验证标准，不宜作为可靠预测或政策推荐依据。"))
    facts = {"study_id": study_id, "study_sha256": s["artifact_sha256"], "run_id": s["run_id"],
        "model_id": s["model_id"], "model_definition_sha256": studies.digest(s["model_definition"]),
        "collection_id": s["collection_id"], "raw_pages": [{"url": p["url"], "sha256": p["sha256"]} for p in s["source_pages"]],
        "dataset_id": s["training_dataset"]["dataset_id"], "dataset_sha256": s["training_dataset"]["sha256"],
        "question": s["question"], "contract": s["contract"], "data_binding": s["run_manifest"]["data_bindings"],
        "best_params": cal["best_params"], "training_rmse": cal["best_loss"], "holdout_rmse": hold["rmse"],
        "baseline_training_rmse": cal["baseline_mean_rmse"], "improvement_vs_baseline": cal["improvement_vs_baseline"],
        "training_dates": cal["training"]["dates"], "holdout_dates": hold["dates"], "status": cal["status"],
        "unit": s["unit"], "threshold": s["tolerance"], "kind": kind, "conclusion": conclusion}
    facts.update(quality=s["quality"],role_check=s["role_check"],source_license=s["training_dataset"]["license"])
    image_path = folder / ("quality_diagnostics.png" if kind=="data_quality" else "diagnostics.png")
    if not image_path.exists(): _plots(s, image_path, kind)
    predicted = {r["date"]: r["predicted"] for r in s["predictions"]}
    table = [[r["date"], "training" if r["date"] < min(hold["dates"]) else "holdout", r["value"], predicted[r["date"]], r["value"]-predicted[r["date"]]] for r in s["records"]]
    with (folder / "observed_predicted.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f); writer.writerow(["year","role","observed","predicted","residual"]); writer.writerows(table)
    (folder / f"{stem}.facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    text = ["# " + title, "", conclusion, "", "## 原始研究问题", s["question"], "", "## 数据与方法",
        f"来源批次 {s['collection_id']}；指标 {s['contract']['indicator']}；国家 {s['contract']['country']}；范围 {s['contract']['date']}；单位 {s['unit']}。",
        f"训练年份 {cal['training']['dates']}；独立留出 {hold['dates']}；完整网格 {cal['n_evaluated']}/{cal['grid_size']}；实际最优参数 {cal['best_params']}。",
        f"模型定义 {s['model_definition']}。初值通过数据映射进入引擎，不在后续年份回灌目标。",
        f"校准相对训练均值基线改善 {cal['improvement_vs_baseline']:.9g}；留出均值基线RMSE {hold['baseline_train_mean_rmse']:.9g}。",
        "", "## 逐年结果", "| 年份 | 角色 | 观测 | 模型 | 残差 |", "|---|---|---|---|---|",
        *["| " + " | ".join(map(str,row)) + " |" for row in table], "", f"![同源诊断图]({image_path.name})",
        "", "## 适用性与未解决问题", *s["limitations"], cal["non_identifiable_note"],
        "此版本未运行政策臂、财政成本或群体异质性分析，不提供相应效应数值。" if kind=="policy" else "所有结论限定于本研究定义与留出窗口。",
        "", "## 复现引用", f"study_id {study_id}；study_sha256 {s['artifact_sha256']}；run_id {s['run_id']}；model_id {s['model_id']}。",
        *[f"来源 {p['url']} SHA256 {p['sha256']}" for p in s["source_pages"]]]
    (folder / f"{stem}.md").write_text("\n\n".join(text), encoding="utf-8")
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    doc = Document(); section = doc.sections[0]
    section.top_margin=Inches(.7); section.bottom_margin=Inches(.7)
    normal = doc.styles["Normal"]; normal.font.name="Calibri"; normal.font.size=Pt(10)
    normal.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Noto Sans CJK SC")
    doc.add_paragraph(title, style="Title")
    doc.add_paragraph(conclusion)
    doc.add_heading("研究问题与数据口径", level=1); doc.add_paragraph(s["question"])
    if kind=="data_quality":
        q=s["quality"]
        doc.add_paragraph(f"记录{q['n_records']}条，数值覆盖{q['coverage_pct']}%；质量状态{q['status']}；范围{q['time_range']}；单位{s['unit']}。未填补缺失，训练与留出观测重叠为{s['role_check']['has_leakage']}。")
        doc.add_paragraph(f"实际数据源页{len(s['source_pages'])}个；许可{s['training_dataset']['license']}；各页请求和SHA256列于证据部分。")
    doc.add_paragraph(f"来源 {s['collection_id']}；{s['contract']['country']}；{s['contract']['indicator']}；{s['contract']['date']}；单位 {s['unit']}。")
    doc.add_paragraph(f"训练年份 {cal['training']['dates']}；留出年份 {hold['dates']}；网格实际评估 {cal['n_evaluated']}/{cal['grid_size']}。")
    doc.add_heading("实际模型与验证", level=1)
    doc.add_paragraph(s["model_definition"]["description"])
    doc.add_paragraph(f"最优参数 {cal['best_params']}；训练均值基线RMSE {cal['baseline_mean_rmse']:.9g}；改善量 {cal['improvement_vs_baseline']:.9g}。")
    t = doc.add_table(rows=1, cols=5); t.style="Light Shading Accent 1"
    for cell,value in zip(t.rows[0].cells,["年份","角色","观测","模型","残差"]): cell.text=value
    header = OxmlElement("w:tblHeader"); t.rows[0]._tr.get_or_add_trPr().append(header)
    for row in table:
        for cell,value in zip(t.add_row().cells,row): cell.text=f"{value:.8g}" if isinstance(value,float) else str(value)
    doc.add_page_break(); doc.add_heading("数据与模型诊断图", level=1)
    doc.add_picture(str(image_path), width=Inches(6.1))
    doc.add_paragraph(f"原单位 {s['unit']}。训练和留出在图中分开显示，全部图取自同一研究与最终运行。")
    doc.add_heading("适用性与证据", level=1)
    for paragraph in s["limitations"]+[cal["non_identifiable_note"]]: doc.add_paragraph(paragraph)
    if kind=="policy": doc.add_paragraph("本版本没有政策臂、成本或因果识别，不生成政策收益或排序。")
    doc.add_paragraph(f"研究 {study_id}\n产物SHA256 {s['artifact_sha256']}\n模型 {s['model_id']}\n运行 {s['run_id']}\n采集 {s['collection_id']}")
    for page in s["source_pages"]: doc.add_paragraph(f"{page['url']}\nSHA256 {page['sha256']}")
    doc.save(folder / f"{stem}.docx")
    # One immutable package includes data, model, all evaluations and the complete saved run.
    pack_path = folder / "replication_pack_v2.zip"
    if not pack_path.exists():
        with zipfile.ZipFile(pack_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(studies.directory(study_id)/"study.json", "study.json")
            for page in s["source_pages"]: z.write(engine_path(page["raw"]), "source/"+Path(page["raw"]).name)
            dsdir = studies.datasets.dataset_dir()/s["training_dataset"]["dataset_id"]
            for name in ("original","data.json","metadata.json"): z.write(dsdir/name, "dataset/"+name)
            for path in studies.get_store()._path(s["run_id"]).iterdir():
                if path.is_file(): z.write(path, "run/"+path.name)
            code = s["run_manifest"]["code_version"]
            code_path = studies.get_store().directory / "code_versions" / (code+".zip")
            if not code_path.is_file():
                raise ValueError("缺少归档代码版本，不能交付不完整复现包")
            z.write(code_path, "code_versions/"+code_path.name)
            z.write(folder/"observed_predicted.csv", "observed_predicted.csv")
    files = [f"{stem}.docx",f"{stem}.md",f"{stem}.facts.json",image_path.name,"observed_predicted.csv","replication_pack_v2.zip"]
    receipt = {"ok": True, "report_schema": 2, "study_id": study_id, "study_sha256": s["artifact_sha256"], "run_id": s["run_id"],
        "validation_status": cal["status"], "kind": kind, "files": {f:hashlib.sha256((folder/f).read_bytes()).hexdigest() for f in files},
        "file": f"/api/research/studies/{study_id}/files/{stem}.docx",
        "bundle_url": f"/api/research/studies/{study_id}/files/replication_pack_v2.zip"}
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return receipt


def engine_path(relative):
    from ..collection import engine
    path = (engine.BASE / relative).resolve()
    if not path.is_relative_to(engine.BASE.resolve()): raise ValueError("非法原始来源路径")
    return path
