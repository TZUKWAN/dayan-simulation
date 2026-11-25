"""Complete heterogeneous populations with typed columns and persistent identities."""
from collections import Counter
import math
import re

import numpy as np

from .limits import limits
from .solvers.codec import decode, encode

FORMAT = "dayan-populations-v1"
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_\-]{0,63}\Z")


def is_grouped(population):
    return isinstance(population, dict) and population.get("format") == FORMAT


def _column(raw):
    if np.ma.isMaskedArray(raw):
        raw = raw.tolist()
    values = np.asarray(raw)
    if values.ndim != 1:
        raise ValueError("人口属性必须是一维列；多维场应保存在独立场状态中")
    if values.dtype.kind in "biuf":
        return {"kind": "numeric", "data": encode(values)}, len(values)
    items = [item.item() if isinstance(item, np.generic) else item for item in raw]
    valid = [item for item in items if item is not None]
    if values.dtype.kind not in 'US' and all(type(item) in (int, float, bool) and math.isfinite(item) for item in valid):
        return {"kind": "nullable_numeric", "data": encode(np.array([0. if item is None else item for item in items])),
                "valid": encode(np.array([item is not None for item in items], dtype=bool))}, len(items)
    if not all(isinstance(item, str) for item in valid):
        raise ValueError("人口列须为有限数字、字符串类别或显式空值，不能混合不同属性类型")
    labels = list(dict.fromkeys(items))
    index = {label: i for i, label in enumerate(labels)}
    return {"kind": "categorical", "labels": labels,
            "codes": encode(np.array([index[item] for item in items], dtype=np.int64))}, len(items)


def decode_attribute(column, count):
    kind = column.get("kind")
    if kind in ("numeric", "nullable_numeric"):
        raw = decode(column["data"])
        if not isinstance(raw, np.ndarray) or raw.ndim != 1 or len(raw) != count or raw.dtype.kind not in "biuf":
            raise ValueError("完整人口数值列尺寸或dtype不一致")
        if kind == "nullable_numeric":
            valid = decode(column["valid"])
            if not isinstance(valid, np.ndarray) or valid.dtype.kind != "b" or valid.shape != raw.shape:
                raise ValueError("完整人口缺失掩码与属性不一致")
            return np.ma.array(raw, mask=~valid)
        return raw
    if kind == "categorical":
        labels, codes = column["labels"], decode(column["codes"])
        if (not isinstance(labels, list) or any(label is not None and not isinstance(label, str) for label in labels)
                or len(set(labels)) != len(labels) or not isinstance(codes, np.ndarray) or codes.ndim != 1
                or len(codes) != count or codes.dtype.kind not in "iu"
                or len(codes) and (codes.min() < 0 or codes.max() >= len(labels))):
            raise ValueError("完整人口类别列编码不一致")
        return np.asarray(labels, dtype=object)[codes]
    raise ValueError("未知完整人口属性编码")


def _ids(raw, count):
    if raw is None:
        return {"kind": "range", "start": 0, "count": count}
    items = raw.tolist() if isinstance(raw, np.ndarray) else list(raw)
    if (len(items) != count or any(type(item) not in (int, str) or not str(item) for item in items)
            or len({str(item) for item in items}) != count):
        raise ValueError("每个人口组必须有唯一、持久且与实际列数一致的字符串/整数ID")
    if items and all(type(item) is int and item == items[0] + i for i, item in enumerate(items)):
        return {"kind": "range", "start": items[0], "count": count}
    return {"kind": "explicit", "values": items}


def group_ids(group):
    spec = group["ids"]
    if spec["kind"] == "range":
        return range(spec["start"], spec["start"] + group["count"])
    return spec["values"]


