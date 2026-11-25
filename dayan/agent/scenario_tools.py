"""Scope a natural-language scenario before choosing or configuring an engine."""
import json
import re
import time
from datetime import datetime,timezone

from ..research.requirements import empirical_validation_requested, extract_request
from ..research.literature import summary as literature_summary
from .model_design import _requirement_index, approved_plan, create_design
from .progress import emit


def needs_incident_model(request):
    return bool(re.search(r"踩踏(?:事件|事故|过程|机制|伤害|情景|场景)|(?:模拟|人群|拥挤).{0,8}踩踏|"
                          r"连锁(?:跌倒|摔倒|倒地)|(?:跌倒|倒地)(?:传播|连锁)|人体失稳|群体挤压",
                          request.get("positive_text", "")))


def requests_scripted_exercise(request):
    """Require the user to explicitly choose an exogenous incident for the drill."""
    text = request.get("positive_text", "")
    clauses = re.split(r"[。；，\n]", text)
    trigger = (r"(?:预先|预设|预定|预指定|事先指定|脚本).{0,12}(?:倒地|跌倒)|"
               r"(?:倒地|跌倒).{0,10}(?:预设|预定|预先指定|脚本触发)")
    return "演练" in text and any(
        re.search(trigger, part) and not re.search(r"不要|不得|不允许|不能|避免|不接受|拒绝", part)
        for part in clauses)


def _numeric_fields(contract):
    return {name: spec["type"] for name, spec in contract["fields"].items()
            if spec["type"] not in ("boolean", "array", "object", "string", "null")}


def permits_partial(request):
    text = request.get("positive_text", "")
    return bool(re.search(r"接受部分覆盖|只做诊断|仅做诊断|只验收子范围|先跑能覆盖的部分", text))


def _coverage(request, model_id):
    from ..output_contract import output_contract
    from ..research.requirements import model_mechanisms
    from ..research.semantics import registry

    profile = registry().get(model_id, {})
    covered = model_mechanisms(model_id)
    gaps = sorted(set(request['mechanisms']) - covered)
    if not set(profile.get("required_mechanisms", [])) <= set(request["mechanisms"]):
        gaps.append("原文领域条件与此模型的具体适用范围不一致")
    from ..engine_capabilities import require_native_methods
    gaps.extend(request["scene_requirements"]["unsupported"])
    gaps.extend(require_native_methods(request, model_id))
    if set(request["excluded_mechanisms"]) & covered:
        gaps.append("候选包含原文明确排除的机制")
    if request["model_ids"] and model_id not in request["model_ids"]:
        gaps.append("与用户指定的模型编号不同")
    if model_id == "NET122" and re.search(r"多个审计(?:机关|机构)|审计(?:机关|机构)之间|不同层级审计|非周期边界|真实地块边界",
                                          request.get("positive_text", "")):
        gaps.append("原生农业审计模型采用一个审计机关与周期边界，需另有多机构或实地拓扑模型")
    if request.get("requires_real_topology"):
        gaps.append("真实路网需要专用数据输入与空间研究入口")
    if request.get("requires_llm_agents"):
        gaps.append("该入口不负责执行原文要求的真实语言模型主体")
    if empirical_validation_requested(request):
        gaps.append("要求基于观测进行校准或独立验证，须使用带校准与留出结果的研究入口")
    expected = request.get("metric")
    if expected and (expected != "flux" or "交通流" in request["mechanisms"]) and expected not in output_contract(model_id)["fields"]:
        gaps.append("候选未导出用户所需的主要指标 " + expected)
    missing_features=set(request['scene_requirements']['features'])-set(profile.get('scene_features',[]))
    if missing_features:
        gaps.append('现有场景缺少设施：'+'、'.join(sorted(missing_features)))
    incident = needs_incident_model(request)
    exercise_model = bool(profile.get("incident_exercise"))
    exercise = exercise_model and requests_scripted_exercise(request)
    if incident and not exercise:
        gaps.append("原文要求事故情境。现有模型缺少事故发生机制，预定倒地仅适用于明确选择的演练")
    if exercise_model and not exercise and not incident:
        gaps.append("该模型会加入预先指定的倒地事件，原文尚未明确选择该演练")
    if incident and re.search(r"(?:必须|要求|研究|计算|预测|复现|推演).{0,12}"
                              r"(?:连锁跌倒|连锁倒地|失稳动力学|伤亡|伤害严重度|实际事故)",
                              request["positive_text"]):
        gaps.append("原文要求的失稳、连锁、伤害或实际事故机制超出现有引擎能力")
    status = "partial" if gaps else "exercise" if exercise else "covered"
    scope = {'status':status, 'covered':sorted(covered), 'limits':profile.get('limitations', []), 'gaps':gaps}
    if exercise_model:
        scope["incident_physics"] = {
            "接触": "几何排斥及相交对数",
            "倒地": "外生事件与姿态、降速响应",
            "失稳触发与连锁倒地": "未求解",
            "人体伤害与真实事故": "未求解",
        }
    return scope


