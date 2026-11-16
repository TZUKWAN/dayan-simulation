# 大衍 DAYAN 社会仿真平台 · 产品与技术白皮书

> 版本 v1.0 · 2026-11-10
> 代码库位置：`D:\社会模拟仿真\msim\`
> 运行方式：`python -m dayan.server` → http://127.0.0.1:8899/

---

## 目录

1. [产品概述](#1-产品概述)
2. [系统总体架构](#2-系统总体架构)
3. [功能介绍](#3-功能介绍)
4. [模型体系（556 目录）](#4-模型体系556-目录)
5. [AI Agent 层详解](#5-ai-agent-层详解)
6. [技术架构详解](#6-技术架构详解)
7. [API 参考](#7-api-参考)
8. [质量与效度体系](#8-质量与效度体系)
9. [快速开始](#9-快速开始)
10. [已知边界与路线图](#10-已知边界与路线图)

---

## 1. 产品概述

### 1.1 定位与愿景

**大衍 DAYAN** 是一站式社会科学仿真基础设施平台。它把政治经济学、社会学、政治学、文化研究、行为科学、网络科学、系统动力学、仿真方法论等领域的方法论模型汇聚在统一引擎之上——用户用一句自然语言描述需求，内置 AI Agent 自动完成：

```
理解需求 → 语义匹配/LLM 规划 → 选模型 → 定参数 → 运行仿真 → 3D 可视化 → 结果回显
```

核心差异化能力：

- **556 条方法论模型目录**，覆盖社会科学主要量化范式（ABM、博弈、网络传播、交通流、行人动力学、宏观经济、人口、排队论、随机过程、参数估计、敏感性分析等）
- **456 个模型可一键运行**，每个都有统一运行接口和数值验证
- **自然语言驱动（中文优先）**：42 个领域语义模式 + 云端 LLM 规划器双通道理解
- **数据驱动的实时 3D 可视化**：仿真跑出的真实观测数据现场构建 Three.js 场景（相空间轨道/多序列山脊/时序曲线），不是贴图动画
- **三主权边界**：LLM 只做规划，引擎确定性执行，结果可复现

### 1.2 核心数字

| 指标 | 数值 |
|---|---|
| 模型目录总量 | 556 条 |
| ├─ 基准通过（有解析解/守恒验证） | 492 |
| ├─ 原型可跑（应用场景配方） | 12 |
| └─ 参考登记（软件生态条目） | 52 |
| 可运行模型 | 456 个 |
| 行为/博弈/认知/RL（BEH） | 138 |
| 网络/传播/交通/行人（NET） | 120 |
| 经济/人口/健康（ECO） | 115 |
| 系统动力学/随机过程（SYS） | 45 |
| 方法论工具（MET） | 64 |
| 应用场景（APP） | 22 |
| 软件参考（TOO） | 52 |
| 平台测试 | **191/191 PASS（31 套件）** |
| 巡检轮次 | 55 轮零失败 |
| 全量逐模型验证 | 456/456（14 秒） |
| Agent 端到端语义测试 | 39/39 |
| AI 工具 | 7 项（执行全确定性） |

### 1.3 设计哲学：三主权边界

平台严格划分三类权力，这是整个系统的宪法：

| 主权 | 归属 | 含义 |
|---|---|---|
| **状态** | 确定性引擎 | 所有状态演化、数值积分、随机数由代码执行；同种子逐位复现；LLM 永不直接生成仿真数据 |
| **意义** | LLM / 语义层 | 大模型只负责理解需求、挑模型、定参数、生成解释文本；规划失败自动回退规则路由 |
| **理论** | 研究者 | 理论假设、效度判据、遮蔽审计、消融设计由研究者定义，平台提供工具支撑 |

这保证了：AI 再聪明也不会"编造"仿真结果；引擎再复杂也不会"理解错"用户意图；而平台本身不预设任何单一理论立场。

---

## 2. 系统总体架构

```
┌───────────────────────────────────────────────────────────┐
│                     用户（浏览器）                          │
│         大衍指挥中心  site/console/                        │
│   4 页面导航 · AI 助手抽屉 · Three.js 3D · 重点事件流       │
│   index.html · app.js · pages.js · viz3d.js · style.css   │
└────────────────────┬──────────────────────────────────────┘
                     │ HTTP fetch（:8899）
┌────────────────────▼──────────────────────────────────────┐
│            服务层  dayan/server.py（FastAPI）               │
│  /api/catalog · /api/run · /api/agent · /api/ai/chat ...  │
│  静态资源托管 · 启动时 LLM planner 健康探测+注入             │
├───────────────────────────────────────────────────────────┤
│                Agent 层  dayan/agent/                      │
│  agent.py(执行编排) · intent.py(规划入口+LLM槽)             │
│  semantic.py(42中文模式→334模型引用) · tools.py(7工具)      │
│  composer.py(扫参/集成/对比/组合) · metadata.py(能力卡)     │
│  llm_planner.py(阿里云 MaaS · deepseek-v4.1-flash)         │
├───────────────────────────────────────────────────────────┤
│            统一运行工厂  dayan/model_index.py               │
│  run_model(model_id, ticks, parameters) —— 456 模型唯一入口 │
│  协议分型：fixed_step / ode / sde / jump / des / demo      │
│  _apply_parameters 参数注入 · dt_scale 子步长机制           │
├───────────────────────────────────────────────────────────┤
│              模型实现层  dayan/models/（28+ 文件）           │
│  BEH 138 · NET 120 · ECO 115 · SYS 45 · MET 64 · APP 22   │
│  epidemic/opinion/culture/game_lib/networks/traffic/       │
│  pedestrian/eco_*/sys_*/met_*/beh_*/net_*/landuse_ca/...   │
├───────────────────────────────────────────────────────────┤
│                内核  dayan/core.py                          │
│  DayanModel 合同 · 四时钟 · RngStreams 派生流               │
│  EventQueue 优先级队列 · BalancedLedger 货币守恒            │
│  StateDelta / DomainEvent · 零时间循环防护                  │
└───────────────────────────────────────────────────────────┘
                     │
        外部 LLM：阿里云 MaaS（OpenAI 兼容接口）
        deepseek-v4.1-flash-1017 · 可热切换本地 LM Studio
