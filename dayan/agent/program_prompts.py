"""Shared program contract for discovery, design, compilation and review."""

DESIGN = '''可选计算路线kind=program：普通Python数值算法在固定Python/NumPy/SciPy/NetworkX隔离环境执行。可独立保存不同人口池、动态图、连续状态和事件队列；宏步内能细分积分和事件，外部观测仍在0及每个宏步末采样。每组保存完整属性、单位和持久ID，关系边连到实际主体；主体显示抽样不影响完整统计。
本阶段只按当前phase要求返回思路、批评、修订、方案或审核对象。尤其plan仍使用scene、variables、data、observables、criteria、coverage等方案字段；不要返回source、scenario、parameters定义、程序代码或占位符。代码合同仅供获批后的编译阶段。
program方案通过source.advance及实际辅助函数引用机制；source.initialize/observe/frame/validate是支撑证据，equations.ID说明方程，populations.ID说明独立群体。方案不受DSL的单人口、512字符或无数组限制。具体算法、状态、时钟、误差和验证仍须完整设计。
execution.inferred_population_parameter表示从“92人”等自然数量推导的兼容参数名，不是用户指定必须叫n。程序可用实际输入人口/分组数量满足scale_requested，不必添加冗余n；平台仍核对完整实际人数。用户明确写n=92时则须保留该同名参数。
方程/人口/参数/观测ID统一以英文字母开头，只含字母、数字或下划线且最多40字符，例如populations.people；中文类别用label、中文含义用说明，不能写populations.居民。source函数名保持实际Python函数名。
state_frames.relations表示sim_t当时生效的完整关系网络，不能混入上一步已用边或未来计划边；历史拓扑保存于state或另行说明的fields，不参与当前图计数。动态网络方案必须安排relation_count直接检查实际关系帧，并与同一时刻、同一范围的边数观测对账；固定边数另给target。它只验证结构，仍须独立验证网络端点和关系对状态推进的作用。
运行参数ticks/dt/seed与模型参数分开。方案可安排顶层state_every正整数控制完整场景帧的归档间隔，计算与观测仍覆盖每步，保留初末帧；只写interval_frame参数不控制平台保存。原文要求逐步全帧时强制1。改变政策的时间可由程序选择step或continuous；continuous分割advance，算法必须处理真实子步长度。观察、验证、帧函数纯读；所有可变状态含随机流/事件游标可恢复，不重复初始化。
真实数据须先collect_data/import_collection并显式data_bindings。records/edges端口保留联合列、稳定ID与时间区间，execution.structured_inputs只给合同与数量，execution.data_bindings保留来源/转换/hash；不把原始微观记录发入提示。方案说明各端口怎样进入initialize/advance，保留输入扰动检查，不能仅引用输入行数证明机制有效。
原文要求独立复算时，方案须说明参照从只读inputs、解析解或独立算法得到；不从待检主state中的派生时间、端点、步长日志或结果缓存取参照。比较器可以读取主state的待检结果，但不能用该结果生成自己的预期值。明确的数据条数/部门数/ID集合等前提须设计实际检查，不能仅在描述中断言。
geojson端口保留完整Feature/几何/属性/身份及原坐标，源CRS与模型声明必须一致，不会自动投影；几何格式核对不代表拓扑或测量准确。方案引用input_ports.端口名并说明坐标如何实际参与计算和场景。
局部CA和ABM可按问题用NumPy/SciPy/NetworkX实现，不受DSL四/八邻域或单人口表限制。方案写明真实邻接、边界、同步/异步更新与随机流；按实际代码给逐格参照，不能用全局均值冒充局部相互作用。格点/角色的完整坐标和属性可用各组frame.populations保存，平台生成显示样本；有连续场或专门网格视图需求时核对其实际消费者。
没有宿主文件、外网、现场数据或LLM调用被自动注入。复杂场景的具体消费和经验数据依据按实际接口实现；数学假设、数值正确性与领域验证分别说明。'''

