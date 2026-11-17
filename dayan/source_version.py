"""Content identity of every first-party Python execution dependency."""
from __future__ import annotations
from functools import lru_cache
import hashlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def source_files():
    paths=[]
    for name in ('dayan','src','experiments'):
        paths.extend(p for p in (ROOT/name).rglob('*.py') if '__pycache__' not in p.parts and 'data' not in p.relative_to(ROOT/name).parts)
    if (ROOT/'requirements.txt').is_file():paths.append(ROOT/'requirements.txt')
    for name in ('dayan_catalog.json','targets.json','calibration_targets.md','model_semantics.json'):
        if (ROOT/'data'/name).is_file():paths.append(ROOT/'data'/name)
    return sorted(paths)


@lru_cache(maxsize=8)
def _digest(signature):
    value=hashlib.sha256()
    for relative,_,_ in signature:
        path=ROOT/relative
        value.update(relative.encode());value.update(b'\0')
        value.update(hashlib.sha256(path.read_bytes()).digest())
    return value.hexdigest()


def source_fingerprint():
    signature=tuple((p.relative_to(ROOT).as_posix(),p.stat().st_mtime_ns,p.stat().st_size) for p in source_files())
    return _digest(signature)
