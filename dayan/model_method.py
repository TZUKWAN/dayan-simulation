"""Source-backed mathematical descriptions saved with model runs."""
from __future__ import annotations


def _dsl_method(definition):
    equations = []

    def add(group, expressions, left):
        for name, expression in expressions.items():
            equations.append({"group": group, "expression": f"{left(name)} = {expression}"})

    add("存量初始化", definition.get("initial_state", {}), lambda name: name+"(0)")
    add("存量微分方程", definition.get("rates", {}), lambda name: "d"+name+"/dt")
    agents = definition.get("agents") or {}
    if agents:
        add("主体规模", {"N": agents["count"]}, str)
        add("个体初始条件", agents["initial"], lambda name: name+"[i,0]")
        add("个体下一步状态", agents["update"], lambda name: name+"[i,k+1]")
        add("同一时点的个体观测", agents.get("measures", {}), lambda name: name+"[i,k]")
        if grid := agents.get("grid"):
            add("固定网格", {key: grid[key] for key in ("rows", "columns", "degree")}, str)
            add("网格边界", {"boundary":grid.get('boundary','periodic')}, str)
            if grid.get('boundary_values'):
                add("吸收域外背景值",grid['boundary_values'],str)
            for name, rule in grid["reductions"].items():
                field, op, lag = rule["field"], rule["op"], rule.get("lag", 0)
                statistic = f"{op}(N(i), {field}[k−{lag}])"
                if op == "pick_max":
                    statistic = f"{field}[argmaxⱼ∈N(i) {rule['by']}[j,k−{lag}], k−{lag}]"
                equations.append({"group": "局部邻域查询", "expression": f"{name}[i,k] = {statistic}"})
    add("观测量定义", definition.get("observables", {}), str)
    space = definition.get("space") or {}
    if space:
        add("计算空间", {key: space[key] for key in ("width", "height")}, str)
    for facility in (definition.get("scenario") or {}).get("facilities", []):
        add(f"设施 {facility['id']}", {key: facility[key] for key in ("x","y","width","depth","value","tone")
                                     if key in facility}, str)
    integration = []
    if definition.get("rates"):
        integration.append("存量使用四阶 Runge–Kutta 积分。四个子步读取同一时步的旧主体聚合量。")
        equations.extend({"group":"RK4 积分", "expression":expression} for expression in (
            "k₁ = F(Sₖ,tₖ)", "k₂ = F(Sₖ + Δt·k₁/2,tₖ + Δt/2)",
            "k₃ = F(Sₖ + Δt·k₂/2,tₖ + Δt/2)", "k₄ = F(Sₖ + Δt·k₃,tₖ + Δt)",
            "Sₖ₊₁ = Sₖ + Δt·(k₁ + 2k₂ + 2k₃ + k₄)/6"))
    if agents:
        integration.append("个体更新同时读取旧属性、旧存量和旧聚合量。各字段更新后，再计算新观测量和场景帧。")
        integration.append("mean、sum、min 和 max 前缀表示对已声明属性的群体聚合，id 为从零开始的个体编号。")
        if agents.get("grid"):
            boundary=agents['grid'].get('boundary','periodic')
            boundary_text={'periodic':'周期环绕','reflecting':'格面反射（包含边格的对称延拓）',
                           'absorbing':'吸收，域外取声明的背景值（未声明字段为0）'}[boundary]
            integration.append(f"固定网格按行编号，边界为{boundary_text}。每步先读旧格点或已保存的历史层，同一轮同步更新。历史不足读取最早时点。")
    return {
        "source": "archived_dsl", "name": definition["name"],
        "description": definition.get("description", ""),
        "equations": equations, "integration": integration,
        "parameters": {key: {"unit":spec.get("unit",""), "meaning":spec.get("description","")}
                       for key,spec in definition.get("parameters", {}).items()},
        "assumptions": definition.get("assumptions", []),
        "limitations": definition.get("limitations", []), "references": [],
    }


