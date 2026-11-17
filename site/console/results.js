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
  let lastPaint = 0, requestRevision = 0, controls = [];

  function notice(text) { if (window.DAYAN_NOTICE) DAYAN_NOTICE(text); else message(text); }
  function modal(title, html) { if (window.DAYAN_MODAL) DAYAN_MODAL(title, html); }
  function setPlaying(value) {
    if (value && state.time >= state.end && state.end > state.start) state.time = state.start;
    state.playing = Boolean(value && state.runs.length && state.end > state.start);
    state.lastWall = null;
    $("#playButton").textContent = state.playing ? "Ⅱ" : "▶";
    $("#playButton").setAttribute("aria-label", state.playing ? "暂停回放" : "播放回放");
    document.body.classList.toggle("paused", !state.playing);
    const live=$(".live");if(live)live.innerHTML='<i></i>'+(state.playing?"回放中":"已暂停");
    const tiny=$(".tiny-live");if(tiny)tiny.innerHTML='<i class="dot"></i>'+(state.playing?(state.runs[state.selected]?.run_id?"已保存状态回放中":"观测回放中"):"回放已暂停");
    if (window.DAYAN3D) state.playing ? DAYAN3D.resume() : DAYAN3D.pause();
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
    $('#playButton').disabled=!run||state.end<=state.start;$('#timeline').disabled=!run||state.end<=state.start;$('#resetButton').disabled=!run;$('#loopPlayback').disabled=!run;
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
    const context=[...document.querySelectorAll('.scenario-strip .context>span')];
    if(context[0])context[0].textContent=run?(entities.length?entities.length+' 个模型主体':'汇总模型'):'暂无运行';
    if(context[1])context[1].textContent=(frame?.space?.time_unit?.includes('观测序号')?'观测序号 ':'模型时间 ')+fmt(state.start)+'–'+fmt(state.end);
    if(context[2])context[2].textContent='当前种子 '+(run?.manifest?.rng?.seed??'—');
    $('.scene-status .micro').textContent=run?.model_id||'无运行';
    const labels=document.querySelectorAll('.timeline-labels>span');labels[0].textContent=fmt(state.start);labels[labels.length-1].textContent=fmt(state.end);
    const events=state.events.filter(e=>(e.sim_t??0)<=state.time+1e-9),key=(run?.run_id||'')+':'+events.length;
    $('#eventCounter').textContent=events.length;
    if(state.eventPaintKey!==key){state.eventPaintKey=key;
      $('#eventList').innerHTML=events.slice(-30).reverse().map(e=>`<div class="event-item"><i class="event-dot"></i><time>${fmt(e.sim_t)}</time><div><b>${esc(e.label||e.etype||'模型记录')}</b><p>${esc((typeof e.message==='string'?e.message:JSON.stringify(e.params||e.decision||Object.fromEntries(Object.entries(e).filter(([k])=>!['sim_t','etype'].includes(k))))).slice(0,600))}</p><button class="event-seek" data-event-time="${e.sim_t}">定位此时刻 ↗</button></div></div>`).join('')||'<div class="empty-events">当前没有已记录的模型事件。</div>';
      document.querySelectorAll('[data-event-time]').forEach(b=>b.onclick=()=>{setPlaying(false);seek(Number(b.dataset.eventTime));});
      $('.timeline-ticks').innerHTML=state.events.filter(e=>finite(e.sim_t)&&e.sim_t>=state.start&&e.sim_t<=state.end).map(e=>`<button class="event-tick" aria-label="${esc(e.label||e.etype)}，模型时间${e.sim_t}" data-timeline-event="${e.sim_t}" style="left:${100*(e.sim_t-state.start)/Math.max(1e-12,state.end-state.start)}%"></button>`).join('');
      document.querySelectorAll('[data-timeline-event]').forEach(b=>b.onclick=()=>{setPlaying(false);seek(Number(b.dataset.timelineEvent));});
    }
    $('footer>span').textContent=run?`${run.model_id} · ${rows.length}条观测 · ${state.stream?.frames?.length||0}帧 · ${run.run_id?'已保存':'旧观测，无完整状态归档'}`:'等待首次仿真';
    window._lastRun=run?{model_id:run.model_id,run_id:run.run_id,observations:rows,params:run.manifest?.actual?.effective_parameters||run.manifest?.actual?.parameters||{},seed:run.manifest?.rng?.seed,ticks:run.manifest?.requested?.ticks,manifest:run.manifest}:null;
    window._obsData=run?{names:[state.metric],series:[rows.map(o=>o[state.metric])],n:rows.length,times:rows.map(o=>o.sim_t)}:null;
    DAYAN_ANALYSIS.render(state);
    window.DAYAN_COMMAND?.paint(state);
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
    const revision=++requestRevision,selected=Number(index),run=state.runs[selected];
    if(!run)return;const previousTime=state.time,previousPlaying=state.playing;setPlaying(false);
    const pack=run.stream||(run.run_id?await api(`/api/runs/${encodeURIComponent(run.run_id)}/state?sample_every=1`):observationOnlyStream(run));
    if(revision!==requestRevision)return;
    if(pack&&run.run_id&&pack.run_id!==run.run_id)throw new Error('动画运行标识与结果不一致，已停止显示');
    state.selected=selected;state.stream=pack;state.followEntity=false;
    state.events=[...(pack?.events||[]),...(pack?.manifest?.interventions||[]).filter(i=>i.applied).map(i=>({etype:'intervention',label:i.label||'参数干预生效',sim_t:i.actual_t,params:i.params}))];state.eventPaintKey=null;
    if(pack){run.stream=pack;run.observations=pack.observations;run.manifest=pack.manifest;DAYAN3D.visualizeState(pack);}
    state.start=Math.min(...state.runs.map(r=>r.observations[0]?.sim_t??0));state.end=Math.max(...state.runs.map(r=>r.observations.at(-1)?.sim_t??0));
    state.time=options.fresh?state.start:Math.min(state.end,Math.max(state.start,previousTime));
    const metrics=fields(run.observations);
    state.metric=metrics.includes(state.metric)?state.metric:(['flux','I','I_total','gini','evacuated','k'].find(k=>metrics.includes(k))||metrics[0]);
    if(options.fresh){state.windowMode=DAYAN_ANALYSIS.interventionTime(state)!==null?'post':'all';state.customWindow=null;state.entityId='';state.entityField='';state.distributionField='';}
    if(options.fresh&&pack?.frames?.[0]?.entities?.length){const first=pack.frames[0].entities[0];state.entityId=String(first.id);state.entityField=finite(first.speed)?'speed':finite(first.x)?'x':'';}
    renderSelectors(metrics);await configurePolicies();if(revision!==requestRevision)return;paint();
    if(window.DAYAN3D?.renderAt)DAYAN3D.renderAt(state.time);
    if(options.fresh&&state.entityId)window.DAYAN3D?.selectEntity(state.entityId);
    setPlaying(options.fresh?true:previousPlaying);
    updateActions();
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
  async function showResult(tool,p,context={}) {
    if(p.run_id&&globalThis.DAYAN_STUDY?.run_id&&p.run_id!==globalThis.DAYAN_STUDY.run_id)globalThis.DAYAN_RESEARCH?.clearContext();
    if(p.archive_only){const id=p.experiment_id||p.analysis_id||p.run_id;if(id){await restore(id);if(context.question){state.question=context.question;$('#researchQuestion').textContent=context.question;$('#scenarioTitle').textContent=context.question.slice(0,70);}return true;}if(p.dataset_id){navigate('data');await openDataManager(p.dataset_id);return true;}return false;}
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
    state.active=true;state.kind=tool;state.payload=p;state.runs=runs;state.metric=p.primary_metric||p.analysis?.metric||null;
    window._chartMode=tool;window._dashModel=true;document.body.classList.add("model-results-active");
    document.querySelectorAll(".weather").forEach(el=>el.style.display="none");
    $("#scenarioTitle").textContent=`${p.model_id||runs[0].model_id} · ${labels[context.intent]||context.intent||labels[tool]||tool}`;
    const tag=$(".scenario-name .tag");if(tag)tag.textContent="模型回放";
    let savedQuestions={};try{savedQuestions=JSON.parse(localStorage.getItem('dayan_research_questions_v1')||'{}');}catch{}
    const key=p.experiment_id||p.analysis_id||runs[0].run_id;
    state.context=context;state.question=context.question||savedQuestions[key]||p.request_text||p.research_spec?.question||p.experiment_spec?.hypothesis||p.intent||"";
    if(state.question&&key){savedQuestions[key]=state.question;const entries=Object.entries(savedQuestions).slice(-80);try{localStorage.setItem('dayan_research_questions_v1',JSON.stringify(Object.fromEntries(entries)));}catch{}}
    $("#researchQuestion").textContent=state.question||"当前为已保存模型的实际运行；可通过 AI 助手继续描述研究问题。";
    if(context.question)$("#scenarioTitle").textContent=context.question.length>70?context.question.slice(0,70)+"…":context.question;
    const code=$(".scenario-strip .code");if(code)code.textContent=(p.experiment_id?"EXPERIMENT":"RESEARCH")+" / "+(p.model_id||runs[0].model_id);
    navigate("overview");await select(0,{fresh:true});addDownloadLinks(p,runs[0],context);return true;
  }
  function addDownloadLinks() { updateActions(); }
  function setStatus(text,kind='ready') {
    $('#workspaceStatus').textContent=text;$('#workspaceStatus').dataset.state=kind;
  }
  async function generateReport() {
    const run=state.runs[state.selected];if(!run?.run_id)return notice('请选择有完整归档的运行。');
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
    const run=state.runs[state.selected],p=state.payload||{};
    const bundleId=p.experiment_id||p.analysis_id||run?.run_id;
    for(const [id,url] of [['#exportCsv',run?.run_id?`/api/runs/${run.run_id}/observations.csv`:null],['#exportBundle',bundleId?`/api/runs/${bundleId}/bundle.zip`:null]]){
      const link=$(id);link.setAttribute('aria-disabled',String(!url));if(url){link.href=url;link.download='';}else link.removeAttribute('href');
    }
    $('#reportButton').disabled=!run?.run_id;$('#resumeButton').disabled=!run?.run_id||!run?.manifest?.checkpoint?.resumable;
    setStatus(run?(run.run_id?'结果已保存；动画与分析使用同一运行记录。':'旧记录仅回放已有观测；不具备完整主体状态与续算依据。'):'等待研究任务');
  }
  async function applyPolicy() {
    const run=state.runs[state.selected];if(!run)throw new Error("请先运行模型");const m=run.manifest,changes={},when=Number($("#policyAt").value);
    if(!finite(when)||when<state.start||when>=state.end)throw new Error("干预时间必须在运行终点之前");
    for(const input of document.querySelectorAll("input[data-policy]")){const name=input.dataset.policy,value=Number(input.value),original=policyValue(run,name,when);if(Math.abs(value-original)>1e-12)changes[name]=value;}
    if(!Object.keys(changes).length)throw new Error("参数没有变化，未创建干预实验");
    $("#applyPolicy").disabled=true;
    const common=(m.interventions||[]).filter(i=>i.applied).map(i=>({at_t:i.requested_t,params:i.params,label:i.label}));
    const bindings=(m.data_bindings||[]).filter(b=>b.parameter).map(b=>Object.fromEntries(Object.entries(b).filter(([k])=>["dataset_id","path","field","aggregate","parameter","scale"].includes(k))));
    const body={model_id:run.model_id,baseline_params:m.requested.parameters,baseline_interventions:common,data_bindings:bindings,ticks:m.requested.ticks,dt:m.requested.dt,seeds:[m.rng.seed],rng_domain:m.rng.experiment,purpose:"policy",primary_metric:state.metric,title:"明确参数的配对干预",arms:[{label:"干预组",params:{},interventions:[{at_t:when,params:changes,label:"用户参数干预"}]}]};
      try{const p=await api("/api/experiments",body);await showResult("experiment",p,{intent:"用户设置的配对干预",question:state.question});}finally{if($("#applyPolicy"))$("#applyPolicy").disabled=!controls.length;}
  }
  async function restore(id) {
    const record=await api(`/api/runs/${encodeURIComponent(id)}`);
    if(record.kind==="run")await showResult("run",{...record,state_url:`/api/runs/${id}/state`},{intent:record.intent});
    else if(record.kind==="analysis")await showResult(record.tool,record.analysis,{intent:record.intent});
    else {const byArm=record.observations;await showResult("experiment",{...record,experiment_id:record.run_id,observations_by_arm:byArm,observations:(byArm["基线"]||[[]])[0]},{intent:record.intent});}
    setPlaying(false);navigate("overview");
    await globalThis.DAYAN_RESEARCH?.associateRun(id);
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
  async function pollJob(jobId,thinking) {
    while(true){const job=await api('/api/jobs/'+encodeURIComponent(jobId));thinking.textContent=(job.stages||[]).at(-1)||'正在执行…';setStatus(thinking.textContent,'working');
      if(job.status==='error'){const error=new Error(job.error||'执行失败');error.terminal=true;throw error;}
      if(job.status==='done'){if(!job.result)throw new Error('任务缺少完成结果');return job.result;}
      await new Promise(resolve=>setTimeout(resolve,600));
    }
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
    try{const result=await pollJob(jobId,thinking);thinking.remove();await presentAssistantResult(result,text);consumed=true;}
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
    const input=$('#aiInput'),text=input.value.trim();if(!text)return;if(window.DAYAN_NATIVE_BRIDGE){DAYAN_NATIVE_BRIDGE.draft(text);input.value='';return;}if($('#aiSend').disabled||window.DAYAN_COMMAND?.busy)return notice('当前任务仍在执行，新的草稿已保留。');input.value='';message(text,'ai-user');$('#aiSend').disabled=true;
    const localAction=window.DAYAN_COMMAND?.assistantAction(text);
    if(localAction){try{const result=await localAction(),item=message(result.text);if(result.url){const link=document.createElement('a');link.href=result.url;link.download='';link.textContent=result.label;link.className='ws-button';item.appendChild(link);}window._aiMsgs=[...(window._aiMsgs||[]),{role:'user',content:text},{role:'assistant',content:result.text}];}catch(error){message('操作未完成：'+error.message);}finally{$('#aiSend').disabled=false;}return;}
    const last=window._lastRun,history=(window._aiMsgs||[]),thinking=message('正在校验需求与执行计划…');
    setPlaying(false);setStatus('正在处理新需求；当前画面仍为已保存的上一结果。','working');
    try{const job=await api('/api/agent',{text,history,last_run:last?.run_id?{model_id:last.model_id,run_id:last.run_id,params:last.params,ticks:last.ticks,seed:last.seed,dt:last.manifest?.requested?.dt,study_id:window.DAYAN_STUDY?.study_id}:{study_id:window.DAYAN_STUDY?.study_id},async_job:true});
      if(!job.job_id)throw new Error('未取得任务标识');savePendingJob(job.job_id,text);await watchAssistantJob(job.job_id,text,thinking);
    }catch(error){thinking.remove();message('提交未完成：'+error.message);setStatus('提交未完成：'+error.message,'error');$('#aiSend').disabled=false;}
  }
  async function openDataManager(focusId=null) {
    const target=$('#dataWorkspace');if(!target)return;
    target.innerHTML=`<p class="chart-caption">保留原始文件、来源与哈希；导入不自动代表完成现实校准。</p><div class="data-input-row"><label>本地 CSV / JSON / GeoJSON <input id="datasetFile" type="file" accept=".csv,.json,.geojson"></label><button class="ws-button" id="datasetUpload">导入文件</button></div><div class="data-input-row"><input id="datasetUrl" type="url" aria-label="公开HTTPS数据地址" placeholder="公开 HTTPS 数据地址"><select id="datasetFormat" aria-label="数据格式"><option value="json">JSON</option><option value="csv">CSV</option><option value="geojson">GeoJSON</option></select><button class="ws-button" id="datasetFetch">采集数据</button></div><div id="datasetStatus" class="data-status" role="status">正在读取已保存的数据…</div><div id="datasetList"></div><section id="datasetAnalysis"></section>`;
    const status=text=>{if($('#datasetStatus'))$('#datasetStatus').textContent=text;};let datasets=[];
    async function analyzeDataset(d,path='') {
      status('正在统计完整数据…');
      const result=await api(`/api/datasets/${d.dataset_id}?path=${encodeURIComponent(path)}`);if(result.analysis_error)throw new Error(result.analysis_error);
      const stats=result.analysis,numeric=Object.entries(stats.numeric),run=state.runs[state.selected];
      const contract=run?(await api(`/api/models/contract/${run.model_id}?include_fidelity=false`)).contract:null;
      const box=$('#datasetAnalysis');box.innerHTML=`<h3>${esc(d.name)} · 数据概况</h3><div class="data-quality"><div><span>完整记录数</span><b>${stats.n_rows}</b></div><div><span>字段数</span><b>${stats.fields.length}</b></div><div><span>数值字段数</span><b>${numeric.length}</b></div><div><span>存在缺失的数值字段</span><b>${numeric.filter(([,v])=>v.missing_or_non_numeric>0).length}</b></div></div><h4>数值字段质量</h4><canvas id="datasetQualityChart" class="data-chart" aria-label="各数值字段的缺失或非数值记录数"></canvas><div style="overflow-x:auto"><table class="data-stat-table"><thead><tr><th>字段</th><th>有效数</th><th>缺失/非数值</th><th>最小</th><th>最大</th><th>均值</th></tr></thead><tbody>${stats.fields.map(k=>{const v=stats.numeric[k];return v?`<tr><td>${esc(k)}</td><td>${v.n}</td><td>${v.missing_or_non_numeric}</td><td>${fmt(v.min)}</td><td>${fmt(v.max)}</td><td>${fmt(v.mean)}</td></tr>`:`<tr><td>${esc(k)}</td><td colspan="5">未识别为可统计的数值字段</td></tr>`;}).join('')}</tbody></table></div><p class="chart-caption">缺失与非数值统计以每个字段的完整记录为分母；不静默补值。</p>`;
      DAYAN_ANALYSIS.drawBars($('#datasetQualityChart'),numeric.map(([field,v])=>({label:field,count:v.missing_or_non_numeric})),'#eebb79','缺失/非数值记录数');
      if(run?.run_id&&run.manifest?.requested&&contract&&numeric.length){box.insertAdjacentHTML('beforeend',`<h4>将数据用于 ${esc(run.model_id)}</h4><div class="binding-controls"><label>字段<select id="bindingField">${numeric.map(([k])=>`<option>${esc(k)}</option>`).join('')}</select></label><label>汇总方式<select id="bindingAggregate">${[['last','末值'],['first','首值'],['mean','均值'],['sum','总和'],['min','最小值'],['max','最大值']].map(([v,n])=>`<option value="${v}">${n}</option>`).join('')}</select></label><label>模型参数<select id="bindingParameter">${Object.entries(contract.params).filter(([k,v])=>['float','int'].includes(v.type)).map(([k])=>`<option>${esc(k)}</option>`).join('')}</select></label><label>换算系数<input id="bindingScale" type="number" value="1" step="any"></label><label>源单位<input id="bindingSourceUnit" value="${esc(d.metadata?.unit||'')}" placeholder="例如 %"></label><label>目标参数单位<input id="bindingTargetUnit" placeholder="例如 fraction"></label><label>源地区/主体范围<input id="bindingSourceScope" value="${esc(d.metadata?.scope||'')}" placeholder="与数据元数据一致"></label><label>目标地区/主体范围<input id="bindingTargetScope" placeholder="本次研究对象"></label><button class="ws-button ws-primary" id="runWithDataset">按映射创建新运行</button></div><p id="bindingPreview" class="data-status"></p>`);
        const preview=()=>{const field=$('#bindingField').value,aggregate=$('#bindingAggregate').value,v=stats.numeric[field],scale=Number($('#bindingScale').value);$('#bindingPreview').textContent=`${field} 的${$('#bindingAggregate option:checked').textContent} ${fmt(v[aggregate])} × ${fmt(scale)} → ${$('#bindingParameter').value} = ${fmt(v[aggregate]*scale)}${v.missing_or_non_numeric?'；含缺失/非数值，不能直接映射':''}`;$('#runWithDataset').disabled=Boolean(v.missing_or_non_numeric)||!finite(scale);};
        for(const id of ['#bindingField','#bindingAggregate','#bindingParameter','#bindingScale'])$(id).addEventListener('input',preview);preview();
        $('#runWithDataset').onclick=async()=>{const button=$('#runWithDataset');button.disabled=true;try{const parameter=$('#bindingParameter').value,parameters={...(run.manifest?.actual?.effective_parameters||{})};delete parameters[parameter];
          const result=await api('/api/run',{model_id:run.model_id,parameters,ticks:run.manifest.requested.ticks,dt:run.manifest.requested.dt,seed:run.manifest.rng.seed,data_bindings:[{dataset_id:d.dataset_id,path,field:$('#bindingField').value,aggregate:$('#bindingAggregate').value,parameter,scale:Number($('#bindingScale').value),...Object.fromEntries([['source_unit','#bindingSourceUnit'],['target_unit','#bindingTargetUnit'],['source_scope','#bindingSourceScope'],['target_scope','#bindingTargetScope']].map(([key,id])=>[key,$(id).value.trim()]).filter(([,value])=>value))}]});
          await showResult('run',result,{intent:'输入数据映射',question:state.question||`用导入数据研究 ${run.model_id}`});
        }catch(error){status('映射未完成：'+error.message);button.disabled=false;}};
      }else box.insertAdjacentHTML('beforeend','<p class="data-status">选择并运行模型后，可在这里将数值字段映射到相应参数。</p>');
      status('统计已完成，来源为完整导入数据。');
    }
    async function refresh(){
      datasets=(await api('/api/datasets')).datasets||[];const box=$('#datasetList');if(!box)return;
      box.innerHTML=datasets.map((d,i)=>`<article class="dataset-row"><div><strong>${esc(d.name)}</strong><p>${esc(d.source)}</p><small>许可 ${esc(d.license||'未提供')} · ${esc(d.dataset_id)}</small><details><summary>文件依据</summary><small>SHA256 ${esc(d.sha256)}</small></details></div><div><label>JSON记录路径 <input data-json-path="${i}" aria-label="${esc(d.name)}的JSON记录路径" placeholder="顶层列表留空" style="width:150px"></label><button class="ws-button" data-analyze-dataset="${i}">查看分析</button> <a class="ws-button" href="${esc(d.data_url)}" download>原始文件</a></div></article>`).join('')||'<p class="data-status">暂无输入数据。导入文件或提供可访问的数据地址后，可检查字段质量和模型映射。</p>';
      box.querySelectorAll('[data-analyze-dataset]').forEach(button=>button.onclick=async()=>{const i=Number(button.dataset.analyzeDataset);try{await analyzeDataset(datasets[i],box.querySelector(`[data-json-path="${i}"]`).value);}catch(error){status('分析未完成：'+error.message);}});
      status(datasets.length?`已保存 ${datasets.length} 个输入数据集。`:'尚未导入数据。');
    }
    $('#datasetUpload').onclick=async()=>{const button=$('#datasetUpload');button.disabled=true;try{
      const file=$('#datasetFile').files[0];if(!file)throw new Error('请先选择文件');if(file.size>10*1024*1024)throw new Error('文件超过10MiB');const bytes=new Uint8Array(await file.arrayBuffer());new TextDecoder('utf-8',{fatal:true}).decode(bytes);
      let binary='';for(let i=0;i<bytes.length;i+=16384)binary+=String.fromCharCode(...bytes.subarray(i,i+16384));status('正在保存原始文件…');
      const d=await api('/api/datasets/import',{name:file.name,format:file.name.toLowerCase().endsWith('.csv')?'csv':file.name.toLowerCase().endsWith('.geojson')?'geojson':'json',content_base64:btoa(binary),source:'用户导入：'+file.name});await refresh();await analyzeDataset(d);
    }catch(error){status('导入未完成：'+error.message);}finally{button.disabled=false;}};
    $('#datasetFetch').onclick=async()=>{const button=$('#datasetFetch');button.disabled=true;try{status('正在采集外部数据…');const d=await api('/api/datasets/collect',{url:$('#datasetUrl').value,format:$('#datasetFormat').value});await refresh();await analyzeDataset(d);}catch(error){status('采集未完成：'+error.message);}finally{button.disabled=false;}};
    await refresh();if(focusId){const d=datasets.find(d=>d.dataset_id===focusId);if(d)await analyzeDataset(d);}
  }
  Object.assign(controller,{setPlaying,seek,clear,paint,showResult,restore,applyPolicy,loadReplay,openDataManager,select,generateReport,send,
    addEvent:(type,title,desc)=>{setStatus([title,desc].filter(Boolean).join(' · '));},
    tick(ts){if(state.lastWall!==null&&state.playing){const next=state.time+(ts-state.lastWall)/1000*state.rate;if(next>=state.end){if(state.loop&&state.end>state.start)state.time=state.start+(next-state.start)%(state.end-state.start);else{state.time=state.end;setPlaying(false);}}else state.time=next;}state.lastWall=ts;if(ts-lastPaint>80){paint();lastPaint=ts;}}});
  function boot() {
    DAYAN_ANALYSIS.bind(state,paint,notice);
    $('#loopPlayback').onchange=e=>{state.loop=e.target.checked;};
    $('#resetCamera').onclick=()=>window.DAYAN3D?.resetCamera();
    document.querySelectorAll('[data-workspace-view]').forEach(button=>button.addEventListener('click',()=>{document.body.classList.toggle('view-immersive',button.dataset.workspaceView==='immersive');document.querySelectorAll('[data-workspace-view]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));window.dispatchEvent(new Event('resize'));paint();}));
    document.querySelectorAll('[data-layer]').forEach(button=>button.addEventListener('click',()=>window.DAYAN3D?.setLayer(button.dataset.layer)));
    document.querySelectorAll(".weather").forEach(el=>el.style.display="none");
    for(const button of document.querySelectorAll("[data-layer]"))if(button.dataset.layer!=="flow"){button.disabled=true;button.title="此模型尚未提供对应真实图层，不显示演示热力或关系";}
    for(const button of document.querySelectorAll("[data-nav]"))button.addEventListener("click",e=>{e.stopImmediatePropagation();document.querySelectorAll("[data-nav]").forEach(b=>b.classList.toggle("active",b===button));switchPage(button.dataset.nav);if(button.dataset.nav!=="overview")$("#aiDrawer")?.classList.remove("open");if(button.dataset.nav==="scenarios"){let note=$("#scenarioEvidenceNote");if(!note){note=document.createElement("p");note.id="scenarioEvidenceNote";note.textContent="预设为机制案例；未接入真实地区数据时，不构成该地区的实证或预测。";$("#scenariosGrid")?.before(note);}}},true);
    $("#configButton").addEventListener("click",e=>{e.stopImmediatePropagation();showEvidence();},true);
    $("#reportButton").onclick=()=>generateReport().catch(()=>{});
    $("#resumeButton").onclick=resumeDialog;
     $("#dataManagerButton").onclick=()=>{navigate("data");};
    $("#helpButton")?.addEventListener("click",e=>{e.stopImmediatePropagation();modal("研究工作台说明","<p>先描述需求或选择模型。每次计算保存独立run_id，动画、数值、原始数据与报告引用该记录。</p><p>暂停、倍速和时间轴只改变回放，不会重新运行模型。模型干预仅支持合同中声明的可变参数。</p><p>个体状态和汇总示意明确区分；旧记录可能截断，不能冒充完整实验。</p>");},true);
    const footer=document.querySelector("footer");if(footer){const label=footer.children[1];if(label){label.textContent="正在读取登记运行入口…";api("/api/models/runnable").then(r=>{label.textContent=`${r.count}个登记运行入口（包含原型与方法例题）`;$("#connectionStatus").textContent="本地引擎已连接";}).catch(()=>{label.textContent="后端尚未连接";$("#connectionStatus").textContent="连接未成功";});}}
    api("/api/agent/planner_status").then(r=>{const badge=$("#aiDrawer .ai-head b span");if(badge)badge.textContent=["rule","unreachable"].includes(r.planner)||String(r.planner).startsWith("error")?"规则保底":"LLM规划已配置";}).catch(()=>{});
    $("#playButton").addEventListener("click",e=>{e.stopImmediatePropagation();setPlaying(!state.playing);},true);
    $("#resetButton").addEventListener("click",e=>{e.stopImmediatePropagation();setPlaying(false);seek(state.start);},true);
    $("#timeline").addEventListener("input",e=>{e.stopImmediatePropagation();setPlaying(false);seek(Number(e.target.value));},true);
    document.querySelectorAll("[data-speed]").forEach(b=>{b.classList.toggle("selected",Number(b.dataset.speed)===state.rate);b.addEventListener("click",e=>{e.stopImmediatePropagation();state.rate=Number(b.dataset.speed);document.querySelectorAll("[data-speed]").forEach(x=>x.classList.toggle("selected",x===b));},true);});
    $("#trackAgent").addEventListener("click",e=>{e.stopImmediatePropagation();$("#entityPanel").scrollIntoView({behavior:'smooth',block:'center'});$("#entitySelect").focus({preventScroll:true});},true);
    $("#snapshotButton").addEventListener("click",e=>{e.stopImmediatePropagation();const r=state.runs[state.selected];if(!r)return notice("没有可保存的运行");const a=JSON.parse(localStorage.getItem("dayan_bookmarks_v3")||"[]");a.push({run_id:r.run_id,sim_t:state.time});localStorage.setItem("dayan_bookmarks_v3",JSON.stringify(a));notice("已保存回放标记；标记不代表可续算检查点");},true);
    window.aiSend=send;
    window.runFromCatalog=async mid=>{try{if(window.DAYAN_COMMAND){await DAYAN_COMMAND.chooseModel(mid);return;}const r=await api("/api/run",{model_id:mid,ticks:100});await showResult("run",r,{intent:"模型资源运行"});switchPage("overview");}catch(e){notice(e.message);}};
    window.loadReplayPage=()=>loadReplay().catch(e=>notice(e.message));
    window.DAYAN_APPLY_INTERVENTION=applyPolicy;
    window.DAYAN_HIST_RESTORE=async i=>{const r=window._histEntries?.[i];if(r?.run_id)await restore(r.run_id);};
    clear();updateActions();
    const recordId=new URLSearchParams(location.search).get("run");const restored=recordId?restore(recordId).catch(error=>{setStatus("未能读取指定研究记录："+error.message,"error");}):(new URLSearchParams(location.search).get("embed")==="dsh"?Promise.resolve():(window.DAYAN_COMMAND?.restoreDefault()||Promise.resolve()));restored.then(resumePendingJob);
  }
  function navigate(name){switchPage(name);for(const b of document.querySelectorAll("[data-nav]"))b.classList.toggle("active",b.dataset.nav===name);if(name!=="overview")$("#aiDrawer")?.classList.remove("open");}
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",boot);else boot();
})();
