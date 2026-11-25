"""Exact typed heterogeneous state, explicitly constructed archive protocol fixtures."""
from copy import deepcopy

import numpy as np
import pytest

from dayan.population_groups import (encode_groups, validate_groups, decode_attribute, find_entity,
                                     sample_entities, field_values, field_metadata, type_counts)


def populations():
    return encode_groups([
        {"id": "workers", "type": "person", "ids": ["张/1", "李:2", "王3"], "columns": {
            "x": [0., 1., 2.], "y": [0., 0., 0.], "income": [10., None, 30.],
            "status": ["working", "working", None]}, "units": {"x": "m", "y": "m", "income": "CNY", "status": "category"}},
        {"id": "firms", "type": "firm", "ids": [2**60], "columns": {"x": [4.], "y": [0.], "capital": [90]},
         "units": {"x": "m", "y": "m", "capital": "CNY"}},
        {"id": "regulators", "type": "person", "columns": {"x": np.array([], dtype=float), "y": np.array([], dtype=float)},
         "units": {"x": "m", "y": "m"}},
    ])


def test_complete_groups_preserve_exact_identity_unit_category_and_missing_state():
    population = populations()
    assert validate_groups(population) is population
    assert population["count"] == 4 and type_counts(population) == {"person": 3, "firm": 1}
    assert find_entity(population, "workers:张/1")["income"] == 10
    assert find_entity(population, "workers:李:2")["income"] is None
    assert find_entity(population, "workers:王3")["status"] is None
    assert find_entity(population, "firms:" + str(2**60))["local_id"] == 2**60
    assert "income" not in find_entity(population, "firms:" + str(2**60))
    assert find_entity(population, "workers:unknown") is None
    with pytest.raises(ValueError, match="不能按显示顺序"):
        find_entity(population, "0")
    income = field_values(population, "workers.income")
    assert np.ma.isMaskedArray(income) and income.mask.tolist() == [False, True, False]
    assert income.compressed().tolist() == [10, 30]
    assert field_values(population, "x").tolist() == [0, 1, 2, 4]
    assert field_values(population, "workers.status").tolist() == ["working", "working", None]
    assert field_metadata(population, "income")["not_applicable"] == 1


def test_display_sampling_preserves_rare_group_and_never_invents_missing_attributes():
    population = encode_groups([
        {"id": "many", "type": "person", "columns": {"x": np.arange(10000.), "y": np.zeros(10000)}},
        {"id": "one", "type": "regulator", "columns": {"authority": [100.]}},
    ])
    sampled = sample_entities(population, size=15)
    assert len(sampled) == 15 and {row["group"] for row in sampled} == {"many", "one"}
    lone = next(row for row in sampled if row["group"] == "one")
    assert lone == {"id": "one:0", "local_id": 0, "group": "one", "type": "regulator", "authority": 100}
    assert population["count"] == 10001
    with pytest.raises(ValueError, match="静默隐藏"):
        sample_entities(population, size=1)


def test_groups_never_merge_unknown_or_different_units_or_redefine_identity():
    groups = [
        {"id": "a", "type": "person", "columns": {"age": [12]}, "units": {"age": "years"}},
        {"id": "b", "type": "person", "columns": {"age": [12]}, "units": {"age": "months"}},
    ]
    population = encode_groups(groups)
    with pytest.raises(ValueError, match="单位"):
        field_values(population, "age")
    assert field_values(population, "a.age").tolist() == [12]
    assert field_values(population, "b.age").tolist() == [12]
    groups[1]["units"] = {}
    with pytest.raises(ValueError, match="单位"):
        field_values(encode_groups(groups), "age")
    with pytest.raises(ValueError, match="唯一"):
        encode_groups([{"id": "a", "type": "person", "ids": [1, "1"], "columns": {"age": [1, 2]}}])
    with pytest.raises(ValueError, match="数量"):
        encode_groups([{**groups[0], "count": 1000}])