CONTRACT = '''kind="program"使用受管隔离Python求解器，可按问题实现异类人口、动态图、连续积分、事件反馈等算法。
可选顶层state_every为正整数宏步归档间隔，例如state_every=5保存t=0、5、10等及终帧。它不改变计算、逐步观测、主体数量或完整检查点；原文要求每步全帧时平台强制1。规划时依据实际帧/字节预算选取，不能只声明interval_frame参数却不接入归档。frame函数每次须返回实际帧，不返回None、skip、should_save或其他自造字段；保存调度由平台执行。
这条路线不是现成的行业模型。方案必须说明具体方程、数值方法、单位、初边界、事件优先级、误差控制和事前验收。
标准库及固定NumPy/SciPy/NetworkX可用；无网络、无宿主目录、无密钥、无pip安装。真实结构数据通过明确input_ports/data_bindings进入inputs；真实外部LLM决策使用下面的decision_policy通道，不能在源码里联网或虚构调用。
完整定义字段：kind,name,description,time_unit,parameters,source,solver,observables,populations,equations,mechanisms,assumptions,limitations；空间需要scenario。source是完整Python代码字符串，不在宿主导入。
parameters={参数名:{type:"float|int|bool|str",default:实际默认值,unit:单位,minimum:可选下界,maximum:可选上界,mutable:可选布尔}}。ticks/dt/seed只作为运行选项。mutable仅允许数值控制量；初始化人口数不声明可变。
input_ports为可选端口字典，与当次data_bindings带port的contract逐项相同；无结构输入时省略。合同kind=records或edges，purpose=initialization/exogenous_input/mechanism_estimation，fields={列名:{type:number/integer/string/boolean,unit:实际单位,nullable:可选布尔默认false}}，primary_key为不可缺失唯一字段列表。edges另须directed布尔和endpoints={source:{field:本端点列,port:人口端口,key:该端口单字段主键},target:同样结构}。时间区间用clock={field:数值时刻字段,origin:原点含义说明,interval:实际正时长或改用end_field:结束字段,boundary:"left_closed_right_open"}；时间单位由字段unit明确，不自动换成模型时钟，源码必须精确处理转换和原点。
文字/布尔字段unit和source_unit用"1"，不写category/identifier作为文字单位。clock给interval时必须显式anchor="start"或"end"；end表示[field-interval,field)。也可显式映射开始/结束两列使用end_field，此时field为开始列，anchor不能是end。不能只在origin说明中改变端点含义；实际源码、合同及输入time_summary须同口径。历史无anchor合同保留原样并标明端点未以字段声明，不自动推断。时间单位采用second/minute等完整拼写，非零原点offset须说明。
点时序用kind=timeseries，clock={field:数值时刻列,origin:原点说明,series_by:[系列身份字段],interpolation:{取值字段:"linear|previous|exact"},outside:"error|hold",missing:"error|preserve",max_gap:时钟单位正间隔或null}。同一系列时刻严格递增，重复不自动去重，必要时绑定显式order_by。linear仅数值列且每系列至少两点，缺失和间隔按合同检查。inputs仍给完整列，宿主不自动插值；源码须按各字段规则真正取值，并在实际观测时点拆分区间积分，不能跨突变直接用宏步端点。exact仅允许观测时点取值，不能无依据积分；outside=error必须拒绝外推，hold只能明确沿边界值。linear使用未来端点，是回溯假设，不证明当时已知；previous也须另核验发布时间。行数不等于主体数，series_by定义各系列身份。不得静默合并系列、跨缺失填值或把插值结果称原始观测。
data_bindings每个结构条目为{dataset_id:实际DS编号,port:端口名,contract:上述合同,columns:{目标列:{field:源列,source_unit:元数据缺失时的已核验单位,scale:显式单位换算倍率,offset:可选偏移,transformation_note:非零偏移依据,missing_values:显式缺失标记,value_map:可选完整类别映射}},path:可选记录数组路径,filters:可选源字段精确匹配,order_by:可选目标字段或字段列表}。数值使用实际类型转换；ID文本保留前导零；缺失不得静默丢弃/补0，未知类别不得默认映射。支持同名自定义单位及明确时间/长度/比例标准换算，其他科学变换在审核后的程序中实现并说明。
运行时inputs[端口]={kind,contract,count,columns:{字段:完整列表},source_row_indices:原始行号列表}。只读，所有入口可读；需要推进的数据复制到state，不能修改inputs列表。人口数可写count={input_port:端口名}，运行前由真实输入记录数确定；不要为硬编码默认人口数截取来源。未知、缺失或合同不符的端口在运行前拒绝。完整输入快照进入检查点和运行包，恢复沿用相同hash；传入成功仅证明数据交付，仍须独立验证初始化、关系端点及数值变化。
geojson端口同样声明purpose/fields/primary_key，fields可以为空；另须geometry={crs:实际源坐标系,axes:按原坐标顺序的轴名列表,units:对应单位列表,coordinate_evidence:源文档依据,allow_null:是否允许缺失几何}。默认GeoJSON为OGC:CRS84，EPSG:4326同样按longitude/latitude、degree顺序；额外维度逐一说明，例如USGS第三坐标是深度km而非高程m。自定义/投影坐标须有原文件或数据元数据crs依据，不能只改端口名称冒充投影。原文件Features默认path="features"，运行inputs[port].features与columns同行同序，保留原feature.id/properties/geometry及内孔，不自动推断空间位置。字段映射可用pointer（JSON Pointer如/properties/name或/geometry/coordinates/0），与field二选一，显式处理嵌套属性，不把点分名称猜作路径。几何语法核验不保证多边形拓扑、地图测量、真实场地或空间算法科学有效。
observables={观测名:{label:中文含义,unit:单位,equation:精确数学式}}；observe实际返回同名有限数值字典。指标须从真实state计算，不得用时钟、常数或目标值代替机制。规模和状态值分开观测。
populations=[{id:英文组ID,label:用户原话的主体类别,type:实体类型,count:整数或只含参数的数量表达式,dynamic:布尔,attributes:{属性名:{kind:"numeric|nullable_numeric|categorical",unit:单位或null}}}]。属性元数据恰好kind/unit两项；属性名不能使用保留字段id/type/group/local_id，原ID通过frame.populations[].ids保留，需重复列时用person_id等独立名称。每组独立属性和数量；无个体时显式[]。有明确多角色数量时label沿用原文角色名。dynamic=true只用于真实进入/退出机制，须保留稳定ID与初态数量。不能为通过验收把固定人口改为dynamic。
equations=[{id:方程ID,expression:完整数学表达,function:source中实际实现该式的函数名,meaning:量纲和机制解释}]。solver={method:真实算法,description:步长/误差/事件时序,intervention_clock:"step|continuous"}。step只接受步边界干预；continuous会在干预时点分段调用advance，算法必须正确处理不同dt。算法需要正态增量时其方差随dt，不能把每个子步固定方差冒充同一SDE。
源码五个必需顶层函数（固定数目的位置参数，不使用入口装饰器/可变或仅关键字参数；可以声明默认值，但平台始终显式传入全部实参，不能以默认动作冒充真实响应）：
initialize(parameters,inputs,rng)->state；advance(state,parameters,inputs,rng,time,dt)->{"state":新状态,"events":事件列表}；observe(state,parameters,inputs,time)->{观测名:有限数值}；frame(state,parameters,inputs,time)->实际帧；validate(state,parameters,inputs,time)->None或[]，不变量失败抛错或返回非空问题列表。
可选decision_policy={instruction:主体决策规则,action_schema:每个action的JSON Schema}启用真实宿主LLM。此时增加纯读decision_requests(state,parameters,inputs,time)->[{id:批次ID,actor_ids:[真实主体ID],prompt:按当前状态构造的实际上下文JSON字符串}]，advance改为七个位置参数，末参数decisions={批次ID:{actions:[{actor_id:原ID,action:符合schema的实际结果}]}}。源码必须真正使用该结果推进状态，不调用外网；一次批次可包含多个主体以扩大规模。宿主在每个宏步起点调用、按当前状态与随机流摘要绑定返回，continuous子步使用该宏步的同一决策。无需在advance伪调用decision_requests，它由真实调度器调用；方案将其映射为外部决策机制并说明advance如何消费。原运行恢复复用已接受结果，公开检查点可以明确重放历史实际响应；重放不冒充新的API调用。所有新调用、动作、schema与历史来源在manifest.actor_decisions及llm_calls留档。schema只用本地$defs引用，不指定服务URL或密钥。
全部可变状态都放state，包括事件队列、方法内部状态、人口、关系、历史；只用传入rng产生随机数。恢复不重复initialize。禁止把变量藏在模块全局或用系统时间/未受管随机源。observe/frame/validate必须纯读，不改state、rng、parameters或inputs。state为JSON值树，可嵌有限NumPy数值数组；不支持对象数组、类实例、pickle、别名共享语义或未掩码NaN。
advance推进[time,time+dt]，内部可细分/求根/事件排序，但必须准确抵达终点，不重复前一步边界事件。事件={time:真实发生时刻,type:领域类型,...}，type="intervention"由平台保留。严禁硬编码结果、用示意随机移动替代规定机制。observations/验证值直接由实际状态推导。
为使数据流可审查，observe用具名指标字典返回，可以调用纯函数；实际值显式读取state["字段"]。方案中的机制验收至少一项读取advance真正推进的状态；len/shape/size只验证数量，不代表值的演化。所有状态更新仍可使用普通Python/数值库，无DSL表达式长度/作用域限制。
按获批方案实现独立参照时，从只读inputs重新构造参照或使用独立解析/数值方法；主state的事件日志、派生端点/时间/初值和结果缓存均可能包含待检错误，不可用于生成预期值。主state仅作为待比对输出。若原文声明数据量、类别或ID集合，initialize/validate须从实际inputs核对，不能硬编码观测数代替前提检查。
frame返回{populations:[{id:与声明相同,type:相同,columns:{属性名:完整数组或列表},units:{属性名:声明单位},ids:原始持久ID列表}],space:{bounds:[xmin,ymin,xmax,ymax],unit:坐标单位},relations:[{id:唯一边ID,source:"组ID:实际持久ID",target:"组ID:实际持久ID",...}],stocks:{库存:数值},facilities:[实际设施],presentation:可选真实显示映射}。动态人口或有外部原始身份时ids必需，包括固定人口。只有无外部原始身份的固定合成人口可省ids用0起编号。关系端点使用ids中的具体值而不是数组位置，例如ids=["001","009"]时source="people:001"，不能写people:0。columns完整匹配attributes，frame.units与声明单位逐项相同，不能在定义写null而帧写1；类别字段可用unit=1。不要自行返回entities或聚合指标；平台从全量人口采样显示并将实际observations作为aggregates。非空间人口不伪造x/y。属性缺失用nullable_numeric与显式掩码/None；不适用属性不补0。
relations只返回sim_t当时有效的关系，多种同时有效关系可用type分层并分别计数。不能同时返回上一步已用边和下一步当前边，再只上报一半数量；历史/未来关系保存在state中，需要导出时用独立fields且说明时序。可给边valid_from/valid_until有限时刻，平台核对半开有效区间[valid_from,valid_until)，无界端点省略字段。relation_count读取实际完整边列表，与target或同刻observable精确核对；不是只核对observe自报数量。
空间scenario={title,setting,agent_label,source_request:完整原文,facilities:[{id,kind,label,role:"modeled|context",model_refs:["source.advance或其实际调用函数"],frame_refs:["source.frame或实际调用函数"]}],requirements:[{quote:逐字原文,model_refs:[实际函数路径],visual_refs:[实际帧函数路径]}]}。设施kind=room/building/exit/destination/source/obstacle/road/signal/service/zone。实际帧facilities须逐一对应ID/type并给有限x,y、正width,depth，空间须有范围与单位。障碍物/信号须参与advance，不能仅绘图；人物坐标/动作须由真实状态给出。程序场景合同与DSL设施表达式格式不同。
只有基础隔离与协议通过不代表数学正确或现实校准；仍须独立语义复核、逐项事前数值验收及同源报告。当前常见验证是异类人口/动态图/随机状态/连续积分与干预；其他算法需本轮实际验证，不能把可写Python说成行业验证已通过。'''

