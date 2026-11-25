# 大衍工作区

## 当前新增执行通道

- 程序真实外部LLM主体：先读schema(build_model)的decision_policy、纯decision_requests、7参数advance。真实调用在宿主完成，密钥不进容器。状态绑定账本保证续接复用已接受动作，历史响应重放明确标记；不能把“隔离无网络”误解成没有主体决策通道。
- 实际三维空间：frame.space以水平bounds及vertical_bounds、terrain高度网格、floors楼板/holes、connectors三维路径输出，人口完整x/y/z及可选floor_id；人物与报告消费同一实际状态。领域运动与局部交互仍由源码实现并独立验算。
- 已审且实际验收的基线可直接global_sensitivity：给独立参数分布、metric、n、seeds，沿analysis_id续到全部真实样本；Word传run_id和analysis_id。冻结研究不被事后改写。
- 扩容用plan_capacity真实测量两档探针并实跑目标档，沿capacity_id续接，读取实际CPU/峰值内存/体积及外推误差。固定人数/时钟不自动改，自由规模采用建议仍重新审查。
- 成功、真实失败和用户纠正记忆在独立构思之后参与审查；跨措辞用实际语义比较。用户纠正用memory_feedback，原生真实原话由宿主绑定。只作参考，不替换当前问题，删除/清空和项目作用域保持。

本仓库是大衍（DAYAN）社会仿真与数据研究平台。它使用自己的 Python 运行引擎 `dayan/runtime.py`，支持受限 DSL `dayan/custom_models.py` 与隔离程序执行器 `dayan/program_runtime.py`。`external/god` 及其中的 AgentSociety/agentsociety2 是可选第三方对接。项目入口和安装方式见 `README.md`。

## DSH 原生建模

- 实现严谨性以本次实际提交的definition.source为准。闭合状态/单位/初边界、随机/事件时序与输入→方程→状态→观测，区分持久状态和派生/累计指标；禁止每步重置跨步量、假零残差、恒定检查量、无效wrapper或只靠场景证明动力学。具体工作规则见plugins/dayan/skills/dayan/SKILL.md。
- 自主源码与提交JSON保持同一版本：修改.py后重新读取并序列化到definition.source，再用同一文件依次validate_model/build_model；文件变化须重新预检。已经自主实现时不另调默认编译替换为第二份模型。逐条处理否决及反例，核对完整反馈后才重交，不能只改说明或漏同步实际提交源码。
- 当前任务范围与用户停止/不运行指令优先：只改提示词或发布时不启动模型、数值测试或全链验收；已经通过的无关能力不重复验证。

- 自建模型基线真实获审并运行后，按schema(experiment)以baseline_run_id、arms、metric和seeds做同源配对对照；省略时钟/参数/数据，平台由基线恢复。无需再让预置模型匹配器重新选题。MI研究仍走原冻结校准/诊断/留出；报告传实际experiment_id，零/负效应是结果，不能为过审强迫假设成立。

- next_action若包含continuation_token，只传回同action、design_id和凭据，平台从持久化任务恢复原文/会话/真实输入/运行设置；不重新填写参数或舍入数据。该凭据不改变方案、数据与科研冻结，修改自拟方案仍须显式修订。

- 自主实现获批方案时，`validate_model`和`build_model`可沿同一build续接凭据附加`definition`或原生`definition_path`。平台恢复原设置，代码仍正常预检、语义审核和实际执行；不能借此改变参数、数据、原文或会话。

