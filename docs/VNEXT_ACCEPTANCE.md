# DAYAN VNext 交付验收

基线为审计分支 `fix/system-audit-20261118` 的 `7160274600e6e8590521f2c63ffcfdbde1bd7bfe`。VNext 以独立分支 `feat/dayan-vnext` 提交。运行执行指纹为 `4ac7cdb7f3904bed2fe24f13094da1dfa04fe127b6120454aad5152fa2218767`。归档保留各自生成时的源指纹及源码内容。

## 按问题核验实现

| 优先级 | 修改前的问题 | 具体修复与源码 |
| --- | --- | --- |
| P0 | 运行入口、机制忠实度和现实研究的验证状态容易混为一谈。12 个模型登记位没有工厂。 | 把登记、工厂、依赖、探针和机制审查分别存证。补齐 12 个工厂。目录、Agent、编译器和专业参数页使用同一执行信息。 [能力目录](../dayan/fidelity.py) · [运行依赖](../dayan/runtime.py) · [20 个核心模型审查](VNEXT_MODEL_REVIEW.md) |
| P0 | 个别模型的实际运行偏离方程或计数约定。 | 保留实际投入产出技术系数，校验谱半径。让 AK 解析序列随真实时钟演化，修复年龄组接触的重复归一化。M/D/1 按实际连续到达时间计等待。保持原 M/D/1 回归容差，非齐次 Poisson 保留原 25% 容差并用 32 种子估计期望、检查同一随机过程在两种观测网格的一致性。 [经济模型](../dayan/models/eco_models.py) · [年龄仓室](../dayan/models/net_final16.py) · [系统模型](../dayan/models/sys_models.py) · [回归](../tests/test_dayan_sys.py) |
| P0 | 研究校准需要明确隔离模型选择和最终测试，成果报告的事实 JSON 有下载路径拒绝。 | 加入可选独立验证段。先用训练排序，按事前约定的短名单用验证段选择，冻结参数后只测一次独立段。保存基线、误差和训练残差带，报告同版本可读。 [校准](../dayan/research/calibration.py) · [研究](../dayan/research/studies.py) · [报告下载](../dayan/server.py) |
| P0 | 耦合场景缺少同地路网、人口与车上主体联动证据。 | TIGERweb 同范围采集、原始哈希、局部单位换算、可达道路、加权主体与车辆容量校验、乘车关系和位置同步。 [采集](../dayan/collection/spatial.py) · [实际耦合](../dayan/models/evacuation_coupled.py) · [实测案例](VNEXT_RESEARCH_CASES.md) |
| P1 | 多个页面缺少统一状态和入口。参数会被异步响应覆盖，DSH 刷新可能恢复上一个工具结果。 | 七个研究空间、键盘命令、分栏、焦点和通知共享外壳。参数草稿随精确模型和档案保存。只让最新请求提交界面结果，时间轴先取得交互值再刷新。DSH 按会话保存游标和选定档案。 [统一外壳](../site/console/workbench.js) · [归档状态](../site/console/results.js) · [参数](../site/console/command.js) · [原生会话](../site/console/research.js) |
| P1 | 场景与图表显现不同来源，夜景变化和密集图层影响结果读取。 | 动态引擎采样、实体归档回放、汇总示意分别呈现，标示单位和实际数据。机位和场景板按房间、道路、群组网络和观测种类适配。历史道路栅格复用，播放时仅移动游标。 [引擎预览](../dayan/task_manager.py) · [场景](../site/console/viz3d.js) · [图表联动](../site/console/workbench-analytics.js) |

## 工作区与图表

系统总览以引擎采样、实际归档、任务与留出状态开场。仿真指挥把模型、指标、视口、事件、时间轴、主体和参数组合在同一页。模型宇宙按领域、范式、证据和依赖筛选，可查相邻机制与对比合同。研究实验室支持原问题编译、配对种子、干预、参数扫描和真实数据校准。数据中心将采集、资产、字段、来源与映射相连。实验分析对照同口径运行，研究成果按出处、数据哈希、代码和归档状态展示下载。

视觉变量集中于 [workbench.css](../site/console/workbench.css)。深蓝和石墨用于工作面，青色用于活动状态和选中项，紫色用于对照，琥珀用于干预，红色用于正式失败。中文界面沿用系统中文字体，数字使用等宽栈。布局过渡、活动态、实时任务进度、镜头入场、帧间插值与事件强调使用同一主题。暂停停止常规帧推进，页面不可见时降低轮询，系统减弱动效偏好适用于界面和初始回放平滑设置。

