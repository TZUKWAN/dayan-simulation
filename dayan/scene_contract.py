"""Trace concrete scene requirements to executable definitions and exported state.

This validates references and data flow. It does not certify domain validity.
"""
from __future__ import annotations

import ast
import re

FACILITY_KINDS = {'room','building','exit','destination','source','obstacle','road','signal','service','zone'}
SCENE_FEATURES = {
    'room': r'大厅|房间|教室|室内|仓库',
    'building': r'建筑|教学楼|办公楼|楼栋',
    'exit': r'出口|安全门',
    'destination': r'目的地|补给点|集合点',
    'obstacle': r'障碍物|避障|绕行|墙体',
    'road': r'十字路口|交叉路口|路口|多车道|双向车道',
    'signal': r'红绿灯|信号灯|交通灯',
    'service': r'服务窗口|挂号窗口|收银台',
}
MODEL_REFS = ('agents.', 'initial_state.', 'rates.', 'observables.', 'space.', 'parameters.')
VISUAL_REFS = ('scenario.facilities.', 'agents.', 'space.', 'visualization.')


def scene_requirements(text):
    text=str(text or '')
    # A request to omit an element is not a requirement to fabricate that element.
    omission=(r'(?:不要(?!省略|删除|忽略|漏掉|遗漏|删去|去掉|取消)|无需|不需要|不考虑|不用'
              r'|(?:不|不能|不得|禁止)(?:虚构|伪造)'
              r'|(?:没有|未)(?:提供|包含|给出|记录|采集到))')
    positive=re.sub(omission+r'(?:(?!但是|但|然而|而是|不过)[^，,。；;\n])*', '', text)
    features=[key for key,pattern in SCENE_FEATURES.items() if re.search(pattern,positive)]
    return {'features':features,
            'spatial':bool(features or re.search(r'场景|布局|地形|地图|建筑物|校区|车站|商场|街区|操场|医院|学校|校园|工厂|地铁站|博物馆|体育场|公园|超市|元胞自动机|局部邻域|摩尔邻域|冯[·・.]?诺依曼邻域',positive)),
            'unsupported':[label for pattern,label in [
                (r'多层(?:场景|建筑|楼房|教学楼|综合体|交通枢纽|疏散)|跨楼层|三维碰撞|三维物理|楼梯疏散','多层/三维实体运动'),
                (r'刚体碰撞|流体力学|烟气扩散|烟雾扩散','物理碰撞/流体或烟气场')]
                if re.search(pattern,positive)]}


def _names(expr):
    return {n.id for n in ast.walk(ast.parse(str(expr),mode='eval')) if isinstance(n,ast.Name)}


def reference(definition,path,*,allow_empty=False):
    """Resolve only real definition paths; facility IDs are stable, not array offsets."""
    if definition.get('kind')=='program' and str(path).startswith('source.'):
        from .program_evidence import fragments
        value=fragments(definition).get(path[7:])
        if value is None:raise ValueError('程序函数证据不存在：'+str(path))
        return value
    node=definition
    for part in str(path).split('.'):
        if isinstance(node,dict) and part in node:node=node[part]
        elif isinstance(node,list):
            node=next((item for item in node if isinstance(item,dict) and item.get('id')==part),None)
            if node is None:raise ValueError('场景证据引用不存在：'+str(path))
        else:raise ValueError('场景证据引用不存在：'+str(path))
    if node in (None,'') or not allow_empty and node in ({},[]):raise ValueError('场景证据引用为空：'+str(path))
    return node


