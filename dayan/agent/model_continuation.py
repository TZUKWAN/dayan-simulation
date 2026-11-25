"""Content-addressed, session-bound authoring continuation arguments."""
from copy import deepcopy
from datetime import datetime,timezone
import re

from ..access import data_root
from ..collection.storage import atomic_json,file_lock,read_json
from ..source_version import source_fingerprint
from .design_checkpoint import digest


def _path(token):
    if not isinstance(token,str) or not re.fullmatch(r'MC-[a-f0-9]{64}',token):
        raise ValueError('建模续接凭据无效')
    return data_root()/'model_continuations'/(token+'.json')


def seal(result,source,session_id,memory_scope=None):
    """Only operational continuations are compacted; revisions remain editable."""
    payload=result.get('payload') or {}
    action=payload.get('next_action') or {}
    arguments=action.get('arguments')
    if (not result.get('ok') or action.get('action') not in ('design_model','build_model')
            or not isinstance(arguments,dict) or arguments.get('continuation_token')):
        return result
    state={'version':'dayan-model-continuation-v1','action':action['action'],
           'arguments':deepcopy(arguments),'source':source,'session_id':session_id,
           'memory_scope':memory_scope,'source_fingerprint':source_fingerprint()}
    token='MC-'+digest(state)
    path=_path(token)
    with file_lock(path.with_suffix('.lock'),timeout=.1):
        if path.exists():
            saved=read_json(path)
            if digest(saved.get('state'))!=digest(state):
                raise ValueError('已保存建模续接参数的内容校验失败')
        else:
            atomic_json(path,{'state':state,'created_at':datetime.now(timezone.utc).isoformat()})
    response=deepcopy(result)
    compact={'continuation_token':token}
    if arguments.get('design_id'):compact['design_id']=arguments['design_id']
    response['payload']['next_action']={'action':action['action'],'arguments':compact}
    response['payload']['continuation_scope']='恢复本次已保存的原文、会话、真实数据和运行设置；不重新填写参数'
    return response


def restore(tool,token,arguments,source,session_id,memory_scope=None):
    state=read_json(_path(token)).get('state')
    if not isinstance(state,dict) or 'MC-'+digest(state)!=token:
        raise ValueError('建模续接参数的内容校验失败')
    explicit=(state.get('action')=='build_model' and tool in ('validate_model','build_model')
              and arguments.get('definition') is not None)
    same_step=(state.get('action')==tool or tool=='build_model' and state.get('action')=='design_model'
               or tool=='validate_model' and explicit)
    if not same_step or state.get('session_id')!=session_id:
        raise ValueError('建模续接的原文、会话或执行设置不一致')
    if source is not None and source!=state['source']:
        raise ValueError('建模续接的原文、会话或执行设置不一致')
    if state.get('source_fingerprint')!=source_fingerprint():
        raise ValueError('建模续接的平台版本已变化，不能混用旧执行设置')
    if memory_scope is not None and memory_scope!=state.get('memory_scope'):
        raise ValueError('建模续接的研究记忆范围已变化')
    saved=state['arguments']
    for name,value in arguments.items():
        if name=='continuation_token' or value is None or name=='revise_proposal' and value is False:
            continue
        if name=='definition' and explicit:
            continue
        if name=='request':
            expected=state['source']
        else:
            expected=saved.get(name)
        if value!=expected:
            raise ValueError('建模续接执行设置冲突：'+name+'；沿原next_action续接，修改自主方案请显式修订')
    restored=deepcopy(saved)
    if explicit:
        restored.pop('request',None)
        restored['definition']=deepcopy(arguments['definition'])
    return restored,state['source'],state.get('memory_scope')