- `modeling_guide.program_engine` 返回实际镜像状态与剩余缺口。`eligible=true` 时可以通过同一 `design_model → build_model` 通路选择 `kind=program`，实现不同人口池、动态图及连续/事件算法；先读 `schema(build_model)` 的完整合同。不要用旧DSL表达式限制拒绝可由受管程序真实实现的算法。源码只在无网络、无宿主挂载的固定Python/NumPy/SciPy/NetworkX镜像中执行。完整可变状态在state中，随机性只用传入rng，观察/验证/帧函数只读。
- 程序方案用 `source.advance` 及其真实辅助函数映射机制，`equations` 保存数学表达、实现函数和意义。人口分组保留各自数量、属性、单位和持久ID，场景来自实际frame。程序也须独立语义审查、原需求数值验收和同源报告。GeoJSON端口保留完整Feature与源CRS、坐标轴单位，模型可读取真实几何；这不自动证明碰撞、地形和空间算法有效。外部LLM主体、复杂场景和研究校准等尚未具备的部分以实时合同为准，不能以“能写Python”冒充已完成领域验证。
- 真实微观记录/关系通过`data_bindings`的`port/contract/columns`映射，并在程序`input_ports`声明同一合同。按实际来源解析规则采集（无标题、分隔符、ZIP成员均显式），完整保留同一行属性、原ID和时间区间。模型只读`inputs[port].columns`；人口数可用`count={"input_port":"people"}`由实际输入确定。`records`和`edges`支持主键/端点核对、单位/缺失及时间原点声明；完整输入进入检查点、运行包与报告。参数聚合仍用`field/parameter`。同一绑定贯穿方案、预检、构建、重复与恢复；不能把留出数据混作输入，也不能用“传入成功”代替真实消费、校准和输入扰动验算。
- 已知公开文件URL优先读`schema(collect_data)`并实际调用；不要猜`http`/`__list__`连接器。`collect_source`的schema列出真实connector枚举；它返回采集批次，而`collect_data`直接返回DS数据集。完成必要数据绑定后即可`design_model`，先取得通过审查的完整方案再编译；不需要预读平台各层源码来猜下一阶段的内部校验。
- `timeseries`保留系列身份与真实观测时点；clock显式声明series_by/interpolation/outside/missing/max_gap，源码按合同取值或跨观测点积分，不能把回溯插值当当时已知。区间数据用anchor=start/end明确源字段端点，原时刻不静默改写。自然语言人数由实际完整人口核对，不必为程序输入人口再造n参数；用户明确指定n时才须同名保留。人口属性的id/type/group/local_id是保留名，原身份放frame.populations[].ids。
- 程序帧的`relations`只放当前`sim_t`有效的完整关系，历史/未来边另存state，不能和当前图混计。方案用`relation_count`直接核对实际帧与同刻边数指标；端点和网络对状态推进的作用仍须独立验算。技术ID采用英文，中文主体类别保留于label。

