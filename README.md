# 大衍 DAYAN — 社会仿真与数据研究工作台

安装、访问控制、资源预算、中文字体、外部服务和归档重跑见 [部署说明](docs/DEPLOYMENT.md)。

当前能力按“目录登记 → 运行工厂 → 当前源码探针 → 机制审查 → 逐研究校准 → 独立留出”分别展示。下文各版本的测试数和实验结果属于当时的历史记录，不代表全部模型已在当前版本通过科学验证。运行成功、动画存在或数据已接入都不能代替校准与留出验证。

2026-11-18 的系统整改、真实数据/原生 DSH/实际 AI 建模验收与逐项证据见 [完整审计交付](docs/SYSTEM_AUDIT_20261118.md)。代码在独立修复分支，main 不自动切换。

早期 VNext 的七个研究空间、实际运行截图、浏览器录屏、模型审查和两项真实数据案例见 [VNext 历史交付验收](docs/VNEXT_ACCEPTANCE.md)。当前界面已合并为下述两页。

Future OS 的场景构图、工作空间改版、前后对照、操作录屏和性能实测见 [第二轮视觉与交互验收](docs/FUTURE_OS_ACCEPTANCE.md)。

当前操作入口为两页：**仿真现场**显示与实际状态相连的场景、指标、过程直播和 AI 对话；**历史记录**支持自动命名、改名、删除、回放和同源分析报告。参数控制在现场按需展开，已移除简易/专业模式切换。DSH 内使用绑定的原生对话。

大规模场景按实际主体显示有界样本；分布、空间密度、属性表与运动统计从完整状态列计算。主体编号框可输入未在画面中抽到的实际编号，按需读取完整轨迹。选区分析和 Word 使用同一时间、字段与空间范围。显示采样数不代表总体统计样本数。

模型目录、实现可运行与实证有效性是不同层次。当前自动研究适配主要覆盖世界银行国家年度序列的线性、指数和 Logistic 描述性趋势；其他来源/机制需要明确映射和逐场景验证。训练合格不等于留出合格，也不等于政策因果效应成立。

## 启动工作台

本次发布准备使用 Python 3.13.2 环境。克隆仓库后，在仓库根目录执行：

```bash
git clone https://github.com/TZUKWAN/dayan-simulation.git
cd dayan-simulation
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# macOS / Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m dayan.server
```

打开 <http://127.0.0.1:8899>。未配置 LLM 凭据仍可使用模型和参数入口；AI 建模/解释等需要实际配置的模型服务，不会用固定回复替代。部分可视化资源和真实数据源需要网络。

独立网页助手可设置环境变量 DAYAN_API_KEY、DAYAN_BASE_URL、DAYAN_MODEL，或将 dayan/config.example.json 复制为 dayan/config.json 后填写真实服务配置。base_url 是 OpenAI 兼容 API 的基础地址（通常以 /v1 结尾）。真实配置已加入忽略规则，不要提交密钥。

## DSH 原生助手

插件位于 plugins/dayan，需要 DSH >=0.2.2-rc.1。克隆后，在 DSH 插件管理中使用该目录的本地 link: 安装方式；例如 link:/absolute/path/dayan-simulation/plugins/dayan。插件必须能定位整个仓库；如果通过复制方式安装，请为宿主设置 DAYAN_PROJECT_ROOT 指向仓库根目录、DAYAN_PYTHON 指向已安装依赖的 Python。

DSH 中左侧使用项目专属原生会话，右侧工作台同步同一会话结果。中间分隔线支持拖拽、刷新保留宽度、双击复位和方向键微调。DSH 原生模式使用 DSH 已配置的模型服务，不经过第二套网页 AI。更新插件后需要按 DSH 的刷新/重载机制应用新代码。

## 代码与数据

- dayan/：模型、运行合同、采集/研究/报告服务与本地后端。
- src/、experiments/：早期经济/社会理论包、实验内核与实验脚本。
- site/console/：真实运行驱动的界面和动画。
- plugins/dayan/：DSH 原生插件。
- tests/：单元与行为回归；测试 fixture 明确标记，不作为实证数据。
- data/：只发布静态模型目录、源码忠实度审查资料及声明的参考靶；运行探针与能力缓存由本机生成。

私人会话、真实 API 配置、采集快照、运行档案、报告和本机验收缓存不随代码公开。程序在实际使用时生成自己的数据目录。external/ 下的可选第三方工程不随仓库打包，GOD/agentsociety2 对接需要另外安装。

