"""Real input datasets: bounded download/import, immutable originals and explicit mappings."""
from __future__ import annotations

import csv
import hashlib
import io
import ipaddress
import json
import math
import os
import re
import socket
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 10 * 1024 * 1024


def _public_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("采集地址必须为不含凭据的公开HTTPS URL")
    if parsed.port not in (None, 443):
        raise ValueError("采集仅支持HTTPS默认端口")
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(addr[4][0]).is_global for addr in addresses):
        raise ValueError("不能采集本机、内网或保留地址")
    return url


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _reject_constant(value):
    raise ValueError(f"数据包含非有限数字 {value}")


def _parse(raw, format):
    text = raw.decode("utf-8-sig")
    if format == "csv":
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError("CSV需要非重复的字段标题")
        rows = list(reader)
        if any(None in row for row in rows):
            raise ValueError("CSV列数不一致")
        return rows
    if format not in ("json", "geojson", "osm"):
        raise ValueError("支持CSV、JSON、GeoJSON和OSM JSON")
    data = json.loads(text, parse_constant=_reject_constant)
    if format == "geojson" and (not isinstance(data, dict) or data.get("type") != "FeatureCollection"):
        raise ValueError("GeoJSON需要FeatureCollection")
    if format == "osm" and (not isinstance(data, dict) or not isinstance(data.get("elements"), list)):
        raise ValueError("OSM JSON缺少elements")
    return data


def _rows(data, path=""):
    for token in path.split(".") if path else []:
        data = data[int(token)] if isinstance(data, list) else data[token]
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        raise ValueError("数据路径必须指向记录对象列表")
    return data


def dataset_dir():
    return Path(os.environ.get("DAYAN_DATA_DIR", ROOT / "data")) / "datasets"


