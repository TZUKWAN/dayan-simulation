"""Measured targets for custom-model studies; never fill or resample observations.

This module checks provenance and declared temporal separation. It cannot prove
that the publisher's values, release dates, or an external feature derivation are
correct. Those limits travel with the prepared contract.
"""
from copy import deepcopy

from .. import datasets
from ..solvers.codec import digest
from ..structured_inputs import _cell, _conversion, _finite, _name, _object, _text

ROLES = ('training', 'validation', 'holdout')


def _selected(record, binding):
    path = binding.get('path', 'features' if binding.get('contract', {}).get('kind') == 'geojson' else '')
    rows = datasets._rows(record['data'], path)
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError('观测源必须是对象记录列表')
    filters = binding.get('filters', {})
    if not isinstance(filters, dict):
        raise ValueError('filters须为源字段精确匹配对象')
    if any(any(key not in row for key in filters) for row in rows):
        raise ValueError('过滤字段缺失，不能静默丢弃观测')
    indices = [i for i, row in enumerate(rows) if all(
        type(row[key]) is type(value) and row[key] == value for key, value in filters.items())]
    return rows, indices, path


def _pointer(transform):
    return transform.get('pointer') or '/' + transform['field'].replace('~', '~0').replace('/', '~1')


def _read(row, transform):
    if 'pointer' in transform:
        from ..structured_geometry import pointer_value
        return pointer_value(row, transform['pointer'])
    if transform['field'] not in row:
        raise ValueError('源字段不存在，不能作为缺失值自动丢弃')
    return row[transform['field']]


def _source_cell(record, path, index, row, transform):
    # Raw-file identity catches aliases with the same bytes. Parsed row identity
    # also catches aliases serialized as a different file format/order.
    pointer = _pointer(transform)
    return {'dataset_id': record['dataset_id'], 'source_row_index': index,
            'path': path, 'pointer': pointer, 'row_sha256': digest(row),
            'source_sha256': record['sha256'], 'data_sha256': record['data_sha256'],
            'file_cell': digest([record['sha256'], path, index, pointer]),
            'content_cell': digest([row, pointer])}