```

---

## 3. 功能介绍

### 3.1 态势总览页（指挥舱主页）

打开平台看到的第一个页面，全局态势驾驶舱：

**顶部 KPI 行（6 卡）**
- 仿真主体数 / 累计到达安置 / 平均出行时间 / 公共服务利用率 / 群体风险指数 / 信息触达率
- 每卡带 spark 迷你趋势线
- 顶部状态标签「大衍 DAYAN · 后端已接 / 仿真引擎在线」来自真实后端探测（目录条数、可运行数实时显示在事件流）

**左栏**
- *群体态势*：全部/通勤/高龄/学生四类筛选，活动状态占比环图（正常活动/调整出行/前往安置/等待服务），平均响应时间与行为调整比例
- *社会传播网络*：canvas 实时动态网络图（68 节点 + 边传播粒子动画），活跃交互数、传播覆盖率随仿真时钟演化

**中央 · 仿真现场（3D）**
- Three.js 渲染主画布（约 876×529，设备像素比自适应防模糊）
- **数据驱动模式**：AI 助手或手动运行任何模型后，自动用该模型的真实观测数据现场构建 3D 场景（详见 3.6）
- 图层切换：人群流动 / 风险热力（径向渐变热区）/ 社会网络（枢纽连线）
- 场景标签：当前情景、降雨强度、滨江枢纽拥堵指数、中央安置点服务容量、东岸社区信息触达
- 底部控制条：暂停/重置、1×/4×/16× 倍速、时间轴拖拽回放（T+00:00 ~ T+12:00）、快照保存
- 跟踪主体卡：A-08721 主体行动链入口

**右栏**
- *干预工作台（POLICY LAB）*：接驳运力投放 / 临时服务容量 / 应急信息触达三滑杆；均衡配置/交通优先/服务优先三预设；「创建干预分支」→ 同一初态生成对照情景 B（配对随机种子），中央与情景对照联动
- *重点事件流*：每次仿真动作实时滚动推送（AI 接收需求 → 每个工具执行 → 运行完成），带时间戳，与仿真时钟同步；后端连接状态也在此呈现

**下方**
- *情景对照*：基准 A vs 干预 B 双轨迹 SVG 趋势图（疏散人数/出行时间/服务负荷三指标切换），NOW 指示线，干预效应量化（+x.x%）
- *主体行动追踪*：观测 → 决策 → 环境校验 → 状态反馈 四步行动链
- *混合模型与运行*：ABM（主体活动）/ DES（服务排队）/ NET（信息传播）/ SD（资源供需）四模块状态卡

### 3.2 场景实验页

8 张内置场景卡，每张含模型 ID、简介、可调参数，点击「▶ 运行」即调后端真实运行并联动 3D：

| 场景 | 模型 | 内容 |
|---|---|---|
| 城市交通流 | NET106 | Nagel-Schreckenberg 元胞自动机，车流密度-通量关系 |
| SIS 疫情传播 | NET052 | 易感-感染-易感，地方病均衡 |
| Solow 增长 | ECO015 | 外生储蓄率 → 稳态人均资本 k* |
| Ramsey 最优增长 | ECO016 | 跨期消费-储蓄权衡（打靶法鞍点路径） |
| 资产市场异质信念 | ECO047 | 基本面 vs 趋势交易者（Brock-Hommes） |
| 零智能交易者 | ECO054 | Gode-Sunder 双向拍卖，配置效率 ≈0.99 |
| 贝叶斯知识追踪 | ECO091 | 学习者掌握概率序列更新 |
| Richardson 军备竞赛 | ECO110 | 两国军备耦合 ODE，稳定/发散分岔 |

### 3.3 模型资源页

- 从 `/api/catalog` 实时拉取 **556 条目录**（非静态写死）
- 每行：状态点（绿=可运行 456 / 灰=登记）、模型 ID、名称、状态、▶ 运行按钮
- 运行结果：弹窗提示观测条数，3D 场景自动切换为该模型的数据驱动场景，事件流同步推送

### 3.4 运行回放页

基于快照体系：在仿真现场保存快照（记录仿真时间、干预分支状态、三滑杆参数、完整事件队列、事件步指针），可从回放页恢复任意节点——恢复后暂停，便于逐帧检查。

### 3.5 AI 助手抽屉（核心交互入口）

**入口**：右下角 ◈ 悬浮球。

**交互流程**：
```
用户输入自然语言
   ↓ POST /api/agent {"text": "..."}
