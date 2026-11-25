"""No host exec/import of generated code: bounded Linux container segments only."""
from dataclasses import dataclass
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid

import psutil

from ..access import data_root
from ..collection.storage import atomic_json
from ..limits import limits
from .codec import decode, digest, dumps, encode

PROTOCOL = "dayan-solver-segment-v1"
DEFAULT_IMAGE = "dayan-solver:local-v1"
BUNDLE_FILES = ("Dockerfile", "requirements.lock", "codec.py", "worker.py", "supervisor.py", "decisions.py", ".dockerignore")


class SolverError(ValueError):
    def __init__(self, kind, message, receipt=None):
        super().__init__(message)
        self.kind, self.receipt = kind, receipt


@dataclass(frozen=True)
class SandboxBudget:
    wall_seconds: float = 120
    memory_bytes: int = 512 * 1024 * 1024
    output_bytes: int = 64 * 1024 * 1024
    cpus: float = 1.0
    pids: int = 64
    tmp_bytes: int = 64 * 1024 * 1024

    def validate(self):
        cap = limits()
        if (type(self.wall_seconds) not in (int, float) or not math.isfinite(self.wall_seconds)
                or not 1 <= self.wall_seconds <= cap.wall_seconds):
            raise ValueError("隔离求解器时间预算不合法")
        if type(self.memory_bytes) is not int or not 64 * 1024 * 1024 <= self.memory_bytes <= cap.memory_bytes:
            raise ValueError("隔离求解器内存预算不合法")
        if type(self.output_bytes) is not int or not 1024 <= self.output_bytes <= cap.job_bytes:
            raise ValueError("隔离求解器输出预算不合法")
        if (type(self.cpus) not in (int, float) or not math.isfinite(self.cpus) or not 0 < self.cpus <= max(1, os.cpu_count() or 1)
                or type(self.pids) is not int or not 16 <= self.pids <= 256
                or type(self.tmp_bytes) is not int or not 1024 <= self.tmp_bytes <= self.memory_bytes // 2):
            raise ValueError("隔离求解器CPU、PID或临时存储预算不合法")


def bundle_fingerprint():
    root = Path(__file__).resolve().parent
    return digest({name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in BUNDLE_FILES})


def _docker(args, timeout=20):
    try:
        return subprocess.run(["docker", *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SolverError("unavailable", "隔离求解环境不可用：" + str(exc)) from exc


def image_contract(image=None):
    image = image or os.environ.get("DAYAN_SOLVER_IMAGE", DEFAULT_IMAGE)
    if not isinstance(image, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,250}", image):
        raise ValueError("隔离求解器镜像标识不合法")
    result = _docker(["image", "inspect", image])
    if result.returncode:
        raise SolverError("unavailable", "未找到已构建的DAYAN求解镜像；先运行scripts/build_solver_image.py。" + result.stderr[-1000:])
    config = json.loads(result.stdout)[0]
    labels = config.get("Config", {}).get("Labels") or {}
    if (config.get("Os") != "linux" or config.get("Architecture") != "amd64"
            or labels.get("org.dayan.solver.protocol") != PROTOCOL
            or labels.get("org.dayan.solver.bundle") != bundle_fingerprint()
            or not re.fullmatch(r"sha256:[a-f0-9]{64}", config.get("Id", ""))):
        raise SolverError("image_mismatch", "隔离镜像与当前受管执行协议或受信任执行文件不一致，须重新构建")
    return {"image_id": config["Id"], "bundle_sha256": labels["org.dayan.solver.bundle"], "protocol": PROTOCOL}


def _remove_owned(name, token):
    inspected = _docker(["container", "inspect", name])
    if inspected.returncode:
        # --rm already removed a completed container. A daemon failure is not
        # silently treated as successful cleanup.
        if "no such" in inspected.stderr.lower():
            return
        raise SolverError("cleanup", "无法核对本任务容器清理状态：" + inspected.stderr[-1000:])
    info = json.loads(inspected.stdout)[0]
    if (info.get("Config", {}).get("Labels") or {}).get("org.dayan.solver.job") != token:
        raise SolverError("cleanup", "容器归属不匹配，未操作该容器")
    result = _docker(["container", "rm", "--force", info["Id"]])
    if result.returncode and "no such" not in result.stderr.lower():
        raise SolverError("cleanup", "本任务容器清理失败：" + result.stderr[-1000:])


def reconcile_jobs():
    """Reconcile only jobs whose actual owner process died, never active peers."""
    from ..collection.storage import file_lock, read_json
    changed = []
    folder = data_root() / "solver_jobs"
    for path in folder.glob("*.json"):
        record = read_json(path)
        if record.get("status") != "running" or "owner_started_at" not in record:
            continue
        token = record.get("job_id", "")
        if (not re.fullmatch(r"[a-f0-9]{32}", token) or path.name != token + ".json"
                or record.get("container_name") != "dayan-solver-" + token):
            raise SolverError("cleanup", "任务恢复账本归属异常，未操作容器")
        try:
            if psutil.Process(record["owner_pid"]).create_time() == record["owner_started_at"]:
                continue
        except psutil.NoSuchProcess:
            pass
        with file_lock(path.with_suffix(".lock"), timeout=.1):
            _remove_owned(record["container_name"], token)
            record.update(status="interrupted", container_removed=True, recovered_at=time.time(),
                          error_kind="owner_terminated", error="原执行进程已退出；本段结果未接受，须从此前完整检查点继续")
            atomic_json(path, record)
            changed.append(token)
    return changed


def _exchange(command, raw, timeout, output_limit):
    child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    buffers = {"out": bytearray(), "err": bytearray()}
    exceeded = threading.Event()
    def collect(stream, key, maximum):
        while True:
            block = stream.read(65536)
            if not block:
                return
            room = max(0, maximum - len(buffers[key]))
            buffers[key].extend(block[:room])
            if len(block) > room:
                exceeded.set()
    def submit():
        try:
            child.stdin.write(raw)
            child.stdin.close()
        except (BrokenPipeError, OSError):
            pass
    threads = [threading.Thread(target=collect, args=(child.stdout, "out", output_limit), daemon=True),
               threading.Thread(target=collect, args=(child.stderr, "err", 65536), daemon=True),
               threading.Thread(target=submit, daemon=True)]
    for thread in threads:
        thread.start()
    end = time.monotonic() + timeout
    try:
        while child.poll() is None:
            if exceeded.is_set() or time.monotonic() >= end:
                raise SolverError("transport_limit", "隔离求解传输超时或输出超预算，未接受部分结果")
            time.sleep(.02)
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)
        for thread in threads:
            thread.join(.5)
    if exceeded.is_set():
        raise SolverError("transport_limit", "隔离求解输出超预算")
    return child.returncode, bytes(buffers["out"]), buffers["err"].decode("utf-8", errors="replace")


def validate_source(source):
    if not isinstance(source, str) or not source.strip() or len(source.encode("utf-8")) > limits().body_bytes // 2:
        raise ValueError("求解源码为空或超过传输预算")
    tree = ast.parse(source, filename="<reviewed-model>")
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    if not {"initialize", "advance", "observe", "frame", "validate"} <= functions:
        raise ValueError("求解源码缺少协议规定的五个顶层函数")
    return tree


def run_segment(source, *, parameters=None, inputs=None, ticks, dt, seed, segment_steps=16,
                checkpoint=None, budget=None, image=None, initial_checkpoint=False, interventions=None,
                capture_initial=False,decision_policy=None,decision_bundle=None):
    """Execute a real finite segment; result is unapproved until model validation."""
    validate_source(source)
    budget = budget or SandboxBudget()
    budget.validate()
    if parameters is not None and not isinstance(parameters, dict) or inputs is not None and not isinstance(inputs, dict):
        raise ValueError("模型parameters和inputs必须为对象，不能静默替换其他类型")
    if (type(ticks) is not int or not 0 <= ticks <= limits().ticks or type(seed) is not int or seed < 0
            or type(dt) not in (int, float) or not math.isfinite(dt) or dt <= 0
            or type(segment_steps) is not int or not 0 <= segment_steps <= limits().ticks):
        raise ValueError("隔离求解器的步数、步长或种子不合法")
    controls=[] if interventions is None else interventions
    if not isinstance(controls,list):raise ValueError('求解器干预须为明确列表')
    previous=-float('inf')
    for row in controls:
        if (not isinstance(row,dict) or not {'at_t','requested_t','params','label','order'}<=row.keys()
                or type(row['at_t']) not in (int,float) or not math.isfinite(row['at_t'])
                or not previous<=row['at_t']<=ticks*dt or row['at_t']<0
                or not isinstance(row['params'],dict) or not row['params']
                or set(row['params'])-set(parameters or {}) or any(type(v) not in (int,float) or not math.isfinite(v) for v in row['params'].values())):
            raise ValueError('求解器干预未预检或顺序/数值不合法')
        previous=row['at_t']
    request = {"protocol": PROTOCOL, "source": source, "parameters": encode(parameters or {}),
               "inputs": encode(inputs or {}), "ticks": ticks, "dt": dt, "seed": seed,
               "segment_steps": segment_steps, "checkpoint": checkpoint, "initial_checkpoint":bool(initial_checkpoint),
               'interventions':controls,'capture_initial':bool(capture_initial)}
    if decision_policy is not None:
        from ..decision_broker import validate_policy
        request['decision_policy']=validate_policy(decision_policy)
        request['decision_bundle']=decision_bundle
    raw = dumps(request).encode("utf-8")
    if len(raw) > limits().body_bytes:
        raise SolverError("input_limit", "完整源码、输入和检查点超出本段传输预算，未缩减需求")
    contract = image_contract(image)
    reconcile_jobs()
    token = uuid.uuid4().hex
    name = "dayan-solver-" + token
    path = data_root() / "solver_jobs" / (token + ".json")
    started = time.monotonic()
    isolation = {"network": "none", "readonly_root": True, "worker_uid": 65532, "worker_capabilities": [],
                 "watchdog_capabilities": ["SETUID", "SETGID", "KILL"], "no_new_privileges": True,
                 "seccomp": "docker-default", "host_mounts": [], "memory_bytes": budget.memory_bytes,
                 "wall_seconds": budget.wall_seconds, "cpus": budget.cpus, "pids": budget.pids,
                 "tmp_bytes": budget.tmp_bytes, "output_bytes": budget.output_bytes}
    receipt = {"job_id": token, "container_name": name, **contract, "status": "running", "isolation": isolation,
               "source_sha256": hashlib.sha256(source.encode()).hexdigest(), "input_sha256": digest(request),
               "owner_pid": os.getpid(), "owner_started_at": psutil.Process().create_time(), "created_at": time.time()}
    atomic_json(path, receipt)
    command = ["docker", "run", "--rm", "-i", "--pull=never", "--platform=linux/amd64", "--name", name,
               "--label", "org.dayan.solver.job=" + token, "--network=none", "--read-only", "--cap-drop=ALL",
               "--cap-add=SETUID", "--cap-add=SETGID", "--cap-add=KILL", "--security-opt=no-new-privileges:true",
               "--memory", str(budget.memory_bytes), "--memory-swap", str(budget.memory_bytes),
               "--cpus", str(budget.cpus), "--pids-limit", str(budget.pids),
               "--tmpfs", f"/tmp:rw,noexec,nosuid,nodev,size={budget.tmp_bytes},mode=1777",
               "--env", "DAYAN_SOLVER_WALL=" + str(budget.wall_seconds),
               "--env", "DAYAN_SOLVER_OUTPUT=" + str(budget.output_bytes),
               "--env", "DAYAN_SOLVER_INPUT=" + str(limits().body_bytes), contract["image_id"]]
    try:
        code, output, error_log = _exchange(command, raw, budget.wall_seconds + 30, 2 * budget.output_bytes + 131072)
        try:
            response = json.loads(output)
        except (ValueError, UnicodeError) as exc:
            raise SolverError("container_error", f"隔离容器未返回有效协议，exit={code}：{error_log[-2000:]}") from exc
        if not response.get("ok") or code:
            failure = response.get("error") or {"kind": "container_error", "message": f"exit={code}"}
            raise SolverError(failure["kind"], failure.get("message", "求解失败") + "\n" + failure.get("detail", ""))
        result = response["result"]
        _validate_result(request, result)
        receipt.update(status="executed", from_step=result["from_step"], to_step=result["to_step"],
                       complete=result["complete"], response_bytes=len(output), logs=response.get("logs", ""),
                       environment=response['environment'],resource_usage=response['resource_usage'],request_bytes=len(raw))
        return {**result, "receipt": receipt}
    except BaseException as exc:
        receipt.update(status="failed", error_kind=getattr(exc, "kind", type(exc).__name__), error=str(exc))
        if isinstance(exc, SolverError):
            exc.receipt = receipt
        raise
    finally:
        try:
            _remove_owned(name, token)
            receipt["container_removed"] = True
        except Exception as exc:
            receipt.update(status="cleanup_failed", cleanup_error=str(exc))
            raise
        finally:
            receipt["wall_seconds"] = time.monotonic() - started
            atomic_json(path, receipt)


def _validate_result(request, result):
    identity_fields={key: request[key] for key in ("protocol", "source", "parameters", "inputs", "seed", "dt", "ticks",'interventions')}
    if request.get('decision_policy') is not None:identity_fields['decision_policy']=request['decision_policy']
    identity = digest(identity_fields)
    prior = request.get("checkpoint")
    start = prior["step"] if prior else 0
    requested_end = min(request["ticks"], start + request["segment_steps"])
    end=requested_end
    if request.get('decision_policy') is not None:
        descriptor=result.get('next_decisions')
        actual_end=result.get('to_step')
        if type(actual_end)!=int or not start<=actual_end<=requested_end:
            raise SolverError('protocol','实际决策边界不在请求段内')
        if actual_end<requested_end:
            if actual_end<=start or not descriptor or not descriptor.get('requests'):
                raise SolverError('protocol','仅真实待决策边界可提前结束计算段')
        end=actual_end
        if descriptor is not None:
            from .decisions import validate_requests
            validate_requests(descriptor['requests'])
            body={key:descriptor[key] for key in ('step','time','requests','state_sha256','policy_sha256')}
            checkpoint=result['checkpoint']
            boundary=digest({'state':checkpoint['state'],'parameters':checkpoint['parameters'],'inputs':request['inputs'],'rng':checkpoint['rng']})
            if (descriptor['step']!=end or descriptor['time']!=end*request['dt'] or descriptor['key']!=digest(body)
                    or descriptor['policy_sha256']!=digest(request['decision_policy']) or descriptor['state_sha256']!=boundary):
                raise SolverError('protocol','实际待决策状态摘要/时钟不一致')
    rows = result["records"]
    expected = list(range(start + (1 if prior and not request.get('capture_initial') else 0), end + 1))
    checkpoint = result["checkpoint"]
    if (result["protocol"] != PROTOCOL or result["identity"] != identity or result["from_step"] != start
            or result["to_step"] != end or result["complete"] != (end == request["ticks"])
            or [row["step"] for row in rows] != expected or checkpoint["step"] != end
            or checkpoint["time"] != end * request["dt"] or checkpoint["identity"] != identity):
        raise SolverError("protocol", "求解器输出未覆盖请求的准确区间或检查点身份不一致")
    for row in rows:
        if row["time"] != row["step"] * request["dt"] or row["frame"]["sim_t"] != row["time"]:
            raise SolverError("protocol", "求解器帧/观测时钟不一致")
        decode(row["frame"])
        obs=row['observations']
        if (not isinstance(obs,dict) or not obs or any(not isinstance(key,str) or not key or key=='sim_t'
                or type(value) not in (int,float) or not math.isfinite(value) for key,value in obs.items())):
            raise SolverError('protocol','实际观测须为有限数值，时钟由平台保存')
        events=decode(row['events'])
        if not isinstance(events,list) or any(not isinstance(ev,dict) or type(ev.get('time')) not in (int,float)
                or not math.isfinite(ev['time']) or not isinstance(ev.get('type'),str) or not ev['type']
                or not (row['step']-1)*request['dt']-1e-12<=ev['time']<=row['time']+1e-12 for ev in events):
            raise SolverError('protocol','领域事件超出实际推进区间')
    decode(checkpoint["state"])
    if request.get('initial_checkpoint') and not prior:
        first=result.get('initial_checkpoint') or {}
        if first.get('step')!=0 or first.get('time')!=0 or first.get('identity')!=identity:
            raise SolverError('protocol','缺少实际初态检查点')
        decode(first['state'])
