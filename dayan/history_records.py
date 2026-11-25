"""Editable titles and visibility for read-only simulation and research archives."""
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
from itertools import chain
import json
from pathlib import Path
import re
import threading

from .collection.storage import atomic_json, file_lock, read_json

TITLE_LIMIT = 80
_AUTO_LIMIT = 44
_PREFERENCES = "history_preferences.json"
_LOCK = threading.Lock()
_UNSET = object()
_LEGACY_ID = re.compile(r"LG-[0-9a-f]{24}")
_ANALYSIS_NAMES = {"compare": "模型对比", "sweep": "参数扫描", "ensemble": "多种子运行", "compose": "模型组合"}
_GENERIC = {"运行", "仿真", "实际运行", "模型资源运行", "模型运行", "仿真运行", "仿真测试",
            "工作台运行", "手动/前端运行", "api运行", "run", "experiment", *_ANALYSIS_NAMES}
_FIELDS = ("run_id", "kind", "model_id", "intent", "request_text", "source", "tool", "created_at",
           "complete", "n_observations", "status", "legacy_run_id")


def preferences(store):
    try:
        return read_json(store.directory / _PREFERENCES)
    except FileNotFoundError:
        return {}


def _time(value, *, local=False):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if local or parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@lru_cache(maxsize=1)
def _model_names():
    path = Path(__file__).resolve().parents[1] / "data" / "dayan_catalog.json"
    return {row["model_id"]: row.get("name") for row in read_json(path)["models"]}


@lru_cache(maxsize=512)
def _run_details(path):
    try:
        manifest = read_json(path)
    except (OSError, ValueError):
        return "", None
    definition = manifest.get("model_definition") or {}
    scenario = definition.get("scenario") or {}
    method = manifest.get("model_method") or {}
    name = scenario.get("title") or definition.get("name") or method.get("name") or ""
    return name, (manifest.get("rng") or {}).get("seed")


def _subject(value):
    if not isinstance(value, str):
        return ""
    text = " ".join(re.split(r"[。！？!?\n\r]", value.strip(), maxsplit=1)[0].split()).strip()
    return text if text.casefold() not in _GENERIC else ""


def presentation(store, entry, saved):
    kind = entry["kind"]
    model_id = entry.get("model_id")
    model_name = _model_names().get(model_id) or model_id or "仿真"
    subject = _subject(entry.get("request_text")) or _subject(entry.get("intent"))
    qualifier = ""
    if kind == "run":
        stored, seed = _run_details(store._path(entry["run_id"]) / "manifest.json")
        source = entry.get("source")
        if source == "resume":
            automatic = _subject(stored) or _subject(entry.get("request_text")) or model_name
            qualifier = " · 续算"
        elif source == "experiment_run":
            automatic = subject or _subject(stored) or model_name
        else:
            automatic = _subject(stored) or subject or model_name
        if source in ("experiment_run", "ensemble") and isinstance(seed, int):
            qualifier = f" · 种子 {seed}"
    elif kind == "experiment":
        automatic = subject or f"{model_name} · 对照实验"
    elif kind == "analysis":
        automatic = subject or f"{model_name} · {_ANALYSIS_NAMES.get(entry.get('tool') or entry.get('source'), '组合分析')}"
    elif kind == "study":
        automatic = subject or "验证研究"
    else:
        automatic = subject or model_name
    limit = _AUTO_LIMIT - len(qualifier)
    if len(automatic) > limit:
        automatic = automatic[:limit-1].rstrip() + "…"
    automatic += qualifier
    custom = saved.get("title")
    return {"title": custom or automatic, "automatic_title": automatic, "title_is_custom": bool(custom)}


def legacy_records(store, path):
    """Stable IDs for journal-only records, with mirror rows folded into their run."""
    if path is None or not path.is_file():
        return
    with path.open(encoding="utf-8-sig") as stream:
        for index, line in enumerate(stream):
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            created = _time(record.get("created_at") or record.get("ts"), local=True)
            if created is None:
                continue
            original = record.get("run_id")
            try:
                if original and (store._path(original) / "metadata.json").is_file():
                    continue
            except ValueError:
                pass
            digest = hashlib.sha256(f"{index}:{line.rstrip()}".encode("utf-8")).hexdigest()
            entry = {**record, "run_id": "LG-" + digest[:24], "kind": "legacy", "complete": False,
                     "legacy_run_id": original, "created_at": created.isoformat()}
            yield entry, record


