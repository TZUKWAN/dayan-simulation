/* Canonical results: a single saved run supplies the scene, clock, charts and exports. */
(() => {
  "use strict";
  const $ = s => document.querySelector(s);
  const colors = ["#47e3d1", "#b693ff", "#ffbd68", "#f8849b", "#86bcff", "#c5d983"];
  const labels = {run:"仿真",resume:"检查点续算",build_model:"生成新模型",experiment:"对照实验",compare:"模型对比",sweep:"参数扫描",ensemble:"种子重复",compose:"模型流水线"};
  const bounds = values => values.reduce((b,v)=>[Math.min(b[0],v),Math.max(b[1],v)],[Infinity,-Infinity]);
  const esc = x => String(x ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const finite = x => typeof x === "number" && Number.isFinite(x);
  const fmt = x => DAYAN_ANALYSIS.fmt(x);
  const at = (arr, t) => {
    let lo = 0, hi = arr.length;
    while (lo < hi) { const m = (lo + hi) >>> 1; if ((arr[m].sim_t ?? m) <= t + 1e-9) lo = m + 1; else hi = m; }
    return Math.max(0, lo - 1);
  };
  async function api(path, body) {
    const response = await fetch(path, body === undefined ? {} : {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
    const value = await response.json();
    if (!response.ok || value.ok === false) {const error=new Error(typeof value.detail === "string" ? value.detail : JSON.stringify(value.detail || value.error || "请求失败"));error.status=response.status;throw error;}
    return value;
  }
  function message(text, kind = "ai-bot") {
    const item = document.createElement("div"); item.className = "ai-msg " + kind;
    item.textContent = text; $("#aiChatBody")?.appendChild(item);
    if ($("#aiChatBody")) $("#aiChatBody").scrollTop = $("#aiChatBody").scrollHeight;
    return item;
  }
  function fields(rows) {
    return [...new Set(rows.flatMap(r => Object.keys(r || {})))].filter(k => k !== "sim_t" && rows.some(r => finite(r[k])));
  }
  const state = {active:true, kind:"empty", runs:[], selected:0, time:0, start:0, end:0,
                  rate:1, playing:false, metric:null, stream:null, payload:null, events:[], lastWall:null,
                  loop:false,followEntity:false,windowMode:'all',customWindow:null,entityId:'',entityField:'',distributionField:'',context:{},question:''};
  const controller = window.DAYAN_RESULTS = Object.assign(state, {});
  let lastPaint = 0, requestRevision = 0, pendingRestore = null, datasetRevision = 0, controls = [];
  let inspectorAnchor, inspectorOpen=false;

  function notice(text) { if (window.DAYAN_NOTICE) DAYAN_NOTICE(text); else message(text); }
  function modal(title, html) { if (window.DAYAN_MODAL) DAYAN_MODAL(title, html); }
  function setPlaying(value, repaint=true) {
    if (value && state.time >= state.end && state.end > state.start) state.time = state.start;
    state.playing = Boolean(value && state.runs.length && !state.stream?.partial && state.end > state.start);
    state.lastWall = null;
    $("#playButton").textContent = state.playing ? "Ⅱ" : "▶";
    $("#playButton").setAttribute("aria-label", state.playing ? "暂停回放" : "播放回放");
    document.body.classList.toggle("paused", !state.playing);
    const live=$(".live");if(live)live.innerHTML='<i></i>'+(state.playing?"回放中":"已暂停");
    const tiny=$(".tiny-live");if(tiny)tiny.innerHTML='<i class="dot"></i>'+(state.playing?(state.runs[state.selected]?.run_id?"已保存状态回放中":"观测回放中"):"回放已暂停");
    if (window.DAYAN3D) state.playing ? DAYAN3D.resume() : DAYAN3D.pause();
    if (state.playing) window.DAYAN_SCHEDULE_TICK?.();
    if(!state.playing&&repaint){paint();window.DAYAN3D?.renderAt?.(state.time);}
  }
  function seek(t) {
    state.time = Math.min(state.end, Math.max(state.start, Number(t)));
    state.lastWall = null; paint();
    if (window.DAYAN3D?.renderAt) DAYAN3D.renderAt(state.time);
  }
  function clear(title = "从一个问题，进入一个可观察的世界") {
    state.kind = "empty"; state.runs = []; state.stream = null; state.payload = null;
    state.start = state.end = state.time = 0; state.events = []; state.metric = null;
    window._lastRun = null; window._obsData = null; window._vizStateStream = null; window._vizStateIdx = -1;
    window._dashModel = true; setPlaying(false);
    $("#scenarioTitle").textContent = title;
    window.DAYAN3D?.clear?.();
    paint(); configurePolicies();updateActions();
    if(window.DAYAN3D?.renderAt)DAYAN3D.renderAt(0);
  }
  function paint() {
    const run=state.runs[state.selected],rows=run?.observations||[],idx=rows.length?at(rows,state.time):0,obs=rows[idx]||{};
    const frame=state.stream?.frames?.[at(state.stream.frames,state.time)],entities=frame?.entities||[];
    const partial=Boolean(state.stream?.partial);
    $('#playButton').disabled=!run||partial||state.end<=state.start;$('#timeline').disabled=$('#playButton').disabled;$('#resetButton').disabled=!run;$('#loopPlayback').disabled=!run;
    $('#stepBack').disabled=!run||partial||idx<=0;
    $('#stepForward').disabled=!run||partial||idx>=rows.length-1;
    $('#sceneEmptyState').hidden=Boolean(run);
    $('#sceneProvenance').textContent=run?(state.stream?.provenance==='entity'?'主体状态来自本次模型计算 · 点击主体可查看轨迹':'汇总指标驱动的场景示意 · 不是个体轨迹'):'运行后呈现对应模型世界';
    const scenario=run?.manifest?.model_definition?.scenario;
    if(scenario){$('#sceneProvenance').textContent=`本次模型状态 · ${/[0-9]/.test(scenario.title)?'底模 · ':''}${scenario.title} · 当前 ${entities.length} ${scenario.agent_label}`;$('#sceneProvenance').title='底模说明：'+scenario.setting;}
    paintScenarioCoverage(run);
    $('#simClock').textContent='sim_t='+fmt(obs.sim_t??state.time);
    $('#timelineText').textContent=run?`${idx}/${Math.max(0,rows.length-1)}步 · ${frame?.space?.time_unit||run.manifest?.model_definition?.time_unit||run.manifest?.actual?.time_unit||'模型时间'}`:'等待模型运行';
    const timeline=$('#timeline');timeline.min=state.start;timeline.max=state.end||1;timeline.step='any';timeline.value=state.time;
    timeline.style.setProperty('--range',100*(state.time-state.start)/Math.max(1e-12,state.end-state.start)+'%');
    $('#obsTick').textContent=run?`当前 sim_t=${fmt(obs.sim_t)} · ${DAYAN_ANALYSIS.label(state.metric)}=${fmt(obs[state.metric])}`:'';
    $('#obsModel').textContent=run?run.label:'暂无运行';
    const legend=state.runs.map((r,i)=>`<span><i style="background:${DAYAN_ANALYSIS.colorFor(state,r,i)}"></i>${esc(r.label+(r.observations.some(o=>finite(o[state.metric]))?'':'（无该指标）'))}</span>`).join('');
    if($('#obsLegend').innerHTML!==legend)$('#obsLegend').innerHTML=legend;
    $('#trackAgent').disabled=!entities.length;
    $('#sceneProcess').disabled=partial||!(state.stream?.frames?.length>1&&state.stream.provenance==='entity');
    const layers = {flow:true,roadFlow:finite(frame?.aggregates?.flux)&&!!frame?.facilities?.some(f=>f.type==='road'&&f.length>0),heat:entities.some(e=>finite(e.x)&&finite(e.y)),network:!!frame?.relations?.length,
      trajectory:!partial&&state.time>state.start&&!!state.entityId&&entities.some(e=>String(e.id)===String(state.entityId)&&finite(e.x)&&finite(e.y))};
    const facilities=frame?.facilities||[],road=f=>['road','road_network'].includes(f.type)||f.kind==='road';
    const visibleLayers={base:!!run,entities:entities.length>0,roads:facilities.some(road),facilities:facilities.some(f=>!road(f)),labels:!!run,events:state.events.length>0};
    for(const button of document.querySelectorAll('[data-scene-toggle]'))button.disabled=!visibleLayers[button.dataset.sceneToggle];
    for(const button of document.querySelectorAll('[data-layer]')) button.disabled=!layers[button.dataset.layer];
    if(document.querySelector('[data-layer].active')?.disabled) selectLayer('flow');
    const context=[...document.querySelectorAll('.scenario-strip .context>span')];
    if(context[0])context[0].textContent=run?(entities.length?entities.length+' 个模型主体':'汇总模型'):'暂无运行';
    if(context[1])context[1].textContent=(frame?.space?.time_unit?.includes('观测序号')?'观测序号 ':'模型时间 ')+fmt(state.start)+'–'+fmt(state.end);
    if(context[2])context[2].textContent='当前种子 '+(run?.manifest?.rng?.seed??'—');
    $('.scene-status .micro').textContent=run?.model_id||'无运行';
    const labels=document.querySelectorAll('.timeline-labels>span');labels[0].textContent=fmt(state.start);labels[labels.length-1].textContent=fmt(state.end);
    const events=state.events.filter(e=>(e.sim_t??0)<=state.time+1e-9),key=(run?.run_id||'')+':'+events.length;
    $('#eventCounter').textContent=events.length;
    if(state.eventPaintKey!==key){state.eventPaintKey=key;
      $('#eventList').innerHTML=events.slice(-30).reverse().map(e=>`<div class="event-item"><i class="event-dot"></i><time>${fmt(e.sim_t)}</time><div><b>${esc(e.label||e.etype||'模型记录')}</b><p>${esc((typeof e.message==='string'?e.message:JSON.stringify(e.params||e.decision||Object.fromEntries(Object.entries(e).filter(([k])=>!['sim_t','etype'].includes(k))))).slice(0,600))}</p><button class="event-seek" data-event-time="${e.sim_t}" data-event-index="${state.events.indexOf(e)}">定位此时刻 ↗</button></div></div>`).join('')||'<div class="empty-events">当前没有已记录的模型事件。</div>';
      const locate=event=>{if(!event)return;setPlaying(false);seek(event.sim_t);DAYAN3D.focusEvent(event);};
      document.querySelectorAll('[data-event-time]').forEach(b=>b.onclick=()=>locate(state.events[Number(b.dataset.eventIndex)]));
      $('.timeline-ticks').innerHTML=state.events.map((e,i)=>finite(e.sim_t)&&e.sim_t>=state.start&&e.sim_t<=state.end?`<button class="event-tick" aria-label="${esc(e.label||e.etype)}，模型时间${e.sim_t}" data-timeline-event="${e.sim_t}" data-event-index="${i}" style="left:${100*(e.sim_t-state.start)/Math.max(1e-12,state.end-state.start)}%"></button>`:'').join('');
      document.querySelectorAll('[data-timeline-event]').forEach(b=>b.onclick=()=>locate(state.events[Number(b.dataset.eventIndex)]));
    }
    $('footer>span').textContent=run?`${run.model_id} · ${rows.length}条观测 · ${state.stream?.frames?.length||0}帧 · ${run.run_id?'已保存':'旧观测，无完整状态归档'}`:'等待首次仿真';
    window._lastRun=run?{model_id:run.model_id,run_id:run.run_id,observations:rows,params:run.manifest?.actual?.effective_parameters||run.manifest?.actual?.parameters||{},seed:run.manifest?.rng?.seed,ticks:run.manifest?.requested?.ticks,manifest:run.manifest}:null;
    window._obsData=run?{names:[state.metric],series:[rows.map(o=>o[state.metric])],n:rows.length,times:rows.map(o=>o.sim_t)}:null;
    DAYAN_ANALYSIS.render(state);
    window.DAYAN_COMMAND?.paint(state);
    if(inspectorOpen)paintInspector(frame);
    paintSceneDiagnostics();
    $('#archiveLoading').hidden=!partial;
  }
  function dockInspector(open) {
    const panel=$('#entityPanel');
    if(!inspectorAnchor||!panel)return;
    inspectorOpen=open;
    const floating=open&&(document.fullscreenElement=== $('.live-panel')||document.body.classList.contains('view-immersive')||document.body.matches('.dsh-native-embed.mode-simple')||innerWidth<=1020);
    const map=$('#mapInspector');map.hidden=!floating;
    $('#trackAgent').setAttribute('aria-expanded',String(open));
    const destination=floating?map:$('#inspectionRail');
    if(open&&panel.parentElement!==destination) destination.append(panel);
    if(!open&&panel.previousSibling!==inspectorAnchor) inspectorAnchor.after(panel);
    $('#closeInspector').hidden=!open;
    $('#inspectorEvidence').hidden=!open;
    if(open){paintInspector(state.stream?.frames[at(state.stream.frames,state.time)]);DAYAN_ANALYSIS.render(state);}
  }
  function paintInspector(frame) {
    const host=$('#inspectorEvidence'),id=state.entityId;
    if(!host)return;
    const entity=frame?.entities?.find(e=>String(e.id)===id);
    if(!entity){host.textContent='';return;}
    const related=(frame.relations||[]).filter(r=>String(r.source)===id||String(r.target)===id);
    const others=related.slice(0,12).map(r=>{
      const source=String(r.source)===id, next=source?r.target:r.source;
      return `<button data-related-entity="${esc(next)}">${r.directed?(source?'→ ':'← '):''}${esc(next)} <span>${esc(r.type||r.kind||'关系')}</span></button>`;
    });
    const ring=frame.facilities?.find(f=>f.type==='road'&&f.length>0);
    const positioned=finite(entity.x)&&finite(entity.y);
    const nearby=positioned&&(frame.space?.bounds||ring)?frame.entities.filter(other=>other!==entity&&finite(other.x)&&finite(other.y)).map(other=>{
      const dx=Math.abs(entity.x-other.x);
      return {other,d:ring?Math.min(dx,Math.abs(ring.length-dx)):Math.hypot(dx,entity.y-other.y)};
    }).sort((a,b)=>a.d-b.d).slice(0,5):[];
    const units=frame.space?.unit||(ring?'格':'模型单位');
    const found=state.events.filter(e=>[e.entity_id,e.agent_id,e.subject_id,e.bus_id===undefined?undefined:'bus-'+e.bus_id].some(key=>key!==undefined&&String(key)===id));
    const trace=state._frameCache?.traces.get(id)||[];
    const path=trace.reduce((n,f)=>n+Number(finite(f.x)&&finite(f.y)),0);
    const html=`<dl class="inspect-facts"><dt>归档帧时间</dt><dd>${esc(fmt(frame.sim_t))}</dd><dt>原始位置</dt><dd>${positioned?esc(`${fmt(entity.x)}, ${fmt(entity.y)} ${units}`):'未记录坐标'}</dd><dt>轨迹位置</dt><dd>${path} 个已载入帧</dd></dl>
      <h3>登记关系 · ${related.length}</h3>${others.length?`<div class="inspect-links">${others.join('')}</div>`:'<p>当前帧无关联边。</p>'}
      ${nearby.length?`<h3>${ring?'环路近邻':'坐标近邻'}</h3><div class="inspect-links">${nearby.map(({other,d})=>`<button data-related-entity="${esc(other.id)}">${esc(other.id)} <span>${esc(fmt(d)+' '+units)}</span></button>`).join('')}</div>`:''}
      <h3>关联事件 · ${found.length}</h3>${found.length?`<div class="inspect-links">${found.slice(0,12).map(e=>`<button data-inspect-time="${esc(e.sim_t)}">${esc(e.label||e.etype)} <span>t=${esc(fmt(e.sim_t))} ↗</span></button>`).join('')}</div>`:'<p>归档中无显式关联到该主体的事件记录。</p>'}`;
    if(host.innerHTML!==html)host.innerHTML=html;
  }
  function paintSceneDiagnostics() {
    const host=$('#sceneDebugInfo');
    if(host.hidden)return;
    const d=window.DAYAN3D?.diagnostics,pack=state.stream;
    if(!d||!pack){host.textContent='场景诊断等待归档';return;}
    const message=`${pack.run_id||'旧观测'}\n状态帧 ${pack.n_frames}/${pack.total_frames} · 渲染主体 ${d.visibleEntities}\nWebGL ${d.drawCalls} 次绘制 · ${d.triangles} 三角形 · ${d.textures} 纹理`;
    if(host.textContent!==message)host.textContent=message;
  }
  function paintScenarioCoverage(run) {
    let box=$('#scenarioCoverage');
    if(!box){box=document.createElement('details');box.id='scenarioCoverage';box.className='panel scenario-coverage';$('.details-grid')?.appendChild(box);}
    box.hidden=!run;if(!run)return;
    const definition=run.manifest?.model_definition||{},scenario=definition.scenario,review=run.manifest?.scenario_review;
    const current=state.stream?.frames?.[at(state.stream.frames,state.time)],actual={...(run.manifest?.actual?.effective_parameters||{})};
    for(const intervention of run.manifest?.interventions||[])if(intervention.applied&&intervention.actual_t<=(current?.sim_t??state.time))Object.assign(actual,intervention.params||{});
    Object.assign(actual,current?.parameters||{});
    const names={n:'主体数',speed:'速度',v_des:'期望速度',vmax:'最高速度',exit_x:'出口横坐标',exit_y:'出口纵坐标'};
    const overrides=Object.entries(actual).filter(([key,value])=>JSON.stringify(value)!==JSON.stringify(definition.parameters?.[key]?.default));
    const effective='sim_t='+fmt(current?.sim_t??state.time)+' · '+(overrides.length?overrides.map(([key,value])=>`${definition.parameters?.[key]?.label||names[key]||key}=${typeof value==='object'?JSON.stringify(value):value}${definition.parameters?.[key]?.unit?' '+definition.parameters[key].unit:''}`).join('；'):'采用底模默认参数');
    const key=run.run_id||run.model_id;if(box.dataset.run===key){const status=box.querySelector('.scenario-effective');if(status)status.textContent=effective;return;}box.dataset.run=key;
    const first=run.stream?.frames?.[0]||state.stream?.frames?.[0]||{},facilities=first.facilities||[];
    const facts=facilities.map(f=>`<li><b>${esc(f.label||f.kind||f.type)}</b><span>${f.role==='context'?'场所参照':f.role==='modeled'?'绑定模型计算':'模型导出设施'}</span></li>`).join('');
    const rows=(scenario?.requirements||[]).map(r=>`<tr><td>${esc(r.quote)}</td><td><details><summary>查看对应依据</summary><p>模型：${esc(r.model_refs.join('、'))}</p><p>画面：${esc(r.visual_refs.join('、'))}</p></details></td></tr>`).join('');
    box.innerHTML=`<summary>场景如何对应需求 <span>${scenario?esc(scenario.title):'查看实际输出'}</span></summary><div class="scenario-evidence"><p>${esc(scenario?'底模说明：'+scenario.setting:(first.entities?.length?'按模型导出的主体和设施构建画面。':'该模型输出汇总指标，当前画面表示指标演化。'))}</p><p class="scenario-effective">${esc(effective)}</p><p>首帧 ${(first.entities||[]).length} 个模型实体${scenario?.agent_label?' · '+esc(scenario.agent_label):''} · ${facilities.length} 项设施</p>${facts?'<ul>'+facts+'</ul>':''}${rows?'<p>以下对应关系来自底模创建时的需求；本次修改以实际参数和状态为准。</p><table><thead><tr><th>建模原文要求</th><th>模型与画面引用</th></tr></thead><tbody>'+rows+'</tbody></table>':''}<p class="chart-caption">${review?'底模已做结构、数据流与语义复核；科学适用性尚未独立校准。':scenario?'依据为用户模型规约与实际归档状态；底模未进行独立LLM语义复核。':'此处列出实际导出的对象与设施，可与研究问题对照检查。'}</p></div>`;
    const limitations=[...new Set([...(definition.limitations||[]),...(review?.limitations||[])])];
    if(limitations.length){const details=document.createElement('details'),summary=document.createElement('summary'),list=document.createElement('ul');summary.textContent='本次模型的简化与未覆盖项';details.appendChild(summary);limitations.forEach(text=>{const li=document.createElement('li');li.textContent=text;list.appendChild(li);});details.appendChild(list);box.querySelector('.scenario-evidence').appendChild(details);}
  }

  function observationOnlyStream(run) {
    const original=run.observations||[],indexed=!!run.legacy_time_is_index||original.some(o=>!finite(o.sim_t));
    const rows=original.map((o,i)=>({...o,sim_t:indexed?i:o.sim_t}));
    const frames=rows.map(o=>({sim_t:o.sim_t,entities:[],facilities:[],relations:[],provenance:'aggregate',
      aggregates:Object.fromEntries(Object.entries(o).filter(([key,value])=>key!=='sim_t'&&finite(value))),
      space:{time_unit:indexed?'观测序号（原记录无完整时间戳）':'模型时间'}}));
    return {model_id:run.model_id,run_id:null,provenance:'aggregate',provenance_note:'旧记录只有观测，画面为汇总指标示意，没有主体轨迹。',
      manifest:run.manifest||{},observations:rows,frames,events:[],sample_every:1,total_frames:frames.length,n_frames:frames.length,n_entities_max:0};
  }

  async function select(index,options={}) {
    const revision=options.revision??++requestRevision,selected=Number(index),run=state.runs[selected];
    if(!run)return false;const previousTime=state.time,previousPlaying=state.playing;
    if(!options.fresh)setPlaying(false);
    const pack=run.stream||(run.run_id?await api(`/api/runs/${encodeURIComponent(run.run_id)}/state?sample_every=1`):observationOnlyStream(run));
    if(revision!==requestRevision)return false;
    if(pack&&run.run_id&&pack.run_id!==run.run_id)throw new Error('动画运行标识与结果不一致，已停止显示');
    state.selected=selected;state.stream=pack;state.followEntity=false;
    state.events=DAYAN_ANALYSIS.savedEvents(pack);state.eventPaintKey=null;
    if(pack)pack.events=state.events;
    if(pack){run.stream=pack;run.observations=pack.observations;run.manifest=pack.manifest;selectLayer('flow',false);DAYAN3D.visualizeState(pack);}
    state.start=Math.min(...state.runs.map(r=>r.observations[0]?.sim_t??0));state.end=Math.max(...state.runs.map(r=>r.observations.at(-1)?.sim_t??0));
    state.time=options.fresh?state.start:Math.min(state.end,Math.max(state.start,previousTime));
    const metrics=fields(run.observations);
    state.metric=metrics.includes(state.metric)?state.metric:(['flux','I','I_total','gini','evacuated','k'].find(k=>metrics.includes(k))||metrics[0]);
    if(options.fresh){state.windowMode=DAYAN_ANALYSIS.interventionTime(state)!==null?'post':'all';state.customWindow=null;state.entityId='';state.entityField='';state.distributionField='';}
    if(options.fresh&&pack?.frames?.[0]?.entities?.length){const first=pack.frames[0].entities[0];state.entityId=String(first.id);state.entityField=finite(first.speed)?'speed':finite(first.x)?'x':'';}
    renderSelectors(metrics);if(!pack?.partial)await configurePolicies();if(revision!==requestRevision)return false;paint();
    if(window.DAYAN3D?.renderAt)DAYAN3D.renderAt(state.time);
    if(options.fresh&&state.entityId)window.DAYAN3D?.selectEntity(state.entityId);
    setPlaying(options.fresh?options.play!==false:previousPlaying);
    updateActions();
    window.dispatchEvent(new CustomEvent('dayan:result',{detail:run.run_id}));
    return true;
  }
  function selectLayer(mode,render=true) {
    if (render) window.DAYAN3D?.setLayer(mode);
    else window.DAYAN3D?.setLayer(mode,false);
    for(const button of document.querySelectorAll('[data-layer]')){
      button.classList.toggle('active',button.dataset.layer===mode);
      button.setAttribute('aria-pressed',String(button.dataset.layer===mode));
    }
  }
  function renderSelectors(metrics) {
    $('#resultSelectors').innerHTML=`<label>观察方案<select id="resultRunSelect" aria-label="选择运行">${state.runs.map((r,i)=>`<option value="${i}" ${i===state.selected?'selected':''}>${esc(r.label)}</option>`).join('')}</select></label><label>结果指标<select id="resultMetricSelect" aria-label="选择观测量">${metrics.map(k=>`<option value="${esc(k)}" ${k===state.metric?'selected':''}>${esc(DAYAN_ANALYSIS.label(k))} · ${esc(k)}</option>`).join('')}</select></label>`;
    $('#resultRunSelect').onchange=e=>select(e.target.value).catch(e=>notice(e.message));
    $('#resultMetricSelect').onchange=e=>{state.metric=e.target.value;paint();};
  }
  function normalizedRuns(tool,p) {
    if(tool==="run"||tool==="resume"||tool==="build_model")return[{...p,label:p.model_id}];
    if(tool==="experiment"){
      const offset={};return(p.runs||[]).map(r=>{const i=offset[r.arm]||0;offset[r.arm]=i+1;return {...r,model_id:p.model_id,label:`${r.arm} · seed=${r.seed}`,observations:p.observations_by_arm?.[r.arm]?.[i]||[]};});
    }
    if(tool==="compose")return(p.stages||[]).map((r,i)=>({...r,label:`阶段${i+1} · ${r.model_id}`}));
    return(p.runs||[]).map(r=>({...r,label:tool==="sweep"?`${p.param}=${r.value}`:tool==="ensemble"?`seed=${r.seed}`:r.model_id}));
  }
  async function showResult(tool,p,context={},revision=++requestRevision) {
    if(p.archive_only){const id=p.experiment_id||p.analysis_id||p.run_id;if(id){const restored=await restore(id);if(restored&&context.question){state.question=context.question;$('#researchQuestion').textContent=context.question;$('#scenarioTitle').textContent=context.question.slice(0,70);}return restored;}if(p.dataset_id){state.datasetFocus=p.dataset_id;await navigate('data');return true;}return false;}
    if(tool==='explain')return false;
    if(tool==='build_model'&&p.result_kind==='ensemble')tool='ensemble';
    if(tool==="collect_data"||tool==="analyze_data"){
      message(`${tool==="collect_data"?"数据已保存":"数据分析已完成"}，可在数据页检查字段、质量与参数映射。`);
      state.datasetFocus=p.dataset_id;setPlaying(false);navigate("data");return true;
    }
    const runs=normalizedRuns(tool,p);if(!runs.length)return false;
    // Publish the next result only after its canonical scene archive is available.
    if(runs[0].run_id&&!runs[0].stream){
      const pack=await api(`/api/runs/${encodeURIComponent(runs[0].run_id)}/state?sample_every=1`);
      if(pack.run_id!==runs[0].run_id)throw new Error('动画运行标识与结果不一致');
      runs[0].stream=pack;runs[0].observations=pack.observations;runs[0].manifest=pack.manifest;
    }
    if(revision!==requestRevision)return false;
    if(globalThis.DAYAN_STUDY?.run_id&&runs[0].run_id!==globalThis.DAYAN_STUDY.run_id)globalThis.DAYAN_RESEARCH?.clearContext();
    setPlaying(false);
    state.active=true;state.kind=tool;state.payload=p;state.runs=runs;state.metric=p.primary_metric||p.analysis?.metric||null;
    window._chartMode=tool;window._dashModel=true;document.body.classList.add("model-results-active");
    document.querySelectorAll(".weather").forEach(el=>el.style.display="none");
    $("#scenarioTitle").textContent=`${p.model_id||runs[0].model_id} · ${labels[context.intent]||context.intent||labels[tool]||tool}`;
    const tag=$(".scenario-name .tag");if(tag)tag.textContent="模型回放";
    let savedQuestions={};try{savedQuestions=JSON.parse(localStorage.getItem('dayan_research_questions_v1')||'{}');}catch{}
    const key=p.experiment_id||p.analysis_id||runs[0].run_id;
    state.context=context;state.question=context.question||savedQuestions[key]||p.request_text||p.research_spec?.question||p.experiment_spec?.hypothesis||p.intent||"";
    if(state.question&&key&&!context.archivePending){savedQuestions[key]=state.question;const entries=Object.entries(savedQuestions).slice(-80);try{localStorage.setItem('dayan_research_questions_v1',JSON.stringify(Object.fromEntries(entries)));}catch{}}
    $("#researchQuestion").textContent=state.question||(context.archivePending?'正在读取完整档案和原始研究问题…':'当前为已保存模型的实际运行；可通过 AI 助手继续描述研究问题。');
    if(context.question)$("#scenarioTitle").textContent=context.question.length>70?context.question.slice(0,70)+"…":context.question;
    const code=$(".scenario-strip .code");if(code)code.textContent=(p.experiment_id?"EXPERIMENT":"RESEARCH")+" / "+(p.model_id||runs[0].model_id);
    navigate("overview");
    if(!await select(0,{fresh:true,play:!context.replaying,revision}))return false;
    addDownloadLinks(p,runs[0],context);return true;
  }
  function addDownloadLinks() { updateActions(); }
  function setStatus(text,kind='ready') {
    $('#workspaceStatus').textContent=text;$('#workspaceStatus').dataset.state=kind;
  }
  async function generateReport() {
    const run=state.runs[state.selected];if(!run?.run_id||state.stream?.partial)return notice('请等待完整归档载入。');
    const study=globalThis.DAYAN_STUDY;
    if(study?.run_id===run.run_id){
      const button=$('#reportButton');button.disabled=true;setStatus('正在核对研究、校准与模型运行版本…','working');
      try{const result=await api('/api/tools/research_report',{arguments:{study_id:study.study_id,kind:'academic'}}),report=result.payload;
        const link=document.createElement('a');link.href=report.file;link.download='';link.textContent='下载当前研究报告';link.className='ws-button';$('#reportDownload')?.remove();link.id='reportDownload';$('.workspace-actions').appendChild(link);link.click();
        setStatus('同源研究报告已生成；验证状态 '+report.validation_status);return {...report,url:report.file};
      }catch(error){setStatus('研究报告未生成：'+error.message,'error');throw error;}finally{button.disabled=false;}
    }
    const p=state.payload||{},window=DAYAN_ANALYSIS.resolvedWindow(state),button=$('#reportButton');
    const request={model_id:run.model_id,run_id:run.run_id,experiment_id:p.experiment_id||null,analysis_id:p.analysis_id||null,
      intent:state.question||state.context.intent||'',planner:state.context.planner||'rule',
      primary_metric:state.metric,analysis_window:window,sim_t:state.time,entity_id:state.entityId||null,entity_metric:state.entityField||null,distribution_field:state.distributionField||null};
    button.disabled=true;setStatus('正在从归档计算分析并生成报告…','working');
    try{
      const report=await api('/api/report',request),link=document.createElement('a');link.href=report.url;link.download='';link.textContent='下载本次报告';link.className='ws-button';
      $('#reportDownload')?.remove();link.id='reportDownload';$('.workspace-actions').appendChild(link);link.click();
      setStatus('报告已生成；指标、分析窗口及所选运行已传入报告。');return report;
    }catch(error){setStatus('报告未生成：'+error.message,'error');notice(error.message);throw error;}
    finally{button.disabled=!state.runs[state.selected]?.run_id;}
  }
  function resumeDialog() {
    const run=state.runs[state.selected];if(!run?.manifest?.checkpoint?.resumable)return;
    modal('从真实检查点继续',`<p>从保存的 sim_t=${fmt(run.manifest.checkpoint.t)} 继续推进，创建新的运行记录。</p><label>增加步数 <input id="resumeTicks" type="number" min="1" max="10000" value="100" step="1"></label><button class="ws-button ws-primary" id="confirmResume">继续计算</button><p id="resumeStatus" role="status"></p>`);
    $('#confirmResume').onclick=async()=>{const ticks=Number($('#resumeTicks').value);if(!Number.isInteger(ticks)||ticks<1||ticks>10000){$('#resumeStatus').textContent='请输入1到10000的整数步数。';return;}$('#confirmResume').disabled=true;
      try{const result=await api(`/api/runs/${run.run_id}/resume`,{ticks});window.DAYAN_CLOSE_MODAL();await showResult('run',result,{intent:'检查点续算',question:state.question});}
      catch(error){$('#resumeStatus').textContent=error.message;$('#confirmResume').disabled=false;}};
  }
  function showEvidence() {
    const run=state.runs[state.selected];if(!run)return modal('实验依据','<p>尚无运行。先描述研究问题、选择模型，或读取研究记录。</p>');
    const m=run.manifest||{},actual=m.actual||{},params=actual.effective_parameters||actual.parameters||{},a=state.viewAnalysis;
    const facts=[['模型',run.model_id],['观察方案',run.label],['推进步数 / 观测数',`${actual.n_steps??'未核验'} / ${run.observations.length}`],['种子',m.rng?.seed??'未记录'],['模型时间',`${state.start} — ${state.end}`],['状态来源',state.stream?.provenance==='entity'?'主体状态':'汇总观测'],['分析指标',DAYAN_ANALYSIS.label(state.metric)],['分析窗口',a?`${a.window.from} ${a.window.exclusive?'<':'≤'} sim_t ≤ ${a.window.to}`:'未选择']];
    modal('研究依据与实际设定',`<div class="evidence-grid">${facts.map(([k,v])=>`<div><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`).join('')}</div><h3>实际模型参数</h3><table class="data-stat-table"><thead><tr><th>参数</th><th>执行值</th></tr></thead><tbody>${Object.entries(params).map(([k,v])=>`<tr><td>${esc(controls.find(c=>c.param===k)?.label||k)}</td><td>${esc(typeof v==='object'?JSON.stringify(v):v)}</td></tr>`).join('')}</tbody></table><p>${esc(state.stream?.provenance_note||'仅使用本次归档保存的状态。')}</p>${(m.warnings||[]).map(w=>`<p>${esc(w)}</p>`).join('')}<details class="evidence-details"><summary>完整运行清单与实验规约</summary><pre>${esc(JSON.stringify({manifest:m,experiment_spec:state.payload?.experiment_spec,comparability:state.payload?.comparability_note},null,2))}</pre></details>`);
  }
  function policyValue(run,parameter,time) {
    const m=run.manifest||{};let value=m.actual?.effective_parameters?.[parameter]??m.actual?.parameters?.[parameter]??controls.find(c=>c.param===parameter)?.default;
    for(const iv of [...(m.interventions||[])].filter(i=>i.applied&&i.actual_t<=time).sort((a,b)=>a.actual_t-b.actual_t))if(Object.prototype.hasOwnProperty.call(iv.params||{},parameter))value=iv.params[parameter];
    return value;
  }
  async function configurePolicies() {
    const panel=$(".policy");if(!panel)return;const run=state.runs[state.selected];let available=[],controlError='';
    if(run?.run_id&&run.manifest?.requested){try{available=(await api(`/api/models/contract/${encodeURIComponent(run.model_id)}?include_fidelity=false`)).contract.policies||[];}catch(e){controlError=e.message;}}
    if(run!==state.runs[state.selected])return;controls=available;
    panel.innerHTML=`<div class="panel-head"><h2>模型参数干预</h2><span id="branchTag">${run?esc(run.model_id):"无运行"}</span></div>`+controls.map((c,i)=>{const id=["transport","service","information"][i]||"policy"+i;const actual=run?policyValue(run,c.param,state.start+(state.end-state.start)*.3):c.default;return `<div class="slider-field"><label>${esc(c.label)} <em id="${id}Val">${fmt(actual)}</em></label><input type="range" id="${id}" data-policy="${esc(c.param)}" min="${c.minimum}" max="${c.maximum}" step="${c.integer?1:(c.maximum-c.minimum)/100}" value="${actual}"><small>${esc(c.param)} · ${esc(c.unit)}</small></div>`;}).join("")+`<label>干预时刻 sim_t <input id="policyAt" type="number" min="${state.start}" max="${state.end}" step="any" value="${state.start+(state.end-state.start)*.3}"></label><button id="applyPolicy" class="apply-policy" ${controls.length?"":"disabled"}>运行配对干预实验</button><span id="policyNote">${controls.length?"只修改已声明可变参数，使用相同种子与基线配置":"该模型未声明运行中可变参数，不能用通用滑杆代替政策"}</span>`;
    for(const input of panel.querySelectorAll("input[data-policy]"))input.oninput=()=>{input.dataset.edited="true";document.getElementById(input.id+"Val").textContent=fmt(Number(input.value));};
    $("#policyAt").oninput=()=>{const time=Number($("#policyAt").value);if(!run||!finite(time))return;for(const input of panel.querySelectorAll("input[data-policy]")){if(input.dataset.edited)continue;const value=policyValue(run,input.dataset.policy,time);input.value=value;document.getElementById(input.id+"Val").textContent=fmt(value);}};
    $("#applyPolicy").onclick=()=>applyPolicy().catch(e=>notice(e.message));
    if(controlError)$("#policyNote").textContent='参数合同暂未取得：'+controlError;
  }
  function updateActions() {
    const run=state.runs[state.selected],p=state.payload||{},complete=Boolean(run?.run_id&&!state.stream?.partial);
    const bundleId=p.experiment_id||p.analysis_id||run?.run_id;
    for(const [id,url] of [['#exportCsv',complete?`/api/runs/${run.run_id}/observations.csv`:null],['#exportBundle',bundleId&&complete?`/api/runs/${bundleId}/bundle.zip`:null]]){
      const link=$(id);link.setAttribute('aria-disabled',String(!url));if(url){link.href=url;link.download='';}else link.removeAttribute('href');
    }
    $('#reportButton').disabled=!complete;$('#resumeButton').disabled=!complete||!run?.manifest?.checkpoint?.resumable;
    setStatus(state.stream?.partial?'正在载入完整状态帧。':run?(run.run_id?'结果已保存；动画与分析使用同一运行记录。':'旧记录仅回放已有观测；不具备完整主体状态与续算依据。'):'等待研究任务');
  }
  async function applyPolicy() {
    const run=state.runs[state.selected];if(!run||state.stream?.partial)throw new Error("请等待完整模型运行归档");const m=run.manifest,changes={},when=Number($("#policyAt").value);
    if(!finite(when)||when<state.start||when>=state.end)throw new Error("干预时间必须在运行终点之前");
    for(const input of document.querySelectorAll("input[data-policy]")){const name=input.dataset.policy,value=Number(input.value),original=policyValue(run,name,when);if(Math.abs(value-original)>1e-12)changes[name]=value;}
    if(!Object.keys(changes).length)throw new Error("参数没有变化，未创建干预实验");
    $("#applyPolicy").disabled=true;
    const common=(m.interventions||[]).filter(i=>i.applied).map(i=>({at_t:i.requested_t,params:i.params,label:i.label}));
    const bindings=(m.data_bindings||[]).filter(b=>b.parameter).map(b=>Object.fromEntries(Object.entries(b).filter(([k])=>["dataset_id","path","field","aggregate","parameter","scale","source_unit","target_unit","source_scope","target_scope","filters","order_by"].includes(k))));
    const body={model_id:run.model_id,baseline_params:m.requested.parameters,baseline_interventions:common,data_bindings:bindings,ticks:m.requested.ticks,dt:m.requested.dt,seeds:[m.rng.seed],rng_domain:m.rng.experiment,purpose:"policy",primary_metric:state.metric,title:"明确参数的配对干预",arms:[{label:"干预组",params:{},interventions:[{at_t:when,params:changes,label:"用户参数干预"}]}]};
      try{const p=await api("/api/experiments",body);await showResult("experiment",p,{intent:"用户设置的配对干预",question:state.question});}finally{if($("#applyPolicy"))$("#applyPolicy").disabled=!controls.length;}
  }
  function completeState(record, pack) {
    const {state_frames:frames=[],checkpoint,...archive}=record;
    if(record.kind!=='run'||record.run_id!==pack.run_id||record.model_id!==pack.model_id||frames.length!==pack.total_frames)
      throw new Error('完整归档与已校验的首批状态帧不一致');
    const stream={...pack,frames,partial:false,sample_every:1,n_frames:frames.length,
      n_entities_max:frames.reduce((n,f)=>Math.max(n,f.entities?.length||0),0),
      provenance:frames.length&&frames.every(f=>f.provenance==='entity')?'entity':'aggregate',
      manifest:record.manifest,observations:record.observations,events:record.events};
    if(stream.provenance!==pack.provenance)stream.provenance_note=stream.provenance==='entity'?'主体位置/状态来自本次模型真实计算':'汇总观测用于指标演化示意';
    return {archive,stream};
  }
  async function restoreRun(id,revision,current) {
    const url=`/api/runs/${encodeURIComponent(id)}`,stateUrl=url+'/state';
    const pack=await api(stateUrl+'?sample_every=24');
    if(!current())return false;
    if(pack.run_id!==id)throw new Error('动画运行标识与档案不一致');
    const loading=$('#archiveLoading');
    // The smaller response contains verified saved frames. Paint it while the exact archive loads.
    pack.partial=true;
    loading.dataset.state='loading';loading.textContent=`已载入 ${pack.n_frames} / ${pack.total_frames} 状态帧 · 正在载入完整档案`;
    const exact=api(url).then(record=>({record}),error=>({error}));
    await showResult('run',{run_id:id,model_id:pack.model_id,stream:pack,observations:pack.observations,manifest:pack.manifest,state_url:stateUrl},
      {replaying:true,archivePending:true},revision);
    const {record,error}=await exact;
    // Edits to a draft may cancel auto-navigation. Finish an already visible archive in place.
    if(state.stream!==pack||state.runs[state.selected]?.run_id!==id)return false;
    try {
      if(error)throw error;
      const {archive,stream}=completeState(record,pack);
      state.events=DAYAN_ANALYSIS.savedEvents(stream);stream.events=state.events;
      Object.assign(state.runs[state.selected],archive,{stream});
      state.stream=stream;state.payload={...archive,state_url:stateUrl};
      state.context={replaying:true,intent:record.intent};
      state.question=record.request_text||state.question;
      $('#researchQuestion').textContent=state.question||'当前为已保存模型的实际运行。';
      if(!liveReading){DAYAN3D.completeArchive(stream);DAYAN3D.renderAt(state.time);}
      loading.dataset.state='ready';loading.hidden=true;
      paint();updateActions();
      if(current())await configurePolicies();
      return current();
    } catch(failure) {
      loading.dataset.state='error';loading.textContent='完整归档读取失败：'+failure.message+' ';
      const retry=document.createElement('button');retry.className='ws-button';retry.textContent='重读档案';
      retry.onclick=()=>restore(id).catch(e=>notice(e.message));loading.append(retry);
      setStatus('无法载入完整归档，当前仅可检查已取得的帧。','error');
      throw failure;
    }
  }
  async function restore(id) {
    const revision=++requestRevision;
    pendingRestore=revision;
    const current=()=>revision===requestRevision;
    try{
      let shown;
      if(/^R[0-9A-Za-z_-]+$/.test(id))shown=await restoreRun(id,revision,current);
      else {
        const record=await api(`/api/runs/${encodeURIComponent(id)}`);
        if(!current())return false;
        const context={intent:record.intent,replaying:true};
        if(record.kind==='analysis')shown=await showResult(record.tool,record.analysis,context,revision);
        else {const byArm=record.observations;shown=await showResult('experiment',{...record,experiment_id:record.run_id,observations_by_arm:byArm,observations:(byArm['基线']||[[]])[0]},context,revision);}
      }
      if(!shown||!current())return false;
      await globalThis.DAYAN_RESEARCH?.associateRun(id,current);
      return current();
    }finally{
      if(pendingRestore===revision)pendingRestore=null;
    }
  }
  async function loadReplay() {
    const response=await api("/api/history?limit=30"),el=$("#replayList");if(!el)return;
    el.innerHTML='<table class="modal-table"><thead><tr><th>模型/类型</th><th>时间</th><th>记录</th><th>操作</th></tr></thead><tbody>'+response.entries.map((e,i)=>`<tr><td>${esc(e.model_id)} · ${esc(e.source)}</td><td>${esc(new Date(e.created_at||e.ts).toLocaleString("zh-CN"))}</td><td>${e.complete?"完整归档":"旧记录，可能截断"}</td><td><button data-restore-record="${i}">回放</button></td></tr>`).join("")+"</tbody></table>";
    for(const button of el.querySelectorAll("button[data-restore-record]"))button.onclick=()=>{const e=response.entries[Number(button.dataset.restoreRecord)];if(e.complete)restore(e.run_id).catch(e=>notice(e.message));else{notice("此记录缺少完整状态，仅可回放已有观测，无法续算");const rows=e.observations||[];showResult("run",{...e,run_id:null,legacy_time_is_index:rows.some(o=>!finite(o.sim_t)),observations:rows},{intent:"旧记录汇总回放"}).then(()=>setPlaying(false)).catch(e=>notice(e.message));}};
    const bookmarks=JSON.parse(localStorage.getItem("dayan_bookmarks_v3")||"[]");
    if(bookmarks.length){const box=document.createElement("div");box.innerHTML='<h3>回放标记（已有运行的显示位置）</h3>'+bookmarks.map((b,i)=>`<button data-bookmark="${i}">${esc(b.run_id)} · sim_t=${fmt(b.sim_t)}</button>`).join(" ");el.prepend(box);for(const b of box.querySelectorAll("button"))b.onclick=async()=>{try{const marker=bookmarks[Number(b.dataset.bookmark)];await restore(marker.run_id);seek(marker.sim_t);}catch(e){notice(e.message);}};}
  }
  function savePendingJob(jobId,text) {try{sessionStorage.setItem('dayan_pending_job_v1',JSON.stringify({job_id:jobId,text}));}catch{}}
  function clearPendingJob(jobId) {try{const saved=JSON.parse(sessionStorage.getItem('dayan_pending_job_v1')||'null');if(saved?.job_id===jobId)sessionStorage.removeItem('dayan_pending_job_v1');}catch{}}
  let liveReading = null;
  function paintTaskSteps(host,job) {
    const stages=(job.stages||[]).slice(-6);
    const label={queued:'队列等待',running:'执行中的任务',done:'已取得执行结果',error:'任务中止'}[job.status]||job.status;
    const markup=`<div class="job-receipt"><b>${esc(label)}</b><code title="${esc(job.job_id)}">${esc(job.job_id)}</code>${stages.length?`<ol class="job-steps">${stages.map((stage,i)=>`<li ${i===stages.length-1&&job.status==='running'?'aria-current="step"':''}>${esc(stage)}</li>`).join('')}</ol>`:''}</div>`;
    if(host.innerHTML!==markup)host.innerHTML=markup;
    host.hidden=false;host.dataset.state=job.status;
  }
  function liveStatus(job) {
    const host = $('#liveCalculation');
    const reading = job.preview;
    if (host.dataset.jobId !== job.job_id) {
      host.dataset.jobId = job.job_id;
      host.innerHTML = '<div class="job-preview"><span>执行采样</span><b></b><button class="ws-button" data-cancel-job>取消</button></div><div class="job-stage-display"></div>';
      host.querySelector('button').dataset.cancelJob = job.job_id;
    }
    host.hidden = false;
    const note = job.status === 'queued' ? '等待工作进程'
      : reading ? `${reading.model_id} · t=${fmt(reading.frame.sim_t)} · 步 ${reading.step} / 请求 ${reading.requested_steps}${reading.entities_total ? ' · 主体 '+reading.frame.entities.length+' / '+reading.entities_total : ' · 汇总示意'}`
        : (job.stages || []).at(-1) || '等待第一帧';
    if (host.querySelector('.job-preview b').textContent !== note) host.querySelector('.job-preview b').textContent = note;
    paintTaskSteps(host.querySelector('.job-stage-display'),job);
    if (!reading || document.hidden || document.body.dataset.page !== 'overview') return;
    if (reading.sampled_at === liveReading?.sampled_at) return;
    state.playing = false;
    $('#playButton').disabled = $('#timeline').disabled = $('#stepBack').disabled = $('#stepForward').disabled = true;
    $('#sceneEmptyState').hidden = true;
    $('#sceneProvenance').textContent = '计算过程采样 · 正在等待正式归档';
    $('#simClock').textContent = 'sim_t='+fmt(reading.frame.sim_t);
    window.DAYAN3D?.preview(reading, liveReading?.preview_id !== reading.preview_id);
    liveReading = reading;
  }
  function endLive() {
    $('#liveCalculation').hidden = true;
    if (!liveReading) return;
    liveReading = null;
    if (state.stream) window.DAYAN3D.visualizeState(state.stream);
    else window.DAYAN3D.clear();
    window.DAYAN3D.renderAt(state.time);
    paint();
  }
  async function pollJob(jobId,update) {
    try {
      while (true) {
        const show = !document.hidden && document.body.dataset.page === 'overview';
        const job = await api('/api/jobs/'+encodeURIComponent(jobId)+(show?'?preview=true':''));
        update?.((job.stages||[]).at(-1)||(job.status==='queued'?'等待工作进程':'正在执行…'),job);
        if(job.status==='error'){const error=new Error(job.error||'执行失败');error.terminal=true;throw error;}
        if(job.status==='done'){if(!job.result)throw new Error('任务缺少完成结果');return job.result;}
        if(show)liveStatus(job);
        await new Promise(resolve=>setTimeout(resolve,show?630:1800));
      }
    } finally { endLive(); }
  }
  async function presentAssistantResult(result,text) {
      for(const row of result.summary||[])message(row);
      let published=false;
      for(const action of result.executed||[]){if(!action.ok)continue;const p=action.payload||{};for(const warning of p.warnings||[])message("提示："+warning);
        if(!result.ok&&['run','resume','build_model','experiment','ensemble','sweep','compare','compose'].includes(action.tool)){
          const item=message('部分结果已归档，本次需求仍未完整满足。');const button=document.createElement('button');button.className='ws-button';button.textContent='查看这条部分记录';button.onclick=()=>showResult(action.tool,p,{intent:result.intent,planner:result.planner,question:'未完整满足的请求 · '+text});item.appendChild(button);continue;
        }
        published=(await showResult(action.tool,p,{intent:result.intent,planner:result.planner,question:text}))||published;
      }
      if(!result.ok){message("本次请求未全部完成，请查看上面的具体原因。");setStatus('本次需求未完成；当前画面保留此前的归档结果。','error');}
      else if(!published)setStatus('解释已返回，引用的运行记录保持可追溯。');
      window._aiMsgs=[...(window._aiMsgs||[]),{role:'user',content:text},{role:'assistant',content:(result.summary||[]).join('\n')}];
  }
  async function watchAssistantJob(jobId,text,thinking) {
    let consumed=false;
    try{const result=await pollJob(jobId,(note,job)=>{thinking.textContent=note;setStatus(note,'working');paintTaskSteps($('#assistantTaskSteps'),job);});thinking.remove();await presentAssistantResult(result,text);consumed=true;}
    catch(error){thinking.remove();message('执行未完成：'+error.message);setStatus('执行未完成：'+error.message,'error');consumed=error.status===404||!!error.terminal;}
    finally{if(consumed)clearPendingJob(jobId);$('#aiSend').disabled=false;}
  }
  async function resumePendingJob() {
    let saved;try{saved=JSON.parse(sessionStorage.getItem('dayan_pending_job_v1')||'null');}catch{return;}
    if(!saved?.job_id||typeof saved.text!=='string')return;
    $('#aiSend').disabled=true;setPlaying(false);const thinking=message('正在恢复已有建模任务的实际状态…');
    await watchAssistantJob(saved.job_id,saved.text,thinking);
  }
  async function send() {
    const input=$('#aiInput'),text=input.value.trim();if(!text)return;if(window.DAYAN_NATIVE_BRIDGE){DAYAN_NATIVE_BRIDGE.draft(text);input.value='';return;}if($('#aiSend').disabled||window.DAYAN_COMMAND?.busy)return notice('当前任务仍在执行，新的草稿已保留。');input.value='';input.dispatchEvent(new Event('input'));message(text,'ai-user');$('#aiSend').disabled=true;
    const localAction=window.DAYAN_COMMAND?.assistantAction(text);
    if(localAction){try{const result=await localAction(),item=message(result.text);if(result.url){const link=document.createElement('a');link.href=result.url;link.download='';link.textContent=result.label;link.className='ws-button';item.appendChild(link);}window._aiMsgs=[...(window._aiMsgs||[]),{role:'user',content:text},{role:'assistant',content:result.text}];}catch(error){message('操作未完成：'+error.message);}finally{$('#aiSend').disabled=false;}return;}
    const last=window._lastRun,history=(window._aiMsgs||[]),thinking=message('正在校验需求与执行计划…');
    setPlaying(false);setStatus('正在处理新需求；当前画面仍为已保存的上一结果。','working');
    try{const job=await api('/api/agent',{text,history,last_run:last?.run_id?{model_id:last.model_id,run_id:last.run_id,params:last.params,ticks:last.ticks,seed:last.seed,dt:last.manifest?.requested?.dt,study_id:window.DAYAN_STUDY?.study_id}:{study_id:window.DAYAN_STUDY?.study_id},async_job:true});
      if(!job.job_id)throw new Error('未取得任务标识');savePendingJob(job.job_id,text);await watchAssistantJob(job.job_id,text,thinking);
    }catch(error){thinking.remove();message('提交未完成：'+error.message);setStatus('提交未完成：'+error.message,'error');$('#aiSend').disabled=false;}
  }
  function paintSourceMap(host, bbox, raw=null) {
    const lines=[],points=[];
    const point=p=>Array.isArray(p)&&finite(p[0])&&finite(p[1]);
    function geometry(shape) {
      const c=shape?.coordinates;
      if(shape?.type==='GeometryCollection') {for(const item of shape.geometries||[])geometry(item);return;}
      if(shape?.type==='Point'&&point(c))points.push(c);
      else if(shape?.type==='MultiPoint')for(const p of c||[]){if(point(p))points.push(p);}
      else if(shape?.type==='LineString')lines.push(c);
      else if(['MultiLineString','Polygon'].includes(shape?.type))for(const part of c||[])lines.push(part);
      else if(shape?.type==='MultiPolygon')for(const polygon of c||[])for(const part of polygon)lines.push(part);
    }
    if(raw?.type==='FeatureCollection')for(const feature of raw.features||[])geometry(feature.geometry);
    else geometry(raw?.geometry||raw);
    const queryBox=Array.isArray(bbox)&&bbox.length===4&&bbox.every(finite)&&bbox[0]<bbox[2]&&bbox[1]<bbox[3]?bbox:null;
    const extent=queryBox?[...queryBox]:[Infinity,Infinity,-Infinity,-Infinity];
    const include=p=>{if(point(p)){extent[0]=Math.min(extent[0],p[0]);extent[1]=Math.min(extent[1],p[1]);extent[2]=Math.max(extent[2],p[0]);extent[3]=Math.max(extent[3],p[1]);}};
    for(const line of lines)for(const p of line||[])include(p);
    for(const p of points)include(p);
    if(!extent.every(finite)){host.innerHTML='<p class="space-note">没有可绘制的来源坐标。</p>';return;}
    const [x0,y0,x1,y1]=extent, scale=Math.min(532/Math.max(1e-9,x1-x0),137/Math.max(1e-9,y1-y0));
    const x=p=>300+(p-(x0+x1)/2)*scale, y=p=>91-(p-(y0+y1)/2)*scale;
    const coordinates=(a,b)=>`${a.toFixed(5)}, ${b.toFixed(5)}`;
    const plotted=Math.min(lines.length,400)+Math.min(points.length,400), left=x(x0),right=x(x1),top=y(y1),bottom=y(y0);
    host.innerHTML=`<svg viewBox="0 0 600 184" aria-label="数据源坐标与查询范围" role="img"><path d="M${left} ${top}H${right}V${bottom}H${left}ZM${left} 91H${right}M300 ${top}V${bottom}" stroke="#365773" fill="none"/>
      ${queryBox?`<rect x="${x(queryBox[0])}" y="${y(queryBox[3])}" width="${x(queryBox[2])-x(queryBox[0])}" height="${y(queryBox[1])-y(queryBox[3])}" stroke="#a7b9ff" stroke-dasharray="4 5" fill="#37507733"/>`:''}
      ${lines.slice(0,400).map(line=>`<polyline stroke="#80e0e4" fill="none" points="${(line||[]).filter(point).map(p=>x(p[0]).toFixed(2)+','+y(p[1]).toFixed(2)).join(' ')}"/>`).join('')}
      ${points.slice(0,400).map(p=>`<circle cx="${x(p[0])}" cy="${y(p[1])}" r="2.2" fill="#82dfcc"/>`).join('')}
      <text x="${left}" y="${bottom+16}">${esc(coordinates(x0,y0))}</text><text x="${right}" y="${top-6}" text-anchor="end">${esc(coordinates(x1,y1))}</text></svg><p>${queryBox?'虚线为已登记查询范围。':''}${plotted?` 显示 ${plotted} / ${lines.length+points.length} 个坐标点或线部件。`:''} 按源坐标单位绘制。</p>`;
  }
  async function openDataManager(focusId=null) {
    const target=$('#dataWorkspace');if(!target)return;
    const revision=++datasetRevision;
    let selectedRevision=0;
    target.innerHTML=`<div class="data-import"><div class="data-input-row"><input id="datasetFile" type="file" accept=".csv,.json,.geojson" hidden><button class="ws-button" id="chooseDatasetFile" aria-describedby="datasetFileName">选择本地文件</button><output id="datasetFileName" aria-live="polite">CSV / JSON / GeoJSON</output><button class="ws-button" id="datasetUpload" disabled>导入</button></div><div class="data-input-row"><input id="datasetUrl" type="url" aria-label="公开HTTPS数据地址" placeholder="公开 HTTPS 数据地址"><select id="datasetFormat" aria-label="数据格式"><option value="json">JSON</option><option value="csv">CSV</option><option value="geojson">GeoJSON</option></select><button class="ws-button" id="datasetFetch">采集数据</button></div></div><div id="datasetStatus" class="data-status" role="status">正在读取已保存的数据…</div><div class="data-inspect-grid"><section class="dataset-catalog" aria-label="数据资产浏览器"><label>搜索资产<input id="datasetSearch" type="search" placeholder="名称、标识或来源"></label><label class="fixture-filter" id="fixtureFilter" hidden><input type="checkbox" id="showDatasetFixtures">显示验收数据</label><div id="datasetList" aria-label="数据资产"></div></section><section id="datasetAnalysis" aria-label="数据质量与来源"><p class="space-empty">选择数据资产查看字段、原始来源与映射。</p></section></div>`;
    const status=text=>{if(revision===datasetRevision)$('#datasetStatus').textContent=text;};let datasets=[];
    const verification=window.DAYAN_WORKBENCH.verificationDataset;
    const roleLabel=d=>verification(d)?'验收数据':({input:'模型输入',calibration:'校准输入',source_snapshot:'源快照',roads:'路网输入',population:'人口输入',initialization:'初始化数据',holdout_validation:'独立验证'}[d.role]||d.role);
    const chosen=$('#datasetFile');
    $('#chooseDatasetFile').onclick=()=>chosen.click();
    chosen.onchange=()=>{$('#datasetFileName').textContent=chosen.files[0]?.name||'CSV / JSON / GeoJSON';$('#datasetUpload').disabled=!chosen.files.length;};
    async function analyzeDataset(d,path='') {
      const selection=++selectedRevision;
      if(revision!==datasetRevision)return;
      status('正在统计完整数据…');
      if(!path&&d.format==='geojson'&&d.preview?.[0]?.type==='Feature')path='features';
      const result=await api(`/api/datasets/${d.dataset_id}?path=${encodeURIComponent(path)}`);
      d=result;
      const stats=result.analysis||{fields:[],numeric:{},n_rows:result.n_records},numeric=Object.entries(stats.numeric),run=state.runs[state.selected];
      const contract=run?(await api(`/api/models/contract/${run.model_id}?include_fidelity=false`)).contract:null;
      if(revision!==datasetRevision||selection!==selectedRevision)return;
      state.datasetFocus=d.dataset_id;
      for(const item of $('#datasetList').querySelectorAll('.dataset-row'))item.classList.toggle('selected',item.dataset.assetId===d.dataset_id);
      const metadata=d.metadata||{};
      const preview=Array.isArray(d.preview)?d.preview:[];
      const dates=stats.numeric.year||stats.numeric.date;
      const timeRange=metadata.time_range||(dates&&Number.isInteger(dates.min)&&Number.isInteger(dates.max)&&dates.min>=1000&&dates.max<=3000?`${dates.min}–${dates.max}`:null)||metadata.date||metadata.vintage||'来源未声明';
      const parents=Array.isArray(metadata.derived_from)?metadata.derived_from:[];
      const binding=(run?.manifest?.data_bindings||[]).find(b=>b.dataset_id===d.dataset_id&&b.sha256===d.sha256);
      const geo=d.format==='geojson'||Array.isArray(metadata.bbox);
      const source=String(d.source||'未登记'), sourceText=/^https?:\/\/[^\s]+$/.test(source)?`<a href="${esc(source)}" target="_blank" rel="noopener noreferrer">${esc(source)}</a>`:esc(source);
      const box=$('#datasetAnalysis');box.innerHTML=`<div class="dataset-hero" data-role="${esc(d.role)}"><span>${esc(roleLabel(d)||'数据资产')}</span><h3>${esc(d.name)}</h3><code>${esc(d.dataset_id)}</code><div class="data-quality"><div><span>${result.analysis?'完整记录数':'已定位记录'}</span><b>${stats.n_rows}</b></div><div><span>字段数</span><b>${result.analysis?stats.fields.length:'—'}</b></div><div><span>数值字段数</span><b>${result.analysis?numeric.length:'—'}</b></div><div><span>含非数值或缺失</span><b>${result.analysis?numeric.filter(([,v])=>v.missing_or_non_numeric>0).length:'—'}</b></div></div></div>
        <div class="dataset-lineage"><div><span>来源</span><p>${sourceText}</p></div><div><span>采集与上游</span><p>${esc(metadata.collection_id||parents.map(p=>p.dataset_id).join(' · ')||'独立归档')}</p></div><div><span>观测范围</span><p>${esc(timeRange)}${metadata.frequency?' · '+esc(metadata.frequency):''}</p></div></div>
        ${geo?`<section class="dataset-map"><div><h4>来源地图</h4>${d.format==='geojson'?'<button class="ws-button" id="datasetFullMap">绘制源文件几何</button>':''}</div><div id="datasetMapShape"></div></section>`:''}
        <h4>数值字段质量</h4><div class="dataset-quality-tracks">${numeric.map(([field,v])=>`<div><code>${esc(field)}</code><meter min="0" max="${Math.max(1,stats.n_rows)}" value="${v.n}" aria-label="${esc(field)} 有效记录"></meter><span>${v.n} / ${stats.n_rows}</span></div>`).join('')||'<p class="space-note">当前记录未导出可统计的数值字段。</p>'}</div><details class="tool-detail"><summary>展开字段统计</summary><div class="table-scroll"><table class="data-stat-table"><thead><tr><th>字段</th><th>有效数</th><th>缺失/非数值</th><th>最小</th><th>最大</th><th>均值</th></tr></thead><tbody>${stats.fields.map(k=>{const v=stats.numeric[k];return v?`<tr><td>${esc(k)}</td><td>${v.n}</td><td>${v.missing_or_non_numeric}</td><td>${fmt(v.min)}</td><td>${fmt(v.max)}</td><td>${fmt(v.mean)}</td></tr>`:`<tr><td>${esc(k)}</td><td colspan="5">未识别为可统计的数值字段</td></tr>`;}).join('')}</tbody></table></div></details>`;
      if(geo)paintSourceMap($('#datasetMapShape'),metadata.bbox);
      if($('#datasetFullMap'))$('#datasetFullMap').onclick=async e=>{
        const button=e.currentTarget;button.disabled=true;
        try{const raw=await api(`/api/datasets/${encodeURIComponent(d.dataset_id)}/original`);
          if(revision===datasetRevision&&selection===selectedRevision)paintSourceMap($('#datasetMapShape'),metadata.bbox,raw);
        }catch(error){status('源地图读取未完成：'+error.message);}finally{button.disabled=false;}
      };
      box.insertAdjacentHTML('beforeend',`<details class="tool-detail data-preview" open><summary>来源、范围与样本</summary>
        <dl class="fact-list"><dt>许可</dt><dd>${esc(d.license||'未提供')}</dd><dt>地理覆盖</dt><dd>${esc(metadata.scope||metadata.bbox||'来源未声明')}</dd><dt>版本 / 角色</dt><dd><code>${esc(d.sha256)}</code> · ${esc(roleLabel(d))}</dd>
        ${metadata.transform?`<dt>转换</dt><dd>${esc(typeof metadata.transform==='string'?metadata.transform:Object.entries(metadata.transform).map(([k,v])=>k+' '+v).join(' · '))}</dd>`:''}${parents.length?`<dt>父版本</dt><dd class="tag-row">${parents.map(p=>`<button class="ws-button" data-open-dataset="${esc(p.dataset_id)}" title="${esc(p.sha256)}">${esc(p.dataset_id)} ↗</button>`).join('')}</dd>`:''}</dl>
        <pre aria-label="原始数据样本">${esc(preview.length?JSON.stringify(preview,null,2):'当前文件结构没有可自动定位的记录样本')}</pre></details>`);
      if(binding)box.insertAdjacentHTML('beforeend',`<div class="dataset-binding"><strong>当前运行已使用该版本</strong><span>${esc(run.model_id)} · ${esc(binding.port||binding.parameter||binding.role)}</span><button class="ws-button" data-open-run="${esc(run.run_id)}">查看同源运行 ↗</button></div>`);
      const admitted=['input','initialization','calibration','exogenous_input','mechanism_estimation'].includes(d.role)&&!verification(d);
      if(run?.run_id&&run.manifest?.requested&&contract&&numeric.length&&admitted){box.insertAdjacentHTML('beforeend',`<h4>将数据用于 ${esc(run.model_id)}</h4><div class="binding-controls"><label>字段<select id="bindingField">${numeric.map(([k])=>`<option>${esc(k)}</option>`).join('')}</select></label><label>汇总方式<select id="bindingAggregate">${[['last','末值'],['first','首值'],['mean','均值'],['sum','总和'],['min','最小值'],['max','最大值']].map(([v,n])=>`<option value="${v}">${n}</option>`).join('')}</select></label><label>模型参数<select id="bindingParameter">${Object.entries(contract.params).filter(([k,v])=>['float','int'].includes(v.type)).map(([k])=>`<option>${esc(k)}</option>`).join('')}</select></label><label>换算系数<input id="bindingScale" type="number" value="1" step="any"></label><label>源单位<input id="bindingSourceUnit" value="${esc(d.metadata?.unit||'')}" placeholder="例如 %"></label><label>目标参数单位<input id="bindingTargetUnit" placeholder="例如 fraction"></label><label>源地区/主体范围<input id="bindingSourceScope" value="${esc(d.metadata?.scope||'')}"></label><label>目标地区/主体范围<input id="bindingTargetScope" placeholder="本次研究对象"></label><button class="ws-button ws-primary" id="runWithDataset">按映射创建新运行</button></div><p id="bindingPreview" class="data-status"></p>`);
        const preview=()=>{const field=$('#bindingField').value,aggregate=$('#bindingAggregate').value,v=stats.numeric[field],scale=Number($('#bindingScale').value);$('#bindingPreview').textContent=`${field} 的${$('#bindingAggregate option:checked').textContent} ${fmt(v[aggregate])} × ${fmt(scale)} → ${$('#bindingParameter').value} = ${fmt(v[aggregate]*scale)}${v.missing_or_non_numeric?'；含缺失/非数值，不能直接映射':''}`;$('#runWithDataset').disabled=Boolean(v.missing_or_non_numeric)||!finite(scale);};
        for(const id of ['#bindingField','#bindingAggregate','#bindingParameter','#bindingScale'])$(id).addEventListener('input',preview);preview();
        $('#runWithDataset').onclick=async()=>{const button=$('#runWithDataset');button.disabled=true;try{const parameter=$('#bindingParameter').value,parameters={...(run.manifest?.actual?.effective_parameters||{})};delete parameters[parameter];
          const result=await api('/api/run',{model_id:run.model_id,parameters,ticks:run.manifest.requested.ticks,dt:run.manifest.requested.dt,seed:run.manifest.rng.seed,data_bindings:[{dataset_id:d.dataset_id,path,field:$('#bindingField').value,aggregate:$('#bindingAggregate').value,parameter,scale:Number($('#bindingScale').value),...Object.fromEntries([['source_unit','#bindingSourceUnit'],['target_unit','#bindingTargetUnit'],['source_scope','#bindingSourceScope'],['target_scope','#bindingTargetScope']].map(([key,id])=>[key,$(id).value.trim()]).filter(([,value])=>value))}]});
          await showResult('run',result,{intent:'输入数据映射',question:state.question||`用导入数据研究 ${run.model_id}`});
        }catch(error){status('映射未完成：'+error.message);button.disabled=false;}};
      }else if(admitted)box.insertAdjacentHTML('beforeend','<p class="data-status">选择并运行适用模型后，可将数值字段映射至参数。</p>');
      status(result.analysis_error?'字段统计需要指明记录路径：'+result.analysis_error:'统计已完成，来源为完整导入数据。');
    }
    function paintDatasets(){
      const box=$('#datasetList'), search=$('#datasetSearch').value.trim().toLowerCase();
      const rows=datasets.filter(d=>(!verification(d)||$('#showDatasetFixtures').checked)&&`${d.name} ${d.dataset_id} ${d.source}`.toLowerCase().includes(search));
      box.innerHTML=rows.map((d,i)=>`<article class="dataset-row ${state.datasetFocus===d.dataset_id?'selected':''}" data-asset-id="${esc(d.dataset_id)}"><div><strong>${esc(d.name)}</strong><small>${esc(roleLabel(d))} · ${esc(d.dataset_id)}</small></div><div class="dataset-actions"><button class="ws-button" data-analyze-dataset="${i}">查看分析</button><a class="ws-button" href="${esc(d.data_url)}" download>原始文件</a>${d.format==='csv'?'':`<details><summary>指定 JSON 记录路径</summary><input data-json-path="${i}" aria-label="${esc(d.name)}的JSON记录路径" placeholder="顶层数组时留空"></details>`}</div></article>`).join('')||'<p class="data-status">没有匹配的研究资产。</p>';
      for(const button of box.querySelectorAll('[data-analyze-dataset]'))button.onclick=async()=>{const i=Number(button.dataset.analyzeDataset);try{await analyzeDataset(rows[i],box.querySelector(`[data-json-path="${i}"]`)?.value||'');}catch(error){status('分析未完成：'+error.message);}};
    }
    async function refresh(){
      datasets=(await api('/api/datasets')).datasets||[];if(revision!==datasetRevision)return;
      $('#fixtureFilter').hidden=!datasets.some(verification);
      if(datasets.some(d=>d.dataset_id===focusId&&verification(d))) $('#showDatasetFixtures').checked=true;
      paintDatasets();
      status(`已保存 ${datasets.filter(d=>!verification(d)).length} 个研究数据资产。`);
    }
    $('#datasetSearch').oninput=$('#showDatasetFixtures').onchange=paintDatasets;
    $('#datasetUpload').onclick=async()=>{const button=$('#datasetUpload');button.disabled=true;try{
      const file=$('#datasetFile').files[0];if(!file)throw new Error('请先选择文件');if(file.size>10*1024*1024)throw new Error('文件超过10MiB');const bytes=new Uint8Array(await file.arrayBuffer());new TextDecoder('utf-8',{fatal:true}).decode(bytes);
      let binary='';for(let i=0;i<bytes.length;i+=16384)binary+=String.fromCharCode(...bytes.subarray(i,i+16384));status('正在保存原始文件…');
      const d=await api('/api/datasets/import',{name:file.name,format:file.name.toLowerCase().endsWith('.csv')?'csv':file.name.toLowerCase().endsWith('.geojson')?'geojson':'json',content_base64:btoa(binary),source:'用户导入：'+file.name});await refresh();await analyzeDataset(d);chosen.value='';chosen.onchange();
    }catch(error){status('导入未完成：'+error.message);}finally{button.disabled=!chosen.files.length;}};
    $('#datasetFetch').onclick=async()=>{const button=$('#datasetFetch');button.disabled=true;try{status('正在采集外部数据…');const d=await api('/api/datasets/collect',{url:$('#datasetUrl').value,format:$('#datasetFormat').value});await refresh();await analyzeDataset(d);}catch(error){status('采集未完成：'+error.message);}finally{button.disabled=false;}};
    await refresh();if(focusId){const d=datasets.find(d=>d.dataset_id===focusId);if(d)await analyzeDataset(d);}
  }
  Object.assign(controller,{setPlaying,seek,clear,paint,showResult,restore,applyPolicy,loadReplay,openDataManager,select,generateReport,send,pollJob,dockInspector,
    cancelPendingView:()=>{requestRevision++;},
    hasPendingView:()=>pendingRestore!==null&&pendingRestore===requestRevision,
    addEvent:(type,title,desc)=>{setStatus([title,desc].filter(Boolean).join(' · '));},
    tick(ts){const wasPlaying=state.playing;if(state.lastWall!==null&&state.playing){const next=state.time+(ts-state.lastWall)/1000*state.rate;if(next>=state.end){if(state.loop&&state.end>state.start)state.time=state.start+(next-state.start)%(state.end-state.start);else{state.time=state.end;setPlaying(false);}}else state.time=next;}state.lastWall=ts;if(wasPlaying&&ts-lastPaint>80){paint();lastPaint=ts;}}});
  function boot() {
    DAYAN_ANALYSIS.bind(state,paint,notice);
    inspectorAnchor=document.createComment('主体分析默认位置');$('#entityPanel').before(inspectorAnchor);
    $('#entityPanel .panel-head').insertAdjacentHTML('beforeend','<button id="closeInspector" aria-label="关闭主体检查器" hidden>关闭 ×</button>');
    $('#entityPanel').insertAdjacentHTML('beforeend','<div id="inspectorEvidence" hidden></div>');
    const leaveInspector=()=>window.DAYAN_COMMAND?.selectRail(window.DAYAN_COMMAND.mode==='professional'?'parameters':'ai');
    $('#closeInspector').onclick=leaveInspector;
    $('#inspectorEvidence').onclick=e=>{
      const hit=e.target.closest('[data-related-entity],[data-inspect-time]');if(!hit)return;
      if(hit.dataset.relatedEntity!==undefined){state.entityId=hit.dataset.relatedEntity;state.entityField='';DAYAN3D.selectEntity(state.entityId);paint();}
      else {setPlaying(false);seek(Number(hit.dataset.inspectTime));}
    };
    document.addEventListener('dayan:entity-selected',()=>window.DAYAN_COMMAND?.selectRail('inspector'));
    $('#loopPlayback').onchange=e=>{state.loop=e.target.checked;};
    $('#sceneProcess').onclick=()=>window.DAYAN_CHARTS.renderProcess(state);
    $('#resetCamera').onclick=()=>window.DAYAN3D?.resetCamera();
    for(const b of document.querySelectorAll('[data-camera-preset]'))b.onclick=()=>window.DAYAN3D?.setCameraPreset(b.dataset.cameraPreset);
    document.addEventListener('dayan:camera-pose',e=>{
      for(const b of document.querySelectorAll('#resetCamera,[data-camera-preset]'))b.setAttribute('aria-pressed',String((b.dataset.cameraPreset||'fit')===e.detail));
    });
    for(const b of document.querySelectorAll('[data-scene-toggle]'))b.onclick=()=>{
      const visible=b.getAttribute('aria-pressed')!=='true';b.setAttribute('aria-pressed',String(visible));
      if(b.dataset.sceneToggle==='labels')$('#mapViewport').classList.toggle('hide-scene-labels',!visible);
      window.DAYAN3D?.setSceneLayer(b.dataset.sceneToggle,visible);paintSceneDiagnostics();
    };
    $('#sceneDebug').onclick=()=>{
      const host=$('#sceneDebugInfo');host.hidden=!host.hidden;$('#sceneDebug').setAttribute('aria-expanded',String(!host.hidden));paintSceneDiagnostics();
    };
    const view=immersive=>{
      document.body.classList.toggle('view-immersive',immersive);
      for(const b of document.querySelectorAll('[data-workspace-view]'))b.setAttribute('aria-pressed',String((b.dataset.workspaceView==='immersive')===immersive));
      window.dispatchEvent(new Event('resize'));paint();
    };
    for(const b of document.querySelectorAll('[data-workspace-view]'))b.onclick=()=>view(b.dataset.workspaceView==='immersive');
    const livePanel=$('.live-panel');
    $('#sceneFullscreen').onclick=async()=>{
      try{if(document.fullscreenElement===livePanel)await document.exitFullscreen();else await livePanel.requestFullscreen();}
      catch{view(!document.body.classList.contains('view-immersive'));}
    };
    document.addEventListener('fullscreenchange',()=>{
      const active=document.fullscreenElement===livePanel;
      $('#sceneFullscreen').textContent=active?'退出全屏':'场景全屏';$('#sceneFullscreen').setAttribute('aria-pressed',String(active));
      window.dispatchEvent(new Event('resize'));paint();
    });
    document.addEventListener('keydown',e=>{
      if(e.key!=='Escape'||document.fullscreenElement||document.body.dataset.page!=='overview'||$('.modal-backdrop.open'))return;
      if(inspectorOpen)leaveInspector();else if(document.body.classList.contains('view-immersive'))view(false);
    });
    window.addEventListener('resize',()=>{if(inspectorOpen)dockInspector(true);});
    document.querySelectorAll('[data-layer]').forEach(button=>button.addEventListener('click',()=>selectLayer(button.dataset.layer)));
    document.querySelectorAll(".weather").forEach(el=>el.style.display="none");
    $("#configButton").addEventListener("click",e=>{e.stopImmediatePropagation();showEvidence();},true);
    $("#reportButton").onclick=()=>generateReport().catch(()=>{});
    $("#resumeButton").onclick=resumeDialog;
     $("#dataManagerButton").onclick=()=>{navigate("data");};
    $("#helpButton")?.addEventListener("click",e=>{e.stopImmediatePropagation();modal("研究工作台说明","<p>先描述需求或选择模型。每次计算保存独立run_id，动画、数值、原始数据与报告引用该记录。</p><p>暂停、倍速和时间轴只改变回放，不会重新运行模型。模型干预仅支持合同中声明的可变参数。</p><p>个体状态和汇总示意明确区分；旧记录可能截断，不能冒充完整实验。</p>");},true);
    const footer=document.querySelector("footer");if(footer){const label=footer.children[1];if(label){label.textContent="正在读取登记运行入口…";api("/api/models/runnable").then(r=>{label.textContent=`${r.count}个登记运行入口（包含原型与方法例题）`;}).catch(()=>{label.textContent="运行入口暂未读取";});}}
    $("#playButton").addEventListener("click",e=>{e.stopImmediatePropagation();setPlaying(!state.playing);},true);
    $("#resetButton").addEventListener("click",e=>{e.stopImmediatePropagation();setPlaying(false);seek(state.start);},true);
    for(const [id,delta] of [['#stepBack',-1],['#stepForward',1]]) $(id).onclick=()=>{
      const rows=state.runs[state.selected]?.observations||[];
      const next=rows[at(rows,state.time)+delta];if(!next)return;
      setPlaying(false);seek(next.sim_t);
    };
    $("#timeline").addEventListener("input",e=>{
      e.stopImmediatePropagation();
      const position=Number(e.currentTarget.value);
      setPlaying(false,false);
      seek(position);
    },true);
    document.querySelectorAll("[data-speed]").forEach(b=>{b.classList.toggle("selected",Number(b.dataset.speed)===state.rate);b.addEventListener("click",e=>{e.stopImmediatePropagation();state.rate=Number(b.dataset.speed);document.querySelectorAll("[data-speed]").forEach(x=>x.classList.toggle("selected",x===b));},true);});
    $("#trackAgent").addEventListener("click",e=>{e.stopImmediatePropagation();if(inspectorOpen){leaveInspector();return;}window.DAYAN_COMMAND?.selectRail('inspector');$('#entitySelect').focus({preventScroll:true});},true);
    $("#snapshotButton").addEventListener("click",e=>{e.stopImmediatePropagation();const r=state.runs[state.selected];if(!r)return notice("没有可保存的运行");const a=JSON.parse(localStorage.getItem("dayan_bookmarks_v3")||"[]");a.push({run_id:r.run_id,sim_t:state.time});localStorage.setItem("dayan_bookmarks_v3",JSON.stringify(a));notice("已保存回放标记；标记不代表可续算检查点");},true);
    window.aiSend=send;
    window.runFromCatalog=async mid=>{try{if(window.DAYAN_COMMAND){await DAYAN_COMMAND.chooseModel(mid);return;}const r=await api("/api/run",{model_id:mid,ticks:100});await showResult("run",r,{intent:"模型资源运行"});switchPage("overview");}catch(e){notice(e.message);}};
    window.loadReplayPage=()=>loadReplay().catch(e=>notice(e.message));
    window.DAYAN_APPLY_INTERVENTION=applyPolicy;
    window.DAYAN_HIST_RESTORE=async i=>{const r=window._histEntries?.[i];if(r?.run_id)await restore(r.run_id);};
    clear();updateActions();
    const context=new URLSearchParams(location.search),recordId=context.get("run");
    const restored=recordId?restore(recordId).catch(error=>{setStatus("未能读取指定研究记录："+error.message,"error");}):Promise.resolve();
    if(context.get('embed')!=='dsh')restored.then(resumePendingJob);
  }
  function navigate(name){return switchPage(name);}
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",boot);else boot();
})();
