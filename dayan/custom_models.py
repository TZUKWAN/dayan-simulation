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

from .limits import limits
from .scaling import LEGACY_AGENTS

ROOT = Path(__file__).resolve().parents[1]
NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,39}\Z")
POSE_CODES = re.compile(r"(?:0|-?[1-9][0-9]{0,3})\Z")
PERSON_POSES = ("idle", "walk", "run", "sit", "down")
FUNCTIONS = {"min": min, "max": max, "abs": abs, "sqrt": math.sqrt,
             "exp": math.exp, "log": math.log, "sin": math.sin, "cos": math.cos,
             "clip": lambda x, lo, hi: min(hi, max(lo, x))}
FUNCTION_ARITY = {**dict.fromkeys(("abs", "sqrt", "exp", "log", "sin", "cos"), (1, 1)),
                  "clip": (3, 3), "uniform": (2, 2), "normal": (2, 2),
                  "min": (2, 9), "max": (2, 9)}
BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
          ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow}
COMPARE = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt,
           ast.GtE: operator.ge, ast.Eq: operator.eq, ast.NotEq: operator.ne}
AGGREGATES = {"mean": np.mean, "sum": np.sum, "min": np.min, "max": np.max}


def aggregate_names(fields):
    return {f"{op}_{name}" for name in fields for op in AGGREGATES}


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
        if isinstance(node, ast.Name):
            if node.id in names:
                return
            raise ValueError(f"未知变量 {node.id}")
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
            if not isinstance(node.func, ast.Name) or node.func.id not in self.functions or node.keywords:
                raise ValueError("不支持的函数调用："+ast.unparse(node.func)+"；仅允许"+",".join(sorted(self.functions))+"。聚合使用mean_属性/sum_属性等实际属性名，不支持mean(表达式)、mean_sqrt等新函数")
            least, most = FUNCTION_ARITY[node.func.id]
            if not least <= len(node.args) <= most:
                expected = f"{least} 至 {most}" if least != most else str(least)
                raise ValueError(f"函数 {node.func.id} 需要 {expected} 个数值参数，收到 {len(node.args)} 个")
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


def validate_expression(path, source, names, *, random=False):
    try:
        return Expression(source, names, random=random)
    except SyntaxError as exc:
        raise ValueError(f"{path} 语法无效。条件表达式使用 A if 条件 else B。{exc.msg}") from exc
    except ValueError as exc:
        raise ValueError(f"{path} 表达式无效。{exc}。可读取变量：{', '.join(sorted(names))}") from exc


def directory():
    return Path(os.environ.get("DAYAN_DATA_DIR", ROOT / "data")) / "custom_models"


