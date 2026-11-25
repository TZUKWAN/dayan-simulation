"""Real input datasets: bounded download/import, immutable originals and explicit mappings."""
from __future__ import annotations

import csv
import hashlib
import io
import http.client
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
DATA_ROLES = ('input', 'initialization', 'exogenous_input', 'mechanism_estimation',
              'calibration', 'validation', 'holdout', 'test', 'background',
              'roads', 'population', 'source_snapshot')


def _public_addresses(host):
    addresses=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
    ips=list(dict.fromkeys(addr[4][0] for addr in addresses))
    if not ips or any(not ipaddress.ip_address(value).is_global for value in ips):
        raise ValueError('不能采集本机、内网或保留地址')
    return ips


def _public_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("采集地址必须为不含凭据的公开HTTPS URL")
    if parsed.port not in (None, 443):
        raise ValueError("采集仅支持HTTPS默认端口")
    _public_addresses(parsed.hostname)
    return url


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect only to validated literal addresses; preserve TLS hostname checks.

    An already configured system proxy remains trusted transport. CONNECT uses
    the validated literal target IP so the proxy cannot resolve a rebinding name.
    No URL/request can configure the proxy or disable certificate verification.
    """
    def connect(self):
        original=self._tunnel_host or self.host
        ips=_public_addresses(original)
        if self._tunnel_host:
            self._tunnel_host=ips[0]
            try:http.client.HTTPConnection.connect(self)
            finally:self._tunnel_host=original
        else:
            error=None
            for address in ips:
                try:
                    self.sock=socket.create_connection((address,self.port),self.timeout,self.source_address)
                    if self.sock.getpeername()[0] not in ips:
                        self.sock.close();raise ValueError('实际连接地址与核验地址不一致')
                    break
                except OSError as exc:error=exc
            else:raise error or OSError('没有可连接的公开地址')
        self.sock=self._context.wrap_socket(self.sock,server_hostname=original)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self,req):
        return self.do_open(_PinnedHTTPSConnection,req,context=self._context)


def public_opener():
    return urllib.request.build_opener(_Redirect(),_PinnedHTTPSHandler())


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _reject_constant(value):
    raise ValueError(f"数据包含非有限数字 {value}")


def _parse(raw, format, parse_options=None):
    from .dataset_parsing import parse_file
    return parse_file(raw, format, parse_options, limit=LIMIT)[0]


def _rows(data, path=""):
    for token in path.split(".") if path else []:
        data = data[int(token)] if isinstance(data, list) else data[token]
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        raise ValueError("数据路径必须指向记录对象列表")
    return data


def dataset_dir():
    return Path(os.environ.get("DAYAN_DATA_DIR", ROOT / "data")) / "datasets"


def ingest(raw, *, name, format, source, license="unknown", role="input", metadata=None, parse_options=None):
    if not isinstance(raw, bytes) or not raw or len(raw) > LIMIT:
        raise ValueError("输入文件须为1字节至10MiB")
    from .dataset_parsing import parse_file
    data, parsing = parse_file(raw, format, parse_options, limit=LIMIT)
    sha = hashlib.sha256(raw).hexdigest()
    definition = {"name": name, "format": format, "source": source,
                  "license": license, "role": role, "metadata": metadata or {}}
    if parse_options is not None:
        definition['parse_options'] = parse_options
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
        meta = {**definition, "dataset_id": dataset_id, "sha256": sha, "bytes": len(raw), 'parsing': parsing,
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


def fetch(url, *, name="远程数据", format="json", license="unknown", role="input", parse_options=None):
    from .dataset_parsing import file_format
    file_format(format)  # Reject an unknown parser before making a network request.
    _public_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": "DAYAN-Research-Workbench/2.1", "Accept": "application/json,text/csv,*/*"})
    with public_opener().open(request, timeout=45) as response:
        raw = response.read(LIMIT + 1)
        return ingest(raw, name=name, format=format, source=response.geturl(), license=license,
                      role=role, parse_options=parse_options, metadata={"requested_url": url, "content_type": response.headers.get("Content-Type"),
                                           "last_modified": response.headers.get("Last-Modified")})


def import_file(path, *, name=None, format="csv", license="unknown", role="input", parse_options=None):
    actual = (ROOT / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    if not actual.is_relative_to(ROOT) or actual.suffix.lower() not in (".csv", ".tsv", ".txt", ".dat", ".zip", ".json", ".jsonl", ".geojson"):
        raise ValueError("只导入当前项目内的文本表格/JSON/GeoJSON/ZIP数据文件，不执行内容")
    if actual.stat().st_size > LIMIT:
        raise ValueError("输入文件超过10MiB")
    return ingest(actual.read_bytes(), name=name or actual.name, format=format,
                  source=str(actual), license=license, role=role, parse_options=parse_options)


def selected_rows(record, path="", filters=None, order_by=None):
    rows = _rows(record["data"], path)
    if filters:
        rows=[r for r in rows if all(r.get(k)==v for k,v in filters.items())]
    if order_by:
        if any(order_by not in r for r in rows):raise ValueError('排序字段缺失')
        rows=sorted(rows,key=lambda r:r[order_by])
    return rows


def analyze(dataset_id, path="",filters=None,order_by=None):
    record = load(dataset_id)
    rows = selected_rows(record, path, filters, order_by)
    fields = sorted(set().union(*(row.keys() for row in rows))) if rows else []
    numeric, profiles = {}, {}
    for field in fields:
        values = []
        missing = 0
        types, distinct = {}, set()
        absent, nulls, blanks = 0, 0, 0
        for row in rows:
            absent += field not in row
            value = row.get(field)
            nulls += field in row and value is None
            blank = isinstance(value,str) and not value.strip()
            blanks += blank
            if field in row:
                typename = type(value).__name__
                types[typename] = types.get(typename,0)+1
            if value is not None and not blank:
                distinct.add(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False))
            try:
                value = float(value)
                if not math.isfinite(value):
                    raise ValueError("非有限数字")
                values.append(value)
            except (TypeError, ValueError, OverflowError):
                missing += 1
        profiles[field] = {'source_types':types, 'absent':absent, 'null':nulls, 'blank_string':blanks,
                           'distinct_nonempty':len(distinct), 'numeric_cast_failures':missing,
                           'identity_comparison':'原始类型与值；不把文字001和1合并'}
        if values:
            numeric[field] = {"n": len(values), "missing_or_non_numeric": missing,
                              "min": min(values), "max": max(values),
                              "mean": sum(values)/len(values), "sum": sum(values),
                              "first": values[0], "last": values[-1]}
    return {"dataset_id": dataset_id, "sha256": record["sha256"], "path": path,
            "n_rows": len(rows), "fields": fields, "numeric": numeric, 'field_profiles':profiles,
            'verification_scope':{'source_integrity':'hash_verified', 'cross_dataset_links':'not_checked',
                'source_dictionary':'not_verified_by_numeric_summary',
                'guidance':'numeric仅为可转为浮点的值摘要，不改变原数据。ID范围重叠不能证明逐个端点匹配；结构绑定按完整原ID集合核对外键。文字类别不因不能转数字而被认定为缺失，参照field_profiles与源字典。'}}


def bind_parameters(bindings,model_id=None):
    params, evidence = {}, []
    for binding in bindings or []:
        record = load(binding["dataset_id"])
        if record.get("role") not in ("input", "initialization", "calibration", "exogenous_input", "mechanism_estimation"):
            raise ValueError("留出验证/背景/文本证据等数据角色不能直接绑定为模型输入参数")
        allowed = {"dataset_id", "path", "field", "aggregate", "parameter", "scale",
                   "source_unit","target_unit","source_scope","target_scope","filters","order_by"}
        if set(binding) - allowed:
            raise ValueError("未知数据映射字段")
        stats = analyze(binding["dataset_id"], binding.get("path", ""),binding.get('filters'),binding.get('order_by'))
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
        from .research.semantics import port
        target=port(model_id,parameter,'inputs') or {}
        if str(model_id).startswith('USR'):
            from .custom_models import factory
            target={**target,**factory(model_id).parameter_schema.get(parameter,{})}
        meta=record.get('metadata',{})
        source_unit=binding.get('source_unit') or meta.get('units',{}).get(binding['field']) or meta.get('unit')
        target_unit=target.get('unit') or binding.get('target_unit')
        if target.get('unit') and binding.get('target_unit') not in (None,target['unit']):
            raise ValueError('映射目标单位与模型参数合同不一致')
        if meta.get('unit') and binding.get('source_unit') not in (None,meta['unit']):
            raise ValueError('源单位声明与已记录数据单位不一致')
        field_unit=meta.get('units',{}).get(binding['field'])
        if field_unit and binding.get('source_unit') not in (None,field_unit):
            raise ValueError('字段单位与已记录元数据不一致')
        status='unverified_units'
        if source_unit and target_unit:
            conversions={('%','fraction'):.01,('fraction','%'):100.,('second','minute'):1/60,('minute','second'):60.}
            required=1. if source_unit==target_unit else conversions.get((source_unit,target_unit))
            if required is None or not math.isclose(scale,required,rel_tol=1e-12,abs_tol=1e-12):
                raise ValueError('数据单位与模型参数单位/显式scale不兼容')
            status='units_verified'
        source_scope=binding.get('source_scope') or meta.get('scope')
        target_scope=binding.get('target_scope')
        if meta.get('scope') and source_scope!=meta['scope']:
            raise ValueError('源地区/主体范围声明与数据元数据不一致')
        if source_scope and target_scope and source_scope!=target_scope:
            raise ValueError('源数据与模型的地区/主体范围不一致：source_scope='+repr(source_scope)
                +'，target_scope='+repr(target_scope)+'。这些字段只写地区/群体标识，不是模型变量、年份或初值用途；须核实际范围后填一致的标识，不能用删范围要求或改标签冒充已匹配。用于独立外部参考且确未声明目标范围时可不填target_scope，按原话保留使用假设')
        if parameter in params:
            raise ValueError("一个参数不能由多个数据映射覆盖")
        params[parameter] = value
        evidence.append({**binding, "resolved_value": value, "sha256": stats["sha256"],
                         "source": record['source'],'source_unit':source_unit,'target_unit':target_unit,
                         "records_used":stats["n_rows"],"license":record.get("license"),
                         **{key:meta[key] for key in ('reference','collection_id','method') if key in meta},
                         'compatibility_status':status,'source_scope':source_scope,'target_scope':target_scope,
                         'role':record['role'],'frequency':meta.get('frequency'),
                         'scope_status':'declared_match' if source_scope and target_scope else 'not_declared',
                         'scope_verification':'matching_declared_labels_not_source_row_membership'})
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
