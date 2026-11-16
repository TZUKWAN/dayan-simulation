"""Session-scoped DSH receipts let the workbench follow the actual native conversation."""
import json
import os
from pathlib import Path
import re
import time
from ..collection.storage import file_lock


def _file(session_id):
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,120}", session_id):
        raise ValueError("DSH工具必须提供实际session_id，不能把结果发给不相关会话")
    root = Path(os.environ.get("DAYAN_DATA_DIR", Path(__file__).resolve().parents[2]/"data"))
    return root / "integrations" / "dsh" / (session_id + ".jsonl")


def append_event(session_id, tool, result):
    path = _file(session_id)
    payload = result.get("payload") or result
    if not isinstance(payload, dict): payload = {}
    with file_lock(path.with_suffix(".lock")):
        seq = len(path.read_text(encoding="utf-8").splitlines())+1 if path.exists() else 1
        event = {"seq": seq, "session_id": session_id, "at": time.time(), "tool": tool,
            "ok": result.get("ok", False), "validation_pass": result.get("validation_pass"),
            "error": result.get("error"), **{k:payload[k] for k in
                ("run_id","experiment_id","analysis_id","study_id","collection_id","dataset_id","workbench_url","file","bundle_url","n_records","artifact_role","status","source_id") if k in payload}}
        with path.open("a", encoding="utf-8") as f: f.write(json.dumps(event, ensure_ascii=False)+"\n")
    return event


def events(session_id, after=0):
    path = _file(session_id)
    if not path.exists(): return []
    return [r for line in path.read_text(encoding="utf-8").splitlines()
            if line and (r := json.loads(line))["seq"] > after][-100:]
