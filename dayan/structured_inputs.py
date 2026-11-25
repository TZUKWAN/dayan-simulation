"""Typed, lossless dataset ports. No expressions or user code run on the host.

Bindings retain joint rows. Only explicit column conversions are allowed; input
summaries contain schemas and hashes, never the source micro-records themselves.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation, localcontext
import math
import re

from .solvers.codec import digest

NAME = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,39}\Z')
PURPOSES = ('initialization', 'exogenous_input', 'mechanism_estimation')
TYPES = ('number', 'integer', 'string', 'boolean')
_UNITS = {
    '1': ('dimensionless', 1), 'fraction': ('ratio', 1), '%': ('ratio', .01),
    'millisecond': ('time', .001), 'second': ('time', 1), 'minute': ('time', 60), 'hour': ('time', 3600), 'day': ('time', 86400),
    'm': ('length', 1), 'km': ('length', 1000), 'cm': ('length', .01), 'mm': ('length', .001),
    'kg': ('mass', 1), 'g': ('mass', .001),
}


def _object(value, allowed, required, label):
    if not isinstance(value, dict) or set(value) - set(allowed) or not set(required) <= set(value):
        raise ValueError(label + '字段缺失或含未知字段')


def _name(value, label):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        raise ValueError(label + '须为英文标识（英文字母开头，字母/数字/下划线，最多40字符）')


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(label + '须为非空文字')


def _finite(value, label):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(label + '须为有限数值')
    return value


def port_contract(value):
    spec = deepcopy(value)
    _object(spec, ('kind', 'purpose', 'fields', 'primary_key', 'endpoints', 'directed', 'clock', 'geometry'),
            ('kind', 'purpose', 'fields'), '输入端口合同')
    if spec['kind'] not in ('records', 'edges', 'geojson', 'timeseries') or spec['purpose'] not in PURPOSES:
        raise ValueError('输入端口kind/purpose不在实际支持的合同内')
    fields = spec['fields']
    if not isinstance(fields, dict) or not fields and spec['kind'] != 'geojson':
        raise ValueError('输入端口fields须非空')
    if spec['kind'] == 'geojson':
        from .structured_geometry import geometry_contract
        spec['geometry'] = geometry_contract(spec.get('geometry'))
    elif 'geometry' in spec:
        raise ValueError('只有geojson端口可声明geometry坐标合同')
    for name, field in fields.items():
        _name(name, '输入字段')
        _object(field, ('type', 'unit', 'nullable'), ('type', 'unit'), '输入字段' + name)
        if field['type'] not in TYPES:
            raise ValueError('输入字段type不合法')
        _text(field['unit'], '输入字段unit')
        field.setdefault('nullable', False)
        if type(field['nullable']) is not bool:
            raise ValueError('nullable须为布尔值')
        if field['type'] in ('string', 'boolean') and field['unit'] != '1':
            raise ValueError('文字/布尔输入须使用无量纲unit=1')
    keys = spec.setdefault('primary_key', [])
    if (not isinstance(keys, list) or any(not isinstance(k, str) or k not in fields for k in keys)
            or len(keys) != len(set(keys)) or any(fields[k]['nullable'] for k in keys)):
        raise ValueError('primary_key须为不重复、不可缺失的实际字段列表')
    if spec['kind'] == 'edges':
        if type(spec.get('directed')) is not bool:
            raise ValueError('边表须明确directed布尔值')
        ends = spec.get('endpoints')
        _object(ends, ('source', 'target'), ('source', 'target'), '边端点')
        for endpoint in ends.values():
            _object(endpoint, ('field', 'port', 'key'), ('field', 'port', 'key'), '边端点引用')
            for key in ('port', 'key'):
                _name(endpoint[key], '边端点' + key)
            if endpoint['field'] not in fields or fields[endpoint['field']]['nullable']:
                raise ValueError('边端点须引用不可缺失的实际字段')
    elif 'endpoints' in spec or 'directed' in spec:
        raise ValueError('只有edges端口可声明endpoints/directed')
    if spec['kind']=='timeseries':
        from .structured_time import series_clock
        spec['clock']=series_clock(spec.get('clock'),fields)
    elif 'clock' in spec:
        clock = spec['clock']
        _object(clock, ('field', 'origin', 'interval', 'end_field', 'boundary', 'anchor'),
                ('field', 'origin', 'boundary'), '输入时钟')
        if clock['boundary'] != 'left_closed_right_open':
            raise ValueError('输入区间须明确采用左闭右开边界')
        _text(clock['origin'], '输入时钟原点说明')
        time_field = fields.get(clock['field'])
        if not time_field or time_field['type'] not in ('number', 'integer') or time_field['nullable']:
            raise ValueError('输入时钟须为不可缺失的数值字段')
        if ('interval' in clock) == ('end_field' in clock):
            raise ValueError('输入时钟须声明interval或end_field之一')
        if clock.get('anchor', 'start') not in ('start', 'end'):
            raise ValueError('输入时钟anchor须为start或end，表示field是区间起点或终点')
        if 'end_field' in clock and clock.get('anchor', 'start') != 'start':
            raise ValueError('end_field已给结束列，field必须是开始列，不能同时anchor=end')
        if 'interval' in clock:
            if _finite(clock['interval'], '时间间隔') <= 0:
                raise ValueError('时间间隔须为正值')
        else:
            end = fields.get(clock['end_field'])
            if not end or end != time_field:
                raise ValueError('结束时间字段的类型/单位/缺失合同须与开始时间一致')
    return spec


def port_contracts(value):
    if not isinstance(value, dict):
        raise ValueError('input_ports须为端口对象')
    result = {}
    for name, spec in value.items():
        _name(name, '输入端口名')
        result[name] = port_contract(spec)
    for name, spec in result.items():
        for endpoint in spec.get('endpoints', {}).values():
            other = result.get(endpoint['port'])
            if not other or other['primary_key'] != [endpoint['key']]:
                raise ValueError(name + '的边端点须引用已有端口的单字段唯一主键')
            if spec['fields'][endpoint['field']] != other['fields'][endpoint['key']]:
                raise ValueError(name + '的边端点类型/单位须与目标主键一致')
    return result


def contract_differences(expected, actual, path='input_ports', limit=12):
    """Bounded schema differences only; never include dataset micro-records."""
    differences=[]
    def walk(left,right,at):
        if len(differences)>=limit or type(left) is type(right) and left==right:
            return
        if isinstance(left,dict) and isinstance(right,dict):
            for key in sorted(left.keys()|right.keys()):
                if len(differences)>=limit:break
                if key not in left or key not in right:
                    differences.append({'path':at+'.'+key,'expected_present':key in left,'actual_present':key in right})
                else:walk(left[key],right[key],at+'.'+key)
        else:
            differences.append({'path':at,'expected':left,'actual':right})
    walk(expected,actual,path)
    return differences


def _conversion(field, mapping, metadata):
    _object(mapping, ('field', 'pointer', 'source_unit', 'scale', 'offset', 'transformation_note', 'missing_values', 'value_map'),
            (), '列映射')
    if ('field' in mapping) == ('pointer' in mapping):
        raise ValueError('列映射须声明field或pointer之一，不能猜嵌套路径')
    source_key = mapping.get('field', mapping.get('pointer'))
    _text(source_key, '源字段/JSON Pointer')
    if 'pointer' in mapping and not source_key.startswith('/'):
        raise ValueError('pointer须为以/开头的明确JSON Pointer')
    scale = _finite(mapping.get('scale', 1), '列scale')
    offset = _finite(mapping.get('offset', 0), '列offset')
    missing = mapping.get('missing_values', [])
    if not isinstance(missing, list) or any(not isinstance(v, (str, int, float, bool, type(None))) for v in missing):
        raise ValueError('missing_values须为显式标量列表')
    if any(type(v) is float and not math.isfinite(v) for v in missing):
        raise ValueError('missing_values不能含非有限数字')
    known_unit = metadata.get('units', {}).get(source_key) or metadata.get('unit')
    source_unit = mapping.get('source_unit', known_unit or ('1' if field['unit'] == '1' else None))
    if known_unit and source_unit != known_unit:
        raise ValueError('源单位声明与数据元数据不一致')
    if not source_unit:
        raise ValueError('数值列须有数据元数据或显式source_unit，不能猜测单位')
    expected = 1 if source_unit == field['unit'] else None
    if expected is None and source_unit in _UNITS and field['unit'] in _UNITS:
        a, b = _UNITS[source_unit], _UNITS[field['unit']]
        if a[0] == b[0]:
            expected = a[1] / b[1]
    if expected is None or not math.isclose(scale, expected, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError('列单位/scale不兼容；自定义同单位变换应在审核后的模型内实现')
    if offset:
        if field['type'] not in ('number', 'integer'):
            raise ValueError('只有数值列可做平移')
        _text(mapping.get('transformation_note'), '非零offset的原点/平移依据')
    if 'value_map' in mapping and (not isinstance(mapping['value_map'], dict)
                                  or any(not isinstance(k, str) for k in mapping['value_map'])):
        raise ValueError('value_map须为源文字类别到目标标量的明确映射')
    return {**deepcopy(mapping), 'source_unit': source_unit, 'target_unit': field['unit'],
            'scale': scale, 'offset': offset, 'missing_values': missing}


def _cell(value, field, transform):
    if value is None or any(type(value) is type(m) and value == m for m in transform['missing_values']):
        if not field['nullable']:
            raise ValueError('不可缺失字段包含缺失值')
        return None
    if 'value_map' in transform:
        if not isinstance(value, str) or value not in transform['value_map']:
            raise ValueError('value_map未覆盖实际源类别')
        value = transform['value_map'][value]
        if value is None:
            if field['nullable']:
                return None
            raise ValueError('value_map不能把不可缺失字段映射为null')
    kind = field['type']
    if kind == 'string':
        if not isinstance(value, str):
            raise ValueError('文字字段不做隐式数字/布尔转换；请显式保留原始ID类型')
        return value
    if kind == 'boolean':
        if type(value) is not bool:
            raise ValueError('布尔字段须为实际布尔值或显式value_map')
        return value
    if type(value) not in (int, float, str):
        raise ValueError('数值字段不可由布尔/对象隐式转换')
    try:
        with localcontext() as context:
            context.prec = max(50, len(str(value)) + len(str(transform['scale'])) + len(str(transform['offset'])) + 20)
            number = Decimal(str(value)) * Decimal(str(transform['scale'])) + Decimal(str(transform['offset']))
        if not number.is_finite():
            raise ValueError('数值字段含非有限数值')
        if kind == 'integer':
            if number != number.to_integral_value():
                raise ValueError('整数列不能取整丢失信息')
            return int(number)
        return _finite(float(number), '转换结果')
    except (InvalidOperation, OverflowError) as exc:
        raise ValueError('数值列解析失败') from exc


def prepare_structured(bindings, declared=None):
    from .datasets import load, _rows
    inputs, evidence = {}, []
    contracts = {}
    for binding in bindings or []:
        _object(binding, ('dataset_id', 'port', 'contract', 'columns', 'path', 'filters', 'order_by'),
                ('dataset_id', 'port', 'contract', 'columns'), '结构数据绑定')
        name = binding['port']
        _name(name, '输入端口名')
        if name in inputs:
            raise ValueError('同一输入端口不能被多次绑定')
        spec = port_contract(binding['contract'])
        mapping = binding['columns']
        if not isinstance(mapping, dict) or set(mapping) != set(spec['fields']):
            raise ValueError('列映射必须恰好覆盖端口全部字段，不能省略或额外注入')
        record = load(binding['dataset_id'])
        if record.get('role') not in ('input', spec['purpose']):
            raise ValueError('数据角色与端口用途不符；留出/验证/背景/校准数据不能混入运行输入')
        transforms = {key: _conversion(spec['fields'][key], value, record.get('metadata', {}))
                      for key, value in mapping.items()}
        data_path = binding.get('path', 'features' if spec['kind'] == 'geojson' else '')
        raw_rows = _rows(record['data'], data_path)
        filters = binding.get('filters', {})
        if not isinstance(filters, dict):
            raise ValueError('filters须为源字段精确匹配对象')
        if any(any(key not in row for key in filters) for row in raw_rows):
            raise ValueError('过滤字段缺失，不能静默丢弃记录')
        indices = [index for index, row in enumerate(raw_rows)
                   if all(type(row[key]) is type(value) and row[key] == value for key, value in filters.items())]
        columns = {key: [] for key in mapping}
        for index in indices:
            for key, transform in transforms.items():
                try:
                    if 'pointer' in transform:
                        from .structured_geometry import pointer_value
                        source_value = pointer_value(raw_rows[index], transform['pointer'])
                    else:
                        if transform['field'] not in raw_rows[index]:
                            raise ValueError('源字段不存在（不同于显式null）')
                        source_value = raw_rows[index][transform['field']]
                    value = _cell(source_value, spec['fields'][key], transform)
                except ValueError as exc:
                    raise ValueError(f'端口{name}原始记录{index}字段{key}：{exc}') from exc
                columns[key].append(value)
        order = binding.get('order_by', [])
        if isinstance(order, str):
            order = [order]
        if not isinstance(order, list) or any(key not in columns for key in order) or len(order) != len(set(order)):
            raise ValueError('order_by须为目标字段名或不重复字段列表')
        if order:
            if any(value is None for key in order for value in columns[key]):
                raise ValueError('排序字段有缺失，须明确处理而非猜测排序')
            permutation = sorted(range(len(indices)), key=lambda i: tuple(columns[key][i] for key in order))
            columns = {key: [values[i] for i in permutation] for key, values in columns.items()}
            indices = [indices[i] for i in permutation]
        keys = spec['primary_key']
        if keys and len({tuple(columns[key][i] for key in keys) for i in range(len(indices))}) != len(indices):
            raise ValueError(name + '的primary_key包含重复，不能静默去重')
        clock = spec.get('clock')
        time_receipt = {}
        if spec['kind']=='timeseries':
            from .structured_time import series_summary
            time_receipt=series_summary(clock,spec['fields'],columns)
        elif clock and 'interval' in clock and 'anchor' not in clock:
            # Historical contracts described endpoint semantics only in prose.
            # Keep their identity and do not reinterpret timestamps on reread.
            at=columns[clock['field']]
            time_receipt={'anchor':'unspecified_legacy','unit':spec['fields'][clock['field']]['unit'],
                          'intervals':len(at),'recorded_min':min(at,default=None),'recorded_max':max(at,default=None),
                          'origin':clock['origin'],'interval_bounds':'not_inferred_without_explicit_anchor'}
        elif clock:
            at = columns[clock['field']]
            start = [t-clock['interval'] for t in at] if clock.get('anchor') == 'end' else at
            end = (at if clock.get('anchor') == 'end' else columns[clock['end_field']]
                   if 'end_field' in clock else [t+clock['interval'] for t in at])
            if any(not math.isfinite(a) or not math.isfinite(b) or b <= a for a,b in zip(start,end)):
                raise ValueError('时间区间结束必须晚于开始')
            time_receipt = {'anchor':clock.get('anchor','start'), 'unit':spec['fields'][clock['field']]['unit'],
                            'intervals':len(at), 'first_start':min(start,default=None), 'last_end':max(end,default=None),
                            'boundary':clock['boundary'], 'origin':clock['origin']}
        inputs[name] = {'kind': spec['kind'], 'contract': spec, 'count': len(indices),
                        'columns': columns, 'source_row_indices': indices}
        geometry_receipt = {}
        if spec['kind'] == 'geojson':
            from .structured_geometry import features_summary, check_crs
            crs_check = check_crs(record['data'],record.get('metadata',{}),spec['geometry'])
            features = [deepcopy(raw_rows[index]) for index in indices]
            geometry_receipt = {**features_summary(features, spec['geometry']), 'crs_check':crs_check}
            inputs[name]['features'] = features
        contracts[name] = spec
        evidence.append({'dataset_id': record['dataset_id'], 'port': name, 'contract': spec, 'binding': deepcopy(binding),
            'columns': transforms, 'path': data_path, 'filters': deepcopy(filters), 'order_by': order,
            'source': record['source'], 'license': record.get('license'), 'role': record['role'],
            'sha256': record['sha256'], 'data_sha256': record['data_sha256'], 'parsing': record.get('parsing'),
            'retrieved_at': record.get('retrieved_at'), 'source_records': len(raw_rows), 'records_used': len(indices),
            'missing': {key: sum(value is None for value in values) for key, values in columns.items()},
            'input_sha256': digest(inputs[name]), 'usage_status': 'prepared_not_yet_executed',
            **({'time_summary':time_receipt} if time_receipt else {}),
            **({'geometry_summary':geometry_receipt} if geometry_receipt else {})})
    contracts = port_contracts(contracts)
    if declared is not None and contracts != port_contracts(declared):
        raise ValueError('实际绑定端口与模型input_ports的完整合同不一致（缺失/多余/含义不同）')
    for name, spec in contracts.items():
        for side, endpoint in spec.get('endpoints', {}).items():
            values = set(inputs[endpoint['port']]['columns'][endpoint['key']])
            if any(value not in values for value in inputs[name]['columns'][endpoint['field']]):
                raise ValueError(name + '.' + side + '含目标人口端口不存在的真实ID')
    return inputs, evidence


def prepare_bindings(bindings, model_id=None, declared=None):
    """One preparation path for design, preflight and execution; never skip ports."""
    from .datasets import bind_parameters
    if bindings is not None and not isinstance(bindings, list):
        raise ValueError('data_bindings须为列表')
    if any(not isinstance(item, dict) for item in bindings or []):
        raise ValueError('每项data_binding须为对象')
    structural = [item for item in bindings or [] if 'port' in item]
    scalar = [item for item in bindings or [] if 'port' not in item]
    parameters, evidence = bind_parameters(scalar, model_id)
    inputs, structured_evidence = prepare_structured(structural, declared)
    return parameters, inputs, [*evidence, *structured_evidence]


def structured_audit(manifest, checkpoint):
    """Recompute from immutable originals and compare with actual solver inputs."""
    bindings = [item for item in manifest.get('data_bindings', []) if 'port' in item]
    if not bindings:
        return []
    snapshot = (checkpoint or {}).get('inputs')
    declared = manifest.get('model_definition', {}).get('input_ports', {})
    summary = manifest.get('structured_inputs', {})
    rows = [{'port': item['port'], 'dataset_id': item['dataset_id'], 'status': 'snapshot_unavailable',
             'records': item['records_used'], 'input_sha256': item['input_sha256'],
             'causal_use': 'not_certified_by_transport'} for item in bindings]
    if not isinstance(snapshot, dict):
        return rows
    valid = (digest(snapshot) == summary.get('sha256') and
             (checkpoint or {}).get('checkpoint_sha256') == digest({
                 k:v for k,v in checkpoint.items() if k != 'checkpoint_sha256'}))
    for row in rows:
        asset = snapshot.get(row['port'])
        row['status'] = 'snapshot_verified_source_unavailable' if (
            valid and isinstance(asset, dict) and digest(asset) == row['input_sha256']
            and asset.get('count') == row['records']) else 'mismatch'
    try:
        prepared, evidence = prepare_structured([item['binding'] for item in bindings], declared)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        for row in rows:
            row['source_check_error'] = str(exc)
        return rows
    original = {item['port']:item for item in bindings}
    recomputed = {item['port']:item for item in evidence}
    for row in rows:
        name = row['port']
        same = (row['status'] != 'mismatch' and prepared[name] == snapshot.get(name) and
                all(original[name].get(key) == recomputed[name].get(key)
                    for key in ('sha256', 'data_sha256', 'input_sha256', 'records_used')))
        row['status'] = 'recomputed' if same else 'mismatch'
    return rows


def binding_schema():
    """The public Agent schema mirrors the actual preparation contract."""
    scalar = {'type':'object', 'required':['dataset_id','field','parameter'],
        'properties':{'dataset_id':{'type':'string'}, 'path':{'type':'string'},
            'field':{'type':'string'}, 'parameter':{'type':'string'},
            'aggregate':{'enum':['first','last','sum','mean','min','max','n']},
            'scale':{'type':'number'}, 'source_unit':{'type':'string'}, 'target_unit':{'type':'string'},
            'source_scope':{'type':'string','description':'源地区或主体群体的可核验标识，例如地区代码。不是指标名、年份、参数用途或模型变量；已存在数据metadata.scope时须一致。'},
            'target_scope':{'type':'string','description':'模型对应的同一地区/群体标识；两侧都填时须精确一致。参数用途/初始条件说明写在availability.basis，不把“模型t=0”写成地区。缺依据时不猜测scope。'},
            'filters':{'type':'object'}, 'order_by':{'type':'string'}}, 'additionalProperties':False}
    column = {'type':'object','oneOf':[{'required':['field']},{'required':['pointer']}],'properties':{
        'field':{'type':'string'}, 'pointer':{'type':'string','pattern':'^/'}, 'source_unit':{'type':'string'}, 'scale':{'type':'number'},
        'offset':{'type':'number'}, 'transformation_note':{'type':'string'},
        'missing_values':{'type':'array','items':{'type':['string','number','boolean','null']}},
        'value_map':{'type':'object','additionalProperties':{'type':['string','number','boolean','null']}}},
        'additionalProperties':False}
    field = {'type':'object','required':['type','unit'],'properties':{
        'type':{'enum':list(TYPES)},'unit':{'type':'string','minLength':1,
            'description':'string/boolean必须为"1"；数值用实际单位。内置换算拼写：second/minute/hour/day/millisecond、m/km/cm/mm、kg/g、fraction/%；同名自定义数值单位可用。'},
        'nullable':{'type':'boolean'}},
        'allOf':[{'if':{'properties':{'type':{'enum':['string','boolean']}}},
                  'then':{'properties':{'unit':{'const':'1'}}}}], 'additionalProperties':False}
    endpoint = {'type':'object','required':['field','port','key'],
        'properties':{key:{'type':'string'} for key in ('field','port','key')},'additionalProperties':False}
    clock = {'type':'object','required':['field','origin','boundary'],'properties':{
        'field':{'type':'string','description':'interval合同须用anchor明确起点start/终点end；不能只在origin文字中改变含义。'},
        'origin':{'type':'string'},'interval':{'type':'number','exclusiveMinimum':0},
        'anchor':{'enum':['start','end']},
        'end_field':{'type':'string','description':'结束列，与起点field相同单位；不能同时anchor=end。'},
        'boundary':{'const':'left_closed_right_open'}},
        'oneOf':[{'required':['interval','anchor']},{'required':['end_field']}],'additionalProperties':False}
    from .structured_time import clock_schema
    point_clock = clock_schema()
    contract = {'type':'object','required':['kind','purpose','fields'],'properties':{
        'kind':{'enum':['records','edges','geojson','timeseries']},'purpose':{'enum':list(PURPOSES)},
        'fields':{'type':'object','additionalProperties':field},
        'primary_key':{'type':'array','items':{'type':'string'},'uniqueItems':True},
        'directed':{'type':'boolean'},'endpoints':{'type':'object','required':['source','target'],
            'properties':{'source':endpoint,'target':endpoint},'additionalProperties':False},'clock':{'oneOf':[clock,point_clock]},
        'geometry':{'type':'object','required':['crs','axes','units','coordinate_evidence','allow_null'],
            'properties':{'crs':{'type':'string'},'axes':{'type':'array','minItems':2,'items':{'type':'string'},'uniqueItems':True},
                'units':{'type':'array','minItems':2,'items':{'type':'string'}},
                'coordinate_evidence':{'type':'string'},'allow_null':{'type':'boolean'}},'additionalProperties':False}},
        'allOf':[{'if':{'properties':{'kind':{'const':'timeseries'}}},
                  'then':{'required':['clock'],'properties':{'clock':point_clock}},
                  'else':{'properties':{'clock':clock}}}], 'additionalProperties':False}
    structure = {'type':'object','required':['dataset_id','port','contract','columns'],
        'properties':{'dataset_id':{'type':'string'},'port':{'type':'string','pattern':'^[A-Za-z][A-Za-z0-9_]{0,39}$'},
            'contract':contract,'columns':{'type':'object','additionalProperties':column},
            'path':{'type':'string'},'filters':{'type':'object'},
            'order_by':{'oneOf':[{'type':'string'},{'type':'array','items':{'type':'string'},'uniqueItems':True}]}},
        'additionalProperties':False}
    return {'oneOf':[scalar,structure]}
