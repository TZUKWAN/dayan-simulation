"""Durable numerical progress: verified JSON chunks, full state and original endpoint."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

from .collection.storage import atomic_json, read_json
from .limits import BudgetExceeded, limits


class RunPaused(Exception):
    """A real solver checkpoint was committed; the original run is unfinished."""


def _digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


class RunProgress:
    def __init__(self, directory, deadline):
        self.directory = Path(directory)
        self.path = self.directory / "progress.json"
        self.pending_path = self.directory / "pending.json"
        self.deadline = deadline
        self.last_save = 0.0
        self.record = None
        self.identity = None
        # Managed workers have a process-wide CPU allowance. Library calls can
        # occur in a long-lived process, so their allowance starts at this call.
        self.cpu_start = 0.0 if os.environ.get("DAYAN_TASK_DIR") else time.process_time()

    def _path(self, name):
        if not isinstance(name, str) or not re.fullmatch(r"(?:rows|frame)-[a-f0-9]{32}\.json", name):
            raise ValueError("计算检查点包含非法块路径")
        path = self.directory / name
        if path.resolve().parent != self.directory.resolve():
            raise ValueError("计算检查点块超出本任务目录")
        return path

    def _read(self, ref):
        raw = self._path(ref["name"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
            raise ValueError("计算检查点块校验失败：" + ref["name"])
        return json.loads(raw)

    def _write(self, name, value):
        path = self._path(name)
        atomic_json(path, value)
        raw = path.read_bytes()
        return {"name": path.name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}

    def _cleanup_pending(self, committed):
        if not self.pending_path.exists():
            return
        wrapper = read_json(self.pending_path)
        pending = wrapper["record"]
        if wrapper.get("sha256") != _digest(pending) or pending["identity"] != self.identity:
            raise ValueError("计算检查点写入账本校验失败；未清理任何文件")
        kept = {ref["name"] for ref in [*committed.get("rows", []), *committed.get("frames", [])]}
        # Validate every path first. Only exact names reserved by this write are
        # eligible; unrelated files in the task directory are never swept.
        paths = [self._path(name) for name in pending["names"]]
        for path in paths:
            if path.name not in kept:
                path.unlink(missing_ok=True)
        # atomic_json can be killed before replace/finally. Match only temporary
        # siblings of this journal's known block names and progress metadata.
        for base in [*paths, self.path, self.pending_path]:
            for candidate in self.directory.glob(base.name + ".*.tmp"):
                if (re.fullmatch(re.escape(base.name) + r"\.[a-f0-9]{32}\.tmp", candidate.name)
                        and candidate.resolve().parent == self.directory.resolve() and candidate.is_file()):
                    candidate.unlink()
        self.pending_path.unlink()

    def load(self, identity):
        self.identity = deepcopy(identity)
        if not self.path.exists():
            self._cleanup_pending({})
            return None
        wrapper = read_json(self.path)
        record = wrapper["record"]
        if wrapper.get("sha256") != _digest(record):
            raise ValueError("计算检查点元数据校验失败")
        if record["identity"] != identity:
            raise ValueError("计算检查点的模型、数据、运行设置或执行版本已变化")
        rows, times, frames = [], [], []
        for ref in record["rows"]:
            chunk = self._read(ref)
            if chunk["start"] != len(rows) or len(chunk["rows"]) != len(chunk["times"]):
                raise ValueError("计算检查点观测序列不连续")
            rows.extend(chunk["rows"])
            times.extend(chunk["times"])
        if len(rows) != record["row_count"]:
            raise ValueError("计算检查点观测数量不一致")
        for ref in record["frames"]:
            frames.append(self._read(ref))
        self._cleanup_pending(record)
        self.record = record
        self.last_save = time.monotonic()
        return {**deepcopy(record["state"]), "observations": rows, "times": times,
                "state_frames": frames, "frame_steps": [ref["step"] for ref in record["frames"]]}

    def should_pause(self):
        # Worker CPU budget covers imports and prior stages too. Reserve time to
        # serialize the checkpoint before the supervisor has to terminate it.
        return (time.monotonic() >= self.deadline - 20
                or time.process_time() - self.cpu_start >= max(1, limits().cpu_seconds - 15))

    def due(self):
        return self.should_pause() or time.monotonic() - self.last_save >= 5

    def save(self, state, rows, times, frames, frame_steps, *, finished=False):
        if self.identity is None:
            raise ValueError("计算检查点尚未绑定实际运行设置")
        prior = self.record or {"rows": [], "frames": [], "row_count": 0}
        if len(rows) != len(times) or len(rows) < prior["row_count"] or len(frames) != len(frame_steps):
            raise ValueError("计算检查点观测或状态序列不一致")
        if len(set(frame_steps)) != len(frame_steps) or sorted(frame_steps) != frame_steps:
            raise ValueError("计算检查点状态帧序号必须唯一且递增")
        old_frames = {ref["step"]: ref for ref in prior["frames"]}
        row_name = "rows-" + uuid.uuid4().hex + ".json" if len(rows) > prior["row_count"] else None
        new_names = {step: "frame-" + uuid.uuid4().hex + ".json" for step in frame_steps if step not in old_frames}
        pending = {"identity": self.identity, "names": [*([row_name] if row_name else []), *new_names.values(),
                    *(ref["name"] for step, ref in old_frames.items() if step not in frame_steps)]}
        # Commit ownership before creating blocks, so termination at any later
        # point leaves enough evidence to remove only uncommitted/retired files.
        atomic_json(self.pending_path, {"record": pending, "sha256": _digest(pending)})
        committed = prior
        try:
            refs = deepcopy(prior["rows"])
            if row_name:
                refs.append(self._write(row_name, {"start": prior["row_count"], "rows": rows[prior["row_count"]:],
                                                  "times": times[prior["row_count"]:]}))
            frame_refs = [{**old_frames[step]} if step in old_frames else {"step": step, **self._write(new_names[step], frame)}
                          for step, frame in zip(frame_steps, frames)]
            record = {"identity": self.identity, "state": state, "rows": refs, "frames": frame_refs,
                      "row_count": len(rows), "finished": finished}
            size = sum(ref["bytes"] for ref in [*refs, *frame_refs]) + len(json.dumps(state, ensure_ascii=False).encode())
            if size > 2 * limits().run_bytes:
                raise BudgetExceeded("完整计算检查点超过恢复存储预算，未减少主体或舍弃原文要求的帧")
            atomic_json(self.path, {"record": record, "sha256": _digest(record)})
            committed = record
            self.record = deepcopy(record)
            self.last_save = time.monotonic()
        finally:
            self._cleanup_pending(committed)
        if not finished and self.should_pause():
            raise RunPaused(f"计算已保存到模型时刻 {state['current_checkpoint']['t']}，须继续原运行至既定终点")
