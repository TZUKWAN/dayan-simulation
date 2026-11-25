"""采集任务引擎：分页预算、原始快照、完整性核验、取消/续采、任务账本。

每个任务：
  data/collections/<collection_id>/
    manifest.json    请求、来源、分页、覆盖、哈希、状态、partial、时间
    originals/       每页原始响应（不可变，页序号+哈希）
    records.jsonl    归一化记录（逐行 JSON，含页来源）
状态：running / done / partial / cancelled / failed；重启后按 manifest 续采。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from . import connectors, registry

ROOT = Path(__file__).resolve().parents[2]   # dayan/collection/ → 工程根
BASE = Path(os.environ.get("DAYAN_DATA_DIR", ROOT / "data")) / "collections"
TASKS_PATH = BASE / "tasks.json"
PAGE_CAP = 16 * 1024 * 1024
DEFAULT_PAGE_BUDGET = 3          # 单任务默认最多取 3 页（防全站爬取）
MD_OK = re.compile(r"[0-9a-zA-Z_\-]{3,64}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dir(collection_id: str) -> Path:
    if not MD_OK.fullmatch(collection_id):
        raise ValueError("非法 collection_id")
    return BASE / collection_id


def load_tasks() -> dict:
    if TASKS_PATH.exists():
        return json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    return {"version": 1, "tasks": {}}


def _save_tasks(tasks: dict) -> None:
    TASKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = TASKS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, TASKS_PATH)


def get_task(collection_id: str) -> dict | None:
    path = _dir(collection_id) / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else load_tasks()["tasks"].get(collection_id)


def list_tasks() -> list[dict]:
    tasks = load_tasks()["tasks"]
    return sorted(tasks.values(), key=lambda t: t.get("started_at", ""), reverse=True)


def _persist(task):
    from .storage import file_lock, atomic_json
    atomic_json(_dir(task["collection_id"]) / "manifest.json", task)
    with file_lock(BASE / ".ledger.lock"):
        tasks = load_tasks()
        tasks["tasks"][task["collection_id"]] = task
        atomic_json(TASKS_PATH, tasks)


def run_collection(connector_id: str, params: dict, *, name="", theme="", purpose="research",
                   page_budget=None, collection_id=None, allow_new_id=False) -> dict:
    """One bounded attempt; explicit ID resumes a partial snapshot, new ID refreshes it.

    Accepted raw pages are immutable. Cancellation is checked before and after each bounded
    network request. A currently blocking request finishes/times out before cancellation settles.
    """
    import uuid
    from .storage import file_lock
    from .evidence import artifact_role
    fn = connectors.CONNECTORS.get(connector_id)
    if fn is None:
        raise ValueError(f"未知连接器 {connector_id}")
    params = dict(params)
    if any(str(k).startswith("_") for k in params):
        raise ValueError("连接器内部游标不能由请求指定")
    source_id = connectors.CONNECTOR_SOURCE.get(connector_id) or params.get("source_id")
    if not source_id and params.get("instance"):
        source_id = {"data.humdata.org": "hdx", "data.gov.uk": "ckan_uk"}.get(
            str(params["instance"]).removeprefix("https://").rstrip("/"))
    if not source_id or registry.get(source_id) is None:
        raise ValueError("需要有效source_id：请使用search_sources返回的来源编号；公开文件URL可直接用collect_data(url=地址, format=实际格式)")
    budget = int(page_budget if page_budget is not None else DEFAULT_PAGE_BUDGET)
    if not 1 <= budget <= 50:
        raise ValueError("page_budget须为1..50（每次新增页预算）")
    cid = collection_id or ("C" + time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8])
    d = _dir(cid)
    (d / "originals").mkdir(parents=True, exist_ok=True)
    with file_lock(d / ".run.lock", timeout=.1):
        task = get_task(cid)
        if collection_id and task is None and not allow_new_id:
            raise ValueError("续采collection_id不存在；请不带ID新建任务，不能把拼错的ID当续采")
        if task and (task["connector"] != connector_id or task["params"] != params):
            raise ValueError("续采ID的连接器/参数必须与原任务一致；更新查询请建立新快照")
        if task and task["status"] == "done":
            return {**task, "reused": True}
        if task and task.get("pages") and not task.get("cursor"):
            raise ValueError("旧任务无可靠续采游标；请建立新快照，旧证据保留")
        task = task or {"version": 2, "collection_id": cid, "connector": connector_id,
            "source_id": source_id, "params": params, "name": name or connector_id,
            "theme": theme, "purpose": purpose, "started_at": _now(),
            "pages": [], "n_records": 0, "source_total": None, "cursor": None}
        task.update(status="running", partial=False, error=None, page_budget=budget,
                    resumed_at=_now() if task["pages"] else None, attempt_at=_now())
        (d / "cancel.requested").unlink(missing_ok=True)
        _persist(task)
        try:
            iterator = iter(fn({**params, "_cursor": task.get("cursor")}, budget))
            for _ in range(budget):
                if (d / "cancel.requested").exists():
                    task["status"] = "cancelled"; break
                try:
                    page = next(iterator)
                except StopIteration:
                    if not task["pages"]:
                        raise ValueError("连接器未返回任何页，不能认定成功")
                    break
                if (d / "cancel.requested").exists():
                    task["status"] = "cancelled"; break
                if len(page.raw) > PAGE_CAP:
                    raise ValueError("原始页超过大小上限")
                idx = len(task["pages"]) + 1
                sha = hashlib.sha256(page.raw).hexdigest()
                raw_path = d / "originals" / f"page_{idx:03d}_{sha[:12]}.raw"
                if raw_path.exists() and hashlib.sha256(raw_path.read_bytes()).hexdigest() != sha:
                    raise ValueError("原始快照哈希冲突")
                if not raw_path.exists():
                    raw_path.write_bytes(page.raw)
                rec_path = d / "originals" / f"records_{idx:03d}_{sha[:12]}.jsonl"
                rec_text = "".join(json.dumps({**r, "_page": idx, "_sha256": sha},
                    ensure_ascii=False, allow_nan=False) + "\n" for r in page.records)
                if not rec_path.exists():
                    rec_path.write_bytes(rec_text.encode("utf-8"))
                elif rec_path.read_text(encoding="utf-8") != rec_text:
                    raise ValueError("同一原始页归一化结果改变，需新建快照")
                role = artifact_role(connector_id, page.records, page.meta)
                task["pages"].append({"idx": idx, "url": page.url,
                    "raw": str(raw_path.relative_to(BASE)), "records_file": str(rec_path.relative_to(BASE)),
                    "sha256": sha, "records_sha256": hashlib.sha256(rec_text.encode("utf-8")).hexdigest(),
                    "bytes": len(page.raw), "n_records": len(page.records),
                    "meta": page.meta, "notes": page.notes, "artifact_role": role})
                task["artifact_role"] = role
                task["n_records"] += len(page.records)
                task["source_total"] = page.meta.get("total", task.get("source_total"))
                task["cursor"] = page.meta.get("cursor")
                task["has_more"] = page.meta.get("has_more")
                if task["has_more"] is None:
                    total = task.get("source_total")
                    task["has_more"] = total is None or task["n_records"] < int(total)
                # Rebuild only from accepted page files: no append duplication after interrupted writes.
                temp = d / "records.new"
                with temp.open("wb") as out:
                    for accepted in task["pages"]:
                        out.write((BASE / accepted["records_file"]).read_bytes())
                os.replace(temp, d / "records.jsonl")
                _persist(task)
                if not task["has_more"]:
                    break
            if task["status"] != "cancelled":
                task["partial"] = bool(task.get("has_more"))
                task["status"] = "partial" if task["partial"] else "done"
                if task["partial"]:
                    task["incomplete_reason"] = "新增页预算用尽；以同collection_id续采，不会从第一页重算"
                else:
                    task.pop('incomplete_reason',None)
                    if not task["n_records"]:
                        task["status"] = "empty"
        except Exception as exc:
            task["status"] = "failed"
            task["error"] = f"{type(exc).__name__}: {exc}"
        task["partial"] = task["status"] != "done"
        task["finished_at"] = _now()
        _persist(task)
        if connector_id == "resource_file":
            task["source_relationship"] = "caller_declared_not_source_verified; actual URL retained in pages"
            _persist(task)
        elif task["status"] in ("done", "partial") and task["n_records"] > 0:
            role = task["artifact_role"]
            registry.set_state(source_id, "catalog_only" if role == "catalog_only" else "live",
                probe_summary=f"{role}: {task['n_records']}条；完整性{task['status']}",
                evidence={"collection_id": cid, "n_records": task["n_records"],
                    "artifact_role": role, "complete": task["status"] == "done", "mode": connector_id,
                    "at": _now(), "sha256_first": task["pages"][0]["sha256"]})
        elif task["status"] == "failed":
            registry.set_state(source_id, "down", failure=task["error"])
        return task


def fetch_url_as_collection(url: str, *, name: str, source_id: str,
                            format="json", theme="", purpose="research") -> dict:
    return run_collection("resource_file", {"url": url, "format": format, "source_id": source_id},
                          name=name, theme=theme, purpose=purpose, page_budget=1)


def io_open(raw: bytes):
    import io as _io
    return _io.StringIO(raw.decode("utf-8-sig"))


def cancel(collection_id: str) -> dict:
    task = get_task(collection_id)
    if not task:
        raise ValueError("采集任务不存在")
    if task["status"] == "running":
        (_dir(collection_id) / "cancel.requested").write_text(_now(), encoding="utf-8")
        return {**task, "cancel_requested": True}
    return task


def records_preview(collection_id: str, limit: int = 10) -> list[dict]:
    path = _dir(collection_id) / "records.jsonl"
    out = []
    if path.exists():
        with path.open(encoding="utf-8") as f:
            for line in f:
                out.append(json.loads(line))
                if len(out) >= limit:
                    break
    return out
