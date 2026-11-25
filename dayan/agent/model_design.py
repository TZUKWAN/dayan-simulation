"""Review research designs against the original request before execution."""
import ast
import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone

from ..access import data_root
from ..collection.storage import atomic_json, file_lock, read_json
from ..llm_client import complete
from ..research import literature
from ..source_version import source_fingerprint
from .literature_review import decisions_for, unlisted_references
from .model_prompts import design_prompt
from .progress import emit
from .verification import criteria_for_plan
from .design_checkpoint import DesignCheckpoint, PendingStage
from .design_revision import ImplementationMismatch

_FIELD = r"[A-Za-z][A-Za-z0-9_]{0,39}"
_EVOLUTION_PATH = re.compile(r"(?:rates|agents\.update)\." + _FIELD)
_PROGRAM_SOURCE = re.compile(r"source\.[A-Za-z_][A-Za-z0-9_]*")
_PROGRAM_SUPPORT = re.compile(r"(?:equations|populations|input_ports)\." + _FIELD)
_SUPPORT_PATH = re.compile(r"(?:initial_state|agents\.initial|agents\.grid\.reductions|agents\.measures|observables|parameters)\." + _FIELD
                           + r"|agents\.grid\.(?:rows|columns|degree|boundary)")
_RUNTIME_PATH = re.compile(r"execution\.(?:ticks|dt|seed|seeds|parameters|data_bindings|structured_inputs|interventions|scale_requested|research)|state_frames\.(?:entities|population|relations)")
_EXECUTION_PARAMETER = re.compile(r"execution\.parameters\.(" + _FIELD + r")$")


def _digest(value):
    content = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(content.encode()).hexdigest()


def _path(design_id):
    if not isinstance(design_id, str) or not re.fullmatch(r"MD-[a-f0-9]{32}", design_id):
        raise ValueError("方案编号无效")
    return data_root() / "model_designs" / f"{design_id}.json"


def load_design(design_id, session_id=None):
    record = read_json(_path(design_id))
    if record.get("design_id") != design_id or (session_id is not None and record.get("session_id") != session_id):
        raise FileNotFoundError("未找到本会话的建模方案")
    return record


def check_design_context(record,design_id,source,execution,session_id,*,allow_source_evidence=False):
    if (record.get('design_id')!=design_id or record.get('session_id')!=session_id or record.get('request')!=source
            or record.get('source_fingerprint')!=source_fingerprint()):
        raise ValueError('原文、会话、执行设置或平台版本已变化，请重新审查方案')
    if record.get('execution_sha256')!=_digest(execution):
        if not allow_source_evidence:raise ValueError('原文、会话、执行设置或平台版本已变化，请重新审查方案')
        if record.get('execution_sha256')!=_digest(record.get('execution')):
            raise ValueError('父方案执行合同校验失败')
        from ..research.model_intents import authorize_context_extension
        return authorize_context_extension(record['execution'],execution,source,session_id)


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"缺少有效的{label}")
    return value.strip()


def _strings(obj, key, empty=False):
    values = obj.get(key)
    if not isinstance(values, list) or (not empty and not values) or len(values) > 40:
        raise ValueError(f"{key}应为{'不超过40项的' if empty else '1至40项的'}字符串列表")
    return [_text(value, key) for value in values]


def _descriptions(value, key):
    rows = value.get(key)
    if isinstance(rows, dict):
        rows = [{name: item} for name, item in rows.items()]
    if isinstance(rows, list):
        rows = [json.dumps(row, ensure_ascii=False) if isinstance(row, dict) and row else row for row in rows]
    return _strings({key: rows}, key)


def _objects(obj, key, fields, empty=False, limit=40):
    values = obj.get(key)
    if (not isinstance(values, list) or (not empty and not values) or len(values) > limit
            or any(not isinstance(value, dict) for value in values)):
        raise ValueError(f"{key}须包含有效的结构化条目")
    return [{field: _text(value.get(field), f"{key}.{field}") for field in fields} for value in values]


