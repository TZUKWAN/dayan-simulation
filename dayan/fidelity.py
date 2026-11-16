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
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEW_DIR = ROOT / "data" / "fidelity_review"
CATALOG_PATH = ROOT / "data" / "model_catalog_v2.json"
PROBE_CACHE = ROOT / "data" / "probe_results.json"

FIDELITY_LEVELS = ("full", "lite", "prototype", "method_demo", "registered")
FIDELITY_ZH = {
    "full": "完整实现",
    "lite": "明确简化版",
    "prototype": "机制原型",
    "method_demo": "方法例题",
    "registered": "仅登记",
}


def models_source_fingerprint() -> str:
    """dayan/models + model_index + core 源码指纹：任何变更使目录过期。"""
    h = hashlib.sha256()
    for p in sorted((ROOT / "dayan" / "models").glob("*.py")) + \
            [ROOT / "dayan" / "model_index.py", ROOT / "dayan" / "core.py"]:
        h.update(p.name.encode("utf-8"))
        h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()[:16]


def test_refs_for(mid: str) -> list[str]:
    """扫描 tests/*.py 找直接引用该 mid 的测试文件。"""
    refs = []
    tests_dir = ROOT / "tests"
    if not tests_dir.exists():
        return refs
    for p in sorted(tests_dir.glob("test_*.py")):
        try:
            if re.search(rf"\b{re.escape(mid)}\b", p.read_text(encoding="utf-8",
                                                              errors="ignore")):
                refs.append(p.name)
        except OSError:
            continue
    return refs


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
            out.update(ok=False, skipped=True, requires_external=True,
                       error="需要显式真实LLM/外部数据调用；目录探针不自动消耗云服务",
                       observables=list(getattr(cls, "declared_observables", [])))
            return out
        obs = run_model(mid, parameters=None, ticks=ticks, seed=0)
        obs = obs if isinstance(obs, list) else []
        last = obs[-1] if obs else {}
        outs = [k for k, v in (last.items() if isinstance(last, dict) else [])
                if isinstance(v, (int, float)) and not isinstance(v, bool)]
        out.update(ok=True, n_obs=len(obs),
                   duration_s=round(time.perf_counter() - t0, 3),
                   observables=outs[:12])
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
    """读取全部源码审查 JSON → {mid: review}。"""
    reviews: dict[str, dict] = {}
    if not REVIEW_DIR.exists():
        return reviews
    for p in sorted(REVIEW_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:                      # noqa: BLE001
            continue
        for item in data.get("reviews", []):
            mid = str(item.get("model_id") or item.get("mid") or "").strip().upper()
            if not mid:
                continue
            fid = item.get("fidelity")
            if fid not in FIDELITY_LEVELS:
                fid = "prototype"              # 未分级/级别非法一律降级为原型
            reviews[mid] = {
                "fidelity": fid,
                "basis": str(item.get("basis", ""))[:120],
                "simplifications": item.get("simplifications") or [],
                "evidence": str(item.get("evidence", ""))[:160],
                "review_source": p.name,
            }
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


def build_catalog(force: bool = False) -> dict:
    """三路合并构建忠实度目录并落盘。"""
    from .model_index import ALL_INDEX, resolve

    fp = models_source_fingerprint()
    rfp = reviews_fingerprint()
    if not force and CATALOG_PATH.exists():
        try:
            old = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
            if old.get("source_fingerprint") == fp \
                    and old.get("review_fingerprint") == rfp:
                return old
        except Exception:                      # noqa: BLE001
            pass

    reviews = load_reviews()
    mids = sorted(ALL_INDEX.keys())
    # registered：声明过但无运行工厂的（从 data/dayan_catalog.json 找差集）
    declared = set()
    cat_path = ROOT / "data" / "dayan_catalog.json"
    if cat_path.exists():
        try:
            declared = {m.get("model_id", "").upper()
                        for m in json.loads(cat_path.read_text(encoding="utf-8"))
                        .get("models", [])}
        except Exception:                      # noqa: BLE001
            pass
    probe_results = _cached_probe(mids, fp)

    models = []
    for mid in mids:
        protocol, _ = resolve(mid)
        pr = probe_results.get(mid, {"ok": False, "error": "未探针"})
        rv = reviews.get(mid)
        if rv is None:
            # 无审查记录：不得虚标。降为 prototype 并标注未审查
            rv = {"fidelity": "prototype",
                  "basis": "无源码审查记录，按未审查降级处理",
                  "simplifications": [], "evidence": "",
                  "review_source": None}
        models.append({
            "model_id": mid,
            "protocol": protocol,
            "runnable": bool(pr.get("ok")),
            "probe": {k: pr.get(k) for k in
                      ("ok", "error", "n_obs", "duration_s", "observables")},
            "fidelity": rv["fidelity"],
            "fidelity_zh": FIDELITY_ZH[rv["fidelity"]],
            "basis": rv["basis"],
            "simplifications": rv["simplifications"],
            "evidence": rv["evidence"],
            "review_source": rv["review_source"],
            "reviewed": rv["review_source"] is not None,
            "test_refs": test_refs_for(mid),
            "entry_status": ("可运行" if pr.get("ok")
                             else ("方法例题" if protocol == "demo"
                                   else "注册但探针失败")),
        })

    # 仅登记：声明于目录但无运行工厂
    for mid in sorted(declared - set(mids)):
        if not mid:
            continue
        models.append({
            "model_id": mid, "protocol": None, "runnable": False,
            "probe": {"ok": False, "error": "无运行工厂"},
            "fidelity": "registered", "fidelity_zh": "仅登记",
            "basis": "目录声明但无实现入口", "simplifications": [],
            "evidence": "", "review_source": None, "reviewed": False,
            "test_refs": test_refs_for(mid), "entry_status": "仅登记",
        })

    counts: dict[str, int] = {}
    for m in models:
        counts[m["fidelity"]] = counts.get(m["fidelity"], 0) + 1
    catalog = {
        "version": 2,
        "generated_at": __import__("datetime").datetime.now()
        .isoformat(timespec="seconds"),
        "source_fingerprint": fp,
        "review_fingerprint": rfp,
        "counts": {
            "total": len(models),
            "runnable": sum(1 for m in models if m["runnable"]),
            "fidelity": counts,
            "reviewed": sum(1 for m in models if m["reviewed"]),
        },
        "models": models,
    }
    CATALOG_PATH.parent.mkdir(exist_ok=True)
    CATALOG_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=1),
                            encoding="utf-8")
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
