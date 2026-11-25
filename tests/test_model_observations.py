"""Contract fixtures, not empirical validation or a native Agent acceptance."""
from copy import deepcopy
import json

import pytest

from dayan import datasets
from dayan.research.model_observations import prepare_targets, audit_input_usage
from dayan.solvers.codec import digest


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setenv('DAYAN_DATA_DIR', str(tmp_path))
    rows = [{'year': i + 2000, 'region': 'A', 'population': 10 + i, 'rain': i * 2} for i in range(6)]
    record = datasets.ingest(json.dumps(rows).encode(), name='明确的协议夹具', format='json',
        source='test-fixture', role='input', metadata={'units': {'year': 'year', 'population': 'person'}})
    return record, rows


def binding(record):
    return {'id': 'people', 'dataset_id': record['dataset_id'], 'observable': 'population',
        'fields': {'t': {'type': 'number', 'unit': 'year'}, 'y': {'type': 'number', 'unit': 'person'},
                   'available': {'type': 'number', 'unit': 'year'},
                   'region': {'type': 'string', 'unit': '1'}},
        'columns': {'t': {'field': 'year', 'source_unit': 'year', 'offset': -2000,
                           'transformation_note': '2000年度观测为t=0'},
                    'y': {'field': 'population', 'source_unit': 'person'}, 'region': {'field': 'region'},
                    'available': {'field':'year','source_unit':'year','offset':-2000,
                                  'transformation_note':'数值夹具假设即时可知，并非现实发布版本'}},
        'time_field': 't', 'value_field': 'y', 'series_by': ['region'], 'time_origin': '2000年度',
        'available_field':'available','availability_basis':'数值夹具规定即时可知，不是现实发布时间'}


def prepare(bindings, **kwargs):
    return prepare_targets(bindings, observables={'population': {'unit': 'person'}, 'alias': {'unit': 'person'}},
        time_unit='year', time_origin='2000年度',
        split=kwargs.get('split', {'kind': 'forward_time', 'training_end': 1, 'validation_end': 3}))


def test_targets_keep_actual_rows_units_series_and_three_roles(source):
    record, rows = source
    result = prepare([binding(record)])
    assert [row['time'] for row in result['roles']['holdout']] == [4, 5]
    assert [row['value'] for row in result['roles']['training']] == [10, 11]
    assert result['roles']['holdout'][0]['provenance']['source_row_index'] == 4
    assert result['roles']['holdout'][0]['provenance']['row_sha256'] == digest(rows[4])
    assert result['roles']['holdout'][0]['series'] == {'region': 'A'}
    assert result['sha256'] == digest({k: v for k, v in result.items() if k != 'sha256'})
    assert result['verification_scope']['release_times'] == 'not_established'
    assert datasets.load(record['dataset_id'])['data'] == rows


def test_missing_binding_origin_inherits_shared_label_without_changing_clock_or_legacy_identity(source):
    record,_=source
    explicit=binding(record)
    inherited=deepcopy(explicit);inherited.pop('time_origin')
    before=deepcopy(inherited)
    expected=prepare([explicit])
    actual=prepare([inherited])
    assert actual==expected and inherited==before
    assert [row['time'] for row in actual['roles']['holdout']]==[4.,5.]
    conflict=deepcopy(inherited);conflict['time_origin']='2001年度'
    with pytest.raises(ValueError,match='统一time_origin='):
        prepare([conflict])


def test_matching_scope_labels_do_not_claim_verified_source_row_membership(tmp_path,monkeypatch):
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    record=datasets.ingest(b'[{"region":"B","population":42}]',name='明确范围标签测试',
        format='json',source='test-declared-scope-labels')
    mapping={'dataset_id':record['dataset_id'],'field':'population','parameter':'initial',
        'source_unit':'person','target_unit':'person','source_scope':'A','target_scope':'A'}
    parameters,evidence=datasets.bind_parameters([mapping])
    assert parameters=={'initial':42.}
    assert evidence[0]['scope_status']=='declared_match'
    assert evidence[0]['scope_verification']=='matching_declared_labels_not_source_row_membership'
    with pytest.raises(ValueError,match='地区/主体范围不一致'):
        datasets.bind_parameters([{**mapping,'target_scope':'B'}])


