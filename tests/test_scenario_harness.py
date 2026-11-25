"""The native modeling tool contract keeps execution apart from coverage."""

from dayan.agent.tools import call_tool
from dayan.research.native_contract import protect
import pytest


REQUEST = '给我设计一个旅游景区踩踏事件的仿真情景，用公开实测数据做模型输入，运行后给我报告。'
EXERCISE = '请模拟虚拟景区步道疏散演练，预先指定一次倒地。用公开实测数据做模型输入，运行后给我报告。'


def test_capabilities_without_model_id_returns_global_contract_without_selecting_a_model():
    global_contract = call_tool('get_capabilities')
    assert global_contract['ok'] and 'technical_methods' in global_contract['payload']
    assert 'model_id' not in global_contract['payload']
    scoped = call_tool('get_capabilities', model_id='NET052')
    assert scoped['ok'] and scoped['payload']['model_id'] == 'NET052'
    missing = call_tool('get_capabilities', model_id='DOES_NOT_EXIST')
    assert not missing['ok'] and 'DOES_NOT_EXIST' in missing['error']


def test_dataset_name_reaches_the_tool():
    result = call_tool('collect_data', name='原生数据名称')
    assert not result['ok'] and '只指定url' in result['error']


def test_guide_exposes_actual_data_and_model_gaps(monkeypatch):
    import dayan.engine_capabilities as capabilities
    # The fallback catalogue remains truthful when the program engine is absent.
    # Available-engine constructive routing has its own program-admission test.
    monkeypatch.setattr(capabilities,'program_status',lambda:{'available':False,'fixture':'unavailable-engine fallback'})
    guide = call_tool('modeling_guide', request=REQUEST)['payload']
    assert guide['real_inputs_required'] and guide['incident_requires_more_than_dsl']
    assert not guide['eligible_models'] and guide['next_tools']['existing_model'] is None
    assert guide['next_tools']['custom_model'] is None
    alternative = next(model for model in guide['models'] if model['model_id'] == 'NET121')
    assert alternative['scope']['status'] == 'partial'
    assert any('事故发生机制' in gap for gap in alternative['scope']['gaps'])

    guide = call_tool('modeling_guide', request=EXERCISE)['payload']
    model = guide['models'][0]
    assert model['model_id'] == 'NET121' and model['scope']['status'] == 'exercise'
    assert model['scope']['incident_physics']['人体伤害与真实事故'] == '未求解'
    assert guide['eligible_models'] == ['NET121']
    ordinary = next(model for model in guide['models'] if model['model_id'] == 'NET114')
    assert ordinary['scope']['status']=='partial' and any('倒地' in issue for issue in ordinary['scope']['gaps'])
    assert 'min_separation' in model['observables'] and model['input_ports']['v_des']['unit']=='m/s'
    assert guide['data_presets'][0]['evidence']['field'] == 'avg_speed_mps'
    contract = next(t['parameters'] for t in guide['tool_contracts'] if t['name']=='reviewed_run')
    assert contract['required'] == ['model_id'] and '_session' not in contract['properties']
    assert contract['properties']['allow_partial']['type'] == 'boolean'
    variants=contract['properties']['data_bindings']['items']['oneOf']
    assert {frozenset(item['required']) for item in variants} == {
        frozenset({'dataset_id','field','parameter'}),frozenset({'dataset_id','port','contract','columns'})}


def test_reference_only_input_does_not_turn_a_new_model_into_a_resume():
    from dayan.research.requirements import extract_request

    request = EXERCISE + "只把日常游客的平均步速当作参考输入。"
    assert not extract_request(request)["reuse"]
    assert extract_request("只把车速上限改为2，其余保持原有设置。")["reuse"]


def test_unreviewed_incident_cannot_be_run_as_complete():
    with pytest.raises(ValueError, match='reviewed_run'):
        protect('run', {'model_id':'NET114'}, REQUEST, 'native-regression')
    result = call_tool('reviewed_run', request=REQUEST, model_id='NET114')
    assert not result['ok'] and '倒地' in result['error'] and not result['llm_calls']
    result = call_tool('reviewed_run', request=REQUEST, model_id='NET114', allow_partial=True)
    assert not result['ok'] and '场景完整性审查未通过' in result['error']
    result = call_tool('reviewed_run', request=REQUEST+' 我接受部分覆盖。', model_id='NET114', allow_partial=True)
    assert not result['ok'] and '入模数据' in result['error'] and not result['llm_calls']