def _resolutions(value, issues):
    resolutions = _objects(value, "resolutions", ("id", "change", "status"), empty=True,
                           limit=max(40, len(issues)))
    addressed = [entry["id"] for entry in resolutions]
    expected = {entry["id"] for entry in issues}
    if len(set(addressed)) != len(addressed) or set(addressed) != expected:
        raise ValueError("必须逐项答复每一条思路缺陷；应答ID=" + ",".join(sorted(expected))
                         + "；缺少=" + ",".join(sorted(expected-set(addressed)))
                         + "；未知=" + ",".join(sorted(set(addressed)-expected))
                         + "；重复=" + ",".join(sorted({key for key in addressed if addressed.count(key)>1})))
    if any(entry["status"] not in ("resolved", "limitation", "unresolved") for entry in resolutions):
        raise ValueError("缺陷状态须为 resolved、limitation 或 unresolved")
    return resolutions


def _requirement_index(source):
    parts = [item.strip() for item in re.split(r'(?<=[。！？；!?])|\n+', source) if item.strip()]
    return {f'U{i}':part for i,part in enumerate(dict.fromkeys(parts),1)}


def _evidence(value, source, key, fields, empty=False):
    rows = value.get(key)
    anchors = _requirement_index(source)
    if isinstance(rows,list):
        rows = [{**row, 'quote':anchors.get(row['requirement_id'])} if isinstance(row,dict)
                and isinstance(row.get('requirement_id'),str) else row for row in rows]
    checked = _objects({key:rows}, key, ('quote',*fields), empty=empty, limit=len(anchors))
    if any(item['quote'] not in source for item in checked):
        raise ValueError('证据必须引用提供的真实需求编号或逐字引用用户原文')
    return checked


def _whole_request(checked, source):
    expected = set(_requirement_index(source).values())
    quoted = [entry["quote"] for entry in checked]
    if len(quoted) != len(expected) or set(quoted) != expected:
        raise ValueError("原文每个需求编号都须完整核对且只能出现一次")


