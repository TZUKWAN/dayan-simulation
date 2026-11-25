"""Acceptance from archived graph data, independent of model-reported counts."""
from ..view_analysis import number


def relation_spec(row, observables):
    allowed = {'id', 'check', 'reason', 'fields', 'atol', 'target', 'observable', 'relation_type', 'step'}
    ident = row['id']
    if set(row) - allowed or row.get('fields', []) != []:
        raise ValueError(f'{ident}关系帧检查不用观测fields；同口径对账用observable')
    if not isinstance(row.get('reason'), str) or not row['reason'].strip():
        raise ValueError(f'{ident}缺少关系数量的原文或方程依据')
    if row.get('atol', 0) != 0 or isinstance(row.get('atol', 0), bool):
        raise ValueError('关系数量须精确核对，atol只能为0')
    if 'target' not in row and 'observable' not in row:
        raise ValueError('relation_count须给非负整数target或同口径observable，或同时给出')
    if 'target' in row and (type(row['target']) is not int or row['target'] < 0):
        raise ValueError('关系数量target须为非负整数')
    if 'observable' in row and (not isinstance(row['observable'], str) or row['observable'] not in observables):
        raise ValueError('关系对账observable须为方案中真实的观测字段')
    if 'relation_type' in row and (not isinstance(row['relation_type'], str) or not row['relation_type'].strip()):
        raise ValueError('关系分层筛选使用非空relation_type，对应实际边的type字段')
    if 'step' in row and (type(row['step']) is not int or row['step'] < 0):
        raise ValueError('关系检查step须为非负整数，0为初态')
    return {**row, 'fields': [], 'atol': 0, 'reason': row['reason'].strip()}


def relation_count(spec, observations, frames):
    """Use complete relations, never display edges or an inferred metric alias."""
    from ..program_frames import validate_relation_time

    by_time = {}
    for row in observations:
        if number(row.get('sim_t')):
            by_time.setdefault(row['sim_t'], []).append(row)
    requested_time = None
    selected = frames or []
    if 'step' in spec:
        step = spec['step']
        requested_time = observations[step].get('sim_t') if step < len(observations) else None
        selected = [frame for frame in selected if number(requested_time) and frame.get('sim_t') == requested_time]
    valid = bool(selected) and ('step' not in spec or len(selected) == 1)
    counts, deviations, reported_deviations, failures, seen = [], [], [], [], set()
    for frame in selected:
        stamp, edges = frame.get('sim_t'), frame.get('relations', [])
        row_ok = number(stamp) and stamp not in seen and len(by_time.get(stamp, [])) == 1
        if number(stamp):
            seen.add(stamp)
        row_ok = row_ok and isinstance(edges, list) and all(isinstance(edge, dict) for edge in edges)
        count = reported = None
        if row_ok:
            try:
                for edge in edges:
                    validate_relation_time(edge, stamp)
            except ValueError:
                row_ok = False
            count = sum('relation_type' not in spec or edge.get('type') == spec['relation_type'] for edge in edges)
            counts.append(count)
            if 'target' in spec:
                deviations.append(abs(count - spec['target']))
                row_ok = row_ok and count == spec['target']
            if 'observable' in spec:
                reported = by_time[stamp][0].get(spec['observable'])
                if number(reported):
                    reported_deviations.append(abs(count - reported))
                row_ok = row_ok and number(reported) and count == reported
        if not row_ok:
            valid = False
            if len(failures) < 8:
                failures.append({'sim_t': stamp, 'actual_count': count, 'reported_count': reported})
    measured = {'source': 'state_frames.relations', 'matched_frames': len(selected), 'valid_counts': len(counts),
                'minimum': min(counts) if counts else None, 'maximum': max(counts) if counts else None,
                'max_target_error': max(deviations) if deviations else None,
                'max_observable_error': max(reported_deviations) if reported_deviations else None,
                'failure_examples': failures}
    if 'step' in spec:
        measured.update(requested_step=spec['step'], requested_time=requested_time)
    return {**spec, 'passed': bool(valid), 'measured': measured}
