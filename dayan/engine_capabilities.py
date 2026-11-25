"""Capabilities of executable methods, shared by discovery and model admission."""

from collections import Counter
import re


METHODS = {
    "discrete_events": {
        "label": "离散事件调度",
        "pattern": r"离散事件|事件队列|(?<![A-Za-z])DES(?![A-Za-z])",
        "native": ("MET-MM1", "SYS018"),
        "contract": "有专用事件队列模型。自定义逐步模型没有事件日历、抢占或一般服务纪律。",
    },
    "stochastic_differentials": {
        "label": "随机微分方程",
        "pattern": r"随机微分方程|伊藤积分|(?<![A-Za-z])SDE(?![A-Za-z])",
        "native": ("SYS034", "SYS035", "SYS036", "SYS037", "SYS038"),
        "contract": "内置模型有漂移与扩散推进。自定义存量使用RK4，不提供自定义布朗增量或相关扩散矩阵。",
    },
    "mixed_clocks": {
        "label": "连续与离散时钟双向耦合",
        "pattern": r"多时钟双向|混合时钟|连续.{0,18}离散事件.{0,12}(?:双向|反馈|耦合)|事件.{0,16}(?:双向|反馈).{0,16}(?:连续|微分)|连续.{0,16}(?:双向|反馈).{0,16}事件",
        "native": (),
        "contract": "compose 可顺序传递结果，同步双向混合时钟需要调度、事件优先级、回滚与守恒协议。",
    },
    "pde_or_contact_physics": {
        "label": "通用连续场和接触动力学",
        "pattern": r"计算流体力学|有限元|通用偏微分方程|Navier[– -]Stokes|三维碰撞|刚体接触|力链",
        "native": (),
        "contract": "有交通和几何避碰的专用实现。通用连续场、三维接触及状态耦合须专用求解器。",
    },
    "multilayer_graphs": {
        "label": "多层、时变或导入的关系网络",
        "pattern": r"多层.{0,10}(?:网络|关系)|时变(?:关系)?网络|导入.{0,12}(?:网络拓扑|边列表|地理邻接关系)",
        "native": (),
        "contract": "部分网络模型接受固定权重矩阵等精确输入。多层时变网络需要图状态及可切换的邻接合同。",
    },
    "sobol_on_model": {
        "label": "任意用户模型全局敏感性",
        "pattern": r"Sobol.{0,14}敏感性|Saltelli|全局敏感性",
        "native": (),
        "contract": "global_sensitivity从已审自建模型基线恢复同源输入/时钟，以独立参数分布实际执行A/B/混合样本，保存种子面板、Sobol一阶/总效应、bootstrap区间及同组报告；不是参数可识别性证明。",
    },
}


def _requested(text, pattern):
    for hit in re.finditer(pattern, text, re.I):
        clause = re.split(r"[，,。；;\n]|但是|但|而是", text[:hit.start()])[-1]
        for method in METHODS.values():clause=re.sub(method['pattern'],'',clause,flags=re.I)
        clause=re.sub(r'(?:和|与|及|、|或|\s)+$','',clause)
        if re.search(r'(?:不是|并非|不能|不得)\s*(?:不使用|不采用|不考虑|不模拟|不要求|不涉及)',clause):return True
        if not re.search(r"(?:不使用|不采用|不考虑|不模拟|不要求|不涉及|无需|不含|不需要|避免|排除|不用|不要|不假称|不声称|不能声称|"
                         r"不得声称|不能冒充|不得冒充|不证明|不代表)\s*(?:已完成|已证明|为|成)?\s*$", clause):
            return True
    return False


def requested_methods(request):
    text = request.get("positive_text", "")
    return [key for key, spec in METHODS.items() if _requested(text, spec["pattern"])]


def require_native_methods(request, model_id):
    return [METHODS[key]["label"] + "需要对应执行实现"
            for key in requested_methods(request) if model_id not in METHODS[key]["native"]]


def custom_blockers(request):
    blockers = list(request["scene_requirements"]["unsupported"])
    for key in requested_methods(request):
        blockers.append(METHODS[key]["label"] + "超出当前自定义执行合同")
    if request.get("requires_real_topology"):
        blockers.append("DSL无真实地理拓扑输入端口，须核对领域适配器的空间数据")
    if request.get("requires_llm_agents"):
        blockers.append("DSL无真实语言模型主体推理，须核对专用主体模型")
    from .scaling import scale_intent
    from .limits import limits
    text = request["positive_text"]
    scale = scale_intent(request.get("original_text", text))
    if scale.get("conflict"):
        blockers.append(scale["conflict"])
    if scale.get("entities",0) > limits().array_entities:
        blockers.append(f"原要求 {scale['entities']:,} 个主体，当前自定义数组结构上限 {limits().array_entities:,}")
    if "网格局部交互" in request["mechanisms"]:
        if scale.get("grid") and min(scale["grid"].values()) < 3:
            blockers.append("自定义固定网格每边至少3格")
        if _requested(text, r"六边形网格|不规则网格"):
            blockers.append("自定义局部网格目前使用四邻或八邻的矩形网格；不规则网格需图或专门求解器")
    return blockers


def program_status():
    from .solvers.sandbox import image_contract, SolverError
    try:
        from .llm_client import configured
        return {'available':True,**image_contract(),'external_decisions':{
            'configured':configured(),'definition':'decision_policy','request_function':'decision_requests',
            'advance_arguments':7,'credentials':'host_only','accepted_response_recovery':True,'recorded_replay':True,
            'initial_frame':'initialize后、首次LLM响应前的真实初态；首次实际消费在step1，不能预填已接受动作',
            'boundary_frames':'先保存上一步末帧，再取得下一步起点的新响应；新动作在后续advance消费'}}
    except (SolverError,ValueError) as exc:
        return {'available':False,'reason':str(exc),'setup':'python scripts/build_solver_image.py'}


