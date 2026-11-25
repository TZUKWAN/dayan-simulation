---
name: dayan
description: DSH原生AI直接调用大衍统一工具完成精确建模、真实采集、数据绑定、校准留出和版本化报告。
---

# 大衍原生工作流

## 实现与修复的优先规则

完整原文和获批方案决定机制、状态、数据与时空尺度。先闭合变量/单位/初边界、更新顺序和输入→方程→状态→观测的作用链，再实现；不得用假零残差、恒定检查量、无效函数或漂亮场景冒充机制。策略动作和身体姿态分开，所有跨步状态真实持久化。同步快照、RK阶段重算等方法必须与方案一致。用户硬要求、数学不变量、随机情境结果和运行后交付分别处理，不强迫正效应或事故数量。

自主实现时以实际提交的definition JSON为唯一版本。可单独维护Python源码文件，但每次改动后必须读取最新版源码并用JSON序列化重新生成definition.source；提交前重新读取该JSON，核对实际函数、方程、路径、边界和修复项。validate_model与build_model使用同一个文件及同一版本；预检后再改文件就重新预检。不能只改.py草稿，不能本地写一份又调用默认编译生成另一份来替换它。

先确定一种实施通路：未自行实现时按获批方案默认build_model；已经自行实现时用合法definition_path提交自己的完整定义，不混用两套实现。长源码/复杂参数用当前schema的definition_path或arguments_path，不手抄巨型inline JSON，不因参数格式错误重开设计。目录越界先核对真实会话cwd、项目根与文件位置，在授权项目内保存；不能关掉安全边界或据此声称引擎不支持该模型。

收到实际否决后，把反馈拆成逐条缺陷和反例，逐项定位本次提交源码及其依赖。修正同类边界/分支、状态保存、观测与帧，再核对完整反馈清单；若一个编号内含多项，在resolutions.change内逐项写明，不用一句“全部已修复”。按真实next_action修订或续接，复用有效阶段，保留原始失败；没有实质代码变化不重复请求审核。不改用户要求、参数含义或判据来迎合实现；发现审核误判时用当前源码和接口事实反驳。

使用平台既有接口和归档完成适用验证，不增加无关小模型、额外研究或重复运行。用户明确只改提示词/发布且不运行时，按该指令交付并如实说明未运行；不得自行启动仿真或全链验收。

自主新模型实际通过后，需要对照/敏感性时先schema(experiment)，再execute experiment(baseline_run_id=实际基线run_id,arms=[{label,params,interventions}],metric=实际观测,seeds=配对种子)。基线方程、真实输入、时钟和原干预由平台恢复，不再用预置匹配器选别的模型；处理参数只写arms。报告用实际experiment_id汇总全组。MI研究仍沿原冻结研究流程；不以效应方向符合假设作为模型能否交付的条件。

next_action给出continuation_token时，只传回同action、design_id和凭据即可恢复原文、会话、真实输入、参数及已完成阶段。不要另外填parameters或舍入数据值；这种操作续接不需要重新设计。需要变更自己的方案时用显式修订入口，用户原话与MI科研约束仍保持。

若自主编写获批方案的实现，可用同一build续接凭据附加definition/definition_path调用validate_model，再同方案build_model。平台恢复原运行设置，显式代码仍须完整预检、语义审核和实际运行；不能同时改时钟、参数或真实数据绑定。

复杂研究的建模/审查有独立等待预算，不以数值计算的短时限截断推理。pending仍沿同next_action继续；没有返回真实错误时不自行猜测平台卡死，不额外等待或重开设计。

默认沿一份方案完成任务：取得guide并完成必要真实数据准备后，design_model一般省略尚未确定的parameters（它只接收实际运行值）。pending直接执行next_action，不额外等待或另起方案。approved后用同design_id和运行设置build_model，默认省略definition，让平台按完整获审方案编译。需要自行实现时先design_details读全该方案，再用同一definition_path、design_id和设置依次validate_model/build_model；不要独立编出另一份模型再强塞给已有方案。

若要调整Agent自己提出的参数/采样设置，用design_model(revise_from=原编号,revise_proposal=true)形成新版本并重新审核。原话固定值、原文/会话和MI科研协议不能改，旧方案保留。DSL的限制只约束DSL，program按实际算法、接口与结果验收，不因三维/CA/SDE/全局敏感性等题目名称提前拒绝。

