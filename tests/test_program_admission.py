"""Planning admission by actual ports, without claiming these topics were simulated."""
import pytest

from dayan.agent import model_tools
from dayan.engine_capabilities import program_blockers
from dayan.research.requirements import extract_request


@pytest.mark.parametrize('topic', [
    '三维碰撞与跨楼层疏散', '踩踏中的局部接触、失稳倒地与伤害机制',
    '相关随机微分方程SDE', '不规则网格上的元胞自动机CA与连续状态耦合',
    '自行实现Saltelli采样与全局敏感性计算',
])
def test_program_topics_reach_constructive_planning_without_bypassing_implementation(monkeypatch,tmp_path,topic):
    import dayan.engine_capabilities as capabilities
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    # Explicit environment/admission fixture. Actual numerical execution is
    # separately covered by the real program runtime and CA container tests.
    monkeypatch.setattr(capabilities,'program_status',lambda:{'available':True,'fixture':'admission protocol only'})
    seen=[]
    class ReachedPlanning(Exception):pass
    def reached(source,parsed,execution,contract,*args,**kwargs):
        seen.append((source,execution,contract))
        raise ReachedPlanning('controlled constructive-planning boundary')
    monkeypatch.setattr(model_tools,'create_design',reached)
    question='自建模型：'+topic+'。运行4步，步长0.2，种子7。无需外部数据或文献。'
    assert not program_blockers(extract_request(question))
    result=model_tools.call_native_model('design_model',{},question,'constructive-admission-owner')
    assert not result['ok'] and 'ReachedPlanning' in result['error'],result
    assert len(seen)==1 and seen[0][0]==question
    assert seen[0][1]['dt']==.2 and '受管程序' in seen[0][2]
    assert not list(tmp_path.glob('research_runs/R*'))


def test_missing_external_llm_port_is_still_a_real_program_gap():
    request=extract_request('每个主体实际调用外部LLM进行语言推理，不用规则脚本代替。')
    assert request['requires_llm_agents']
    assert any('LLM主体调用端口' in reason for reason in program_blockers(request))
    assert not extract_request('不用真实LLM主体，使用概率规则更新。')['requires_llm_agents']


def test_guide_routes_complex_research_to_the_actual_design_and_compile_interfaces(monkeypatch,tmp_path):
    import dayan.engine_capabilities as capabilities
    from dayan.agent.scenario_tools import modeling_guide
    from dayan.agent.tools import TOOL_IMPL
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    monkeypatch.setattr(capabilities,'program_status',lambda:{'available':True,'fixture':'guide routing only'})
    question='自建三维踩踏接触与跨楼层疏散模型，用实测数据校准参数并以独立数据验证。'
    guide=modeling_guide(question)['payload']
    assert guide['program_engine']['eligible_with_research_intent']
    assert guide['next_tools']['research_model']=='research_model_prepare'
    contracts={entry['name']:entry['parameters'] for entry in guide['tool_contracts']}
    assert {'design_model','build_model','validate_model'}<=contracts.keys()
    workflow=guide['authoring_workflow']
    assert workflow['design']['tool'] in TOOL_IMPL
    assert workflow['construct']['tool'] in TOOL_IMPL
    assert 'design_id' in contracts['build_model']['properties']
    assert 'revise_proposal' in contracts['design_model']['properties']
    assert 'definition_path' not in contracts['build_model']['properties']  # Host file bridge, not an invented backend input.
    assert not list(tmp_path.glob('research_runs/R*'))
