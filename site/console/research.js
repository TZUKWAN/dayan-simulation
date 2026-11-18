/* Real collection and versioned research controls; DSH embed follows only its own native session. */
(() => {
  'use strict';
  const $ = s => document.querySelector(s), esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const query = new URLSearchParams(location.search), nativeSession = query.get('dsh_session');
  let currentStudy = query.get('study'), currentCollection = null, lastEvent = 0, following = false;
  async function request(path, body) {
    const response = await fetch(path, body === undefined ? {} : {method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});
    const result = await response.json(); if (!response.ok) throw new Error(result.detail || result.error || '请求失败'); return result;
  }
  async function tool(name, args) {
    const result = await request('/api/tools/'+encodeURIComponent(name), {arguments:args});
    if (!result.ok) { const error = new Error(result.error || result.payload?.error || result.payload?.status || '未完成'); error.result=result; throw error; }
    return result;
  }
  function status(value) {const el=$('#researchStatus'); if(el)el.textContent=value;}
  function announce(value) {if(window.DAYAN_NOTICE)window.DAYAN_NOTICE(value); status(value);}
  function paintDiagnostics(s) {
    $('#studyDiagnostics')?.remove();
    const cal=s.calibration;if(!cal?.training||!cal?.holdout?.predicted||!s.predictions)return;
    const fit=new Map(s.predictions.map(r=>[r.date,r.predicted]));
    const observed=s.records.map(r=>r.value),predicted=s.records.map(r=>fit.get(r.date)),dates=s.records.map(r=>r.date);
    function chart(title,labels,series,legend) {
      const values=series.flat().filter(Number.isFinite),lo=Math.min(...values),hi=Math.max(...values),span=hi-lo||1;
      const x=i=>28+i*260/Math.max(1,labels.length-1),y=v=>92-(v-lo)/span*72;
      const colors=['#52d8c8','#ffb16c'];
      const paths=series.map((ys,j)=>`<polyline points="${ys.map((v,i)=>`${x(i)},${y(v)}`).join(' ')}" fill="none" stroke="${colors[j]}" stroke-width="2"/>${ys.map((v,i)=>`<circle cx="${x(i)}" cy="${y(v)}" r="2.4" fill="${colors[j]}"><title>${esc(labels[i])} · ${esc(legend[j])} ${esc(v)}</title></circle>`).join('')}`).join('');
      return `<article style="padding:10px;border:1px solid #314b60;background:#0c1d2b"><strong>${esc(title)}</strong><svg viewBox="0 0 316 120" role="img" aria-label="${esc(title)}" style="width:100%;height:140px"><path d="M28 15V96H292" stroke="#486478" fill="none"/><text x="2" y="18" fill="#b4cfda" font-size="8">${esc(hi.toPrecision(4))}</text><text x="2" y="96" fill="#b4cfda" font-size="8">${esc(lo.toPrecision(4))}</text>${paths}<text x="28" y="112" fill="#b4cfda" font-size="9">${esc(labels[0])}</text><text x="260" y="112" fill="#b4cfda" font-size="9">${esc(labels.at(-1))}</text></svg><small>${legend.map((v,i)=>`<span style="color:${colors[i]}">● ${esc(v)}</span>`).join('　')}</small></article>`;
    }
    const valid=cal.evaluations.filter(e=>Number.isFinite(e.loss)).slice(0,200),residual=observed.map((v,i)=>v-predicted[i]);
    const section=document.createElement('section');section.id='studyDiagnostics';section.dataset.studyId=s.study_id;section.dataset.runId=s.run_id;
    section.innerHTML=`<p style="font-size:12px;color:#b4cfda">真实观测与同一模型版本　·　${esc(s.unit)}　·　训练 ${s.training.length} 年 / 留出 ${s.holdout.length} 年　·　${esc(cal.status)}</p><div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:8px">${
      chart('真实数据与模型轨迹',dates,[observed,predicted],['真实观测','模型'])+
      chart('逐年残差',dates,[residual,dates.map(()=>0)],['观测减模型','零误差'])+
      chart('独立留出误差与事前阈值',['训练','留出'],[[cal.best_loss,cal.holdout.rmse],[s.tolerance,s.tolerance]],['RMSE','事前阈值'])+
      chart('真实网格评估损失',valid.map(e=>e.combo_id),[valid.map(e=>e.loss)],['有效评估点，最多显示前200点'])+
      chart('真实变化与模型变化',dates.slice(1),[observed.slice(1).map((v,i)=>v-observed[i]),predicted.slice(1).map((v,i)=>v-predicted[i])],['真实年度变化','模型年度变化'])+
      chart('相同训练均值基线与模型误差',['训练','留出'],[[cal.baseline_mean_rmse,cal.holdout.baseline_train_mean_rmse],[cal.best_loss,cal.holdout.rmse]],['训练均值基线','当前模型'])
    }</div>`;
    const anchor=$('#pageOverview .workspace-grid');if(anchor)anchor.after(section);else $('#pageOverview')?.append(section);
  }
  function inputs(preset) {
    const tokens = [...new Set(Array.from(JSON.stringify(preset.params_template).matchAll(/\{([a-zA-Z_]+)\}/g),m=>m[1]))];
    return tokens.map(key => `<label>${esc(key)} · ${esc(preset.placeholders?.[key] || '必填参数')}<input name="${esc(key)}" required autocomplete="off" list="${esc(preset.preset_id)}-${key}">${['indicator','dataset'].includes(key) ? `<datalist id="${esc(preset.preset_id)}-${key}">${Object.entries(preset.indicator_options||{}).map(([label,id])=>`<option value="${esc(id)}">${esc(label)}</option>`).join('')}</datalist>`:''}</label>`).join('');
  }
  async function paintSources(el) {
    try {
      const [sources,presets,tasks] = await Promise.all([request('/api/collection/sources?limit=200'),request('/api/collection/presets'),request('/api/collection/tasks?limit=30')]);
      el.innerHTML=`<p class="research-note">目录仅证明发现资源；实际数据、文本证据和完整性分别显示。</p><details><summary>来源矩阵 ${sources.n_sources} 源</summary><div class="research-scroll"><table><tr><th>来源</th><th>状态与证据</th></tr>${sources.sources.map(s=>`<tr><td title="${esc(s.source_id)}">${esc(s.name)}</td><td>${esc(s.state_zh||s.state)}<br><small>${esc(s.probe_summary||'待验证')}</small></td></tr>`).join('')}</table></div></details>
      <details><summary>采集预设 ${presets.presets.length} 个</summary>${presets.presets.map(p=>`<details><summary>${esc(p.title)}</summary><form class="preset-form" data-preset="${esc(p.preset_id)}">${inputs(p)}<label>本次页预算<input name="page_budget" type="number" min="1" max="50" value="2" required></label><button>执行真实采集</button><output role="status"></output></form></details>`).join('')}</details>
      <details open><summary>采集任务 ${tasks.n_tasks} 个</summary><div id="collectionTaskRows" class="research-scroll"></div><button type="button" id="moreCollectionTasks">加载更多</button></details>`;
      for (const form of el.querySelectorAll('.preset-form')) form.onsubmit=async event=>{
        event.preventDefault(); const button=form.querySelector('button'), output=form.querySelector('output');button.disabled=true;output.textContent='正在实际下载与检查完整性…';
        const values=Object.fromEntries(new FormData(form));const budget=Number(values.page_budget);delete values.page_budget;
        const poll=window.setInterval(()=>refreshTasks().catch(()=>{}),1500);
        try {const r=await request('/api/collection/run_preset',{preset_id:form.dataset.preset,values,page_budget:budget});const t=r.task;
          output.textContent=t ? `${t.status} · ${t.n_records}条 · ${t.artifact_role} · ${t.collection_id}${r.error?' · '+r.error:''}` : r.error;
          if(t?.status==='done'){currentCollection=t.collection_id;if($('#researchCollection'))$('#researchCollection').value=currentCollection;}
          await refreshTasks();
        } catch(error) {output.textContent='执行失败：'+error.message;} finally {window.clearInterval(poll);button.disabled=false;}
      };
      let offset=0;
      function taskRows(items,append=false) {
        const host=$('#collectionTaskRows');if(!host)return;
        if(!append)host.innerHTML='';
        host.insertAdjacentHTML('beforeend',items.map(t=>`<article class="research-task"><strong>${esc(t.name||t.connector)}</strong><p>${esc(t.status)} · ${t.n_records}条 · ${esc(t.artifact_role||'旧批次，角色未核验')}<br><small>${esc(t.collection_id)}</small></p>${t.error?`<p class="research-error">${esc(t.error)}</p>`:''}${['partial','failed','cancelled'].includes(t.status)?`<button data-resume="${esc(t.collection_id)}">续采</button>`:''}${t.status==='done'?`<button data-bind="${esc(t.collection_id)}">用于研究</button><button data-import="${esc(t.collection_id)}">导入模型数据集</button>`:''}<output role="status"></output></article>`).join(''));
        for(const button of host.querySelectorAll('[data-bind]'))button.onclick=()=>{
          currentCollection=button.dataset.bind;
          window.DAYAN_TOOLS.useCollection(currentCollection);
          status('已选择实际批次 '+currentCollection+'，请填写原始研究问题与模型合同。');
        };
        for(const button of host.querySelectorAll('[data-import]'))button.onclick=async()=>{button.disabled=true;try{const r=await tool('import_collection',{collection_id:button.dataset.import});button.parentElement.querySelector('output').textContent='实际模型输入数据集 '+r.payload.dataset_id;await window.DAYAN_RESULTS?.openDataManager(r.payload.dataset_id);}catch(e){button.parentElement.querySelector('output').textContent=e.message;}finally{button.disabled=false;}};
        for(const button of host.querySelectorAll('[data-resume]'))button.onclick=async()=>{button.disabled=true;const id=button.dataset.resume;try{const r=await tool('collection_status',{collection_id:id});const t=r.payload.task;await tool('collect_source',{connector:t.connector,params:t.params,collection_id:id,page_budget:2});await refreshTasks();}catch(e){button.parentElement.querySelector('output').textContent=e.message;button.disabled=false;}};
        for(const article of host.querySelectorAll('.research-task')) {
          const match=items.find(t=>article.textContent.includes(t.collection_id));
          if(match?.status==='running') {
            const button=document.createElement('button');button.textContent='取消采集';button.type='button';article.append(button);
            button.onclick=async()=>{button.disabled=true;try{const r=await tool('cancel_collection',{collection_id:match.collection_id});article.querySelector('output').textContent=r.payload.cancel_requested?'已请求取消，等待当前有界HTTP请求结束':'任务已结束：'+r.payload.status;}catch(e){article.querySelector('output').textContent=e.message;button.disabled=false;}};
          }
        }
      }
      async function refreshTasks(){const r=await request('/api/collection/tasks?limit=30');offset=r.tasks.length;taskRows(r.tasks);$('#moreCollectionTasks').hidden=offset>=r.n_tasks;}
      taskRows(tasks.tasks);offset=tasks.tasks.length;$('#moreCollectionTasks').hidden=offset>=tasks.n_tasks;
      $('#moreCollectionTasks').onclick=async()=>{const r=await request('/api/collection/tasks?offset='+offset+'&limit=30');taskRows(r.tasks,true);offset+=r.tasks.length;$('#moreCollectionTasks').hidden=offset>=r.n_tasks;};
    } catch(error) {el.textContent='来源与任务加载失败：'+error.message;}
  }
  async function showStudy(id,restore=false) {
    const r=await request('/api/research/studies/'+encodeURIComponent(id));const s=r.study;currentStudy=id;window.DAYAN_STUDY=s;
    const cal=s.calibration, host=$('#researchEvidence');if(!host)return;
    paintDiagnostics(s);
    let validationBar=$('#studyValidationBar');
    if(!validationBar){validationBar=document.createElement('div');validationBar.id='studyValidationBar';validationBar.style.cssText='padding:8px 12px;font-size:12px;line-height:1.6;border-bottom:1px solid #40536a;background:#142331';$('#pageOverview')?.prepend(validationBar);}
    validationBar.innerHTML=`${esc(s.contract.country)} · ${esc(s.contract.definition.concept)} · ${esc(s.contract.date)}　<strong class="${cal&&cal.status!=='pass'?'research-error':''}">${esc(cal?.status||'尚未校准')}</strong>${cal?`　训练 RMSE ${esc(cal.best_loss?.toPrecision(5))} · 留出 ${esc(cal.holdout?.rmse?.toPrecision(5))} · 事前阈值 ${esc(s.tolerance)}（${esc(s.unit)}原单位）`:''}`;
    host.innerHTML=`<strong>${esc(s.question)}</strong><p>${esc(s.study_id)}<br>${esc(s.model_family)} · ${esc(s.contract.country)} · ${esc(s.contract.indicator)} · ${esc(s.unit)}</p>
    <p>${cal?`执行 ${esc(s.phase)}；验证 <b class="${cal.status==='pass'?'':'research-error'}">${esc(cal.status)}</b><br>训练RMSE ${esc(cal.best_loss)}；留出RMSE ${esc(cal.holdout?.rmse)}；事前阈值 ${esc(s.tolerance)}`:'合同已保存，尚未校准'}</p>
    <details><summary>数据绑定与模型依据</summary><pre>${esc(JSON.stringify({collection_id:s.collection_id,dataset_id:s.training_dataset.dataset_id,data_binding:s.data_binding,run_id:s.run_id,model_id:s.model_id,best_params:cal?.best_params,study_sha256:s.artifact_sha256,limitations:s.limitations},null,2))}</pre></details>
    ${s.run_id?`<button type="button" id="openStudyRun">在大屏查看实际运行</button>`:''}<div id="studyReportLinks"></div>`;
    if(s.run_id){$('#openStudyRun').onclick=()=>window.DAYAN_RESULTS?.restore(s.run_id);if(restore)await window.DAYAN_RESULTS?.restore(s.run_id);}
    const reportLabels={academic:'学术报告',data_quality:'数据质量报告',policy:'政策适用性简报'};
    for(const report of r.reports||[]){
      if(!report.file){const txt=document.createElement('p');txt.textContent=report.label+' · '+report.error;$('#studyReportLinks').append(txt);continue;}
      const a=document.createElement('a');a.href=report.file;a.download='';a.textContent='下载'+(reportLabels[report.kind]||'已生成报告');$('#studyReportLinks').append(a);
    }
    $('#calibrateStudy').disabled=s.phase!=='prepared';for(const b of document.querySelectorAll('[data-study-report]'))b.disabled=!s.run_id;
    status(cal?`实际研究已保存 · ${cal.status}；报告将保留这个验证结论。`:'研究合同已准备；使用独立留出集执行校准。');
    return s;
  }
  function boot() {
    const style=document.createElement('style');style.textContent=`.preset-form,#studyForm{display:grid;gap:7px;padding:8px 0}.preset-form label,#studyForm label{display:grid;gap:3px;font-size:11px}.preset-form input,#studyForm input,#studyForm textarea,#studyForm select{box-sizing:border-box;max-width:100%;width:100%;padding:5px;background:#101c29;border:1px solid #40536a;color:#d5e9ef}.research-scroll{max-height:260px;overflow:auto}.research-scroll table{width:100%;font-size:10px;border-collapse:collapse}.research-scroll td{border-bottom:1px solid #314254;padding:5px}.research-task{padding:8px 0;border-bottom:1px solid #314254}.research-task p,.research-note,#researchEvidence{font-size:11px;line-height:1.5}.research-task small{overflow-wrap:anywhere}#researchEvidence pre{white-space:pre-wrap;word-break:break-all;font-size:10px}#researchStatus{font-size:11px;line-height:1.5;white-space:pre-wrap}.research-error{color:#ffb380}#studyReportLinks a{display:inline-block;margin:6px}.dsh-native-embed #aiDrawer,.dsh-native-embed [data-rail-tab="ai"]{display:none!important}.dsh-native-embed.mode-simple #operationRail{display:none!important}.dsh-native-embed.mode-simple #commandShell{grid-template-columns:minmax(0,1fr)!important}.dsh-native-embed #assistantButton,.dsh-native-embed .ai-fab{display:none!important}@media(min-width:581px) and (max-width:1100px){.dsh-native-embed .analysis-column{grid-template-columns:minmax(0,1fr)}}#nativeContextBar{padding:6px 12px;font-size:11px;color:#9cc8dc;border-bottom:1px solid #314254}`;document.head.append(style);
    const host=$('#proConsole');if(!host)return;
    const panel=document.createElement('details');panel.id='researchPanel';panel.innerHTML=`<summary>真实数据建模与独立验证</summary><form id="studyForm"><label>原始研究问题（包含地区 指标 年份 模型）<textarea id="researchQuestionInput" required rows="3"></textarea></label><label>真实完整采集批次<input id="researchCollection" required placeholder="collection_id"></label><label>描述性模型<select id="researchFamily"><option value="linear">线性趋势</option><option value="exponential">指数趋势</option><option value="logistic">Logistic增长</option></select></label><label>参数网格 JSON<textarea id="researchGrid" required rows="2" placeholder='例如 {"slope":[-0.5,0,0.5]}'></textarea></label><label>事前RMSE阈值（原单位）<input id="researchTolerance" type="number" min="0" step="any" required></label><label>末尾留出年份数<input id="researchHoldout" type="number" min="1" value="2" required></label><button>保存研究合同</button></form><button id="calibrateStudy" disabled>执行真实校准与留出验证</button><p><button data-study-report="academic" disabled>学术报告</button> <button data-study-report="data_quality" disabled>数据质量报告</button> <button data-study-report="policy" disabled>政策适用性简报</button></p><div id="researchStatus" role="status">填写原始需求和完整真实数据，禁止用默认案例替代。</div><div id="researchEvidence"></div><details><summary>已保存研究</summary><div id="studyHistory"></div><button id="refreshStudies">刷新研究列表</button></details>`;
    host.prepend(panel);
    $('#refreshSources').onclick=()=>loadSources(true);
    $('#studyForm').onsubmit=async e=>{e.preventDefault();const button=e.currentTarget.querySelector('button');button.disabled=true;status('校验国家、指标、时期、单位与数据角色…');try{const r=await tool('research_create',{question:$('#researchQuestionInput').value,collection_id:$('#researchCollection').value,model_family:$('#researchFamily').value,param_grid:JSON.parse($('#researchGrid').value),tolerance:Number($('#researchTolerance').value),holdout_years:Number($('#researchHoldout').value)});await showStudy(r.payload.study_id);}catch(error){status('合同未建立：'+error.message);}finally{button.disabled=false;}};
    $('#calibrateStudy').onclick=async()=>{const button=$('#calibrateStudy');button.disabled=true;status('使用统一仿真引擎实际评估参数网格…');try{const r=await tool('research_calibrate',{study_id:currentStudy});await showStudy(r.payload.study_id);}catch(e){status('校准未完成：'+e.message);button.disabled=false;}};
    for(const button of panel.querySelectorAll('[data-study-report]'))button.onclick=async()=>{button.disabled=true;status('核对研究版本并生成同源报告…');try{const r=await tool('research_report',{study_id:currentStudy,kind:button.dataset.studyReport});$('#studyReportLinks').insertAdjacentHTML('beforeend',`<a href="${esc(r.payload.file)}" download>下载本研究${esc(button.textContent)}</a><a href="${esc(r.payload.bundle_url)}" download>复现包</a>`);status('报告已生成 · 验证结论 '+r.payload.validation_status);}catch(e){status('报告未生成：'+e.message);}finally{button.disabled=false;}};
    async function history(){const r=await request('/api/research/studies');$('#studyHistory').innerHTML=r.studies.map(s=>`<button data-saved-study="${esc(s.study_id)}">${esc(s.question||s.study_id)} · ${esc(s.calibration?.status||s.phase)}</button>`).join('')||'尚无研究';for(const b of panel.querySelectorAll('[data-saved-study]'))b.onclick=()=>showStudy(b.dataset.savedStudy).catch(e=>status(e.message));}
    $('#refreshStudies').onclick=()=>history().catch(e=>status(e.message));history().catch(e=>status(e.message));
    if(currentStudy)showStudy(currentStudy).catch(e=>status(e.message));
    if(query.get('embed')==='dsh') {
      document.body.classList.add('dsh-native-embed');
      if(!query.get('run'))window.DAYAN_RESULTS?.clear();
      const banner=document.createElement('div');banner.id='nativeContextBar';banner.textContent=nativeSession?'DSH 原生会话已连接 · 此工作台只同步当前会话真实结果':'DSH原生会话尚未连接';$('#pageOverview')?.prepend(banner);
      window.DAYAN_NATIVE_BRIDGE={draft(text){if(!nativeSession){announce('DSH原生会话尚未连接，请等待连接完成后重试。');return;}window.parent.postMessage({type:'dayan:native-draft',sessionId:nativeSession,text},query.get('parent_origin')||location.origin);announce('草稿已交给DSH原生输入框，请在左侧发送。');}};
      const follow=async()=>{if(following||!nativeSession)return;following=true;try{const r=await request('/api/integrations/dsh/events?session_id='+encodeURIComponent(nativeSession)+'&after='+lastEvent);for(const event of r.events){lastEvent=Math.max(lastEvent,event.seq);banner.textContent=`DSH实际工具 ${event.tool} · ${event.ok?'已执行':'未完成'}${event.validation_pass===false?' · 留出未通过':''}`;if(!event.ok){status(event.error||'原生工具执行未完成');continue;}if(event.study_id){panel.open=true;await showStudy(event.study_id,!!event.run_id);}else if(event.experiment_id||event.analysis_id||event.run_id){await window.DAYAN_RESULTS?.restore(event.experiment_id||event.analysis_id||event.run_id);}else if(event.dataset_id){await window.DAYAN_RESULTS?.openDataManager(event.dataset_id);}else if(event.collection_id){currentCollection=event.collection_id;if($('#researchCollection'))$('#researchCollection').value=currentCollection;status(`真实采集 ${event.n_records??'?'} 条 · ${event.artifact_role||'待检查'} · ${event.status||''} · ${event.collection_id}；需显式绑定后才进入模型。`);}if(event.file){$('#studyReportLinks')?.insertAdjacentHTML('beforeend',`<a href="${esc(event.file)}" download>下载原生AI本次报告</a>`);}}}catch(e){banner.textContent='原生结果同步未完成：'+e.message;}finally{following=false;}};
      follow();window.setInterval(follow,2000);
    }
  }
  async function associateRun(runId) {
    if(window.DAYAN_STUDY?.run_id===runId)return;
    const r=await request('/api/research/for_run/'+encodeURIComponent(runId));
    if(r.study)await showStudy(r.study.study_id);
    else window.DAYAN_STUDY=null;
  }
  function clearContext(){window.DAYAN_STUDY=null;$('#studyDiagnostics')?.remove();$('#studyValidationBar')?.remove();}
  let sourceTask;
  function loadSources(force=false){
    const host=$('#dsContent');if(!host)return;
    if(force)sourceTask=null;
    return sourceTask ||= paintSources(host);
  }
  function mount(host){
    const panel=$('#researchPanel');
    if(!panel||!host||panel.parentElement===host)return;
    const parent=panel.parentElement,button=document.createElement('button');
    button.className='rail-ai-link';button.textContent='真实数据校准与验证 →';
    button.onclick=()=>{switchPage('lab'); document.querySelector('[data-lab-tab=calibration]')?.click();};
    parent.prepend(button);
    host.append(panel);panel.open=true;
  }
  window.DAYAN_RESEARCH={loadSources,showStudy,associateRun,clearContext,mount};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
