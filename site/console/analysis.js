/* Shared, deterministic analysis of the saved observations; no data generation. */
(() => {
  'use strict';
  const finite = x => typeof x === 'number' && Number.isFinite(x);
  const numericFields = rows => [...new Set(rows.flatMap(r => Object.keys(r || {})))].filter(k => k !== 'sim_t' && rows.some(r => finite(r[k])));
  const mean = xs => xs.length ? xs.reduce((s,x) => s+x,0)/xs.length : null;
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
  const names = {arrived_count:'累计到达',arrived_fraction:'到达比例',n:'主体数量',exit_x:'出口横坐标',exit_y:'出口纵坐标',flux:'交通通量',density:'车辆密度',n_cars:'车辆数',speed:'速度',I:'感染量 I',S:'易感量 S',R:'康复量 R',I_total:'感染总量',gini:'基尼系数',evacuated:'累计疏散',arrived:'累计到达',waiting:'等待人数',k:'人均资本',wealth:'财富',income:'收入',population:'人口',x:'横向位置',y:'纵向位置',state:'主体状态',type:'主体类型',group:'所属群体',age:'年龄',risk:'风险',information:'信息状态',infected:'感染状态',susceptible:'易感状态',recovered:'康复状态',moving:'移动',exited:'已离开',waiting_service:'等待服务',mean_speed:'平均速度',total:'总量'};
  const label = key => names[key] || key;
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
  function drawLine(element,series,metric,time,limits,events=[],window=null,unit='原模型单位',clock='模型时间 sim_t') {
    const c=canvas(element);if(!c)return;
    const {ctx,w,h}=c,all=series.flatMap(r=>r.rows.map(o=>o[metric]).filter(finite));
    if(!all.length){empty(element,'该指标没有可绘制的观测');return;}
    let [lo,hi]=extent(all);if(lo>=0)lo=0;if(lo===hi){hi=lo+Math.max(1,Math.abs(lo)*.1);}
    const p={l:57,r:19,t:23,b:33},pw=w-p.l-p.r,ph=h-p.t-p.b;
    const x=t=>p.l+(t-limits[0])/Math.max(1e-12,limits[1]-limits[0])*pw,y=v=>p.t+(hi-v)/(hi-lo)*ph;
    if(window&&window.mode!=='all'){ctx.fillStyle='#87a9c012';ctx.fillRect(x(window.from),p.t,Math.max(0,x(window.to)-x(window.from)),ph);}
    ctx.strokeStyle='#294553';ctx.lineWidth=1;ctx.fillStyle='#94afc0';
    for(let i=0;i<4;i++){const value=lo+(hi-lo)*i/3,yy=y(value);ctx.beginPath();ctx.moveTo(p.l,yy);ctx.lineTo(w-p.r,yy);ctx.stroke();ctx.textAlign='right';ctx.fillText(fmt(value),p.l-7,yy+4);}
    ctx.textAlign='left';ctx.fillText(unit,p.l,12);
    for(let i=0;i<=3;i++){const t=limits[0]+(limits[1]-limits[0])*i/3;ctx.textAlign=i===3?'right':i===0?'left':'center';ctx.fillText(fmt(t),x(t),h-16);}
    ctx.textAlign='right';ctx.fillText(clock,w-p.r,h-1);
    for(const t of [...new Set(events.filter(finite))]){if(t<limits[0]||t>limits[1])continue;ctx.setLineDash([3,3]);ctx.strokeStyle='#99b8c080';ctx.beginPath();ctx.moveTo(x(t),p.t);ctx.lineTo(x(t),h-p.b);ctx.stroke();ctx.setLineDash([]);}
    series.forEach((r,j)=>{ctx.strokeStyle=r.color||colors[j%colors.length];ctx.lineWidth=1.8;ctx.setLineDash(j%2?[5,3]:[]);ctx.beginPath();let pen=false;const stride=Math.max(1,Math.ceil(r.rows.length/1200));
      r.rows.forEach((o,i)=>{if(!finite(o[metric])){pen=false;return;}if(i%stride&&i!==r.rows.length-1)return;const xx=x(o.sim_t),yy=y(o[metric]);if(pen)ctx.lineTo(xx,yy);else ctx.moveTo(xx,yy);pen=true;});ctx.stroke();ctx.setLineDash([]);
      const row=r.rows[at(r.rows,time)];if(row&&finite(row[metric])){ctx.fillStyle=r.color||colors[j%colors.length];ctx.beginPath();ctx.arc(x(row.sim_t),y(row[metric]),3,0,Math.PI*2);ctx.fill();}
    });
    ctx.strokeStyle='#c6d8df85';ctx.setLineDash([3,3]);ctx.beginPath();ctx.moveTo(x(time),p.t);ctx.lineTo(x(time),h-p.b);ctx.stroke();ctx.setLineDash([]);
    element.dataset.kind='line';element._plot={x0:p.l,x1:w-p.r,t0:limits[0],t1:limits[1]};
    element.setAttribute('aria-label',`${label(metric)}时间序列，${series.length}条真实运行，当前模型时间${fmt(time)}，单位${unit}`);
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
  function renderComparison(s,summary) {
    const svg=$('#comparisonChart');if(!svg)return;const width=svg.clientWidth||300,items=(s.kind==='ensemble'?summary.perRun.map(r=>({name:r.run.label,mean:r.mean,n:1})):summary.groups).filter(g=>finite(g.mean));
    const height=Math.max(document.body.classList.contains('command-center')?70:166,items.length*33+35);svg.style.height=height+'px';svg.setAttribute('viewBox',`0 0 ${width} ${height}`);
    if(!items.length){svg.innerHTML=`<text x="16" y="60" fill="#a1b5c3" font-size="12">所选窗口内没有可比较的观测</text>`;return;}
    const lo=Math.min(0,...items.map(x=>x.mean)),hi=Math.max(0,...items.map(x=>x.mean)),span=hi-lo||1,left=Math.min(120,width*.35),right=68,pw=Math.max(40,width-left-right),x=v=>left+(v-lo)/span*pw;
    svg.innerHTML=items.map((g,i)=>{const y=18+i*33,b0=x(0),b1=x(g.mean);return `<text x="4" y="${y+14}" fill="#b1c9d6" font-size="11">${esc(g.name.length>13?g.name.slice(0,12)+'…':g.name)}</text><rect x="${Math.min(b0,b1)}" y="${y}" width="${Math.max(.7,Math.abs(b1-b0))}" height="20" rx="2" fill="${colors[i%colors.length]}"/><text x="${width-3}" y="${y+14}" text-anchor="end" fill="#e6f2f7" font-size="11">${esc(fmt(g.mean))}</text><title>${esc(g.name)}：${g.mean}；${g.n}次运行均值</title>`;}).join('')+`<line x1="${x(0)}" x2="${x(0)}" y1="13" y2="${items.length*33+7}" stroke="#6c8797"/><text x="${left}" y="${height-6}" fill="#94afc0" font-size="11">${esc(label(s.metric))} · 窗口均值</text>`;
    svg.setAttribute('aria-label',items.map(g=>`${g.name}窗口均值${g.mean}，${g.n}次运行`).join('；'));
    put('#comparisonTitle',s.kind==='ensemble'?'不同种子的结果':s.runs.length>1?'方案差异有多大':'这段过程的结果');
    put('#effectLabel',summary.arm?'相对基线差异':'窗口均值');
    put('#effectNumber',summary.arm?pct(summary.relative):fmt(summary.perRun[s.selected]?.mean));
    put('#effectSub',summary.arm?`差值 ${fmt(summary.difference)}${summary.pairedN?' · 配对种子 '+summary.pairedN:''}`:`${summary.perRun[s.selected]?.n||0}个观测时点`);
    put('#comparisonSample',summary.pairedN?`配对 n=${summary.pairedN}`:`${s.runs.length}次运行`);
    put('#comparisonNote',summary.arm?'先对每次运行计算窗口均值，再按方案汇总；不将时间点当作独立实验。':'仅描述本次运行；重复种子实验后才能判断跨运行稳定性。');
  }
  let roadRaster;
  function renderStructure(s,frame) {
    const el=$('#structureChart'),frames=s.stream?.frames||[],entities=frame?.entities||[],road=frame?.facilities?.find(f=>f.type==='road'&&finite(f.length));
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
    const spatial=entities.filter(e=>finite(e.x)&&finite(e.y));
    if(spatial.length){const c=canvas(el);if(!c)return;const {ctx,w,h}=c,p={l:36,r:15,t:20,b:34},shown=spatial.slice(0,3000),xs=spatial.map(e=>e.x),ys=spatial.map(e=>e.y),bx=extent(xs),by=extent(ys),loX=bx[0],hiX=bx[1],loY=by[0],hiY=by[1];ctx.fillStyle='#182f3e';ctx.fillRect(p.l,p.t,w-p.l-p.r,h-p.t-p.b);
      const x=v=>p.l+(v-loX)/Math.max(1e-12,hiX-loX)*(w-p.l-p.r),y=v=>h-p.b-(v-loY)/Math.max(1e-12,hiY-loY)*(h-p.t-p.b);
      shown.forEach(e=>{ctx.fillStyle=e.id===s.entityId?'#eebb79':colors[0];ctx.beginPath();ctx.arc(x(e.x),y(e.y),e.id===s.entityId?5:2.5,0,Math.PI*2);ctx.fill();el._hits.push({x:x(e.x)-6,y:y(e.y)-6,w:12,h:12,text:`${e.id} · x=${fmt(e.x)}, y=${fmt(e.y)}`,entityId:e.id});});
      ctx.fillStyle='#a1b5c3';ctx.textAlign='left';ctx.fillText(fmt(loX),p.l,h-17);ctx.textAlign='right';ctx.fillText(fmt(hiX),w-p.r,h-17);ctx.fillText('模型 x / y 坐标',w-p.r,h-1);put('#structureTitle','主体分布在哪里');put('#structureSubtitle',`sim_t=${fmt(frame.sim_t)}`);put('#structureNote',`实际模型位置，点击主体可查看轨迹。${shown.length<spatial.length?'视图显示前3000/'+spatial.length+'个主体。':''}`);el.dataset.kind='spatial';return;}
    const rows=s.runs[s.selected]?.observations||[],fields=numericFields(rows).filter(k=>k!==s.metric&&new Set(rows.map(o=>o[k])).size>1).slice(0,3);
    put('#structureTitle','其他指标怎样变化');put('#structureSubtitle','各图独立量纲');
    if(!fields.length){empty(el,entities.length?'当前主体没有可绘制的位置；可在右侧查看属性轨迹。':'模型没有主体位置或其他变化指标，不生成地图。');put('#structureNote','仅使用模型实际提供的数据。');return;}
    const c=canvas(el);if(!c)return;const {ctx,w,h}=c,part=(h-16)/fields.length;
    fields.forEach((key,j)=>{const vals=rows.map(o=>o[key]).filter(finite),domain=extent(vals),lo=domain[0],hi=domain[1],top=j*part+18;ctx.fillStyle='#b6cdda';ctx.textAlign='left';ctx.fillText(label(key),15,top);ctx.textAlign='right';ctx.fillText(`${fmt(lo)} — ${fmt(hi)}`,w-15,top);ctx.strokeStyle=colors[(j+1)%colors.length];ctx.lineWidth=1.5;ctx.beginPath();let pen=false;rows.forEach(o=>{if(!finite(o[key])){pen=false;return;}const xx=15+(o.sim_t-s.start)/Math.max(1e-12,s.end-s.start)*(w-30),yy=top+9+(1-(o[key]-lo)/Math.max(1e-12,hi-lo))*(part-30);if(pen)ctx.lineTo(xx,yy);else ctx.moveTo(xx,yy);pen=true;});ctx.stroke();});
    el.dataset.kind='small-multiples';put('#structureNote','当前模型没有主体位置；显示其他真实观测的独立尺度趋势，不生成虚构地图。');
  }
  function render(s) {
    const run=s.runs[s.selected],frames=s.stream?.frames||[],frame=frames[at(frames,s.time)],entities=frame?.entities||[],summary=summarize(s);s.viewAnalysis=summary;
    const info=metricInfo(run?.model_id,s.metric,run?.manifest),observed=run?.observations?.[at(run.observations,s.time)]||{};
    if(!run){for(const id of ['#obsChart','#distributionChart','#structureChart','#entityChart'])empty($(id),'开始研究后显示真实计算结果');document.querySelectorAll('.kpi-row article').forEach(e=>{e.hidden=true;e.style.display='none';});$('#comparisonChart').innerHTML='';put('#sampleNote','');put('#effectNumber','—');put('#insightSummary','');return;}
    const eventTimes=s.runs.flatMap(r=>(r.manifest?.interventions||[]).filter(i=>i.applied).map(i=>i.actual_t));
    const clock=unitLabel(frame?.space?.time_unit||run.manifest?.actual?.time_unit)||'模型时间 sim_t';
    const entityUnit=key=>{
      if(['x','y'].includes(key))return unitLabel(frame?.space?.unit)||'模型空间单位';
      if(key==='speed'&&frame?.space?.unit&&frame?.space?.time_unit&&run.model_id!=='NET106')return unitLabel(frame.space.unit)+'/'+unitLabel(frame.space.time_unit);
      return metricInfo(run.model_id,key).unit;
    };
    drawLine($('#obsChart'),s.runs.map((r,i)=>({rows:r.observations,color:colorFor(s,r,i)})),s.metric,s.time,[s.start,s.end],eventTimes,summary.window,info.unit,clock);
    put('#metricDescription',`${info.name} · ${info.unit}${info.definition?' · '+info.definition:''}`);
    const window=summary.window,per=summary.perRun[s.selected];put('#analysisWindowLabel',`${fmt(window.from)} ${window.exclusive?'<':'≤'} sim_t ≤ ${fmt(window.to)} · 当前方案 ${per?.n||0} 个观测时点`);
    const independent=s.kind==='experiment'?summary.pairedN:s.kind==='ensemble'?s.runs.length:1;
    put('#sampleNote',independent>1?`${independent}个${s.kind==='experiment'?'配对':''}种子；差异仅在模型内解释`:'单个种子，尚未评估跨种子稳健性');
    const post=$('#analysisWindow option[value="post"]');post.disabled=interventionTime(s)===null;$('#analysisWindow').value=s.windowMode||'all';
    $('#customWindowInputs').hidden=s.windowMode!=='custom';
    const cards=summary.arm?[
      [`${summary.baseline.name} · 窗口均值`,fmt(summary.baseline.mean),`${info.name} · ${summary.baseline.n}次运行`],
      [`${summary.arm.name} · 窗口均值`,fmt(summary.arm.mean),`${info.name} · ${summary.arm.n}次运行`],
      ['相对参照差异',pct(summary.relative),`${summary.pairedN?'配对差':'均值差'} ${fmt(summary.difference)} · n=${summary.pairedN||'未配对'}`],
      [`当前${info.name}`,fmt(observed[s.metric]),`sim_t=${fmt(observed.sim_t)} · ${run.label}`]
    ]:s.kind==='ensemble'?[['各种子均值的平均',fmt(summary.seedAverage),`${s.runs.length}次实际运行`],['跨种子样本标准差',fmt(summary.seedStd),'按各次窗口均值计算；不是置信区间'],[`当前${info.name}`,fmt(observed[s.metric]),run.label]]:[[info.name,fmt(observed[s.metric]),`当前 sim_t=${fmt(observed.sim_t)}`],['窗口均值',fmt(per?.mean),`${per?.n||0}个观测时点 · ${info.unit}`],['窗口首末变化',finite(per?.last)&&finite(per?.first)?fmt(per.last-per.first):'—','所选窗口末值 − 首值']];
    [...document.querySelectorAll('.kpi-row article')].forEach((el,i)=>{el.hidden=!cards[i];el.style.display=cards[i]?'':'none';if(cards[i]){const html=`<div class="kpi-label">${esc(cards[i][0])}</div><div class="kpi-val"><b>${esc(cards[i][1])}</b></div><div class="kpi-foot">${esc(cards[i][2])}</div>`;if(el.innerHTML!==html)el.innerHTML=html;}});
    const fields=numericFields(entities).filter(k=>k!=='id'),cat=['state','group','type'].filter(k=>!(run.model_id==='NET106'&&k==='state')&&entities.some(e=>typeof e[k]==='string'||typeof e[k]==='boolean'));
    const choices=[...fields.filter(k=>!['x','y'].includes(k)),...cat,...fields.filter(k=>['x','y'].includes(k))];
    if(!choices.includes(s.distributionField))s.distributionField=['speed','arrived','exited','state'].find(k=>choices.includes(k))||choices[0]||'';
    options($('#distributionField'),choices.map(k=>[k,label(k)]),s.distributionField,'无主体属性');
    if(entities.length&&s.distributionField){const numeric=fields.includes(s.distributionField),dist=numeric?histogram(entities,s.distributionField):categories(entities,s.distributionField),binary=['arrived','exited'].includes(s.distributionField)&&dist.bins.every(b=>['0','1'].includes(b.label));if(binary)dist.bins=dist.bins.map(b=>({...b,color:b.label==='1'?'#eebb79':'#51decc',label:(s.distributionField==='arrived'?(b.label==='1'?'已到达':'未到达'):(b.label==='1'?'已离开':'未离开'))}));drawBars($('#distributionChart'),dist.bins,colorFor(s,run,s.selected));put('#distributionTitle',binary?(s.distributionField==='arrived'?'到达状态构成':'离开状态构成'):`${label(s.distributionField)}如何分布`);put('#distributionNote',`${run.label} · sim_t=${fmt(frame.sim_t)} · ${dist.n}个有效主体${dist.missing?'，另有'+dist.missing+'个缺失/非数值':''}${numeric&&!binary?' · 属性单位 '+entityUnit(s.distributionField):''}${numeric&&dist.bins.length>1&&dist.bins[0].from!==dist.bins[0].to?' · 等宽分箱，区间左闭右开，末箱含最大值':''}`);}
    else{const metrics=numericFields(run.observations).filter(k=>k!==s.metric).slice(0,6),bins=metrics.filter(k=>finite(observed[k])).map(k=>({label:label(k),count:observed[k]}));
      const scaled=bins.map(b=>{const key=metrics.find(k=>label(k)===b.label),values=run.observations.map(o=>o[key]).filter(finite),peak=values.reduce((v,x)=>Math.max(v,Math.abs(x)),0);return {label:b.label,count:peak?100*Math.abs(b.count)/peak:0};});
      drawBars($('#distributionChart'),scaled,colorFor(s,run,s.selected),'各自绝对峰值占比 %');put('#distributionTitle','汇总指标当前强度');put('#distributionNote',(bins.map(b=>b.label+'='+fmt(b.count)).join('；')||'无额外数值')+' · 各自绝对峰值归一；无主体状态，不是个体分布');}
    renderComparison(s,summary);renderStructure(s,frame);
    if(s._frameCache?.frames!==frames)s._frameCache={frames,ids:[...new Set(frames.flatMap(f=>(f.entities||[]).map(e=>String(e.id))))],traces:new Map()};
    const allIds=s._frameCache.ids;
    const displayed=allIds.slice(0,1500);if(s.entityId&&!displayed.includes(s.entityId)&&allIds.includes(s.entityId))displayed.push(s.entityId);
    options($('#entitySelect'),allIds.length?[['','选择主体'],...displayed.map(id=>[id,id])]:[],s.entityId||'','无实体轨迹');
    put('#entityCount',allIds.length?`${entities.length}个当前主体${allIds.length>1500?' · 列表显示前1500':''}`:'仅汇总输出');
    const entity=entities.find(e=>String(e.id)===s.entityId);
    if(s.entityId&&!s._frameCache.traces.has(s.entityId))s._frameCache.traces.set(s.entityId,frames.map(f=>{const e=f.entities?.find(e=>String(e.id)===s.entityId);return {...(e||{}),sim_t:f.sim_t};}));
    const trace=s._frameCache.traces.get(s.entityId)||[];
    const numericAttributes=numericFields(trace),attributes=[...numericAttributes.filter(k=>!['x','y'].includes(k)),...numericAttributes.filter(k=>['x','y'].includes(k))];
    if(!attributes.includes(s.entityField))s.entityField=attributes.includes('speed')?'speed':attributes[0]||'';
    options($('#entityMetric'),attributes.map(k=>[k,label(k)]),s.entityField,'无数值属性');$('#focusEntity').disabled=!entity||!finite(entity.x);
    $('#followEntity').disabled=!entity||!finite(entity.x);$('#followEntity').setAttribute('aria-pressed',String(Boolean(s.followEntity)));$('#followEntity').textContent=s.followEntity?'停止跟随':'跟随主体';
    if(entity){const values=Object.entries(entity).filter(([k,v])=>k!=='id'&&!(entity.type==='car'&&k==='state')&&v!==null&&typeof v!=='object').map(([k,v])=>`<span>${esc(label(k))} <b>${esc(finite(v)?fmt(v):label(String(v)))}</b></span>`);if(entity.type==='car'&&finite(entity.speed))values.push(`<span>运动状态 <b>${entity.speed===0?'停车':'行驶'}</b></span>`);$('#entitySummary').innerHTML=values.join('');
      drawLine($('#entityChart'),[{rows:trace}],s.entityField,s.time,[s.start,s.end],[],null,entityUnit(s.entityField),clock);}
    else{put('#entitySummary',s.entityId?'该主体在当前帧不存在，轨迹不补造缺失值。':'点击动画中的主体或在列表中选择，查看实际状态与轨迹。');if(s.entityId&&s.entityField)drawLine($('#entityChart'),[{rows:trace}],s.entityField,s.time,[s.start,s.end]);else empty($('#entityChart'),allIds.length?'选择一个主体，观察它随时间的变化。':'模型没有输出个体轨迹。');}
    put('#trackAgent',s.entityId?`已选主体 ${s.entityId} · 查看详情 ↗`:'在场景中点击主体 · 或从列表选择 ↗');
    put('#insightSummary',summary.arm&&!finite(summary.difference)?'所选指标在部分方案中缺失，尚不能直接比较。':summary.arm?`在当前窗口，${summary.arm.name}的${info.name}均值${summary.difference<0?'低于':summary.difference>0?'高于':'等于'}${summary.baseline.name}。${independent>1?'已按种子配对比较。':'当前仅有单个配对种子，不能据此判断稳健性。'}`:(s.kind==='ensemble'?`这里比较${s.runs.length}个种子的实际结果；标准差描述各次窗口均值的离散程度。`:'图表描述当前保存的运行；更改分析窗口仅重新统计已有结果，不会重跑模型。'));
    const comparability=s.payload?.comparability_note||s.payload?.coupling_note;if(comparability)put('#comparisonNote',comparability);
  }
  function bind(s,paint,notice) {
    $('#analysisWindow').addEventListener('change',e=>{s.windowMode=e.target.value;if(e.target.value==='custom'){s.customWindow={from:s.start,to:s.end};$('#analysisFrom').value=s.start;$('#analysisTo').value=s.end;}paint();});
    $('#applyWindow').addEventListener('click',()=>{const from=Number($('#analysisFrom').value),to=Number($('#analysisTo').value);if(!finite(from)||!finite(to)||from>to||from<s.start||to>s.end){notice('分析窗口须在本次运行范围内，且起点不晚于终点。');return;}s.customWindow={from,to};s.windowMode='custom';paint();});
    $('#distributionField').addEventListener('change',e=>{s.distributionField=e.target.value;paint();});
    $('#entitySelect').addEventListener('change',e=>{s.entityId=e.target.value;s.entityField='';window.DAYAN3D?.selectEntity(s.entityId);paint();});
    $('#entityMetric').addEventListener('change',e=>{s.entityField=e.target.value;paint();});
    $('#focusEntity').addEventListener('click',()=>{if(s.entityId)window.DAYAN3D?.focusEntity(s.entityId);});
    $('#followEntity').addEventListener('click',()=>{if(s.entityId)window.DAYAN3D?.followEntity(s.entityId,!s.followEntity);});
    document.addEventListener('dayan:camera-mode',e=>{s.followEntity=Boolean(e.detail.following);paint();});
    document.addEventListener('dayan:entity-selected',e=>{s.entityId=String(e.detail.id);s.entityField='';paint();});
    for(const el of document.querySelectorAll('.analysis-canvas')){
      el.addEventListener('mousemove',e=>{const r=el.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top,hit=el._hits?.find(h=>x>=h.x&&x<=h.x+h.w&&y>=h.y&&y<=h.y+h.h);el.title=hit?.text||'';});
      el.addEventListener('click',e=>{const r=el.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top,hit=el._hits?.find(h=>x>=h.x&&x<=h.x+h.w&&y>=h.y&&y<=h.y+h.h);if(hit?.entityId){s.entityId=String(hit.entityId);window.DAYAN3D?.selectEntity(s.entityId);paint();}else if(el._timePlot){const p=el._timePlot;s.setPlaying(false);s.seek(p.from+Math.max(0,Math.min(1,(y-p.top)/(p.bottom-p.top)))*(p.to-p.from));}else if(el._plot){const p=el._plot;s.setPlaying(false);s.seek(p.t0+Math.max(0,Math.min(1,(x-p.x0)/(p.x1-p.x0)))*(p.t1-p.t0));}});
    }
    let scheduled=false;new ResizeObserver(()=>{if(!scheduled){scheduled=true;requestAnimationFrame(()=>{scheduled=false;paint();});}}).observe($('.workspace-grid'));
  }
  window.DAYAN_ANALYSIS = {finite,numericFields,mean,correlation,savedEvents,windowRows,label,metricInfo,interventionTime,resolvedWindow,summarize,histogram,categories,drawLine,drawBars,render,bind,fmt,esc,colorFor};
})();