def _pedestrian_method(exercise, legacy_layout=False):
    from .models.pedestrian import R_PED
    separated = exercise and not legacy_layout
    equations = [
        ("状态与边界", "pᵢ = (xᵢ, yᵢ),  vᵢ = (vₓᵢ, vᵧᵢ)", "p 为位置，单位 m。v 为速度，单位 m/s。"),
        ("初始条件", "xᵢ候选 ∼ U(x₀+1,x₁−1),  yᵢ候选 ∼ U(y₀+1,y₁−2)",
         ("沿编号接受候选点，与已放置者间距须不小于两倍行人半径。否则随机重抽，最多检查 1024 次。"
          "初始速度为零，接受后的点不独立。" if separated else
          "各坐标独立均匀抽样，候选点直接为初始位置。初始速度为零，抽样不限制最小间距。")),
        ("出口与方向", "g = ((x₀+x₁)/2, y₁),  eᵢ = (g−pᵢ)/max(‖g−pᵢ‖,0.05)", "g 为出口中心。"),
        ("行人距离", "dᵢⱼ = ‖pᵢ−pⱼ‖,  uᵢⱼ = (pᵢ−pⱼ)/max(dᵢⱼ,0.05)",
         "对其他位置槽位计算。已离场位置被移至场外哨兵坐标，常规矩形内超出短程作用范围。"),
        ("局部交互", f"aᵢˢ = ∑[dᵢⱼ<1.2] 2·exp(({2*R_PED:g}−dᵢⱼ)/0.3)·uᵢⱼ", "短程行为排斥。"),
        ("几何接触", f"aᵢᶜ = ∑ⱼ 12·max(0,{2*R_PED:g}−dᵢⱼ)·uᵢⱼ", "几何重叠项加入移动方程。"),
        ("墙边约束", "aʷ = Σ壁 8·exp(−max(d壁,0.02)/0.15)·n壁",
         "n 是每侧墙的内法向，先累加四侧贡献。出口带内将净 y 分量改为 min(a_y,0)，其余分量不变。"
         "这是当前实现的裁剪规则，而非单独取消顶边项。"),
        ("速度更新", "v* = vᵢ + Δt·[(v_des·sᵢ·eᵢ−vᵢ)/0.5 + aᵢˢ + aᵢᶜ + aᵢʷ]",
         "s 缩放指向出口的目标速度大小，基础模型取 1。局部降速不改变目标方向。"),
        ("速度上界", "vᵢ(k+1) = v*·min(1,1.6·v_des/‖v*‖)",
         "当预测速度为零时保持零。"),
        ("位置更新", "pᵢ(k+1) = pᵢ(k) + Δt·vᵢ(k+1)",
         "演练模型随后将位置投影到矩形边界内。" if exercise else "按更新后的速度推进位置。"),
        ("离场判据", "yᵢ ≥ y₁−0.4  且  |xᵢ−gₓ| ≤ exit_half", "满足条件的行人退出活动主体集合。"),
        ("在场统计", "N在场(k) + N累计疏散(k) = n", "离场主体保留历史身份，已不参与当前位置和速度统计。"),
    ]
    parameters = {
        "n":{"unit":"人","meaning":"模拟人数"},
        "bounds":{"unit":"m","meaning":"场地的 x₀、y₀、x₁、y₁ 边界"},
        "exit_half":{"unit":"m","meaning":"离场口宽度的一半"},
        "v_des":{"unit":"m/s","meaning":"无局部避让时的目标步速"},
        "dt":{"unit":"模型秒","meaning":"积分步长"},
    }
    references = ["Helbing 与 Molnár（1995）为驱动与社会排斥形式的理论来源。代码含独立设定及裁剪规则。https://doi.org/10.1103/PhysRevE.51.4282",
                  "Grimm 等（2020）用于组织主体模型的目的、尺度、状态、调度、输入和子模型。https://doi.org/10.18564/jasss.4259",
                  "Ronchi 等（2013）用于区分程序验证与实证适用性检验。https://doi.org/10.6028/NIST.TN.1822"]
    assumptions = ["空间为参数化矩形，有一个离场口。初态依种子确定，步速在个体间取同一个实际参数。"]
    limits = ["局部接触项描述几何排斥。人体内部受力、伤害和真实场地外推不在这个模型范围内。"]
    integration = ["先计算局部方向与排斥，再更新速度及位置，判定离场，最后记录观测和状态帧。"]
    if exercise:
        equations.extend([
            ("外生状态转换", "在场 → 倒地 → 受助 → 恢复活动",
             "在满足预定时点且有人在场的首个步末，从在场者均匀抽取一人。之后按实际触发时点起算两个设定间隔。"
             "受助由同一人的坐姿表示。恢复指允许继续移动，离场仍取决于运动轨迹与出口判据。"),
            ("停留与周围降速", "sᵢ = clip(‖pᵢ−p事件‖/1.5, 0.25, 1)",
             "仅在倒地或受助期间作用于其他在场者。事件主体速度为零且位置固定，其余行人仍受局部排斥。"
             "降速规则作用人数统计本步未离场且 sᵢ 小于 1 的行人，属于规则覆盖人数。"),
            ("局部相交观测", f"C(k) = ∑[i<j, i与j均在场] 𝟙(dᵢⱼ < {2*R_PED:g})",
             "用本步更新后的在场位置计数，排除自身和重复对。几何相交不测量身体压力。"),
        ])
        integration.insert(0,"每步末端时刻先判断演练状态转移，本步写入对应事件与实际行人状态。")
        parameters.update(exercise_time={"unit":"模型秒","meaning":"预定的演练事件时点"},
                          response_delay={"unit":"模型秒","meaning":"倒地到就地协助的设定间隔"},
                          assistance_time={"unit":"模型秒","meaning":"开始协助到恢复行动的设定间隔"})
        assumptions.append("倒地是预设演练事件。响应和协助作为研究假设，源数据只约束实际绑定的参数。")
        limits.append("受助阶段是同一个人的外生状态。模型没有独立救助者、主动绕行策略或医学过程。"
                      "人体失稳、连锁倒地与伤害没有经过求解。")
        references.append("HSE 事件与应急响应 https://www.hse.gov.uk/event-safety/incidents-and-emergencies.htm")
    return {
        "source":"verified_implementation", "revision":2 if legacy_layout else 3,
        "layout":"separated_rejection" if separated else "independent_uniform",
        "name":"景区步道人群疏散演练" if exercise else "几何接触疏散",
        "description":"二维行人固定步长模型。通过局部相互作用、移动更新和状态帧记录研究疏散过程。",
        "equations":[{"group":group,"expression":expr,"meaning":meaning} for group,expr,meaning in equations],
        "parameters":parameters,"assumptions":assumptions,"limitations":limits,
        "integration":integration,"references":references,
    }


