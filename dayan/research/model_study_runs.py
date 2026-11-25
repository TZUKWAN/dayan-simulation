"""Archive an actual selected-model trajectory for study playback.

This run reproduces one predeclared seed, not the uncertainty of all replicates.
Its observations must match the corresponding evaluated trial before archival.
"""
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import uuid

from ..collection.storage import file_lock,read_json
from ..solvers.codec import digest
from . import model_studies as studies


def can_finalize(study):
    state=study['state']
    return (state.get('selection') is not None and state.get('holdout',{} ) is not None
            and state.get('conclusion') in ('passed_declared_checks','passed_declared_checks_with_reused_holdout',
                'failed_predeclared_tolerance','evaluated_without_full_acceptance_thresholds'))


def next_action(study):
    sid=study['state']['study_id']
    if study['state']['status']=='running':
        return {'action':'research_calibrate','arguments':{'study_id':sid,'max_evaluations':1}}
    if study['state']['status']=='invalidated':return None
    if can_finalize(study) and not study['state'].get('selected_run'):
        return {'action':'research_finalize','arguments':{'study_id':sid}}
    return {'action':'research_report','arguments':{'study_id':sid}}


def _reference(study):
    p,s=study['protocol'],study['state']
    seed=p['seeds'][0]
    reference=next((row for row in s['trials'] if row['role']=='holdout'
                    and row['candidate']==s['selection']['candidate'] and row['seed']==seed),None)
    if not reference or reference['status']!='evaluated':
        raise ValueError('所选展示种子没有实际留出求值，不能用另一随机轨迹冒充')
    folder=studies.directory(s['study_id'])/reference['directory']
    receipt=studies._verified_trial(folder)
    return seed,receipt,read_json(folder/'observations.json')


def _matches(study,manifest,observations):
    p,s=study['protocol'],study['state'];c=p['evaluation']
    seed,reference,expected=_reference(study)
    provenance=manifest.get('research_study',{})
    parameters={name:spec['default'] for name,spec in c['model']['definition'].get('parameters',{}).items()}
    parameters.update(c['execution']['parameters']);parameters.update(s['selection']['parameters'])
    if (manifest['source_fingerprint']!=c['source_fingerprint'] or manifest['model_definition']!=c['model']['definition']
            or manifest['rng']['seed']!=seed or manifest['actual']['n_steps']!=c['execution']['ticks']
            or manifest['actual']['dt_used']!=c['execution']['dt']
            or provenance.get('study_id')!=s['study_id'] or provenance.get('protocol_sha256')!=p['sha256']
            or provenance.get('trial_receipt_sha256')!=reference['sha256']
            or provenance.get('selected_parameters')!=s['selection']['parameters']
            or manifest['actual']['effective_parameters']!=parameters
            or digest(observations[:len(expected)])!=digest(expected)):
        raise ValueError('科研结果运行未复现同模型/版本/时钟/参数/种子的实际求值轨迹')
    return seed,reference


def verify_selected_run(study):
    from ..run_store import get_store
    entry=study['state'].get('selected_run')
    if not entry:return None
    store=get_store()
    meta,manifest=store.load_manifest(entry['run_id'])
    if meta['files']!=entry['archive_files']:raise ValueError('科研结果归档版本已改变')
    for name,expected in meta['files'].items():
        with (store._path(entry['run_id'])/name).open('rb') as handle:
            if hashlib.file_digest(handle,'sha256').hexdigest()!=expected:
                raise ValueError('科研结果归档文件校验失败：'+name)
    saved=store.load(entry['run_id'],exclude=['state_frames.json','checkpoint.json','events.json'])
    _matches(study,manifest,saved['observations'])
    return {'run_id':entry['run_id'],'manifest':manifest,'observations':saved['observations'],
            'archive_files':meta['files'],'scope':entry['scope']}


