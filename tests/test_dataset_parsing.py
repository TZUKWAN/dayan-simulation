"""Retain genuine file structure with explicit parsers and original-byte evidence."""
import base64
import hashlib
import io
from zipfile import ZipFile

import pytest

from dayan import datasets
from dayan.dataset_parsing import parse_file, parse_table


def zipped(members):
    output = io.BytesIO()
    with ZipFile(output, 'w') as archive:
        for name, value in members.items():
            archive.writestr(name, value)
    return output.getvalue()


def test_headerless_rows_keep_first_record_joint_columns_empty_values_and_quoted_lines():
    raw = '001\t农户甲\t\n002\t"跨\n行"\t3\n'.encode()
    rows, receipt = parse_table(raw, {'header': False, 'fieldnames': ['id','name','value']}, format='tsv')
    assert rows == [{'id':'001','name':'农户甲','value':''}, {'id':'002','name':'跨\n行','value':'3'}]
    assert receipt['records'] == 2 and receipt['header'] is False
    assert receipt['automatic_type_conversion'] is False
    rows, _ = parse_table('编号,姓名\n01,小李\n'.encode('gb18030'), {'encoding':'gb18030'})
    assert rows == [{'编号':'01','姓名':'小李'}]
    for options in ({'header':False}, {'header':'false'}, {'header':False,'fieldnames':['x','x']},
                    {'header':True,'fieldnames':['x']}, {'delimiter':'::'}, {'execute':'python'}):
        with pytest.raises(ValueError):
            parse_table(b'a,b\n1,2\n', options)
    for raw in (b'a,b\n1\n', b'a,b\n1,2,3\n', b'a,a\n1,2\n', b'a,b\n"unterminated,2\n'):
        with pytest.raises(ValueError):
            parse_table(raw)


def test_zip_member_selection_original_bytes_and_parser_identity(tmp_path, monkeypatch):
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    raw = zipped({'a.dat':'1\t2\n3\t4\n','b.dat':'5\t6\n'})
    ids = []
    for member in ('a.dat','b.dat'):
        options = {'archive_member':member,'header':False,'fieldnames':['source','target']}
        ds = datasets.ingest(raw,name='明确的协议夹具',format='tsv.zip',source='fixture',parse_options=options)
        loaded = datasets.load(ds['dataset_id'])
        assert (datasets.dataset_dir()/ds['dataset_id']/'original').read_bytes() == raw
        assert loaded['parsing']['archive_member'] == member
        assert loaded['sha256'] == hashlib.sha256(raw).hexdigest()
        assert loaded['parse_options'] == options
        assert ds['n_records'] == (2 if member=='a.dat' else 1)
        ids.append(ds['dataset_id'])
    assert ids[0] != ids[1]
    with pytest.raises(ValueError,match='archive_member'):
        parse_file(raw,'tsv.zip',limit=1000)
    for member in ('../a.dat','missing.dat'):
        with pytest.raises(ValueError):
            parse_file(raw,'csv.zip',{'archive_member':member},limit=1000)
    with pytest.raises(ValueError,match='超预算'):
        parse_file(zipped({'large.csv':'a\n'+'1\n'*50}),'csv.zip',{'archive_member':'large.csv'},limit=20)
    with pytest.raises(ValueError,match='ZIP'):
        parse_file(b'not zip','csv.zip',{'archive_member':'a.csv'},limit=1000)


def test_jsonl_and_geojson_preserve_feature_identity_geometry_and_reject_nonfinite():
    raw = b'{"id":"001","geometry":{"type":"Point","coordinates":[114,30]}}\n'
    rows, receipt = parse_file(raw,'jsonl',limit=1000)
    assert rows[0]['id']=='001' and rows[0]['geometry']['coordinates']==[114,30]
    assert receipt['format']=='jsonl'
    with pytest.raises(ValueError,match='非有限'):
        parse_file(b'{"x":NaN}','json',limit=1000)
    with pytest.raises(ValueError,match='encoding'):
        parse_file(b'[]','json',{'delimiter':','},limit=1000)
    geo = b'{"type":"FeatureCollection","features":[{"type":"Feature","id":"original-id","properties":{"id":"property-id"},"geometry":null}]}'
    feature = parse_file(geo,'geojson',limit=1000)[0]['features'][0]
    assert feature['id']=='original-id' and feature['properties']['id']=='property-id'


