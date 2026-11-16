"""Complete, immutable run/experiment artifacts; views never rerun a saved model."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import platform
import re
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .runtime import RunResult, _jsonable

ROOT = Path(__file__).resolve().parents[1]
_LOCK = threading.RLock()


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _bytes(data):
    return json.dumps(_jsonable(data), ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def _atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with tmp.open("wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def state_stream(record: dict, sample_every=1) -> dict:
    """Produce a display sample from saved states, retaining first and final frames."""
    if not isinstance(sample_every, int) or sample_every < 1:
        raise ValueError("sample_every 必须为正整数")
    all_frames = record.get("state_frames") or []
    frames = all_frames[::sample_every]
    if all_frames and (not frames or frames[-1] is not all_frames[-1]):
        frames.append(all_frames[-1])
    provenance = "entity" if frames and all(f.get("provenance") == "entity" for f in frames) else "aggregate"
    return {"model_id": record["model_id"], "run_id": record["run_id"],
            "provenance": provenance,
            "provenance_note": "主体位置/状态来自本次模型真实计算" if provenance == "entity" else
            "模型未导出个体状态，汇总数据驱动的示意动画（非主体轨迹）",
            "sample_every": sample_every, "total_frames": len(all_frames),
            "n_frames": len(frames), "frames": frames,
            "n_entities_max": max((len(f.get("entities") or []) for f in frames), default=0),
            "observations": record.get("observations") or [],
            "events": record.get("events") or [], "manifest": record["manifest"]}


class RunStore:
    def __init__(self, directory: Path | str):
        self.directory = Path(directory)

    def _path(self, record_id):
        if not re.fullmatch(r"(?:R[0-9A-Za-z_-]+|EX-[0-9A-Za-z_-]+|AN-[0-9A-Za-z_-]+)", str(record_id)):
            raise ValueError("非法运行标识")
        return self.directory / str(record_id)

    def _write_record(self, record_id, pieces, metadata):
        target = self._path(record_id)
        with _LOCK:
            if target.exists():
                raise ValueError(f"运行记录已存在，禁止覆盖: {record_id}")
            stage = self.directory / (".pending-" + uuid.uuid4().hex)
            stage.mkdir(parents=True)
            files = {}
            try:
                for name, value in pieces.items():
                    content = _bytes(value)
                    _atomic_write(stage / name, content)
                    files[name] = hashlib.sha256(content).hexdigest()
                _atomic_write(stage / "metadata.json", _bytes({**metadata, "files": files, "complete": True}))
                os.rename(stage, target)
            except Exception:
                # Only remove files created inside our verified private staging directory.
                if stage.parent.resolve() != self.directory.resolve() or not stage.name.startswith(".pending-"):
                    raise
                for p in stage.iterdir():
                    if p.is_file():
                        p.unlink()
                stage.rmdir()
                raise

    def save_run(self, rr: RunResult, source="run", intent="", request_text=""):
        run_id = rr.manifest["run_id"]
        manifest = dict(rr.manifest)
        manifest["code_version"] = self.archive_code()
        manifest["software"] = {"python": platform.python_version()}
        from importlib.metadata import version, PackageNotFoundError
        for package in ("numpy", "scipy", "pandas", "fastapi", "pydantic"):
            try:
                manifest["software"][package] = version(package)
            except PackageNotFoundError:
                manifest["software"][package] = None
        manifest["artifact_schema"] = 3
        rr.manifest.update(manifest)
        self._write_record(run_id,
                           {"manifest.json": manifest, "observations.json": rr.observations,
                            "state_frames.json": rr.state_frames, "events.json": rr.events,
                            "checkpoint.json": rr.checkpoint},
                           {"kind": "run", "run_id": run_id, "model_id": rr.model_id,
                            "source": source, "intent": intent, "request_text": request_text,
                            "created_at": utc_now(), "n_observations": len(rr.observations)})
        return run_id

    def save_experiment(self, result, intent="", research_spec=None):
        if not result.ok:
            raise ValueError("实验未完成，不能保存为成功实验")
        spec = result.spec.to_dict()
        eid = spec["experiment_id"]
        self._write_record(eid,
                           {"experiment_spec.json": spec, "runs.json": result.runs,
                            "observations.json": result.observations, "analysis.json": result.analysis,
                            "warnings.json": result.warnings,
                            "research_spec.json": research_spec or {}},
                           {"kind": "experiment", "run_id": eid, "model_id": spec["model_id"],
                            "source": "experiment", "intent": intent or spec["title"],
                            "created_at": utc_now()})
        return eid

    def annotate(self, record_id, intent="", request_text=""):
        path = self._path(record_id) / "metadata.json"
        with _LOCK:
            meta = json.loads(path.read_text(encoding="utf-8"))
            meta.update(intent=intent or meta.get("intent", ""),
                        request_text=request_text or meta.get("request_text", ""))
            _atomic_write(path, _bytes(meta))

    def save_analysis(self, tool, payload):
        aid = "AN-" + uuid.uuid4().hex
        payload["analysis_id"] = aid
        payload["data_url"] = f"/api/runs/{aid}/bundle.zip"
        runs = payload.get("runs") or payload.get("stages") or []
        if not runs or any(not r.get("run_id") for r in runs):
            raise ValueError("分析缺少真实运行引用，不能归档")
        self._write_record(aid, {"analysis.json": payload, "runs.json": runs},
                           {"kind": "analysis", "run_id": aid, "source": tool, "tool": tool,
                            "model_id": payload.get("model_id", runs[0]["model_id"]),
                            "intent": tool, "created_at": utc_now()})
        return aid

    def load(self, record_id):
        directory = self._path(record_id)
        meta_path = directory / "metadata.json"
        if not meta_path.is_file():
            raise KeyError(f"运行记录不存在: {record_id}")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        record = dict(meta)
        for name, digest in meta["files"].items():
            if name not in {"manifest.json", "observations.json", "state_frames.json", "events.json",
                            "checkpoint.json", "experiment_spec.json", "research_spec.json",
                            "runs.json", "analysis.json", "warnings.json"}:
                raise ValueError("运行记录含非法产物名称")
            content = (directory / name).read_bytes()
            if hashlib.sha256(content).hexdigest() != digest:
                raise ValueError(f"运行产物校验失败: {name}")
            record[name.removesuffix(".json")] = json.loads(content)
        return record

    def history(self, limit=30):
        if not self.directory.exists():
            return []
        cutoff_path = self.directory / "history_cutoff.json"
        cutoff = json.loads(cutoff_path.read_text(encoding="utf-8")) if cutoff_path.exists() else ""
        metas = []
        for path in self.directory.glob("*/metadata.json"):
            if path.parent.name.startswith(".pending-"):
                continue
            meta = json.loads(path.read_text(encoding="utf-8"))
            if meta.get("created_at", "") > cutoff:
                metas.append(meta)
        metas.sort(key=lambda m: m["created_at"], reverse=True)
        entries = []
        for meta in metas[:max(0, min(int(limit), 60))]:
            record = self.load(meta["run_id"])
            if record["kind"] == "run":
                m = record["manifest"]
                record.update(params=m["requested"].get("parameters", m["actual"].get("parameters", {})),
                              ticks=m["actual"]["n_steps"], seed=m["rng"].get("seed"))
            elif record["kind"] == "experiment":
                spec = record["experiment_spec"]
                record.update(ticks=spec["ticks"], params=spec["baseline_params"],
                              experiment_observations=record["observations"])
                record["observations"] = (record["experiment_observations"].get("基线") or [[]])[0]
            else:
                first = record["runs"][0]
                record.update(observations=first.get("observations") or [],
                              params=first.get("params") or {},
                              ticks=first.get("manifest", {}).get("actual", {}).get("n_steps", 0),
                              analysis_id=record["run_id"])
            record["ts"] = record["created_at"][:19]
            record.pop("state_frames", None)
            record.pop("checkpoint", None)
            entries.append(record)
        return entries

    def clear_history(self):
        # Clear visibility without destroying research artifacts or their download links.
        _atomic_write(self.directory / "history_cutoff.json", _bytes(utc_now()))

    def observations_csv(self, run_id):
        record = self.load(run_id)
        if record["kind"] != "run":
            raise ValueError("实验包含多组运行，请导出完整研究包或选择具体run_id")
        rows = record["observations"]
        fields = list(dict.fromkeys(k for row in rows if isinstance(row, dict) for k in row))
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                             for k, v in row.items()})
        return stream.getvalue().encode("utf-8-sig")

    def bundle(self, record_id):
        record = self.load(record_id)  # Verify integrity before export.
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            ids = list(dict.fromkeys([record_id] + ([r["run_id"] for r in record["runs"]]
                                                   if record["kind"] != "run" else [])))
            codes = set()
            datasets = set()
            for rid in ids:
                r = self.load(rid)
                codes.add(r.get("manifest", {}).get("code_version"))
                datasets.update(b["dataset_id"] for b in r.get("manifest", {}).get("data_bindings", []))
                for p in self._path(rid).iterdir():
                    if p.is_file():
                        archive.write(p, f"{rid}/{p.name}")
            for code in codes - {None}:
                p = self.directory / "code_versions" / (code + ".zip")
                archive.write(p, "code_versions/" + p.name)
            from .datasets import load as load_dataset, dataset_dir
            for dataset in datasets:
                load_dataset(dataset)
                for path in (dataset_dir() / dataset).iterdir():
                    archive.write(path, "datasets/" + dataset + "/" + path.name)
        return output.getvalue()

    def archive_code(self):
        paths = sorted((ROOT / "dayan").rglob("*.py"))
        source = [(str(p.relative_to(ROOT)).replace("\\", "/"), p.read_bytes()) for p in paths
                  if "__pycache__" not in p.parts]
        h = hashlib.sha256()
        for name, content in source:
            h.update(name.encode("utf-8")); h.update(hashlib.sha256(content).digest())
        code = h.hexdigest()
        target = self.directory / "code_versions" / (code + ".zip")
        if not target.exists():
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, content in source:
                    archive.writestr(name, content)
            _atomic_write(target, output.getvalue())
        return code


def get_store():
    return RunStore(Path(os.environ.get("DAYAN_DATA_DIR", str(ROOT / "data"))) / "research_runs")


def resume_saved_run(run_id,ticks,dt=None):
    """Shared API/assistant continuation; state restoration never means reinitialization."""
    from .runtime import resume_from_checkpoint
    store=get_store();parent=store.load(run_id);checkpoint=parent.get('checkpoint')
    if parent['kind']!='run' or not checkpoint:raise ValueError('该记录没有可用于真实续算的检查点')
    step=dt if dt is not None else parent['manifest'].get('requested',{}).get('dt',.1)
    result=resume_from_checkpoint(checkpoint,ticks,step,capture_state=True,with_initial=True)
    result.manifest['requested']['parameters']=dict(result.manifest.get('actual',{}).get('effective_parameters') or {})
    result.manifest['parent_run_id']=run_id
    result.manifest['parent_code_version']=parent['manifest'].get('code_version')
    result.manifest['data_bindings']=parent['manifest'].get('data_bindings',[])
    for key in ('seed','experiment'):
        if key in parent['manifest'].get('rng',{}):result.manifest['rng'][key]=parent['manifest']['rng'][key]
    store.save_run(result,'resume',f'从{run_id}检查点续算')
    return {'model_id':result.model_id,'run_id':result.manifest['run_id'],'observations':result.observations,
            'n':len(result.observations),'manifest':result.manifest,'parent_run_id':run_id,
            'state_url':f"/api/runs/{result.manifest['run_id']}/state"}