def _green_subsidy_method():
    from .models.spatial_audit import GreenSubsidyAuditGame, PAPER_URL
    equations = [
        ("拓扑", "i=(r,c),  N=L²,  r,c ∈ {0,…,L−1}",
         "每格一名监管人员、一户农业主体。两坐标均对 L 取模，邻域可取四邻或八邻。"),
        ("初态", "dᵢ(0)∼Bernoulli(y₀),  gᵢ(0)∼Bernoulli(z₀),  x(0)=x₀",
         "基层积极监管 d=1，绿色生产 g=1。x 表示单个审计机关的目标覆盖比例。"),
        ("派单", "A(k)⊂网格,  |A(k)|=⌊x(k)N⌋,  aᵢ(k)=𝟙(i∈A(k))",
         "风险模式优先抽查上一有样本审计周期发现的欺诈格及其局部邻域，其后从余格无放回抽选。"
         "随机模式均匀抽取，集中模式按距网格中心的距离安排。暂停时 A 为空。"),
        ("支付记号", "G=R_f+R_e+S_f−C_H,  M=R_f−C_L,  Q=R_d−C_d,  K=R_a−C_a",
         "同一格以索引 4a+2d+g 查表，下面按审计、监管、农业顺序给出三方支付。P_f=bS_f，B=bribe_fraction·S_f。"),
        ("支付 000", "(−S_f−R_d, R_d+B, M+S_f−B)", "未审计、监管松懈、农业欺诈。"),
        ("支付 001", "(−R_d, R_d, G)", "未审计、监管松懈、绿色生产。"),
        ("支付 010", "(0, Q, M−κP_f)", "未审计、积极监管、农业欺诈。κ=0 为表2，κ=1 对应式(1)。"),
        ("支付 011", "(0, Q, G)", "未审计、积极监管、绿色生产。"),
        ("支付 100", "(K+P_f+B, −P_dh, M−B−P_f)", "审计、监管松懈、农业欺诈。"),
        ("支付 101", "(K, −P_dl, G)", "审计、监管松懈、绿色生产。"),
        ("支付 110", "(K, Q, M−P_f)", "审计、积极监管、农业欺诈。"),
        ("支付 111", "(K, Q, G)", "审计、积极监管、绿色生产。"),
        ("审计反馈", "Δ=R_a−C_a+(J/nₐ)(S_f+P_f+B)+(D/nₐ)R_d",
         "nₐ 为上一周期已审计的格次，D 为其中松懈格次，J 为松懈且欺诈的共同格次。零样本时只比较审计隐性收益与成本。"),
        ("强度更新", "x(k+1)=clip(x(k)+[0.05 若 Δ>0，否则 −0.01], x_min, x_max)",
         "每到审计调整周期更新目标。暂停只将实际覆盖设置为零。目标仍按同一周期和当前可用证据计算。"),
        ("局部决策", "j*=argmax[j∈N(i)] Π_j(k−ℓ),  p=clip((Π_{j*}(k−ℓ)−Π_i(k))/(Π_max−Π_min),0,1)",
         "监管和农业分角色比较。各自到期时，以概率 p 采纳同角色邻居 j* 当时的策略。分母为相应角色八种支付的极差。"),
        ("结果量", "y(k)=Σdᵢ(k)/N,  z(k)=Σgᵢ(k)/N,  coverage(k)=|A(k)|/N",
         "报告覆盖率使用实际掩码，欺诈率为 1−z。审计发现数针对本轮策略更新前的状态。"),
    ]
    parameters = {name: {"unit": ("千元/亩" if "千元/亩" in spec["description"] else
                                    "MCS" if "MCS" in spec["description"] else "模型参数"),
                         "meaning": spec["description"]}
                  for name, spec in GreenSubsidyAuditGame.parameter_schema.items()}
    return {
        "description": "农业绿色补贴审计的三方空间演化博弈。策略调度、支付与邻域选择按一个蒙特卡洛步运行。",
        "equations": [{"group": name, "expression": expr, "meaning": meaning} for name, expr, meaning in equations],
        "parameters": parameters,
        "integration": [
            "先更新审计目标与抽查掩码，再计算每格两类主体的当期支付。双方读取同一份旧状态并同步写入新策略。",
            "图层时间 t>0 的审计掩码为刚完成回合，监管和农业是该回合更新结果。初态掩码为初始计划。",
            "若连续200个记录点的目标审计强度、积极监管率和绿色生产率标准差均小于0.0001，记录首个满足时点。运行继续到用户明确的终点。",
        ],
        "assumptions": [
            "默认采用论文表4情况6与 100×100 周期网格。论文表2与式(1)在 010 农户处罚项有分歧，运行记录所选版本。",
            "初始策略按概率独立抽样。并列最佳按上、下、左、右、对角的固定顺序选取。历史时滞不足时读取最早的已记录收益和策略。",
            "风险超预算时在风险集合均匀抽选。中心距离并列时按行优先。抽查和两类策略更新使用独立可复现随机流。",
        ],
        "limitations": [
            "参数依据属于发表的研究情景。缺少可追溯的区域微观观测，不能把模型内演化当作政策净效应。",
            "论文未随公开正文提供仿真程序。即时支付、采样和同步更新的独立实现可能产生不同的数值轨迹。",
            "模型没有策略突变，已消失的策略不会自发恢复。审计机关仅控制覆盖与抽样，模型没有机构间博弈。",
        ],
        "references": ["戴莹、赵琛（2026），《审计与经济研究》第5期，绿色补贴审计三方时空演化博弈，表2、表4、式(2)至式(3)。" + PAPER_URL],
    }


def model_method(model_id, definition=None, *, legacy_layout=False):
    if definition and definition.get('kind')=='program':
        return {'source':'archived_program','name':definition['name'],'description':definition['description'],
                'equations':[{'group':row['id']+' · '+row['function'],'expression':row['expression'],
                              'meaning':row['meaning']} for row in definition['equations']],
                'parameters':{key:{'unit':meta['unit'],'meaning':meta.get('label',key)}
                              for key,meta in definition['parameters'].items()},
                'integration':[definition['solver']['method'],definition['solver']['description'],
                    '参数干预按步边界执行。' if definition['solver']['intervention_clock']=='step' else
                    '参数干预按指定时刻分段调用advance，输出帧仍使用原定时钟；具体数值方法须正确处理变化的子步长。'],
                'assumptions':definition['assumptions'],'limitations':definition['limitations'],'references':[],
                'verification_note':'数学说明与对应源码均归档；结构关联不替代独立数学和经验验证'}
    if definition:
        return _dsl_method(definition)
    if model_id in ("NET114", "NET121"):
        return _pedestrian_method(model_id == "NET121", legacy_layout)
    if model_id == "NET122":
        return _green_subsidy_method()
    return None