def _plan(value, source, resolutions, execution):
    if 'source' in value or 'scenario' in value and 'scene' not in value:
        raise ValueError('当前是实施方案阶段，不是模型定义。请按plan格式完整返回kind/mechanisms/variables/data/assumptions/limitations/scene/observables/verification/criteria/coverage；不要source、scenario或占位代码。')
    kind = value.get("kind")
    if kind not in ("stocks", "agents", "hybrid", "program"):
        raise ValueError("方案缺少受支持的模型类型")
    if kind=='program' and execution.get('model_id'):
        raise ValueError('程序方案须走自建受管入口，不能替代选定的原生模型')
    fields = ("variables", "data", "assumptions", "limitations", "verification")
    custom = not execution.get("model_id")
    raw_mechanisms = value.get("mechanisms")
    if custom and isinstance(raw_mechanisms, list) and raw_mechanisms and isinstance(raw_mechanisms[0], dict):
        rule_refs = _equation_refs(raw_mechanisms,kind)
        mechanisms = [entry["mechanism"] for entry in rule_refs]
    else:
        mechanisms = _strings(value, "mechanisms")
        rule_refs = _legacy_rule_refs(value, mechanisms,kind) if custom else None
    if len(set(mechanisms)) != len(mechanisms):
        raise ValueError("每项演化机制只声明一次，可以在同一项列出多条方程路径")
    scene = value.get("scene")
    if not isinstance(scene, dict) or not scene:
        scene = _text(scene, "场景定义")
    observables = value.get("observables")
    details = {}
    if isinstance(observables, dict):
        details = observables
        observables = list(observables)
    elif isinstance(observables, list):
        details = {item["name"]: item for item in observables
                   if isinstance(item, dict) and isinstance(item.get("name"), str)}
        observables = [item.get("name") if isinstance(item, dict) else item for item in observables]
    plan = {"kind": kind, "mechanisms": mechanisms, **{key: _descriptions(value, key) for key in fields},
            "scene": scene, "observables": _strings({"observables": observables}, "observables"),
            "coverage": _evidence(value, source, "coverage", ("role", "implementation", "test")),
            "resolutions": resolutions}
    if details:
        plan["observable_details"] = details
    scale = execution.get("scale_requested", {})
    if custom and kind == "stocks" and scale.get("granularity") == "individual":
        raise ValueError("原文要求逐主体建模，方案不能选择无实际个体的纯存量模型")
    if custom and kind != "stocks" and scale.get("maximize") and not scale.get("entities"):
        from ..limits import limits
        target = value.get("population_target")
        if type(target) is not int or not 1 <= target <= limits().array_entities:
            raise ValueError("最大可行规模需要明确给出正整数 population_target，按当前容量与实际规则决定")
        plan["population_target"] = target
    from ..custom_models import NAME
    for name in plan["observables"]:
        valid = NAME.fullmatch(name) if custom else re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name)
        if not valid or name == "sim_t":
            raise ValueError(f"观测字段 {name[:70]!r} 不能编译。observables 每项只写一个数值字段名，例如 mean_load。"
                             "解释和单位写在 variables；时钟、随机种子与主体帧由平台保存。")
    if custom and kind!='program' and len(plan["observables"]) > 32:
        raise ValueError("自建模型最多声明32个实际数值观测字段")
    if len(set(plan["observables"])) != len(plan["observables"]):
        raise ValueError("计划观测量重复")
    _whole_request(plan["coverage"], source)
    plan["criteria"] = criteria_for_plan(value.get("criteria"), plan["observables"])
    if any("step" in row and row["step"] > execution.get("ticks", 10000)
           for row in plan["criteria"]):
        raise ValueError("指定步验收超出本轮实际运行步数")
    if kind=='program' and execution.get('dt') is not None:
        from math import isclose
        dt=execution['dt']
        for row in plan['criteria']:
            if row['check']=='at_time' and not 0 <= row['time'] <= execution.get('ticks',10000)*dt:
                raise ValueError('指定时刻验收超出本轮实际运行区间')
            if row['check']=='at_time' and not isclose(round(row['time']/dt)*dt,row['time'],rel_tol=0,abs_tol=row['time_atol']):
                raise ValueError('program的at_time须对应实际宏步观测；步间事件时点用event_time核对事件日志，不伪造或插值观测')
    available = {item["id"] for item in plan["criteria"]}
    for raw, row in zip(value["coverage"], plan["coverage"]):
        ids = raw.get("criteria", [])
        if (not isinstance(ids, list) or any(not isinstance(i, str) or i not in available for i in ids)
                or row["role"] not in ("mechanism", "outcome", "input", "setting", "delivery", "disclosure",'research')):
            raise ValueError("原文对应条目缺少有效类型或数值检查编号")
        if row["role"] in ("mechanism", "outcome") and not ids:
            raise ValueError("原文机制与结局要求须关联事前数值检查")
        if row['role']=='research':
            research=execution.get('research',{})
            if not research.get('research_intent_id') or research.get('phase')!='baseline_model_only':
                raise ValueError('research职责须有实际冻结研究意图，不能借此跳过原文验收')
            row['research_intent_id']=research['research_intent_id']
            row['research_stages']=research['stage_rule']
        row["criteria"] = ids
    if execution.get('research') and not any(row['role']=='research' for row in plan['coverage']):
        raise ValueError('研究方案须将校准/独立验证/科研报告条款明确绑定research职责；基线数值检查不能替代后续研究')
    if custom:
        evolution = [entry for entry in rule_refs if _advances_state(entry,kind)]
        if not evolution:
            raise ValueError("自建模型至少需要一项实际状态演化规则")
        plan["mechanisms"] = [entry["mechanism"] for entry in evolution]
        plan["rule_refs"] = evolution
        support = [entry for entry in rule_refs if not _advances_state(entry,kind)]
        if support:
            plan["support_refs"] = support
        runtime = sorted({path for row in rule_refs for path in row["paths"] if _RUNTIME_PATH.fullmatch(path)})
        if 'execution.research' in runtime:
            research=execution.get('research',{})
            if not research.get('research_intent_id') or research.get('phase')!='baseline_model_only':
                raise ValueError('execution.research支撑引用须有真实冻结研究意图及baseline_model_only阶段，不能替代模型演化证据')
        if runtime:
            if kind == "stocks" and any(path.startswith("state_frames.") for path in runtime):
                raise ValueError("纯存量模型不能保存逐主体状态；须核对方案中要求的回放")
            plan["runtime_refs"] = runtime
    from ..research.diagnostic_bindings import plan_bindings
    bindings=plan_bindings(execution.get('research',{}).get('diagnostics',[]),plan,value.get('diagnostic_bindings'))
    if bindings:plan['diagnostic_bindings']=bindings
    return plan


