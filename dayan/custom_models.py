"""Executable, inspectable custom models using a restricted mathematical DSL.

No generated Python is imported or evaluated. Stocks use RK4; agents update
simultaneously from the previous state. Every generated definition is archived.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import math
import operator
import os
import re
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,39}\Z")
FUNCTIONS = {"min": min, "max": max, "abs": abs, "sqrt": math.sqrt,
             "exp": math.exp, "log": math.log, "sin": math.sin, "cos": math.cos,
             "clip": lambda x, lo, hi: min(hi, max(lo, x))}
BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
          ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow}
COMPARE = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt,
           ast.GtE: operator.ge, ast.Eq: operator.eq, ast.NotEq: operator.ne}


class Expression:
    def __init__(self, source, names, random=False):
        self.source = str(source)
        if len(self.source) > 512:
            raise ValueError("表达式超过512字符")
        self.tree = ast.parse(self.source, mode="eval").body
        if len(list(ast.walk(self.tree))) > 120:
            raise ValueError("表达式过于复杂")
        self.functions = {**FUNCTIONS, **({"uniform": None, "normal": None} if random else {})}
        self._validate(self.tree, set(names))

    def _validate(self, node, names):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, bool)):
            if not math.isfinite(float(node.value)) or abs(node.value) > 1e15:
                raise ValueError("表达式常数超界")
            return
        if isinstance(node, ast.Name) and node.id in names:
            return
        if isinstance(node, ast.BinOp) and type(node.op) in BINARY:
            children = [node.left, node.right]
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub, ast.Not)):
            children = [node.operand]
        elif isinstance(node, ast.IfExp):
            children = [node.test, node.body, node.orelse]
        elif isinstance(node, ast.Compare) and all(type(op) in COMPARE for op in node.ops):
            children = [node.left, *node.comparators]
        elif isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            children = node.values
        elif isinstance(node, ast.Call):
            if not isinstance(node.func,ast.Name) or node.func.id not in self.functions or node.keywords or len(node.args)>4:
                raise ValueError("不支持的函数调用："+ast.unparse(node.func)+"；仅允许"+",".join(sorted(self.functions))+"。聚合使用mean_属性/sum_属性等实际属性名，不支持mean(表达式)、mean_sqrt等新函数")
            children = node.args
        else:
            raise ValueError(f"不允许的表达式节点或未知变量：{ast.dump(node)[:180]}")
        for child in children:
            self._validate(child, names)

    def value(self, env, rng=None):
        def visit(node):
            if isinstance(node, ast.Constant):
                return node.value
            if isinstance(node, ast.Name):
                return env[node.id]
            if isinstance(node, ast.BinOp):
                left, right = visit(node.left), visit(node.right)
                if isinstance(node.op, ast.Pow) and abs(right) > 12:
                    raise ValueError("幂指数绝对值不能超过12")
                return BINARY[type(node.op)](left, right)
            if isinstance(node, ast.UnaryOp):
                val = visit(node.operand)
                return not val if isinstance(node.op, ast.Not) else -val if isinstance(node.op, ast.USub) else val
            if isinstance(node, ast.IfExp):
                return visit(node.body) if visit(node.test) else visit(node.orelse)
            if isinstance(node, ast.Compare):
                left = visit(node.left)
                for op, right_node in zip(node.ops, node.comparators):
                    right = visit(right_node)
                    if not COMPARE[type(op)](left, right):
                        return False
                    left = right
                return True
            if isinstance(node, ast.BoolOp):
                return all(visit(n) for n in node.values) if isinstance(node.op, ast.And) else any(visit(n) for n in node.values)
            args = [visit(a) for a in node.args]
            if node.func.id in ("uniform", "normal"):
                if rng is None:
                    raise ValueError("观测与存量方程不能消耗随机数")
                return float(getattr(rng, node.func.id)(*args))
            return self.functions[node.func.id](*args)
        result = float(visit(self.tree))
        if not math.isfinite(result) or abs(result) > 1e15:
            raise ValueError(f"表达式结果非有限或超出1e15：{self.source}")
        return result


def directory():
    return Path(os.environ.get("DAYAN_DATA_DIR", ROOT / "data")) / "custom_models"


def validate_definition(definition):
    d = copy.deepcopy(definition)
    allowed = {"name", "description", "kind", "time_unit", "parameters", "initial_state", "rates", "observables", "agents", "space", "mechanisms", "assumptions", "limitations", "visualization", "scenario"}
    if not isinstance(d, dict) or set(d) - allowed:
        raise ValueError("自定义模型含未知字段")
    if not d.get("name") or not d.get("description") or not d.get("time_unit"):
        raise ValueError("模型须声明名称、机制描述和模型时间单位")
    if d.get("kind") not in ("stocks", "agents", "hybrid"):
        raise ValueError("kind必须为stocks、agents或hybrid")
    params = d.get("parameters", {})
    stocks = d.get("initial_state", {})
    agent_spec = d.get("agents") or {}
    attrs = agent_spec.get("initial", {})
    for group, max_count in ((params, 32), (stocks, 32), (attrs, 16), (d.get("observables", {}), 32)):
        if not isinstance(group, dict) or len(group) > max_count or any(not NAME.fullmatch(n) for n in group):
            raise ValueError("变量名或变量数量不符合合同")
    if set(params) & set(stocks):
        raise ValueError("参数与存量重名：" + str(sorted(set(params) & set(stocks))) + "；初值参数应另命名，例如x0，存量用x")
    if (set(params) | set(stocks)) & {"t", "dt", "id", *FUNCTIONS, "uniform", "normal"}:
        raise ValueError("参数或状态覆盖保留变量/函数")
    if set(attrs) & (set(params) | set(stocks) | {"t", "dt", "id", *FUNCTIONS, "uniform", "normal"}):
        raise ValueError("主体属性与全局变量重名")
    for name, meta in params.items():
        if not isinstance(meta, dict) or set(meta) - {"default", "minimum", "maximum", "type", "unit", "mutable", "label"}:
            raise ValueError("参数元数据包含未知字段")
        if meta.get("type", "float") not in ("float", "int"):
            raise ValueError("DSL参数只支持有限数值")
        value = meta.get("default")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"参数 {name} 缺少有限默认值")
        lo, hi = meta.get("minimum", -1e12), meta.get("maximum", 1e12)
        if not math.isfinite(lo) or not math.isfinite(hi) or not lo <= value <= hi:
            raise ValueError("参数边界非法")
        if meta.get("type") == "int" and int(value) != value:
            raise ValueError("整数参数默认值必须是整数")
    if "visualization" in d:
        visual = d["visualization"]
        if not isinstance(visual, dict) or set(visual) - {"glyph", "color_by", "label"}:
            raise ValueError("visualization只允许glyph、color_by、label；不接受渲染代码或任意场景字段")
        if visual.get("glyph", "auto") not in ("auto", "person", "vehicle", "cell", "point"):
            raise ValueError("visualization.glyph必须为auto、person、vehicle、cell或point")
        if "color_by" in visual and (not isinstance(visual["color_by"], str) or visual["color_by"] not in attrs):
            raise ValueError("visualization.color_by必须是实际声明的主体属性")
        if "label" in visual and (not isinstance(visual["label"], str) or not 1 <= len(visual["label"]) <= 32):
            raise ValueError("visualization.label必须是1–32字的字段名称")
        if not attrs and visual.get("glyph", "auto") != "auto":
            raise ValueError("无主体模型只能使用auto指标场景，不能指定虚构主体")
    names = {"t", "dt", *params, *stocks}
    aggregates = {f"{op}_{key}" for key in attrs for op in ("mean", "sum", "min", "max")} | {"n_agents"}
    for value in stocks.values():
        Expression(value, names)
    rates = d.get("rates", {})
    if set(rates) != set(stocks):
        raise ValueError("每个存量必须有且只有一个变化率方程")
    for expr in rates.values():
        Expression(expr, names | aggregates)
    if d["kind"] in ("stocks", "hybrid") and not stocks:
        raise ValueError("stocks/hybrid需要存量与变化率")
    if d["kind"] in ("agents", "hybrid"):
        if set(agent_spec) - {"count", "initial", "update", "type", "color_by"} or not attrs:
            raise ValueError("主体规约非法或缺少属性")
        count_expr = Expression(agent_spec.get("count", "0"), names)
        count_names = {n.id for n in ast.walk(count_expr.tree) if isinstance(n, ast.Name)}
        if any(params[n].get("mutable") for n in count_names & set(params)):
            raise ValueError("主体数量参数不能在运行中修改")
        for expr in attrs.values():
            Expression(expr, names | {"id"}, random=True)
        if not set(agent_spec.get("update", {})).issubset(attrs):
            raise ValueError("主体更新只能修改已声明属性")
        for expr in agent_spec.get("update", {}).values():
            Expression(expr, names | aggregates | set(attrs) | {"id"}, random=True)
        space = d.get("space", {})
        if not {"x", "y"} <= attrs.keys() or set(space) != {"width", "height", "unit"}:
            raise ValueError("主体动画需要x/y和明确空间宽高/单位")
        for key in ("width", "height"):
            Expression(space[key], names)
    if not d.get("observables"):
        raise ValueError("必须声明至少一个数值观测量")
    for expr in d["observables"].values():
        Expression(expr, names | aggregates)
    expressions = [*stocks.values(), *rates.values(), *d["observables"].values(),
                   *attrs.values(), *agent_spec.get("update", {}).values()]
    if agent_spec:
        expressions += [agent_spec["count"], d["space"]["width"], d["space"]["height"]]
    referenced = {node.id for expr in expressions for node in ast.walk(ast.parse(str(expr), mode="eval")) if isinstance(node, ast.Name)}
    unused = set(params) - referenced
    if unused:
        raise ValueError("参数未被任何方程/主体规则/观测读取：" + str(sorted(unused)) + "；运行的步数、步长与种子由平台管理，不能添加成无效模型参数")
    if len(json.dumps(d, ensure_ascii=False)) > 100_000:
        raise ValueError("模型定义超过100KiB")
    from .scene_contract import validate_scene
    validate_scene(d)
    return d


class DeclarativeModel:
    clock_type = "fixed_step"
    dt_scale = 1
    definition = {}

    def __init__(self, **parameters):
        self.parameter_schema = self.definition.get("parameters", {})
        for name, spec in self.parameter_schema.items():
            value = parameters.get(name, spec["default"])
            if not spec.get("minimum", -1e12) <= value <= spec.get("maximum", 1e12):
                raise ValueError(f"{name} 超出模型声明边界")
            setattr(self, name, value)

    def _env(self):
        return {name: getattr(self, name) for name in self.parameter_schema} | self.state | {"t": self.t, "dt": self.dt}

    def _aggregates(self):
        result = {"n_agents": len(self.agents)}
        for key in (self.definition.get("agents") or {}).get("initial", {}):
            values = [agent[key] for agent in self.agents]
            for op, fn in (("mean", np.mean), ("sum", np.sum), ("min", np.min), ("max", np.max)):
                result[f"{op}_{key}"] = float(fn(values)) if values else 0.0
        return result

    def initialize(self, context=None, parameters=None, population=None, topology=None, rng=None):
        self.rng = rng if rng is not None else np.random.default_rng(0)
        self.t, self.dt, self.state, self.agents, self.events = 0., 0., {}, [], []
        for key, expr in self.definition.get("initial_state", {}).items():
            self.state[key] = Expression(expr, self._env()).value(self._env())
        spec = self.definition.get("agents") or {}
        if spec:
            count = Expression(spec["count"], self._env()).value(self._env())
            if not count.is_integer() or not 1 <= count <= 2000:
                raise ValueError("主体数量必须为1–2000整数；不静默截断")
            for i in range(int(count)):
                env = {**self._env(), "id": i}
                self.agents.append({key: Expression(expr, env, random=True).value(env, self.rng)
                                    for key, expr in spec["initial"].items()})
        self._rates = {key: Expression(expr, self._env().keys() | self._aggregates().keys())
                       for key, expr in self.definition.get("rates", {}).items()}
        self._updates = {key: Expression(expr, self._env().keys() | self._aggregates().keys() | set(spec.get("initial", {})) | {"id"}, random=True)
                         for key, expr in spec.get("update", {}).items()}
        self._observables = {key: Expression(expr, self._env().keys() | self._aggregates().keys())
                             for key, expr in self.definition["observables"].items()}

    def step(self, t, dt):
        self.t, self.dt = float(t), float(dt)
        env = {**self._env(), **self._aggregates()}
        old_state = dict(self.state)
        if old_state:
            def derivative(state, at):
                return {key: expr.value({**env, **state, "t": at}) for key, expr in self._rates.items()}
            def shifted(rate, frac):
                return {key: old_state[key] + dt * frac * rate[key] for key in old_state}
            k1 = derivative(old_state, t)
            k2 = derivative(shifted(k1, .5), t+dt/2)
            k3 = derivative(shifted(k2, .5), t+dt/2)
            k4 = derivative(shifted(k3, 1), t+dt)
            self.state = {key: old_state[key] + dt/6*(k1[key]+2*k2[key]+2*k3[key]+k4[key]) for key in old_state}
        self.agents = [{**agent, **{key: expr.value({**env, **agent, "id": i}, self.rng) for key, expr in self._updates.items()}}
                       for i, agent in enumerate(self.agents)]
        self.t = float(t+dt)
        if any(not math.isfinite(v) or abs(v) > 1e15 for v in self.state.values()):
            raise ValueError("存量演化非有限或发散，运行失败")

    def observe(self):
        env = {**self._env(), **self._aggregates()}
        return {key: expr.value(env) for key, expr in self._observables.items()}

    def state_frame(self):
        if not self.agents:
            return None
        env = self._env()
        space = self.definition["space"]
        width = Expression(space["width"], env).value(env)
        height = Expression(space["height"], env).value(env)
        if width <= 0 or height <= 0:
            raise ValueError("空间宽高必须为正")
        facilities=[]
        for spec in self.definition.get("scenario",{}).get("facilities",[]):
            values={key:Expression(spec[key],env).value(env) for key in ("x","y","width","depth","value","tone") if key in spec}
            if values["width"]<=0 or values["depth"]<=0:
                raise ValueError("场景设施尺寸必须保持正值："+spec["id"])
            if "tone" in values and values["tone"] not in (0,1,2,3):
                raise ValueError("设施tone必须为0中性/1停止/2警示/3通行："+spec["id"])
            facilities.append({"id":spec["id"],"type":"model_facility","kind":spec["kind"],
                               "label":spec["label"],"role":spec["role"],**values})
        return {"entities": [{"id": i, "type": (self.definition.get("agents") or {}).get("type", "agent"),
                               **agent, "state": agent.get((self.definition.get("agents") or {}).get("color_by"), 0)}
                              for i, agent in enumerate(self.agents)],
                "aggregates": self.observe(), "relations": [], "facilities": facilities,
                "parameters":{name:getattr(self,name) for name in self.parameter_schema},
                "space": {"bounds": [0, 0, width, height], "unit": space["unit"]}}

    def snapshot(self):
        return {"state": self.state, "agents": self.agents, "t": self.t, "dt": self.dt,
                "parameters": {key: getattr(self, key) for key in self.parameter_schema},
                "rng_state": self.rng.bit_generator.state}

    def restore(self, snapshot):
        self.__init__(**snapshot["parameters"])
        self.initialize()
        self.state, self.agents = copy.deepcopy(snapshot["state"]), copy.deepcopy(snapshot["agents"])
        self.t, self.dt = snapshot["t"], snapshot["dt"]
        self.rng.bit_generator.state = snapshot["rng_state"]

    def validate_state(self):
        return []


def factory(model_id):
    if not re.fullmatch(r"USR[0-9A-F]{12}", str(model_id)):
        raise ValueError("非法自定义模型标识")
    record = json.loads((directory() / (model_id + ".json")).read_text(encoding="utf-8"))
    d = validate_definition(record["definition"])
    blob = json.dumps(d, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    if "USR" + hashlib.sha256(blob).hexdigest()[:12].upper() != model_id:
        raise ValueError("模型定义哈希与标识不一致")
    schema = {key: {**meta, "type": meta.get("type", "float"), "required": False}
              for key, meta in d.get("parameters", {}).items()}
    return type("Declarative_" + model_id, (DeclarativeModel,),
                {"model_id": model_id, "definition": d, "parameter_schema": schema, "time_unit": d["time_unit"],
                 "scenario_review":record.get("scenario_review")})


def register(definition, original_request="", llm_audit=None, scenario_review=None):
    d = validate_definition(definition)
    blob = json.dumps(d, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    mid = "USR" + hashlib.sha256(blob).hexdigest()[:12].upper()
    directory().mkdir(parents=True, exist_ok=True)
    path = directory() / (mid + ".json")
    if not path.exists():
        # Exclusively create; an existing content-addressed definition is immutable.
        with path.open("x", encoding="utf-8") as stream:
            json.dump({"model_id": mid, "definition": d, "original_request": original_request,
                       "llm_calls": llm_audit or [], "scenario_review":scenario_review,
                       "validation": "DSL安全与结构校验通过；尚未做领域校准"}, stream, ensure_ascii=False, indent=2)
    cls = factory(mid)
    from . import model_index
    model_index._FIXED_STEP[mid] = cls
    model_index.ALL_INDEX[mid] = cls
    return {"model_id": mid, "definition": d, "definition_url": f"/api/custom_models/{mid}",
            "validation": "结构校验通过；运行结果和科学适用性分别验证"}


def capabilities():
    out = []
    for path in sorted(directory().glob("USR*.json")):
        try:
            cls = factory(path.stem)
        except (ValueError, KeyError, SyntaxError) as exc:
            out.append({"model_id": path.stem, "parameters": [], "observables": [],
                        "runnable": False, "error": f"当前DSL校验未通过：{exc}"})
            continue
        out.append({"model_id": path.stem, "protocol": "fixed_step", "name": cls.definition["name"],
                    "description":cls.definition["description"],
                    "scenario_title":cls.definition.get("scenario",{}).get("title",''),
                    "parameters": [{"name": key, **meta} for key, meta in cls.parameter_schema.items()],
                    "observables": list(cls.definition["observables"]), "runnable": True,
                    "fidelity": "unreviewed", "requires_external": False})
    return out
