"""Internal worker entry: fixed whitelist, no user-provided Python execution."""
from __future__ import annotations
import asyncio
import inspect
import json
import os
from pathlib import Path
import sys
import time
import uuid
from .collection.storage import atomic_json


def progress(message):
    folder=Path(os.environ['DAYAN_TASK_DIR'])
    path=folder/'progress.json'
    previous=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'stages':[]}
    previous['stages']=(previous['stages']+[str(message)[:2000]])[-100:]
    atomic_json(path,previous)


def frame_observer(model_id, planned_steps):
    """Throttled, size-bounded emission of actual frames from a supervised calculation."""
    folder = os.environ.get('DAYAN_LIVE_PREVIEW')
    if not folder:
        return None
    preview_id = uuid.uuid4().hex
    last_at = 0.0

    def capture(frame, step):
        nonlocal last_at
        now = time.monotonic()
        if now - last_at < 0.85:
            return
        last_at = now
        entities = frame.get('entities', [])
        facilities = frame.get('facilities', [])
        relations = frame.get('relations', [])
        preview = {
            'preview_id': preview_id, 'model_id': model_id, 'step': step,
            'requested_steps': planned_steps, 'entities_total': len(entities),
            'facilities_total': len(facilities), 'relations_total': len(relations),
            'sampled_at': time.time(),
            'frame': {**frame, 'entities': entities[:350], 'facilities': facilities[:250],
                      'relations': relations[:350]},
        }
        try:
            for limit in (350, 100, 20, 0):
                if limit != 350:
                    for key in ('entities', 'facilities', 'relations'):
                        preview['frame'][key] = preview['frame'][key][:limit]
                raw = json.dumps(preview, ensure_ascii=False, allow_nan=False).encode('utf-8')
                if len(raw) <= 196_608:
                    atomic_json(Path(folder) / 'preview.json', preview)
                    break
        except (OSError, TypeError, ValueError):
            # The preview is optional. The runtime validates and archives full outputs separately.
            return

    return capture


async def execute(folder):
    from .task_manager import TARGETS
    request=json.loads((folder/'request.json').read_text(encoding='utf-8'))
    from .source_version import source_fingerprint
    if request.get('source_fingerprint')!=source_fingerprint():
        raise ValueError('排队期间源码已变化；未用另一个版本执行已提交任务')
    from . import server
    server.configure_planner()
    target=request['target']
    if target not in TARGETS:raise ValueError('未知工作进程操作')
    if request.get('preview'):
        os.environ['DAYAN_LIVE_PREVIEW'] = str(folder)
    else:
        os.environ.pop('DAYAN_LIVE_PREVIEW', None)
    fn=getattr(server,target)
    signature=inspect.signature(fn)
    arguments={}
    for key,value in request['arguments'].items():
        annotation=signature.parameters[key].annotation
        arguments[key]=annotation.model_validate(value) if hasattr(annotation,'model_validate') else value
    return await fn(**arguments)


def main():
    folder=Path(sys.argv[1]).resolve()
    expected=Path(os.environ['DAYAN_TASK_DIR']).resolve()
    if folder!=expected or not folder.is_dir():raise ValueError('工作进程目录不匹配')
    try:
        value=asyncio.run(execute(folder))
        result={'success':True,'value':value}
    except Exception as exc:
        result={'success':False,'http_status':getattr(exc,'status_code',400 if isinstance(exc,ValueError) else 500),
                'error':str(getattr(exc,'detail',None) or exc)}
    content=json.dumps(result,ensure_ascii=False,allow_nan=False).encode()
    from .limits import limits
    if len(content)>limits().job_bytes:
        result={'success':False,'http_status':413,'error':'任务结果超过预算；已保存的研究归档仍可按ID读取'}
    atomic_json(folder/'result.json',result)


if __name__=='__main__':main()
