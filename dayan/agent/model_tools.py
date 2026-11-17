"""Real language-to-model compilation and executable registration."""
import json

from ..custom_models import register, validate_definition, directory
from ..llm_client import complete, json_object
from ..research.requirements import extract_request
from ..scene_contract import validate_scene, review_definition, scene_requirements
from .progress import emit

DSL_CONTRACT = """只输出一个JSON模型定义，不能输出Python/JS代码。
顶层字段：name,description,kind(stocks|agents|hybrid),time_unit,mechanisms(机制列表),assumptions(假设列表),limitations(局限列表),parameters,initial_state,rates,observables；主体模型另需agents,space。
parameters为{参数名:{default:有限数值,type:float或int,minimum:数值,maximum:数值,unit:单位,mutable:布尔}}，参数与状态/属性不能重名。
只声明实际被方程/主体规则使用的参数。不要把ticks、dt、seed、步数、步长声明成模型参数，这些由平台运行选项管理。
initial_state为{存量名:数值或表达式}，rates必须对每个存量给出导数表达式，平台实际用RK4推进；没有存量时两者为空对象。
agents为{count:表达式,initial:{属性:表达式},update:{属性:下一时刻表达式},type:agent,color_by:属性名}。
主体必须有x,y属性，主体数1-2000，count使用的参数不能mutable。space={width:正数或参数表达式,height:正数或参数表达式,unit:距离单位}。
主体模型同时给出visualization={glyph:auto|person|vehicle|cell|point,color_by:实际主体属性名,label:该属性的中文名称（1–32字）}。按主体语义选外形，例如人群person、车辆vehicle、格点cell，抽象主体point；颜色须对应真实计算属性。此字段只选择平台统一呈现器，不输出JS、材质、灯光代码或不存在的地物/关系；实际空间/道路由状态数据决定。无主体的stocks模型省略visualization，平台使用明确标注的指标演化场景。
具体空间/地点/设施需求还必须给出scenario={title:场景名称,setting:实际建模与简化说明,agent_label:主体角色,facilities:[{id:英文唯一名,kind:room|building|exit|destination|source|obstacle|road|signal|service|zone,label:名称,x:表达式,y:表达式,width:表达式,depth:表达式,role:modeled或context,behavior_parameters:[真实参数名]}],requirements:[{quote:用户原文逐字短语,model_refs:[实际定义路径],visual_refs:[实际定义路径]}]}。平台会加入source_request原文。
设施x/y为模型坐标中心，width/depth为模型空间中的宽深，须保持正值；value可选数值表达式表示实际状态。只允许读取参数、存量、t/dt。kind=road为矩形道路区域，不代表环形道路。不能凭装饰冒充模型作用：modeled设施的behavior_parameters全部必须进入agents.update或rates，且至少一个绑定同时进入设施位置/尺寸/状态表达式；obstacle/signal必须为modeled。context只表示假设场所，不宣称碰撞/墙体/通行影响。
设施tone为可选状态表达式，0中性/1停止红色/2警示琥珀/3通行青色，必须对应真实行为状态；不提供时不猜测红绿含义。信号灯可用tone表达实际相位，value显示实际数值。
model_refs例如agents.count、agents.update.x、rates.water、space或parameters.exit_x；visual_refs例如scenario.facilities.gate、agents.initial、visualization.color_by。设施引用使用id而非数组下标。每条对应关系都要给出真实可解析路径，不能只引用name/description/mechanisms。必须覆盖人数/角色、地点/设施/布局、行为和用户指定约束，不能用随机游走替代目标行为。
用户显式参数必须作为同名有效参数实际使用（37名主体会映射n），不得改变数量/单位/初始条件以便套模型。二维DSL不实现楼层、刚体碰撞、烟气/流体场，不得假装生成。空间复杂或表达能力不足时返回error和具体缺口。
每步主体更新同时使用上一步状态；可读mean_属性,sum_属性,min_属性,max_属性,n_agents。不要用这些名称作为主体属性。
主体初始化和更新可使用uniform(a,b)、normal(mu,sigma)。存量方程和observables不得使用随机调用。
目标移动必须避免越过目标后振荡：每步位移不得大于当前到目标的距离，到达后停止。所有更新同时读旧值，不要把缓存的旧distance当成当前坐标的距离；直接用当前x/y计算距离，注意除零与dt。固定速度/目标移动不应偷偷改成随机游走。
表达式只可使用声明变量、t、dt、主体id、算术+-*/%**、比较、条件a if条件 else b，以及min,max,abs,sqrt,exp,log,sin,cos,clip(x,lo,hi)。禁止属性访问、数组索引、循环、导入、字符串、代码和未知函数。
observables为{字段名:表达式}，至少一个观测量。单位、参数及假设必须清楚；不虚构真实数据或宣称已校准。
聚合的合法例子：若agents.initial声明value和arrived，observables可为{"value_mean":"mean_value","arrived_count":"sum_arrived","population":"n_agents"}。不能直接聚合表达式；mean_sqrt、mean(expr)、sum(expr)和mean_distance（未声明distance属性时）都不合法。无需为了丰富指标而增加不被用户需要的复杂属性。
不能用无关模型替代所需机制。无法在此DSL表达时返回{error:具体缺失机制}。"""