def encode_groups(groups):
    """Accept actual column arrays, never inflate a displayed sample to full size."""
    if not isinstance(groups, (list, tuple)) or not groups:
        raise ValueError("完整人口须显式声明一个或多个人口组，可声明空组")
    packed, names, total = [], set(), 0
    for group in groups:
        key, kind = group.get("id"), group.get("type")
        columns = group.get("columns")
        if (not isinstance(key, str) or not NAME.fullmatch(key) or key in names
                or not isinstance(kind, str) or not kind or not isinstance(columns, dict) or not columns):
            raise ValueError("人口组缺少唯一id、类型或完整属性列")
        names.add(key)
        encoded, counts = {}, set()
        for field, raw in columns.items():
            if not isinstance(field, str) or not NAME.fullmatch(field) or field in ("id", "type", "group", "local_id"):
                raise ValueError("人口属性名非法或覆盖身份字段")
            column, count = _column(raw)
            encoded[field] = column
            counts.add(count)
            if field in ("x", "y", "z") and column["kind"] != "numeric":
                raise ValueError("空间坐标必须是完整有限数值，不能以空值或类别替代")
        if len(counts) != 1:
            raise ValueError("同一人口组的各属性列长度必须完全相等")
        count = counts.pop()
        if "count" in group and (type(group["count"]) is not int or group["count"] != count):
            raise ValueError("人口组声明数量与实际属性列数不一致")
        total += count
        if total > limits().array_entities:
            raise ValueError("实际完整人口总数超出当前容量预算，未截断或采样人口")
        units = group.get("units") or {}
        if (not isinstance(units, dict) or set(units) - set(columns)
                or any(value is not None and (not isinstance(value, str) or not value.strip()) for value in units.values())):
            raise ValueError("人口单位须对应实际属性，未知单位应明确为空")
        primary = group.get("color_by")
        if primary is not None and primary not in encoded:
            raise ValueError("人口显示主字段须为实际属性")
        packed.append({"id": key, "type": kind, "label": str(group.get("label") or key), "count": count,
                       "ids": _ids(group.get("ids"), count), "columns": encoded,
                       "units": {field: units.get(field) for field in columns}, "color_by": primary})
    return {"format": FORMAT, "count": total, "groups": packed}


def validate_groups(population):
    if not is_grouped(population) or not isinstance(population.get("groups"), list) or not population["groups"]:
        raise ValueError("多人口归档格式不合法")
    seen, total = set(), 0
    for group in population["groups"]:
        key, count = group.get("id"), group.get("count")
        if (not isinstance(key, str) or not NAME.fullmatch(key) or key in seen or type(count) is not int or count < 0
                or not isinstance(group.get("type"), str) or not group["type"]):
            raise ValueError("多人口归档的身份或数量非法")
        seen.add(key)
        total += count
        if total > limits().array_entities:
            raise ValueError("完整人口总数超出解码预算")
        spec = group["ids"]
        if spec.get("kind") == "range":
            if type(spec.get("start")) is not int or spec.get("count") != count:
                raise ValueError("人口连续ID与实际数量不一致")
        elif spec.get("kind") == "explicit":
            _ids(spec["values"], count)
        else:
            raise ValueError("人口ID编码不合法")
        columns = group.get("columns")
        if not isinstance(columns, dict) or not columns:
            raise ValueError("完整人口归档缺少属性列")
        units = group.get("units")
        if (not isinstance(units, dict) or set(units) != set(columns)
                or any(unit is not None and (not isinstance(unit, str) or not unit.strip()) for unit in units.values())):
            raise ValueError("完整人口归档单位与实际属性不一致")
        if group.get("color_by") is not None and group["color_by"] not in columns:
            raise ValueError("完整人口显示主字段不存在")
        for field, column in columns.items():
            if not isinstance(field, str) or not NAME.fullmatch(field) or field in ("id", "type", "group", "local_id"):
                raise ValueError("人口归档字段名非法")
            decode_attribute(column, count)
            if field in ("x", "y", "z") and column.get("kind") != "numeric":
                raise ValueError("空间坐标须为完整数值列")
    if type(population.get("count")) is not int or population["count"] != total:
        raise ValueError("完整人口总数与分组数量不一致")
    return population


def find_entity(population, entity_id, fields=None):
    """Qualified group:local_id is durable across frame reordering, births and exits."""
    text = str(entity_id)
    if ":" not in text:
        if len(population["groups"]) != 1:
            raise ValueError("多个主体组须使用组名:主体ID，不能按显示顺序猜测身份")
        key, local = population["groups"][0]["id"], text
    else:
        key, local = text.split(":", 1)
    group = next((item for item in population["groups"] if item["id"] == key), None)
    if group is None:
        return None
    spec = group["ids"]
    if spec["kind"] == "range":
        try:
            index = int(local) - spec["start"]
        except ValueError:
            return None
        if str(index + spec["start"]) != local or not 0 <= index < group["count"]:
            return None
        native_id = index + spec["start"]
    else:
        index = next((i for i, value in enumerate(spec["values"]) if str(value) == local), None)
        if index is None:
            return None
        native_id = spec["values"][index]
    result = {"id": key + ":" + str(native_id), "local_id": native_id, "group": key, "type": group["type"]}
    for field in group["columns"] if fields is None else fields:
        if field not in group["columns"]:
            continue
        value = decode_attribute(group["columns"][field], group["count"])[index]
        result[field] = None if np.ma.is_masked(value) else value.item() if isinstance(value, np.generic) else value
    return result