PLAN = '''方案kind可选program。选择依据是用户机制和求解方法，不是套用旧模型。简单DSL已准确覆盖时可沿用DSL；有多个独立人口池或复杂算法时可选program。
方案verification是说明性字符串列表；可执行检查对象只放criteria，不混用。observables只列实际数值指标，sim_t是平台保留时钟，不能重复声明；时间范围通过运行合同和criteria时点核对，不另造常数指标凑验收。
采集与原始文件/解析哈希核验属于宿主collect_data及execution.data_bindings准备阶段；field/parameter聚合映射通过parameters[参数名]进入initialize/advance，port/contract/columns结构映射才通过inputs[端口]进入。无结构端口时inputs为空是合法合同，不能强迫把聚合参数改成微观输入。两者都不联网、不读宿主原文件。方案分别安排采集证据、绑定准备、实际消费和运行后独立验算，不能要求initialize重复采集。真实人员ID通过frame.populations[].ids保留，关系端点为group_id:原始ID；不可替换成数组索引。保留指定属性不自动排斥辅助诊断字段，若有排他约束须引用原文依据。
program方案的mechanisms为[{"mechanism":"具体机制","paths":["source.advance","source.实际由advance调用的辅助函数"]}]；初始化/观察/帧/验证用source.initialize/source.observe/source.frame/source.validate作为支撑引用。方程说明可引用equations.方程ID，人口用populations.组ID，参数和指标用parameters.参数名/observables.指标名，真实结构端口用input_ports.端口名和execution.structured_inputs。实际演化至少引用一个由advance可达的函数。不得引用尚不存在的函数或用说明文字当实现。
沿用共同的coverage、criteria、变量、数据、单位、假设、数值方法与验收要求；本阶段不写完整代码。编译阶段严格保持函数名、真实状态、方程、观测定义和数值目标。
把输入冻结、ID保持、初始化前提写作support_refs与coverage.role=input/setting；输出帧/归档对应delivery/outcome。它们不能因重要就被误列为advance动力学。mechanism行须由真实推进函数及至少一个状态值验收支撑；relation_count只证明关系结构一致，不能单独证明关系导致的状态变化。若用户同时要求动态关系影响行为，把结构检查和状态影响检查都安排，不用重新定义人数/边数的含义来凑机制验收。审核阶段须核对这些类别与判据是否一致，避免到编译时才发现获批方案无法验证。
存在真实execution.research且phase=baseline_model_only时，校准/验证选型/留出/平台数值诊断与科研报告由后续研究执行；这些条目在mechanisms映射中只引用execution.research，平台会分类为support_refs，并在coverage.role=research逐项绑定原要求与同MI。不能为它们在baseline声明source.loss_partition等评分函数，更不能把评分函数插入advance来凑可达路径；原文要求的实际模型学习/策略演化仍按真实动力学实现，不与平台研究评分混同。缺少真实冻结MI时不得使用execution.research支撑引用。'''

