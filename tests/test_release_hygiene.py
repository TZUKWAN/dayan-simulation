"""Publication checks must catch private files even after forced git staging."""
import importlib.util
from pathlib import Path
import subprocess

import pytest


def test_forced_private_staging_is_rejected_without_exposing_contents(tmp_path):
    spec = importlib.util.spec_from_file_location('source_checks', Path(__file__).with_name('check_sources.py'))
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True, capture_output=True)
    (tmp_path / 'README.md').write_text('Public project', encoding='utf-8')
    subprocess.run(['git', 'add', 'README.md'], cwd=tmp_path, check=True)
    checks.check_repository_hygiene(tmp_path)
    folder = tmp_path / 'dayan_runtime_data'
    folder.mkdir()
    (folder / '.workbench-token').write_text('synthetic-test-secret-never-echo', encoding='utf-8')
    subprocess.run(['git', 'add', '-f', 'dayan_runtime_data/.workbench-token'], cwd=tmp_path, check=True)
    with pytest.raises(RuntimeError, match='dayan_runtime_data/.workbench-token') as caught:
        checks.check_repository_hygiene(tmp_path)
    assert 'synthetic-test-secret-never-echo' not in str(caught.value)
