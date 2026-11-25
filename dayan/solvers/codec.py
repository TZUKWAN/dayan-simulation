"""Lossless JSON numerical state; no pickle, object dtype or executable payloads."""
import base64
import hashlib
import json
import math

import numpy as np

ARRAY = "__dayan_ndarray__"
MASKED = "__dayan_masked_array__"


def _pack_array(value):
    if value.dtype.kind not in "biufc":
        raise ValueError("数值数组不能使用对象或字符串dtype")
    return {"dtype": value.dtype.str, "shape": list(value.shape),
            "data": base64.b64encode(np.ascontiguousarray(value).tobytes()).decode("ascii")}


def _unpack_array(spec):
    if not isinstance(spec, dict) or set(spec) != {"dtype", "shape", "data"}:
        raise ValueError("数值数组编码字段不合法")
    dtype, shape = np.dtype(spec["dtype"]), spec["shape"]
    if (dtype.kind not in "biufc" or not isinstance(shape, list) or len(shape) > 16
            or any(type(size) is not int or size < 0 for size in shape)):
        raise ValueError("数值数组dtype/shape不合法")
    raw = base64.b64decode(spec["data"], validate=True)
    if math.prod(shape) * dtype.itemsize != len(raw):
        raise ValueError("数值数组声明尺寸与实际字节不一致")
    return np.frombuffer(raw, dtype=dtype).reshape(shape).copy()


def encode(value):
    if np.ma.isMaskedArray(value):
        data, mask = np.asarray(value.data), np.ma.getmaskarray(value)
        if data.dtype.kind not in "biufc" or not (np.isfinite(data) | mask).all():
            raise ValueError("非有限数值必须具有显式缺失掩码")
        return {MASKED: {"data": _pack_array(data), "mask": _pack_array(mask),
                         "fill": _pack_array(np.asarray(value.fill_value)), "hardmask": bool(value.hardmask)}}
    if isinstance(value, np.ndarray):
        if value.dtype.kind not in "biufc" or not np.isfinite(value).all():
            raise ValueError("求解器数值数组必须为有限数值，不能使用对象或字符串dtype")
        return {ARRAY: _pack_array(value)}
    if isinstance(value, np.generic):
        return encode(value.item())
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, (list, tuple)):
        return [encode(item) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) and key not in (ARRAY, MASKED) for key in value):
        return {key: encode(item) for key, item in value.items()}
    raise ValueError("求解器状态包含不能无损归档的类型或非有限数值：" + type(value).__name__)


def decode(value):
    if isinstance(value, dict):
        if MASKED in value:
            spec = value[MASKED]
            if set(value) != {MASKED} or not isinstance(spec, dict) or set(spec) != {"data", "mask", "fill", "hardmask"}:
                raise ValueError("缺失掩码数组字段不合法")
            data, mask, fill = (_unpack_array(spec[key]) for key in ("data", "mask", "fill"))
            if (mask.shape != data.shape or mask.dtype.kind != "b" or fill.shape != ()
                    or type(spec["hardmask"]) is not bool or not (np.isfinite(data) | mask).all()):
                raise ValueError("数组数据、缺失掩码或填充值不一致")
            return np.ma.array(data, mask=mask, fill_value=fill.item(), hard_mask=spec["hardmask"])
        if ARRAY in value:
            if set(value) != {ARRAY}:
                raise ValueError("数值数组编码字段不合法")
            result = _unpack_array(value[ARRAY])
            if not np.isfinite(result).all():
                raise ValueError("数值数组包含非有限状态")
            return result
        return {key: decode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decode(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("JSON包含非有限数值")
    return value


def dumps(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(dumps(value).encode("utf-8")).hexdigest()