def modeling_guide(request):
    """Read-only interpretation and current model/data workflow for the real user request."""
    from ..collection.presets import list_presets
    from ..output_contract import output_contract
    from ..research.semantics import candidates, registry
    from .tools import TOOL_SPECS, tool_get_capabilities

    parsed = extract_request(request)
    incident = needs_incident_model(parsed)
    empirical = empirical_validation_requested(parsed)
    from ..engine_capabilities import custom_blockers, requested_methods,program_status,program_blockers
    from ..scaling import capacity, scale_intent
    local_grid = "网格局部交互" in parsed["mechanisms"]
    blockers = custom_blockers(parsed)
    dsl_possible = not (incident or requests_scripted_exercise(parsed) or empirical or blockers)
    program=program_status()
    program_gaps=program_blockers(parsed)
    program_possible=program['available'] and not (empirical or program_gaps)
    custom_possible=dsl_possible or program_possible
    design_first = custom_possible and not (parsed["model_ids"] or parsed["reuse"] or parsed["kind"] == "search_models")
    models = []
    for row in ([] if design_first else candidates(parsed)[:8]):
        mid = row['model_id']
        profile = registry()[mid]
        parameters = tool_get_capabilities(mid).get('payload',{}).get('parameters',[])
        models.append({'model_id':mid,'description':row['description'],
                       'scope':_coverage(parsed,mid),'input_ports':profile.get('inputs',{}),
                       'parameters':parameters,'observables':list(_numeric_fields(output_contract(mid))),
                       'recommended_run':profile.get('recommended_run'), 'method_evidence':profile.get('method_evidence'),
                       'execution_notes':profile.get('execution_notes',[])})
    models.sort(key=lambda item: item["scope"]["status"] == "partial")
    eligible = [item["model_id"] for item in models if item["scope"]["status"] in ("covered","exercise")]
    if incident and not eligible:
        blockers.append("现有引擎无法计算原文所需的事故发生机制")
    if empirical:
        blockers.append("实际参数校准或独立验证需要对应的观测证据和研究入口")
    presets = [{key:p[key] for key in ('preset_id','title','evidence','placeholders')}
               for p in list_presets() if p.get('evidence') and any(topic in request for topic in p.get('topics',()))]
    workflow = None
    if parsed["interventions"] or parsed["kind"] == "experiment":
        workflow = "experiment"
    elif parsed["kind"] in {"ensemble", "compare", "sweep", "resume", "compose"}:
        workflow = parsed["kind"]
    names={'report_run','reviewed_run','get_capabilities','execution_capabilities'}
    if empirical:
        names.update(('research_model_prepare','research_model_context','research_model_create','research_calibrate','research_finalize','research_status','research_report'))
    if eligible and workflow:
        names.add(workflow)
    if custom_possible or empirical:
        names.update(('design_model','build_model','validate_model'))
    if parsed['requires_real_data'] or parsed.get('requires_real_topology'):
        names.add('collect_data')
        names.update(('run_preset','import_collection','analyze_data') if presets else
                     ('search_sources','collect_source','import_collection','analyze_data'))
    executable = bool(eligible or custom_possible or permits_partial(parsed))
    examples = {}
    if custom_possible:
        examples["custom_model"] = {"action": "build_model"}
    if eligible and not workflow:
        examples["existing_model"] = {"action": "reviewed_run", "model_id": eligible[0]}
    return {'ok':True,'payload':{
        'runtime_clock':{'observed_at_utc':datetime.now(timezone.utc).isoformat(),
            'basis':'platform_system_clock',
            'scope':'本次工具回执的墙上时钟，非仿真时间或数据发布时间；后续采集可晚于这次回执，不能将其当作永不变化的当前时刻。'},
        'intent':parsed['kind'],'spatial':parsed['scene_requirements']['spatial'],
        'design_first':design_first,
        'real_inputs_required':parsed['requires_real_data'] or parsed.get('requires_real_topology',False), 'requested_mechanisms':parsed['mechanisms'],
        'technical_methods': requested_methods(parsed),
        'execution_scale': {'request': scale_intent(request), 'capacity': capacity(),
                            'contract': '大规模主体走列式执行。保持指定人数、网格和步数；工作内存随后按实际规约预检。'},
        'execution_evidence': '原生候选、DSL和程序通路均须通过需求/源码审查、实际运行、数据与状态核验',
        'authoring_workflow':{
            'default':'同一份方案贯穿设计、审核、编译和执行；平台负责将获审方案编译为模型',
            'design':{'tool':'design_model','parameters':'一般省略；只传已确定的实际运行值，类型/default/unit定义属于definition.parameters'},
            'continue':'pending直接执行next_action，保留design_id和运行设置；不自行等待或重做已完成阶段',
            'construct':{'tool':'build_model','design_id':'approved方案的同一编号','definition':'默认省略，由平台按完整获审方案生成'},
            'manual':'需要自行实现时先用design_details读全同号方案，再用同一definition_path、design_id和运行设置依次validate_model/build_model',
            'revise_choices':'调整Agent自己提出的运行取值时用design_model(revise_from=原编号,revise_proposal=true)，重新审核；用户原话固定值和MI科研协议保持',
            'research':'要求实测校准/独立验证时先research_model_prepare，后续沿同MI和next_action执行'
        },
        'model_research':{'prepare_tool':'research_model_prepare','context_tool':'research_model_context','create_tool':'research_model_create',
                          'source_evidence':'先实际采集定义/单位/方法原件，再用context_tool按同MI引用DS原字段JSON Pointer；不改数值输入、网格、划分和阈值。blocked后追加须再独立审查，运行后不悄补。',
                          'requires':'新建研究先真实采集目标DS，再冻结完整原文/目标/单位/时钟/划分/网格/种子/阈值/诊断，沿返回的MI和next_action审查与构建；已有已审实际基线可直接create',
                          'new_empirical_model_workflow':'prepare_intent_then_review_build_baseline_then_actual_calibration_diagnostics_holdout_and_report',
                          'diagnostic_binding':'未选模型时，消融科学声明用binding={kind:approved_plan}，获审方案diagnostic_bindings按同id给实际演化rule_refs/reason并逐项复核；编译核真实路径，同MS保存科学原声明与绑定hash。不提前猜DSL/program路径，不改阈值或机制。',
                          'scope':'基线只为中间态，仍须同MS实际校准/留出/诊断和科研报告；低误差不证明政策因果。'},
        'custom_engine': ('fixed_grid' if scale_intent(request).get('boundary') in ('nonperiodic','reflecting','absorbing')
                          else 'fixed_periodic_grid') if dsl_possible and local_grid else 'math_and_abm' if dsl_possible else None,
        'incident_requires_more_than_dsl':incident,
        'program_engine':{**program,'eligible':bool(program_possible),'blocked_by':program_gaps,
                          'eligible_with_research_intent':bool(program['available'] and not program_gaps),
                          'contract':'schema(build_model)包含kind=program的完整函数/帧/方程合同；先design_model审查再构建'},
        'models':models,'eligible_models':eligible, 'data_presets':presets, 'dsl_blocked_by':blockers,
        'data_routes':{
            'known_public_file':{'tool':'collect_data','schema':{'action':'schema','tool':'collect_data'},
                'result':'实际下载并返回DS数据集标识，无需import_collection',
                'parsing':'按源字典声明format及parse_options；无标题用header=false/fieldnames，ZIP用archive_member'},
            'source_connector':{'tool':'collect_source','schema':{'action':'schema','tool':'collect_source'},
                'result':'返回collection_id；仅status=done且artifact_role=dataset时import_collection得到DS。catalog_only/text_only按当前批次留作检索参考；论文/引用网络本身作为研究对象时，采集相应实际字段并按records/edges数据合同建模。partial沿同ID续采',
                'discovery':'connector只能用schema枚举；search_sources查询来源，不是连接器列表API'}},
        'invocation_examples': examples,
        'tool_contracts':[{key:entry[key] for key in ('name','description','parameters')}
                          for entry in TOOL_SPECS if entry['name'] in names],
        'next_tools':{'existing_model':'reviewed_run' if not design_first and (eligible or permits_partial(parsed)) and not workflow else None,
                      'study_workflow':workflow if eligible else None,
                      'inventory':'execution_capabilities',
                      'custom_model':'build_model' if custom_possible else None,
                      'research_model':'research_model_prepare' if empirical else None,
                      'data':['collect_data','analyze_data',*(['run_preset','import_collection'] if presets else ['search_sources','collect_source','import_collection'])]
                      if (executable or empirical) and (parsed['requires_real_data'] or parsed.get('requires_real_topology')) else [],
                      'report':'report_run' if executable else None},
        'notes':['新研究先从原话独立设计，相关研究记忆在思路审查时提供参考。现有模型用 reviewed_run 核对范围、机制、输入和事前检验。',
                 '研究建模在独立思路后自动检索中英文期刊与 arXiv，在线正文的实际精读数量和证据进入设计与报告。复杂任务可先 design_model，按 next_action 实际构建。',
                 '比较、扫描、重复、干预与续跑用对应 study_workflow 合同。需要外部校准时核对实测输入与适用研究适配器。',
                 '执行路径缺失时保留原文、具体机制和缺失的计算或数据端口。能力总览见 execution_capabilities。',
                 '按问题选择DSL或kind=program。program可用时，通过受管Python实际实现不同人口池/动态图/连续与事件算法，不受旧DSL表达式限制；每个新算法仍须独立复核和数值验证。具体剩余缺口见program_engine，不能删掉用户要求来规避。',
                 'fixed_grid/fixed_periodic_grid 用 agents.grid，4或8邻域，boundary可选periodic、reflecting、absorbing；局部累加/均值/极值/按最大者取状态、至多20步历史。反射以格面镜像复制边格，吸收域外默认0，吸收虚格不参与pick_max。依据 execution_scale 和实际规约选定规模。',
                 '默认交付完整覆盖。只有原文明确接受诊断子范围时才使用 allow_partial。部分结果不得视为整题完成。',
                 'collection_id是采集批次；只有done且artifact_role=dataset才import_collection(role="input")并核字段/绑定。检索目录批次留作本轮参考，不把论文元数据当作农业等问题的行为参数；若问题本身研究论文/引用网络，按相应records/edges合同采集实际数据，公开URL可用collect_data。partial沿同ID续采；独立留出验证才用holdout。',
                 '已有公开数据文件URL时先schema(collect_data)，通过execute调用collect_data(url,format,parse_options)。它直接取得DS标识；不要猜http、__list__等连接器或翻源码寻找下载入口。连接器只用schema(collect_source)枚举。',
                 'data_bindings标量条目含dataset_id、field、parameter。program的逐记录或关系输入用dataset_id、port、contract、columns，合同与input_ports一致，保留联合列、真实ID和时间区间，不用均值代替结构。已绑定参数不重复写进parameters；来源/单位/范围须核对，不能把假设场景说成实际事故或已校准。',
                 '运行报告用report_run(run_id)；整组对照/多种子报告同时传实际experiment_id或analysis_id（二选一），读取同组全部真实成员。校准研究用research_report(study_id)。'],
    }}