def validate_scene(definition,request=None):
    if definition.get('kind')=='program':
        from .program_scene import validate_scene as validate_program_scene
        return validate_program_scene(definition,request)
    scene=definition.get('scenario')
    if scene is None:
        if request and scene_requirements(request)['spatial']:
            raise ValueError('具体空间需求缺少scenario场景合同；不能用抽象主体或汇总图替代')
        return
    if not isinstance(scene,dict) or set(scene)-{'title','setting','agent_label','source_request','facilities','requirements'}:
        raise ValueError('scenario含未知字段')
    for field,limit in [('title',48),('setting',160),('agent_label',32)]:
        if not isinstance(scene.get(field),str) or not 1<=len(scene[field])<=limit:
            raise ValueError('scenario.'+field+'缺少受限长度的真实场景说明')
    if definition['kind']=='stocks' or not definition.get('agents'):
        raise ValueError('空间scenario需要实际主体与明确空间，纯汇总模型不能声明主体场景')
    source=scene.get('source_request','')
    if not isinstance(source,str) or len(source)>8000 or (request is not None and source!=request):
        raise ValueError('场景source_request必须保留用户原始需求，不得改写或省略')
    facilities=scene.get('facilities',[])
    if not isinstance(facilities,list) or len(facilities)>48:
        raise ValueError('场景设施须为最多48项的列表')
    from .custom_models import validate_expression,NAME
    names=set(definition.get('parameters',{}))|set(definition.get('initial_state',{}))|{'t','dt'}
    behavior_exprs=[*definition.get('rates',{}).values(),*definition.get('agents',{}).get('update',{}).values()]
    behavior_names=set().union(*(_names(expr) for expr in behavior_exprs)) if behavior_exprs else set()
    ids=set()
    for f in facilities:
        if not isinstance(f,dict) or set(f)-{'id','kind','label','x','y','width','depth','value','tone','role','behavior_parameters'}:
            raise ValueError('场景设施含未知字段')
        fid=f.get('id')
        if not isinstance(fid,str) or not NAME.fullmatch(fid) or fid in ids:raise ValueError('设施id非法或重复')
        ids.add(fid)
        if f.get('kind') not in FACILITY_KINDS:raise ValueError('不支持的场景设施类型')
        if not isinstance(f.get('label'),str) or not 1<=len(f['label'])<=32:raise ValueError('设施必须有1–32字名称')
        if f.get('role') not in ('modeled','context'):raise ValueError('设施role须明确modeled或context')
        used=set()
        for key in ('x','y','width','depth','value','tone'):
            if key in ('x','y','width','depth') and key not in f:raise ValueError('设施缺少位置/尺寸：'+key)
            if key in f:
                validate_expression(f"scenario.facilities.{fid}.{key}", f[key], names)
                used |= _names(f[key])
        links=f.get('behavior_parameters',[])
        if not isinstance(links,list) or any(not isinstance(k,str) or k not in definition.get('parameters',{}) for k in links):
            raise ValueError('设施行为绑定必须引用实际参数')
        if f['role']=='modeled' and (not links or not set(links)&used or not set(links)<=behavior_names):
            raise ValueError('设施'+fid+'缺少真实数据流：行为绑定须全部进入agents.update或rates，至少一个绑定同时进入设施位置/尺寸/状态表达式；未参与行为的绑定：'+str(sorted(set(links)-behavior_names))+'；设施表达式读取：'+str(sorted(used)))
        if f['kind'] in ('obstacle','signal') and f['role']!='modeled':
            raise ValueError('障碍物/信号灯必须影响实际计算，不能只加装饰冒充机制')
    requirements=scene.get('requirements',[])
    if not isinstance(requirements,list) or len(requirements)>32:raise ValueError('场景需求对应表须为最多32项列表')
    if request and not requirements:raise ValueError('缺少用户需求与实际实现的对应表')
    for index, item in enumerate(requirements):
        if not isinstance(item,dict) or set(item)!={'quote','model_refs','visual_refs'}:raise ValueError('场景需求必须给出quote/model_refs/visual_refs')
        if not isinstance(item['quote'],str) or not item['quote'] or item['quote'] not in source:
            raise ValueError('场景需求quote必须逐字来自用户原文')
        for field in ('model_refs','visual_refs'):
            refs=item[field]
            if not isinstance(refs,list) or not refs or len(refs)>12 or any(not isinstance(p,str) for p in refs):
                raise ValueError('场景需求必须提供真实模型和视觉引用')
            for path in refs:reference(definition,path)
        if not any(p == 'space' or p.startswith(MODEL_REFS) for p in item['model_refs']):
            raise ValueError(f'scenario.requirements[{index}].model_refs 至少要引用一个实际执行字段。'
                             '请填写具体路径，例如 agents.update.x、observables.x_mean 或 space.width')
        if not all(p == 'space' or p.startswith(VISUAL_REFS) for p in item['visual_refs']):
            raise ValueError(f'scenario.requirements[{index}].visual_refs 只能引用实际设施、主体、空间或视觉字段')
    if request:
        needed=scene_requirements(request)
        if needed['unsupported']:raise ValueError('当前受限二维DSL未实现：'+'、'.join(needed['unsupported']))
        kinds={f['kind'] for f in facilities}
        absent=set(needed['features'])-kinds
        if absent:raise ValueError('场景合同缺少用户明确要求的设施：'+'、'.join(sorted(absent)))


