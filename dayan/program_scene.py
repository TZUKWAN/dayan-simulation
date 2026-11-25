"""Program scene declarations point to real code and matching complete frames."""
import math

from .program_evidence import reachable


def validate_scene(definition, request=None):
    from .scene_contract import FACILITY_KINDS, reference, scene_requirements
    scene=definition.get('scenario')
    if scene is None:
        if request and scene_requirements(request)['spatial']:
            raise ValueError('空间程序须提供scenario及实际场景帧，不能仅返回汇总指标')
        return
    if not isinstance(scene,dict) or set(scene)-{'title','setting','agent_label','source_request','facilities','requirements'}:
        raise ValueError('程序scenario含未知字段')
    for key in ('title','setting','agent_label','source_request'):
        if not isinstance(scene.get(key),str) or not scene[key].strip():raise ValueError('程序场景缺少'+key)
    if request is not None and scene['source_request']!=request:raise ValueError('程序场景必须保留完整用户原文')
    forward=reachable(definition,'advance')
    render=reachable(definition,'frame')
    facilities=scene.get('facilities')
    if not isinstance(facilities,list):raise ValueError('程序场景须明确facilities列表')
    seen=set()
    for item in facilities:
        if (not isinstance(item,dict) or set(item)!={'id','kind','label','role','model_refs','frame_refs'}
                or not isinstance(item['id'],str) or not item['id'] or item['id'] in seen
                or item['kind'] not in FACILITY_KINDS or not isinstance(item['label'],str) or not item['label']
                or item['role'] not in ('modeled','context')):raise ValueError('程序设施合同不合法')
        seen.add(item['id'])
        for key in ('model_refs','frame_refs'):
            refs=item[key]
            if not isinstance(refs,list) or not refs or any(not isinstance(p,str) for p in refs):
                raise ValueError('程序设施须给真实计算与帧函数引用')
            for path in refs:reference(definition,path)
        if not any(p.startswith('source.') and p[7:] in render for p in item['frame_refs']):
            raise ValueError('设施未引用实际帧导出函数')
        if item['role']=='modeled' and not any(p.startswith('source.') and p[7:] in forward for p in item['model_refs']):
            raise ValueError('设施未引用真实advance可达行为函数')
        if item['kind'] in ('obstacle','signal') and item['role']!='modeled':
            raise ValueError('障碍与信号必须参与实际模型，不能只绘制装饰')
    requirements=scene.get('requirements')
    if not isinstance(requirements,list) or not requirements:raise ValueError('程序场景缺少原文对应表')
    for row in requirements:
        if (not isinstance(row,dict) or set(row)!={'quote','model_refs','visual_refs'}
                or not isinstance(row['quote'],str) or not row['quote'] or row['quote'] not in scene['source_request']):
            raise ValueError('程序场景引用须逐字来自原文')
        for key in ('model_refs','visual_refs'):
            refs=row[key]
            if not isinstance(refs,list) or not refs or any(not isinstance(p,str) for p in refs):
                raise ValueError('程序场景缺少实际证据引用')
            for path in refs:reference(definition,path)
        if not any(p.startswith('source.') for p in row['model_refs']):raise ValueError('程序场景须引用实际计算函数')
        if not any(p.startswith('source.') and p[7:] in render for p in row['visual_refs']):
            raise ValueError('程序场景须引用实际frame可达函数')
    if request:
        needed=scene_requirements(request)
        missing=set(needed['features'])-{f['kind'] for f in facilities}
        if missing:raise ValueError('程序场景缺少原文设施：'+'、'.join(sorted(missing)))


def validate_frame(frame, definition):
    specs={f['id']:f for f in (definition.get('scenario') or {}).get('facilities',[])}
    actual=frame.get('facilities',[])
    if not isinstance(actual,list):raise ValueError('实际设施须为列表')
    seen=set()
    for facility in actual:
        if not isinstance(facility,dict) or not isinstance(facility.get('id'),str) or facility['id'] in seen:
            raise ValueError('实际设施缺少唯一ID')
        ident=facility['id']
        seen.add(ident)
        if ident not in specs or facility.get('type',facility.get('kind'))!=specs[ident]['kind']:
            raise ValueError('实际设施偏离已审查场景：'+ident)
        for key in ('x','y','width','depth'):
            value=facility.get(key)
            if type(value) not in (float,int) or not math.isfinite(value) or key in ('width','depth') and value<=0:
                raise ValueError('实际设施位置和尺寸不合法：'+ident+'.'+key)
        if 'z' in facility and (type(facility['z']) not in (float,int) or not math.isfinite(facility['z'])):
            raise ValueError('设施z须为实际有限高度')
    if seen!=specs.keys():raise ValueError('实际帧未导出全部场景设施')
    if definition.get('scenario') and not frame.get('space'):
        raise ValueError('实际场景缺少空间坐标与单位')