REVIEW = '''复核用户原文与隔离程序源码是否对应，只输出与平台审核合同相同的JSON。
必须逐项阅读initialize/advance/observe/frame/validate及其辅助函数，将实际代码与方程、方案和用户原文对照。核对分组数量、持久ID、拓扑、局部查询、初边界、单位、随机增量的dt尺度、积分误差、事件边界与干预分段、数据来源、完整状态与真实动作。
frame.relations须恰为当前sim_t有效边；核对初态、宏步边界、事件前后的端点规则与真实advance现金流/作用方向，不能把旧/未来边并列当当前图。relation_count检查实际帧与同刻观测，仍不能代替端点及动力学验证。多个真实关系类型允许并存，但全部计数与分类型计数须各自同口径。
functions中的每个片段从source AST直接提取，不是作者另写的说明；refs用source.函数名或提供的真实定义/执行/运行合同路径。机制须有真实advance依赖和可证伪验收。常数目标、只读时钟、数量、空事件、伪数据依赖或初始化装饰不能证明动力学。
结构输入检查：逐端口核对真实绑定合同、源单位/时钟/缺失、读取列、联合属性/ID保持和关系端点；检查数据真正进入initialize/advance而非读取后丢弃或硬编码替换。样本范围和许可不能凭数据可下载就推断适用。输入行数和hash仅证明交付，不替代机制敏感性、校准或现实验证。
采集/数据哈希核验由宿主collect_data及绑定准备完成。field/parameter绑定的有效值通过parameters进入模型；只有port结构绑定通过inputs进入。读取已绑定的parameters不等于未用真实数据，inputs为空也不证明缺数据；按runtime_contract.input_pipeline.prepared_parameters/prepared_ports和execution.effective_inputs核对当前实际通道。prepared_not_yet_executed是运行前正常状态；不要求沙箱联网、读取宿主原件或复制采集。缺少来源、口径或源码不消费绑定值仍须指出，消费作用须源码和独立扰动验证，不把传入成功当科学有效。
人口关系端点使用人口组命名空间：group_id:原始持久ID；与frame.populations[].ids逐一对应，不能用行索引替换原ID。原始ID另存属性不能弥补错误的实际关系端点。要求保留若干属性不是自动禁止额外诊断属性，只有原文/方案明确限定唯一字段时才按排他列表核对；所有实际帧属性仍须与定义的属性合同一致。
只要代码与明确需求、方程或事前判据矛盾就matched=false，并指出具体原话与函数证据。普通数值程序可使用提供的NumPy/SciPy/NetworkX，不套用旧DSL的512字符、无索引等限制。隔离无外部网络/文件，未提供的输入不可能被代码真实采集。平台负责归档、报告、完整随机检查点；领域机制仍必须由代码实际实现。'''

