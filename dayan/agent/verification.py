"""Finite, executable acceptance conditions frozen before model execution."""
from __future__ import annotations

import re
from math import isclose

from ..view_analysis import number


class RunVerificationError(ValueError):
    def __init__(self, receipt):
        super().__init__("；".join(receipt["issues"]))
        self.receipt = receipt


def criteria_for_plan(value, observables):
    if not isinstance(value, list) or not 2 <= len(value) <= 64:
        raise ValueError("方案须约定 2 至 64 个可执行检查，按实际要求选取，不为凑数重复")
    used = set()
    signatures = set()
    criteria = []
    for row in value:
        if not isinstance(row, dict):
            raise ValueError("数值检查须为结构化对象")
        ident, kind, fields, reason = (row.get(key) for key in ("id", "check", "fields", "reason"))
        if not isinstance(ident, str) or not re.fullmatch(r"V[1-9][0-9]*", ident) or ident in used:
            raise ValueError("检查编号须为唯一的 V1、V2 等")
        if kind == 'relation_count':
            from .frame_verification import relation_spec
            spec = relation_spec(row, observables)
            signature = (kind, spec.get('relation_type'), spec.get('step'))
            if signature in signatures:
                raise ValueError(f'{ident}与已有关系检查重复；同口径target和observable合在一项')
            used.add(ident)
            signatures.add(signature)
            criteria.append(spec)
            continue
        if kind in ('event_count','event_time','event_value'):
            spec=_event_spec(row)
            signature=(kind,spec['event'],spec.get('occurrence'),spec.get('field'))
            if signature in signatures:raise ValueError(f'{ident}与已有事件检查重复')
            used.add(ident)
            signatures.add(signature)
            criteria.append(spec)
            continue
        if not isinstance(fields, list) or not fields or any(
                not isinstance(field, str) or field not in observables for field in fields):
            raise ValueError(f"{ident} 必须引用计划中真实的观测字段")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"{ident} 缺少从研究要求或方程推导的阈值依据")
        if kind not in ("range", "delta", "start", "end", "at_step", "at_time", "nondecreasing", "nonincreasing", "balance"):
            raise ValueError(f"{ident} 的检查类型不可执行")
        permitted = {"id", "check", "fields", "reason", "atol"}
        permitted.update(("min", "max") if kind in ("range", "delta") else
                         ("target",) if kind in ("start", "end", "at_step", "at_time", "balance") else ())
        if kind == "at_step":
            permitted.add("step")
            if type(row.get("step")) is not int or row["step"] < 0:
                raise ValueError(f"{ident} 的 step 须为非负整数；0为初态，1为第一次更新后")
        if kind == "at_time":
            permitted.update(("time", "time_atol"))
            if not number(row.get("time")) or not number(row.get("time_atol", 1e-9)) or row.get("time_atol", 1e-9) < 0:
                raise ValueError(f"{ident} 须给出有限 time 和非负 time_atol")
        unknown = set(row) - permitted
        if unknown:
            raise ValueError(f"{ident} 含不支持的验收字段 {sorted(unknown)}；指定步用 check=at_step、step，指定时刻用 check=at_time、time")
        if len(fields) != len(set(fields)):
            raise ValueError(f"{ident} 的观测字段须各不相同")
        if kind not in ("start", "end", "at_step", "at_time", "balance") and len(fields) != 1:
            raise ValueError(f"{ident} 的 {kind} 只使用一个实际观测字段。多个指标分别写成多条检查。")
        signature = (kind, tuple(sorted(fields)), row.get("step"), row.get("time"))
        if signature in signatures:
            raise ValueError(f"{ident} 与已有检查重复，须验证另一实际约束")
        atol = row.get("atol", 1e-9)
        if not number(atol) or atol < 0:
            raise ValueError(f"{ident} 的绝对容差须为有限非负数")
        spec = {"id": ident, "check": kind, "fields": fields, "reason": reason.strip(), "atol": atol}
        if kind == "at_step":
            spec["step"] = row["step"]
        if kind == "at_time":
            spec.update(time=row["time"], time_atol=row.get("time_atol", 1e-9))
        if kind in ("range", "delta"):
            low, high = row.get("min"), row.get("max")
            if not number(low) or not number(high) or low > high:
                raise ValueError(f"{ident} 须提供有效 min 和 max")
            spec.update(min=low, max=high)
        if kind in ("start", "end", "at_step", "at_time", "balance"):
            if not number(row.get("target")):
                raise ValueError(f"{ident} 须提供有限目标值 target")
            spec["target"] = row["target"]
        criteria.append(spec)
        used.add(ident)
        signatures.add(signature)
    if not any(row["check"] in ("delta", "end", "balance") or
               row["check"] == "at_time" and row["time"] > 0 or
               row["check"] == "at_step" and row["step"] > 0 for row in criteria):
        raise ValueError("至少检验净变化、终值或守恒，单靠数值范围和单调性不能验收")
    _check_balance_consistency(criteria)
    return criteria


