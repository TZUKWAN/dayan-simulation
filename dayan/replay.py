"""Verify a research ZIP; --execute reruns deterministic models from archived code.

Usage: python -m dayan.replay bundle.zip --output new_directory --execute
The output directory must be new. Archived Python is executed only on explicit
--execute, so only use trusted first-party research bundles. No credentials are
copied and live LLM replay is refused rather than replaced with canned responses.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import subprocess
import sys
import zipfile


def extract_checked(archive,target,max_bytes=128*1024*1024):
    total=0
    with zipfile.ZipFile(archive) as z:
        if len(z.infolist())>5000:raise ValueError('归档文件数超限')
        for item in z.infolist():
            name=PurePosixPath(item.filename)
            if name.is_absolute() or '..' in name.parts or '\\' in item.filename or ':' in item.filename:
                raise ValueError('归档包含非法路径')
            total+=item.file_size
            if total>max_bytes or (item.external_attr>>16)&0o170000==0o120000:raise ValueError('归档大小超限或包含符号链接')
        z.extractall(target)


def verify_source(directory):
    meta=json.loads((directory/'SOURCE_MANIFEST.json').read_text(encoding='utf-8'))
    value=hashlib.sha256()
    for name,digest in sorted(meta['files'].items()):
        path=(directory/name).resolve()
        if not path.is_relative_to(directory.resolve()):raise ValueError('源码清单路径越界')
        actual=hashlib.sha256(path.read_bytes()).hexdigest()
        if actual!=digest:raise ValueError('归档源码哈希不一致：'+name)
        value.update(name.encode());value.update(b'\0');value.update(bytes.fromhex(actual))
    if value.hexdigest()!=meta['code_version']:raise ValueError('代码版本总哈希不一致')
    return meta


def internal_run(record_directory,result_file):
    from .run_store import RunStore
    from .runtime import run_model_full,resume_from_checkpoint
    store=RunStore(record_directory.parent);saved=store.load(record_directory.name)
    m=saved['manifest'];mid=saved['model_id'];request=m['requested']
    if m.get('llm_calls'):raise ValueError('真实LLM生成不保证离线重现，保存原始行动/审计供回放；未伪造重推理')
    if m.get('model_definition'):
        from .custom_models import register
        if register(m['model_definition'])['model_id']!=mid:raise ValueError('自定义模型ID与归档定义不一致')
    if m.get('parent_run_id'):
        parent=store.load(m['parent_run_id'])
        rr=resume_from_checkpoint(parent['checkpoint'],m['actual']['n_steps'],request['dt'],capture_state=True,with_initial=True)
    else:
        rr=run_model_full(mid,parameters=request['parameters'],ticks=request['ticks'],dt=request['dt'],
            seed=m['rng']['seed'],experiment=m['rng'].get('experiment','exp0'),strict=True,
            data_bindings=[{k:v for k,v in b.items() if k in {'dataset_id','path','field','aggregate','parameter','scale',
                'source_unit','target_unit','source_scope','target_scope','filters','order_by'}}
                for b in m.get('data_bindings',[]) if 'parameter' in b],
            interventions=request.get('interventions') or [{'at_t':i['requested_t'],'params':i['params'],'label':i.get('label','')}
                for i in m.get('interventions',[]) if i.get('applied')],
            capture_state=bool(saved['state_frames']),state_every=m.get('state_every') or 1)
    clean=lambda frames:[{k:v for k,v in frame.items() if k!='run_id'} for frame in frames]
    result={'run_id':saved['run_id'],'model_id':mid,'observations_equal':rr.observations==saved['observations'],
            'state_frames_equal':clean(rr.state_frames)==clean(saved['state_frames']),
            'n_observations':len(rr.observations),'source_fingerprint':rr.manifest.get('source_fingerprint')}
    result_file.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    if not result['observations_equal'] or not result['state_frames_equal']:raise ValueError('重跑结果与归档不一致')


def replay(bundle,output,execute=False):
    output=Path(output).resolve()
    output.mkdir(parents=True,exist_ok=False)
    artifacts=output/'artifacts';extract_checked(bundle,artifacts)
    from .run_store import RunStore
    store=RunStore(artifacts)
    records=[store.load(p.parent.name) for p in artifacts.glob('*/metadata.json')]
    runs=[r for r in records if r['kind']=='run']
    versions={}
    for r in runs:
        code=r['manifest']['code_version'];path=artifacts/'code_versions'/(code+'.zip')
        expected=r['manifest'].get('code_archive_sha256')
        if expected and hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise ValueError('源码ZIP哈希不一致')
        if code not in versions:
            directory=output/'sources'/code;extract_checked(path,directory)
            versions[code]=verify_source(directory)
    # Dataset hashes are checked even in verify-only mode.
    from .datasets import load
    previous=os.environ.get('DAYAN_DATA_DIR');os.environ['DAYAN_DATA_DIR']=str(artifacts)
    try:
        for p in (artifacts/'datasets').glob('DS-*'):load(p.name)
    finally:
        if previous is None:os.environ.pop('DAYAN_DATA_DIR',None)
        else:os.environ['DAYAN_DATA_DIR']=previous
    result={'verified':True,'run_count':len(runs),'source_versions':list(versions),'executed':[]}
    if execute:
        for r in runs:
            source=output/'sources'/r['manifest']['code_version'];target=output/(r['run_id']+'.replay.json')
            env={**os.environ,'DAYAN_DATA_DIR':str(artifacts),'DAYAN_API_KEY':'','DAYAN_BASE_URL':'','DAYAN_MODEL':'',
                 'PYTHONPATH':str(source),'PYTHONIOENCODING':'utf-8'}
            for key,value in r['manifest'].get('environment',{}).get('thread_environment',{}).items():
                if value is not None:env[key]=value
            proc=subprocess.run([sys.executable,'-m','dayan.replay','--internal-run',str(artifacts/r['run_id']),str(target)],
                cwd=source,env=env,capture_output=True,text=True,encoding='utf-8',timeout=240,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if proc.returncode:raise ValueError('归档源码重跑失败：'+proc.stderr[-3000:])
            result['executed'].append(json.loads(target.read_text(encoding='utf-8')))
    (output/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def main():
    if len(sys.argv)>1 and sys.argv[1]=='--internal-run':
        internal_run(Path(sys.argv[2]),Path(sys.argv[3]));return
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle',type=Path);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    print(json.dumps(replay(args.bundle,args.output,args.execute),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
