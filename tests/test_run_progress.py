"""Numerical interruption tests using real state, random streams and actual processes."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from dayan.custom_models import register
from dayan.run_progress import RunPaused, RunProgress
from dayan.runtime import run_model_full


class PauseAt(RunProgress):
    def __init__(self, path, step):
        super().__init__(path, time.monotonic() + 240)
        self.step = step

    def due(self):
        return True

    def should_pause(self):
        return bool(self.record and self.record["state"]["n_iter"] >= self.step)


def grid_model(backend):
    return {"name": "随机时滞扩散续算验算", "description": "恢复逐格浓度及真实随机流和局部历史",
            "kind": "agents", "time_unit": "MCS",
            "agents": {"backend": backend, "type": "cell", "color_by": "value",
                       "grid": {"rows": 8, "columns": 8, "degree": 4, "boundary": "reflecting",
                                "reductions": {"peer": {"op": "mean", "field": "value", "lag": 3}}},
                       "initial": {"value": "uniform(0,1)"},
                       "update": {"value": "0.8*peer+0.2*uniform(0,1)"}},
            "observables": {"total": "sum_value", "mean": "mean_value"}}


def frames(result):
    return [{key: value for key, value in frame.items() if key != "run_id"} for frame in result.state_frames]


@pytest.mark.parametrize("backend", ["scalar", "array"])
def test_random_lagged_local_state_and_every_frame_match_uninterrupted_run(tmp_path, monkeypatch, backend):
    monkeypatch.setenv("DAYAN_DATA_DIR", str(tmp_path / "data"))
    mid = register(grid_model(backend))["model_id"]
    args = {"ticks": 9, "dt": 1, "seed": 11, "capture_state": True, "full_frames": True}
    expected = run_model_full(mid, **args)
    path = tmp_path / "progress"
    with pytest.raises(RunPaused):
        run_model_full(mid, **args, _progress=PauseAt(path, 2))
    progressed = []
    actual = run_model_full(mid, **args, _progress=RunProgress(path, time.monotonic() + 240),
                            on_step=lambda t, _model: progressed.append(t))
    assert progressed == list(range(3, 10))
    assert actual.observations == expected.observations
    assert frames(actual) == frames(expected) and len(actual.state_frames) == 10
    assert actual.checkpoint == expected.checkpoint
    assert actual.manifest["actual"] == expected.manifest["actual"]


@pytest.mark.parametrize("interrupted_step", [0, 4])
def test_killed_uncommitted_write_cleans_only_its_owned_blocks(tmp_path, monkeypatch, interrupted_step):
    monkeypatch.setenv("DAYAN_DATA_DIR", str(tmp_path / "data"))
    mid = register(grid_model("array"))["model_id"]
    args = {"ticks": 9, "dt": 1, "seed": 11, "capture_state": True, "full_frames": True}
    expected = run_model_full(mid, **args)
    path, marker = tmp_path / "progress", tmp_path / "orphan-ready.json"
    root = Path(__file__).resolve().parents[1]
    script = r'''
import os, time
from pathlib import Path
from dayan.run_progress import RunProgress
from dayan.runtime import run_model_full
class StopDuringWrite(RunProgress):
    stopping = False
    def due(self): return True
    def save(self, state, *args, **kw):
        self.stopping = state["n_iter"] == int(os.environ["INTERRUPTED_STEP"])
        super().save(state, *args, **kw)
    def _write(self, name, value):
        result = super()._write(name, value)
        if self.stopping:
            Path(os.environ["STEP_MARKER"]).write_text(name, encoding="utf-8")
            while True: time.sleep(.1)
        return result
run_model_full(os.environ["MODEL_ID"], ticks=9, dt=1, seed=11, capture_state=True, full_frames=True,
               _progress=StopDuringWrite(os.environ["PROGRESS_PATH"], time.monotonic()+240))
'''
    env = {**os.environ, "MODEL_ID": mid, "STEP_MARKER": str(marker), "PROGRESS_PATH": str(path),
           "INTERRUPTED_STEP": str(interrupted_step), "PYTHONPATH": str(root), "PYTHONIOENCODING": "utf-8"}
    with (tmp_path / "child.log").open("w", encoding="utf-8") as log:
        child = subprocess.Popen([sys.executable, "-u", "-c", script], cwd=root, env=env, stdout=log, stderr=log)
        try:
            end = time.monotonic() + 25
            while not marker.exists() and child.poll() is None and time.monotonic() < end:
                time.sleep(.05)
            assert marker.exists(), (tmp_path / "child.log").read_text(encoding="utf-8")
        finally:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=10)
    orphan = path / marker.read_text(encoding="utf-8")
    assert orphan.exists() and (path / "pending.json").exists()
    unrelated = path / ("frame-" + "0" * 32 + ".json")
    unrelated.write_text("user-owned content", encoding="utf-8")
    progressed = []
    actual = run_model_full(mid, **args, _progress=RunProgress(path, time.monotonic() + 240),
                            on_step=lambda t, _model: progressed.append(t))
    assert not orphan.exists() and not (path / "pending.json").exists()
    assert unrelated.read_text(encoding="utf-8") == "user-owned content"
    assert actual.observations == expected.observations and frames(actual) == frames(expected)
    assert actual.checkpoint == expected.checkpoint
    if interrupted_step:
        assert progressed == list(range(interrupted_step, 10))
    record = json.loads((path / "progress.json").read_text(encoding="utf-8"))["record"]
    referenced = {ref["name"] for ref in [*record["rows"], *record["frames"]]}
    assert {p.name for p in path.glob("*-*.json")} == referenced | {unrelated.name}
    assert actual.manifest["actual"] == expected.manifest["actual"]


def test_fractional_clock_and_pending_interventions_resume_at_original_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYAN_DATA_DIR", str(tmp_path / "data"))
    model = {"name": "分步干预库存基准", "description": "检查完整时钟和待执行干预", "kind": "stocks", "time_unit": "小时",
             "parameters": {"rate": {"default": .2, "minimum": 0, "maximum": 1, "mutable": True}},
             "initial_state": {"stock": 1}, "rates": {"stock": "rate*stock"}, "observables": {"stock": "stock"}}
    mid = register(model)["model_id"]
    args = {"ticks": 10, "dt": .1, "seed": 13, "capture_state": True, "full_frames": True, "checkpoint_at": 2,
            "interventions": [{"t": .35, "params": {"rate": .4}}, {"at_t": .75, "params": {"rate": .1}}]}
    expected = run_model_full(mid, **args)
    path = tmp_path / "progress"
    with pytest.raises(RunPaused):
        run_model_full(mid, **args, _progress=PauseAt(path, 3))
    actual = run_model_full(mid, **args, _progress=RunProgress(path, time.monotonic() + 240))
    assert actual.observations == expected.observations
    assert frames(actual) == frames(expected)
    assert actual.manifest["interventions"] == expected.manifest["interventions"]
    assert [row["actual_t"] for row in actual.manifest["interventions"]] == [.35, .75]
    assert actual.manifest["actual"]["final_t"] == 1
    assert actual.checkpoint == expected.checkpoint and actual.checkpoint["t"] == .2


def test_corrupt_chunks_and_changed_inputs_fail_without_advancing(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYAN_DATA_DIR", str(tmp_path / "data"))
    mid = register(grid_model("array"))["model_id"]
    args = {"ticks": 9, "dt": 1, "seed": 11, "capture_state": True, "full_frames": True}
    path = tmp_path / "progress"
    with pytest.raises(RunPaused):
        run_model_full(mid, **args, _progress=PauseAt(path, 2))
    with pytest.raises(ValueError, match="设置或执行版本已变化"):
        run_model_full(mid, **{**args, "seed": 12}, _progress=RunProgress(path, time.monotonic() + 240))
    saved = json.loads((path / "progress.json").read_text(encoding="utf-8"))
    (path / saved["record"]["frames"][0]["name"]).write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="检查点块校验失败"):
        run_model_full(mid, **args, _progress=RunProgress(path, time.monotonic() + 240))


def test_actual_process_termination_resumes_later_steps_only(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYAN_DATA_DIR", str(tmp_path / "data"))
    mid = register(grid_model("array"))["model_id"]
    args = {"ticks": 9, "dt": 1, "seed": 11, "capture_state": True, "full_frames": True}
    expected = run_model_full(mid, **args)
    path, marker = tmp_path / "progress", tmp_path / "ready.json"
    root = Path(__file__).resolve().parents[1]
    script = r'''
import os, time
from pathlib import Path
from dayan.run_progress import RunProgress
from dayan.runtime import run_model_full
class PersistThenWait(RunProgress):
    def due(self): return True
    def save(self, state, *args, **kw):
        super().save(state, *args, **kw)
        if state["n_iter"] == 4:
            Path(os.environ["STEP_MARKER"]).write_text("4", encoding="utf-8")
            while True: time.sleep(.1)
run_model_full(os.environ["MODEL_ID"], ticks=9, dt=1, seed=11, capture_state=True, full_frames=True,
               _progress=PersistThenWait(os.environ["PROGRESS_PATH"], time.monotonic()+240))
'''
    env = {**os.environ, "MODEL_ID": mid, "STEP_MARKER": str(marker), "PROGRESS_PATH": str(path),
           "PYTHONPATH": str(root), "PYTHONIOENCODING": "utf-8"}
    with (tmp_path / "child.log").open("w", encoding="utf-8") as log:
        child = subprocess.Popen([sys.executable, "-u", "-c", script], cwd=root, env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 25
            while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(.05)
            assert marker.exists(), (tmp_path / "child.log").read_text(encoding="utf-8")
        finally:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=10)
    progressed = []
    actual = run_model_full(mid, **args, _progress=RunProgress(path, time.monotonic() + 240),
                            on_step=lambda t, _model: progressed.append(t))
    assert progressed == [5, 6, 7, 8, 9]
    assert actual.observations == expected.observations and frames(actual) == frames(expected)
    assert actual.checkpoint == expected.checkpoint
