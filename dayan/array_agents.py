"""Evaluate approved DSL expressions over synchronous float64 state columns."""
from __future__ import annotations

import ast
from collections import deque
import numpy as np

from .custom_models import AGGREGATES, BINARY, COMPARE, Expression
from .scaling import ARRAY_KERNEL, array_profile

_FUNCTIONS = {"abs": np.abs, "sqrt": np.sqrt, "exp": np.exp, "log": np.log,
              "sin": np.sin, "cos": np.cos, "clip": lambda x, low, high: np.minimum(high, np.maximum(low, x))}


class ArrayExpression(Expression):
    def evaluate(self, env, count, rng=None):
        def choose(condition, selected, when_true, when_false):
            test = np.asarray(condition, dtype=bool)
            if test.ndim == 0 or test.all() or not test.any():
                return (when_true if bool(np.ravel(test)[0]) else when_false)(selected, None)
            source = selected if selected is not None else np.arange(count, dtype=np.intp)
            result = np.empty(len(source), dtype=np.float64)
            result[test] = when_true(source[test], test)
            result[~test] = when_false(source[~test], ~test)
            return result

        def visit(node, selected):
            if isinstance(node, ast.Constant):
                return node.value
            if isinstance(node, ast.Name):
                value = env[node.id]
                return value[selected] if selected is not None and isinstance(value, np.ndarray) else value
            if isinstance(node, ast.BinOp):
                a, b = visit(node.left, selected), visit(node.right, selected)
                if isinstance(node.op, ast.Pow) and np.any(np.abs(b) > 12):
                    raise ValueError("幂指数绝对值不能超过12")
                return BINARY[type(node.op)](a, b)
            if isinstance(node, ast.UnaryOp):
                value = visit(node.operand, selected)
                if isinstance(node.op, ast.Not):
                    return np.logical_not(value)
                return -value if isinstance(node.op, ast.USub) else +value
            if isinstance(node, ast.IfExp):
                return choose(visit(node.test, selected), selected,
                              lambda part, _: visit(node.body, part), lambda part, _: visit(node.orelse, part))
            if isinstance(node, ast.BoolOp):
                def fold(index, part):
                    value = np.asarray(visit(node.values[index], part), dtype=bool)
                    if index == len(node.values)-1:
                        return value
                    remaining = lambda indices, _: fold(index+1, indices)
                    if isinstance(node.op, ast.And):
                        return choose(value, part, remaining, lambda *_: False)
                    return choose(value, part, lambda *_: True, remaining)
                return fold(0, selected)
            if isinstance(node, ast.Compare):
                def compare(index, left, part):
                    right = visit(node.comparators[index], part)
                    valid = COMPARE[type(node.ops[index])](left, right)
                    if index == len(node.ops)-1:
                        return valid
                    return choose(valid, part, lambda indices, mask: compare(
                        index+1, right[mask] if mask is not None and isinstance(right, np.ndarray) else right, indices),
                                  lambda *_: False)
                return compare(0, visit(node.left, selected), selected)
            key = node.func.id
            if key in ("min", "max"):
                prefers = np.less if key == "min" else np.greater
                best = visit(node.args[0], selected)
                for argument in node.args[1:]:
                    candidate = visit(argument, selected)
                    best = np.where(prefers(candidate, best), candidate, best)
                return best
            args = [visit(value, selected) for value in node.args]
            if key in ("uniform", "normal"):
                if rng is None:
                    raise ValueError("观测不能消耗随机数")
                return getattr(rng, key)(*args, size=count if selected is None else len(selected))
            return _FUNCTIONS[key](*args)

        try:
            with np.errstate(divide="raise", invalid="raise", over="raise"):
                result = np.asarray(visit(self.tree, None), dtype=np.float64)
            if not np.isfinite(result).all() or np.any(np.abs(result) > 1e15):
                raise ValueError("表达式结果非有限或超出1e15")
            return np.broadcast_to(result, (count,))
        except (ArithmeticError, TypeError, ValueError) as exc:
            raise ValueError(f"列式表达式 {self.source!r} 失败：{exc}") from None
        finally:
            # The recursive closure otherwise retains the previous step's full columns until cyclic GC.
            visit = None


class ArrayAgents:
    kernel = ARRAY_KERNEL

    def __init__(self, spec, count, environment, rng):
        self.settings, self.count = spec, count
        self.profile = array_profile(spec, count)
        self.grid = spec.get("grid")
        positions = np.arange(count, dtype=np.int32)
        self.coordinates = {"id": positions.astype(float)}
        if self.grid:
            cols = self.grid["columns"]
            self.coordinates.update(row=(positions // cols).astype(float), col=(positions % cols).astype(float))
        base = {**environment, **self.coordinates}
        self.values = {key: ArrayExpression(expr, base, random=True).evaluate(base, count, rng)
                       for key, expr in spec["initial"].items()}
        self.reductions = (self.grid or {}).get("reductions", {})
        self.history = {}
        for rule in self.reductions.values():
            for key in ("field", "by"):
                if key in rule:
                    name = rule[key]
                    lag = rule.get("lag", 0) + 1
                    self.history[name] = deque(maxlen=max(lag, self.history[name].maxlen if name in self.history else 1))
        from .custom_models import aggregate_names
        env_names = base.keys() | self.values.keys()
        update_names = env_names | aggregate_names(self.values) | {"n_agents"} | self.reductions.keys()
        self.updates = {key: ArrayExpression(expr, update_names, random=True)
                        for key, expr in spec.get("update", {}).items()}
        self.measures = {key: ArrayExpression(expr, env_names) for key, expr in spec.get("measures", {}).items()}

    def _local_values(self):
        if not self.reductions:
            return {}
        for name, window in self.history.items():
            window.append(self.values[name])

        def read(name, lag):
            window = self.history[name]
            return window[max(0, len(window)-lag-1)]
        from .grid_neighborhood import reduce_grid
        return reduce_grid(self.grid, read)

    def step(self, environment, rng):
        env = {**environment, **self.coordinates, **self.values, **self._local_values()}
        self.values.update({field: expression.evaluate(env, self.count, rng)
                            for field, expression in self.updates.items()})

    def aggregates(self, environment=None):
        values = self.values
        if environment is not None and self.measures:
            env = {**environment, **self.coordinates, **self.values}
            values = {**values, **{name: expr.evaluate(env, self.count) for name, expr in self.measures.items()}}
        return {"n_agents": self.count, **{f"{op}_{name}": float(fn(column))
                                         for name, column in values.items() for op, fn in AGGREGATES.items()}}

    def columns(self):
        return {name: values for name, values in self.values.items() if not self.grid or name not in ("x", "y")}

    def snapshot(self):
        from .population import encode_column
        return {"kernel": self.kernel, "count": self.count,
                "columns": {name: encode_column(values) for name, values in self.columns().items()},
                "history": {name: [encode_column(values) for values in window]
                            for name, window in self.history.items()}}

    def restore(self, saved):
        from .population import decode_column
        if saved["kernel"] != self.kernel or saved["count"] != self.count or saved["columns"].keys() != self.columns().keys():
            raise ValueError("检查点主体规模或列式推进版本与定义不一致")
        if saved["history"].keys() != self.history.keys():
            raise ValueError("检查点的邻域历史字段与定义不一致")
        self.values.update({name: decode_column(values, self.count) for name, values in saved["columns"].items()})
        for key, values in saved["history"].items():
            if len(values) > self.history[key].maxlen:
                raise ValueError("检查点记录了超出定义的邻域历史")
            self.history[key].extend(decode_column(column, self.count) for column in values)
