"""Execute the registered model for research, with exact observed-time scoring.

No fitting lambda, interpolated prediction, or archived result is substituted for
a fresh run. These internal trials are stored under their study, not the user's
main simulation history. Public approval and study-stage orchestration are the
caller's responsibility; an evaluator alone does not certify a research study.
"""
from copy import deepcopy
import math
from pathlib import Path

from ..collection.storage import atomic_json
from ..solvers.codec import digest
from ..structured_inputs import _finite, _object, _text, prepare_bindings
from .model_observations import ROLES, prepare_targets, audit_input_usage


def model_identity(model_id):
    from ..custom_models import factory
    cls = factory(model_id)
    definition = cls.definition
    if definition['kind']=='program':
        observables=deepcopy(definition['observables'])
    else:
        units=definition.get('observable_units',{})
        if set(units)!=set(definition['observables']):
            raise ValueError('校准须声明全部observable_units，不能把旧DSL未声明的单位猜成无量纲')
        observables={name:{'unit':units[name],'equation':expr} for name,expr in definition['observables'].items()}
    return {'model_id': model_id, 'definition_sha256': digest(definition),
            'definition': deepcopy(definition), 'time_unit': definition['time_unit'],
            'observables': observables,
            'scenario_review_sha256': digest(cls.scenario_review),
            'approval_scope': 'existing_review_preserved_not_certified_by_evaluator'}


def parameter_specs(definition):
    """Share numeric type checks without changing historical DSL model identity."""
    if definition['kind']=='program':
        return definition['parameters']
    return {name:{'type':'float','minimum':-1e12,'maximum':1e12,**spec}
            for name,spec in definition.get('parameters',{}).items()}


def _sealed(value, label):
    if not isinstance(value, dict) or value.get('sha256') != digest({k: v for k, v in value.items() if k != 'sha256'}):
        raise ValueError(label + '哈希不一致')


def objective_contract(spec, targets):
    outputs = {row['observable'] for row in targets['roles']['training']}
    if not isinstance(spec, dict) or set(spec) != outputs:
        raise ValueError('objective必须逐项覆盖全部实际目标observable')
    result = {}
    for output, item in spec.items():
        _object(item, ('weight', 'scale'), ('weight', 'scale'), '目标损失')
        weight = _finite(item['weight'], '目标权重')
        if weight <= 0:
            raise ValueError('目标权重须为正值，不能用零权重省去原目标')
        scale = item['scale']
        _object(scale, ('kind', 'value', 'unit', 'basis'), ('kind',), '误差标准化尺度')
        training = [row for row in targets['roles']['training'] if row['observable'] == output]
        unit = training[0]['unit']
        if scale['kind'] == 'external':
            if set(scale) != {'kind', 'value', 'unit', 'basis'} or scale['unit'] != unit:
                raise ValueError('外部尺度须事前声明值、同一单位及依据')
            resolved = _finite(scale['value'], '事前尺度')
            _text(scale['basis'], '尺度事前依据')
        elif scale['kind'] == 'training_std':
            if set(scale) != {'kind'} or len(training) < 2:
                raise ValueError('training_std只能使用至少两个训练观测，不接收外部值')
            values = [row['value'] for row in training]
            mean = math.fsum(values) / len(values)
            resolved = math.sqrt(math.fsum((v-mean)**2 for v in values) / len(values))
        else:
            raise ValueError('标准化尺度仅支持external或training_std')
        if not math.isfinite(resolved) or resolved <= 0:
            raise ValueError('标准化尺度须有限且大于零；常量训练列须给事前外部尺度')
        result[output] = {'weight': weight, 'scale': resolved, 'unit': unit, 'declaration': deepcopy(scale)}
    if not math.isfinite(math.fsum(item['weight'] for item in result.values())):
        raise ValueError('目标权重总和溢出')
    return result


