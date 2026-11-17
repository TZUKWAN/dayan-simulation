"""Discover real provider limits; preserve input and allocate available output.

Unknown capabilities stay unknown. The verified provider fallback below is
specific to Alibaba's documented offering, not an invented cross-provider limit.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request
from urllib.parse import urlsplit

ALIYUN_DEEPSEEK_SOURCE='https://help.aliyun.cn/zh/model-studio/deepseek-v4-1-flash'


def _positive(value):
    try:
        number=int(value)
        return number if number>0 else None
    except (ValueError,TypeError):return None


def discover(cfg):
    host=urlsplit(cfg['base_url']).hostname or ''
    overrides=[os.environ.get('DAYAN_CONTEXT_WINDOW'),os.environ.get('DAYAN_MAX_OUTPUT_TOKENS'),
               cfg.get('context_window'),cfg.get('max_output_tokens')]
    key=hashlib.sha256((cfg['base_url']+'\0'+cfg['model_id']+json.dumps(overrides)).encode()).hexdigest()
    root=Path(os.environ.get('DAYAN_DATA_DIR',Path(__file__).resolve().parents[1]/'data'))/'llm_profiles'
    path=root/(key+'.json')
    if path.exists():
        cached=json.loads(path.read_text(encoding='utf-8'))
        if time.time()-cached.get('checked_at',0)<21600:return cached
    model=None;error=None
    try:
        headers={'Authorization':'Bearer '+cfg['api_key']} if cfg.get('api_key') else {}
        req=urllib.request.Request(cfg['base_url'].rstrip('/')+'/models',headers=headers)
        with urllib.request.urlopen(req,timeout=8) as response:
            raw=response.read(2*1024*1024+1)
            if len(raw)>2*1024*1024:raise ValueError('模型元数据响应超限')
            body=json.loads(raw)
        rows=body.get('data',[]) if isinstance(body,dict) else body
        model=next((row for row in rows if row.get('id')==cfg['model_id']),None)
    except Exception as exc:error=type(exc).__name__
    model=model or {};provider=model.get('top_provider') or {}
    context=next((_positive(model.get(k)) for k in ('loaded_context_length','context_window','context_length','max_context_length') if _positive(model.get(k))),None)
    maximum=next((_positive(model.get(k)) for k in ('max_output_tokens','max_completion_tokens','output_limit') if _positive(model.get(k))),None)
    context=context or _positive(provider.get('context_length'))
    maximum=maximum or _positive(provider.get('max_completion_tokens'))
    source='provider-model-metadata' if context or maximum else 'provider-default-unverified'
    reference=None
    if host in ('127.0.0.1','localhost','::1') and (not context or not maximum):
        try:
            endpoint=urlsplit(cfg['base_url'])
            local_url=endpoint.scheme+'://'+endpoint.netloc+'/api/v1/models'
            req=urllib.request.Request(local_url,headers=headers)
            with urllib.request.urlopen(req,timeout=3) as response:local=json.loads(response.read(2*1024*1024))
            for row in local.get('models',[]):
                instances=row.get('loaded_instances',[])
                exact=[i for i in instances if i.get('id')==cfg['model_id']]
                selected=exact or (instances if row.get('key')==cfg['model_id'] else [])
                lengths=[_positive((i.get('config') or {}).get('context_length')) for i in selected]
                lengths=[n for n in lengths if n]
                if lengths:
                    context=min(lengths);maximum=context
                    source='lmstudio-loaded-context';reference='https://lmstudio.ai/docs/developer/rest/list'
                    break
        except Exception:pass  # Absence of this provider-specific endpoint is not evidence of capacity.
    if host.endswith('.maas.aliyuncs.com') or host=='dashscope.aliyuncs.com':
        if cfg['model_id'].lower().startswith('deepseek-v4.1-flash'):
            context=context or 1000000;maximum=maximum or 393216
            source='provider-metadata-and-official-documentation';reference=ALIYUN_DEEPSEEK_SOURCE
    explicit_context=_positive(os.environ.get('DAYAN_CONTEXT_WINDOW')) or _positive(cfg.get('context_window'))
    explicit_output=_positive(os.environ.get('DAYAN_MAX_OUTPUT_TOKENS')) or _positive(cfg.get('max_output_tokens'))
    if explicit_context:context=min(context,explicit_context) if context else explicit_context
    if explicit_output:maximum=min(maximum,explicit_output) if maximum else explicit_output
    if explicit_context or explicit_output:source+='; explicit-configuration'
    result={'model_id':cfg['model_id'],'context_window':context,'max_output_tokens':maximum,
            'source':source,'reference':reference,'metadata_error_type':error,'checked_at':time.time(),
            'listed':bool(model)}
    from .collection.storage import atomic_json
    atomic_json(path,result)
    return result


def allocation(messages,profile,requested=None):
    # Text-only byte upper bound is deliberately labelled, never reported as an
    # exact tokenizer count. No history/messages are silently discarded.
    input_bound=len(json.dumps(messages,ensure_ascii=False).encode())+256*len(messages)+512
    window=profile.get('context_window');maximum=profile.get('max_output_tokens')
    if window and input_bound>=window:
        raise ValueError('完整输入超过已知上下文预算；未截断原始需求或历史，请减少重复工具内容')
    available=window-input_bound if window else None
    chosen=maximum
    if chosen and available:chosen=min(chosen,available)
    elif available and not chosen:
        # A context window does not prove the provider's maximum output setting.
        chosen=None
    if requested is not None:
        if isinstance(requested,bool) or not isinstance(requested,int) or requested<1:raise ValueError('显式max_tokens须为正整数')
        chosen=min(requested,chosen) if chosen else min(requested,available) if available else requested
    return {'max_tokens':chosen,'input_token_upper_bound':input_bound,
            'input_count_method':'UTF-8 bytes plus message-format margin (upper bound)',
            'context_window':window,'provider_max_output_tokens':maximum,
            'limit_source':profile['source'],'limit_reference':profile.get('reference')}
