"""Actual 3D frame geometry; x/y footprint and z elevation use one unit."""
import math
import numpy as np


def finite(value):return type(value) in (int,float) and math.isfinite(value)


def rectangle(value):
    return isinstance(value,list) and len(value)==4 and all(finite(v) for v in value) and value[0]<value[2] and value[1]<value[3]


def terrain_height(terrain,x,y):
    ox,oy=terrain['origin'];dx,dy=terrain['spacing'];h=terrain['heights']
    u=(x-ox)/dx;v=(y-oy)/dy
    if not 0<=u<=len(h[0])-1 or not 0<=v<=len(h)-1:raise ValueError('地形坐标在真实高度网格之外')
    i=min(int(u),len(h[0])-2);j=min(int(v),len(h)-2);a=u-i;b=v-j
    return (1-a)*(1-b)*h[j][i]+a*(1-b)*h[j][i+1]+(1-a)*b*h[j+1][i]+a*b*h[j+1][i+1]


def validate_space(space):
    if not isinstance(space,dict) or set(space)-{'bounds','unit','time_unit','vertical_bounds','terrain','floors','connectors'}:
        raise ValueError('程序空间合同不合法')
    if space.get('bounds') is not None and not rectangle(space['bounds']):raise ValueError('程序空间水平范围不合法')
    if not any(space.get(k) for k in ('terrain','floors','connectors')) and 'vertical_bounds' not in space:return
    if not rectangle(space.get('bounds')) or not isinstance(space.get('unit'),str) or not space['unit']:
        raise ValueError('三维场景须给水平bounds及统一坐标单位')
    vertical=space.get('vertical_bounds')
    if not isinstance(vertical,list) or len(vertical)!=2 or not all(finite(v) for v in vertical) or vertical[0]>=vertical[1]:
        raise ValueError('三维场景须给有限递增vertical_bounds=[zmin,zmax]')
    ids=set();supports={}
    def identify(item,allowed):
        if not isinstance(item,dict) or set(item)-allowed or not isinstance(item.get('id'),str) or not item['id'] or item['id'] in ids:
            raise ValueError('三维几何须有唯一ID且只含公开合同字段')
        ids.add(item['id'])
    terrain=space.get('terrain')
    if terrain:
        identify(terrain,{'id','origin','spacing','heights','label'})
        for key in ('origin','spacing'):
            if not isinstance(terrain.get(key),list) or len(terrain[key])!=2 or not all(finite(v) for v in terrain[key]):raise ValueError('地形origin/spacing须为二维有限向量')
        if min(terrain['spacing'])<=0:raise ValueError('地形spacing须为正')
        h=terrain.get('heights')
        if (not isinstance(h,list) or len(h)<2 or not isinstance(h[0],list) or len(h[0])<2 or any(not isinstance(row,list) or len(row)!=len(h[0]) or any(not finite(v) or not vertical[0]<=v<=vertical[1] for v in row) for row in h)):
            raise ValueError('地形heights须为至少2×2完整有限高度网格，位于vertical_bounds内')
        supports[terrain['id']]=terrain
    floors=space.get('floors',[])
    if not isinstance(floors,list):raise ValueError('floors须为列表')
    for floor in floors:
        identify(floor,{'id','label','elevation','bounds','holes'})
        if not finite(floor.get('elevation')) or not vertical[0]<=floor['elevation']<=vertical[1] or not rectangle(floor.get('bounds')):
            raise ValueError('楼层须给真实elevation和水平bounds')
        if not isinstance(floor.get('holes',[]),list) or any(not rectangle(hole) or hole[0]<floor['bounds'][0] or hole[1]<floor['bounds'][1] or hole[2]>floor['bounds'][2] or hole[3]>floor['bounds'][3] for hole in floor.get('holes',[])):
            raise ValueError('楼层holes须为楼板范围内的实际矩形开口')
        supports[floor['id']]=floor
    connectors=space.get('connectors',[])
    if not isinstance(connectors,list):raise ValueError('connectors须为列表')
    for connection in connectors:
        identify(connection,{'id','label','kind','from','to','polyline','width'})
        if connection.get('kind') not in ('ramp','stairs','passage','lift') or connection.get('from') not in supports or connection.get('to') not in supports:
            raise ValueError('通行连接须为ramp/stairs/passage/lift并引用实际楼层或地形')
        points=connection.get('polyline')
        if not isinstance(points,list) or len(points)<2 or any(not isinstance(p,list) or len(p)!=3 or not all(finite(v) for v in p) or not vertical[0]<=p[2]<=vertical[1] for p in points):raise ValueError('连接polyline须为实际三维路径')
        if not finite(connection.get('width')) or connection['width']<=0:raise ValueError('连接width须为正')
        for point,key in ((points[0],'from'),(points[-1],'to')):
            support=supports[connection[key]]
            z=support['elevation'] if 'elevation' in support else terrain_height(support,*point[:2])
            if not math.isclose(z,point[2],abs_tol=1e-7,rel_tol=0):raise ValueError('连接端点高度与实际楼层/地形不一致')


def validate_population(frame):
    from .population_groups import decode_attribute
    space=frame.get('space') or {}
    if 'vertical_bounds' not in space:return
    lo,hi=space['vertical_bounds'];unit=space['unit']
    supports={f['id']:f for f in space.get('floors',[])}
    if space.get('terrain'):supports[space['terrain']['id']]=space['terrain']
    connectors={c['id']:c for c in space.get('connectors',[])}
    for group in frame.get('population',{}).get('groups',[]):
        columns=group['columns']
        if not {'x','y'}<=set(columns):continue
        if 'z' not in columns or any(group['units'].get(k)!=unit or columns[k]['kind']!='numeric' for k in ('x','y','z')):raise ValueError('三维空间人口须实际输出同坐标单位的x/y/z完整数值列')
        x,y,z=[decode_attribute(columns[k],group['count']) for k in ('x','y','z')]
        if np.any(z<lo) or np.any(z>hi):raise ValueError('完整人口实际z超出三维空间范围')
        if 'floor_id' not in columns:continue
        locations=decode_attribute(columns['floor_id'],group['count'])
        for ident in set(locations.tolist()):
            mask=locations==ident
            if ident in supports:
                support=supports[ident]
                heights=np.full(int(mask.sum()),support['elevation']) if 'elevation' in support else np.array([terrain_height(support,float(a),float(b)) for a,b in zip(x[mask],y[mask])])
                if not np.allclose(z[mask],heights,rtol=0,atol=1e-7):raise ValueError('人口floor_id与真实支撑面高度不一致')
            elif ident in connectors:
                route=np.array(connectors[ident]['polyline'],dtype=float);positions=np.column_stack((x[mask],y[mask],z[mask]));distance=np.full(len(positions),np.inf)
                for a,b in zip(route[:-1],route[1:]):
                    delta=b-a;square=float(delta@delta)
                    if not square:continue
                    t=np.clip((positions-a)@delta/square,0,1)
                    distance=np.minimum(distance,np.linalg.norm(positions-a-t[:,None]*delta,axis=1))
                if np.any(distance>connectors[ident]['width']/2+1e-7):raise ValueError('连接上的人口坐标偏离实际通行路径宽度')
            else:raise ValueError('人口floor_id引用不存在的楼层/地形/连接')
