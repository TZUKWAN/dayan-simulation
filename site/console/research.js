/* Real collection and versioned research controls; DSH embed follows only its own native session. */
(() => {
  'use strict';
  const $ = s => document.querySelector(s), esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const query = new URLSearchParams(location.search), nativeSession = query.get('dsh_session');
  let currentStudy = query.get('study'), currentCollection = null, studyRevision = 0;
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
  function connectNative(panel) {
    const banner=document.createElement('div');
    banner.id='nativeContextBar';
    banner.textContent=nativeSession?'DSH 原生会话已连接 · 此工作台只同步当前会话真实结果':'DSH原生会话尚未连接';
    $('#pageOverview')?.prepend(banner);
    window.DAYAN_NATIVE_BRIDGE={draft(text){
      if(!nativeSession){announce('DSH原生会话尚未连接，请等待连接完成后重试。');return;}
      window.parent.postMessage({type:'dayan:native-draft',sessionId:nativeSession,text},query.get('parent_origin')||location.origin);
      announce('草稿已交给DSH原生输入框，请在左侧发送。');
    }};
    if(!nativeSession)return;

    const key='dayan_native_workspace_vnext:'+nativeSession;
    let checkpoint={after:0,target:null,page:null}, following=false, ready=false;
    try{checkpoint={...checkpoint,...JSON.parse(sessionStorage.getItem(key)||'null')};}catch{}
    const save=()=>{try{sessionStorage.setItem(key,JSON.stringify(checkpoint));}catch{}};
    const view=window.DAYAN_RESULTS;
    window.addEventListener('dayan:result',e=>{
      const id=view.payload?.experiment_id||view.payload?.analysis_id||e.detail;
      if(id){checkpoint.target={kind:'record',id};if(ready)save();}
    });
    window.addEventListener('dayan:page',e=>{if(ready){checkpoint.page=e.detail;save();}});
    const open=async({kind,id,restoreRun})=>{
      if(kind==='record'&&!await view.restore(id))return;
      if(kind==='study'){panel.open=true;await showStudy(id,restoreRun);}
      if(kind==='dataset'){view.datasetFocus=id;await switchPage('data');}
      if(kind==='collection'){currentCollection=id;$('#researchCollection').value=id;}
      checkpoint.target={kind,id,restoreRun};
    };
    const follow=async()=>{
      if(following||document.hidden)return;
      following=true;
      try{
        const r=await request('/api/integrations/dsh/events?session_id='+encodeURIComponent(nativeSession)+'&after='+checkpoint.after);
        for(const event of r.events){
          banner.textContent=`DSH实际工具 ${event.tool} · ${event.ok?'已执行':'未完成'}${event.validation_pass===false?' · 留出未通过':''}`;
          if(!event.ok)status(event.error||'原生工具执行未完成');
          else{
            const record=event.experiment_id||event.analysis_id||event.run_id;
            if(event.study_id)await open({kind:'study',id:event.study_id,restoreRun:!!event.run_id});
            else if(record)await open({kind:'record',id:record});
            else if(event.dataset_id)await open({kind:'dataset',id:event.dataset_id});
            else if(event.collection_id){
              await open({kind:'collection',id:event.collection_id});
              status(`真实采集 ${event.n_records??'?'} 条 · ${event.artifact_role||'待检查'} · ${event.status||''} · ${event.collection_id}；需显式绑定后才进入模型。`);
            }
            if(event.file)$('#studyReportLinks')?.insertAdjacentHTML('beforeend',`<a href="${esc(event.file)}" download>下载原生AI本次报告</a>`);
          }
          checkpoint.after=event.seq;
          checkpoint.banner=banner.textContent;
          save();
        }
      }catch(e){banner.textContent='原生结果同步未完成：'+e.message;}
      finally{following=false;}
    };
    async function resume(){
      try{
        if(!query.has('run')&&!query.has('study')&&checkpoint.target){
          await open(checkpoint.target);
          if(checkpoint.page)switchPage(checkpoint.page,false);
          if(checkpoint.banner)banner.textContent=checkpoint.banner;
        }
      }catch(e){
        checkpoint={after:0,target:null,page:null};
        banner.textContent='正在从会话记录重新同步：'+e.message;
      }
      ready=true;save();follow();window.setInterval(follow,2000);
      document.addEventListener('visibilitychange',()=>{if(!document.hidden)follow();});
    }
    queueMicrotask(resume);
  }
  function paintDiagnostics(s) {
    $('#studyDiagnostics')?.remove();
    const cal=s.calibration;if(!cal?.training||!cal?.holdout?.predicted||!s.predictions)return;
    const plots=window.DAYAN_CHARTS;if(!plots)return;
    const fit=new Map(s.predictions.map(r=>[r.date,r.predicted]));
    const validation=cal.selection?.validation, test=cal.holdout, uncertainty=cal.uncertainty;
    const stages=[['训练',cal.training],...(validation?[['验证',validation]]:[]),['独立测试',test]];
    const years=s.records.map(r=>r.date);
    const stride=Math.max(1,Math.ceil((years.length-1)/5));
    const yearTicks=years.filter((_,i)=>i%stride===0||i===years.length-1).map(year=>[year,String(year)]);
    const events=[{x:test.dates[0],label:'独立测试开始'}];
    if(validation)events.push({x:validation.dates[0],label:'验证开始'});
    const band=uncertainty?.holdout_interval.map(([a,b],i)=>[uncertainty.holdout_dates[i],a,b]);
    const grid=cal.evaluations.filter(e=>Number.isFinite(e.loss));
    const variable=Object.keys(s.param_grid||{}).length===1?Object.keys(s.param_grid)[0]:null;
    const evaluated=e=>variable?e.params[variable]:e.combo_id;
    const titles=['实测与模型轨迹','误差与基线','逐年残差','参数敏感性'];
    const section=document.createElement('section');section.id='studyDiagnostics';section.dataset.studyId=s.study_id;section.dataset.runId=s.run_id;
    section.innerHTML=`<div class="study-caption"><b>模型诊断</b><span>${esc(s.contract.country)} · ${esc(s.contract.indicator)} · ${esc(s.contract.date)} · ${esc(s.study_id)}</span></div><div class="study-chart-grid">${titles.map(title=>`<article class="panel"><div class="panel-head"><h2>${title}</h2></div><div class="chart-host"></div></article>`).join('')}</div>`;
    if(document.body.dataset.page==='lab'&&$('#labCalibration'))$('#labCalibration').append(section);
    else $('#pageOverview .workspace-grid')?.after(section);
    const host=section.querySelectorAll('.chart-host');
    plots.plot(host[0],{title:titles[0],xUnit:'年度',yUnit:s.unit,xTicks:yearTicks,events,series:[
      {label:'统计观测',points:s.records.map(r=>[r.date,r.value])},
      {label:'模型运行'+(band?' / 训练残差经验带':''),points:s.predictions.map(r=>[r.date,r.predicted]),band,dashed:true},
    ]});
    const metrics=[...stages.map(([key,role])=>[key,role.rmse??cal.best_loss]),['测试 · 训练均值',test.baseline_train_mean_rmse]];
    if(Number.isFinite(test.baseline_last_training_rmse))metrics.push(['测试 · 训练末值',test.baseline_last_training_rmse]);
    plots.plot(host[1],{title:titles[1],xUnit:'评估角色与基线',yUnit:s.unit,zero:true,xRange:[-.55,metrics.length-.45],
      xTicks:metrics.map(([key],i)=>[i,key]),series:[
      {label:'RMSE',kind:'bars',points:metrics.map(([k,v],i)=>[i,v,k])},
      {label:'事前测试阈值',dashed:true,points:[[0,s.tolerance],[metrics.length-1,s.tolerance]]},
    ]});
    plots.plot(host[2],{title:titles[2],xUnit:'年度',yUnit:s.unit,xTicks:yearTicks,zero:true,events,
      series:stages.map(([label,role])=>({label,kind:'bars',points:role.dates.map((year,i)=>[year,role.actual[i]-fit.get(year),label])})),
      note:'残差为实际观测减模型预测。'});
    plots.plot(host[3],{title:titles[3],xUnit:variable||'组合序号',yUnit:'RMSE · '+s.unit,
      series:[{label:'训练损失',kind:'scatter',points:grid.map(e=>[evaluated(e),e.loss])},
        ...(cal.selection?[{label:'短名单验证损失',kind:'scatter',points:cal.selection.finalists.map(e=>[evaluated(e),e.rmse])}]:[])],
      note:`${cal.n_evaluated} / ${cal.grid_size} 组实际执行 · ${cal.n_failed} 组失败`});
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
  async function showStudy(id,restore=false,accepted=()=>true) {
    const revision=++studyRevision;
    const r=await request('/api/research/studies/'+encodeURIComponent(id));if(revision!==studyRevision||!accepted())return;
    const s=r.study;currentStudy=id;window.DAYAN_STUDY=s;
    const cal=s.calibration, host=$('#researchEvidence');if(!host)return;
    paintDiagnostics(s);
    let validationBar=$('#studyValidationBar');
    if(!validationBar){validationBar=document.createElement('div');validationBar.id='studyValidationBar';validationBar.style.cssText='padding:8px 12px;font-size:12px;line-height:1.6;border-bottom:1px solid #40536a;background:#142331';$('#pageOverview')?.prepend(validationBar);}
    validationBar.innerHTML=`${esc(s.contract.country)} · ${esc(s.contract.definition.concept)} · ${esc(s.contract.date)}　<strong class="${cal&&cal.status!=='pass'?'research-error':''}">${esc(cal?.status||'尚未校准')}</strong>${cal?`　训练 RMSE ${esc(cal.best_loss?.toPrecision(5))} · 留出 ${esc(cal.holdout?.rmse?.toPrecision(5))} · 事前阈值 ${esc(s.tolerance)}（${esc(s.unit)}原单位）`:''}`;
    host.innerHTML=`<strong>${esc(s.question)}</strong><p>${esc(s.study_id)}<br>${esc(s.model_family)} · ${esc(s.contract.country)} · ${esc(s.contract.indicator)} · ${esc(s.unit)}</p>
    <div class="research-time-roles">${[['训练',s.training],['验证',s.validation],['独立测试',s.holdout]].filter(([,rows])=>rows?.length).map(([name,rows])=>`<span><b>${name}</b> <code>${rows[0].date}–${rows.at(-1).date}</code></span>`).join('')}</div>
    <p>${cal?`执行 ${esc(s.phase)} · 验证 <b class="${cal.status==='pass'?'':'research-error'}">${esc(cal.status)}</b><br>训练 RMSE ${esc(cal.best_loss?.toPrecision(6))}${cal.selection?.validation?` · 验证 ${esc(cal.selection.validation.rmse.toPrecision(6))}`:''} · 测试 ${esc(cal.holdout?.rmse?.toPrecision(6))} · 事前阈值 ${esc(s.tolerance)} ${esc(s.unit)}`:'合同已保存，可执行校准与独立测试。'}</p>
    <details><summary>数据绑定与模型依据</summary><pre>${esc(JSON.stringify({collection_id:s.collection_id,dataset_id:s.training_dataset.dataset_id,data_binding:s.data_binding,run_id:s.run_id,model_id:s.model_id,best_params:cal?.best_params,study_sha256:s.artifact_sha256,limitations:s.limitations},null,2))}</pre></details>
    ${s.run_id?`<button type="button" id="openStudyRun">在大屏查看实际运行</button>`:''}<div id="studyReportLinks"></div>`;
    if(s.run_id){$('#openStudyRun').onclick=()=>window.DAYAN_RESULTS?.restore(s.run_id);if(restore)await window.DAYAN_RESULTS?.restore(s.run_id);}
    const reportLabels={academic:'学术报告',data_quality:'数据质量报告',policy:'政策适用性简报'};
    for(const report of r.reports||[]){
      if(!report.file){const txt=document.createElement('p');txt.textContent=report.label+' · '+report.error;$('#studyReportLinks').append(txt);continue;}
      const a=document.createElement('a');a.href=report.file;a.download='';a.textContent='下载'+(reportLabels[report.kind]||'已生成报告');$('#studyReportLinks').append(a);
    }
    $('#studyEditor').open=false;
    $('#calibrateStudy').disabled=$('#calibrateStudy').hidden=s.phase!=='prepared';
    for(const b of document.querySelectorAll('[data-study-report]'))b.disabled=!s.run_id||!Number.isFinite(cal?.holdout?.rmse);
    status(cal?`实际研究已保存 · ${cal.status}；报告将保留这个验证结论。`:'研究合同已准备；使用独立留出集执行校准。');
    return s;
  }
  function boot() {
    const style=document.createElement('style');style.textContent=`.preset-form,#studyForm{display:grid;gap:7px;padding:8px 0}.preset-form label,#studyForm label{display:grid;gap:3px;font-size:11px}.preset-form input,#studyForm input,#studyForm textarea,#studyForm select{box-sizing:border-box;max-width:100%;width:100%;padding:5px;background:#101c29;border:1px solid #40536a;color:#d5e9ef}.research-scroll{max-height:260px;overflow:auto}.research-scroll table{width:100%;font-size:10px;border-collapse:collapse}.research-scroll td{border-bottom:1px solid #314254;padding:5px}.research-task{padding:8px 0;border-bottom:1px solid #314254}.research-task p,.research-note,#researchEvidence{font-size:11px;line-height:1.5}.research-task small{overflow-wrap:anywhere}#researchEvidence pre{white-space:pre-wrap;word-break:break-all;font-size:10px}#researchStatus{font-size:11px;line-height:1.5;white-space:pre-wrap}.research-error{color:#ffb380}#studyReportLinks a{display:inline-block;margin:6px}.dsh-native-embed #aiDrawer,.dsh-native-embed [data-rail-tab="ai"]{display:none!important}.dsh-native-embed.mode-simple #operationRail{display:none!important}.dsh-native-embed.mode-simple #commandShell{grid-template-columns:minmax(0,1fr)!important}.dsh-native-embed #assistantButton,.dsh-native-embed .ai-fab{display:none!important}@media(min-width:581px) and (max-width:1100px){.dsh-native-embed .analysis-column{grid-template-columns:minmax(0,1fr)}}#nativeContextBar{padding:6px 12px;font-size:11px;color:#9cc8dc;border-bottom:1px solid #314254}`;document.head.append(style);
    const host=$('#proConsole');if(!host)return;
    const panel=document.createElement('details');panel.id='researchPanel';panel.innerHTML=`<summary>真实数据建模与独立验证</summary><form id="studyForm"><label>原始研究问题（地区、指标、年份、模型）<textarea id="researchQuestionInput" required rows="3"></textarea></label><label>完整采集批次<input id="researchCollection" required placeholder="collection_id"></label><label>描述性模型<select id="researchFamily"><option value="linear">线性趋势</option><option value="exponential">指数趋势</option><option value="logistic">Logistic 增长</option></select></label><label>参数网格 JSON<textarea id="researchGrid" required rows="2" placeholder='例如 {"slope":[-0.5,0,0.5]}'></textarea></label><label>事前 RMSE 阈值（原单位）<input id="researchTolerance" type="number" min="0" step="any" required></label><label>末尾独立测试年份<input id="researchHoldout" type="number" min="1" value="2" required></label><label>训练与测试之间的验证年份（0 为两段）<input id="researchValidation" type="number" min="0" value="0" required></label><label>进入验证的训练排序前几名<input id="researchSelection" type="number" min="1" max="30" value="3" required></label><button>保存研究合同</button></form><button id="calibrateStudy" disabled>执行校准与独立测试</button><p><button data-study-report="academic" disabled>学术报告</button> <button data-study-report="data_quality" disabled>数据质量报告</button> <button data-study-report="policy" disabled>政策适用性简报</button></p><div id="researchStatus" role="status">填写原始问题和已完成的实际采集批次。</div><div id="researchEvidence"></div><details><summary>已保存研究</summary><div id="studyHistory"></div><button id="refreshStudies">刷新研究列表</button></details>`;
    const form=panel.querySelector('#studyForm'), editor=document.createElement('details');
    editor.id='studyEditor';editor.open=!currentStudy;editor.innerHTML='<summary>新建研究合同</summary>';
    form.before(editor);editor.append(form);
    host.prepend(panel);
    $('#refreshSources').onclick=()=>loadSources(true);
    mountSpatialSource();
    $('#studyForm').onsubmit=async e=>{e.preventDefault();const button=e.currentTarget.querySelector('button');button.disabled=true;status('校验国家、指标、时期、单位与数据角色…');try{const r=await tool('research_create',{question:$('#researchQuestionInput').value,collection_id:$('#researchCollection').value,model_family:$('#researchFamily').value,param_grid:JSON.parse($('#researchGrid').value),tolerance:Number($('#researchTolerance').value),holdout_years:Number($('#researchHoldout').value),validation_years:Number($('#researchValidation').value),selection_top:Number($('#researchSelection').value)});await showStudy(r.payload.study_id);}catch(error){status('合同未建立：'+error.message);}finally{button.disabled=false;}};
    $('#calibrateStudy').onclick=async()=>{const button=$('#calibrateStudy');button.disabled=true;status('使用统一仿真引擎实际评估参数网格…');try{const r=await tool('research_calibrate',{study_id:currentStudy});await showStudy(r.payload.study_id);}catch(e){status('校准未完成：'+e.message);button.disabled=false;}};
    for(const button of panel.querySelectorAll('[data-study-report]'))button.onclick=async()=>{
      const id=currentStudy;button.disabled=true;status('核对研究版本并生成同源报告…');
      try{
        const r=await tool('research_report',{study_id:id,kind:button.dataset.studyReport});
        if(currentStudy!==id)return;
        $('#studyReportLinks').insertAdjacentHTML('beforeend',`<a href="${esc(r.payload.file)}" download>下载本研究${esc(button.textContent)}</a><a href="${esc(r.payload.bundle_url)}" download>复现包</a>`);
        status('报告已生成 · 验证结论 '+r.payload.validation_status);
      }catch(e){if(currentStudy===id)status('报告未生成：'+e.message);}
      finally{if(currentStudy===id)button.disabled=false;}
    };
    async function history(){const r=await request('/api/research/studies');$('#studyHistory').innerHTML=r.studies.map(s=>`<button data-saved-study="${esc(s.study_id)}">${esc(s.question||s.study_id)} · ${esc(s.calibration?.status||s.phase)}</button>`).join('')||'尚无研究';for(const b of panel.querySelectorAll('[data-saved-study]'))b.onclick=()=>showStudy(b.dataset.savedStudy).catch(e=>status(e.message));}
    $('#refreshStudies').onclick=()=>history().catch(e=>status(e.message));history().catch(e=>status(e.message));
    if(currentStudy)showStudy(currentStudy).catch(e=>status(e.message));
    window.addEventListener('dayan:page', e=>{
      const s=window.DAYAN_STUDY, selected=window.DAYAN_RESULTS?.runs[window.DAYAN_RESULTS.selected]?.run_id;
      if(s&&(e.detail==='lab'||e.detail==='overview'&&selected===s.run_id))paintDiagnostics(s);
    });
    if(query.get('embed')==='dsh') {
      document.body.classList.add('dsh-native-embed');
      if(!query.get('run'))window.DAYAN_RESULTS?.clear();
      connectNative(panel);
    }
  }
  async function associateRun(runId,accepted=()=>true) {
    if(window.DAYAN_STUDY?.run_id===runId)return;
    const r=await request('/api/research/for_run/'+encodeURIComponent(runId));
    if(!accepted())return;
    if(r.study)await showStudy(r.study.study_id,false,accepted);
    else window.DAYAN_STUDY=null;
  }
  function clearContext(){window.DAYAN_STUDY=null;$('#pageOverview #studyDiagnostics')?.remove();$('#studyValidationBar')?.remove();}
  let sourceTask;
  function mountSpatialSource(){
    const host=$('#spatialSource');
    host.innerHTML=`<details class="tool-detail"><summary>TIGERweb 2020 路网与普查人口</summary><form class="tool-form" id="censusSceneForm">
      <div class="tool-columns">${[['west','西经度'],['south','南纬度'],['east','东经度'],['north','北纬度']].map(([axis,name])=>`<label>${name}<input name="${axis}" type="number" step="any" required></label>`).join('')}</div>
      <fieldset><legend>道路类别</legend><label><input type="checkbox" name="road" value="local" checked>地方道路</label><label><input type="checkbox" name="road" value="secondary" checked>次级道路</label><label><input type="checkbox" name="road" value="primary" checked>主要道路</label></fieldset>
      <button class="ws-button ws-primary">采集同范围空间输入</button><output id="censusSceneStatus" role="status"></output><div id="censusSceneLinks" class="space-actions"></div>
      </form></details>`;
    $('#censusSceneForm').onsubmit=async e=>{
      e.preventDefault();
      const form=e.currentTarget,submit=form.querySelector('button'),input=new FormData(form),out=$('#censusSceneStatus');
      const links=$('#censusSceneLinks');
      submit.disabled=true;links.replaceChildren();out.textContent='读取官方地理图层并归档原始响应…';
      try{
        const {payload:{roads,population}}=await tool('collect_census_scene',{
          bbox:['west','south','east','north'].map(key=>Number(input.get(key))),road_classes:input.getAll('road')});
        out.textContent=`${roads.n_records} 条道路 · ${population.n_records} 个普查区 · ${population.metadata.population} 人`;
        for(const [label,asset] of [['路网',roads],['人口',population]]){
          const action=document.createElement('button');action.className='ws-button';action.type='button';
          action.textContent=label+' '+asset.dataset_id;
          action.onclick=()=>window.DAYAN_RESULTS.openDataManager(asset.dataset_id);
          links.append(action);
        }
        const use=document.createElement('button');use.className='ws-button';use.type='button';use.id='useCensusScene';use.textContent='在 CPL001 检查输入与参数 ↗';
        use.onclick=async()=>{
          await window.DAYAN_COMMAND.chooseModel('CPL001');
          const model=document.querySelector('[data-model-param=roads_dataset_id]'),people=document.querySelector('[data-model-param=population_dataset_id]');
          if(!model||!people){announce('未取得 CPL001 参数合同');return;}
          model.value=roads.dataset_id;people.value=population.dataset_id;
        };
        links.append(use);
        await window.DAYAN_RESULTS.openDataManager(population.dataset_id);
      }catch(error){out.textContent='空间输入未完成 · '+error.message;}
      finally{submit.disabled=false;}
    };
  }
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
    if(window.DAYAN_STUDY)paintDiagnostics(window.DAYAN_STUDY);
  }
  window.DAYAN_RESEARCH={loadSources,showStudy,associateRun,clearContext,mount};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
