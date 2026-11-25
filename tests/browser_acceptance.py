"""Real headless workbench acceptance against an isolated local service.

Install requirements-ui.txt and a Playwright browser. This creates actual model
runs and one explicitly labelled security fixture in the selected backend. Use
an isolated DAYAN_DATA_DIR, never a user's existing research workspace.
"""
from __future__ import annotations
import argparse
import csv
import io
import json
import math
from pathlib import Path
from urllib.parse import urlsplit


def run(base,output,engine='firefox'):
    from playwright.sync_api import expect, sync_playwright
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
            page.locator('[data-nav=overview]').click()
            page.evaluate('(id)=>DAYAN_RESULTS.restore(id,{userRequested:true})',rid)
            page.evaluate('DAYAN_RESULTS.setPlaying(false);DAYAN3D.setSmoothing(false)')
        def open_tool(name):
            page.keyboard.press('Control+k')
            expect(page.locator('#paletteQuery')).to_be_focused()
            page.locator('#paletteQuery').fill(name)
            page.keyboard.press('Enter')
        try:
            page.goto(base,wait_until='domcontentloaded')
            page.wait_for_function('window.DAYAN_RESULTS && window.DAYAN_COMMAND && window._vizRenderer')
            check('actual WebGL renderer initialized',page.evaluate('!!_vizRenderer.getContext()'))
            expect(page.locator('#pageOverview')).to_be_visible()
            open_tool('系统总览')
            expect(page.locator('#missionModels')).not_to_have_text('—',timeout=30000)
            platform=api('/api/workbench/status')
            check('mission control shows measured engine and factory status',
                  platform['resources']['engine_rss_bytes'] > 0 and int(page.locator('#missionModels').inner_text()) >= 497)
            open_tool('数据中心')
            expect(page.locator('#pageData')).to_be_visible()
            expect(page.locator('#researchDrawer #pageData')).to_be_visible()
            for space in ('overview','replay'):
                page.locator(f'[data-nav="{space}"]').click()
                expect(page.locator(f'[data-nav="{space}"]')).to_have_attribute('aria-current','page')
                expect(page.locator('[data-workspace-page]:visible')).to_have_count(1)
            check('two primary pages and contextual research tools are keyboard reachable',page.locator('#systemNavigation [data-nav]').count()==2)
            open_tool('模型库')
            page.locator('#modelSearch').fill('NET106')
            page.locator('#modelRows [data-model-open="NET106"]').click()
            expect(page.locator('#modelDetail')).to_contain_text('density',timeout=20000)
            check('library exposes model-specific inputs and semantic relationships',page.locator('.model-network svg').count()==1)
            network=page.locator('.model-network svg')
            network.focus();network.press('ArrowRight')
            check('model network can be explored and reset with the keyboard',
                  'translate(-30 0)' in page.locator('[data-network-world]').get_attribute('transform'))
            page.locator('[data-network-reset]').click()
            page.locator('#runModelDetail').click()
            page.wait_for_selector('[data-model-param="density"]')
            contract=api('/api/models/contract/NET106?include_fidelity=false')['contract']
            check('the parameter panel exposes every real parameter',set(page.locator('[data-model-param]').evaluate_all('(els)=>els.map(e=>e.dataset.modelParam)'))==set(contract['params']))
            for key,value in [('cells','80'),('density','.35')]:page.locator('[data-model-param="'+key+'"]').fill(value)
            for selector,value in [('#proTicks','20'),('#proDt','1'),('#proSeed','7')]:page.locator(selector).fill(value)
            page.locator('#proRun').click()
            page.wait_for_function('DAYAN_RESULTS.runs[0]?.run_id',timeout=45000)
            rid=page.evaluate('DAYAN_RESULTS.runs[DAYAN_RESULTS.selected].run_id');saved=api('/api/runs/'+rid)
            check('professional action creates actual saved requested configuration',saved['manifest']['actual']['effective_parameters']['cells']==80 and saved['manifest']['rng']['seed']==7 and len(saved['observations'])==21)
            cold=browser.new_page(viewport={'width':1680,'height':1100})
            try:
                cold.goto(base,wait_until='domcontentloaded')
                cold.locator('[data-nav=replay]').click()
                cold.locator('#outputSearch').fill(rid)
                cold.locator(f'[data-output="{rid}"]').click()
                cold.wait_for_function('!DAYAN_RESULTS.stream?.partial && DAYAN_RESULTS.stream?.n_frames>0')
                check('the first scene opened from history expands the renderer and its HUD',
                      cold.evaluate("()=>{const c=document.querySelector('#viz3dContainer canvas').getBoundingClientRect();return c.width>300&&c.height>300&&document.querySelector('#vizStateHud')?.offsetHeight>0;}"))
            finally:
                cold.close()
            restore(rid)
            page.evaluate('DAYAN_RESULTS.seek(DAYAN_RESULTS.end)')
            frame=page.evaluate('_vizStateStream.frames[_vizStateIdx]')
            meshes=page.evaluate('Array.from(_scene.children.find(g=>g.userData.isStateGroup).userData.meshMap.values()).filter(m=>m.userData.entityId!==undefined).map(m=>({id:m.userData.entityId,position:m.position.toArray()}))')
            by_id={str(m['id']):m for m in meshes};length=next(f['length'] for f in frame['facilities'] if f['type']=='road')
            check('rendered persistent IDs equal archived entity IDs',set(by_id)=={str(e['id']) for e in frame['entities']})
            check('rendered ring positions transform actual saved cells',all(abs(by_id[str(e['id'])]['position'][0]-30*math.cos(e['x']/length*2*math.pi))<1e-8 and abs(by_id[str(e['id'])]['position'][2]-30*math.sin(e['x']/length*2*math.pi))<1e-8 for e in frame['entities']))
            page.locator('#sceneOptions summary').click()
            page.locator('[data-layer=roadFlow]').click()
            expect(page.locator('#layerReadout')).to_contain_text('整条环路归档通量')
            check('traffic layer visualizes the actual archived whole-road flux',
                  page.evaluate('_vizStateStream.frames[_vizStateIdx].aggregates.flux')==frame['aggregates']['flux'])
            page.locator('[data-layer=flow]').click()
            page.locator('#sceneOptions summary').click()
            page.locator('#trackAgent').click()
            expect(page.locator('#inspectionRail #inspectorEvidence')).to_contain_text('环路近邻')
            page.locator('#sceneFullscreen').click()
            page.wait_for_function("document.fullscreenElement?.classList.contains('live-panel')")
            expect(page.locator('#mapInspector #entityPanel')).to_be_visible()
            page.locator('#sceneFullscreen').click()
            page.wait_for_function('!document.fullscreenElement')
            page.locator('#closeInspector').click()
            check('full-screen scene retains the same single inspector and archived selection',
                  page.locator('#entityPanel').count()==1 and page.evaluate('DAYAN_RESULTS.runs[0].run_id')==rid)
            page.screenshot(path=str(output/'traffic.png'),full_page=True)
            timeline=page.locator('#timeline').bounding_box()
            page.mouse.click(timeline['x']+timeline['width']*.65,timeline['y']+timeline['height']/2)
            check('the visible replay slider seeks before repainting the archived frame',
                  page.evaluate('!DAYAN_RESULTS.playing && DAYAN_RESULTS.time>11 && DAYAN_RESULTS.time<15'))
            before=len(posts);page.evaluate('DAYAN_RESULTS.seek(DAYAN_RESULTS.start);DAYAN_RESULTS.setPlaying(true)')
            # Two real animation frames are required after the clock resets.
            # Software WebGL in CI may take longer than a fixed 300 ms delay.
            page.wait_for_function('DAYAN_RESULTS.time>DAYAN_RESULTS.start',timeout=15000)
            check('playback advances the actual shared clock',page.evaluate('DAYAN_RESULTS.time>DAYAN_RESULTS.start'))
            page.evaluate('DAYAN_RESULTS.setPlaying(false)');paused=page.evaluate('DAYAN_RESULTS.time');page.wait_for_timeout(120)
            check('pause and seek never rerun a model',page.evaluate('DAYAN_RESULTS.time')==paused and len(posts)==before)
            page.evaluate("window._idleClockChanges=0;window._idleClockObserver=new MutationObserver(()=>_idleClockChanges++);_idleClockObserver.observe(document.getElementById('simClock'),{subtree:true,childList:true,characterData:true});")
            page.wait_for_timeout(250)
            check('paused workbench stops repeated chart and clock repaint',page.evaluate('(()=>{_idleClockObserver.disconnect();return _idleClockChanges===0;})()'))
            page.locator('#entitySelect').fill(str(frame['entities'][0]['id']))
            page.locator('#entitySelect').press('Enter')
            page.locator('#focusEntity').click();page.locator('#followEntity').click()
            check('entity selection and camera follow use the same persistent ID',page.evaluate('DAYAN_RESULTS.entityId')==str(frame['entities'][0]['id']) and page.evaluate('DAYAN3D.cameraState.following')==str(frame['entities'][0]['id']))
            page.locator('#sceneOptions summary').click()
            page.locator('#sceneProcess').click()
            expect(page.locator('#processArea svg')).to_be_visible()
            with page.expect_download() as state_download:
                page.locator('#exportProcess').click()
            process_csv=Path(state_download.value.path()).read_text(encoding='utf-8-sig')
            check('state transitions export against the selected archive',rid in process_csv)
            page.keyboard.press('Escape')
            iv=api('/api/run',{'model_id':'NET052','ticks':30,'dt':.1,'seed':7,'interventions':[{'at_t':1.,'params':{'beta':'*0.5'}}]})
            restore(iv['run_id']);page.evaluate('DAYAN_RESULTS.seek(1.5)')
            check('intervention timeline displays one actual event',page.evaluate("DAYAN_RESULTS.events.filter(e=>e.etype==='intervention').length")==1)
            check('SIS moves data composition to analysis while the scene remains spatial-only',
                  page.evaluate("""()=>{
                    const chart=document.querySelector('#structureChart');
                    return DAYAN3D.presentation.kind==='observations' && chart.dataset.kind==='composition'
                      && !_scene.children.some(node=>node.userData.isStateGroup);
                  }"""))
            page.screenshot(path=str(output/'aggregate.png'),full_page=True)
            queue=api('/api/run',{'model_id':'SYS002','ticks':40,'dt':.1,'seed':7})
            restore(queue['run_id']);page.evaluate('DAYAN_RESULTS.seek(DAYAN_RESULTS.end)')
            check('queue scene retains persistent server and customer types',page.evaluate("_vizStateStream.frames.at(-1).entities.some(e=>e.type==='server')"))
            page.screenshot(path=str(output/'queue.png'),full_page=True)
            delayed=[]
            old_state=f'**/api/runs/{rid}/state?*'
            page.route(old_state,lambda route:delayed.append(route))
            with page.expect_request(lambda req:f'/api/runs/{rid}/state?' in req.url):
                page.evaluate('(id)=>{window.testDelayedRestore=DAYAN_RESULTS.restore(id);}',rid)
            restore(queue['run_id'])
            delayed[0].continue_();page.unroute(old_state)
            check('a delayed older archive cannot overwrite the newly selected run',
                  page.evaluate('async(id)=>await testDelayedRestore===false&&DAYAN_RESULTS.runs[0].run_id===id',queue['run_id']))
            large=api('/api/run',{'model_id':'NET106','parameters':{'cells':5000,'density':.8},'ticks':250,'dt':1,'seed':7})
            exact_url=base+'/api/runs/'+large['run_id']
            exact_requests=[];page.route(exact_url,lambda route:exact_requests.append(route))
            with page.expect_request(exact_url):
                page.evaluate('(id)=>{window.testProgressive=DAYAN_RESULTS.restore(id);}',large['run_id'])
            page.wait_for_function('DAYAN_RESULTS.stream?.partial && DAYAN3D.diagnostics.visibleEntities===3000',timeout=45000)
            check('a real labelled frame sample is interactive while full playback waits for the verified archive',
                  page.locator('#playButton').is_disabled() and page.evaluate('DAYAN_RESULTS.stream.n_frames<DAYAN_RESULTS.stream.total_frames'))
            exact_requests[0].continue_();page.unroute(exact_url)
            check('the full archive replaces the sample and enables exact playback',
                  page.evaluate('()=>testProgressive') and page.locator('#playButton').is_enabled())
            page.evaluate('DAYAN3D.setSmoothing(false);DAYAN_RESULTS.seek(DAYAN_RESULTS.end)')
            check('large run retains final frame and discloses render sampling',page.evaluate('_vizStateStream.frames.at(-1).sim_t===DAYAN_RESULTS.end') and '采样3000' in page.locator('#vizStateHud').inner_text())
            check('large-scene GPU instances retain actual entity IDs and coordinates',page.evaluate('''()=>{const g=_scene.children.find(c=>c.userData.isStateGroup),b=g.userData.carBatch,f=_vizStateStream.frames.at(-1),road=f.facilities.find(f=>f.type==='road');if(!b||b.count!==3000)return false;const saved=new Map(f.entities.map(e=>[String(e.id),e])),m=new THREE.Matrix4(),v=new THREE.Vector3();return b.userData.instanceIds.every((id,i)=>{const e=saved.get(String(id));b.getMatrixAt(i,m);v.setFromMatrixPosition(m);return !!e&&Math.abs(v.x-30*Math.cos(e.x/road.length*Math.PI*2))<1e-4&&Math.abs(v.z-30*Math.sin(e.x/road.length*Math.PI*2))<1e-4;});}'''))
            performance=page.evaluate('''()=>{const times=[];for(let i=0;i<5;i++){const start=performance.now();DAYAN3D.renderAt(DAYAN_RESULTS.end);_vizRenderer.getContext().finish();times.push(performance.now()-start);}return {timing:'completed GPU render (WebGL finish)',render_ms:times,geometries:_vizRenderer.info.memory.geometries,draw_calls:_vizRenderer.info.render.calls,triangles:_vizRenderer.info.render.triangles,archived_entities:_vizStateStream.n_entities_max,frames:_vizStateStream.frames.length};}''')
            print('Measured browser render: '+json.dumps(performance),flush=True)
            check('large-scene render remains bounded',max(performance['render_ms'])<5000 and performance['frames']<=201)
            # Keep the actual visible WebGL viewport; expanding a large canvas
            # for a full-page capture can stall Chromium's software compositor.
            page.screenshot(path=str(output/'large.png'),full_page=False)
            ds=api('/api/datasets/import',{'name':'<img src=x onerror="window.UNIT_XSS=1"> security fixture','format':'csv','content':'value\n1\n','source':'explicit browser security fixture; not empirical'})
            open_tool('数据中心')
            expect(page.locator('#showDatasetFixtures')).to_be_visible()
            check('default catalogue hides the verification fixture and offers a localized file chooser',
                  page.locator(f'[data-asset-id="{ds["dataset_id"]}"]').count()==0 and page.locator('#chooseDatasetFile').is_visible())
            page.evaluate('(id)=>DAYAN_RESULTS.openDataManager(id)',ds['dataset_id'])
            check('dataset names render as text without executable markup',page.evaluate('!window.UNIT_XSS') and page.locator('#datasetList img').count()==0)
            open_tool('研究设计')
            question='运行 NET106，环形道路交通流，ticks=18 dt=1，cells=80 density=0.25'
            page.locator('#labQuestion').fill(question)
            page.locator('#labRequestedMetric').fill('flux')
            page.locator('#labCompile').click()
            expect(page.locator('#labNext')).to_be_enabled(timeout=20000)
            page.locator('#labNext').click()
            page.locator('#labSeeds').fill('3,5,7')
            page.locator('#labArms').fill('[{"label":"较高密度","params":{"density":0.5},"interventions":[]}]')
            page.locator('#labExecute').click()
            page.wait_for_function('!!DAYAN_RESULTS.payload?.experiment_id',timeout=65000)
            experiment_id=page.evaluate('DAYAN_RESULTS.payload.experiment_id')
            archive=api('/api/runs/'+experiment_id)
            check('lab preserves the original question through six real paired runs',
                  archive['research_spec']['original_request']==question and len(archive['runs'])==6
                  and archive['analysis']['arms']['较高密度']['paired_diff']['n']==3)
            open_tool('实验分析')
            page.locator('#analyticsCurrent').click()
            expect(page.locator(f'[data-remove-archive="{experiment_id}"]')).to_be_visible(timeout=25000)
            expect(page.locator('#analyticsTrend svg')).to_be_visible(timeout=25000)
            expect(page.locator('#analyticsEffect svg')).to_be_visible()
            expect(page.locator('#analyticsMetric')).to_have_value('flux')
            chart=page.locator('#analyticsTrend svg')
            legend=page.locator('#analyticsTrend [data-chart-legend]').first
            legend.click()
            check('chart legend switches actual traces without changing archived observations',
                  legend.get_attribute('aria-pressed')=='false' and page.locator('#analyticsTrend [data-chart-series="0"]').get_attribute('display')=='none')
            legend.click();chart.scroll_into_view_if_needed()
            x,y,end=chart.evaluate('''svg=>{const m=svg.getScreenCTM(),w=svg.viewBox.baseVal.width;
                const a=new DOMPoint(w*.3,125).matrixTransform(m),b=new DOMPoint(w*.75,125).matrixTransform(m);return [a.x,a.y,b.x];}''')
            page.mouse.move(x,y);page.mouse.down();page.mouse.move(end,y,steps=8);page.mouse.up()
            check('range brush selects real observation times',
                  0<float(page.locator('#analyticsFrom').input_value())<float(page.locator('#analyticsTo').input_value())<18)
            page.locator('#analyticsResetWindow').click()
            page.locator('#analyticsLayout').select_option('four')
            check('the four-chart layout shows precisely four graph panels',page.locator('[data-plot-panel]:visible').count()==4)
            slider=page.locator('#analyticsCursor')
            box=slider.bounding_box()
            page.mouse.click(box['x']+box['width']*.65,box['y']+box['height']/2)
            check('arbitrary slider positions resolve to recorded observation times',
                  float(page.locator('#cursorAt').inner_text()) in range(1,18) and '—' not in page.locator('#analyticsAt').inner_text())
            slider.press('Home')
            expect(page.locator('#cursorAt')).to_have_text('0')
            with page.expect_download() as chart_download:
                page.locator('#analyticsExport').click()
            csv_rows=list(csv.DictReader(io.StringIO(Path(chart_download.value.path()).read_text(encoding='utf-8-sig'))))
            check('linked analytics export real run versions and the selected metric',
                  any(row['archive_id']==experiment_id and row['metric']=='flux' and row['code_version'] for row in csv_rows))
            page.locator('[data-nav="replay"]').click()
            page.locator(f'[data-output="{experiment_id}"]').click()
            page.locator('#historyReportTab').click()
            expect(page.locator('#outputDetail')).to_contain_text(experiment_id)
            check('research outputs resolves the same experiment and bundle',page.locator(f'#outputDetail a[href="/api/runs/{experiment_id}/bundle.zip"]').count()==1)
            restore(rid)
            divider=page.locator('#operationResize')
            original_width=int(divider.get_attribute('aria-valuenow'))
            divider.press('ArrowLeft')
            check('keyboard resizing changes the operation rail width',int(divider.get_attribute('aria-valuenow'))>original_width)
            density=page.locator('[data-model-param="density"]')
            expect(density).to_have_value('0.35')
            density.fill('0.42')
            open_tool('研究设计');page.locator('[data-nav="overview"]').click()
            expect(density).to_have_value('0.42')
            page.set_viewport_size({'width':1000,'height':900});page.wait_for_timeout(120)
            check('viewport resize keeps one renderer canvas',page.locator('#viz3dContainer>canvas').count()==1)
            page.locator('#assistantButton').click()
            check('one workspace exposes AI and parameters',page.locator('#aiInput').is_visible() and not page.locator('[data-operation-mode]').count())
            page.reload(wait_until='domcontentloaded');page.wait_for_function('DAYAN_RESULTS.runs[0]?.run_id',timeout=30000)
            check('reload restores the saved run without creating a new one',page.evaluate('DAYAN_RESULTS.runs[0].run_id')==rid)
            page.locator('#openExperiment').click()
            expect(density).to_have_value('0.42')
            check('unsent professional edits survive workspace switches and reload',True)
            check('no uncaught application JavaScript errors',not errors)
            result={'ok':True,'browser':engine,'checks':checks,'errors':errors,'performance':performance,'run_ids':[rid,iv['run_id'],queue['run_id'],large['run_id']], 'experiment_id':experiment_id}
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