- 收到自然语言仿真请求时，先通过 DSH 的 `dayan(action="execute", tool="modeling_guide", arguments={})` 从当前原文取得真实候选、能力缺口、数据预设及实际参数合同。新宿主也可直接用 `dayan(action="guide")`。依据返回的合同选已有模型用 `reviewed_run`，或选 `build_model` 新建。使用已有模型时，部分覆盖和实际运行成功是两个独立字段。日常建模用平台工具，源码查阅用于维护代码和定位平台故障。
- 平台可以用 `request` 自动完成审查与构建，也可以传入已批准的 `design_id`。原生助手自行编写 DSL 时，从 `schema(build_model)` 读取当前合同，并将同一份 `definition`、`design_id` 和运行选项先后提交给 `validate_model`、`build_model`。用户原文由宿主单独绑定，场景的 `requirements.quote` 逐字引用它。方案绑定原文、会话和实际执行设置。方程还须单独通过语义复核。
- 设计、编译和语义复核按阶段保存。`status=pending` 表示整个请求尚未完成，须继续回执 `next_action`，沿用 `design_id`、原文与运行设置；多种子任务的 `completed_runs` 列出已归档成员，续接不会重算它们。不能另起缩减方案。网络或工作进程中断时，相同调用可恢复已保存阶段。`approved` 仍须构建/运行；最终以真实 `run_id` 和验收回执为准。
- 自建DSL的计算检查点包含完整状态、随机流、局部历史、时钟、干预队列和观测/状态块。`solver_progress` 只表示尚未完成的实际进度，须按 `next_action` 继续到原定终点并通过原验收。其他执行协议的中途恢复能力须单独核对。
- 预检/编译返回 `revision_required` 时，用回执 `design_model(revise_from=原方案ID)` 针对实际缺陷修订并重新审核。原文、运行选项及有效研究阶段保持，新方案另有编号，旧版不覆盖。不要修改变量含义、添加零乘状态的伪依赖、删原文验收或修改平台文件绕过检查。
- `pending`中的草稿校验失败是下一次同一`next_action`的定向修复依据，不能当成最终否决并改做无关探针。Agent自行编写含多行源码的定义时，用JSON序列化写成项目内文件，通过原生`definition_path`（相对会话目录）先`validate_model`，再以同文件、同`design_id`和原运行选项`build_model`。它与`definition`/`request`互斥，原文仍由会话绑定；宿主只读JSON，所有后台审核照常执行。不要在工具参数手抄巨型源码或混用Python None与JSON null。
- 真实语义否决也返回上述定向修订入口，保留否决依据和实际定义。重复提交同一未改正定义会复用否决，不能用反复重审换取通过；编译修订方案时须处理原失败证据。
- 若复杂方案回执含`plan_omitted`，先按`plan_access`调用原生`design_details`。该只读动作绑定本会话；section可读plan/execution/review/request，大字段用field，数组沿next_offset读至null。编写定义前读全函数路径、方程、观测与全部criteria，不能凭“approved”猜实现或去磁盘搜索方案。自动build_model仍读取同号完整方案。
- DSL 主体更新使用上一步的属性和全局聚合。初始化不能读取同一主体的其他属性。固定位置的元胞空间用 agents.grid 表达四邻或八邻；boundary 可选 periodic、reflecting、absorbing，含局部统计和按邻居收益取状态。反射发生在格面，吸收域外默认0且虚格不参与收益模仿；原文边界必须与实际执行一致。规模由 guide.execution_scale 和规约内存预检确定。超过 2000 主体时用列式推进及无损分列归档。按原文保留主体数、网格长宽、步数和逐步归档要求。可移动异类人口池、自定义拓扑、连续碰撞及多楼层实体运动须核对专门执行入口。农业绿色补贴审计的三方 CA＋ABM 原生模型可保存三层逐格状态。关键机制超出当前执行入口时说明具体缺口、参数证据和预期检验。
- 用户需要看见空间中的人物行动时，用模型计算主体坐标和动作状态，在 `scenario.facilities` 声明场地、出口和其他实际设施，并将动作属性映射到 `visualization.action_poses`。核对真实状态帧中的位置、设施与动作。汇总趋势由分析区显示。
- 预检只能证明结构与可解析约束通过。实际运行和工作台大屏以返回的 `run_id` 或多种子归档为准。`payload.observations` 是实际时间序列，有 `run_receipt` 时可直接读取起止观测。真实数据要求必须完成采集、数据集核对和显式绑定。模型能够运行与经过现实校准是两个不同结论。
- `eligible_models` 仅是能力初筛。方案须有原文逐项适配、替代结构取舍、实际状态方程、可证伪的事前检查和局限。关键缺陷未解决或运行验收失败时保留回执，不能声称完成。预定倒地演练需要原文明确选择，日常步速参考不能代替应急校准。只有原文明确接受诊断子范围才允许 `allow_partial`。
- Word 由 `report_run` 使用本轮实际 `run_id` 生成，含建模依据、实际方程和参数、图表、主要发现及适用范围。报告回执已给文件路径和主要发现，直接用它答复。校准研究使用 `research_report(study_id)`。
- 新建科研需求先实际采集目标DS，用`research_model_prepare`固定完整原文、观测/单位、时钟、三分区、输入、网格、重复、阈值与诊断。按MI和next_action设计/预检/修订/构建；基线只是中间态，自动接同MS实际校准/诊断/留出，之后`research_finalize`真正运行所选参数的完整状态，再`research_report`。已有当前版本已审且数值验收通过的基线可直接`research_model_create`。单个展示seed不代表重复均值，失败结论必须保留；不得删校准要求、用基线Word或创建成功冒充经验验证。未知复杂机制仍需真实数值与领域验收。
- 研究诊断按schema的oneOf明确dynamics=deterministic或ensemble_moments，不填观测名；随机矩模式至少两个seed并给max_scaled_mc_se。准备时核对结构/时钟/单位，模型生成后继续核对真实参数和方程路径。execution.delivery提供真实回放状态API与工作台恢复入口；科研显示所选结果、报告用同MS。方案blocked按next_action的revise_from在同MI下修订，有效阶段复用、旧否决保留，不另建缩减研究或直接构建未批准方案。
- 未选择模型时，消融以binding={"kind":"approved_plan"}事前声明parameters/mechanism/outputs/basis，不猜rates或source。后续方案diagnostic_bindings按每个原消融id给真实演化rule_refs/reason，独立审核逐项返回diagnostic_checks；编译核路径存在及程序advance可达，同MS保存科学原声明和绑定的方案/定义hash。已明确实现可继续用旧rule_refs，两者互斥。绑定不允许改科学参数、机制、指标、尺度或判据，不能插入伪调用凑路径。
- execution.research.execution_rules给实际诊断/留出/轨迹复现协议：新版将全部细化档与首档基线在共同物理时点比较并取最大差异；历史旧规则保留版本与局限。finalize只复现轨迹，不重评留出。input_availability/input_usage_audit是实际冻结的初值使用证据；科研复核包下载/hash在execution.delivery.research。另行采集来源定义文件不等于已经进入方案或报告，缺少核验链接时须保留缺口，不能把资料假装成数值输入。

