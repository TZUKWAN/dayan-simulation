"""Lossless column archives and bounded views for large simulated populations."""
from __future__ import annotations

import base64
import math
import zlib

import numpy as np

from .limits import limits

_CODECS = {"bit-le": None, "u8": np.dtype("u1"), "i32-le": np.dtype("<i4"), "f64-le": np.dtype("<f8")}


def encode_column(values):
    low, high = float(values.min()), float(values.max())
    negative_zero = low <= 0 <= high and np.any(np.signbit(values) & (values == 0))
    if low == high and not negative_zero:
        return {"codec": "constant", "value": low}
    if low == 0 and high == 1 and not negative_zero and np.all((values == 0) | (values == 1)):
        codec, data = "bit-le", np.packbits(values.astype(np.uint8, copy=False), bitorder="little").tobytes()
    else:
        codec = "f64-le"
        if not negative_zero and -2**31 <= low <= high < 2**31 and np.all(values == np.trunc(values)):
            codec = "u8" if 0 <= low and high <= 255 else "i32-le"
        data = values.astype(_CODECS[codec], copy=False).tobytes()
    if len(data) >= 256:
        packed = zlib.compress(data, level=1)
        if len(packed) < len(data):
            return {"codec": codec, "compression": "zlib", "data": base64.b64encode(packed).decode("ascii")}
    return {"codec": codec, "data": base64.b64encode(data).decode("ascii")}


def decode_column(column, count):
    codec = column["codec"]
    if type(count) is not int or not 1 <= count <= limits().array_entities:
        raise ValueError("归档主体列规模超出当前解码预算")
    if codec == "constant":
        value = float(column["value"])
        if not math.isfinite(value) or abs(value)>1e15:
            raise ValueError("归档主体列常数非法")
        return np.broadcast_to(np.asarray(value), (count,))
    try:
        dtype = _CODECS[codec]
    except KeyError:
        raise ValueError("未知主体列编码") from None
    length = (count+7)//8 if codec == "bit-le" else count * dtype.itemsize
    data = base64.b64decode(column["data"], validate=True)
    if column.get("compression") == "zlib":
        stream = zlib.decompressobj()
        data = stream.decompress(data, length+1)
        if not stream.eof or stream.unused_data:
            raise ValueError("压缩主体列缺失、超长或含额外数据")
    elif "compression" in column:
        raise ValueError("未知主体列压缩方式")
    if len(data) != length:
        raise ValueError("主体列长度与归档规模不符")
    if codec == "bit-le":
        return np.unpackbits(np.frombuffer(data, dtype=np.uint8), count=count, bitorder="little").astype(float)
    values = np.frombuffer(data, dtype=dtype).astype(float, copy=False)
    if not np.isfinite(values).all() or np.any(np.abs(values) > 1e15):
        raise ValueError("主体列含非法数值")
    return values


def encode_population(state, primary=None):
    spec = state.settings
    columns = state.columns()
    if primary not in columns:
        primary = next(iter(columns), None)
    return {"format": "dayan-columns-v1", "count": state.count,
            "type": spec.get("type", "agent"), "color_by": primary,
            "grid": {**{k:state.grid[k] for k in ("rows", "columns")},
                     'boundary':state.grid.get('boundary','periodic'), 'degree':state.grid['degree']} if state.grid else None,
            "columns": {name: encode_column(values) for name, values in columns.items()}}


def sampled_entities(state, primary, size=640):
    """Stable IDs for the scene; every state column remains available in the archive."""
    stride = max(1, math.ceil(state.count / size))
    return [{"id": i, "type": state.settings.get("type", "agent"),
             **{name: float(values[i]) for name, values in state.values.items()},
             "state": float(state.values.get("state", state.values[primary])[i]) if primary else 0}
            for i in range(0, state.count, stride)]


def entity_at(frame, entity_id, fields=None):
    """Read a real ID from full columns; display sampling never defines existence."""
    population = frame.get('population')
    from .population_groups import is_grouped, find_entity
    if is_grouped(population):
        return find_entity(population, entity_id, fields)
    if not population:
        entity = next((item for item in frame.get('entities', []) if str(item.get('id')) == str(entity_id)), None)
        if entity is None:
            return None
        return dict(entity) if fields is None else {key:value for key,value in entity.items()
                                                    if key in {'id', 'type', *fields}}
    try:
        index = int(entity_id)
    except (TypeError, ValueError):
        return None
    if str(index) != str(entity_id) or not 0 <= index < population['count']:
        return None
    columns = population.get('columns')
    if columns is None:
        raise ValueError('主体查询需要完整归档，不能使用画面样本')
    wanted = set(columns) | {'x', 'y', 'state'} if fields is None else set(fields)
    result = {'id':index, 'type':population['type']}
    for field in wanted:
        key = field if field in columns else population.get('color_by') if field == 'state' else field
        if key in columns:
            result[field] = float(decode_column(columns[key], population['count'])[index])
        elif population.get('grid') and field in ('x', 'y'):
            width = population['grid']['columns']
            result[field] = (index % width if field == 'x' else index // width) + .5
    return result


def entity_trace(frames, entity_id, fields=None):
    """Use every retained frame and preserve gaps without interpolation."""
    return [{'sim_t':frame['sim_t'], **(entity_at(frame, entity_id, fields) or {})} for frame in frames]


def grid_preview(state, primary, label, max_side=224):
    rows, cols = state.grid["rows"], state.grid["columns"]
    values = state.values[primary].reshape(rows, cols)
    stride = math.ceil(max(rows,cols)/max_side)
    if stride == 1:
        means = values
    else:
        row, col = np.arange(0, rows, stride), np.arange(0, cols, stride)
        sums = np.add.reduceat(np.add.reduceat(values, row, axis=0), col, axis=1)
        areas = np.diff(np.r_[row,rows])[:, None] * np.diff(np.r_[col,cols])[None, :]
        means = sums / areas
    low, high = float(values.min()), float(values.max())
    if 0 <= low <= high <= 1:
        low, high = 0.0, 1.0
    intensity = np.zeros(means.shape, dtype=np.uint8)
    if high > low:
        intensity = np.rint(np.clip((means-low)/(high-low),0,1)*255).astype(np.uint8)
    return {"width": means.shape[1], "height": means.shape[0], "encoding": "u8-preview",
            "source_width": cols, "source_height": rows, "block_side": stride,
            "layers": [{"id": primary, "label": label, "states": [f"{low:g}", f"{high:g}"],
                        "values": base64.b64encode(intensity.tobytes()).decode("ascii")}]}


def playback_frame(frame, previous=None):
    if "population" not in frame:
        return frame
    from .population_analysis import frame_statistics, movement_between
    statistics = frame_statistics(frame)
    from .population_groups import is_grouped
    if is_grouped(frame['population']):
        statistics['movement'] = movement_between(frame, previous)
        public = {**frame['population'], 'groups': [
            {key: value for key, value in group.items() if key not in ('columns', 'ids')}
            for group in frame['population']['groups']]}
        return {**frame, 'population': public, 'statistics': statistics}
    if frame['population'].get('grid') or {'x','y'} <= frame['population']['columns'].keys():
        statistics['movement'] = movement_between(frame, previous)
    return {**frame, "population": {key: value for key, value in frame["population"].items() if key != "columns"},
            "statistics": statistics}