def test_explicit_mask_and_empty_string_column_keep_missing_and_category_semantics():
    masked = np.ma.array([2., -999., 4.],mask=[False,True,False])
    population = encode_groups([{'id':'people','type':'person','columns':{'income':masked}}])
    assert field_values(population,'income').compressed().tolist() == [2,4]
    assert find_entity(population,'people:1')['income'] is None
    empty = encode_groups([{'id':'empty','type':'person','columns':{'status':np.array([],dtype=str)}}])
    assert empty['groups'][0]['columns']['status']['kind'] == 'categorical'
    assert validate_groups(empty)['count'] == 0


def test_malformed_counts_mask_and_encoded_ids_fail_without_sampling_or_padding():
    for mutate in (
        lambda p: p.update(count=1000),
        lambda p: p["groups"][0]["ids"]["values"].append("extra"),
        lambda p: p["groups"][0]["columns"]["income"].update(valid={}),
        lambda p: p["groups"][0]["columns"]["x"].update(data={}),
    ):
        population = deepcopy(populations())
        mutate(population)
        with pytest.raises((ValueError, TypeError, KeyError)):
            validate_groups(population)


def test_full_distribution_and_views_keep_missingness_and_different_populations_separate():
    from dayan.population import entity_at, entity_trace, playback_frame
    from dayan.population_analysis import distribution, frame_statistics, spatial_density
    population = populations()
    frame = {'sim_t':0, 'space':{'bounds':[0,-1,5,1], 'unit':'m'}, 'population':population,
             'entities':sample_entities(population,size=2)}
    stats = frame_statistics(frame)
    income = stats['distributions']['workers.income']
    assert income['n'] == 2 and income['missing'] == 1 and income['not_applicable'] == 1
    assert income['mean'] == 20 and income['unit'] == 'CNY'
    assert stats['distributions']['firms.capital']['mean'] == 90
    assert stats['distributions']['workers.status']['counts'] == {'working':2}
    assert stats['distributions']['workers.status']['missing'] == 1
    assert 'income' not in stats['distributions']  # No fabricated firm/regulator income.
    assert spatial_density(frame)['n'] == 4
    region = distribution(frame,'workers.income',[0,-1,2,1])
    assert region['n'] == 1 and region['missing'] == 1 and region['mean'] == 10
    assert entity_at(frame,'workers:李:2')['income'] is None
    assert entity_trace([frame], 'firms:'+str(2**60))[0]['capital'] == 90
    public = playback_frame(frame)
    assert public['statistics'] == {**stats, 'movement':public['statistics']['movement']}
    assert public['population']['count'] == 4
    assert all('columns' not in group and 'ids' not in group for group in public['population']['groups'])
    assert 'columns' in frame['population']['groups'][0]  # No mutation of full archive.


def test_movement_matches_stable_ids_across_row_reordering_births_and_exits():
    from dayan.population_analysis import movement_between
    def frame(t,ids,x):
        return {'sim_t':t,'population':encode_groups([{'id':'people','type':'person','ids':ids,
            'columns':{'x':x,'y':np.zeros(len(x))},'units':{'x':'m','y':'m'}}])}
    old = frame(0,['a','b','c'],[0.,10.,20.])
    new = frame(1,['c','a','new'],[22.,0.,500.])
    result = movement_between(new,old)
    assert result['comparable'] == 2 and result['moved'] == 1 and result['stationary'] == 1
    assert result['meanDistance'] == 1 and result['entered'] == 1 and result['exited'] == 1
    assert result['unit'] == 'm'


def test_births_in_nonspatial_groups_update_cached_denominators_and_region_scope():
    from dayan.population_analysis import frame_statistics, distribution, spatial_density, movement_between
    def frame(ids):
        return {'sim_t':len(ids),'space':{'bounds':[0,-1,3,1],'unit':'m'},'population':encode_groups([
            {'id':'people','type':'person','columns':{'x':[0.,2.],'y':[0.,0.],'income':[10.,20.]},
             'units':{'x':'m','y':'m','income':'CNY'}},
            {'id':'firms','type':'firm','ids':ids,'columns':{'capital':[10.]*len(ids)},'units':{'capital':'CNY'}}])}
    old,new=frame(['a']),frame(['a','b'])
    assert distribution(old,'people.income')['not_applicable']==1
    assert distribution(new,'people.income')['not_applicable']==2
    assert spatial_density(old)['not_spatial']==1
    assert spatial_density(new)['not_spatial']==2
    stats=frame_statistics(new)
    assert stats['distributions']['group']['counts']=={'people':2,'firms':2}
    region=distribution(new,'group',[0,-1,1,1])
    assert region['n']==1 and region['not_spatial']==2 and region['counts']=={'people':1}
    movement=movement_between(new,old)
    assert movement['entered']==1 and movement['exited']==0 and movement['comparable']==2


