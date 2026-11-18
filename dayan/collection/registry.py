"""来源注册表：版本化来源定义 + 证据状态机 + 真实探测记录。

状态口径（任务书 §3.1，从弱到强）：
  candidate      候选待核验：仅有名称/入口，未发真实请求
  catalog_only   仅目录可检索：抓到过目录/页面元数据，未下载到数据
  configured     采集器已配置但未验证：连接器已实现，未跑真实查询
  live           真实采集可用：本机真实请求拿到过非空数据（附 collection_id）
  needs_auth     需免费凭据/注册：官方要求注册或申请，未冒充可用
  restricted     需登记/申请/受限字段：有明确条件，登记入口与引导
  down           临时不可用：请求失败/迁移，留失败证据，待复查
  na             条款不适用：许可/范围不符合本项目使用，明确排除

本模块只管"来源"这一层；数据集目录与采集任务在 engine/presets。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # dayan/collection/ → 工程根
STATE_PATH = Path(os.environ.get("DAYAN_DATA_DIR", ROOT / "data")) / "collection" / "sources.json"

# 证据状态与允许的迁移（只许变强或如实降级，不许把弱状态标成强状态）
STATES = ("candidate", "catalog_only", "configured", "live",
          "needs_auth", "restricted", "down", "na")
STATE_ZH = {"candidate": "候选待核验", "catalog_only": "仅目录可检索",
            "configured": "已配置未验证", "live": "真实采集可用",
            "needs_auth": "需免费凭据/注册", "restricted": "需登记/申请/受限",
            "down": "暂不可用", "na": "条款不适用"}

# 类别（任务书 §3.2 A-H）
CATS = {"A": "中国官方统计与普查", "B": "中国公共数据与政策",
        "C": "国际人口与社会经济", "D": "家庭与社会态度调查",
        "E": "开放研究仓储与文献", "F": "空间设施与流动",
        "G": "文本新闻事件历史文化", "H": "通用开放平台"}

# 版本化来源定义（source_id 稳定；改动走 rev 字段）
SOURCES = [
    # ---- A 中国官方统计与普查 ----
    {"source_id": "cn_nbs_data", "cat": "A", "name": "国家统计局·数据发布库",
     "org": "国家统计局", "entry": "https://data.stats.gov.cn/",
     "doc": "2026升级公告 https://www.stats.gov.cn/xw/tjxw/tzgg/202603/t20260325_1962844.html",
     "topics": ["人口", "就业", "GDP", "教育", "财政"], "lang": "zh", "geo": "CN",
     "granularity": "全国/省/地市，年/季/月", "auth": "无（公开查询）",
     "license": "政府公开统计资料，使用需遵守统计局条款", "rate_limit": "未知，需实测",
     "mode": ["structured_api", "web_page"], "rev": 1},
    {"source_id": "cn_nbs_bulletin", "cat": "A", "name": "国家统计局·统计公报与年鉴",
     "org": "国家统计局", "entry": "https://www.stats.gov.cn/sj/tjgb/ndtjgb/",
     "topics": ["人口", "就业", "GDP"], "lang": "zh", "geo": "CN",
     "granularity": "全国，年", "auth": "无", "license": "政府公开",
     "mode": ["web_page", "pdf_table"], "rev": 1},
    {"source_id": "cn_gov_policy", "cat": "B", "name": "国务院政策文件库",
     "org": "中国政府网", "entry": "https://sousuo.www.gov.cn/zcwjk/",
     "topics": ["政策文件", "公报"], "lang": "zh", "geo": "CN",
     "granularity": "国家，文件级", "auth": "无（公开检索）",
     "license": "政府公开文件", "mode": ["web_page"], "rev": 1},
    {"source_id": "cn_data_sh", "cat": "B", "name": "上海公共数据开放平台",
     "org": "上海市大数据中心", "entry": "https://data.sh.gov.cn/",
     "topics": ["公共服务", "交通", "卫生", "经济"], "lang": "zh", "geo": "CN-上海",
     "granularity": "市/区，数据集级", "auth": "下载/API权限逐资源核实",
     "license": "逐数据集标注", "mode": ["open_portal"], "rev": 1},
    {"source_id": "cn_data_beijing", "cat": "B", "name": "北京市公共数据开放平台",
     "org": "北京市经信局", "entry": "https://data.beijing.gov.cn/",
     "topics": ["公共服务", "交通", "教育"], "lang": "zh", "geo": "CN-北京",
     "granularity": "市/区，数据集级", "auth": "逐资源核实",
     "license": "逐数据集标注", "mode": ["open_portal"], "rev": 1},
    {"source_id": "cn_moe_stats", "cat": "A", "name": "教育部·教育统计（公报/表格）",
     "org": "教育部", "entry": "http://www.moe.gov.cn/jyb_sjzl/",
     "topics": ["教育"], "lang": "zh", "geo": "CN",
     "granularity": "全国/省，年", "auth": "无", "license": "政府公开",
     "mode": ["web_page", "pdf_table"], "rev": 1},
    {"source_id": "cn_mca_stats", "cat": "A", "name": "民政部·统计公报",
     "org": "民政部", "entry": "https://www.mca.gov.cn/n156/n2679/index.html",
     "topics": ["社会保障", "社会组织", "养老"], "lang": "zh", "geo": "CN",
     "granularity": "全国/省，年/季", "auth": "无", "license": "政府公开",
     "mode": ["web_page", "pdf_table"], "rev": 1},
    # ---- C 国际人口与社会经济 ----
    {"source_id": "wb_indicators", "cat": "C", "name": "World Bank Indicators API v2",
     "org": "World Bank", "entry": "https://api.worldbank.org/v2/",
     "doc": "https://datahelpdesk.worldbank.org/knowledgebase/articles/889392",
     "topics": ["人口", "就业", "教育", "卫生", "经济"], "lang": "en", "geo": "全球+各国",
     "granularity": "国家/聚合，年", "auth": "无", "license": "CC BY 4.0",
     "rate_limit": "礼貌限速，分页 per_page≤50000", "mode": ["structured_api"], "rev": 1},
    {"source_id": "wb_data360", "cat": "C", "name": "World Bank Data360 · WDI",
     "org": "World Bank", "entry": "https://data360api.worldbank.org/data360/data",
     "doc": "https://data360.worldbank.org/en/api", "topics": ["就业", "失业率"], "lang": "en", "geo": "各国",
     "granularity": "国家年度，ILO模型估计总失业率", "auth": "无", "license": "CC BY 4.0",
     "mode": ["structured_api"], "rev": 1},
    {"source_id": "eurostat", "cat": "C", "name": "Eurostat 统计 API（JSON-stat）",
     "org": "欧盟统计局", "entry": "https://ec.europa.eu/eurostat/api/dissemination/",
     "doc": "https://ec.europa.eu/eurostat/en/web/user-guides/data-browser/api-data-access/api-introduction",
     "topics": ["人口", "就业", "教育", "卫生", "区域"], "lang": "en", "geo": "EU+候选国",
     "granularity": "国家/NUTS，年/季/月", "auth": "无", "license": "CC BY 4.0",
     "rate_limit": "有限流，需礼貌使用", "mode": ["structured_api", "sdmx"], "rev": 1},
    {"source_id": "unsdg", "cat": "C", "name": "UN SDG 指标 API",
     "org": "UN Statistics Division", "entry": "https://unstats.un.org/SDGAPI/v1/",
     "doc": "https://unstats.un.org/SDGAPI/swagger/",
     "topics": ["SDG指标", "人口", "卫生", "教育"], "lang": "en", "geo": "全球+国家",
     "granularity": "国家，年", "auth": "无", "license": "UN公开",
     "rate_limit": "分页 pageSize≤", "mode": ["structured_api"], "rev": 1},
    {"source_id": "ilostat_bulk", "cat": "C", "name": "ILOSTAT 批量/指标 CSV",
     "org": "国际劳工组织", "entry": "https://ilostat.ilo.org/data/bulk/",
     "topics": ["就业", "失业", "劳动收入"], "lang": "en", "geo": "全球+国家",
     "granularity": "国家，年/季", "auth": "无", "license": "ILO公开（注明出处）",
     "rate_limit": "批量文件较大，按指标取", "mode": ["bulk_file"], "rev": 1},
    {"source_id": "who_gho", "cat": "C", "name": "WHO GHO OData API",
     "org": "WHO", "entry": "https://ghoapi.azureedge.net/api/",
     "topics": ["卫生"], "lang": "en", "geo": "全球+国家",
     "granularity": "国家，年", "auth": "无", "license": "WHO公开",
     "mode": ["structured_api"], "rev": 1},
    {"source_id": "unesco_uis", "cat": "C", "name": "UNESCO UIS API",
     "org": "UNESCO 统计所", "entry": "https://api.uis.unesco.org/api/public/",
     "topics": ["教育", "科技", "文化"], "lang": "en", "geo": "全球+国家",
     "granularity": "国家，年", "auth": "无", "license": "CC BY 4.0",
     "mode": ["structured_api"], "rev": 1},
    {"source_id": "us_census", "cat": "C", "name": "US Census API",
     "org": "美国普查局", "entry": "https://api.census.gov/data.html",
     "topics": ["人口", "收入", "住房"], "lang": "en", "geo": "US 国家/州/县",
     "granularity": "州/县/ tract，年", "auth": "无key可少量查询（>500/日需免费key）",
     "license": "美国政府公开", "mode": ["structured_api"], "rev": 1},
    {"source_id": "oecd_sdmx", "cat": "C", "name": "OECD SDMX API",
     "org": "OECD", "entry": "https://sdmx.oecd.org/public/rest/",
     "doc": "https://www.oecd.org/en/data/insights/data-explainers/2024/09/api.html",
     "topics": ["经济", "就业", "教育"], "lang": "en", "geo": "OECD+伙伴国",
     "granularity": "国家，年/季/月", "auth": "无", "license": "OECD公开（注明）",
     "rate_limit": "有访问条件与限流", "mode": ["sdmx"], "rev": 1},
    # ---- D 家庭与社会态度调查 ----
    {"source_id": "cfps", "cat": "D", "name": "中国家庭追踪调查 CFPS",
     "org": "北京大学 ISSS", "entry": "https://www.isss.pku.edu.cn/cfps/",
     "topics": ["家庭", "收入", "教育", "健康"], "lang": "zh", "geo": "CN",
     "granularity": "个体/家庭微观，双年波次", "auth": "需注册（免费）",
     "license": "学术使用协议", "mode": ["survey_micro"], "rev": 1},
    {"source_id": "cgss", "cat": "D", "name": "中国综合社会调查 CGSS",
     "org": "中国人民大学", "entry": "http://cgss.ruc.edu.cn/",
     "topics": ["社会态度", "治理", "健康"], "lang": "zh", "geo": "CN",
     "granularity": "个体微观，年波次", "auth": "需申请",
     "license": "学术使用协议", "mode": ["survey_micro"], "rev": 1},
    {"source_id": "charls", "cat": "D", "name": "中国健康与养老追踪调查 CHARLS",
     "org": "北京大学", "entry": "https://charls.charlsdata.com/",
     "topics": ["养老", "健康", "家庭"], "lang": "zh", "geo": "CN",
     "granularity": "个体/家庭微观", "auth": "需注册（免费）",
     "license": "学术使用协议", "mode": ["survey_micro"], "rev": 1},
    {"source_id": "chfs", "cat": "D", "name": "中国家庭金融调查 CHFS",
     "org": "西南财经大学", "entry": "https://chfs.swufe.edu.cn/",
     "topics": ["家庭金融", "收入"], "lang": "zh", "geo": "CN",
     "granularity": "个体/家庭微观", "auth": "需注册/申请",
     "license": "学术使用协议", "mode": ["survey_micro"], "rev": 1},
    {"source_id": "wvs", "cat": "D", "name": "世界价值观调查 WVS",
     "org": "WVS Association", "entry": "https://www.worldvaluessurvey.org/",
     "topics": ["价值观", "社会态度"], "lang": "en", "geo": "全球+国家",
     "granularity": "个体微观，波次", "auth": "需注册（免费）",
     "license": "学术使用，逐波次条款", "mode": ["survey_micro"], "rev": 1},
    {"source_id": "ess", "cat": "D", "name": "European Social Survey ESS",
     "org": "ESS ERIC", "entry": "https://www.europeansocialsurvey.org/",
     "topics": ["社会态度"], "lang": "en", "geo": "欧洲",
     "granularity": "个体微观", "auth": "需注册（免费）",
     "license": "学术使用", "mode": ["survey_micro"], "rev": 1},
    {"source_id": "gss_us", "cat": "D", "name": "美国综合社会调查 GSS",
     "org": "NORC", "entry": "https://gssdataexplorer.norc.org/",
     "topics": ["社会态度"], "lang": "en", "geo": "US",
     "granularity": "个体微观", "auth": "免费提取（部分免登录）",
     "license": "公开学术使用", "mode": ["survey_micro"], "rev": 1},
    # ---- E 开放研究仓储与文献 ----
    {"source_id": "crossref", "cat": "E", "name": "Crossref REST API",
     "org": "Crossref", "entry": "https://api.crossref.org/",
     "doc": "https://www.crossref.org/documentation/retrieve-metadata/rest-api/",
     "topics": ["文献元数据", "DOI"], "lang": "en", "geo": "全球",
     "granularity": "论文级", "auth": "无（polite pool 建议 mailto）",
     "license": "元数据开放", "rate_limit": "Mono pool 50/s", "mode": ["literature_api"], "rev": 1},
    {"source_id": "openalex", "cat": "E", "name": "OpenAlex API",
     "org": "OurResearch", "entry": "https://api.openalex.org/",
     "topics": ["文献", "作者", "机构"], "lang": "en", "geo": "全球",
     "granularity": "论文级", "auth": "无（mailto 进 polite pool；额度见当日文档）",
     "license": "CC0", "mode": ["literature_api"], "rev": 1},
    {"source_id": "datacite", "cat": "E", "name": "DataCite API",
     "org": "DataCite", "entry": "https://api.datacite.org/",
     "topics": ["数据集DOI"], "lang": "en", "geo": "全球",
     "granularity": "数据集级", "auth": "无", "license": "元数据开放",
     "mode": ["literature_api"], "rev": 1},
    {"source_id": "zenodo", "cat": "E", "name": "Zenodo REST API",
     "org": "CERN", "entry": "https://zenodo.org/api/",
     "topics": ["开放数据集", "预印本"], "lang": "en", "geo": "全球",
     "granularity": "记录级（含文件）", "auth": "无（公开记录）",
     "license": "逐记录标注", "mode": ["open_portal"], "rev": 1},
    {"source_id": "dataverse", "cat": "E", "name": "Dataverse API（Harvard/实例通用）",
     "org": "Dataverse Project", "entry": "https://dataverse.harvard.edu/",
     "doc": "https://guides.dataverse.org/en/latest/api/dataaccess.html",
     "topics": ["研究数据"], "lang": "en", "geo": "全球",
     "granularity": "Dataset/文件级", "auth": "公开部分无；ICPSR等受限",
     "license": "逐数据集", "mode": ["open_portal"], "rev": 1},
    # ---- F 空间设施与流动 ----
    {"source_id": "osm_overpass", "cat": "F", "name": "OpenStreetMap Overpass",
     "org": "OSM 社区", "entry": "https://overpass-api.de/",
     "topics": ["道路", "设施", "POI"], "lang": "en", "geo": "全球",
     "granularity": "要素级", "auth": "无", "license": "ODbL-1.0",
     "rate_limit": "公共实例有限流", "mode": ["geo_api"], "rev": 1},
    {"source_id": "hdx", "cat": "F", "name": "UN OCHA Humanitarian Data Exchange",
     "org": "UN OCHA", "entry": "https://data.humdata.org/",
     "topics": ["人口", "灾害", "行政边界"], "lang": "en", "geo": "全球（发展中国家多）",
     "granularity": "数据集级（CKAN）", "auth": "无", "license": "逐数据集",
     "mode": ["open_portal"], "rev": 1},
    {"source_id": "worldpop", "cat": "F", "name": "WorldPop 人口网格",
     "org": "WorldPop", "entry": "https://www.worldpop.org/",
     "topics": ["人口栅格"], "lang": "en", "geo": "全球",
     "granularity": "100m/1km 栅格，年", "auth": "无", "license": "CC BY 4.0",
     "mode": ["bulk_file"], "rev": 1},
    # ---- G 文本新闻事件历史文化 ----
    {"source_id": "gdelt", "cat": "G", "name": "GDELT 2.0 文档 API",
     "org": "GDELT Project", "entry": "https://api.gdeltproject.org/api/v2/doc/",
     "doc": "https://www.gdeltproject.org/data.html",
     "topics": ["新闻事件"], "lang": "en", "geo": "全球",
     "granularity": "文章级，15分钟窗", "auth": "无",
     "license": "GDELT 公开（原始出处为准）", "rate_limit": "有速率限制",
     "mode": ["text_api"], "rev": 1},
    {"source_id": "wikidata", "cat": "G", "name": "Wikidata SPARQL",
     "org": "Wikimedia", "entry": "https://query.wikidata.org/",
     "doc": "https://www.wikidata.org/wiki/Wikidata:Data_access",
     "topics": ["实体", "历史", "文化"], "lang": "多语", "geo": "全球",
     "granularity": "实体级", "auth": "无", "license": "CC0",
     "rate_limit": "公共端点限流，UA 必须", "mode": ["text_api"], "rev": 1},
    {"source_id": "wikipedia_pageviews", "cat": "G", "name": "Wikimedia Pageviews API",
     "org": "Wikimedia", "entry": "https://wikimedia.org/api/rest_v1/",
     "topics": ["公众关注（代理）"], "lang": "多语", "geo": "全球",
     "granularity": "页面/日", "auth": "无", "license": "CC0",
     "mode": ["text_api"], "rev": 1},
    # ---- H 通用开放平台 ----
    {"source_id": "socrata", "cat": "H", "name": "Socrata 开放数据平台（多城市/州）",
     "org": "Tyler Technologies", "entry": "https://dev.socrata.com/",
     "doc": "https://dev.socrata.com/consumers/getting-started.html",
     "topics": ["公共服务", "交通", "卫生"], "lang": "en", "geo": "北美为主",
     "granularity": "记录级", "auth": "无（app_token 可选）",
     "license": "逐数据集", "mode": ["open_portal"], "rev": 1},
    {"source_id": "ckan_uk", "cat": "H", "name": "UK data.gov.uk（CKAN）",
     "org": "GDS", "entry": "https://data.gov.uk/",
     "topics": ["公共服务", "经济", "环境"], "lang": "en", "geo": "UK",
     "granularity": "数据集级（CKAN API）", "auth": "无", "license": "逐数据集",
     "mode": ["open_portal"], "rev": 1},
    {"source_id": "datagov_us", "cat": "H", "name": "data.gov（DCAT catalog）",
     "org": "美国 GSA", "entry": "https://catalog.data.gov/",
     "topics": ["全域"], "lang": "en", "geo": "US",
     "granularity": "数据集目录", "auth": "无", "license": "逐数据集",
     "mode": ["open_portal"], "rev": 1},
    # ---- 刘总补充：通用开放平台/国内免费来源（2026-11-13） ----
    {"source_id": "huggingface", "cat": "H", "name": "Hugging Face Datasets API",
     "org": "Hugging Face", "entry": "https://huggingface.co/api/datasets",
     "topics": ["NLP语料", "社会科学数据集", "表格数据"], "lang": "多语", "geo": "全球",
     "granularity": "数据集级（公开仓库免key）", "auth": "公开仓库无；部分数据集需gate同意",
     "license": "逐数据集标注（含CC/专有）", "rate_limit": "公开API有速率限制",
     "mode": ["open_portal"], "rev": 1},
    {"source_id": "kaggle", "cat": "H", "name": "Kaggle Datasets",
     "org": "Kaggle (Google)", "entry": "https://www.kaggle.com/datasets",
     "topics": ["表格", "社会", "经济", "NLP"], "lang": "en/多语", "geo": "全球",
     "granularity": "数据集级", "auth": "下载需免费账号+API token",
     "license": "逐数据集", "mode": ["bulk_file"], "rev": 1},
    {"source_id": "cn_tianchi", "cat": "H", "name": "阿里云天池数据集",
     "org": "阿里云", "entry": "https://tianchi.aliyun.com/dataset",
     "topics": ["城市交通", "消费", "金融", "气象"], "lang": "zh", "geo": "CN为主",
     "granularity": "数据集级", "auth": "下载需登录（免费）",
     "license": "逐数据集（多为研究授权）", "mode": ["bulk_file"], "rev": 1},
    {"source_id": "cn_aistudio", "cat": "H", "name": "百度飞桨AI Studio数据集",
     "org": "百度", "entry": "https://aistudio.baidu.com/datasetoverview",
     "topics": ["视觉", "文本", "城市"], "lang": "zh", "geo": "CN为主",
     "granularity": "数据集级", "auth": "下载需登录（免费）",
     "license": "逐数据集", "mode": ["bulk_file"], "rev": 1},
    {"source_id": "cn_cma", "cat": "A", "name": "国家气象科学数据中心",
     "org": "中国气象局", "entry": "https://data.cma.cn/",
     "topics": ["气象观测", "气候"], "lang": "zh", "geo": "CN",
     "granularity": "站点/格点，时/日/月", "auth": "部分免费，下载需注册",
     "license": "气象数据使用协议", "mode": ["structured_api", "bulk_file"], "rev": 1},
    {"source_id": "cn_nesdc", "cat": "A", "name": "国家生态科学数据中心",
     "org": "中国科学院", "entry": "https://www.nesdc.org.cn/",
     "topics": ["生态", "环境", "遥感"], "lang": "zh", "geo": "CN",
     "granularity": "站点/流域/格点", "auth": "部分免费，下载需注册",
     "license": "逐数据集", "mode": ["open_portal"], "rev": 1},
    {"source_id": "cn_webmap", "cat": "F", "name": "全国地理信息资源目录（1:100万）",
     "org": "国家基础地理信息中心", "entry": "https://www.webmap.cn/",
     "topics": ["行政边界", "道路", "水系"], "lang": "zh", "geo": "CN",
     "granularity": "图层级", "auth": "免费下载需注册",
     "license": "测绘地理信息成果使用协议", "mode": ["bulk_file"], "rev": 1},
    {"source_id": "cn_ncmi", "cat": "A", "name": "国家人口健康科学数据中心",
     "org": "中国医学科学院", "entry": "https://www.ncmi.cn/",
     "topics": ["健康", "医疗资源"], "lang": "zh", "geo": "CN",
     "granularity": "数据集/统计级", "auth": "部分公开，下载需注册",
     "license": "逐数据集", "mode": ["open_portal"], "rev": 1},
    {"source_id": "gesis", "cat": "D", "name": "GESIS 数据归档（ISSP/ESS 下载）",
     "org": "GESIS Leibniz", "entry": "https://data.gesis.org/",
     "topics": ["调查微观"], "lang": "en", "geo": "全球",
     "granularity": "研究级（SAV/DTA+码本）", "auth": "需注册（免费）",
     "license": "学术条款", "mode": ["survey_micro"], "rev": 1},
]


def state_file() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"version": 1, "sources": {}}


def save_state(state: dict) -> None:
    from .storage import atomic_json
    atomic_json(STATE_PATH, state)


def definitions() -> list[dict]:
    """来源定义（静态部分），按类别排序。"""
    return sorted(SOURCES, key=lambda s: (s["cat"], s["source_id"]))


def runtime_state() -> dict:
    """source_id → 证据状态（live/configured/…、last_checked、probe、collections）。"""
    return state_file().get("sources", {})


def matrix() -> list[dict]:
    """可行性矩阵：定义 × 运行证据 合并视图。"""
    rt = runtime_state()
    rows = []
    for d in definitions():
        r = rt.get(d["source_id"], {})
        state = r.get("state", "candidate")
        evidence = r.get("evidence", [])
        if state == "live" and evidence and all(e.get("mode") in ("huggingface_datasets", "ckan_search") for e in evidence):
            state = "catalog_only"
        if state == "live" and d["source_id"] == "cn_mca_stats" and not any(e.get("artifact_role") in ("dataset", "text_evidence") for e in evidence):
            state = "catalog_only"
        rows.append({**d, "state": state, "state_zh": STATE_ZH[state],
                     "last_checked": r.get("last_checked"),
                     "probe_summary": r.get("probe_summary"),
                     "evidence": r.get("evidence", []),
                     "failures": r.get("failures", [])})
    return rows


def set_state(source_id: str, state: str, *, probe_summary: str | None = None,
              evidence: dict | None = None, failure: str | None = None) -> dict:
    if state not in STATES:
        raise ValueError(f"非法状态 {state}")
    from .storage import file_lock
    with file_lock(STATE_PATH.with_suffix(".lock")):
        st = state_file()
        cur = st["sources"].setdefault(source_id, {"evidence": [], "failures": []})
        cur["state"] = state
        cur["last_checked"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if probe_summary:
            cur["probe_summary"] = probe_summary
        if evidence:
            cur["evidence"] = ([e for e in cur.get("evidence", []) if e.get("collection_id") != evidence.get("collection_id")]
                               + [evidence])[-20:]
        if failure:
            cur.setdefault("failures", []).append(
                {"at": cur["last_checked"], "detail": failure[:500]})
            cur["failures"] = cur["failures"][-10:]
        save_state(st)
        return cur


def record_configured(source_id: str, note: str = "连接器已实现，待真实查询验证"):
    set_state(source_id, "configured", probe_summary=note)


def get(source_id: str) -> dict | None:
    for d in definitions():
        if d["source_id"] == source_id:
            return d
    return None