def _audit_game_evidence(seed):
    """Use opposing observed states to verify that discoveries drive the third actor."""
    from ..runtime import run_model_full

    rows = []
    for state in (0, 1):
        parameters = {"grid_side": 4, "initial_audit": .5, "initial_strict": state,
                      "initial_green": state, "audit_cost": .001, "audit_value": 0}
        run = run_model_full("NET122", parameters, ticks=2, dt=1, seed=seed,
                             strict=True, capture_state=True)
        observed = run.observations[-1]
        rows.append({"control": "全松懈与欺诈" if state == 0 else "全积极与合规",
                     "initial_target": run.observations[0]["audit_target"],
                     "target_after_feedback": observed["audit_target"], "audit_gain": observed["audit_feedback"],
                     "prior_joint_findings": observed["feedback_lax_fraud"], "prior_audits": observed["feedback_samples"],
                     "actual_lattice_fields": [layer["id"] for layer in run.state_frames[-1]["lattice"]["layers"]]})
    if not rows[0]["target_after_feedback"] > .5 > rows[1]["target_after_feedback"]:
        raise ValueError("审计机关的实际策略未对不同发现反馈作出可区分响应")
    return {
        "source": "dayan/models/spatial_audit.py",
        "reference": "https://xbbjb.nau.edu.cn/sjyjjyj/article/pdf/20260205006",
        "experimental_scope": "4×4、2步机制对照，使用控制初值检验实现。正式运行另用同用户需求绑定的实参。",
        "controlled_actual_observations": rows,
        "audit_party": {
            "strategies": ["实施审计", "不审计"],
            "institution_count": 1,
            "state": "audit_target，中央机关的混合策略。每格实际二元审计决策由预算及抽查模式实现",
            "payoff": "三方逐格支付按 a_i、d_i、g_i 共同决定。机关用实际已查处风险计算审计和不审计的期望净收益差 Δ",
            "adaptive_update": "x'=clip(x+0.05 if Δ>0 else x-0.01, audit_min, audit_max)",
            "feedback_path": "实际监管松懈与农户欺诈 → 上周期已审计元胞的 joint/n 与 lax/n → Δ → 机关下期覆盖及派单 → 两类主体的当期支付",
            "scope": "同一研究的时空模型由单一审计机关经局部查处信息调整强度。论文式(2)、图2规定自适应调控，局部同类模仿用于监管与农业",
        },
        "archived_spatial_evidence": {
            "path": "state_frames[*].lattice.layers", "layer_ids": ["audit", "regulator", "farm"],
            "run_api": "/api/runs/{run_id}/state",
            "verify": "治理与生产各格值、审计选区以及三层同时点计数均由执行验收读取。标量观测合同单列数值字段",
        },
    }


