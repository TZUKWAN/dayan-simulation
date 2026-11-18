"""Verified 2020 TIGERweb road and census-block inputs for local evacuation scenarios."""
from __future__ import annotations

import json
import math
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError

from .connectors import _get
from .. import datasets

ROOT = "https://tigerweb.geo.census.gov/arcgis/rest/services"
ROADS = ROOT + "/Census2020/tigerWMS_PhysicalFeatures/MapServer"
BLOCKS = ROOT + "/TIGERweb/tigerWMS_Census2020/MapServer/10"
CENSUS_LICENSE = "U.S. Census Bureau TIGERweb, 2020 Census · U.S. Government public data"


def _bbox(value):
    if not isinstance(value, list) or len(value) != 4 or any(isinstance(x, bool) for x in value):
        raise ValueError("边界依次为西经度、南纬度、东经度、北纬度")
    west, south, east, north = map(float, value)
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90) or (east-west)*(north-south) > .02:
        raise ValueError("WGS84 边界非法或超过单次 0.02 平方经纬度预算")
    return west, south, east, north


def _query(layer, bbox, **parameters):
    url = _query_url(layer, bbox, **parameters)
    for attempt in range(2):
        try:
            raw, final = _get(url, timeout=35, cap=6*1024*1024)
            break
        except (TimeoutError, URLError) as exc:
            transient = not isinstance(exc, HTTPError) or exc.code in (429,502,503,504)
            if attempt or not transient:
                raise ValueError(f"官方图层 {layer.rsplit('/',1)[-1]} 获取失败：{exc}") from exc
    _features(raw)
    return raw, final


def _query_url(layer, bbox, *, f, where, outSR=None, outFields, returnGeometry, **optional):
    base = {"f":f,"where":where,"geometry":",".join(map(str,bbox)),
            "geometryType":"esriGeometryEnvelope","inSR":4326}
    if outSR is not None:
        base["outSR"]=outSR
    base.update(spatialRel="esriSpatialRelIntersects",outFields=outFields,returnGeometry=returnGeometry,
                resultRecordCount=2000 if f=="geojson" else 1000)
    return layer + "/query?" + urlencode(base | optional)


def _features(raw):
    record = json.loads(raw)
    features = record.get("features")
    if record.get("error") or not isinstance(features, list) or record.get("exceededTransferLimit") or len(features) >= 2000:
        raise ValueError("官方图层请求异常或触及记录上限；缩小范围后重试")
    return features


def _normalize_blocks(features, bbox):
    west, south, east, north = bbox
    rows, seen = [], set()
    for feature in features:
        f = feature["attributes"]
        block = str(f["GEOID"])
        lon, lat, population = (float(f[key]) for key in ("INTPTLON", "INTPTLAT", "POP100"))
        if (not (len(block)==15 and block.isascii() and block.isdigit()) or block in seen
                or not (-180<=lon<=180 and -90<=lat<=90)
                or not math.isfinite(population) or not population.is_integer() or population<=0):
            raise ValueError("普查区标识、内点坐标或人口总量不符合2020普查合同")
        seen.add(block)
        if west <= lon <= east and south <= lat <= north:
            rows.append({"geoid":block,"lon":lon,"lat":lat,"population":int(population)})
    return sorted(rows, key=lambda row:row["geoid"])


def collect_census_scene(bbox, road_classes=None):
    """Collect documented layers and keep each original raw body and transformation."""
    bbox = _bbox(bbox)
    classes = ["local", "secondary", "primary"] if road_classes is None else road_classes
    layer_ids = {"local":5, "secondary":3, "primary":1}
    if not isinstance(classes,list) or not 1<=len(classes)<=3 or any(c not in layer_ids for c in classes) or len(set(classes))!=len(classes):
        raise ValueError("道路类别须为不重复的 local / secondary / primary")
    road_responses = {}
    for name in classes:
        road_responses[name] = _query(f"{ROADS}/{layer_ids[name]}", bbox, f="geojson", where="1=1",
                                    outSR=4326, outFields="*", returnGeometry="true")
    population_response = _query(BLOCKS,bbox,f="json",where="POP100 > 0",outFields="GEOID,INTPTLAT,INTPTLON,POP100",
                                 returnGeometry="false",orderByFields="GEOID")
    return archive_census_scene(list(bbox), road_responses, population_response)


def archive_census_scene(bbox, road_responses, population_response):
    """Reproducibly normalize original layer response bytes, with upstream hashes."""
    bbox = _bbox(bbox)
    shared = {"bbox":list(bbox),"vintage":"2020-01-01","coordinate_crs":"EPSG:4326",
              "scope":"Census 2020 TIGERweb "+",".join(map(str,bbox))}
    parts, roads = [], []
    for name,(raw,url) in road_responses.items():
        features = _features(raw)
        source = datasets.ingest(raw,name=f"TIGERweb 道路原始响应 · {name}",format="geojson",source=url,
                                 license=CENSUS_LICENSE,role="source_snapshot",metadata=shared | {"road_class":name})
        parts.append({"dataset_id":source["dataset_id"],"sha256":source["sha256"]})
        for feature in features:
            if (feature.get("geometry") or {}).get("type") not in ("LineString","MultiLineString"):
                raise ValueError("官方道路图层出现不支持的几何类型")
            roads.append({**feature,"properties":{**(feature.get("properties") or {}),"dayan_road_class":name}})
    raw,url = population_response
    features = _features(raw)
    population = _normalize_blocks(features,bbox)
    if not roads or not population:
        raise ValueError("所选范围没有可用的道路和带人口的普查区内点")
    raw_population = datasets.ingest(raw, name="TIGERweb 普查分区与人口原始响应", format="json", source=url,
                                     license=CENSUS_LICENSE, role="source_snapshot", metadata=shared)
    road_asset = datasets.ingest(json.dumps({"type":"FeatureCollection","features":roads},ensure_ascii=False,allow_nan=False).encode(),
                                 name="CPL001 · 2020 Census 路网",format="geojson",source=ROADS,license=CENSUS_LICENSE,role="roads",
                                 metadata=shared | {"derived_from":parts,"transform":"合并选定道路图层，保持经纬度及原始地物ID；保留与查询范围相交的完整线",
                                                    "road_classes":list(road_responses)})
    population_asset = datasets.ingest(json.dumps(population,ensure_ascii=False,allow_nan=False).encode(),
                                       name="CPL001 · 2020 Census 普查区人口",format="json",source=url,license=CENSUS_LICENSE,role="population",
                                       metadata=shared | {"derived_from":[{"dataset_id":raw_population["dataset_id"],"sha256":raw_population["sha256"]}],
                                                          "transform":"用落在查询范围内的普查区内点定位整区POP100，保留GEOID；非范围内精细人口估算",
                                                          "unit":"person","matched_blocks":len(population),"population":sum(r["population"] for r in population),
                                                          "source_intersections":len(features),"age_fraction":"not_provided"})
    return {"roads":road_asset,"population":population_asset}
