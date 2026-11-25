"""Resumable pick-freeze Sobol evaluations of an actual reviewed model."""
from copy import deepcopy
import math
import time
import numpy as np
from scipy import stats

from ..access import data_root
from ..collection.storage import atomic_json,read_json,file_lock
from ..solvers.codec import digest
from ..limits import limits


def folder(analysis_id):
    import re
    if not isinstance(analysis_id,str) or not re.fullmatch(r'AN-GS-[a-f0-9]{32}',analysis_id):
        raise ValueError('全局敏感性编号格式错误')
    return data_root()/'global_sensitivity'/analysis_id


def distribution(spec):
    if not isinstance(spec,dict) or set(spec)-{'kind','low','high','mode'}:
        raise ValueError('独立参数分布须给kind、low、high；triangular另给mode')
    low,high=spec.get('low'),spec.get('high')
    if any(type(x) not in (int,float) or not math.isfinite(x) for x in (low,high)) or low>=high:
        raise ValueError('分布上下界须为有限数且low<high')
    kind=spec.get('kind')
    if kind=='uniform':return stats.uniform(loc=low,scale=high-low)
    if kind=='loguniform' and low>0:return stats.loguniform(low,high)
    if kind=='triangular' and type(spec.get('mode')) in (int,float) and low<=spec['mode']<=high:
        return stats.triang((spec['mode']-low)/(high-low),loc=low,scale=high-low)
    raise ValueError('分布支持uniform、正值loguniform或含mode的triangular')


def sample(distributions,n,seed):
    if type(n)!=int or n<2 or n&(n-1):raise ValueError('Sobol n须为至少2的二次幂，不静默改写')
    names=list(distributions)
    if not names:raise ValueError('须声明至少一个独立数值参数分布')
    points=stats.qmc.Sobol(d=2*len(names),scramble=True,seed=seed).random_base2(int(math.log2(n)))
    a=np.empty((n,len(names)));b=a.copy()
    for j,key in enumerate(names):
        dist=distribution(distributions[key]);a[:,j]=dist.ppf(points[:,j]);b[:,j]=dist.ppf(points[:,j+len(names)])
    matrices=[('A',a),('B',b)]
    for j,key in enumerate(names):
        mixed=a.copy();mixed[:,j]=b[:,j];matrices.append(('AB:'+key,mixed))
    return [{'matrix':label,'row':i,'parameters':dict(zip(names,map(float,row)))}
            for label,matrix in matrices for i,row in enumerate(matrix)]


def calculate(values,n,names,*,seed=0):
    y=np.asarray(values,dtype=float).reshape(len(names)+2,n)
    if not np.isfinite(y).all():raise ValueError('实际求值含非有限数，不能制造敏感性结论')
    variance=float(np.var(y[:2]))
    if variance==0:
        return {'status':'undefined_constant_output','variance':0.,'indices':[
            {'parameter':key,'first_order':None,'total_order':None,'first_interval':None,'total_interval':None} for key in names]}
    # Same Saltelli-2010 centered estimator, without SciPy 1.16's scalar-output
    # item-assignment bug for d=1. Resample corresponding A/B/AB rows together.
    def estimate(matrix):
        centered=matrix-matrix[:2].mean()
        var=np.var(centered[:2])
        if var==0:return np.full(len(names),np.nan),np.full(len(names),np.nan)
        a,b,ab=centered[0],centered[1],centered[2:]
        return np.mean(b*(ab-a),axis=-1)/var,.5*np.mean((a-ab)**2,axis=-1)/var
    first,total=estimate(y)
    rng=np.random.default_rng(seed)
    replicas=[estimate(y[:,rng.integers(0,n,n)]) for _ in range(256)]
    lo1,hi1=np.nanpercentile([r[0] for r in replicas],[2.5,97.5],axis=0)
    lot,hit=np.nanpercentile([r[1] for r in replicas],[2.5,97.5],axis=0)
    finite=lambda value:float(value) if np.isfinite(value) else None
    return {'status':'estimated','variance':variance,'indices':[{
        'parameter':key,'first_order':float(first[j]),'total_order':float(total[j]),
        'first_interval':[finite(lo1[j]),finite(hi1[j])],'total_interval':[finite(lot[j]),finite(hit[j])]}
        for j,key in enumerate(names)]}