class SemanticMismatch(ValueError):
    """A structurally valid negative review, not a malformed response to retry."""

    def __init__(self, review):
        super().__init__('模型与用户场景尚不对应：'+'；'.join(map(str,review.get('missing') or ['缺少有效覆盖证据'])))
        self.review = review


def review_definition(request,definition,audit,execution=None,*,plan=None,deadline=None,checkpoint=None):
    """A real second model call checks semantics; structural evidence is rechecked locally."""
    import json
    import time
    from .llm_client import complete,json_object
    validate_scene(definition,request)
    from .agent.model_prompts import SCENE_REVIEW
    prompt = SCENE_REVIEW
    program=definition.get('kind')=='program'
    if program:
        from .agent.program_prompts import REVIEW
        prompt=('只输出JSON：{"matched":true或false,"missing":[],"checks":[{"quote":"逐字原文","refs":["实际路径"]}],"limitations":[]}。\n'+REVIEW)
    grid = (definition.get("agents") or {}).get("grid")
    from .scaling import ARRAY_KERNEL
    scaled = (execution or {}).get("compiled_scale", {}).get("kernel") == ARRAY_KERNEL
    runtime_contract = {
        "state_frames": ("每个保存时点的 population 是实际主体数及完整状态列，工作台使用有界视图。"
                         if scaled else "主体帧的 entities 包含实际主体 id、坐标和全量已声明的主体属性。")
    } if definition.get("agents") else {}
    program_functions={}
    if program:
        from .program_evidence import fragments,state_dependencies
        program_functions=fragments(definition)
        runtime_contract.update(
            state_frames='各人口组完整属性列、持久ID和单位；不适用不补0，显示实体从全量采样；关系端点核对完整人口',
            relation_identity='source/target采用group_id:原始持久ID，与该组frame.populations[].ids一致；不是行索引',
            input_pipeline={
                'phase':'before_solver_execution',
                'ingestion':'宿主collect_data/import先落盘原始文件与解析记录，绑定准备重新核验源文件与解析哈希',
                'solver_access':'聚合参数绑定(field/parameter)由宿主准备后通过只读parameters[parameter]传入；结构端口绑定(port/contract/columns)才通过只读inputs[port]传入。没有结构端口时inputs可以为空；两种路径都无网络或宿主文件访问',
                'prepared_parameters':[{'parameter':item['parameter'],'dataset_id':item.get('dataset_id'),
                    'field':item.get('field'),'sha256':item.get('sha256'),'data_sha256':item.get('data_sha256'),
                    'effective_value':(execution or {}).get('effective_inputs',{}).get(item['parameter']),
                    'channel':'parameters'} for item in (execution or {}).get('data_bindings',[])
                    if 'parameter' in item and 'port' not in item],
                'prepared_status':'prepared_not_yet_executed表示尚未执行此模型，不表示没有采集；运行后才标记实际交付',
                'prepared_ports':[{'port':item['port'],'dataset_id':item.get('dataset_id'),
                    'sha256':item.get('sha256'),'data_sha256':item.get('data_sha256'),'input_sha256':item.get('input_sha256'),
                    'records_used':item.get('records_used'),'usage_status':item.get('usage_status','not_verified')}
                    for item in (execution or {}).get('data_bindings',[]) if 'port' in item],
                'limits':'本阶段哈希/解析/绑定证据不证明已执行、因果消费、校准或原来源准确性'},
            program_state_dependencies=state_dependencies(definition),
            program_clock={'observation':'每个宏步的精确末时点，含0初态','dt':(execution or {}).get('dt'),
                           'interventions':definition['solver']['intervention_clock'],
                           'checkpoint':'完整JSON状态、PCG64随机流、时钟及干预游标；恢复不初始化'},
            environment='专用隔离Python/NumPy/SciPy/NetworkX；无网络、无宿主数据或密钥；数学有效性仍需本轮实际验证')
    all_frames = bool((execution or {}).get("scale_requested", {}).get("all_frames"))
    runtime_contract["frame_archive"] = {
        "capture_state": True, "include_initial": True, "include_final": True,
        "all_steps_required": all_frames,
        "retention": ("每次实际状态更新后的完整帧均保存，不能降采样时点或主体；超预算拒绝，不能缩小需求"
                      if all_frames else "按已披露预算保存完整状态的部分时点；保存时点可从实际manifest核对"),
        "verification": ("归档前强制完整帧数等于实际观测数（包括初态）；不满足则不能发布成功运行"
                         if all_frames else "实际帧数、采样间隔和保留范围写入manifest"),
        "evidence_phase": "这里是实际执行器合同；具体帧、帧数和下载包在运行完成后核验，不冒充已执行结果",
    }
    if definition.get('kind') == 'program':
        runtime_contract['spatial_3d']={'axes':'bounds=[xmin,ymin,xmax,ymax]; vertical_bounds=[zmin,zmax]; x/y/z同单位，z为脚底/支撑面高度',
            'geometry':'space.terrain实际高度网格、floors实际标高/矩形楼板/holes、connectors实际三维中心线和宽度；全部来自frame，不由前端补造',
            'population':'三维空间组须输出完整x/y/z；可选floor_id引用真实楼层/地形/连接，核对支撑高度与连接路径宽度',
            'consumers':'Three.js地形网格/分层楼板/连接、人动作和高度插值；全量分层人数及真实三维轨迹报告',
            'verification':'几何输出不自动证明地形/局部交互/碰撞算法已实现；仍核advance真实消费和独立数值验算'}
        runtime_contract['frame_archive'].update(
            definition_state_every=definition.get('state_every'),
            effective_interval=1 if all_frames else definition.get('state_every', 'platform_budgeted'),
            scheduling='平台调度归档；frame始终返回实际完整状态，不能靠自造skip字段控制保存；观测和动态仍每宏步计算')
        if definition.get('decision_policy') is not None:
            runtime_contract['external_decisions']={
                'phase':'host_calls_at_actual_macrostep_boundary',
                'request_function':'source.decision_requests (pure; runtime entry independent of advance)',
                'delivery':'advance的第7参数decisions，批次ID映射到真实actions；源码不得在沙箱联网',
                'frame_order':'step0为initialize后/首次响应前；每宏步末先存帧，再取得下宏步新响应，新动作在下个advance消费；不能把意图或预填数组称作已接受响应',
                'policy':definition['decision_policy'],
                'verification':'运行后manifest.actor_decisions给实际调用、动作、状态/响应摘要及明确历史重放；编译前尚未调用不是缺失实现',
                'causal_use':'检查advance真实消费动作并影响state，原需求数值验收和输入扰动仍须独立验证'}
    if grid:
        runtime_contract["grid"] = {
            "boundary": {'periodic':'矩形周期边界，行列分别按 rows 和 columns 环绕',
                         'reflecting':'格面反射边界，域外一格的状态取边缘本格（含边格的镜像）',
                         'absorbing':'域外虚格取boundary_values中的固定状态，未声明字段为0；pick_max只从真实邻格选择'}[grid.get('boundary','periodic')],
            "identity": "每格一号，行优先从0开始，x=col+0.5，y=row+0.5",
            "topology": f"每格读取{grid['degree']}个邻接偏移，域外按boundary替代；周期模式排除本格，反射模式的镜像可指向本格",
            "history": "时点t求t+1时，lag=0从t读，lag=k从t-k读。历史不足用最早已存状态",
            "sampling": ("每次保存完整逐格状态列，两个坐标由网格尺寸和行优先编号派生。"
                         if scaled else "保存的 entities 含两个坐标和各角色状态字段。"),
        }
    evidence={**definition,'execution':execution or {},'runtime_contract':runtime_contract}
    empty_execution_fields = {'execution.data_bindings', 'execution.parameters', 'execution.interventions'}
    paths=[]
    def collect(node,path=''):
        if node in (None,'') or path not in empty_execution_fields and node in ({},[]):return
        if path:paths.append(path)
        if isinstance(node,dict):
            for key,value in node.items():
                if key not in ('description','name','mechanisms','assumptions','limitations','source_request','requirements','title','setting'):
                    collect(value,(path+'.' if path else '')+key)
        elif isinstance(node,list):
            for item in node:
                if isinstance(item,dict) and isinstance(item.get('id'),str):collect(item,path+'.'+item['id'])
    collect(evidence)
    paths.extend('source.'+name for name in program_functions)
    # Set-derived data-flow member ordering varies with the worker's hash seed.
    # Evidence order is not model semantics; it must not trigger another review.
    paths=sorted(set(paths))
    prompt+='\nrefs必须从提供的真实可用路径中选择，不能写顶层type或虚构字段。检查排除的机制时引用实际演化源码/方程，不能仅引用limitations。不要为了引用错误改变模型。'
    if (execution or {}).get('research'):
        prompt+='\nexecution.research是实际已冻结且绑定同原文的研究阶段合同。本次仅审核模型基线；校准、数值诊断、独立留出和研究Word由同意图的后续MS实际执行。核对参数网格、目标观测单位和时钟、输入与机制是否支持后续研究；不要要求基线已取得未来评分，也不能把尚未执行的校准声称为通过。校准/验证条款可引用execution.research（已列为可用路径）。'
        paths=sorted(set([*paths,'execution.research']))
    if plan:
        prompt+='\n将实际方程与 approved_plan.rule_refs 对照，验证量必须读取被规则推进的状态。标题、常数、仅计时和直接抄目标均不能证明所需机制。'
        if not program:prompt+='\nagents.measures 从同一观测时点的主体状态和坐标计算派生值。observables 可聚合这些值。检查条件计数、分组及状态帧是否一致。'
        prompt+='\nchecks 须逐条引用 approved_plan.coverage 内完整的 quote，一条对应一条。逐项核对真实数据、初态、主体行为、更新顺序、时点及检验值。'
        prompt+='\n报告属于运行后平台交付。execution.delivery.report_tool 是真实报告入口，可作为报告交付核对依据。不要要求方程生成文件或编造DSL字段。'
        prompt+='\nexecution.delivery.replay包含真实状态/归档API、工作台URL和恢复控制器。按同一run_id的实际帧和观测回放，不需要模型源码实现HTTP或界面。科研回放使用research_finalize返回的真实所选参数结果，报告使用research_report；基线仍是中间态，不能声称后续已经执行。'
        prompt+='\n完整状态归档核对 runtime_contract.frame_archive；运行包核对 execution.delivery.bundle_url/bundle_contents。这些是平台实际合同，运行后仍要验收，不要求DSL方程实现文件导出。'
        prompt+='\napproved_plan的state_frames.*是运行后证据路径；本阶段用runtime_contract核对支持性，不能因还没有运行实例就判定归档能力不存在。'
        prompt+='\n如果原文规定跳过检索，引用 execution.literature_review.mode 和 execution.literature_review.performed。空的 data_bindings 只证明未绑定输入数据，不能证明是否检索过论文。'
    messages=[{'role':'system','content':prompt},{'role':'user','content':json.dumps({'request':request,'definition':definition,'execution':execution or {},'approved_plan':plan,'runtime_contract':runtime_contract,'available_refs':paths,
        **({'functions':program_functions} if program else {})},ensure_ascii=False,sort_keys=True)}]
    def validate(result):
        if not isinstance(result.get('matched'),bool) or not isinstance(result.get('missing'),list) or not isinstance(result.get('checks'),list):
            raise ValueError('场景语义审核未返回有效结构')
        for check in result['checks']:
            if not isinstance(check,dict) or not isinstance(check.get('quote'),str) or not check['quote'] or check['quote'] not in request:
                raise ValueError('语义审核证据不是用户原文')
            if not isinstance(check.get('refs'),list) or not check['refs']:raise ValueError('语义审核缺少实际字段证据')
            for path in check['refs']:
                if not isinstance(path,str) or path not in paths:raise ValueError('语义审核引用不在真实可用路径中：'+str(path))
                reference(evidence,path,allow_empty=path in empty_execution_fields)
        if result['matched'] and plan:
            from .agent.model_design import _whole_request
            _whole_request(result['checks'], request)
        return result

    def feedback(error):
        return ('审核回执格式或引用错误：'+error+'。保持对同一原模型的独立判断，只修正回执引用；'
                '若实际机制不满足则仍须matched=false并列出缺失项。')

    if checkpoint is not None:
        result = checkpoint.call('semantic_review', messages, validate, complete,
                                 purpose='scene-semantic-review', thinking=True, feedback=feedback)
    else:
        for attempt in range(2):
            timeout=min(180,deadline-time.monotonic()) if deadline is not None else 180
            if timeout<2:raise TimeoutError('实际方程复核时间已用完，未保存模型')
            raw=complete(messages,timeout=timeout,purpose='scene-semantic-review',audit=audit,thinking=True)
            try:
                result=validate(json_object(raw))
                break
            except (ValueError,SyntaxError) as exc:
                if audit:audit[-1]['review_validation_error']=str(exc)
                if attempt:raise
                messages+=[{'role':'assistant','content':raw},{'role':'user','content':feedback(str(exc))}]
    if not result['matched'] or result['missing'] or not result['checks']:
        raise SemanticMismatch(result)
    return {**result,'method':'真实LLM语义复核 + 本地引用/数据流校验','scientific_validation':False}