def _advances_state(entry,kind=None):
    if kind=='program':
        return any(_PROGRAM_SOURCE.fullmatch(path) and path not in
                   ('source.initialize','source.observe','source.frame','source.validate') for path in entry['paths'])
    return any(_EVOLUTION_PATH.fullmatch(path) for path in entry["paths"])


def _equation_refs(raw,kind=None):
    if not isinstance(raw, list) or not raw or len(raw) > 40:
        raise ValueError("自建模型须给出1至40项有实际演化方程的关键机制")
    refs = []
    for row in raw:
        if not isinstance(row, dict):
            raise ValueError("机制映射须为对象")
        mechanism = _text(row.get("mechanism"), "机制名")
        paths = list(dict.fromkeys(_EXECUTION_PARAMETER.sub(r"parameters.\1", path) for path in _strings(row, "paths")))
        patterns=(_PROGRAM_SOURCE,_PROGRAM_SUPPORT,_SUPPORT_PATH,_RUNTIME_PATH) if kind=='program' else (_EVOLUTION_PATH,_SUPPORT_PATH,_RUNTIME_PATH)
        invalid = [path for path in paths if not any(pattern.fullmatch(path) for pattern in patterns)]
        if invalid:
            guidance = ("程序实际演化引用source.advance或实际辅助函数，方程/人口引用equations.英文ID、populations.英文ID；"
                        "参数和指标引用parameters.英文名、observables.英文名。ID以英文字母开头，只含字母/数字/下划线且最多40字符，中文类别放label。"
                        if kind == 'program' else
                        "实际演化可用 rates.backlog 或 agents.update.load；可附确切的初态、局部查询、参数和观测字段。")
            raise ValueError(f"机制 {mechanism[:100]!r} 的路径 {invalid[:3]!r} 不是模型证据字段。"
                             + guidance +
                             "时钟、种子、干预与导出由执行记录核对。")
        refs.append({"mechanism": mechanism, "paths": paths})
    return refs


def _legacy_rule_refs(value, mechanisms,kind=None):
    refs = _equation_refs(value.get("rule_refs"),kind)
    if len(refs) != len(mechanisms) or {row["mechanism"] for row in refs} != set(mechanisms):
        raise ValueError("机制与 rule_refs 未逐项对应。请在 mechanisms 中直接填写 "
                         '{"mechanism":"机制说明","paths":["agents.update.load"]}，每项只写一次。')
    return refs


def create_design(source, _parsed, execution, contract, audit, *, session_id=None, deadline, plan_check=None,
                  memory_scope=None, design_id=None, revise_from=None,revise_proposal=False):
    """Resume only validated stages bound to this exact request, session and execution."""
    identity = {"request": source, "session_id": session_id, "source_fingerprint": source_fingerprint(),
                "execution_sha256": _digest(execution), "memory_scope": memory_scope}
    if revise_from:
        if design_id:
            raise ValueError("首次修订用revise_from；之后只用新返回的design_id续接")
        from .design_revision import fork_revision
        design_id = fork_revision(revise_from, source, execution, session_id, memory_scope,
                                  revise_proposal=revise_proposal)
        # A lost revision response must recover the active child, not reopen
        # the blocked parent or start the same research from scratch.
        index = data_root() / 'model_designs' / 'pending' / (_digest(identity) + '.json')
        with file_lock(index.with_suffix('.lock'), timeout=.1):
            atomic_json(index, {'design_id':design_id})
    if design_id is None:
        # The client may lose the response when a worker dies. An identical retry recovers
        # only an unfinished design; a completed prior request never replaces a new run.
        index = data_root() / "model_designs" / "pending" / (_digest(identity) + ".json")
        with file_lock(index.with_suffix(".lock"), timeout=.1):
            if index.exists():
                candidate = load_design(read_json(index)["design_id"], session_id)
                if (candidate.get("status") in ("reviewing", "pending")
                        and all(candidate.get(key) == value for key, value in identity.items())):
                    design_id = candidate["design_id"]
            if design_id is None:
                design_id = "MD-" + uuid.uuid4().hex
                record = {"design_id": design_id, "status": "reviewing", **identity,
                          "execution": execution, "contract": contract,
                          "created_at": datetime.now(timezone.utc).isoformat(),
                          "prompt_protocol": "phased_v5", "stages": []}
                atomic_json(_path(design_id), record)
                atomic_json(index, {"design_id": design_id})
    path = _path(design_id)
    with file_lock(path.with_suffix(".lock"), timeout=.1):
        record = load_design(design_id, session_id)
        if any(record.get(key) != value for key, value in identity.items()):
            raise ValueError("原文、会话、执行设置、记忆范围或平台版本已变化，请重新审查方案")
        if record["status"] == "approved":
            return approved_plan(design_id, source, execution, session_id, record=record)
        if record["status"] == "blocked":
            return record
        if record.get("prompt_protocol") != "phased_v5":
            raise ValueError("旧版方案没有可验证阶段检查点，须重新审查")
        checkpoint = DesignCheckpoint(record, path, audit, deadline)
        if record.get("inflight"):
            record.setdefault("interruptions", []).append(record.pop("inflight"))
        # Freeze the first contract's resource snapshot and reference context across calls.
        return _advance_design(source, _parsed, execution, record["contract"], audit,
                               session_id, deadline, plan_check, memory_scope, checkpoint)


