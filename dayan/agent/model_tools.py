"""Real language-to-model compilation and executable registration."""
import ast
import json
import time
from contextlib import ExitStack
from copy import deepcopy

from ..custom_models import register, validate_definition, population_plan
from ..llm_client import complete
from ..research.requirements import empirical_validation_requested, extract_request
from ..scene_contract import validate_scene, review_definition, SemanticMismatch
from .model_design import approved_plan, check_definition, create_design
from ..research.literature import summary as literature_summary
from ..scaling import capacity, check_scale, scale_intent
from .progress import emit
from .build_checkpoint import build_checkpoint
from .design_checkpoint import PendingStage
from .design_revision import ImplementationMismatch, record_feedback

from .model_prompts import DSL_CONTRACT as _DSL_CONTRACT, DSL_DESIGN, GRID_REDUCTIONS, compilation_prompt
from .program_prompts import CONTRACT as PROGRAM_CONTRACT, DESIGN as PROGRAM_DESIGN
DSL_CONTRACT=_DSL_CONTRACT+'\n另一可选合同（kind=program，与DSL字段不能混用）：\n'+PROGRAM_CONTRACT


def _execution_parameters(definition, parsed, parameters):
    values=dict(parameters or {})
    implied=parsed.get('inferred_population_parameter')
    if definition.get('kind')=='program' and implied and implied not in definition.get('parameters',{}):
        # The actual group/port count is checked separately by check_scale.
        # A natural-language population quantity does not name a Python parameter.
        values.pop(implied,None)
    return values


def _checked_definition(definition, source, parsed, parameters):
    if isinstance(definition, dict) and isinstance(definition.get("scenario"), dict) and source:
        definition = deepcopy(definition)
        definition["scenario"]["source_request"] = source
    definition = validate_definition(definition)
    program=definition['kind']=='program'
    for key in ("mechanisms", "assumptions", "limitations"):
        items = definition.get(key, [])
        if not isinstance(items, (list, tuple)) or any(not isinstance(item, str) for item in items):
            raise ValueError(f"definition.{key} 必须为字符串列表")
    if "网格局部交互" in parsed["mechanisms"] and not program:
        if not (definition.get("agents") or {}).get("grid"):
            raise ValueError("原文要求真实局部邻域，须使用 agents.grid 声明与读取逐格局部查询，或运行适配的原生模型")
        if "网格局部交互" not in definition.get("mechanisms", []):
            # A validated grid reads its local queries in the update rules.
            definition["mechanisms"] = [*definition.get("mechanisms", []), "网格局部交互"]
    missing = set(parsed["mechanisms"]) - set(definition.get("mechanisms", []))
    if missing and not program:
        raise ValueError("缺少明确机制：" + "、".join(sorted(missing)))
    if source:
        for field, expected in parsed.get("initial_state", {}).items():
            if program:
                if field not in definition['observables']:
                    raise ValueError('用户指定初值须保留同名实际观测以便初态核验：'+field)
                continue
            rule = definition.get("initial_state", {}).get(field)
            try:
                actual = ast.literal_eval(str(rule))
            except (ValueError, SyntaxError):
                actual = None
            if type(actual) not in (int, float) or actual != expected:
                raise ValueError(f"用户明确指定的状态初值必须准确实现：initial_state.{field}={expected}")
        required = set(_execution_parameters(definition,parsed,parameters)) | {
            name for change in parsed["interventions"] for name in change["params"]
        }
        missing = required - set(definition.get("parameters", {}))
        if missing:
            raise ValueError("用户参数未保留为有效同名参数：" + "、".join(sorted(missing)))
        validate_scene(definition, source)
    return definition


def build_model(request=None, definition=None, parameters=None, ticks=None, seed=None, dt=None,
                data_bindings=None, last_run=None, seeds=None, design_id=None, research_intent_id=None,
                continuation_token=None):
    return _author_model("build_model", None, None, request=request, definition=definition, parameters=parameters,
                         ticks=ticks, seed=seed, dt=dt, data_bindings=data_bindings,
                         last_run=last_run, seeds=seeds, design_id=design_id,research_intent_id=research_intent_id,
                         continuation_token=continuation_token)


