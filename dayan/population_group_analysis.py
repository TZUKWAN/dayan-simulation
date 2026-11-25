"""Full heterogeneous statistics; distinct units, missingness and identities stay distinct."""
import numpy as np

from .population_groups import (decode_attribute, field_groups, field_metadata, field_values,
                                group_ids, is_grouped, type_counts)
from .solvers.codec import digest


def _single(frame, group):
    return {**frame, 'population': {**frame['population'], 'count':group['count'], 'groups':[group]}}


def _concat(arrays):
    return np.ma.concatenate(arrays) if any(np.ma.isMaskedArray(raw) for raw in arrays) else np.concatenate(arrays)


def _position_unit(group):
    if not {'x','y'} <= group['columns'].keys():
        raise ValueError('该人口组没有完整二维位置：'+group['id'])
    x, y = group['units'].get('x'), group['units'].get('y')
    if x is None or x != y:
        raise ValueError('人口坐标单位未知或不一致：'+group['id'])
    return x


def _mask(frame, group, region):
    from .population_analysis import _region_mask
    unit = _position_unit(group)
    if frame.get('space', {}).get('unit') not in (None, unit):
        raise ValueError('选区与实际人口坐标的单位不一致：'+group['id'])
    return _region_mask(_single(frame, group), region)


def distribution(frame, field, region=None):
    from .population_analysis import _cached, _numbers
    population = frame['population']
    if field in ('type', 'group'):
        counts, not_spatial = {}, 0
        for group in population['groups']:
            name = group['type'] if field == 'type' else group['id']
            if region is not None and not {'x','y'} <= group['columns'].keys():
                not_spatial += group['count']
                continue
            count = group['count'] if region is None else int(_mask(frame, group, region).sum())
            counts[name] = counts.get(name, 0) + count
        return {'field':field, 'n':sum(counts.values()), 'missing':0, 'counts':counts, 'scope':'full_population',
                'not_spatial':not_spatial, 'population_count':population['count']}
    selected = field_groups(population, field)
    evidence = [{'id':g['id'], 'count':g['count'], 'unit':g['units'][name],
                 'columns':{key:g['columns'].get(key) for key in ({name,'x','y'} if region else {name})}}
                 for g,name in selected]
    key = digest(['groups-distribution-v1', field, population['count'], evidence, region, frame.get('space')])
    def compute():
        arrays = []
        for group, name in selected:
            raw = decode_attribute(group['columns'][name], group['count'])
            arrays.append(raw if region is None else raw[_mask(frame, group, region)])
        return {**_numbers(_concat(arrays), field), **field_metadata(population, field), 'scope':'full_population'}
    return _cached(key, compute)


def spatial_density(frame, bins=(44,44)):
    from .population_analysis import _cached
    population = frame['population']
    selected = [group for group in population['groups'] if {'x','y'} <= group['columns'].keys()]
    if not selected:
        raise ValueError('完整人口没有可定位的二维主体组')
    units = {_position_unit(group) for group in selected}
    if len(units) != 1 or frame.get('space', {}).get('unit') not in (None, *units):
        raise ValueError('不同坐标单位不能合并成同一密度图')
    count = sum(group['count'] for group in selected)
    evidence = [{key:group[key] for key in ('id','count','units')} | {'x':group['columns']['x'],'y':group['columns']['y']}
                for group in selected]
    bounds = frame.get('space', {}).get('bounds')
    def compute():
        x,y = [np.concatenate([decode_attribute(group['columns'][field], group['count']) for group in selected]) for field in ('x','y')]
        ranges = [[bounds[0],bounds[2]],[bounds[1],bounds[3]]] if bounds and len(bounds)==4 else None
        counts,xs,ys = np.histogram2d(x,y,bins=bins,range=ranges)
        inside = int(counts.sum())
        return {'counts':counts.T.astype(np.int64).tolist(), 'x_edges':xs.tolist(), 'y_edges':ys.tolist(),
                'n':count, 'count_in_bounds':inside, 'outside_bounds':count-inside, 'scope':'full_population',
                'population_count':population['count'], 'not_spatial':population['count']-count, 'unit':next(iter(units))}
    return _cached(digest(['groups-density-v1', population['count'], evidence, list(bins), bounds]), compute)