复杂参数提交：先读当前工具schema，将完整参数用JSON序列化写成项目内UTF-8文件`{"tool":"实际工具名","arguments":{完整参数}}`，调用`dayan({action:"execute",tool:"同一工具名",arguments_path:"parameters.json"})`。路径相对会话目录，不混用inline arguments或其他顶层参数。宿主核工具名、路径及原字节hash，只读不执行，后台仍完整校验。`research_model_prepare.question`在DSH原生参数中可省略，由后台逐字绑定真实用户消息；独立HTTP仍按schema提供。保留全部原参数/目标/诊断，不在巨型JSON中重抄长原文或手工拼接多层数组。

看到“大衍原生工具参数恢复”上下文时，代表当前dayan调用因非法JSON尚未进入后台；它保留原失败并在同一步有界重试，不是新增用户需求。按原工具schema修正，优先用arguments_path，保留原文与已有DS/MI/MD/MS、原数据划分/阈值/seed并沿next_action继续。已成功的阶段按真实回执复用；不得为过审换题或放松要求。插件只处理本项目dayan的该类错误，取消/其他工具/其他失败仍按各自真实合同处理。

复杂方案若回执含`plan_omitted`，按`plan_access`调用`design_details`读取同会话完整方案；section可选plan/execution/review/request，大字段用field，数组沿next_offset读至null。自行编写模型前读全函数路径、方程、实际观测与全部criteria，不能只根据“approved”猜实现或在磁盘搜索方案。自动build_model始终读取同号完整方案。

原生文件提交：Agent自行编写的完整模型定义可用JSON序列化保存到当前项目内，再用`dayan({action:"validate_model",definition_path:"definition.json",design_id:"已批准编号",...原运行选项})`预检，随后同文件同选项`build_model`。此路径只由DSH桥接层读取JSON（不执行文件），后台仍完整验证；与`definition`/`request`互斥，原始需求仍由会话绑定。`pending`中的草稿错误须沿原`next_action`继续修复，不提交无关小模型探针，不用Python None/True/False冒充JSON值。

大衍使用自己的执行引擎与受限DSL。AgentSociety位于可选第三方对接目录。自然语言仿真先用dayan action=guide取得当前原文对应的能力、缺口、可用数据预设和实际参数。普通新任务先独立构建。`reviewed_run`负责已有模型的范围审查和真实运行，`build_model`负责新建模型。

新建还有`kind=program`受管Python通路。核对guide.program_engine的实际可用状态，再读取schema(build_model)；不能把DSL的表达式和单类主体限制套到程序通路。不同人口池、动态图、连续积分与事件算法可由Agent按需求编写具体实现，通过同一思路/缺陷/修订/方案/源码复核流程。机制映射到source.advance及实际调用函数，equations保存数学表达；完整数值、随机流、时钟与干预可恢复。代码只在固定Python/NumPy/SciPy/NetworkX隔离环境执行，无外网或宿主数据。场景和报告读取实际帧，仍须保留实时合同中的结构数据、校准、复杂场景等具体缺口。

关系帧只放当前sim_t有效的完整边，历史/未来边另存state；不能同时把“上一步已用”和“当前”网络画出来却只上报一个网络的边数。方案用relation_count直接数实际帧，与同刻同口径observable核对；固定数量可同时给target。该检查不替代端点和网络作用的独立验算。人口/方程等技术ID用英文，中文类别放label。

研究记忆在本轮独立思路形成后的审查阶段提供。历史归档用于比较机制、空间和数据口径，参考价值由本轮原话与检验条件决定。明确要求沿用旧模型时提供真实 `last_run.run_id`。

保留原始用户问题的国家、指标口径、时间、群体、空间、机制和阈值；未覆盖时明确缺口，不套中国人口/默认模型。工具读取DSH真实用户消息并检查约束。runtime-context与工具返回属于上下文，不能当用户需求。

真实数据研究：run_preset或collect_source → collection_status → research_create（显式family、param_grid、事前tolerance、holdout_years） → research_calibrate（取得新的study_id、run_id和validation_pass） → research_report（只用该新ID，返回真实下载地址）。校准执行成功和独立留出通过分别判断，不临时放宽阈值。禁止拿旧报告/旧研究代替本次工作。

