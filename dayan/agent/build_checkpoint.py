"""Input-bound build stages and durable identities for accepted simulation archives."""
from contextlib import contextmanager
from datetime import datetime, timezone
import uuid

from .design_checkpoint import DesignCheckpoint, digest
from ..collection.storage import atomic_json, file_lock, read_json
from ..access import data_root
from ..limits import limits


class BuildCheckpoint(DesignCheckpoint):
    def reserve(self, key, *, analysis=False):
        slots = self.record.setdefault("archives", {})
        if key not in slots:
            prefix = "AN-" if analysis else "R" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-"
            slots[key] = {"record_id": prefix + uuid.uuid4().hex, "committed": False}
            self.save()
        return slots[key]

    def archive_marker(self, key):
        return {"operation_id": self.record["operation_id"], "key": key}

    def recover(self, key, *, analysis=False):
        from ..run_store import get_store
        slot = self.reserve(key, analysis=analysis)
        store = get_store()
        from ..history_records import preferences
        if preferences(store).get(slot["record_id"], {}).get("deleted"):
            raise ValueError("该构建的运行记录已被用户删除；不能将删除记录作为新的续接交付")
        if not store._path(slot["record_id"]).exists():
            if slot["committed"]:
                raise ValueError("该构建已完成但运行记录已删除；不会通过续接恢复已删除历史")
            return None
        saved = store.load(slot["record_id"])
        payload = saved["analysis"] if analysis else saved["manifest"]
        if payload.get("continuation") != self.archive_marker(key):
            raise ValueError("已归档结果与本次构建账本不匹配")
        if not analysis and payload.get("source_fingerprint") != self.record["identity"]["source_fingerprint"]:
            raise ValueError("已归档结果的执行版本与审查版本不一致")
        self.committed(key)
        return saved

    def committed(self, key):
        self.record["archives"][key]["committed"] = True
        self.record.pop("inflight", None)
        self.save()

    def start_run(self, key):
        # Reserve time for a full compute slot and archival, rather than handing the
        # solver the few seconds left by semantic review.
        seconds = min(limits().cpu_seconds + 20, max(2, limits().wall_seconds - 25))
        self.begin("execution", digest(self.archive_marker(key)), seconds)

    def bind_run(self, key, rr):
        slot = self.reserve(key)
        rr.manifest.update(run_id=slot["record_id"], continuation=self.archive_marker(key))
        for frame in rr.state_frames:
            frame["run_id"] = slot["record_id"]


@contextmanager
def build_checkpoint(design, definition, audit, deadline):
    identity = {key: design[key] for key in ("design_id", "request", "session_id", "execution_sha256",
                                           "plan_sha256", "source_fingerprint")}
    identity["definition_sha256"] = digest(definition) if definition is not None else None
    operation_id = digest(identity)
    path = data_root() / "model_builds" / (operation_id + ".json")
    with file_lock(path.with_suffix(".lock"), timeout=.1):
        if path.exists():
            record = read_json(path)
            if record.get("identity") != identity or record.get("operation_id") != operation_id:
                raise ValueError("构建检查点的输入身份校验失败")
        else:
            record = {"identity": identity, "operation_id": operation_id, "status": "building", "stages": [],
                      "created_at": datetime.now(timezone.utc).isoformat()}
            atomic_json(path, record)
        checkpoint = BuildCheckpoint(record, path, audit, deadline)
        if record.get("inflight"):
            record.setdefault("interruptions", []).append(record.pop("inflight"))
        try:
            yield checkpoint
        finally:
            checkpoint.save()


def accepted_run(model_id, execute, certify, source, *, checkpoint=None, key="run"):
    """Reuse only a hash-verified, certified archive belonging to this operation."""
    from ..runtime import ParamIssue, RunResult
    from ..run_store import get_store
    progress = None
    if checkpoint:
        saved = checkpoint.recover(key)
        if saved:
            if saved["model_id"] != model_id:
                raise ValueError("已保存运行的模型与当前构建不一致")
            return RunResult(model_id=model_id, observations=saved["observations"], manifest=saved["manifest"],
                             state_frames=saved["state_frames"], events=saved["events"], checkpoint=saved["checkpoint"],
                             issues=[ParamIssue(**issue) for issue in saved["manifest"].get("param_issues", [])])
        checkpoint.start_run(key)
        from ..run_progress import RunProgress
        progress = RunProgress(checkpoint.path.parent / checkpoint.record["operation_id"] / digest(key), checkpoint.deadline)
    try:
        rr = execute(progress)
    except Exception as exc:
        from ..run_progress import RunPaused
        if not isinstance(exc, RunPaused):
            raise
        from .design_checkpoint import PendingStage
        checkpoint.record.update(pause_reason="solver_checkpoint", solver_progress={
            "key": key, "saved_step": progress.record["state"]["n_iter"],
            "saved_time": progress.record["state"]["current_checkpoint"]["t"]})
        checkpoint.save()
        raise PendingStage(str(exc)) from exc
    if not rr.observations:
        raise ValueError(f"{model_id} 运行无观测")
    if certify:
        certify(rr)
    if checkpoint:
        checkpoint.bind_run(key, rr)
    get_store().save_run(rr, source, request_text=checkpoint.record["identity"]["request"] if checkpoint else "")
    if checkpoint:
        checkpoint.committed(key)
    return rr


def attach_authoring_audit(rr, calls):
    """This run's actual authoring calls belong to its archive, not a cached model class."""
    from copy import deepcopy
    combined = [*(calls or []), *rr.manifest.get("llm_calls", [])]
    by_id = {row["call_id"]: deepcopy(row) for row in combined}
    rr.manifest["llm_calls"] = list(by_id.values())
    rr.manifest.setdefault("clocks", {})["llm_wall_seconds"] = sum(row.get("duration_s", 0) for row in by_id.values())