def validate_model(definition, parameters=None, ticks=None, seed=None, dt=None,
                   data_bindings=None, last_run=None, seeds=None, design_id=None,research_intent_id=None,continuation_token=None):
    """预检显式DSL、原文约束与运行选项。返回结构结果和表达式字段，未注册、运行或调用LLM。"""
    return _author_model("validate_model", None, None, definition=definition, parameters=parameters, ticks=ticks,
                         seed=seed, dt=dt, data_bindings=data_bindings, last_run=last_run, seeds=seeds,
                         design_id=design_id,research_intent_id=research_intent_id,continuation_token=continuation_token)


def design_model(request=None, parameters=None, ticks=None, seed=None, dt=None,
                 data_bindings=None, last_run=None, seeds=None, design_id=None, revise_from=None,research_intent_id=None,
                 revise_proposal=False,continuation_token=None):
    return _author_model("design_model", None, None, request=request, parameters=parameters,
                         ticks=ticks, seed=seed, dt=dt, data_bindings=data_bindings,
                         last_run=last_run, seeds=seeds, design_id=design_id, revise_from=revise_from,
                         research_intent_id=research_intent_id,revise_proposal=revise_proposal,
                         continuation_token=continuation_token)


def call_native_model(tool, arguments, original_text, session_id, *, memory_scope=None):
    """Pass the durable DSH user message separately from public model arguments."""
    if not original_text.strip():
        raise ValueError("缺少本轮DSH用户原文，不能确认建模需求")
    args = dict(arguments)
    request = args.get("request")
    implicit = tool == "design_model" or (tool == "build_model" and "request" not in args)
    valid = isinstance(request, str) and request.strip()
    if tool in ("design_model", "build_model") and args.get("definition") is None and (valid or request is None and implicit):
        args["request"] = original_text
    if memory_scope is None:
        from ..research.model_memory import native_scope
        memory_scope = native_scope(session_id)
    return _author_model(tool, original_text, session_id, memory_scope=memory_scope, **args)


def _author_model(tool,bound_request,session_id,/,*,memory_scope=None,continuation_token=None,**arguments):
    from .model_continuation import restore,seal
    result=None
    try:
        source=bound_request if bound_request is not None else arguments.get('request')
        if continuation_token is not None:
            arguments,source,memory_scope=restore(tool,continuation_token,arguments,source,session_id,memory_scope)
            bound_request=source
        if arguments.get('ticks') is None:arguments['ticks']=100
        result=_author_model_impl(tool,bound_request,session_id,memory_scope=memory_scope,**arguments)
        return seal(result,source,session_id,memory_scope)
    except Exception as exc:
        failure={'ok':False,'error':f'{type(exc).__name__}: {exc}',
                 'llm_calls':(result or {}).get('llm_calls',(result or {}).get('payload',{}).get('llm_calls',[]))}
        if result is not None:failure['payload']=result.get('payload',{})
        return failure


