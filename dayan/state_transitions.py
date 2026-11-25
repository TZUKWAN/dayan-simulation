"""State counts and endpoint transitions from complete archived identities."""
from collections import defaultdict
import json

import numpy as np

from .population import decode_column
from .population_group_analysis import _pairs
from .population_groups import is_grouped
from .solvers.codec import decode
from .view_analysis import number


def _groups(frame):
    population = frame.get('population')
    if is_grouped(population):
        if any('columns' not in group or 'ids' not in group for group in population['groups']):
            raise ValueError('状态流需要完整人口归档，不能读取显示样本')
        return {group['id']: {**group, 'scope': 'full_population'} for group in population['groups']}
    if population:
        if 'columns' not in population:
            raise ValueError('状态流需要完整状态列，不能读取显示样本')
        return {'population': {'id': 'population', 'label': population['type'], 'type': population['type'],
            'count': population['count'], 'ids': {'kind': 'range', 'start': 0, 'count': population['count']},
            'columns': population['columns'], 'scope': 'full_population', 'legacy_columns': True, 'units': {}}}
    groups = defaultdict(list)
    for entity in frame.get('entities') or []:
        groups[str(entity.get('type') or 'agent')].append(entity)
    return {key: {'id': key, 'label': key, 'type': key, 'count': len(items),
            'ids': {'kind': 'explicit', 'values': [str(item['id']) for item in items]},
            'columns': {'state': [item.get('state') for item in items]} if any('state' in item for item in items) else {},
            'scope': 'archived_entities', 'legacy_entities': True, 'units': {}}
            for key, items in groups.items()}


def _fields(group):
    fields = {name for name, column in group['columns'].items()
              if name == 'state' or isinstance(column, dict) and column.get('kind') == 'categorical'}
    # Presentation color is not a scientific state variable.
    return fields


def _key(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _codes(group, field):
    if group is None:
        return [], np.array([], dtype=np.int64)
    column = group['columns'].get(field)
    if column is None:
        return [None], np.zeros(group['count'], dtype=np.int64)
    if group.get('legacy_entities'):
        labels = list(dict.fromkeys(column))
        index = {_key(value): i for i, value in enumerate(labels)}
        return labels, np.array([index[_key(value)] for value in column], dtype=np.int64)
    if isinstance(column, dict) and column.get('kind') == 'categorical':
        raw = decode(column['codes'])
        used, codes = np.unique(raw, return_inverse=True)
        return [column['labels'][i] for i in used], codes
    if group.get('legacy_columns'):
        raw = decode_column(column, group['count'])
        valid = np.isfinite(raw)
    else:
        raw = decode(column['data'])
        valid = decode(column['valid']) if column['kind'] == 'nullable_numeric' else np.ones(len(raw), dtype=bool)
    labels, inverse = np.unique(raw[valid], return_inverse=True)
    codes = np.full(group['count'], len(labels), dtype=np.int64)
    codes[valid] = inverse
    return labels.tolist() + ([None] if not np.all(valid) else []), codes


def _node(value, present=True):
    return {'present': bool(present), 'state': value}


def state_history(frames):
    """Counts are exact for archived scope; paths between saved times are unknown."""
    times = [frame.get('sim_t') for frame in frames]
    if any(not number(t) for t in times) or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError('状态流需要严格递增的有限归档时刻，不能推断重复或倒序帧')
    grouped = [_groups(frame) for frame in frames]
    definitions = {}
    for groups in grouped:
        for group in groups.values():
            for field in sorted(_fields(group)):
                definitions.setdefault((group['id'], field), group)
    series, unavailable = [], []
    for (group_id, field), spec in definitions.items():
        snapshots, transitions, previous, previous_codes = [], [], None, None
        labels, indices = [], {}
        for i, groups in enumerate(grouped):
            current = groups.get(group_id)
            if current and current['units'].get(field) != spec['units'].get(field):
                raise ValueError('状态字段在前后帧改变单位，不能合并：' + group_id + '.' + field)
            local_labels, local_codes = _codes(current, field)
            for value in local_labels:
                key = _key(value)
                if key not in indices:
                    indices[key] = len(labels)
                    labels.append(value)
            remap = np.array([indices[_key(value)] for value in local_labels], dtype=np.int64)
            codes = remap[local_codes]
            counts = np.bincount(codes, minlength=len(labels))
            snapshots.append({'sim_t': times[i], 'count': len(codes),
                'states': [{'state': labels[j], 'count': int(n)} for j, n in enumerate(counts) if n]})
            if i:
                if current and previous:
                    new_indices, old_indices = _pairs(current, previous)
                else:
                    new_indices = old_indices = np.array([], dtype=np.int64)
                entered = np.ones(len(codes), dtype=bool)
                exited = np.ones(len(previous_codes), dtype=bool)
                entered[new_indices] = False
                exited[old_indices] = False
                pairs = np.concatenate((
                    np.column_stack((previous_codes[old_indices], codes[new_indices])),
                    np.column_stack((np.full(int(entered.sum()), -1), codes[entered])),
                    np.column_stack((previous_codes[exited], np.full(int(exited.sum()), -1))),
                )).astype(np.int64)
                unique, quantities = np.unique(pairs, axis=0, return_counts=True)
                links = [{'from': _node(labels[a] if a >= 0 else None, a >= 0),
                          'to': _node(labels[b] if b >= 0 else None, b >= 0), 'count': int(n)}
                         for (a, b), n in zip(unique, quantities)]
                changed = sum(row['count'] for row in links if row['from']['present'] and row['to']['present']
                    and row['from']['state'] is not None and row['to']['state'] is not None
                    and row['from']['state'] != row['to']['state'])
                transitions.append({'from': times[i-1], 'to': times[i], 'matched': len(new_indices),
                    'entered': int(entered.sum()), 'exited': int(exited.sum()), 'changed_known': changed,
                    'links': links})
            previous, previous_codes = current, codes
        series.append({'key': _key([group_id, field]), 'group': group_id, 'type': spec['type'],
            'label': spec['label'], 'field': field, 'unit': spec['units'].get(field), 'scope': spec['scope'],
            'snapshots': snapshots, 'transitions': transitions})
    return {'state_source': 'full_archive', 'interpolated': False, 'times': times,
            'series': series, 'unavailable': unavailable}