| 数据合同 | 图表与操作 |
| --- | --- |
| 带实际时间戳的运行观测、单位、缺失值与干预日志 | 趋势、同种子范围带、相邻变化、事件标记、共同观测散点和相关矩阵。可选择指标和窗口，联动回放到真实观测时点，导出 CSV 和 SVG。 |
| 有有限数值的窗口观测、同模型／单位／时钟、配对种子 | 直方图、核密度、箱线、配对差、参数扫描响应、平行变量轮廓。常量无法估计核带宽时显示原因。 |
| 带实际位置和持久 ID 的主体帧、道路和有向关系 | 道路时空栅格、主体密度和关系图层、选择与相邻有效帧轨迹、时间轴、摄像机定位。汇总或旧式单纯观测只形成指标示意。 |
| 两个相邻帧可按 ID 匹配的主体状态 | 状态堆叠和桑基迁移、选择主体类型/时点和 CSV。数据缺口保留；状态带使用已保存帧。 |
| 同源研究对象、真实观测、预测和分段校准记录 | 统计观测与模型趋势、训练残差经验带、基线及阈值、分段残差、训练网格与验证候选。图和报告引用相同研究 ID。 |

## 六个实际流程

| 流程 | 浏览器证据 |
| --- | --- |
| 自然语言仿真 | 原文要求 37 人、40 米 × 30 米大厅和明确出口，执行 200 步、步长 0.2、种子 7。两次实际语言模型调用，37 个实际主体、201 帧、末时刻 40。核对场景对应、专业参数、运动、暂停、定位、状态迁移与研究包。 [实际需求、版本与调用凭证](verification/vnext/web_ai_vnext.json) |
| 复杂多主体 | 通过数据中心采集 2020 年真实官方同范围道路和人口快照，进入 CPL001 专业参数并运行。路网、关系、密度、主体定位、轨迹和回放均读取正式档案。 [在线采集和运行](verification/vnext/cpl_online_receipt.json) |
| 真实数据研究 | 加拿大 25 年 WDI 年度原始数据按 18/3/4 年切分。事前阈值 1 个百分点，独立测试 RMSE 1.07854937，结论 `failed_holdout`。校准、预测、图表、报告和复现包使用同一研究。 [案例](VNEXT_RESEARCH_CASES.md) · [报告事实](verification/vnext/canada_facts.json) |
| 实验对比 | 输入交通原问题并保存规约，基线与较高密度各使用 3 个配对种子。对照归档 `EX-7c3ee2b7`，114 条观测，用共同时间筛选与导出。 [联动录屏](verification/vnext/workbench-recording.mp4) |
| 模型探索 | 从模型宇宙搜索 NET106，核对真实参数、机制关系和证据，经专业模式启动引擎并核对呈现位置。CPL001 的同一入口连接采集、路网和人口。 [模型页截图](verification/vnext/models.png) |
| DSH 协同 | 隔离 DSH Web 宿主使用项目绑定会话，原生 AI 调用真实运行工具。调密度得到新运行，拖动分隔线约 110 px，刷新仍在同一会话并恢复后一次运行。CSV 和研究包下载哈希可核验。 [12 项凭证](verification/vnext/native_vnext.json) |

## 实机截图与录屏

| 工作台 | 文件 |
| --- | --- |
| 系统总览 | [1920×1080](verification/vnext/mission-1920.png) |
| 仿真指挥 | [1920×1080](verification/vnext/command-1920.png) · [2560×1440，专业模式](verification/vnext/command-2560.png) · [自然语言大厅](verification/vnext/command-ai-1920.png) |
| 模型宇宙 | [模型与机制](verification/vnext/models.png) |
| 数据中心 | [实际资产与质量](verification/vnext/data.png) |
| 研究实验室 | [时序诊断和阈值](verification/vnext/lab.png) |
| 实验分析 | [多种子曲线、分布与联动](verification/vnext/analytics.png) |
| 研究成果 | [研究档案和报告](verification/vnext/outputs.png) |

