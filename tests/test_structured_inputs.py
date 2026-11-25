"""Explicit protocol fixtures: verify row fidelity, not empirical model validity."""
from copy import deepcopy
import json

import pytest

from dayan import datasets
from dayan.solvers.codec import digest
from dayan.structured_inputs import port_contracts, prepare_bindings, prepare_structured


def dataset(rows, role='input', metadata=None):
    return datasets.ingest(json.dumps(rows).encode(), name='结构输入协议夹具', format='json',
                           source='controlled-test-fixture', license='test-only', role=role,
                           metadata=metadata)['dataset_id']


def people_binding(dataset_id):
    return {'dataset_id': dataset_id, 'port': 'people', 'contract': {
        'kind': 'records', 'purpose': 'initialization', 'primary_key': ['id'],
        'fields': {'id': {'type': 'string', 'unit': '1'},
                   'cash': {'type': 'number', 'unit': 'CNY', 'nullable': True},
                   'group': {'type': 'string', 'unit': '1'}}},
        'columns': {'id': {'field': 'id'}, 'cash': {'field': 'income', 'source_unit': 'CNY', 'missing_values': ['?']},
                    'group': {'field': 'category'}}}


def edge_binding(dataset_id):
    return {'dataset_id': dataset_id, 'port': 'contacts', 'contract': {
        'kind': 'edges', 'purpose': 'exogenous_input', 'primary_key': ['at', 'source', 'target'],
        'directed': False,
        'fields': {'at': {'type': 'integer', 'unit': 'second'},
                   'source': {'type': 'string', 'unit': '1'}, 'target': {'type': 'string', 'unit': '1'}},
        'endpoints': {side: {'field': side, 'port': 'people', 'key': 'id'} for side in ('source', 'target')},
        'clock': {'field': 'at', 'origin': '保留原始相对秒，不推断日期', 'interval': 20,
                  'anchor':'start', 'boundary': 'left_closed_right_open'}},
        'columns': {'at': {'field': 'time', 'source_unit': 'second'},
                    'source': {'field': 'source'}, 'target': {'field': 'target'}},
        'order_by': 'at'}


def test_joint_records_missing_ids_and_numeric_sort_are_lossless(tmp_path, monkeypatch):
    monkeypatch.setenv('DAYAN_DATA_DIR', str(tmp_path))
    pid = dataset([{'id': '001', 'income': '40.5', 'category': 'A'},
                   {'id': '002', 'income': '?', 'category': 'B'},
                   {'id': '003', 'income': '0', 'category': 'A'}])
    binding = people_binding(pid)
    inputs, evidence = prepare_structured([binding])
    assert inputs['people']['columns'] == {'id': ['001','002','003'], 'cash': [40.5,None,0.], 'group': ['A','B','A']}
    assert inputs['people']['source_row_indices'] == [0,1,2]
    assert evidence[0]['missing'] == {'id':0,'cash':1,'group':0}
    assert evidence[0]['input_sha256'] == digest(inputs['people'])
    assert '001' not in json.dumps(evidence) and 'income' in json.dumps(evidence)
    edges = edge_binding(dataset([{'time':'100', 'source':'001', 'target':'003'},
                                  {'time':'20', 'source':'002', 'target':'001'}]))
    inputs, _ = prepare_structured([edges, binding])
    assert inputs['contacts']['columns'] == {'at':[20,100], 'source':['002','001'], 'target':['001','003']}
    assert inputs['contacts']['source_row_indices'] == [1,0]
    filtered = deepcopy(binding)
    filtered['filters'] = {'category':'A'}
    assert prepare_structured([filtered])[0]['people']['columns']['cash'] == [40.5,0.]


def test_interval_end_anchor_preserves_raw_time_and_matches_machine_readable_contract(tmp_path,monkeypatch):
    import jsonschema
    from dayan.structured_inputs import binding_schema
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    people=people_binding(dataset([{'id':'001','income':'1','category':'A'}]))
    edge=edge_binding(dataset([{'time':'20','source':'001','target':'001'}]))
    edge['contract']['clock']['anchor']='end'
    inputs,evidence=prepare_structured([people,edge])
    assert inputs['contacts']['columns']['at']==[20]
    assert evidence[1]['time_summary']['first_start']==0
    assert evidence[1]['time_summary']['last_end']==20
    jsonschema.validate(edge,binding_schema())
    legacy=deepcopy(edge)
    legacy['contract']['clock'].pop('anchor')
    old_inputs,old_evidence=prepare_structured([people,legacy])
    assert 'anchor' not in old_inputs['contacts']['contract']['clock']
    assert old_evidence[1]['time_summary']['anchor']=='unspecified_legacy'
    assert 'first_start' not in old_evidence[1]['time_summary']
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(legacy,binding_schema())
    bad=deepcopy(people)
    bad['contract']['fields']['group']['unit']='category'
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(bad,binding_schema())
    with pytest.raises(ValueError,match='无量纲'):prepare_structured([bad])
    edge['contract']['clock']['end_field']='at'
    edge['contract']['clock'].pop('interval')
    with pytest.raises(ValueError,match='anchor=end'):prepare_structured([people,edge])


