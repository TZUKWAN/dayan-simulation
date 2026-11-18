/* Command workspace. Every displayed quantity is derived from a saved run. */
(() => {
  'use strict';
  const finite = v => typeof v === 'number' && Number.isFinite(v);
  const numericFields = rows => [...new Set(rows.flatMap(r => Object.keys(r || {})))].filter(k => k !== 'sim_t' && rows.some(r => finite(r[k])));
  function stats(values) {
    const xs = values.filter(finite);
    if (!xs.length) return {n:0,min:null,max:null,mean:null,std:null};
    let sum=0,min=Infinity,max=-Infinity;
    for (const x of xs) {sum+=x;min=Math.min(min,x);max=Math.max(max,x);}
    const mean=sum/xs.length;
    return {n:xs.length,min,max,mean,std:Math.sqrt(xs.reduce((s,x)=>s+(x-mean)**2,0)/xs.length)};
  }
  const correlation=(rows,a,b)=>DAYAN_ANALYSIS.correlation(rows,a,b);
  function changes(rows,key) {
    return rows.map((r,i)=>({sim_t:r.sim_t,change:i>0&&finite(r[key])&&finite(rows[i-1][key])?r[key]-rows[i-1][key]:null}));
  }
  function movement(current,previous) {
    if (!previous) return {comparable:0,moved:null,stationary:null,meanDistance:null};
    const prev=new Map((previous.entities||[]).map(e=>[String(e.id),e]));let moved=0,total=0,sum=0;
    for (const e of current?.entities||[]) {
      const p=prev.get(String(e.id));
      if (![e.x,e.y,p?.x,p?.y].every(finite)) continue;
      const d=Math.hypot(e.x-p.x,e.y-p.y);total++;sum+=d;if(d>1e-9)moved++;
    }
    return {comparable:total,moved:total?moved:null,stationary:total?total-moved:null,meanDistance:total?sum/total:null};
  }
  function fieldStats(entities) {
    return numericFields(entities).filter(k=>k!=='id').map(key=>({key,...stats(entities.map(e=>e[key]))}));
  }
  function parseParameter(text,meta,name) {
    const type=meta.type,raw=String(text).trim();let value;
    if (!raw) {if(meta.required)throw new Error(name+' 必须填写');return undefined;}
    if (type==='int'||type==='float'||type==='number') {
      value=Number(raw);if(!finite(value)||(type==='int'&&!Number.isSafeInteger(value)))throw new Error(name+' 需要有效'+(type==='int'?'整数':'数值'));
    } else if (type==='bool'||type==='boolean') {
      if(!['true','false'].includes(raw))throw new Error(name+' 需要 true 或 false');value=raw==='true';
    } else if (['str','string'].includes(type)) value=String(text);
    else {try{value=JSON.parse(raw);}catch{throw new Error(name+' 需要合法 JSON（字符串使用双引号）');}}
    if(finite(value)&&((finite(meta.minimum)&&value<meta.minimum)||(finite(meta.maximum)&&value>meta.maximum)))throw new Error(name+' 超出合同范围');
    if(meta.enum&&!meta.enum.some(v=>JSON.stringify(v)===JSON.stringify(value)))throw new Error(name+' 不在可选值内');
    return value;
  }
  const metrics={finite,numericFields,stats,correlation,changes,movement,fieldStats,parseParameter};
  if (typeof module !== 'undefined' && module.exports) module.exports=metrics;
  if (typeof document === 'undefined') return;
  window.DAYAN_METRICS=metrics;

  const $=s=>document.querySelector(s), A=()=>window.DAYAN_ANALYSIS;
  const esc=v=>A().esc(v),fmt=v=>A().fmt(v),label=v=>A().label(v);
  const palette=['#4ce0cf','#98abff','#f2c579','#75b9f4','#ee9fba','#a8cc91'];
  let mode='simple',railTab='ai',lastPaintKey='',historyPromise,analysisCache=null,proRevision=0,lastRunKey=null;
  let pro={modelId:'',contract:null,source:null},manualRunning=false;
  async function api(path,body) {
    const r=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const v=await r.json();if(!r.ok||v.ok===false)throw new Error(typeof v.detail==='string'?v.detail:JSON.stringify(v.detail||v.error||'请求失败'));return v;
  }
  function at(rows,t) {let i=0;for(;i+1<rows.length&&(rows[i+1].sim_t??i+1)<=t+1e-9;i++);return i;}
  function storage(key,value) {try{if(value===undefined)return localStorage.getItem(key);localStorage.setItem(key,value);}catch{}return null;}
  function text(id,value) {const e=$(id);if(e&&e.textContent!==String(value))e.textContent=value;}
  function spark(values,color) {
    const valid=values.filter(finite);if(!valid.length)return '<svg viewBox="0 0 160 30" aria-hidden="true"></svg>';
    const s=stats(valid),span=s.max-s.min||1;let d='',last=false;
    values.forEach((v,i)=>{if(!finite(v)){last=false;return;}d+=(last?'L':'M')+(i*156/Math.max(1,values.length-1)+2).toFixed(2)+','+(26-(v-s.min)/span*22).toFixed(2);last=true;});
    return `<svg viewBox="0 0 160 30" aria-hidden="true"><path d="${d}" fill="none" stroke="${color}" stroke-width="1.5" vector-effect="non-scaling-stroke"/></svg>`;
  }
  function canvas(el) {
    if(!el?.checkVisibility())return null;const w=el.clientWidth,h=el.clientHeight;if(w<30||h<30)return null;
    const d=Math.min(devicePixelRatio||1,2);el.width=Math.round(w*d);el.height=Math.round(h*d);
    const c=el.getContext('2d');c.setTransform(d,0,0,d,0,0);c.font='10px Consolas, monospace';return {c,w,h};
  }
  function emptyCanvas(el,note) {const p=canvas(el);if(!p)return;p.c.fillStyle='#7195aa';p.c.fillText(note,12,p.h/2);el.dataset.points='0';}
  function drawChanges(el,rows,time) {
    const p=canvas(el);if(!p)return;const {c,w,h}=p,data=rows.filter(r=>finite(r.change));el.dataset.points=String(data.length);
    if(!data.length)return emptyCanvas(el,'至少需要两条有效连续观测');
    const max=Math.max(...data.map(r=>Math.abs(r.change)),1e-12),left=36,right=w-10,mid=(h-20)/2,half=mid-12;
    c.strokeStyle='#254350';c.beginPath();c.moveTo(left,mid);c.lineTo(right,mid);c.stroke();
    data.forEach((r,i)=>{const x=left+(right-left)*i/data.length,bw=Math.max(.8,(right-left)/data.length-1),height=r.change/max*half;
      c.fillStyle=r.sim_t>time+1e-9?'#344b5d':r.change<0?'#e2ad74':'#4ce0cf';c.fillRect(x,Math.min(mid,mid-height),bw,Math.max(1,Math.abs(height)));});
    c.fillStyle='#8eabba';c.fillText(fmt(max),1,13);c.fillText('0',17,mid+3);c.fillText(fmt(-max),1,h-23);
    c.fillText('sim_t '+fmt(data[0].sim_t),left,h-4);c.textAlign='right';c.fillText(fmt(data.at(-1).sim_t),right,h-4);
  }
  function drawCorrelation(el,rows,keys) {
    const p=canvas(el);if(!p)return;const {c,w,h}=p,n=keys.length;el.dataset.fields=String(n);el.dataset.rows=String(rows.length);
    if(!n)return emptyCanvas(el,'当前没有数值观测');
    const left=70,top=24,size=Math.min((w-left-5)/n,(h-top-12)/n),font=Math.max(8,Math.min(10,size*.4));
    c.font=font+'px Consolas, monospace';
    keys.forEach((k,i)=>{c.fillStyle='#91adbc';c.textAlign='right';c.fillText(k.slice(0,11),left-7,top+(i+.6)*size);c.save();c.translate(left+(i+.5)*size,top-7);c.textAlign='left';c.rotate(-.18);c.fillText(k.slice(0,9),0,0);c.restore();
      keys.forEach((q,j)=>{const r=correlation(rows,k,q);c.fillStyle=r.value===null?'#192c3c':r.value>=0?`rgba(76,224,207,${.12+.75*Math.abs(r.value)})`:`rgba(242,197,121,${.12+.75*Math.abs(r.value)})`;
        c.fillRect(left+j*size,top+i*size,Math.max(1,size-2),Math.max(1,size-2));c.fillStyle='#d6e8ef';c.textAlign='center';if(size>22)c.fillText(r.value===null?'—':r.value.toFixed(2),left+(j+.48)*size,top+(i+.6)*size);});});
  }
  function drawActivity(el,activity,entities) {
    const p=canvas(el);if(!p)return;const {c,w,h}=p,cx=w*.3,cy=h*.5,r=Math.min(h*.37,w*.18),fraction=activity.comparable?activity.moved/activity.comparable:0;
    c.lineWidth=8;c.strokeStyle='#253c4c';c.beginPath();c.arc(cx,cy,r,0,Math.PI*2);c.stroke();
    if(activity.comparable){c.strokeStyle='#4ce0cf';c.beginPath();c.arc(cx,cy,r,-Math.PI/2,-Math.PI/2+Math.PI*2*fraction);c.stroke();}
    c.fillStyle='#e0f1f4';c.font='20px Consolas, monospace';c.textAlign='center';c.fillText(activity.comparable?(fraction*100).toFixed(0)+'%':'—',cx,cy+6);
    c.textAlign='left';c.font='10px sans-serif';c.fillStyle='#93afbf';c.fillText('位置变化 / 可比较主体',w*.56,cy-22);
    c.fillStyle='#4ce0cf';c.fillText(activity.comparable?`${activity.moved} / ${activity.comparable}`:'首帧或无位置状态',w*.56,cy);
    c.fillStyle='#93afbf';c.fillText('当前主体 '+entities.length,w*.56,cy+22);
    el.dataset.moved=activity.moved===null?'':String(activity.moved);el.dataset.total=String(activity.comparable);
  }
  function paint(s,force=false) {
    if(!$('#commandShell')||!$('#pageOverview').checkVisibility())return;
    const run=s.runs[s.selected],frames=s.stream?.frames||[],rows=run?.observations||[],idx=at(rows,s.time),fi=at(frames,s.time),frame=frames[fi]||{},entities=frame.entities||[];
    const key=[run?.run_id,fi,idx,s.metric,s.windowMode,JSON.stringify(s.customWindow),s.selected].join('|');
    if(!force&&lastPaintKey===key)return;lastPaintKey=key;
    const runKey=run?.run_id||run?.model_id||null;
    if(runKey!==lastRunKey){lastRunKey=runKey;if(run?.run_id)storage('dayan_last_record_v1',run.run_id);if(run){loadParameters(run.model_id,run).catch(e=>proError(e.message));historyPromise=null;recentRecords();}}
    const window=s.runs.length?A().resolvedWindow(s):null,windowKey=JSON.stringify(window);
    if(!analysisCache||analysisCache.run!==run||analysisCache.windowKey!==windowKey){
      const view=window?A().windowRows(rows,window):rows;
      analysisCache={run,windowKey,rows:view,keys:numericFields(rows),stats:Object.fromEntries(numericFields(rows).map(k=>[k,stats(view.map(r=>r[k]))]))};
    }
    const cache=analysisCache,observed=rows[idx]||{},previous=rows[idx-1]||{},displayed=cache.keys.slice(0,16);
    text('#signalCount',cache.keys.length+' 项观测');
    $('#signalDeck').innerHTML=displayed.length?displayed.map((k,i)=>{const v=observed[k],d=finite(v)&&finite(previous[k])?v-previous[k]:null,st=cache.stats[k];return `<button class="signal-card ${s.metric===k?'selected':''}" data-signal="${esc(k)}" aria-pressed="${s.metric===k}" title="${esc(k)}：${esc(label(k))}"><span>${esc(label(k))}<small>${esc(k)}</small></span><strong data-value="${finite(v)?v:''}">${fmt(v)}</strong>${spark(rows.map(r=>r[k]),palette[i%palette.length])}<div><b>Δ ${finite(d)&&d>0?'+':''}${fmt(d)}</b><small>均值 ${fmt(st.mean)}</small></div></button>`;}).join(''):'<p class="command-empty">暂无实际观测。描述需求，或载入已有归档。</p>';
    for(const b of $('#signalDeck').querySelectorAll('[data-signal]'))b.onclick=()=>{s.metric=b.dataset.signal;$('#resultMetricSelect').value=s.metric;s.paint();};
    text('#signalFoot',cache.keys.length>16?'显示前16项；全部指标可在专业模式下选择':'每项独立纵轴 · Δ为相邻观测差');
    const activity=movement(frame,fi?frames[fi-1]:null);drawActivity($('#activityChart'),activity,entities);
    text('#activityNote',activity.comparable?'与上一存档帧比较，位置差 > 10⁻⁹ 为变化':'没有相邻位置依据时不推算主体运动');
    drawChanges($('#changeChart'),changes(cache.rows,s.metric),s.time);text('#changeMetric',label(s.metric||'—'));
    text('#changeNote','相邻有效观测差值 · 当前分析窗口 '+cache.rows.length+' 条');
    drawCorrelation($('#correlationChart'),cache.rows,cache.keys.slice(0,8));
    text('#correlationNote',`Pearson · ${cache.rows.length}条窗口观测 · ${cache.keys.length>8?'前8项；':''}常量/不足3条为 — · 非因果`);
    const fs=fieldStats(entities),table=fs.length?fs.map(v=>({key:v.key,...v})):cache.keys.map(key=>({key,...cache.stats[key]}));
    $('#fieldTable tbody').innerHTML=table.slice(0,14).map(v=>`<tr><td title="${esc(v.key)}">${esc(v.key)}</td><td>${v.n}</td><td>${fmt(v.min)}</td><td>${fmt(v.max)}</td><td>${fmt(v.mean)}</td></tr>`).join('')||'<tr><td colspan="5">等待实际数值</td></tr>';
    text('#fieldTableTitle',entities.length?'主体属性剖面':'观测字段剖面');text('#fieldTableNote',entities.length?`${entities.length}主体 · 当前保存帧 · 均值保留原单位`:`${cache.rows.length}条窗口观测 · 原模型单位`);
    const facts=[['实体',entities.length],['设施',(frame.facilities||[]).length],['关系',(frame.relations||[]).length],['状态帧',frames.length],['观测',rows.length],['指标',cache.keys.length],['事件',s.events.filter(e=>(e.sim_t??0)<=s.time+1e-9).length],['种子',run?.manifest?.rng?.seed??'—']];
    $('#runVitals').innerHTML=facts.map(([k,v])=>`<div><span>${k}</span><b>${esc(v)}</b></div>`).join('');
    text('#archiveBadge',run?(run.run_id?'归档状态回放 · 非实时采集':'旧记录观测回放'):'尚无运行数据');
    text('#railContext',run?`${run.model_id} · sim_t=${fmt(s.time)} · ${entities.length?entities.length+'主体':cache.keys.length+'项汇总观测'}`:'描述场景、目标和约束，AI会规划并执行');
    text('#commandRecord',run?.run_id||'等待归档');
    if(run)text('#scenarioTitle',run.manifest?.model_definition?.scenario?.title||window.DAYAN3D?.presentation?.title||run.model_id);
    text('#commandClock','sim_t '+fmt(s.time));
  }
  function selectRail(tab) {
    railTab=mode==='simple'?'ai':tab;
    $('#aiDrawer').hidden=railTab!=='ai';$('#proConsole').hidden=railTab!=='parameters';
    for(const b of document.querySelectorAll('[data-rail-tab]'))b.setAttribute('aria-selected',String(b.dataset.railTab===railTab));
    $('#aiDrawer').classList.add('open');
  }
  // ===== 数据源面板（专业模式） =====
  function initDataSourcePanel() {
    const host=$('#proConsole');if(!host||$('#dsPanel'))return;
    const panel=document.createElement('details');panel.id='dsPanel';
    panel.innerHTML=`<summary>📊 数据源与采集</summary><div id="dsContent"><p>加载中…</p></div>`;
    host.prepend(panel);
    loadDataSourcePanel();
  }
  async function loadDataSourcePanel() {
    const el=document.getElementById('dsContent');if(!el)return;
    if(window.DAYAN_RESEARCH)return DAYAN_RESEARCH.paintSources(el);
    el.textContent='数据研究组件尚未加载，请刷新页面。';
  }
  let defaultRestoreCancelled=false;
  function manualIntent() {defaultRestoreCancelled=true;window.DAYAN_RESULTS?.cancelPendingView();}
  function setMode(value,remember=true) {
    if(remember)manualIntent();
    mode=value==='professional'?'professional':'simple';document.body.dataset.operationMode=mode;
    document.body.classList.toggle('mode-simple',mode==='simple');document.body.classList.toggle('mode-professional',mode==='professional');
    for(const b of document.querySelectorAll('[data-operation-mode]'))b.setAttribute('aria-pressed',String(b.dataset.operationMode===mode));
    text('#modeDescription',mode==='simple'?'简易模式 · 用自然语言完成建模与分析':'专业模式 · 全参数控制 + AI协作');
    if(remember)storage('dayan_operation_mode_v1',mode);
    selectRail(mode==='professional'?'parameters':'ai');
    if(mode==='professional')initDataSourcePanel();
    requestAnimationFrame(()=>{window.dispatchEvent(new Event('resize'));window.DAYAN_RESULTS?.paint();paint(window.DAYAN_RESULTS,true);});
  }
  function proError(message) {text('#proStatus',message);$('#proStatus').dataset.state='error';}
  async function loadParameters(mid,source=null) {
    const revision=++proRevision;$('#proRun').disabled=true;text('#proStatus','正在读取真实参数合同…');
    try {
      const result=await api('/api/models/contract/'+encodeURIComponent(mid)+'?include_fidelity=false');if(revision!==proRevision)return;
      pro={modelId:mid,contract:result.contract,source};$('#proModel').value=mid;
      const params=source?.manifest?.actual?.effective_parameters||source?.manifest?.actual?.parameters||{};
      const policies=new Map((result.contract.policies||[]).map(p=>[p.param,p]));
      $('#proParameters').innerHTML=Object.entries(result.contract.params).map(([name,spec])=>{
        const meta={...policies.get(name),...spec},v=Object.hasOwn(params,name)?params[name]:spec.default;
        const value=v===undefined?'':typeof v==='string'&&['str','string'].includes(meta.type)?v:JSON.stringify(v);
        const numeric=['int','float','number'].includes(meta.type),type=numeric?'number':'text';
        return `<label class="parameter-field"><span>${esc(meta.label||label(name))}<small>${esc(name)} · ${esc(meta.type||'JSON')}${meta.unit?' · '+esc(meta.unit):''}</small></span><input data-model-param="${esc(name)}" type="${type}" ${numeric?'step="'+(meta.type==='int'?'1':'any')+'"':''} ${finite(meta.minimum)?'min="'+meta.minimum+'"':''} ${finite(meta.maximum)?'max="'+meta.maximum+'"':''} value="${esc(value)}" ${spec.required?'required':''} aria-label="模型参数 ${esc(name)}"><em>${meta.mutable_at_runtime?'支持运行中干预':'初始化参数'}${finite(meta.minimum)||finite(meta.maximum)?' · '+(meta.minimum??'−∞')+'…'+(meta.maximum??'∞'):''}</em></label>`;
      }).join('')||'<p>该模型未公开构造参数。</p>';
      text('#parameterCount',Object.keys(result.contract.params).length+' 项全部参数');
      $('#proTicks').value=source?.manifest?.requested?.ticks??100;$('#proDt').value=source?.manifest?.requested?.dt??'';$('#proSeed').value=source?.manifest?.rng?.seed??'';
      $('#proCheckpoint').value='';
      $('#proInterventions').value=JSON.stringify((source?.manifest?.interventions||[]).filter(i=>i.applied).map(i=>({at_t:i.requested_t,params:i.params,label:i.label})),null,2);
      $('#proBindings').value=JSON.stringify((source?.manifest?.data_bindings||[]).filter(b=>b.parameter).map(b=>Object.fromEntries(Object.entries(b).filter(([k])=>['dataset_id','path','field','aggregate','parameter','scale','source_unit','target_unit','source_scope','target_scope','filters','order_by'].includes(k)))),null,2);
      text('#proStatus',source?'已载入当前归档的实际初始配置；编辑后创建独立新运行。':'已读取模型默认合同；更改尚未执行。');$('#proStatus').dataset.state='ready';$('#proRun').disabled=false;
    } catch(e) {if(revision===proRevision){pro={modelId:mid,contract:null,source:null};proError('参数合同未取得：'+e.message);}}
  }
  function proRequest() {
    if(!pro.contract)throw new Error('请先读取有效模型合同');const parameters={},policies=new Map((pro.contract.policies||[]).map(p=>[p.param,p]));
    for(const input of $('#proParameters').querySelectorAll('[data-model-param]')) {
      const name=input.dataset.modelParam,value=parseParameter(input.value,{...policies.get(name),...pro.contract.params[name]},name);
      if(value!==undefined)parameters[name]=value;
    }
    const ticks=Number($('#proTicks').value);if(!$('#proTicks').value||!Number.isInteger(ticks)||ticks<0||ticks>10000)throw new Error('步数必须为0到10000的整数');
    const request={model_id:pro.modelId,parameters,ticks,strict:true};
    if($('#proDt').value.trim()){const dt=Number($('#proDt').value);if(!finite(dt)||dt<=0)throw new Error('dt必须为有限正数');request.dt=dt;}
    if($('#proSeed').value.trim()){const seed=Number($('#proSeed').value);if(!Number.isSafeInteger(seed)||seed<0)throw new Error('种子须为非负安全整数');request.seed=seed;}
    for(const [id,key] of [['#proInterventions','interventions'],['#proBindings','data_bindings']]) {
      try{request[key]=JSON.parse($(id).value||'[]');}catch{throw new Error(key+' 需要合法 JSON');}if(!Array.isArray(request[key]))throw new Error(key+' 必须为JSON数组');
    }
    if($('#proCheckpoint').value.trim()){const cp=Number($('#proCheckpoint').value);if(!Number.isInteger(cp)||cp<0||cp>ticks)throw new Error('检查点步数应位于0到总步数之间');request.checkpoint_at=cp;}
    return request;
  }
  async function executeProfessional() {
    if(mode!=='professional'||manualRunning)return;let request;
    try {request=proRequest();}catch(e){return proError(e.message);}
    if($('#aiSend').disabled)return proError('AI任务仍在执行，请等待实际结果。');
    manualRunning=true;$('#proRun').disabled=true;text('#proStatus','引擎实际计算并保存中…');window.DAYAN_RESULTS.setPlaying(false);
    try {const result=await api('/api/run',request);await DAYAN_RESULTS.showResult('run',result,{intent:'专业模式参数运行',question:`专业参数运行 ${request.model_id}`});text('#proStatus','新运行已真实归档：'+result.run_id);}
    catch(e){proError('运行未完成：'+e.message);}finally{manualRunning=false;$('#proRun').disabled=!pro.contract;}
  }
  function prefill(textValue) {if(window.DAYAN_NATIVE_BRIDGE)return DAYAN_NATIVE_BRIDGE.draft(textValue);selectRail('ai');$('#aiInput').value=textValue;$('#aiInput').focus();}
  async function chooseModel(mid) {
    setMode('professional');window.switchPage?.('overview');
    const current=DAYAN_RESULTS.runs[DAYAN_RESULTS.selected];
    await loadParameters(mid,current?.model_id===mid?current:null);selectRail('parameters');
  }
  function history() {return historyPromise||(historyPromise=api('/api/history?limit=30&metadata_only=true').catch(e=>{historyPromise=null;throw e;}));}
  async function restoreDefault() {
    try {
      const h=await history(),saved=storage('dayan_last_record_v1'),complete=h.entries.filter(e=>e.complete&&e.run_id),chosen=complete.find(e=>e.run_id===saved)||complete[0];
      if(chosen&&!defaultRestoreCancelled&&!DAYAN_RESULTS.runs.length&&!$('#aiSend').disabled){const restored=await DAYAN_RESULTS.restore(chosen.run_id);if(restored!==false&&!defaultRestoreCancelled)text('#workspaceStatus','已恢复最近保存的归档；当前为暂停回放，未启动新计算。');}
    }catch(e){text('#workspaceStatus','未能恢复最近记录：'+e.message+'；可直接向AI描述新任务。');}
  }
  async function recentRecords() {
    try {const h=await history(),complete=h.entries.filter(e=>e.complete&&e.run_id).slice(0,3);
      $('#recentRecords').innerHTML=complete.map(e=>`<button data-recent-run="${esc(e.run_id)}"><span>${esc(e.intent||e.model_id)}</span><small>${esc(e.model_id)} · ${esc(e.kind||e.source||'归档')}</small></button>`).join('')||'<span>暂无完整归档</span>';
      for(const b of $('#recentRecords').querySelectorAll('button'))b.onclick=()=>DAYAN_RESULTS.restore(b.dataset.recentRun).catch(e=>window.DAYAN_NOTICE(e.message));
    }catch{text('#recentRecords','历史记录读取失败，AI仍可发起新任务。');}
  }
  function assistantAction(value) {
    const text=value.trim().replace(/[。！!？?\s]+$/,'');
    const scheme=text.match(/^(?:请)?(?:查看|切换到)(?:第)?(\d+)个?方案$/);
    if(scheme)return async()=>{const index=Number(scheme[1])-1,s=DAYAN_RESULTS;if(!Number.isSafeInteger(index)||index<0||index>=s.runs.length)throw new Error('当前共有'+s.runs.length+'个已有方案');await s.select(index);return {text:'已读取方案 '+scheme[1]+'：'+s.runs[index].label+'；使用已有归档。'};};
    const metric=text.match(/^(?:请)?查看(.+?)(?:指标|趋势)$/);
    if(metric)return async()=>{const s=DAYAN_RESULTS,keys=numericFields(s.runs[s.selected]?.observations||[]),key=keys.find(k=>k===metric[1]||label(k)===metric[1]);if(!key)throw new Error('当前实际指标为：'+keys.map(k=>label(k)+'('+k+')').join('、'));s.metric=key;$('#resultMetricSelect').value=key;s.paint();return {text:'已切换到'+label(key)+'的实际观测趋势。'};};
    const position=text.match(/^(?:请)?(?:回放到|定位到)(?:模型时间)?\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))$/);
    if(position)return async()=>{const s=DAYAN_RESULTS,t=Number(position[1]);if(!s.runs.length||t<s.start||t>s.end)throw new Error('回放位置应在'+fmt(s.start)+'到'+fmt(s.end)+'之间');s.setPlaying(false);s.seek(t);return {text:'已将已有结果的回放位置设为 sim_t='+fmt(t)+'。'};};
    if(/^(请|帮我)?生成(当前|本次)?(研究|分析)?报告$/.test(text))return async()=>{const r=await DAYAN_RESULTS.generateReport();if(!r)throw new Error('当前没有可生成报告的完整归档');return {text:'报告已从实际归档生成。',url:r.url,label:'下载研究报告'};};
    if(/^(请|帮我)?导出(当前|本次)?(原始数据|原始CSV|CSV|研究包)$/i.test(text))return async()=>{
      const s=DAYAN_RESULTS,r=s.runs[s.selected];if(!r?.run_id)throw new Error('当前没有完整归档可导出');
      const bundle=/研究包/.test(text),id=bundle?(s.payload?.experiment_id||s.payload?.analysis_id||r.run_id):r.run_id;
      return {text:'已提供当前归档的'+(bundle?'完整研究包':'原始观测数据')+'。',url:'/api/runs/'+encodeURIComponent(id)+(bundle?'/bundle.zip':'/observations.csv'),label:bundle?'下载研究包':'下载原始 CSV'};
    };
    return null;
  }
  function boot() {
    document.body.classList.add('command-center');
    const mast=$('.headright'),modes=document.createElement('div');modes.className='operation-modes';modes.setAttribute('aria-label','操作模式');modes.innerHTML='<button data-operation-mode="simple" aria-pressed="true">简易模式</button><button data-operation-mode="professional" aria-pressed="false">专业模式</button>';mast.prepend(modes);
    $('.brand p').textContent='社会仿真 · 态势观察与决策推演';
    const shell=document.createElement('div');shell.id='commandShell';const main=document.createElement('div');main.id='commandMain';$('#pageMission').before(shell);shell.append(main);
    for(const page of document.querySelectorAll('[data-workspace-page]'))main.append(page);
    const rail=document.createElement('aside');rail.id='operationRail';rail.setAttribute('aria-label','AI与专业操作');shell.append(rail);
    rail.innerHTML=`<div class="rail-title"><span>OPERATIONS</span><b id="modeDescription"></b></div><div class="rail-tabs" role="tablist" aria-label="操作工具"><button data-rail-tab="ai" role="tab" aria-selected="true">◈ AI协作</button><button data-rail-tab="parameters" role="tab" aria-selected="false">全部参数</button></div><div id="railContext"></div><section id="aiRail"></section><section id="proConsole" hidden><div class="pro-heading"><b>模型与运行控制</b><span id="parameterCount"></span></div><form id="proForm"><div class="pro-model"><input id="proModel" type="text" list="proModelList" placeholder="选择或输入模型ID" aria-label="专业模型ID"><datalist id="proModelList"></datalist><button type="button" id="proLoad">读取</button></div><div id="proParameters"><p>载入当前模型的全部真实参数。</p></div><div class="pro-runtime"><label>步数<input id="proTicks" type="number" min="0" max="10000" step="1" value="100"></label><label>dt<input id="proDt" type="number" min="0" step="any" placeholder="模型默认"></label><label>随机种子<input id="proSeed" type="number" min="0" step="1" placeholder="引擎默认"></label></div><details class="pro-advanced"><summary>定时干预、数据映射与检查点</summary><label>interventions · 定时干预<textarea id="proInterventions" rows="4">[]</textarea></label><label>data_bindings · 数据参数映射<textarea id="proBindings" rows="4">[]</textarea></label><label>checkpoint_at · 保存检查点步数<input id="proCheckpoint" type="number" min="0" step="1" placeholder="默认末步"></label><p>沿用真实接口结构；不支持的参数/组合由引擎明确拒绝。</p></details><div class="pro-buttons"><button type="button" id="proReset">恢复模型默认</button><button type="submit" id="proRun" disabled>执行新运行 ↗</button></div><p id="proStatus" role="status">等待参数合同</p></form><button id="askAboutParameters" class="rail-ai-link">让 AI 帮我解释和调整参数 →</button></section><div class="rail-records"><span>最近归档 · 读取不重新计算</span><div id="recentRecords"></div></div>`;
    $('#aiRail').append($('#aiDrawer'));$('#aiDrawer').classList.add('open');
    const tools=document.createElement('div');tools.className='ai-command-chips';tools.innerHTML='<button data-draft="解释当前结果，并指出主要变化和局限">解释结果</button><button data-draft="生成研究报告">研究报告</button><button data-draft="导出原始数据">原始数据</button><label title="导入真实CSV/JSON数据">＋ 数据<input id="chatDataFile" type="file" accept=".csv,.json,.geojson" hidden></label>';
    $('#aiDrawer .ai-input-row').before(tools);
    const left=document.createElement('aside');left.className='command-left';left.innerHTML='<section class="panel signal-panel"><div class="panel-head"><h2>全域指标</h2><span id="signalCount" class="micro"></span></div><div id="signalDeck"></div><p class="chart-caption" id="signalFoot"></p></section><section class="panel activity-panel"><div class="panel-head"><h2>主体运动构成</h2><span class="micro">POSITION DELTA</span></div><canvas id="activityChart" aria-label="实际相邻帧主体位置变化占比"></canvas><p class="chart-caption" id="activityNote"></p></section>';
    $('.workspace-grid').prepend(left);
    const vitals=document.createElement('div');vitals.className='command-vitals';vitals.innerHTML='<span id="archiveBadge">等待真实归档</span><div id="runVitals"></div><strong id="commandClock">sim_t 0</strong>';
    $('.workspace-grid').before(vitals);
    const extra=document.createElement('section');extra.className='command-analysis-grid';extra.innerHTML='<section class="panel"><div class="panel-head"><h2>指标联动矩阵</h2><span class="micro">CORRELATION</span></div><canvas id="correlationChart" aria-label="真实观测的两两相关系数"></canvas><p class="chart-caption" id="correlationNote"></p></section><section class="panel"><div class="panel-head"><h2>单步变化强度</h2><span class="micro" id="changeMetric"></span></div><canvas id="changeChart" aria-label="所选指标的相邻观测差值"></canvas><p class="chart-caption" id="changeNote"></p></section><section class="panel field-profile"><div class="panel-head"><h2 id="fieldTableTitle">状态剖面</h2><span class="micro">RAW VALUES</span></div><div class="field-table-scroll"><table id="fieldTable"><thead><tr><th>字段</th><th>有效数</th><th>最小</th><th>最大</th><th>均值</th></tr></thead><tbody></tbody></table></div><p class="chart-caption" id="fieldTableNote"></p></section>';
    $('.analysis-grid').after(extra);
    $('.intervention-details').dataset.proOnly='';$('.workspace-toolbar').dataset.proOnly='';
    $('.scenario-name .code').textContent='DAYAN / SIMULATION COMMAND';
    const record=document.createElement('span');record.id='commandRecord';record.className='micro';$('#workspaceStatus').after(record);
    const events=$('.events');events.open=true;
    $('#aiInput').placeholder='描述场景、修改参数、分析结果…';
    $('#aiChatBody').innerHTML='<div class="ai-msg ai-bot"><span class="assistant-mark">DAYAN ASSISTANT</span><b>从一句话，进入一个可观察的世界。</b><p>告诉我场景、主体与研究目标。我会选择或构建模型，执行计算，再将实际结果呈现在指挥屏。</p><p>也可以直接说：调整参数、解释当前结果、生成研究报告。</p></div>';
    for(const b of modes.querySelectorAll('button'))b.onclick=()=>setMode(b.dataset.operationMode);
    for(const b of rail.querySelectorAll('[data-rail-tab]'))b.onclick=()=>selectRail(b.dataset.railTab);
    for(const b of tools.querySelectorAll('[data-draft]'))b.onclick=()=>prefill(b.dataset.draft);
    window.toggleAIDrawer=()=>{if(document.body.dataset.page!=='overview')window.switchPage?.('overview');selectRail('ai');$('#aiInput').focus({preventScroll:true});if(innerWidth<1000)rail.scrollIntoView({block:'start'});};
    $('#proLoad').onclick=()=>{manualIntent();return loadParameters($('#proModel').value.trim().toUpperCase()).catch(e=>proError(e.message));};
    $('#aiInput').addEventListener('input',manualIntent);
    $('#proReset').onclick=()=>pro.modelId&&loadParameters(pro.modelId);
    $('#proForm').onsubmit=e=>{e.preventDefault();executeProfessional();};
    $('#askAboutParameters').onclick=()=>prefill('解释当前模型的参数含义，并建议如何调整来研究不同方案');
    $('#chatDataFile').onchange=async e=>{
      const file=e.target.files[0];if(!file)return;const msg=document.createElement('div');msg.className='ai-msg ai-bot';msg.textContent='正在导入 '+file.name+'…';$('#aiChatBody').append(msg);
      try {if(file.size>10*1024*1024)throw new Error('文件超过10MiB');const bytes=new Uint8Array(await file.arrayBuffer());new TextDecoder('utf-8',{fatal:true}).decode(bytes);let binary='';for(let i=0;i<bytes.length;i+=16384)binary+=String.fromCharCode(...bytes.subarray(i,i+16384));
        const d=await api('/api/datasets/import',{name:file.name,format:file.name.toLowerCase().endsWith('.csv')?'csv':file.name.toLowerCase().endsWith('.geojson')?'geojson':'json',content_base64:btoa(binary),source:'用户导入：'+file.name});msg.textContent='已导入真实文件：'+file.name+' · '+d.dataset_id;prefill(`请分析数据集 ${d.dataset_id}，并说明如何用于当前模型。`);
      }catch(error){msg.textContent='导入未完成：'+error.message;}finally{e.target.value='';}
    };
    api('/api/models/runnable').then(r=>{$('#proModelList').innerHTML=r.models.map(m=>`<option value="${esc(m.model_id)}">${esc(m.protocol)}</option>`).join('');}).catch(()=>{});
    recentRecords();setMode(storage('dayan_operation_mode_v1')||'simple',false);
    let resizing=false;window.addEventListener('resize',()=>{if(resizing)return;resizing=true;requestAnimationFrame(()=>{resizing=false;if(window.DAYAN_RESULTS)paint(DAYAN_RESULTS,true);});});
  }
  window.DAYAN_COMMAND={paint,setMode,selectRail,restoreDefault,assistantAction,proRequest,loadParameters,chooseModel,get mode(){return mode;},get busy(){return manualRunning;}};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
