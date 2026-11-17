"""Cold metadata is fast and performs no model probing or paid calls."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dayan import fidelity,source_version


class Catalogue(unittest.TestCase):
    def test_cold_catalog_never_probes(self):
        with tempfile.TemporaryDirectory() as td,patch.object(fidelity,'CATALOG_PATH',Path(td)/'catalog.json'),\
             patch.object(fidelity,'PROBE_CACHE',Path(td)/'no-probes.json'),\
             patch.object(fidelity,'probe_batch',side_effect=AssertionError('directory must not run probes')):
            t=time.perf_counter();catalog=fidelity.build_catalog(force=True);duration=time.perf_counter()-t
            print('Measured cold catalog seconds: %.4f'%duration)
            self.assertLess(duration,5)
            self.assertEqual(catalog['counts']['total'],len(catalog['models']))
            self.assertGreater(catalog['counts']['factory_entries'],0)
            self.assertTrue(all(m['fidelity'] not in ('full','lite') or m['reviewed'] for m in catalog['models']))

    def test_engine_runtime_compiler_and_legacy_sources_are_versioned(self):
        paths={p.relative_to(source_version.ROOT).as_posix() for p in source_version.source_files()}
        self.assertTrue({'dayan/engines/games.py','dayan/runtime.py','dayan/research/compiler.py',
                         'dayan/policies.py','src/kernel/core.py','requirements.txt'} <= paths)
        self.assertFalse(any('config.json' in p for p in paths))


if __name__=='__main__':unittest.main(verbosity=2)
