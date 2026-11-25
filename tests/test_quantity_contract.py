"""Regression cases for real request fidelity, including scoped negations."""
import pytest

from dayan.agent.scenario_tools import modeling_guide
from dayan.research.requirements import extract_request
from dayan.scaling import check_scale, scale_intent


@pytest.mark.parametrize('words,expected', [
    ('一万', 10000), ('壹万', 10000), ('十二', 12), ('两千零五', 2005),
    ('一万二千三百四十五', 12345), ('1万2千', 12000), ('1.2万', 12000),
    ('一亿两千万', 120000000), ('１，０００', 1000), ('1e4', 10000),
])
def test_numeric_spellings_preserve_exact_population_and_source(words, expected):
    source = f'请模拟{words}个主体。'
    contract = scale_intent(source)
    assert contract['entities'] == expected
    assert contract['granularity'] == 'individual'
    for item in contract['evidence']:
        assert source[item['start']:item['end']] == item['quote']
    assert extract_request(source)['parameters']['n'] == expected


def test_repeated_named_people_and_bare_human_total_are_the_same_population():
    from dayan.research.quantity_contract import quantity_contract
    contract=quantity_contract('128名行人，完整归档每步全部128名主体状态。测量正式128人目标档，固定128名行人不变。')
    assert contract['entities']==128 and contract['populations']=={'行人':128} and 'conflict' not in contract
    independent=quantity_contract('20人和30辆车辆参与仿真。')
    assert independent['entities']==50 and independent['populations']=={'人':20,'车辆':30}


def test_global_analysis_sample_size_does_not_override_model_population_parameter():
    parsed=extract_request('新建128名行人的模型，正式24步，seed=7。随后做global_sensitivity：n=8、seeds=[7,11]，不得改变正式128人。')
    assert parsed['parameters']['n']==128 and parsed['inferred_population_parameter']=='n'
    explicit=extract_request('模型n=128，正式24步。随后做Sobol敏感性分析：n=8、seeds=[7,11]。')
    assert explicit['parameters']['n']==128 and explicit['explicit_parameters']['n']==128
    phases=extract_request('128名行人，正式运行24步、seed=7。做global_sensitivity：n=8、seeds=[7,11]。另做有无疏导的同源配对对照（seeds=[7,11]）。')
    assert phases['options']=={'ticks':24,'seed':7}
    assert phases['parameters']['n']==128


def test_multiple_populations_have_separate_constraints_and_total():
    source = '构建1000家企业与一万个居民的异质主体模型。'
    contract = modeling_guide(source)['payload']['execution_scale']['request']
    assert contract['entities'] == 11000
    assert contract['populations'] == {'企业':1000, '居民':10000}
    compiled = {'kernel':'array', 'entities':11000, 'grid':None, 'populations':{'企业':500, '居民':10500}}
    with pytest.raises(ValueError, match='各类主体'):
        check_scale(contract, compiled)
    check_scale(contract, {**compiled, 'populations':{'企业':1000, '居民':10000}})


def test_unrelated_negation_does_not_remove_saved_frames_or_required_neighbors():
    source = '采用100×100四邻网格，不使用八邻域。不用视频，但是每步保存所有主体状态。'
    contract = modeling_guide(source)['payload']['execution_scale']['request']
    assert contract['grid_degree'] == 4
    assert contract['excluded_grid_degrees'] == [8]
    assert contract['all_frames']
    with pytest.raises(ValueError, match='实际定义为8邻域'):
        check_scale(contract, {'kernel':'array', 'entities':10000, 'grid':contract['grid'], 'grid_degree':8})


@pytest.mark.parametrize('source', ['不要每步保存主体状态', '每步不要保存主体状态', '不用保存每步的主体状态'])
def test_explicitly_excluded_retention_is_not_requested(source):
    contract = scale_intent(source)
    assert not contract.get('all_frames')


@pytest.mark.parametrize('source', [
    '保留初态和每一步全部92人及当前关系。',
    '每个时间步归档全部主体和关系。',
    '留存每一个时间步所有人的轨迹。',
    '不用视频，但是保留初态和每一步全部92人及当前关系。',
])
def test_complete_population_retention_reaches_runtime_contract(source):
    contract = modeling_guide(source)['payload']['execution_scale']['request']
    assert contract['all_frames'] is True
    citations = [item for item in contract['evidence'] if item['field']=='all_frames']
    assert citations and not any(item['excluded'] for item in citations)
    assert all(source[item['start']:item['end']]==item['quote'] for item in citations)


@pytest.mark.parametrize('source', [
    '不保留每一步全部92人及当前关系。', '不留存每步全部主体。', '不归档每步完整状态。',
    '每步不保留全部92人及当前关系。', '每步直播所有人的动作。',
    '每步保留所有人的平均接触秒数。', '归档每步的状态摘要。',
    '保留最终结果。每步展示完整主体。',
])
def test_retention_does_not_promote_negation_summaries_or_live_display(source):
    assert not scale_intent(source).get('all_frames')


def test_individual_population_cannot_be_substituted_by_stock():
    contract = scale_intent('模拟10000个居民，每个居民都是一个独立主体，保存每人的行动')
    with pytest.raises(ValueError, match='纯存量模型'):
        check_scale(contract, {'kernel':'stock', 'entities':0, 'grid':None})
    # Explicit population quantities can still be represented by a macro stock
    # when the user has not required individual simulation or trajectories.
    macro = scale_intent('用宏观存量模型模拟10000名居民的人口总量变化')
    check_scale(macro, {'kernel':'stock', 'entities':0, 'grid':None})


def test_count_corrections_and_nonpopulation_quantities_are_not_confused():
    contract = scale_intent('不用1000个主体，改为两千个主体')
    assert contract['entities'] == 2000 and not contract.get('conflict')
    assert 'entities' not in scale_intent('场地有五个出口')
    assert 'entities' not in scale_intent('观察第一万个主体的运动')
    assert scale_intent('总共11000个主体，1000家企业和9000个居民')['conflict']


def test_boundary_and_excluded_neighbors_are_checked_against_execution():
    contract = scale_intent('100×100网格使用反射边界，不用八邻域')
    with pytest.raises(ValueError, match='边界'):
        check_scale(contract, {'kernel':'array', 'entities':10000, 'grid':contract['grid'], 'grid_degree':4})
    with pytest.raises(ValueError, match='明确排除'):
        check_scale(contract, {'kernel':'array', 'entities':10000, 'grid':contract['grid'], 'grid_degree':8, 'boundary':'reflecting'})