LLM 规划器（阿里云 MaaS deepseek-v4.1-flash）或规则路由（保底）
   ↓ 返回 JSON 计划（≤3 个动作）
逐动作确定性执行（7 工具）
   ↓ ✓/✗ 摘要逐条回显 + [llm · 意图] 标签
run 结果 → DAYAN3D.visualize() 数据驱动 3D + 事件流推送
```

**快捷按钮**：🚗 交通CA（运行 NET106）/ 🦠 SIS疫情（运行 NET052）/ 📈 Ramsey扫参（sweep ECO016）/ 💡 搜模型（search_models）。

**透明性设计**：
- 规划器来源标注：`[llm · 运行 Goodwin 工资-就业周期模型...]` 或 `[rule-semantic · ...]`
- 每个动作执行结果独立回显（能力卡内容、run 的最终观测值）
- 失败动作显式 ✗ + 错误原因
- LLM 不可用时自动降级规则路由，**对话永不失败**

**示例指令**（都已实测通过）：
- 「构建一个政治经济学仿真：资本主义工资份额与就业率的 Goodwin 增长周期，跑 400 步观察周期性」→ LLM 规划 → ECO019 → 相空间轨道
- 「扫参 NET106 density 0.1 0.3 0.5」→ sweep
- 「比较 ECO110 和 ECO111」→ compare
- 「找 gini 相关的模型」→ search_models

### 3.6 3D 可视化引擎（viz3d.js / Three.js）

引擎注册两条场景生成路径：

**① 族类模板场景**（autoDetect，按模型 ID 前缀映射）：

| 场景原型 | 视觉内容 | 触发条件 |
|---|---|---|
| city | 城市建筑群（发光线框+窗户光）+ 十字道路 + 车流粒子 | NET 交通类（NET095-112）、APP |
| particles | 500 粒子群体（呼吸浮动+边界反弹+加法混合发光） | BEH 群体、NET05x 疫情、MET |
| network | Fibonacci 球面分布 3D 网络图（hub 放大+脉冲环） | NET 社会网络类 |
| waves | 40×40 线框波场（三重正弦叠加） | ECO/SYS 系统动力学 |
| terrain | 顶点色地形（低蓝/中黄/高绿）+ 巡游主体 | BEH001 Schelling、ECO110-115 |

**② 数据驱动场景**（`DAYAN3D.visualize(modelId, observations, meta)`，运行后有观测数据时优先）：

- **2 条数值序列 → 相空间轨道**（最有表现力）：
  - 完整轨迹画成 3D 环线（x=变量1 归一化，z=变量2 归一化，y=时间推进）
  - 底面投影闭合环 = 相图（如 Goodwin 工资×就业的极限环一眼可见）
  - 金色发光球 + 呼吸光晕沿轨道循环重放（14 秒/圈）
  - 青色轨迹点云 + 紫色投影 + 坐标轴线
  - HUD 面板：模型 ID、场景类型、两变量名=实时值（彩色区分）、tick 进度
  - 相机自动缓慢环绕，可随时拖拽/缩放接管
- **>2 条序列 → 多序列山脊**：每个变量一条彩色 3D 折线（六色调色板），白色运动头沿第一条线跑，HUD 列出全部变量实时值
- **1 条序列 → 时序曲线**：单变量演化动画
- **无数值序列**：回退族类模板

数值序列提取规则：剔除 `_min/_max/_std/_mean` 统计后缀列、非有限值列、常量列（无信息），按名称稳定排序。运行中 HUD 每帧刷新——**这就是"仿真变化流程"的可视化本质：不是预设动画，而是把每个 tick 的真实状态值现场绘制出来**。

### 3.7 重点事件流

全局钩子 `window.DAYAN_EVENT(type, title, desc)`：
- AI 助手：接收需求 / 每个工具执行（含模型 ID）/ 运行完成（观测条数）/ 失败告警（warn 类型）
- 手动运行（场景卡、模型表 ▶）：运行中 → 完成/失败
- 后端连接状态：目录条数 · 可运行数
- 事件与仿真时钟同步显示（HH:MM）

---

## 4. 模型体系（556 目录）

### 4.1 家族构成与代表模型

**BEH — 行为/博弈/文化/认知/强化学习（138）**

| 子域 | 代表模型 | 说明 |
|---|---|---|
| 经典 ABM | BEH001/002 Schelling、BEH003/004 Sugarscape、BEH005 Epstein 文明、BEH009 March 探索利用、BEH012 NK 崎岖地形 | 空间隔离/资源/组织 |
| 集体行动 | BEH014 Granovetter 阈值、BEH005/006 | 参与率级联 |
| 文化演化 | BEH041-048 Axelrod 文化、Henrich-Boyd 从众/声望、Rogers 创新扩散、命名博弈 | 规范涌现 |
| 博弈论 | BEH049-063 囚徒/公共品/最后通牒/鹰鸽/猎鹿/信任 + 20+ 收益规格 | 纳什/演化均衡 |
| 策略与学习 | TFT/GTFT/Pavlov/Grim/零决定策略、复制动态/Moran/Fermi/EWA/遗憾匹配 | 演化学习规则 |
| 行为决策 | 前景理论/CPT、Level-k、QRE、DDM drift-diffusion | 心理微观 |
| 认知架构 | BEH094-101 BDI/ACT-R/Soar/CLARION/OCC 情绪/PECS/Consumat | 符号认知 |
| LLM 主体骨架 | BEH129-135 ReAct/Reflexion/Voyager/Concordia/GraphRAG/生成式环 | 脚本适配器（待 LLM 在环） |
| 深度强化学习 | BEH112-128 Q/SARSA/DQN/Double/Dueling/REINFORCE/A3C/TRPO/PPO/DDPG/TD3/SAC/MADDPG/COMA/VDN/QMIX/MAPPO | numpy MLP 手工反传，零框架依赖 |
| 政治社会 | BEH136-138 | 选民/极化/运动 |

**NET — 网络/传播/交通/行人（120）**

| 子域 | 代表模型 | 说明 |
|---|---|---|
| 网络生成 | ER/WS/BA/配置模型/双曲图/LFR/DC-SBM/MMSBM/潜在空间（NET018-038） | 度分布/聚类/社团基准全过 |
| 传播动力学 | SIS/SIR/SEIR/SEIRS/SEIRD/SEIAR/SIRV/Reed-Frost/Gillespie 跳跃（NET051-077 + epidemic.py 11 仓室） | 终局规模方程解析对拍 |
| 信息/谣言 | Watts 级联 NET079、DK 模型 NET080、MT 谣言 NET081、Hawkes NET083、活动驱动 | 级联规模/谣言三态 |
| 级联/相依网络 | Motter-Lai NET088、Buldyrev 相依 NET089、Eisenberg-Noe NET090、DebtRank NET092、资产抛售 | 金融传染 |
| 交通流 | LWR/CTM/ARZ/IDM/Gipps/Newell/OVM/FVD/Krauß/Wiedemann/NS 元胞机 NET095-106、BML、VDR、Wardrop UE/SO、MOBIL | 基本图/相变解析 |
| 行人疏散 | 社会力 NET113、接触摩擦、离心力、VO/RVO/ORCA、地板场、OSM（NET113-120） | Helbing 恐慌疏散经典 |
| 元胞自动机 | Wolfram 4 规则、生命游戏、Greenberg-Hastings、森林火灾、Fisher-KPP（NET001-008） | 规则族基准 |
| 土地利用 CA | White-Engelen/SLEUTH/CLUE-S/Dyna-CLUE/FLUS/PLUS/CA-Markov（NET009-015） | 城市扩张 |
| 统计网络 | ERGM/TERGM/STERGM/SAOM×2/REM（NET039-044） | 网络统计推断 |

**ECO — 经济/人口/健康（115）**

| 子域 | 代表模型 | 说明 |
|---|---|---|
| 增长理论 | Solow ECO015、Ramsey ECO016（打靶法）、AK ECO017、Romer ECO018、Goodwin 周期 ECO019 | 稳态/鞍点/闭轨道 |
| 经济周期 | Samuelson 乘数加速、Kaldor 极限环（参数网格校准）、Kalecki 时滞、RBC、真实周期 ECO020-022 | 振荡机制 |
| 宏观货币财政 | Taylor 规则、菲利普斯、IS-LM、DYNARE-lite、三部门存量流量 GL-SIM（守恒 ~1e-13） | 政策实验 |
| 金融市场 | Brock-Hommes 异质信念、Kirman 羊群、Lux-Marchesi 肥尾、Santa-Fe 人工市场、Gode-Sunder ZI、订单簿 ECO046-056 | 配置效率/波动聚集 |
| 投入产出 | Leontief 数量/价格/Ghosh 动态、SAM 乘数、Miyazawa、MRIO、环境 IO | 逆矩阵精确解 |
| 微观计量 | Mincer 工资、McCall 搜寻、Burdett-Mortensen、Roy 职业选择、Jovanovic 匹配、Ben-Porath 人力资本 | 结构估计 |
| 异质Agent宏观 | Bewley/Huggett/Aiyagari/Deaton 缓冲储蓄、HANK-lite、两家庭 NK | 岔点二分/值函数迭代 |
| 贸易 | Melitz-lite、Eurace-lite、K+S-lite、GTAP-lite/递归 CGE/PEP-1-1 | 企业异质性 |
| 人口 | Leslie 矩阵 ECO057、Lee-Carter SVD、Gompertz、Brass Logit、Coale-McNeil 婚姻、迁移辐射/Harris-Todaro、Gale-Shapley 稳定匹配 | 增长率=λ1 解析 |
| 综合评估 | DICE-lite、RICE、FUND、PAGE09（肥尾 MC）、World3、Forrester 城市 | 气候-经济 |
| 健康 | 健康Markov/QALY、BKT 教育追踪、个体健康微仿真 | 成本效果 |

**SYS — 系统动力学/随机过程（45）**

| 子域 | 代表模型 |
|---|---|
| 排队论 | M/M/1、M/M/c Erlang-C、Erlang-B、M/M/∞ Little、M/D/1 PK、GI/G/1 Kingman、Jackson 乘积形式、封闭网络 MVA、BCMP、优先队列 |
| 离散事件 | Petri 网三型（含有色/循环）、DEVS 三型（含并行/动态结构）、CTMC、生灭过程 |
| 随机过程 | 泊松齐次/非齐次（稀疏化）、GBM、OU、CIR、Heston、Wiener、复合泊松 |
| 因果推断 | SCM do 算子、反事实、HMM Viterbi、线性高斯 SSM、HSMM、DBN |

**MET — 方法论工具（64）**

| 子域 | 代表模型 |
|---|---|
| 数值积分 | Euler/RK4 阶验证、DP 自适应、隐式 Newton、BDF、刚性切换 |
| 随机模拟 | Euler-Maruyama、Milstein、SSA Gillespie、下一反应、τ-leaping |
| 蒙特卡洛 | 8 法（含 Sobol/Halton 序列、CRN 公共随机数、对偶变量） |
| 优化 | CMA-ES、差分演化、GP 贝叶斯优化、NSGA-II 多目标 |
| 估计推断 | MH/Gibbs/HMC/NUTS-lite、ABC/SMC-ABC/SMM、NPE/SNPE/NLE、间接推断 |
| 滤波同化 | KF/EKF/UKF/EnKF/PF/APF、4D-Var |
| 敏感性 | Morris、Sobol 分解、FAST、PAWN、Shapley、Bootstrap、PPC |
| 人口合成 | IPF、IPU、整数化、水塘抽样、组合合成 |
| 实验设计 | DOE 四型、KOH 校准 |

**APP — 应用场景（22）**：应急疏散、公共卫生干预、城市规划、教育、文化语言、参与式建模、严肃游戏、数字孪生、可微仿真、神经符号、反事实分析、结构洞等场景配方（12 原型可跑 + 10 终批）。

**TOO — 软件参考（52）**：NetLogo、Mason、RepastPy、Mesa、AnyLogic 等仿真平台的登记条目。按规范**仅作生态参考、不运行**。

### 4.2 六级状态体系

| 状态 | 数量 | 判据 |
|---|---|---|
| 基准通过 | 492 | 有解析基准（如 π₁=a/(a+b)、SIR 终局规模方程、Leslie λ₁、Erlang-C 公式）或守恒验证（货币/人口/曝光），数值逐项对拍通过 |
| 原型可跑 | 12 | APP 场景配方完整执行出结果 |
| 参考登记 | 52 | TOO 软件条目，按规范终点 |

**零"仅登记"**——目录里每一条要么可运行、要么有明确登记理由。

### 4.3 统一建模合同

每个可运行模型实现 `DayanModel` 基类合同：

```python
class MyModel(DayanModel):
    model_id  = "XXX000"
    clock_type = "fixed_step"        # 四时钟之一
    dt_scale   = 1.0                 # 可选：刚性/振荡模型子步长

    def initialize(self, context, parameters, population, topology, rng): ...
    def step(self, t, dt): ...           # 或 ode_right/DES 事件等按协议
    def observe(self) -> dict: ...       # 每 tick 的观测（喂 3D/工具）
    def validate_state(self) -> list: ...# 不变量校验
