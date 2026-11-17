"""Discover Python + Node suites, isolate sources/data, preserve real outcomes.

Default: all offline categories. --online/--llm opt into external services;
unselected external suites are explicitly SKIP, never counted as passed.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITE_TIMEOUT_S = 180
CATEGORIES = ('unit','mechanism','api','e2e','online','llm','performance')


def category(name):
    if 'online' in name: return 'online'
    if 'live_llm' in name: return 'llm'
    if 'performance' in name: return 'performance'
    if any(s in name for s in ('e2e','requirements','scenario_alignment','assistant_scene','workspace_reports','research_integrity')): return 'e2e'
    if any(s in name for s in ('report','datasets','artifacts','job_store','security','task_manager')): return 'api'
    if any(s in name for s in ('civil_violence','game_contract','benchmarks','model_probe','mechfix','families','models','engines','eco_','net_','coupled')): return 'mechanism'
    return 'unit'


def discover(root=ROOT):
    paths = sorted((root/'tests').rglob('test_*.py'))+sorted((root/'tests').rglob('*.test.mjs'))
    return [{'name':p.stem,'path':p.relative_to(root).as_posix(),
             'runtime':'node' if p.suffix=='.mjs' else 'python','category':category(p.stem)}
            for p in paths if '__pycache__' not in p.parts]


SUITES = [s['name'] for s in discover()]


def judge_suite(name, returncode, stdout, stderr, duration_s, timed_out=False, missing=False):
    output = (stdout or '')+(stderr or '')
    reasons = []
    if missing: reasons.append('套件文件不存在')
    if timed_out: reasons.append('执行超时')
    if returncode != 0: reasons.append('退出码='+str(returncode))
    if '[FAIL]' in output: reasons.append('输出含失败断言')
    if 'Traceback (most recent call last)' in output: reasons.append('输出含Traceback')
    passed, skipped = output.count('[PASS]'), output.count('[SKIP]')
    ran = re.search(r'^Ran (\d+) tests? in ',output,re.M)
    ok = re.search(r'^OK(?: \(skipped=(\d+)\))?\s*$',output,re.M)
    if ran and ok:
        skipped += int(ok.group(1) or 0)
        passed += int(ran.group(1))-int(ok.group(1) or 0)
    node_tests = re.search(r'^# tests (\d+)',output,re.M)
    if node_tests:
        node_pass = re.search(r'^# pass (\d+)',output,re.M)
        node_skip = re.search(r'^# skipped (\d+)',output,re.M)
        node_fail = re.search(r'^# fail (\d+)',output,re.M)
        passed += int(node_pass.group(1)) if node_pass else 0
        skipped += int(node_skip.group(1)) if node_skip else 0
        if node_fail and int(node_fail.group(1)): reasons.append('Node失败断言')
    if passed+skipped == 0 and not reasons: reasons.append('未发现执行或明确跳过的断言（空跑）')
    verdict = 'FAIL' if reasons else 'PASS' if passed else 'SKIP'
    return {'suite':name,'verdict':verdict,'reasons':reasons,'passed':passed,
            'skipped':skipped,'returncode':returncode,'duration_s':round(duration_s,3),
            'excerpt':output[-2500:] if verdict=='FAIL' else ''}


def _snapshot(target):
    for directory in ('dayan','src','tests','experiments','plugins','site','assets'):
        if (ROOT/directory).is_dir():
            shutil.copytree(ROOT/directory,target/directory,
                ignore=shutil.ignore_patterns('__pycache__','node_modules','data','config.json','*.pyc'))
    (target/'data').mkdir()
    for path in (ROOT/'data').glob('*'):
        if path.name=='fidelity_review' and path.is_dir(): shutil.copytree(path,target/'data'/path.name)
        elif path.name in {'dayan_catalog.json','calibration_targets.md','targets.json','output_contract_evidence.json','model_semantics.json'}:
            shutil.copy2(path,target/'data'/path.name)
    for name in ('README.md','requirements.txt','requirements-dev.txt','.gitignore'):
        if (ROOT/name).exists(): shutil.copy2(ROOT/name,target/name)


def _stop_tree(proc):
    if proc.poll() is not None: return
    if os.name=='nt':
        subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True,timeout=15)
    else:
        try: os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError: pass
    proc.wait(timeout=15)


def run_suite(suite, root, output, timeout=SUITE_TIMEOUT_S, online=False, llm=False):
    started = time.perf_counter()
    work = output/suite['name']; work.mkdir(parents=True,exist_ok=True)
    env = {**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONPATH':str(root),
           'DAYAN_DATA_DIR':str(work/'data'),'DAYAN_REPORTS_DIR':str(work/'reports'),
           'DAYAN_PYTHON':sys.executable,
           'DAYAN_TEST_ONLINE':'1' if online else '0','DAYAN_TEST_LLM':'1' if llm else '0'}
    if not llm:
        env.update(DAYAN_API_KEY='',DAYAN_BASE_URL='',DAYAN_MODEL='')
    path = root/suite['path']
    if not path.exists(): return judge_suite(suite['name'],None,'','',0,missing=True)
    node = shutil.which('node')
    command = [sys.executable,str(path)] if suite['runtime']=='python' else [node or 'node','--test','--test-reporter=tap',str(path)]
    proc = None; timed_out = False
    try:
        proc = subprocess.Popen(command,cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
             text=True,encoding='utf-8',errors='replace',
             creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0,
             start_new_session=os.name!='nt')
        try: stdout,stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True; _stop_tree(proc); stdout,stderr = proc.communicate(timeout=5)
        code = proc.returncode
    except (OSError,subprocess.SubprocessError) as exc:
        if proc is not None: _stop_tree(proc)
        stdout,stderr,code = '',str(exc),-1
    (work/'stdout.log').write_text(stdout,encoding='utf-8')
    (work/'stderr.log').write_text(stderr,encoding='utf-8')
    result = judge_suite(suite['name'],code,stdout,stderr,time.perf_counter()-started,timed_out=timed_out)
    result.update(category=suite['category'],runtime=suite['runtime'],logs=str(work))
    return result


def _selftest():
    cases = [(0,'[PASS] a','',False,'PASS'),(1,'[PASS] a','',False,'FAIL'),
             (None,'','',True,'FAIL'),(0,'[FAIL] a','',False,'FAIL'),
             (0,'nothing','',False,'FAIL'),(0,'','Traceback (most recent call last)',False,'FAIL'),
             (0,'Ran 2 tests in 0.1s\n\nOK (skipped=2)\n','',False,'SKIP'),
             (0,'# tests 2\n# pass 2\n# fail 0\n# skipped 0\n','',False,'PASS')]
    for code,out,err,timed,expect in cases:
        assert judge_suite('self',code,out,err,0,timed_out=timed)['verdict']==expect
    print('[PASS] runner selftest: exit, timeout, assertion, empty, traceback, unittest skip, Node TAP')
    return 0


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('suite',nargs='?')
    parser.add_argument('--only',nargs='+')
    parser.add_argument('--category',choices=CATEGORIES)
    parser.add_argument('--online',action='store_true')
    parser.add_argument('--llm',action='store_true')
    parser.add_argument('--list',action='store_true')
    parser.add_argument('--selftest',action='store_true')
    parser.add_argument('--timeout',type=float,default=SUITE_TIMEOUT_S)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args(argv)
    if args.selftest: return _selftest()
    if not 0 < args.timeout <= 1800: parser.error('timeout必须在0..1800秒')
    suites=discover(); names=args.only or ([args.suite] if args.suite else None)
    if names:
        missing=set(names)-{s['name'] for s in suites}
        if missing: parser.error('未知套件: '+str(sorted(missing)))
        suites=[s for s in suites if s['name'] in names]
    if args.category: suites=[s for s in suites if s['category']==args.category]
    if args.list:
        print(json.dumps(suites,ensure_ascii=False,indent=2));return 0
    output=(args.output or ROOT/'.claude'/'test_runs'/time.strftime('%Y%m%dT%H%M%S')).resolve()
    output.mkdir(parents=True,exist_ok=True)
    stats={'suites':{},'passed':0,'skipped':0,'failed_suites':0,'categories':{},
           'online_requested':args.online,'llm_requested':args.llm,'source_isolated':True}
    with tempfile.TemporaryDirectory(prefix='dayan-tests-') as td:
        root=Path(td);_snapshot(root)
        for suite in suites:
            if suite['category'] in ('online','llm') and not (args.online if suite['category']=='online' else args.llm):
                res={'suite':suite['name'],'category':suite['category'],'runtime':suite['runtime'],
                     'verdict':'SKIP','passed':0,'skipped':1,'reasons':['未选择外部服务；未执行，不能当作通过'],'duration_s':0}
            else: res=run_suite(suite,root,output,args.timeout,args.online,args.llm)
            stats['suites'][suite['name']]=res
            stats['passed']+=res['passed'];stats['skipped']+=res.get('skipped',0)
            stats['failed_suites']+=int(res['verdict']=='FAIL')
            print(res['verdict']+' '+suite['name']+': '+str(res['passed'])+' passed, '+str(res.get('skipped',0))+' skipped; '+str(res['duration_s'])+'s',flush=True)
            (output/'test_stats.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
    stats['total']=stats['passed'];stats['generated_at']=time.strftime('%Y-%m-%dT%H:%M:%S')
    for cat in CATEGORIES:
        rows=[v for v in stats['suites'].values() if v['category']==cat]
        stats['categories'][cat]={v:sum(r['verdict']==v for r in rows) for v in ('PASS','FAIL','SKIP')}
    (output/'test_stats.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Result: '+str(stats['passed'])+' assertions passed; '+str(stats['skipped'])+' skipped; '+str(stats['failed_suites'])+' suites failed. '+str(output),flush=True)
    return int(bool(stats['failed_suites']))


if __name__=='__main__':
    sys.exit(main())
