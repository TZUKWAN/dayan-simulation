"""状态帧层（WP7 状态同源沙盘）。

state_frame() 合同：模型可选实现，返回
  {"entities": [{id, type, x, y, z?, state, ...extra}],
   "relations": [...], "facilities": [...], "aggregates": {...}}
平台在 on_step 钩子按 sample_every 采样帧；未实现 state_frame() 的模型
退回"聚合帧"（仅 aggregates，provenance=aggregate）——前端必须把聚合驱动
的动画标注为「汇总数据驱动的示意动画」，不得冒充主体轨迹。
"""
from __future__ import annotations

from typing import Any
from numbers import Integral,Real
from math import ceil


def validate_lattice(lattice):
    """Validate dense per-cell binary state without decoding each cell as an entity."""
    if not isinstance(lattice, dict):
        raise ValueError("网格状态必须为对象")
    width, height = lattice.get("width"), lattice.get("height")
    preview = lattice.get("encoding") == "u8-preview"
    edge = 224 if preview else 128
    if any(type(n) is not int or not 1 <= n <= edge for n in (width, height)):
        raise ValueError(f"网格显示边长须为1至{edge}的整数")
    if preview:
        source_width, source_height, stride = (lattice.get(k) for k in ("source_width","source_height","block_side"))
        if any(type(n) is not int or n < 1 for n in (source_width, source_height, stride)) or (
                ceil(source_width/stride), ceil(source_height/stride)) != (width,height):
            raise ValueError("网格预览的区域和显示尺寸不一致")
    layers = lattice.get("layers")
    if not isinstance(layers, list) or not 1 <= len(layers) <= 3:
        raise ValueError("网格须包含1至3个编码层")
    ids = set()
    for layer in layers:
        if not isinstance(layer, dict):
            raise ValueError("网格层必须为对象")
        key, values, states = layer.get("id"), layer.get("values"), layer.get("states")
        if not isinstance(key, str) or not key or key in ids:
            raise ValueError("网格层标识缺失或重复")
        if not isinstance(layer.get("label"), str) or not layer["label"]:
            raise ValueError("网格层名称缺失")
        if not isinstance(states, list) or len(states) != 2 or any(not isinstance(s, str) or not s for s in states):
            raise ValueError("网格层须说明二元状态含义")
        if preview:
            import base64
            if not isinstance(values, str) or len(values) != 4*ceil(width*height/3) or len(
                    base64.b64decode(values, validate=True)) != width*height:
                raise ValueError("网格预览编码与显示尺寸不符")
        elif not isinstance(values, str) or len(values) != width * height or values.count("0") + values.count("1") != len(values):
            raise ValueError("网格编码与网格尺寸或二元状态不符")
        ids.add(key)


def has_spatial_state(frame):
    return bool(frame.get("entities") or frame.get("lattice") or frame.get("population"))


def population_size(frame):
    return (frame.get("population") or {}).get("count", len(frame.get("entities") or []))


def state_frame_of(model: Any, t: float) -> dict | None:
    """未实现返回None；已实现的状态帧出错则向上传播，不伪装成成功。"""
    fn = getattr(model, "state_frame", None)
    if not callable(fn):
        return None
    fr = fn()
    if fr is None:
        return None
    return validate_state_frame(fr, t)