## 定向测试

```bash
python -m unittest discover -s tests -p test_research_integrity.py
node --test tests/dayan_session_binding.test.mjs
```

下文保留早期开发与实验记录。其中的测试数量、模型规模和实验结论属于记录时的特定版本与条件，不是对全部模型、全部数据源或任意政策场景的统一验收结论。此前公开快照只做过内容审计和启动检查；本轮系统整改另有实际全入口回归与在线验收，见上方审计交付。

---

## 历史项目与实验记录

> **大衍 DAYAN**：多范式（ABM/SD/CA/博弈/DES/ODE/SDE/微观仿真）× 多学科
> （482 具名模型目录 + 21 应用组合）× LLM 语义层（本地 Qwen3.5-4B，遮蔽设计）
> 的一站式社会仿真平台。基于《DAYAN 社会仿真模型级方法论清单与平台实现规范》
> （v1.0，检索截止 2026-11-07）第二章平台实现规范建设。
>
> 历史：DAYAN 在 msim 马克思主义理论大模型仿真实验台（v0/v1 全绿）基础上扩建；
> msim 的政治经济学/社会学/政治学/文化媒介包全部保留为 DAYAN 的 ABM 理论包。

> 独立立项的新研究工程。外部文献基础（三份调研报告）在 `../llm_sim_survey/`；
> 总体设计见 `../llm_sim_survey/00_总览与项目设计.md`。

## 这是什么

用本地大模型（Qwen3.5-4B @ LM Studio）驱动的多智能体"玩具资本主义"受控实验，
对马克思主义政治经济学命题做**涌现探索**与**机制验证**：

- **层1 确定性经济内核**（`src/ledger/`）：雇佣、计件工资、订单制市场、设备部门
  （两大部类货币回流）、逐 tick 全量记账——LLM 不做任何算术；
- **层2 LLM 语义层**（`src/agents/`）：求职/定价/用工/开业等自然语言决策 + 叙事生成；
  遮蔽设计（prompt 零理论词汇，已审计）+ 规则回退；
- **层3 测量层**（`src/measures/`）：基尼/双形态拟合（Yakovenko 靶）、剥削率代理、
  阶级转移矩阵、Seeman 五维异化量表（LLM-as-judge）；
- **层4 效度对照层**（`src/validity/`）：规则基线差分、人设消融、种子稳健性、
  自动报告（图+markdown+校准靶对照+口径声明）。

## 快速开始

```bash
# 0) 启动 LM Studio 并加载 qwen3.5-4b（默认端口 1234，无需鉴权）

# 1) 经济内核单元测试（守恒/复现/激活/钳制）
python tests/test_ledger.py

# 2) 规则基线组（零 LLM，1 秒）
python experiments/run_mvp.py --mode rule --agents 200 --ticks 200 --seed 7 --tag mvp_rule_s7

# 3) LLM 主组（25% LLM agent 混合人口，约 15 分钟）
python experiments/run_mvp.py --mode llm --agents 200 --ticks 200 --llm-ratio 0.25 \
    --seed 7 --narr-every 8 --narr-sample 24 --workers 8 --tag mvp_llm_s7

# 4) 人设消融（消融B）
python experiments/run_mvp.py --mode llm ... --no-persona --tag mvp_llm_s7_nopersona

# 5) 组间对比
python experiments/compare_runs.py mvp_rule_s7 mvp_llm_s7 mvp_llm_s7_nopersona mvp_llm_s43
```

## 产物结构（results/<tag>/）

`config.json`（快照）· `metrics.csv`（逐 tick 指标+守恒残差）· `firms.csv`（企业账本）
· `agents_final.csv` · `transitions.json`（阶级转移矩阵）· `alienation.csv` + `narratives.jsonl`
· `llm_log.jsonl`（全量调用审计）· `cache.jsonl`（响应缓存）· `REPORT.md` + 图。

## 首轮结果（2026-11-06）

- H1–H5 方向性全部成立；**异化组间排序与《1844手稿》预期一致**：
  无力感 受雇 3.05 > 自营 2.29；总分 失业 15.75 > 受雇 10.36 > 自营 8.89（n=600，99.3% LLM-judge）；
- LLM 组涌现规则组没有的行为：**价格战**（p_ref 7.43→2.82，−60%）与**财富集中**
  （基尼 0.306→0.727）——LLM 语义层不是噪声；