def run(*,query=None,baseline_run_id=None,distributions=None,metric=None,n=128,seeds=None,
        sampling_seed=0,statistic='last',analysis_id=None,max_evaluations=1):
    from .baseline_context import restore
    from ..runtime import run_model_full
    from ..run_store import get_store
    from ..agent.tools import _coerce_seeds
    from ..run_progress import RunProgress,RunPaused
    if type(max_evaluations)!=int or max_evaluations<1:raise ValueError('max_evaluations须为正整数')
    store=get_store()
    if analysis_id is None:
        context=restore(baseline_run_id)
        if not isinstance(query,str) or not query.strip():raise ValueError('须保留实际研究问题')
        if statistic not in ('last','mean','peak'):raise ValueError('statistic为last、mean或peak')
        if metric not in context['definition']['observables']:raise ValueError('metric须为实际观测')
        if not isinstance(distributions,dict):raise ValueError('distributions须按实际参数名声明独立分布')
        for key,spec in distributions.items():
            p=context['definition'].get('parameters',{}).get(key)
            if not p or p['type']!='float' or key in context['bound']:
                raise ValueError('只可采样未被真实数据固定的连续参数：'+key)
            distribution(spec)
            if spec['low']<p.get('minimum',-math.inf) or spec['high']>p.get('maximum',math.inf):
                raise ValueError('分布超出模型实际参数边界：'+key)
        points=sample(distributions,n,sampling_seed)
        protocol={'query':query,'baseline_run_id':baseline_run_id,'definition_sha256':digest(context['definition']),
            'source_fingerprint':context['proof']['source_fingerprint'],'distributions':deepcopy(distributions),
            'metric':metric,'n':n,'seeds':list(_coerce_seeds(seeds if seeds is not None else context['proof']['manifest']['rng']['seed'])),
            'sampling_seed':sampling_seed,'statistic':statistic,'points':points,
            'scope':'独立参数分布的配对种子面板均值敏感性；256次配对行percentile bootstrap为有限样本近似区间，不代表现实因果效应或参数可识别性'}
        analysis_id='AN-GS-'+digest(protocol)[:32]
        directory=folder(analysis_id)
        directory.mkdir(parents=True,exist_ok=True)
        if not (directory/'protocol.json').exists():atomic_json(directory/'protocol.json',protocol)
    else:
        if any(v is not None for v in (query,baseline_run_id,distributions,metric,seeds)):
            raise ValueError('续接只传analysis_id及max_evaluations，恢复原协议不重新填参')
        directory=folder(analysis_id);protocol=read_json(directory/'protocol.json')
        if analysis_id!='AN-GS-'+digest(protocol)[:32]:raise ValueError('敏感性协议摘要不一致')
        context=restore(protocol['baseline_run_id'])
        if digest(context['definition'])!=protocol['definition_sha256']:raise ValueError('模型定义已变化')
    with file_lock(directory/'work.lock',timeout=.1):
        call_deadline=time.monotonic()+limits().wall_seconds-10
        state=read_json(directory/'state.json') if (directory/'state.json').exists() else {'runs':[]}
        if state.get('complete'):return state['payload']
        total=len(protocol['points'])*len(protocol['seeds'])
        for _ in range(min(max_evaluations,total-len(state['runs']))):
            index=len(state['runs']);point=protocol['points'][index//len(protocol['seeds'])]
            seed=protocol['seeds'][index%len(protocol['seeds'])]
            progress=RunProgress(directory/'evaluations'/str(index),call_deadline)
            try:
                rr=run_model_full(context['proof']['model_id'],**{**context['options'],'parameters':{**context['parameters'],**point['parameters']}},
                    seed=seed,capture_state=False,strict=True,_progress=progress)
            except RunPaused as exc:
                return {'status':'pending','analysis_id':analysis_id,'completed_runs':len(state['runs']),'required_runs':total,
                    'solver_progress':{'sample':index,'reason':str(exc),'checkpoint_saved':progress.record is not None},
                    'next_action':{'action':'global_sensitivity','arguments':{'analysis_id':analysis_id,'max_evaluations':max_evaluations}}}
            values=[float(row[protocol['metric']]) for row in rr.observations]
            if not values or not np.isfinite(values).all():raise ValueError('实际运行无完整有限观测')
            value=values[-1] if protocol['statistic']=='last' else float(np.mean(values)) if protocol['statistic']=='mean' else max(values)
            rr.manifest['global_sensitivity']={'analysis_id':analysis_id,'baseline_run_id':protocol['baseline_run_id'],
                'matrix':point['matrix'],'row':point['row'],'sample_parameters':point['parameters'],'scope':protocol['scope']}
            rid=rr.manifest['run_id']
            if store._path(rid).exists():
                saved=store.load(rid)
                if saved['manifest'].get('global_sensitivity')!=rr.manifest['global_sensitivity'] or saved['observations']!=rr.observations:
                    raise ValueError('该敏感性样本的既存真实运行与恢复结果不一致')
            else:store.save_run(rr,source='global_sensitivity',request_text=protocol['query'])
            state['runs'].append({'run_id':rid,'model_id':rr.model_id,'seed':seed,'point_index':index//len(protocol['seeds']),
                'matrix':point['matrix'],'row':point['row'],'parameters':point['parameters'],'value':value,'label':point['matrix']+' / '+str(point['row'])})
            atomic_json(directory/'state.json',state)
        if len(state['runs'])<total:
            return {'status':'pending','analysis_id':analysis_id,'completed_runs':len(state['runs']),'required_runs':total,
                'next_action':{'action':'global_sensitivity','arguments':{'analysis_id':analysis_id,'max_evaluations':max_evaluations}}}
        panels=np.array([r['value'] for r in state['runs']]).reshape(len(protocol['points']),len(protocol['seeds']))
        analysis={'kind':'global_sensitivity','analysis_id':analysis_id,'metric':protocol['metric'],'protocol':protocol,
            **calculate(panels.mean(axis=1),protocol['n'],list(protocol['distributions']),seed=protocol['sampling_seed']),
            'sampling_values':panels.mean(axis=1).tolist(),
            'mean_within_point_seed_variance':float(np.var(panels,axis=1,ddof=1).mean()) if len(protocol['seeds'])>1 else None,
            'causality_note':protocol['scope'],'replicate_note':'单种子不能估计随机噪声；外部LLM不由数值seed完全决定；跨种子重复及更大n用于检查估计稳健性。'}
        payload={'status':'completed','tool':'global_sensitivity','model_id':context['proof']['model_id'],
            'run_id':state['runs'][0]['run_id'],'analysis_id':analysis_id,'runs':state['runs'],'analysis':analysis,
            'completed_runs':total,'required_runs':total,'baseline_run_id':protocol['baseline_run_id']}
        store.save_analysis('global_sensitivity',payload,record_id=analysis_id)
        state.update(complete=True,payload=payload);atomic_json(directory/'state.json',state)
        return payload


def tool_global_sensitivity(**kwargs):
    try:return {'ok':True,'payload':run(**kwargs)}
    except Exception as exc:return {'ok':False,'error':f'{type(exc).__name__}: {exc}'}


def schema():
    return {'type':'object','additionalProperties':False,'properties':{
        'query':{'type':'string'},'baseline_run_id':{'type':'string'},'analysis_id':{'type':'string'},
        'distributions':{'type':'object','additionalProperties':{'type':'object','required':['kind','low','high'],
            'additionalProperties':False,'properties':{'kind':{'enum':['uniform','loguniform','triangular']},
                'low':{'type':'number'},'high':{'type':'number'},'mode':{'type':'number'}}}},
        'metric':{'type':'string'},'n':{'type':'integer','minimum':2,'default':128},
        'seeds':{'type':'array','items':{'type':'integer','minimum':0},'minItems':1},
        'sampling_seed':{'type':'integer','minimum':0},'statistic':{'enum':['last','mean','peak'],'default':'last'},
        'max_evaluations':{'type':'integer','minimum':1,'default':1}},
        'oneOf':[{'required':['query','baseline_run_id','distributions','metric'],'not':{'required':['analysis_id']}},
                 {'required':['analysis_id'],'not':{'anyOf':[{'required':[x]} for x in ('query','baseline_run_id','distributions','metric','seeds','n','sampling_seed','statistic')]}}]}