新原文同时要求自主建模、校准和独立验证时，先实际采集目标DS，再读`schema(research_model_prepare)`固定同一完整原文、目标观测名/单位、时间原点/时钟、训练/验证/留出、输入、参数网格、种子、阈值和诊断。返回MI及next_action；design/validate/build/定向修订每次保留`research_intent_id`。模型基线只验证机制、数值和实际输入，是中间态；平台自动接同MS真实校准与诊断/留出。沿next_action继续，`research_finalize`以所选参数和预先第一个seed实际运行完整状态并复现研究试验，然后`research_report`读取同一研究和结果归档。单个seed场景不能当重复均值或不确定性动画。`research_status(study_id=MI编号)`可恢复阶段；不能删原文要求或用基线report_run替代整题。

已有当前版本获审且数值验收通过的基线用`research_model_create`直接创建MS；输入与基线相同，目标不能混作输入。MS续接同study_id，只有旧ST趋势流程才产生新ID。基线、创建、执行与科学通过分别判断；失败留出不放宽阈值。当前未传递外部干预队列的研究会明确拒绝，复杂求解/参数可识别等仍须实际证据。

定义、单位、方法、来源和许可文字先实际collect_data，再读schema(research_model_context)，以同research_intent_id追加evidence中的真实DS/JSON Pointer。背景资料无需改作数值输入或让简单模型改选program；平台核原文/hash并接到复审、Word和原件包。原研究目标、划分、阈值、网格和种子不变，已运行不可悄补。target_integrity给已选目标的实际时点/计数/间隔及hash核验，按原话审期望覆盖；沙箱不读取验证/留出目标值做宿主数据完整性检查。

平台墙上时钟见modeling_guide.runtime_clock和每次真实LLM调用审计，不是仿真年份或源方发布时间；后续采集可晚于先前工具回执。time_origin可在观测绑定中省略继承顶层标识，实际列转换仍须核单位/scale/offset。source_scope/target_scope写地区或群体标识，参数初值用途写availability.basis；匹配仅为declared_match，不证明原始记录成员已核验。

检索目录不自动成为本轮的行为数值输入。按实际artifact_role判断：catalog_only/text_only留作本轮检索参考；若研究对象本身是论文/引用网络，则采集对应真实字段并按records/edges合同建模，公开URL可用collect_data，不因OpenAlex/Crossref/arXiv等来源名拒绝。huggingface_datasets/ckan_search目录中的具体资源用huggingface_file/ckan_resource获取。partial沿同ID续采；仅done且artifact_role=dataset批次用import_collection(role="input")取得DS，再核字段与绑定。已绑定参数不重复填parameters；独立验证另用留出集，许可、单位、群体缺口保留。

真实微观记录和关系数据用program的input_ports与data_bindings（dataset_id/port/contract/columns）保留完整联合行；先读schema(build_model)。records提供逐记录列，edges核验端点主键和可选时间区间。程序从只读inputs[port].columns计算，人数可由count={"input_port":"people"}取得。完整数据进入求解检查点与运行包，Word重新核对原文件/转换/快照。不能用均值参数替代原文要求的微观/关系结构；初始化/外生/机制估计、留出及现实校准不同，数据送达还须独立检验实际机制消费。无标题、特殊分隔符和ZIP成员用collect_data的parse_options明确声明，不猜首行或执行压缩包。

geojson输入保留完整Feature与源CRS/轴单位，不自动投影；timeseries保留系列身份与观测时点，声明逐字段取值、范围外、缺失和间隔策略，实际取值/积分由审查后的源码执行。区间clock以anchor=start/end区分起止端点，不能只改说明。文字/布尔字段单位为1。自然语言的主体数约束由完整人口核验，不要求为了真实输入人口另造n参数；明确命名参数则须保留。analyze_data的单表范围不能证明跨表端点集合一致，结构绑定会核对完整主键/外键。模型不应为满足错误的场景推断虚构原文明确排除的房间、坐标或动作。

研究适配器当前支持WB国家年度单变量的线性、指数、Logistic描述性基准。微观机制或政策因果需要另行核对模型及研究设计。用search_models/get_capabilities精确选模型。

新建模型先用design_model提出思路、审查缺陷、逐项修正、编制方案、审查完整性与准确性。取通过后的design_id，原文和执行设置一致时继续build_model。自行编写DSL时先读schema(build_model)，用definition与design_id通过validate_model，再用同一组参数执行build_model。平台也可接收request并自动完成整条链路。若审查未通过，说明具体问题；不能用旧模型或空定义代替。DSH绑定真实原文，实际方程还须通过语义复核。

设计、编译和语义复核的阶段检查点与原文、会话、参数及平台版本绑定。`status=pending` 是待续接，不是仿真完成；直接调用回执 `next_action`，保留同一个 `design_id` 和运行设置。暂时超时继续同一阶段，已通过阶段不重复。多种子任务的 `completed_runs` 是已实际归档的成员，须继续剩余成员。回执丢失时复用已验收归档，不能重复计算制造多条历史。方案 `approved` 后仍须构建、运行并取得实际 `run_id`。