def ingest(raw, *, name, format, source, license="unknown", role="input", metadata=None):
    if not isinstance(raw, bytes) or not raw or len(raw) > LIMIT:
        raise ValueError("输入文件须为1字节至10MiB")
    data = _parse(raw, format)
    sha = hashlib.sha256(raw).hexdigest()
    definition = {"name": name, "format": format, "source": source,
                  "license": license, "role": role, "metadata": metadata or {}}
    identity = hashlib.sha256(raw + json.dumps(definition, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    dataset_id = "DS-" + identity[:24]
    directory = dataset_dir() / dataset_id
    if directory.exists():
        return summary(load(dataset_id))
    # Write to a private temporary sibling, then atomically publish.
    import uuid
    stage = dataset_dir() / (".pending-" + uuid.uuid4().hex)
    stage.mkdir(parents=True, exist_ok=False)
    try:
        (stage / "original").write_bytes(raw)
        (stage / "data.json").write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        meta = {**definition, "dataset_id": dataset_id, "sha256": sha, "bytes": len(raw),
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "data_sha256": hashlib.sha256((stage / "data.json").read_bytes()).hexdigest(),
                "provenance_note": "来源描述不自动证明数据准确、适用或已校准；许可unknown须自行核验"}
        (stage / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        os.rename(stage, directory)
    finally:
        if stage.exists():
            for file in stage.iterdir():
                file.unlink()
            stage.rmdir()
    return summary(load(dataset_id))


def load(dataset_id):
    if not re.fullmatch(r"DS-[0-9a-f]{24}", str(dataset_id)):
        raise ValueError("非法数据集标识")
    directory = dataset_dir() / dataset_id
    meta = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    if hashlib.sha256((directory / "original").read_bytes()).hexdigest() != meta["sha256"]:
        raise ValueError("数据集原始文件哈希不一致")
    data_raw = (directory / "data.json").read_bytes()
    if hashlib.sha256(data_raw).hexdigest() != meta["data_sha256"]:
        raise ValueError("数据集解析结果哈希不一致")
    return {**meta, "data": json.loads(data_raw)}


def summary(record):
    result = {k: v for k, v in record.items() if k != "data"}
    data = record["data"]
    rows = data if isinstance(data, list) else data.get("features", data.get("elements", [])) if isinstance(data, dict) else []
    result.update(n_records=len(rows), preview=rows[:3], data_url=f"/api/datasets/{record['dataset_id']}/original")
    return result


def fetch(url, *, name="远程数据", format="json", license="unknown", role="input"):
    _public_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": "DAYAN-Research-Workbench/2.1", "Accept": "application/json,text/csv,*/*"})
    with urllib.request.build_opener(_Redirect()).open(request, timeout=45) as response:
        raw = response.read(LIMIT + 1)
        return ingest(raw, name=name, format=format, source=response.geturl(), license=license,
                      role=role, metadata={"requested_url": url, "content_type": response.headers.get("Content-Type"),
                                           "last_modified": response.headers.get("Last-Modified")})


def import_file(path, *, name=None, format="csv", license="unknown", role="input"):
    actual = (ROOT / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if not actual.is_relative_to(ROOT) or actual.suffix.lower() not in (".csv", ".json", ".geojson"):
        raise ValueError("只导入当前项目内的CSV/JSON/GeoJSON数据文件")
    if actual.stat().st_size > LIMIT:
        raise ValueError("输入文件超过10MiB")
    return ingest(actual.read_bytes(), name=name or actual.name, format=format,
                  source=str(actual), license=license, role=role)


def analyze(dataset_id, path=""):
    record = load(dataset_id)
    rows = _rows(record["data"], path)
    fields = sorted(set().union(*(row.keys() for row in rows))) if rows else []
    numeric = {}
    for field in fields:
        values = []
        missing = 0
        for row in rows:
            value = row.get(field)
            try:
                value = float(value)
                if not math.isfinite(value):
                    raise ValueError("非有限数字")
                values.append(value)
            except (TypeError, ValueError):
                missing += 1
        if values:
            numeric[field] = {"n": len(values), "missing_or_non_numeric": missing,
                              "min": min(values), "max": max(values),
                              "mean": sum(values)/len(values), "sum": sum(values),
                              "first": values[0], "last": values[-1]}
    return {"dataset_id": dataset_id, "sha256": record["sha256"], "path": path,
            "n_rows": len(rows), "fields": fields, "numeric": numeric}


def bind_parameters(bindings):
    params, evidence = {}, []
    for binding in bindings or []:
        record = load(binding["dataset_id"])
        if record.get("role") not in ("input", "initialization", "calibration", "exogenous_input", "mechanism_estimation"):
            raise ValueError("留出验证/背景/文本证据等数据角色不能直接绑定为模型输入参数")
        allowed = {"dataset_id", "path", "field", "aggregate", "parameter", "scale"}
        if set(binding) - allowed:
            raise ValueError("未知数据映射字段")
        stats = analyze(binding["dataset_id"], binding.get("path", ""))
        aggregate = binding.get("aggregate", "last")
        if aggregate not in ("first", "last", "sum", "mean", "min", "max", "n"):
            raise ValueError("未知数据聚合方法")
        values = stats["numeric"].get(binding["field"])
        if not values or values["missing_or_non_numeric"]:
            raise ValueError("映射字段有缺失或非数值，必须先显式清理，不能静默丢弃")
        scale = float(binding.get("scale", 1))
        value = values[aggregate] * scale
        if not math.isfinite(value):
            raise ValueError("映射值必须有限")
        parameter = binding["parameter"]
        if parameter in params:
            raise ValueError("一个参数不能由多个数据映射覆盖")
        params[parameter] = value
        evidence.append({**binding, "resolved_value": value, "sha256": stats["sha256"],
                         "source": load(binding["dataset_id"])["source"]})
    return params, evidence


def osm_roads(bbox):
    if len(bbox) != 4:
        raise ValueError("bbox格式为南纬、西经、北纬、东经")
    south, west, north, east = map(float, bbox)
    if not (-90 <= south < north <= 90 and -180 <= west < east <= 180) or (north-south)*(east-west) > .02:
        raise ValueError("边界非法或过大；单次采集区域不超过0.02平方经纬度")
    query = f'[out:json][timeout:25];way["highway"]({south},{west},{north},{east});out geom;'
    url = "https://overpass-api.de/api/interpreter?" + urllib.parse.urlencode({"data": query})
    return fetch(url, name="OpenStreetMap道路", format="osm", role="roads",
                 license="ODbL-1.0; © OpenStreetMap contributors; https://www.openstreetmap.org/copyright")
