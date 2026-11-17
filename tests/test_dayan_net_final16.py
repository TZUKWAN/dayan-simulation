"""NET 终批 16 验收（NET018-072 补齐）。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dayan import simulate  # noqa: E402
from dayan.models.net_final16 import (  # noqa: E402
    AdaptiveRewiringSISModel, AgeContactSEIRModel, BianconiBarabasiModel,
    DCSBMModel, DirectedConfigModel, EdgeBasedSIRModel, GnmModel,
    HarrisContactModel, HoffLatentModel, HyperbolicModel,
    LatentClusterModel, LFRCatalogModel, MMSBMModel,
    PairApproxSIRModel, RenewalEpidemicModel, SoftRGGModel)

from dayan.model_index import ALL_INDEX  # noqa: E402


def test_final_16_runnable():
    """16 个 NET 补齐模型全部可运行。"""
    bad = []
    rng = np.random.default_rng(0)
    models = [GnmModel, DirectedConfigModel, BianconiBarabasiModel,
              SoftRGGModel, HyperbolicModel, DCSBMModel, MMSBMModel,
              LFRCatalogModel, HoffLatentModel, LatentClusterModel,
              AgeContactSEIRModel, RenewalEpidemicModel, PairApproxSIRModel,
              EdgeBasedSIRModel, AdaptiveRewiringSISModel]
    for cls in models:
        m = cls()
        m.initialize({}, {}, None, None, rng)
        for _ in range(3):
            m.step(0, 0.1)
        if not m.observe():
            bad.append((cls.model_id, "empty"))
    hc = HarrisContactModel()
    r = simulate(hc, horizon=10.0, dt=0.05, parameters={}, rng=rng)
    if not r["final"]:
        bad.append(("NET071", "empty"))
    assert not bad, f"NET 终批失败: {bad}"
    print(f"[PASS] NET 终批：{len(models)} + Harris = 16 全可运行")


def test_platform_zero_remaining():
    """An implementation entry is separate from a declaration and verification."""
    from dayan.fidelity import get_catalog
    from dayan.model_index import resolve
    cat=get_catalog()
    for row in cat['models']:
        assert row['has_factory']==(resolve(row['model_id'])[0] is not None)
        if not row['has_factory']:
            assert row['fidelity']=='registered' and not row['runnable']
        if row['probe']['status']=='not_run':
            assert row['probe'].get('ok') is None
    assert cat['counts']['registered_no_factory']==sum(not m['has_factory'] for m in cat['models'])
    print('[PASS] 目录逐项核对真实运行工厂；仅登记项如实保留，不以旧状态声明零残留')


if __name__ == "__main__":
    test_final_16_runnable()
    test_platform_zero_remaining()
    print("\n===== NET 终批 16：全部通过 =====")
