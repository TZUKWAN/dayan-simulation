"""A changed file must not be presented as code already loaded by the server."""
from dayan import server, source_version
from api_client import local_client


def test_status_distinguishes_loaded_and_disk_revision(tmp_path, monkeypatch):
    # Isolate the fingerprint input; actually change a file without modifying
    # the user's live checkout or restarting any application.
    root = tmp_path / 'source'
    (root / 'dayan').mkdir(parents=True)
    path = root / 'dayan/fixture.py'
    path.write_text('version = 1\n', encoding='utf-8')
    monkeypatch.setattr(source_version, 'ROOT', root)
    loaded = source_version.source_fingerprint()
    monkeypatch.setattr(server, '_LOADED_REVISION', loaded)
    monkeypatch.setenv('DAYAN_DATA_DIR', str(tmp_path / 'data'))
    with local_client(server.app) as client:
        initial = client.get('/api/workbench/status').json()
        assert initial['loaded_revision'] == initial['disk_revision'] == loaded
        assert initial['restart_required'] is False
        path.write_text('version = 2\n', encoding='utf-8')
        changed = client.get('/api/workbench/status').json()
        assert changed['revision'] == changed['loaded_revision'] == loaded
        assert changed['disk_revision'] == source_version.source_fingerprint() != loaded
        assert changed['restart_required'] is True
        path.write_text('version = 1\n', encoding='utf-8')
        assert client.get('/api/workbench/status').json()['restart_required'] is False


def test_solver_image_recipe_and_dependency_lock_are_execution_dependencies(tmp_path, monkeypatch):
    monkeypatch.setattr(source_version, 'ROOT', tmp_path)
    root = tmp_path / 'dayan/solvers'
    root.mkdir(parents=True)
    before = source_version.source_fingerprint()
    for name in ('Dockerfile', 'requirements.lock', '.dockerignore'):
        (root / name).write_text(name + '\n', encoding='utf-8')
        after = source_version.source_fingerprint()
        assert after != before
        before = after
