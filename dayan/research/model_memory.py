"""Scoped references derived from accepted runs, available after independent design."""
from datetime import datetime, timezone
import hashlib
import hmac
import math
import re

from ..access import access_token, data_root
from ..collection.storage import atomic_json, read_json
from ..history_records import cutoff, preferences
from ..run_store import get_store


WORKBENCH_SCOPE = "workbench"
_KEY = re.compile(r"[a-f0-9]{64}")
_SCOPE = re.compile(r"(?:project|session)-[a-f0-9]{64}")
_TERMS = re.compile(r"[\u3400-\u9fff]+|[a-z][a-z0-9_]*")
_COMMON = {"大衍", "请用", "建模", "模型", "新建", "建立", "构建", "仿真", "模拟", "运行",
           "实际", "用户", "需求", "进行", "研究", "输出", "观测", "结果", "报告", "每步"}
_ARCHIVE_ERRORS = (OSError, KeyError, TypeError, ValueError)


def native_scope(session_id, key=None, proof=None):
    """Resolve a host-asserted profile and project, or the existing pinned chat."""
    if key is not None or proof is not None:
        if not (isinstance(key, str) and _KEY.fullmatch(key)
                and isinstance(proof, str) and _KEY.fullmatch(proof)):
            raise ValueError("DSH研究记忆绑定格式无效")
        message = f"dayan-research-memory-v1\n{session_id}\n{key}"
        signature = hmac.new(access_token().encode(), message.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, proof):
            raise ValueError("DSH研究记忆绑定校验失败")
    matches = []
    for path in (data_root() / "integrations/dsh/project_sessions").glob("*.json"):
        try:
            record = read_json(path)
            if not isinstance(record, dict):
                continue
            if (record.get("schemaVersion") == 2 and record.get("sessionId") == session_id
                    and _KEY.fullmatch(path.stem) and _KEY.fullmatch(record.get("profileKey", ""))
                    and record.get("projectRoot")):
                matches.append(path.stem)
        except (OSError, TypeError, ValueError):
            continue
    if len(matches) == 1:
        if key is not None and key != matches[0]:
            raise ValueError("DSH研究记忆项目与已绑定会话不一致")
        key = matches[0]
    if key is not None:
        return "project-" + key
    return "session-" + hashlib.sha256(session_id.encode()).hexdigest()


def _directory(scope):
    if scope != WORKBENCH_SCOPE and not _SCOPE.fullmatch(scope):
        raise ValueError("研究记忆缺少有效归属")
    return data_root() / "research_memory" / scope


def _keywords(text):
    terms = set()
    for token in _TERMS.findall(text.casefold()):
        if token.isascii():
            terms.add(token)
        else:
            terms.update(token[i:i + 2] for i in range(len(token) - 1))
    return terms - _COMMON


def _texts(values):
    return [value[:220] for value in values[:8] if isinstance(value, str)]


def _data_fields(manifest):
    fields = ("dataset_id", "sha256", "path", "field", "parameter", "scale", "source_unit", "target_unit",
              "source_scope", "target_scope", "frequency", "compatibility_status", "role", "filters", "order_by")
    return [{"aggregate": row.get("aggregate", "last"), **{name: row[name] for name in fields if name in row}}
            for row in (manifest.get("data_bindings") or [])[:8]]


def _remember(store, folder, run_id, request):
    meta, manifest = store.load_manifest(run_id)
    definition = manifest.get("model_definition")
    review = manifest.get("scenario_review") or {}
    verification = (review.get("runtime_checks") or {}).get("verification") or {}
    if (not isinstance(definition, dict) or not str(meta.get("model_id", "")).startswith("USR")
            or verification.get("status") != "passed" or (review.get("coverage") or {}).get("status") != "covered"):
        return False
    if manifest.get("run_id") != run_id or manifest.get("model_id") != meta["model_id"]:
        raise ValueError("研究记忆引用与运行归档不一致")
    mechanisms = _texts(definition.get("mechanisms", []))
    description = definition["description"][:420]
    title = definition["name"][:120]
    fields = list(definition["observables"])[:16]
    evidence_text = " ".join([title, description, *mechanisms, *fields])
    terms = _keywords(evidence_text + " " + (request or meta.get("request_text") or ""))
    reference = {"run_id": run_id, "model_id": meta["model_id"], "title": title, "kind": definition["kind"],
                 "description": description, "mechanisms": mechanisms, "observables": fields,
                 "time_unit": definition["time_unit"], "limitations": _texts(review.get("limitations", [])),
                 "data_fields": _data_fields(manifest), "code_version": manifest.get("code_version"),
                 "execution_verified": True, "scientific_validation": review.get("scientific_validation") is True}
    atomic_json(folder / (run_id + ".json"), {"reference": reference, "terms": sorted(terms)})
    return True