SPATIAL_3D = '''
真实三维/地形/跨楼层消费者已接入程序帧，不是用柱状图代替场景。frame.space沿用bounds=[xmin,ymin,xmax,ymax]，三维另给vertical_bounds=[zmin,zmax]和统一unit；空间人口columns须有同单位x/y/z（z为脚底或支撑面高度），实际帧可给floor_id类别列。
可选space.terrain={id,label,origin:[x0,y0],spacing:[dx,dy],heights:[[z00,z01,...],...]}；heights为至少2×2完整网格，按双线性支撑面核对人口；不能将GIS平面坐标伪称高度。
space.floors=[{id,label,elevation:实际标高,bounds:[xmin,ymin,xmax,ymax],holes:可选矩形开口列表}]；space.connectors=[{id,label,kind:"ramp|stairs|passage|lift",from:真实楼层或地形ID,to:真实楼层或地形ID,polyline:[[x,y,z],...],width:实际通行宽度}]。连接端点标高必须对应两支撑面，floor_id在连接期间用连接ID，楼层/地形上用对应支撑ID；不要把floor_id当上一次楼层而让实际z矛盾。floor_id也可省略，用实际x/y/z自由空间运动。
楼层、地形、连接几何由实际frame输出；其对速度、局部密度、路径、碰撞、策略等的影响由advance真实计算。平台不自动替你实现领域运动算法。声明几何不证明已消费，方案与独立数值验收须包含竖直/跨层行为及原机制。设施可给真实z，其形状/尺寸仍走实际设施合同。动作来自实际属性和presentation/visualization.action_poses，不能由前端编造伤亡或行走轨迹。
Three.js绘制实际高度网格、分层楼板/开口、三维通路，人物按真实高度和动作回放；Word另有真实三维轨迹、z时间变化、完整人口分层流转。空间测量和3D消费已可用不等于任何行业接触力学或经验校准已经成立。
'''
DESIGN += SPATIAL_3D
CONTRACT += SPATIAL_3D
PLAN += SPATIAL_3D
REVIEW += SPATIAL_3D

