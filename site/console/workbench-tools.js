/* Catalog, research design and archive navigation. Running always uses the engine API. */
(() => {
  'use strict';
  const {api,catalog,esc,date,empty,write,preference,validations} = window.DAYAN_WORKBENCH;
  const $ = selector => document.querySelector(selector);
  const showError = (id,error) => write(id,error.message || error);
  const json = data => JSON.stringify(data,null,2);
  const slug = value => encodeURIComponent(value);
  const human = value => typeof value === 'object' ? JSON.stringify(value) : value;
  const classNames = {ECO:'经济与产业',NET:'网络与传播',SYS:'系统与排队',BEH:'行为与主体',CPL:'多机制耦合',MET:'统计方法',APP:'应用场景',USR:'研究自定义'};
  const family = mid => /^[A-Z]+/.exec(mid)?.[0] || mid;
  const cjkStatus = {...validations,pass:'独立测试通过',failed_tolerance:'训练阈值未通过',integrity_failed:'档案校验异常'};
  const stages = [['contract','研究规约'],['experiment','配对实验'],['calibration','真实数据验证']];
  const safeUrl = url => typeof url==='string' && /^(https?:\/\/[^\s]+|\/api\/[A-Za-z0-9_%/?.-]+|\/reports\/[A-Za-z0-9_%/?.-]+)$/.test(url);
  const ref = (url,label) => safeUrl(url) ? `<a href="${esc(url)}" ${url.startsWith('http')?'target="_blank" rel="noopener noreferrer"':''}>${esc(label)}</a>` : '';
  let modelRows=[], openModelId=null, modelRevision=0, initializedModels=false;
  const catalogContracts=new Map();
  async function contract(mid) {
    if(!catalogContracts.has(mid)) catalogContracts.set(mid,await api('/api/models/contract/'+slug(mid)));
    return catalogContracts.get(mid);
  }
  function panel(title, html, extra='') {
    return `<section class="panel ${extra}"><div class="panel-head"><h2>${title}</h2></div><div class="tool-body">${html}</div></section>`;
  }
  const options = (rows, placeholder) => `<option value="">${esc(placeholder)}</option>` +
    rows.map(([id,name])=>`<option value="${esc(id)}">${esc(name)}</option>`).join('');
  function linkMap(row) {
    const mechanisms=new Set(row.mechanisms || []);
    const names=modelRows.filter(m=>m.model_id!==row.model_id && m.has_factory).map(m=>({row:m,parts:(m.mechanisms||[]).filter(x=>mechanisms.has(x))}))
      .filter(m=>m.parts.length).sort((a,b)=>b.parts.length-a.parts.length||Number(b.row.reviewed)-Number(a.row.reviewed)||a.row.model_id.localeCompare(b.row.model_id)).slice(0,6);
    const colors=window.DAYAN_CHARTS.colors;
    const entries=names.length?names.map(({row:m,parts})=>({id:m.model_id,text:m.name,parts,model:true})):
      [...mechanisms].map(x=>({id:x,text:x,parts:['声明覆盖的机制']})).concat(
        Object.entries(row.output_contract?.fields||{}).filter(([k,f])=>k!=='sim_t'&&f.type==='number').slice(0,4).map(([k,f])=>({id:k,text:k,parts:['观测输出',f.unit||'模型原单位']})));
    if(!entries.length)return empty('此条目暂无机制关系或可核对的输出字段。');
    const nodes=entries.slice(0,7).map((node,i,list)=>{
      const angle=(i/list.length)*2*Math.PI - Math.PI/2;
      return {...node,x:Math.round(345+233*Math.cos(angle)),y:Math.round(140+91*Math.sin(angle)),color:colors[i%colors.length]};
    });
    return `<div class="model-network"><svg viewBox="0 0 690 280" role="group" aria-label="共享机制的模型关系">
      <defs><pattern id="modelDots" width="20" height="20" patternUnits="userSpaceOnUse"><circle r="1" cx="2" cy="2" fill="#30435a"/></pattern></defs>
      <rect width="690" height="280" fill="url(#modelDots)"/>
      ${nodes.map(node=>`<path d="M345 140 Q${node.x} 140 ${node.x} ${node.y}" stroke="${node.color}" stroke-opacity=".55" stroke-width="${1+node.parts.length*.6}" fill="none"><title>${esc(node.parts.join('、'))}</title></path>`).join('')}
      <rect x="288" y="112" width="114" height="56" rx="4" fill="#13434e" stroke="#6ee0dd"/>
      <text x="345" y="146" fill="#ecffff" text-anchor="middle" font-family="monospace" font-size="16">${esc(row.model_id)}</text>
      ${nodes.map(node=>`<g ${node.model?`tabindex="0" role="button" data-model-open="${esc(node.id)}" aria-label="${esc(node.id+' '+node.text+' · 共享 '+node.parts.join('、'))}"`:''}><title>${esc(node.text+' · '+node.parts.join('、'))}</title><rect x="${node.x-55}" y="${node.y-17}" width="110" height="34" rx="3" fill="#132338" stroke="${node.color}"/><text x="${node.x}" y="${node.y+4}" fill="#dceaf7" text-anchor="middle" font-size="13" font-family="monospace">${esc(node.id.length>12?node.id.slice(0,11)+'…':node.id)}</text></g>`).join('')}
      </svg><p class="space-note">${names.length?'边表示目录中已登记的共同机制。悬停核对机制，选择邻居查看合同。':'连接指向该模型明确声明的机制和观测字段，悬停查看含义。'}</p></div>`;
  }
  function parametersTable(params) {
    const items=Object.entries(params||{});
    return items.length ? `<div class="table-scroll"><table class="workbench-table"><thead><tr><th>参数</th><th>类型 / 单位</th><th>默认值</th><th>可干预</th></tr></thead><tbody>${items.map(([key,p])=>`<tr><td><code>${esc(key)}</code></td><td>${esc(p.type)} · ${esc(p.unit||'模型定义')}</td><td>${esc(p.required?'必须提供':human(p.default))}</td><td>${p.mutable_at_runtime?'声明支持':'—'}</td></tr>`).join('')}</tbody></table></div>`
      : empty('无独立构造参数。');
  }
  function paintModel(row, material, error='') {
    if(!row)return;
    const meta=material?.fidelity || row, c=material?.contract;
    const fields=Object.entries(row.output_contract?.fields || {});
    const cfg=row.required_data||[];
    const mechanisms=(row.mechanisms||[]).map(m=>`<span class="mechanism-tag">${esc(m)}</span>`).join('');
    const sources=(meta.review_sources||[]).map(s=>ref(s.url,s.title||s.url)).filter(Boolean);
    $('#modelDetail').innerHTML=`<section class="model-intro"><div><p class="space-kicker"><code>${esc(row.model_id)}</code> · ${esc(row.protocol||row.layer||'引用')}</p><h3>${esc(row.name)}</h3><p>${esc(row.description?.split('\n')[0] || row.basis)}</p><div class="tag-row">${mechanisms}</div></div>
      <div class="space-actions"><button class="ws-button" id="pinModel">加入比较</button><button class="ws-button ws-primary" id="runModelDetail" ${row.has_factory?'':'disabled'}>检查参数并运行 ↗</button></div></section>
      <div class="model-evidence-grid">
        ${panel('机制关系',linkMap(row),'model-map-panel')}
        ${panel('科学与执行证据',`<dl class="fact-list"><dt>实现级别</dt><dd>${esc(meta.fidelity_zh)}</dd><dt>运行入口</dt><dd>${esc(meta.entry_status)}</dd><dt>机制审查</dt><dd>${esc(meta.reviewed?'与当前实现匹配':meta.review_status==='stale_or_unanchored'?'历史资料待复核':'尚未完成')}</dd><dt>站点校准</dt><dd>以具体研究规约、实测数据和独立测试判定</dd><dt>依据</dt><dd>${esc(meta.basis)}</dd><dt>适用范围 / 假设</dt><dd>${esc(meta.simplifications?.join('；')||'见模型定义与原始文献')}</dd><dt>数据要求</dt><dd>${esc(cfg.join('、')||'构造器与研究设计声明')}</dd><dt>依赖状态</dt><dd>${esc((c?.dependencies||meta.dependencies)?.map(d=>d.name+' · '+({requires_configuration:'需配置',configured_not_probed:'已配置，未发出调用',missing_configuration:'缺少配置',invalid_configuration:'配置不可读取',requires_saved_dataset:'需选择归档数据集'}[d.state]||d.state)).join('、')||'本地计算')}</dd></dl>
          ${sources.length?`<div class="tag-row">${sources.join('')}</div>`:''}${meta.evidence?`<p class="space-note">${esc(meta.evidence)}</p>`:''}`)}
      </div>
      ${panel('参数与输入输出合同',(!row.has_factory?empty(row.entry_kind==='software_reference'?'外部软件登记，使用对应软件及所在环境执行。':'无内置执行合同。'):error?empty(error):!c?empty('读取参数合同…'):parametersTable(c.params))+ (fields.length?`<details class="tool-detail"><summary>查看观测输出字段（${fields.length}）</summary><div class="table-scroll"><table class="workbench-table"><thead><tr><th>指标</th><th>类型</th><th>单位</th><th>证据</th></tr></thead><tbody>${fields.map(([key,f])=>`<tr><td>${esc(key)}</td><td>${esc(f.type)}</td><td>${esc(f.unit||'由模型定义')}</td><td>${esc(f.source||row.output_contract.evidence_status||'输出合同')}</td></tr>`).join('')}</tbody></table></div></details>`:'') )}`;
    $('#runModelDetail').onclick=()=>window.DAYAN_COMMAND.chooseModel(row.model_id);
    $('#pinModel').textContent=pinned.includes(row.model_id)?'从比较移除':'加入比较';
    $('#pinModel').onclick=()=>pin(row.model_id);
    for(const node of $('#modelDetail').querySelectorAll('[data-model-open]')) {
      node.onclick=()=>openModel(node.dataset.modelOpen);
      node.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();node.onclick();}};
    }
  }
  async function openModel(mid) {
    if(!initializedModels)await models(false);
    const row=modelRows.find(m=>m.model_id===mid);
    if(!row)throw new Error('目录中没有模型 '+mid);
    const revision=++modelRevision;
    openModelId=mid;
    $('#modelSelection').textContent=mid;
    for(const b of $('#modelRows').querySelectorAll('button')) b.setAttribute('aria-pressed',String(b.dataset.modelOpen===mid));
    if(!row.has_factory) {paintModel(row,null);return;}
    paintModel(row,catalogContracts.get(mid));
    try {const c=await contract(mid);if(revision===modelRevision)paintModel(row,c);}
    catch(error) {if(revision===modelRevision)paintModel(row,null,error.message);}
  }
  let modelOffset=0;
  function compareFilters() {
    const terms=$('#modelSearch').value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const f=$('#modelFamily').value,p=$('#modelProtocol').value,e=$('#modelEvidence').value,d=$('#modelData').value;
    return modelRows.filter(m=>(!f||family(m.model_id)===f)&&(!p||(m.protocol||'none')===p)
      &&(!e||(e==='reviewed'?m.reviewed:e==='references'?!m.has_factory:m.probe.status===e))
      &&(!d||(d==='explicit'?m.required_data?.length>0:d==='external'?m.requires_external:!(m.required_data?.length||m.requires_external)))
      &&terms.every(t=>[`${m.model_id} ${m.name} ${m.basis} ${m.description} ${m.mechanisms.join(' ')}`.toLowerCase()].some(v=>v.includes(t))));
  }
  function paintModelRows() {
    const rows=compareFilters(), page=rows.slice(modelOffset,modelOffset+26);
    write('#modelCount',`${rows.length} 个匹配 · ${rows.length?modelOffset+1:0}–${modelOffset+page.length}`);
    $('#modelRows').innerHTML=page.length?page.map(m=>`<button class="model-result" data-model-open="${esc(m.model_id)}" aria-pressed="${m.model_id===openModelId}"><div><code>${esc(m.model_id)}</code><b>${esc(m.name)}</b></div><small>${esc(m.fidelity_zh)} · ${esc(m.reviewed?'当前机制审查':m.entry_status)}</small></button>`).join(''):empty('没有匹配的模型。');
    for(const b of $('#modelRows').querySelectorAll('button'))b.onclick=()=>openModel(b.dataset.modelOpen);
    $('#modelPrev').disabled=modelOffset===0;
    $('#modelNext').disabled=modelOffset+26>=rows.length;
  }
  const pinned=[];
  function pin(mid) {
    const i=pinned.indexOf(mid);
    if(i>=0)pinned.splice(i,1);
    else {if(pinned.length>=3)pinned.shift();pinned.push(mid);}
    write('#modelComparisonLabel',pinned.join(' / ')||'尚未选择');
    $('#compareModels').disabled=pinned.length<2;
    $('#pinModel').textContent=pinned.includes(mid)?'从比较移除':'加入比较';
  }
  async function models(autoSelect=true) {
    if(initializedModels)return;
    const el=$('#modelsTable');el.innerHTML=empty('正在读取统一模型能力目录…');
    const data=await catalog();
    if(initializedModels)return;
    modelRows=data.models;
    const prefixes=[...new Set(modelRows.map(m=>family(m.model_id)))].sort();
    const protocols=[...new Set(modelRows.map(m=>m.protocol||'none'))].sort();
    el.innerHTML=`<div class="tool-bar"><label class="search-control">搜索模型<input id="modelSearch" type="search" placeholder="模型名、ID 或机制"></label>
      <label>研究领域<select id="modelFamily">${options(prefixes.map(f=>[f,classNames[f]||f]),'全部领域')}</select></label>
      <label>运行范式<select id="modelProtocol">${options(protocols.map(p=>[p,p==='none'?'无工厂':p]),'全部范式')}</select></label>
      <label>证据<select id="modelEvidence">${options([['reviewed','当前机制审查'],['passed','当前探针通过'],['failed','探针失败'],['references','仅登记/引用']],'全部状态')}</select></label>
      <label>输入与依赖<select id="modelData">${options([['explicit','需要明确数据集'],['external','需要外部服务'],['standalone','本地执行']],'全部输入')}</select></label></div>
      <div class="model-layout"><aside class="panel model-roster"><div class="panel-head"><h2 id="modelCount">目录</h2><code id="modelSelection"></code></div><div id="modelRows"></div><div class="pager"><button id="modelPrev">上一页</button><button id="modelNext">下一页</button></div><div class="model-compare-controls"><span id="modelComparisonLabel">尚未选择</span><button id="compareModels" class="ws-button" disabled>比较合同</button></div></aside><div id="modelDetail"></div></div>`;
    initializedModels=true;
    for(const id of ['#modelSearch','#modelFamily','#modelProtocol','#modelEvidence','#modelData']) $(id).oninput=()=>{modelOffset=0;paintModelRows();};
    $('#modelPrev').onclick=()=>{modelOffset=Math.max(0,modelOffset-26);paintModelRows();};
    $('#modelNext').onclick=()=>{modelOffset+=26;paintModelRows();};
    $('#compareModels').onclick=async()=>{
      const chosen=pinned.map(id=>modelRows.find(m=>m.model_id===id));
      const material=await Promise.allSettled(chosen.map(m=>m.has_factory?contract(m.model_id):null));
      window.DAYAN_MODAL('比较模型合同',`<div class="model-compare">${chosen.map((m,i)=>`<section><h3>${esc(m.model_id+' · '+m.name)}</h3><p>${esc(m.entry_status)}</p><p>${esc(m.basis)}</p><p>共同口径需由研究规约明示 · ${esc((m.mechanisms||[]).join('、'))}</p>${m.has_factory?parametersTable(material[i].value?.contract?.params):empty('无运行合同')}</section>`).join('')}</div>`);
    };
    paintModelRows();
    if(autoSelect) await openModel(modelRows.find(m=>m.reviewed&&m.mechanisms.length)?.model_id || modelRows[0]?.model_id);
  }

  let prepared=null, labBusy=false;
  function labTab(tab) {
    for(const [id] of stages) {
      $("[data-lab-view="+id+"]").hidden=id!==tab;
      $("[data-lab-tab="+id+"]").setAttribute('aria-selected',String(id===tab));
    }
    preference('dayan_lab_tab_vnext',tab,true);
  }
  const readJson = (id,label) => {try{return JSON.parse($(id).value);}catch{throw new Error(label+'需要合法 JSON');}};
  function experimentFields(spec) {
    $('#labModel').value=spec.model_id;
    $('#labTicks').value=spec.ticks;$('#labDt').value=spec.dt;
    $('#labSeeds').value=spec.seeds.join(',');$('#labMetric').value=spec.primary_metric;
    $('#labBaseline').value=json(spec.baseline_params);$('#labArms').value=json(spec.arms);
    $('#labBindings').value=json(spec.data_bindings||[]);
    $('#labWindow').value=json(spec.analysis_window||[]);
    $('#labWarmup').value=spec.warmup_ticks;
  }
  async function compile(mid) {
    const original=$('#labQuestion').value.trim();
    if(!original)throw new Error('请填写原始研究问题。');
    const button=$('#labCompile');
    button.disabled=true;$('#labExecute').disabled=true;
    write('#labStatus','正在匹配机制、时间和数据约束…');
    try {
      const result=await api('/api/research/compile',{text:original,model_id:mid||null,metric:$('#labRequestedMetric').value.trim()||null,parameters:readJson('#labInputs','模型输入')});
      const spec=result.research_spec, exp=result.experiment_spec;
      if(original!==$('#labQuestion').value.trim()||result.research_spec.original_request!==original) return;
      prepared=exp?result:null;
      $('#labMatch').innerHTML=`<div class="lab-facts"><span>研究 ${esc(spec.research_id)}</span><span>用途 ${esc(spec.purpose)}</span><span>证据 ${esc(spec.evidence_requirement)}</span></div>
        <p class="space-note">必需机制 ${esc(spec.mechanisms_required.join('、')||'待明确')}</p>
        ${result.warnings.length?`<ul class="form-issues">${result.warnings.map(esc).map(value=>'<li>'+value+'</li>').join('')}</ul>`:''}
        <div class="candidate-rows">${result.candidates.slice(0,9).map(m=>`<div class="system-row"><div><b>${esc(m.model_id)} · ${esc(m.description||m.reason)}</b><small>${esc((m.missing_mechanisms||[]).length?'缺少 '+m.missing_mechanisms.join('、'):(m.mechanism||[]).join('、'))}</small></div><button class="ws-button" data-lab-model="${esc(m.model_id)}" ${m.missing_mechanisms?.length?'disabled':''}>核对候选</button></div>`).join('')}</div>
        <details class="tool-detail"><summary>查看完整研究规约</summary><pre>${esc(json(spec))}</pre></details>`;
      for(const b of $('#labMatch').querySelectorAll('[data-lab-model]'))b.onclick=()=>compile(b.dataset.labModel).catch(e=>showError('#labStatus',e));
      if(exp) {
        experimentFields(exp);
        $('#labExecute').disabled=false;
        $('#labNext').disabled=false;
        write('#labSpecId',exp.experiment_id);
      }
      write('#labStatus',exp?'规约已编译，核对参数与干预后可执行。':'仍有需要补充的约束。');
    } finally {button.disabled=false;}
  }
  function lab() {
    const el=$('#labWorkspace');
    if(el.dataset.ready)return Promise.resolve();
    el.dataset.ready='true';
    el.innerHTML=`<div class="lab-tabs" role="tablist" aria-label="研究步骤">${stages.map(([id,label])=>`<button data-lab-tab="${id}" role="tab" aria-selected="false">${label}</button>`).join('')}</div>
      <section data-lab-view="contract" class="lab-layout">
        ${panel('从研究问题出发',`<form id="labCompileForm" class="tool-form"><label>原始研究问题<textarea id="labQuestion" rows="6" required placeholder="描述模型、主体、地区、时间、对照组与主要观测指标"></textarea></label>
          <label>主要观测字段<input id="labRequestedMetric" placeholder="沿用问题或模型合同"></label>
          <details class="tool-detail"><summary>明确模型输入或数据集 ID</summary><label>参数对象<textarea rows="3" id="labInputs">{}</textarea></label></details>
          <div class="space-actions"><button class="ws-button ws-primary" id="labCompile">匹配并编译规约</button><button type="button" class="ws-button" id="labAssistant">与 AI 讨论</button></div><p class="space-status" id="labStatus" role="status"></p></form>`)}
        ${panel('匹配与约束',`<div id="labMatch">${empty('编译后查看模型候选、待补的数据和完整研究规约。')}</div><button class="ws-button" id="labNext" disabled>编辑实验规约 ↗</button>`)}
      </section>
      <section data-lab-view="experiment" class="lab-layout" hidden>
        ${panel('基线、干预与重复运行',`<form id="labExperimentForm" class="tool-form"><div class="tool-columns"><label>模型 ID<input id="labModel" readonly></label><label>主要结局指标<input id="labMetric" required></label><label>步数<input type="number" min="0" max="10000" id="labTicks" required></label><label>步长<input type="number" min="0" step="any" id="labDt" required></label></div>
          <label>配对随机种子（逗号分隔）<input id="labSeeds" required></label><label>基线参数<textarea rows="4" id="labBaseline">{}</textarea></label><label>干预臂（每臂 label、params、interventions）<textarea rows="5" id="labArms">[]</textarea></label>
          <details class="tool-detail"><summary>数据映射与分析范围</summary><label>数据映射<textarea id="labBindings" rows="4">[]</textarea></label><label>分析窗口<textarea id="labWindow" rows="1">[]</textarea></label><label>预热步数<input id="labWarmup" type="number" min="0" value="0"></label></details>
          <button class="ws-button ws-primary" id="labExecute" disabled>执行并归档配对实验 ↗</button><p class="space-status" id="labExecutionStatus" role="status"></p></form>`)}
        ${panel('研究证据与工具',`<p class="space-note">实验规约 <code id="labSpecId">待编译</code></p><button class="ws-button" id="labOpenParameters">查看单次模型参数</button>
          <details class="tool-detail"><summary>参数扫描与敏感性</summary><form class="tool-form" id="labSweepForm"><label>比较参数<input id="labSweepParam" required></label><label>扫描值（逗号分隔）<input id="labSweepValues" required></label><button class="ws-button" id="labSweep">执行参数扫描</button><p class="space-status" id="labSweepStatus" role="status"></p></form></details>
          <p class="space-note">重复运行的种子、实际参数、干预时点与观测窗口会进入实验归档。</p><button class="ws-button" data-go="analytics">查看实验分析 ↗</button>`)}
      </section>
      <section data-lab-view="calibration" id="labCalibration" hidden></section>`;
    for(const [id] of stages)$('[data-lab-tab='+id+']').onclick=()=>labTab(id);
    const last=preference('dayan_lab_tab_vnext',undefined,true);
    labTab(stages.some(([id])=>id===last)?last:'contract');
    $('#labQuestion').value=preference('dayan_lab_question_vnext',undefined,true)||'';
    $('#labQuestion').oninput=()=>{
      preference('dayan_lab_question_vnext',$('#labQuestion').value,true); prepared=null;$('#labExecute').disabled=$('#labNext').disabled=true;
    };
    for(const id of ['#labRequestedMetric','#labInputs'])$(id).oninput=()=>{prepared=null;$('#labExecute').disabled=$('#labNext').disabled=true;};
    $('#labAssistant').onclick=()=>{
      const value=$('#labQuestion').value.trim();
      if(!value)return window.DAYAN_NOTICE('先写下要讨论的研究问题。');
      if(!window.DAYAN_NATIVE_BRIDGE)switchPage('overview');
      window.DAYAN_COMMAND.prefill(value);
    };
    $('#labCompileForm').onsubmit=e=>{e.preventDefault();compile().catch(error=>showError('#labStatus',error));};
    $('#labNext').onclick=()=>labTab('experiment');
    $('#labOpenParameters').onclick=()=>{
      if(prepared)window.DAYAN_COMMAND.chooseModel(prepared.experiment_spec.model_id);
      else window.DAYAN_NOTICE('先编译模型规约。');
    };
    $('#labExperimentForm').onsubmit=async e=>{
      e.preventDefault();
      if(!prepared||labBusy)return;
      const button=$('#labExecute');
      try {
        const source=prepared, spec=source.experiment_spec;
        const edited={...spec,
          baseline_params:readJson('#labBaseline','基线参数'),arms:readJson('#labArms','干预臂'),data_bindings:readJson('#labBindings','数据映射'),
          ticks:Number($('#labTicks').value),dt:Number($('#labDt').value),primary_metric:$('#labMetric').value.trim(),seeds:$('#labSeeds').value.split(/[,，]/).map(s=>s.trim()).filter(Boolean).map(Number),
          analysis_window:readJson('#labWindow','观察时间窗'),warmup_ticks:Number($('#labWarmup').value),research_spec:source.research_spec,async_job:true};
        // An edited execution receives a new experiment identity. The source research ID remains stable.
        delete edited.experiment_id; delete edited.created_at;
        labBusy=button.disabled=true;
        const ticket=await api('/api/experiments',edited);
        write('#labSpecId',ticket.job_id);
        switchPage('overview');window.DAYAN_RESULTS.setPlaying(false);
        const result=await window.DAYAN_RESULTS.pollJob(ticket.job_id,note=>write('#labExecutionStatus',note));
        await window.DAYAN_RESULTS.showResult('experiment',result,{intent:'实验室配对实验',question:spec.title});
        write('#labSpecId',result.experiment_id);write('#labExecutionStatus','已归档 '+result.experiment_id);
      } catch(error) {showError('#labExecutionStatus',error);window.DAYAN_NOTICE(error.message);}
      finally {labBusy=false;button.disabled=!prepared;}
    };
    $('#labSweepForm').onsubmit=async e=>{
      e.preventDefault();
      if(!prepared||labBusy){window.DAYAN_NOTICE('先编译模型规约，等待当前实验结束。');return;}
      const button=$('#labSweep');
      labBusy=button.disabled=true;
      const spec=prepared.experiment_spec;
      try {
        write('#labSweepStatus','执行已指定的扫描值…');
        const r=await api('/api/tools/sweep',{arguments:{model_id:spec.model_id,param:$('#labSweepParam').value.trim(),
          values:$('#labSweepValues').value.split(/[,，]/).map(v=>v.trim()).filter(Boolean).map(Number),
          ticks:Number($('#labTicks').value),dt:Number($('#labDt').value),seed:spec.seeds[0],parameters:readJson('#labBaseline','基线参数'),field:$('#labMetric').value.trim()}});
        if(!r.ok)throw new Error(r.error||'扫描未完成');
        await window.DAYAN_RESULTS.showResult('sweep',r.payload,{intent:'参数敏感性扫描',question:spec.title});
        switchPage('analytics');
        write('#labSweepStatus','已归档 '+r.payload.analysis_id);
      } catch(error){showError('#labSweepStatus',error);}
      finally{labBusy=button.disabled=false;}
    };
    window.DAYAN_RESEARCH.mount($('#labCalibration'));
    return Promise.resolve();
  }
  async function openStudy(id) {
    lab();
    switchPage('lab');
    labTab('calibration');
    $('#researchPanel').open=true;
    return window.DAYAN_RESEARCH.showStudy(id);
  }
  async function useCollection(id) {
    lab();switchPage('lab');labTab('calibration');$('#researchPanel').open=true;
    $('#studyEditor').open=true;
    $('#researchCollection').value=id;
    $('#researchQuestionInput').focus();
  }

  async function outputs() {
    const host=$('#replayList');
    if(!host.dataset.ready) {
      host.dataset.ready='true';
      host.innerHTML=`<div class="tool-bar"><label class="search-control">搜索归档<input id="outputSearch" type="search" placeholder="研究问题、模型或运行 ID"></label><label>档案类型<select id="outputKind">${options([['run','运行'],['experiment','配对实验'],['analysis','扫描与组合'],['study','研究验证']],'全部类型')}</select></label><button class="ws-button" id="refreshOutputs">刷新档案</button><button class="ws-button" id="legacyOutputs">旧观测与标记</button></div>
      <div class="output-layout">${panel('研究档案索引','<div id="outputRows"></div>')}${panel('来源与可复现性','<div id="outputDetail"></div>')}</div>`;
      $('#outputSearch').oninput=()=>paintOutputs();
      $('#outputKind').onchange=()=>paintOutputs();
      $('#refreshOutputs').onclick=()=>outputs().catch(e=>window.DAYAN_NOTICE(e.message));
      $('#legacyOutputs').onclick=async()=>{
        host.dataset.ready='';
        await window.DAYAN_RESULTS.loadReplay();
        const b=document.createElement('button');b.className='ws-button';b.textContent='返回研究档案索引';b.onclick=outputs;host.prepend(b);
      };
    }
    const [h,s]=await Promise.all([api('/api/history?metadata_only=true&limit=60'),api('/api/research/studies')]);
    outputRows=[...s.studies.map(v=>({kind:'study',run_id:v.study_id,created_at:v.created_at,model_id:v.model_id,intent:v.question,status:v.calibration?.status||v.phase})),
      ...h.entries].sort((a,b)=>(b.created_at||'').localeCompare(a.created_at||''));
    paintOutputs();
  }
  let outputRows=[],outputRevision=0;
  function paintOutputs() {
    if(!$('#outputRows'))return;
    const q=$('#outputSearch').value.toLowerCase().trim(),kind=$('#outputKind').value;
    const rows=outputRows.filter(r=>(!kind||r.kind===kind)&&`${r.run_id} ${r.intent} ${r.model_id}`.toLowerCase().includes(q));
    $('#outputRows').innerHTML=rows.length?`<div class="system-rows output-rows">${rows.map(r=>`<button class="system-row row-action" data-output="${esc(r.run_id)}"><div><b>${esc(r.intent||r.model_id||r.run_id)}</b><small>${esc(r.model_id||'研究')} · ${esc(r.run_id)}</small></div><time>${esc(date(r.created_at))}</time><span class="state-pill" data-state="${esc(r.status==='pass'?'passed':r.status)}">${esc(cjkStatus[r.status]||{run:'运行',experiment:'实验',analysis:'分析',study:'研究'}[r.kind])}</span></button>`).join('')}</div>`:empty('没有匹配档案。');
    for(const b of $('#outputRows').querySelectorAll('[data-output]'))b.onclick=()=>outputDetail(rows.find(r=>r.run_id===b.dataset.output)).catch(e=>showError('#outputDetail',e));
    if(!$('#outputDetail').innerHTML)$('#outputDetail').innerHTML=empty('选择档案查看版本、数据与下载。');
  }
  async function outputDetail(row) {
    const revision=++outputRevision;
    const host=$('#outputDetail');host.innerHTML=empty('读取并核验档案…');
    const id=slug(row.run_id), isStudy=row.kind==='study';
    if(isStudy) {
      const {study,reports}=await api('/api/research/studies/'+id);
      if(revision!==outputRevision)return;
      const status=study.calibration?.status;
      host.innerHTML=`<h3>${esc(study.question)}</h3><dl class="fact-list"><dt>研究 ID</dt><dd><code>${esc(study.study_id)}</code></dd><dt>验证状态</dt><dd>${esc(cjkStatus[status]||study.phase)}</dd>
        <dt>采集 / 训练快照</dt><dd><code>${esc(study.collection_id)} / ${esc(study.training_dataset.dataset_id)}</code></dd><dt>研究哈希</dt><dd><code>${esc(study.artifact_sha256)}</code></dd><dt>训练数据哈希</dt><dd><code>${esc(study.training_dataset.sha256)}</code></dd></dl>
        <div class="tag-row">${(study.source_pages||[]).map(p=>ref(p.url,'原始来源')).join('')}</div><div class="space-actions"><button class="ws-button" data-study="${esc(study.study_id)}">打开研究</button>${study.run_id?`<button class="ws-button" data-open-run="${esc(study.run_id)}">回放对应模型</button>`:''}</div>
        <div class="tag-row">${(reports||[]).map(r=>r.error?`<span>${esc(r.label+' · '+r.error)}</span>`:ref(r.file,r.label)+' '+ref(r.bundle_url,'复现包')).join('')}</div>`;
      return;
    }
    const r=await api('/api/runs/'+id);
    if(revision!==outputRevision)return;
    const m=r.manifest||r.runs?.[0]?.manifest;
    const source=m?.code_version||m?.source_fingerprint;
    host.innerHTML=`<h3>${esc(row.intent||row.model_id)}</h3><dl class="fact-list"><dt>归档 ID</dt><dd><code>${esc(row.run_id)}</code></dd><dt>模型</dt><dd>${esc(row.model_id)}</dd>
      <dt>源码版本</dt><dd><code>${esc(source||'在子运行清单中')}</code></dd><dt>已绑定数据</dt><dd>${esc((m?.data_bindings||[]).map(b=>b.dataset_id+' '+(b.sha256||'')).join('；')||'本档案未声明外部输入')}</dd>
      <dt>归档文件</dt><dd>${Object.entries(r.files||{}).map(([key,digest])=>`<code class="hash-line" title="${esc(digest)}">${esc(key)} · ${esc(digest.slice(0,12))}</code>`).join('')}</dd></dl>
      <div class="space-actions"><button class="ws-button" data-open-run="${esc(row.run_id)}">回放</button><button class="ws-button" id="analyzeOutput">分析</button><a class="ws-button" href="/api/runs/${id}/bundle.zip" download>下载研究包</a>${row.kind==='run'?`<a class="ws-button" href="/api/runs/${id}/observations.csv" download>观测 CSV</a>`:''}</div>`;
    $('#analyzeOutput').onclick=()=>window.DAYAN_ANALYTICS.open(row.run_id);
  }
  const modules={models:()=>models(),lab:()=>lab(),replay:()=>outputs(),analytics:()=>window.DAYAN_ANALYTICS.load()};
  window.DAYAN_TOOLS={load(name){return modules[name]?.();},openModel,openStudy,useCollection};
})();
