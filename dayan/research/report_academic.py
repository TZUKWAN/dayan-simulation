"""三类研究报告生成（任务书 §7.2）：
A 数据采集与质量报告
B 学术研究报告
C 政策模拟简报

每份报告引用真实 collection_id / 校准结果 / 数据哈希，不编造数字。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # dayan/research/ → 工程根
REPORTS_DIR = ROOT / "data" / "collection" / "reports"


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _md_table(headers: list, rows: list) -> str:
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def generate_data_quality_report(matrix: list, tasks: list, quality_checks: list,
                                 output_dir: Path = None) -> str:
    """报告A：数据来源、真实查询/覆盖、缺失、口径、许可、复用度。"""
    live = [m for m in matrix if m["state"] == "live"]
    needs_auth = [m for m in matrix if m["state"] == "needs_auth"]
    down = [m for m in matrix if m["state"] == "down"]
    other = [m for m in matrix if m["state"] not in ("live", "needs_auth", "down")]

    lines = [
        "# 数据采集与质量报告",
        f"\n生成时间：{_now()}\n",
        f"\n## 1. 来源矩阵概览\n",
        f"总来源 {len(matrix)} 个；真实采集可用 {len(live)}；需凭据 {len(needs_auth)}；"
        f"暂不可用 {len(down)}；其他（候选/已配置） {len(other)}。",
        "",
        "### 状态分布",
        _md_table(["状态", "数量", "来源"],
                  [(registry_STATE_ZH[m["state"]], 1, m["source_id"])
                   for m in matrix]),
        "\n### 真实采集可用来源（live）",
        _md_table(["来源", "类别", "采集模式", "许可", "认证"],
                  [(m["name"], m.get("cat"), ",".join(m.get("mode", [])),
                    m.get("license", ""), m.get("auth", ""))
                   for m in live]),
        "\n### 需凭据来源（用户可免费注册后解锁）",
        _md_table(["来源", "认证要求"],
                  [(m["name"], m.get("auth", "")) for m in needs_auth]),
        "\n### 暂不可用（留证待复查）",
        _md_table(["来源", "失败原因"],
                  [(m["source_id"], "; ".join(f.get("detail", "")[:80]
                                              for f in m.get("failures", [])[-1:]))
                   for m in down]),
    ]

    # 采集任务明细
    ok_tasks = [t for t in tasks if t.get("status") in ("done", "partial")
                and t.get("n_records", 0) > 0]
    lines.append("\n## 2. 真实采集任务明细")
    lines.append(_md_table(
        ["任务ID", "来源", "连接器", "主题", "状态", "记录数", "部分标记"],
        [(t["collection_id"], t.get("source_id"), t.get("connector"),
          t.get("theme", ""), t["status"], t.get("n_records", 0),
          "是" if t.get("partial") else "否")
         for t in ok_tasks]))

    # 质量检查汇总
    if quality_checks:
        lines.append("\n## 3. 数据质量检查结果")
        lines.append(_md_table(
            ["变量", "状态", "记录数", "覆盖率%", "时间范围", "问题"],
            [(q["variable"], q["status"], q.get("n_records", 0),
              q.get("coverage_pct", ""), str(q.get("time_range", "")),
              "; ".join(q.get("issues", []))[:60])
             for q in quality_checks]))

    lines.append("\n## 4. 局限与边界\n")
    lines.append("- 本报告仅覆盖本轮实际探测和采集的来源，不声称穷尽所有人文社科数据渠道。")
    lines.append("- 「真实采集可用」表示本机已成功获取非空数据，不表示数据完整、准确或已校准。")
    lines.append("- 需凭据来源按任务书要求留证，用户注册后可解锁。")
    lines.append("- 部分采集（partial）明确标记，不代表全量。")

    text = "\n".join(lines)
    output_dir = output_dir or REPORTS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "report_A_data_quality.md"
    path.write_text(text, encoding="utf-8")
    return str(path)


def generate_academic_report(use_case_data: dict, output_dir: Path = None) -> str:
    """Compatibility entry: only verified versioned studies may produce a research report."""
    study_id = use_case_data.get("study_id")
    if not study_id:
        raise ValueError("历史用例没有统一study_id，不能套固定人口模板；请先执行research_create/research_calibrate")
    from .study_reports import generate_report
    from .studies import directory
    report = generate_report(study_id, "academic")
    return str(directory(study_id)/"reports"/(Path(report["file"]).stem+".md"))


def _legacy_academic_template_disabled(use_case_data: dict, output_dir: Path = None) -> str:
    """报告B：学术研究（问题/文献/方法/设计/结果/反证/局限）。"""
    uc = use_case_data
    cal = uc.get("calibration", {})
    lines = [
        "# 学术研究报告：中国人口趋势的指数增长模型校准与留出验证",
        f"\n生成时间：{_now()}\n",
        "\n## 1. 研究问题\n",
        "中国人口总量 2018-2022 的变动是否可用简单指数增长模型描述？"
        "模型在未经拟合的 2022 年留出数据上的预测误差是多少？",
        "\n## 2. 数据来源与方法\n",
        f"- 数据来源：World Bank Indicators API（SP.POP.TOTL 指标），"
        f"collection_id={uc.get('requirement', {}).get('requirement_id', '')}，"
        f"共 {uc.get('n_records_used', '?')} 条中国人口记录",
        "- 清洗：剔除缺失/非有限值（操作链哈希见归档）",
        "- 时间切分：2018-2021 用于参数拟合，2022 作为留出验证（非随机分割）",
        "- 泄漏检查：校准/留出集合无重叠",
        "\n## 3. 模型说明\n",
        "指数增长模型：P(t) = P0 · exp(r · (t - 2018))",
        "其中 P0 为初始人口，r 为年增长率（待估参数）。",
        "参考模型（基线）：历史均值预测。",
        "\n## 4. 参数校准（网格搜索）\n",
        f"- 待估参数网格：P0 ∈ [1400M, 1402.5M, 1405M, 1406.17M, 1406.5M]，"
        f"r ∈ [-0.002, -0.001, -0.0001, 0.0001, 0.001]",
        f"- 最优参数：{cal.get('best_params')}",
        f"- 校准 RMSE：{cal.get('best_loss')}（vs 基线均值 RMSE {cal.get('baseline_mean_rmse')}）",
        f"- 改善：{cal.get('improvement_vs_baseline')}",
        f"- 评估次数：{cal.get('n_evaluated')}（失败 {cal.get('n_failed')}）",
        f"- 不可识别：{'是' if cal.get('non_identifiable') else '否'}"
        f"（{cal.get('non_identifiable_note', '')}）",
    ]
    if cal.get("holdout"):
        h = cal["holdout"]
        lines.append("\n## 5. 留出验证（2022年，独立于拟合数据）\n")
        lines.append(f"- 留出集大小：{h['n']} 条")
        lines.append(f"- 留出 RMSE：{h['rmse']:.0f}")
        lines.append(f"- 实际值：{h['actual']}")
        lines.append(f"- 模型预测：{h['predicted']}")
        lines.append(f"- 残差：{h['residuals']}")
        if h.get("residuals") and all(abs(r) < 2000000 for r in h["residuals"]):
            lines.append("- 2022 年留出误差约 1.5M（0.11%），模型可描述该时期的整体趋势，"
                         "但简单指数模型无法刻画人口结构性变化（老龄化、出生率下降等）。")
    if cal.get("tolerance") is not None:
        lines.append(f"\n## 6. 验收标准与通过状态\n")
        lines.append(f"- 事先声明阈值 RMSE ≤ {cal['tolerance']}；"
                     f"实际 {cal.get('best_loss')} → "
                     f"{'通过' if cal.get('tolerance_met') else '未通过（如实报告，不调阈）'}")
    lines.append("\n## 7. 局限与替代解释\n")
    lines.append("- 指数增长模型是极简描述；替代机制包括 Leslie 矩阵模型（含年龄结构）、"
                 "Logistic 增长模型（容量约束）、或分解死亡率/出生率/迁移的分方程模型。")
    lines.append("- 单一指数模型对 4 年数据的拟合无法区分多种机制，"
                 f"不可识别诊断 = {cal.get('non_identifiable')}。")
    lines.append("- 本结果仅描述历史趋势，不构成对生育政策效果的因果推断。")
    lines.append("- World Bank 人口数据基于联合国估算，本身存在口径和时滞。")

    text = "\n".join(lines)
    output_dir = output_dir or REPORTS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "report_B_academic.md"
    path.write_text(text, encoding="utf-8")
    return str(path)


def generate_policy_brief(use_case_data: dict, policy_data: dict,
                          output_dir: Path = None) -> str:
    """Do not fabricate policy effects from an unrelated population fit or old cost sample."""
    if policy_data:
        raise ValueError("旧政策字典没有统一运行/来源/假设合同，不可套用固定成本或排序生成现实政策简报")
    study_id=use_case_data.get("study_id")
    if not study_id:raise ValueError("须指定实际study_id；描述性趋势仅可输出政策适用性限制")
    from .study_reports import generate_report
    from .studies import directory
    report=generate_report(study_id,"policy")
    return str(directory(study_id)/"reports"/(Path(report["file"]).stem+".md"))


def _legacy_policy_template_disabled(use_case_data: dict, policy_data: dict,
                          output_dir: Path = None) -> str:
    """报告C：政策模拟简报（现状/政策/预算/不确定性/失效条件）。"""
    cal = use_case_data.get("calibration", {})
    baseline = policy_data.get("baseline", {})
    p1 = policy_data.get("policy1", {})
    p2 = policy_data.get("policy2", {})

    b_last = baseline["trajectory"][-1]
    p1_last = p1["trajectory"][-1]
    p2_last = p2["trajectory"][-1]

    lines = [
        "# 政策模拟简报：人口趋势政策情景（基线 vs 生育激励）",
        f"\n生成时间：{_now()}\n",
        "\n## 1. 适用范围与现状\n",
        f"- 地域：中国（全国层面）；分析单位：人口总量（人）",
        f"- 基准期：2018-2022（真实数据校准）；"
        f"模型校准 RMSE {cal.get('best_loss', '?')}（vs 均值基线 {cal.get('baseline_mean_rmse', '?')}）",
        f"- 2022 年实际人口：{all_data.get('holdout_actual', '[见学术报告]')}",
        "\n## 2. 政策方案\n",
        "| 方案 | 增长率变化 | 成本口径 | 人均年成本 |",
        "|---|---|---|---|",
        f"| 基线（现有趋势） | {baseline.get('rate', '?')} | — | 0 |",
        f"| 生育激励(温和) | {p1.get('rate', '?')} | 年度财政投入 | 500元/人 |",
        f"| 生育激励(强)+托育 | {p2.get('rate', '?')} | 年度财政投入 | 1500元/人 |",
        "\n## 3. 结果与预算\n",
        _md_table(["方案", "2027年人口", "vs基线差异", "累计成本(2023-2027)"],
                  [(baseline["scenario"], f"{b_last['population']/1e6:.1f}M", "—", "—"),
                   (p1["scenario"], f"{p1_last['population']/1e6:.1f}M",
                    f"+{(p1_last['population']-b_last['population'])/1e6:.1f}M",
                    f"{p1['total_cost_by_2027']/1e12:.2f}万亿"),
                   (p2["scenario"], f"{p2_last['population']/1e6:.1f}M",
                    f"+{(p2_last['population']-b_last['population'])/1e6:.1f}M",
                    f"{p2['total_cost_by_2027']/1e12:.2f}万亿")]),
        "\n## 4. 不确定性与敏感性\n",
        "- 增长率 r 的校准不确定度未做置信区间（需多种子或贝叶斯校准）；"
        "模型内多次仿真重复只反映仿真随机波动，不是现实总体 CI。",
        "- 敏感性：r±0.0005 的变化对 2027 年人口影响约 ±5-6M；"
        "增长率的不确定性是首要脆弱参数。",
        "- 政策效果参数（Δr = +0.001/+0.002）基于文献区间假设（非实际估计），"
        "标注为「文献迁移假设」。实际政策效果需准实验数据。",
        "\n## 5. 结论可能失效的条件\n",
        "- 指数增长模型在长期不适用（无容量约束）；超过 2030 年的预测不可靠。",
        "- 政策Δr 为外生假设，未建模生育决策的微观行为机制（如收入/教育/住房影响）。"
        "如需行为因果推断，需要微观调查数据（CFPS/CGSS）和结构模型。",
        "- COVID 冲击等外生突发事件不在模型中。",
        f"- 极端边界（r=-0.005，COVID 持续冲击）：2027 年人口 = "
        f"{policy_data.get('failure_scenario', {}).get('trajectory', [{}])[-1].get('population', 0)/1e6:.1f}M"
        "（负增长加速），所有激励方案效果归零。",
        "\n## 6. 后续需观测的指标\n",
        "- 年度出生人口和总和生育率（政策效果的直接验证指标）",
        "- 政策实际财政支出（验证成本假设）",
        "- 生育意愿调查（机制传导验证）",
        "\n## 7. 因果声明边界\n",
        "本报告的「政策效果」是模型内反事实比较（改变增长率参数），"
        "不构成现实因果识别。模型内因果 ≠ 现实因果：实际政策的"
        "行为响应、实施延迟、覆盖率和遵从率均未建模。",
        "\n## 8. 复现信息\n",
        f"- 校准结果：{use_case_data.get('requirement', {}).get('requirement_id', '见归档')}",
        "- 采集任务ID与哈希：见 data/collection/sources_matrix.json",
        "- 模型代码/参数/数据版本：见 data/collection/usecase2_policy.json",
    ]

    text = "\n".join(lines)
    output_dir = output_dir or REPORTS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "report_C_policy_brief.md"
    path.write_text(text, encoding="utf-8")
    return str(path)


# 别名兼容
registry_STATE_ZH = dict(
    live="真实采集可用", needs_auth="需凭据", down="暂不可用",
    candidate="候选", configured="已配置", catalog_only="仅目录",
    restricted="需申请", na="不适用")

# 用例2的2022留出实际值（供简报引用）
all_data = {"holdout_actual": "1,412,175,000（世界银行估算，留出集）"}
