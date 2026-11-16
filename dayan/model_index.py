"""DAYAN 全家族模型索引：目录 ID → 统一运行工厂。

resolve(mid) 返回 (model, protocol)，protocol ∈ fixed_step/ode/sde/jump/demo。
运行规则：
- fixed_step: initialize → step×ticks → 逐 tick observe
- ode/sde/jump: 走 core.simulate 统一编排器
- demo（MET 方法演示）: initialize 后 observe 即结果
"""
from __future__ import annotations

from .models.game_catalog import ALL_BEH_MODELS
from .models.net_catalog import ALL_NET_MODELS
from .models.met_registry import MET_DEMOS
from .models.traffic import (ARZModel, BMLModel, CTMModel,  # noqa: F401
                             FVDModel, GippsModel, IDMModel, KraussModel,
                             LWRModel, MOBILModel, NewellModel, NSModel,
                             OVMModel, VickreyBottleneckModel, VDRModel,
                             WardropSOModel, WardropUEModel,
                             Wiedemann74Model, Wiedemann99Model)
from .models.pedestrian import (CentrifugalModel, ContactEvacModel,  # noqa: F401
                                FloorFieldModel, ORCAModel,
                                OptimalStepsModel, RVOModel,
                                SocialForceModel, VOModel)
from .models import eco_models as ECO_A
from .models import eco_demog as ECO_B
from .models import eco_flagship_lite as ECO_C
from .models import sys_models as SYS
from .models import sys_extras as SYSX
from .models.wave2 import (BassModel, SISModel, SolowModel, VoterModel)  # noqa: F401
from .models.benchmarks import LeslieModel as _Leslie  # ECO057
from .models.opinion import MODELS as OPINION_MODELS  # noqa: F401


def _cls(mod, name):
    return getattr(mod, name, None)


_FIXED_STEP = {}
_ODE = {}
_DEMO = {}
from .models.net_extended import GeneralizedBassModel as _NET075_cls
_ODE["NET075"] = _NET075_cls

# ---- 交通 ----
for mid, cls in {
    "NET095": LWRModel, "NET096": CTMModel, "NET098": IDMModel,
    "NET099": GippsModel, "NET100": NewellModel, "NET101": OVMModel,
    "NET102": FVDModel, "NET103": KraussModel, "NET104": Wiedemann74Model,
    "NET105": Wiedemann99Model, "NET106": NSModel, "NET107": BMLModel,
    "NET108": VDRModel, "NET109": VickreyBottleneckModel,
    "NET110": WardropUEModel, "NET111": WardropSOModel,
    "NET112": MOBILModel,
}.items():
    _FIXED_STEP[mid] = cls
_FIXED_STEP["NET097"] = ARZModel       # ode
_ODE["NET097"] = ARZModel

# ---- 行人 ----
for mid, cls in {
    "NET113": SocialForceModel, "NET114": ContactEvacModel,
    "NET115": CentrifugalModel, "NET116": VOModel, "NET117": RVOModel,
    "NET118": ORCAModel, "NET119": FloorFieldModel,
    "NET120": OptimalStepsModel,
}.items():
    _FIXED_STEP[mid] = cls

# ---- 经济批次 A ----
for mid, cls in {
    "ECO001": ECO_A.LeontiefQuantityModel, "ECO002": ECO_A.LeontiefPriceModel,
    "ECO004": ECO_A.GhoshModel, "ECO005": ECO_A.LeontiefDynamicModel,
    "ECO016": ECO_A.RamseyModel, "ECO017": ECO_A.AKModel,
    "ECO020": ECO_A.KaldorModel, "ECO021": ECO_A.KaleckiModel,
    "ECO031": ECO_A.DiamondOLGModel, "ECO032": ECO_A.BlanchardYOUTHModel,
    "ECO033": ECO_A.LifeCycleModel, "ECO035": ECO_A.GodleyLavoieSIMModel,
    "ECO054": ECO_A.GodeSunderZIModel, "ECO078": ECO_A.McCallModel,
    "ECO082": ECO_A.BenPorathModel, "ECO083": ECO_A.MincerModel,
    "ECO087": ECO_A.GibratModel, "ECO088": ECO_A.RaschModel,
    "ECO089": ECO_A.TwoPLModel, "ECO090": ECO_A.ThreePLModel,
    "ECO096": ECO_A.StaticTaxBenefitModel,
    "ECO110": ECO_A.RichardsonArmsModel, "ECO111": ECO_A.LanchesterSquareModel,
    "ECO112": ECO_A.LanchesterLinearModel, "ECO113": ECO_A.SchaeferFisheryModel,
    "ECO115": ECO_A.HotellingModel, "ECO104": ECO_A.BeerGameModel,
    "ECO106": ECO_A.DICELiteModel, "ECO018": ECO_A.RomerModel,
}.items():
    if cls.clock_type == "ode":
        _ODE[mid] = cls
    else:
        _FIXED_STEP[mid] = cls

