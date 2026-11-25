"""Compile source-backed candidates without replacing explicit research constraints."""
from __future__ import annotations
from dataclasses import dataclass, field
from .specs import ResearchSpec, ExperimentSpec
from .requirements import extract_request, model_mechanisms, coverage_issues
from .semantics import candidates as rank_candidates, registry


@dataclass
class CompileResult:
    research_spec: ResearchSpec
    candidates: list = field(default_factory=list)
    experiment_spec: ExperimentSpec | None = None
    warnings: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def _pick_metric(mid, requested=None):
    from ..output_contract import output_contract, validate_metric
    schema = output_contract(mid)
    if requested:return validate_metric(mid, requested)
    if schema['primary_metric']:return schema['primary_metric']
    numeric=[name for name,f in schema['fields'].items() if f['type']=='number'
             and name not in ('sim_t','t','tick','step')]
    return numeric[0] if len(numeric)==1 else ''


def compile_research(text: str, purpose=None, ticks=None, dt=None, seeds=None,
                     research_id='', model_id=None, parameters=None,
                     interventions=None, metric=None, last_run=None) -> CompileResult:
    request=extract_request(text,last_run)
    options=request['options']
    dt_explicit = dt is not None or 'dt' in options
    ticks=options.get('ticks',200 if ticks is None else ticks)
    dt=options.get('dt',.1 if dt is None else dt)
    seeds=options.get('seeds',[options['seed']] if 'seed' in options else seeds)
    seeds=[0,1,2,3] if seeds is None else list(seeds)
    purpose=request['purpose'] if purpose is None else purpose
    ids=request['model_ids']
    mid=ids[0] if len(ids)==1 else model_id
    baseline={**(parameters or {}),**request['parameters']}
    for key in ('analysis_window','warmup_ticks'):baseline.pop(key,None)
    required=request['mechanisms'] or sorted(model_mechanisms(mid))
    research=ResearchSpec(original_request=text,purpose=purpose,
        mechanisms_required=required or (['用户指定模型'] if mid else []),research_questions=[text],
        population='、'.join(request['population']),space_scope='、'.join(request['space_scope']),
        time_scope='、'.join(request['time_scope']),outcomes=[metric or request['metric']] if metric or request['metric'] else [],
        evidence_requirement='validated' if purpose=='prediction' else 'calibrated' if request['requires_real_data'] else 'theoretical').finalize()
    if research_id:research.research_id=research_id
    research.assumptions['confirmed']=[f'排除机制：{name}' for name in request['excluded_mechanisms']]
    for key,value in (('ticks',ticks),('dt',dt),('seeds',seeds)):
        if key not in options and not (key=='seeds' and 'seed' in options):
            research.assumptions['suggested'].append(f'执行默认{key}={value}；不是从自然语言推断的实测值')
    ranked=rank_candidates(request)
    eligible=[c for c in ranked if not c['missing_mechanisms'] and c['requested_metric_supported']]
    issues=[]
    if not mid and eligible:
        top=eligible[0]
        if len(eligible)==1 or top['score']>eligible[1]['score']:
            mid=top['model_id']
        else:issues.append('候选机制存在歧义，请明确模型或机制变体：'+', '.join(c['model_id']+' '+c['description'] for c in eligible))
    if not mid and not eligible:issues.append('尚未找到覆盖全部原始机制和指标的可运行模型；不能用局部匹配替代')
    # Disable features in the actual model, not just in presentation.
    if mid=='CPL001':
        disabled={'信息传播':{'initial_rumor_fraction':0.,'rumor_rate':0.},
                  '接驳运力':{'bus_count':0},'积水影响':{'flood_severity':0.}}
        for name in request['excluded_mechanisms']:
            for key,value in disabled.get(name,{}).items():
                if key in baseline and baseline[key]!=value:issues.append(f'排除{name}与显式参数{key}={baseline[key]}冲突')
                else:baseline[key]=value
    effective={**request,'parameters':baseline}
    issues.extend(coverage_issues(effective,mid))
    if len(ids)>1:issues.append('多模型实验必须明确每个模型的规约和映射，不能只运行第一个')
    from ..model_index import resolve
    _, factory = resolve(mid) if mid else (None, None)
    if mid and factory is None:issues.append(f'{mid} 无运行工厂')
    if factory is not None:
        cls = factory[1] if isinstance(factory,tuple) else factory
        fixed_dt = getattr(cls,'fixed_dt',None)
        if fixed_dt is not None and dt_explicit and dt!=fixed_dt:
            issues.append(f'{mid} 每步对应一个观测间隔，dt须为{fixed_dt}')
        elif fixed_dt is not None and not dt_explicit:
            research.assumptions['suggested']=[s for s in research.assumptions['suggested'] if not s.startswith('执行默认dt=')]
            research.assumptions['suggested'].append(f'dt={fixed_dt} 来自模型的观测间隔合同')
            dt = fixed_dt
    if factory is not None and not any(c['model_id']==mid for c in ranked):
        from ..output_contract import output_contract
        ranked.insert(0,{'model_id':mid,'runnable':True,'mechanism':sorted(model_mechanisms(mid)),
                         'reason':'原始需求指定','output_fields':list(output_contract(mid)['fields']),
                         'fidelity':'unverified','basis':'用户指定工厂；不推断已校准或科学有效'})
    required_data=registry().get(mid,{}).get('required_data',[])
    missing_data=[name for name in required_data if not baseline.get(name)]
    if missing_data:issues.append('所选模型需要实际数据输入：'+', '.join(missing_data))
    import math,re
    duration=re.search(r'(?:持续|运行|模拟)\s*(\d+(?:\.\d+)?)\s*(秒|分钟|小时|天)',text)
    if duration:
        clock=registry().get(mid,{}).get('clock')
        seconds=float(duration.group(1))*{'秒':1,'分钟':60,'小时':3600,'天':86400}[duration.group(2)]
        if clock not in ('second','minute'):
            issues.append('指定了现实时间，但当前模型没有经核定的秒/分钟换算；不能将小时擅自当作仿真步')
        else:
            horizon=seconds/(60 if clock=='minute' else 1)
            count=horizon/dt
            if not math.isclose(count,round(count),rel_tol=0,abs_tol=1e-8):
                issues.append('指定时长不是步长的整数倍，请明确终点或步长；不能截短最后一段')
            elif 'ticks' in options and not math.isclose(ticks*dt,horizon,rel_tol=0,abs_tol=1e-8):
                issues.append('显式运行步数/步长与指定时长冲突')
            else:ticks=round(count)
    if purpose=='prediction':issues.append('现实预测必须先绑定同地区、主体和时间口径数据，校准并通过独立留出验证；本次不能冒充已验证预测')
    research.mechanisms_missing=sorted(set(required)-model_mechanisms(mid)) if mid else list(required)
    issues.extend(research.validate())
    ivs=request['interventions'] or interventions or []
    if any(iv.get('at_t') is None for iv in ivs):issues.append('干预缺少明确时点，不能擅自选择第25%处')
    if mid and not issues:
        try:primary=_pick_metric(mid,metric or request['metric'])
        except ValueError as exc:issues.append(str(exc));primary=''
        if not primary and not issues:
            from ..output_contract import output_contract
            issues.append('请选择主要结局指标 primary_metric；不能擅自选择第一个字段。可选：'+', '.join(output_contract(mid)['fields']))
    if issues:
        issues=list(dict.fromkeys(issues));research.unsupported_requirements=issues;research.open_questions=issues
        return CompileResult(research,ranked,None,issues,[])
    research.outcomes=[primary]
    arms=[{'label':'用户指定干预','params':{},'interventions':ivs}] if ivs else []
    exp=ExperimentSpec(research_id=research.research_id,model_id=mid,title=text[:100],
        baseline_params=baseline,arms=arms,ticks=ticks,dt=dt,seeds=seeds,primary_metric=primary,
        warmup_ticks=options.get('warmup_ticks',0),analysis_window=options.get('analysis_window',[]),purpose=purpose,
        hypothesis='用户指定干预相对同种子基线的模型内差异' if arms else '基线重复运行').finalize()
    validation=exp.validate()
    research.unsupported_requirements=validation
    return CompileResult(research,ranked,None if validation else exp,validation,
        ['候选比较依据源码机制和输出合同；未把探针、历史审查或真实数据存在当作校准成功',
         '仅执行原始需求中的干预；未插入固定幅度或时间模板'])