def _event_spec(row):
    kind,ident=row['check'],row['id']
    allowed={'id','check','reason','event','target','atol','fields'}
    if kind!='event_count':allowed.add('occurrence')
    if kind=='event_value':allowed.add('field')
    if set(row)-allowed:raise ValueError(f'{ident}事件检查含未知字段；事件用event，数值字段检查才用fields')
    if 'fields' in row and row['fields'] != []:
        raise ValueError(f'{ident}事件检查不用观测fields；事件载荷路径使用field')
    if not isinstance(row.get('event'),str) or not row['event'] or not isinstance(row.get('reason'),str) or not row['reason'].strip():
        raise ValueError(f'{ident}须给真实事件类型event和检查依据reason')
    if not number(row.get('target')):raise ValueError(f'{ident}事件target须为有限数值')
    atol=row.get('atol',0 if kind=='event_count' else 1e-9)
    if not number(atol) or atol<0:raise ValueError(f'{ident}事件容差不合法')
    spec={**row,'fields':[],'atol':atol}
    if kind=='event_count':
        if type(row['target']) is not int or row['target']<0 or atol!=0:
            raise ValueError('事件次数须为非负整数且精确核对')
    else:
        occurrence=row.get('occurrence',1)
        if type(occurrence) is not int or occurrence<1:raise ValueError('事件occurrence从1开始，须为正整数')
        spec['occurrence']=occurrence
    if kind=='event_value' and (not isinstance(row.get('field'),str) or not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*',row['field'])):
        raise ValueError('event_value须指定真实数值载荷field路径')
    return spec


def _check_balance_consistency(criteria):
    """A constant balance must agree with every specified observation point."""
    points = {}
    for row in criteria:
        kind = row['check']
        if kind == 'start' or kind == 'at_step' and row['step'] == 0 or kind == 'at_time' and row['time'] == 0:
            point = ('start', 0)
        elif kind in ('end', 'at_step', 'at_time'):
            point = (kind, row.get('step', row.get('time')))
        else:
            continue
        points.setdefault(point, []).append(row)
    for balance in (row for row in criteria if row["check"] == "balance"):
        fields = frozenset(balance["fields"])
        for boundary, rows in points.items():
            targets = {frozenset(row['fields']): row for row in rows}
            combinations = [[row] for row in rows if frozenset(row['fields']) == fields]
            terms = [targets.get(frozenset((field,))) for field in balance['fields']]
            if all(terms):
                combinations.append(terms)
            for terms in combinations:
                total = sum(term['target'] for term in terms)
                tolerance = balance['atol'] + sum(term['atol'] for term in terms)
                if abs(total - balance['target']) > tolerance:
                    ids = '、'.join(term['id'] for term in terms)
                    raise ValueError(f"{balance['id']} 要求所有时点的字段和为 {balance['target']}，"
                                     f"与 {ids} 的 {boundary} 字段和 {total} 冲突。"
                                     '若目标是终点字段和，请使用 end 并列出相应字段。')


def evaluate_criteria(criteria, observations, events=None, frames=None):
    results = []
    event_groups = {}
    for event in events or []:
        if isinstance(event, dict):
            event_groups.setdefault(event.get('etype', event.get('type')), []).append(event)
    event_order = {}
    for spec in criteria:
        kind, fields, atol = spec["check"], spec["fields"], spec["atol"]
        if kind == 'relation_count':
            from .frame_verification import relation_count
            results.append(relation_count(spec, observations, frames))
            continue
        if kind.startswith('event_'):
            matched=event_groups.get(spec['event'], [])
            values=[event.get('sim_t',event.get('time')) for event in matched]
            valid=all(number(value) for value in values)
            # Chronological order is explicit, stable for simultaneous events.
            if spec['event'] not in event_order:
                event_order[spec['event']] = sorted(zip(values, matched), key=lambda item:item[0]) if valid else []
            ordered=event_order[spec['event']]
            measured=len(matched) if kind=='event_count' else None
            stamp=None
            if kind!='event_count' and len(ordered)>=spec['occurrence']:
                stamp,event=ordered[spec['occurrence']-1]
                measured=stamp
                if kind=='event_value':
                    measured=event
                    for key in spec['field'].split('.'):
                        measured=measured.get(key) if isinstance(measured,dict) else None
            evidence={'matched_events':len(matched),'actual':measured,
                      'actual_times':[item[0] for item in ordered[:32]],
                      'times_truncated':len(ordered)>32, 'selected_event_time':stamp,
                      'valid_event_times':valid}
            passed=valid and number(measured) and abs(measured-spec['target'])<=atol
            results.append({**spec,'passed':bool(passed),'measured':evidence})
            continue
        selection = {}
        if kind == "at_step":
            step = spec["step"]
            rows = observations[step:step+1]
            selection = {"requested_step": step, "matched_rows": len(rows)}
        elif kind == "at_time":
            rows = [row for row in observations if number(row.get("sim_t")) and
                    isclose(row["sim_t"], spec["time"], rel_tol=0, abs_tol=spec["time_atol"])]
            selection = {"requested_time": spec["time"], "matched_rows": len(rows)}
            if len(rows) != 1:
                rows = []  # Missing/ambiguous times are not silently snapped or interpolated.
        else:
            rows = observations[:1] if kind == "start" else observations[-1:] if kind == "end" else observations
        measured = []
        for row in rows:
            values = [row.get(field) for field in fields]
            if all(number(value) for value in values):
                measured.append(sum(values))
        evidence = {"required_rows": max(1, len(rows)), "valid_rows": len(measured), **selection}
        if kind in ("at_step", "at_time"):
            evidence["selected_times"] = [row.get("sim_t") for row in rows]
        passed = False
        if measured and len(rows) == len(measured):
            evidence.update(first=measured[0], last=measured[-1], minimum=min(measured), maximum=max(measured))
            if kind in ("range", "delta"):
                low, high = evidence["minimum"], evidence["maximum"]
                if kind == "delta":
                    low = high = measured[-1] - measured[0]
                    evidence["delta"] = low
                passed = spec["min"] - atol <= low <= high <= spec["max"] + atol
            elif kind in ("start", "end", "at_step", "at_time", "balance"):
                evidence["max_abs_error"] = max(abs(value - spec["target"]) for value in measured)
                passed = evidence["max_abs_error"] <= atol
            else:
                sign = 1 if kind == "nondecreasing" else -1
                evidence["violations"] = sum(sign * (b - a) < -atol for a, b in zip(measured, measured[1:]))
                passed = len(measured) > 1 and not evidence["violations"]
        results.append({**spec, "passed": bool(passed), "measured": evidence})
    return results


def _structured_execution(run, execution):
    """Verify the approved ports against both originals and actual solver inputs."""
    from ..structured_inputs import structured_audit
    expected = [item for item in execution.get('data_bindings', []) if 'port' in item]
    actual = [item for item in run.manifest.get('data_bindings', []) if 'port' in item]
    if not expected and not actual:
        return [], []
    issues = []
    planned = {item['port']:item for item in expected}
    delivered = {item['port']:item for item in actual}
    if (len(planned) != len(expected) or len(delivered) != len(actual)
            or planned.keys() != delivered.keys()):
        issues.append('实际结构数据端口与审查方案不一致（缺失、多余或重复）')
    declared = execution.get('structured_inputs', {})
    if declared.keys() != planned.keys():
        issues.append('审查方案结构输入声明与绑定端口不一致')
    ports = run.manifest.get('structured_inputs', {}).get('ports', {})
    if ports.keys() != planned.keys():
        issues.append('实际结构输入摘要端口与审查方案不一致')
    for name, item in planned.items():
        bound = delivered.get(name, {})
        # Preparation becomes delivery only after real execution. Every other
        # field (originals, conversions, original row identity, clock and units)
        # must retain the approved meaning; a matching dataset label is not enough.
        prepared = {k:v for k,v in item.items() if k != 'usage_status'}
        received = {k:v for k,v in bound.items() if k != 'usage_status'}
        if (prepared != received or not bound.get('usage_status', '').startswith('delivered_to_solver;')
                or declared.get(name) != {'contract':item['contract'], 'count':item['records_used']}
                or ports.get(name) != {'sha256':item['input_sha256'], 'records':item['records_used'],
                                       'contract':item['contract']}):
            issues.append('结构数据未按审查的原文件、转换和合同实际交付：' + name)
    audit = structured_audit(run.manifest, run.checkpoint)
    for row in audit:
        if row['status'] != 'recomputed':
            issues.append('结构数据原文件与实际求解输入快照未核对一致：' + row['port'])
    return issues, audit


def verify_execution(run, execution, criteria):
    """Check actual settings, clock and predeclared observable rules before archival."""
    manifest = run.manifest
    actual = manifest["actual"]
    requested = manifest["requested"]
    issues = []
    data = {(item["parameter"], item["dataset_id"], item["field"], item["sha256"]): item
            for item in manifest.get("data_bindings", []) if item.get("parameter") and item.get("field") and item.get("sha256")}
    for item in execution.get("data_bindings", []):
        if 'port' in item:
            continue
        parameter = item["parameter"]
        key = (parameter, item["dataset_id"], item["field"], item["sha256"])
        bound = data.get(key)
        applied = actual.get("effective_parameters", {}).get(parameter)
        if (not bound or not number(applied)
                or not isclose(applied, item["resolved_value"], rel_tol=1e-12, abs_tol=1e-12)
                or bound["resolved_value"] != item["resolved_value"]):
            issues.append(f"数据字段未按审查绑定实际生效：{parameter}")
    structural_issues, structural_audit = _structured_execution(run, execution)
    issues.extend(structural_issues)
    expected_interventions = sorted(execution.get("interventions", []), key=lambda item: float(item["at_t"]))
    applied_interventions = manifest.get("interventions", [])
    if len(expected_interventions) != len(applied_interventions):
        issues.append("实际干预次数与审查方案不一致")
    else:
        for expected, applied in zip(expected_interventions, applied_interventions):
            instant = float(expected["at_t"])
            parameters = applied.get("params", {})
            if (not applied.get("applied") or not number(applied.get("actual_t"))
                    or not isclose(applied["actual_t"], instant, rel_tol=0, abs_tol=1e-9)
                    or set(parameters) != set(expected["params"])
                    or any(number(value) and parameters[key] != value for key, value in expected["params"].items())):
                issues.append(f"审查的干预未在指定时点按原值生效：t={instant}")
    for name in ("ticks", "dt", "seed"):
        expected = execution.get(name)
        if expected is not None and requested.get(name) != expected:
            issues.append(f"实际运行未保留方案的 {name}")
    for field, expected in execution.get("initial_state_check", {}).items():
        if run.observations[0].get(field) != expected:
            issues.append("正式运行与已核验的初始化不一致：" + field)
    for key, expected in execution.get("parameters", {}).items():
        if key in ("dt", "seed"):
            continue
        effective = actual.get("effective_parameters", {}).get(key)
        if isinstance(expected, (tuple, list)) and isinstance(effective, (tuple, list)):
            effective, expected = list(effective), list(expected)
        if effective != expected:
            issues.append(f"方案参数没有按原值生效：{key}")
    times = [row.get("sim_t") for row in run.observations]
    if any(not number(t) for t in times) or any(b <= a for a, b in zip(times, times[1:])):
        issues.append("实际观测时间必须有限且严格递增")
    elif manifest.get("protocol") in ("fixed_step","managed_program"):
        horizon = requested["ticks"] * actual["dt_used"]
        if not isclose(times[-1], horizon, rel_tol=0, abs_tol=1e-9):
            issues.append("实际固定步长的记录终点偏离计划")
        if not requested.get("interventions") and actual["n_steps"] != requested["ticks"]:
            issues.append("实际固定步长的推进次数偏离计划")
    verdicts = evaluate_criteria(criteria, run.observations, run.events, run.state_frames)
    issues.extend("数值检验未通过：" + item["id"] for item in verdicts if not item["passed"])
    return {"status": "failed" if issues else "passed", "issues": issues, "criteria": verdicts,
            "clock": {"rows": len(times), "from": times[0], "to": times[-1], "protocol": manifest.get("protocol")},
            "bindings_checked": len(execution.get("data_bindings", [])),
            **({'structured_data_audit':structural_audit} if structural_audit else {})}


def _check_audit_lattice(frames, by_time, parameters, receipt):
    checked = 0
    side = parameters["grid_side"]
    count_keys = {"audit": "audited_cells", "regulator": "strict_cells", "farm": "green_cells"}
    rate_keys = {"audit": "audit_coverage", "regulator": "strict_share", "farm": "green_share"}
    for frame in frames:
        row = by_time.get(frame["sim_t"])
        lattice = frame.get("lattice") or {}
        if not row or lattice.get("width") != side or lattice.get("height") != side:
            break
        counts = {layer["id"]: layer["values"].count("1") for layer in lattice["layers"]}
        if counts.keys() != count_keys.keys() or any(counts[key] != row[count_keys[key]] or
                                                    counts[key] / side**2 != row[rate_keys[key]]
                                                    for key in counts):
            break
        checked += 1
    if not checked or checked != len(frames):
        receipt["issues"].append("实际网格帧的维度、图层或状态计数与同一时点观测不一致")
    cap = side ** 2
    if any(row["n_cells"] != cap or not 0 <= row["audited_cells"] <= cap or
           not 0 <= row["lax_fraud_detected"] <= min(row["fraud_detected"], row["lax_detected"]) or
           max(row["fraud_detected"], row["lax_detected"]) > row["audited_cells"] or
           (not row["audit_active"] and row["audited_cells"] != 0)
           for row in by_time.values()):
        receipt["issues"].append("网格规模、发现数或审计间断未满足执行合同")
    receipt["lattice"] = {"width": side, "height": side, "matched_frames": checked,
                          "layers": list(count_keys)}


def certify_run(run, review, acceptance):
    """A failed engine run or a failed test cannot become a completed archive."""
    observations = run.observations
    if not observations:
        raise RunVerificationError({"status": "failed", "issues": ["运行没有可验证的观测"]})
    receipt = verify_execution(run, acceptance["execution"], acceptance["criteria"])
    issues = receipt["issues"]
    observed = {key for row in observations for key, value in row.items() if number(value)}
    missing = set(acceptance["observables"]) - observed
    if missing:
        issues.append("运行没有生成方案要求的有效数值观测：" + "、".join(sorted(missing)))
    frames = run.state_frames
    from ..stateframe import has_spatial_state, population_size
    expected_scale = acceptance["execution"].get("verified_scale")
    if expected_scale:
        actual_scale = run.manifest.get("scale") or {}
        entities = expected_scale["entities"]
        if actual_scale.get("entities") != entities or actual_scale.get("grid") != expected_scale["grid"]:
            issues.append("实际推进的主体数或网格尺寸与批准方案不符")
        if expected_scale.get("grid_degree") and actual_scale.get("grid_degree") != expected_scale["grid_degree"]:
            issues.append("实际推进的邻域阶数与原文不符")
        from ..scaling import check_scale
        try:
            check_scale(expected_scale, {'grid':None, 'kernel':'unknown', 'entities':None, **actual_scale})
        except ValueError as exc:
            issues.append(str(exc))
        groups=actual_scale.get('populations',[])
        dynamic=(run.manifest.get('protocol')=='managed_program' and isinstance(groups,list)
                 and any(group.get('dynamic') for group in groups))
        if dynamic and frames and population_size(frames[0])!=entities:
            issues.append('动态人口初态数量与批准方案不符')
        if entities and not dynamic and any(population_size(frame) != entities for frame in frames):
            issues.append("归档状态未保存方案要求的全量主体")
        if expected_scale.get("all_frames") and [frame["sim_t"] for frame in frames] != [row["sim_t"] for row in observations]:
            issues.append("逐步状态归档未覆盖全部实际观测时点")
        receipt["execution_scale"] = {key: actual_scale.get(key)
                                      for key in ("entities", "grid", "grid_degree", "boundary", "populations", "kernel", "all_steps_archived")}
    if acceptance["spatial"] and not any(has_spatial_state(frame) for frame in frames):
        issues.append("空间需求没有生成实际主体或网格状态帧")
    matching = []
    events = acceptance["events"]
    by_time = {row["sim_t"]: row for row in observations}
    relevant = [event for event in run.events if event.get("etype") in events]
    if [item["etype"] for item in relevant] != list(events):
        issues.append("实际事件类型、次数或顺序偏离模型合同")
    else:
        for i, event in enumerate(relevant):
            kind, at = event["etype"], event["sim_t"]
            metric, state = events[kind]
            value = by_time.get(at, {}).get(metric)
            end = relevant[i+1]["sim_t"] if i+1 < len(relevant) else float("inf")
            if not number(value) or value < 1 or end <= at:
                issues.append("事件时刻与同一时点的观测不一致：" + kind)
                continue
            if state and not any(e["id"] == event["entity_id"] and e.get("state") == state
                                 for frame in frames if at <= frame["sim_t"] < end
                                 for e in frame["entities"]):
                issues.append("阶段内没有保存对应主体的实际姿态：" + kind)
                continue
            matching.append(kind)
    if run.manifest["model_id"] == "NET121":
        n = run.manifest["actual"]["effective_parameters"]["n"]
        count_fields = ("waiting", "moving", "fallen", "assisted")
        if any(row["alive"] + row["evacuated"] != n or
               sum(row[field] for field in count_fields) != row["alive"] for row in observations):
            issues.append("在场、离场及处置状态的总人数不守恒")
        if len({event["entity_id"] for event in relevant}) > 1:
            issues.append("倒地、受助和恢复主体不一致")
        if observations[0].get("local_conflicts") != 0:
            issues.append("初始时点包含不应出现的行人重叠")
    if run.manifest["model_id"] == "NET122":
        _check_audit_lattice(frames, by_time, run.manifest["actual"]["effective_parameters"], receipt)
    if issues:
        receipt["status"] = "failed"
        raise RunVerificationError(receipt)
    run.manifest["scenario_review"] = {**review, "runtime_checks": {
        "observables": acceptance["observables"], "verified_events": matching,
        "state_frames": len(frames), "observations": len(observations), "verification": receipt,
    }}
