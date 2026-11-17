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


def state_frame_of(model: Any, t: float) -> dict | None:
    """未实现返回None；已实现的状态帧出错则向上传播，不伪装成成功。"""
    fn = getattr(model, "state_frame", None)
    if not callable(fn):
        return None
    fr = fn()
    if fr is None:
        return None
    if not isinstance(fr, dict) or "entities" not in fr:
        raise ValueError("模型state_frame()未满足实体帧合同")
    fr = dict(fr)
    import math
    if 'sim_t' in fr and (not isinstance(fr['sim_t'],(int,float)) or not math.isclose(fr['sim_t'],t,rel_tol=0,abs_tol=1e-8)):
        raise ValueError('模型状态帧时间与执行时钟不一致')
    fr['sim_t']=round(float(t),9)
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
    fr["provenance"] = "entity"
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