def _archives(store):
    for path in store.directory.glob("*/metadata.json"):
        if not path.parent.name.startswith(".pending-"):
            yield read_json(path)


def _studies():
    from .research.studies import list_studies

    for study in list_studies():
        yield {"run_id": study["study_id"], "kind": "study", "model_id": study.get("model_id"),
               "created_at": study.get("created_at"), "request_text": study.get("question"),
               "status": (study.get("calibration") or {}).get("status") or study.get("phase")}


def cutoff(store):
    path = store.directory / "history_cutoff.json"
    return _time(read_json(path)) if path.is_file() else None


def metadata_page(store, limit, *, offset, search, before, after, workbench, legacy_path):
    saved = preferences(store)
    since = cutoff(store)
    archive = _archives(store)
    if workbench:
        archive = chain(archive, _studies(), (entry for entry, _ in legacy_records(store, legacy_path)))
    rows = []
    query = search.casefold()
    for entry in archive:
        state = saved.get(entry["run_id"], {})
        if state.get("deleted"):
            continue
        timestamp = _time(entry.get("created_at"))
        if entry["kind"] != "study" and since and (timestamp is None or timestamp <= since):
            continue
        if before and (timestamp is None or timestamp >= before):
            continue
        if after and (timestamp is None or timestamp < after):
            continue
        row = {key: entry[key] for key in _FIELDS if key in entry}
        row.update(presentation(store, entry, state))
        if query and not any(query in str(row.get(key) or "").casefold()
                             for key in ("title", "automatic_title", "request_text", "intent", "model_id", "run_id", "legacy_run_id")):
            continue
        rows.append((timestamp or datetime.min.replace(tzinfo=timezone.utc), row["run_id"], row))
    offset, limit = max(0, offset), max(0, min(int(limit), 60))
    rows.sort(key=lambda item: item[:2], reverse=True)
    return [row for _, _, row in rows[offset:offset+limit]]


def load_legacy(store, path, record_id):
    if not _LEGACY_ID.fullmatch(record_id):
        raise ValueError("非法旧记录标识")
    for entry, original in legacy_records(store, path):
        if entry["run_id"] == record_id:
            return entry, original
    raise KeyError("历史记录不存在")


def _entry(store, legacy_path, record_id):
    if record_id.startswith("LG-"):
        return load_legacy(store, legacy_path, record_id)[0]
    if record_id.startswith("ST-"):
        from .research.studies import directory

        path = directory(record_id) / "study.json"
        if not path.is_file():
            raise KeyError("历史记录不存在")
        try:
            study = read_json(path)
        except ValueError:
            study = {}
        return {"run_id": record_id, "kind": "study", "request_text": study.get("question"),
                "model_id": study.get("model_id")}
    path = store._path(record_id) / "metadata.json"
    if not path.is_file():
        raise KeyError("历史记录不存在")
    return read_json(path)


def change(store, legacy_path, record_id, *, title=_UNSET, deleted=None):
    if title is not _UNSET and title is not None:
        title = title.strip()
        if not 1 <= len(title) <= TITLE_LIMIT:
            raise ValueError(f"名称须包含 1 至 {TITLE_LIMIT} 个字符")
        if any(ord(char) < 32 or 0x7f <= ord(char) < 0xa0 or 0xd800 <= ord(char) <= 0xdfff for char in title):
            raise ValueError("名称须为单行可显示文字")
    entry = _entry(store, legacy_path, record_id)
    path = store.directory / _PREFERENCES
    with _LOCK, file_lock(path.with_suffix(".lock")):
        saved = preferences(store)
        state = saved.get(record_id, {})
        if title is not _UNSET:
            if title is None:
                state.pop("title", None)
            else:
                state["title"] = title
        if deleted is not None:
            if deleted:
                state["deleted"] = True
            else:
                state.pop("deleted", None)
        if state:
            saved[record_id] = state
        else:
            saved.pop(record_id, None)
        atomic_json(path, saved)
    return {"run_id": record_id, **presentation(store, entry, state), "deleted": state.get("deleted", False)}