def remember_build(scope, payload, request):
    """Index actual accepted single runs and each archived replicate."""
    store = get_store()
    folder = _directory(scope)
    runs = [payload] if payload.get("run_id") else payload.get("runs", [])
    saved, errors = [], []
    for run in runs:
        run_id = run.get("run_id")
        if not run_id:
            continue
        try:
            if _remember(store, folder, run_id, request):
                saved.append(run_id)
                meta,manifest=store.load_manifest(run_id)
                design_id=(manifest.get('scenario_review') or {}).get('model_design',{}).get('design_id')
                if design_id:
                    from ..agent.model_design import load_design
                    design=load_design(design_id)
                    prior=design.get('implementation_feedback') or {}
                    if design.get('revision_of') and prior.get('feedback_id'):
                        _lesson(scope,'accepted_revision',request,
                            {'run_id':run_id,'model_id':meta['model_id'],'archive_files':meta['files'],
                             'design_id':design['revision_of'],'feedback_id':prior['feedback_id']},
                            {'previous_error':prior.get('error'),'accepted_design_id':design_id,
                             'status':'actual_model_acceptance_not_empirical_validation'})
        except _ARCHIVE_ERRORS as exc:
            errors.append({"run_id": run_id, "error": str(exc)})
    return {"indexed_run_ids": saved, "errors": errors}


def _backfill(store, folder, scope, session_id):
    """Use only successful native builds owned by this session as legacy evidence."""
    if not session_id:
        return
    from .integration_events import events

    legacy_scope = native_scope(session_id)
    for event in events(session_id, limit=None):
        if event.get("session_id") != session_id or event.get("tool") != "build_model" or not event.get("ok"):
            continue
        if event.get("memory_scope", legacy_scope) != scope:
            continue
        try:
            run_ids = event.get("run_ids") or ([event["run_id"]] if event.get("run_id") else [])
            if not run_ids and event.get("analysis_id"):
                run_ids = [row["run_id"] for row in store.load(event["analysis_id"])["runs"]]
            for run_id in run_ids:
                # _path also validates IDs in legacy receipts before they are used as filenames.
                if not (folder / (store._path(run_id).name + ".json")).is_file():
                    _remember(store, folder, run_id, None)
        except _ARCHIVE_ERRORS:
            continue


def references(scope, session_id, request, concept, *, _all_candidates=False, _limit=3):
    """Rank by lexical overlap, then verify the referenced archives are still visible."""
    store = get_store()
    folder = _directory(scope)
    _backfill(store, folder, scope, session_id)
    query = _keywords(request)
    ideas = _keywords(" ".join([concept["approach"], *concept["mechanisms"]]))
    hidden, cleared = preferences(store), cutoff(store)
    ranked = []
    for path in folder.glob("R*.json"):
        try:
            card = read_json(path)
            ref = card["reference"]
            if ref["run_id"] != path.stem or hidden.get(path.stem, {}).get("deleted"):
                continue
            terms = set(card["terms"])
            common = query & terms
            if len(common) >= 2 or _all_candidates:
                score = (2 * len(common) + len(ideas & terms)) / math.sqrt(len(terms))
                ranked.append((score, path.stem, ref))
        except _ARCHIVE_ERRORS:
            continue
    result, models = [], set()
    for _, run_id, ref in sorted(ranked, key=lambda row: row[:2], reverse=True):
        try:
            if ref["model_id"] in models:
                continue
            meta, manifest = store.load_manifest(run_id)
            if (manifest.get("code_version") != ref["code_version"] or meta["model_id"] != ref["model_id"]
                    or not isinstance(manifest.get("model_definition"), dict)):
                continue
            if cleared:
                timestamp = datetime.fromisoformat(meta["created_at"])
                if (timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)) <= cleared:
                    continue
        except _ARCHIVE_ERRORS:
            continue
        definition = manifest["model_definition"]
        result.append({**ref, "data_fields": _data_fields(manifest), "equations": {
            "rates": dict(list(definition.get("rates", {}).items())[:6]),
            "agent_updates": dict(list((definition.get("agents") or {}).get("update", {}).items())[:6]),
        }})
        models.add(ref["model_id"])
        if len(result) == _limit:
            break
    return result


def _lesson(scope,kind,source,reference,content):
    from ..solvers.codec import digest
    record={'kind':kind,'source_request':source,'reference':reference,'content':content,
            'scope':scope,'created_at':datetime.now(timezone.utc).isoformat(),
            'use':'仅在独立构思后参考；本轮需求和实际数据优先，不自动复制历史模型或将历史约束变成本轮规则'}
    ident='L-'+digest({'kind':kind,'source':source,'reference':reference,'content':content})
    record['memory_id']=ident
    path=_directory(scope)/(ident+'.json')
    if not path.exists():atomic_json(path,{'record':record,'sha256':digest(record)})
    return ident


