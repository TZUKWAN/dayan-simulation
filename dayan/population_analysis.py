"""Bounded statistics computed from every archived individual, never scene samples."""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
import threading

import numpy as np

from .population import decode_column

_CACHE = OrderedDict()
_LOCK = threading.Lock()
_PROBABILITIES = np.array([0, .05, .25, .5, .75, .95, 1])


def values(frame, field):
    population = frame['population']
    from .population_groups import is_grouped, field_values
    if is_grouped(population):
        return field_values(population, field)
    columns = population.get('columns')
    if columns is None:
        raise ValueError('全量统计需要完整状态列，不能从显示样本推算')
    key = field if field in columns else population.get('color_by') if field == 'state' else field
    if key in columns:
        return decode_column(columns[key], population['count'])
    if field in ('x', 'y') and population.get('grid'):
        ids = np.arange(population['count'])
        width = population['grid']['columns']
        return (ids % width if field == 'x' else ids // width).astype(float) + .5
    raise ValueError('完整归档没有主体字段：' + str(field))


def _key(frame, fields, extra):
    population = frame['population']
    digest = hashlib.sha256(json.dumps([population['count'], population.get('grid'), fields, extra],
                                       ensure_ascii=False, sort_keys=True).encode())
    for field in fields:
        key = field if field in population['columns'] else population.get('color_by') if field == 'state' else field
        digest.update(json.dumps(population['columns'].get(key), sort_keys=True, separators=(',', ':')).encode())
    return digest.hexdigest()


def _cached(key, compute):
    # Only small results are retained. No full state arrays or encoded columns
    # are captured by cache keys, avoiding multi-run memory accumulation.
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return deepcopy(_CACHE[key])
    result = compute()
    with _LOCK:
        _CACHE[key] = result
        _CACHE.move_to_end(key)
        while len(_CACHE) > 128:
            _CACHE.popitem(last=False)
    return deepcopy(result)


def _numbers(raw, field):
    mask = np.ma.getmaskarray(raw)
    raw = np.asarray(raw.data if np.ma.isMaskedArray(raw) else raw)
    original_count = len(raw)
    if raw.dtype.kind not in 'biuf':
        from collections import Counter
        items = [str(item) for item, missing in zip(raw, mask) if not missing and item is not None]
        return {'field':field, 'n':len(items), 'missing':original_count-len(items),
                'counts':dict(Counter(items)), 'kind':'categorical'}
    raw = raw[~mask & np.isfinite(raw)]
    count = len(raw)
    if not count:
        return {'field':field, 'n':0, 'missing':original_count, 'cdf':[], 'quantiles':{}}
    distinct, frequencies = np.unique(raw, return_counts=True)
    cumulative = np.cumsum(frequencies)
    positions = (count - 1) * _PROBABILITIES
    low, high = positions.astype(np.int64), np.ceil(positions).astype(np.int64)
    # Exact ordinary (linear) order-statistic quantiles, using compressed counts.
    a = distinct[np.searchsorted(cumulative, low + 1)]
    b = distinct[np.searchsorted(cumulative, high + 1)]
    quantiles = a.astype(float) + (b.astype(float) - a.astype(float)) * (positions - low)
    picks = np.unique(np.linspace(0, len(distinct)-1, min(129, len(distinct)), dtype=np.int64))
    return {'field':field, 'n':count, 'missing':original_count-count, 'min':float(distinct[0]), 'max':float(distinct[-1]),
            'mean':float(np.mean(raw)), 'zero_count':int(np.count_nonzero(raw == 0)),
            'quantiles':{f'{p:g}':float(v) for p,v in zip(_PROBABILITIES, quantiles)},
            'quantile_method':'linear',
            'cdf':[[float(distinct[i]), float(cumulative[i] / count)] for i in picks],
            'cdf_complete':len(picks) == len(distinct), 'cdf_source_count':count,
            **({'counts':{str(int(v)) if isinstance(v,(int,np.integer,np.bool_)) or float(v).is_integer() else repr(float(v)):int(n)
                          for v,n in zip(distinct, frequencies)}} if len(distinct) <= 64 else {})}


def distribution(frame, field, region=None):
    population = frame['population']
    from .population_groups import is_grouped
    if is_grouped(population):
        from .population_group_analysis import distribution as grouped_distribution
        return grouped_distribution(frame, field, region)
    if field == 'type' and field not in population['columns']:
        count = population['count'] if region is None else int(_region_mask(frame, region).sum())
        return {'field':'type', 'n':count, 'missing':0, 'counts':{population['type']:count}}
    def compute():
        raw = values(frame, field)
        return _numbers(raw if region is None else raw[_region_mask(frame, region)], field)
    fields = [field, 'x', 'y'] if region is not None else [field]
    return _cached(_key(frame, fields, ['distribution-v1', region, frame.get('space', {}).get('bounds')]), compute)


def _region_mask(frame, region):
    if (not isinstance(region, (list, tuple)) or len(region) != 4 or
            any(isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value) for value in region)):
        raise ValueError('选区需要四个有限边界数值')
    x0,y0,x1,y1 = region
    if x0 >= x1 or y0 >= y1:
        raise ValueError('选区边界须从小到大')
    x,y = values(frame, 'x'), values(frame, 'y')
    boundary = frame.get('space', {}).get('bounds') or []
    right = x <= x1 if len(boundary) == 4 and x1 == boundary[2] else x < x1
    top = y <= y1 if len(boundary) == 4 and y1 == boundary[3] else y < y1
    return (x >= x0) & right & (y >= y0) & top