def test_unsupported_incident_is_not_a_complete_exercise():
    guide = call_tool('modeling_guide',request=REQUEST+' 必须计算真实伤害与连锁倒地。')['payload']
    assert not guide['eligible_models'] and guide['next_tools']['existing_model'] is None
    guide = call_tool('modeling_guide',request=EXERCISE + ' 基于实测校准模型并用独立数据验证。')['payload']
    assert not guide['eligible_models'] and not guide['next_tools']['custom_model']


def test_exercise_state_frames_and_events_close_the_loop():
    from dayan.runtime import run_model_full
    result = run_model_full('NET121',parameters={'n':16},ticks=350,dt=.05,seed=17,capture_state=True,strict=True)
    assert all(row['alive']+row['evacuated']==16 and
               row['moving']+row['waiting']+row['fallen']+row['assisted']==row['alive']
               for row in result.observations)
    by_time = {row['sim_t']:row for row in result.observations}
    assert [event['etype'] for event in result.events] == ['drill_fall','aid_started','aid_completed']
    for event, field in zip(result.events,['fallen','assisted','aid_completed']):
        assert by_time[event['sim_t']][field] == 1
    assert {'fallen','seated'} <= {e['state'] for frame in result.state_frames for e in frame['entities']}
    assert result.manifest['model_method']['source']=='verified_implementation'


def test_report_does_not_accept_an_unrelated_native_run(tmp_path, monkeypatch):
    monkeypatch.setenv('DAYAN_DATA_DIR', str(tmp_path))
    with pytest.raises(ValueError, match='本次原生会话'):
        protect('report_run', {'run_id':'R20261119-old-other'}, REQUEST, 'native-regression')


def test_terminal_sum_and_conservation_use_different_windows():
    from dayan.agent.verification import criteria_for_plan, evaluate_criteria

    base = [
        {"id": "V1", "check": "start", "fields": ["received"], "target": 1, "reason": "初态"},
        {"id": "V2", "check": "start", "fields": ["ready"], "target": 1, "reason": "初态"},
    ]
    total = {"id": "V3", "check": "balance", "fields": ["received", "ready"], "target": 26, "reason": "末态"}
    with pytest.raises(ValueError, match="V3.*V1、V2.*2"):
        criteria_for_plan([*base, total], ["received", "ready"])
    conditions = criteria_for_plan([*base, {**total, "check": "end"}], ["received", "ready"])
    observed = [{"received": 1, "ready": 1}, {"received": 5, "ready": 1}, {"received": 13, "ready": 13}]
    verdicts = evaluate_criteria(conditions, observed)
    assert all(row["passed"] for row in verdicts)
    assert verdicts[-1]["measured"]["required_rows"] == 1


def test_native_report_accepts_members_of_its_actual_batch(tmp_path, monkeypatch):
    from dayan.research.integration_events import append_event
    from dayan.research.model_study_runs import for_model_run

    monkeypatch.setenv("DAYAN_DATA_DIR", str(tmp_path))
    result = call_tool("ensemble", model_id="NET052", ticks=3, seeds=[3, 5])
    assert result["ok"], result
    payload = result["payload"]
    run_ids = [row["run_id"] for row in payload["runs"]]
    event = append_event("native-current", "ensemble", result)
    assert event["run_ids"] == run_ids
    append_event("native-legacy", "ensemble", {"ok": True, "payload": {"analysis_id": payload["analysis_id"]}})
    append_event("native-failed", "ensemble", {**result, "ok": False})
    for run_id in run_ids:
        assert for_model_run(run_id) is None
        args = {"run_id": run_id}
        for session in ("native-legacy", "native-current"):
            assert protect("report_run", args, "导出本对话刚跑过的报告", session) == args
        for session in ("native-other", "native-failed"):
            with pytest.raises(ValueError, match="本次原生会话"):
                protect("report_run", args, "导出本对话刚跑过的报告", session)


