"""Internal worker entry: fixed whitelist, no user-provided Python execution."""
from __future__ import annotations
import asyncio
import inspect
import json
import os
from pathlib import Path
import sys
from .collection.storage import atomic_json


def progress(message):
    folder=Path(os.environ['DAYAN_TASK_DIR'])
    path=folder/'progress.json'
    previous=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'stages':[]}
    previous['stages']=(previous['stages']+[str(message)[:2000]])[-100:]
    atomic_json(path,previous)


async def execute(folder):
    from .task_manager import TARGETS
    from . import server
    server.configure_planner()
    request=json.loads((folder/'request.json').read_text(encoding='utf-8'))
    target=request['target']
    if target not in TARGETS:raise ValueError('未知工作进程操作')
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