- 来源定义、单位、方法或许可文字先实际collect_data（可为background/source_snapshot），再读schema(research_model_context)，以research_intent_id和evidence的DS/JSON Pointer附到同MI。它核原文/hash，保持原输入/目标/网格/阈值/种子；blocked后追加会重新审查，运行后不能事后补证据。文字依据不伪装成数值输入，也不强迫改选program。execution.research.target_integrity提供目标时点计数、起止、间隔和原件核验事实；按原话检查期望覆盖，不要求沙箱读取验证/留出值做数据完整性检查。

- modeling_guide.runtime_clock和真实LLM调用审计给平台墙上时钟，仿真年份/t=0仍按原话；不用模型训练记忆中的当前日期否定实际采集。target_sources.retrieved_at是采集记录，不是源方发布时间。观测绑定可省略time_origin继承顶层统一标识，显式填写须一致，实际时点仍由columns单位/scale/offset核验。source_scope/target_scope仅写地区或群体标识，不写模型变量、年份或初值用途；匹配标签仅标declared_match，不能冒充已核对原始记录的地区成员。

复杂工具参数可用原生`arguments_path`：先按`schema(实际工具名)`编写完整参数，用JSON序列化保存项目内UTF-8文件`{"tool":"实际工具名","arguments":{完整参数}}`，再调用`dayan({action:"execute",tool:"同一工具名",arguments_path:"parameters.json"})`。路径相对当前会话目录；不能混用inline arguments或其他顶层参数。宿主只读文件并核工具名/原字节hash，后台原文、schema、审查和数值校验不变。研究prepare的`question`在DSH原生参数中可省略，后台从真实用户消息逐字绑定；独立HTTP调用仍按原schema提供question。不要手抄巨型JSON中的多层数组或重复长原文。

原生dayan工具在分派前发生MALFORMED_RESPONSE时，本插件仅在本项目会话内提供同turn/step最多5次定向恢复，原失败不删；恢复提示使用带平台source标记的上下文，不能当作新的用户需求。按提示核实时schema并改用上述文件通道，保留已有DS/MI/MD/MS和全部科学约束；不用重新采集、重建成功阶段或降低验收。其他工具、认证错误、取消及其他项目不由此钩子接管。预算耗尽仍保留真实失败，不冒充任务完成。

通过正常入口执行和复核。已有运行的修改用真实 `last_run.run_id`。不要通过脚本注册、直接写工件或替换成无关模型来跳过合同检查。

在线文献的提供方检索、逐篇正文读取、逐篇方法/依据/验证/局限审核和跨论文比较分别持久化，pending沿同design_id续接，已接受阶段不重取。默认5–10篇是研究目标；暂时不足时依据实际已读材料与明确假设继续设计、补查和数值检验，显示真实数量，不自动把篇数目标变成拒绝建模的门槛。具体必需证据按用户原话判断，论文数量、期刊索引与模型经验有效性分开说明。

program可用实际Python算法实现局部CA与异类ABM、自定义拓扑，完整格点/角色用分组人口坐标和属性归档；按本轮算法核邻接/边界/更新顺序，不按“CA”名称自动拒绝。文献结论可以关联多段真实S编号。阶段格式恢复只补可确定的对象闭合符并保留原始响应，语义/来源/数值审核照常执行，不能把格式错误扩大成整套任务重做。

design_model/build_model/validate_model的parameters是实际运行取值，如{"grid_rows":60,"fraud_penalty":3}。type/default/unit/minimum等参数定义属于definition.parameters，不作为运行值传入；平台在开始设计前指出该类形状错误，避免完成长方案后才发现无法运行。

新建任务默认让同一份方案贯穿全链：design_model一般省略尚未确定的parameters；pending直接执行next_action，不自行等待或重开已完成阶段；approved后用同design_id及运行设置调用build_model，省略definition让平台编译完整获审方案。需要自行实现时先读全design_details，再以同definition_path、design_id和设置依次validate_model/build_model，避免内外两份模型互相冲突。调整Agent自拟取值用design_model(revise_from=原编号,revise_proposal=true)重新审核；原话固定参数、原文、会话和MI科研协议保持，旧方案保留。

program按实际接口与实现验收，不继承DSL的专题限制；三维、局部CA、SDE、全局敏感性等名称不是拒绝自主设计的理由。外部服务端口等真实缺口照实指出。整组报告用report_run(实际成员run_id,experiment_id=实际组号)或analysis_id（二选一），由全部真实成员生成，不能以单条轨迹代替重复统计。