def test_state_frame_rejects_fabricated_preview_and_preserves_small_exact_clock():
    from dayan.stateframe import validate_state_frame
    population = populations()
    frame = {'population':population, 'entities':sample_entities(population,2), 'sim_t':1e-12}
    assert validate_state_frame(frame,1e-12)['sim_t'] == 1e-12
    wrong = deepcopy(frame)
    wrong['entities'][0]['x'] += 1
    with pytest.raises(ValueError, match='样本'):
        validate_state_frame(wrong,1e-12)
    wrong = deepcopy(frame)
    wrong['sim_t'] = 2e-12
    with pytest.raises(ValueError, match='时钟'):
        validate_state_frame(wrong,1e-12)


def test_saved_group_protocol_fixture_is_queryable_by_full_id_and_analyzed_without_sample_bias(tmp_path, monkeypatch):
    """Constructed archive fixture tests storage/API consumers; not a claimed simulation."""
    from uuid import uuid4
    from urllib.parse import quote
    from api_client import local_client
    from dayan.runtime import RunResult, assert_loaded_source
    from dayan.run_store import get_store, state_stream
    from dayan.server import app
    from dayan.view_analysis import analyze_view
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    population = populations()
    frames = [{'sim_t':t, 'space':{'bounds':[0,-1,5,1],'unit':'m'},'population':population,
               'entities':sample_entities(population,size=2),'provenance':'entity'} for t in range(3)]
    rid = 'R20261124T000000-'+uuid4().hex
    rr = RunResult(model_id='GROUP_PROTOCOL_FIXTURE', observations=[{'sim_t':t,'fixture_value':t+1} for t in range(3)],
                   state_frames=frames, manifest={'run_id':rid,'test_scope':'constructed archive protocol fixture',
                                                   'source_fingerprint':assert_loaded_source()})
    get_store().save_run(rr,source='constructed_protocol_fixture',request_text='测试夹具，不是已建模仿真')
    saved = get_store().load(rid)
    view = analyze_view([saved],rid)
    assert view['entity_count'] == 4 and view['distribution']['field'] == 'group'
    assert view['distribution']['counts'] == {'workers':3,'firms':1,'regulators':0}
    selected = analyze_view([saved],rid,distribution_field='workers.income',entity_id='workers:张/1',entity_metric='income')
    assert selected['distribution']['mean'] == 20 and selected['entity_trace'][0]['income'] == 10
    stream = state_stream(saved)
    assert stream['n_entities_max'] == 4 and stream['rendered_entities_max'] == 2
    assert stream['frames'][0]['statistics']['distributions']['workers.income']['missing'] == 1
    with local_client(app) as client:
        response = client.get(f'/api/runs/{rid}/entities/{quote("workers:张/1",safe="")}?field=income')
        assert response.status_code == 200, response.text
        assert [row['income'] for row in response.json()['trace']] == [10,10,10]
        result = client.post(f'/api/runs/{rid}/population',json={'sim_t':1,'field':'firms.capital'})
        assert result.status_code == 200, result.text
        assert result.json()['distribution']['mean'] == 90
        assert result.json()['distribution']['not_applicable'] == 3