@pytest.mark.parametrize('change,match', [
    ('time_unit', '单位'), ('value_unit', '单位'), ('origin', '原点'),
    ('missing', '缺失'), ('mixed_series', '多个系列'), ('duplicate', '重复观测'),
    ('false_filter', '过滤字段缺失'), ('empty', '没有匹配观测'), ('unknown_output', 'observable'),
])
def test_ambiguous_or_invalid_targets_fail_without_dropping(source, change, match):
    record, rows = source
    b = binding(record)
    if change == 'time_unit': b['fields']['t']['unit'] = 'second'
    elif change == 'value_unit': b['fields']['y']['unit'] = 'kg'
    elif change == 'origin': b['time_origin'] = '2001年度'
    elif change == 'false_filter': b['filters'] = {'absent': 1}
    elif change == 'empty': b['filters'] = {'region': 'B'}
    elif change == 'unknown_output': b['observable'] = 'not_computed'
    else:
        if change == 'missing': rows[2]['population'] = None
        elif change == 'mixed_series': rows[2]['region'] = 'B'
        else: rows.append({**rows[2], 'population': 999})
        r = datasets.ingest(json.dumps(rows).encode(), name=change, format='json', source='test-fixture')
        b['dataset_id'] = r['dataset_id']
    with pytest.raises(ValueError, match=match): prepare([b])


def test_aliases_and_offset_changes_cannot_reuse_same_source_cells(source):
    record, rows = source
    alias = datasets.ingest(('\n'.join(json.dumps(r) for r in reversed(rows))).encode(),
        name='另一个DS和格式', format='jsonl', source='test-alias', role='input')
    a, b = binding(record), binding(alias)
    b.update(id='alias', observable='alias')
    b['columns']['t']['offset'] = -1990
    with pytest.raises(ValueError, match='重复观测/源单元格'): prepare([a, b])


def test_all_three_roles_required_and_declared_holdout_cannot_be_training(source):
    record, rows = source
    with pytest.raises(ValueError, match='同时有训练、验证和留出'):
        prepare([binding(record)], split={'kind': 'forward_time', 'training_end': 4, 'validation_end': 5})
    held = datasets.ingest(json.dumps(rows).encode(), name='只用于留出', format='json', source='test', role='holdout')
    with pytest.raises(ValueError, match='用途与实际划分冲突'): prepare([binding(held)])
    with pytest.raises(ValueError, match='验证终点须晚于'):
        prepare([binding(record)], split={'kind': 'forward_time', 'training_end': 4, 'validation_end': 3})


def access(b, *, at=1, reuse='none'):
    return {'binding_sha256': digest(b), 'available_at': at, 'basis': '测试声明，并非外部发布日期核验',
            'training_target_use': reuse}


def audit(targets, b, **kw):
    return audit_input_usage(targets, [b], availability=[access(b, **kw)],
                             information_mode='forecast', forecast_origin=1)


def test_input_alias_leakage_and_available_information_not_just_dataset_role(source):
    record, rows = source
    targets = prepare([binding(record)])
    alias = datasets.ingest(('\n'.join(json.dumps(r) for r in rows)).encode(),
                           name='复制留出为input', format='jsonl', source='test-alias', role='input')
    b = {'dataset_id': alias['dataset_id'], 'field': 'population', 'aggregate': 'mean', 'parameter': 'initial'}
    with pytest.raises(ValueError, match='验证/留出目标单元格'): audit(targets, b)
    b['field'] = 'rain'
    result = audit(targets, b)
    assert result['inputs'][0]['training_target_cells'] == 0
    with pytest.raises(ValueError, match='之后才可用'): audit(targets, b, at=2)
    late = audit_input_usage(targets, [b], availability=[access(b, at=2)],
                            information_mode='retrospective_conditioning', forecast_origin=1)
    assert late['information_mode'] == 'retrospective_conditioning'
    with pytest.raises(ValueError, match='同一实际数据映射'):
        audit_input_usage(targets, [b], availability=[{**access(b), 'binding_sha256': 'wrong'}],
                          information_mode='forecast', forecast_origin=1)