def prepare_evaluation(model_id, *, target_bindings, time_origin, split, execution, objectives,
                       availability, information_mode):
    from ..runtime import assert_loaded_source, validate_run_arguments
    identity = model_identity(model_id)
    _object(execution, ('parameters', 'ticks', 'dt', 'data_bindings', 'experiment', 'time_atol'),
            ('parameters', 'ticks', 'dt', 'data_bindings', 'experiment', 'time_atol'), '研究执行合同')
    validate_run_arguments(execution['ticks'], execution['dt'], 0)
    _text(execution['experiment'], '共同随机流实验标识')
    atol = _finite(execution['time_atol'], '时间匹配容差')
    if not 0 <= atol < execution['dt'] / 4:
        raise ValueError('时间匹配容差须非负且小于dt/4；不能把不同时点混合')
    targets = prepare_targets(target_bindings, observables=identity['observables'],
                              time_unit=identity['time_unit'], time_origin=time_origin, split=split)
    for group in targets['roles'].values():
        for row in group:
            step = round(row['time'] / execution['dt'])
            if abs(step * execution['dt'] - row['time']) > atol or step > execution['ticks']:
                raise ValueError('观测时刻不对应实际模型步或超出终点；须调整dt/范围，不自动插值')
    bound, inputs, evidence = prepare_bindings(execution['data_bindings'], model_id,
                                              identity['definition'].get('input_ports', {}))
    from ..program_models import effective_parameters
    parameters = deepcopy(execution['parameters'])
    if not isinstance(parameters, dict):
        raise ValueError('研究parameters须为对象')
    for key, value in bound.items():
        if key in parameters and parameters[key] != value:
            raise ValueError('研究基准参数与实际数据绑定冲突')
        parameters[key] = value
    effective_parameters({**identity['definition'],'parameters':parameter_specs(identity['definition'])}, parameters)
    leakage = audit_input_usage(targets, execution['data_bindings'], availability=availability,
                                information_mode=information_mode, forecast_origin=split['training_end'])
    result = {'protocol': 'dayan-model-evaluation-v1', 'model': identity, 'targets': targets,
              'source_fingerprint': assert_loaded_source(), 'execution': deepcopy(execution),
              'bound_parameters': bound, 'input_sha256': digest(inputs), 'input_evidence': evidence,
              'input_audit': leakage, 'objectives': objective_contract(objectives, targets),
              'loss': 'weighted_mean_of_per_observable_mean_squared_scaled_residuals',
              'replicate_rule': 'mean_of_individual_run_losses_not_loss_of_ensemble_mean',
              'limits': ['数值评估不替代已审查的机制、现实适用性或参数可识别性',
                         '共同seed不保证分支算法/不同步长下的共同随机样本路径']}
    result['sha256'] = digest(result)
    return result


def score_observations(observations, target_rows, objectives, *, time_atol):
    """Exact one-to-one model timestamps; no zip truncation or nearest resampling."""
    from bisect import bisect_left, bisect_right
    times = [_finite(row.get('sim_t'), '实际观测sim_t') for row in observations]
    if not times or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError('实际观测时钟须非空、唯一且严格递增')
    scored = []
    for row in target_rows:
        lo, hi = bisect_left(times, row['time']-time_atol), bisect_right(times, row['time']+time_atol)
        if hi - lo != 1:
            raise ValueError('每个真实观测须恰好匹配一个实际模型时点，不能遗漏或插值')
        predicted = _finite(observations[lo].get(row['observable']), '实际模型目标观测')
        residual = predicted - row['value']
        squared = (residual / objectives[row['observable']]['scale'])**2
        if not math.isfinite(squared):
            raise ValueError('实际误差溢出，不能忽略失败观测')
        scored.append({**deepcopy(row), 'predicted': predicted, 'actual_model_time': times[lo],
                       'residual_predicted_minus_observed': residual, 'scaled_squared_error': squared})
    summaries = {}
    for name, objective in objectives.items():
        rows = [row for row in scored if row['observable'] == name]
        if not rows:
            raise ValueError('本分区缺少目标：' + name)
        errors = [row['residual_predicted_minus_observed'] for row in rows]
        summaries[name] = {'n': len(rows), 'unit': objective['unit'],
                           'rmse': math.sqrt(math.fsum(e*e for e in errors)/len(rows)),
                           'mae': math.fsum(abs(e) for e in errors)/len(rows),
                           'bias_predicted_minus_observed': math.fsum(errors)/len(rows),
                           'scaled_mse': math.fsum(row['scaled_squared_error'] for row in rows)/len(rows)}
    total = math.fsum(item['weight'] for item in objectives.values())
    loss = math.fsum(objectives[name]['weight']/total*item['scaled_mse'] for name,item in summaries.items())
    if not math.isfinite(loss):
        raise ValueError('整体损失非有限')
    return {'loss': loss, 'observables': summaries, 'points': scored}