def _advance_design(source, _parsed, execution, contract, audit, session_id, deadline,
                    plan_check, memory_scope, checkpoint):
    record = checkpoint.record
    save = checkpoint.save
    partial = execution.get('coverage', {}).get('status') == 'partial'
    scope = execution.get("coverage", {}).get("status")
    literature_mode = literature.requested(source)
    research = None

    def stage(key, label, inputs, validate, prompt=None):
        emit(label)
        messages = [
            {"role": "system", "content": prompt or design_prompt(
                key, contract, scope, custom=not execution.get("model_id"), literature="literature" in inputs)},
            {"role": "user", "content": json.dumps({"original_request": source, "requirement_index":_requirement_index(source),
                                                     **({} if key in ('literature_paper','literature_passages') else {"execution":execution}),
                                                     **inputs}, ensure_ascii=False)},
        ]
        return checkpoint.call(key, messages, validate, complete)

    def concept(value):
        return {"approach": _text(value.get("approach"), "建模思路"),
                **{key: _strings(value, key) for key in ("mechanisms", "assumptions", "risks")},
                "alternatives": _objects(value, "alternatives", ("structure", "limitation"))}

    def critique(value):
        issues = _objects(value, "issues", ("id", "severity", "problem", "fix"), empty=True)
        if len({item["id"] for item in issues}) != len(issues):
            raise ValueError("缺陷ID必须唯一")
        if any(item["severity"] not in ("critical", "limitation", "runtime") for item in issues):
            raise ValueError("缺陷类型须为 critical、limitation 或 runtime")
        return issues

    def review(value, plan):
        issues = _strings(value, "issues", empty=True)
        checks = _evidence(value, source, "checks", ("verdict", "evidence"), empty=True)
        criteria = _objects(value, "criteria", ("id", "verdict", "evidence"), empty=True, limit=len(plan["criteria"]))
        binding_ids={row['id'] for row in plan.get('diagnostic_bindings',[])}
        diagnostic_checks=(_objects(value,'diagnostic_checks',('id','verdict','evidence'),empty=True,limit=len(binding_ids))
                           if binding_ids else [])
        if any(row['id'] not in binding_ids or row['verdict'] not in ('grounded','insufficient') for row in diagnostic_checks):
            raise ValueError('消融实现复核须引用实际绑定ID并使用grounded或insufficient')
        approved = value.get("approved")
        if type(approved) is not bool or approved == bool(issues):
            raise ValueError("审查结论、问题列表或原文覆盖证据不一致")
        if any(row["verdict"] not in ("ready", "disclosed", "gap") for row in checks):
            raise ValueError("需求复核结果须为 ready、disclosed 或 gap")
        if any(row["verdict"] not in ("grounded", "insufficient") for row in criteria):
            raise ValueError("数值校核结果须为 grounded 或 insufficient")
        if approved:
            _whole_request(checks, source)
            expected = {criterion["id"] for criterion in plan["criteria"]}
            if len(criteria) != len(expected) or {row["id"] for row in criteria} != expected:
                raise ValueError("通过时每条事前数值检查都须独立核对")
            if (len(diagnostic_checks)!=len(binding_ids) or {row['id'] for row in diagnostic_checks}!=binding_ids
                    or any(row['verdict']!='grounded' for row in diagnostic_checks)):
                raise ValueError('通过时每项消融实现绑定须独立复核参数、实际方程与观测，不能跳过或放宽科学要求')
            roles = {row["quote"]: row["role"] for row in plan["coverage"]}
            if any(row["verdict"] == "gap" or (
                    row["verdict"] == "disclosed" and roles[row["quote"]] != "disclosure" and not partial)
                    for row in checks) or any(row["verdict"] != "grounded" for row in criteria):
                raise ValueError("存在未满足的原文要求或无有效依据的检查，不能通过方案")
        return {"approved": approved, "issues": issues, "checks": checks, "criteria": criteria,
                **({'diagnostic_checks':diagnostic_checks} if binding_ids else {})}

    def check_plan(value):
        plan = _plan(value, source, revision["resolutions"], execution)
        if research is not None:
            plan["literature_sha256"] = _digest(research)
            plan["literature_decisions"] = decisions_for(value, plan, research)
            if research["cards"] and value.get("literature_discussion"):
                discussion = _text(value["literature_discussion"], "文献讨论")
                missing = unlisted_references(discussion, research["cards"], research["evidence"])
                if missing:
                    raise ValueError("文献讨论引用了未入选的编号：" + "、".join(missing))
                plan["literature_discussion"] = discussion
            if execution.get("model_id"):
                available = execution.get("effective_inputs") or {}
                for item in plan["literature_decisions"]:
                    if item["target"].startswith("parameters.") and item["target"].split(".", 1)[1] not in available:
                        raise ValueError(f"文献决策目标 {item['target']} 不在本轮实际原生模型参数中")
        if plan_check:
            plan_check(plan)
        return plan

    def check_concept(value):
        result = concept(value)
        queries = literature.queries_from(value.get("literature_queries"), mode=literature_mode)
        if queries:
            result["literature_queries"] = queries
        return result

    try:
        idea = stage("concept", "提出建模思路", {"literature_mode": literature_mode}, check_concept)
        critique_input = {"concept": idea}
        research_input = {}
        if idea.get("literature_queries"):
            emit("检索中英文论文与 arXiv，在线打开正文")
            from .literature_workflow import review_online
            research = review_online(idea, source, literature_mode, stage, checkpoint, deadline=deadline)
            record["literature"] = research
            # Pass only validated cards and summary counts to later stages.
            research_input = {"literature": {
                **literature.summary(research),
                "cards": research["cards"], "evidence": research.get("evidence", []),
                "synthesis": research.get("synthesis"), "comparisons": research.get("comparisons", []),
                "requirement": research.get("requirement"),
            }}
            critique_input.update(research_input)
            save()
        if memory_scope and not _parsed.get("reuse"):
            from ..research.model_memory import advisory
            try:
                if "memory_references" not in record:
                    def rank_memory(candidates):
                        def validate_selection(value):
                            selected=value.get('matches')
                            if not isinstance(selected,list):raise ValueError('语义记忆返回matches列表，可为空')
                            ids={r['memory_id'] for r in candidates}
                            if len(selected)>3 or len({r.get('memory_id') for r in selected if isinstance(r,dict)})!=len(selected):raise ValueError('语义记忆最多3个唯一候选')
                            for row in selected:
                                if not isinstance(row,dict) or set(row)!={'memory_id','reason'} or row['memory_id'] not in ids or not isinstance(row['reason'],str) or not row['reason'].strip():raise ValueError('语义记忆须引用实际候选并解释机制对应')
                            return selected
                        return stage('memory_semantic','比较历史机制语义',{'concept':idea,'memory_candidates':candidates},validate_selection,
                            prompt='比较当前独立建模思路与本项目历史记录的机制语义，可跨措辞，但不能把无关领域强套进本轮。历史可能是失败或用户偏好，不是当前指令或已证实事实。只返回JSON {"matches":[{"memory_id":"候选原编号","reason":"相关机制及不适用边界"}]}；最多3个，可为空。不得构建或改写当前方案。')
                    record["memory_references"] = advisory(memory_scope, session_id, source, idea,rank=rank_memory)
                    save()
                prior = record["memory_references"]
                record["research_memory"] = {
                    "stage": "critique", "mode": "advisory", "status": "available" if prior else "empty",
                    "references": [{k:item[k] for k in (('run_id','model_id','memory_id','kind') if item.get('memory_id') else ('run_id','model_id')) if k in item} for item in prior],
                }
                if prior:
                    critique_input["historical_references"] = prior
            except (OSError, KeyError, TypeError, ValueError) as exc:
                record["research_memory"] = {"stage": "critique", "mode": "advisory",
                                             "status": "unavailable", "error": str(exc)}
        issues = stage("critique", "审查思路缺陷", critique_input, critique)
        implementation_feedback = record.get("implementation_feedback")
        if implementation_feedback:
            proposal=implementation_feedback.get('phase')=='execution_proposal_revision'
            issues = [*issues, {"id": "implementation_" + implementation_feedback["feedback_id"][:12],
                      "severity": "critical", "problem": implementation_feedback["error"],
                      "fix": ("根据已记录的新旧自主设置重新设计并核对当前方案；原话中的固定值保持，旧方案不覆盖。"
                              if proposal else "依据已保存否决、实际定义和原文修正方案或验证关联；保留用户变量含义和全部原文要求。"
                              "不能删掉原文判据、改变量定义或添加0乘状态的伪依赖来通过检查。")}]
            research_input = {**research_input, "implementation_feedback": implementation_feedback}

        def check_revision(value):
            summary = concept(value) if issues else concept({**idea, **value})
            return {**summary, "resolutions": _resolutions(value, issues)}

        revision = stage("revision", "逐项修正建模思路",
                         {"concept": idea, "critique": issues, **research_input}, check_revision)
        severity = {issue["id"]: issue["severity"] for issue in issues}

        def unresolved(value):
            return [item["change"] for item in value["resolutions"]
                    if severity[item["id"]] == "critical" and item["status"] != "resolved"]

        blockers = unresolved(revision)
        if blockers:
            revision = stage("evidence_recheck", "核对未解决缺陷的执行证据",
                             {"concept": revision, "critique": issues, "prior_revision": revision, **research_input},
                             check_revision)
            blockers = unresolved(revision)
        if blockers:
            raise ValueError("方案存在未解决的关键缺陷：" + "；".join(blockers))
        inputs = {"revision": revision,
                  "runtime_checks_to_plan": [issue for issue in issues if issue["severity"] == "runtime"],
                  **research_input}
        for attempt in range(2):
            plan = stage("plan", "编制可执行建模方案", inputs, check_plan)
            review_context = dict(research_input)
            if implementation_feedback:
                # The rejected source belongs to the previous implementation.
                # Reviewing a new plan against those old bytes creates a cycle:
                # new source cannot be built until the new plan is approved.
                review_context["implementation_feedback"] = {
                    key: implementation_feedback[key] for key in
                    ("feedback_id", "design_id", "phase", "error", "source_fingerprint")
                    if key in implementation_feedback
                }
                review_context["implementation_feedback"].update(
                    authority="historical_rejection_only",
                    current_implementation="not_built_yet; validate the newly built source after plan approval",
                )
            verdict = stage("review", "审查方案完整性与准确性",
                            {"plan": plan, "review_round": attempt + 1,
                             "prior_review_issues": inputs.get("review_issues", []),
                             "issues_to_recheck": issues, "revision": revision, **review_context},
                            lambda value: review(value, plan))
            if verdict["approved"] or attempt:
                break
            inputs["rejected_plan"] = plan
            inputs["review_issues"] = verdict["issues"]
        scope = execution.get("coverage", {}).get("status")
        record.update(status="approved" if verdict["approved"] else "blocked",
                      approval_scope={"partial":"diagnostic","exercise":"exercise"}.get(scope,"original_request"), plan=plan,
                      plan_sha256=_digest(plan), review=verdict)
        record.pop("error", None)
        record.pop("pause_reason", None)
        record.pop("last_error", None)
        record.pop("inflight", None)
    except PendingStage as exc:
        record.update(status="pending", resume_available=True, continuation_note=str(exc))
    except Exception as exc:
        record.update(status="blocked", error=f"{type(exc).__name__}: {exc}")
        record.pop("inflight", None)
    record["resume_available"] = record["status"] == "pending"
    save()
    return record


