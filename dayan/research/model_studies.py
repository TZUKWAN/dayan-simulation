"""Resumable finite-grid studies over the actual registered-model evaluator.

Training makes a fixed shortlist, validation selects once, and holdout evaluates
only that selection. Prior holdout exposure is recorded across study revisions.
This is not a global optimizer or a proof of scientific identifiability.
"""
from copy import deepcopy
from datetime import datetime, timezone
import math
from pathlib import Path
import re

from ..access import data_root
from ..collection.storage import atomic_json, file_lock, read_json
from ..solvers.codec import digest
from ..structured_inputs import _finite, _text
from .model_evaluation import _sealed, evaluate_role, parameter_specs
from .model_observations import ROLES


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def base():
    return data_root() / 'model_studies'


def directory(study_id):
    if not re.fullmatch(r'MS-[a-f0-9]{24}', str(study_id)):
        raise ValueError('非法自建模型study_id')
    return base()/study_id


def _write(path, value):
    value = {k: v for k, v in value.items() if k != 'sha256'}
    value['sha256'] = digest(value)
    atomic_json(path, value)
    return value


def _read(path, label):
    value = read_json(path)
    _sealed(value, label)
    return value


def _cells(evaluation):
    return sorted({row['provenance'][key] for row in evaluation['targets']['roles']['holdout']
                   for key in ('file_cell', 'content_cell')})


def _prior_exposure(evaluation, own_id):
    cells = set(_cells(evaluation))
    previous = []
    for path in sorted((base()/'holdout_exposures').glob('MS-*.json')):
        item = _read(path, '留出使用账本')
        if item['study_id'] != own_id and cells & set(item['cells']):
            previous.append({'study_id': item['study_id'], 'first_exposed_at': item['first_exposed_at'],
                             'overlapping_cells': len(cells & set(item['cells']))})
    return previous


def _expose(study_id, evaluation):
    folder = base()/'holdout_exposures'
    with file_lock(folder/'exposure.lock', timeout=.1):
        path = folder/(study_id+'.json')
        if path.exists():
            value = _read(path, '留出使用账本')
            if value['evaluation_sha256'] != evaluation['sha256']:
                raise ValueError('同一研究留出版本不一致')
            return value
        previous = _prior_exposure(evaluation, study_id)
        return _write(path, {'study_id': study_id, 'evaluation_sha256': evaluation['sha256'],
            'cells': _cells(evaluation), 'first_exposed_at': _now(), 'previous_exposures': previous,
            'independence_status': 'previously_examined_outcomes' if previous else 'no_prior_platform_exposure_record',
            'scope': '平台账本中的已评估结果使用记录；不证明用户或Agent从未从其他渠道看过原数据'})


