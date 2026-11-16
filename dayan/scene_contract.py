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


def scene_requirements(text):
    text=str(text or '')
    # A request to omit an element is not a requirement to fabricate that element.
    positive=re.sub(r'(?:不要|无需|不需要|不考虑|不用)[^，。；\n]{0,24}', '', text)
    features=[key for key,pattern in SCENE_FEATURES.items() if re.search(pattern,positive)]
    return {'features':features,
            'spatial':bool(features or re.search(r'场景|布局|地形|地图|建筑物|校区|车站|商场|街区|操场|医院|学校|校园|工厂|地铁站|博物馆|体育场|公园|超市',positive)),
            'unsupported':[label for pattern,label in [
                (r'多层|跨楼层|三维碰撞|三维物理|楼梯疏散','多层/三维实体运动'),
                (r'刚体碰撞|流体力学|烟气扩散|烟雾扩散','物理碰撞/流体或烟气场')]
                if re.search(pattern,positive)]}


def _names(expr):
    return {n.id for n in ast.walk(ast.parse(str(expr),mode='eval')) if isinstance(n,ast.Name)}


def reference(definition,path):
    """Resolve only real definition paths; facility IDs are stable, not array offsets."""
    node=definition
    for part in str(path).split('.'):
        if isinstance(node,dict) and part in node:node=node[part]
        elif isinstance(node,list):
            node=next((item for item in node if isinstance(item,dict) and item.get('id')==part),None)
            if node is None:raise ValueError('场景证据引用不存在：'+str(path))
        else:raise ValueError('场景证据引用不存在：'+str(path))
    if node in (None,'',{},[]):raise ValueError('场景证据引用为空：'+str(path))
    return node


def validate_scene(definition,request=None):
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
    from .custom_models import Expression,NAME
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
                Expression(f[key],names);used|=_names(f[key])
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
    for item in requirements:
        if not isinstance(item,dict) or set(item)!={'quote','model_refs','visual_refs'}:raise ValueError('场景需求必须给出quote/model_refs/visual_refs')
        if not isinstance(item['quote'],str) or not item['quote'] or item['quote'] not in source:
            raise ValueError('场景需求quote必须逐字来自用户原文')
        for field in ('model_refs','visual_refs'):
            refs=item[field]
            if not isinstance(refs,list) or not refs or len(refs)>12 or any(not isinstance(p,str) for p in refs):
                raise ValueError('场景需求必须提供真实模型和视觉引用')
            for path in refs:reference(definition,path)
        if not any(p=='space' or p.startswith(('agents.','rates.','space.','parameters.')) for p in item['model_refs']):
            raise ValueError('模型对应关系不能只引用标题或描述')
        if not all(p=='space' or p.startswith(('scenario.facilities.','agents.','space.','visualization.')) for p in item['visual_refs']):
            raise ValueError('视觉对应关系必须引用实际设施/主体/空间/视觉字段')
    if request:
        needed=scene_requirements(request)
        if needed['unsupported']:raise ValueError('当前受限二维DSL未实现：'+'、'.join(needed['unsupported']))
        kinds={f['kind'] for f in facilities}
        absent=set(needed['features'])-kinds
        if absent:raise ValueError('场景合同缺少用户明确要求的设施：'+'、'.join(sorted(absent)))