```

- **`_apply_parameters`**：`run_model` 在 `initialize` 之前自动把 `parameters` 字典按 `__init__` 签名注入——任何模型无需自己解析参数即可被 Agent 驱动
- **`dt_scale`**：模型声明等效步长缩减（如刚性问题 0.01），工厂自动应用
- **`demo` 协议**：RL/推断类工具（81 个）在 initialize 内一次性计算并返回诊断观测，是设计特性非缺陷

---

## 5. AI Agent 层

### 5.1 工具合同（7 项）

| 工具 | 签名 | 功能 |
|---|---|---|
| `search_models` | (keyword) | 按 ID/名称/领域关键词搜索 456 模型 |
| `get_capabilities` | (model_id) | 能力卡：`__init__` 参数签名+默认值、数值观测量、协议类型 |
| `run` | (model_id, parameters, ticks) | 运行 → `{"model_id","n","observations":[...]}` |
| `sweep` | (model_id, param, values, ticks) | 参数扫描（一维多值） |
| `ensemble` | (model_id, seeds, parameters, ticks) | 多种子稳健性：均值/方差/CV |
| `compare` | (model_ids, ticks) | 跨模型共同观测量对照表 |
| `compose` | (steps) | 流水线：handoff 自动把前级终值字段注入后级参数（如 Goodwin 终态 k → AK 模型 k₀） |

**执行纪律**：所有工具确定性执行；返回经 `_clean_nan` 递归清理 NaN/Inf → null，保证 JSON 序列化永不 500。

### 5.2 语义映射层（semantic.py）

42 个中文领域正则模式 → 334 个模型引用，是 LLM 不可用时的保底理解层：

| 需求关键词 | 首选路由 |
|---|---|
| 疫情/传播/感染 | NET052 SIS 族 |
| 交通/拥堵/车流 | NET106 NS 元胞机 |
| 经济增长/储蓄/稳态 | ECO015 Solow |
| 经济周期/振荡 | ECO020 族 / ECO019 Goodwin |
| 金融/股市/崩盘 | ECO046 族 |
| 失业/就业/工资 | ECO078 族 / ECO019 |
| 人口/老龄化 | ECO057 Leslie 族 |
| 创新/熊彼特/研发 | ECO052 |
| 军备/冲突/战争 | ECO110 Richardson |
| 意见/投票/选举/极化 | BEH020 族 |
| 博弈/囚徒/合作 | BEH049 族 |
| 隔离/居住/城市空间 | BEH001 Schelling |
| 级联/停电/连锁崩溃 | NET078 族 |
| 信息/谣言/扩散 | NET074/081 族 |
| 供应链/牛鞭效应 | ECO104 |
| 气候/碳/排放 | ECO102 族 |
| 排队/服务/窗口 | SYS001 族 |
| 强化学习/智能体学习 | BEH112 族 |
| 认知/信念/决策 | BEH094 族 |
| 敏感性/Sobol/Morris | MET051 族 |
| 滤波/卡尔曼/同化 | MET043 族 |
| 集体行动/抗议/阈值 | BEH014 Granovetter |
| 行人/疏散 | NET113 社会力族 |
| ……（共 42 模式） | |

39 条端到端「需求→模型→运行」测试全通过。

### 5.3 LLM 规划器（llm_planner.py）

- **接入方式**：OpenAI 兼容 `chat/completions`；当前配置为阿里云 MaaS `deepseek-v4.1-flash-1017`；接口同构，可一行热切换本地 LM Studio
- **注入时机**：服务器启动事件里 `health()` 探测通过才调用 `set_llm_planner(llm_planner)`；`GET /api/agent/planner_status` 可查当前状态（`"aliyun-maas"` / `"rule"`）
- **输入**：系统提示（平台简介+工具说明+规划规则+模型家族提示）+ 工具清单 JSON + 用户需求文本
- **输出**：`{"planner":"llm","intent":"...","plan":[{"tool":"run","args":{...}},...]}`（最多 3 个动作）
- **鲁棒性**：网络异常/非 JSON 输出/结构缺失 → 返回空计划 → **自动回退规则路由**，用户侧永不报错

### 5.4 一次仿真请求的完整生命周期（真实案例）

用户在 AI 抽屉输入：

```
构建一个政治经济学仿真：资本主义工资份额与就业率的 Goodwin 增长周期，跑 400 步观察周期性
```

**① 前端** → `POST /api/agent {"text": "..."}`，同时事件流推送「AI 助手接收需求」。

**② 规划**（LLM）返回：

```json
{"planner":"llm",
 "intent":"运行 Goodwin 工资份额-就业率增长周期模型（ECO019），400 步观察周期性",
 "plan":[
   {"tool":"get_capabilities","args":{"model_id":"ECO019"}},
   {"tool":"run","args":{"model_id":"ECO019","ticks":400}}]}
