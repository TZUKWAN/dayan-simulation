"""Trusted container PID 1. User model code is never imported at watchdog privileges."""
import json
import importlib.metadata
import os
import platform
import resource
import subprocess
import sys
import threading
import time


def main():
    wall = float(os.environ["DAYAN_SOLVER_WALL"])
    output_limit = int(os.environ["DAYAN_SOLVER_OUTPUT"])
    input_limit = int(os.environ["DAYAN_SOLVER_INPUT"])
    deadline = time.monotonic() + wall
    # Reading from a lost host pipe yields EOF; a stuck host is bounded too.
    request = bytearray()
    read_error = []

    def read_input():
        request.extend(sys.stdin.buffer.read(input_limit + 1))
        if len(request) > input_limit:
            read_error.append("输入超过已声明预算")

    reader = threading.Thread(target=read_input, daemon=True)
    reader.start()
    reader.join(max(0, deadline - time.monotonic()))
    if reader.is_alive() or read_error or not request:
        return {"ok": False, "error": {"kind": "input", "message": "输入为空、超量或未在期限内提交"}}

    def drop_privileges():
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024 * 1024, 32 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
        resource.setrlimit(resource.RLIMIT_CPU, (max(1, int(wall)), max(1, int(wall)) + 1))
        os.setgroups([])
        os.setgid(65532)
        os.setuid(65532)

    # Only this trusted watchdog retains SETUID/SETGID/KILL; the worker has no
    # capabilities and cannot stop its root watchdog with kill or SIGSTOP.
    child = subprocess.Popen([sys.executable, "-I", "-u", "/opt/dayan/worker.py"], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=drop_privileges,
                             start_new_session=True, env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp",
                             "LANG": "C.UTF-8", "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"})
    buffers = {"out": bytearray(), "err": bytearray()}
    exceeded = threading.Event()

    def collect(stream, key, limit):
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            buffer = buffers[key]
            room = max(0, limit - len(buffer))
            buffer.extend(chunk[:room])
            if len(chunk) > room:
                exceeded.set()

    def submit():
        try:
            child.stdin.write(request)
            child.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    threads = [threading.Thread(target=collect, args=(child.stdout, "out", output_limit), daemon=True),
               threading.Thread(target=collect, args=(child.stderr, "err", 65536), daemon=True),
               threading.Thread(target=submit, daemon=True)]
    for thread in threads:
        thread.start()
    reason = None
    while child.poll() is None:
        if exceeded.is_set() or time.monotonic() >= deadline:
            reason = "output_limit" if exceeded.is_set() else "timeout"
            child.kill()
            break
        time.sleep(.01)
    child.wait()
    usage=resource.getrusage(resource.RUSAGE_CHILDREN)
    for thread in threads:
        thread.join(.5)
    log = buffers["err"].decode("utf-8", errors="replace")
    if exceeded.is_set():
        reason = "output_limit"
    if reason or child.returncode:
        return {"ok": False, "error": {"kind": reason or "model_error", "exit_code": child.returncode,
                "message": "隔离求解器未成功完成本段计算", "detail": log[-12000:]}}
    try:
        result = json.loads(buffers["out"])
    except (ValueError, UnicodeError) as exc:
        return {"ok": False, "error": {"kind": "protocol", "message": str(exc), "detail": log[-12000:]}}
    # These facts come from the trusted supervisor, not generated model output.
    environment = {"python":platform.python_version(), "system":platform.system(),
                   "machine":platform.machine(),
                   "packages":{name:importlib.metadata.version(name) for name in ('numpy','scipy','networkx')}}
    return {"ok": True, "result": result, "logs": log, "environment":environment,
            "resource_usage":{"cpu_seconds":usage.ru_utime+usage.ru_stime,
                              "peak_worker_rss_bytes":int(usage.ru_maxrss)*1024,
                              "source":"trusted Linux watchdog getrusage(RUSAGE_CHILDREN); KiB converted to bytes"}}


if __name__ == "__main__":
    try:
        result = main()
    except BaseException as exc:
        result = {"ok": False, "error": {"kind": "supervisor", "message": f"{type(exc).__name__}: {exc}"}}
    sys.stdout.write(json.dumps(result, ensure_ascii=False, allow_nan=False))
    sys.stdout.flush()
    # As PID 1 exits, the container also stops any orphan worker descendants.
    os._exit(0 if result["ok"] else 1)