def check_saved_scene(request,payload):
    """Check the saved output, not an LLM's promise that something was rendered."""
    from .run_store import get_store
    record=get_store().load(payload['run_id'],exclude=('checkpoint.json',))
    frames=record.get('state_frames') or []
    first=frames[0] if frames else {}
    needs=request.get('scene_requirements') or scene_requirements(request.get('original_text',''))
    issues=[]
    expected=request.get('model_ids') or []
    if expected and request.get('kind') in ('run','resume','compare','ensemble','sweep') and record['model_id'] not in expected:
        issues.append('实际模型'+record['model_id']+'不在用户指定的模型中：'+'、'.join(expected))
    from .stateframe import has_spatial_state, population_size
    if needs['spatial'] and not has_spatial_state(first):
        issues.append('用户要求具体空间场景，但实际运行仅有汇总状态，不能展示虚构主体')
    facilities=first.get('facilities',[])
    kinds={f.get('kind',f.get('type')) for f in facilities}
    if 'road_network' in kinds:kinds.add('road')
    missing=set(needs['features'])-kinds
    if missing:issues.append('实际状态未导出所需设施：'+'、'.join(sorted(missing)))
    if 'road' in needs['features'] and any(f.get('type')=='road' and f.get('length') for f in facilities):
        issues.append('实际状态是单一环形车道，不能替代用户要求的交叉路口/多车道')
    count=request.get('parameters',{}).get('n')
    entities=first.get('entities',[])
    population=first.get('population')
    wanted={'行人':{'pedestrian','agent'},'居民':{'resident','agent'}}.get(request.get('agent_count_label'))
    actual_count = (population['count'] if not wanted or population.get('type') in wanted else 0) if population else (
        len([entity for entity in entities if entity.get('type') in wanted]) if wanted else len(entities))
    if count is not None and (entities or population) and actual_count!=count:
        issues.append(f'请求主体数{count}与首帧实际对应主体数{actual_count}不符')
    definition=record.get('manifest',{}).get('model_definition') or {}
    scene=definition.get('scenario')
    if scene:validate_scene(definition)
    review=record.get('manifest',{}).get('scenario_review')
    lattice=first.get('lattice') or {}
    return {'status':'mismatch' if issues else 'semantic_reviewed' if review else 'state_checked',
            'issues':issues,'required_facilities':needs['features'],'actual_facilities':sorted(str(k) for k in kinds),
            'actual_entities':population_size(first),
            **({'lattice_cells':lattice.get('source_width',lattice['width'])*lattice.get('source_height',lattice['height'])} if lattice else {}),
            'title':scene.get('title') if scene else None,
            'coverage':scene.get('requirements',[]) if scene else [],'scientific_validation':False,
            'method':'实际归档字段与设施核对'+('；含真实LLM语义复核' if review else '')}
