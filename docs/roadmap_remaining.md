# 剩余路线图（本页即"待办收口"，逐项销账）

## 已完成（2026-11-06 大冲刺后）
- [x] 预注册固化 v0.1（H7-H9 + 统计方案，SHA256 校验通过）
- [x] 合作社制度变体（模式C）+ 冲击实验（H7）+ 问卷（H9a）+ 物化话语（H9b）
- [x] mock 集成测试（test_pipeline 5/5）
- [x] campaign runner（多种子×多条件 + MWU 汇总）
- [x] 报告升级：转移矩阵/企业生命周期/定量靶对照（targets.json）
- [x] 价值规律实验 v1（rule 版相关 0.78→0.87；LLM 版待 campaign 空闲后冒烟）
- [x] 多组 dashboard（浅色版 + s43 版）+ 论文骨架 + 跨模型协议
- [x] LLM 管线自动化测试缺失 → 已补

## 等待后台 campaign 完成
- [ ] 16 runs（rule×4 / llm×4 / nopersona×2 / coop-rule×2 / coop-llm×2 / shock×1）
- [ ] H7-H9 判决 + MWU 汇总（run_campaign.py --summary 自动生成）
- [ ] value law LLM 冒烟（LLM 空闲后：`python experiments/run_value_law.py --mode llm --agents 12 --ticks 40`）

## 需要用户参与
- [ ] judge 人工复核：用 results/mvp_llm_s7/alienation.csv 抽 30-50 条人工评分
      （1-5 五维），与 LLM 评分算一致率（协议可另出表格模板）
- [ ] 跨模型消融执行：见 docs/protocol_跨模型稳健性.md（放开"只用4B"约束后）

## 阶段 3-4（大项，另立会话执行）
- [ ] OASIS/AgentSociety 1000+ 观念实验（装 camel-oasis 依赖；单独立项）
- [ ] GOD 可视化控制室教学演示（克隆仓库 + 运行时对接）
- [ ] 论文成稿（骨架见 docs/论文骨架_v0.md；campaign 数据回填后可开写）
- [ ] 国社科申报对接（D:\国社科 模板）
