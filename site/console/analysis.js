/* Shared, deterministic analysis of the saved observations; no data generation. */
(() => {
  'use strict';
  const finite = x => typeof x === 'number' && Number.isFinite(x);
  const present = entity => !(entity.type === 'pedestrian' && entity.state === 'exited');
  const numericFields = rows => [...new Set(rows.flatMap(r => Object.keys(r || {})))].filter(k => k !== 'sim_t' && rows.some(r => finite(r[k])));
  const mean = xs => xs.length ? xs.reduce((s,x) => s+x,0)/xs.length : null;
  function varyingFields(rows, keys = numericFields(rows)) {
    return keys.filter(key => {
      let first;
      for (const row of rows) if (finite(row[key])) {
        if (first === undefined) first = row[key];
        else if (row[key] !== first) return true;
      }
      return false;
    });
  }
  function correlationFields(rows, keys = numericFields(rows), limit = 8) {
    const candidates = varyingFields(rows, keys), selected = [];
    for (let i=0; i<candidates.length; i++) for (let j=i+1; j<candidates.length; j++) {
      const pair = [candidates[i],candidates[j]], extra = pair.filter(key=>!selected.includes(key));
      if (!extra.length || selected.length+extra.length>limit) continue;
      if (correlation(rows,...pair).value !== null) selected.push(...extra);
      if (selected.length===limit) return selected;
    }
    return selected;
  }
  function correlation(rows,a,b) {
    let n=0,ma=0,mb=0,cov=0,va=0,vb=0;
    for(const r of rows){
      if(!finite(r[a])||!finite(r[b]))continue;
      n++;const dx=r[a]-ma,dy=r[b]-mb;ma+=dx/n;mb+=dy/n;
      cov+=dx*(r[b]-mb);va+=dx*(r[a]-ma);vb+=dy*(r[b]-mb);
    }
    return {value:n>=3&&va>0&&vb>0?Math.max(-1,Math.min(1,cov/Math.sqrt(va*vb))):null,n};
  }
  function savedEvents(stream) {
    const events=(stream?.events||[]).filter(e=>finite(e.sim_t??e.t)).map(e=>({...e,sim_t:e.sim_t??e.t}));
    const ordered=params=>JSON.stringify(Object.fromEntries(Object.entries(params||{}).sort(([a],[b])=>a.localeCompare(b))));
    for(const iv of stream?.manifest?.interventions||[]){
      if(!iv.applied||!finite(iv.actual_t))continue;
      const exists=events.some(e=>e.etype==='intervention'&&Math.abs(e.sim_t-iv.actual_t)<1e-9&&ordered(e.params)===ordered(iv.params));
      if(!exists)events.push({etype:'intervention',applied:true,label:iv.label||'参数干预生效',sim_t:iv.actual_t,params:{...iv.params}});
    }
    return events.sort((a,b)=>a.sim_t-b.sim_t);
  }
  function windowRows(rows, window) {
    return rows.filter(o => !window || ((window.exclusive ? o.sim_t > window.from + 1e-9 : o.sim_t >= window.from - 1e-9) && o.sim_t <= window.to + 1e-9));
  }
  const names = {audit_target:'审计目标覆盖率',audit_coverage:'实际审计覆盖率',green_share:'绿色生产率',fraud_share:'绿色欺诈率',strict_share:'积极监管率',lax_share:'监管松懈率',audited_cells:'审计格数',n_cells:'元胞数',strict_cells:'积极监管格数',green_cells:'绿色生产格数',lax_detected:'发现监管松懈',fraud_detected:'发现绿色欺诈',lax_fraud_detected:'发现松懈与欺诈并存',audit_feedback:'审计净收益差',regulator_switches:'监管策略变动',farm_switches:'生产策略变动',distance_to_ideal:'距理想状态',arrived_count:'累计到达',arrived_fraction:'到达比例',n:'主体数量',exit_x:'出口横坐标',exit_y:'出口纵坐标',flux:'交通通量',density:'车辆密度',n_cars:'车辆数',speed:'速度',I:'感染量 I',S:'易感量 S',R:'康复量 R',I_total:'感染总量',gini:'基尼系数',evacuated:'累计疏散',arrived:'累计到达',waiting:'等待人数',k:'人均资本',wealth:'财富',income:'收入',population:'人口',x:'横向位置',y:'纵向位置',state:'主体状态',type:'主体类型',group:'所属群体',age:'年龄',risk:'风险',information:'信息状态',infected:'感染状态',susceptible:'易感状态',recovered:'康复状态',moving:'移动',exited:'已离开',waiting_service:'等待服务',mean_speed:'平均速度',total:'总量'};
  Object.assign(names,{alive:'在场人数',fallen:'倒地待助人数',assisted:'协助中人数',aid_completed:'累计恢复人数',
    yielding:'局部避让人数',local_conflicts:'几何相交对数',min_separation:'最小行人间距'});
  const label = key => names[key] || key;
  function populationField(frame,key) {
    const dot=key.indexOf('.'), groups=frame?.statistics?.groups||frame?.population?.groups||[];
    const group=dot>0?groups.find(g=>g.id===key.slice(0,dot)):null, field=group?key.slice(dot+1):key;
    const unit=group?.units?.[field]??frame?.statistics?.distributions?.[key]?.unit;
    const name=(group?group.label+' · ':'')+label(field);
    return {name,unit,title:name+(unit&&unit!=='category'?'（'+unit+'）':'')};
  }
  const colors = ['#51decc','#b6a0fb','#eebb79','#86bdf2','#ed9bac','#b9d98c'];
  const esc = x => String(x ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt = x => !finite(x)?'—':Math.abs(x)>=1e7?new Intl.NumberFormat('zh-CN',{notation:'compact',maximumSignificantDigits:5}).format(x):x!==0&&Math.abs(x)<1e-4?x.toExponential(3):new Intl.NumberFormat('zh-CN',{maximumSignificantDigits:5}).format(x);
  const extent=values=>{let lo=Infinity,hi=-Infinity;for(const value of values){if(value<lo)lo=value;if(value>hi)hi=value;}return [lo,hi];};
  const pct = x => finite(x) ? new Intl.NumberFormat('zh-CN',{style:'percent',maximumFractionDigits:1}).format(x) : '—';
  const colorFor=(s,run,index)=>s.kind==='experiment'?colors[[...new Set(s.runs.map(r=>r.arm))].indexOf(run.arm)%colors.length]:colors[index%colors.length];
  const $ = s => document.querySelector(s);
  const put = (s,text) => {const e=$(s);if(e&&e.textContent!==String(text))e.textContent=text;};
  const at = (rows,t) => {let lo=0,hi=rows.length;while(lo<hi){const m=(lo+hi)>>>1;if(rows[m].sim_t<=t+1e-9)lo=m+1;else hi=m;}return Math.max(0,lo-1);};
  const unitLabel=unit=>({'model agent':'模型主体','person':'人','people':'人','fraction':'比例','minute':'分钟','second':'秒','m':'米','person · minute × scenario severity':'人·分钟×情景强度'})[unit]||unit;
  function metricInfo(model,key,manifest) {
    const declared=manifest?.output_contract?.fields?.[key]?.unit;
    if(model==='NET106')return {name:label(key),unit:({flux:'模型通量',speed:'格/步',n_cars:'辆',density:'比例'})[key]||unitLabel(declared)||'原模型单位',definition:key==='flux'?'车辆密度 × 平均速度，未换算为现实交通流量':''};
    if(model==='NET052'&&['I','S'].includes(key))return {name:key==='I'?'感染比例':'易感比例',unit:'比例',definition:'模型状态比例'};
    if(declared)return {name:label(key),unit:unitLabel(declared),definition:''};
    return {name:label(key),unit:'原模型单位',definition:'保留模型原始量纲；不自动换算现实单位'};
  }
  function interventionTime(s) {
    const base=s.runs.find(r=>r.arm==='基线')||s.runs[0];
    const signature=i=>JSON.stringify([i.requested_t??i.at_t,i.params]);
    const common=new Set((base?.manifest?.interventions||[]).filter(i=>i.applied).map(signature));
    const times=s.runs.flatMap(r=>(r.manifest?.interventions||[]).filter(i=>i.applied&&(s.runs.length===1||!common.has(signature(i)))).map(i=>i.actual_t));
    return times.filter(finite).sort((a,b)=>a-b)[0]??null;
  }
  function resolvedWindow(s) {
    if(s.windowMode==='post'){const t=interventionTime(s);if(t!==null)return {from:t,to:s.end,exclusive:true,mode:'post'};}
    if(s.windowMode==='custom'&&s.customWindow)return {...s.customWindow,exclusive:false,mode:'custom'};
    return {from:s.start,to:s.end,exclusive:false,mode:'all'};
  }
  function summarize(s) {
    const window=resolvedWindow(s), perRun=s.runs.map((r,i)=>{
      const values=windowRows(r.observations||[],window).map(o=>o[s.metric]).filter(finite);
      return {run:r,index:i,n:values.length,mean:mean(values),first:values[0]??null,last:values.at(-1)??null};
    });
    const groupMap=new Map();
    for(const p of perRun){const name=s.kind==='experiment'?(p.run.arm||p.run.label):s.kind==='ensemble'?'种子重复':p.run.label; if(!groupMap.has(name))groupMap.set(name,[]);groupMap.get(name).push(p);}
    const groups=[...groupMap].map(([name,entries])=>({name,entries,mean:mean(entries.map(x=>x.mean).filter(finite)),n:entries.filter(x=>finite(x.mean)).length}));
    const baseline=groups.find(g=>g.name==='基线')||groups[0], arm=groups.find(g=>g!==baseline&&g.name===(s.kind==='experiment'?s.runs[s.selected]?.arm:s.runs[s.selected]?.label))||groups.find(g=>g!==baseline);
    const differences=[],pairedBaselines=[];
    if(s.kind==='experiment'&&baseline&&arm){for(const x of arm.entries){const seed=x.run.seed??x.run.manifest?.rng?.seed;const b=baseline.entries.find(v=>(v.run.seed??v.run.manifest?.rng?.seed)===seed);if(b&&finite(x.mean)&&finite(b.mean)){differences.push(x.mean-b.mean);pairedBaselines.push(b.mean);}}}
    const difference=differences.length?mean(differences):(finite(arm?.mean)&&finite(baseline?.mean)?arm.mean-baseline.mean:null);
    const denominator=pairedBaselines.length?mean(pairedBaselines):baseline?.mean;
    const seedMeans=perRun.map(x=>x.mean).filter(finite),seedAverage=mean(seedMeans),seedStd=seedMeans.length>1?Math.sqrt(seedMeans.reduce((sum,x)=>sum+(x-seedAverage)**2,0)/(seedMeans.length-1)):null;
    return {window,perRun,groups,baseline,arm,difference,relative:denominator&&finite(difference)?difference/denominator:null,pairedN:differences.length,seedAverage,seedStd};
  }
  function histogram(entities,field) {
    const values=entities.map(e=>e[field]).filter(finite),missing=entities.length-values.length;
    if(!values.length)return {bins:[],n:0,missing};
    const sorted=[...new Set(values)].sort((a,b)=>a-b);
    if(sorted.length<=10&&sorted.every(Number.isInteger))return {bins:sorted.map(v=>({label:String(v),count:values.filter(x=>x===v).length,from:v,to:v})),n:values.length,missing};
    let [lo,hi]=extent(sorted);if(lo===hi)return {bins:[{label:fmt(lo),count:values.length,from:lo,to:hi}],n:values.length,missing};
    const n=8,width=(hi-lo)/n,bins=Array.from({length:n},(_,i)=>({label:fmt(lo+i*width),count:0,from:lo+i*width,to:lo+(i+1)*width}));
    values.forEach(x=>bins[Math.min(n-1,Math.floor((x-lo)/width))].count++);
    return {bins,n:values.length,missing};
  }
  function categories(entities,field) {
    const counts=new Map();let missing=0;
    for(const e of entities){const x=e[field];if(x===null||x===undefined||typeof x==='object'){missing++;continue;}const name=String(x);counts.set(name,(counts.get(name)||0)+1);}
    const all=[...counts].sort((a,b)=>b[1]-a[1]),head=all.slice(0,9),tail=all.slice(9);
    if(tail.length)head.push([`其他（${tail.length}类）`,tail.reduce((s,x)=>s+x[1],0)]);
    return {bins:head.map(([name,count])=>({label:label(name),count})),n:entities.length-missing,missing};
  }
  function options(select,choices,value,empty) {
    if(!select)return;
    const signature=JSON.stringify(choices);
    if(select.dataset.options!==signature){select.innerHTML=choices.length?choices.map(([key,name])=>`<option value="${esc(key)}">${esc(name)}</option>`).join(''):`<option value="">${esc(empty)}</option>`;select.dataset.options=signature;}
    select.disabled=!choices.length;if(choices.some(x=>String(x[0])===String(value)))select.value=value;
  }
  function canvas(element) {
    if(!element||!element.checkVisibility())return null;
    const w=Math.round(element.clientWidth),h=Math.round(element.clientHeight);if(w<50||h<40)return null;
    const ratio=Math.min(window.devicePixelRatio||1,2);
    if(element.width!==Math.round(w*ratio))element.width=Math.round(w*ratio);
    if(element.height!==Math.round(h*ratio))element.height=Math.round(h*ratio);
    const ctx=element.getContext('2d');ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,w,h);ctx.font='11px "Microsoft YaHei",sans-serif';ctx.fillStyle='#a8c0cf';
    element._hits=[];delete element._plot;delete element._timePlot;return {ctx,w,h,element};
  }
  function empty(element,text) {const c=canvas(element);if(!c)return;c.ctx.fillStyle='#a1b5c3';const max=Math.max(10,Math.floor((c.w-40)/12));let y=50;for(let i=0;i<text.length;i+=max){c.ctx.fillText(text.slice(i,i+max),20,y);y+=21;}element.setAttribute('aria-label',text);element.dataset.kind='empty';}
  function drawLine(element,series,metric,time,limits,events=[],window=null,unit='原模型单位',clock='模型时间 sim_t',options={}) {
    const c=canvas(element);if(!c)return;
    const {ctx,w,h}=c,all=series.flatMap(r=>r.rows.map(o=>o[metric]).filter(finite));
    if(!all.length){empty(element,'该指标没有可绘制的观测');return;}
    let [lo,hi]=extent(all);
    if(options.includeZero){lo=Math.min(0,lo);hi=Math.max(0,hi);}
    if(options.zeroBaseline!==false&&lo>=0)lo=0;
    if(lo===hi){const pad=Math.max(1,Math.abs(lo)*.01);lo-=options.zeroBaseline===false?pad:0;hi+=pad;}
    else if(options.zeroBaseline===false){const pad=(hi-lo)*.06;lo-=pad;hi+=pad;}
    const p={l:57,r:19,t:23,b:33},pw=w-p.l-p.r,ph=h-p.t-p.b;
    const x=t=>limits[0]===limits[1]?p.l+pw/2:p.l+(t-limits[0])/(limits[1]-limits[0])*pw,y=v=>p.t+(hi-v)/(hi-lo)*ph;
    for(const band of options.bands||[]){const from=Math.max(limits[0],band.from),to=Math.min(limits[1],band.to);if(!(to>from))continue;
      ctx.fillStyle=band.color;ctx.fillRect(x(from),p.t,x(to)-x(from),ph);
      ctx.fillStyle='#9db3c5';ctx.textAlign='center';ctx.fillText(band.label,(x(from)+x(to))/2,p.t+13);}
    if(window&&window.mode!=='all'){ctx.fillStyle='#87a9c012';ctx.fillRect(x(window.from),p.t,Math.max(0,x(window.to)-x(window.from)),ph);}
    ctx.strokeStyle='#294553';ctx.lineWidth=1;ctx.fillStyle='#94afc0';
    for(let i=0;i<4;i++){const value=lo+(hi-lo)*i/3,yy=y(value);ctx.beginPath();ctx.moveTo(p.l,yy);ctx.lineTo(w-p.r,yy);ctx.stroke();ctx.textAlign='right';ctx.fillText(fmt(value),p.l-7,yy+4);}
    ctx.textAlign='left';ctx.fillText(unit,p.l,12);
    for(let i=0;i<=3;i++){const t=limits[0]+(limits[1]-limits[0])*i/3;ctx.textAlign=i===3?'right':i===0?'left':'center';ctx.fillText(fmt(t),x(t),h-16);}
    ctx.textAlign='right';ctx.fillText(clock,w-p.r,h-1);
    for(const t of [...new Set(events.filter(finite))]){if(t<limits[0]||t>limits[1])continue;ctx.setLineDash([3,3]);ctx.strokeStyle='#99b8c080';ctx.beginPath();ctx.moveTo(x(t),p.t);ctx.lineTo(x(t),h-p.b);ctx.stroke();ctx.setLineDash([]);}
    series.forEach((r,j)=>{ctx.strokeStyle=r.color||colors[j%colors.length];ctx.lineWidth=1.8;ctx.setLineDash(j%2?[5,3]:[]);ctx.beginPath();let pen=false;const stride=Math.max(1,Math.ceil(r.rows.length/1200));
      r.rows.forEach((o,i)=>{if(!finite(o[metric])){pen=false;return;}if(i%stride&&i!==r.rows.length-1)return;const xx=x(o.sim_t),yy=y(o[metric]);
        if(r.pointsOnly){ctx.moveTo(xx+3,yy);ctx.arc(xx,yy,3,0,Math.PI*2);}else{if(pen)ctx.lineTo(xx,yy);else ctx.moveTo(xx,yy);pen=true;}});
      if(r.pointsOnly){ctx.fillStyle=r.color||colors[j%colors.length];ctx.fill();}else ctx.stroke();ctx.setLineDash([]);
      const row=finite(time)&&r.rows[at(r.rows,time)];if(row&&finite(row[metric])){ctx.fillStyle=r.color||colors[j%colors.length];ctx.beginPath();ctx.arc(x(row.sim_t),y(row[metric]),3,0,Math.PI*2);ctx.fill();}
    });
    if(finite(time)){ctx.strokeStyle='#c6d8df85';ctx.setLineDash([3,3]);ctx.beginPath();ctx.moveTo(x(time),p.t);ctx.lineTo(x(time),h-p.b);ctx.stroke();ctx.setLineDash([]);}
    element.dataset.kind='line';element._plot={x0:p.l,x1:w-p.r,t0:limits[0],t1:limits[1]};
    element.dataset.yMin=String(lo);element.dataset.yMax=String(hi);
    element.setAttribute('aria-label',`${label(metric)}时间序列，${series.length}组实际数据，当前模型时间${fmt(time)}，单位${unit}`);
  }
  function drawBars(element,bins,color=colors[0],unit='主体数') {
    const c=canvas(element);if(!c)return;const {ctx,w,h}=c;if(!bins.length){empty(element,'当前没有可统计的数据');return;}
    const p={l:42,r:14,t:22,b:40},pw=w-p.l-p.r,ph=h-p.t-p.b,max=Math.max(1,Math.ceil(Math.max(...bins.map(x=>x.count))/3)*3),step=pw/bins.length;
    ctx.fillStyle='#94afc0';ctx.fillText(unit,p.l,12);ctx.strokeStyle='#294553';
    for(let i=0;i<=3;i++){const n=max*i/3,yy=p.t+(1-i/3)*ph;ctx.beginPath();ctx.moveTo(p.l,yy);ctx.lineTo(w-p.r,yy);ctx.stroke();ctx.textAlign='right';ctx.fillText(fmt(n),p.l-6,yy+4);}
    bins.forEach((b,i)=>{const xx=p.l+(i+.15)*step,bw=step*.7,hh=b.count/max*ph;ctx.fillStyle=b.color||color;ctx.fillRect(xx,p.t+ph-hh,bw,hh);ctx.fillStyle='#d6e8f0';ctx.textAlign='center';ctx.fillText(fmt(b.count),xx+bw/2,Math.max(23,p.t+ph-hh-5));
      const title=String(b.label),maxChars=Math.max(2,Math.floor(step/11));ctx.fillStyle='#a1b5c3';ctx.fillText(title.length>maxChars?title.slice(0,maxChars)+'…':title,xx+bw/2,h-21);element._hits.push({x:xx,y:p.t,w:bw,h:ph,text:`${title}：${fmt(b.count)} ${unit}`});});
    element.dataset.kind='bar';element.dataset.total=String(bins.reduce((s,b)=>s+b.count,0));element.setAttribute('aria-label',bins.map(b=>`${b.label} ${b.count}${unit}`).join('；'));
  }
  function drawCdf(element, values, unit, color = colors[0]) {
    const c=canvas(element);
    if (!c) return;
    const summary=Array.isArray(values)?null:values;
    const xs=summary?[]:values.filter(finite).sort((a,b)=>a-b), curve=summary?.cdf||[];
    if(!summary)for(let i=0;i<xs.length;){let j=i+1;while(j<xs.length&&xs[j]===xs[i])j++;curve.push([xs[i],j/xs.length]);i=j;}
    if (!curve.length) return empty(element,'当前没有数值主体属性');
    const n=summary?.n??xs.length, lo=curve[0][0], hi=curve.at(-1)[0];
    const {ctx,w,h}=c, left=45, right=w-16, top=21, bottom=h-29, span=hi-lo;
    const x=value=>span?left+(value-lo)/span*(right-left):(left+right)/2;
    const y=fraction=>bottom-fraction*(bottom-top);
    for (const fraction of [0,.5,1]) {
      ctx.fillStyle='#a8c0cf';ctx.textAlign='right';ctx.fillText(Math.round(fraction*100)+'%',left-6,y(fraction)+3);
      ctx.strokeStyle='#2c4658';ctx.beginPath();ctx.moveTo(left,y(fraction));ctx.lineTo(right,y(fraction));ctx.stroke();
    }
    ctx.beginPath();ctx.moveTo(left,bottom);
    let previous=0;
    for(const [value,probability] of curve){
      if(summary?.cdf_complete!==false)ctx.lineTo(x(value),y(previous));
      previous=probability;ctx.lineTo(x(value),y(probability));
    }
    ctx.lineTo(right,top);
    ctx.strokeStyle=color;ctx.lineWidth=2;ctx.stroke();
    ctx.lineTo(right,bottom);ctx.closePath();ctx.fillStyle=color+'22';ctx.fill();
    ctx.fillStyle='#a8c0cf';ctx.textAlign='left';ctx.fillText(fmt(lo),left,h-10);
    ctx.textAlign='right';ctx.fillText(span?fmt(hi):'',right,h-10);
    element.dataset.kind='cdf';element.dataset.total=String(n);
    element.dataset.scope=summary?'full_population':'archived_values';
    element.setAttribute('aria-label',unit+'累计分布，'+n+'个实际值，范围'+fmt(lo)+'至'+fmt(hi)+(summary?.cdf_complete===false?'，按全量累计概率取点显示':''));
  }

  let differenceCache;
  function pairedDifference(s, summary) {
    if (s.kind!=='experiment'||!summary.arm||!summary.baseline) return [];
    const {arm,baseline}=summary;
    if (differenceCache?.runs===s.runs && differenceCache.metric===s.metric && differenceCache.arm===arm.name) return differenceCache.rows;
    const mapped=new Map();
    const seed=entry=>entry.run.seed??entry.run.manifest?.rng?.seed;
    for (const test of arm.entries) {
      const reference=baseline.entries.find(entry=>seed(test)!==undefined&&seed(test)===seed(entry));
      if(!reference || reference.run.model_id!==test.run.model_id)continue;
      const byTime=new Map(reference.run.observations.map(row=>[row.sim_t,row[s.metric]]));
      for(const row of test.run.observations){
        const value=byTime.get(row.sim_t);
        if(!finite(value)||!finite(row[s.metric]))continue;
        const item=mapped.get(row.sim_t)||{sum:0,n:0};
        item.sum+=row[s.metric]-value;item.n++;
        mapped.set(row.sim_t,item);
      }
    }
    const times=[...new Set(arm.entries.flatMap(entry=>entry.run.observations.map(row=>row.sim_t)))].sort((a,b)=>a-b);
    const rows=times.map(sim_t=>{const point=mapped.get(sim_t);return {sim_t,difference:point?point.sum/point.n:null,pairs:point?.n||0};});
    differenceCache={runs:s.runs,arm:arm.name,metric:s.metric,rows};return rows;
  }
  function renderComparison(s,summary) {
    const svg=$('#comparisonChart');if(!svg)return;const width=svg.clientWidth||300,items=(s.kind==='ensemble'?summary.perRun.map(r=>({name:r.run.label,mean:r.mean,n:1})):summary.groups).filter(g=>finite(g.mean));
    const contrast=pairedDifference(s,summary);
    const hasPaired=contrast.some(row=>row.pairs);
    $('#effectTrend').hidden=!hasPaired;
    svg.toggleAttribute('hidden',hasPaired);
    if(hasPaired){
      drawLine($('#effectTrend'),[{rows:contrast,color:colors[1]}],'difference',s.time,[s.start,s.end],
        s.events.filter(e=>e.etype==='intervention').map(e=>e.sim_t),summary.window,metricInfo(s.runs[s.selected].model_id,s.metric,s.runs[s.selected].manifest).unit);
      $('#effectTrend').dataset.kind='paired-difference';
      $('#effectTrend').setAttribute('aria-label','同种子配对差，'+summary.arm.name+'减'+summary.baseline.name);
    }
    const height=Math.max(document.body.classList.contains('command-center')?70:166,items.length*33+35);svg.style.height=height+'px';svg.setAttribute('viewBox',`0 0 ${width} ${height}`);
    if(!items.length){svg.innerHTML=`<text x="16" y="60" fill="#a1b5c3" font-size="12">所选窗口内没有可比较的观测</text>`;return;}
    const lo=Math.min(0,...items.map(x=>x.mean)),hi=Math.max(0,...items.map(x=>x.mean)),span=hi-lo||1,left=Math.min(120,width*.35),right=68,pw=Math.max(40,width-left-right),x=v=>left+(v-lo)/span*pw;
    if (!hasPaired) svg.innerHTML=items.map((g,i)=>{
      const y=29+i*33;
      return `<text x="4" y="${y+4}" fill="#b1c9d6" font-size="11">${esc(g.name.length>13?g.name.slice(0,12)+'…':g.name)}</text><line x1="${left}" y1="${y}" x2="${width-right}" y2="${y}" stroke="#365367"/><circle cx="${x(g.mean)}" cy="${y}" r="4.5" fill="${colors[i%colors.length]}"><title>${esc(g.name)} · ${g.mean} · ${g.n}次运行</title></circle><text x="${width-3}" y="${y+4}" text-anchor="end" fill="#e6f2f7" font-size="11">${esc(fmt(g.mean))}</text>`;
    }).join('');
    svg.setAttribute('aria-label',items.map(g=>`${g.name}窗口均值${g.mean}，${g.n}次运行`).join('；'));
    put('#comparisonTitle',s.kind==='ensemble'?'不同种子的结果':s.runs.length>1?'方案差异有多大':'这段过程的结果');
    put('#effectLabel',summary.arm?'相对基线差异':'窗口均值');
    put('#effectNumber',summary.arm?pct(summary.relative):fmt(summary.perRun[s.selected]?.mean));
    put('#effectSub',summary.arm?`差值 ${fmt(summary.difference)}${summary.pairedN?' · 配对种子 '+summary.pairedN:''}`:`${summary.perRun[s.selected]?.n||0}个观测时点`);
    put('#comparisonSample',summary.pairedN?`配对 n=${summary.pairedN}`:`${s.runs.length}次运行`);
    put('#comparisonNote',hasPaired?'同种子、同一时点的方案差':'');
  }
  let roadRaster;
  function renderHeat(s,frame,entities){
    const el=$('#structureChart'), c=canvas(el);
    if(!c)return;
    const {ctx,w,h}=c, p={l:34,r:12,t:14,b:28}, pw=w-p.l-p.r, ph=h-p.t-p.b;
    const density=frame.statistics?.density;
    const scope=density?[density.x_edges[0],density.y_edges[0],density.x_edges.at(-1),density.y_edges.at(-1)]:frame.space?.bounds;
    const [x0,x1]=scope?.length===4&&scope.every(finite)?[scope[0],scope[2]]:extent(entities.map(e=>e.x));
    const [y0,y1]=scope?.length===4&&scope.every(finite)?[scope[1],scope[3]]:extent(entities.map(e=>e.y));
    const nx=density?density.x_edges.length-1:x1>x0?12:1,ny=density?density.y_edges.length-1:y1>y0?8:1,dx=(x1-x0)/nx,dy=(y1-y0)/ny;
    const cells=Array.from({length:nx*ny},(_,i)=>({n:density?.counts[Math.floor(i/nx)][i%nx]??0,entities:[]}));
    for(const e of entities){
      if(e.x<x0||e.x>x1||e.y<y0||e.y>y1)continue;
      const x=dx?Math.max(0,Math.min(nx-1,Math.floor((e.x-x0)/dx))):0;
      const y=dy?Math.max(0,Math.min(ny-1,Math.floor((e.y-y0)/dy))):0;
      const cell=cells[y*nx+x];if(!density)cell.n++;cell.entities.push(e);
    }
    const peak=Math.max(0,...cells.map(cell=>cell.n)), cw=pw/nx, ch=ph/ny;
    const unit=unitLabel(density?.unit||frame.space?.unit)||'模型空间单位';
    cells.forEach((cell,i)=>{
      const ix=i%nx,iy=Math.floor(i/nx);
      const x=p.l+ix*cw,y=p.t+(ny-iy-1)*ch;
      const bounds=[x0+ix*dx,y0+iy*dy,x0+(ix+1)*dx,y0+(iy+1)*dy];
      const region='x '+fmt(bounds[0])+'–'+fmt(bounds[2])+'，y '+fmt(bounds[1])+'–'+fmt(bounds[3])+' '+unit;
      ctx.fillStyle=cell.n?'rgba(88,220,200,'+(.15+.73*cell.n/peak)+')':'#142739';
      ctx.fillRect(x,y,Math.max(1,cw-1),Math.max(1,ch-1));
      if(s.region?.index===i){ctx.strokeStyle='#ffcf87';ctx.strokeRect(x+.5,y+.5,cw-2,ch-2);}
      el._hits.push({x,y,w:cw,h:ch,text:region+' · '+cell.n+' 个主体',region,index:i,bounds,entities:cell.entities});
    });
    ctx.fillStyle='#a8c0cf';ctx.textAlign='left';ctx.fillText(fmt(x0),p.l,h-12);
    ctx.textAlign='right';ctx.fillText(fmt(x1),w-p.r,h-12);ctx.fillText(unit,w-p.r,h-1);
    el.dataset.kind='heatmap';el.dataset.total=String(density?.n??entities.length);
    el.dataset.scope=density?'full_population':'archived_entities';
    el.setAttribute('aria-label','主体位置热力图，共'+(density?.n??entities.length)+'个有坐标的主体');
    put('#structureTitle','主体空间密度');
    put('#structureSubtitle','t='+fmt(frame.sim_t));
    put('#structureNote',s.region?'当前选区 '+s.region.region+' · '+(cells[s.region.index]?.n||0)+' 个主体':(density?'全量归档 · ':'')+'最密分区 '+peak+' 个'+(density?.outside_bounds?' · 空间范围外 '+density.outside_bounds+' 个':''));
  }
  function renderComposition(el,record) {
    const c=canvas(el);
    if(!c)return;
    const {ctx,w,h}=c;
    const {nodes,paths,shares,reference}=record;
    const dx=w/(nodes.length+1),center=h*.45;
    const x=Object.fromEntries(nodes.map((node,i)=>[node.key,(i+1)*dx]));
    const maxRadius=Math.min(dx*.33,h*.26,30);
    for(const [from,to] of paths){
      const direction=Math.sign(x[to]-x[from]);
      const y=center+(nodes.length===2?-direction*maxRadius*.45:0);
      const end=x[to]-direction*(maxRadius+7);
      ctx.strokeStyle='#8aafbc';
      ctx.lineWidth=1.3;
      ctx.beginPath();ctx.moveTo(x[from]+direction*(maxRadius+3),y);ctx.lineTo(end,y);
      ctx.moveTo(end-5*direction,y-3);ctx.lineTo(end,y);ctx.lineTo(end-5*direction,y+3);ctx.stroke();
    }
    ctx.textAlign='center';
    for(const {key,label:group,color} of nodes) {
      const tone='#'+color.toString(16).padStart(6,'0');
      ctx.strokeStyle=tone;
      ctx.beginPath();ctx.arc(x[key],center,maxRadius,0,Math.PI*2);ctx.stroke();
      ctx.fillStyle=tone+'45';
      ctx.beginPath();ctx.arc(x[key],center,maxRadius*Math.sqrt(shares[key]),0,Math.PI*2);ctx.fill();
      ctx.fillStyle='#e0edf3';
      ctx.fillText(fmt(shares[key]*100)+'%',x[key],center+4);
      ctx.fillText(group,x[key],center+maxRadius+19);
    }
    el.dataset.kind='composition';
    put('#structureTitle',record.title);
    put('#structureSubtitle','当前群体占比');
    const note=paths.map(([from,to,transition])=>from+' → '+to+' '+transition).join(' · ');
    put('#structureNote',note+(reference===null?'':' · 稳态参考 '+fmt(reference*100)+'%'));
    el.setAttribute('aria-label',nodes.map(({key,label:group})=>group+' '+fmt(shares[key]*100)+'%').join('，'));
  }
  function renderStructure(s,frame) {
    const el=$('#structureChart'),frames=s.stream?.frames||[],entities=(frame?.entities||[]).filter(present),road=frame?.facilities?.find(f=>f.type==='road'&&finite(f.length));
    const run=s.runs[s.selected],modelId=s.stream?.model_id||run?.model_id;
    const composition=window.DAYAN_SCENE_STUDIO?.compositionFor(modelId,frame,run?.manifest?.actual?.effective_parameters?.N);
    if(composition){renderComposition(el,composition);return;}
    if(road&&entities.length&&entities.every(e=>finite(e.x)&&finite(e.speed))){
      const c=canvas(el);if(!c)return;const {ctx,w,h}=c,p={l:38,r:14,t:20,b:35},pw=w-p.l-p.r,ph=h-p.t-p.b,step=Math.max(1,Math.ceil(frames.length/240)),selected=frames.filter((f,i)=>i%step===0||i===frames.length-1);
      const span=Math.max(1e-12,s.end-s.start);
      const signature=[el.width,el.height,road.length,s.start,s.end].join('/');
      if(roadRaster?.frames!==frames||roadRaster.signature!==signature){
        const bitmap=document.createElement('canvas');bitmap.width=el.width;bitmap.height=el.height;
        const raster=bitmap.getContext('2d');
        raster.scale(bitmap.width/w,bitmap.height/h);
        raster.fillStyle='#182f3e';raster.fillRect(p.l,p.t,pw,ph);
        raster.save();raster.beginPath();raster.rect(p.l,p.t,pw,ph);raster.clip();
        const cellWidth=Math.max(1,pw/road.length);
        selected.forEach((f,i)=>{
          const y=(f.sim_t-s.start)/span*ph;
          const height=Math.max(1,((selected[i+1]?.sim_t??s.end)-f.sim_t)/span*ph);
          for(const e of f.entities||[]){
            if(!finite(e.x)||!finite(e.speed))continue;
            raster.fillStyle=e.speed===0?'#eebb79f2':'#51decc99';
            raster.fillRect(p.l+e.x/road.length*pw,p.t+Math.min(ph-1,y),cellWidth,height);
          }
        });
        raster.restore();roadRaster={frames,signature,bitmap};
      }
      ctx.drawImage(roadRaster.bitmap,0,0,w,h);
      ctx.fillStyle='#9bb7c7';ctx.textAlign='right';for(const f of [0,.5,1])ctx.fillText(fmt(s.start+(s.end-s.start)*f),p.l-6,p.t+f*ph+4);ctx.textAlign='left';ctx.fillText('sim_t',p.l,11);ctx.fillText('0',p.l,h-19);ctx.textAlign='right';ctx.fillText(fmt(road.length),w-p.r,h-19);ctx.fillText('道路位置（格）',w-p.r,h-2);
      const yy=p.t+(s.time-s.start)/span*ph;ctx.strokeStyle='#ecf7ffa0';ctx.beginPath();ctx.moveTo(p.l,yy);ctx.lineTo(w-p.r,yy);ctx.stroke();el.dataset.kind='space-time';el._timePlot={top:p.t,bottom:p.t+ph,from:s.start,to:s.end};
      put('#structureTitle','停车在何处形成');put('#structureSubtitle',s.runs[s.selected].label);put('#structureNote',`青色：行驶；琥珀：速度=0；底色：空格。${selected.length<frames.length?'显示'+selected.length+'/'+frames.length+'帧，完整状态可导出。':'使用完整'+frames.length+'帧。'}点击图中时间可定位回放。`);el.setAttribute('aria-label',`${s.runs[s.selected].label}的实际道路位置与时间，停车按速度零判断。`);return;
    }
    roadRaster=null;
    const spatial=entities.filter(e=>e.type!=='age_group'&&finite(e.x)&&finite(e.y));
    if(frame?.statistics?.density_unavailable){
      empty(el,frame.statistics.density_unavailable);put('#structureTitle','空间坐标范围');
      put('#structureSubtitle','');put('#structureNote','各主体组的属性可分别查看');return;
    }
    if(frame?.statistics?.density || spatial.length || (frame?.space?.bounds && frame.entities?.some(e=>!present(e)))){renderHeat(s,frame,spatial);return;}
    const rows=s.runs[s.selected]?.observations||[],fields=numericFields(rows).filter(k=>k!==s.metric&&new Set(rows.map(o=>o[k])).size>1).slice(0,3);
    put('#structureTitle','其他指标怎样变化');put('#structureSubtitle','各图独立量纲');
    if(!fields.length){empty(el,entities.length?'当前主体没有可绘制的位置；可在右侧查看属性轨迹。':'模型没有主体位置或其他变化指标，不生成地图。');put('#structureNote','仅使用模型实际提供的数据。');return;}
    const c=canvas(el);if(!c)return;const {ctx,w,h}=c,part=(h-16)/fields.length;
    fields.forEach((key,j)=>{const vals=rows.map(o=>o[key]).filter(finite),domain=extent(vals),lo=domain[0],hi=domain[1],top=j*part+18;ctx.fillStyle='#b6cdda';ctx.textAlign='left';ctx.fillText(label(key),15,top);ctx.textAlign='right';ctx.fillText(`${fmt(lo)} — ${fmt(hi)}`,w-15,top);ctx.strokeStyle=colors[(j+1)%colors.length];ctx.lineWidth=1.5;ctx.beginPath();let pen=false;rows.forEach(o=>{if(!finite(o[key])){pen=false;return;}const xx=15+(o.sim_t-s.start)/Math.max(1e-12,s.end-s.start)*(w-30),yy=top+9+(1-(o[key]-lo)/Math.max(1e-12,hi-lo))*(part-30);if(pen)ctx.lineTo(xx,yy);else ctx.moveTo(xx,yy);pen=true;});ctx.stroke();});
    el.dataset.kind='small-multiples';put('#structureNote','');
  }
  function render(s) {
    const run=s.runs[s.selected],frames=s.stream?.frames||[],frame=frames[at(frames,s.time)],entities=(frame?.entities||[]).filter(present),summary=summarize(s);s.viewAnalysis=summary;
    const info=metricInfo(run?.model_id,s.metric,run?.manifest),observed=run?.observations?.[at(run.observations,s.time)]||{};
    $('.analysis-controls').hidden=!run;
    $('.comparison').hidden=s.runs.length<2;
    $('#distributionPanel').hidden=!run;
    $('#entityPanel').hidden=!frames.some(item=>item.entities?.length||item.population?.count);
    if(!run){for(const id of ['#obsChart','#structureChart','#entityChart'])empty($(id),'');document.querySelectorAll('.kpi-row article').forEach(e=>{e.hidden=true;e.style.display='none';});$('#comparisonChart').innerHTML='';globalThis.DAYAN_PROCESS_CHARTS?.render([],null,0);return;}
    const eventTimes=s.runs.flatMap(r=>(r.manifest?.interventions||[]).filter(i=>i.applied).map(i=>i.actual_t));
    const clock=unitLabel(frame?.space?.time_unit||run.manifest?.actual?.time_unit)||'模型时间 sim_t';
    const entityUnit=key=>{
      const selected=frame?.entities?.find(e=>String(e.id)===s.entityId);
      const group=frame?.population?.groups?.find(g=>g.id===selected?.group);
      if(group)return group.units?.[key]||'未知单位';
      if(['x','y'].includes(key))return unitLabel(frame?.space?.unit)||'模型空间单位';
      if(key==='speed'&&frame?.space?.unit&&frame?.space?.time_unit&&run.model_id!=='NET106')return unitLabel(frame.space.unit)+'/'+unitLabel(frame.space.time_unit);
      return metricInfo(run.model_id,key).unit;
    };
    drawLine($('#obsChart'),s.runs.map((r,i)=>({rows:r.observations,color:colorFor(s,r,i)})),s.metric,s.time,[s.start,s.end],eventTimes,summary.window,info.unit,clock);
    put('#metricDescription',info.name);
    $('#metricDescription').title=info.definition;
    const window=summary.window,per=summary.perRun[s.selected];put('#analysisWindowLabel',window.mode==='all'?'':`${per?.n||0} 个观测时点`);
    const independent=s.kind==='experiment'?summary.pairedN:s.kind==='ensemble'?s.runs.length:1;
    put('#sampleNote',independent>1?`${independent} 个种子`:'');
    const post=$('#analysisWindow option[value="post"]');post.disabled=interventionTime(s)===null;$('#analysisWindow').value=s.windowMode||'all';
    $('#customWindowInputs').hidden=s.windowMode!=='custom';
    const cards=summary.arm?[
      [`${summary.baseline.name} · 窗口均值`,fmt(summary.baseline.mean),`${info.name} · ${summary.baseline.n}次运行`],
      [`${summary.arm.name} · 窗口均值`,fmt(summary.arm.mean),`${info.name} · ${summary.arm.n}次运行`],
      ['相对参照差异',pct(summary.relative),`${summary.pairedN?'配对差':'均值差'} ${fmt(summary.difference)} · n=${summary.pairedN||'未配对'}`],
      [`当前${info.name}`,fmt(observed[s.metric]),`sim_t=${fmt(observed.sim_t)} · ${run.label}`]
    ]:s.kind==='ensemble'?[['各种子均值的平均',fmt(summary.seedAverage),`${s.runs.length}次实际运行`],['跨种子样本标准差',fmt(summary.seedStd),'按各次窗口均值计算；不是置信区间'],[`当前${info.name}`,fmt(observed[s.metric]),run.label]]:[[info.name,fmt(observed[s.metric]),`当前 sim_t=${fmt(observed.sim_t)}`],['窗口均值',fmt(per?.mean),`${per?.n||0}个观测时点 · ${info.unit}`],['窗口首末变化',finite(per?.last)&&finite(per?.first)?fmt(per.last-per.first):'—','所选窗口末值 − 首值']];
    if(!summary.arm&&s.kind!=='ensemble'&&per?.n>=2&&!varyingFields(windowRows(run.observations,window),[s.metric]).length){
      cards.splice(1);
      cards[0][2]+=` · 所选窗口的${per.n}个有效观测值保持不变`;
    }
    [...document.querySelectorAll('.kpi-row article')].forEach((el,i)=>{el.hidden=!cards[i];el.style.display=cards[i]?'':'none';if(cards[i]){const html=`<div class="kpi-label">${esc(cards[i][0])}</div><div class="kpi-val"><b>${esc(cards[i][1])}</b></div><div class="kpi-foot">${esc(cards[i][2])}</div>`;if(el.innerHTML!==html)el.innerHTML=html;}});
    const [x0,y0,x1,y1]=s.region?.bounds||[];
    const bounds=frame?.space?.bounds||[];
    const distributionEntities=s.region?entities.filter(e=>finite(e.x)&&finite(e.y)&&e.x>=x0&&(x1===bounds[2]?e.x<=x1:e.x<x1)&&e.y>=y0&&(y1===bounds[3]?e.y<=y1:e.y<y1)):entities;
    const full=frame?.statistics?.distributions;
    const fields=full?Object.keys(full).filter(k=>full[k].quantiles):numericFields(entities).filter(k=>k!=='id');
    const cat=full?Object.keys(full).filter(k=>!full[k].quantiles):['state','group','type'].filter(k=>!(run.model_id==='NET106'&&k==='state')&&entities.some(e=>typeof e[k]==='string'||typeof e[k]==='boolean'));
    const coordinate=k=>['x','y','z'].includes(k.split('.').at(-1));
    const choices=[...fields.filter(k=>!coordinate(k)),...cat,...fields.filter(coordinate)];
    if(!choices.includes(s.distributionField))s.distributionField=['speed','arrived','exited','state','group'].find(k=>choices.includes(k))||choices[0]||'';
    options($('#distributionField'),choices.map(k=>[k,populationField(frame,k).title]),s.distributionField,'无主体属性');
    $('#distributionField').parentElement.hidden=!choices.length;
    if(frame?.population&&s.distributionField){
      const key=s.distributionField;
      const selected=s.region?s.queryRegion?.(frame,key,s.region.bounds):{distribution:full?.[key]};
      const stats=selected?.distribution;
      if(stats){
        const description=populationField(frame,key);
        if(stats.cdf)drawCdf($('#distributionChart'),stats,description.title,colorFor(s,run,s.selected));
        else drawBars($('#distributionChart'),Object.entries(stats.counts||{}).map(([name,count])=>({label:key==='group'?(frame.statistics?.groups?.find(g=>g.id===name)?.label||name):label(name),count})),colorFor(s,run,s.selected));
        $('#distributionChart').dataset.scope='full_population';
        put('#distributionTitle',description.title+(stats.cdf?'累计分布':'类别构成'));
        put('#distributionNote',(s.region?'选区全量 · ':'全量归档 · ')+stats.n.toLocaleString('zh-CN')+' 个有效主体'+(stats.missing?' · 缺失 '+stats.missing:'')+(stats.not_applicable?' · 其他组不适用 '+stats.not_applicable:'')+(stats.not_spatial?' · 无坐标 '+stats.not_spatial:'')+(stats.cdf_complete===false?' · '+stats.cdf.length+' 个概率点':''));
      }else{
        empty($('#distributionChart'),selected?.error||'正在读取全量统计…');
        put('#distributionNote',selected?.error?'查询失败，可重新选择区域':'');
      }
    }else if(entities.length&&s.distributionField){
      const key=s.distributionField, isNumeric=fields.includes(key), values=distributionEntities.map(e=>e[key]);
      const classified=['arrived','exited'].includes(key)&&values.every(v=>v===0||v===1||v===undefined);
      const n=values.filter(v=>isNumeric?finite(v):v!==undefined&&v!==null).length;
      if(isNumeric&&!classified)drawCdf($('#distributionChart'),values,label(key),colorFor(s,run,s.selected));
      else {
        const bins=classified?[0,1].map(v=>({label:v?(key==='arrived'?'已到达':'已离开'):(key==='arrived'?'未到达':'未离开'),count:values.filter(x=>x===v).length})):categories(distributionEntities,key).bins;
        drawBars($('#distributionChart'),bins,colorFor(s,run,s.selected));
      }
      put('#distributionTitle',label(key)+(isNumeric&&!classified?'累计分布':'类别构成'));
      put('#distributionNote',(s.region?'选区 · ':'')+n+' 个主体'+(n<distributionEntities.length?` / ${distributionEntities.length}`:'')+(isNumeric&&!classified?' · '+entityUnit(key):''));
    } else if (frame?.entities?.some(e=>!present(e))) {
      empty($('#distributionChart'),'当前没有在场行人');
      put('#distributionTitle','场内行人分布');
      put('#distributionNote','离场人数见累计疏散趋势');
    } else {
      const scope=windowRows(run.observations,summary.window);
      drawCdf($('#distributionChart'),scope.map(o=>o[s.metric]),info.name,colorFor(s,run,s.selected));
      put('#distributionTitle',info.name+'的观测分布');
      put('#distributionNote',`${per?.n||0} 个观测时点 · ${info.unit}`);
    }
    if(s.runs.length>1)renderComparison(s,summary);
    renderStructure(s,frame);
    globalThis.DAYAN_PROCESS_CHARTS?.render(run.observations,s.metric,s.time,run.model_id,run.manifest,clock,window,eventTimes);
    if(s._frameCache?.frames!==frames)s._frameCache={frames,ids:[...new Set(frames.flatMap(f=>(f.entities||[]).map(e=>String(e.id))))],traces:new Map()};
    const allIds=s._frameCache.ids;
    const displayed=allIds.slice(0,1500);if(s.entityId&&!displayed.includes(s.entityId)&&allIds.includes(s.entityId))displayed.push(s.entityId);
    options($('#entityChoices'),displayed.map(id=>[id,id]),s.entityId||'','');
    $('#entitySelect').disabled=!allIds.length&&!frame?.population?.count;
    if(document.activeElement!==$('#entitySelect'))$('#entitySelect').value=s.entityId||'';
    put('#entityCount',frame?.population?`${frame.population.count.toLocaleString('zh-CN')} 个主体 · 可按编号查询`:allIds.length?`${entities.length}个当前主体`:'仅汇总输出');
    const entity=entities.find(e=>String(e.id)===s.entityId);
    if(s.entityId&&!s._frameCache.traces.has(s.entityId))s._frameCache.traces.set(s.entityId,frames.map(f=>{const e=f.entities?.find(e=>String(e.id)===s.entityId&&present(e));return {...(e||{}),sim_t:f.sim_t};}));
    const archiveTrace=s._archiveEntityTrace?.stream===s.stream&&s._archiveEntityTrace?.id===s.entityId?s._archiveEntityTrace:null;
    const trace=archiveTrace?.trace||(frame?.population?[]:s._frameCache.traces.get(s.entityId)||[]);
    const numericAttributes=numericFields(trace).filter(k=>k!=='id'),attributes=[...numericAttributes.filter(k=>!['x','y'].includes(k)),...numericAttributes.filter(k=>['x','y'].includes(k))];
    if(!attributes.includes(s.entityField))s.entityField=attributes.includes('speed')?'speed':attributes[0]||'';
    options($('#entityMetric'),attributes.map(k=>[k,label(k)]),s.entityField,'无数值属性');$('#focusEntity').disabled=!entity||!finite(entity.x);
    $('#followEntity').disabled=!entity||!finite(entity.x);$('#followEntity').setAttribute('aria-pressed',String(Boolean(s.followEntity)));$('#followEntity').textContent=s.followEntity?'停止跟随':'跟随主体';
    if(entity){const values=Object.entries(entity).filter(([k,v])=>k!=='id'&&!(entity.type==='car'&&k==='state')&&v!==null&&typeof v!=='object').map(([k,v])=>`<span>${esc(label(k))} <b>${esc(finite(v)?fmt(v):label(String(v)))}</b></span>`);if(entity.type==='car'&&finite(entity.speed))values.push(`<span>运动状态 <b>${entity.speed===0?'停车':'行驶'}</b></span>`);$('#entitySummary').innerHTML=values.join('');
      drawLine($('#entityChart'),[{rows:trace}],s.entityField,s.time,[s.start,s.end],[],null,entityUnit(s.entityField),clock);}
    else{put('#entitySummary',s._entityLoading?'正在读取完整主体轨迹…':s.entityId?'该主体在当前帧不存在，轨迹不补造缺失值。':'输入主体编号或点击动画中的主体。');if(s.entityId&&s.entityField)drawLine($('#entityChart'),[{rows:trace}],s.entityField,s.time,[s.start,s.end]);else empty($('#entityChart'),frame?.population||allIds.length?'输入主体编号，观察它随时间的变化。':'模型没有输出个体轨迹。');}
    if(archiveTrace?.error)put('#entitySummary',archiveTrace.error);
    $('#entityChart').dataset.total=String(trace.length);
    $('#entityChart').dataset.scope=archiveTrace?.trace?'full_archive':'archived_frames';
    put('#trackAgent',s.entityId?`已选主体 ${s.entityId} · 查看详情 ↗`:'在场景中点击主体 · 或从列表选择 ↗');
    put('#insightSummary',summary.arm&&!finite(summary.difference)?'部分方案缺少该指标':summary.arm&&independent<2?'跨种子稳健性待验证':'');
    const comparability=s.payload?.comparability_note||s.payload?.coupling_note;if(comparability)put('#comparisonNote',comparability);
  }
  function bind(s,paint,notice) {
    $('#analysisWindow').addEventListener('change',e=>{s.windowMode=e.target.value;if(e.target.value==='custom'){s.customWindow={from:s.start,to:s.end};$('#analysisFrom').value=s.start;$('#analysisTo').value=s.end;}paint();});
    $('#applyWindow').addEventListener('click',()=>{const from=Number($('#analysisFrom').value),to=Number($('#analysisTo').value);if(!finite(from)||!finite(to)||from>to||from<s.start||to>s.end){notice('分析窗口须在本次运行范围内，且起点不晚于终点。');return;}s.customWindow={from,to};s.windowMode='custom';paint();});
    $('#distributionField').addEventListener('change',e=>{s.distributionField=e.target.value;paint();});
    $('#entitySelect').addEventListener('change',e=>s.chooseEntity(e.target.value.trim()));
    $('#entitySelect').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();e.target.blur();}});
    $('#entityMetric').addEventListener('change',e=>{s.entityField=e.target.value;paint();});
    $('#focusEntity').addEventListener('click',()=>{if(s.entityId)window.DAYAN3D?.focusEntity(s.entityId);});
    $('#followEntity').addEventListener('click',()=>{if(s.entityId)window.DAYAN3D?.followEntity(s.entityId,!s.followEntity);});
    document.addEventListener('dayan:camera-mode',e=>{s.followEntity=Boolean(e.detail.following);paint();});
    document.addEventListener('dayan:entity-selected',e=>{s.region=null;s.chooseEntity(String(e.detail.id));});
    for(const el of document.querySelectorAll('.analysis-canvas')){
      el.addEventListener('mousemove',e=>{const r=el.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top,hit=el._hits?.find(h=>x>=h.x&&x<=h.x+h.w&&y>=h.y&&y<=h.y+h.h);el.title=hit?.text||'';});
      el.addEventListener('click',e=>{
        const r=el.getBoundingClientRect(), x=e.clientX-r.left, y=e.clientY-r.top;
        const hit=el._hits?.find(h=>x>=h.x&&x<=h.x+h.w&&y>=h.y&&y<=h.y+h.h);
        if(hit?.region&&!document.body.dataset.liveSampling){
          s.setPlaying(false,false);
          s.region=s.region?.index===hit.index?null:hit;
          if(s.region&&hit.entities.length)window.DAYAN3D?.focusEntity(hit.entities[0].id);
          paint();
          window.DAYAN_LIVE?.choose(s,s.region?{region:hit.region}:null);
        } else if(finite(hit?.time)){
          s.seekChart(hit.time);
        } else if(el._timePlot){
          const p=el._timePlot;
          s.seekChart(p.from+Math.max(0,Math.min(1,(y-p.top)/(p.bottom-p.top)))*(p.to-p.from));
        } else if(el._plot){
          const p=el._plot;
          s.seekChart(p.t0+Math.max(0,Math.min(1,(x-p.x0)/(p.x1-p.x0)))*(p.t1-p.t0));
        }
      });
    }
    let scheduled=false;new ResizeObserver(()=>{if(!scheduled){scheduled=true;requestAnimationFrame(()=>{scheduled=false;paint();});}}).observe($('.workspace-grid'));
  }
  window.DAYAN_ANALYSIS = {finite,numericFields,mean,varyingFields,correlationFields,correlation,savedEvents,windowRows,label,populationField,metricInfo,interventionTime,resolvedWindow,summarize,histogram,categories,drawLine,drawBars,drawCdf,renderStructure,clearChart:empty,render,bind,fmt,esc,colorFor,canvas,extent};
})();

