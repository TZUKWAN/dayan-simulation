"""Preserve GeoJSON features and check syntax without inventing a projection.

RFC 7946 geometry structure; CRS/axis declarations are not proof of physical
accuracy or polygon topology. No GIS code from a dataset is evaluated.
"""
from copy import deepcopy
import math


def geometry_contract(value):
    if not isinstance(value, dict) or set(value) != {'crs', 'axes', 'units', 'coordinate_evidence', 'allow_null'}:
        raise ValueError('geometry合同须明确crs/axes/units/coordinate_evidence/allow_null')
    if (not isinstance(value['crs'], str) or not value['crs'].strip()
            or not isinstance(value['coordinate_evidence'], str) or not value['coordinate_evidence'].strip()):
        raise ValueError('几何坐标系及来源依据须明确，不能猜测单位')
    axes, units = value['axes'], value['units']
    if (not isinstance(axes,list) or not isinstance(units,list) or len(axes)!=len(units)
            or len(axes)<2 or any(not isinstance(x,str) or not x.strip() for x in axes+units)
            or len(set(axes))!=len(axes) or type(value['allow_null']) is not bool):
        raise ValueError('几何轴名称/单位/缺失规则不完整')
    if value['crs'] in ('OGC:CRS84', 'EPSG:4326') and (
            axes[:2]!=['longitude','latitude'] or units[:2]!=['degree','degree']):
        raise ValueError('GeoJSON的WGS84前两轴必须按经度/纬度、角度声明，不能当作米')
    return deepcopy(value)


def features_summary(features, spec):
    """Validate actual features, retaining nulls, holes, extra properties and IDs."""
    types, dimensions = {}, set()
    position_count = null_count = 0
    def position(value):
        nonlocal position_count
        if (not isinstance(value,list) or not 2<=len(value)<=len(spec['axes'])
                or any(type(x) not in (int,float) or not math.isfinite(x) for x in value)):
            raise ValueError('几何坐标须为有限数值，且所有坐标维度须有明确轴/单位')
        if spec['crs'] in ('OGC:CRS84','EPSG:4326') and not -90<=value[1]<=90:
            raise ValueError('纬度超出范围，可能混用了坐标轴或坐标系')
        dimensions.add(len(value))
        position_count += 1
    def line(value, ring=False):
        if not isinstance(value,list) or len(value)<(4 if ring else 2):
            raise ValueError('线段/闭合环缺少足够坐标')
        for point in value:
            position(point)
        if ring and value[0]!=value[-1]:
            raise ValueError('Polygon环未闭合，不能静默补点改变原几何')
    def polygon(value):
        if not isinstance(value,list):
            raise ValueError('Polygon坐标须为环数组')
        for ring in value:
            line(ring,True)
    def geometry(value):
        nonlocal null_count
        if value is None:
            if not spec['allow_null']:
                raise ValueError('输入含缺失几何；须明确allow_null并由模型处理')
            null_count += 1
            return
        if not isinstance(value,dict):
            raise ValueError('GeoJSON几何须为对象或明确null')
        kind=value.get('type')
        if kind not in ('Point','MultiPoint','LineString','MultiLineString','Polygon','MultiPolygon','GeometryCollection'):
            raise ValueError('未知GeoJSON几何类型')
        types[kind]=types.get(kind,0)+1
        if kind=='GeometryCollection':
            nested=value.get('geometries')
            if not isinstance(nested,list):
                raise ValueError('GeometryCollection须有geometries列表')
            for child in nested:
                geometry(child)
            return
        coords=value.get('coordinates')
        if not isinstance(coords,list):
            raise ValueError('几何缺少coordinates数组')
        # RFC 7946 permits empty coordinates. Retain the original empty object;
        # it is explicitly counted as unavailable geometry rather than dropped.
        if not coords:
            geometry(None)
            return
        if kind=='Point':position(coords)
        elif kind=='MultiPoint':
            for point in coords:position(point)
        elif kind=='LineString':line(coords)
        elif kind=='MultiLineString':
            for part in coords:line(part)
        elif kind=='Polygon':polygon(coords)
        else:
            for part in coords:polygon(part)
    seen=[]
    for feature in features:
        if (not isinstance(feature,dict) or feature.get('type')!='Feature' or 'geometry' not in feature
                or 'properties' not in feature or not isinstance(feature['properties'],(dict,type(None)))):
            raise ValueError('每条几何记录须为完整Feature，含geometry与properties')
        if 'id' in feature:
            ident=feature['id']
            if type(ident) not in (int,float,str) or type(ident) is float and not math.isfinite(ident):
                raise ValueError('GeoJSON feature.id须为有限数字或文字')
            seen.append((type(ident).__name__,ident))
        geometry(feature['geometry'])
    return {'features':len(features),'feature_ids_present':len(seen),
        'duplicate_feature_ids':len(seen)-len(set(seen)), 'geometry_types':types,
        'positions':position_count,'dimensions':sorted(dimensions),'null_or_empty_geometries':null_count,
        'validation':'syntax_and_finite_coordinates_only; topology_and_physical_accuracy_not_certified',
        'projection':'none; original_coordinate_values_retained'}


def check_crs(document, metadata, declared):
    """RFC 7946 defaults to WGS84; projected sources need explicit source evidence."""
    raw = document.get('crs') if isinstance(document,dict) else None
    if isinstance(raw,dict) and raw.get('type')=='name':
        raw=raw.get('properties',{}).get('name')
    aliases={'EPSG:4326':'OGC:CRS84','urn:ogc:def:crs:OGC:1.3:CRS84':'OGC:CRS84',
             'urn:ogc:def:crs:EPSG::4326':'OGC:CRS84'}
    def normalize(value):
        if not isinstance(value,str) or not value.strip():
            raise ValueError('源坐标系声明不可解析，需要实际来源的明确CRS')
        return aliases.get(value,value)
    stored=metadata.get('crs')
    if raw is not None and stored is not None and normalize(raw)!=normalize(stored):
        raise ValueError('原文件crs与数据元数据crs冲突')
    actual=normalize(stored if stored is not None else raw) if raw is not None or stored is not None else 'OGC:CRS84'
    if actual!=normalize(declared['crs']):
        raise ValueError('源GeoJSON坐标系与端口不一致；不能只改crs声明代替投影')
    return {'source_crs':actual,'basis':'explicit_source_crs' if raw is not None or stored is not None else 'RFC7946_default',
            'projection':'none'}


def pointer_value(value, pointer):
    """RFC 6901 token traversal; unlike dot paths, property names are unambiguous."""
    if not isinstance(pointer,str) or not pointer.startswith('/'):
        raise ValueError('pointer须为以/开头的明确JSON Pointer')
    for token in pointer.split('/')[1:]:
        import re
        if re.search(r'~(?:[^01]|$)',token):
            raise ValueError('JSON Pointer转义非法')
        token=token.replace('~1','/').replace('~0','~')
        if isinstance(value,dict) and token in value:
            value=value[token]
        elif isinstance(value,list) and re.fullmatch(r'0|[1-9][0-9]*',token) and int(token)<len(value):
            value=value[int(token)]
        else:
            raise ValueError('JSON Pointer引用不存在（不同于显式null）')
    return value