def create_study(question, evaluation, *, param_grid, seeds, selection_top, max_loss, parent_study_id=None,
                 diagnostics=None, baseline=None):
    """Persist an immutable protocol before making any candidate evaluation."""
    from ..program_models import parameter_value
    from ..runtime import validate_run_arguments
    _text(question, '研究原问题')
    _sealed(evaluation, '研究执行合同')
    _sealed(evaluation['targets'], '观测合同')
    declared = parameter_specs(evaluation['model']['definition'])
    if not isinstance(param_grid, dict) or not param_grid:
        raise ValueError('待估参数网格须非空')
    grids = {}
    for name in sorted(param_grid):
        values = param_grid[name]
        if name not in declared or name in evaluation['bound_parameters']:
            raise ValueError('待估参数须存在且不覆盖真实数据绑定：' + name)
        if not isinstance(values, list) or not values:
            raise ValueError('每个参数网格须为非空列表')
        values = [parameter_value(name, v, declared[name]) for v in values]
        if len({digest(v) for v in values}) != len(values):
            raise ValueError('参数候选重复，不能虚增搜索次数')
        grids[name] = values
    total = math.prod(len(values) for values in grids.values())
    if type(selection_top) is not int or not 1 <= selection_top <= total:
        raise ValueError('事前验证短名单数量须在1至网格大小之间')
    if not isinstance(seeds, list) or not seeds:
        raise ValueError('须预先声明实际随机种子列表')
    for seed in seeds:
        validate_run_arguments(0, evaluation['execution']['dt'], seed)
    if len(set(seeds)) != len(seeds):
        raise ValueError('重复seed不能作为独立重复')
    if not isinstance(max_loss, dict) or set(max_loss) != set(ROLES):
        raise ValueError('须逐分区事前声明误差阈值（null表示未设验收阈值）')
    for value in max_loss.values():
        if value is not None and _finite(value, '事前误差阈值') < 0:
            raise ValueError('误差阈值不得为负数')
    if parent_study_id is not None:
        load_study(parent_study_id)
    protocol = {'version': 'dayan-model-study-v1', 'question': question, 'evaluation': deepcopy(evaluation),
                'param_grid': grids, 'seeds': list(seeds), 'grid_size': total, 'selection_top': selection_top,
                'max_loss': deepcopy(max_loss), 'parent_study_id': parent_study_id,
                'selection_rule': 'lowest_validation_loss_among_training_shortlist; training_rank_breaks_ties',
                'failure_rule': 'any_failed_seed_invalidates_candidate_in_that_role',
                'replicate_rule': evaluation['replicate_rule']}
    if baseline is not None:
        _sealed(baseline,'已审查基线证据')
        if baseline['model_id']!=evaluation['model']['model_id'] or baseline['source_fingerprint']!=evaluation['source_fingerprint']:
            raise ValueError('研究与基线的模型或平台版本不一致')
        protocol['baseline']=deepcopy(baseline)
    if diagnostics is not None:
        from .model_diagnostics import diagnostic_contract,CURRENT_COMPARISON_RULE
        from .diagnostic_bindings import resolve_bindings,binding_evidence
        resolved,mappings=resolve_bindings(diagnostics,(baseline or {}).get('plan'),evaluation['model']['definition'])
        protocol['diagnostics']=diagnostic_contract(evaluation,resolved,seeds)
        if mappings:
            protocol['diagnostic_declarations']=deepcopy(diagnostics)
            protocol['diagnostic_implementation_binding']=binding_evidence(
                diagnostics,resolved,mappings,baseline,evaluation['model']['definition'])
        protocol['diagnostic_comparison_rule']=CURRENT_COMPARISON_RULE
        protocol['diagnostic_rule']='freeze_validation_selection; evaluate_predeclared_diagnostics_before_holdout; stop_on_failure'
    study_id = 'MS-'+digest(protocol)[:24]
    folder = directory(study_id)
    with file_lock(folder/'study.lock', timeout=.1):
        path = folder/'protocol.json'
        if path.exists():
            old = _read(path, '固定研究协议')
            if {k:v for k,v in old.items() if k != 'sha256'} != protocol:
                raise ValueError('研究内容标识冲突')
        else:
            _write(path, protocol)
        # Publishing protocol before state is recoverable after interruption.
        if not (folder/'state.json').exists():
            _write(folder/'state.json', {'study_id': study_id, 'status': 'running', 'stage': 'training',
                'created_at': _now(), 'trials': [], 'training': [], 'shortlist': [], 'validation': [],
                'selection': None, 'holdout': None, 'previous_exposures_at_creation': _prior_exposure(evaluation, study_id)})
    return summary(load_study(study_id))


def _candidate(protocol, index):
    if not 0 <= index < protocol['grid_size']:
        raise ValueError('候选编号越界')
    remaining, params = index, {}
    for name, values in reversed(list(protocol['param_grid'].items())):
        remaining, offset = divmod(remaining, len(values))
        params[name] = values[offset]
    return {key: params[key] for key in protocol['param_grid']}


def _trial_key(role, candidate, seed):
    return f'{role}-C{candidate:08d}-S{seed}'


def _verified_trial(path):
    result = _read(path/'result.json', '模型求值回执')
    if read_json(path/'request.json') != {key: result[key] for key in
            ('contract_sha256', 'model_id', 'parameters', 'seed', 'role', 'ticks')}:
        raise ValueError('候选实际请求与结果不一致')
    if result['status'] in ('evaluated','executed'):
        for filename, key in [('fit.json','fit_sha256'), ('observations.json','observations_sha256'), ('manifest.json','manifest_sha256')]:
            if digest(read_json(path/filename)) != result[key]:
                raise ValueError('研究实际运行证据发生变化：' + filename)
    return result