def test_incident_requires_an_engine_that_supports_its_mechanisms(monkeypatch):
    import dayan.engine_capabilities as capabilities
    monkeypatch.setattr(capabilities,'program_status',lambda:{'available':False,'fixture':'unsupported-engine fallback'})
    result = call_tool('design_model',request=REQUEST)
    assert not result['ok'] and '局部人体接触' in result['error'] and not result['llm_calls']


def test_plan_evidence_resolves_ids_to_exact_user_text():
    from dayan.agent.model_design import _evidence

    request = '原文要求保留。\n运行后给我报告。'
    result = _evidence({'checks':[{'requirement_id':'U2','evidence':'报告归档号'}]},request,'checks',('evidence',))
    assert result == [{'quote':'运行后给我报告。','evidence':'报告归档号'}]
    with pytest.raises(ValueError):
        _evidence({'checks':[{'requirement_id':'U3','evidence':'报告归档号'}]},request,'checks',('evidence',))
    with pytest.raises(ValueError):
        _evidence({'checks':[{'quote':'立即输出错误报告','evidence':'报告归档号'}]},request,'checks',('evidence',))


def test_failed_preregistered_check_cannot_be_archived(tmp_path, monkeypatch):
    from dayan.agent.tools import _archive_run
    from dayan.agent.verification import criteria_for_plan
    from dayan.run_store import get_store

    monkeypatch.setenv("DAYAN_DATA_DIR", str(tmp_path))
    criteria = criteria_for_plan([
        {"id": "V1", "check": "start", "fields": ["alive"], "target": 16, "reason": "已指定初始人数"},
        {"id": "V2", "check": "end", "fields": ["evacuated"], "target": 17, "reason": "用于验证程序能拦截错误阈值"},
    ], {"alive", "evacuated"})
    acceptance = {"criteria": criteria, "observables": ["alive", "evacuated"], "events": {}, "spatial": True,
                  "execution": {"ticks": 120, "seed": 17, "dt": .05, "parameters": {"n": 16}}}
    rejected = _archive_run("NET121", {"n": 16}, 120, 17, .05, None, None, review={}, acceptance=acceptance)
    assert not rejected["ok"] and "V2" in rejected["error"]
    assert [v["passed"] for v in rejected["verification"]["criteria"]] == [True, False]
    assert not any(get_store().directory.glob("R*"))


def test_fixed_step_does_not_record_a_duplicate_terminal_update():
    from dayan.core import DayanModel, simulate

    class Counter(DayanModel):
        clock_type = "fixed_step"

        def initialize(self, *args):
            self.steps = 0

        def step(self, t, dt):
            self.steps += 1

        def observe(self):
            return self.steps

    result = simulate(Counter(), horizon=120, dt=.05)
    assert result["times"][-1] == 120
    assert len(result["times"]) == 2401
    assert result["observations"][-1] == 2400


def test_report_keeps_valid_spacing_and_discards_exit_sentinels():
    from dayan.report_gen import report_facts
    from dayan.view_analysis import analyze_view

    observations = [{'sim_t':0, 'evacuated':0, 'min_separation':.5},
                    {'sim_t':1, 'evacuated':2, 'min_separation':None}]
    departed = {'id':'ped_0', 'type':'pedestrian', 'state':'exited', 'x':-100, 'y':-100, 'speed':1.2}
    record = {'run_id':'R-test','model_id':'NET114','observations':observations,
              'state_frames':[{'sim_t':1, 'entities':[departed,{**departed,'id':'ped_1'}]}]}
    view = analyze_view([record],record['run_id'],'evacuated',distribution_field='speed')
    assert view['entity_count']==0 and view['departed_entities']==2 and view['distribution']=={}
    facts = report_facts('NET114',observations,{'view_analysis':view})
    assert facts['stats']['min_separation']['n_valid'] == 1
    assert facts['stats']['min_separation']['last'] == .5