def prepare_targets(bindings, *, observables, time_unit, time_origin, split):
    """Bind scalar model outputs to one explicitly identified series per binding.

    Multiple series use distinct model observables; mixing regions/persons into
    a single scalar output is rejected. Forward-time partitions are declared
    before execution, and every modeled output needs all three roles.
    """
    _text(time_unit, '模型时间单位')
    _text(time_origin, '模型时间原点')
    _object(split, ('kind', 'training_end', 'validation_end'),
            ('kind', 'training_end', 'validation_end'), '观测划分')
    if split['kind'] != 'forward_time':
        raise ValueError('当前观测协议仅实现forward_time，不能冒充空间/分组独立划分')
    train_end = _finite(split['training_end'], '训练终点')
    val_end = _finite(split['validation_end'], '验证终点')
    if train_end < 0 or val_end <= train_end:
        raise ValueError('验证终点须晚于非负训练终点')
    if not isinstance(bindings, list) or not bindings:
        raise ValueError('target_bindings须为非空列表')
    # One shared origin label avoids asking callers to repeat the same free
    # text in every binding. Explicit conflicting labels still fail below;
    # source-to-model offsets/units continue to be independently validated.
    bindings=deepcopy(bindings)
    for binding in bindings:
        if isinstance(binding,dict):binding.setdefault('time_origin',time_origin)
    result = {'protocol': 'dayan-model-targets-v1', 'time_unit': time_unit,
              'time_origin': time_origin, 'split': deepcopy(split),
              'roles': {role: [] for role in ROLES}, 'sources': [], 'bindings': deepcopy(bindings)}
    names, used_points, used_cells, identities = set(), set(), set(), {}
    for binding in bindings:
        _object(binding, ('id', 'dataset_id', 'observable', 'fields', 'columns', 'time_field',
                          'value_field', 'series_by', 'path', 'filters', 'time_origin',
                          'available_field', 'availability_basis'),
                ('id', 'dataset_id', 'observable', 'fields', 'columns', 'time_field',
                 'value_field', 'series_by', 'time_origin'), '观测绑定')
        name, output = binding['id'], binding['observable']
        _name(name, '观测绑定id')
        if name in names:
            raise ValueError('观测绑定id重复')
        names.add(name)
        if output not in observables or not isinstance(observables[output], dict):
            raise ValueError('观测绑定须引用模型实际声明的observable')
        unit = observables[output].get('unit')
        _text(unit, '模型观测单位')
        if binding['time_origin'] != time_origin:
            raise ValueError('观测与模型时间原点不一致：'+name+'.time_origin='+repr(binding['time_origin'])
                +'，统一time_origin='+repr(time_origin)+'。可省略绑定中的time_origin继承统一标识；实际时点转换仍由columns的单位/scale/offset核验，不能只改标签')
        fields, columns = binding['fields'], binding['columns']
        if not isinstance(fields, dict) or not isinstance(columns, dict) or set(fields) != set(columns):
            raise ValueError('观测fields/columns必须完整一一对应；fields为目标列定义，columns以同样的目标列名映射原列。'
                '当前fields='+str(sorted(fields) if isinstance(fields,dict) else type(fields).__name__)+
                '，columns='+str(sorted(columns) if isinstance(columns,dict) else type(columns).__name__))
        at, value = binding['time_field'], binding['value_field']
        available = binding.get('available_field')
        if (available is None) != ('availability_basis' not in binding):
            raise ValueError('观测可用时点须同时声明available_field和availability_basis')
        if available is not None:
            _name(available, 'available_field')
            _text(binding['availability_basis'], '观测可用时点依据')
        series = binding['series_by']
        if (not isinstance(series, list) or any(not isinstance(key, str) for key in series)
                or len(series) != len(set(series)) or at == value
                or at in series or value in series
                or available is not None and available in (at, value, *series)
                or set(fields) != {at, value, *series, *([available] if available is not None else [])}):
            raise ValueError('字段须恰好覆盖独立的time_field/value_field/series_by，及可选available_field；'
                '不映射未使用的原始列。当前字段='+str(sorted(fields))+'；需要='+str([at,value,*series,*([available] if available is not None else [])]))
        # Reuse the same strict conversion/units rules as actual model inputs.
        from ..structured_inputs import port_contract
        checked = port_contract({'kind': 'records', 'purpose': 'mechanism_estimation', 'fields': fields})
        fields = checked['fields']
        if any(field['nullable'] for field in fields.values()):
            raise ValueError('校准观测及其身份不得缺失，不自动删除或插补')
        if (fields[at]['type'] not in ('number', 'integer') or fields[at]['unit'] != time_unit
                or fields[value]['type'] not in ('number', 'integer') or fields[value]['unit'] != unit):
            raise ValueError('观测时间/值的类型或单位与实际模型不一致')
        if available is not None and (fields[available]['type'] not in ('number', 'integer')
                                      or fields[available]['unit'] != time_unit):
            raise ValueError('观测可用时点必须使用同一模型时间单位')
        record = datasets.load(binding['dataset_id'])
        dataset_role = record.get('role')
        if dataset_role not in ('input', 'calibration', 'validation', 'holdout', 'test'):
            raise ValueError('观测数据角色须为input/calibration/validation/holdout/test；整份待按时间三分区的原始观测用collect_data(role="input")，background/source_snapshot只作参考，不能评分')
        transforms = {key: _conversion(field, columns[key], record.get('metadata', {}))
                      for key, field in fields.items()}
        rows, indices, path = _selected(record, binding)
        if not indices:
            raise ValueError(name + '没有匹配观测，不能忽略空目标')
        counts = dict.fromkeys(ROLES, 0)
        for index in indices:
            row = rows[index]
            try:
                converted = {key: _cell(_read(row, transform), fields[key], transform)
                             for key, transform in transforms.items()}
            except ValueError as exc:
                raise ValueError(f'观测{name}原始行{index}：{exc}') from exc
            t, actual = converted[at], converted[value]
            if t < 0:
                raise ValueError('观测时刻早于模型原点，不能静默截去')
            identity = {key: converted[key] for key in series}
            identity_hash = digest(identity)
            if output in identities and identities[output] != identity_hash:
                raise ValueError('同一标量observable混合多个系列；请分别输出并绑定')
            identities[output] = identity_hash
            role = 'training' if t <= train_end else 'validation' if t <= val_end else 'holdout'
            allowed = {'calibration': 'training', 'validation': 'validation', 'holdout': 'holdout', 'test': 'holdout'}
            if dataset_role != 'input' and role != allowed[dataset_role]:
                raise ValueError(f'数据已声明用途与实际划分冲突，不能重用留出数据拟合；{name}原始行{index}的t={t}属于{role}，数据集role={dataset_role}。'
                    '整份含训练/验证/留出时点的原始观测应采集为input并由split固定划分；calibration仅限训练数据，不缩减时期、改时刻或将已明确留出样本改作拟合')
            provenance = _source_cell(record, path, index, row, transforms[value])
            key = (output, identity_hash, t)
            cells = {provenance['file_cell'], provenance['content_cell']}
            if key in used_points or cells & used_cells:
                raise ValueError('重复观测/源单元格，包含换DS编号、改格式或改时间后重复使用')
            used_points.add(key)
            used_cells.update(cells)
            counts[role] += 1
            result['roles'][role].append({'binding_id': name, 'observable': output, 'time': t,
                                         'value': actual, 'unit': unit, 'series': identity,
                                         'available_at': converted[available] if available is not None else None,
                                         'provenance': provenance})
        result['sources'].append({'binding_id': name, 'dataset_id': record['dataset_id'],
            'sha256': record['sha256'], 'data_sha256': record['data_sha256'],
            'source': record['source'], 'license': record.get('license'), 'role': dataset_role,
            'path': path, 'source_row_indices': indices, 'transforms': transforms, 'counts': counts})
    outputs = set(identities)
    for role, rows in result['roles'].items():
        if {row['observable'] for row in rows} != outputs:
            raise ValueError('每个目标observable必须同时有训练、验证和留出观测：' + role)
        rows.sort(key=lambda row: (row['time'], row['observable'], row['binding_id']))
    result['verification_scope'] = {
        'source_hashes': 'verified', 'time_partition': 'strictly_forward',
        'sampling': 'original_points_no_resampling_or_imputation',
        'source_accuracy': 'not_established', 'release_times': 'not_established',
        'independence': 'row_cell_and_declared_series_checks_only_not_statistical_independence'}
    result['sha256'] = digest(result)
    return result