DECISION_BOUNDARIES = '''
frame.presentation可直接给{glyph,color_by,label,action_by,action_poses}，也可用presentation.visualization包含同一映射；消费者读取实际属性，不根据图形效果猜动作。与space.floors/connectors同ID的设施使用已声明三维几何，不重复生成水平道路或额外墙体。
外部决策与初态的准确顺序：initialize → validate/observe/frame保存step0真实初态 → decision_requests(t=0) → 宿主真实响应 → advance(time=0,dt)消费 → step1观测。后续宏步末帧先保存，再为下一宏步起点收集响应。因此step0尚无真实响应，不能要求初始“已接受LLM动作数=N”，也不能初始化假动作来凑此目标；应在step1核对首批真实消费。t=3.0末帧对应之前的动力学，新t=3.0动作从下一advance生效，事件与响应账本保留其实际边界时刻。意图、已接受动作和执行姿态要分别准确说明。
只在需要新决策时返回非空批次；其他宏步返回[]，此时advance收到{}并可保留state中此前已接受的动作。调度器会在空边界连续推进、遇真实请求返回，不需要每帧重新调用LLM。类别状态/帧列使用Python字符串列表；NumPy RPC数组仅支持有限数值类型，不使用object或Unicode数组。
历史响应的恢复/公开检查点重放要求请求的state、parameters、inputs和随机流摘要匹配。改变参数或轨迹的干预臂、敏感性样本默认根据各自当前上下文发起真实新调用；相同seed不固定外部LLM响应。平台不自动把某一基线动作带注入其他情境，不得虚构未声明参数或输入通道。若另行设计固定真实动作输入的条件实验，须通过实际声明并绑定的输入接口实现，报告其条件范围，不能称为新上下文的LLM决策。
真实调用与历史重放的来源由宿主manifest.actor_decisions及llm_calls审计；求解器收到的decisions只含合同所示actions，不要求读取宿主未提供的来源字段。NumPy的object/Unicode限制适用于跨RPC边界返回的状态和帧数组，不禁止函数内部临时数组运算；返回分类状态/帧时须转换为Python字符串列表。
'''
DESIGN += DECISION_BOUNDARIES
CONTRACT += DECISION_BOUNDARIES
PLAN += DECISION_BOUNDARIES
REVIEW += DECISION_BOUNDARIES

