"""History presentation may change while runs and their research references stay intact."""
import io
import json
from zipfile import ZipFile

from fastapi.testclient import TestClient

from api_client import local_client
from dayan.server import app


def history(client, **query):
    response = client.get("/api/history", params={"metadata_only": True, "workbench": True, **query})
    assert response.status_code == 200, response.text
    return response.json()["entries"]


def test_titles_and_deletion_keep_experiment_replay_and_bundle(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYAN_DATA_DIR", str(tmp_path))
    with local_client(app) as client:
        response = client.post("/api/experiments", json={
            "model_id": "NET106", "title": "道路限速对照", "primary_metric": "flux", "ticks": 8, "dt": 1,
            "seeds": [7], "baseline_params": {"density": .3, "p": .2},
            "arms": [{"label": "高慢化概率", "params": {"p": .7}}]})
        assert response.status_code == 200, response.text
        experiment = response.json()
        parent = experiment["experiment_id"]
        child = experiment["runs"][0]["run_id"]
        directory = tmp_path/"research_runs"
        run_file = directory/child/"metadata.json"
        original = run_file.read_bytes()
        by_id = {row["run_id"]: row for row in history(client)}
        assert by_id[parent]["title"] == "道路限速对照"
        assert by_id[child]["title"] == "道路限速对照 · 基线 · 种子 7"
        assert not by_id[child]["title_is_custom"]
        endpoint = "/api/history/" + child
        renamed = client.patch(endpoint, json={"title": "  工作日高峰基线  "})
        assert renamed.json()["record"]["title"] == "工作日高峰基线", renamed.text
        assert [row["run_id"] for row in history(client, search="高峰基线")] == [child]
        assert client.patch(endpoint, json={"title": "  "}).status_code == 400
        assert client.patch(endpoint, json={"title": "过"*81}).status_code == 400
        assert client.patch(endpoint, json={"title": "第一行\n第二行"}).status_code == 400

        other = TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1",50001))
        assert other.delete(endpoint).status_code == 401
        assert client.delete(endpoint, headers={"Origin":"https://invalid.example"}).status_code == 403
        assert client.delete("/api/history/Rno_such_run").status_code == 404
        assert client.delete(endpoint).json()["record"]["deleted"]
        assert client.delete(endpoint).json()["record"]["deleted"]
        with local_client(app) as reopened:
            assert child not in {row["run_id"] for row in history(reopened)}
            assert parent in {row["run_id"] for row in history(reopened)}
            assert reopened.get(f"/api/runs/{child}/state").json()["run_id"] == child
            export = reopened.get(f"/api/runs/{parent}/bundle.zip")
            assert export.status_code == 200, export.text
            with ZipFile(io.BytesIO(export.content)) as bundle:
                assert bundle.read(f"{child}/observations.json") == (directory/child/"observations.json").read_bytes()
            assert reopened.post(endpoint+"/restore").json()["record"]["title"] == "工作日高峰基线"
            assert reopened.patch(endpoint, json={"title": None}).json()["record"]["title"] == by_id[child]["title"]
            assert reopened.delete("/api/history/"+parent).status_code == 200
            assert child in {row["run_id"] for row in history(reopened)}
        assert original == run_file.read_bytes()


def test_legacy_entries_get_distinct_id_and_deleted_mirrors_stay_out(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYAN_DATA_DIR", str(tmp_path))
    with local_client(app) as client:
        response = client.post("/api/run", json={"model_id": "NET052", "ticks": 5, "seed": 9})
        assert response.status_code == 200, response.text
        run = response.json()
        legacy = {"ts": "2020-01-01T12:00:00", "source": "run", "model_id": run["model_id"],
                  "observations": run["observations"]}
        rows = [legacy, {**legacy, "run_id": run["run_id"]}]
        journal = tmp_path/"run_history.jsonl"
        journal.write_text("".join(json.dumps(row)+"\n" for row in rows), encoding="utf-8")
        before = journal.read_bytes()
        first, old = history(client)
        assert first["run_id"] == run["run_id"]
        assert old["kind"] == "legacy" and old["run_id"].startswith("LG-") and old["title"] == first["title"]
        assert history(client, limit=1, offset=1)[0]["run_id"] == old["run_id"]
        assert history(client, before="2020-01-03T00:00:00Z")[0]["run_id"] == old["run_id"]
        endpoint = "/api/history/"+old["run_id"]
        assert client.get(endpoint+"/legacy").json()["observations"] == legacy["observations"]
        assert client.patch(endpoint, json={"title":"旧感染场景"}).status_code == 200
        assert history(client, search="旧感染")[0]["run_id"] == old["run_id"]
        assert client.delete("/api/history/"+first["run_id"]).status_code == 200
        remaining = client.get("/api/history").json()["entries"]
        assert len(remaining) == 1 and remaining[0]["history_id"] == old["run_id"]
        assert client.delete(endpoint).status_code == 200
        assert not history(client) and not client.get("/api/history").json()["entries"]
        assert journal.read_bytes() == before