def reviewed_run(model_id, request=None, parameters=None, ticks=None, seed=None, dt=None,
                 data_bindings=None, allow_partial=False, design_id=None, *, _session=None):
    """Plan and independently review the exact scope/configuration of an existing model."""
    from ..datasets import bind_parameters
    from ..limits import limits, validate_compute
    from ..output_contract import output_contract
    from ..model_index import resolve
    from ..research.semantics import registry
    from ..runtime import validate_run_arguments
    from .tools import _archive_run, _coerce_ticks, _norm_mid, tool_get_capabilities

    audit = []
    design = None
    try:
        continuation_parameters = parameters
        if not isinstance(request,str) or not request.strip():
            raise ValueError('缺少原始研究需求')
        mid = _norm_mid(model_id)
        parsed = extract_request(request)
        profile = registry().get(mid)
        if not profile or not parsed['mechanisms'] or not set(parsed['mechanisms']) & set(profile['mechanisms']):
            raise ValueError('所选模型没有经核验的原文机制对应关系，先使用 modeling_guide 核对')
        if parsed['model_ids'] and mid not in parsed['model_ids']:
            raise ValueError('所选模型与用户指定的模型编号不符')
        if set(parsed['excluded_mechanisms']) & set(profile['mechanisms']):
            raise ValueError('所选模型包含用户要求排除的机制')
        if parsed['reuse'] or parsed['interventions'] or parsed['options'].get('seeds') or parsed["kind"] in ("compare", "sweep", "ensemble"):
            raise ValueError('此入口执行一个新配置和单种子；已有运行、干预和多种子由对应工具执行')
        if parsed['unresolved_constraints'] or parsed.get('requires_real_topology') or parsed.get('requires_llm_agents'):
            raise ValueError('原文含当前参数场景不能覆盖的约束，须保留具体机制和现场数据')
        if type(allow_partial) is not bool:
            raise ValueError('allow_partial 必须是布尔值')
        scope = _coverage(parsed,mid)
        if scope['gaps'] and not (allow_partial and permits_partial(parsed)):
            raise ValueError('场景完整性审查未通过：'+'；'.join(scope['gaps']))
        if parsed['requires_real_data'] and not data_bindings:
            raise ValueError('还缺实际入模数据。采集并导入得到 dataset_id 后提交 data_bindings')
        bound,evidence=bind_parameters(data_bindings,mid) if data_bindings else ({},[])
        if parsed['dataset_id'] and parsed['requires_real_data'] and not any(entry['dataset_id']==parsed['dataset_id'] for entry in evidence):
            raise ValueError('数据映射未包含用户指定的数据集')
        parameters={**(parameters or {}),**parsed['parameters']}
        replaced={}
        for field,value in bound.items():
            if field not in parameters or parameters[field]==value:
                continue
            if not _session or field in parsed['explicit_parameters']:
                raise ValueError(f'明确的参数 {field} 与数据绑定结果冲突')
            replaced[field]=parameters.pop(field)
        cap=tool_get_capabilities(mid)
        if not cap['ok']:
            raise ValueError(cap['error'])
        permitted={row['name'] for row in cap['payload']['parameters']}
        if (set(parameters)|set(bound))-permitted:
            raise ValueError('模型不提供实参：'+'、'.join(sorted((set(parameters)|set(bound))-permitted)))
        options=parsed['options']
        defaults={row['name']:row['default'] for row in cap['payload']['parameters'] if 'default' in row}
        suggested=profile.get("recommended_run",{})
        ticks=_coerce_ticks(options.get('ticks',ticks if ticks is not None else suggested.get("ticks",100)))
        dt=options.get('dt',dt if dt is not None else parameters.get('dt',suggested.get('dt',defaults.get('dt',.1))))
        seed=options.get('seed',seed if seed is not None else parameters.get('seed',suggested.get('seed',0)))
        for key, value in {'dt':dt,'seed':seed}.items():
            if key in parameters and parameters[key]!=value:
                raise ValueError(f'运行选项 {key} 冲突。请仅在顶层填写，保留原文指定值。')
        validate_run_arguments(ticks,dt,seed)
        validate_compute(ticks,parameters={**parameters,**bound})
        outputs = output_contract(mid)
        fields = list(_numeric_fields(outputs))
        effective={**defaults,**parameters,**bound}
        effective.update({key:value for key,value in {'dt':dt,'seed':seed}.items() if key in defaults})
        _, factory = resolve(mid)
        event_checks = getattr(factory, "delivery_events", {})
        event_kinds = list(event_checks)
        if event_kinds:
            required_time = sum(effective[key] for key in ("exercise_time","response_delay","assistance_time"))
            if ticks*dt < required_time + 3*dt:
                raise ValueError("运行时长未覆盖完整处置过程。请延长 ticks 以保存事件、协助及恢复状态。")
        relevant = {'model_id':mid,'description':profile['description'],'kind':profile.get('model_kind'),
                    'clock':profile.get('clock'), 'fixed_dt':getattr(factory,"fixed_dt",None),
                    'source_factory':getattr(factory,"__module__",None),
                    'parameters':cap['payload']['parameters'],'observables':fields,'scope':scope,
                    'non_numeric_outputs':{name: spec["type"] for name,spec in outputs["fields"].items() if name not in fields},
                    'execution_notes':profile.get('execution_notes',[])}
        from ..model_method import model_method
        method = model_method(mid)
        if method:
            relevant["method"] = method
        checks = [
            '比对模型实参和数据映射记录，对绑定字段核对聚合值、单位、来源和哈希。其他未绑定参数为假设或模型默认值。',
            '计算后核对实际事件的同一时点观测及主体状态采样。缺少要求字段、事件或空间主体则返回失败。',
            '运行成功后从真实归档取得一个 run_id。场景、观测、回放和报告共同使用这个编号。未归档不能生成报告。',
            '报告与工作台保留覆盖范围及明确缺口，实际仅计算的指标不得用于推断未求解的状态。'
        ]
        execution={'model_id':mid,'parameters':parameters,'effective_inputs':effective,
                   'ticks':ticks,'dt':dt,'seed':seed,'data_bindings':evidence,'coverage':scope,
                   'superseded_agent_parameters':replaced,'acceptance_checks':checks,
                   'purpose':'coverage_diagnostic' if scope['gaps'] else 'requested_run'}
        if mid == "NET122":
            execution["verified_engine_evidence"] = _audit_game_evidence(seed)
        if profile.get("incident_exercise"):
            from ..runtime import run_model_full
            trial = run_model_full(mid, parameters=parameters, ticks=0, seed=seed, dt=dt,
                                   data_bindings=data_bindings, strict=True, with_time=True)
            initial = trial.observations[0]
            execution["initial_state_check"] = {key:initial[key] for key in ("alive","evacuated","local_conflicts","min_separation")}
            if initial["alive"] != effective["n"] or initial["local_conflicts"] != 0:
                raise ValueError("已实际初始化核对，初态不满足人数和无重叠条件")
        contract = ("执行入口为注册原生模型。审查选型、实际参数及其运行验证。"
                    "可执行函数、时间、数值字段与空间状态见下方实际合同。"
                    "observables 和 criteria.fields 只使用实际的数值字段。"
                    "数据绑定项与文献或模型默认参数分别追溯。\n"
                    + json.dumps(relevant,ensure_ascii=False))
        if profile.get("incident_exercise"):
            contract += ("\n本次审查对象是明确选择外生倒地的虚拟演练。状态帧提供每人 id、x、y、speed、state。"
                         "地面坐标二维，工作台用三维人物姿态渲染帧。fallen 和 seated 是当事人本身的状态。"
                         "实际存在 exercise_time、response_delay、assistance_time 参数。暂停期间其他在场者的目标速度乘以距离缩放系数；"
                         "yielding 数的是规则生效者，不等于改道人数或由反事实估计的影响。"
                         "execution.initial_state_check 是同种子、同实参的实际初始化，未推进或归档正式运行。"
                         "min_separation 在少于两人时为 null，若检验它只用初时点，不作全窗完整观测。"
                         "用人口守恒、实际阶段事件与姿态、降速规则的可观察证据核验执行。事件时程是参数设定。"
                         "一个公开步速字段可以作为外部参考输入。场地、事件、响应时长是情景假设。")
        if mid == "NET122":
            contract += ("\n执行引用 execution.verified_engine_evidence。审计机关是第三个内生决策主体。"
                         "策略由审计/不审计及混合强度 x 表示，支付差 Δ 读取真实已审计风险，按式(2)与图2自主调整 x。"
                         "对照试跑已验证发现差异改变 x，审计行为反过来改变每格监管与农业支付。"
                         "基于支付的中央适应和局部模仿属于两种决策方式。"
                         "原文并未要求复制多个审计机关或让机关也通过邻域模仿，增加它们属于另一研究设定。"
                         "空间证据是 state_frames.lattice 中每格主动监管、绿色生产、实际审计的独立二元状态。标量观测支持数值条件。"
                         "事前用全程 n_cells 守恒与 strict_share+lax_share、green_share+fraud_share 各和为1，以及 audit_coverage 在0至1。"
                         "局部时空核验已由执行器检查每个保存的元胞与观测计数，各相应标量可关联到方案检验。"
                         "方案保留表2与式(1)的分歧、范围假设和证据缺口。可重复执行不等于论文图示重现或实地校准。"
                         "无预设绿色比例必然上升的结论。")
        expected_kind=profile.get('model_kind')
        requirements=set(_requirement_index(request).values())

        def check_plan(plan):
            if expected_kind and plan['kind']!=expected_kind:
                raise ValueError(f'当前模型的类型为 {expected_kind}')
            missing=set(plan['observables'])-set(fields)
            if missing:
                raise ValueError('计划观测字段不在输出合同：'+'、'.join(sorted(missing)))
            uncovered=requirements-{entry['quote'] for entry in plan['coverage']}
            if uncovered:
                raise ValueError('coverage 缺少原文需求证据：'+' / '.join(sorted(uncovered)))
            plan['verification'] = list(dict.fromkeys([*checks,*plan['verification']]))

        from ..limits import authoring_wall_seconds
        deadline = time.monotonic() + authoring_wall_seconds() - 15
        design=create_design(request,parsed,execution,contract,audit,session_id=_session,
            deadline=deadline,plan_check=check_plan,design_id=design_id)
        if design['status']=='pending' or (design['status']=='approved' and deadline-time.monotonic()<min(120,limits().cpu_seconds)):
            return {'ok':True,'payload':{**design,'executed':False,
                'literature_summary':literature_summary(design['literature']) if 'literature' in design else None,
                'next_action':{'action':'reviewed_run','arguments':{
                    'request':request,'model_id':mid,'design_id':design['design_id'],'parameters':continuation_parameters,
                    'ticks':ticks,'dt':dt,'seed':seed,'data_bindings':data_bindings,'allow_partial':allow_partial}}}}
        if design['status']!='approved':
            problems=design.get('review',{}).get('issues') or [design.get('error') or '独立复核未通过']
            raise ValueError('实施方案未通过：'+'；'.join(problems))
        approved_plan(design['design_id'],request,execution,_session,record=design)
        emit('建模方案已通过审查')
        emit('按通过审查的方案执行模型')
        review={'model_design':{'design_id':design['design_id'],'plan_sha256':design['plan_sha256']},
                'coverage':scope,'scientific_validation':False,
                'method':'既有模型合同、数据绑定核验和独立LLM实施方案审查'}
        if "literature" in design:
            review["model_design"]["literature_summary"] = literature_summary(design["literature"])
        acceptance={'observables':design["plan"]["observables"], 'criteria':design["plan"]["criteria"],
                    'execution':execution, 'events':event_checks,
                    'spatial':parsed["scene_requirements"]["spatial"] or bool(event_kinds)}
        from .build_checkpoint import build_checkpoint
        from .design_checkpoint import PendingStage
        with build_checkpoint(design, {"model_id": mid}, audit, deadline) as checkpoint:
            try:
                result=_archive_run(mid,parameters,ticks,seed,dt,None,data_bindings,
                                    review=review,acceptance=acceptance,checkpoint=checkpoint,llm_calls=design['llm_calls'])
            except PendingStage as exc:
                checkpoint.record.update(status="pending")
                return {'ok':True,'payload':{'status':'pending','executed':False,'design_id':design['design_id'],
                    'current_stage':checkpoint.record.get('current_stage'),'message':str(exc),
                    'next_action':{'action':'reviewed_run','arguments':{
                        'request':request,'model_id':mid,'design_id':design['design_id'],'parameters':continuation_parameters,
                        'ticks':ticks,'dt':dt,'seed':seed,'data_bindings':data_bindings,'allow_partial':allow_partial}}}}
            checkpoint.record.update(status="complete" if result.get("ok") else "failed")
        if result.get('ok'):
            result['payload'].update(design_id=design['design_id'],
                scenario_review=result["payload"]["manifest"]["scenario_review"],llm_calls=design['llm_calls'])
            if "literature" in design:
                result['payload']["literature_summary"] = review["model_design"]["literature_summary"]
        elif result.get("verification"):
            result["design_id"] = design["design_id"]
        return result
    except (ValueError, TypeError, KeyError, FileNotFoundError) as exc:
        return {'ok':False,'error':str(exc),'llm_calls':audit,
                **({'design_id':design['design_id']} if design else {})}


def report_run(run_id, primary_metric=None, experiment_id=None, analysis_id=None):
    """Generate the workbench's report from an existing immutable run, without recalculation."""
    from ..run_store import get_store
    from ..report_gen import generate_report
    from ..server import ReportRequest, _report_material

    record=get_store().load(run_id)
    request=ReportRequest(run_id=run_id,model_id=record['model_id'],primary_metric=primary_metric,
                          experiment_id=experiment_id,analysis_id=analysis_id)
    observations,meta=_report_material(request)
    report=generate_report(record['model_id'],observations,meta)
    if not report["ok"]:
        return report
    scope = report["scope"]
    review = meta["manifest"].get("scenario_review") or {}
    status = "report_ready"
    if isinstance(scope,dict) and scope.get("status")=="partial":
        status = "partial"
    elif (isinstance(scope,dict) and
          (review.get("runtime_checks") or {}).get("verification",{}).get("status") == "passed"
          and report["mathematics"] and report["figure_count"]):
        status = {"covered":"accepted","exercise":"exercise_completed"}.get(scope.get("status"),status)
    return {'ok':True,'payload':{**report,'file':report["url"],"delivery_status":status}}
