"""One bounded queue and supervised worker processes for expensive API operations."""
from __future__ import annotations
import atexit
import asyncio
from collections import deque
from functools import wraps
import inspect
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import uuid
import psutil

from .access import data_root
from .limits import limits, validate_envelope
from .collection.storage import atomic_json, file_lock, read_json

ROOT=Path(__file__).resolve().parents[1]
TARGETS={'api_run','api_experiment','api_agent','api_ai_chat','api_report',
         'api_state_stream','api_resume','api_custom_model','api_dataset_collect','api_dataset_import',
         'api_run_preset','api_render_collection_reports','api_platform_tool','api_prepare_bundle'}
_managers={}
_manager_lock=threading.Lock()


def _read(path):
    return read_json(path)


def _kill(proc):
    if proc.poll() is not None:return
    try:
        parent=psutil.Process(proc.pid)
        children=parent.children(recursive=True)
        for child in reversed(children):
            try:child.kill()
            except psutil.NoSuchProcess:pass
        parent.kill();proc.wait(timeout=10)
        psutil.wait_procs(children,timeout=3)
    except (psutil.NoSuchProcess,ProcessLookupError):pass


class QueueFull(RuntimeError):
    pass


class TaskManager:
    def __init__(self,base=None,cap=None):
        self.base=Path(base or data_root()).resolve();self.base.mkdir(parents=True,exist_ok=True)
        self.directory=self.base/'tasks';self.directory.mkdir(exist_ok=True)
        self.cap=cap or limits();self.lock=threading.RLock();self.queue=deque();self.active={}
        self.owner=None;self._ensure_owner()
        self.closed=False;self._disk_at=0.;self._disk_bytes=0
        for path in self.directory.glob('*/status.json'):
            row=_read(path)
            if row.get('status') in ('running','queued'):
                pid=row.get('pid')
                if pid:
                    try:
                        process=psutil.Process(pid)
                        command=process.cmdline()
                        if 'dayan.task_worker' in command and str(path.parent) in command:
                            for child in process.children(recursive=True):child.kill()
                            process.kill()
                    except psutil.NoSuchProcess:pass
                row.update(status='error',terminal_reason='interrupted',error='服务进程中断；没有自动重复调用/重跑，已有归档保留',result=None)
                atomic_json(path,row)
        self._release_owner()
        self.thread=threading.Thread(target=self._monitor,name='dayan-task-supervisor',daemon=True)
        self.thread.start();atexit.register(self.close)

    def _path(self,jid):
        if not re.fullmatch('[0-9a-f]{32}',str(jid)):raise ValueError('非法任务标识')
        return self.directory/jid

    def _ensure_owner(self):
        if self.owner is None:
            owner=file_lock(self.directory/'.manager.lock',timeout=.2)
            owner.__enter__();self.owner=owner

    def _release_owner(self):
        if self.owner is not None:
            self.owner.__exit__(None,None,None);self.owner=None

    def _disk(self,force=False):
        if force or time.monotonic()-self._disk_at>1:
            self._disk_bytes=0
            for p in self.base.rglob('*'):
                try:
                    if p.is_file():self._disk_bytes+=p.stat().st_size
                except FileNotFoundError:pass  # An atomic staging rename is not a failed task.
            self._disk_at=time.monotonic()
        return self._disk_bytes

    def submit(self,target,arguments,*,preview=False):
        if target not in TARGETS:raise ValueError('未知受管操作')
        validate_envelope(arguments)
        if len(json.dumps(arguments,ensure_ascii=False).encode())>self.cap.body_bytes:
            raise ValueError('任务请求超过大小预算')
        with self.lock:
            if self.closed:raise QueueFull('任务管理器已关闭')
            if len(self.active)+len(self.queue)>=self.cap.concurrent+self.cap.queued:
                raise QueueFull('任务队列已满，未创建额外线程/进程')
            if self._disk(force=True)>=self.cap.data_bytes:raise QueueFull('研究数据目录达到磁盘配额；未删除历史数据')
            if psutil.disk_usage(str(self.base)).free<self.cap.job_bytes:raise QueueFull('可用磁盘不足，未启动任务')
            self._ensure_owner()
            jid=uuid.uuid4().hex;path=self._path(jid);path.mkdir()
            from .source_version import source_fingerprint
            atomic_json(path/'request.json',{'target':target,'arguments':arguments,
                        'source_fingerprint':source_fingerprint(),'preview':preview})
            atomic_json(path/'status.json',{'job_id':jid,'status':'queued','stages':['已入队，等待有界工作进程'],
                'result':None,'ts':time.time(),'target':target,'limits':vars(self.cap)})
            self.queue.append(jid)
        return jid

    def get(self,jid,*,preview=False):
        path=self._path(jid)
        if not (path/'status.json').exists():raise KeyError('任务不存在')
        row=_read(path/'status.json')
        if row['status'] in ('running','queued') and (path/'progress.json').exists():
            row['stages']=_read(path/'progress.json').get('stages',row['stages'])
        if preview and row['status'] == 'running':
            try:
                row['preview'] = _read(path/'preview.json')
            except FileNotFoundError:
                pass
        if row['status']=='done' and (path/'result.json').exists():row['result']=_read(path/'result.json')['value']
        return row

    def snapshot(self):
        """Bounded public view of the live queue, without task inputs or results."""
        with self.lock:
            jobs = []
            for jid in (*self.active, *self.queue):
                path = self._path(jid)
                row = _read(path / 'status.json')
                progress_path = path / 'progress.json'
                stages = _read(progress_path).get('stages', []) if progress_path.exists() else []
                jobs.append({key: row.get(key) for key in ('job_id', 'target', 'status', 'ts')}
                            | {'stage': (stages or row.get('stages') or [''])[-1]})
            return {'jobs': jobs, 'running': len(self.active), 'queued': len(self.queue),
                    'concurrent_limit': self.cap.concurrent, 'queue_limit': self.cap.queued}

    def cancel(self,jid,reason='cancelled'):
        with self.lock:
            current=self.active.pop(jid,None)
            row=dict(current['row']) if current else self.get(jid)
            if row['status'] not in ('queued','running'):return row
            if jid in self.queue:self.queue.remove(jid)
            if current:_kill(current['process'])
            if not self.active and not self.queue:self._release_owner()
            row.update(status='error',terminal_reason=reason,error=('用户已取消' if reason=='cancelled' else '任务状态读取异常')+'，工作进程已停止；已生成归档保留',result=None)
            atomic_json(self._path(jid)/'status.json',row)
        return row

    async def execute(self,target,arguments):
        jid=self.submit(target,arguments)
        try:
            while True:
                row=self.get(jid)
                if row['status']=='done':return row['result']
                if row['status']=='error':
                    from fastapi import HTTPException
                    raise HTTPException(row.get('http_status',500),row.get('error','任务失败'))
                await asyncio.sleep(.04)
        except asyncio.CancelledError:
            self.cancel(jid);raise
        except Exception:
            try:self.cancel(jid,reason='result_read_error')
            except Exception:pass  # Original storage failure remains the returned error; owned worker is already stopped.
            raise

    def _start(self,jid):
        path=self._path(jid)
        env={**os.environ,'DAYAN_TASK_WORKER':'1','DAYAN_TASK_DIR':str(path),
             'DAYAN_DATA_DIR':str(self.base),'PYTHONPATH':str(ROOT),'PYTHONIOENCODING':'utf-8',
             'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
        # A worker inherits credentials in its environment, never in a command line.
        log=(path/'worker.log').open('wb')
        try:
            process=subprocess.Popen([sys.executable,'-m','dayan.task_worker',str(path)],cwd=ROOT,env=env,
                 stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        finally:log.close()
        row=self.get(jid);row.update(status='running',pid=process.pid,started_at=time.time())
        atomic_json(path/'status.json',row)
        self.active[jid]={'process':process,'started':time.monotonic(),'row':row}

    def _finish(self,jid,current,reason=None):
        process=current['process'];path=self._path(jid);row=current['row']
        if reason:
            _kill(process);row.update(status='error',terminal_reason=reason,error='任务因资源限制停止：'+reason,http_status=429)
        elif process.returncode==0 and (path/'result.json').exists():
            result=_read(path/'result.json')
            if result.get('success'):
                if row['target'] in ('api_agent','api_ai_chat'):
                    from .agent.job_store import bounded_job
                    envelope=bounded_job(jid,{'status':'done','result':result['value']},'')
                    result['value']=envelope['result'];atomic_json(path/'result.json',result)
                row.update(status='done',result=None)
            else:row.update(status='error',error=result.get('error','任务失败'),http_status=result.get('http_status',500),result=None)
        else:row.update(status='error',error='工作进程异常退出，未认定任务成功',returncode=process.returncode,result=None)
        row['finished_at']=time.time()
        if (path/'progress.json').exists():row['stages']=_read(path/'progress.json').get('stages',row['stages'])
        self.active.pop(jid,None)
        if not self.active and not self.queue:self._release_owner()
        atomic_json(path/'status.json',row)

    def _tick(self):
        with self.lock:
            for jid,current in list(self.active.items()):
                proc=current['process']
                if proc.poll() is not None:
                    self._finish(jid,current);continue
                reason=None
                try:
                    processes=[psutil.Process(proc.pid)]
                    processes+=processes[0].children(recursive=True)
                    memory=sum(p.memory_info().rss for p in processes)
                    cpu=sum(sum(p.cpu_times()[:2]) for p in processes)
                    if memory>self.cap.memory_bytes:reason='memory_bytes'
                    elif cpu>self.cap.cpu_seconds:reason='cpu_seconds'
                    elif time.monotonic()-current['started']>self.cap.wall_seconds:reason='wall_timeout'
                    elif self._disk()>self.cap.data_bytes:reason='data_disk_quota'
                    elif sum(p.stat().st_size for p in self._path(jid).rglob('*') if p.is_file())>self.cap.job_bytes:reason='job_disk_quota'
                except psutil.NoSuchProcess:continue
                if reason:self._finish(jid,current,reason)
            while self.queue and len(self.active)<self.cap.concurrent:
                jid=self.queue.popleft()
                try:self._start(jid)
                except Exception as exc:
                    row=self.get(jid);row.update(status='error',error='工作进程启动失败：'+str(exc),result=None)
                    atomic_json(self._path(jid)/'status.json',row)

    def _monitor(self):
        while not self.closed:
            try:self._tick()
            except Exception as exc:
                # Preserve the supervisor failure; do not silently fabricate completion.
                atomic_json(self.directory/'supervisor_error.json',{'error':str(exc),'at':time.time()})
            time.sleep(.05)

    def close(self):
        with self.lock:
            if self.closed:return
            self.closed=True
            for jid in list(self.active)+list(self.queue):self.cancel(jid)
        self.thread.join(timeout=2);self._release_owner()


def get_manager():
    key=str(data_root())
    with _manager_lock:
        manager=_managers.get(key)
        if manager is None or manager.closed:
            manager=_managers[key]=TaskManager()
        return manager


def close_managers():
    for manager in list(_managers.values()):manager.close()


def managed_endpoint(fn):
    signature=inspect.signature(fn,eval_str=True)
    @wraps(fn)
    async def wrapper(*args,**kwargs):
        if os.environ.get('DAYAN_TASK_WORKER')=='1':return await fn(*args,**kwargs)
        from fastapi import HTTPException
        bound=signature.bind(*args,**kwargs);bound.apply_defaults()
        values={k:v.model_dump() if hasattr(v,'model_dump') else v for k,v in bound.arguments.items()}
        asynchronous=False
        if fn.__name__ in ('api_agent','api_run'):
            asynchronous=values['req'].get('async_job',False) is True
            values['req']['async_job']=False
        if fn.__name__=='api_experiment':
            asynchronous=values['body'].pop('async_job',False) is True
        try:
            if asynchronous:return {'job_id':get_manager().submit(fn.__name__,values,preview=True)}
            return await get_manager().execute(fn.__name__,values)
        except QueueFull as exc:raise HTTPException(429,str(exc))
        except ValueError as exc:raise HTTPException(413,str(exc))
    wrapper.__signature__=signature
    return wrapper
