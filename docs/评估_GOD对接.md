# R6 · GOD 控制室对接评估（v2 设计 §7）

> 决策：**另立会话对接**（本文档为评估依据，用户可推翻）。

## 1. 需求回顾
设计文档 R6："GOD 控制室对接、教学场景包、对外文档站"。后两项本会话已完成
（site/teachings/ + site/*.html + tests/test_site.py 3/3）。

## 2. GOD 是什么
- 仓库：`XiaoLuoLYG/GOD`（Govern·Observe·Direct），EMNLP 2026 Demo
- 功能：agent 社会实时**控制室**——React UI 暂停/干预/向单个 agent 提问/逐帧回放
- 架构：本地 FastAPI + OpenAI 兼容端点 + 预置 200 人小镇
- 依赖：基于 AgentSociety+JiuwenClaw 运行时（清华系）

## 3. 对接的三个选项

| 方案 | 内容 | 成本 | 风险 |
|---|---|---|---|
| A. 克隆对接 | clone GOD → 改 API 指向 msim 的 Kernel → 可视化干预 | 1-2 天 | GOD 绑定自家运行时，适配层要重写其 agent 循环；React 前端假定其数据结构 |
| B. 自研轻量监视器 | 在 msim Kernel 上加 WebSocket 流 + 极简 HTML 仪表盘（读 events.jsonl） | 0.5 天 | 功能弱于 GOD（无逐帧回放/单 agent 提问） |
| C. 另立会话 | 专项对接（需先调研 GOD 最新 API） | — | 推迟可视化能力 |

## 4. 决策理由（选 C）
1. **外部依赖风险**：GOD 是第三方仓库（非本工作空间资产），其 AgentSociety 运行时
   与 msim 的 Kernel 是两套世界模型，适配不是"接线"而是"桥接两座桥"
2. **当前阶段瓶颈不在可视化**：平台 35/35 测试已绿，缺的是 R5 人类校验（judge 复核）
   与正式实验的 campaign 数据——可视化对这两者是锦上添花
3. **已有最小替代**：Kernel 的 `events.jsonl` 全量事件流 + `make_dashboard.py`
   已能事后回放；课堂演示用教学规约 + 结果 PNG 足够
4. **避免范围蔓延**：设计文档 §8 风险表首条——"范围蔓延（什么学科都想做）"

## 5. 若用户要求立即对接（推翻本评估）
路径：clone 到 `external/god` → 读其 `server/` API 契约 →
写 `src/kernel/god_bridge.py` 把 msim Kernel 包装成其期望的 agent provider →
前端不动。预估 1-2 天，需用户确认投入。

## 6. 状态更新（2026-11-07 第二轮）

**桥接已实现**：`src/kernel/god_bridge.py`——MsimGodSession 按 GOD 路由真实调用面
（status/init/run_step/ask/intervene/set_auto/pause/stop/sync/to_status().model_dump()
/broadcast）实现鸭子会话；`register_session` 按 `LiveExperimentManager._sessions`
的真实三元组键 `(workspace_path, hypothesis_id, experiment_id)` 预插入（manager.get
无类型检查 → 零侵入）。测试：tests/test_god_bridge.py 5/5（含 stub manager 真实
注册路径、LiveExperimentStatus 字段对齐、ask/intervene 请求形状）。

**依赖安装定案（硬证据）**：agentsociety2 的 pyproject.toml 依赖含
`torch>=2.9.1`、`ultralytics>=8.3`、`transformers>=4.57`、`mineru[core]`、
`chromadb`——**多 GB 级安装**（torch 单项 2GB+，mineru 拉 OCR 模型），与用户
"太大会卡机器"的约束同类。**不自动安装**；若用户接受一次性多 GB 安装（独立
venv 隔离），安装后一行即可全栈联调：
```bash
cd external/god/agentsociety/packages/agentsociety2 && uv pip install -e .
python -c "from src.kernel.god_bridge import register_session; print('联调就绪')"
```