def test_foreign_keys_duplicates_schema_mismatches_and_missing_are_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv('DAYAN_DATA_DIR', str(tmp_path))
    people = people_binding(dataset([{'id':'001','income':'1','category':'A'}]))
    edges = edge_binding(dataset([{'time':'20','source':'001','target':'002'}]))
    with pytest.raises(ValueError, match='不存在的真实ID'):
        prepare_structured([people,edges])
    with pytest.raises(ValueError, match='已有端口'):
        prepare_structured([edges])
    with pytest.raises(ValueError, match='input_ports'):
        prepare_structured([people], {})
    declared = {'people': deepcopy(people['contract'])}
    prepare_structured([people], declared)
    declared['people']['fields']['cash']['unit'] = 'USD'
    with pytest.raises(ValueError, match='input_ports'):
        prepare_structured([people], declared)
    for rows, pattern in (([{'id':'001','income':'1','category':'A'}]*2, '重复'),
                          ([{'id':'001','category':'A'}], '源字段不存在'),
                          ([{'id':1,'income':'1','category':'A'}], '文字字段'),
                          ([{'id':'001','income':True,'category':'A'}], '布尔')):
        with pytest.raises(ValueError, match=pattern):
            prepare_structured([people_binding(dataset(rows))])
    no_null = people_binding(dataset([{'id':'001','income':'?','category':'A'}]))
    no_null['contract']['fields']['cash']['nullable'] = False
    with pytest.raises(ValueError, match='缺失值'):
        prepare_structured([no_null])


def test_explicit_units_integer_precision_and_input_roles(tmp_path, monkeypatch):
    monkeypatch.setenv('DAYAN_DATA_DIR', str(tmp_path))
    big = '123456789012345678901234567890123456789'
    binding = {'dataset_id': dataset([{'duration':'2','large':big}], metadata={'units':{'duration':'minute'}}),
        'port':'measurements','contract': {'kind':'records','purpose':'initialization',
            'fields':{'seconds':{'type':'integer','unit':'second'},'large':{'type':'integer','unit':'1'}}},
        'columns':{'seconds':{'field':'duration','scale':60},'large':{'field':'large'}}}
    prepared, _ = prepare_structured([binding])
    assert prepared['measurements']['columns'] == {'seconds':[120],'large':[int(big)]}
    bad = deepcopy(binding)
    bad['columns']['seconds']['source_unit'] = 'hour'
    with pytest.raises(ValueError, match='元数据'):
        prepare_structured([bad])
    bad['columns']['seconds'] = {'field':'duration','scale':1}
    with pytest.raises(ValueError, match='单位/scale'):
        prepare_structured([bad])
    for role in ('holdout','validation','background','calibration','exogenous_input'):
        bad = people_binding(dataset([{'id':'001','income':'1','category':'A'}], role))
        with pytest.raises(ValueError, match='数据角色'):
            prepare_structured([bad])
    bad = deepcopy(binding)
    bad['columns']['seconds'].update(offset=.5,transformation_note='测试非整数偏移')
    with pytest.raises(ValueError, match='不能取整'):
        prepare_structured([bad])
    bad['columns']['seconds'].update(offset=1,transformation_note='显式重置时间原点')
    assert prepare_structured([bad])[0]['measurements']['columns']['seconds']==[121]


def test_contracts_are_explicit_and_parameter_binding_remains_compatible(tmp_path, monkeypatch):
    monkeypatch.setenv('DAYAN_DATA_DIR', str(tmp_path))
    people=people_binding(dataset([{'id':'001','income':'1','category':'A'}]))
    for change in ({'kind':'imaginary'}, {'purpose':'holdout'}, {'execute':'do_something'},
                   {'primary_key':['missing']}, {'fields':{}}):
        with pytest.raises(ValueError):
            port_contracts({'people':{**people['contract'],**change}})
    scalar_id = dataset([{'rate':2},{'rate':4}])
    scalar = {'dataset_id':scalar_id,'field':'rate','aggregate':'mean','parameter':'rate'}
    parameters, inputs, evidence = prepare_bindings([scalar,people])
    assert parameters == {'rate':3.} and inputs['people']['count']==1
    assert [entry.get('port') for entry in evidence] == [None,'people']
    # Old direct scalar path must reject an unfamiliar structured binding rather
    # than dropping it and falsely reporting successful ingestion into a model.
    with pytest.raises(ValueError, match='未知数据映射字段'):
        datasets.bind_parameters([people])