录屏从真实浏览器工作区捕获，含页面切换、实体选择、真实轨迹、主动回放、拖动面板和联动比较。截图使用隔离验收项目，标为安全测试的导入条目只用于验证文本显示。 [MP4](verification/vnext/workbench-recording.mp4)

第一轮修复空场景构图、导航切换和分隔线释放。第二轮修正对照分析分栏、图表范围及真实任务采样。第三轮修正地理灯光和图例、校准与数据结果的位置、档案主指标、回放交互、加载结果竞态以及密集交通的重复栅格绘制。三档窗口分别检查七页测得 21 个组合。断开状态采样后，确认界面显示连接异常，恢复后重新读取。 [布局记录](verification/vnext/layout.json)

## 运行性能

同一台 Windows 设备，Firefox headless、1920×1080。表内帧率为每次约两秒的应用 `requestAnimationFrame` 采样。绘制时间为八次状态重绘与 WebGL `finish`，浏览器 RSS 是本次隔离 Firefox 进程树各进程 RSS 之和。

| 归档场景 | 归档主体 / 实际绘制上限 | 帧率 | 同步绘制范围 | 首次读取 | 引擎 / 浏览器 RSS |
| --- | --- | ---: | ---: | ---: | ---: |
| 自然语言大厅 | 37 / 37 | 75.7 | 3–6 ms | 0.72 s | 164 / 787 MiB |
| TIGERweb CPL001 | 122 / 122 | 76.5 | 2–5 ms | 2.16 s | 165 / 953 MiB |
| NET106 大场景 | 4,000 / 3,000 | 70.2 | 4–9 ms | 7.03 s | 137 / 686 MiB |

大场景优化前同一归档测得约 6.0 帧每秒。只栅格化一次历史图，减少持续计算的实例变换和颜色传输后，用相同浏览器和画面尺寸复测。保留 85 帧和完整观测，连续在大、小归档间切换六次，每套几何体、贴图及画布数量各自稳定。 [实测输出](verification/vnext/performance.json)

## 测试与证据边界

| 命令 | 实测 |
| --- | --- |
| `python tests/check_sources.py` | 228 个 Python 文件与 17 个 JavaScript 文件解析检查。 |
| `python tests/run_all.py --output .claude/ci` | 本机 85 组、517 项通过、3 项按离线配置跳过、0 套失败。原 83 组继续执行。覆盖鉴权、队列、归档、模型、研究、前端静态资源及 Node 插件。 |
| `python tests/run_all.py --only test_online_sources --online` | 世界银行和 TIGERweb 两项真实公开数据验收通过。保留初次网络超时与抽样权重错误的记录，最终用合法的场景复测。 |
| `python tests/run_all.py --only test_live_llm --llm` | 已配置真实模型的 5 个入口全部发出实际调用并应用动作。保持提供方窗口，归档请求／响应哈希。 [调用记录](verification/vnext/live_provider_receipts.json) |
| `python tests/browser_acceptance.py --base-url http://127.0.0.1:8918 --browser chromium --output .claude/browser-ci` | GitHub 的 `ubuntu-latest` 已转向 26.04。首次浏览器作业在安装阶段遇到 Playwright 1.58 缺少该版依赖映射，改用 24.04。相同脚本在本机 Firefox 实测 32 项通过。 [事件与断言](verification/vnext/browser.json) · [Playwright 依赖表](https://github.com/microsoft/playwright/blob/v1.58.0/packages/playwright-core/src/server/registry/nativeDeps.ts) |

内置目录 561 项、509 个运行工厂和 52 项软件引用。501 个直接离线探针通过，5 个入口需要语言模型，3 个需要项目输入。20 个不同工厂完成当前源码级机制审查，另有一个兼容注册标识。其余模型逐项记录实际证据与条件。模型适用性仍须由具体研究的数据与验证确定。加拿大和原德国的留出失败属于研究结果。CPL001 的地理和人口输入已经实测，现实疏散行为尚未做地方独立校准。 [逐项台账](verification/vnext/model_ledger.csv) · [统计凭证](verification/vnext/model_counts.json)

复现命令、DSH 安装与来源许可见 [部署说明](DEPLOYMENT.md)。项目中原有研究文件的校验结果与验收材料哈希见 [归档索引](verification/vnext/artifacts.json)。最新提交 SHA 与 Windows、Linux、Chromium 检查由 PR 提交页记录。