def _validate_grid(definition, spec, attrs):
    grid = spec["grid"]
    required = {'rows','columns','degree','reductions'}
    if (definition['kind'] != 'agents' or not isinstance(grid, dict) or not required <= grid.keys()
            or grid.keys() - required - {'boundary','boundary_values'}):
        raise ValueError("agents.grid 只用于 agents。需要 rows、columns、degree、reductions")
    if not isinstance(attrs, dict) or not attrs:
        raise ValueError("固定网格需要实际的 initial 状态字段")
    rows, columns, degree = (grid[name] for name in ("rows", "columns", "degree"))
    if (type(rows) is not int or type(columns) is not int or min(rows, columns) < 3
            or type(degree) is not int or degree not in (4, 8)):
        raise ValueError("固定网格每边至少3格，degree 必须为4或8")
    if grid.get('boundary','periodic') not in ('periodic','reflecting','absorbing'):
        raise ValueError('grid.boundary 须为 periodic、reflecting 或 absorbing')
    outside = grid.get('boundary_values', {})
    if (not isinstance(outside, dict) or outside.keys() - attrs.keys() or
            any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>1e15 for v in outside.values()) or
            outside and grid.get('boundary') != 'absorbing'):
        raise ValueError('boundary_values 仅用于吸收边界的已声明状态字段，须为有限数值')
    size = rows * columns
    if size > limits().array_entities:
        raise ValueError(f"网格 {rows}×{columns} 超过当前数组规模预算 {limits().array_entities:,}")
    if spec.get("count", size) != size:
        raise ValueError("agents.count 必须与网格面积一致。也可省略由网格派生")
    spec["count"] = size
    space = {"width": columns, "height": rows, "unit": "格"}
    if definition.get("space", space) != space:
        raise ValueError("固定网格 space 与网格维度不一致。可省略由网格派生")
    definition["space"] = space
    for key, expression in (("x", "col + 0.5"), ("y", "row + 0.5")):
        if attrs.get(key, expression) != expression or key in spec.get("update", {}):
            raise ValueError("固定网格的位置由行列派生，不能移动或重写")
        attrs[key] = expression
    reductions = grid["reductions"]
    if not isinstance(reductions, dict) or not 1 <= len(reductions) <= 8:
        raise ValueError("至少声明1项实际使用的局部查询，最多8项")
    from .grid_neighborhood import OPS
    for name, rule in reductions.items():
        if not isinstance(name, str) or not NAME.fullmatch(name) or not isinstance(rule, dict):
            raise ValueError("局部查询需要合法变量名和对象合同")
        op = rule.get("op")
        if not isinstance(op, str) or op not in {*OPS, "pick_max"}:
            raise ValueError("局部查询 op 须为 sum、mean、min、max 或 pick_max")
        expected = {"field", "op"} | ({"by"} if op == "pick_max" else set())
        if not expected <= rule.keys() or set(rule) - (expected | {"lag"}):
            raise ValueError(f"局部查询 {name} 的字段不符合合同")
        for field in ("field", "by"):
            if field in rule and (not isinstance(rule[field], str) or rule[field] not in attrs):
                raise ValueError(f"局部查询 {name} 必须读取实际已声明的格点属性")
        lag = rule.get("lag", 0)
        if type(lag) is not int or not 0 <= lag <= 20:
            raise ValueError(f"局部查询 {name} 的 lag 须为0至20的整数步")
    return reductions