def sample_entities(population, size=640):
    """Bounded stratified view; the population archive and statistics stay complete."""
    if type(size) is not int or size < 1:
        raise ValueError("显示样本预算必须为正整数")
    groups = [group for group in population["groups"] if group["count"]]
    if len(groups) > size:
        raise ValueError("显示预算不足以表示每个人口组；须选择分组视图，不能静默隐藏主体类型")
    total = population["count"]
    allocation = {group["id"]: 1 for group in groups}
    remaining = min(size, total) - len(groups)
    # Largest deficit allocation preserves rare groups without exceeding size.
    while remaining:
        group = max((group for group in groups if allocation[group["id"]] < group["count"]),
                    key=lambda group: min(size, total) * group["count"] / total - allocation[group["id"]])
        allocation[group["id"]] += 1
        remaining -= 1
    result = []
    for group in groups:
        picks = np.linspace(0, group["count"] - 1, allocation[group["id"]], dtype=np.int64)
        columns = {name: decode_attribute(column, group["count"]) for name, column in group["columns"].items()}
        ids = group_ids(group)
        for index in picks:
            native_id = ids[int(index)]
            item = {"id": group["id"] + ":" + str(native_id), "local_id": native_id,
                    "group": group["id"], "type": group["type"]}
            for field, column in columns.items():
                value = column[index]
                item[field] = None if np.ma.is_masked(value) else value.item() if isinstance(value, np.generic) else value
            result.append(item)
    return result


def field_groups(population, field):
    key, name = field.split(".", 1) if "." in field else (None, field)
    selected = [(group, name) for group in population["groups"] if (key is None or group["id"] == key) and name in group["columns"]]
    if not selected:
        raise ValueError("完整人口没有属性：" + field)
    if len(selected) > 1:
        units = [group["units"][name] for group, name in selected]
        kinds = {group["columns"][name]["kind"] == "categorical" for group, name in selected}
        if None in units or len(set(units)) != 1 or len(kinds) != 1:
            raise ValueError("同名属性的单位未知/不一致或类型不同，请用组名.属性分别分析：" + field)
        # Categorical codes are decoded to original labels, never pooled by code.
    return selected


def field_values(population, field):
    selected = field_groups(population, field)
    arrays = [decode_attribute(group["columns"][name], group["count"]) for group, name in selected]
    return np.ma.concatenate(arrays) if any(np.ma.isMaskedArray(raw) for raw in arrays) else np.concatenate(arrays)


def field_metadata(population, field):
    selected = field_groups(population, field)
    count = sum(group["count"] for group, _ in selected)
    return {"groups": [group["id"] for group, _ in selected], "unit": selected[0][0]["units"][selected[0][1]],
            "population_count": population["count"], "applicable_count": count,
            "not_applicable": population["count"] - count}


def type_counts(population):
    result = Counter()
    for group in population["groups"]:
        result[group["type"]] += group["count"]
    return dict(result)


def validate_preview(population, entities):
    """Validate selected rows against complete columns, decoding each column once."""
    pending = {}
    for entity in entities:
        key, separator, local = str(entity['id']).partition(':')
        if not separator:
            raise ValueError('多人口显示样本须保留组名:实际ID')
        pending.setdefault(key, []).append((local, entity))
    groups = {group['id']:group for group in population['groups']}
    for key, rows in pending.items():
        if key not in groups:
            raise ValueError('显示样本引用不存在的人口组')
        group = groups[key]
        wanted = {local for local, _ in rows}
        if group['ids']['kind'] == 'range':
            first = group['ids']['start']
            indices = {text:(int(text)-first,int(text)) for text in wanted
                       if re.fullmatch(r'-?(?:0|[1-9][0-9]*)',text) and str(int(text))==text
                       and first <= int(text) < first+group['count']}
        else:
            indices = {str(value):(i,value) for i,value in enumerate(group['ids']['values']) if str(value) in wanted}
        fields = set().union(*(set(entity) for _,entity in rows)) - {'id','type','group','local_id'}
        if fields - set(group['columns']):
            raise ValueError('显示样本添加了未归档的人口属性')
        columns = {name:decode_attribute(group['columns'][name],group['count']) for name in fields}
        for local, entity in rows:
            if local not in indices:
                raise ValueError('显示样本中的主体不在完整归档中')
            index,native_id = indices[local]
            actual = {'id':key+':'+str(native_id),'type':group['type'],'group':key,'local_id':native_id}
            for name,column in columns.items():
                value=column[index]
                actual[name]=None if np.ma.is_masked(value) else value.item() if isinstance(value,np.generic) else value
            if any(actual[name] != value for name,value in entity.items()):
                raise ValueError('显示样本的身份、坐标或属性与完整归档不一致')
