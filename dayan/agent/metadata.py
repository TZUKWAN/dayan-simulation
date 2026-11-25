"""模型能力元数据层：Agent 的"眼睛"。

generate_capabilities()：对 290 个可运行模型逐一
  1) 反射 __init__ 签名 → 参数清单（名称/默认值）
  2) 探针运行（小步数）→ 数值观测量字段清单 + 终值样例
结果写入 data/model_capabilities.json，供 Agent 搜索/组合/改参时
做语义决策（未来 LLM 直接读这份"模型说明书"）。

load_capabilities()：读盘（不存在则现场生成并缓存）。
"""
from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAP_PATH = ROOT / "data" / "model_capabilities.json"
CAP_META_PATH = ROOT / "data" / "model_capabilities.meta.json"


def _index_signature():
    """全索引签名：模型 ID → 类名 + 参数签名。用于检测能力卡陈旧。"""
    import hashlib
    from ..model_index import ALL_INDEX

    sig = {}
    for mid in sorted(ALL_INDEX):
        protocol, factory = resolve_sig(mid)
        cls = None
        if protocol in ("fixed_step", "simulate"):
            cls = factory
        elif protocol == "demo" and isinstance(factory, tuple) and factory[1]:
            cls = factory[1]
        if cls is None:
            sig[mid] = [protocol, ""]
            continue
        params = [(p["name"], str(p["default"]))
                  for p in _param_signature(cls)]
        sig[mid] = [getattr(cls, "__name__", str(cls)), params]
    blob = json.dumps(sig, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def resolve_sig(mid):
    # 延迟导入避免环；仅启动校验/生成时调用
    from ..model_index import resolve
    return resolve(mid)


def _param_signature(cls):
    try:
        sig = inspect.signature(cls.__init__)
        params = []
        for name, p in list(sig.parameters.items())[1:]:  # 跳过 self
            if name in ("kwargs", "kw", "args"):
                continue
            entry = {"name": name, "default": (None if p.default is inspect.Parameter.empty
                                               else _safe(p.default))}
            params.append(entry)
        return params
    except (ValueError, TypeError):
        return []


def _safe(v):
    try:
        json.dumps(v)
        return v
    except (TypeError, ValueError):
        return str(v)


def _numeric_fields(observations):
    """从 observe 序列提取数值字段 + 终值样例。"""
    if not observations:
        return {}
    last = observations[-1] or {}
    out = {}
    for k, v in last.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = round(float(v), 6)
    return out


def _list_fields(observations):
    if not observations:
        return []
    last = observations[-1] or {}
    return [k for k, v in last.items() if isinstance(v, list)]


def generate_capabilities(ticks=20, seed=0, progress=None):
    """全量探针：返回 capabilities 列表并写盘。"""
    import numpy as np
    from ..model_index import ALL_INDEX, resolve, run_model

    caps = []
    items = sorted(ALL_INDEX)
    for i, mid in enumerate(items):
        protocol, factory = resolve(mid)
        try:
            cls = factory if protocol == "fixed_step" or protocol == "simulate" \
                else None
            params = _param_signature(cls) if cls else []
        except Exception:                                  # noqa: BLE001
            params = []
        obs_fields = {}
        run_ok = True
        err = None
        try:
            if getattr(cls, "requires_external", False):
                raise RuntimeError("目录探针需要显式服务或数据输入")
            observations = run_model(mid, ticks=ticks, seed=seed)
            obs_fields = _numeric_fields(observations)
            list_fields = _list_fields(observations)
        except Exception as e:                             # noqa: BLE001
            run_ok = False
            err = f"{type(e).__name__}: {e}"
            list_fields = []
        cap = {
            "model_id": mid,
            "protocol": protocol,
            "parameters": params,
            "observables": sorted(obs_fields),
            "observable_samples": obs_fields,
            "list_outputs": sorted(list_fields),
            "runnable": run_ok,
            "error": err,
        }
        caps.append(cap)
        if progress:
            progress(i + 1, len(items), mid)
    CAP_PATH.parent.mkdir(exist_ok=True)
    CAP_PATH.write_text(json.dumps(caps, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    # 同步写入索引签名 → load 时自动检测陈旧
    try:
        CAP_META_PATH.write_text(json.dumps(
            {"sig": _index_signature()}, ensure_ascii=False), encoding="utf-8")
    except Exception:                                      # noqa: BLE001
        pass
    return caps


def load_capabilities(refresh=False):
    """Reflect current contracts without silently running every model or cloud agent."""
    if refresh:
        return generate_capabilities()
    from ..model_index import ALL_INDEX, resolve
    from ..runtime import param_contract
    from ..custom_models import capabilities as custom_capabilities
    from ..output_contract import output_contract
    from ..fidelity import _existing_probes, models_source_fingerprint
    reference = _existing_probes(models_source_fingerprint())
    by_id = {}
    catalog_names=_catalog_names()
    for mid in sorted(ALL_INDEX):
        if mid.startswith("USR"):
            continue
        protocol, factory = resolve(mid)
        cls = factory[1] if isinstance(factory, tuple) else factory
        schema = output_contract(mid, reference_results=reference)
        contract = param_contract(mid)
        cap = dict(by_id.get(mid, {}))
        cap.update(model_id=mid, protocol=protocol,
                   name=(inspect.getdoc(cls) or catalog_names.get(mid) or mid).splitlines()[0][:160],
                   catalog_name=catalog_names.get(mid,''),
                   implementation=getattr(cls,'__module__','')+'.'+getattr(cls,'__name__',''),
                   implementation_name=getattr(cls,'__name__',''),
                   description=(inspect.getdoc(cls) or '')[:800],
                   aliases=[getattr(cls,'model_id',mid)],
                   parameters=[{"name": key, **meta} for key, meta in contract["params"].items()],
                   dependencies=contract["dependencies"], fixed_dt=contract["fixed_dt"],
                   requires_external=bool(getattr(cls, "requires_external", False)),
                   runnable=True)
        cap["observables"] = list(schema["fields"])
        cap["output_contract"] = schema
        cap["primary_metric"] = schema["primary_metric"]
        cap["observables_note"] = '源码声明的输出字段；不是本次运行测量，实际输出见归档'
        by_id[mid] = cap
    return [cap for mid, cap in by_id.items() if not mid.startswith("USR")] + custom_capabilities()


def _catalog_names():
    """model_id → 中文名称（来自目录）。"""
    p = CAP_PATH.parent / "dayan_catalog.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {m["model_id"]: m.get("name", "")
                for m in data.get("models", [])}
    except Exception:                                  # noqa: BLE001
        return {}


# 中文概念词 → 模型 ID 别名（search 时把这些词也映射到具体模型）
_SEARCH_ALIAS = {
    "恐慌": ["beh005", "beh014", "net052"],
    "情绪": ["beh005", "beh020", "net074"],
    "传染": ["net052", "net053", "net055"],
    "传播": ["net052", "net074", "net075", "net078"],
    "扩散": ["net074", "net075", "bass"],
    "疏散": ["net113", "net114", "net115", "net116"],
    "逃离": ["net113", "net114"],
    "人群": ["net113", "net114", "net115"],
    "骚乱": ["beh005", "beh014"],
    "秩序": ["beh005", "beh014"],
    "罢工": ["beh014"],
    "抗议": ["beh014", "beh005"],
    "隔离": ["beh001", "beh002"],
    "工资": ["eco019"],
    "就业": ["eco019", "eco078"],
    "周期": ["eco019", "eco020", "eco021"],
    "疫情": ["net052", "net053", "net055"],
    "交通": ["net106", "net095", "net096"],
    "拥堵": ["net106"],
    "军备": ["eco110"],
    "冲突": ["eco110", "eco111", "beh049"],
    "舆论": ["beh020", "net074"],
    "谣言": ["net074", "net075"],
    "创新": ["eco052"],
    "增长": ["eco015", "eco016"],
    "贫困": ["eco105", "eco076"],
    "分化": ["beh001", "eco105"],
}


def filter_names(value):
    if value is None:return []
    if isinstance(value,str):values=re.split(r'[\s,，、;；/]+',value)
    elif isinstance(value,(list,tuple)):values=value
    else:raise ValueError('筛选字段须为名称列表或逗号分隔字符串')
    if len(values)>32 or any(not isinstance(v,str) or len(v)>80 for v in values):raise ValueError('筛选字段非法或超过32项')
    return list(dict.fromkeys(v.strip() for v in values if v.strip()))


def search_capabilities(query="", paradigm=None, has_param=None,
                        observable=None):
    """语义搜索：查询词分词后按 OR 匹配 ID/中文名/参数名/观测量名，
    支持中文概念别名映射；按命中词数排序返回前 12 个。"""
    caps = load_capabilities()
    required_parameters,required_observables=filter_names(has_param),filter_names(observable)
    names = _catalog_names()
    terms = [t for t in re.split(r"[\s,，、;；/]+", (query or "").lower()) if t]
    terms=list(dict.fromkeys(terms+re.findall(r'[A-Za-z][A-Za-z0-9_-]*', (query or '').lower())))
    out = []
    for c in caps:
        mid = c["model_id"].lower()
        if not re.fullmatch(r'(?:beh|net|eco|sys|met|app|cpl)\d{3}|usr[0-9a-f]{12}',mid):continue
        name = names.get(c["model_id"], "").lower()
        params = " ".join(p["name"].lower() for p in c["parameters"])
        obs = " ".join(ob.lower() for ob in c["observables"])
        implementation=re.sub(r'([A-Z]+)([A-Z][a-z])',r'\1 \2',c.get('implementation_name','')).lower()
        hay = f"{mid} {name} {c.get('name','')} {c.get('description','')} {c.get('scenario_title','')} {implementation} {' '.join(c.get('aliases',[]))} {params} {obs}".lower()
        if terms:
            hits = 0
            for t in terms:
                if t in hay:
                    hits += 6 if len(t)>1 and (t==mid or t in implementation.split() or t==c.get('implementation_name','').lower()) else 2 if len(t)>1 else .2
                    continue
                # 中文概念别名：词映射到具体模型 ID
                if any(word in t and mid in ids for word,ids in _SEARCH_ALIAS.items()):hits += 1
            if hits == 0:
                continue
        else:
            hits = 1
        if not set(required_parameters)<={p['name'] for p in c['parameters']}:
            continue
        if not set(required_observables)<=set(c['observables']):
            continue
        out.append((hits, c))
    out.sort(key=lambda x: -x[0])
    return [c for _, c in out[:12]]
