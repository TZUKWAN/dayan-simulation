"""Regression for the actual native research parser failure, no external calls."""
from dayan.research.requirements import extract_request
from dayan.engine_capabilities import requested_methods


def test_source_url_and_diagnostic_metadata_do_not_replace_baseline_parameters():
    original=('采集 https://api.worldbank.org/v2/country/JPN/indicator/SP.POP.TOTL?date=2010:2020&format=json&per_page=1000 。'
        '新建人口模型。运行10步，dt=1年，基线参数r=-0.001，种子19。'
        '执行数值诊断：时间细化dt=[1,0.5,0.25]，max_scaled_change=0.000001；'
        '参数响应扫描r=[-0.004,-0.002,0]；参数消融令r=0。'
        '不假称全局敏感性或参数可识别。')
    parsed=extract_request(original)
    assert parsed['original_text']==original
    assert parsed['options']=={'ticks':10,'dt':1,'seed':19}
    assert parsed['parameters']=={'r':-.001}
    assert parsed['interventions']==[]
    assert 'sobol_on_model' not in requested_methods(parsed)
    mixed=extract_request('新建模型，r=0.1，dt=1，随后数值诊断时间细化dt=[1,0.5,0.25]。')
    assert mixed['parameters']=={'r':.1} and mixed['options']=={'dt':1}


def test_real_parameter_names_and_schedules_outside_research_metadata_are_preserved():
    parsed=extract_request('新建模型，date=2010，per_page=1000，weights=[1,2,3]。运行10步，dt=0.5。在t=2把rate改为0.3。')
    assert parsed['parameters']=={'date':2010,'per_page':1000,'weights':[1,2,3]}
    assert parsed['options']=={'ticks':10,'dt':.5}
    assert [(e['at_t'],e['params']) for e in parsed['interventions']]==[(2.,{'rate':.3})]


def test_explicit_methods_remain_required_after_negative_clauses_and_contrast():
    for original in ('不要省略全局敏感性。','不只做全局敏感性。','不使用SDE，但需要全局敏感性。'):
        assert 'sobol_on_model' in requested_methods(extract_request(original))
    for original in ('不假称全局敏感性。','不能冒充全局敏感性。','不代表全局敏感性。'):
        assert 'sobol_on_model' not in requested_methods(extract_request(original))
    assert requested_methods(extract_request('不使用SDE或全局敏感性。'))==[]
    assert requested_methods(extract_request('不考虑SDE，但需要全局敏感性。'))==['sobol_on_model']
    assert 'sobol_on_model' in requested_methods(extract_request('不是不使用全局敏感性。'))