def remember_failure(design,feedback_id,feedback):
    scope=design.get('memory_scope')
    if not scope:return None
    from ..agent.design_checkpoint import digest
    if digest(feedback)!=feedback_id:raise ValueError('失败记忆须来自实际反馈摘要')
    return _lesson(scope,'failure',design['request'],
        {'design_id':design['design_id'],'feedback_id':feedback_id,'plan_sha256':design['plan_sha256']},
        {'error':feedback['error'],'evidence':feedback.get('evidence'),
         'mechanisms':feedback.get('definition',{}).get('mechanisms',[]),
         'equations':feedback.get('definition',{}).get('equations',feedback.get('definition',{}).get('rates',{}))})


def remember_correction(scope,session_id,correction,*,design_id=None,run_id=None):
    from ..agent.model_design import load_design
    from .native_contract import _session_has_run
    if not isinstance(correction,str) or not correction.strip():raise ValueError('纠正须来自本次真实用户原文')
    if bool(design_id)==bool(run_id):raise ValueError('纠正须明确一个实际design_id或run_id')
    if design_id:
        design=load_design(design_id,session_id if session_id else None)
        if design.get('memory_scope')!=scope:raise ValueError('纠正方案不在当前项目记忆作用域')
        reference={'design_id':design_id,'plan_sha256':design.get('plan_sha256')}
        source=design['request']
    else:
        if session_id and run_id not in correction and not _session_has_run(session_id,run_id):
            raise ValueError('纠正引用须属于本次会话或由用户明确指定运行')
        # Accepted or failed observed results are both valid subjects of correction;
        # the quote is not transformed into a certified scientific assertion.
        meta,manifest=get_store().load_manifest(run_id)
        reference={'run_id':run_id,'model_id':meta['model_id'],'archive_files':meta['files']}
        source=meta.get('request_text','')
    ident=_lesson(scope,'user_correction',source,reference,
        {'user_quote':correction,'session_id':session_id,'status':'user_stated_preference_or_correction_not_verified_fact'})
    return {'memory_id':ident,'kind':'user_correction','mode':'advisory','original_quote':correction}


def lessons(scope):
    from ..solvers.codec import digest
    store=get_store();hidden,cleared=preferences(store),cutoff(store);result=[]
    for path in _directory(scope).glob('L-*.json'):
        try:
            wrapped=read_json(path);row=wrapped['record'];ref=row['reference']
            if wrapped['sha256']!=digest(row) or row['scope']!=scope or row['memory_id']!=path.stem:continue
            if cleared and datetime.fromisoformat(row['created_at'])<=cleared:continue
            if ref.get('run_id'):
                if hidden.get(ref['run_id'],{}).get('deleted'):continue
                meta,_=store.load_manifest(ref['run_id'])
                if meta['files']!=ref['archive_files']:continue
            if ref.get('feedback_id'):
                from ..agent.design_checkpoint import digest as feedback_digest
                original=read_json(data_root()/'model_design_feedback'/ref['design_id']/(ref['feedback_id']+'.json'))
                if feedback_digest(original['record'])!=ref['feedback_id']:continue
            result.append(row)
        except _ARCHIVE_ERRORS:continue
    return sorted(result,key=lambda row:row['created_at'],reverse=True)[:24]


def advisory(scope,session_id,request,concept,*,rank=None):
    """Lexical references first; semantic comparison recovers cross-wording mechanisms."""
    lexical=references(scope,session_id,request,concept)
    candidates=references(scope,session_id,request,concept,_all_candidates=True,_limit=24)
    lesson_cards=lessons(scope)
    known={r['run_id'] for r in lexical}
    extras=[{**r,'memory_id':r['run_id'],'kind':'accepted_model'} for r in candidates if r['run_id'] not in known]+lesson_cards
    query=_keywords(request+' '+concept['approach']+' '+' '.join(concept['mechanisms']))
    direct=[r for r in extras if len(query&_keywords(__import__('json').dumps(r,ensure_ascii=False)))>=2]
    remaining=[r for r in extras if r not in direct]
    semantic=[]
    if remaining and rank:
        ranked=rank(remaining)
        lookup={r['memory_id']:r for r in remaining}
        if not isinstance(ranked,list) or len(ranked)>3 or len({r['memory_id'] for r in ranked})!=len(ranked):
            raise ValueError('语义记忆须选择最多3个不重复的实际候选')
        for match in ranked:
            if set(match)!={'memory_id','reason'} or match['memory_id'] not in lookup or not isinstance(match['reason'],str) or not match['reason'].strip():
                raise ValueError('语义记忆不能捏造候选编号或相关依据')
            semantic.append({**lookup[match['memory_id']],'retrieval':{'method':'llm_semantic_mechanism_comparison','reason':match['reason']}})
    return [*lexical,*direct[:3],*semantic][:6]


def tool_memory_feedback(design_id=None,run_id=None,correction=None):
    try:return {'ok':True,'payload':remember_correction(WORKBENCH_SCOPE,'',correction,design_id=design_id,run_id=run_id)}
    except Exception as exc:return {'ok':False,'error':f'{type(exc).__name__}: {exc}'}
