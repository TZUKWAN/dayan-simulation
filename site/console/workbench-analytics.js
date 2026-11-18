/* Linked analysis of verified saved records. Model/time scopes are explicit. */
(() => {
  'use strict';
  const $ = selector=>document.querySelector(selector);
  const {api,esc,empty,write} = window.DAYAN_WORKBENCH;
  const {plot,colors,distribution,correlationMatrix,csv,download,nfmt,quantile,mean,range} = window.DAYAN_CHARTS;
  const finite=Number.isFinite;
  const source = new Map();
  let initialized=false, userSelection=false, loading=null, mainChart=null, activeRows=[], activeMetric='', activeUnit='', cursor=null;
  let pair=null;
  function observationRuns(record) {
    if(record.kind==='run')return [{...record,label:record.model_id}];
    if(record.kind==='experiment'){
      const offset={};
      return (record.runs||[]).map(run=>{
        const i=offset[run.arm]||0;offset[run.arm]=i+1;
        return {...run,model_id:record.model_id,label:run.arm+' · seed='+String(run.seed),observations:record.observations?.[run.arm]?.[i]||[]};
      });
    }
    const p=record.analysis;
    return (p?.runs||p?.stages||[]).map((r,i)=>({...r,label:p.param?`${p.param}=${r.value}`:r.seed!==undefined?`seed=${r.seed}`:r.model_id||'阶段 '+(i+1)}));
  }
  async function addArchive(id,automatic=false) {
    if(!id||source.has(id))return;
    if(source.size>=8)throw new Error('单个比较视图最多显示八份归档。');
    write('#analyticsStatus','正在核验归档 '+id+' …');
    const rec=await api('/api/runs/'+encodeURIComponent(id));
    const runs=observationRuns(rec).filter(r=>r.run_id&&r.observations?.length);
    if(!runs.length)throw new Error('此记录缺少带标识的实际观测。');
    if(automatic&&userSelection)return;
    source.set(id,{record:rec,runs});
    write('#analyticsStatus','');
  }
  function headings() {
    const section=(id,name,note)=>`<section class="panel analytic-panel" data-plot-panel="${id}"><div class="panel-head"><h2>${name}</h2><span class="micro">${note}</span></div><div class="chart-host" id="${id}"></div></section>`;
    $('#analyticsWorkspace').innerHTML=`<div class="tool-bar analytics-controls">
      <label class="search-control">归档<select id="analyticsPick"><option value="">正在读取...</option></select></label>
      <button class="ws-button" id="analyticsAdd">加入</button><button class="ws-button" id="analyticsCurrent">使用当前实验</button>
      <label>模型 / 时间尺度<select id="analyticsCohort"></select></label><label>指标<select id="analyticsMetric"></select></label>
      <label>起点<input type="number" step="any" id="analyticsFrom"></label><label>终点<input type="number" step="any" id="analyticsTo"></label>
      <button class="ws-button" id="analyticsExport">导出筛选 CSV</button><button class="ws-button" id="analyticsSvg">导出主图 SVG</button>
      </div><div class="analytics-sources" id="analyticsSources"></div><p class="space-status" id="analyticsStatus" role="status"></p>
      <div class="analytics-stats" id="analyticsFacts"></div>
      <div class="analytics-layout">
        <section class="panel analytic-panel analytic-main"><div class="panel-head"><h2>时间序列与不确定性</h2><span id="analyticsRange"></span></div>
        <div class="chart-host" id="analyticsTrend"></div>
        <div class="analytics-cursor"><label>联动时点 <output id="cursorAt"></output><input id="analyticsCursor" aria-label="实验联动观察时点" type="range" step="any"></label><button id="analyticsJump" class="ws-button">在仿真中查看 ↗</button></div>
        <div id="analyticsAt" class="analytic-inline" aria-label="当前时刻各组观测"></div></section>
        ${section('analyticsDistribution','时间窗内分布','观测频数')}
        ${section('analyticsDensity','核密度','高斯核')}
        ${section('analyticsBox','方案分布比较','中位数 / 四分位')}
        ${section('analyticsMatrix','观测联动矩阵','选择一对指标')}
        ${section('analyticsScatter','指标联合分布','同一时刻配对')}
        ${section('analyticsEffect','同种子效应','干预组减基线')}
        ${section('analyticsSensitivity','参数扫描','窗口内均值')}
        ${section('analyticsMulti','多变量轮廓','各轴用实际单位')}
      </div>
      <section class="panel tool-detail"><div class="panel-head"><h2>运行与证据索引</h2></div><div class="tool-body table-scroll" id="analyticsProvenance"></div></section>`;
  }
  const available = rows=>[...new Set(rows.flatMap(r=>r.observations.flatMap(o=>Object.entries(o).filter(([k,v])=>k!=='sim_t'&&finite(v)).map(([k])=>k))))].sort();
  function metricUnit(run, key) {
    return run.manifest?.output_contract?.fields?.[key]?.unit || window.DAYAN_ANALYSIS.metricInfo(run.model_id,key)?.unit || '模型原单位';
  }
  function period(run) {
    return run.manifest?.model_definition?.time_unit || run.manifest?.actual?.time_unit || '模型时间';
  }
  const cohort = r=>r.model_id+' · '+period(r);
  function allRows() {
    return [...source.values()].flatMap(({record,runs})=>runs.map(run=>({...run,origin_id:record.run_id,declared_window:record.experiment_spec?.analysis_window,scan_param:record.analysis?.param})));
  }
  function selectedRows() {
    const key=$('#analyticsCohort').value;
    return allRows().filter(r=>cohort(r)===key);
  }
  function setOptions(select, values, fallback) {
    const previous=select.value;
    select.replaceChildren(...values.map(v=>new Option(v,v)));
    if(values.includes(previous))select.value=previous;
    else if(values.includes(fallback))select.value=fallback;
  }
  function initializeFilters() {
    const selected=$('#analyticsCohort');
    setOptions(selected,[...new Set(allRows().map(cohort))]);
    selectDetails();
  }
  function selectDetails(reset=false) {
    const rows=selectedRows();
    const fields=available(rows);
    const first=rows[0], preferred=window.DAYAN_RESULTS?.metric || first?.manifest?.output_contract?.primary_metric;
    if(reset) $('#analyticsMetric').value='';
    setOptions($('#analyticsMetric'),fields,preferred);
    const time=rows.flatMap(r=>r.observations.map(o=>o.sim_t).filter(finite));
    if(time.length) {
      const bounds=range(time), declared=first.declared_window;
      const [from,to]=Array.isArray(declared)&&declared.length===2&&rows.every(r=>r.origin_id===first.origin_id)?declared:bounds;
      $('#analyticsFrom').value=String(from);$('#analyticsTo').value=String(to);
      cursor=to;
    } else {
      $('#analyticsFrom').value=$('#analyticsTo').value='';
      cursor=null;
    }
    pair=null;
    paint();
  }
  function armTraces(rows,metric) {
    const groups=new Map();
    for(const row of rows) {
      const key=row.origin_id + ' / '+(row.arm??(row.scan_param?'scan '+String(row.value):row.label));
      if(!groups.has(key))groups.set(key,[]);
      groups.get(key).push(row);
    }
    const traces=[];
    for(const group of groups.values()) {
      const id=group[0].origin_id, label=group[0].arm||group[0].label;
      const gather=new Map();
      for(const r of group)for(const o of r.window)if(finite(o[metric])) {
        const items=gather.get(o.sim_t)||[];items.push(o[metric]);gather.set(o.sim_t,items);
      }
      const full=group.length>1&&new Set(group.map(r=>r.seed)).size===group.length;
      const times=[...new Set(group.flatMap(r=>r.window.map(o=>o.sim_t)))].sort((a,b)=>a-b);
      const history=times.map(t=>[t,gather.get(t)||[]]);
      traces.push({label:`${label} · ${id.slice(-7)}${full?' · '+group.length+' 种子':''}`,points:history.map(([t,values])=>[t,mean(values),values.length?'n='+values.length:'缺失']),
        band:full?history.filter(([,values])=>values.length===group.length).map(([t,values])=>[t,...range(values)]):null});
    }
    return traces;
  }
  function updateCursor(value, moveChart=false) {
    if(!finite(value))return;
    cursor=value;
    $('#analyticsCursor').value=String(value);
    write('#cursorAt',nfmt(value));
    if(moveChart)mainChart?.seek(value,false);
    const observed=activeRows.map(r=>{
      const o=r.window.find(o=>Math.abs(o.sim_t-value)<1e-8);
      return `<span><b>${esc(r.label)}</b> ${esc(nfmt(o?.[activeMetric]))} ${esc(activeUnit)}</span>`;
    });
    $('#analyticsAt').innerHTML=observed.slice(0,16).join('');
  }
  function panelsEmpty() {
    for (const id of ['Trend','Distribution','Density','Box','Matrix','Scatter','Effect','Sensitivity','Multi'])
      $('#analytics'+id).innerHTML=empty('选择包含实际观测的归档。');
    $('#analyticsFacts').replaceChildren();
    $('#analyticsAt').replaceChildren();
    $('#analyticsProvenance').innerHTML=empty('归档校验后会显示独立运行、种子与源码版本。');
  }
  function paint() {
    const metric=$('#analyticsMetric').value, rows=selectedRows(), start=Number($('#analyticsFrom').value), end=Number($('#analyticsTo').value);
    $('#analyticsSources').innerHTML=[...source.values()].map(({record})=>`<button data-remove-archive="${esc(record.run_id)}" title="移出当前分析">${esc(record.model_id||'研究')} · ${esc(record.run_id)} <span aria-hidden="true">×</span></button>`).join('');
    for(const b of $('#analyticsSources').querySelectorAll('button'))b.onclick=()=>{userSelection=true;source.delete(b.dataset.removeArchive);initializeFilters();};
    const controls=$('#analyticsWorkspace').querySelectorAll('#analyticsExport,#analyticsJump,#analyticsSvg,#analyticsCursor');
    for(const c of controls)c.disabled=true;
    write('#analyticsRange','');
    if (!metric||!rows.length) {activeRows=[];panelsEmpty();return;}
    if (!finite(start)||!finite(end)||start>end||!$('#analyticsFrom').value||!$('#analyticsTo').value) {write('#analyticsStatus','请输入有效观察范围。');panelsEmpty();return;}
    const unit=metricUnit(rows[0],metric), timeUnit=period(rows[0]), label=window.DAYAN_ANALYSIS.label(metric);
    const included=rows.filter(r=>metricUnit(r,metric)===unit);
    const windowed=included.map(r=>({...r,window:r.observations.filter(o=>finite(o.sim_t)&&o.sim_t>=start&&o.sim_t<=end)}));
    const samples=windowed.flatMap(r=>r.window.map(o=>o[metric])).filter(finite),missing=windowed.reduce((n,r)=>n+r.window.filter(o=>!finite(o[metric])).length,0);
    activeRows=windowed;activeMetric=metric;activeUnit=unit;
    if(!samples.length){write('#analyticsStatus','所选时间窗没有有限观测。');panelsEmpty();return;}
    $('#analyticsFacts').innerHTML=[
      ['对照运行',included.length,rows[0].model_id],['有效观测',samples.length,'全部已选运行'],['缺失观测',missing,'保留空值'],['窗口极值',range(samples).map(nfmt).join(' — '),unit]
    ].map(([key,value,note])=>`<div><span>${esc(key)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></div>`).join('');
    write('#analyticsStatus',included.length<rows.length?'不同口径分组展示。部分运行的单位与当前指标不一致。':'');
    write('#analyticsRange',`${label} · ${nfmt(start)}–${nfmt(end)} ${timeUnit}`);
    const events=windowed.flatMap(r=>(r.manifest?.interventions||[]).filter(e=>e.applied).map(e=>({x:e.actual_t,label:e.label||'干预'})));
    const bands=armTraces(windowed,metric);
    mainChart=plot($('#analyticsTrend'),{title:label+'同模型对照',xUnit:timeUnit,yUnit:unit,series:bands,events,
      note:'同臂多种子显示均值曲线与同一时点种子最小–最大带。琥珀虚线为模型归档中的干预。',
      cursor:Math.min(end,Math.max(start,cursor??end)),onHover:t=>updateCursor(t)});
    const first=windowed.find(r=>r.window.some(o=>finite(o[metric])));
    const d=distribution(first.window.map(o=>o[metric]));
    plot($('#analyticsDistribution'),{title:label+'频数分布',xUnit:unit,yUnit:'观测数',zero:true,series:[{label:first.label,points:d.counts,kind:'bars',barHalfWidth:d.width*.44}]});
    plot($('#analyticsDensity'),{title:label+'核密度',xUnit:unit,yUnit:`密度 / ${unit}`,zero:true,empty:'观测恒定，无法估计正带宽。',series:[{label:first.label,points:d.density,kind:'area',color:colors[1]}],
      note:'描述性分布 · 带宽 '+nfmt(d.bandwidth)+' '+unit});
    const boxGroups=windowed.slice(0,12).map((r,i)=>{
      const a=r.window.map(o=>o[metric]).filter(finite).sort((x,y)=>x-y);
      return a.length?[i+1,quantile(a,.5),r.label,a[0],quantile(a,.25),quantile(a,.75),a.at(-1)]:null;
    }).filter(Boolean);
    const bounds=range(boxGroups.flatMap(p=>[p[3],p[6]]));
    plot($('#analyticsBox'),{title:'观测分布对照',xUnit:'运行序号',yUnit:unit,xRange:[0,boxGroups.length+1],yRange:bounds,
      xTicks:boxGroups.map(p=>[p[0],p[0]]),series:[{kind:'box',label:'每运行最小–最大 / IQR',points:boxGroups}],note:'横轴按当前运行列表排序。'});
    const keys=available([first]).filter(k=>first.window.some(o=>finite(o[k]))).slice(0,8);
    correlationMatrix($('#analyticsMatrix'),Object.fromEntries(keys.map(key=>[key,first.window.map(o=>o[key])])),(a,b)=>{pair=[a,b];drawScatter(first,pair);});
    drawScatter(first,pair?.every(k=>keys.includes(k))?pair:[metric,keys.find(k=>k!==metric)]);
    drawEffects(windowed,metric,unit);
    drawSensitivity(windowed,metric,unit);
    drawProfiles(windowed,keys,first);
    paintProvenance();
    const slider=$('#analyticsCursor');slider.min=start;slider.max=end;
    updateCursor(Math.min(end,Math.max(start,cursor??end)),true);
    for(const c of controls)c.disabled=false;
  }
  function drawScatter(run,[a,b]) {
    if(!a||!b) {$('#analyticsScatter').innerHTML=empty('至少需要两个数值字段。');return;}
    plot($('#analyticsScatter'),{title:a+' × '+b,xUnit:`${a} · ${metricUnit(run,a)}`,yUnit:`${b} · ${metricUnit(run,b)}`,
      series:[{label:run.label,kind:'scatter',points:run.window.map(o=>[o[a],o[b],'t='+nfmt(o.sim_t)])}],note:'使用同条观测，缺失成对排除。'});
  }
  function drawEffects(rows,metric,unit) {
    const baseline=new Map(rows.filter(r=>r.arm==='基线').map(r=>[r.origin_id+'|'+r.seed,r]));
    const effect=new Map();
    for(const row of rows) {
      const match=baseline.get(row.origin_id+'|'+row.seed);
      if(!match||row.arm==='基线')continue;
      const byTime=new Map(match.window.map(o=>[o.sim_t,o[metric]]));
      const differences=row.window.filter(o=>finite(o[metric])&&finite(byTime.get(o.sim_t))).map(o=>o[metric]-byTime.get(o.sim_t));
      if(!differences.length)continue;
      const key=row.origin_id.slice(-7)+' · '+row.arm,p=effect.get(key)||[];
      p.push([p.length+1,mean(differences),'种子 '+row.seed+' · '+differences.length+' 组共同时间点']);effect.set(key,p);
    }
    plot($('#analyticsEffect'),{title:'同种子配对差',xUnit:'配对序号',yUnit:unit,zero:true,
      empty:'需要同一实验中具有同种子、同时间观测的基线与干预组。',series:[...effect].map(([label,points])=>({label,kind:'scatter',points})),
      note:'每点为当前窗口确有共同观测的干预减基线均值。'});
  }
  function drawSensitivity(rows,metric,unit) {
    const groups=new Map();
    for(const r of rows)if(r.scan_param&&finite(r.value)) {
      const points=groups.get(r.scan_param)||[];
      points.push([r.value,mean(r.window.map(o=>o[metric]).filter(finite)),r.run_id]);groups.set(r.scan_param,points);
    }
    const first=[...groups][0];
    plot($('#analyticsSensitivity'),{title:'参数扫描敏感性',xUnit:first?.[0]||'扫描参数',yUnit:unit,
      empty:'先在研究实验室执行参数扫描，然后加入该扫描归档。',series:first?[{label:first[0],kind:'scatter',points:first[1]}]:[]});
  }
  function drawProfiles(rows,keys,first) {
    const chosen=keys.slice(0,6);
    const host=$('#analyticsMulti');
    if(chosen.length<2){host.innerHTML=empty('多变量坐标需至少两个观测字段。');return;}
    const profiles=rows.slice(0,12).map(r=>({label:r.label,values:chosen.map(k=>mean(r.window.map(o=>o[k]).filter(finite)))}));
    const extents=chosen.map((_,i)=>range(profiles.map(p=>p.values[i]).filter(finite)));
    const x=i=>57+526*i/(chosen.length-1);
    host.innerHTML=`<svg viewBox="0 0 640 230" role="img" aria-label="按运行比较不同单位指标的时间窗均值">
      <rect width="640" height="230" fill="#0d1826"/>${chosen.map((k,i)=>`<path d="M${x(i)} 37V168" stroke="#66839b"/><text x="${x(i)}" y="19" text-anchor="middle" fill="#dae9f4" font-size="10">${esc(k.length>14?k.slice(0,13)+'…':k)}<title>${esc(k)}</title></text><text x="${x(i)}" y="190" text-anchor="middle" fill="#a7bdd1" font-size="10">${esc(metricUnit(first,k))}</text><text x="${x(i)}" y="33" text-anchor="middle" fill="#a7bdd1" font-size="10">${esc(nfmt(extents[i][1]))}</text><text x="${x(i)}" y="181" text-anchor="middle" fill="#a7bdd1" font-size="10">${esc(nfmt(extents[i][0]))}</text>`).join('')}
      ${profiles.map((p,j)=>{
        let connected=false;
        const d=p.values.map((v,i)=>{
          if(!finite(v)){connected=false;return '';}
          const [a,b]=extents[i],y=a===b?103:168-131*(v-a)/(b-a);
          const command=connected?'L':'M';connected=true;return command+x(i)+' '+y;
        }).join(' ');
        return `<path d="${d}" stroke="${colors[j%colors.length]}" fill="none" stroke-width="2" opacity=".72"><title>${esc(p.label+' · '+chosen.map((k,i)=>k+' '+nfmt(p.values[i])).join(' / '))}</title></path>`;
      }).join('')}</svg><p class="space-note">每轴按所选运行均值范围缩放。绝对最小值、最大值与单位标在轴上。</p>`;
  }
  function paintProvenance() {
    const rows=allRows();
    $('#analyticsProvenance').innerHTML=`<table class="workbench-table"><thead><tr><th>运行</th><th>模型 / 时间尺度</th><th>组或参数</th><th>种子</th><th>观测</th><th>代码版本</th></tr></thead><tbody>
    ${rows.map(r=>`<tr><td><button data-open-run="${esc(r.run_id)}"><code>${esc(r.run_id)}</code></button></td><td>${esc(cohort(r))}</td><td>${esc(r.label)}</td><td>${esc(r.seed??r.manifest?.rng?.seed??'—')}</td><td>${r.observations.length}</td><td><code title="${esc(r.manifest?.code_version||r.manifest?.source_fingerprint||'')}" >${esc((r.manifest?.code_version||r.manifest?.source_fingerprint||'未记载').slice(0,15))}</code></td></tr>`).join('')}</tbody></table>`;
  }
  async function recent() {
    const h=await api('/api/history?metadata_only=true&limit=60'),select=$('#analyticsPick'),previous=select.value;
    select.replaceChildren(new Option('选择已保存的运行或实验',''),...h.entries.map(r=>new Option(`${r.model_id||''} · ${r.intent||r.kind} · ${r.run_id}`,r.run_id)));
    if(h.entries.some(r=>r.run_id===previous))select.value=previous;
    return h.entries;
  }
  function currentId() {
    const s=window.DAYAN_RESULTS;
    return s.payload?.experiment_id || s.payload?.analysis_id || s.runs[s.selected]?.run_id;
  }
  const error=e=>write('#analyticsStatus',e.message||e);
  function init() {
    if(initialized)return;
    headings();
    initialized=true;
    $('#analyticsAdd').onclick=()=>{
      userSelection=true;
      addArchive($('#analyticsPick').value).then(initializeFilters).catch(error);
    };
    $('#analyticsCurrent').onclick=()=>{
      const id=currentId();
      if(!id){error('当前没有完整归档。');return;}
      userSelection=true;addArchive(id).then(initializeFilters).catch(error);
    };
    $('#analyticsCohort').oninput=()=>selectDetails(true);
    for(const id of ['#analyticsMetric','#analyticsFrom','#analyticsTo']) $(id).onchange=paint;
    $('#analyticsCursor').oninput=()=>updateCursor(Number($('#analyticsCursor').value),true);
    $('#analyticsJump').onclick=async()=>{
      if(!activeRows.length)return;
      try{const t=cursor;await window.DAYAN_RESULTS.restore(activeRows[0].run_id);window.DAYAN_RESULTS.seek(t);}
      catch(e){error(e);}
    };
    $('#analyticsExport').onclick=()=>{
      const header=['archive_id','run_id','model_id','clock','metric','unit','sim_t','value','missing','seed','arm','code_version'];
      csv('DAYAN-observations-'+activeMetric+'.csv',[header,...activeRows.flatMap(r=>r.window.map(o=>[r.origin_id,r.run_id,r.model_id,period(r),activeMetric,activeUnit,o.sim_t,
        finite(o[activeMetric])?o[activeMetric]:null,finite(o[activeMetric])?0:1,r.seed??r.manifest?.rng?.seed,r.arm,r.manifest?.code_version||r.manifest?.source_fingerprint]))]);
    };
    $('#analyticsSvg').onclick=()=>{if(mainChart)download('DAYAN-'+activeMetric+'.svg',mainChart.svg.outerHTML,'image/svg+xml');};
  }
  async function load() {
    init();
    if(loading)return loading;
    loading=recent().then(async rows=>{
      if(!source.size&&!userSelection) await addArchive(currentId()||rows.find(r=>r.kind==='experiment')?.run_id||rows[0]?.run_id,true);
      if(!activeRows.length)initializeFilters();
    }).catch(error).finally(()=>{loading=null;});
    return loading;
  }
  async function open(id) {
    init();userSelection=true;
    switchPage('analytics');
    try{await addArchive(id);initializeFilters();}
    catch(e){error(e);}
  }
  window.DAYAN_ANALYTICS={load,open};
})();