def load_study(study_id):
    folder = directory(study_id)
    protocol = _read(folder/'protocol.json', '固定研究协议')
    if 'MS-'+protocol['sha256'][:24] != study_id:
        raise ValueError('研究ID与固定协议不一致')
    state = _read(folder/'state.json', '研究进度')
    if state['study_id'] != study_id:
        raise ValueError('研究进度归属错误')
    keys = set()
    for trial in state['trials']:
        relative = Path(trial['directory'])
        path = (folder/relative).resolve()
        if relative.is_absolute() or not path.is_relative_to((folder/'trials').resolve()):
            raise ValueError('候选证据路径越界')
        receipt = _verified_trial(path)
        if receipt['sha256'] != trial['receipt_sha256']:
            raise ValueError('候选回执与研究进度不一致')
        expected = _trial_key(trial['role'], trial['candidate'], trial['seed'])
        if (expected in keys or receipt['role'] != trial['role'] or receipt['seed'] != trial['seed']
                or receipt['parameters'] != _candidate(protocol, trial['candidate'])
                or receipt['contract_sha256'] != protocol['evaluation']['sha256']
                or receipt['status'] != trial['status'] or receipt['loss'] != trial['loss']):
            raise ValueError('实际候选/种子/角色与固定研究不一致')
        keys.add(expected)
    if state.get('diagnostics'):
        from .model_diagnostics import load_diagnostics,LEGACY_COMPARISON_RULE
        actual=load_diagnostics(protocol['evaluation'],state['selection']['parameters'],
            protocol['diagnostics'],protocol['seeds'],directory=folder/'diagnostics',
            comparison_rule=protocol.get('diagnostic_comparison_rule',LEGACY_COMPARISON_RULE))
        # A crash may publish a newer diagnostic result before the study state.
        # Validate it, then let advance_study recover it without repeating trials.
        if state['status']!='running' and actual['sha256']!=state['diagnostics']['result_sha256']:
            raise ValueError('已结束研究的诊断结果发生变化')
    return {'protocol': protocol, 'state': state}


def _aggregate(protocol, state, role, candidate):
    rows = [r for r in state['trials'] if r['role'] == role and r['candidate'] == candidate]
    if {r['seed'] for r in rows} != set(protocol['seeds']):
        return None
    failed = [r for r in rows if r['status'] != 'evaluated']
    losses = [r['loss'] for r in rows if r['status'] == 'evaluated']
    mean = math.fsum(losses)/len(losses) if losses else None
    variance = math.fsum((loss-mean)**2 for loss in losses)/(len(losses)-1) if len(losses)>1 else None
    return {'candidate': candidate, 'parameters': _candidate(protocol,candidate), 'seeds': list(protocol['seeds']),
            'loss': None if failed else mean, 'replicate_losses': losses,
            'failed_seeds': [r['seed'] for r in failed], 'status': 'failed' if failed else 'evaluated',
            'replicate_summary': {'completed':len(losses),'requested':len(protocol['seeds']),
                'sample_sd':None if variance is None or failed else math.sqrt(variance),
                'mean_standard_error':None if variance is None or failed else math.sqrt(variance/len(losses)),
                'scope':'实际重复的目标损失离散度；标准误依赖独立随机重复，不是参数区间或现实预测区间'}}