- 剥削率代理 0.31–0.37，劳动份额 0.73–0.76（靶区间附近）；
- 金钱守恒残差 ~1e-13；同种子完全可复现。

## v0.1 扩展（2026-11-06 第二轮）

- **预注册 v0.1**（H7-H9 + 统计方案，SHA256 固化，`experiments/verify_prereg.py` 校验）
- **制度对照（模式C）**：`--institute coop` 生产合作社（社员均分结余、民主积累）
- **危机冲击（H7）**：`--shock-factor 0.45 --shock-tick 120`（含求职摩擦→真实失业存量）
- **测量扩展**：阶级意识问卷（survey.csv）+ 商品拜物教话语（fetishism.csv，双通道叙事轮替）
- **价值规律实验 v1**：`experiments/run_value_law.py`（rule 版 Pearson 0.78→0.87）
- **campaign**：`experiments/run_campaign.py`（多种子×6条件 + Mann-Whitney U 汇总）
- **工程**：mock 集成测试 `tests/test_pipeline.py`（5/5）；报告升级（转移矩阵/企业生命周期/定量靶 targets.json）
- **文档**：论文骨架、跨模型协议、剩余路线图（docs/）

## DAYAN P0+P1（2026-11-07，按《规范》第二章实施）

### P0 内核与合同（验收：test_dayan_core 11/11）
- 模型登记表：10 字段组合同 + 六级实现状态（仅登记→原型可跑→基准通过→数据校准→留出验证→生产可用）+ 合同校验拦截
- 四时钟（仿真/迭代/LLM墙钟/批次）· 派生随机流（按名独立、跨实例可复现）· 事件队列（时间→优先级→稳定序号 + 取消 + 零循环防护）· 平衡账本 · StateDelta/DomainEvent · 快照恢复
- **556 条目录登记**：482 具名模型（BEH138/NET120/ECO115/SYS45/MET64）+ 22 应用 + 52 软件（data/dayan_catalog.json，从规范 docx 自动提取）

### P1 基准模型（验收：test_dayan_models 13/13，全部解析/公开基准）
DTMC（平稳分布）· M/M/1（DES，吞吐≈λ）· SIR（终局规模方程）· SEIR（R0>1 爆发）· DeGroot（共识=左特征向量）· HK（有限簇）· ER（平均度）· WS（小世界）· BA（幂律 CCDF≈-2）· IC（单调）· LT（阈值0=可达闭包）· Leslie（增长率=λ1）· Leontief（(I-A)^-1d）

### 既有资产迁移（登记为基准通过）
Schelling 分异涌现 · Axelrod 地域化 · Sugarscape 财富分布 · 玩具资本主义（15 runs campaign）· LLM 语义层（四包在环+三包冒烟零回退）

## v2 平台化（2026-11-07，按 docs/设计_v2_社会科学仿真基础设施.md 实现）

**五层架构已落地，验收全绿（26/26 测试）：**

| 层 | 组件 | 验收证据 |
|---|---|---|
| 层0 中立内核 | `src/kernel/`（事件溯源/不变量校验/种子纪律/JSONL日志） | 纯净性测试：无 LLM/学科依赖 |
| 层1 理论包 | `src/packs/`：政治经济学包(含组织/劳动增量)/社会学包/政治学包/文化媒介包/基准×2 | 空包骨架声明七件套即可注册 |
| 层2 认知层 | 复用 v0/v1 agents（遮蔽/回退/judge） | 三主权边界测试：LLM 意向经 action_handler 裁决 |
| 层3 测量 | 复用 v0/v1 measures（分布/量表/问卷/物化） | 测量钩子注册制 |
| 层4 实验管理 | `experiments/run_spec.py`（YAML 规约驱动）+ 效度门禁 | 门禁拦截缺效度方案的规约 |

**基准复现套件（R1）**：Sugarscape 财富分布（gini 0.53）· Axelrod 规范地域化（900→278 区域）——常驻回归，任何内核改动后必跑全绿。

**R5 规约注册表**：实验可引用性——登记入册（内容寻址句柄 `msim://spec/<hash16>`，改动即新句柄防篡改）、幂等、按包/关键词/作者检索、引用计数。教学规约已联动登记。

**R6 教学场景包+文档站**：3 个预置教学规约（Schelling/Downs/假新闻级联，含教学要点）；文档站 `site/`（index/packs/teachings/roadmap 四页，`experiments/build_site.py` 一键重建）。GOD 控制室桥接 src/kernel/god_bridge.py（协议面/run_step/ask/intervene 全通，GOD 未装时降级为会话工厂；external/god 已 clone）。

