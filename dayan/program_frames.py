"""Convert decoded program output into validated, complete common state frames."""
from copy import deepcopy
import math

from .population_groups import encode_groups, group_ids, sample_entities
from .stateframe import validate_state_frame
from .solvers.codec import encode


def validate_relation_time(edge, time):
    """relations is the effective graph at sim_t, with optional half-open validity."""
    start, end = edge.get('valid_from', -math.inf), edge.get('valid_until', math.inf)
    for name in ('valid_from', 'valid_until'):
        if name in edge and (type(edge[name]) not in (int, float) or not math.isfinite(edge[name])):
            raise ValueError('关系有效区间须为有限时刻；无界端点省略字段')
    if start >= end or not start <= time < end:
        raise ValueError('relations只能含sim_t当时有效的边，区间为[valid_from, valid_until)；历史/未来关系另存state')


def state_frame(raw, observations, definition, expected, step, time):
    if not isinstance(raw,dict):raise ValueError('程序frame须为实际状态对象')
    if set(raw)-{'sim_t','populations','space','relations','facilities','stocks','fields','presentation'}:
        raise ValueError('程序frame含未知字段；完整个体用populations声明，显示采样由平台生成')
    if raw.get('sim_t',time)!=time:raise ValueError('程序状态帧与实际时钟不一致')
    frame={key:encode(value) for key,value in raw.items() if key not in ('populations','sim_t')}
    declared={group['id']:group for group in definition['populations']}
    if declared:
        population=encode_groups(raw.get('populations'))
        if {g['id'] for g in population['groups']}!=set(declared):raise ValueError('实际人口组与已声明方案不一致')
        counts={group['id']:group['count'] for group in expected['populations']}
        for group in population['groups']:
            spec=declared[group['id']]
            if group['type']!=spec['type'] or set(group['columns'])!=set(spec['attributes']):
                raise ValueError('实际人口类型或属性偏离声明：'+group['id'])
            if (step==0 or not spec['dynamic']) and group['count']!=counts[group['id']]:
                raise ValueError('实际完整人口数量偏离原定规模：'+group['id'])
            if spec['dynamic'] and next(g for g in raw['populations'] if g['id']==group['id']).get('ids') is None:
                raise ValueError('动态人口组必须显式返回持久ID，不能每帧重新编号')
            for name,field in spec['attributes'].items():
                if group['columns'][name]['kind']!=field['kind'] or group['units'][name]!=field['unit']:
                    raise ValueError('实际人口属性类型/单位偏离声明：'+group['id']+'.'+name)
            group['label']=spec['label']
        frame['population']=population
        frame['entities']=sample_entities(population)
    else:
        if raw.get('populations'):raise ValueError('未声明的个体人口不能以显示输出加入模型')
        frame['entities']=[]
    space=frame.get('space')
    if space is not None:
        from .spatial_contract import validate_space,validate_population
        validate_space(space)
        validate_population(frame)
        if space.get('time_unit',definition['time_unit'])!=definition['time_unit']:raise ValueError('场景时间单位偏离求解单位')
        space['time_unit']=definition['time_unit']
    relations=frame.get('relations',[])
    if not isinstance(relations,list):raise ValueError('程序relations须为实际关系边列表')
    ids={g['id']:g['ids'] for g in frame.get('population',{}).get('groups',[])}
    explicit={g['id']:{str(i) for i in group_ids(g)} for g in frame.get('population',{}).get('groups',[])
              if g['ids']['kind']=='explicit'}
    def exists(ident):
        if not isinstance(ident,str) or ':' not in ident:return False
        key,local=ident.split(':',1)
        spec=ids.get(key)
        if spec is None:return False
        if spec['kind']=='explicit':return local in explicit[key]
        try:value=int(local)
        except ValueError:return False
        return str(value)==local and spec['start']<=value<spec['start']+spec['count']
    seen=set()
    for edge in relations:
        if (not isinstance(edge,dict) or not isinstance(edge.get('id'),str) or not edge['id']
                or edge['id'] in seen or not exists(edge.get('source')) or not exists(edge.get('target'))):
            raise ValueError('关系边缺少唯一ID或引用不存在的完整人口主体')
        seen.add(edge['id'])
        validate_relation_time(edge, time)
    # Metrics are the same actually computed observation vector, not an
    # independently generated frame summary which might contradict the report.
    frame['aggregates']=deepcopy(observations)
    from .program_scene import validate_frame
    validate_frame(frame,definition)
    for facility in frame.get('facilities',[]):
        spec=next(item for item in definition['scenario']['facilities'] if item['id']==facility['id'])
        facility.update(type='model_facility',kind=spec['kind'],role=spec['role'],label=spec['label'])
    return validate_state_frame(frame,time,exact_time=True)