def _next(protocol, state):
    done = {_trial_key(r['role'],r['candidate'],r['seed']) for r in state['trials']}
    for role in ROLES:
        if role == 'training':
            candidates = range(protocol['grid_size'])
        elif role == 'validation':
            candidates = state['shortlist']
        else:
            candidates = [state['selection']['candidate']]
        state['stage'] = role
        for candidate in candidates:
            for seed in protocol['seeds']:
                if _trial_key(role,candidate,seed) not in done:
                    return role,candidate,seed
        aggregates = [_aggregate(protocol,state,role,c) for c in candidates]
        state[role] = aggregates if role != 'holdout' else aggregates[0]
        if role == 'training':
            ranked = sorted((r for r in aggregates if r['status'] == 'evaluated'), key=lambda r:(r['loss'],r['candidate']))
            if not ranked:
                state.update(status='failed', conclusion='all_training_candidates_failed')
                return None
            state['shortlist'] = [r['candidate'] for r in ranked[:protocol['selection_top']]]
        elif role == 'validation':
            ranked = sorted((r for r in aggregates if r['status'] == 'evaluated'),
                            key=lambda r:(r['loss'],state['shortlist'].index(r['candidate'])))
            if not ranked:
                state.update(status='failed', conclusion='all_validation_candidates_failed')
                return None
            selected = deepcopy(ranked[0])
            if state['selection'] is not None and state['selection'] != selected:
                raise ValueError('既定验证选型发生变化，不能用留出结果重新挑参数')
            state['selection'] = selected
            if protocol.get('diagnostics') and state.get('diagnostics',{}).get('status')!='complete':
                state['stage']='diagnostics'
                return 'diagnostics',selected['candidate'],None
    candidate = state['selection']['candidate']
    selected = {role: _aggregate(protocol,state,role,candidate) for role in ROLES}
    checks = {role: None if protocol['max_loss'][role] is None else
              selected[role]['loss'] is not None and selected[role]['loss'] <= protocol['max_loss'][role] for role in ROLES}
    state['acceptance'] = checks
    state['status'] = 'complete'
    state['stage'] = 'complete'
    state['conclusion'] = ('failed_holdout_execution' if state['holdout']['status'] == 'failed' else
        'failed_predeclared_tolerance' if False in checks.values() else
        'evaluated_without_full_acceptance_thresholds' if None in checks.values() else
        'passed_declared_checks_with_reused_holdout' if state['exposure']['previous_exposures'] else
        'passed_declared_checks')
    return None


def advance_study(study_id, *, max_evaluations=1):
    """Bound each tool call by actual trials; subsequent calls resume persisted work."""
    if type(max_evaluations) is not int or max_evaluations < 1:
        raise ValueError('本次实际求值数须为正整数')
    folder = directory(study_id)
    with file_lock(folder/'study.lock', timeout=.1):
        loaded = load_study(study_id)
        protocol, state = loaded['protocol'], loaded['state']
        if state['status'] in ('complete','failed','invalidated'):
            return summary(loaded)
        evaluations = 0
        while True:
            task = _next(protocol,state)
            state['updated_at'] = _now()
            _write(folder/'state.json',state)
            if task is None or evaluations >= max_evaluations:
                break
            role,candidate,seed = task
            if role=='diagnostics':
                from .model_diagnostics import advance_diagnostics,LEGACY_COMPARISON_RULE
                try:
                    diagnostic=advance_diagnostics(protocol['evaluation'],state['selection']['parameters'],
                        protocol['diagnostics'],protocol['seeds'],directory=folder/'diagnostics',
                        max_evaluations=max_evaluations-evaluations,
                        comparison_rule=protocol.get('diagnostic_comparison_rule',LEGACY_COMPARISON_RULE))
                    evaluations+=diagnostic['new_evaluations']
                    state['diagnostics']={key:diagnostic[key] for key in
                        ('status','completed_trials','total_trials','protocol_sha256')}
                    state['diagnostics']['result_sha256']=diagnostic['sha256']
                    if diagnostic['status']=='failed':
                        state.update(status='failed',conclusion='failed_predeclared_diagnostics')
                except ValueError as exc:
                    state.update(status='failed',conclusion='diagnostic_protocol_invalidated',error=str(exc))
                _write(folder/'state.json',state)
                if state['status']=='failed':break
                continue
            if role == 'holdout':
                state['exposure'] = _expose(study_id,protocol['evaluation'])
                _write(folder/'state.json',state)  # record before evaluation, even if later interrupted
            trial_folder = folder/'trials'/_trial_key(role,candidate,seed)
            attempts = sorted(trial_folder.glob('attempt-*'))
            finished = [path for path in attempts if (path/'result.json').is_file()]
            if finished:
                attempt = finished[-1]
                receipt = _verified_trial(attempt)  # recover published result after a lost state write
            else:
                attempt = trial_folder/f'attempt-{len(attempts)+1:06d}'
                receipt = evaluate_role(protocol['evaluation'], parameters=_candidate(protocol,candidate),
                                        seed=seed, role=role, directory=attempt)
                evaluations += 1
            expected = {'contract_sha256':protocol['evaluation']['sha256'], 'parameters':_candidate(protocol,candidate),
                        'seed':seed,'role':role,'model_id':protocol['evaluation']['model']['model_id']}
            if any(receipt.get(k) != v for k,v in expected.items()):
                raise ValueError('恢复的实际求值不属于当前研究候选')
            state['trials'].append({'candidate':candidate, 'seed':seed, 'role':role,
                'directory':attempt.relative_to(folder).as_posix(), 'receipt_sha256':receipt['sha256'],
                'status':receipt['status'], 'loss':receipt['loss']})
            if receipt.get('failure_stage') == 'preflight':
                state.update(status='invalidated',conclusion='pre_execution_contract_invalidated',
                             error=receipt['error'])
            _write(folder/'state.json',state)
            if state['status']=='invalidated':
                break
    return summary(load_study(study_id))