def test_scalar_first_input_checks_only_consumed_initial_cell_and_declares_reuse(source):
    record, rows = source
    targets = prepare([binding(record)])
    b = {'dataset_id': record['dataset_id'], 'field': 'population', 'aggregate': 'first',
         'parameter': 'initial', 'order_by': 'year'}
    with pytest.raises(ValueError, match='复用了训练目标'): audit(targets, b)
    result = audit(targets, b, reuse='initial_condition')
    assert result['inputs'][0]['source_row_indices'] == [0]
    assert result['inputs'][0]['training_target_cells'] == 1
    b['aggregate'] = 'last'
    with pytest.raises(ValueError, match='验证/留出目标单元格'): audit(targets, b, reuse='initial_condition')


def test_structured_inputs_cannot_hide_target_column_or_full_geometry_properties(source):
    record, rows = source
    targets = prepare([binding(record)])
    b = {'dataset_id': record['dataset_id'], 'port': 'forcing', 'contract': {'kind': 'records'},
         'columns': {'rain': {'field': 'rain'}, 'target_under_another_name': {'field': 'population'}}}
    with pytest.raises(ValueError, match='验证/留出目标单元格'): audit(targets, b)
    del b['columns']['target_under_another_name']
    assert audit(targets, b)['status'] == 'declared_contract_checked'


def test_full_geojson_properties_are_checked_even_if_not_declared_in_columns(source):
    _, rows = source
    features = [{'type': 'Feature', 'properties': row, 'geometry': {'type': 'Point', 'coordinates': [0, 0]}}
                for row in rows]
    record = datasets.ingest(json.dumps({'type': 'FeatureCollection', 'features': features}).encode(),
                            name='带观测属性的协议几何夹具', format='geojson', source='test-fixture')
    target = binding(record)
    target['path'] = 'features'
    for column in target['columns'].values():
        column['pointer'] = '/properties/' + column.pop('field')
    targets = prepare([target])
    b = {'dataset_id': record['dataset_id'], 'port': 'geometry', 'contract': {'kind': 'geojson'},
         'columns': {'rain': {'pointer': '/properties/rain'}}}
    with pytest.raises(ValueError, match='验证/留出目标单元格'): audit(targets, b)


def test_changed_raw_data_fails_provenance_before_research(source):
    record, _ = source
    (datasets.dataset_dir() / record['dataset_id'] / 'original').write_bytes(b'changed')
    with pytest.raises(ValueError, match='原始文件哈希不一致'): prepare([binding(record)])


def test_observed_date_does_not_establish_historical_availability(source):
    record,_=source
    b=binding(record)
    b.pop('available_field');b.pop('availability_basis')
    b['fields'].pop('available');b['columns'].pop('available')
    targets=prepare([b])
    with pytest.raises(ValueError,match='仅观测年份'):
        audit_input_usage(targets,[],availability=[],information_mode='forecast',forecast_origin=1)
    assert audit_input_usage(targets,[],availability=[],information_mode='retrospective_conditioning',forecast_origin=1)
    b=binding(record)
    b['columns']['available']['offset']=-1998
    delayed=prepare([b])
    with pytest.raises(ValueError,match='训练观测.*之后才可获得'):
        audit_input_usage(delayed,[],availability=[],information_mode='forecast',forecast_origin=1)
