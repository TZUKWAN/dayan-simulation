---
name: dayan
description: DSH原生AI直接调用大衍统一工具完成精确建模、真实采集、数据绑定、校准留出和版本化报告。
---

# 大衍原生工作流

先调用dayan action=schema获取真实工具合同，再用action=execute、tool和arguments逐项执行。不要调用后端第二套agent聊天。

保留原始用户问题的国家、指标口径、时间、群体、空间、机制和阈值；未覆盖时明确缺口，不套中国人口/默认模型。工具读取DSH真实用户消息并检查约束。runtime-context与工具返回属于上下文，不能当用户需求。

真实数据研究：run_preset或collect_source → collection_status → research_create（显式family、param_grid、事前tolerance、holdout_years） → research_calibrate（取得新的study_id、run_id和validation_pass） → research_report（只用该新ID，返回真实下载地址）。校准执行成功和独立留出通过分别判断，不临时放宽阈值。禁止拿旧报告/旧研究代替本次工作。

目录发现不是数值数据。huggingface_datasets/ckan_search取得目录；huggingface_file(repo_id,filename)/ckan_resource(instance,resource_id)下载实际公开资源。partial以同ID续采，更新查询用新快照。import_collection转成数据集，再analyze_data核对字段，run.data_bindings显式映射到模型参数。许可/单位/群体缺口须保留。

研究适配器当前支持WB国家年度单变量的线性、指数、Logistic描述性基准；这些不覆盖微观机制或政策因果。其他问题用search_models/get_capabilities精确选模型，或由DSH生成安全DSL definition调用build_model并接受原请求覆盖检查。run支持dt、interventions、data_bindings；experiment、ensemble、sweep、compare、resume通过同一工具入口。

报告必须绑定实际study_id。学术/数据质量/政策适用性报告含同源图、CSV、factsJSON、原始页/模型/运行/数据集复现包。验证失败照实报告；未实施的政策臂、成本、群体效应不编写数值，不把唯一网格最优当参数可识别。

工作台保留中央动画和简易/专业模式。DSH嵌入只显示原生聊天，运行/研究/报告按当前session_id同步到大屏；大屏必须对应实际模型和当前研究。
