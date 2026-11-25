"""Real Docker execution. No fake engine/provider substitutes for integration cases."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import pytest

from dayan.solvers.codec import decode, encode
from dayan.solvers.sandbox import SandboxBudget, SolverError, image_contract, run_segment, reconcile_jobs

LIVE = pytest.mark.skipif(os.environ.get("DAYAN_TEST_SOLVER") != "1",
                         reason="requires explicitly built DAYAN solver image; set DAYAN_TEST_SOLVER=1")

MINIMAL = '''
def initialize(parameters, inputs, rng):
    return {"v": 1}
def advance(state, parameters, inputs, rng, time, dt):
    return {"state": {"v": state["v"] + 1}, "events": []}
def observe(state, parameters, inputs, time):
    return {"value": state["v"]}
def frame(state, parameters, inputs, time):
    return {"stocks": state}
def validate(state, parameters, inputs, time):
    return None
'''

MODEL = '''
import numpy as np
from scipy.integrate import solve_ivp
import networkx as nx

def initialize(parameters, inputs, rng):
    return {"people": inputs["positions"].copy(), "firms": np.array([2., 3.]),
            "balance": np.array(5.), "edges": np.array([[0, 1], [1, 2]], dtype=np.int64)}

def advance(state, parameters, inputs, rng, time, dt):
    state["people"] += rng.normal(0., .25, size=state["people"].shape)
    answer = solve_ivp(lambda t,y: parameters["rate"] * (10-y), [time, time+dt],
                       [float(state["balance"])], rtol=1e-11, atol=1e-12)
    state["balance"] = np.array(answer.y[0, -1])
    graph = nx.Graph()
    graph.add_edges_from(state["edges"].tolist())
    graph = nx.relabel_nodes(graph, {i: (i+1) % len(state["people"]) for i in graph})
    state["edges"] = np.array(sorted(tuple(sorted(edge)) for edge in graph.edges), dtype=np.int64)
    return {"state": state, "events": [{"time": time+dt/2, "type": "relationship_update"}]}

def observe(state, parameters, inputs, time):
    return {"total_x": float(state["people"].sum()), "balance": float(state["balance"]),
            "people": len(state["people"]), "firms": len(state["firms"]), "edges": len(state["edges"])}

def frame(state, parameters, inputs, time):
    return {"people": state["people"], "firms": state["firms"], "edges": state["edges"], "balance": state["balance"]}

def validate(state, parameters, inputs, time):
    if state["edges"].max() >= len(state["people"]):
        raise ValueError("edge endpoint out of bounds")
'''


@LIVE
def test_observation_cannot_advance_random_stream(tmp_path,monkeypatch):
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    source=MINIMAL.replace('return {"v": 1}', 'global random_stream\n    random_stream=rng\n    return {"v": 1}')
    source=source.replace('return {"value": state["v"]}', 'random_stream.random()\n    return {"value": state["v"]}')
    with pytest.raises(SolverError,match='随机流'):
        run_segment(source,ticks=0,dt=1,seed=3)


def test_lossless_numeric_state_preserves_shape_dtype_and_rejects_executable_formats():
    for value in (np.array(3.5), np.arange(12, dtype="<f8").reshape(3, 4)[:, ::2], np.array([1, 2], dtype=">i8")):
        actual = decode(encode(value))
        assert actual.shape == value.shape and actual.dtype == value.dtype
        assert np.array_equal(actual, value)
    with pytest.raises(ValueError):
        encode(np.array([object()], dtype=object))
    with pytest.raises(ValueError):
        decode({"__dayan_ndarray__": {"dtype": "O", "shape": [1], "data": ""}})
    masked = np.ma.array([1., np.nan, 3.], mask=[False, True, False], fill_value=-99., hard_mask=True)
    actual = decode(encode(masked))
    assert np.array_equal(actual.data, masked.data, equal_nan=True)
    assert np.array_equal(actual.mask, masked.mask)
    assert actual.fill_value == -99 and actual.hardmask is True
    with pytest.raises(ValueError, match="非有限"):
        encode(np.ma.array([np.nan], mask=False))


@LIVE
def test_real_container_hybrid_numerical_state_and_rng_resume_without_repeating_steps(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYAN_DATA_DIR", str(tmp_path))
    contract = image_contract()
    assert contract["image_id"].startswith("sha256:")
    args = {"parameters": {"rate": .7}, "inputs": {"positions": np.arange(9.)}, "ticks": 5, "dt": .2, "seed": 19}
    expected = run_segment(MODEL, **args, segment_steps=5)
    first = run_segment(MODEL, **args, segment_steps=2)
    second = run_segment(MODEL, **args, segment_steps=3, checkpoint=first["checkpoint"])
    assert first["records"] + second["records"] == expected["records"]
    assert second["checkpoint"] == expected["checkpoint"]
    assert [row["step"] for row in second["records"]] == [3, 4, 5]
    assert expected["records"][-1]["observations"]["balance"] == pytest.approx(10 - 5 * np.exp(-.7), abs=1e-9)
    state = decode(second["checkpoint"]["state"])
    assert state["people"].shape == (9,) and state["firms"].shape == (2,) and state["balance"].shape == ()
    assert not np.array_equal(state["edges"], np.array([[0, 1], [1, 2]]))
    assert all(row["receipt"]["container_removed"] for row in (first, second, expected))
    assert len(list((tmp_path / "solver_jobs").glob("*.json"))) == 3
    with pytest.raises(SolverError, match="执行设置已变化"):
        run_segment(MODEL, **{**args, "seed": 20}, checkpoint=first["checkpoint"])


@LIVE
def test_actual_model_has_no_host_network_secret_root_write_or_watchdog_privilege(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYAN_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DAYAN_SENTINEL_SECRET", "test sentinel must stay on host")
    code = MINIMAL.replace('return {"v": 1}', '''import os, signal, socket
    status = dict(line.split(":", 1) for line in open("/proc/self/status") if ":" in line)
    facts = {"uid": os.getuid(), "caps": int(status["CapEff"], 16),
             "no_new_privs": int(status["NoNewPrivs"]), "seccomp": int(status["Seccomp"]),
             "host_secret": int("DAYAN_SENTINEL_SECRET" in os.environ),
             "docker_socket": int(os.path.exists("/var/run/docker.sock"))}
    try:
        open("/etc/dayan-untrusted-write", "w").write("forbidden")
        facts["readonly_root"] = 0
    except OSError:
        facts["readonly_root"] = 1
    try:
        os.kill(os.getppid(), signal.SIGSTOP)
        facts["watchdog_protected"] = 0
    except PermissionError:
        facts["watchdog_protected"] = 1
    try:
        s = socket.socket()
        s.settimeout(.3)
        s.connect(("1.1.1.1", 443))
        facts["network_isolated"] = 0
    except OSError:
        facts["network_isolated"] = 1
    finally:
        s.close()
    open("/tmp/owned-temporary-file", "w").write("allowed")
    return facts''').replace('return {"value": state["v"]}', 'return state')
    result = run_segment(code, ticks=0, dt=1, seed=0)
    assert result["records"][0]["observations"] == {"uid": 65532, "caps": 0, "no_new_privs": 1, "seccomp": 2,
        "host_secret": 0, "docker_socket": 0, "readonly_root": 1, "watchdog_protected": 1, "network_isolated": 1}
    assert result["receipt"]["container_removed"]


@LIVE
def test_masked_inputs_and_snapshot_aliases_keep_same_meaning_across_real_segments(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYAN_DATA_DIR", str(tmp_path))
    code = '''
import numpy as np
def initialize(parameters, inputs, rng):
    values = inputs["values"].copy()
    return {"a": values, "b": values}
def advance(state, parameters, inputs, rng, time, dt):
    state["a"] += 1
    state["b"] += 2
    return {"state": state, "events": []}
def observe(state, parameters, inputs, time):
    return {"a_mean": float(state["a"].mean()), "b_mean": float(state["b"].mean()),
            "missing": int(np.ma.getmaskarray(state["a"]).sum())}
def frame(state, parameters, inputs, time):
    return state
def validate(state, parameters, inputs, time):
    return None
'''
    args = {'ticks':3,'dt':1,'seed':0,'inputs':{'values':np.ma.array([1.,np.nan,3.],mask=[False,True,False])}}
    full = run_segment(code, **args, segment_steps=3)
    first = run_segment(code, **args, segment_steps=1)
    second = run_segment(code, **args, segment_steps=2, checkpoint=first['checkpoint'])
    assert first['records'] + second['records'] == full['records']
    assert second['checkpoint'] == full['checkpoint']
    assert full['records'][-1]['observations'] == {'a_mean':5., 'b_mean':8., 'missing':1}


@LIVE
@pytest.mark.parametrize("action,kind", [('while True: pass', 'timeout'), ('print("x"*150000)', 'output_limit')])
def test_actual_timeout_and_output_flood_fail_and_remove_only_owned_container(tmp_path, monkeypatch, action, kind):
    monkeypatch.setenv("DAYAN_DATA_DIR", str(tmp_path))
    code = MINIMAL.replace('return {"v": 1}', action + '\n    return {"v": 1}')
    with pytest.raises(SolverError) as raised:
        run_segment(code, ticks=0, dt=1, seed=0, budget=SandboxBudget(wall_seconds=3, output_bytes=4096))
    assert raised.value.kind == kind
    assert raised.value.receipt["container_removed"] and raised.value.receipt["status"] == "failed"
    receipt, = (tmp_path / "solver_jobs").glob("*.json")
    assert json.loads(receipt.read_text("utf-8"))["error_kind"] == kind


@LIVE
def test_container_exits_on_its_own_after_real_host_worker_termination(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYAN_DATA_DIR", str(tmp_path))
    root = Path(__file__).resolve().parents[1]
    codefile = tmp_path / "model.txt"
    codefile.write_text(MINIMAL.replace('return {"v": 1}', 'while True: pass'), encoding="utf-8")
    script = '''
from pathlib import Path
import os
from dayan.solvers.sandbox import run_segment, SandboxBudget
run_segment(Path(os.environ["MODEL_TEXT"]).read_text("utf-8"), ticks=0, dt=1, seed=0,
            budget=SandboxBudget(wall_seconds=4))
'''
    with (tmp_path / "child.log").open("w", encoding="utf-8") as log:
        child = subprocess.Popen([sys.executable, "-u", "-c", script], cwd=root,
                    env={**os.environ, "MODEL_TEXT": str(codefile), "PYTHONPATH": str(root)}, stdout=log, stderr=log)
        name = None
        try:
            end = time.monotonic() + 20
            while child.poll() is None and time.monotonic() < end:
                jobs = list((tmp_path / "solver_jobs").glob("*.json"))
                if jobs:
                    name = json.loads(jobs[0].read_text("utf-8"))["container_name"]
                    result = subprocess.run(["docker", "container", "inspect", "--format", "{{.State.Running}}", name], capture_output=True)
                    if result.returncode == 0 and result.stdout.strip() == b"true":
                        break
                time.sleep(.05)
            else:
                pytest.fail((tmp_path / "child.log").read_text("utf-8"))
        finally:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=5)
        assert name
        end = time.monotonic() + 10
        while time.monotonic() < end:
            result = subprocess.run(["docker", "container", "inspect", name], capture_output=True)
            if result.returncode and b"no such" in result.stderr.lower():
                break
            time.sleep(.1)
        else:
            pytest.fail("owned container survived its watchdog deadline")
    recovered = reconcile_jobs()
    assert recovered == [name.removeprefix("dayan-solver-")]
    record = json.loads(next((tmp_path / "solver_jobs").glob("*.json")).read_text("utf-8"))
    assert record["status"] == "interrupted" and record["container_removed"]
    assert record["error_kind"] == "owner_terminated"