def finalize_study(study_id):
    from ..runtime import run_model_full,assert_loaded_source
    from ..run_store import get_store
    folder=studies.directory(study_id)
    with file_lock(folder/'study.lock',timeout=.1):
        study=studies.load_study(study_id)
        p,s=study['protocol'],study['state'];c=p['evaluation']
        if not can_finalize(study):raise ValueError('该研究尚无可归档的所选模型，或未通过必要的数值诊断')
        if s.get('selected_run'):
            verify_selected_run(study)
            return result(study)
        if assert_loaded_source()!=c['source_fingerprint']:raise ValueError('研究源码版本已变化，不能重新计算结果运行')
        seed,reference,_=_reference(study)
        if not s.get('selected_run_reservation'):
            s['selected_run_reservation']='R'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex
            s=studies._write(folder/'state.json',s)
            study['state']=s
        rid=s['selected_run_reservation'];store=get_store()
        from ..history_records import preferences
        if preferences(store).get(rid,{}).get('deleted'):raise ValueError('结果归档已被用户删除，不能自动恢复删除项')
        if store._path(rid).exists():
            saved=store.load(rid)
            _matches(study,saved['manifest'],saved['observations'])
        else:
            e=c['execution']
            run=run_model_full(c['model']['model_id'],parameters={**e['parameters'],**s['selection']['parameters']},
                ticks=e['ticks'],dt=e['dt'],seed=seed,experiment=e['experiment'],strict=True,with_time=True,
                data_bindings=e['data_bindings'],capture_state=True,
                full_frames=bool(p.get('baseline',{}).get('manifest',{}).get('scale',{}).get('all_steps_archived')))
            run.manifest['run_id']=rid
            for frame in run.state_frames:frame['run_id']=rid
            run.manifest['research_study']={'study_id':study_id,'protocol_sha256':p['sha256'],
                'selected_parameters':s['selection']['parameters'],'representative_seed':seed,
                'trial_receipt_sha256':reference['sha256'],'conclusion':s.get('conclusion'),
                'scope':'预先种子列表第一项的实际状态回放；不是重复均值或现实因果证明'}
            _matches(study,run.manifest,run.observations)
            review=deepcopy(run.manifest.get('scenario_review') or {})
            review['coverage']={'status':'research_result','gaps':[],
                'limits':['同研究的所选参数、一个事前种子的实际状态回放；研究结论见research_study.conclusion']}
            review['runtime_checks']={'observations':len(run.observations),'state_frames':len(run.state_frames),
                'verification':{'status':'passed','issues':[],
                    'scope':'实际引擎结构校验及所选研究试验逐观测复现；不沿用默认参数的基线数值检查',
                    'criteria':[],'matched_trial_receipt_sha256':reference['sha256']}}
            run.manifest['scenario_review']=review
            store.save_run(run,source='research_selected_result',request_text=p['question'],intent=p['question'])
            saved=store.load(rid,exclude=['state_frames.json','checkpoint.json','events.json'])
        s['selected_run']={'run_id':rid,'archive_files':deepcopy(saved['files']),
            'seed':seed,'trial_receipt_sha256':reference['sha256'],
            'scope':'实际所选参数、预先种子列表第一项；不是多seed均值动画'}
        studies._write(folder/'state.json',s)
        study=studies.load_study(study_id)
        verify_selected_run(study)
    return result(study)


def result(study):
    p,s=study['protocol'],study['state'];rid=s['selected_run']['run_id']
    return {'study_id':s['study_id'],'run_id':rid,'model_id':p['evaluation']['model']['model_id'],
        'status':'result_archived','request_complete':False,'conclusion':s.get('conclusion'),
        'state_url':'/api/runs/'+rid+'/state','bundle_url':'/api/runs/'+rid+'/bundle.zip',
        'scope':s['selected_run']['scope'],'next_action':{'action':'research_report','arguments':{'study_id':s['study_id']}}}


def for_model_run(run_id):
    from ..run_store import get_store
    try:_,manifest=get_store().load_manifest(run_id)
    except (OSError,KeyError):return None
    link=manifest.get('research_study') or {}
    sid=link.get('study_id')
    if not sid:
        intent=(manifest.get('scenario_review') or {}).get('research_intent')
        if intent:
            from .model_intents import load_intent
            sid=load_intent(intent['research_intent_id'])['state'].get('study_id')
    if not sid:return None
    study=studies.load_study(sid)
    if run_id not in (study['protocol'].get('baseline',{}).get('run_id'),study['state'].get('selected_run',{}).get('run_id')):
        raise ValueError('运行编号与研究的真实基线/结果关联不一致')
    return studies.summary(study)