def program_blockers(request):
    """Keep genuine missing ports/workflows separate from the DSL grammar."""
    # Topic names do not limit numerical Python. Each proposed algorithm still
    # needs its own implementation, review and actual numerical/scene checks.
    blockers=[]
    if request.get('requires_llm_agents'):
        from .llm_client import configured
        if not configured():blockers.append('真实主体决策需要配置宿主LLM服务；不会以固定动作替代')
    from .scaling import scale_intent
    from .limits import limits
    scale=scale_intent(request.get('original_text',request['positive_text']))
    if scale.get('conflict'):blockers.append(scale['conflict'])
    if scale.get('entities',0)>limits().array_entities:blockers.append('原人数超过当前受管人口预算')
    return blockers


def method_inventory():
    """List available compute routes and explicit boundaries, without claiming validation."""
    from .limits import limits
    from .model_index import ALL_INDEX, resolve
    from .research.semantics import registry
    from .scaling import capacity

    counts = Counter()
    for model_id in ALL_INDEX:
        if model_id.startswith("USR"):
            continue
        protocol, factory = resolve(model_id)
        if factory is not None:
            counts[protocol] += 1
    budget = limits()
    return {"ok": True, "payload": {
        "runnable_factories_by_entry": dict(counts),
        "semantic_profiles": sum(model_id in ALL_INDEX for model_id in registry()),
        "technical_methods": {
            key: {**{k: spec[k] for k in ("label", "contract")},
                  "native_examples": [model_id for model_id in spec["native"] if resolve(model_id)[1] is not None]}
            for key, spec in METHODS.items()
        },
        "custom": {
            "limits_scope": "下面的单表和固定网格限制属于DSL；program按实际代码、接口与资源判断",
            "build_model": ["常微分存量", "同类主体", "存量与主体固定步耦合", "固定位置的网格角色槽位"],
            "local_grid": {"theoretical_cells_ceiling": budget.array_entities, "neighbors": [4, 8],
                           "history_steps": 20, "default_boundary": "periodic",
                           "boundaries": ['periodic','reflecting','absorbing'], "capacity": capacity()},
            "limits": ["可移动的不同人口池", "任意输入图的局部查询", "通用事件调度和多时钟反馈", "任意行业物理内核"],
            "program": {**program_status(), 'kind':'program','entry':'build_model',
                        'implemented':'普通Python算法在隔离求解器执行；完整异类人口、局部CA/自定义拓扑、动态图、连续积分、事件/干预及随机状态可归档和续算',
                        'verification':'每个新算法仍须独立方案/源码审查、数值验收；没有内置该领域的科学有效性保证',
                        'input_ports':['records联合记录','edges端点引用及显式时间区间','geojson完整Feature/几何/属性/ID及CRS核对','timeseries系列身份/观测时点与取值策略；模型源码实际插值/积分，非宿主自动补值'],
                        'external_decisions':'decision_policy + pure decision_requests + seven-argument advance; real host calls and checkpoint-bound replay',
                        'global_sensitivity':'global_sensitivity(baseline_run_id,distributions,metric,n,seeds)，按实际analysis_id续接并生成同源报告',
                        'measured_capacity':'plan_capacity：实际两档探针+目标档；CPU/峰值RSS/体积/云调用及外推误差；原规模不自动改',
                        'spatial_3d':'实际terrain高度网格、floor楼板/开口、connector三维路径/宽度；完整x/y/z、floor_id与人物动作、分层回放和同源报告',
                        'remaining':['参数可识别及各领域数值/经验验证仍随具体研究执行；空间绘制不自动等于通用接触物理']},
        },
        "data_paths": [
            {"contract": "数据字段到数值参数", "tools": ["collect_source", "import_collection", "analyze_data", "run", "ensemble"],
             "limit": "标量合同为数值聚合；program用input_ports/data_bindings的records/edges/geojson/timeseries保留联合行、时间边、完整几何与系列。点时序取值须在审核源码中按合同实现；核对源CRS，不自动投影；图像与更丰富场景仍待专门实现"},
            {"contract": "路网和人口耦合", "model": "CPL001",
             "limit": "读取已转换并核验的道路和人口资产；并非通用GIS建模器"},
            {"contract": "校准与独立时段留出", "tools": ["research_create", "research_calibrate", "research_report"],
             "limit": "自动研究入口覆盖现有WB年度指标的描述型线性、指数和Logistic适配"},
            {'contract':'自建模型的完整科研阶段','tools':['research_model_prepare','research_model_context','design_model','build_model','research_model_create','research_calibrate','research_finalize','research_status','research_report'],
             'limit':'新研究先prepare固定完整原文/真实DS目标/输入/三分区/网格/重复/阈值/诊断，MI贯穿审查构建；实际基线为中间态，自动接同MS求值、诊断与留出，再实际运行所选参数和同源报告。创建或基线通过非科学验收；外部干预队列及参数可识别按各入口实际能力处理。敏感性为另行归档的探索分析，不能改写冻结研究。'},
        ],
        "budgets": {"ticks": budget.ticks, "combined_steps": budget.total_steps, "seeds": budget.seeds,
                    "arms": budget.arms, "individual_entities": budget.entities, "wall_seconds": budget.wall_seconds},
        "scope": "运行工厂与适用性合同的实时清单。模型可表达性、执行验收、数值基准与现实验证需要各自的证据。",
    }}