def test_report_figures_use_full_group_values_and_do_not_put_unlocated_objects_on_map(tmp_path):
    """Actual plotting of declared protocol fixture data, not an empirical simulation."""
    import base64
    import matplotlib.pyplot as plt
    from dayan.fonts import configure_matplotlib
    from dayan.report_spatial_charts import spatial_figures
    from dayan.view_analysis import analyze_view
    configure_matplotlib()
    population = encode_groups([
        {'id':'walkers','type':'person','label':'行人','columns':{'x':[0.,1.,2.],'y':[0.,0.,0.],
            'income':[10.,None,30.],'speed':[1.,2.,3.]}, 'units':{'x':'m','y':'m','income':'CNY','speed':'m/s'}},
        {'id':'firms','type':'firm','label':'企业','columns':{'capital':[100.,200.]},'units':{'capital':'CNY'}},
    ])
    preview = {'encoding':'u8-preview','width':2,'height':1,'source_width':4,'source_height':2,'block_side':2,
               'layers':[{'id':'heat','label':'试验场预览','states':['低','高'],
                          'values':base64.b64encode(bytes([0,255])).decode('ascii')}]}
    frames = [{'sim_t':t,'population':population,'entities':sample_entities(population,2), 'lattice':preview,
               'space':{'bounds':[0,-1,3,1],'unit':'m'}} for t in range(3)]
    record = {'run_id':'fixture','model_id':'GROUP_PROTOCOL_FIXTURE','kind':'run','state_frames':frames,
              'observations':[{'sim_t':t,'test_value':t+1} for t in range(3)],'manifest':{}}
    view = analyze_view([record],'fixture',distribution_field='walkers.income')
    assert view['lattice']['preview_only'] is True
    assert all('count' not in layer for layer in view['lattice']['layers'])
    figures = []
    def save(fig,title,kind,section,caption,**evidence):
        path=tmp_path/(str(len(figures))+'-'+kind+'.png')
        fig.savefig(path)
        plt.close(fig)
        figures.append({'kind':kind,'caption':caption,'evidence':evidence,'path':path})
    spatial_figures(record,view,save)
    previews = [row for row in figures if row['kind']=='lattice_preview']
    assert len(previews)==3 and all(row['evidence']['preview_only'] for row in previews)
    assert all('不能用于逐格数值' in row['caption'] for row in previews)
    density = next(row for row in figures if row['kind']=='population_density')
    assert density['evidence']['entities']==3 and density['evidence']['population_total']==5
    assert density['evidence']['histogram_total']==3 and '2 个无二维坐标' in density['caption']
    distribution = next(row for row in figures if row['kind']=='entity_distribution')
    assert distribution['evidence']['distribution']['mean']==20
    assert '缺失值 1' in distribution['caption'] and '不适用该属性的主体 2' in distribution['caption']
    quantiles = next(row for row in figures if row['kind']=='speed_quantiles')
    assert quantiles['evidence']['field']=='walkers.speed' and quantiles['evidence']['unit']=='m/s'
    assert quantiles['evidence']['quantiles']==[[t,1.5,2.,2.5] for t in range(3)]
    assert all(row['path'].is_file() for row in figures)


def test_report_categorical_counts_and_corrupt_speed_are_not_relabelled_as_numeric_or_missing():
    import matplotlib.pyplot as plt
    from dayan.report_spatial_charts import _distribution, _speed_series
    from dayan.view_analysis import analyze_view
    population = populations()
    frame = {'sim_t':0.,'population':population,'entities':sample_entities(population,2)}
    record = {'run_id':'fixture','model_id':'GROUP_PROTOCOL_FIXTURE','kind':'run','state_frames':[frame],
              'observations':[{'sim_t':0.,'test_value':1.}],'manifest':{}}
    view = analyze_view([record],'fixture')
    captions=[]
    def save(fig,title,kind,section,caption,**evidence):
        plt.close(fig)
        captions.append(caption)
    _distribution(frame,view,record,save)
    assert '逐类别统计' in captions[0] and '累计概率' not in captions[0]
    group=population['groups'][0]
    group['columns']['speed']={'kind':'numeric','data':{'bad':'corrupted encoded column'}}
    group['units']['speed']='m/s'
    with pytest.raises((TypeError,ValueError)):
        _speed_series([frame],record,save,'workers.speed','工作人员','m/s')