# ---- 经济批次 B ----
for mid, cls in {
    "ECO058": ECO_B.LefkovitchModel, "ECO060": ECO_B.RogersMultiregionalModel,
    "ECO061": ECO_B.LeeCarterModel, "ECO063": ECO_B.BrassLogitModel,
    "ECO064": ECO_B.GompertzMakehamModel, "ECO065": ECO_B.CoaleMcNeilModel,
    "ECO066": ECO_B.HadwigerModel, "ECO069": ECO_B.WilsonGravityModel,
    "ECO070": ECO_B.RadiationModel, "ECO071": ECO_B.HarrisTodaroModel,
    "ECO073": ECO_B.BeckerMarriageModel, "ECO074": ECO_B.GaleShapleyModel,
    "ECO076": ECO_B.BeckerTomesModel,
    "ECO077": ECO_B.IntergenerationalMarkovModel,
    "ECO091": ECO_B.BKTModel, "ECO099": ECO_B.HealthMarkovModel,
}.items():
    _FIXED_STEP[mid] = cls

# ---- 大型模型 lite ----
for name, cls in vars(ECO_C).items():
    if isinstance(cls, type) and hasattr(cls, "model_id") and \
            isinstance(getattr(cls, "model_id", None), str) and \
            cls.model_id.startswith("ECO"):
        mid = cls.model_id
        if getattr(cls, "clock_type", "fixed_step") == "ode":
            _ODE[mid] = cls
        else:
            _FIXED_STEP[mid] = cls

# ---- SYS ----
for mid, cls in {
    "SYS002": SYS.MMCQueueModel, "SYS003": SYS.ErlangBModel,
    "SYS006": SYS.MMInfQueueModel, "SYS007": SYS.MD1QueueModel,
    "SYS010": SYS.JacksonNetworkModel, "SYS013": SYS.PriorityQModel,
    "SYS015": SYS.PetriNetModel, "SYS017": SYS.TimedPetriModel,
    "SYS021": SYS.AtomicDEVModel, "SYS022": SYS.CoupledDEVModel,
    "SYS025": SYS.CellDEVModel, "SYS029": SYS.SemiMarkovModel,
    "SYS031": SYS.PoissonProcessModel, "SYS042": SYS.HMMModel,
    "SYS044": SYS.LinearGaussianSSMModel, "SYS045": SYS.DBNModel,
    "SYS004": SYSX.Sys004FiniteCapacityModel,
    "SYS008": SYSX.Sys008DeterministicModel,
    "SYS009": SYSX.GIG1QueueModel, "SYS011": SYSX.GordonNewellModel,
    "SYS012": SYSX.BCMPModel, "SYS016": SYSX.ColoredPetriModel,
    "SYS020": SYSX.Sys020TimedArcModel, "SYS023": SYSX.ParallelDEVModel,
    "SYS024": SYSX.DynamicStructureDEVModel,
    "SYS027": SYSX.Sys027DTMCModel, "SYS033": SYSX.Sys033GaltonWatsonModel,
    "SYS043": SYSX.HSMMModel,
}.items():
    _FIXED_STEP[mid] = cls
_ODE["SYS026"] = None  # PDMP 暂缺实现（登记态）
_ODE.pop("SYS026")
for mid, cls in {"SYS028": SYS.CTMCModel, "SYS030": SYS.BirthDeathModel,
                 "SYS039": SYS.CompoundPoissonModel,
                 "SYS019": SYSX.Sys018StochasticPetriModel}.items():
    _ODE.pop(mid, None)
    _DEMO[mid] = ("jump_sim", cls)

# SDE / 随机过程
for mid, cls in {"SYS034": SYS.GBMModel, "SYS035": SYS.OUModel,
                 "SYS036": SYS.CIRModel, "SYS037": SYS.HestonModel,
                 "SYS038": SYS.WienerModel}.items():
    _ODE[mid] = cls

# ---- BEH / NET / MET ----
_FIXED_STEP.update(ALL_BEH_MODELS)
for mid, cls in ALL_NET_MODELS.items():
    if getattr(cls, "clock_type", "fixed_step") == "jump":
        _DEMO[mid] = ("jump_sim", cls)
    else:
        _FIXED_STEP[mid] = cls
