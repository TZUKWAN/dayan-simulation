"""Detailed research report evidence derived from saved definitions and observations."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from statistics import median
from zipfile import BadZipFile, ZipFile

from .model_method import model_method
from .view_analysis import in_window, metric_info, number


def _design(manifest):
    from .agent.model_design import _digest, load_design

    pointer = (manifest.get("scenario_review") or {}).get("model_design") or {}
    context=manifest.get('experiment_context') or {}
    if not pointer and context.get('model_definition_sha256')==_digest(manifest.get('model_definition')):
        pointer=context.get('model_design') or {}
    if not pointer.get("design_id"):
        return None
    try:
        record = load_design(pointer["design_id"])
    except (ValueError, FileNotFoundError):
        return None
    if (record.get("status") != "approved" or not record.get("plan")
            or _digest(record["plan"]) != pointer.get("plan_sha256")
            or record.get("source_fingerprint") != manifest.get("source_fingerprint")):
        return None
    steps = {stage["step"]: stage["output"] for stage in record["stages"]}
    changes = {item["id"]: item["change"] for item in steps.get("revision",{}).get("resolutions",[])}
    literature = record.get("literature")
    if literature and record["plan"].get("literature_sha256") != _digest(literature):
        literature = None
    return {
        "id": record["design_id"], "scope": 'same_reviewed_model_comparison' if context else record.get("approval_scope", "original_request"),
        "approach": steps.get("revision",{}).get("approach") or steps.get("concept",{}).get("approach",""),
        "reviewed_stages": [stage["step"] for stage in record["stages"]],
        "issues": [{"problem":item["problem"], "response":changes.get(item["id"],item["fix"])}
                   for item in steps.get("critique",[])],
        "coverage": record["plan"].get("coverage", []),
        "assumptions": record["plan"].get("assumptions", []),
        "limitations": record["plan"].get("limitations", []),
        "alternatives": steps.get("revision", steps.get("concept", {})).get("alternatives", []),
        "rule_refs": record["plan"].get("rule_refs", []),
        "literature": literature,
        "literature_decisions": record["plan"].get("literature_decisions", []) if literature else [],
        "literature_discussion": record["plan"].get("literature_discussion") if literature else None,
    }


def _in_window(row, window):
    return not window or in_window(row["sim_t"], window)


def _describe_metrics(model_id, selected):
    series = {}
    for index, row in enumerate(selected):
        time = row.get("sim_t", index)
        for key, value in row.items():
            if key != "sim_t" and number(value):
                series.setdefault(key, []).append((time,value))
    metrics = {}
    for key, pairs in series.items():
        times, values = zip(*pairs)
        minimum, maximum = min(values), max(values)
        pairs_by_time = [(b_t-a_t,b-a) for (a_t,a),(b_t,b) in zip(pairs,pairs[1:]) if b_t>a_t]
        best_rate = max((change/dt for dt,change in pairs_by_time),default=None)
        metrics[key] = {
            **metric_info(model_id,key), "n":len(values), "missing":len(selected)-len(values),
            "first":values[0],"first_t":times[0],"last":values[-1],"last_t":times[-1],
            "delta":values[-1]-values[0],"median":median(values),
            "minimum":minimum,"min_t":times[values.index(minimum)],
            "maximum":maximum,"max_t":times[values.index(maximum)],"max_rate":best_rate,
            "increases":sum(b>a for a,b in zip(values,values[1:])),
            "decreases":sum(b<a for a,b in zip(values,values[1:])),
        }
    return metrics


def _findings(metrics, key, events, n_runs, pedestrian):
    if not metrics:
        return []
    primary = metrics[key] if key in metrics else next(iter(metrics.values()))
    name, unit = primary["name"], primary["unit"]
    findings = [f"{name}从模型时刻 {primary['first_t']:g} 的 {primary['first']:.6g} {unit} "
                f"变为 {primary['last_t']:g} 的 {primary['last']:.6g} {unit}，"
                f"变化量 {primary['delta']:+.6g} {unit}。"]
    if "evacuated" in metrics and "alive" in metrics:
        evacuated, alive = metrics["evacuated"], metrics["alive"]
        findings.append(f"窗口最后有效观测有 {evacuated['last']:g} 人累计离场，仍有 {alive['last']:g} 人在场。")
        if not alive["last"] and evacuated["maximum"]>0 and evacuated["last"]==evacuated["maximum"]:
            findings.append(f"窗口内首次观测到场地清空的模型时刻为 {evacuated['max_t']:g}。")
    if pedestrian.get("clearance"):
        milestones = pedestrian["clearance"]
        findings.append("按累计离场量首次达到各比例的保存时点计，" +
                        "，".join(f"{item['fraction']:.0%} 为 {item['sim_t']:g} 模型秒" for item in milestones) + "。")
    for field in ("yielding","min_separation"):
        if field not in metrics:
            continue
        item = metrics[field]
        extreme = "minimum" if field == "min_separation" else "maximum"
        at = "min_t" if field == "min_separation" else "max_t"
        label = "最低" if field == "min_separation" else "最高"
        findings.append(f"{item['name']}{label}为 {item[extreme]:.6g} {item['unit']}，首次出现在模型时刻 {item[at]:g}。")
    if pedestrian.get("initial_overlaps") is not None and pedestrian.get("subsequent_overlap_peak") is not None:
        findings.append(f"初态有 {pedestrian['initial_overlaps']} 对几何相交，"
                        f"初态之后峰值为 {pedestrian['subsequent_overlap_peak']} 对。")
    if events:
        label = "归档的阶段转换" if pedestrian else "归档事件"
        findings.append(label + "依次为 " + "、".join(f"{e['label']}（{e['sim_t']:g}）" for e in events[:12]) + "。")
    if n_runs == 1:
        findings.append("结论限定在本次配置和种子。独立重复、干预效应与现实校准需要各自的运行证据。")
    return findings


def _event_phases(observations, events, window):
    names = {"drill_fall":"倒地待助","aid_started":"就地协助","aid_completed":"恢复及离场"}
    bounds = [(event["sim_t"], names[event["etype"]]) for event in events if event["etype"] in names]
    if not bounds:
        return []
    low,high = (window["from"],window["to"]) if window else (observations[0]["sim_t"],observations[-1]["sim_t"])
    points = [(observations[0]["sim_t"],"事件前"),*bounds,(observations[-1]["sim_t"],"")]
    phase_rows = []
    for (start,label),(end,_) in zip(points,points[1:]):
        a,b = max(low,start),min(high,end)
        valid = [row for row in observations if a<=row["sim_t"]<=b and _in_window(row, window)]
        if b<=a or not valid:
            continue
        during = [row for row in valid if row["sim_t"]<b]
        phase_rows.append({"phase":label,"from":a,"to":b,
                           "departed":valid[-1]["evacuated"]-valid[0]["evacuated"],
                           "active_at_start":valid[0]["alive"],"active_at_end":valid[-1]["alive"],
                           "peak_avoiding":max((row["yielding"] for row in during),default=0),
                           "peak_contacts":max((row["local_conflicts"] for row in during),default=0)})
    return phase_rows


def _model_description(model_id, manifest):
    saved = manifest.get("model_method")
    if not saved and manifest.get("model_definition"):
        return model_method(model_id, manifest["model_definition"])
    if not saved or saved.get("revision") or model_id not in ("NET114", "NET121"):
        return saved
    # A revised description may be applied to a historical run only after matching the implemented dynamics.
    from .run_store import get_store
    from .source_version import ROOT

    code_version = manifest.get("code_version", "")
    if not re.fullmatch("[a-f0-9]{64}", code_version):
        return saved
    pack = get_store().directory / "code_versions" / (code_version + ".zip")
    path = "dayan/models/pedestrian.py"
    try:
        with pack.open("rb") as stream:
            if hashlib.file_digest(stream,"sha256").hexdigest() != manifest.get("code_archive_sha256"):
                return saved
        with ZipFile(pack) as archive:
            if archive.read(path).replace(b"\r\n",b"\n") != (ROOT/Path(path)).read_bytes().replace(b"\r\n",b"\n"):
                return saved
            if model_id == "NET121":
                # Version of the archived implementation which placed agents independently.
                archived_layout = hashlib.sha256(archive.read("dayan/models/crowd_response.py").replace(b"\r\n",b"\n")).hexdigest()
                if archived_layout != "28ab6a60819ea42b37f7b89e31a947e06b62d5cbca957a40032367a2d990660f":
                    return saved
            return {**model_method(model_id, legacy_layout=True), "historical_description_rechecked": True}
    except (BadZipFile, OSError, KeyError):
        pass
    return saved


def _data_audit(manifest):
    from .datasets import analyze, load

    checks = []
    for binding in manifest.get("data_bindings", []):
        if not all(key in binding for key in ("dataset_id", "parameter", "field", "resolved_value", "sha256")):
            continue
        row = {"parameter":binding["parameter"], "dataset_id":binding["dataset_id"], "status":"unavailable"}
        try:
            dataset = load(binding["dataset_id"])
            stats = analyze(binding["dataset_id"], binding.get("path",""), binding.get("filters"), binding.get("order_by"))
            values = stats["numeric"][binding["field"]]
            aggregate = binding.get("aggregate", "last")
            from math import isclose
            execution = manifest.get("actual",{}).get("effective_parameters",{}).get(binding["parameter"])
            verified = dataset["sha256"] == binding["sha256"] and values["n"] == binding.get("records_used") and (
                number(execution) and isclose(execution, binding["resolved_value"], rel_tol=1e-12, abs_tol=1e-12)
                and isclose(values[aggregate] * binding.get("scale",1), execution, rel_tol=1e-12, abs_tol=1e-12))
            pages = dataset["metadata"].get("pages") or []
            provenance = pages[0].get("meta",{}).get("provenance",{}) if len(pages)==1 else {}
            row.update(status="recomputed" if verified else "mismatch", n=values["n"], mean=values["mean"],
                       minimum=values["min"], maximum=values["max"], retrieved_at=dataset.get("retrieved_at"),
                       **{key:provenance[key] for key in ("archive_member","published_rows","payload_sha256") if key in provenance})
        except (OSError, ValueError, KeyError, TypeError):
            pass
        checks.append(row)
    return checks


def _pedestrian_results(model_id, rows, manifest):
    if model_id not in ("NET114", "NET121") or not rows:
        return {}
    n = manifest.get("actual",{}).get("effective_parameters",{}).get("n")
    if not number(n) or n <= 0 or any(not number(row.get("evacuated")) or not number(row.get("alive")) for row in rows):
        return {}
    milestones = []
    for fraction in (.5,.9,1.):
        first = next((row for row in rows if row["evacuated"] >= fraction*n), None)
        if first and (first is not rows[0] or rows[0]["sim_t"] == 0):
            milestones.append({"fraction":fraction, "sim_t":first["sim_t"], "evacuated":first["evacuated"]})
    initial = rows[0].get("local_conflicts") if rows[0]["sim_t"]==0 else None
    later = [row["local_conflicts"] for row in rows[1:] if number(row.get("local_conflicts"))]
    return {
        "clearance":milestones, "initial_overlaps":initial, "subsequent_overlap_peak":max(later,default=None),
        "undefined_spacing":sum(row["alive"]<2 for row in rows),
        "unexpected_missing_spacing":sum(row["alive"]>=2 and not number(row.get("min_separation")) for row in rows),
    }


def report_evidence(model_id, observations, meta):
    from .structured_inputs import structured_audit
    manifest = meta.get("manifest") or {}
    method = _model_description(model_id, manifest)
    view = meta.get("view_analysis") or {}
    record = next((record for record in meta.get("view_records", [])
                   if record.get("run_id")==manifest.get("run_id")), {})
    events = [{"sim_t":event["sim_t"],"label":event.get("label") or event.get("etype","事件"),
               "etype":event.get("etype",""),"entity_id":event.get("entity_id","")}
              for event in record.get("events",[]) if number(event.get("sim_t"))]
    events.sort(key=lambda event:event["sim_t"])
    window = view.get("window")
    selected = [row for row in observations if _in_window(row, window)]
    metrics = _describe_metrics(model_id, selected)
    pedestrian = _pedestrian_results(model_id, selected, manifest)
    window_events = [event for event in events if _in_window(event, window)]
    first_frame = next(iter(record.get("state_frames",[])),{})
    facilities = [{key:entry[key] for key in ("id","label","kind","x","y","width","depth","role") if key in entry}
                  for entry in first_frame.get("facilities",[])]
    return {
        "model_method": method, "design": _design(manifest),
        "metrics": metrics, "events": window_events, "phases": _event_phases(observations,events,window),
        "scene": {"space":first_frame.get("space"),"facilities":facilities},
        "data_audit": _data_audit(manifest),
        "structured_data_audit": structured_audit(manifest, record.get('checkpoint')), "pedestrian": pedestrian,
        "findings":_findings(metrics,view.get("metric"),window_events,len(view.get("run_ids",[None])),pedestrian),
    }
