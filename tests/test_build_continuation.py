"""Controlled LLM responses with real solvers, archives, locks and process termination."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

import test_design_continuation as fixture
from test_design_continuation import provider
from dayan.agent import model_tools
from dayan.collection.storage import atomic_json, read_json
from dayan.run_store import get_store


def approved_args(provider, **extra):
    reply = fixture.advance(extra)
    assert reply["ok"] and reply["payload"]["status"] == "approved", reply
    return reply["payload"]["next_action"]["arguments"]


def build(args):
    return model_tools.call_native_model("build_model", args, fixture.SOURCE, "continuation-owner")


def test_compilation_semantic_review_and_execution_have_separate_reusable_budgets(provider):
    args = approved_args(provider)
    def charge(purpose):
        if purpose in ("build-model", "scene-semantic-review"):
            provider.now += 100
    provider.on_call = charge
    first = build(args)
    assert first["ok"] and first["payload"]["current_stage"] == "semantic_review", first
    assert first["payload"]["status"] == "pending" and not first["payload"]["executed"]
    second = build(first["payload"]["next_action"]["arguments"])
    assert second["ok"] and second["payload"]["current_stage"] == "execution", second
    third = build(second["payload"]["next_action"]["arguments"])
    assert third["ok"] and third["payload"]["observations"][-1]["stock"] == pytest.approx(14), third
    assert len(provider.calls) == 7 and len(third["payload"]["llm_calls"]) == 7
    archived = get_store().load(third["payload"]["run_id"])
    assert archived["manifest"]["llm_calls"] == third["payload"]["llm_calls"]
    assert all(row["thinking"] is True and row["timeout"] == 176 for row in provider.calls[-2:])
    again = build(args)
    assert again["ok"] and again["payload"]["run_id"] == third["payload"]["run_id"], again
    assert len(provider.calls) == 7
    assert len(get_store().history()) == 1


def test_transient_semantic_error_resumes_review_without_recompiling(provider):
    args = approved_args(provider)
    failed = False
    def transient(purpose):
        nonlocal failed
        if purpose == "scene-semantic-review" and not failed:
            failed = True
            raise TimeoutError("controlled transport interruption")
    provider.on_call = transient
    first = build(args)
    assert first["ok"] and first["payload"]["pause_reason"] == "transient_provider_error", first
    second = build(first["payload"]["next_action"]["arguments"])
    assert second["ok"] and second["payload"]["observations"][-1]["stock"] == pytest.approx(14), second
    assert [r["purpose"] for r in provider.calls].count("build-model") == 1
    assert all(r["thinking"] is True for r in provider.calls if r["purpose"] == "scene-semantic-review")


def test_compiler_repair_feedback_survives_budget_boundary(provider):
    args = approved_args(provider)
    def invalid(purpose):
        if purpose == "build-model":
            provider.now += 100
            if sum(r["purpose"] == purpose for r in provider.calls) == 1:
                return '{"kind": "stocks", "rates": {"stock": "unknown_var"}}'
    provider.on_call = invalid
    first = build(args)
    assert first["ok"] and first["payload"]["status"] == "pending", first
    args = first["payload"]["next_action"]["arguments"]
    for _ in range(3):
        result = build(args)
        assert result["ok"], result
        if "run_id" in result["payload"]:
            break
        args = result["payload"]["next_action"]["arguments"]
    assert result["payload"]["observations"][-1]["stock"] == pytest.approx(14)
    compiles = [r for r in provider.calls if r["purpose"] == "build-model"]
    assert len(compiles) == 2 and "unknown_var" in compiles[1]["messages"][2]["content"]
    assert "回执校验" in compiles[1]["messages"][3]["content"]


def test_killed_process_after_archive_commit_recovers_same_run_without_execution(provider, tmp_path, monkeypatch):
    args = approved_args(provider)
    args_path = tmp_path / "call.json"
    atomic_json(args_path, args)
    marker = tmp_path / "archive-committed.json"
    root = Path(__file__).resolve().parents[1]
    script = r'''
import json, os, time
from pathlib import Path
from test_design_continuation import ControlledProvider, SOURCE
from dayan.agent import model_tools
from dayan import llm_client
from dayan.run_store import RunStore
control = ControlledProvider()
control.calls = [{}] * 5
model_tools.complete = llm_client.complete = control.complete
save = RunStore.save_run
def save_then_wait(self, rr, *args, **kw):
    result = save(self, rr, *args, **kw)
    Path(os.environ["COMMIT_MARKER"]).write_text(json.dumps({"run_id": result}), encoding="utf-8")
    while True: time.sleep(.1)
RunStore.save_run = save_then_wait
args = json.loads(Path(os.environ["CALL_ARGS"]).read_text(encoding="utf-8"))
print(model_tools.call_native_model("build_model", args, SOURCE, "continuation-owner"), flush=True)
'''
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(root), str(root / "tests")]),
           "CALL_ARGS": str(args_path), "COMMIT_MARKER": str(marker), "PYTHONIOENCODING": "utf-8"}
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
    run_id = read_json(marker)["run_id"]
    import dayan.runtime
    def forbidden(*args, **kwargs):
        raise AssertionError("an already committed run must not be recomputed")
    monkeypatch.setattr(dayan.runtime, "run_model_full", forbidden)
    provider.on_call = lambda purpose: forbidden()
    resumed = build(args)
    assert resumed["ok"] and resumed["payload"]["run_id"] == run_id, resumed
    assert resumed["payload"]["observations"][-1]["stock"] == pytest.approx(14)
    saved = get_store().load(run_id)
    assert saved["request_text"] == fixture.SOURCE and saved["manifest"]["rng"]["seed"] == 7
    assert all(frame["run_id"] == run_id for frame in saved["state_frames"])
    assert len(get_store().history()) == 1


def test_saved_stage_and_run_corruption_are_rejected_without_recalculation(provider, tmp_path, monkeypatch):
    args = approved_args(provider)
    completed = build(args)
    assert completed["ok"], completed
    path = next((tmp_path / "model_builds").glob("*.json"))
    record = read_json(path)
    broken = deepcopy(record)
    next(row for row in broken["stages"] if row["step"] == "compilation")["output"]["rates"]["stock"] = 999
    atomic_json(path, broken)
    response = build(args)
    assert not response["ok"] and "内容校验失败" in response["error"], response
    atomic_json(path, record)
    run_id = completed["payload"]["run_id"]
    (get_store()._path(run_id) / "observations.json").write_text("[]", encoding="utf-8")
    response = build(args)
    assert not response["ok"] and "校验" in response["error"], response
    assert len(provider.calls) == 7


def test_ensemble_resumes_only_unfinished_seeds_and_reuses_analysis(provider, monkeypatch):
    monkeypatch.setattr(fixture, "SOURCE", "新建库存模型，记录库存增长。运行4步，步长0.5。")
    args = approved_args(provider, seeds=[7, 8, 9])
    from dayan.agent import composer
    original = composer.run_model_full
    calls = []
    def execute(*args, **kwargs):
        calls.append(kwargs["seed"])
        result = original(*args, **kwargs)
        provider.now += 100
        return result
    monkeypatch.setattr(composer, "run_model_full", execute)
    for index in range(3):
        result = build(args)
        assert result["ok"], result
        if index < 2:
            assert result["payload"]["status"] == "pending", result
            assert result["payload"]["executed"] is True and result["payload"]["execution_complete"] is False
            assert len(result["payload"]["completed_runs"]) == index + 1
            args = result["payload"]["next_action"]["arguments"]
    payload = result["payload"]
    assert calls == [7, 8, 9] and payload["stats"]["stock"]["mean"] == pytest.approx(14)
    assert len(provider.calls) == 7 and len(payload["runs"]) == 3
    for member in payload["runs"]:
        assert get_store().load(member["run_id"])["manifest"]["llm_calls"] == payload["llm_calls"]
    again = build(args)
    assert again["ok"] and again["payload"]["analysis_id"] == payload["analysis_id"], again
    assert calls == [7, 8, 9] and len(get_store().history()) == 4


def test_resource_snapshot_changes_do_not_invalidate_semantic_review(provider, monkeypatch):
    args = approved_args(provider)
    original = model_tools.population_plan
    snapshots = []
    def changing(*args, **kwargs):
        profile = original(*args, **kwargs)
        snapshots.append(len(snapshots))
        return {**profile, "host_available_bytes": 8_000_000_000 + len(snapshots)}
    monkeypatch.setattr(model_tools, "population_plan", changing)
    first = build(args)
    assert first["ok"], first
    second = build(args)
    assert second["ok"] and second["payload"]["run_id"] == first["payload"]["run_id"], second
    assert len(snapshots) >= 3 and len(provider.calls) == 7


def test_build_resumes_actual_solver_checkpoint_without_repeating_steps(provider, monkeypatch):
    from dayan.run_progress import RunProgress
    from dayan.custom_models import DeclarativeModel
    args = approved_args(provider)
    paused = False
    def pause_once(self):
        nonlocal paused
        if not paused and self.record and self.record["state"]["n_iter"] == 2:
            paused = True
            return True
        return False
    monkeypatch.setattr(RunProgress, "due", lambda self: True)
    monkeypatch.setattr(RunProgress, "should_pause", pause_once)
    steps = []
    original = DeclarativeModel.step
    def step(self, t, dt):
        steps.append(t)
        return original(self, t, dt)
    monkeypatch.setattr(DeclarativeModel, "step", step)
    first = build(args)
    assert first["ok"] and first["payload"]["pause_reason"] == "solver_checkpoint", first
    assert first["payload"]["solver_progress"]["saved_step"] == 2
    assert first["payload"]["execution_complete"] is False and not first["payload"]["completed_runs"]
    second = build(first["payload"]["next_action"]["arguments"])
    assert second["ok"] and second["payload"]["observations"][-1]["stock"] == pytest.approx(14), second
    assert steps == [0, .5, 1, 1.5] and len(provider.calls) == 7
    assert second["payload"]["manifest"]["execution_recovery"]["resumed"] is True
    assert second["payload"]["manifest"]["execution_recovery"]["from_step"] == 2


def test_deleted_history_is_not_reissued_as_a_new_build(provider):
    from dayan.history_records import change
    args = approved_args(provider)
    first = build(args)
    assert first["ok"], first
    store = get_store()
    change(store, store.directory / "unused-legacy.json", first["payload"]["run_id"], deleted=True)
    retry = build(args)
    assert not retry["ok"] and "已被用户删除" in retry["error"], retry
    assert len(provider.calls) == 7 and not store.history()
