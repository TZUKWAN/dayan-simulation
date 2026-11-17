"""Source-backed output schemas, without running models during discovery.

Literal output keys are read from observe() (including inherited implementations)
and from self.result dictionaries used by scenario adapters. Unknown types stay
unknown. This declares fields; it is neither a probe result nor validity evidence.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import textwrap
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Reviewed defaults refer to a specific model, never to the first numeric column.
PRIMARY_METRICS = {"NET052": "I", "NET053": "I", "NET055": "I",
                   "NET106": "flux", "NET113": "evacuated",
                   "BEH001": "segregation", "BEH018": "mean",
                   "ECO019": "employment", "SYS002": "Wq_sim",
                   "CPL001": "evacuated"}


def _type(node, names):
    if isinstance(node, ast.Name) and node.id in names:
        return _type(names[node.id], {})
    if isinstance(node, ast.Constant):
        return ("boolean" if isinstance(node.value, bool) else
                "number" if isinstance(node.value, (int, float)) else
                "string" if isinstance(node.value, str) else "null")
    if isinstance(node, (ast.Compare, ast.BoolOp)):
        return "boolean"
    if isinstance(node, (ast.List, ast.Tuple, ast.ListComp)):
        return "array"
    if isinstance(node, (ast.Dict, ast.DictComp)):
        return "object"
    if isinstance(node, ast.IfExp):
        kinds = {_type(node.body, names), _type(node.orelse, names)} - {"null"}
        return kinds.pop() if len(kinds) == 1 else "unknown"
    if isinstance(node, ast.Call):
        name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        if name in {"float", "int", "len", "round", "sum", "mean", "std", "var", "min", "max", "median", "quantile", "percentile", "count_nonzero", "norm"}:
            return "number"
        if name in {"bool", "any", "all", "isfinite", "isclose"}:
            return "boolean"
        if name in {"str", "format"}:
            return "string"
        if name in {"list", "tolist", "sorted"}:
            return "array"
        if name == "dict":
            return "object"
    if isinstance(node, (ast.BinOp, ast.UnaryOp)):
        operands = [n for n in (getattr(node, "left", None), getattr(node, "right", None), getattr(node, "operand", None)) if n is not None]
        if operands and all(_type(n, names) == "number" for n in operands):
            return "number"
    return "unknown"


def _is_result(node):
    return isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self" and node.attr == "result"


@lru_cache(maxsize=1024)
def _class_fields(cls):
    fields, evidence = {}, []
    if not isinstance(cls, type):
        return fields, evidence
    # Methods may augment a super().observe() result; walk the whole MRO.
    for base in reversed(cls.__mro__):
        for method_name in ("initialize", "observe"):
            method = base.__dict__.get(method_name)
            if not callable(method):
                continue
            try:
                source, first = inspect.getsourcelines(method)
                source = textwrap.dedent("".join(source))
                tree = ast.parse(source)
                file = Path(inspect.getsourcefile(method)).relative_to(ROOT).as_posix()
            except (OSError, TypeError, ValueError, SyntaxError):
                continue
            names = {n.targets[0].id: n.value for n in ast.walk(tree)
                     if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)}
            evidence.append({"file": file, "line": first, "method": base.__name__+"."+method_name,
                             "sha256": hashlib.sha256(source.encode()).hexdigest()})

            def add_dict(node):
                if isinstance(node, ast.Name) and node.id in names:
                    add_dict(names[node.id])
                elif isinstance(node, ast.Dict):
                    for k, v in zip(node.keys, node.values):
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            fields[k.value] = {"type": _type(v, names), "optional": True}
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict":
                    for kw in node.keywords:
                        if kw.arg:
                            fields[kw.arg] = {"type": _type(kw.value, names), "optional": True}
            for node in ast.walk(tree):
                if method_name == "observe":
                    if isinstance(node, ast.Return):
                        add_dict(node.value)
                    elif isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant) and isinstance(target.slice.value, str):
                                fields[target.slice.value] = {"type": _type(node.value, names), "optional": True}
                    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "update":
                        for arg in node.args:
                            add_dict(arg)
                elif isinstance(node, ast.Assign) and any(_is_result(t) for t in node.targets):
                    add_dict(node.value)
    declared = getattr(cls, "declared_observables", ())
    for name in declared:
        fields.setdefault(name, {"type": "unknown", "optional": True})
    return fields, evidence


def output_contract(mid, *, reference_results=None):
    from .model_index import resolve
    protocol, factory = resolve(mid)
    if factory is None:
        raise ValueError(f"{mid} 无运行工厂")
    cls = factory[1] if isinstance(factory, tuple) else factory
    if str(mid).startswith("USR"):
        from .custom_models import factory as custom_factory
        definition = custom_factory(mid).definition
        fields = {name: {"type": "number", "optional": False} for name in definition["observables"]}
        evidence = [{"kind": "validated-custom-definition", "model_id": mid}]
    else:
        fields, evidence = _class_fields(cls)
    fields = {k: dict(v) for k, v in fields.items()}
    # Explicit, saved reference probes can supply dynamic fields. No discovery
    # request initiates a simulation. Changed execution sources invalidate them.
    from .fidelity import _existing_probes, models_source_fingerprint
    if reference_results is None:
        reference_results = _existing_probes(models_source_fingerprint())
    reference = reference_results.get(mid, {})
    if reference.get('ok'):
        for name, kinds in reference.get('output_types', {}).items():
            scalar = set(kinds)-{'null'}
            fields[name] = {'type': next(iter(scalar)) if len(scalar)==1 else 'unknown',
                            'nullable': 'null' in kinds, 'optional': True}
    primary = getattr(cls, "primary_metric", None) or PRIMARY_METRICS.get(str(mid).upper())
    if primary not in fields:
        primary = None
    return {"version": "source-output-1", "model_id": mid, "protocol": protocol,
            "fields": fields, "primary_metric": primary, "additional_fields": True,
            "evidence_kind": "source-contract", "evidence": evidence,
            "reference_probe": {'status': 'passed' if reference.get('ok') else 'not_executed',
                                'scope': '对应源码的参考运行，不是当前请求的测量'},
            "runtime_verified": False}


def validate_metric(mid, metric):
    schema = output_contract(mid)
    field = schema["fields"].get(metric)
    if not field:
        raise ValueError(f"{mid} 未声明指标 {metric}；可选字段: {sorted(schema['fields'])}")
    if field["type"] in {"boolean", "array", "object", "string", "null"}:
        raise ValueError(f"主要结局指标必须为数值，{metric} 类型为 {field['type']}")
    return metric