def review_definition(request,definition,audit,execution=None):
    """A real second model call checks semantics; structural evidence is rechecked locally."""
    import json
    from .llm_client import complete,json_object
    validate_scene(definition,request)
    prompt='''复核用户原文与实际数学/主体DSL是否对应。只输出JSON：
{"matched":true或false,"missing":[缺失/冲突项],"checks":[{"quote":"用户原文逐字短语","refs":["实际定义字段路径"]}],"limitations":[局限]}。
逐项检查主体数量/角色、场所/设施/布局、行为、相互作用、随机性、单位、颜色语义和用户指定约束。
execution.prior存在时还要对比原模型与本次修改，原始主体/场所/设施/机制不能丢失，只允许用户明确要求的变化。不能把新写的无关模型当成“沿用”。
路径直接以agents/parameters/rates/space/scenario等开头，不加definition前缀；设施路径为scenario.facilities.设施id，不使用数组下标。平台执行约束可引用execution.ticks、execution.dt、execution.seed等真实执行选项。
不能因标题、mechanisms列表或漂亮外观就判定满足；必须阅读实际表达式。设施被画出但未影响用户要求的行为，应判定missing。
如用户要求的具体场景被抽象汇总模型、随机游走或无关机制替代，matched=false。refs只能引用实际DSL字段路径；不能引用description/name/mechanisms作为实现证据。
不要要求平台不支持的任意代码，不把数学模型当成现实校准；模型简化与用户明确要求有冲突时不能判定满足。'''
    raw=complete([{'role':'system','content':prompt},{'role':'user','content':json.dumps({'request':request,'definition':definition,'execution':execution or {}},ensure_ascii=False)}],
                 max_tokens=16384,timeout=150,purpose='scene-semantic-review',audit=audit,thinking=True)
    result=json_object(raw)
    if not isinstance(result.get('matched'),bool) or not isinstance(result.get('missing'),list) or not isinstance(result.get('checks'),list):
        raise ValueError('场景语义审核未返回有效结构')
    for check in result['checks']:
        if not isinstance(check,dict) or not isinstance(check.get('quote'),str) or not check['quote'] or check['quote'] not in request:
            raise ValueError('语义审核证据不是用户原文')
        if not isinstance(check.get('refs'),list) or not check['refs']:raise ValueError('语义审核缺少实际字段证据')
        for path in check['refs']:
            if not isinstance(path,str) or path.split('.')[0] in ('description','name','mechanisms','assumptions','limitations'):
                raise ValueError('语义审核用文字声明冒充实现证据')
            reference({**definition,'execution':execution or {}},path)
    if not result['matched'] or result['missing'] or not result['checks']:
        raise ValueError('模型与用户场景尚不对应：'+'；'.join(map(str,result.get('missing') or ['缺少有效覆盖证据'])))
    return {**result,'method':'真实LLM语义复核 + 本地引用/数据流校验','scientific_validation':False}


def check_saved_scene(request,payload):
    """Check the saved output, not an LLM's promise that something was rendered."""
    from .run_store import get_store
    record=get_store().load(payload['run_id'])
    frames=record.get('state_frames') or []
    first=frames[0] if frames else {}
    needs=request.get('scene_requirements') or scene_requirements(request.get('original_text',''))
    issues=[]
    expected=request.get('model_ids') or []
    if expected and request.get('kind') in ('run','resume','compare','ensemble','sweep') and record['model_id'] not in expected:
        issues.append('实际模型'+record['model_id']+'不在用户指定的模型中：'+'、'.join(expected))
    if needs['spatial'] and not first.get('entities'):
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
    wanted={'行人':{'pedestrian','agent'},'居民':{'resident','agent'}}.get(request.get('agent_count_label'))
    actual_count=len([e for e in entities if e.get('type') in wanted]) if wanted else len(entities)
    if count is not None and entities and actual_count!=count:
        issues.append(f'请求主体数{count}与首帧实际对应主体数{actual_count}不符')
    definition=record.get('manifest',{}).get('model_definition') or {}
    scene=definition.get('scenario')
    if scene:validate_scene(definition)
    review=record.get('manifest',{}).get('scenario_review')
    return {'status':'mismatch' if issues else 'semantic_reviewed' if review else 'state_checked',
            'issues':issues,'required_facilities':needs['features'],'actual_facilities':sorted(str(k) for k in kinds),
            'actual_entities':len(first.get('entities',[])),'title':scene.get('title') if scene else None,
            'coverage':scene.get('requirements',[]) if scene else [],'scientific_validation':False,
            'method':'实际归档字段与设施核对'+('；含真实LLM语义复核' if review else '')}
