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
  const networkTone = {ECO:'#91bdf5',NET:'#70e0df',SYS:'#eabb80',BEH:'#b6a5ff',CPL:'#76d3ad',MET:'#b7cae0',APP:'#e3a0c6',USR:'#9bb3ff'};
  function linkMap(row) {
    const mechanisms=new Set(row.mechanisms || []);
    const names=modelRows.filter(m=>m.model_id!==row.model_id && m.has_factory).map(m=>({row:m,parts:(m.mechanisms||[]).filter(x=>mechanisms.has(x))}))
      .filter(m=>m.parts.length).sort((a,b)=>b.parts.length-a.parts.length||Number(b.row.reviewed)-Number(a.row.reviewed)||a.row.model_id.localeCompare(b.row.model_id)).slice(0,6);
    const entries=names.length?names.map(({row:m,parts})=>({id:m.model_id,text:m.name,parts,category:family(m.model_id)})):
      [...mechanisms].map(x=>({id:x,text:x,parts:['声明覆盖的机制']})).concat(
        Object.entries(row.output_contract?.fields||{}).filter(([k,f])=>k!=='sim_t'&&f.type==='number').slice(0,4).map(([k,f])=>({id:k,text:k,parts:['观测输出',f.unit||'模型原单位']})));
    if(!entries.length)return empty('此条目暂无机制关系或可核对的输出字段。');
    const nodes=entries.slice(0,7).map((node,i,list)=>{
      const angle=(i/list.length)*2*Math.PI - Math.PI/2;
      return {...node,x:Math.round(480+324*Math.cos(angle)),y:Math.round(215+151*Math.sin(angle)),color:networkTone[node.category]||'#91bdf5'};
    });
    const categories=[...new Set(nodes.map(n=>n.category).filter(Boolean))];
    return `<div class="model-network"><svg viewBox="0 0 960 430" role="group" aria-label="模型机制关系图" tabindex="0">
      <g data-network-world>
      ${nodes.map((node,i)=>`<path data-network-edge="${i}" d="M480 215 L${node.x} ${node.y}" stroke="${node.color}" stroke-width="${1.2+node.parts.length*.5}" fill="none"><title>${esc(node.parts.join('、'))}</title></path>`).join('')}
      <circle cx="480" cy="215" r="68" fill="#0b24367a" stroke="#437689" stroke-dasharray="2 6"/>
      <path d="M480 168l63 24v46l-63 24-63-24v-46z" fill="#14394b" stroke="#7adfe0" stroke-width="2"/>
      <text x="480" y="222" fill="#ecffff" text-anchor="middle" font-family="monospace" font-size="19">${esc(row.model_id)}</text>
      ${nodes.map((node,i)=>`<g data-network-node="${i}" data-description="${esc(node.text+' · '+node.parts.join('、'))}" tabindex="0" ${node.category?`role="button" data-model-open="${esc(node.id)}"`:'role="img"'} aria-label="${esc(node.id+' '+node.text+' · '+node.parts.join('、'))}"><rect x="${node.x-66}" y="${node.y-23}" width="132" height="46" rx="8" fill="#14283e" stroke="${node.color}"/><text x="${node.x}" y="${node.y+5}" fill="#e2eff9" text-anchor="middle" font-size="15" font-family="monospace">${esc(node.id.length>10?node.id.slice(0,9)+'…':node.id)}</text></g>`).join('')}
      </g></svg><div class="network-toolbar"><div class="network-legend">${categories.map(k=>`<span><i style="background:${networkTone[k]||'#91bdf5'}"></i>${esc(classNames[k]||k)}</span>`).join('')}</div><button class="ws-button" data-network-reset>复位关系图</button></div>
      <output class="network-reading">${names.length?'拖动探索，滚轮缩放，选择相关模型。线宽随共享机制数变化。':'图中连接声明的机制及观测字段。'}</output></div>`;
  }
  function activateNetwork() {
    const host=$('#modelDetail .model-network');
    if(!host)return;
    const svg=host.querySelector('svg'), world=svg.querySelector('[data-network-world]'), reading=host.querySelector('output');
    const initial=reading.textContent;
    let left=0, top=0, scale=1, drag;
    const paint=()=>world.setAttribute('transform',`translate(${left} ${top}) scale(${scale})`);
    const reset=()=>{left=top=0;scale=1;paint();};
    const point=e=>new DOMPoint(e.clientX,e.clientY).matrixTransform(svg.getScreenCTM().inverse());
    const zoom=(delta,p={x:480,y:215})=>{
      const next=Math.max(.6,Math.min(3,scale*delta));
      left=p.x-(p.x-left)*next/scale;top=p.y-(p.y-top)*next/scale;scale=next;paint();
    };
    host.querySelector('[data-network-reset]').onclick=reset;
    svg.addEventListener('wheel',e=>{e.preventDefault();zoom(Math.exp(-e.deltaY*.0015),point(e));},{passive:false});
    svg.addEventListener('pointerdown',e=>{
      if(e.button!==0||e.target.closest('[data-network-node]'))return;
      drag=point(e);svg.setPointerCapture(e.pointerId);svg.classList.add('dragging');
    });
    svg.addEventListener('pointermove',e=>{
      if(!drag)return;
      const p=point(e);left+=p.x-drag.x;top+=p.y-drag.y;drag=p;paint();
    });
    svg.onlostpointercapture=()=>{drag=null;svg.classList.remove('dragging');};
    svg.addEventListener('keydown',e=>{
      const shifts={ArrowLeft:[30,0],ArrowRight:[-30,0],ArrowUp:[0,30],ArrowDown:[0,-30]};
      if(e.key==='Home') reset();
      else if(e.key==='+'||e.key==='-') zoom(e.key==='+'?1.2:1/1.2);
      else if(shifts[e.key]) {left+=shifts[e.key][0];top+=shifts[e.key][1];paint();}
      else return;
      e.preventDefault();
    });
    for(const node of svg.querySelectorAll('[data-network-node]')){
      const edge=svg.querySelector(`[data-network-edge="${node.dataset.networkNode}"]`);
      const highlight=active=>{edge.classList.toggle('highlighted',active);reading.textContent=active?node.dataset.description:initial;};
      node.onpointerenter=node.onfocus=()=>highlight(true);
      node.onpointerleave=node.onblur=()=>highlight(false);
    }
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
    activateNetwork();
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

  let prepared=null, labBusy=false, labStage='contract', labStudy=null;
  function paintLabFlow() {
    const host=$('#labFlow');if(!host)return;
    const s=labStage==='calibration'?labStudy:null, spec=prepared?.experiment_spec, cal=s?.calibration;
    const flow=[['contract','研究问题',s?.question||($('#labQuestion').value.trim()?'问题草稿已填写':'填写研究问题'),'question'],
      ['contract','模型选择',s?.model_id||spec?.model_id||'匹配机制','model'],
      ['experiment','实验设计',s?.study_id||spec?.experiment_id||'核对参数与对照','design'],
      ['calibration','数据校准',cal?`实际执行 ${cal.n_evaluated} 组`:s?.training_dataset?.dataset_id||'选择数据与阈值','train'],
      ['calibration','独立验证',cal?(cjkStatus[cal.status]||cal.status):'检查独立留出','test'],
      ['calibration','结果解释',s?.run_id?'查看误差与研究报告':'待生成证据','explain']];
    host.innerHTML=flow.map(([,label,value,key])=>`<div data-phase="${key}" ${key==='test'&&cal?`data-state="${esc(cal.status)}"`:''}><b>${label}</b><span title="${esc(value)}">${esc(value)}</span></div>`).join('');
  }
  function labTab(tab) {
    labStage=tab;
    for(const [id] of stages) {
      $("[data-lab-view="+id+"]").hidden=id!==tab;
      $("[data-lab-tab="+id+"]").setAttribute('aria-selected',String(id===tab));
    }
    preference('dayan_lab_tab_vnext',tab,true);
    paintLabFlow();
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
      paintLabFlow();
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
    el.innerHTML=`<div id="labFlow" class="lab-flow" aria-label="研究证据流程"></div><div class="lab-tabs" role="tablist" aria-label="研究步骤">${stages.map(([id,label])=>`<button data-lab-tab="${id}" role="tab" aria-selected="false">${label}</button>`).join('')}</div>
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
    paintLabFlow();
    window.addEventListener('dayan:study',e=>{labStudy=e.detail;paintLabFlow();});
    $('#labQuestion').oninput=()=>{
      preference('dayan_lab_question_vnext',$('#labQuestion').value,true); prepared=null;$('#labExecute').disabled=$('#labNext').disabled=true;paintLabFlow();
    };
    for(const id of ['#labRequestedMetric','#labInputs'])$(id).oninput=()=>{prepared=null;$('#labExecute').disabled=$('#labNext').disabled=true;paintLabFlow();};
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

  let outputRows=[], outputOffset=0, outputQuery=0, outputTimer, outputRevision=0;
  let selectedOutput, openHistoryTab, historyPlaybackReady, reportRequest;
  let historyEdit, lastDeleted;
  const archiveTypes={run:'单次运行',experiment:'配对实验',analysis:'组合分析',study:'验证研究',legacy:'早期记录'};
  const pageSize=30;

  function initOutputs() {
    const host=$('#replayList');
    if(host.dataset.ready)return;
    host.dataset.ready='true';
    host.innerHTML='<div class="tool-bar history-filter"><label class="search-control">搜索历史<input id="outputSearch" type="search" placeholder="名称、研究问题或编号"></label>'
      +'<label>日期<input id="outputDate" type="date"></label></div><p class="space-status" id="outputStatus" role="status"></p>'
      +'<div id="outputRows" class="history-rows"></div><button class="ws-button" id="moreOutputs" hidden>加载更早记录</button>'
      +'<details class="tool-detail history-legacy"><summary>回放标记</summary><div id="legacyHistory"></div></details>';
    const refresh=()=>{
      clearTimeout(outputTimer);
      ++outputQuery;
      outputTimer=setTimeout(()=>readOutputs().catch(e=>showError('#outputStatus',e)),200);
    };
    $('#outputSearch').oninput=refresh;
    $('#outputDate').onchange=refresh;
    $('#moreOutputs').onclick=()=>readOutputs(true).catch(e=>showError('#outputStatus',e));
    $('#outputRows').onclick=e=>{
      const action=e.target.closest('[data-history-action]');
      if(action){
        const row=outputRows.find(item=>item.run_id===action.dataset.historyId);
        if(row)openHistoryManage(row,action);
        return;
      }
      const hit=e.target.closest('[data-output]');
      const row=hit&&outputRows.find(item=>item.run_id===hit.dataset.output);
      if(row) showOutput(row).catch(e=>showError('#historyLoading',e));
    };
    $('.history-legacy').ontoggle=e=>{
      if(e.target.open)window.DAYAN_RESULTS.paintBookmarks($('#legacyHistory'));
    };
    $('#historyDetailActions').onclick=e=>{
      const action=e.target.closest('[data-history-action]');
      if(action&&selectedOutput)openHistoryManage(selectedOutput.row,action);
    };
    $('#historyManageForm').onsubmit=e=>{e.preventDefault();saveHistoryChange();};
    $('#historyUseAuto').onclick=()=>saveHistoryChange(true);
    $('#historyManageCancel').onclick=()=>$('#historyManage').close();
    $('#historyManage').oncancel=e=>{if($('#historyManageApply').disabled)e.preventDefault();};
    $('#historyManage').onclose=()=>historyEdit?.trigger.focus({preventScroll:true});
    $('#historyName').oninput=()=>write('#historyManageError','');
    $('#historyBack').onclick=()=>{
      const id=selectedOutput?.row.run_id;
      leaveHistory();
      [...$('#outputRows').querySelectorAll('[data-output]')].find(b=>b.dataset.output===id)?.focus({preventScroll:true});
      window.dispatchEvent(new Event('resize'));
    };
    $('.history-tabs').onclick=e=>{
      const tab=e.target.closest('[data-history-tab]');
      if(tab)selectHistoryTab(tab.dataset.historyTab);
    };
    $('.history-tabs').onkeydown=e=>{
      if(e.key!=='ArrowLeft'&&e.key!=='ArrowRight')return;
      const tabs=[...e.currentTarget.querySelectorAll('[role=tab]')].filter(tab=>!tab.hidden);
      if(tabs.length<2)return;
      e.preventDefault();
      const next=tabs.find(tab=>tab.dataset.historyTab!==openHistoryTab);
      next.click();next.focus();
    };
  }

  function historyDate() {
    const day=$('#outputDate').value;
    if(!day)return {};
    const start=new Date(day+'T00:00:00'), end=new Date(start);
    end.setDate(start.getDate()+1);
    return {after:start.toISOString(),before:end.toISOString()};
  }

  async function readOutputs(append=false) {
    const revision=++outputQuery, dateRange=historyDate();
    const search=$('#outputSearch').value.trim();
    const query=new URLSearchParams({metadata_only:'true',workbench:'true',limit:String(pageSize),offset:String(append?outputOffset:0),search,...dateRange});
    $('#moreOutputs').disabled=true;
    if(!append)write('#outputStatus','读取历史记录…');
    try{
      const history=await api('/api/history?'+query);
      if(revision!==outputQuery)return;
      outputOffset=append?outputOffset+history.entries.length:history.entries.length;
      const base=append?outputRows:[];
      outputRows=[...new Map([...base,...history.entries].map(row=>[row.run_id,row])).values()];
      paintOutputs();
      paintHistoryStatus();
      $('#moreOutputs').hidden=history.entries.length<pageSize;
    } finally {if(revision===outputQuery)$('#moreOutputs').disabled=false;}
  }

  function historyActions(row) {
    const key=esc(row.run_id);
    return '<details class="control-menu history-actions" name="history-manage"><summary class="ws-button" aria-label="管理 '+esc(row.title)+'">⋯</summary>'
      +'<div class="control-menu-panel"><button type="button" class="ws-button" data-history-action="rename" data-history-id="'+key+'">重命名</button>'
      +'<button type="button" class="ws-button history-danger" data-history-action="delete" data-history-id="'+key+'">删除记录</button></div></details>';
  }

  function paintOutputs() {
    $('#outputRows').innerHTML=outputRows.map(row=>'<div class="history-record"><button class="archive-row" data-output="'+esc(row.run_id)+'" data-kind="'+esc(row.kind)+'">'
      +'<strong>'+esc(row.title)+'</strong><span>'+esc([archiveTypes[row.kind],row.model_id,row.status?cjkStatus[row.status]||row.status:''].filter(Boolean).join(' · '))+'</span>'
      +'<time datetime="'+esc(row.created_at||'')+'">'+esc(date(row.created_at))+'</time></button>'+historyActions(row)+'</div>').join('')||empty('没有匹配的历史记录。');
  }

  function paintHistoryHeading(row) {
    write('#historyTitle',row.title);
    write('#historyIdentity',[archiveTypes[row.kind],row.model_id,date(row.created_at),row.run_id].filter(Boolean).join(' · '));
    $('#historyDetailActions').innerHTML=historyActions(row);
  }

  function openHistoryManage(row, button) {
    const action=button.dataset.historyAction;
    const dialog=$('#historyManage');
    if(dialog.open)return;
    const menu=button.closest('details');
    historyEdit={row,action,trigger:menu.querySelector('summary')};
    menu.open=false;
    const deleting=action==='delete';
    write('#historyManageTitle',deleting?'删除历史记录':'重命名记录');
    write('#historyManageText',deleting?'将「'+row.title+'」从历史记录删除？关联归档仍可用于回放与报告。':'自动名称  '+row.automatic_title);
    write('#historyManageError','');
    $('#historyNameField').hidden=$('#historyName').disabled=deleting;
    $('#historyName').value=row.title;
    $('#historyUseAuto').hidden=deleting||!row.title_is_custom;
    const apply=$('#historyManageApply');
    apply.classList.toggle('history-delete-apply',deleting);
    write('#historyManageApply',deleting?'删除记录':'保存名称');
    dialog.showModal();
    if(deleting)$('#historyManageCancel').focus();
    else{$('#historyName').focus();$('#historyName').select();}
  }

  function paintHistoryStatus(message='') {
    const status=$('#outputStatus');
    const removed=lastDeleted;
    status.textContent=message||(removed?'已删除「'+removed.title+'」':'');
    if(!removed)return;
    const undo=document.createElement('button');
    undo.type='button';
    undo.className='ws-button history-undo';
    undo.textContent='撤销删除';
    undo.onclick=async()=>{
      undo.disabled=true;
      try {
        await api('/api/history/'+slug(removed.run_id)+'/restore',{},'POST');
      } catch(error) {
        window.DAYAN_NOTICE(error.message);
        undo.disabled=false;
        return;
      }
      if(lastDeleted===removed)lastDeleted=null;
      document.dispatchEvent(new Event('dayan:history-change'));
      await readOutputs().catch(error=>paintHistoryStatus(error.message));
      window.DAYAN_NOTICE('已恢复「'+removed.title+'」');
    };
    status.append(undo);
  }

  async function saveHistoryChange(useAutomatic=false) {
    const {row,action}=historyEdit;
    const apply=$('#historyManageApply'), cancel=$('#historyManageCancel'), reset=$('#historyUseAuto');
    if(apply.disabled)return;
    const deleting=action==='delete';
    const title=useAutomatic?null:$('#historyName').value.trim();
    if(!deleting&&title===''){write('#historyManageError','输入记录名称后再保存。');return;}
    apply.disabled=cancel.disabled=reset.disabled=true;
    let changed;
    try {
      const route='/api/history/'+slug(row.run_id);
      const response=deleting?await api(route,undefined,'DELETE'):await api(route,{title},'PATCH');
      changed=response.record;
    } catch(error) {
      write('#historyManageError',error.message);
      return;
    } finally {
      apply.disabled=cancel.disabled=reset.disabled=false;
    }
    $('#historyManage').close();
    if(deleting){
      lastDeleted=row;
      outputRows=outputRows.filter(item=>item.run_id!==row.run_id);
      if(selectedOutput?.row.run_id===row.run_id)leaveHistory();
    } else {
      for(const item of outputRows)if(item.run_id===row.run_id)Object.assign(item,changed);
      if(selectedOutput?.row.run_id===row.run_id){
        Object.assign(selectedOutput.row,changed);
        paintHistoryHeading(selectedOutput.row);
      }
      window.DAYAN_NOTICE('名称已保存');
    }
    paintOutputs();
    document.dispatchEvent(new Event('dayan:history-change'));
    await readOutputs().catch(error=>paintHistoryStatus(error.message));
    if(!selectedOutput){
      const savedButton=[...document.querySelectorAll('[data-output]')].find(item=>item.dataset.output===row.run_id);
      (savedButton||$('#outputSearch')).focus({preventScroll:true});
    }
  }

  function leaveHistory() {
    if(!selectedOutput)return;
    ++outputRevision;
    selectedOutput=null;
    historyPlaybackReady=false;
    reportRequest=null;
    const surface=$('#simulationSurface');
    $('#pageOverview').append(surface);
    surface.hidden=false;
    $('#historyDetail').hidden=true;
    $('#historyHeading').hidden=$('#replayList').hidden=false;
    window.DAYAN_RESULTS.endHistory();
  }

  function selectHistoryTab(name) {
    openHistoryTab=name;
    for(const tab of document.querySelectorAll('[data-history-tab]')){
      const active=tab.dataset.historyTab===name;
      tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;
    }
    $('#historyPlayback').hidden=name!=='playback';
    $('#historyReport').hidden=name!=='report';
    if(name==='report'){
      window.DAYAN_RESULTS.setPlaying(false);
      const revision=outputRevision;
      if(!reportRequest)reportRequest=readHistoryReport(selectedOutput).catch(error=>{
        if(revision!==outputRevision)return;
        const host=$('#outputDetail');
        host.replaceChildren(Object.assign(document.createElement('p'),{textContent:error.message}));
        const retry=Object.assign(document.createElement('button'),{className:'ws-button',textContent:'重试读取报告'});
        retry.onclick=()=>{reportRequest=null;selectHistoryTab('report');};host.append(retry);
      });
    } else {
      requestAnimationFrame(()=>{
        window.dispatchEvent(new Event('resize'));
        if(historyPlaybackReady)window.DAYAN_RESULTS.paint();
      });
    }
    window.dispatchEvent(new Event('dayan:display'));
  }

  async function showOutput(row) {
    const revision=++outputRevision;
    selectedOutput={row};
    historyPlaybackReady=false;reportRequest=null;
    window.DAYAN_RESULTS.beginHistory();
    $('#historyHeading').hidden=$('#replayList').hidden=true;
    $('#historyDetail').hidden=false;
    $('#historyPlaybackTab').hidden=false;
    $('#historyReportTab').hidden=row.kind==='legacy';
    $('#historyReportTab').disabled=true;
    paintHistoryHeading(row);
    write('#historyLoading','正在校验归档…');
    const surface=$('#simulationSurface');
    surface.hidden=true;
    $('#historyPlayback').append(surface);
    selectHistoryTab('playback');
    window.scrollTo(0,0);
    $('#historyBack').focus({preventScroll:true});
    try{
      let legacy;
      if(row.kind==='study'){
        selectedOutput.study=await api('/api/research/studies/'+slug(row.run_id));
        if(revision!==outputRevision)return;
        selectedOutput.runId=selectedOutput.study.study.run_id;
      } else if(row.kind==='legacy'){
        legacy=await api('/api/history/'+slug(row.run_id)+'/legacy');
      } else {
        selectedOutput.runId=row.run_id;
        if(row.kind==='run'){
          const relation=await api('/api/research/for_run/'+slug(row.run_id));
          if(revision!==outputRevision)return;
          if(relation.study)selectedOutput.study=await api('/api/research/studies/'+slug(relation.study.study_id));
        }
      }
      if(revision!==outputRevision)return;
      $('#historyReportTab').disabled=false;
      if(!legacy&&!selectedOutput.runId){
        $('#historyPlaybackTab').hidden=true;
        selectHistoryTab('report');
        return;
      }
      surface.hidden=false;
      $('#sceneEmptyState').hidden=false;
      const context={history:true,userRequested:true};
      const restored=legacy?await window.DAYAN_RESULTS.showResult('run',{...legacy,
        legacy_time_is_index:(legacy.observations||[]).some(point=>!Number.isFinite(point.sim_t))},
        {...context,replaying:true,question:row.title,intent:'旧记录观测回放'}):
        await window.DAYAN_RESULTS.restore(selectedOutput.runId,context);
      if(revision!==outputRevision)return;
      if(!restored)throw new Error('未能还原该记录的运行状态。');
      historyPlaybackReady=true;
      write('#historyLoading',legacy?'旧格式记录仅供观测回放。':'');
      window.dispatchEvent(new Event('dayan:display'));
    } catch(error){
      if(revision!==outputRevision)return;
      surface.hidden=true;
      write('#historyLoading','读取失败 · '+error.message);
    }
  }

  function reportDownloads(markup, exportReport) {
    const host=$('#outputDetail');
    host.innerHTML=markup;
    const button=$('#downloadHistoryReport');
    if (!button) return;
    button.onclick=async()=>{
      button.disabled=true;
      write('#reportJobStatus','正在生成该归档的 Word 报告…');
      try{
        const url=await exportReport();
        if(!button.isConnected)return;
        $('#reportJobStatus').innerHTML=ref(url,'下载已生成的 Word 报告');
        const link=$('#reportJobStatus a');
        if(link){button.hidden=true;link.download='';link.click();}
      }catch(error){if(button.isConnected)write('#reportJobStatus','报告未生成 · '+error.message);}
      finally{button.disabled=false;}
    };
  }

  function reportFigureGallery(figures) {
    const groups=new Map();
    for(const figure of figures||[]){
      if(!/^\/reports\/research_[a-z0-9_]+\.png$/.test(figure.url))continue;
      if(!groups.has(figure.section))groups.set(figure.section,[]);
      groups.get(figure.section).push(figure);
    }
    return [...groups].map(([section,items])=>
      '<section class="report-figure-section"><h4>'+esc(section)+'</h4><div class="report-figure-grid">'
      +items.map(figure=>{
        const height=Math.round(740/figure.aspect);
        const size=Number.isFinite(height)&&height>0?' width="740" height="'+height+'"':'';
        return '<figure><a href="'+esc(figure.url)+'" target="_blank" rel="noopener" aria-label="放大查看'+esc(figure.title)+'">'
          +'<img src="'+esc(figure.url)+'" alt="'+esc(figure.title)+'"'+size+' loading="lazy" decoding="async"></a>'
          +'<figcaption><strong>图 '+esc(figure.number)+'　'+esc(figure.title)+'</strong><p>'+esc(figure.caption)
          +'</p></figcaption></figure>';
      }).join('')+'</div></section>').join('');
  }

  async function readHistoryReport(entry) {
    const revision=outputRevision;
    const host=$('#outputDetail');
    host.innerHTML=empty('正在核对与该记录对应的报告…');
    const downloadButton='<button class="ws-button ws-primary" id="downloadHistoryReport">生成 Word 报告</button><span id="reportJobStatus" role="status"></span>';
    if(entry.study){
      const {study,reports}=entry.study, cal=study.calibration, status=cal?.status||study.phase;
      const saved=(reports||[]).filter(report=>report.file);
      const heading='<header class="report-heading"><h3>研究分析报告</h3><span class="state-pill" data-state="'+esc(status==='pass'?'passed':status)+'">'+esc(cjkStatus[status]||status)+'</span></header>';
      const summary=cal?'<dl class="report-facts"><div><dt>独立测试 RMSE</dt><dd>'+esc(cal.holdout?.rmse?.toPrecision(6)??'—')+'</dd></div>'
        +'<div><dt>事前阈值</dt><dd>'+esc(study.tolerance)+' '+esc(study.unit)+'</dd></div><div><dt>独立观测</dt><dd>'+esc(study.holdout?.length||0)+'</dd></div></dl>'
        +'<p>'+esc(cal.interpretation?.interpretation_text||cal.interpretation_text||'')+'</p><div id="outputPreview" class="chart-host"></div>':'<p>研究合同已归档，等待校准和独立验证。</p>';
      const links=saved.map(report=>'<a class="ws-button" href="'+esc(report.file)+'" download>'+esc(report.label)+'</a>').join('');
      reportDownloads(heading+summary+'<details class="tool-detail"><summary>数据、模型与验证依据</summary>'
        +'<dl class="fact-list"><dt>研究问题</dt><dd>'+esc(study.question)+'</dd><dt>地区和时期</dt><dd>'+esc(study.contract.country+' · '+study.contract.date)+'</dd>'
        +'<dt>研究与运行</dt><dd><code>'+esc(study.study_id+' / '+(study.run_id||'待运行'))+'</code></dd>'
        +'<dt>数据版本</dt><dd><button data-open-dataset="'+esc(study.training_dataset.dataset_id)+'">'+esc(study.training_dataset.dataset_id)+'</button></dd>'
        +'<dt>模型</dt><dd><button data-graph-model="'+esc(study.model_id)+'">'+esc(study.model_id)+'</button></dd></dl>'
        +'<div class="tag-row">'+(study.source_pages||[]).map(page=>ref(page.url,'原始来源')).join('')+'</div><p>'
        +esc(Array.isArray(study.limitations)?study.limitations.join('；'):study.limitations||'')+'</p></details>'
        +'<div class="space-actions report-downloads">'+links+(entry.runId&&!saved.some(report=>report.kind==='academic')?downloadButton:'')
        +(saved[0]?'<a href="'+esc(saved[0].bundle_url)+'" download>下载复现包</a>':'')+'</div>',
        async()=>{const report=await api('/api/tools/research_report',{arguments:{study_id:study.study_id,kind:'academic'}});return report.payload.file;});
      if(cal && study.predictions?.length)window.DAYAN_CHARTS.plot($('#outputPreview'),{title:'实际观测与模型预测',xUnit:'年度',yUnit:study.unit,
        events:study.holdout?.length?[{x:study.holdout[0].date,label:'独立测试开始'}]:[],
        series:[{label:'实际观测',points:study.records.map(r=>[r.date,r.value])},{label:'模型预测',dashed:true,points:study.predictions.map(r=>[r.date,r.predicted])}]});
      return;
    }
    const {row}=entry, archive=await api('/api/runs/'+slug(row.run_id));
    if(revision!==outputRevision)return;
    const run=row.kind==='run'?archive:archive.runs?.find(item=>item.arm==='基线')||archive.runs?.[0];
    if(!run)throw new Error('这条归档没有可核验的具体运行。');
    const request={model_id:run.model_id||row.model_id, ...(row.kind==='experiment'?{experiment_id:row.run_id}:{}), ...(row.kind==='analysis'?{analysis_id:row.run_id}:{})};
    const reportRoute='/api/runs/'+slug(run.run_id)+'/report?';
    const {facts}=await api(reportRoute+new URLSearchParams(request));
    if(revision!==outputRevision)return;
    if(facts.run_id!==run.run_id)throw new Error('报告与当前归档的运行标识不一致。');
    const view=facts.view_analysis, content=facts.content, metric=view.metric_info, period=view.window;
    const format=window.DAYAN_ANALYSIS.fmt;
    const entries=[['观察指标',metric.name||view.metric],['观测点',facts.n_observations],['分析窗口',format(period.from)+' 至 '+format(period.to)]];
    const numbers=entries.map(([label,value])=>'<div><dt>'+esc(label)+'</dt><dd>'+esc(value)+'</dd></div>').join('');
    const comparison=view.comparisons?.length?'<table class="workbench-table report-comparison"><thead><tr><th>方案</th><th>基线</th><th>均值差</th><th>配对种子</th></tr></thead><tbody>'
      +view.comparisons.map(group=>'<tr><td>'+esc(group.group)+'</td><td>'+esc(group.baseline)+'</td><td>'+format(group.difference)+'</td><td>'
        +(group.paired_n?group.paired_n+' 个配对种子':'—')+'</td></tr>').join('')+'</tbody></table>':'';
    const files='<a class="ws-button" href="/api/runs/'+slug(row.run_id)+'/bundle.zip" download>下载复现包</a>';
    const coverage=facts.manifest.scenario_review?.coverage;
    const scope=coverage?.status==='partial'?
      '<p><strong>原需求部分覆盖</strong> · '+esc(coverage.gaps.join('；'))+'</p>':'';
    const question=archive.request_text?.trim()||content.background;
    const questionFact=question&&question!==row.title?'<dt>原始需求</dt><dd>'+esc(question)+'</dd>':'';
    reportDownloads('<header class="report-heading"><h3>'+esc(content.title)+'</h3>'+downloadButton+'</header><dl class="report-facts">'+numbers+'</dl>'
      +scope+'<p>'+esc(content.abstract)+'</p>'+comparison
      +'<div id="reportFigures" aria-busy="true"><p class="report-figure-status" role="status">正在生成归档图表…</p></div>'
      +'<section class="report-findings"><h4>过程与结果</h4><p>'+esc(content.analysis)+'</p></section>'
      +'<h4>结论与适用范围</h4><p>'+esc(content.conclusion)+'</p><p>'+esc(content.limitations)+'</p>'
      +'<details class="tool-detail"><summary>数据与模型依据</summary><dl class="fact-list"><dt>归档 / 运行</dt><dd><code>'+esc(row.run_id+' / '+run.run_id)+'</code></dd>'
      +questionFact
      +'<dt>模型版本</dt><dd><code>'+esc(facts.manifest.code_version||facts.manifest.source_fingerprint||'未记录')+'</code></dd>'
      +'<dt>输入数据</dt><dd>'+((facts.manifest.data_bindings||[]).map(binding=>'<button data-open-dataset="'+esc(binding.dataset_id)+'">'+esc(binding.dataset_id)+'</button>').join(' ')||'该运行未绑定外部数据')+'</dd></dl></details>'
      +'<div class="report-downloads space-actions">'+files+'<button class="ws-button" id="analyzeOutput">展开图表分析</button></div>',
      async()=>{const response=await api('/api/report',{...request,run_id:run.run_id,primary_metric:view.metric});return response.url;});
    $('#analyzeOutput').onclick=()=>window.DAYAN_ANALYTICS.open(row.run_id);
    const gallery=$('#reportFigures');
    try {
      const preview=await api(reportRoute+new URLSearchParams({...request,primary_metric:view.metric,figure_preview:'true'}));
      if(revision!==outputRevision)return;
      if(preview.facts.run_id!==run.run_id)throw new Error('图表与当前归档的运行标识不一致。');
      gallery.innerHTML=reportFigureGallery(preview.facts.view_analysis.figures);
      gallery.hidden=!gallery.firstElementChild;
    } catch(error) {
      if(revision!==outputRevision)return;
      gallery.firstElementChild.textContent='图表预览暂不可用 · '+error.message;
    } finally {
      gallery.removeAttribute('aria-busy');
    }
  }

  function outputs() {
    initOutputs();
    if (selectedOutput) return Promise.resolve();
    return readOutputs();
  }
  const modules={models:()=>models(),lab:()=>lab(),replay:()=>outputs(),analytics:()=>window.DAYAN_ANALYTICS.load()};
  window.DAYAN_TOOLS={load(name){return modules[name]?.();},openModel,openStudy,useCollection,leaveHistory};
})();
