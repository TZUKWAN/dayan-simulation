"""Explicit parsing contracts retain original files; nothing is executed or extracted."""
import codecs
import csv
import hashlib
import io
import json
import zipfile


TABLE_KEYS = {'delimiter', 'header', 'fieldnames', 'encoding', 'skipinitialspace'}
FILE_KINDS = ('csv', 'tsv', 'json', 'jsonl', 'geojson', 'osm')
FILE_FORMATS = FILE_KINDS + tuple(kind + '.zip' for kind in FILE_KINDS)


def file_format(value):
    if not isinstance(value, str) or value.lower() not in FILE_FORMATS:
        raise ValueError('format须声明成员的数据格式：' + ', '.join(FILE_FORMATS)
                         + '；ZIP须另给parse_options.archive_member，不能只写zip')
    return value.lower()


def table_options(options=None, *, format='csv'):
    options = {} if options is None else options
    if not isinstance(options, dict) or set(options)-TABLE_KEYS:
        raise ValueError('表格解析仅支持delimiter/header/fieldnames/encoding/skipinitialspace')
    spec = {'delimiter': '\t' if format=='tsv' else ',', 'header': True,
            'encoding': 'utf-8-sig', 'skipinitialspace': False, **options}
    if not isinstance(spec['delimiter'], str) or len(spec['delimiter']) != 1 or spec['delimiter'] in '\r\n\0"':
        raise ValueError('delimiter须为一个字符，例如逗号或制表符')
    if type(spec['header']) is not bool or type(spec['skipinitialspace']) is not bool:
        raise ValueError('header和skipinitialspace须为布尔值')
    encoding = spec['encoding']
    if not isinstance(encoding, str) or not encoding or len(encoding)>64:
        raise ValueError('须显式给出有效文本编码')
    try:
        codecs.lookup(encoding)
    except LookupError as exc:
        raise ValueError('未知文本编码：'+encoding) from exc
    names = spec.get('fieldnames')
    if spec['header'] and names is not None:
        raise ValueError('header=true使用实际标题；不能同时给fieldnames覆盖原字段')
    if not spec['header'] and (not isinstance(names, list) or not names or
        any(not isinstance(name, str) or not name.strip() for name in names) or len(set(names)) != len(names)):
        raise ValueError('无标题表格须显式给出非空、唯一的fieldnames')
    return spec


def parse_table(raw, options=None, *, format='csv'):
    spec = table_options(options, format=format)
    text = raw.decode(spec['encoding'])
    reader = csv.reader(io.StringIO(text, newline=''), delimiter=spec['delimiter'],
                        skipinitialspace=spec['skipinitialspace'], strict=True)
    try:
        names = next(reader, None) if spec['header'] else spec['fieldnames']
        if not names or any(not name.strip() for name in names) or len(set(names)) != len(names):
            raise ValueError('表格需要非空、非重复的字段标题')
        rows = []
        for values in reader:
            if not values:  # A physical blank line is not a CSV record; quoted empty fields are preserved.
                continue
            if len(values) != len(names):
                raise ValueError(f'表格第{reader.line_num}行列数不一致：需要{len(names)}列，实际{len(values)}列')
            rows.append(dict(zip(names, values)))
    except csv.Error as exc:
        raise ValueError('表格引号或字段语法不合法：'+str(exc)) from exc
    return rows, {**spec, 'fields': names, 'records': len(rows), 'automatic_type_conversion': False}


def parse_file(raw, format, options=None, *, limit):
    format = file_format(format)
    opts = {} if options is None else options
    if not isinstance(opts, dict) or set(opts)-TABLE_KEYS-{'archive_member'}:
        raise ValueError('未知解析选项')
    kind = format.removesuffix('.zip')
    member_name = opts.get('archive_member')
    payload, receipt = raw, {'format': kind}
    if format.endswith('.zip') or member_name is not None:
        if (not isinstance(member_name, str) or not member_name or member_name.startswith(('/', '\\'))
                or ':' in member_name or '..' in member_name.replace('\\','/').split('/')):
            raise ValueError('ZIP须显式指定安全的archive_member，不自动挑选或解包')
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                matches = [info for info in archive.infolist() if info.filename == member_name]
                if len(matches) != 1:
                    raise ValueError('archive_member不存在或存在重名成员')
                info = matches[0]
                if info.is_dir() or info.flag_bits & 1 or info.file_size > limit:
                    raise ValueError('ZIP成员是目录、加密文件或解压大小超预算')
                with archive.open(info) as stream:
                    payload = stream.read(limit+1)
                if len(payload) > limit:
                    raise ValueError('ZIP成员解压大小超预算')
        except zipfile.BadZipFile as exc:
            raise ValueError('ZIP损坏或成员校验失败') from exc
        receipt.update(archive_member=member_name, payload_sha256=hashlib.sha256(payload).hexdigest(),
                       payload_bytes=len(payload), archive_policy='memory_read_only_no_extract_no_execute')
    parser_options = {key: value for key, value in opts.items() if key != 'archive_member'}
    if kind in ('csv','tsv'):
        data, table = parse_table(payload, parser_options, format=kind)
        return data, {**receipt, **table}
    if set(parser_options)-{'encoding'}:
        raise ValueError('非表格JSON格式仅接受encoding解析选项')
    encoding = parser_options.get('encoding', 'utf-8-sig')
    def reject(value):
        raise ValueError('数据包含非有限数字 '+value)
    text = payload.decode(encoding)
    if kind == 'jsonl':
        data = [json.loads(line, parse_constant=reject) for line in text.splitlines() if line.strip()]
        if any(not isinstance(row, dict) for row in data):
            raise ValueError('JSONL每行须为记录对象')
    else:
        data = json.loads(text, parse_constant=reject)
    if kind == 'geojson' and (not isinstance(data, dict) or data.get('type')!='FeatureCollection'):
        raise ValueError('GeoJSON需要FeatureCollection')
    if kind == 'osm' and (not isinstance(data, dict) or not isinstance(data.get('elements'), list)):
        raise ValueError('OSM JSON缺少elements')
    return data, {**receipt, 'encoding': encoding}