def target_binding_schema():
    """Expose the actual target parser shape, including destination column names."""
    field={'type':'object','properties':{'type':{'enum':['number','integer','string','boolean']},
        'unit':{'type':'string','minLength':1},'nullable':{'const':False}},
        'required':['type','unit'],'additionalProperties':False}
    conversion={'type':'object','properties':{'field':{'type':'string'},'pointer':{'type':'string','pattern':'^/'},
        'source_unit':{'type':'string'},'scale':{'type':'number'},'offset':{'type':'number'},
        'transformation_note':{'type':'string'},'missing_values':{'type':'array'},'value_map':{'type':'object'}},
        'additionalProperties':False,'oneOf':[{'required':['field']},{'required':['pointer']}],
        'description':'目标列到原字段或JSON Pointer的映射；数值列须source_unit。同单位scale=1，非零offset说明原点依据。'}
    properties={name:{'type':'string','minLength':1} for name in
        ('id','dataset_id','observable','time_origin','time_field','value_field','available_field','availability_basis')}
    properties['time_origin']['description']='统一模型时间原点的标识；省略则继承顶层time_origin，填写时须逐字相同。实际日历到模型时间用columns的单位/scale/offset转换。'
    properties.update(path={'type':'string','description':'原始JSON记录列表路径，WB接口常为"1"；不是磁盘路径'},
        filters={'type':'object','description':'原始记录字段精确匹配；不要用已转换的目标字段名'},
        fields={'type':'object','minProperties':2,'additionalProperties':field,
                'description':'只定义time_field、value_field、series_by及可选available_field指定的目标列，数值时间/值带实际单位；文字身份unit=1。'},
        columns={'type':'object','minProperties':2,'additionalProperties':conversion,
                 'description':'键必须与fields完全相同；值指定每个目标列从哪个原字段读取。不要以原字段名替代目标列名。'},
        series_by={'type':'array','uniqueItems':True,'items':{'type':'string'},'description':'字段为目标身份列名；单一明确系列可用[]。一个模型标量观测不能混合多个国家或群体。'})
    return {'type':'object','properties':properties,'required':['id','dataset_id','observable','fields','columns','time_field','value_field','series_by'],
        'additionalProperties':False,'description':'整份跨阶段原始观测用role=input采集；split负责分区。calibration/validation/holdout数据集只允许各自分区，background/source_snapshot不能评分。',
        'examples':[{'id':'population','dataset_id':'实际collect_data返回的DS编号','observable':'population','time_origin':'2010年度',
            'path':'1','fields':{'time':{'type':'number','unit':'year'},'value':{'type':'number','unit':'person'}},
            'columns':{'time':{'field':'date','source_unit':'year','offset':-2010,'transformation_note':'2010年度为模型t=0'},
                       'value':{'field':'value','source_unit':'person'}},'time_field':'time','value_field':'value','series_by':[]}]}