_DEMO.update({mid: ("met_demo", None) for mid in MET_DEMOS})

# ---- wave2 / 意见动力学 ----
for mid, cls in {"ECO015": SolowModel, "NET052": SISModel,
                 "NET074": BassModel}.items():
    _ODE[mid] = cls
_FIXED_STEP["BEH020"] = VoterModel
_FIXED_STEP["ECO057"] = _Leslie
# 意见动力学家族（BEH016-032 等）：此前仅导入未注册（目录声明≠可运行，修复接入）
for _mid, _cls in OPINION_MODELS.items():
    if getattr(_cls, "clock_type", "fixed_step") == "ode":
        _ODE[_mid] = _cls
    else:
        _FIXED_STEP[_mid] = _cls

# ---- 文化演化 + benchmarks + epidemic 死代码类接入（旧资产真实实现，此前未注册）----
from .models import culture as _culture_mod
from .models import benchmarks as _bench_mod
from .models import epidemic as _epi_mod
_SEEN_MIDS = set(_FIXED_STEP) | set(_ODE) | set(_DEMO)
import inspect as _insp
for _mod in (_culture_mod, _bench_mod, _epi_mod):
    for _name, _cls in vars(_mod).items():
        if not isinstance(_cls, type):
            continue
        _mid = getattr(_cls, "model_id", None)
        # 只认自己声明的 model_id（不继承基类 "unset"）；跳过占位名
        if not (isinstance(_mid, str) and _mid) or _mid == "unset"                 or "model_id" not in _cls.__dict__:
            continue
        if _mid in _SEEN_MIDS:
            continue
        # 跳过无参构造不了的类（如需 spec 的通用引擎 CompartmentModel）
        try:
            _req = [p for p in _insp.signature(_cls.__init__).parameters.values()
                    if p.name != "self" and p.default is _insp._empty
                    and p.kind is not p.VAR_KEYWORD]
            if _req:
                continue
        except (ValueError, TypeError):
            pass
        # 已有实现的注册位不抢占（如 NET064/ECO001/BEH021），仅补真空位
        _SEEN_MIDS.add(_mid)
        _ct = getattr(_cls, "clock_type", "fixed_step")
        if _ct in ("ode", "sde", "des"):
            _ODE[_mid] = _cls       # simulate 协议按模型 clock_type 分派
        elif _ct == "jump":
            _DEMO[_mid] = ("jump_sim", _cls)
        else:
            _FIXED_STEP[_mid] = _cls
# 目录声明 mid ↔ 旧实现别名 对齐（NET-SIR 类实现 → 目录位 NET053）
for _alias_mid, _alias_cls in {"NET053": _bench_mod.SIRModel,
                               "NET-SIR": _bench_mod.SIRModel,
                               "SYS018": SYSX.Sys018StochasticPetriModel}.items():
    if _alias_mid not in _SEEN_MIDS:
        _SEEN_MIDS.add(_alias_mid)
        _ODE[_alias_mid] = _alias_cls   # ODE 语义实现，走 simulate 协议

ALL_INDEX = {}
ALL_INDEX.update(_FIXED_STEP)
ALL_INDEX.update(_ODE)
ALL_INDEX.update(_DEMO)


def resolve(mid):
    """返回 (protocol, factory) 或 (None, None)。"""
    if str(mid).startswith("USR") and mid not in _FIXED_STEP:
        from .custom_models import factory as custom_factory
        try:
            cls = custom_factory(mid)
        except FileNotFoundError:
            return None, None
        _FIXED_STEP[mid] = cls
        ALL_INDEX[mid] = cls
    if mid in MET_DEMOS:
        return "demo", ("met_demo", mid)
    if mid in _DEMO:
        return "demo", _DEMO[mid]
    if mid in _ODE:
        return "simulate", _ODE[mid]
    if mid in _FIXED_STEP:
        return "fixed_step", _FIXED_STEP[mid]
    return None, None


def run_model(mid, parameters=None, ticks=200, dt=0.1, seed=0):
    """兼容入口：委托统一运行层 dayan.runtime.run_model_full
    （单次初始化、参数合同、派生随机流、RunManifest）。"""
    from .runtime import run_model_full
    rr = run_model_full(mid, parameters=parameters, ticks=ticks, dt=dt,
                        seed=seed, with_time=False)
    return rr.observations


# ============ 终批扩展（认知/RL/NET扩展/土地利用/经济终量/APP 终批）============
from .models import beh_abm as _beh_abm
from .models import beh_mind as _beh_mind
from .models import beh_rl as _beh_rl
from .models import net_extended as _net_ext
from .models import landuse_ca as _landuse
from .models import eco_final as _eco_final
from .models.app_scenarios import ALL_APP_SCENARIOS as _APP_SC
from .models.app_final import ALL_APP_FINAL as _APP_F
from .models.met_registry import MET_DEMOS as _MET_DEMOS

