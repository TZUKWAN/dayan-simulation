"""Shared, explicit execution budgets. Refusal precedes model construction."""
from __future__ import annotations
import math
import os
from dataclasses import dataclass


class BudgetExceeded(ValueError):
    pass


def _int(name, default):
    value = int(os.environ.get('DAYAN_'+name, default))
    if value <= 0:
        raise ValueError('DAYAN_'+name+'必须为正数')
    return value


@dataclass(frozen=True)
class Limits:
    concurrent: int = 2
    queued: int = 8
    ticks: int = 10000
    total_steps: int = 100000
    arms: int = 8
    seeds: int = 10
    entities: int = 5000
    frames: int = 201
    entity_frames: int = 500000
    body_bytes: int = 16*1024*1024
    run_bytes: int = 32*1024*1024
    job_bytes: int = 64*1024*1024
    data_bytes: int = 2*1024*1024*1024
    memory_bytes: int = 768*1024*1024
    cpu_seconds: int = 120
    wall_seconds: int = 240


def limits():
    return Limits(**{k: _int(k.upper(), v.default) for k, v in Limits.__dataclass_fields__.items()})


def validate_compute(ticks, *, runs=1, seeds=1, arms=0, parameters=None):
    cap=limits()
    for label,value,maximum in [('ticks',ticks,cap.ticks),('seeds',seeds,cap.seeds),('arms',arms,cap.arms)]:
        if isinstance(value,bool) or not isinstance(value,int) or not 0 <= value <= maximum:
            raise BudgetExceeded(f'{label}预算超限：须为0..{maximum}整数')
    if isinstance(runs,bool) or not isinstance(runs,int) or runs < 1 or ticks*runs > cap.total_steps:
        raise BudgetExceeded(f'总运行步数超过{cap.total_steps}预算')
    for key,value in (parameters or {}).items():
        if key in ('n','n_agents','cells','cities','nodes','n_cops','n_firms') and isinstance(value,(int,float)) and value > cap.entities:
            raise BudgetExceeded(f'{key}超过{cap.entities}主体/结构规模预算')
        if key in ('size','grid_size') and isinstance(value,(int,float)) and value*value > cap.entity_frames:
            raise BudgetExceeded('格点规模超过预算')


def frame_stride(ticks, requested=1, parameters=None):
    cap=limits();n=max([int(v) for k,v in (parameters or {}).items()
                        if k in ('n','n_agents','cells','nodes') and isinstance(v,(int,float)) and math.isfinite(v) and v>0] or [1])
    frame_cap=max(2,min(cap.frames,cap.entity_frames//n))
    return max(int(requested),math.ceil(max(1,ticks)/(frame_cap-1)))


def validate_envelope(payload):
    """Inspect nested tool/experiment envelopes before accepting a queue slot."""
    if isinstance(payload,dict):
        ticks=payload.get('ticks',0)
        seeds=payload.get('seeds',[payload.get('seed',0)])
        arms=payload.get('arms',[])
        if isinstance(seeds,list) and isinstance(arms,list):
            validate_compute(ticks,runs=max(1,len(seeds))*(len(arms)+1),seeds=len(seeds),arms=len(arms),parameters=payload.get('parameters') or payload.get('baseline_params'))
        for value in payload.values():
            if isinstance(value,(dict,list)):validate_envelope(value)
    elif isinstance(payload,list):
        if len(payload)>10000:raise BudgetExceeded('请求列表长度超过预算')
        for value in payload:
            if isinstance(value,(dict,list)):validate_envelope(value)