/* Replay and live plots derived from the currently selected run's observations. */
(() => {
  'use strict';
  const A=window.DAYAN_ANALYSIS, {canvas,extent,finite,fmt,label,numericFields}=A;
  const $=id=>document.getElementById(id);
  const cyan='#67e1d4', amber='#f4c282', ink='#abc7d6', grid='#2a4456';
  const sampled=(rows,count)=>rows.length<=count?rows:Array.from({length:count},(_,i)=>rows[Math.round(i*(rows.length-1)/(count-1))]);
  const fraction=(value,lo,hi)=>lo===hi?.5:(value-lo)/(hi-lo);
  let cache;

  function derive(rows,key,window) {
    const scope=window?A.windowRows(rows,window):rows;
    const readings=scope.filter(row=>finite(row.sim_t));
    const rate=readings.map((row,i)=>{
      const previous=readings[i-1],dt=row.sim_t-previous?.sim_t;
      const value=dt>0&&finite(row[key])&&finite(previous[key])?(row[key]-previous[key])/dt:null;
      return {sim_t:row.sim_t,rate:finite(value)?value:null};
    });
    const fields=numericFields(readings);
    const ordered=fields.includes(key)?[key,...fields.filter(field=>field!==key)]:fields;
    const domains=new Map(ordered.map(field=>[field,extent(readings.map(row=>row[field]).filter(finite))]));
    let horizontal,vertical,pairs=[];
    const varying=ordered.filter(field=>{const [lo,hi]=domains.get(field);return hi>lo;});
    if(varying.length>1){
      horizontal=varying[0];
      const candidates=varying.slice(1).map(field=>({field,...A.correlation(readings,horizontal,field)})).filter(r=>r.n>=3&&r.value!==null);
      vertical=(candidates.find(r=>Math.abs(r.value)<.999999)||candidates[0])?.field;
      if(vertical)pairs=readings.filter(row=>finite(row[horizontal])&&finite(row[vertical]));
    }
    return {readings,rate,validRate:rate.filter(row=>finite(row.rate)),fields:varying.slice(0,10),domains,horizontal,vertical,pairs};
  }

  function drawHeat(data,time,model,manifest,clock) {
    const el=$('metricHeatChart'), plot=canvas(el);
    if(!plot)return;
    const {ctx,w,h}=plot, {readings,fields,domains}=data;
    const left=Math.min(114,Math.max(65,w*.25)),right=w-13,top=10,bottom=h-28;
    const from=readings[0].sim_t,to=readings.at(-1).sim_t;
    const visible=sampled(readings,Math.max(2,Math.min(180,Math.floor((right-left)/2.5))));
    const x=t=>left+(right-left)*fraction(t,from,to),rowH=(bottom-top)/fields.length;
    fields.forEach((key,i)=>{
      const y=top+i*rowH,name=A.metricInfo(model,key,manifest).name,[lo,hi]=domains.get(key);
      ctx.fillStyle=ink;ctx.textAlign='right';ctx.fillText(name,left-7,y+rowH/2+4,left-12);
      for(let j=0;j<visible.length;j++){
        const row=visible[j],value=row[key],center=x(row.sim_t);
        const start=j?(x(visible[j-1].sim_t)+center)/2:left;
        const end=j<visible.length-1?(center+x(visible[j+1].sim_t))/2:right;
        const level=finite(value)?Math.max(0,Math.min(1,fraction(value,lo,hi))):null;
        ctx.fillStyle=level===null?'#162736':`hsl(${208-level*48} 64% ${25+level*44}%)`;
        const width=Math.max(0,end-start);
        ctx.fillRect(start,y,width>1.8?width-.7:width,rowH-2);
        if(width>0)el._hits.push({x:start,y,w:width,h:rowH,time:row.sim_t,
          text:`${name} ${fmt(value)} · ${clock} ${fmt(row.sim_t)}`});
      }
    });
    ctx.fillStyle=ink;ctx.textAlign='left';ctx.fillText(fmt(from),left,h-10);
    ctx.textAlign='right';ctx.fillText(`${clock} ${fmt(to)}`,right,h-10);
    if(time>=from&&time<=to){ctx.strokeStyle='#f7f5db';ctx.beginPath();ctx.moveTo(x(time),top-2);ctx.lineTo(x(time),bottom);ctx.stroke();}
    el.dataset.points=String(readings.length);el.dataset.fields=fields.join(',');
    el.setAttribute('aria-label',`${fields.length}项指标的分时热图，${readings.length}个观测时点。各行使用该指标的窗口范围。`);
  }

  function drawRelation(data,time,model,manifest) {
    const el=$('metricRelationChart'), plot=canvas(el);
    if(!plot)return;
    const {ctx,w,h}=plot,{pairs,horizontal,vertical}=data;
    const xInfo=A.metricInfo(model,horizontal,manifest),yInfo=A.metricInfo(model,vertical,manifest);
    const [x0,x1]=extent(pairs.map(row=>row[horizontal])),[y0,y1]=extent(pairs.map(row=>row[vertical]));
    const left=57,right=w-18,top=24,bottom=h-37;
    const x=value=>left+(right-left)*fraction(value,x0,x1), y=value=>bottom-(bottom-top)*fraction(value,y0,y1);
    ctx.fillStyle=ink;ctx.strokeStyle=grid;
    ctx.textAlign='left';ctx.fillText(`${yInfo.name} · ${yInfo.unit}`,left,13,w-left-8);
    for(const step of [0,.5,1]){
      const value=y0+step*(y1-y0),yy=y(value),xx=left+step*(right-left);
      ctx.textAlign='right';ctx.fillText(fmt(value),left-6,yy+3,left-9);
      ctx.beginPath();ctx.moveTo(left,yy);ctx.lineTo(right,yy);ctx.stroke();
      ctx.textAlign=step===1?'right':step===0?'left':'center';ctx.fillText(fmt(x0+step*(x1-x0)),xx,bottom+15);
    }
    ctx.textAlign='right';ctx.fillText(`${xInfo.name} · ${xInfo.unit}`,right,h-6,w-left);
    const point=(row,radius,color)=>{
      const xx=x(row[horizontal]),yy=y(row[vertical]);
      ctx.fillStyle=color;ctx.beginPath();ctx.arc(xx,yy,radius,0,Math.PI*2);ctx.fill();
      return {x:xx-5,y:yy-5,w:10,h:10,time:row.sim_t,
        text:`${xInfo.name} ${fmt(row[horizontal])} · ${yInfo.name} ${fmt(row[vertical])} · t ${fmt(row.sim_t)}`};
    };
    for(const row of sampled(pairs,800))el._hits.push(point(row,2.7,'#62d2c19c'));
    const current=pairs.findLast(row=>row.sim_t<=time+1e-9);
    if(current&&time>=pairs[0].sim_t&&time<=pairs.at(-1).sim_t)el._hits.unshift(point(current,5,amber));
    el.dataset.points=String(pairs.length);el.dataset.fields=[horizontal,vertical].join(',');
    el.setAttribute('aria-label',`${xInfo.name}与${yInfo.name}在同一时点的${pairs.length}对观测`);
    $('metricRelationCount').textContent=`${pairs.length} 对`;
  }

  function render(rows,key,time,model,manifest,clock='模型时间',window=null,events=[]) {
    const signature=JSON.stringify(window);
    if(cache?.rows!==rows||cache.key!==key||cache.signature!==signature)cache={rows,key,signature,data:derive(rows,key,window)};
    const data=cache.data, {readings,rate,validRate,fields,pairs}=data;
    const hasTime=readings.length>1&&readings[0].sim_t<readings.at(-1).sim_t;
    const rateEl=$('rateChart');
    $('ratePanel').hidden=!hasTime||!validRate.some(row=>row.rate!==0);
    $('metricHeatPanel').hidden=!hasTime||fields.length<2;
    $('metricRelationPanel').hidden=pairs.length<3;
    if(!$('ratePanel').hidden){
      const from=readings[0].sim_t,to=readings.at(-1).sim_t;
      const current=time>=from&&time<=to?rate.findLast(row=>row.sim_t<=time+1e-9):null;
      const info=A.metricInfo(model,key,manifest),unit=`${info.unit} / ${clock}`;
      $('rateValue').textContent=finite(current?.rate)?(current.rate>0?'+':'')+fmt(current.rate):'—';
      A.drawLine(rateEl,[{rows:rate,color:cyan}],'rate',current?time:null,[from,to],events,null,unit,clock);
      rateEl.dataset.points=String(validRate.length);
      rateEl.setAttribute('aria-label',`${info.name}相邻观测差除以实际时间差，${validRate.length}个有效区间，单位${unit}`);
      const p=rateEl._plot;
      if(p)for(const row of sampled(validRate,800)){
        const x=p.x0+(p.x1-p.x0)*fraction(row.sim_t,from,to);
        rateEl._hits.push({x:x-3,y:20,w:6,h:rateEl.clientHeight-46,time:row.sim_t,
          text:`${fmt(row.rate)} ${unit} · ${clock} ${fmt(row.sim_t)}`});
      }
    }
    if(!$('metricHeatPanel').hidden)drawHeat(data,time,model,manifest,clock);
    if(!$('metricRelationPanel').hidden)drawRelation(data,time,model,manifest);
  }

  window.DAYAN_PROCESS_CHARTS={render};
})();