_BEH_ABM_IDS = {
    "BEH001": "SchellingModel", "BEH002": "SchellingTippingModel",
    "BEH003": "SugarscapeModel", "BEH004": "SugarscapeTradeModel",
    "BEH005": "EpsteinViolenceModel", "BEH006": "AgentZeroModel",
    "BEH009": "BonabeauModel", "BEH010": "MarchExploitationModel",
    "BEH011": "GarbageCanModel", "BEH012": "NKLandscapeModel",
    "BEH013": "LazerFriedmanModel",
    "BEH041": "BoydRichersonModel", "BEH042": "AokiCoevolutionModel",
    "BEH043": "EthnocentrismModel", "BEH044": "UlloaCoevolutionModel",
    "BEH047": "BilingualCompetitionModel",
    "BEH048": "BayesianIteratedLearningModel",
    "BEH082": "ReplicatorCatalogModel", "BEH103": "TPBModel",
    "BEH107": "ERCModel", "BEH108": "RabinReciprocityModel",
    "BEH110": "CognitiveHierarchyModel",
    "BEH136": "DownsHotellingSpatialModel",
    "BEH137": "SocialIdentityModel", "BEH138": "BourdieuCapitalModel",
}
for _mid, _cname in _BEH_ABM_IDS.items():
    _FIXED_STEP[_mid] = getattr(_beh_abm, _cname)

_BEH_MIND_IDS = {
    "BEH094": "BDIAgentFullModel", "BEH095": "ACTRModel",
    "BEH096": "SoarLiteModel", "BEH097": "CLARIONModel",
    "BEH098": "SigmaFactorGraphModel", "BEH099": "OCCModel",
    "BEH100": "PECSModel", "BEH101": "ConsumatModel",
    "BEH129": "GenerativeAgentModel", "BEH130": "ReActModel",
    "BEH131": "ReflexionModel", "BEH132": "VoyagerSkillLibraryModel",
    "BEH133": "ConcordiaModel", "BEH134": "GraphRAGModel",
    "BEH135": "NeurosymbolicModel",
}
for _mid, _cname in _BEH_MIND_IDS.items():
    _FIXED_STEP[_mid] = getattr(_beh_mind, _cname)

for _mid, _cls in _beh_rl.ALL_RL_MODELS.items():
    _DEMO[_mid] = ("rl_demo", _cls)   # initialize 内自训练，observe 即诊断

_NET_EXT_IDS = {
    "NET039": "ERGMModel", "NET040": "TERGMModel", "NET041": "STERGMModel",
    "NET042": "SAOMModel", "NET043": "NetBehaviorSAOMModel",
    "NET044": "REMModel", "NET046": "ActivityDrivenModel",
    "NET047": "SimplexActivityModel", "NET049": "RandomIntersectionModel",
    "NET050": "BipartiteConfigModel", 
    "NET078": "WattsCascadeModel", "NET079": "DoddsWattsModel",
    "NET080": "DKRumorModel", "NET081": "MakiThompsonModel",
    "NET082": "SimplicialContagionModel", "NET083": "ICEModel",
    "NET084": "ICPModel", "NET085": "BondPercolationModel",
    "NET086": "SitePercolationModel", "NET087": "KCoreModel",
    "NET088": "BootstrapPercolationModel", "NET089": "MotterLaiModel",
    "NET090": "BuldyrevModel", "NET091": "EisenbergNoeModel",
    "NET092": "RogersVeraartModel", "NET093": "DebtRankModel",
    "NET094": "AssetFireSaleModel",
}
for _mid, _cname in _NET_EXT_IDS.items():
    _FIXED_STEP[_mid] = getattr(_net_ext, _cname)
_ODE["NET045"] = _net_ext.HawkesModel          # jump
_DEMO["NET045"] = ("jump_sim", _net_ext.HawkesModel)
_FIXED_STEP.pop("NET045", None)

_LANDUSE_IDS = {
    "NET009": "WhiteEngelenModel", "NET010": "SLEUTHLiteModel",
    "NET011": "CLUESLiteModel", "NET012": "DynaCLUEModel",
    "NET013": "FLUSModel", "NET014": "PLUSModel", "NET015": "CAMarkovModel",
}
for _mid, _cname in _LANDUSE_IDS.items():
    _FIXED_STEP[_mid] = getattr(_landuse, _cname)