def approved_plan(design_id, source, execution, session_id, *, record=None):
    record = record or load_design(design_id, session_id)
    if record.get("status") != "approved" or not record.get("review", {}).get("approved"):
        reasons = record.get("review", {}).get("issues") or [record.get("error") or "方案尚未通过审查"]
        raise ValueError("建模方案未通过：" + "；".join(reasons))
    check_design_context(record,design_id,source,execution,session_id)
    if record["plan_sha256"] != _digest(record["plan"]):
        raise ValueError("已审查方案的内容校验失败")
    if record["plan"].get("literature_sha256") and record["plan"]["literature_sha256"] != _digest(record.get("literature")):
        raise ValueError("已审查文献证据的内容校验失败")
    return record


def check_definition(plan, definition):
    if plan["kind"] != definition["kind"]:
        raise ValueError("DSL模型类型偏离已审查方案")
    missing = set(plan["observables"]) - set(definition["observables"])
    if missing:
        raise ValueError("DSL遗漏审查方案中的观测量：" + "、".join(sorted(missing)))
    if definition['kind']=='program':
        from ..program_evidence import check_plan
        check_plan(plan,definition)
        return
    from ..scene_contract import reference
    from ..custom_models import aggregate_names

    for decision in plan.get("literature_decisions", []):
        if decision["target"].startswith("parameters."):
            reference(definition, decision["target"])
    for evidence in plan.get("support_refs", []):
        for path in evidence["paths"]:
            if not _RUNTIME_PATH.fullmatch(path):
                reference(definition, path)
    dynamic = set()
    changing_attributes = set()
    for mechanism in plan.get("rule_refs", []):
        changing = False
        for path in mechanism["paths"]:
            if _RUNTIME_PATH.fullmatch(path):
                continue
            evidence = reference(definition, path)
            if not _EVOLUTION_PATH.fullmatch(path):
                continue
            expr = ast.parse(str(evidence), mode="eval").body
            name = path.rsplit(".", 1)[-1]
            stock = path.startswith("rates.")
            if isinstance(expr, ast.Constant) and (not stock or expr.value == 0):
                continue
            if isinstance(expr, ast.Name) and not stock and expr.id == name:
                continue
            changing = True
            if stock:
                dynamic.add(name)
            else:
                changing_attributes.add(name)
        if not changing:
            raise ValueError(f"关键机制没有作用于状态的演化表达式：{mechanism['mechanism']}")
    measures = (definition.get("agents") or {}).get("measures", {})
    dynamic.update(aggregate_names(changing_attributes))
    for name, expression in measures.items():
        dependencies = {node.id for node in ast.walk(ast.parse(str(expression), mode="eval")) if isinstance(node, ast.Name)}
        if dependencies & changing_attributes:
            dynamic.update(aggregate_names([name]))
    numerical = {spec["id"]: spec["fields"] for spec in plan.get("criteria", [])}
    for row in plan["coverage"]:
        if row["role"] != "mechanism":
            continue
        fields = {field for check in row["criteria"] for field in numerical[check]}
        for field in fields:
            expr = ast.parse(str(definition["observables"][field]), mode="eval")
            if dynamic & {node.id for node in ast.walk(expr) if isinstance(node, ast.Name)}:
                break
        else:
            raise ImplementationMismatch("用于验证机制的观测量未读取实际演化的状态：" + row["quote"],
                {"requirement": row["quote"], "criteria": row["criteria"],
                 "observables": {field: definition["observables"][field] for field in sorted(fields)},
                 "available_dynamic_dependencies": sorted(dynamic),
                 "instruction": "核对方案的criteria关联和实际观测定义。规模/格数只能证明规模，不能单独验证动力学。"
                                "如关联错误，用实际反馈修订方案；禁止为了通过依赖检查改写观测含义。"}, definition)