def test_actual_managed_import_api_preserves_zip_and_exposes_agent_parser_contract(tmp_path, monkeypatch):
    from api_client import local_client
    from dayan.server import app
    from dayan.agent.tools import TOOL_SPECS
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path/'data'))
    raw = zipped({'contacts.dat':'20\t001\t002\n40\t002\t003\n'})
    client = local_client(app)
    response = client.post('/api/datasets/import',json={'name':'无标题接触表协议夹具','format':'tsv.zip',
        'content_base64':base64.b64encode(raw).decode(), 'parse_options':{'archive_member':'contacts.dat',
        'header':False,'fieldnames':['time','source','target']}})
    assert response.status_code==200, response.text
    data = response.json()
    assert data['n_records']==2 and data['preview'][0]=={'time':'20','source':'001','target':'002'}
    assert client.get(data['data_url']).content==raw
    spec=next(spec for spec in TOOL_SPECS if spec['name']=='collect_data')
    parser=spec['parameters']['properties']['parse_options']
    assert parser['type']==['object','null'] and 'archive_member' in parser['properties']


def test_public_tool_describes_actual_formats_and_usable_roles_before_network():
    from dayan.agent.tools import TOOL_SPECS, call_tool
    from dayan.dataset_parsing import FILE_FORMATS
    schema=next(spec for spec in TOOL_SPECS if spec['name']=='collect_data')['parameters']['properties']
    assert schema['format']['enum']==list(FILE_FORMATS)
    assert schema['role']['enum']==list(datasets.DATA_ROLES)
    assert schema['role']['default']=='input' and 'contract.kind' in schema['role']['description']
    # An invalid HTTPS address would fail earlier if either bad argument reached transport.
    result=call_tool('collect_data',url='http://127.0.0.1',format='zip')
    assert not result['ok'] and 'archive_member' in result['error']
    assert result['available_formats']==list(FILE_FORMATS)
    result=call_tool('collect_data',url='http://127.0.0.1',format='csv',role='temporal_contact_edges')
    assert not result['ok'] and '未知数据用途role' in result['error']
    assert 'input' in result['available_roles']
    result=call_tool('import_collection',collection_id='not-a-real-collection',role='invented')
    assert not result['ok'] and '未知数据用途role' in result['error']


def test_data_profiles_do_not_conflate_text_ids_categories_or_missing(tmp_path,monkeypatch):
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    raw=b'[{"id":"001","group":"A","v":null},{"id":"1","group":"B","v":""},{"id":"001","group":"A"}]'
    ds=datasets.ingest(raw,name='类型与缺失的协议夹具',format='json',source='controlled-test-fixture')
    profile=datasets.analyze(ds['dataset_id'])
    assert profile['field_profiles']['id']['distinct_nonempty']==2
    assert profile['field_profiles']['group']['distinct_nonempty']==2
    assert profile['field_profiles']['group']['null']==0
    assert profile['field_profiles']['group']['numeric_cast_failures']==3
    assert {key:profile['field_profiles']['v'][key] for key in ('absent','null','blank_string')}=={
        'absent':1,'null':1,'blank_string':1}
    assert profile['verification_scope']['cross_dataset_links']=='not_checked'
    assert datasets.load(ds['dataset_id'])['data'][0]['id']=='001'


def test_collection_parser_keeps_original_archive_and_feature_identity(monkeypatch):
    from dayan.collection import connectors
    url='https://example.org/controlled-file'
    raw=zipped({'contacts.dat':'20\t001\t002\n40\t002\t003\n'})
    # Explicit transport fixture: only parsing/provenance are tested here.
    monkeypatch.setattr(connectors,'_get',lambda *args,**kwargs:(raw,url))
    page,=connectors.resource_file({'url':url,'format':'tsv','archive_member':'contacts.dat',
        'parse_options':{'header':False,'fieldnames':['time','source','target']}},1)
    assert page.raw==raw and len(page.records)==2
    assert page.records[0]['source']=='001' and page.meta['provenance']['parsing']['header'] is False
    raw=b'{"type":"FeatureCollection","features":[{"type":"Feature","id":"feature","properties":{"id":"property","geometry":"attribute"},"geometry":null}]}'
    page,=connectors.resource_file({'url':url,'format':'geojson'},1)
    assert page.records[0]['geojson_feature']['id']=='feature'
    assert page.records[0]['geojson_feature']['properties']['geometry']=='attribute'
    assert page.records[0]['id']=='property' and page.records[0]['geometry'] is None