def _pairs(current, previous):
    a, b = current['ids'], previous['ids']
    if a['kind'] == b['kind'] == 'range':
        start = max(a['start'], b['start'])
        end = min(a['start']+current['count'], b['start']+previous['count'])
        count = max(0, end-start)
        return np.arange(count)+start-a['start'], np.arange(count)+start-b['start']
    if a == b:
        return np.arange(current['count']), np.arange(previous['count'])
    old = {str(value):i for i,value in enumerate(group_ids(previous))}
    matched = [(i,old[str(value)]) for i,value in enumerate(group_ids(current)) if str(value) in old]
    return tuple(np.array([pair[i] for pair in matched],dtype=np.int64) for i in (0,1))


def movement_between(frame, previous):
    from .population_analysis import _cached
    empty = {'comparable':0, 'moved':None, 'stationary':None, 'meanDistance':None, 'scope':'full_population'}
    if not previous or not is_grouped(previous.get('population')):
        return empty
    def evidence(source):
        return [{'id':g['id'], 'ids':g['ids'], 'count':g['count'], 'units':g['units'],
                 'columns':{field:g['columns'].get(field) for field in ('x','y','z')}} for g in source['population']['groups']]
    def compute():
        old = {g['id']:g for g in previous['population']['groups']}
        groups, unavailable = [], []
        current_keys = {group['id'] for group in frame['population']['groups']}
        exited = sum(group['count'] for group in old.values() if group['id'] not in current_keys)
        for group in frame['population']['groups']:
            prior = old.get(group['id'])
            if prior is None:
                groups.append({'group':group['id'], 'comparable':0, 'entered':group['count'], 'exited':0,
                               'moved':0,'stationary':0,'distance_sum':0,'unit':None})
                continue
            new_indices, old_indices = _pairs(group,prior)
            try:
                unit = _position_unit(group)
                if unit != _position_unit(prior):
                    raise ValueError('前后帧位置单位已变化')
            except ValueError as exc:
                unavailable.append({'group':group['id'], 'reason':str(exc)})
                groups.append({'group':group['id'], 'comparable':0, 'moved':0,'stationary':0,
                               'distance_sum':0,'unit':None, 'entered':group['count']-len(new_indices),
                               'exited':prior['count']-len(old_indices)})
                continue
            dimensions=('x','y','z') if ('z' in group['columns'] and 'z' in prior['columns']
                and group['units'].get('z')==unit and prior['units'].get('z')==unit) else ('x','y')
            delta = [decode_attribute(group['columns'][field],group['count'])[new_indices]
                     - decode_attribute(prior['columns'][field],prior['count'])[old_indices] for field in dimensions]
            distances = np.sqrt(sum(value*value for value in delta))
            count = len(distances)
            moved = int(np.count_nonzero(distances > 1e-9))
            groups.append({'group':group['id'], 'comparable':count, 'moved':moved, 'stationary':count-moved,
                           'distance_sum':float(distances.sum()), 'unit':unit,'dimensions':list(dimensions),
                           'entered':group['count']-count, 'exited':prior['count']-count})
        count = sum(row['comparable'] for row in groups)
        units = {row['unit'] for row in groups if row['comparable']}
        total = sum(row['distance_sum'] for row in groups)
        return {**empty, 'comparable':count, 'moved':sum(row['moved'] for row in groups) if count else None,
                'stationary':sum(row['stationary'] for row in groups) if count else None,
                'meanDistance':total/count if count and len(units)==1 else None,
                'unit':next(iter(units)) if len(units)==1 else None, 'groups':groups, 'unavailable':unavailable,
                'entered':sum(row['entered'] for row in groups), 'exited':exited+sum(row['exited'] for row in groups)}
    return {**_cached(digest(['groups-movement-v1',evidence(frame),evidence(previous)]),compute),
            'from':previous['sim_t'], 'to':frame['sim_t']}


def frame_statistics(frame, fields=None, region=None):
    population = frame['population']
    if fields is None:
        fields = ['group', 'type', *[group['id']+'.'+field for group in population['groups'] for field in group['columns']]]
    distributions = {field:distribution(frame,field,region) for field in dict.fromkeys(fields)}
    result = {'scope':'full_population', 'count':population['count'], 'sim_t':frame['sim_t'], 'region':region,
              'distributions':distributions, 'types':type_counts(population),
              'groups':[{key:group[key] for key in ('id','type','label','count','units','color_by')} for group in population['groups']]}
    try:
        result['density'] = spatial_density(frame)
    except ValueError as exc:
        result['density_unavailable'] = str(exc)
    return result
