"""Real headless workbench acceptance against an isolated local service.

Install requirements-ui.txt and a Playwright browser. This creates actual model
runs and one explicitly labelled security fixture in the selected backend. Use
an isolated DAYAN_DATA_DIR, never a user's existing research workspace.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import time
from urllib.parse import urlsplit


def run(base,output,engine='firefox'):
    from playwright.sync_api import sync_playwright
    if urlsplit(base).hostname not in ('127.0.0.1','localhost','::1'):raise ValueError('Use an isolated loopback workbench')
    output.mkdir(parents=True,exist_ok=True)
    checks=[];errors=[];posts=[];performance={}
    def check(name,value):
        if not value:raise AssertionError(name)
        checks.append(name);print('[PASS] '+name,flush=True)
    with sync_playwright() as p:
        options={'headless':True,'timeout':30000}
        if engine=='firefox':options['firefox_user_prefs']={'network.proxy.type':0}
        else:options['args']=['--use-angle=swiftshader','--enable-unsafe-swiftshader']
        browser=getattr(p,engine).launch(**options)
        page=browser.new_page(viewport={'width':1680,'height':1100},accept_downloads=True)
        page.route('https://**/*',lambda route:route.abort())
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        def api(path,payload=None):
            response=page.request.get(base+path) if payload is None else page.request.post(base+path,data=payload)
            if not response.ok:raise RuntimeError(str(response.status)+' '+response.text()[:1000])
            return response.json()
        def restore(rid):
            page.evaluate('(id)=>DAYAN_RESULTS.restore(id)',rid)
            page.evaluate('DAYAN_RESULTS.setPlaying(false);DAYAN3D.setSmoothing(false)')
        try:
            page.goto(base,wait_until='domcontentloaded')
            page.wait_for_function('window.DAYAN_RESULTS && window.DAYAN_COMMAND && window._vizRenderer')
            check('actual WebGL renderer initialized',page.evaluate('!!_vizRenderer.getContext()'))
            page.get_by_role('button',name='专业模式',exact=True).click()
            page.locator('#proModel').fill('NET106');page.locator('#proLoad').click()
            page.wait_for_selector('[data-model-param="density"]')
            contract=api('/api/models/contract/NET106?include_fidelity=false')['contract']
            check('professional mode exposes every real parameter',set(page.locator('[data-model-param]').evaluate_all('(els)=>els.map(e=>e.dataset.modelParam)'))==set(contract['params']))
            for key,value in [('cells','80'),('density','.35')]:page.locator('[data-model-param="'+key+'"]').fill(value)
            for selector,value in [('#proTicks','20'),('#proDt','1'),('#proSeed','7')]:page.locator(selector).fill(value)
            page.locator('#proRun').click()
            page.wait_for_function('DAYAN_RESULTS.runs[0]?.run_id',timeout=45000)
            rid=page.evaluate('DAYAN_RESULTS.runs[DAYAN_RESULTS.selected].run_id');saved=api('/api/runs/'+rid)
            check('professional action creates actual saved requested configuration',saved['manifest']['actual']['effective_parameters']['cells']==80 and saved['manifest']['rng']['seed']==7 and len(saved['observations'])==21)
            restore(rid)
            page.evaluate('DAYAN_RESULTS.seek(DAYAN_RESULTS.end)')
            frame=page.evaluate('_vizStateStream.frames[_vizStateIdx]')
            meshes=page.evaluate('Array.from(_scene.children.find(g=>g.userData.isStateGroup).userData.meshMap.values()).filter(m=>m.userData.entityId!==undefined).map(m=>({id:m.userData.entityId,position:m.position.toArray()}))')
            by_id={str(m['id']):m for m in meshes};length=next(f['length'] for f in frame['facilities'] if f['type']=='road')
            check('rendered persistent IDs equal archived entity IDs',set(by_id)=={str(e['id']) for e in frame['entities']})
            check('rendered ring positions transform actual saved cells',all(abs(by_id[str(e['id'])]['position'][0]-30*math.cos(e['x']/length*2*math.pi))<1e-8 and abs(by_id[str(e['id'])]['position'][2]-30*math.sin(e['x']/length*2*math.pi))<1e-8 for e in frame['entities']))
            page.screenshot(path=str(output/'traffic.png'),full_page=True)
            before=len(posts);page.evaluate('DAYAN_RESULTS.seek(DAYAN_RESULTS.start);DAYAN_RESULTS.setPlaying(true)')
            # Two real animation frames are required after the clock resets.
            # Software WebGL in CI may take longer than a fixed 300 ms delay.
            page.wait_for_function('DAYAN_RESULTS.time>DAYAN_RESULTS.start',timeout=15000)
            check('playback advances the actual shared clock',page.evaluate('DAYAN_RESULTS.time>DAYAN_RESULTS.start'))
            page.evaluate('DAYAN_RESULTS.setPlaying(false)');paused=page.evaluate('DAYAN_RESULTS.time');page.wait_for_timeout(120)
            check('pause and seek never rerun a model',page.evaluate('DAYAN_RESULTS.time')==paused and len(posts)==before)
            page.locator('#entitySelect').select_option(str(frame['entities'][0]['id']))
            page.locator('#focusEntity').click();page.locator('#followEntity').click()
            check('entity selection and camera follow use the same persistent ID',page.evaluate('DAYAN_RESULTS.entityId')==str(frame['entities'][0]['id']) and page.evaluate('DAYAN3D.cameraState.following')==str(frame['entities'][0]['id']))
            iv=api('/api/run',{'model_id':'NET052','ticks':30,'dt':.1,'seed':7,'interventions':[{'at_t':1.,'params':{'beta':'*0.5'}}]})
            restore(iv['run_id']);page.evaluate('DAYAN_RESULTS.seek(1.5)')
            check('intervention timeline displays one actual event',page.evaluate("DAYAN_RESULTS.events.filter(e=>e.etype==='intervention').length")==1)
            check('aggregate animation explicitly discloses no individual tracks','示意' in page.locator('#sceneProvenance').inner_text())
            page.screenshot(path=str(output/'aggregate.png'),full_page=True)
            queue=api('/api/run',{'model_id':'SYS002','ticks':40,'dt':.1,'seed':7})
            restore(queue['run_id']);page.evaluate('DAYAN_RESULTS.seek(DAYAN_RESULTS.end)')
            check('queue scene retains persistent server and customer types',page.evaluate("_vizStateStream.frames.at(-1).entities.some(e=>e.type==='server')"))
            page.screenshot(path=str(output/'queue.png'),full_page=True)
            large=api('/api/run',{'model_id':'NET106','parameters':{'cells':5000,'density':.8},'ticks':250,'dt':1,'seed':7})
            restore(large['run_id']);page.evaluate('DAYAN_RESULTS.seek(DAYAN_RESULTS.end)')
            check('large run retains final frame and discloses render sampling',page.evaluate('_vizStateStream.frames.at(-1).sim_t===DAYAN_RESULTS.end') and '采样3000' in page.locator('#vizStateHud').inner_text())
            check('large-scene GPU instances retain actual entity IDs and coordinates',page.evaluate('''()=>{const g=_scene.children.find(c=>c.userData.isStateGroup),b=g.userData.carBatch,f=_vizStateStream.frames.at(-1),road=f.facilities.find(f=>f.type==='road');if(!b||b.count!==3000)return false;const saved=new Map(f.entities.map(e=>[String(e.id),e])),m=new THREE.Matrix4(),v=new THREE.Vector3();return b.userData.instanceIds.every((id,i)=>{const e=saved.get(String(id));b.getMatrixAt(i,m);v.setFromMatrixPosition(m);return !!e&&Math.abs(v.x-30*Math.cos(e.x/road.length*Math.PI*2))<1e-4&&Math.abs(v.z-30*Math.sin(e.x/road.length*Math.PI*2))<1e-4;});}'''))
            performance=page.evaluate('''()=>{const times=[];for(let i=0;i<5;i++){const start=performance.now();DAYAN3D.renderAt(DAYAN_RESULTS.end);times.push(performance.now()-start);}return {render_ms:times,geometries:_vizRenderer.info.memory.geometries,draw_calls:_vizRenderer.info.render.calls,archived_entities:_vizStateStream.n_entities_max,frames:_vizStateStream.frames.length};}''')
            check('large-scene render remains bounded',max(performance['render_ms'])<5000 and performance['frames']<=201)
            page.screenshot(path=str(output/'large.png'),full_page=True)
            ds=api('/api/datasets/import',{'name':'<img src=x onerror="window.UNIT_XSS=1"> security fixture','format':'csv','content':'value\n1\n','source':'explicit browser security fixture; not empirical'})
            page.evaluate('(id)=>DAYAN_RESULTS.openDataManager(id)',ds['dataset_id'])
            check('dataset names render as text without executable markup',page.evaluate('!window.UNIT_XSS') and page.locator('#datasetList img').count()==0)
            restore(rid);page.set_viewport_size({'width':1000,'height':900});page.wait_for_timeout(120)
            check('viewport resize keeps one renderer canvas',page.locator('#viz3dContainer>canvas').count()==1)
            page.get_by_role('button',name='简易模式',exact=True).click()
            check('simple mode retains AI interaction',page.locator('#aiInput').is_visible())
            page.reload(wait_until='domcontentloaded');page.wait_for_function('DAYAN_RESULTS.runs[0]?.run_id',timeout=30000)
            check('reload restores the saved run without creating a new one',page.evaluate('DAYAN_RESULTS.runs[0].run_id')==rid)
            check('no uncaught application JavaScript errors',not errors)
            result={'ok':True,'checks':checks,'errors':errors,'performance':performance,'run_ids':[rid,iv['run_id'],queue['run_id'],large['run_id']]}
            (output/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            return result
        except Exception as error:
            print('Browser acceptance error: '+repr(error),flush=True)
            (output/'failure.json').write_text(json.dumps({'checks':checks,'errors':errors,'performance':performance,'exception':repr(error)},ensure_ascii=False,indent=2),encoding='utf-8')
            try:page.screenshot(path=str(output/'failure.png'),full_page=True,timeout=3000)
            except Exception as capture_error:print('Diagnostic screenshot unavailable: '+repr(capture_error),flush=True)
            raise
        finally:browser.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--base-url',required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--browser',choices=['firefox','chromium'],default='firefox')
    args=parser.parse_args();run(args.base_url,args.output,args.browser)