def summary(study):
    protocol,state = study['protocol'],study['state']
    result = {key: deepcopy(state[key]) for key in ('study_id','status','stage','created_at','updated_at',
        'training','shortlist','validation','selection','holdout','diagnostics','acceptance','conclusion','error','previous_exposures_at_creation') if key in state}
    result.update(question=protocol['question'],model_id=protocol['evaluation']['model']['model_id'],
        protocol_sha256=protocol['sha256'], completed_trials=len(state['trials']),
        failed_trials=sum(row['status'] != 'evaluated' for row in state['trials']),
        grid_size=protocol['grid_size'], seeds=protocol['seeds'], selection_top=protocol['selection_top'],
        limits=['有限网格选型不证明全局最优、参数可识别或现实政策因果',
                '训练/验证/留出误差是不同分区的证据，原始数据可用时点另需核验'])
    result['diagnostic_scope']=('已事前声明，完整试验和比较保存在同研究diagnostics目录'
        if protocol.get('diagnostics') else '未声明数值/机制诊断，不能据拟合误差认定数值收敛或机制有效')
    if protocol.get('diagnostics'):
        from .model_diagnostics import CURRENT_COMPARISON_RULE,LEGACY_COMPARISON_RULE
        result['diagnostic_comparison_rule']=protocol.get('diagnostic_comparison_rule',LEGACY_COMPARISON_RULE)
        result['diagnostic_scope']+=('；全部细化档分别与首档基线比较，全部共同时间/指标差异取最大值'
            if result['diagnostic_comparison_rule']==CURRENT_COMPARISON_RULE else
            '；历史旧规则仅以最细档对基线判定，不能证明中间细化档通过；原记录保留，未冒充新版检查')
    if protocol.get('baseline'):
        result['baseline_run_id']=protocol['baseline']['run_id']
    if state.get('selected_run'):
        result['run_id']=state['selected_run']['run_id']
        result['result_scope']=state['selected_run']['scope']
    if state.get('exposure'):
        result['holdout_exposure'] = {key:value for key,value in state['exposure'].items() if key != 'cells'}
    if state['status'] == 'running':
        result['continuation'] = {'study_id':state['study_id'],'max_evaluations':1}
        result['next_action']={'action':'research_calibrate','arguments':result['continuation']}
    return result


def list_studies():
    rows=[]
    for path in base().glob('MS-*/protocol.json'):
        try:rows.append(summary(load_study(path.parent.name)))
        except (OSError,ValueError,KeyError) as exc:
            rows.append({'study_id':path.parent.name,'status':'integrity_failed','error':str(exc)})
    return sorted(rows,key=lambda row:row.get('created_at',''),reverse=True)
