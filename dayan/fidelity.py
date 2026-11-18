"""模型忠实度目录（WP1 真实能力与证据分级）。

分级口径（宁降不虚）：
- full        完整实现：忠实实现经典/原论文核心机制，仅常规工程简化
- lite        明确简化版：机制核心在，但维度/规模/细节显著缩减
- prototype   机制原型：只有大致机制示意，未按原论文规则实现
- method_demo 方法例题：演示估计/推断方法本身（MET/ABC 等），模型为固定合成例题
- registered  仅登记：无运行工厂

目录来源（三路合并，全部落盘可审计）：
1. 源码审查 JSON：data/fidelity_review/*.json（人工/智能体逐模型审查，含行号证据）
2. 运行探针：子进程隔离逐模型跑 5 tick，记录 ok/error/时长/观测量
3. 测试证据：扫描 tests/*.py 中对 model_id 的直接引用

输出：data/model_catalog_v2.json（含 models 源码指纹，源码变更后目录作废重审）
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEW_DIR = ROOT / "data" / "fidelity_review"
CACHE_ROOT = Path(os.environ.get('DAYAN_DATA_DIR', ROOT/'data'))
CATALOG_PATH = CACHE_ROOT / "model_catalog_v2.json"
PROBE_CACHE = CACHE_ROOT / "probe_results.json"

FIDELITY_LEVELS = ("full", "lite", "prototype", "method_demo", "registered")
FIDELITY_ZH = {
    "full": "完整实现",
    "lite": "明确简化版",
    "prototype": "机制原型",
    "method_demo": "方法例题",
    "registered": "仅登记",
}


def models_source_fingerprint() -> str:
    """Models, engines, runtime, compiler, legacy packages and dependencies."""
    from .source_version import source_fingerprint
    return source_fingerprint()


from functools import lru_cache


@lru_cache(maxsize=8)
def _test_reference_index(signature):
    index={}
    for relative,_,_ in signature:
        text=(ROOT/relative).read_text(encoding='utf-8')
        for mid in set(re.findall(r'\b(?:BEH|NET|ECO|SYS|MET|APP|CPL)\d{3}\b|\bNET-SIR\b',text)):
            index.setdefault(mid,[]).append(relative.removeprefix('tests/'))
    return index


def _all_test_refs():
    paths=sorted(p for p in (ROOT/'tests').rglob('*') if p.suffix in ('.py','.mjs') and '__pycache__' not in p.parts)
    signature=tuple((p.relative_to(ROOT).as_posix(),p.stat().st_mtime_ns,p.stat().st_size) for p in paths)
    return _test_reference_index(signature)


def test_refs_for(mid: str) -> list[str]:
    return _all_test_refs().get(mid,[])


def _probe_worker(mid: str, ticks: int = 5) -> dict:
    """单模型探针（在工作进程内执行）。"""
    import time
    t0 = time.perf_counter()
    out: dict = {"model_id": mid}
    try:
        from .model_index import resolve, run_model
        protocol, factory = resolve(mid)
        if protocol is None or factory is None:
            out.update(ok=False, error="无运行工厂", protocol=None)
            return out
        out["protocol"] = protocol
        cls = factory[1] if isinstance(factory, tuple) else factory
        if getattr(cls, "requires_external", False):
            needs = getattr(cls,"external_dependencies",())
            out.update(ok=False, skipped=True, requires_external=True,
                       dependencies=list(needs),
                       error="需要真实语言模型调用" if "language_model" in needs else "需指定真实数据集，目录探针不替换输入",
                       observables=list(getattr(cls, "declared_observables", [])))
            return out
        obs = run_model(mid, parameters=None, ticks=ticks, seed=0)
        obs = obs if isinstance(obs, list) else []
        last = obs[-1] if obs else {}
        outs = [k for k, v in (last.items() if isinstance(last, dict) else [])
                if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if not obs:
            raise ValueError('探针没有任何实际观测')
        import math
        def kind(value):
            if isinstance(value,bool):return 'boolean'
            if isinstance(value,(int,float)):
                if not math.isfinite(value):raise ValueError('探针输出含非有限数值')
                return 'number'
            if isinstance(value,str):return 'string'
            if isinstance(value,list):
                for item in value:kind(item)
                return 'array'
            if isinstance(value,dict):
                for item in value.values():kind(item)
                return 'object'
            return 'null'
        fields={key: sorted({kind(row[key]) for row in obs if key in row})
                for key in {key for row in obs for key in row}}
        out.update(ok=True, n_obs=len(obs), output_types=fields,
                   duration_s=round(time.perf_counter() - t0, 3),
                   observables=outs)
    except Exception as e:                     # noqa: BLE001
        out.update(ok=False, error=f"{type(e).__name__}: {e}"[:200],
                   duration_s=round(time.perf_counter() - t0, 3))
    return out


def probe_batch(mids: list[str], ticks: int = 5) -> dict[str, dict]:
    """子进程批量探针；批量超时则逐个隔离定位挂起模型。"""
    results: dict[str, dict] = {}
    B = 10
    for i in range(0, len(mids), B):
        chunk = mids[i:i + B]
        payload = json.dumps({"mids": chunk, "ticks": ticks})
        code = (
            "import sys, json; sys.path.insert(0, r'%s'); "
            "from dayan.fidelity import _probe_worker; "
            "req=json.loads(sys.argv[1]); "
            "print(json.dumps([_probe_worker(m, req['ticks']) for m in req['mids']]))"
        ) % str(ROOT)
        try:
            r = subprocess.run([sys.executable, "-c", code, payload],
                               capture_output=True, text=True, timeout=120,
                               encoding="utf-8", errors="replace",
                               cwd=str(ROOT))
            if r.returncode == 0 and r.stdout.strip():
                arr = json.loads(r.stdout.strip().splitlines()[-1])
                for item in arr:
                    results[item["model_id"]] = item
                continue
            raise RuntimeError(f"rc={r.returncode} {r.stderr[-200:]}")
        except subprocess.TimeoutExpired:
            # 批内逐个隔离，找出挂起者
            for mid in chunk:
                one = json.dumps({"mids": [mid], "ticks": ticks})
                try:
                    r1 = subprocess.run([sys.executable, "-c", code, one],
                                        capture_output=True, text=True,
                                        timeout=30, encoding="utf-8",
                                        errors="replace", cwd=str(ROOT))
                    if r1.returncode == 0 and r1.stdout.strip():
                        results[mid] = json.loads(
                            r1.stdout.strip().splitlines()[-1])[0]
                    else:
                        results[mid] = {"model_id": mid, "ok": False,
                                        "error": f"probe rc={r1.returncode}"}
                except subprocess.TimeoutExpired:
                    results[mid] = {"model_id": mid, "ok": False,
                                    "error": "probe timeout >30s（疑似挂起）"}
        except Exception as e:                 # noqa: BLE001
            for mid in chunk:
                results.setdefault(mid, {"model_id": mid, "ok": False,
                                         "error": f"batch error: {e}"[:150]})
    return results


def load_reviews() -> dict[str, dict]:
    """Unanchored/changed historical reviews never assert current fidelity."""
    reviews={};fp=models_source_fingerprint()
    for p in sorted(REVIEW_DIR.glob('*.json')) if REVIEW_DIR.exists() else []:
        data=json.loads(p.read_text(encoding='utf-8'))
        for item in data.get('reviews',[]):
            mid=str(item.get('model_id') or item.get('mid') or '').strip().upper()
            if not mid:continue
            current=item.get('source_fingerprint',data.get('source_fingerprint'))==fp
            historical=item.get('fidelity','prototype')
            if historical not in FIDELITY_LEVELS:historical='prototype'
            reviews[mid]={'fidelity':historical if current else 'prototype',
                'basis':item.get('basis','') if current else '历史审查未绑定当前执行源码，不能作为当前机制忠实度证明',
                'simplifications':item.get('simplifications',[]) if current else [],
                'evidence':item.get('evidence','') if current else '',
                'review_source':p.name,'review_status':'current' if current else 'stale_or_unanchored',
                'reviewed':current,'historical_review':{k:item.get(k) for k in ('fidelity','basis','simplifications','evidence')},
                'references':item.get('references',[])}
    return reviews


def _cached_probe(mids: list[str], fingerprint: str) -> dict[str, dict]:
    """探针结果按源码指纹缓存；指纹变了才重新全量探测。"""
    if PROBE_CACHE.exists():
        try:
            old = json.loads(PROBE_CACHE.read_text(encoding="utf-8"))
            if old.get("source_fingerprint") == fingerprint:
                have = old.get("results", {})
                if set(have.keys()) >= set(mids):
                    return {m: have[m] for m in mids}
        except Exception:                      # noqa: BLE001
            pass
    results = probe_batch(mids)
    try:
        PROBE_CACHE.write_text(json.dumps(
            {"source_fingerprint": fingerprint, "results": results},
            ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return results


def reviews_fingerprint() -> str:
    """审查文件内容指纹：审查更新后目录自动重算。"""
    h = hashlib.sha256()
    if REVIEW_DIR.exists():
        for p in sorted(REVIEW_DIR.glob("*.json")):
            h.update(p.name.encode("utf-8"))
            h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()[:16]


def _existing_probes(fp):
    for path in (PROBE_CACHE,ROOT/'data'/'output_contract_evidence.json'):
        if path.exists():
            try:
                record=json.loads(path.read_text(encoding='utf-8'))
                if record.get('source_fingerprint')==fp:return record.get('results',{})
            except (ValueError,OSError):pass
    return {}


def build_catalog(force: bool = False) -> dict:
    """Fast metadata assembly. Probes run only in an explicit test/CLI operation."""
    from .model_index import ALL_INDEX,resolve
    from .custom_models import capabilities as custom_capabilities
    from .output_contract import output_contract
    from .research.requirements import model_mechanisms
    fp=models_source_fingerprint();rfp=reviews_fingerprint()
    custom=custom_capabilities()
    probes=_existing_probes(fp)
    pfp=hashlib.sha256(json.dumps(probes,sort_keys=True).encode()).hexdigest()
    cfp=hashlib.sha256(json.dumps(custom,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if not force and CATALOG_PATH.exists():
        try:
            old=json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
            if old.get('source_fingerprint')==fp and old.get('review_fingerprint')==rfp and old.get('custom_fingerprint')==cfp and old.get('probe_fingerprint')==pfp and old.get('version')==3:
                return old
        except (OSError,ValueError):pass
    declared_data=json.loads((ROOT/'data/dayan_catalog.json').read_text(encoding='utf-8'))
    declared={m['model_id'].upper():m for m in declared_data.get('models',[])}
    reviews=load_reviews();mids=sorted(set(ALL_INDEX)|{c['model_id'] for c in custom})
    probes=_existing_probes(fp);models=[]
    refs=_all_test_refs()
    from .research.semantics import registry as semantics_registry
    from .runtime import execution_dependencies
    semantics = semantics_registry()
    for mid in sorted(set(mids)|set(declared)):
        registered=declared.get(mid,{})
        protocol,factory=resolve(mid)
        cls=factory[1] if isinstance(factory,tuple) else factory
        has_factory=factory is not None
        external=bool(getattr(cls,'requires_external',False))
        dependencies=execution_dependencies(mid,check_configuration=False) if external else []
        requires_provider=any(d['type']=='language_model' for d in dependencies)
        pr=probes.get(mid)
        probe_status=('skipped_external' if external else 'not_run') if not pr else ('passed' if pr.get('ok') else 'skipped_external' if pr.get('skipped') else 'failed')
        rv=reviews.get(mid,{})
        method_demo=protocol=='demo' and isinstance(cls,str)
        level='registered' if not has_factory else 'method_demo' if method_demo else rv.get('fidelity','prototype')
        schema=output_contract(mid,reference_results=probes) if has_factory else None
        description=__import__('inspect').getdoc(cls) if isinstance(cls,type) else ''
        entry={'model_id':mid,'name':registered.get('name') or getattr(cls,'__name__',mid),
            'kind':registered.get('kind','机制/方法实现'),'layer':registered.get('layer','模型层'),
            'description':description or '', 'registered':mid in declared,
            'protocol':protocol,'has_factory':has_factory,'runnable':has_factory,
            'entry_kind':'software_reference' if registered.get('layer')=='软件层' else 'compatibility_or_benchmark' if mid not in declared else 'application' if registered.get('layer')=='应用层' else 'model',
            'requires_external':external,'dependencies':dependencies,'output_contract':schema,'mechanisms':sorted(model_mechanisms(mid)),
            'required_data':semantics.get(mid,{}).get('required_data',[]) or [d['name'] for d in dependencies if d['type']=='dataset'],
            'probe':{'status':probe_status,**(pr or {'ok':None,'error':'没有当前源码对应的实际探针证据'})},
            'fidelity':level,'fidelity_zh':FIDELITY_ZH[level],
            'basis':'目录声明但无实现入口' if not has_factory else rv.get('basis','无当前源码审查；运行入口不代表科学有效'),
            'simplifications':rv.get('simplifications',[]),'evidence':rv.get('evidence',''),
            'review_source':rv.get('review_source'),'reviewed':bool(rv.get('reviewed')),
            'review_sources':[{'url':u} for u in rv.get('references',[]) if isinstance(u,str)] if rv.get('reviewed') else [],
            'review_status':rv.get('review_status','unreviewed'),'historical_review':rv.get('historical_review'),
            'test_refs':refs.get(mid,[]),'numerical_benchmark':{'state':'see_test_receipts','scope':'测试引用本身不证明断言已经通过'},
            'data_calibration':{'state':'per_study','scope':'不能把一个场景的校准升级为全模型有效'},
            'independent_holdout':{'state':'per_study'},
            'entry_status':('软件引用' if registered.get('layer')=='软件层' else '仅登记') if not has_factory else
                '需要真实语言模型服务' if requires_provider else '需要指定真实数据集' if external else
                '有运行入口；'+{'passed':'探针通过','failed':'探针失败','not_run':'未探针','skipped_external':'外部服务未探针'}[probe_status]}
        entry['status']=entry['entry_status'];models.append(entry)
    levels={level:sum(m['fidelity']==level for m in models) for level in FIDELITY_LEVELS}
    counts={'total':len(models),'static_registered':len(declared),'factory_entries':sum(m['has_factory'] for m in models),
            'registered_by_layer':{layer:sum(m.get('layer')==layer for m in declared.values()) for layer in ('模型层','应用层','软件层')},
            'compatibility_or_benchmark_entries':sum(m['entry_kind']=='compatibility_or_benchmark' for m in models),
            'registered_model_factories':sum(m['has_factory'] and m['registered'] for m in models),
            'registered_models_without_factory':sum(m['registered'] and m['entry_kind']!='software_reference' and not m['has_factory'] for m in models),
            'runnable':sum(m['runnable'] for m in models),'registered_no_factory':sum(m['registered'] and not m['has_factory'] for m in models),
            'factory_outside_static':[m['model_id'] for m in models if m['has_factory'] and not m['registered']],
            'probe_passed':sum(m['probe']['status']=='passed' for m in models),'probe_failed':sum(m['probe']['status']=='failed' for m in models),
            'probe_skipped_external':sum(m['probe']['status']=='skipped_external' for m in models),
            'provider_entries':sum(any(d['type']=='language_model' for d in m['dependencies']) for m in models),
            'dataset_required_entries':sum(any(d['type']=='dataset' for d in m['dependencies']) for m in models),
            'probe_not_run':sum(m['has_factory'] and m['probe']['status']=='not_run' for m in models),
            'fidelity':levels,'reviewed':sum(m['reviewed'] for m in models),
            'historical_reviews_stale':sum(m['review_status']=='stale_or_unanchored' for m in models)}
    catalog={'version':3,'generated_at':__import__('datetime').datetime.now().isoformat(timespec='seconds'),
             'source_fingerprint':fp,'review_fingerprint':rfp,'custom_fingerprint':cfp,'probe_fingerprint':pfp,
             'counts':counts,'models':models}
    try:
        from .collection.storage import atomic_json
        atomic_json(CATALOG_PATH,catalog)
    except OSError:
        catalog['cache_note']='缓存不可写，本次使用内存目录；未修改只读源码'
    return catalog


def get_catalog(force: bool = False) -> dict:
    return build_catalog(force=force)


def get_model_record(mid: str) -> dict | None:
    mid = mid.strip().upper()
    cat = get_catalog()
    for m in cat.get("models", []):
        if m["model_id"] == mid:
            return m
    return None


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "probe":
        # 工作进程模式：python -m dayan.fidelity probe '<json payload>'
        req = json.loads(sys.argv[2])
        print(json.dumps([_probe_worker(m, req.get("ticks", 5))
                          for m in req["mids"]]))
    else:
        cat = build_catalog(force="--force" in sys.argv)
        print(json.dumps(cat["counts"], ensure_ascii=False))