def audit_input_usage(targets, bindings, *, availability, information_mode, forecast_origin):
    """Check the actual selected input columns against evaluation target cells.

    Availability is an explicit research assumption, not a verified release
    timestamp. Existing forward data can be used for retrospective conditioning
    only if that weaker interpretation is recorded. Held-out outcome cells never
    enter the evaluated model, even under that interpretation.
    """
    if information_mode not in ('forecast', 'retrospective_conditioning'):
        raise ValueError('information_mode须明确forecast或retrospective_conditioning')
    _finite(forecast_origin, '信息截止时刻')
    if forecast_origin != targets['split']['training_end']:
        raise ValueError('信息截止时刻必须等于事前训练终点')
    if information_mode == 'forecast':
        for row in targets['roles']['training']:
            if row['available_at'] is None:
                raise ValueError('预测模式须为训练观测声明可用时点及依据；仅观测年份不能证明当时可获得')
            if row['available_at'] > forecast_origin:
                raise ValueError('训练观测在预测信息截止时刻之后才可获得，发生时间泄漏')
    if not isinstance(bindings, list) or not isinstance(availability, list) or len(bindings) != len(availability):
        raise ValueError('每项实际输入都须有且仅有一项availability声明')
    protected, training = set(), set()
    for role, rows in targets['roles'].items():
        for row in rows:
            cells = {row['provenance']['file_cell'], row['provenance']['content_cell']}
            (training if role == 'training' else protected).update(cells)
    receipts = []
    for binding, access in zip(bindings, availability):
        _object(access, ('binding_sha256', 'available_at', 'basis', 'training_target_use'),
                ('binding_sha256', 'available_at', 'basis', 'training_target_use'), '输入可用时点')
        if access['binding_sha256'] != digest(binding):
            raise ValueError('availability未绑定同一实际数据映射')
        at = _finite(access['available_at'], '输入可用时点')
        _text(access['basis'], '输入可用时点依据')
        if access['training_target_use'] not in ('none', 'initial_condition', 'lagged_observation'):
            raise ValueError('训练目标复用须明确none/initial_condition/lagged_observation')
        if information_mode == 'forecast' and at > forecast_origin:
            raise ValueError('预测输入含信息截止时刻之后才可用的数据')
        record = datasets.load(binding['dataset_id'])
        rows, indices, path = _selected(record, binding)
        if not indices:
            raise ValueError('实际输入选择为空')
        if 'port' in binding:
            transforms = list(binding['columns'].values())
            # Geometry contains the complete properties too, not just mapped columns.
            if binding['contract']['kind'] == 'geojson':
                transforms += [{'pointer': pointer} for pointer in sorted({item['provenance']['pointer']
                    for group in targets['roles'].values() for item in group})]
        else:
            transforms = [{'field': binding['field']}]
            order = binding.get('order_by')
            if order:
                if any(order not in rows[i] for i in indices):
                    raise ValueError('输入排序字段不存在')
                indices.sort(key=lambda i: rows[i][order])
            if binding.get('aggregate', 'last') == 'first':
                indices = indices[:1]
            elif binding.get('aggregate', 'last') == 'last':
                indices = indices[-1:]
        overlaps = 0
        for index in indices:
            for transform in transforms:
                cell = _source_cell(record, path, index, rows[index], transform)
                cells = {cell['file_cell'], cell['content_cell']}
                if cells & protected:
                    raise ValueError('模型输入含验证/留出目标单元格（含别名数据集），发生泄漏')
                overlaps += bool(cells & training)
        if overlaps and access['training_target_use'] == 'none':
            raise ValueError('实际输入复用了训练目标，必须声明初值或滞后观测用途')
        receipts.append({'binding_sha256': digest(binding), 'dataset_id': record['dataset_id'],
                         'source_row_indices': indices, 'training_target_cells': overlaps,
                         'availability': deepcopy(access)})
    return {'status': 'declared_contract_checked', 'information_mode': information_mode,
            'forecast_origin': forecast_origin, 'inputs': receipts,
            'limits': ['可用时点依据由研究方案声明，未自动核验原发布版本/日期',
                       '外部已派生特征的未知血缘和统计相关性不由单元格哈希证明无泄漏']}