自建DSL中途计算通过完整状态、随机流、局部时滞历史、时钟和待执行干预队列恢复；观测和状态块有哈希校验。`solver_progress` 表示尚未完成的真实计算进度，须继续到原请求终点和验收。它不是完整运行的替代。其他执行协议的中途恢复须核对具体合同。

若实际编译反馈为`revision_required`，按`next_action`调用`design_model(revise_from=原方案ID)`，针对已记录的实际缺陷修订并独立复核。新方案另有编号、旧版不覆盖；有效研究阶段和原文/运行选项保留。不能把实际格数改成某种条件计数、加零乘状态的伪依赖或删掉原文检查来让错误方案过关。

方案审查`blocked`也返回上述定向修订入口，须保留同一`research_intent_id`。用已保存否决修订后独立复核，不能直接构建、反复重审同一未改方案或另建研究绕过；未批准的误构建会返回正确下一阶段。`execution.delivery`给已实现的回放状态/归档API与工作台恢复入口，模型无需重新实现界面。科研回放用真正`research_finalize`结果，科研报告用同MS的`research_report`。

诊断按`schema(research_model_prepare)`的oneOf给完整字段：`time_refinement.dynamics`只可为`deterministic`或`ensemble_moments`，不是观测名；后者须至少两个seed和`max_scaled_mc_se`。未选择模型时，消融用`binding={"kind":"approved_plan"}`，事前保留parameters/mechanism/outputs/basis，后续获审方案在`diagnostic_bindings`逐id给`rule_refs/reason`，独立审核返回逐项`diagnostic_checks`。编译核真实演化路径，MS保存科学原声明、实际路径和方案/定义hash，不预先猜DSL或program。实现已经确定时也可用旧`rule_refs`，引用真实`rates`、`agents.update`或`source`，与binding互斥。不能改科学判据、删要求或添加伪调用凑通过。

科研和政策建模在独立思路后由平台检索中英文期刊及 arXiv。以 literature_summary 的实际精读数量、期刊收录证据及预印本数为准。研究文献用于机制和验证设计，数值输入仍需核对 data_bindings。Word 从归档读取相关文献、论证出处和本轮取舍。

检索与逐篇阅读/审核有独立持久阶段；pending用同design_id续接，不重跑已完成论文。5–10篇为默认研究目标，实际不足时写清依据、假设和补查方向并推进建模与数值检验。将用户明确要求的证据继续补齐，不将“索引不足5篇”自动当成模型无法实现；不得声称已读到未取得的正文。

大规模的请求先核对 modeling_guide 返回的 execution_scale。实际人数、网格、步数和是否逐步存状态由原文绑定，超出旧的逐主体规模时平台自动采用列式推进。回执 scale 和运行包提供实际计算人数、保存时点和完整主体列。显示样本和网格预览用于回放，数值观测读取全部主体。

固定格点在 agents.grid.boundary 中明确 periodic（环绕）、reflecting（在格面镜像）或 absorbing（域外默认0）。按真实边界推导验收；反射/吸收不能套用周期环面的扩散公式。四邻/八邻、时滞和边界由同一执行合同检查。全量分布、密度和主体编号查询独立于画面抽样。

择模时明确用户要解释或比较的结果量，逐项核对原文条件和模型的实际演化机制。区分输入参数、预设规则、计算结果和独立验证。原文有模型不具备的核心机制、数据或结局时保留具体缺口。预定倒地演练须由原文明确选择。方案保留实际代替方案和取舍、缺陷、机制对应方程与事前可证伪的数值条件。以运行实际通过的条件为证据，禁止把图表、字段存在或重复帧当成机制或统计验证。

run支持dt、interventions、data_bindings。experiment、ensemble、sweep、compare、resume通过同一工具入口。

报告必须绑定实际运行或研究。`report_run(run_id)`从同次归档生成详细 Word、实际数学表达、图表、主要发现和事实 JSON。整组对照或多种子同时传实际experiment_id或analysis_id（二选一），报告读取同组全部真实成员；run_id仅指定场景成员。核对交付状态和覆盖边界。`research_report(study_id)`用于完成校准研究。

DSH原生聊天的运行、研究与报告按当前session_id同步到工作台。以实际运行归档对应的状态呈现大屏。