_ECO_FINAL_IDS = {
    "ECO003": "MiyazawaModel", "ECO006": "MRIModel", "ECO007": "EnvIOModel",
    "ECO008": "SAMMultiplierModel", "ECO010": "GtapeEModel",
    "ECO013": "GubedLiteModel", "ECO014": "RHOMOLOLiteModel",
    "ECO019": "GoodwinCatalogModel",
    "ECO022": "RBCModel", "ECO024": "SmetsWoutersLiteModel",
    "ECO025": "TwoHouseholdNKModel", "ECO026": "HankLiteModel",
    "ECO030": "SamuelsonOLGModel", "ECO034": "DeatonBufferModel",
    "ECO037": "GodleyPCModel", "ECO042": "LocalLinearTrendModel",
    "ECO050": "MarkOneModel", "ECO052": "KSschumpeterLiteModel",
    "ECO053": "EuraceLiteModel", "ECO059": "CohortComponentModel",
    "ECO062": "RenshawHabermanModel", "ECO068": "OriginConstrainedGravityModel",
    "ECO072": "LeePushPullModel", "ECO075": "SOCSIMLiteModel",
    "ECO079": "MortensenPissaridesModel", "ECO080": "BurdettMortensenModel",
    "ECO081": "RoySelfSelectionModel", "ECO084": "JovanovicMatchingModel",
    "ECO085": "HopenhaynModel", "ECO086": "MelitzLiteModel",
    "ECO092": "DKTModel", "ECO093": "PFAModel",
    "ECO094": "SamejimaGRMModel", "ECO095": "MastersPCMModel",
    "ECO097": "VanSoestModel", "ECO098": "DYNASIMModel",
    "ECO100": "PartitionedSurvivalModel", "ECO101": "IndividualHealthMicrosimModel",
    "ECO105": "QuantityQualityModel",
}
for _mid, _cname in _ECO_FINAL_IDS.items():
    _cls = getattr(_eco_final, _cname, None)
    if _cls is None:
        continue
    if getattr(_cls, "clock_type", "fixed_step") == "ode":
        _ODE[_mid] = _cls
    else:
        _FIXED_STEP[_mid] = _cls

for _mid, _cls in _APP_SC.items():
    _FIXED_STEP[_mid] = _cls
for _mid, _cls in _APP_F.items():
    _FIXED_STEP[_mid] = _cls
_FIXED_STEP["SYS001"] = _SYSX.Sys001MM1Model if "_SYSX" in dir() else None
try:
    from .models.app_final import SYS001MM1Model as _SYS001
    _FIXED_STEP["SYS001"] = _SYS001
except ImportError:
    pass

ALL_INDEX = {}
ALL_INDEX.update(_FIXED_STEP)
ALL_INDEX.update(_ODE)
ALL_INDEX.update(_DEMO)

# ---- NET final 16（NET018-072 补齐）----
from .models.net_final16 import (GnmModel, DirectedConfigModel,  # noqa: E402
                                 BianconiBarabasiModel, SoftRGGModel,
                                 HyperbolicModel, DCSBMModel, MMSBMModel,
                                 LFRCatalogModel, HoffLatentModel,
                                 LatentClusterModel, AgeContactSEIRModel,
                                 RenewalEpidemicModel, PairApproxSIRModel,
                                 EdgeBasedSIRModel, HarrisContactModel,
                                 AdaptiveRewiringSISModel)

_NET_F16 = {
    "NET018": GnmModel, "NET020": DirectedConfigModel,
    "NET027": BianconiBarabasiModel, "NET029": SoftRGGModel,
    "NET030": HyperbolicModel, "NET033": DCSBMModel,
    "NET034": MMSBMModel, "NET035": LFRCatalogModel,
    "NET037": HoffLatentModel, "NET038": LatentClusterModel,
    "NET061": AgeContactSEIRModel, "NET067": RenewalEpidemicModel,
    "NET069": PairApproxSIRModel, "NET070": EdgeBasedSIRModel,
    "NET072": AdaptiveRewiringSISModel,
}
for _mid, _cls in _NET_F16.items():
    _FIXED_STEP[_mid] = _cls
_DEMO["NET071"] = ("jump_sim", HarrisContactModel)

# 最终全量
ALL_INDEX = {}
ALL_INDEX.update(_FIXED_STEP)
ALL_INDEX.update(_ODE)
ALL_INDEX.update(_DEMO)

from .models.evacuation_coupled import RoadEvacuationModel
_FIXED_STEP["CPL001"] = RoadEvacuationModel
ALL_INDEX["CPL001"] = RoadEvacuationModel
