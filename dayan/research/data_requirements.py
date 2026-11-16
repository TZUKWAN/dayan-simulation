"""DataRequirement / CollectionPlan：数据需求与采集计划的版本化规约。

任务书 §四.1：不能只把用户原文塞进"研究问题"字符串——每个必需变量须有
概念定义、同义词、单位、时间频率、地域粒度、群体分组、目标用途、可接受来源与替代口径。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
import uuid

# 目标用途（§四.1；用于后续数据角色泄漏检查）
PURPOSES = ("initialization", "exogenous_input", "mechanism_estimation",
            "calibration", "holdout_validation", "text_evidence", "background")
# 地域粒度层级（从粗到细；实际能力必须与此匹配，不得虚标）
GEO_LEVELS = ("national", "province", "city", "district", "community", "individual")


@dataclass
class DataVariable:
    """一个必需数据变量。"""
    name: str = ""               # 变量名（模型侧参数/字段）；缺名由 validate 拦截
    concept: str = ""            # 概念定义（口径，非模型名）
    synonyms: list = field(default_factory=list)  # 同义词（用于源检索）
    unit: str = ""               # 单位（如 万人、％、元、人/平方公里）
    base_year: str = ""          # 价格基年（名义/实际金额时必填）
    frequency: str = "annual"    # 时间频率：annual/quarterly/monthly/daily
    geo_level: str = "national"  # 地域粒度
    groups: list = field(default_factory=list)     # 群体分组维度（性别/年龄/城乡…）
    purpose: str = "initialization"  # PURPOSes 之一
    preferred_sources: list = field(default_factory=list)  # 首选 source_id
    alt_sources: list = field(default_factory=list)        # 替代来源
    alt_concepts: list = field(default_factory=list)       # 可接受替代口径（须声明）
    coverage_gaps: list = field(default_factory=list)       # 已知覆盖缺口
    min_records: int = 3       # 至少需要的记录数（时间点/地区数）
    time_range: str = ""       # 期望时间范围 如 2018:2024

    def validate(self) -> list[str]:
        issues = []
        if not self.name:
            issues.append("缺 name")
        if not self.concept:
            issues.append(f"{self.name}: 缺概念定义（不能只给变量名）")
        if not self.unit:
            issues.append(f"{self.name}: 缺单位")
        if self.purpose not in PURPOSES:
            issues.append(f"{self.name}: purpose 非法 {self.purpose}")
        if self.geo_level not in GEO_LEVELS:
            issues.append(f"{self.name}: geo_level 非法 {self.geo_level}")
        if ("元" in self.unit or "¥" in self.unit or "USD" in self.unit) and not self.base_year:
            issues.append(f"{self.name}: 金额变量须声明价格基年（名义/实际）")
        return issues


@dataclass
class DataRequirement:
    """完整数据需求规约（版本化）。"""
    requirement_id: str = ""
    version: int = 1
    created_at: str = ""
    research_id: str = ""
    question: str = ""           # 研究问题原文（辅助理解，不是唯一规约）
    population: str = ""         # 目标人群/抽样总体
    geo_scope: str = ""          # 地域范围
    time_scope: str = ""         # 时间范围
    analysis_level: str = "national"  # 分析层级
    variables: list = field(default_factory=list)   # [DataVariable]
    notes: list = field(default_factory=list)
    # 三类假设区分（任务书 §四.1）
    user_set: list = field(default_factory=list)      # 用户明确设定
    data_estimated: list = field(default_factory=list) # 由资料估计
    literature_borrowed: list = field(default_factory=list)  # 文献迁移
    unknown_assumptions: list = field(default_factory=list)  # 未知/待补

    def finalize(self):
        if not self.requirement_id:
            self.requirement_id = "DR-" + uuid.uuid4().hex[:8]
        if not self.created_at:
            self.created_at = datetime.now().isoformat(timespec="seconds")
        return self

    def validate(self) -> list[str]:
        issues = []
        if not self.variables:
            issues.append("无必需数据变量")
        for v in self.variables:
            issues.extend(v.validate())
        if self.purpose_of() == "prediction" and \
                not any(v.purpose == "holdout_validation" for v in self.variables):
            issues.append("预测用途须含 holdout_validation 角色")
        return issues

    def purpose_of(self) -> str:
        return "policy" if any(v.purpose == "calibration" for v in self.variables) else "mechanism"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DataRequirement":
        known = set(cls.__dataclass_fields__)
        obj = cls(**{k: v for k, v in d.items() if k in known})
        obj.variables = [DataVariable(**v) for v in d.get("variables", [])]
        return obj


@dataclass
class CollectionPlanStep:
    """一步采集：连接器+参数（由 DataRequirement 自动生成或人工指定）。"""
    step_id: str
    connector: str
    params: dict
    source_id: str
    variable_name: str          # 对应 DataVariable.name
    purpose: str
    page_budget: int = 2
    status: str = "pending"     # pending/done/partial/failed/skipped
    collection_id: str = ""
    n_records: int = 0
    error: str = ""


@dataclass
class CollectionPlan:
    """采集计划：从 DataRequirement 到连接器参数的映射（可执行、可审计）。"""
    plan_id: str = ""
    requirement_id: str = ""
    created_at: str = ""
    steps: list = field(default_factory=list)

    def finalize(self):
        if not self.plan_id:
            self.plan_id = "CP-" + uuid.uuid4().hex[:8]
        if not self.created_at:
            self.created_at = datetime.now().isoformat(timespec="seconds")
        return self

    def to_dict(self) -> dict:
        return {"plan_id": self.plan_id, "requirement_id": self.requirement_id,
                "created_at": self.created_at,
                "steps": [asdict(s) for s in self.steps]}

    def summary(self) -> dict:
        by_status = {}
        for s in self.steps:
            by_status[s.status] = by_status.get(s.status, 0) + 1
        return {"plan_id": self.plan_id, "n_steps": len(self.steps),
                "status": by_status,
                "total_records": sum(s.n_records for s in self.steps)}


# ---------- 自动计划生成（§3.4：基于 DataRequirement 生成有限额的 CollectionPlan） ----------
# 概念词→连接器+参数模板 的映射表（可扩展，不硬编码展示结果）
CONCEPT_ROUTES = {
    # 人口与就业
    "人口总量": {"connector": "worldbank", "indicator": "SP.POP.TOTL", "source": "wb_indicators"},
    "城镇人口占比": {"connector": "worldbank", "indicator": "SP.URB.TOTL.IN.ZS", "source": "wb_indicators"},
    "老龄化": {"connector": "worldbank", "indicator": "SP.POP.65UP.TO.ZS", "source": "wb_indicators"},
    "失业率": {"connector": "worldbank", "indicator": "SL.UEM.TOTL.ZS", "source": "wb_indicators"},
    "出生率": {"connector": "worldbank", "indicator": "SP.DYN.CBRT.IN", "source": "wb_indicators"},
    "死亡率": {"connector": "worldbank", "indicator": "SP.DYN.CDRT.IN", "source": "wb_indicators"},
    "生育率": {"connector": "worldbank", "indicator": "SP.DYN.TFRT.IN", "source": "wb_indicators"},
    "劳动力参与": {"connector": "worldbank", "indicator": "SL.TLF.CACT.ZS", "source": "wb_indicators"},
    
    # 经济
    "人均GDP": {"connector": "worldbank", "indicator": "NY.GDP.PCAP.CD", "source": "wb_indicators"},
    "GDP总量": {"connector": "worldbank", "indicator": "NY.GDP.MKTP.CD", "source": "wb_indicators"},
    "GDP增速": {"connector": "worldbank", "indicator": "NY.GDP.MKTP.KD.ZG", "source": "wb_indicators"},
    "通胀率": {"connector": "worldbank", "indicator": "FP.CPI.TOTL.ZG", "source": "wb_indicators"},
    "政府债务": {"connector": "worldbank", "indicator": "GC.DOD.TOTL.GD.ZS", "source": "wb_indicators"},
    "贸易总额": {"connector": "worldbank", "indicator": "NE.TRD.GNFS.ZS", "source": "wb_indicators"},
    "外国投资": {"connector": "worldbank", "indicator": "BX.KLT.DINV.CD.WD", "source": "wb_indicators"},
    # 教育
    "教育支出": {"connector": "worldbank", "indicator": "SE.XPD.TOTL.GD.ZS", "source": "wb_indicators"},
    "成人识字率": {"connector": "worldbank", "indicator": "SE.ADT.LITR.ZS", "source": "wb_indicators"},
    "小学师生比": {"connector": "worldbank", "indicator": "SE.PRM.ENRL.TC.ZS", "source": "wb_indicators"},
    "教育数据": {"connector": "web_page", "source": "cn_nbs_bulletin",
                  "url": "https://www.stats.gov.cn/sj/zxfb/202602/t20260228_1962662.html",
                  "keywords": ["教育", "学校", "入学", "教师", "研究生"]},
    # 卫生
    "公共卫生": {"connector": "who_gho", "indicator": "WHOSIS_000001", "source": "who_gho"},
    "五岁以下死亡率": {"connector": "who_gho", "indicator": "MORT_1", "source": "who_gho"},
    "卫生支出": {"connector": "who_gho", "indicator": "GHED_CHEXP1", "source": "who_gho"},
    "医务人员": {"connector": "who_gho", "indicator": "HWFH_6", "source": "who_gho"},
    # 环境
    "碳排放": {"connector": "worldbank", "indicator": "EN.ATM.CO2E.PC", "source": "wb_indicators"},
    "能源消耗": {"connector": "worldbank", "indicator": "EG.USE.PCAP.KG.OE", "source": "wb_indicators"},
    "可再生能源": {"connector": "worldbank", "indicator": "EG.FEC.RNEW.ZS", "source": "wb_indicators"},
    "森林面积": {"connector": "worldbank", "indicator": "AG.LND.FRST.ZS", "source": "wb_indicators"},
    "PM2.5": {"connector": "worldbank", "indicator": "EN.ATM.PM25.MC.M3", "source": "wb_indicators"},
    # 交通
    "交通数据": {"connector": "web_page", "source": "cn_nbs_bulletin",
                  "url": "https://www.stats.gov.cn/sj/zxfb/202602/t20260228_1962662.html",
                  "keywords": ["交通", "铁路", "公路", "民航", "旅客", "货物"]},
    "航空客运": {"connector": "worldbank", "indicator": "IS.AIR.PSGR", "source": "wb_indicators"},
    # 住房
    "住房数据": {"connector": "web_page", "source": "cn_nbs_bulletin",
                  "url": "https://www.stats.gov.cn/sj/zxfb/202602/t20260228_1962662.html",
                  "keywords": ["房地产", "住宅", "商品房", "住房", "房价"]},
    # 社会
    "SDG失业": {"connector": "unsdg", "indicator": "8-5-2", "source": "unsdg"},
    "SDG贫困": {"connector": "unsdg", "indicator": "1-1-1", "source": "unsdg"},
    "SDG教育": {"connector": "unsdg", "indicator": "4-1-1", "source": "unsdg"},
    "SDG性别": {"connector": "unsdg", "indicator": "5-5-1", "source": "unsdg"},
    "统计公报": {"connector": "web_page", "source": "cn_nbs_bulletin"},
    "民政统计": {"connector": "web_page", "source": "cn_mca_stats"},
    "学术文献": {"connector": "crossref", "source": "crossref"},
    "文献": {"connector": "openalex", "source": "openalex"},
    "新闻事件": {"connector": "gdelt_doc", "source": "gdelt"},
    "历史实体": {"connector": "wikidata_sparql", "source": "wikidata"},
    "开放数据集": {"connector": "huggingface_datasets", "source": "huggingface"},
}


def build_plan(req: DataRequirement) -> CollectionPlan:
    """从 DataRequirement 自动生成采集计划（首匹配路由，后续可人工调整）。"""
    plan = CollectionPlan(requirement_id=req.requirement_id)
    for i, v in enumerate(req.variables):
        route = None
        for key in [v.concept, *v.synonyms]:
            if key in CONCEPT_ROUTES:
                route = CONCEPT_ROUTES[key]
                break
        if route is None:
            plan.steps.append(CollectionPlanStep(
                step_id=f"S{i+1}", connector="(无匹配路由)", params={},
                source_id="", variable_name=v.name, purpose=v.purpose,
                status="skipped", error="无精确统计口径路由，需明确来源和映射"))
            continue
        from .request_contract import country_code, year_range
        params = {"indicator": route.get("indicator", "")}
        try:
            if v.frequency != "annual" or v.geo_level != "national" or v.groups:
                raise ValueError("当前路由不支持所需时间频率、地域层级或分组；须选择对应维度连接器")
            if route["connector"] == "worldbank":
                params["country"] = country_code(req.geo_scope)
                params["date"] = year_range(v.time_range or req.time_scope)
            elif route["connector"] in ("unsdg", "who_gho", "web_page", "huggingface_datasets"):
                raise ValueError("此来源须指定并核验实际地区、年份和资源参数，不能静默忽略需求")
            elif route["connector"] in ("crossref", "openalex", "gdelt_doc", "wikidata_sparql"):
                raise ValueError("须明确检索式与时间/范围过滤参数，不能用默认检索代替")
        except ValueError as exc:
            plan.steps.append(CollectionPlanStep(step_id=f"S{i+1}", connector=route["connector"],
                params={}, source_id=route["source"], variable_name=v.name,
                purpose=v.purpose, status="skipped", error=str(exc)))
            continue
        plan.steps.append(CollectionPlanStep(
            step_id=f"S{i+1}", connector=route["connector"], params=params,
            source_id=route["source"], variable_name=v.name, purpose=v.purpose))
    plan.finalize()
    return plan
