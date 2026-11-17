"""Reproducibility inventory without credentials, user histories or virtualenvs."""
from __future__ import annotations
from functools import lru_cache
import hashlib
from importlib import metadata
import os
from pathlib import Path
import platform
import sys

ROOT=Path(__file__).resolve().parents[1]


def source_inventory():
    paths=set()
    for name in ('dayan','src','experiments'):
        paths.update(p for p in (ROOT/name).rglob('*.py') if '__pycache__' not in p.parts and 'data' not in p.relative_to(ROOT/name).parts)
    for name in ('site/console','plugins/dayan'):
        for path in (ROOT/name).rglob('*'):
            if path.is_file() and not {'node_modules','data','__pycache__'} & set(path.relative_to(ROOT/name).parts) and (path.name=='LICENSE' or path.suffix.lower() in ('.js','.mjs','.cjs','.json','.html','.css','.webp','.svg','.woff2','.ttf','.otf','.txt','.md')):
                if path.name not in ('config.json','package-lock.json'):paths.add(path)
    for name in ('requirements.txt','requirements-dev.txt','requirements-ui.txt','README.md','dayan/config.example.json',
                 'data/model_semantics.json','data/dayan_catalog.json','data/targets.json','data/calibration_targets.md'):
        if (ROOT/name).is_file():paths.add(ROOT/name)
    # Packaged report fonts and licenses are part of rendering reproducibility.
    for p in (ROOT/'assets/fonts').rglob('*'):
        if p.is_file():paths.add(p)
    sources=[(p.relative_to(ROOT).as_posix(),p.read_bytes()) for p in sorted(paths,key=lambda p:p.relative_to(ROOT).as_posix())]
    digests={name:hashlib.sha256(content).hexdigest() for name,content in sources}
    h=hashlib.sha256()
    for name,content in sources:h.update(name.encode());h.update(b'\0');h.update(hashlib.sha256(content).digest())
    return h.hexdigest(),sources,digests


@lru_cache(maxsize=1)
def _packages():
    return dict(sorted((d.metadata['Name'],d.version) for d in metadata.distributions() if d.metadata.get('Name')))


def environment():
    from .limits import limits
    return {'python':platform.python_version(),'implementation':platform.python_implementation(),
            'platform':platform.platform(),'byteorder':sys.byteorder,
            'packages':_packages(),
            'execution_limits':vars(limits()),
            'thread_environment':{k:os.environ.get(k) for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')},
            'configuration_policy':'Secrets, account tokens, personal config, histories, collected data outside bound inputs are excluded.'}