def validate_definition(definition):
    if isinstance(definition,dict) and definition.get('kind')=='program':
        from .program_models import validate_definition as validate_program
        return validate_program(definition)
    d = copy.deepcopy(definition)
    allowed = {"name", "description", "kind", "time_unit", "parameters", "initial_state", "rates", "observables", "observable_units", "agents", "space", "mechanisms", "assumptions", "limitations", "visualization", "scenario"}
    if not isinstance(d, dict):
        raise ValueError("definition必须为对象")
    unknown = set(d) - allowed
    if unknown:
        raise ValueError("definition含未知顶层字段 " + "、".join(sorted(unknown)))
    if not d.get("name") or not d.get("description") or not d.get("time_unit"):
        raise ValueError("模型须声明名称、机制描述和模型时间单位")
    if d.get("kind") not in ("stocks", "agents", "hybrid"):
        raise ValueError("kind必须为stocks、agents或hybrid")
    params = d.get("parameters", {})
    stocks = d.get("initial_state", {})
    agent_spec = d.get("agents") or {}
    attrs = agent_spec.get("initial", {})
    measures = agent_spec.get("measures", {})
    grid = agent_spec.get("grid")
    local_fields = _validate_grid(d, agent_spec, attrs) if "grid" in agent_spec else {}
    cell_coordinates = {"row", "col"} if grid else set()
    for group, max_count in ((params, 32), (stocks, 32), (attrs, 16), (measures, 16), (d.get("observables", {}), 32)):
        if not isinstance(group, dict) or len(group) > max_count or any(not NAME.fullmatch(n) for n in group):
            raise ValueError("变量名或变量数量不符合合同")
    if 'observable_units' in d:
        units=d['observable_units']
        if (not isinstance(units,dict) or set(units)!=set(d.get('observables',{}))
                or any(not isinstance(unit,str) or not unit.strip() for unit in units.values())):
            raise ValueError('observable_units须完整覆盖全部实际观测量并使用非空单位文字')
    shared = set(params) | set(stocks) | set(attrs)
    if shared & cell_coordinates or set(local_fields) & (shared | cell_coordinates | {"t", "dt", "id", "uniform", "normal", *FUNCTIONS}):
        raise ValueError("网格行列、局部查询与原有模型字段重名")
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
        if not isinstance(visual, dict) or set(visual) - {"glyph", "color_by", "label", "action_by", "action_poses"}:
            raise ValueError("visualization只接受主体外形、颜色和动作的结构化映射")
        if visual.get("glyph", "auto") not in ("auto", "person", "vehicle", "cell", "point"):
            raise ValueError("visualization.glyph必须为auto、person、vehicle、cell或point")
        if "color_by" in visual and (not isinstance(visual["color_by"], str) or visual["color_by"] not in attrs):
            raise ValueError("visualization.color_by必须是实际声明的主体属性")
        if "label" in visual and (not isinstance(visual["label"], str) or not 1 <= len(visual["label"]) <= 32):
            raise ValueError("visualization.label必须是1–32字的字段名称")
        if not attrs and visual.get("glyph", "auto") != "auto":
            raise ValueError("无主体模型只能使用auto指标场景，不能指定虚构主体")
        if "action_by" in visual or "action_poses" in visual:
            field, poses = visual.get("action_by"), visual.get("action_poses")
            if visual.get("glyph") != "person" or not isinstance(field, str) or field not in attrs:
                raise ValueError("visualization.action_by需要person外形和真实主体属性名")
            if (not isinstance(poses, dict) or not 1 <= len(poses) <= 16
                    or any(not isinstance(code, str) or not POSE_CODES.fullmatch(code)
                           or pose not in PERSON_POSES for code, pose in poses.items())):
                raise ValueError("visualization.action_poses需要整数代码到idle、walk、run、sit或down的映射")
    names = {"t", "dt", *params, *stocks}
    aggregates = aggregate_names(attrs) | {"n_agents"}
    measure_aggregates = aggregate_names(measures)
    if measures and (d["kind"] == "stocks" or set(measures) & (shared | cell_coordinates | set(local_fields))
                     or measure_aggregates & (aggregates | names | set(local_fields))):
        raise ValueError("agents.measures 只用于主体的独立派生观测名，聚合名称不能与现有字段重名")
    if set(local_fields) & aggregates:
        raise ValueError("局部查询与全局聚合字段重名")
    initial_names = {"t", "dt", *params}
    for name, value in stocks.items():
        validate_expression(f"initial_state.{name}", value, initial_names)
        initial_names.add(name)
    rates = d.get("rates", {})
    if set(rates) != set(stocks):
        raise ValueError("每个存量必须有且只有一个变化率方程")
    for name, expr in rates.items():
        validate_expression(f"rates.{name}", expr, names | aggregates)
    if d["kind"] in ("stocks", "hybrid") and not stocks:
        raise ValueError("stocks/hybrid需要存量与变化率")
    if d["kind"] in ("agents", "hybrid"):
        if set(agent_spec) - {"count", "initial", "update", "measures", "type", "color_by", "grid", "backend"} or not attrs:
            raise ValueError("主体规约非法或缺少属性")
        if agent_spec.get("backend", "auto") not in ("auto", "scalar", "array"):
            raise ValueError("agents.backend 须为 auto、scalar 或 array")
        count_expr = validate_expression("agents.count", agent_spec.get("count", "0"), names)
        count_names = {n.id for n in ast.walk(count_expr.tree) if isinstance(n, ast.Name)}
        if any(params[n].get("mutable") for n in count_names & set(params)):
            raise ValueError("主体数量参数不能在运行中修改")
        for name, expr in attrs.items():
            validate_expression(f"agents.initial.{name}", expr, names | {"id"} | cell_coordinates, random=True)
        for name, expr in measures.items():
            validate_expression(f"agents.measures.{name}", expr, names | set(attrs) | {"id"} | cell_coordinates)
        if not set(agent_spec.get("update", {})).issubset(attrs):
            raise ValueError("主体更新只能修改已声明属性")
        used = set()
        for name, expr in agent_spec.get("update", {}).items():
            update = validate_expression(f"agents.update.{name}", expr,
                                         names | aggregates | set(attrs) | {"id"} | cell_coordinates | set(local_fields),
                                         random=True)
            used.update(n.id for n in ast.walk(update.tree) if isinstance(n, ast.Name))
        if not set(local_fields) <= used:
            raise ValueError("每项局部查询均须参与主体更新：" + "、".join(sorted(set(local_fields) - used)))
        space = d.get("space", {})
        if not {"x", "y"} <= attrs.keys() or set(space) != {"width", "height", "unit"}:
            raise ValueError("主体动画需要x/y和明确空间宽高/单位")
        for key in ("width", "height"):
            validate_expression(f"space.{key}", space[key], names)
    if not d.get("observables"):
        raise ValueError("必须声明至少一个数值观测量")
    for name, expr in d["observables"].items():
        validate_expression(f"observables.{name}", expr, names | aggregates | measure_aggregates)
    expressions = [*stocks.values(), *rates.values(), *d["observables"].values(),
                   *attrs.values(), *agent_spec.get("update", {}).values(), *measures.values()]
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

    @property
    def agent_count(self):
        return self._array.count if self._array else len(self.agents)

    def _aggregates(self):
        if self._array:
            return self._array.aggregates()
        result = {"n_agents": len(self.agents)}
        for key in (self.definition.get("agents") or {}).get("initial", {}):
            values = [agent[key] for agent in self.agents]
            for op, fn in AGGREGATES.items():
                result[f"{op}_{key}"] = float(fn(values)) if values else 0.0
        return result

    def initialize(self, context=None, parameters=None, population=None, topology=None, rng=None):
        self.rng = rng if rng is not None else np.random.default_rng(0)
        self.t, self.dt, self.state, self.agents, self.events = 0., 0., {}, [], []
        for key, expr in self.definition.get("initial_state", {}).items():
            self.state[key] = Expression(expr, self._env()).value(self._env())
        spec = self.definition.get("agents") or {}
        from .grid_neighborhood import GridNeighborhood
        self._array = self._grid = None
        if spec:
            count = Expression(spec["count"], self._env()).value(self._env())
            if not count.is_integer() or not 1 <= count <= limits().array_entities:
                raise ValueError("实际主体数量须为正整数且满足当前数组规模预算")
            count = int(count)
            if use_arrays(spec, count):
                from .array_agents import ArrayAgents
                self._array = ArrayAgents(spec, count, self._env(), self.rng)
            else:
                self._grid = GridNeighborhood(spec["grid"]) if spec.get("grid") else None
                init_env = {**self._env(), "id": 0}
                if self._grid:
                    init_env.update(row=0, col=0)
                initial = {key: Expression(expr, init_env, random=True) for key, expr in spec["initial"].items()}
                for i in range(count):
                    env = {**init_env, "id": i}
                    if self._grid:
                        env.update(self._grid.context(i))
                    self.agents.append({key: expr.value(env, self.rng) for key, expr in initial.items()})
        aggregate_fields = aggregate_names(spec.get("initial", {})) | {"n_agents"}
        self._rates = {key: Expression(expr, self._env().keys() | aggregate_fields)
                       for key, expr in self.definition.get("rates", {}).items()}
        update_fields = self._env().keys() | aggregate_fields | set(spec.get("initial", {})) | {"id"}
        if self._grid:
            update_fields |= {"row", "col"} | self._grid.reductions.keys()
        self._updates = {key: Expression(expr, update_fields, random=True) for key, expr in spec.get("update", {}).items()} if not self._array else {}
        measure_names = self._env().keys() | set(spec.get("initial", {})) | {"id"}
        if self._grid:
            measure_names |= {"row", "col"}
        self._measures = {key: Expression(expr, measure_names) for key, expr in spec.get("measures", {}).items()} if not self._array else {}
        observation_names = self._env().keys() | aggregate_fields | aggregate_names(spec.get("measures", {}))
        self._observables = {key: Expression(expr, observation_names)
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
        if (self._grid or self._array and self._array.grid) and dt != 1:
            raise ValueError("固定网格按完整蒙特卡洛步运行，dt须为1，干预时间须为整数步")
        if self._array:
            self._array.step(env, self.rng)
        else:
            local_values = self._grid.before_step(self.agents) if self._grid else None
            updated = []
            for index, agent in enumerate(self.agents):
                context = {**env, **agent, "id": index}
                if self._grid:
                    context.update(self._grid.context(index, local_values))
                updated.append({**agent, **{key: expr.value(context, self.rng) for key, expr in self._updates.items()}})
            self.agents = updated
        self.t = float(t+dt)
        if any(not math.isfinite(v) or abs(v) > 1e15 for v in self.state.values()):
            raise ValueError("存量演化非有限或发散，运行失败")

    def observe(self):
        base = self._env()
        aggregates = self._array.aggregates(base) if self._array else self._aggregates()
        env = {**base, **aggregates}
        if self._measures:
            samples = {name: [] for name in self._measures}
            for index, agent in enumerate(self.agents):
                context = {**env, **agent, "id": index}
                if self._grid:
                    context.update(self._grid.context(index))
                for name, measure in self._measures.items():
                    samples[name].append(measure.value(context))
            env.update({f"{op}_{name}": float(fn(values)) if values else 0.0
                        for name, values in samples.items() for op, fn in AGGREGATES.items()})
        return {key: expr.value(env) for key, expr in self._observables.items()}

    def state_frame(self):
        if not self.agent_count:
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
        view = self.definition.get("visualization")
        presentation = {}
        if view:
            if "action_by" in view:
                codes = {int(code) for code in view["action_poses"]}
                field = view["action_by"]
                actions = self._array.values[field] if self._array else np.asarray([agent[field] for agent in self.agents])
                if not np.isin(actions, list(codes)).all():
                    raise ValueError(f"主体动作属性 {field} 有未配置的动作映射")
            presentation["visualization"] = view
        if scene := self.definition.get("scenario"):
            presentation["scenario"] = {key: scene[key] for key in ("title", "agent_label")}
        spec = self.definition["agents"]
        if self._array:
            from .population import encode_population, grid_preview, sampled_entities
            population = encode_population(self._array, (view or {}).get("color_by") or spec.get("color_by"))
            primary = population["color_by"]
            spatial = {"population": population, "entities": []}
            if self._array.grid:
                spatial["lattice"] = grid_preview(self._array, primary, (view or {}).get("label", primary))
            else:
                spatial["entities"] = sampled_entities(self._array, primary)
        else:
            spatial = {"entities": [{"id": i, "type": spec.get("type", "agent"),
                                     **agent, "state": agent.get('state', agent.get(spec.get("color_by"), 0))}
                                    for i, agent in enumerate(self.agents)]}
        return {**spatial,
                "aggregates": self.observe(), "relations": [], "facilities": facilities,
                "parameters":{name:getattr(self,name) for name in self.parameter_schema},
                "space": {"bounds": [0, 0, width, height], "unit": space["unit"]},
                **({"presentation": presentation} if presentation else {})}

    def snapshot(self):
        agents = {"array_state": self._array.snapshot()} if self._array else {"agents": self.agents}
        return {"state": self.state, **agents, "t": self.t, "dt": self.dt,
                "parameters": {key: getattr(self, key) for key in self.parameter_schema},
                "rng_state": self.rng.bit_generator.state,
                **({"grid_history": self._grid.saved_history()} if self._grid else {})}

    def restore(self, snapshot):
        self.__init__(**snapshot["parameters"])
        self.initialize()
        self.state = copy.deepcopy(snapshot["state"])
        if self._array:
            if "array_state" not in snapshot:
                raise ValueError("数组模型检查点缺少真实主体列")
            self._array.restore(snapshot["array_state"])
        else:
            self.agents = copy.deepcopy(snapshot["agents"])
        self.t, self.dt = snapshot["t"], snapshot["dt"]
        self.rng.bit_generator.state = snapshot["rng_state"]
        if self._grid:
            self._grid.restore_history(snapshot["grid_history"])

    def validate_state(self):
        return []


def use_arrays(spec, count):
    backend = spec.get("backend", "auto")
    if backend == "scalar" and count > LEGACY_AGENTS:
        raise ValueError(f"逐主体兼容执行器最多 {LEGACY_AGENTS} 个主体，大规模规约须采用列式执行器")
    return backend == "array" or count > LEGACY_AGENTS


def population_plan(definition, parameters=None):
    spec = definition.get("agents")
    if not spec:
        return {"kernel": "stock", "entities": 0, "grid": None}
    env = {name: meta["default"] for name, meta in definition.get("parameters", {}).items()}
    env.update({name: value for name, value in (parameters or {}).items() if name in env})
    env.update(t=0.0, dt=0.0)
    for name, expr in definition.get("initial_state", {}).items():
        env[name] = Expression(expr, env).value(env)
    value = Expression(spec["count"], env).value(env)
    if not value.is_integer() or not 1 <= value <= limits().array_entities:
        raise ValueError("实际主体数量须为正整数且满足当前预算")
    count = int(value)
    if use_arrays(spec, count):
        from .scaling import array_profile
        return array_profile(spec, count)
    grid = spec.get("grid")
    return {"kernel": "scalar-compatible", "entities": count,
            "grid": {key:grid[key] for key in ("rows","columns")} if grid else None,
            **({"grid_degree": grid["degree"], 'boundary':grid.get('boundary','periodic')} if grid else {})}


def factory(model_id):
    if not re.fullmatch(r"USR[0-9A-F]{12}", str(model_id)):
        raise ValueError("非法自定义模型标识")
    record = json.loads((directory() / (model_id + ".json")).read_text(encoding="utf-8"))
    d = validate_definition(record["definition"])
    blob = json.dumps(d, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    if "USR" + hashlib.sha256(blob).hexdigest()[:12].upper() != model_id:
        raise ValueError("模型定义哈希与标识不一致")
    if d['kind']=='program':
        from .program_models import factory_class
        return factory_class(model_id,d,record.get('scenario_review'))
    schema = {key: {**meta, "type": meta.get("type", "float"), "required": False}
              for key, meta in d.get("parameters", {}).items()}
    return type("Declarative_" + model_id, (DeclarativeModel,),
                {"model_id": model_id, "definition": d, "parameter_schema": schema, "time_unit": d["time_unit"],
                 "output_units":d.get("observable_units",{}),
                 "scenario_review":record.get("scenario_review"),
                 **({"fixed_dt": 1.0} if (d.get("agents") or {}).get("grid") else {})})


def register(definition, original_request="", llm_audit=None, scenario_review=None):
    d = validate_definition(definition)
    blob = json.dumps(d, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    mid = "USR" + hashlib.sha256(blob).hexdigest()[:12].upper()
    directory().mkdir(parents=True, exist_ok=True)
    path = directory() / (mid + ".json")
    from .collection.storage import atomic_json, file_lock
    with file_lock(path.with_suffix(".lock")):
        if not path.exists():
            # Publish a complete JSON atomically. A killed compiler cannot leave a
            # half-written content-addressed model which permanently blocks retry.
            atomic_json(path, {"model_id": mid, "definition": d, "original_request": original_request,
                               "llm_calls": llm_audit or [], "scenario_review":scenario_review,
                               "validation": "程序AST与结构校验通过；尚未做数学/领域验证" if d['kind']=='program' else "DSL安全与结构校验通过；尚未做领域校准"})
    factory(mid)
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
        out.append({"model_id": path.stem, "protocol": cls.clock_type, "name": cls.definition["name"],
                    "description":cls.definition["description"],
                    "scenario_title":cls.definition.get("scenario",{}).get("title",''),
                    "parameters": [{"name": key, **meta} for key, meta in cls.parameter_schema.items()],
                    "observables": list(cls.definition["observables"]), "runnable": True,
                    "fidelity": "unreviewed", "requires_external": cls.clock_type=='managed_program'})
    return out