IMPLEMENTATION_RIGOR = '''
程序实现以本次提交definition.source的完整代码为唯一证据，按真实调用链核对方程，不以函数名或作者自述代替实现。
1. 状态生命周期：逐个区分一次初始化、每步更新、派生重算和累计统计。所有跨步量、方法内部状态、历史、事件游标和已接受动作保存在state；advance不得把它们每次重置为初值。当前数量、累计发生次数和历史峰值分别命名，observe/frame只读并保持相同物理时点及定义。
2. 输入到结果：绑定参数/结构输入必须用于对应初始化或动力学，不能另写同值常量或读取后丢弃。动作经decisions真实消费，只改变所声明的控制量；策略动作枚举与身体姿态、退出/死亡/倒地等物理状态分开。随机只使用传入rng，概率或噪声按实际dt缩放。
3. 完整边界：同一空间定义贯穿initialize、推进、validate和frame；二维/三维各轴、楼层/连接、孔洞、障碍和出口均按实际声明判断。合法终点不证明路径合法；不能通过大幅clip/投影把墙外、禁区或楼层外主体瞬移进来。出口须与碰撞墙开口一致。初始化先计算能覆盖实际n的行列/分组数，再用同一组尺寸生成所有主体；改人数后不能沿用旧行距或漏检查尾组。容量探针应落在明确的几何与初始化有效域内，不以探针改写正式人数/时钟。
4. 同一算法：同步快照、异步更新、RK阶段重算、子步积分和事件推进须与获批方案一致。需要改变算法或科学假设时正式修订，不能在实现里静默替换。真实机制必须从advance可达，不能加未调用stub、无效wrapper或零乘依赖凑rule_refs。
5. 真正的检查量：每个残差/违例/诊断字段均须追到实际计算及更新位置。初始化0且永不更新、返回目标常量、重复同一算式再相减、从待检结果构造参照，均不能证明正确。独立参照从原始输入/同一步快照用独立算法或解析推导计算；比较器可读待检结果，但不能拿它生成预期值。无需新造数十个自报指标；优先复用平台真实归档/调用账本与适用的独立检查。无法实现的检查如实说明，不能伪造通过。
6. 指标与显示：均值、瞬时峰值、累计量、时间最大值严格按equation实现；单位不同的量不混入同一残差。活动主体从实际物理状态判定，不猜动作文本。floor_id/设施/连接ID与实际space一致，同一三维结构不另画冲突的平面替身。人物动作、轨迹、热力及报告读取同一真实状态。
7. 修复闭环：按现有反馈的每个具体缺陷核对本次source、元数据、方程和引用；旧问题涉及的同类边界、其他分支和依赖指标一起修正，其他科学要求保持。提交前逐条代入反馈中的反例，确认改动确实进入最终定义。未改的旧source不得作为“新修复”重复提交，不能只改外部.py草稿而忘记重新序列化definition.source。
源码审核必须依据当前实际代码指出函数、表达式、可重现条件及违反的原话/方案/接口；不把上一版错误套在已修复代码上，不因篇数目标不足或运行后产物尚未生成否决可执行实现。缺少运行证据记为runtime待核；真实实现缺陷仍须拒绝。若引用计划外的规模、统计显著性、额外实验或阈值，先说明其是否为用户硬要求，不自行加门槛。最终只返回既有审核schema，不新增格式。
'''
CONTRACT += IMPLEMENTATION_RIGOR
REVIEW += IMPLEMENTATION_RIGOR

DECISION_COUNTING = '''
准确区分决策物理时点、边界、请求批次、API尝试和主体动作数。同一边界可按规模拆成多个合法batch；不得把同一t的多batch误判成额外决策时点，也不能把两次边界伪称只有两次实际API调用。事件名与criteria应明确计数单位，实际来源以宿主账本为准；源码无需伪造宿主专有字段。
'''
DESIGN += DECISION_COUNTING
PLAN += DECISION_COUNTING
CONTRACT += DECISION_COUNTING
REVIEW += DECISION_COUNTING