```

**③ 确定性执行**：
- `get_capabilities` → 读 `data/model_capabilities.json` 能力卡
- `run` → `run_model("ECO019", ticks=400)` → Goodwin 模型每 tick 以中点法（40 子步）积分两组 ODE（ẇ/ω = −a+b·λ；λ̇/λ = (1−ω)/ν − δ），产出 **401 条观测**

**④ 回显**：
- 聊天区：`✓ 能力卡 ECO019: ...` / `✓ run ECO019（401 obs） wage_share=0.9746 employment=0.7281 ...`
- 标签：`[llm · 运行 Goodwin 工资份额-就业率增长周期模型 400 步观察周期性]`
- 事件流：`AI 执行 get_capabilities` → `模型运行完成 ECO019 · 401 个观测`
- **3D**：`DAYAN3D.visualize("ECO019", observations)` → 工资份额×就业率相空间轨道（w ∈ [0.876, 0.976]，λ ∈ [0.640, 0.871] 的闭合极限环），发光球循环重放，HUD 实时刷新

**三主权体现**：LLM 只写了那两行 plan（意义）；401 个状态值全部由确定性数值积分产生（状态）；Goodwin 方程与判据来自研究者定义的模型合同（理论）。

### 5.5 组合分析能力

| 能力 | 示例 | 已验证结果 |
|---|---|---|
| compose handoff | Goodwin 终态 → AK 增长 | 前级 k=3.047 自动注入后级 k₀ |
| sweep | NET106 density 0.1/0.3/0.5 | 通量-密度倒 U 曲线 |
| ensemble | 5 种子 | 均值±标准差+CV 稳健性 |
| compare | ECO110 vs ECO111 | 共同观测量对照表 |

---

## 6. 技术架构详解

### 6.1 代码库结构

```
msim/
├── dayan/                        # 平台 Python 包
│   ├── core.py                   # 内核：合同/时钟/队列/账本
│   ├── model_index.py            # 统一运行工厂（456 模型入口）
│   ├── coupled.py                # 范式耦合器（SD×ABM×LLM 三模式）
│   ├── server.py                 # FastAPI 服务（:8899）
│   ├── agent/
│   │   ├── agent.py              # fulfill 编排 + summarize 前端摘要
│   │   ├── intent.py             # 规划入口：LLM 槽 + 规则路由
│   │   ├── semantic.py           # 42 中文模式语义映射
│   │   ├── tools.py              # 7 工具实现 + _clean_nan
│   │   ├── composer.py           # sweep/ensemble/compare/compose
│   │   ├── metadata.py           # 能力卡探针生成
│   │   └── llm_planner.py        # 阿里云 MaaS 适配器
│   └── models/                   # 28+ 实现文件（按家族）
│       ├── epidemic.py opinion.py culture.py game_lib.py networks.py
│       ├── traffic.py pedestrian.py
│       ├── eco_models.py eco_demog.py eco_flagship_lite.py eco_final.py
│       ├── sys_models.py sys_extras.py
│       ├── met_models.py met_registry.py met_missing.py
│       ├── beh_abm.py beh_mind.py beh_rl.py game_catalog.py
│       ├── net_catalog.py net_extended.py net_final16.py landuse_ca.py
│       ├── app_scenarios.py app_final.py wave2.py benchmarks ...
├── site/console/                 # 前端（指挥中心）
│   ├── index.html  app.js  pages.js  viz3d.js  style.css  assets/
├── data/
│   ├── dayan_catalog.json        # 556 条目录
│   ├── model_capabilities.json   # 456 张能力卡
│   ├── full_validation.json      # 全量逐模型验证结果
│   └── test_stats.json           # 测试统计（31 套件）
├── tests/                        # run_all.py + 31 套件（191 断言）
├── results/
│   ├── patrol_log.txt            # 55 轮巡检 JSON-lines 审计
│   └── server.log
└── docs/                         # 平台手册、设计文档、本白皮书
```

### 6.2 内核（core.py）

- **ModelRecord** 十字段目录合同 + 合同校验拦截（缺字段直接拒绝注册）
- **四时钟语义**：fixed_step（固定步长离散）/ DES（事件驱动）/ ODE（连续积分）/ jump（跳跃过程）——目录里每条模型声明自己的时间观
- **RngStreams**：主种子派生子流（`seedRand` 分域），同种子实验逐位复现
- **EventQueue**：优先级键排序 + 事件取消 + **零时间循环防护**（同一时刻事件链 1000 步上限，防死循环吃内存）
- **BalancedLedger**：复式货币账本，每 tick 守恒检验（实测残差 ~1e-13）
- **StateDelta / DomainEvent**：状态增量与领域事件分离，观测与演化解耦
- **MAX_OBS**：观测列表容量护栏，防长时运行内存膨胀

### 6.3 统一运行工厂（model_index.py）

```python
run_model(model_id, ticks=100, parameters=None) -> list[dict]
```

- `ALL_INDEX`：456 个模型 ID → 工厂的映射（启动时从 models/ 全量注册）
- 按模型的 `clock_type` 分型执行：fixed_step 用 `eff_dt = dt × dt_scale`；ode 走积分器；sde 走 Euler-Maruyama；jump 走 Gillespie；des 走事件队列；demo 单次诊断
- `_apply_parameters`：**在 initialize 之前**注入参数（顺序经过实测修正——先 initialize 后注入会失效）
- 参数越界返回结构化错误而非异常炸服

### 6.4 服务端（server.py）

| 方法 | 路径 | 功能 |
|---|---|---|
| GET | `/` | 指挥中心页面（托管 site/console/） |
| GET | `/api/catalog` | 556 条目录 JSON |
| GET | `/api/models/runnable` | 456 个可运行模型清单 |
| POST | `/api/run` | 统一运行（ticks ≤ 500 护栏） |
| POST | `/api/agent` | Agent 完整执行（规划+工具+摘要） |
| GET | `/api/agent/tools` | 工具清单 JSON（喂 LLM 的 manifest） |
| GET | `/api/agent/planner_status` | 当前规划器（aliyun-maas / rule） |
| POST | `/api/ai/chat` | 通用对话（LLM 聊天回退） |
| 静态 | `/app.js /style.css /viz3d.js /pages.js /assets/*` | 前端资源 |

启动顺序：建 app → startup 事件 → LLM `health()` 探测 → 通过则 `set_llm_planner` 注入 → 控制台打印 `[DAYAN] LLM planner 已接入：aliyun-maas`。

### 6.5 前端架构（site/console/）

| 文件 | 职责 |
|---|---|
| `index.html` | 驾驶舱 DOM 骨架；Three.js CDN；脚本按序加载 app.js → pages.js；`?v=4` 缓存版本号 |
| `app.js` | ①`API` 桥接层（loadCatalog/runModel/agent，自动聚合目录+可运行集）②frame 主循环（时钟推进/事件节流/KPI 刷新/FPS）③城市 canvas 图层（人群粒子/热力/网络三图层）④`addEvent` + `window.DAYAN_EVENT` 钩子 ⑤干预分支/快照/模态（场景/模型/回放/追踪/帮助） |
| `pages.js` | ①`switchPage` 4 页导航（切页自动加载内容）②AI 抽屉（创建/收发/快捷按钮；run 结果 → `DAYAN3D.visualize` + 全动作事件推送）③模型表（201 行真实目录）④场景卡 ⑤回放页 |
| `viz3d.js` | Three.js 引擎：init 防重入；5 族类模板场景；`visualize()` 数据驱动三型场景（orbit/ridge/curve）；HUD；轨道控制器（拖拽旋转/滚轮缩放） |
| `style.css` | 赛博霓虹视觉（shadowBlur 发光/渐变描边）；AI 抽屉右侧滑入 |

### 6.6 数据文件

| 文件 | 内容 |
|---|---|
| `data/dayan_catalog.json` | 556 条目录（ID/名称/状态/家族/协议） |
| `data/model_capabilities.json` | 456 张能力卡：`__init__` 参数签名+默认值、数值观测量清单、时钟协议 |
| `data/full_validation.json` | 全量逐模型 50-tick 验证结果 |
| `data/test_stats.json` | 31 套件 191 断言统计（前端徽章数据源） |
| `results/patrol_log.txt` | 55 轮巡检审计（JSON-lines：轮次/时间/检查项/结论） |

---

## 7. API 参考

```bash
# 目录
curl http://127.0.0.1:8899/api/catalog
# → {"count": 556, "models": [{"model_id","name","status",...}, ...]}

# 可运行清单
curl http://127.0.0.1:8899/api/models/runnable

# 运行模型（带参数）
curl -X POST http://127.0.0.1:8899/api/run \
  -H "Content-Type: application/json" \
  -d '{"model_id":"ECO019","ticks":400,"parameters":{"nu":2.5}}'
# → {"model_id","ok":true,"n":401,"observations":[{...每tick观测...}]}

# Agent（自然语言）
curl -X POST http://127.0.0.1:8899/api/agent \
  -H "Content-Type: application/json" \
  -d '{"text":"扫参 NET106 density 0.1 0.3 0.5"}'
# → {"planner":"llm","intent":"...","plan":[...],"executed":[...],
#     "summary":["✓ sweep ..."],"ok":true}

# 工具清单 / 规划器状态
curl http://127.0.0.1:8899/api/agent/tools
curl http://127.0.0.1:8899/api/agent/planner_status
```

**`observations` 结构**：每 tick 一个字典，键为模型观测量名（数值/布尔/列表），直接可画图。前端 `DAYAN3D.visualize` 与 `tool_run` 共用此结构。

---

## 8. 质量与效度体系

### 8.1 测试矩阵

| 维度 | 结果 |
|---|---|
| 平台套件 | **191/191 PASS（31 套件）**：内核/引擎/家族基准/Agent/前端结构 |
| 全量逐模型 | 456/456 可运行（50 ticks，14 秒） |
| 数值合理性抽查 | 12/12（SIS 稳态/Solow 稳态/守恒 1e-13 级/配置效率 0.99…） |
| 参数敏感性 | 6/6（阈值/密度/储蓄率/初值全响应） |
| 边界值 | 9/9（极端参数不崩溃） |
| 长时运行 | 500-1000 ticks 10/10（无 NaN） |
| 服务压力 | 65/65（50 目录 + 10 运行 + 5 Agent 并发） |
| Agent 语义 | 39/39 端到端 |
| 前端路由 | 11/11 |

### 8.2 巡检机制

55 轮持续巡检零失败（`results/patrol_log.txt` 逐轮审计）：服务器健康 → 全量回归 → 轮换抽查 → 发现即修复 → 记录。累计修复 20+ 个缺陷（含参数注入顺序、注释吞行、画布重复初始化、事件流断链等）。

### 8.3 效度内建（v2 平台遗产）

- **遮蔽审计**：LLM 语义层 prompt 零理论词汇检测
- **消融**：去人设/去 LLM 对照
- **种子批**：多种子稳健性内置为 Agent 工具（ensemble）
- **发散监测**：gini/集中度越界告警
- **预注册器**：假设文本 SHA256 固化，`verify_prereg.py` 校验

### 8.4 诚实边界（重要）

- 态势总览页的「江城暴雨」KPI/热力/对照图为**合成演示数据**（展示驾驶舱形态用）；**真实仿真能力**通过 AI 助手、场景卡、模型表、`/api/run` 体现，运行结果即真实模型输出
- TOO 52 条为软件生态参考，不参与运行
- demo 协议模型（RL/MET 推断类 81 个）返回单条诊断观测，属设计约定
- 旧 msim v2 引擎（五层架构/理论包）与本平台（dayan/）并存，两套引擎不可跨对比（results/README.md 有标注）

---

## 9. 快速开始

```bash
# 1. 启动
cd D:\社会模拟仿真\msim
python -m dayan.server
# 看到 [DAYAN] LLM planner 已接入：aliyun-maas 即完整启动

# 2. 打开
# 浏览器访问 http://127.0.0.1:8899/

# 3. 用 AI 助手（推荐）
# 右下角 ◈ → 输入自然语言，例如：
#   「运行 NET106」
#   「构建 Goodwin 工资-就业周期仿真，跑 400 步」
#   「对 ECO016 扫参 k0 0.5 1.0 2.0」
#   「比较 ECO110 和 ECO111」

# 4. 程序化调用
# 见第 7 节 API 参考
```

**运行测试**：

```bash
python tests/run_all.py        # 191 断言 / 31 套件
python tests/test_dayan_agent.py
```

---

## 10. 已知边界与路线图

### 已知边界

| 项 | 现状 |
|---|---|
| LLM 依赖 | 规划器用阿里云 MaaS（可热切换本地 LM Studio）；断网自动回退规则路由，功能不中断 |
| 态势总览演示层 | 暴雨情景面板为合成数据（见 8.4） |
| LLM 微观主体 | BEH129-135 骨架就绪（ReAct/Reflexion/Voyager/Concordia 适配器），真正 LLM 在环实验待开启 |
| 人工参与项 | judge 打分工具就绪待打分；跨模型消融待批准；CGSS 微观数据待授权 |

### 路线图候选

1. 仿真结果持久化 + 历史运行库（回放页接真实历史）
2. 多模型对比自动报告导出（sweep/compare → PDF/MD）
3. 场景包扩展：恐怖事件应急、舆情危机、产业链中断等预制配方
4. LLM 在环微观主体实验（beh_mind × llm_planner 复用同一接入层）
5. 耦合器产品化：Goodwin SD × LLM 微观经济旗舰实验入 UI

---

*本文档对应 2026-11-10 代码状态：556 目录零仅登记 / 456 可运行 / 191 PASS / 55 轮巡检 / LLM planner 已接入 / 3D 数据驱动可视化上线。*