def build_model(request=None, definition=None, parameters=None, ticks=100, seed=None, dt=None,
                data_bindings=None, last_run=None, seeds=None):
    audit = []
    try:
        if (request is None) == (definition is None):
            raise ValueError("只指定原始request或显式definition之一")
        from .context import canonical_context
        last_run=canonical_context(last_run)
        parsed = extract_request(request or "",last_run)
        if parsed["missing_context"]:
            raise ValueError("缺少上一次实际运行上下文，不能重建一个无关模型来替代")
        if request and scene_requirements(request)["unsupported"]:
            raise ValueError("当前二维DSL缺少："+"、".join(scene_requirements(request)["unsupported"]))
        if parsed.get("requires_llm_agents"):
            raise ValueError("数学DSL不实现LLM主体推理循环；应显式运行BEH129–133真实LLM模型，不能生成一个普通主体冒充")
        if parsed["requires_real_data"] and not data_bindings:
            raise ValueError("需求要求现实数据；须先取得并核验数据集，不能用假设空间替代")
        options = parsed["options"]
        ticks, seed, dt = options.get("ticks", ticks), options.get("seed", seed), options.get("dt", dt)
        seeds=options.get("seeds",seeds)
        if seeds is not None and (not isinstance(seeds,(list,tuple)) or not seeds):
            raise ValueError("seeds必须为非空种子列表")
        if seeds and parsed["interventions"]:
            raise ValueError("新模型创建后同时进行多种子时点干预尚无合并执行入口；不能只运行一个种子或漏掉干预")
        if seeds and data_bindings:
            raise ValueError("新模型多种子入口尚不接收数据映射；不能忽略数据绑定")
        parameters = {**(parameters or {}), **parsed["parameters"]}
        scenario_review=None
        if definition is None:
            context={}
            if parsed["reuse"] and last_run:
                from ..run_store import get_store
                if not last_run.get("run_id"):
                    raise ValueError("修改已有模型需要真实run_id，以保留原模型方程与场景")
                prior=get_store().load(last_run["run_id"])
                if not prior["manifest"].get("model_definition"):
                    raise ValueError("原模型没有可编辑DSL规约，不能声称完整沿用其内部机制；可调整该模型公开参数")
                context={"model_definition":prior["manifest"].get("model_definition"),
                         "actual_parameters":prior["manifest"].get("actual",{}).get("effective_parameters"),
                         "requested":prior["manifest"].get("requested")}
            messages = [{"role": "system", "content": "你负责把需求转成可审查且真实执行的数学/主体模型。" + DSL_CONTRACT},
                        {"role": "user", "content": "原始需求：" + request+"\n用户显式约束："+json.dumps(parsed,ensure_ascii=False)+"\n已有实际模型（如有）："+json.dumps(context,ensure_ascii=False)}]
            for attempt in range(2):
                emit(f"正在{'修正' if attempt else '生成'}实际模型方程与场景合同…")
                raw = complete(messages, timeout=180,
                               purpose="build-model", audit=audit,thinking=True if attempt else None)
                drafts = directory() / "drafts"
                drafts.mkdir(parents=True, exist_ok=True)
                (drafts / (audit[-1]["call_id"] + ".txt")).write_text(raw, encoding="utf-8")
                try:
                    definition = json_object(raw)
                    if definition.get("error"):
                        raise ValueError(definition["error"])
                    if isinstance(definition.get("scenario"),dict):
                        definition["scenario"]["source_request"]=request
                    definition = validate_definition(definition)
                    missing=set(parsed["mechanisms"])-set(definition.get("mechanisms",[]))
                    if missing:raise ValueError("缺少明确机制："+"、".join(sorted(missing)))
                    missing_params=set(parameters)-set(definition.get("parameters",{}))
                    if missing_params:raise ValueError("用户参数未保留为有效同名参数："+"、".join(sorted(missing_params)))
                    validate_scene(definition,request)
                    emit("结构与设施绑定已通过，正在复核是否符合用户原文…")
                    scenario_review=review_definition(request,definition,audit,{**options,"parameters":parameters,"ticks":ticks,"dt":dt,"seed":seed,"prior":context})
                    if parsed["reuse"]:scenario_review["parent_run_id"]=last_run["run_id"]
                    break
                except (ValueError, SyntaxError) as exc:
                    audit[-1]["definition_validation_error"] = str(exc)
                    if attempt == 1:
                        raise
                    messages += [{"role": "assistant", "content": raw},
                                 {"role": "user", "content": "结构或场景对应校验失败：" + str(exc) + "。修正实际方程、主体规则与场景，不得仅补名称。保留原始需求全部参数与机制。只返回完整定义JSON。"}]
        definition = validate_definition(definition)
        missing = set(parsed["mechanisms"]) - set(definition.get("mechanisms", []))
        if missing:
            raise ValueError("生成定义未覆盖明确机制：" + "、".join(sorted(missing)))
        if parsed["requires_real_data"] and not data_bindings:
            raise ValueError("原始需求要求真实数据，须先采集并指定数据映射；未运行合成人口替代")
        if parsed["requires_real_data"] and set(parsed["mechanisms"]) & {"人群疏散", "交通流", "积水影响", "接驳运力"}:
            raise ValueError("当前DSL只将数据字段绑定到参数，不能冒充真实路网拓扑；真实空间疏散需求应使用CPL001并指定roads_dataset_id和population_dataset_id")
        result = register(definition, request or "用户显式模型规约", audit, scenario_review=scenario_review)
        emit("模型与场景规约已保存，正在实际运行并归档状态…")
        from .tools import tool_run,tool_ensemble
        if seeds:
            run=tool_ensemble(result["model_id"],parameters=parameters,ticks=ticks,dt=dt,seeds=seeds)
            if run.get("ok"):run["payload"]["result_kind"]="ensemble"
        else:
            run = tool_run(result["model_id"], parameters=parameters, ticks=ticks, seed=seed,
                           dt=dt, data_bindings=data_bindings,interventions=parsed["interventions"])
        if not run["ok"]:
            return {**run, "model": result, "llm_calls": audit}
        run["payload"].update(result)
        run["payload"]["llm_calls"] = audit
        run["payload"]["scenario_review"] = scenario_review
        run["payload"]["warnings"] = list(run["payload"].get("warnings", [])) + [
            "此模型已实际执行；生成的机制假设与领域适用性未经过独立科学验证，不能当成已校准预测。"]
        return run
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "llm_calls": audit}
