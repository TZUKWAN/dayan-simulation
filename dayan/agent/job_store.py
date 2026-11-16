"""Bounded durable assistant job state. Model artifacts stay in the canonical run store."""
import copy
import hashlib
import json
import re

from ..run_store import get_store,_atomic_write,_bytes

LIMIT=2*1024*1024


def _path(job_id):
    if not re.fullmatch(r'(?:[0-9a-f]{32}|[0-9]{6}\.[0-9]{6})',str(job_id)):
        raise ValueError('非法任务标识')
    return get_store().directory.parent/'agent_jobs'/(str(job_id)+'.json')


def save_job(job_id,job,request_text):
    record=copy.deepcopy(job);record.update(job_id=job_id,request_text=request_text)
    data=_bytes(record)
    if len(data)>LIMIT:
        result=record.get('result') or {}
        for action in result.get('executed',[]):
            args=action.pop('args',None)
            if args is not None:action['arguments_sha256']=hashlib.sha256(_bytes(args)).hexdigest()
            payload=action.get('payload')
            if isinstance(payload,dict):
                keys=('model_id','run_id','analysis_id','experiment_id','dataset_id','result_kind','warnings')
                action['payload']={**{k:payload[k] for k in keys if k in payload},'archive_only':True}
        result.pop('rounds',None);result.pop('plan',None)
        record['result']=result;record['artifact_note']='完整模型数据保存在引用的研究归档；任务信封省略重复数据。'
        data=_bytes(record)
    if len(data)>LIMIT:raise ValueError('任务日志超过2MiB，未写入不完整JSON')
    _atomic_write(_path(job_id),data)


def load_job(job_id):
    path=_path(job_id)
    if not path.exists():raise KeyError('任务不存在')
    if path.stat().st_size>LIMIT:raise ValueError('任务日志超出读取界限')
    record=json.loads(path.read_text(encoding='utf-8'))
    if record.get('job_id')!=job_id:raise ValueError('任务日志标识不一致')
    if record.get('status')=='running':
        record.update(status='error',error='原执行进程已中断，尚未确认任务完成；请核对研究记录中的已有产物。',result=None)
    return record