def evaluate_role(contract, *, parameters, seed, role, directory):
    """Publish a complete success/failure receipt for one actual model trial."""
    if role not in ROLES:
        raise ValueError('评估角色不合法')
    return _execute_trial(contract,parameters=parameters,seed=seed,role=role,directory=directory)


def evaluate_diagnostic(contract, *, parameters, seed, directory):
    """Run the full horizon without using held-out values in scoring or selection."""
    return _execute_trial(contract,parameters=parameters,seed=seed,role='diagnostic',directory=directory)


def _execute_trial(contract, *, parameters, seed, role, directory):
    from ..runtime import run_model_full, assert_loaded_source, validate_run_arguments
    _sealed(contract, '研究执行合同')
    _sealed(contract['targets'], '观测合同')
    execution = contract['execution']
    diagnostic=role=='diagnostic'
    target_rows=[] if diagnostic else contract['targets']['roles'][role]
    ticks=execution['ticks'] if diagnostic else round(max(row['time'] for row in target_rows)/execution['dt'])
    validate_run_arguments(ticks, execution['dt'], seed)
    if not isinstance(parameters, dict):
        raise ValueError('候选参数须为对象')
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=False)
    request = {'contract_sha256': contract['sha256'], 'model_id': contract['model']['model_id'],
               'parameters': deepcopy(parameters), 'seed': seed, 'role': role, 'ticks': ticks}
    atomic_json(path/'request.json', request)
    receipt = {**request, 'status': 'failed', 'loss': None}
    stage = 'preflight'
    try:
        if assert_loaded_source() != contract['source_fingerprint']:
            raise ValueError('研究执行源码已变化，不能混合不同实现的候选结果')
        identity = model_identity(contract['model']['model_id'])
        if identity != contract['model']:
            raise ValueError('研究模型或审查版本已变化')
        refreshed = prepare_targets(contract['targets']['bindings'], observables=identity['observables'],
            time_unit=identity['time_unit'], time_origin=contract['targets']['time_origin'], split=contract['targets']['split'])
        if refreshed['sha256'] != contract['targets']['sha256']:
            raise ValueError('实际目标数据与固定研究合同不一致')
        bound, inputs, evidence = prepare_bindings(execution['data_bindings'], identity['model_id'],
                                                  identity['definition'].get('input_ports', {}))
        if digest(inputs) != contract['input_sha256'] or bound != contract['bound_parameters'] or evidence != contract['input_evidence']:
            raise ValueError('实际模型输入与研究版本不一致')
        if set(parameters) & set(bound):
            raise ValueError('待估参数与真实数据绑定参数冲突，不能静默覆盖数据')
        stage = 'model_execution'
        rr = run_model_full(identity['model_id'], parameters={**execution['parameters'], **parameters},
            ticks=ticks, dt=execution['dt'], seed=seed, experiment=execution['experiment'],
            strict=True, with_time=True, data_bindings=execution['data_bindings'], capture_state=False)
        atomic_json(path/'manifest.json', rr.manifest)
        atomic_json(path/'observations.json', rr.observations)
        if rr.manifest['source_fingerprint'] != contract['source_fingerprint']:
            raise ValueError('实际执行版本与事前版本不一致')
        stage = 'scoring'
        fit = ({'loss':None,'status':'not_scored','scope':'完整模型数值诊断；目标数据仅作版本核对，不用于诊断评分或选型'} if diagnostic else
               score_observations(rr.observations, target_rows, contract['objectives'], time_atol=execution['time_atol']))
        atomic_json(path/'fit.json', fit)
        receipt.update(status='executed' if diagnostic else 'evaluated', loss=fit['loss'], run_id=rr.manifest['run_id'],
                       actual=rr.manifest['actual'], observations_sha256=digest(rr.observations),
                       manifest_sha256=digest(rr.manifest), fit_sha256=digest(fit))
    except Exception as exc:
        receipt['error'] = {'type': type(exc).__name__, 'message': str(exc)}
        receipt['failure_stage'] = stage
    receipt['sha256'] = digest(receipt)
    atomic_json(path/'result.json', receipt)
    return receipt
