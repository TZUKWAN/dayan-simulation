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
from copy import deepcopy
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


def _read_verified(directory, name, digest):
    content = (directory / name).read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError(f"运行产物校验失败: {name}")
    return json.loads(content)


def state_stream(record: dict, sample_every=1) -> dict:
    """Produce a display sample from saved states, retaining first and final frames."""
    if not isinstance(sample_every, int) or sample_every < 1:
        raise ValueError("sample_every 必须为正整数")
    all_frames = record.get("state_frames") or []
    scaled = any("population" in frame for frame in all_frames)
    requested_every=sample_every
    frame_budget=8*1024*1024
    frame_bytes=None
    if scaled:
        import math
        from .population import playback_frame
        # Measure real display payloads before removing temporal observations.
        # Stop an oversized attempt early, then use its measured cost to pick a
        # coarser stride. Movement is recomputed against the actual displayed
        # predecessor, not a discarded intermediate frame.
        while True:
            selected=all_frames[::sample_every]
            if all_frames and (not selected or selected[-1] is not all_frames[-1]):selected.append(all_frames[-1])
            frames=[];frame_bytes=2
            for index,frame in enumerate(selected):
                rendered=playback_frame(frame,selected[index-1] if index else None)
                frames.append(rendered)
                frame_bytes+=len(_bytes(rendered))+(1 if index else 0)
                if frame_bytes>frame_budget and len(selected)>2:
                    projected=frame_bytes/len(frames)*len(selected)
                    sample_every*=max(2,math.ceil(projected/frame_budget))
                    break
            else:break
    else:
        frames = all_frames[::sample_every]
        if all_frames and (not frames or frames[-1] is not all_frames[-1]):
            frames.append(all_frames[-1])
    sources = {frame.get("provenance") for frame in frames}
    notes = {
        "entity": "主体位置与状态来自本次模型实际计算",
        "lattice": "各网格层来自本次模型逐格状态",
        "aggregate": "模型未导出个体状态，汇总数据驱动的示意动画（非主体轨迹）",
    }
    provenance = next(iter(sources)) if len(sources) == 1 and sources <= notes.keys() else "aggregate"
    lattice = frames[0].get("lattice") if provenance == "lattice" else None
    from .stateframe import population_size
    if scaled:
        notes["lattice"] = "画面按区域汇总实际格点状态；完整状态保存在本次运行包"
        notes["entity"] = "画面显示固定真实主体样本；仿真与归档包含全部主体"
    return {"model_id": record["model_id"], "run_id": record["run_id"],
            "provenance": provenance,
            "provenance_note": notes[provenance],
            **({"lattice_cells": lattice.get("source_width",lattice["width"]) * lattice.get("source_height",lattice["height"])} if lattice else {}),
            "sample_every": sample_every, "total_frames": len(all_frames),
            **({'frame_sampling':{'requested_every':requested_every,'measured_frame_bytes':frame_bytes,
                  'budget_bytes':frame_budget,'budget_satisfied':frame_bytes<=frame_budget,
                  'scope':'回放帧实际UTF-8字节，不含响应中其他元数据；原始归档帧未修改'}} if scaled else {}),
            "n_frames": len(frames), "frames": frames,
            "n_entities_max": max((population_size(f) for f in frames), default=0),
            **({"rendered_entities_max": max((len(f["entities"]) for f in frames), default=0),
                "created_at": record.get("created_at"), "request_text": record.get("request_text"), "intent": record.get("intent"),
                "full_state_url": f"/api/runs/{record['run_id']}/bundle.zip"} if scaled else {}),
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
        from .limits import limits
        budget = limits().run_bytes
        target = self._path(record_id)
        with _LOCK:
            if target.exists():
                raise ValueError(f"运行记录已存在，禁止覆盖: {record_id}")
            stage = self.directory / (".pending-" + uuid.uuid4().hex)
            stage.mkdir(parents=True)
            files = {}
            try:
                size = 0
                for name, value in pieces.items():
                    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":"))
                    digest = hashlib.sha256()
                    with (stage / name).open("xb") as stream:
                        buffer = []
                        buffered = 0
                        for part in encoder.iterencode(_jsonable(value)):
                            buffer.append(part)
                            buffered += len(part)
                            if buffered < 65536:
                                continue
                            chunk = "".join(buffer).encode("utf-8")
                            size += len(chunk)
                            if size > budget:
                                raise ValueError("运行归档超过单次大小预算；未发布不完整记录")
                            stream.write(chunk)
                            digest.update(chunk)
                            buffer.clear()
                            buffered = 0
                        chunk = "".join(buffer).encode("utf-8")
                        size += len(chunk)
                        if size > budget:
                            raise ValueError("运行归档超过单次大小预算；未发布不完整记录")
                        stream.write(chunk)
                        digest.update(chunk)
                        stream.flush()
                        os.fsync(stream.fileno())
                    files[name] = digest.hexdigest()
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
        manifest["code_version"] = self.archive_code(manifest.get('source_fingerprint'))
        manifest['code_archive_sha256']=hashlib.sha256((self.directory/'code_versions'/(manifest['code_version']+'.zip')).read_bytes()).hexdigest()
        from .reproducibility import environment
        manifest['environment']=environment()
        manifest["software"] = {"python": platform.python_version()}
        from importlib.metadata import version, PackageNotFoundError
        for package in ("numpy", "scipy", "pandas", "fastapi", "pydantic"):
            try:
                manifest["software"][package] = version(package)
            except PackageNotFoundError:
                manifest["software"][package] = None
        if manifest.get('protocol')=='managed_program':
            executed=manifest.get('execution_environment')
            if not executed or not executed.get('image_id') or not executed.get('python'):
                raise ValueError('受管程序缺少实际容器环境回执，不能用宿主软件版本代替')
            manifest['orchestrator_environment']=manifest['environment']
            manifest['environment']=deepcopy(executed)
            manifest['software']={'python':executed['python'],**executed['packages']}
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

    def save_analysis(self, tool, payload, *, record_id=None):
        aid = record_id or "AN-" + uuid.uuid4().hex
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

    def load(self, record_id, *, exclude=()):
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
            if name not in exclude:
                record[name.removesuffix(".json")] = _read_verified(directory, name, digest)
        return record

    def load_manifest(self, run_id):
        """Read a completed run's verified manifest without opening frames and observations."""
        directory = self._path(run_id)
        meta = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        if meta.get("kind") != "run" or not meta.get("complete") or meta.get("run_id") != run_id:
            raise ValueError("研究记忆需要已完整归档的原始运行")
        return meta, _read_verified(directory, "manifest.json", meta["files"]["manifest.json"])

    def history(self, limit=30, *, metadata_only=False, offset=0, search='', before=None, after=None,
                workbench=False, legacy_path=None):
        from .history_records import metadata_page

        page = metadata_page(self, limit, offset=offset, search=search, before=before, after=after,
                             workbench=workbench and metadata_only, legacy_path=legacy_path)
        if metadata_only:
            return page
        entries = []
        for meta in page:
            record = self.load(meta["run_id"], exclude=("state_frames.json", "checkpoint.json"))
            record.update({key: meta[key] for key in ("title", "automatic_title", "title_is_custom")})
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
        record = self.load(run_id, exclude=("state_frames.json", "checkpoint.json"))
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
        """Compatibility bytes helper; HTTP delivery uses the prepared file."""
        return self.prepare_bundle(record_id).read_bytes()

    def prepare_bundle(self, record_id):
        record = self.load(record_id)  # Verify integrity before export.
        from .limits import limits
        cap = limits()
        bundle_budget = cap.run_bytes + cap.job_bytes
        target=self.directory/'exports'/(record_id+'.zip')
        target.parent.mkdir(parents=True,exist_ok=True)
        temporary=target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
        total=0
        try:
          with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            ids = list(dict.fromkeys([record_id] + ([r["run_id"] for r in record["runs"]]
                                                   if record["kind"] != "run" else [])))
            codes = set()
            datasets = set()
            for rid in ids:
                r = self.load(rid)
                version=r.get('manifest',{}).get('code_version')
                codes.add(version)
                if version:
                    code_path=self.directory/'code_versions'/(version+'.zip')
                    expected=r.get('manifest',{}).get('code_archive_sha256')
                    if expected and hashlib.sha256(code_path.read_bytes()).hexdigest()!=expected:
                        raise ValueError('归档代码ZIP哈希不一致')
                datasets.update(b["dataset_id"] for b in r.get("manifest", {}).get("data_bindings", []))
                for p in self._path(rid).iterdir():
                    if p.is_file():
                        total+=p.stat().st_size
                        if total>bundle_budget:raise ValueError('研究包超过导出大小预算')
                        archive.write(p, f"{rid}/{p.name}")
            for code in codes - {None}:
                p = self.directory / "code_versions" / (code + ".zip")
                total+=p.stat().st_size
                if total>bundle_budget:raise ValueError('研究包超过导出大小预算')
                archive.write(p, "code_versions/" + p.name)
            from .datasets import load as load_dataset, dataset_dir
            pending = {dataset: None for dataset in datasets}
            included = set()
            while pending:
                dataset, expected = pending.popitem()
                asset = load_dataset(dataset)
                if expected and asset["sha256"] != expected:
                    raise ValueError('上游数据快照哈希与派生产物记录不一致')
                if dataset in included:
                    continue
                included.add(dataset)
                for parent in asset.get("metadata",{}).get("derived_from",[]):
                    pending[parent["dataset_id"]] = parent["sha256"]
                for path in (dataset_dir() / dataset).iterdir():
                    total+=path.stat().st_size
                    if total>bundle_budget:raise ValueError('研究包超过导出大小预算')
                    archive.write(path, "datasets/" + dataset + "/" + path.name)
          os.replace(temporary,target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def archive_code(self,expected_source=None):
        from .runtime import assert_loaded_source
        from .reproducibility import source_inventory
        current=assert_loaded_source()
        if not expected_source or expected_source!=current:
            raise ValueError('执行版本与归档源码不一致；未伪造本次源码证据')
        code,source,digests=source_inventory()
        if assert_loaded_source()!=expected_source:raise ValueError('归档期间源码变化')
        target = self.directory / "code_versions" / (code + ".zip")
        if not target.exists():
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, content in source:
                    archive.writestr(name, content)
                archive.writestr('SOURCE_MANIFEST.json',_bytes({'schema':1,'code_version':code,
                    'source_fingerprint':expected_source,'files':digests,
                    'exclusions':['private config and secrets','historical research and collected data','virtual environments']}))
            _atomic_write(target, output.getvalue())
        return code


def get_store():
    return RunStore(Path(os.environ.get("DAYAN_DATA_DIR", str(ROOT / "data"))) / "research_runs")


def resume_saved_run(run_id,ticks,dt=None):
    """Shared API/assistant continuation; state restoration never means reinitialization."""
    from .runtime import resume_from_checkpoint
    store=get_store();parent=store.load(run_id);checkpoint=parent.get('checkpoint')
    from .runtime import assert_loaded_source
    if parent.get('manifest',{}).get('source_fingerprint')!=assert_loaded_source():
        raise ValueError('原运行源码与当前进程不一致；须在归档源码中恢复，不能用修改后的模型冒充连续状态')
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
