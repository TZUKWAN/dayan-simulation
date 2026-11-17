"""大衍 DAYAN 平台服务器：FastAPI 后端 + AI 助手。

启动：python -m dayan.server
浏览器打开：http://127.0.0.1:8899
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from .access import WorkbenchAccess
from .task_manager import managed_endpoint, get_manager

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))



app = FastAPI(title="大衍 DAYAN", version="2.0")
app.add_middleware(WorkbenchAccess)

_state: dict = {}


@app.on_event('shutdown')
async def shutdown():
    from .task_manager import close_managers
    close_managers()


def _dt_now():
    from datetime import datetime as _d
    return _d.now()


def configure_planner():
    from .agent import intent
    from .agent.llm_planner import llm_planner
    from .llm_client import configured
    available=configured()
    intent.set_llm_planner(llm_planner if available else None)
    _state['llm_planner']='configured-not-probed' if available else 'unconfigured'
    return _state['llm_planner']


def _load_catalog():
    cat_path = ROOT / "data" / "dayan_catalog.json"
    cat = json.loads(cat_path.read_text(encoding="utf-8")) if cat_path.exists() else {"models": []}
    from .custom_models import capabilities
    extra = [{"model_id": c["model_id"], "name": c.get("name", c["model_id"]),
              "kind": "自定义可执行规约", "layer": "模型层",
              "status": "未独立审查" if c["runnable"] else "规约未通过"} for c in capabilities()]
    extra.append({"model_id": "CPL001", "name": "路网疏散 老年行动 信息 公交耦合", "kind": "复合机制模型", "layer": "模型层", "status": "情景原型 需真实数据输入"})
    existing = {m["model_id"] for m in cat["models"]}
    cat["models"] += [m for m in extra if m["model_id"] not in existing]
    cat["count"] = len(cat["models"])
    return cat


@app.on_event("startup")
async def startup():
    from .access import access_token
    access_token()  # Native DSH may use tools before any page has been opened.
    _state["catalog"] = _load_catalog()
    # Asset versions are transformed in the response, never in tracked sources.
    print(f"[DAYAN] 目录加载：{_state['catalog']['count']} 条")
    # 注入阿里云 MaaS LLM planner（失败时规则路由自动保底）
    try:
        print('[DAYAN] planner '+configure_planner()+'；实际请求结果单独记录')
    except Exception as e:
        _state["llm_planner"] = f"error:{e}"
        print(f"[DAYAN] LLM planner 注入失败：{e}")


# ============ 静态页面 ============
@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = ROOT / "site" / "console" / "index.html"
    if html_path.exists():
        # no-cache：JS/CSS 有 ?v= 版本号，但 HTML 本身必须每次拉新，否则更新后用户拿旧页
        import hashlib
        digest=hashlib.sha256()
        for file in sorted((ROOT/'site'/'console').glob('*')):
            if file.suffix in ('.js','.css','.html'):digest.update(file.read_bytes())
        html=re.sub(r'v=\d+', 'v='+digest.hexdigest()[:12], html_path.read_text(encoding='utf-8'))
        return HTMLResponse(html,
                            headers={"Cache-Control": "no-cache"})
    html_path2 = ROOT / "site" / "dayan_ui.html"
    if html_path2.exists():
        return HTMLResponse(html_path2.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>大衍 DAYAN</h1><p>UI 文件缺失</p>")


@app.get("/app.js")
async def root_js():
    fp = ROOT / "site" / "console" / "app.js"
    if fp.exists():
        return HTMLResponse(fp.read_text(encoding="utf-8"),
                            media_type="application/javascript", headers={"Cache-Control": "no-store"})
    raise HTTPException(404)


@app.get("/pages.js")
async def pages_js():
    fp = ROOT / "site" / "console" / "pages.js"
    if fp.exists():
        return HTMLResponse(fp.read_text(encoding="utf-8"),
                            media_type="application/javascript", headers={"Cache-Control": "no-store"})
    raise HTTPException(404)


@app.get("/style.css")
async def root_css():
    fp = ROOT / "site" / "console" / "style.css"
    if fp.exists():
        return HTMLResponse(fp.read_text(encoding="utf-8"),
                            media_type="text/css", headers={"Cache-Control": "no-store"})
    raise HTTPException(404)


@app.get("/scene-studio.js")
async def scene_studio_js():
    fp = ROOT / "site" / "console" / "scene-studio.js"
    return HTMLResponse(fp.read_text(encoding="utf-8"), media_type="application/javascript",
                        headers={"Cache-Control": "no-store"})


@app.get("/viz3d.js")
async def viz3d_js():
    fp = ROOT / "site" / "console" / "viz3d.js"
    if fp.exists():
        return HTMLResponse(fp.read_text(encoding="utf-8"),
                            media_type="application/javascript", headers={"Cache-Control": "no-store"})
    raise HTTPException(404)


@app.get("/console/app.js")
async def console_js():
    fp = ROOT / "site" / "console" / "app.js"
    if fp.exists():
        return HTMLResponse(fp.read_text(encoding="utf-8"),
                            media_type="application/javascript", headers={"Cache-Control": "no-store"})
    raise HTTPException(404)


@app.get("/console/style.css")
async def console_css():
    fp = ROOT / "site" / "console" / "style.css"
    if fp.exists():
        return HTMLResponse(fp.read_text(encoding="utf-8"),
                            media_type="text/css", headers={"Cache-Control": "no-store"})
    raise HTTPException(404)


@app.get("/console/assets/{filename}")
async def console_assets(filename: str):
    base=(ROOT/'site'/'console'/'assets').resolve()
    fp=(base/filename).resolve()
    if fp.parent!=base or not re.fullmatch(r'[A-Za-z0-9_.-]+',filename):
        raise HTTPException(404,'资源路径不在允许目录')
    if fp.is_file():
        suffix = fp.suffix.lower()
        media = {".webp": "image/webp", ".png": "image/png",
                 ".jpg": "image/jpeg", ".svg": "image/svg+xml"}
        if suffix not in media:raise HTTPException(404,'资源类型不允许')
        return Response(fp.read_bytes(),media_type=media[suffix])
    raise HTTPException(404)


@app.get("/demo", response_class=HTMLResponse)
async def demo():
    html_path = ROOT / "site" / "dayan_demo.html"
    if html_path.exists():
        return HTMLResponse(html_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>演示页</h1><p>文件缺失</p>")


# ============ API: 目录 ============
@app.get("/api/catalog")
async def api_catalog():
    cat = _load_catalog()
    # 只返回摘要字段
    models = [{"model_id": m["model_id"], "name": m["name"],
               "kind": m.get("kind", ""), "layer": m.get("layer", "模型层"),
               "status": m.get("status", "仅登记")}
              for m in cat.get("models", [])]
    return {"count": len(models), "models": models}


@app.get("/api/catalog/search")
async def api_catalog_search(q: str = "", layer: str = "", limit: int = 50):
    cat = _load_catalog()
    q_lower = q.lower()
    results = []
    for m in cat.get("models", []):
        if layer and m.get("layer") != layer:
            continue
        if q_lower and q_lower not in m["model_id"].lower() \
                and q_lower not in m["name"].lower():
            continue
        results.append({"model_id": m["model_id"], "name": m["name"],
                        "kind": m.get("kind", ""), "layer": m.get("layer", "模型层")})
        if len(results) >= limit:
            break
    return {"results": results, "total": len(results)}


@app.get("/api/demo/data")
async def api_demo_data():
    """加载 campaign 真实数据供前端渲染（全维度，磁盘内容缓存避免重复读盘）。"""
    if _state.get("demo_data") is not None:
        return JSONResponse(content=_state["demo_data"])
    import numpy as np
    import pandas as pd

    def _clean(obj):
        text = json.dumps(obj, ensure_ascii=False, default=str)
        text = text.replace("NaN", "null").replace("Infinity", "null") \
                   .replace("-Infinity", "null")
        return json.loads(text)

    result: dict = {}
    for name, rel in [("llm", "camp_llm_s7"), ("rule", "camp_rule_s7")]:
        d: dict = {}
        base = ROOT / "results" / rel
        # ---- 时间序列全字段 ----
        fp = base / "metrics.csv"
        if fp.exists():
            df = pd.read_csv(fp)
            cols = [c for c in ["tick", "gini", "top10", "top1", "bottom50",
                    "unemployment", "p_ref", "n_firms", "n_firms_with_workers",
                    "wages", "profits", "labor_share", "sales",
                    "exploitation_rate", "conserv_err",
                    "pos_worker", "pos_self", "pos_employer", "pos_unemployed"]
                    if c in df.columns]
            d["series"] = df[cols].round(5).to_dict(orient="records")
        # ---- 财富分布直方图（期末 agents）----
        afp = base / "agents_final.csv"
        if afp.exists():
            af = pd.read_csv(afp)
            w = af["wealth"].to_numpy(dtype=float)
            hi = float(np.quantile(w, 0.98)) if len(w) else 1.0
            hi = max(hi, 1.0)
            clipped = np.clip(w, 0, hi)
            counts, edges = np.histogram(clipped, bins=24, range=(0, hi))
            d["wealth_hist"] = {"edges": edges.round(2).tolist(),
                                "counts": counts.tolist(),
                                "median": float(np.median(w)),
                                "mean": float(np.mean(w)),
                                "max": float(w.max())}
        # ---- 阶级转移矩阵（行归一）----
        tjp = base / "transitions.json"
        if tjp.exists():
            tj = json.loads(tjp.read_text(encoding="utf-8"))
            labels = ["unemployed", "worker", "self", "employer", "member"]
            zh = ["失业", "受雇", "自营", "经营者", "社员"]
            m = np.zeros((len(labels), len(labels)))
            for k, v in tj.items():
                try:
                    a, b = k.split("->")
                    if a in labels and b in labels:
                        m[labels.index(a)][labels.index(b)] = v
                except ValueError:
                    pass
            rs = m.sum(axis=1, keepdims=True)
            rs[rs == 0] = 1
            d["transitions"] = {"labels": zh, "matrix": (m / rs).round(3).tolist()}
        # ---- 拜物教话语 ----
        ftp = base / "fetishism.csv"
        if ftp.exists():
            fet = pd.read_csv(ftp)
            d["fetishism"] = fet.groupby("position")["fetishism"].mean().round(2) \
                                .to_dict()
            d["fetishism_n"] = len(fet)
        # ---- 归因结构（H9a 朴素阶级意识）----
        svp = base / "survey.csv"
        if svp.exists():
            sv = pd.read_csv(svp)
            if "attribution" in sv.columns:
                d["attribution"] = sv["attribution"].value_counts().to_dict()
            sm = sv.groupby("position")[["fairness", "conflict", "optimism"]] \
                   .mean().round(2)
            sd = sm.to_dict(orient="index")
            for pos in sd:
                for k, v in sd[pos].items():
                    if pd.isna(v):
                        sd[pos][k] = None
            d["survey"] = sd
        # ---- 企业规模分布（期末）----
        ffp = base / "firms.csv"
        if ffp.exists():
            ff = pd.read_csv(ffp)
            last = ff[ff["tick"] == ff["tick"].max()]
            d["firm_sizes"] = last[last["n_workers"] > 0]["n_workers"] \
                .tolist()
        result[name] = _clean(d)

    # ---- Seeman 异化（LLM 组）----
    ali_fp = ROOT / "results" / "camp_llm_s7" / "alienation.csv"
    if ali_fp.exists():
        ali = pd.read_csv(ali_fp)
        dims = ["powerlessness", "meaninglessness", "normlessness",
                "isolation", "self_estrangement"]
        ad = ali.groupby("position")[dims].mean().round(3).to_dict(orient="index")
        for pos in ad:
            for k, v in ad[pos].items():
                if pd.isna(v):
                    ad[pos][k] = None
        result["alienation"] = {"dims": dims, "data": _clean(ad)}
        result["alienation_n"] = len(ali)
    _state["demo_data"] = _clean(result)
    return JSONResponse(content=_state["demo_data"])


# ============ API: 忠实度目录（WP1）与参数合同（WP3） ============
@app.get("/api/models/catalog")
async def api_models_catalog(fidelity: str = "", family: str = "", limit: int = 0):
    """模型忠实度目录：full/lite/prototype/method_demo/registered + 探针 + 测试证据。"""
    from .fidelity import get_catalog
    cat = await asyncio.to_thread(get_catalog)
    models = cat["models"]
    if fidelity:
        fset = {f.strip() for f in fidelity.split(",") if f.strip()}
        models = [m for m in models if m["fidelity"] in fset]
    if family:
        models = [m for m in models if m["model_id"].startswith(family.upper())]
    if limit:
        models = models[:int(limit)]
    return {"generated_at": cat.get("generated_at"),
            "source_fingerprint": cat.get("source_fingerprint"),
            "counts": cat["counts"], "models": models}


@app.get("/api/models/search")
async def api_models_search(theme: str = "", limit: int = 60):
    """主题搜索模型：先按机制表正则（疾病传播/交通流/就业劳动…）匹配，未命中再全文关键词兜底。"""
    from .fidelity import get_catalog
    from .research.requirements import MECHANISMS
    cat = await asyncio.to_thread(get_catalog)
    models = cat["models"]
    theme = (theme or "").strip()
    if not theme:
        return {"theme": "", "total": len(models), "mechanism_names": list(MECHANISMS.keys()),
                "models": models[:int(limit)], "hint": "传 theme 如 传染病/谣言/交通流/疏散/就业劳动/排队，或模型ID片段"}
    matched = [name for name, pat in MECHANISMS.items() if re.search(pat, theme)]
    hits: list = []
    if matched:
        rx = re.compile("|".join(MECHANISMS[m] for m in matched), re.I)
        for m in models:
            blob = " ".join([m.get("basis") or "", m.get("model_id") or "",
                             " ".join(m.get("simplifications") or []),
                             m.get("evidence") or "", m.get("fidelity_zh") or ""])
            if rx.search(blob):
                hits.append(m)
    if not hits:
        kw = re.escape(theme)
        for m in models:
            if kw in json.dumps(m, ensure_ascii=False):
                hits.append(m)
    return {"theme": theme, "mechanisms": matched, "total": len(hits),
            "models": hits[:int(limit)],
            "hint": ("机制匹配: " + ", ".join(matched)) if matched else "未命中机制表，按全文关键词匹配"}


@app.get("/api/models/contract/{mid}")
async def api_model_contract(mid: str, include_fidelity: bool = True):
    """参数合同：__init__ 形参、类型、默认值（UI/Agent/实验共用一份）。"""
    from .runtime import param_contract
    from .fidelity import get_model_record
    mid = mid.strip().upper()
    try:
        contract = param_contract(mid)
    except KeyError as e:
        raise HTTPException(404, str(e))
    rec = await asyncio.to_thread(get_model_record, mid) if include_fidelity else None
    return {"contract": contract, "fidelity": rec}


def _manifest_public(m: dict) -> dict:
    """manifest 的对外子集（完整版落盘历史）。"""
    keys = ("run_id", "requested", "actual", "param_issues", "param_effect",
            "rng", "clocks", "checkpoint", "events_n", "interventions",
            "started_at", "finished_at", "duration_s", "warnings",
            "runtime_version", "model_id", "protocol", "code_version", "software",
            "artifact_schema", "state_frame_count", "state_every", "data_bindings", "model_definition",
            "llm_calls", "implementation_note", "fidelity", "scenario_review")
    return {k: m.get(k) for k in keys if k in m}


# ============ API: 已实现的模型（从忠实度目录动态派生，不再静态硬编码） ============
@app.get("/api/models/implemented")
async def api_implemented():
    """按证据分级的可运行模型清单（full/lite 优先），替代旧静态列表。"""
    from .fidelity import get_catalog
    cat = await asyncio.to_thread(get_catalog)
    models = []
    for m in cat["models"]:
        if not m["runnable"] or m["fidelity"] in ("method_demo", "registered"):
            continue
        models.append({"model_id": m["model_id"], "protocol": m["protocol"],
                       "fidelity": m["fidelity"],
                       "fidelity_zh": m["fidelity_zh"],
                       "basis": m["basis"]})
    return {"count": len(models), "models": models}


# ============ API: 运行仿真 ============
@app.post("/api/custom_models")
@managed_endpoint
async def api_custom_model(req: dict):
    from .agent.model_tools import build_model
    try:
        result = await asyncio.to_thread(build_model, **req)
    except TypeError as exc:
        raise HTTPException(400, str(exc))
    if not result["ok"]:
        raise HTTPException(400, result["error"])
    return result["payload"]


@app.get("/api/custom_models/{model_id}")
async def api_custom_definition(model_id: str):
    from .custom_models import factory
    try:
        cls = factory(model_id)
        return {"model_id": model_id, "definition": cls.definition,
                "validation": "可执行DSL结构校验；科学适用性与校准状态须另行验证"}
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(404, str(exc))


class DatasetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    format: str = "csv"
    content: str | None = Field(default=None, max_length=10 * 1024 * 1024)
    content_base64: str | None = Field(default=None, max_length=14 * 1024 * 1024)
    source: str = "user-upload"
    license: str = "unknown"
    role: str = "input"


@app.post("/api/datasets/import")
@managed_endpoint
async def api_dataset_import(req: DatasetInput):
    from .datasets import ingest
    try:
        if (req.content is None) == (req.content_base64 is None):
            raise ValueError("只提供content或content_base64之一")
        import base64
        raw = req.content.encode("utf-8") if req.content is not None else base64.b64decode(req.content_base64, validate=True)
        return await asyncio.to_thread(ingest, raw, name=req.name,
                                        format=req.format, source=req.source, license=req.license, role=req.role)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/datasets/collect")
@managed_endpoint
async def api_dataset_collect(req: dict):
    from .agent.data_tools import collect_data
    result = await asyncio.to_thread(collect_data, **req)
    if not result["ok"]:
        raise HTTPException(400, result["error"])
    return result["payload"]


@app.get("/api/datasets")
async def api_datasets():
    from .datasets import dataset_dir, load, summary
    return {"datasets": [summary(load(p.name)) for p in sorted(dataset_dir().glob("DS-*")) if p.is_dir()]}


@app.get("/api/datasets/{dataset_id}")
async def api_dataset(dataset_id: str, path: str = ""):
    from .datasets import load, summary, analyze
    try:
        record = load(dataset_id)
        result = summary(record)
        try:
            result["analysis"] = analyze(dataset_id, path)
        except ValueError as exc:
            result["analysis_error"] = str(exc)
        return result
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(404, str(exc))


@app.get("/api/datasets/{dataset_id}/original")
async def api_dataset_original(dataset_id: str):
    from .datasets import load, dataset_dir
    try:
        record = load(dataset_id)
        return Response((dataset_dir() / dataset_id / "original").read_bytes(),
                        media_type="application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="{dataset_id}.{record["format"]}"'})
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(404, str(exc))


class SimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_id: str
    parameters: dict = {}
    ticks: int = Field(default=200, ge=0, le=10000, strict=True)
    dt: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    seed: int | None = Field(default=None, ge=0, lt=2 ** 64, strict=True)
    strict: bool = True
    data_bindings: list = []
    checkpoint_at: int | None = Field(default=None, ge=0, strict=True)
    interventions: list = []   # WP8 时点干预：[{"at_t": sim时刻, "label": str, "params": {...}}]


@app.post("/api/run")
@managed_endpoint
async def api_run(req: SimRequest):
    """统一运行入口（WP3/WP4/WP5）：run_model_full → 单次初始化、
    参数合同、派生随机流、sim_t 时间戳、RunManifest。
    成功运行完整归档到research_runs，回放与续算读取同一记录。"""
    from .model_index import ALL_INDEX
    from .runtime import run_model_full
    from .agent.tools import _clean_nan
    mid = str(req.model_id).strip().upper()          # 小写/空格容忍（与 Agent 工具一致）
    from .model_index import resolve
    if resolve(mid)[0] is None:
        raise HTTPException(404, f"模型 {mid} 无运行工厂")
    try:
        ticks = int(req.ticks)
        rr = await asyncio.to_thread(
            run_model_full, mid, parameters=req.parameters, ticks=ticks, dt=req.dt,
            seed=req.seed, strict=bool(req.strict), with_time=True,
            interventions=req.interventions, capture_state=True, data_bindings=req.data_bindings,
            checkpoint_at=req.checkpoint_at)
        from .run_store import get_store
        await asyncio.to_thread(get_store().save_run, rr, "run", "手动/前端运行")
        run_id = rr.manifest["run_id"]
        return {"model_id": mid, "observations": _clean_nan(rr.observations),
                "ok": True, "n": len(rr.observations),
                "run_id": run_id, "state_url": f"/api/runs/{run_id}/state",
                "data_url": f"/api/runs/{run_id}/observations.csv",
                "manifest": _manifest_public(rr.manifest)}
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:                    # 严格模式参数拒绝等
        raise HTTPException(400, str(e))
    except Exception as e:                     # noqa: BLE001
        raise HTTPException(500, f"{type(e).__name__}: {e}")


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticks: int = Field(ge=0, le=10000, strict=True)
    dt: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)


@app.post("/api/runs/{run_id}/resume")
@managed_endpoint
async def api_resume(run_id: str, req: ResumeRequest):
    from .run_store import resume_saved_run
    try:
        payload=await asyncio.to_thread(resume_saved_run,run_id,req.ticks,req.dt)
        return {"ok":True,**payload}
    except (ValueError,KeyError,FileNotFoundError) as exc:
        raise HTTPException(400,str(exc))


class StateStreamRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str | None = None
    model_id: str | None = None
    parameters: dict = {}
    ticks: int = Field(default=120, ge=0, le=10000, strict=True)
    dt: float | None = Field(default=None, gt=0, allow_inf_nan=False, strict=True)
    seed: int | None = Field(default=None, ge=0, lt=2 ** 64, strict=True)
    sample_every: int = Field(default=5, ge=1, le=10000, strict=True)
    interventions: list = []


@app.post("/api/state_stream")
@managed_endpoint
async def api_state_stream(req: StateStreamRequest):
    """WP7 状态同源沙盘：运行模型并采样状态帧。
    provenance=entity：主体位置/状态来自模型真实计算；
    provenance=aggregate：模型未导出个体状态，前端必须标注「汇总驱动的示意动画」。"""
    from .model_index import ALL_INDEX
    from .run_store import get_store, state_stream
    from .runtime import run_model_full
    from .agent.tools import _clean_nan
    try:
        store = get_store()
        if req.run_id:
            record = await asyncio.to_thread(store.load, req.run_id)
        else:
            mid = str(req.model_id or "").strip().upper()
            if mid not in ALL_INDEX:
                raise KeyError(f"模型 {mid} 无运行工厂")
            rr = await asyncio.to_thread(run_model_full, mid, parameters=req.parameters,
                                         ticks=req.ticks, dt=req.dt, seed=req.seed,
                                         interventions=req.interventions, capture_state=True)
            await asyncio.to_thread(store.save_run, rr, "state", "直接状态运行")
            record = await asyncio.to_thread(store.load, rr.manifest["run_id"])
        if record["kind"] != "run":
            raise ValueError("实验包含多组运行，请选定一个run_id获取状态")
        return _clean_nan(state_stream(record, req.sample_every))
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:                     # noqa: BLE001
        raise HTTPException(500, f"{type(e).__name__}: {e}")


HIST_PATH = ROOT / "data" / "run_history.jsonl"


@app.get("/api/runs/{run_id}")
async def api_saved_run(run_id: str):
    from .run_store import get_store
    try:
        return await asyncio.to_thread(get_store().load, run_id)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/experiments")
@managed_endpoint
async def api_experiment(body: dict):
    from .research.specs import ExperimentSpec
    from .research.experiment import run_experiment, experiment_payload
    from .run_store import get_store
    try:
        spec = ExperimentSpec.from_dict(body).finalize()
        problems = spec.validate()
        if problems:
            raise ValueError("；".join(problems))
        result = await asyncio.to_thread(run_experiment, spec, strict=True, persist=True)
        if not result.ok:
            raise ValueError("实验未完成: " + str(result.warnings))
        await asyncio.to_thread(get_store().save_experiment, result)
        return {"ok": True, **experiment_payload(result)}
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc))
    except KeyError as exc:
        raise HTTPException(404, str(exc))


@app.get("/workspace.css")
async def workspace_css():
    path = ROOT / "site" / "console" / "workspace.css"
    return Response(path.read_text(encoding="utf-8"), media_type="text/css",
                    headers={"Cache-Control": "no-store"})


@app.get("/research.js")
async def research_workspace_js():
    path = ROOT / "site" / "console" / "research.js"
    return Response(path.read_text(encoding="utf-8"), media_type="application/javascript",
                    headers={"Cache-Control": "no-store"})


@app.get("/analysis.js")
async def analysis_js():
    path = ROOT / "site" / "console" / "analysis.js"
    return Response(path.read_text(encoding="utf-8"), media_type="application/javascript",
                    headers={"Cache-Control": "no-store"})


@app.get("/command.js")
async def command_js():
    path = ROOT / "site" / "console" / "command.js"
    return Response(path.read_text(encoding="utf-8"), media_type="application/javascript",
                    headers={"Cache-Control": "no-store"})


@app.get("/command.css")
async def command_css():
    path = ROOT / "site" / "console" / "command.css"
    return Response(path.read_text(encoding="utf-8"), media_type="text/css",
                    headers={"Cache-Control": "no-store"})


@app.get("/results.js")
async def results_js():
    path = ROOT / "site" / "console" / "results.js"
    if not path.is_file():
        raise HTTPException(404, "结果视图脚本不存在")
    return Response(path.read_text(encoding="utf-8"), media_type="application/javascript",
                    headers={"Cache-Control": "no-store"})


@app.get("/api/runs/{run_id}/state")
async def api_saved_state(run_id: str, sample_every: int = 1):
    from .run_store import get_store, state_stream
    try:
        record = await asyncio.to_thread(get_store().load, run_id)
        if record["kind"] != "run":
            raise ValueError("请选择实验内具体运行的run_id")
        return state_stream(record, sample_every)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/runs/{run_id}/observations.csv")
async def api_saved_csv(run_id: str):
    from .run_store import get_store
    try:
        data = await asyncio.to_thread(get_store().observations_csv, run_id)
        return Response(data, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{run_id}.csv"'})
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/runs/{run_id}/bundle.zip")
async def api_saved_bundle(run_id: str):
    from .run_store import get_store
    try:
        data = await asyncio.to_thread(get_store().bundle, run_id)
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{run_id}.zip"'})
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


def _log_history(entry: dict):
    try:
        HIST_PATH.parent.mkdir(exist_ok=True)
        with HIST_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception:                          # noqa: BLE001
        pass


@app.get("/api/history")
async def api_history(limit: int = 30):
    """磁盘运行历史（最新在前，含截断观测序列，供回放页恢复）。"""
    import time as _time
    from .run_store import get_store
    store = get_store()
    entries = await asyncio.to_thread(store.history, limit)
    seen = {e["run_id"] for e in entries}
    if HIST_PATH.exists() and len(entries) < min(limit, 60) \
            and not (store.directory / "history_cutoff.json").exists():
        lines = HIST_PATH.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines[-300:]):
            try:
                e = json.loads(line)
                if e.get("run_id") in seen:
                    continue
                e.update(complete=False, legacy=True,
                         legacy_warning="旧格式记录可能截断，缺少完整状态/规约，不能作为完整研究归档")
                e["age_min"] = max(0, int((_time.time() - _time.mktime(
                    _time.strptime(e["ts"], "%Y-%m-%dT%H:%M:%S"))) / 60))
                entries.append(e)
            except Exception:                  # noqa: BLE001
                continue
            if len(entries) >= min(limit, 60):
                break
    return {"count": len(entries), "entries": entries}


@app.delete("/api/history")
async def api_history_clear():
    """清空磁盘运行历史。"""
    try:
        from .run_store import get_store
        get_store().clear_history()
    except Exception as e:                     # noqa: BLE001
        raise HTTPException(500, str(e))
    return {"ok": True}


@app.get("/api/models/runnable")
async def api_runnable():
    """可运行模型清单（ID + 协议）。"""
    from dayan.model_index import ALL_INDEX, resolve
    from .custom_models import capabilities
    for cap in capabilities():
        if cap["runnable"]:
            resolve(cap["model_id"])
    out = []
    for mid in sorted(ALL_INDEX):
        protocol, _ = resolve(mid)
        out.append({"model_id": mid, "protocol": protocol})
    return {"count": len(out), "models": out}


class AgentRequest(BaseModel):
    text: str = Field(min_length=1,max_length=8000)
    history: list = []
    last_run: dict = {}
    async_job: bool = True


# Expensive work is queued in supervised processes; no thread per request.

@app.post("/api/agent")
@managed_endpoint
async def api_agent(req: AgentRequest):
    """One grounded agent result. managed_endpoint handles sync/queued delivery."""
    from .agent.agent import get_agent
    from .task_worker import progress
    agent=get_agent()
    callback=progress if __import__('os').environ.get('DAYAN_TASK_DIR') else None
    result=await asyncio.to_thread(agent.fulfill,req.text,history=req.history,last_run=req.last_run,progress=callback)
    return {"ok":result.get("ok",False),"planner":result.get("planner"),
            "intent":result.get("intent"),"scene":result.get("scene"),
            "requirements":result.get("requirements"),"errors":result.get("errors",[]),
            "constraint_corrections":result.get("constraint_corrections",[]),
            "planner_error":result.get("planner_error"),
            "summary":agent.summarize(result),"executed":result.get("executed",[])}


@app.get("/api/jobs/{job_id}")
async def api_job(job_id: str):
    try:
        return get_manager().get(job_id)
    except (KeyError,ValueError):
        from .agent.job_store import load_job
        try:return await asyncio.to_thread(load_job,job_id)
        except (KeyError,ValueError,OSError):raise HTTPException(404,'job不存在或无法核验')


@app.delete('/api/jobs/{job_id}')
async def api_job_cancel(job_id: str):
    try:return get_manager().cancel(job_id)
    except (KeyError,ValueError):raise HTTPException(404,'job不存在')


@app.get("/api/agent/planner_status")
async def api_planner_status():
    return {"planner": _state.get("llm_planner", "rule")}


class ReportRequest(BaseModel):
    model_id: str
    run_id: str | None = None
    experiment_id: str | None = None
    analysis_id: str | None = None
    observations: list = []
    intent: str = ""
    planner: str = "rule"
    manifest: dict = {}      # WP5：本次运行的 RunManifest（实际配置/警告/干预）
    analysis: dict = {}      # WP8：程序先行实验分析（效应量/配对差）
    primary_metric: str | None = None
    analysis_window: dict | None = None
    sim_t: float | None = None
    entity_id: str | None = None
    entity_metric: str | None = None
    distribution_field: str | None = None


@app.post("/api/report")
@managed_endpoint
async def api_report(req: ReportRequest):
    """生成 Word 仿真实验事实报告（程序统计 + docx + 结果图）。
    报告基于 manifest 实际配置与程序分析，不用默认值叙事。"""
    from .report_gen import generate_report
    from .view_analysis import analyze_view
    if not req.run_id:
        raise HTTPException(400, "研究报告需要已归档的run_id，不能仅凭客户端观测生成")
    if not req.experiment_id and not req.analysis_id:
        from .research.studies import for_run
        study = await asyncio.to_thread(for_run, req.run_id)
        if study:
            if study["model_id"] != req.model_id:
                raise HTTPException(400, "报告模型与研究运行不一致")
            from .research.study_reports import generate_report as study_report
            report = await asyncio.to_thread(study_report, study["study_id"], "academic")
            return {**report, "url": report["file"], "source": "verified_study"}
    records, view, report_kind = [], None, "run"
    observations, manifest, analysis = req.observations, req.manifest, req.analysis
    if req.run_id:
        from .run_store import get_store
        try:
            record = get_store().load(req.run_id)
            if record.get("kind") != "run":
                raise ValueError("请选择研究记录内的具体运行")
            if record["model_id"] != req.model_id:
                raise ValueError("报告模型与归档运行不一致")
            observations, manifest = record["observations"], record["manifest"]
            analysis = {}
            records = [{**record, "view_label": record["model_id"], "view_group": record["model_id"]}]
            if req.experiment_id and req.analysis_id:
                raise ValueError("报告不能同时指定实验和分析组")
            if req.experiment_id:
                exp = get_store().load(req.experiment_id)
                if not any(r["run_id"] == req.run_id for r in exp.get("runs", [])):
                    raise ValueError("运行不属于报告指定实验")
                analysis = exp["analysis"]
                report_kind = "experiment"
                records = [{**get_store().load(ref["run_id"]), "view_label": f"{ref['arm']} · seed={ref['seed']}",
                            "view_group": ref["arm"], "view_seed": ref["seed"]} for ref in exp["runs"]]
            elif req.analysis_id:
                group = get_store().load(req.analysis_id)
                if group.get("kind") != "analysis" or not any(r["run_id"] == req.run_id for r in group.get("runs", [])):
                    raise ValueError("运行不属于报告指定分析组")
                payload = group["analysis"]
                analysis = payload.get("analysis", {})
                report_kind = payload.get("tool", group.get("tool", "analysis"))
                records = [{**get_store().load(ref["run_id"]),
                            "view_label": str(ref.get("label") or (f"{payload.get('param')}={ref['value']}" if "value" in ref else f"seed={ref['seed']}" if "seed" in ref else ref["model_id"]))}
                           for ref in group["runs"]]
                if report_kind == "ensemble":
                    for item in records:
                        item["view_group"] = "种子重复"
            view = analyze_view(records, req.run_id, req.primary_metric or analysis.get("metric"),
                                req.analysis_window, req.sim_t, req.entity_id, report_kind,
                                req.entity_metric, req.distribution_field)
        except KeyError as exc:
            raise HTTPException(400, "报告关联记录类型不匹配")
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(400, str(exc))
    meta = {"intent": req.intent, "planner": req.planner,
             "manifest": manifest, "analysis": analysis, "view_analysis": view, "view_records": records}
    try:
        result = await asyncio.to_thread(
            generate_report, req.model_id, observations, meta)
    except Exception as e:                     # noqa: BLE001
        raise HTTPException(500, f"{type(e).__name__}: {e}")
    if not result.get("ok"):
        raise HTTPException(500, result.get("error", "报告生成失败"))
    return result


# ============ API: 专业模式数据源/采集/质量 ============
@app.get("/api/collection/sources")
async def api_collection_sources(theme: str = "", state: str = "", offset: int = 0, limit: int = 100):
    """来源矩阵（含证据状态）。"""
    from .collection import registry
    rows = registry.matrix()
    if state:
        rows = [r for r in rows if r["state"] == state]
    if theme:
        for r in rows[:]:
            hay = " ".join([r["source_id"], r["name"], r.get("org", ""),
                             " ".join(r.get("topics", []))])
            if theme.lower() not in hay.lower():
                rows.remove(r)
    return {"ok": True, "n_sources": len(rows),
             "state_counts": {s: sum(1 for r in registry.matrix() if r["state"] == s)
                              for s in registry.STATES},
             "offset": max(0, offset), "sources": rows[max(0, offset):max(0, offset)+max(1, min(limit, 200))]}


@app.get("/api/collection/presets")
async def api_collection_presets():
    """采集预设清单。"""
    from .collection import presets
    return {"ok": True, "presets": presets.list_presets()}


@app.post("/api/collection/run_preset")
@managed_endpoint
async def api_run_preset(body: dict):
    """执行采集预设。"""
    from .agent.data_tools import run_preset
    result = await asyncio.to_thread(run_preset, body.get("preset_id", ""), body.get("values", {}), body.get("page_budget", 1))
    return {**result, "task": result.get("payload")}


@app.get("/api/collection/tasks")
async def api_collection_tasks(offset: int = 0, limit: int = 100):
    """采集任务列表。"""
    from .collection import engine
    tasks = engine.list_tasks()
    return {"ok": True, "n_tasks": len(tasks), "offset": max(0, offset), "tasks": [
        {k: v for k, v in t.items() if k != "pages"} for t in tasks[max(0, offset):max(0, offset)+max(1, min(limit, 200))]]}


@app.get("/api/collection/reports/docx/{filename}")
async def api_collection_report_docx(filename: str, legacy: bool = False):
    """下载 DOCX 格式研究报告。"""
    import re
    from fastapi.responses import FileResponse
    from .research.report_docx import REPORTS_DIR
    if not re.fullmatch(r"report_[A-Za-z0-9_\-]+\.docx", filename):
        raise HTTPException(400, "非法文件名")
    path = REPORTS_DIR / filename
    if not path.exists():
        raise HTTPException(404, "文件不存在")
    if not legacy:
        raise HTTPException(409, "这是缺少统一study_id的历史报告，部分模型/校准版本不一致；请用当前研究生成报告。仅历史查阅可显式加legacy=true")
    return FileResponse(str(path), filename=filename,
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.post("/api/collection/reports/render_docx")
@managed_endpoint
async def api_render_collection_reports(body: dict):
    """Reports always require a concrete immutable study; legacy templates never overwrite outputs."""
    from .agent.data_tools import research_report
    study_id = body.get("study_id")
    if not study_id:
        return {"ok": False, "error": "必须指定实际study_id；旧报告缺少统一版本合同，不能用于当前研究"}
    kind = {"B_academic": "academic", "policy": "policy", "data_quality": "data_quality"}.get(body.get("report"), body.get("kind", "academic"))
    return await asyncio.to_thread(research_report, study_id, kind)


@app.get("/api/health")
async def api_health():
    from .access import access_token
    access_token()
    return {"ok": True, "service": "dayan", "contract_version": "research-integrity-1", "access_contract": "loopback-capability-1", "task_contract": "bounded-process-1"}


@app.post("/api/tools/{tool_name}")
@managed_endpoint
async def api_platform_tool(tool_name: str, body: dict):
    """Shared explicit tool execution for DSH and professional UI. No second LLM planner."""
    from .agent.tools import call_tool, TOOL_IMPL
    if tool_name not in TOOL_IMPL:
        raise HTTPException(404, "未知平台工具")
    args = body.get("arguments", body)
    if not isinstance(args, dict): raise HTTPException(400, "arguments必须为对象")
    try:
        if body.get("origin") == "dsh":
            from .research.native_contract import protect
            args = protect(tool_name, args, str(body.get("original_text", "")), str(body.get("session_id", "")))
        result = await asyncio.to_thread(call_tool, tool_name, **args)
    except Exception as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if body.get("origin") == "dsh":
        from .research.integration_events import append_event
        result["integration_event"] = append_event(str(body.get("session_id", "")), tool_name, result)
    return result


@app.get("/api/integrations/dsh/events")
async def api_dsh_events(session_id: str, after: int = 0):
    from .research.integration_events import events
    return {"ok": True, "events": events(session_id, after)}


@app.get("/api/research/studies")
async def api_studies():
    from .research.studies import list_studies
    return {"ok": True, "studies": await asyncio.to_thread(list_studies)}


@app.get("/api/research/for_run/{run_id}")
async def api_research_for_run(run_id: str):
    from .research.studies import for_run, summary
    study = await asyncio.to_thread(for_run, run_id)
    return {"ok": True, "study": summary(study) if study else None}


@app.get("/api/research/legacy")
async def api_legacy_research():
    from .research.legacy_audit import inspect_legacy
    return {"ok": True, "audit": await asyncio.to_thread(inspect_legacy)}


@app.get("/api/research/studies/{study_id}")
async def api_study(study_id: str):
    from .research.studies import load
    try: return {"ok": True, "study": await asyncio.to_thread(load, study_id)}
    except (ValueError, OSError) as exc: raise HTTPException(400, str(exc))


@app.get("/api/research/studies/{study_id}/files/{filename}")
async def api_study_file(study_id: str, filename: str):
    from .research.studies import load, directory
    from fastapi.responses import FileResponse
    import re
    try: load(study_id)
    except (ValueError, OSError) as exc: raise HTTPException(400, str(exc))
    if not re.fullmatch(r"[A-Za-z0-9_\-]+\.(docx|md|png|csv|json|zip)", filename):
        raise HTTPException(400, "非法文件名")
    path = directory(study_id) / "reports" / filename
    if not path.is_file(): raise HTTPException(404, "研究文件尚未生成")
    return FileResponse(path, filename=filename)


@app.get("/reports/{filename}")
async def download_report(filename: str):
    """下载生成的实验报告（仅 reports 目录内的 docx/png）。"""
    import re
    from fastapi.responses import FileResponse
    from .report_gen import REPORTS_DIR
    if not re.fullmatch(r"[A-Za-z0-9_\-]+\.(docx|png|json)", filename):
        raise HTTPException(400, "非法文件名")
    path = REPORTS_DIR / filename
    if not path.exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(str(path),
                        filename=filename,
                        media_type={".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                    ".png": "image/png", ".json": "application/json"}[path.suffix])


@app.get("/api/agent/tools")
async def api_agent_tools():
    """Agent 工具清单（未来 LLM 的 function-calling 合同）。"""
    from .agent.tools import tool_manifest
    import json as _json
    return JSONResponse(content={"tools": _json.loads(tool_manifest())})


@app.get("/api/ai/health")
async def api_ai_health():
    """LLM 健康：以平台实际接入的 planner（阿里云 MaaS）为准。"""
    from .agent.llm_planner import health
    return {"llm_available": health(), "planner": _state.get("llm_planner", "rule")}


# ============ API: AI 助手 ============
class ChatMessage(BaseModel):
    message: str = Field(min_length=1,max_length=8000)
    history: list = []
    last_run: dict = {}


@app.post("/api/ai/chat")
@managed_endpoint
async def api_ai_chat(msg: ChatMessage):
    """Compatibility endpoint using the same grounded agent, not a second promise-only chatbot."""
    from .agent.agent import get_agent
    agent=get_agent()
    result=await asyncio.to_thread(agent.fulfill,msg.message,history=msg.history,last_run=msg.last_run)
    return {"reply":"\n".join(agent.summarize(result)),"status":"ok" if result.get("ok") else "error",
            "ok":result.get("ok",False),"executed":result.get("executed",[]),
            "requirements":result.get("requirements"),"errors":result.get("errors",[])}


# ============ 启动 ============
if __name__ == "__main__":
    import os
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("DAYAN_PORT", "8899")), log_level="info")