def validate_state_frame(fr, t, *, exact_time=False):
    """Shared validation for native hooks and decoded managed-solver frames."""
    if not isinstance(fr, dict) or "entities" not in fr:
        raise ValueError("模型state_frame()未满足实体帧合同")
    fr = dict(fr)
    import math
    from .population_groups import is_grouped, validate_groups, validate_preview
    grouped = is_grouped(fr.get('population'))
    exact_time = grouped or exact_time
    if 'sim_t' in fr and (not isinstance(fr['sim_t'],(int,float)) or
                          (fr['sim_t'] != t if exact_time else not math.isclose(fr['sim_t'],t,rel_tol=0,abs_tol=1e-8))):
        raise ValueError('模型状态帧时间与执行时钟不一致')
    fr['sim_t']=float(t) if exact_time else round(float(t),9)
    entities=fr['entities']
    if not isinstance(entities,list):raise ValueError('状态帧entities须为列表')
    from .limits import limits
    if len(entities)>limits().entities:raise ValueError('实际状态帧主体数量超过预算')
    ids=set()
    for entity in entities:
        if not isinstance(entity,dict) or not isinstance(entity.get('id'),(str,Integral)) or isinstance(entity['id'],bool):
            raise ValueError('实体须有持久字符串/整数ID')
        key=str(entity['id'])
        if key in ids:raise ValueError('状态帧实体ID重复')
        ids.add(key)
        for coordinate in ('x','y','z'):
            if coordinate in entity and (isinstance(entity[coordinate],bool) or not isinstance(entity[coordinate],Real) or not math.isfinite(entity[coordinate])):
                raise ValueError('状态帧坐标须为有限数值')
    if "lattice" in fr:
        validate_lattice(fr["lattice"])
    if grouped:
        validate_groups(fr['population'])
        validate_preview(fr['population'], entities)
    elif "population" in fr:
        population = fr["population"]
        count = population.get("count")
        columns = population.get("columns")
        grid = population.get("grid")
        if (population.get("format") != "dayan-columns-v1" or type(count) is not int
                or not 1 <= count <= limits().array_entities or not isinstance(columns,dict)
                or not 1 <= len(columns) <= 16 or population.get("color_by") not in columns):
            raise ValueError("实际全量主体列不满足归档合同")
        if grid and (grid.get("rows", 0)*grid.get("columns", 0) != count
                     or fr.get("lattice", {}).get("source_width") != grid.get("columns")
                     or fr.get("lattice", {}).get("source_height") != grid.get("rows")):
            raise ValueError("网格预览与实际主体列的尺寸不一致")
        if any(type(entity["id"]) is not int or not 0 <= entity["id"] < count for entity in entities):
            raise ValueError("主体预览必须引用实际归档主体编号")
    fr["provenance"] = "lattice" if "lattice" in fr else "entity"
    return fr


def _aggregate_frame(model: Any, t: float) -> dict:
    obs = model.observe() if hasattr(model, "observe") else {}
    agg = {k: v for k, v in (obs.items() if isinstance(obs, dict) else [])
           if isinstance(v, (int, float))}
    return {"sim_t": round(float(t), 9), "entities": [], "relations": [],
            "facilities": [], "aggregates": agg, "provenance": "aggregate"}


def collect_state_stream(model_id: str, parameters: dict | None = None,
                         ticks: int = 120, dt: float = 0.1, seed: int = 0,
                         sample_every: int = 5,
                         experiment: str = "exp0",
                         max_frames: int | None = None,
                         interventions: list | None = None) -> dict:
    """One execution produces both metrics and states; sampling only affects the view."""
    from .runtime import run_model_full
    from .run_store import state_stream
    rr = run_model_full(model_id, parameters=parameters, ticks=ticks,
                        dt=dt, seed=seed, experiment=experiment,
                        with_time=True, capture_state=True, interventions=interventions)
    if max_frames is not None:
        if max_frames < 2:
            raise ValueError("max_frames 至少为2，以保留首末状态")
        import math
        sample_every = max(sample_every, math.ceil(max(0, len(rr.state_frames)-1) / (max_frames-1)))
    return state_stream({"model_id": model_id, "run_id": rr.manifest["run_id"],
                         "manifest": rr.manifest, "observations": rr.observations,
                         "state_frames": rr.state_frames, "events": rr.events}, sample_every)


def _aggregate_frame_from_obs(observations: list) -> dict:
    """完全无钩子帧时的兜底：用观测序列构造聚合帧。"""
    frames = []
    for o in observations or []:
        if not isinstance(o, dict):
            continue
        agg = {k: v for k, v in o.items()
               if k not in ("sim_t",) and isinstance(v, (int, float))}
        frames.append({"sim_t": o.get("sim_t"), "entities": [],
                       "relations": [], "facilities": [], "aggregates": agg,
                       "provenance": "aggregate"})
    return frames[0] if frames else {"sim_t": 0.0, "entities": [],
                                     "aggregates": {}, "provenance": "aggregate"}