**文化媒介包（R4）**：假新闻级联基准（算法偏置放大 3.2×，public 所有制压制至 0.31）· 回音室测量（同温层门控同化，echo_chamber 0.794→0.852）· 拜物教通道复用（与 polecon TransactionPipeline 联动）。

**组织/劳动过程增量（§3.5 方案A并入 polecon）**：Braverman 去技能化（受雇者技能退化 0.47，就业收缩 2→0）· 监控强度接线（待 LLM 异化实测）——评估报告见 docs/评估_组织劳动包.md。

**政治学包（R3）**：Downs 中位选民收敛（胜方-中位距 0.018）· Duverger 定律（plurality→1.00 两党 / proportional→2.84 多党）· **经济基础→政治反应联合实验**（政治经济学冲击→失业 13 人→抗议率 0.11 vs 对照 0.00，差分 +0.11）——v2 设计 §3.3 的跨包传导链验证。

**社会学包（R2）**：Schelling 分异（0.52→0.97）· 规范采纳 · 地位字段 · **跨包联动接口**（政治经济学包的阶级位置 → 社会学包的规范采纳先验）——基础-上层建筑传导的最可操作化切口已打通。

**用法（平台统一入口）**：
```bash
python experiments/run_spec.py --spec tests/fixtures/scenario_smoke.yaml --tag my_run
```

## Campaign v2（当前引擎重跑，2026-11-07）

15 runs 在审计修复后的引擎上全部重跑（节欲/门槛/背叛机制已变）：H1-H5 方向性结论保持；**合作社方差坍缩效应复现**（coop-llm gini std 0.009 vs llm 0.273）；H6 人设消融坍缩未复现（修正为"依赖种子"）；H7 仍 inconclusive（n=3<20）。完整判决见 results/CAMPAIGN_SUMMARY.md v2 表。

## judge 人工复核工具（R5）
```bash
python experiments/judge_review.py make --run camp_llm_s7 --n 40   # 生成分层抽样评分表
# 打开 results/judge_review_*/review_sheet.csv 在 5 个"人工_*"列填 1-5 → 保存
python experiments/judge_review.py score --run camp_llm_s7          # 自动一致性报告
```
你的参与被压缩为：打分 → 跑一条命令。

## R7 多范式引擎（2026-11-07，按 docs/设计_v3_多范式仿真扩展.md 实现）

### EquationEngine（系统动力学，`dayan/engines/sd.py`）
- 声明式存量-流量规约（stocks/flows/net_stock/aux/params/links）
- RK4 积分（经统一编排器 ODE 分支）+ 因果图 mermaid 渲染
- 基准：茶杯冷却（解析解误差<0.05）· **Goodwin 增长周期**（有界闭轨道 0.93~1.03）
- 数值警告全程 np.errstate 抑制（宕机根因修复：eval 空 builtins 下溢出告警→`__import__` 查询→KeyError）

### GameEngine（博弈，`dayan/engines/games.py`）
- 纯纳什枚举 + 2x2 混合纳什（标准无差异公式）+ 复制动态
- 基准：PD 唯一纯纳什 (D,D)（B=A 转置修复）· 鹰鸽混合 x_H=V/C=0.67 · 性别战 2 纯+1 混合
- LLM 玩家（遮蔽变体）：未告知博弈名，PD 下动作分布 [1]——**自发收敛到纳什**（涌现发现）

### OREngine（运筹，`dayan/engines/or_lp.py`）
- scipy linprog 运输/LP + propose–dispose 协议（LLM 提案、求解器裁决）
- 基准：教科书 LP 最优命中；运输最优 465 vs 非最优提案 gap=80>0；负运量被拒

### Wave-2 目录模型（`dayan/models/wave2.py`）
Solow（k*收敛<1%）· SIS（地方病均衡=1−1/R0）· 选民（共识均值=初始份额，20 次重复）· Bass（F(30) 解析吻合）· 复制动态（x_H→V/C）

**全平台 93/93 测试通过（18 套件）**。

## 已知局限

跨模型稳健性协议已备好待批准（docs/protocol_跨模型稳健性.md）；judge 人工复核待用户参与；
剥削率为代理口径（data/calibration_targets.md）；价值规律 LLM 版待跑；
定量靶为已发表口径数字（CGSS 微观数据接入留待阶段2）。
