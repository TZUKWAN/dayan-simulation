"""Small cross-process JSON locks; no shared temporary filename or lost updates."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import threading
import time
import uuid

_THREAD_LOCK = threading.RLock()


@contextmanager
def file_lock(path, timeout=10):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as f:
        if not f.tell():
            f.write(b"0"); f.flush()
        end = time.monotonic() + timeout
        while True:
            try:
                f.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= end:
                    raise TimeoutError("任务正在执行或账本忙，请稍后重试")
                time.sleep(.03)
        try:
            yield
        finally:
            f.seek(0)
            if os.name == "nt":
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    try:
        deadline=time.monotonic()+1.5
        while True:
            try:os.replace(tmp,path);break
            except PermissionError:
                # Windows readers/antivirus can briefly hold a sharing handle.
                if time.monotonic()>=deadline:raise
                time.sleep(.015)
    finally:
        tmp.unlink(missing_ok=True)


def read_json(path):
    deadline=time.monotonic()+1.5
    while True:
        try:return json.loads(Path(path).read_text(encoding='utf-8'))
        except PermissionError:
            if time.monotonic()>=deadline:raise
            time.sleep(.015)