def _author_model_impl(tool, bound_request, session_id, /, *, request=None, definition=None, parameters=None,
                  ticks=100, seed=None, dt=None, data_bindings=None, last_run=None, seeds=None,
                  design_id=None, memory_scope=None, revise_from=None,research_intent_id=None,revise_proposal=False):
    audit = []
    stack = ExitStack()
    checkpoint = None
    continuation_args = None
    design = None
    try:
        validate_only = tool == "validate_model"
        design_only = tool == "design_model"
        if design_only and revise_from and design_id == revise_from:
            # Repeating the same parent ID is unambiguous. All normal parent,
            # feedback, request, session and execution checks still run.
            design_id = None
        if type(revise_proposal) is not bool or revise_proposal and (not design_only or not revise_from):
            raise ValueError('revise_proposal只用于design_model携带revise_from显式修订自主提出的运行设置')
        if parameters is not None:
            if not isinstance(parameters,dict):
                raise ValueError('parameters须为实际运行取值对象，例如{"grid_rows":60}')
            for key,value in parameters.items():
                if isinstance(value,(dict,list,tuple)):
                    hint=(f'，该声明的默认取值为{json.dumps(value["default"],ensure_ascii=False)}'
                          if isinstance(value,dict) and 'default' in value else '')
                    raise ValueError(f'parameters.{key}须填实际运行值{hint}；type/default/unit等参数定义写入definition.parameters，'
                                     'design_model的parameters只填数值、布尔或字符串取值')
        if revise_from and not design_only:
            raise ValueError("方案修订须用design_model的revise_from参数")
        if design_only:
            if definition is not None or request is None:
                raise ValueError("design_model接收原始需求与运行选项；用同一design_id续接未完成阶段")
        elif validate_only:
            if definition is None or request is not None:
                raise ValueError("validate_model只接收显式definition")
        elif (request is None) == (definition is None):
            raise ValueError("只指定原始request或显式definition之一")
        if request is not None and (not isinstance(request, str) or not request.strip()):
            raise ValueError("request必须为非空用户需求")
        source = bound_request or request
        from ..research.model_memory import WORKBENCH_SCOPE
        memory_scope = memory_scope or WORKBENCH_SCOPE
        from .context import canonical_context
        last_run = canonical_context(last_run)
        parsed = extract_request(source or "", last_run)
        scale = scale_intent(source or "")
        if parsed["missing_context"]:
            raise ValueError("缺少上一次实际运行上下文，不能重建一个无关模型来替代")
        if parsed["unresolved_constraints"]:
            raise ValueError("有未解析的修改约束：" + "、".join(parsed["unresolved_constraints"]))
        from .scenario_tools import needs_incident_model, requests_scripted_exercise
        incident_requested=needs_incident_model(parsed) or requests_scripted_exercise(parsed)
        intent=None
        if research_intent_id:
            from ..research.model_intents import checked_intent
            intent=checked_intent(research_intent_id,source,session_id)
            if design_id is None and not revise_from:design_id=intent['state'].get('design_id')
        if empirical_validation_requested(parsed) and not intent:
            raise ValueError('原文要求校准或独立验证。先采集真实目标数据并用research_model_prepare冻结同一完整原文的研究协议，再按next_action建模；单个输入或基线运行不能替代研究。')
        from ..engine_capabilities import custom_blockers,program_blockers,program_status
        blockers = custom_blockers(parsed)
        if incident_requested:
            blockers.append('DSL没有局部人体接触、失稳倒地和伤害机制；可用program设计实际算法并验证')
        program_gaps=program_blockers(parsed)
        status=program_status()
        if blockers and (program_gaps or not status['available']):
            raise ValueError('自定义执行合同缺口：DSL：'+'、'.join(blockers)+'；程序：'+
                             '、'.join(program_gaps or [status.get('reason','求解环境不可用')]))
        if parsed["requires_real_data"] and not data_bindings and not intent:
            raise ValueError("需求要求现实数据；须先取得并核验数据集，不能用假设空间替代")
        options = parsed["options"]
        ticks, seed, dt = options.get("ticks", ticks), options.get("seed", seed), options.get("dt", dt)
        grid_requested = "网格局部交互" in parsed["mechanisms"] or (
            isinstance(definition, dict) and (definition.get("agents") or {}).get("grid"))
        if grid_requested:
            dt = 1.0 if dt is None else dt
        seeds = options.get("seeds", None if "seed" in options else seeds)
        if seeds is not None and (not isinstance(seeds,(list,tuple)) or not seeds):
            raise ValueError("seeds必须为非空种子列表")
        parameters = {**(parameters or {}), **parsed["parameters"]}
        from .tools import _archive_run, _coerce_seeds, _coerce_ticks, tool_ensemble
        from ..limits import limits, validate_compute
        from ..runtime import validate_run_arguments
        ticks = _coerce_ticks(ticks)
        seeds = _coerce_seeds(seeds) if seeds is not None else None
        validate_run_arguments(ticks, .1 if dt is None else dt, 0 if seed is None or seeds else seed)
        validate_compute(ticks, runs=len(seeds) if seeds else 1, seeds=len(seeds) if seeds else 1,
                         parameters=parameters, array=True)

        context = {}
        if parsed["reuse"]:
            if not last_run.get("run_id"):
                raise ValueError("修改已有模型需要真实run_id，以保留原模型方程与场景")
            prior = last_run["manifest"]
            if not prior.get("model_definition"):
                raise ValueError("原模型没有可编辑DSL规约；可调整该模型公开参数")
            context = {"model_definition": prior["model_definition"],
                       "actual_parameters": prior.get("actual", {}).get("effective_parameters"),
                       "requested": prior.get("requested")}
        execution = {**options, "parameters": parameters, "ticks": ticks, "dt": dt,
                     "seed": seed, "prior": context}
        if scale:
            execution["scale_requested"] = scale
        if parsed.get('inferred_population_parameter'):
            execution['inferred_population_parameter']=parsed['inferred_population_parameter']
        if seeds:
            execution["seeds"] = list(seeds)
        if intent:
            from ..research.model_intents import authoring_contract
            execution['research']=authoring_contract(research_intent_id,source,session_id,execution,data_bindings,seeds)
        from ..structured_inputs import prepare_bindings, port_contracts
        bound, prepared_ports, evidence = prepare_bindings(data_bindings)
        if parsed.get('requires_real_topology') and not any(asset['kind']=='geojson' for asset in prepared_ports.values()):
            raise ValueError('原文要求真实场地/地理拓扑，须绑定实际geojson端口；合成布局或均值参数不能替代')
        if parsed["requires_real_data"] and parsed["dataset_id"] and not any(
                entry["dataset_id"] == parsed["dataset_id"] for entry in [*evidence,*((intent or {}).get('protocol',{}).get('targets',{}).get('sources',[]))]):
            raise ValueError("数据映射未包含用户指定的数据集")
        for name, value in bound.items():
            if name in parameters and parameters[name] != value:
                raise ValueError(f"真实数据绑定与已明确的参数{name}数值冲突")
        design_execution = execution
        if source and (not validate_only or design_id is not None):
            from .model_delivery import delivery_contract
            design_execution = {**execution, "effective_inputs": {**parameters, **bound},
                                "data_bindings": evidence, "interventions": parsed["interventions"],
                                "structured_inputs": {name:{'contract':asset['contract'],'count':asset['count']}
                                                      for name,asset in prepared_ports.items()},
                                "delivery": delivery_contract(execution.get('research'))}
        from ..limits import authoring_wall_seconds
        deadline = time.monotonic() + authoring_wall_seconds() - 12

        def checked_size(definition, design):
            if intent:
                from ..research.model_intents import check_model
                check_model(research_intent_id,definition,(design or {}).get('plan'))
            is_program=definition['kind']=='program'
            if is_program and (program_gaps or not status['available']):
                raise ValueError('程序执行合同缺口：'+'、'.join(program_gaps or [status.get('reason','求解环境不可用')]))
            if not is_program and blockers:raise ValueError('此方案仍选择不能覆盖原文的DSL：'+'、'.join(blockers))
            if not is_program and definition.get('agents',{}).get('grid') and dt!=1:
                raise ValueError('DSL固定网格以一个MCS为一步，需dt=1；其他时钟应由program实际实现')
            inputs = {**_execution_parameters(definition,parsed,parameters), **bound}
            declared = definition.get('input_ports', {}) if is_program else {}
            actual_contracts=port_contracts(declared)
            expected_contracts={name:asset['contract'] for name,asset in prepared_ports.items()}
            if actual_contracts != expected_contracts:
                from ..structured_inputs import contract_differences
                raise ValueError('编译模型input_ports与本方案真实结构绑定不一致；不能遗漏或替换输入。字段差异：'+
                    json.dumps(contract_differences(expected_contracts,actual_contracts),ensure_ascii=False)+
                    '。按已批准方案execution.structured_inputs中的contract逐项修正定义；原生可用design_details读取，'
                    '不要修改已绑定的data_bindings、原文或运行设置来迎合错误定义。')
            if is_program:
                from ..program_models import population_plan as program_population_plan
                compiled=program_population_plan(definition,inputs,prepared_ports)
            else:
                compiled = population_plan(definition, inputs)
            target = (design or {}).get("plan", {}).get("population_target")
            check_scale({**scale, **({"entities":target} if target is not None and not scale.get("entities") else {})}, compiled)
            return compiled

        def design_next(record,*,rejected=False):
            arguments={'request':source,'parameters':parameters,'ticks':ticks,'dt':dt,'seed':seed,
                       'data_bindings':deepcopy(data_bindings or [])}
            arguments['revise_from' if rejected else 'design_id']=record['design_id']
            if seeds is not None:arguments['seeds']=list(seeds)
            if research_intent_id:arguments['research_intent_id']=research_intent_id
            if last_run.get('run_id'):arguments['last_run']={'run_id':last_run['run_id']}
            payload={**record,'executed':False,'execution_complete':False,
                     'next_action':{'action':'design_model','arguments':arguments}}
            if rejected:
                payload['revision_available']=True
                reasons=record.get('review',{}).get('issues') or [record.get('error') or '方案审查未通过']
                return {'ok':False,'error':'；'.join(reasons),'payload':payload,'design_id':record['design_id']}
            return {'ok':True,'payload':payload,'design_id':record['design_id']}

        if design_id:
            from .model_design import load_design,check_design_context
            existing=load_design(design_id,session_id)
            check_design_context(existing,design_id,source,design_execution,session_id,
                                 allow_source_evidence=existing.get('status')=='blocked')
            if existing.get('status')=='blocked':return design_next(existing,rejected=True)
            if not design_only and existing.get('status') in ('pending','reviewing'):
                return design_next(existing)

        if design_only or request is not None:
            design = None
            if design_id is None or design_only:
                contract = DSL_DESIGN + "\n" + GRID_REDUCTIONS + "\n当前资源参考为 " + json.dumps(capacity(), ensure_ascii=False)
                contract += '\n受管程序：'+json.dumps({'environment':status,'remaining':program_gaps},ensure_ascii=False)
                if status['available'] and not program_gaps:contract+='\n'+PROGRAM_DESIGN
                design = create_design(source, parsed, design_execution, contract, audit,
                                       session_id=session_id, deadline=deadline, memory_scope=memory_scope,
                                       design_id=design_id, revise_from=revise_from,revise_proposal=revise_proposal)
                design_id = design["design_id"]
                if intent:
                    from ..research.model_intents import remember_design
                    remember_design(research_intent_id,design)
                if design["status"] == "approved":
                    emit("建模方案已通过审查")
                elif design["status"] != "pending":
                    return design_next(design,rejected=True)
            # Compilation gets its own call if the completed research used most of this one.
            if design and (design_only or design["status"] == "pending"
                           or deadline - time.monotonic() < min(150, (limits().wall_seconds - 20) * .7)):
                build_args = {"request": source, "design_id": design_id, "ticks": ticks}
                if intent:build_args['research_intent_id']=research_intent_id
                for key, value in (("dt", dt), ("seed", seed), ("seeds", execution.get("seeds")),
                                   ("parameters", parameters), ("data_bindings", data_bindings)):
                    if value is not None:
                        build_args[key] = value
                if last_run.get("run_id"):
                    build_args["last_run"] = {"run_id": last_run["run_id"]}
                summary = literature_summary(design["literature"]) if "literature" in design else None
                action = "design_model" if design["status"] == "pending" else "build_model"
                return {"ok": True, "payload": {**design, "literature_summary": summary, "executed": False,
                    "next_action": {"action": action, "arguments": build_args}}}
            design = approved_plan(design_id, source, design_execution, session_id, record=design)
        else:
            design = None

        scenario_review = None
        if definition is not None:
            definition = _checked_definition(definition, source, parsed, parameters)
            if design_id is not None:
                if source is None:
                    raise ValueError("显式DSL使用审查方案时，需要DSH已绑定的用户原文；也可用request继续")
                design = approved_plan(design_id, source, design_execution, session_id)
                check_definition(design["plan"], definition)
            compiled_scale = checked_size(definition, design)
            if validate_only:
                return {"ok": True, "payload": {
                    "validation": "模型结构、证据路径、场景引用、可解析原文约束和运行预算通过；尚未执行或证明科学有效性",
                    "model_name": definition["name"], "kind": definition["kind"],
                    "parameter_names": list(definition.get("parameters", {})),
                    "observables": list(definition["observables"]),
                    "execution_scale": compiled_scale,
                    "execution": {**{key: value for key, value in execution.items() if key not in ("prior", "scale_requested", "inferred_population_parameter")},
                                  'parameters':_execution_parameters(definition,parsed,parameters)},
                    **({"scale_requested": scale} if scale else {}),
                    **({"design_id": design_id} if design else {}),
                    "semantic_review_pending": bool(source), "executed": False}}
            if source and not design:
                raise ValueError("请先完成design_model审查，再用design_id提交显式DSL")
        if design:
            continuation_args = {"design_id": design_id, "parameters": parameters, "ticks": ticks,
                                 "seed": seed, "dt": dt, "data_bindings": data_bindings, "seeds": seeds}
            if intent:continuation_args['research_intent_id']=research_intent_id
            continuation_args.update({"definition": deepcopy(definition)} if definition is not None else {"request": source})
            if last_run.get("run_id"):
                continuation_args["last_run"] = {"run_id": last_run["run_id"]}
            checkpoint = stack.enter_context(build_checkpoint(design, definition, audit, deadline))

        def review(d, compiled):
            emit("结构与设施绑定已通过，正在复核是否符合用户原文…")
            if checkpoint:
                # Hardware availability changes between calls. Keep the reviewed
                # resource snapshot, while checked_size and the solver still perform
                # fresh capacity checks before execution.
                compiled = checkpoint.operation("execution_scale", {"definition": d, "execution": design_execution},
                                                lambda _deadline: compiled, seconds=0)
            context = {**design_execution, "compiled_scale": compiled}
            if design:
                from ..research.literature import requested as literature_mode
                context["literature_review"] = {"mode": literature_mode(source), "performed": "literature" in design}
            try:
                result = review_definition(source, d, audit, context,
                                           plan=design["plan"] if design else None, deadline=deadline,
                                           checkpoint=checkpoint)
            except SemanticMismatch as exc:
                if not design:
                    raise
                raise ImplementationMismatch(str(exc), {
                    "phase": "semantic_review", "review": deepcopy(exc.review),
                    "instruction": "依据真实否决和原定义修订实施方案或方程，重新独立审核。"
                                   "保留原始需求、变量含义和验收目标；不能把同一个否决反复送审直到通过。",
                }, d) from exc
            if design:
                result["model_design"] = {"design_id": design_id, "plan_sha256": design["plan_sha256"]}
                if intent:
                    result['research_intent']={'research_intent_id':research_intent_id,
                        'protocol_sha256':intent['protocol']['sha256'],'phase':'baseline_model_only','request_complete':False}
                if "research_memory" in design:
                    result["model_design"]["research_memory"] = design["research_memory"]
                if "literature" in design:
                    result["model_design"]["literature_summary"] = literature_summary(design["literature"])
            if parsed["reuse"]:
                result["parent_run_id"] = last_run["run_id"]
            return result

        if definition is None:
            emit("按通过审查的方案构建模型")
            messages = [{"role": "system", "content": compilation_prompt(design['plan']['kind'])},
                        {"role": "user", "content": json.dumps({"原始需求": source,
                         "实际执行与数据": design_execution, "已通过审查的实施方案": design["plan"],
                         "真实实施反馈": design.get("implementation_feedback"),
                         "required_mechanism_labels":parsed['mechanisms'],
                         "编译必需的引擎字段": {"agents.grid": grid_requested,
                                              "scenario": parsed["scene_requirements"]["spatial"],
                                              "scenario.facilities所需实体类型": parsed["scene_requirements"]["features"]}},
                            ensure_ascii=False)}]
            for attempt in range(2):
                emit(f"正在{'修正' if attempt else '生成'}实际模型方程与场景合同…")
                def validate_compiled(value):
                    checked = _checked_definition(value, source, parsed, parameters)
                    check_definition(design["plan"], checked)
                    checked_size(checked, design)
                    return checked

                definition = checkpoint.call("compilation", messages, validate_compiled, complete,
                                             purpose="build-model", thinking=True)
                compiled_scale = checked_size(definition, design)
                try:
                    scenario_review = review(definition, compiled_scale)
                    break
                except (ValueError, SyntaxError) as exc:
                    if attempt == 1 or getattr(exc, "requires_design_revision", False):
                        raise
                    messages += [{"role": "assistant", "content": json.dumps(definition, ensure_ascii=False)},
                                 {"role": "user", "content": "编译回执：" + str(exc) + "。修正报错对应的字段、作用域或实际规则。其余已审查语义继续保留。重新返回可运行的完整定义JSON。"}]
        else:
            if source:
                emit("按通过审查的方案构建模型")
                scenario_review = review(definition, compiled_scale)
        build_audit = audit
        if design:
            build_audit = list({entry["call_id"]: entry for entry in
                                [*design["llm_calls"], *checkpoint.prior_audit, *audit]}.values())
        result = register(definition, source or "用户显式模型规约", build_audit, scenario_review=scenario_review)
        emit("模型与场景规约已保存，正在实际运行并归档状态…")
        acceptance = None
        if design:
            requires_entities = any(path.startswith("state_frames.") for path in design["plan"].get("runtime_refs", []))
            verified_scale = {**scale, "entities": compiled_scale["entities"], "grid": compiled_scale["grid"]}
            acceptance = {"observables": design["plan"]["observables"], "criteria": design["plan"]["criteria"],
                          "execution": {**design_execution, "verified_scale": verified_scale,
                                        **({'initial_state_check':parsed.get('initial_state',{})} if definition['kind']=='program' else {})}, "events": {},
                          "spatial": requires_entities or parsed["scene_requirements"]["spatial"]}
            scenario_review["coverage"] = {"status": "covered", "gaps": [], "limits": scenario_review.get("limitations", [])}
            if intent:
                scenario_review['coverage'].update(status='model_ready',pending_stages=['calibration','diagnostics','holdout','research_report'])
        if seeds:
            from .verification import certify_run

            def certify(rr):
                from .build_checkpoint import attach_authoring_audit
                attach_authoring_audit(rr, build_audit)
                certify_run(rr, scenario_review, {**acceptance, "execution": {**acceptance["execution"], "seed": rr.manifest["rng"]["seed"]}})

            run = tool_ensemble(result["model_id"], parameters=_execution_parameters(definition,parsed,parameters), ticks=ticks, dt=dt, seeds=seeds,
                                interventions=parsed["interventions"], data_bindings=data_bindings,
                                _certify=certify if acceptance else None, _full_frames=bool(scale.get("all_frames")),
                                _checkpoint=checkpoint)
            if run.get("ok"):
                run["payload"]["result_kind"] = "ensemble"
        else:
            run = _archive_run(result["model_id"],_execution_parameters(definition,parsed,parameters),ticks,seed,dt,parsed["interventions"],data_bindings,
                               review=scenario_review,acceptance=acceptance,full_frames=bool(scale.get("all_frames")),
                               checkpoint=checkpoint, llm_calls=build_audit)
        if not run["ok"]:
            return {**run, "model": result, "llm_calls": build_audit,
                    **({"design_id": design_id} if design else {})}
        run["payload"].update(result)
        runtime_calls=[*run['payload'].get('manifest',{}).get('llm_calls',[]),
                       *(entry for member in run['payload'].get('runs',[]) for entry in member.get('manifest',{}).get('llm_calls',[]))]
        run["payload"]["llm_calls"] = list({entry['call_id']:entry for entry in [*build_audit,*runtime_calls]}.values())
        if source:
            from ..run_store import get_store
            archive_id = run["payload"].get("analysis_id") or run["payload"].get("run_id")
            if archive_id:
                get_store().annotate(archive_id, request_text=source)
        if design:
            run["payload"]["design_id"] = design_id
            if "research_memory" in design:
                run["payload"]["research_memory"] = design["research_memory"]
            if "literature" in design:
                run["payload"]["literature_summary"] = literature_summary(design["literature"])
            from ..research.model_memory import remember_build
            run["payload"]["memory_index"] = remember_build(memory_scope, run["payload"], source)
        run["payload"]["scenario_review"] = run["payload"].get("manifest", {}).get("scenario_review", scenario_review)
        run["payload"]["warnings"] = list(run["payload"].get("warnings", [])) + [
            "此模型已实际执行；生成的机制假设与领域适用性未经过独立科学验证，不能当成已校准预测。"]
        if checkpoint:
            checkpoint.record.update(status="complete", current_stage="complete")
        if intent:
            from ..research.model_intents import complete_baseline,intent_summary
            payload=run['payload']
            baseline_id=payload.get('run_id') or next((row['run_id'] for row in payload.get('runs',[]) if row.get('run_id')),None)
            if not baseline_id:raise ValueError('研究基线未取得实际run_id，不能继续研究')
            try:
                study=complete_baseline(research_intent_id,baseline_id)
            except OSError as exc:
                payload.update(status='research_pending',research_intent_id=research_intent_id,
                    request_complete=False,execution_complete=True,
                    continuation_error=f'{type(exc).__name__}: {exc}',
                    next_action={'action':'build_model','arguments':continuation_args})
                run['validation_pass']=False
                return run
            workflow=intent_summary(research_intent_id)
            payload.update(status=workflow['status'],request_complete=workflow['request_complete'],execution_complete=True,
                research_intent_id=research_intent_id,study_id=study['study_id'],research=study,
                next_action=workflow['next_action'])
            run['validation_pass']=workflow['request_complete'] and study.get('conclusion')=='passed_declared_checks'
        return run
    except ImplementationMismatch as exc:
        feedback_id = record_feedback(design, exc.definition, exc,
                                      [*(checkpoint.prior_audit if checkpoint else []), *audit])
        arguments = {"request": source, "revise_from": design["design_id"], "parameters": parameters,
                     "ticks": ticks, "dt": dt, "seed": seed, "seeds": seeds, "data_bindings": data_bindings}
        if research_intent_id:arguments['research_intent_id']=research_intent_id
        if last_run.get("run_id"):
            arguments["last_run"] = {"run_id": last_run["run_id"]}
        return {"ok": False, "error": str(exc), "design_id": design["design_id"],
                "payload": {"status": "revision_required", "design_id": design["design_id"],
                            "executed": False, "feedback_id": feedback_id, "evidence": exc.evidence,
                            "next_action": {"action": "design_model", "arguments": arguments}}}
    except PendingStage as exc:
        checkpoint.record.update(status="pending")
        checkpoint.save()
        completed_runs = [value["record_id"] for value in checkpoint.record.get("archives", {}).values()
                          if value.get("committed")]
        return {"ok": True, "payload": {"status": "pending", "design_id": design_id,
                "executed": bool(completed_runs), "execution_complete": False, "completed_runs": completed_runs,
                "current_stage": checkpoint.record.get("current_stage"),
                "pause_reason": checkpoint.record.get("pause_reason"), "message": str(exc),
                "solver_progress": checkpoint.record.get("solver_progress"),
                "llm_calls": [*checkpoint.prior_audit, *audit],
                "next_action": {"action": "build_model", "arguments": continuation_args}}}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "llm_calls": audit,
                **({"design_id": design_id} if design_id else {})}
    finally:
        stack.close()
