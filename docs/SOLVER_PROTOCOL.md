# 受管程序模型与求解器协议

该通路用于在专门环境中执行经过审查的数值实现，突破单表DSL的表达范围。隔离执行、多人口归档、统一运行/API/报告、定时干预和检查点已实测。真实DSH自然语言基准`native-program-04`通过：4096居民、64企业、11完整帧、逐帧4096当前关系，连续数值与0.35秒事件、同run_id报告经独立验算。此前三个失败案例保留，不能称无失败或现实已校准。结构记录/时间边及GeoJSON端口已完成实际容器、输入扰动与报告定向验证。后续WDI研究已通过任意新模型校准和留出链。程序CA的独立局部算法与三种边界已做下述实际数值验证，复杂连续场和场景专门消费者继续完善。

公共模型用`kind=program`，完整字段合同见`schema(build_model)`及`dayan/agent/program_prompts.py`。`source`内五个函数实际执行，`equations`将数学表达对应到真实函数。`populations`分别声明各组数量、类型、属性、单位、是否有真实进入/退出机制；`frame`返回完整组列和持久ID，显示样本由平台生成。`observe`与帧汇总共用实际观测，Word读取同一归档。

局部CA可用实际NumPy算法、自定义邻接和同步/异步更新，按分组人口保存完整格点/角色的坐标和属性；方法名称不再触发program的笼统拒绝。`tests/test_program_ca.py`实际7项通过：三层概率CA在隔离容器内逐格对照独立标量循环，覆盖四/八邻域及周期、格面反射、域外零值三种边界，完整帧/全量占比相同；全局均值负对照产生不同结果，一个档的随机检查点续算与连续结果完全一致并实际归档。此为维护者规定的数学执行夹具，不是原生Agent政策研究或所有CA算法的效度保证。

`solver.intervention_clock=step`只接受步边界干预；`continuous`在干预时点分段调用advance。可干预参数必须声明`mutable=true`，相对操作按时序解析，实际生效时刻/值进入事件与检查点。用户算法须正确处理变化的子步长度，例如SDE增量方差随dt，不能因平台分段而改变方程。

自动恢复沿用原运行和原终点。公开`resume_from_checkpoint`验证完整摘要、源码、定义、镜像和时钟后另建运行；保留原步长、状态、随机流及未来干预，不重复初始化或已发生事件。明确追加至原终点之外会记录来源与新终点；短分支不丢失原后续干预。原归档不修改。

## 结构化真实输入

`data_bindings`保留原有标量`field/parameter`格式；程序另支持`{dataset_id,port,contract,columns,path?,filters?,order_by?}`。`contract`必须与`definition.input_ports[port]`规范化后完全一致。`records`保留联合行，`edges`增加有向性和端点外键，每个端点引用另一端口的唯一主键。字段明确`type/unit/nullable`；缺失不补零、不独立洗牌、不静默去重，ID文本不丢前导零。列转换限于明确类型、单位倍率、注明依据的偏移、类别映射和缺失标记，不执行宿主表达式。

时间区间用`clock.field/origin`与`interval`或`end_field`，采用左闭右开边界；原始相对时间不会自动变成某个日期或时区。算法须按字段单位和自身时钟明确处理。`inputs[port]`提供`count/columns/contract/source_row_indices`，所有程序入口只读；初始人口数可写`count={"input_port":"people"}`，由实际行数决定。

`clock`给`interval`时，新工具合同须显式声明`anchor="start"/"end"`，分别表示`[field,field+interval)`或`[field-interval,field)`。显式开始/结束两列用`end_field`，不可再设`anchor=end`。历史无anchor合同仍可读取，保持身份并标明端点未以字段声明，不自动重解释时间。端口不改写原时间列，制备回执`time_summary`给明确区间范围与单位，报告同口径。文字与布尔字段单位使用`"1"`，类别含义写在字段/说明中。

`timeseries`保留观测时点，clock必须声明`field/origin/series_by/interpolation/outside/missing/max_gap`。身份字段区分系列，每个系列的时刻必须严格递增且不重复，原始行号随显式排序保留。逐取值字段选择`linear/previous/exact`，范围外`error/hold`、缺失`error/preserve`、最大间隔正数或明确null。准备器不生成插值样本；审核后程序按合同取值/跨观测点积分，再用实际状态验证。linear是使用两端点的回溯假设，不证明当时可知；记录条数也不是主体数。实际容器的分段积分、输入扰动、覆盖范围错误和检查点恢复已定向验证，不能据此宣称现实预测有效。

原文件及解析结果SHA、源/选取行数、转换、缺失和输入SHA进入审查及manifest，不把整份微观记录发送给建模LLM。完整输入存于`checkpoint.json:inputs`并绑定求解身份，公开续算与自动恢复使用相同数据。报告重新从原文件制备并核对实际快照，运行包含原文件。数据送入求解器和其因果影响是两个结论：须用独立输入扰动和机制检查证明消费；更不能据此宣称现实校准。holdout/validation/background/calibration不能作为这些运行端口的输入。