def spatial_density(frame, bins=(44, 44)):
    from .population_groups import is_grouped
    if is_grouped(frame['population']):
        from .population_group_analysis import spatial_density as grouped_density
        return grouped_density(frame, bins)
    bounds = frame.get('space', {}).get('bounds')
    def compute():
        x,y = values(frame, 'x'), values(frame, 'y')
        ranges = [[bounds[0], bounds[2]], [bounds[1], bounds[3]]] if bounds and len(bounds) == 4 else None
        counts, xs, ys = np.histogram2d(x, y, bins=bins, range=ranges)
        inside = int(counts.sum())
        return {'counts':counts.T.astype(np.int64).tolist(), 'x_edges':xs.tolist(), 'y_edges':ys.tolist(),
                'n':len(x), 'count_in_bounds':inside, 'outside_bounds':len(x)-inside, 'scope':'full_population'}
    return _cached(_key(frame, ['x', 'y'], ['density-v1', list(bins), bounds]), compute)


def movement_between(frame, previous):
    from .population_groups import is_grouped
    if is_grouped(frame['population']):
        from .population_group_analysis import movement_between as grouped_movement
        return grouped_movement(frame, previous)
    if not previous or not previous.get('population'):
        return {'comparable':0, 'moved':None, 'stationary':None, 'meanDistance':None, 'scope':'full_population'}
    fields = ['x','y']
    key = _key(frame, fields, ['movement-v1', _key(previous, fields, None)])
    def compute():
        count = min(frame['population']['count'], previous['population']['count'])
        distance = np.hypot(values(frame,'x')[:count]-values(previous,'x')[:count],
                            values(frame,'y')[:count]-values(previous,'y')[:count])
        moved = int(np.count_nonzero(distance > 1e-9))
        return {'comparable':count, 'moved':moved, 'stationary':count-moved,
                'meanDistance':float(distance.mean()) if count else None, 'scope':'full_population'}
    return {**_cached(key, compute), 'from':previous['sim_t'], 'to':frame['sim_t']}


def frame_statistics(frame, fields=None, region=None):
    population = frame['population']
    from .population_groups import is_grouped
    if is_grouped(population):
        from .population_group_analysis import frame_statistics as grouped_statistics
        return grouped_statistics(frame, fields, region)
    fields = list(dict.fromkeys(fields or population['columns']))
    distributions = {field:distribution(frame, field, region) for field in fields}
    primary = population.get('color_by')
    if 'state' not in distributions and primary in distributions:
        distributions['state'] = {**distributions[primary], 'field':'state'}
    result = {'scope':'full_population', 'count':population['count'], 'sim_t':frame['sim_t'],
              'region':region, 'distributions':distributions}
    if not population.get('grid') and {'x', 'y'} <= population['columns'].keys():
        result['density'] = spatial_density(frame)
    return result
