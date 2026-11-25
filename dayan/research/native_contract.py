"""Protect explicit constraints from the native user's durable message before tool dispatch."""
import json
import math
import re
from .request_contract import parse_data_request


def _session_has_run(session_id, run_id):
    from .integration_events import events
    from ..run_store import get_store

    for receipt in reversed(events(session_id)):
        if not receipt.get("ok"):
            continue
        if receipt.get("run_id") == run_id or run_id in receipt.get("run_ids", []):
            return True
        # Earlier receipts point to the batch without recording its members.
        batch_id = receipt.get("analysis_id") or receipt.get("experiment_id")
        if not batch_id or "run_ids" in receipt:
            continue
        try:
            batch = get_store().load(batch_id)
        except (KeyError, OSError, ValueError):
            continue
        if any(row.get("run_id") == run_id for row in batch.get("runs", [])):
            return True
    return False


def protect(tool, arguments, original_text, session_id=""):
    args = dict(arguments)
    if tool=='memory_feedback':
        if not original_text:raise ValueError('纠正记忆缺少真实用户消息')
        args['correction']=original_text
        return args
    if tool=='explain' and 'request' not in args:
        if not original_text:raise ValueError('原生解释缺少用户原文或明确request，不能猜测问题')
        args['request']=original_text
    if tool in ('global_sensitivity','plan_capacity'):
        from ..collection.storage import read_json
        from ..run_store import get_store
        baseline=args.get('baseline_run_id')
        continuation=args.get('analysis_id') if tool=='global_sensitivity' else args.get('capacity_id')
        if continuation:
            if tool=='global_sensitivity':
                from .global_sensitivity import folder
                directory=folder(continuation)
            else:
                from ..access import data_root
                if not re.fullmatch(r'CP-[a-f0-9]{32}',continuation):raise ValueError('容量编号无效')
                directory=data_root()/'capacity_plans'/continuation
            protocol=read_json(directory/'protocol.json')
            baseline=protocol['baseline_run_id']
            if protocol['query']!=original_text and continuation not in original_text:
                raise ValueError('诊断续接须属于本次原文或明确指定编号')
        meta,_=get_store().load_manifest(baseline)
        if not original_text or (baseline not in original_text and session_id and not _session_has_run(session_id,baseline)):
            raise ValueError('诊断基线须属于本次原生会话或由用户明确指定')
        if baseline not in original_text and meta.get('request_text')!=original_text:
            raise ValueError('敏感性不能替换本次需求为无关基线')
        if not continuation:args['query']=original_text
        return args
    if not original_text:
        if tool in ('research_model_prepare','research_model_context','research_model_create','research_create','research_calibrate','research_finalize','research_report') or tool=='experiment' and args.get('baseline_run_id'):
            raise ValueError('原生研究工具缺少用户原文，不能确认本次研究归属')
        return args
    if tool=='research_model_prepare':
        args['question']=original_text
        return args
    if tool=='research_model_create':
        from ..run_store import get_store
        baseline=args.get('baseline_run_id')
        meta,_=get_store().load_manifest(baseline)
        if baseline not in original_text and meta.get('request_text')!=original_text:
            raise ValueError('本次原文须明确指定基线run_id或与该基线原始建模需求相同；不能拿无关模型代替研究')
        if baseline not in original_text and session_id and not _session_has_run(session_id,baseline):
            raise ValueError('研究基线不属于本次原生会话，也未经用户明确指定')
        args['question']=original_text
        return args
    if tool=='experiment' and args.get('baseline_run_id'):
        from ..run_store import get_store
        from .requirements import extract_request
        baseline=args['baseline_run_id'];meta,manifest=get_store().load_manifest(baseline)
        explicit=baseline in original_text
        if not explicit and session_id and not _session_has_run(session_id,baseline):
            raise ValueError('对照基线不属于本次原生会话，也未经用户明确指定')
        if not explicit and meta.get('request_text')!=original_text and not extract_request(original_text).get('reuse'):
            raise ValueError('不能把无关模型当作本轮新需求的对照基线')
        if (manifest.get('scenario_review') or {}).get('research_intent'):
            raise ValueError('冻结MI研究须沿原校准/诊断/留出流程，不能另建对照改写科研协议')
        args['query']=original_text
        return args  # The tool still verifies the actual reviewed baseline, source and inputs.
    if tool in ('run', 'experiment', 'sweep', 'ensemble', 'compose', 'compare'):
        from ..agent.scenario_tools import needs_incident_model, requests_scripted_exercise
        from .requirements import extract_request
        parsed = extract_request(original_text)
        if needs_incident_model(parsed) or requests_scripted_exercise(parsed):
            raise ValueError('事故情景须先通过 modeling_guide 核对实有机制，用 reviewed_run 留存方案审查和执行证据')
        if parsed["kind"] == "build_model":
            raise ValueError('新建模型须先用 modeling_guide，再用 build_model 形成方案、实际方程和运行检验')
        if tool == 'run' and not parsed["model_ids"] and re.search(r"场景|情景|假设|设计|建模|仿真|模拟", original_text):
            raise ValueError('自然语言仿真须经 modeling_guide 和 reviewed_run 或 build_model 审查，以原文和真实运行检验为准')
    if tool == 'report_run' and session_id:
        run = args.get('run_id')
        if isinstance(run, str) and run not in original_text and not _session_has_run(session_id, run):
            raise ValueError('报告须使用本次原生会话实际返回的运行编号，或来自用户明确指定的归档')
        from ..run_store import get_store
        _,manifest=get_store().load_manifest(run)
        if (manifest.get('scenario_review') or {}).get('research_intent'):
            raise ValueError('该运行是完整研究的模型基线；须按同研究next_action完成research_calibrate并用research_report，不能用基线Word代替科研报告')
    if tool in ("research_calibrate", 'research_finalize', "research_report"):
        if str(args['study_id']).startswith('MS-'):
            from .model_studies import load_study
            study=load_study(args['study_id'])['protocol']
        else:
            from .studies import load
            study = load(args["study_id"])
        if study["question"] != original_text and args["study_id"] not in original_text:
            # A short follow-up may refer to this native session's most recent actual study.
            latest = None
            if session_id:
                from .integration_events import events
                latest = next((e for e in reversed(events(session_id)) if e.get("ok") and e.get("study_id")), None)
            scope = parse_data_request(original_text)
            referential = (not any(scope.get(k) for k in ("country", "indicator", "date"))
                and bool(re.fullmatch(r'(?:请|帮我)?\s*(?:继续|接着|续算|生成|导出|查看)\s*(?:生成|导出|查看|校准)?\s*(?:这个|该|上一个|刚才的)?\s*(?:研究|校准|研究报告|报告|结果)?\s*[。！!？?]*',original_text.strip())))
            if not (referential and latest and latest["study_id"] == args["study_id"]):
                raise ValueError("研究不属于本次原始需求；不能拿旧结果代替本次任务。明确study_id或引用本会话当前研究才可复用")
    if tool not in ("research_create", "run_preset", "collect_source"):
        return args
    contract = parse_data_request(original_text)
    if (tool == "run_preset" and args.get("preset_id") == "pop_employment_wb") or (tool == "collect_source" and args.get("connector") == "worldbank"):
        if tool == "run_preset":
            from ..collection.presets import get_preset, resolve_params
            params = resolve_params(get_preset(args["preset_id"]), args.get("values", {}))
        else:
            params = args.get("params", {})
        for field in ("country", "indicator", "date"):
            if contract.get(field) and params.get(field) != contract[field]:
                raise ValueError(f"DSH工具参数{field}与原始用户需求冲突；不执行替换后的采集")
    if tool == "research_create":
        if contract["errors"]:
            raise ValueError("原始DSH需求尚有缺口："+"；".join(contract["errors"]))
        args["question"] = original_text
        split = re.search(r"末尾\s*(\d+)\s*年.*?留出", original_text)
        if split and int(split[1]) != args.get("holdout_years", 1):
            raise ValueError("DSH留出划分与原始要求冲突")
        tolerance = re.search(r"阈值\s*(?:均为|均|为|是)?\s*([\d.]+)", original_text)
        if tolerance and not math.isclose(float(tolerance[1]), float(args["tolerance"]), abs_tol=1e-12):
            raise ValueError("DSH误差阈值与原始事前要求冲突，不能事后放宽")
        for key, values in args.get("param_grid", {}).items():
            match = re.search(r"(?<![A-Za-z0-9_])"+re.escape(key)+r"\s*=\s*(\[[^\]]+\])", original_text)
            if match and json.loads(match[1]) != values:
                raise ValueError(f"DSH参数{key}网格与原始用户要求冲突")
        budget = re.search(r"预算\s*(?:最多|不超过|为|是)?\s*(\d+)", original_text)
        if budget:
            args["budget"] = min(int(args.get("budget", budget[1])), int(budget[1]))
    return args