`geojson`端口在同一合同中增加`geometry={crs,axes,units,coordinate_evidence,allow_null}`。源文件和元数据CRS须与模型声明相同；无额外源声明时按[RFC 7946](https://www.rfc-editor.org/info/rfc7946/)使用WGS84经度/纬度及degree，不能改个标签就当米。所有额外坐标维度也须明确单位/含义。输入`features`保留完整几何、内孔、Feature ID、原属性及其他字段，与映射的`columns`同序；嵌套字段用明确JSON Pointer（`pointer`与`field`二选一）。缺失几何需显式允许；不自动投影、修环、翻转环序或删除孔洞。格式检查不等于拓扑有效、测量准确或有真实场景渲染。

独立公开数据验算`r03-real-geometry/verified.json`实际采集USGS的42个历史事件，完整原始GeoJSON进入容器，按原事件时间推进24步，25状态帧的三维坐标累计与原始文件独立计算最大差4.55×10⁻¹³；Word、快照和运行包同源。这是数据与数值机制验收，由验证脚本构造程序，不是DSH原生建模，也不是地震预测或政策效度验证。字段依据[USGS GeoJSON](https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php)及[目录API](https://earthquake.usgs.gov/fdsnws/event/1/)；许可遵循[USGS数据说明](https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits)，不能泛化为所有第三方资料无版权。

## 执行环境与隔离

运行 `python scripts/build_solver_image.py` 构建专用镜像。构建上下文只含 `dayan/solvers` 白名单文件，不传整个工作区。基础Python镜像固定摘要；NumPy、SciPy、NetworkX固定版本及PyPI实际wheel哈希。执行前核对镜像内协议及受信任执行文件摘要，实际执行使用不可变image ID。

每次只向stdin传入代码、参数、已核验数据与JSON检查点。无宿主目录/套接字挂载，无外网，只读根文件系统，临时目录为限额tmpfs，并限制内存、CPU、PID、时间与输出。根权限的受信任PID 1只处理协议和监护，保留SETUID/SETGID/KILL用于降权和强制停止；生成的模型在UID/GID 65532、无capabilities、no-new-privileges及默认seccomp下执行，不能停止监护进程。此设计使宿主进程被终止后仍有容器内截止时间。

部署合同依据Docker官方[运行参数](https://docs.docker.com/engine/containers/run/)及[seccomp说明](https://docs.docker.com/engine/security/seccomp/)。隔离降低代码执行风险，不证明模型方程或经验解释正确。

## 模型接口

源代码必须给出五个顶层Python函数：

```python
initialize(parameters, inputs, rng) -> state
advance(state, parameters, inputs, rng, time, dt) -> {"state": state, "events": events}
observe(state, parameters, inputs, time) -> {"metric_name": finite_number}
frame(state, parameters, inputs, time) -> actual_frame
validate(state, parameters, inputs, time) -> None  # 或空列表；发现缺陷须抛错或给出非空问题列表
```

Program definitions may declare a positive integer `state_every`, for example
`5` to archive complete frames at steps 0, 5, 10, and the final step. Computation,
observations, events, population counts and full checkpoints remain unchanged.
`frame` always returns its actual complete state; invented `skip` fields and
`None` are not the scheduling API. An explicit every-step requirement overrides
this setting. The manifest records `frame_retention` and the actual interval;
an explicit schedule beyond the configured frame or byte budget is reported,
not silently thinned. Definitions without this field retain their previous policy.

所有可变求解状态必须放入state，包括不同主体组、动态关系、事件队列、连续状态和方法内部状态。随机性只使用传入rng，并在检查点中保存完整bit-generator状态。不得把未归档的模块全局变量当作恢复状态。观察、验证和帧函数不得修改state；parameters和inputs也不能被模型修改。

`advance`对应区间`[time, time+dt]`。区间内可用实际算法处理更细子步、事件与连续状态反馈；产生的事件必须给出该区间内的真实time和非空type。平台并不会因有一个事件名字就自动提供其机制，算法和事件顺序仍须在方案及独立检验中说明。

`frame.relations`是`sim_t`当时有效的完整关系快照。多种同时有效的关系可以用`type`分层；上一步用过的边、尚未生效的未来边存于state或另行说明的fields，不能混入当前图。可选`valid_from/valid_until`采用半开区间，给出的端点须有限且包含本帧时刻。默认省略端点表示本帧有效，并不宣称跨时刻永久有效。方案中的`relation_count`直接对完整帧数边，与整数target及/或同刻observable对账，容差固定为0；可按relation_type和实际step选择范围。报告读取同一验收回执。此检查仅覆盖数量与时序合同，端点规则及其动力学作用仍需独立检验。

state必须是JSON值树，可嵌套有限数值NumPy数组；保留dtype、维数、精确字节、随机流和原终点。每步边界规范化为值树，不能依靠数组共享内存来保存隐含状态。按NumPy[掩码数组语义](https://numpy.org/doc/stable/reference/maskedarray.generic.html)，显式MaskedArray会完整保存数据、缺失掩码、填充值和hardmask，不能把缺失视作零值参与统计。没有pickle或宿主模型代码导入。超过预算会失败，不能减少主体或偷换归档范围。未掩码的NaN、对象dtype、错误尺寸、错种子/输入/源码的检查点会被拒绝。

`run_segment`返回实际执行区间、每步观测与帧、事件、完整末状态、随机检查点和容器执行回执。回执`executed`只表示这段计算执行成功，仍需要原需求语义复核、数值验收及经验验证。宿主执行进程死亡后，恢复账本将其标记为interrupted，从此前完整检查点重算未接受的段，不把半段输出当作成功运行。

## 已有验证及范围

`DAYAN_TEST_SOLVER=1 python -m pytest -q tests/test_solver_sandbox.py tests/test_loaded_revision.py`实际执行专门容器，不用仿造的引擎响应。2026-11-24定向8项通过，包含：

- 不同数组规模、动态关系、SciPy连续积分与随机更新的分段/连续结果一致，连续变量另有解析解对照。
- 模型实际UID、capabilities、seccomp、只读目录、断网、宿主环境隔离和无法停止监护进程。
- 超时、输出洪泛、真实宿主进程被终止后容器自行退出及账本修正。
- 镜像构建依赖变动进入平台执行版本识别。

上述是运行器与数值协议验证，由维护测试提供模型代码；不是原生DSH自然语言自主建模验收，也不是多领域科学有效性或真实数据验证。后续必须通过正常建模入口接入，再分别验收。
