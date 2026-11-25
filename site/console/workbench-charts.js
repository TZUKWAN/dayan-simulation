/* Chart inputs are explicit arrays from observed runs, frames, or validation artifacts. */
(() => {
  'use strict';
  const colors = ['#6ee0dd','#b6a5ff','#f4c783','#62aeee','#df92bb','#b5dc80','#8fd3f8','#e79880'];
  const {esc,empty} = window.DAYAN_WORKBENCH;
  const finite = Number.isFinite;
  const nfmt = x => !finite(x) ? '—' : Number(x.toPrecision(5)).toLocaleString('zh-CN',{maximumFractionDigits:8});
  const range = values => values.length ? [values.reduce((a,v)=>Math.min(a,v),Infinity),values.reduce((a,v)=>Math.max(a,v),-Infinity)] : [0,1];
  const mean = a => a.length ? a.reduce((sum,v)=>sum+v,0)/a.length : null;
  const quantile = (sorted,q) => {
    if(!sorted.length) return null;
    const k=(sorted.length-1)*q,i=Math.floor(k);
    return sorted[i]+(sorted[Math.ceil(k)]-sorted[i])*(k-i);
  };
  function download(name, value, type) {
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([value],{type}));
    link.download = name;
    link.click();
    setTimeout(()=>URL.revokeObjectURL(link.href),1200);
  }
  function csv(name, rows) {
    const cell = value => {
      let s = String(value ?? '');
      if (typeof value !== 'number' && /^[=+@\-\t\r]/.test(s)) s = "'"+s;
      return '"'+s.replaceAll('"','""')+'"';
    };
    download(name,'\uFEFF'+rows.map(row=>row.map(cell).join(',')).join('\r\n'),'text/csv;charset=utf-8');
  }
  function domain(values, fixed) {
    const [lo,hi]=fixed || range(values);
    return hi > lo ? [lo,hi] : [lo-Math.max(Math.abs(lo)*.08,.5),hi+Math.max(Math.abs(hi)*.08,.5)];
  }
  function compact(values, limit) {
    if (values.length<=limit) return values;
    const stride = Math.ceil(values.length/limit);
    return values.filter((p,i)=>i%stride===0||i===values.length-1||!finite(p[1])||!finite(values[i-1]?.[1]));
  }
  function path(points,x,y) {
    let connected=false;
    return points.map(p=>{
      if(!finite(p[0])||!finite(p[1])){connected=false;return '';}
      const command=connected?'L':'M'; connected=true;
      return command+x(p[0]).toFixed(2)+' '+y(p[1]).toFixed(2);
    }).join(' ');
  }
  const textAttr = 'font-family="system-ui,sans-serif" font-size="12" fill="#b7cbe0"';
  const disabledSeries = new WeakMap();
  function plot(host, spec) {
    if(!host)return;
    const series = spec.series || [];
    const defined = series.flatMap(trace=>trace.points).filter(p=>finite(p[0])&&finite(p[1]));
    if(!defined.length) {host.innerHTML=empty(spec.empty || '此选择没有可绘制的有限观测。');return;}
    const yValues=defined.map(p=>p[1]);
    for (const trace of series) for (const band of trace.band || []) if(finite(band[1])&&finite(band[2])) yValues.push(band[1],band[2]);
    const xValues=defined.map(p=>p[0]);
    for(const trace of series) if(trace.kind==='bars'){
      const half=trace.barHalfWidth||.36;
      for(const p of trace.points) if(finite(p[0])) xValues.push(p[0]-half,p[0]+half);
    }
    const [loX,hiX]=domain(xValues,spec.xRange);
    const [loY,hiY]=domain(spec.zero ? [...yValues,0] : yValues,spec.yRange);
    const w=Math.max(320,Math.min(1440,host.clientWidth-22||650));
    const h=spec.height||260,L=68,R=w-18,T=25,B=h-48;
    const x=v=>L+(v-loX)/(hiX-loX)*(R-L),y=v=>B-(v-loY)/(hiY-loY)*(B-T);
    const xTicks=spec.xTicks || Array.from({length:6},(_,i)=>[loX+i*(hiX-loX)/5,nfmt(loX+i*(hiX-loX)/5)]);
    const yTicks=Array.from({length:5},(_,i)=>loY+i*(hiY-loY)/4);
    const axes=yTicks.map(v=>`<line x1="${L}" y1="${y(v)}" x2="${R}" y2="${y(v)}" stroke="#2b4159"/><text x="${L-9}" y="${y(v)+4}" text-anchor="end" ${textAttr}>${esc(nfmt(v))}</text>`).join('')
      +xTicks.map(([v,label])=>`<text x="${x(v)}" y="${B+18}" text-anchor="middle" ${textAttr}>${esc(label)}</text>`).join('');
    const zones=(spec.zones||[]).filter(z=>finite(z.from)&&finite(z.to)&&z.to>=loX&&z.from<=hiX).map(z=>{
      const left=x(Math.max(loX,z.from)),right=x(Math.min(hiX,z.to));
      return `<rect x="${left}" y="${T}" width="${Math.max(0,right-left)}" height="${B-T}" fill="${esc(z.color)}" opacity=".15"><title>${esc(z.label)}</title></rect>`;
    }).join('');
    const references=(spec.events||[]).filter(e=>finite(e.x)&&e.x>=loX&&e.x<=hiX).slice(0,25).map(e=>`<line x1="${x(e.x)}" x2="${x(e.x)}" y1="${T}" y2="${B}" stroke="#f4c783" stroke-dasharray="3 5"><title>${esc(e.label)} · ${esc(nfmt(e.x))}</title></line>`).join('');
    const muted=disabledSeries.get(host)||new Set();
    disabledSeries.set(host,muted);
    const markers=series.map((trace,i)=>{
      const color=trace.color || colors[i%colors.length], marks=compact(trace.points,1100);
      const tip=p=>esc(`${trace.label} · ${p[2] || nfmt(p[0])} · ${nfmt(p[1])} ${spec.yUnit||''}`);
      let shape='';
      if(trace.band?.length) {
        const above=trace.band.map(p=>[p[0],p[2]]),below=trace.band.map(p=>[p[0],p[1]]).reverse();
        shape+=`<path d="${path(above,x,y)} ${path(below,x,y).replace(/^M/,'L')} Z" fill="${color}" opacity=".16"/>`;
      }
      if (trace.kind==='bars') {
        const half=trace.barHalfWidth||.36;
        shape+=marks.filter(p=>finite(p[0])&&finite(p[1])).map(p=>`<rect x="${x(p[0]-half)}" y="${Math.min(y(trace.base??0),y(p[1]))}" width="${Math.max(1,x(p[0]+half)-x(p[0]-half))}" height="${Math.abs(y(trace.base??0)-y(p[1]))}" fill="${color}" opacity=".76"><title>${tip(p)}</title></rect>`).join('');
      } else if (trace.kind==='scatter') {
        shape+=marks.filter(p=>finite(p[0])&&finite(p[1])).map(p=>`<circle cx="${x(p[0])}" cy="${y(p[1])}" r="3.1" fill="${color}" opacity=".8"><title>${tip(p)}</title></circle>`).join('');
      } else if (trace.kind==='box') {
        shape+=marks.map(p=>{
          const [value,med,detail,lo,lower,upper,hi]=p,xx=x(value);
          return `<g><title>${tip(p)} · 最小 ${nfmt(lo)} · Q1 ${nfmt(lower)} · Q3 ${nfmt(upper)} · 最大 ${nfmt(hi)}</title><path d="M${xx} ${y(lo)}V${y(hi)} M${xx-6} ${y(lo)}h12 M${xx-6} ${y(hi)}h12" stroke="${color}"/><rect x="${xx-12}" y="${y(upper)}" width="24" height="${Math.max(1,y(lower)-y(upper))}" fill="#263d56" stroke="${color}"/><path d="M${xx-12} ${y(med)}h24" stroke="${color}" stroke-width="2"/></g>`;
        }).join('');
      } else {
        const line=path(marks,x,y);
        if(trace.kind==='area' && line && marks.every(p=>finite(p[1]))) {
          const lower=trace.lower ? marks.map(p=>[p[0],p[3]]).reverse() : [[marks.at(-1)[0],trace.base??0],[marks[0][0],trace.base??0]];
          shape+=`<path d="${line} ${path(lower,x,y).replace(/^M/,'L')} Z" fill="${color}" opacity=".35"/>`;
        }
        shape+=`<path d="${line}" fill="none" stroke="${color}" stroke-width="1.85" vector-effect="non-scaling-stroke"${trace.dashed?' stroke-dasharray="5 4"':''}/>`;
        if (marks.length===1) shape+=`<circle cx="${x(marks[0][0])}" cy="${y(marks[0][1])}" r="3" fill="${color}"><title>${tip(marks[0])}</title></circle>`;
      }
      return `<g data-chart-series="${i}"${muted.has(trace.label)?' display="none"':''}>${shape}</g>`;
    }).join('');
    const legends=series.map((trace,i)=>`<button data-chart-legend="${i}" aria-pressed="${!muted.has(trace.label)}" title="切换 ${esc(trace.label)} 曲线"><i style="background:${trace.color||colors[i%colors.length]}"></i>${esc(trace.label)}</button>`).join('');
    host.innerHTML=`<div class="plot-stage"><svg tabindex="0" ${spec.onWindow?'data-brush-chart':''} viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="${esc(spec.title)}" xmlns="http://www.w3.org/2000/svg">
      <title>${esc(spec.title)}</title><rect width="${w}" height="${h}" rx="6" fill="#101b2b"/>${zones}${axes}${references}${markers}
      <path d="M${L} ${T}V${B}H${R}" stroke="#627b93" fill="none"/>
      <text x="${L}" y="15" ${textAttr}>${esc(spec.yUnit||'')}</text><text x="${(R+L)/2}" y="${h-8}" text-anchor="middle" ${textAttr}>${esc(spec.xUnit||'')}</text>
      <line data-chart-cursor display="none" y1="${T}" y2="${B}" stroke="#f8fdff" stroke-dasharray="2 4" pointer-events="none"/>
      <g data-chart-points pointer-events="none"></g>
      <rect data-chart-brush display="none" y="${T}" height="${B-T}" fill="#a99aef33" stroke="#bdadff" pointer-events="none"/>
      </svg><div class="chart-tooltip" aria-hidden="true" hidden></div></div><div class="chart-legend">${legends}</div><output class="chart-readout" aria-live="off">移至曲线或按方向键查看观测。</output>${spec.note?`<p class="chart-method">${esc(spec.note)}</p>`:''}`;
    const svg=host.querySelector('svg'), cursor=host.querySelector('[data-chart-cursor]'), info=host.querySelector('output'), points=host.querySelector('[data-chart-points]');
    const tooltip=host.querySelector('.chart-tooltip'), brush=host.querySelector('[data-chart-brush]');
    const xs=[...new Set(defined.map(p=>p[0]))].sort((a,b)=>a-b);
    const lookup=series.map(trace=>new Map(trace.points.filter(p=>finite(p[1])).map(p=>[p[0],p])));
    let selected = 0, drag;
    const nearest = raw => {
      let a=0,b=xs.length-1;
      while(a<b) {const m=(a+b)>>1;if(xs[m]<raw)a=m+1;else b=m;}
      if(a>0 && Math.abs(raw-xs[a-1])<Math.abs(raw-xs[a]))a--;
      return a;
    };
    const seek = (raw,broadcast = true) => {
      selected=nearest(raw);
      const value=xs[selected];
      cursor.setAttribute('x1',x(value));cursor.setAttribute('x2',x(value));cursor.removeAttribute('display');
      const dots=[];
      const details=series.flatMap((trace,i)=>{
        if(muted.has(trace.label))return [];
        const p=lookup[i].get(value);
        const reading=!p?'—':trace.band?.find(r=>r[0]===value)?.slice(1).map(nfmt).join('–');
        if(p&&(!trace.kind||trace.kind==='area'||trace.kind==='scatter')) dots.push(`<circle cx="${x(value)}" cy="${y(p[1])}" r="3.2" fill="${trace.color||colors[i%colors.length]}" stroke="#101b2b"/>`);
        return `${trace.label} ${nfmt(p?.[1])}${reading&&reading!=='—'?' ['+reading+']':''}${p?.[2]?' · '+p[2]:''}`;
      });
      points.innerHTML=dots.join('');
      const timestamp=`${nfmt(value)} ${spec.xUnit||''}`;
      info.textContent=[timestamp,...details].join('  |  ');
      if(!tooltip.hidden)tooltip.innerHTML=`<b>${esc(timestamp)}</b>${details.slice(0,8).map(line=>`<span>${esc(line)}</span>`).join('')}`;
      if(broadcast)spec.onHover?.(value);
    };
    const atPointer=e=>new DOMPoint(e.clientX,e.clientY).matrixTransform(svg.getScreenCTM().inverse());
    const fromX=xx=>loX+(Math.max(L,Math.min(R,xx))-L)/(R-L)*(hiX-loX);
    svg.addEventListener('pointerdown',e=>{
      if(!spec.onWindow||e.button!==0)return;
      const p=atPointer(e);if(p.x<L||p.x>R||p.y<T||p.y>B)return;
      drag=p.x;svg.setPointerCapture(e.pointerId);tooltip.hidden=true;
    });
    svg.addEventListener('pointermove',e=>{
      const p=atPointer(e);
      if(drag!==undefined){
        const target=Math.max(L,Math.min(R,p.x));
        brush.setAttribute('x',Math.min(drag,target));brush.setAttribute('width',Math.abs(target-drag));brush.removeAttribute('display');return;
      }
      tooltip.hidden=p.x<L||p.x>R||p.y<T||p.y>B;
      if(tooltip.hidden)return;
      tooltip.classList.toggle('place-left',p.x>(L+R)/2);
      seek(fromX(p.x));
    });
    svg.addEventListener('pointerleave',()=>{tooltip.hidden=true;});
    svg.addEventListener('lostpointercapture',()=>{drag=undefined;brush.setAttribute('display','none');});
    svg.addEventListener('pointerup',e=>{
      if(drag===undefined)return;
      const end=atPointer(e).x, a=xs[nearest(fromX(drag))], b=xs[nearest(fromX(end))];
      if(Math.abs(drag-end)>=10&&b!==a)spec.onWindow(Math.min(a,b),Math.max(a,b));
      else seek(fromX(end));
    });
    svg.addEventListener('keydown',e=>{
      if(e.key!=='ArrowRight'&&e.key!=='ArrowLeft')return;
      e.preventDefault();
      seek(xs[Math.max(0,Math.min(xs.length-1,selected+(e.key==='ArrowRight'?1:-1)))]);
    });
    for(const button of host.querySelectorAll('[data-chart-legend]'))button.onclick=()=>{
      const i=Number(button.dataset.chartLegend), label=series[i].label, marks=svg.querySelector(`[data-chart-series="${i}"]`);
      if(muted.delete(label)) marks.removeAttribute('display');
      else {muted.add(label);marks.setAttribute('display','none');}
      button.setAttribute('aria-pressed',String(!muted.has(label)));seek(xs[selected],false);
    };
    if (finite(spec.cursor)) seek(spec.cursor,false);
    return {seek,svg};
  }
  function correlationMatrix(host, series, onPair) {
    const keys=Object.keys(series);
    if(keys.length<2){host.innerHTML=empty('相关性需要至少两个同一运行的数值指标。');return;}
    const pairs=keys.map(a=>keys.map(b=>window.DAYAN_ANALYSIS.correlation(series[a].map((x,i)=>({a:x,b:series[b][i]})),'a','b')));
    host.innerHTML='<table class="matrix-table"><caption>同时间窗观测的 Pearson r · 缺失成对排除</caption><thead><tr><th scope="col">指标</th>'+keys.map(k=>`<th scope="col" title="${esc(k)}">${esc(window.DAYAN_ANALYSIS.label(k))}</th>`).join('')+'</tr></thead><tbody>'+
      pairs.map((row,i)=>`<tr><th scope="row">${esc(window.DAYAN_ANALYSIS.label(keys[i]))}</th>${row.map((r,j)=>`<td><button data-matrix-pair="${i},${j}" ${finite(r)?'':'disabled'} style="--strength:${finite(r)?Math.abs(r):0};--hue:${r<0?253:177}" title="${esc(keys[i]+' × '+keys[j]+' · '+nfmt(r))}">${nfmt(r)}</button></td>`).join('')}</tr>`).join('')+'</tbody></table>';
    host.querySelectorAll('[data-matrix-pair]').forEach(button=>button.onclick=()=>onPair(...button.dataset.matrixPair.split(',').map(i=>keys[Number(i)])));
  }
  function distribution(values) {
    const sorted=values.filter(finite).sort((a,b)=>a-b);
    if(!sorted.length)return null;
    const [min,max]=[sorted[0],sorted.at(-1)], m=mean(sorted);
    const deviation=Math.sqrt(mean(sorted.map(x=>(x-m)**2)));
    const q1=quantile(sorted,.25),q3=quantile(sorted,.75);
    const span=max-min;
    if(span===0){
      const width=Math.max(Math.abs(min)*.1,.01);
      return {counts:[[min,sorted.length,'每条有效观测皆为 '+nfmt(min)]],width,domain:[min-width,min+width],
        ticks:[[min,nfmt(min)]],sorted,quantiles:[min,q1,quantile(sorted,.5),q3,max],density:[],bandwidth:0};
    }
    const bins=Math.min(16,Math.max(3,Math.ceil(Math.sqrt(sorted.length)))), step=span/bins;
    const counts=Array(bins).fill(0);
    for(const val of sorted) counts[Math.min(bins-1,Math.max(0,Math.floor((val-min)/step)))]++;
    const bandwidth = 0.9*Math.min(deviation,(q3-q1)/1.34||deviation)*sorted.length**(-.2);
    const density = bandwidth>0 ? Array.from({length:61},(_,i)=>{
      const x=min-bandwidth+i*(max-min+2*bandwidth)/60;
      return [x,mean(sorted.map(v=>Math.exp(-.5*((x-v)/bandwidth)**2)))/(bandwidth*Math.sqrt(2*Math.PI))];
    }):[];
    return {counts:counts.map((n,i)=>[min+(i+.5)*step,n]),width:step,domain:[min,max],sorted,quantiles:[min,q1,quantile(sorted,.5),q3,max],density,bandwidth};
  }
  function processCsvRows(runId, series, flow) {
    const header=['run_id','previous_t','next_t','scope','group','entity_type','state_field','previous_present','previous_state','next_present','next_state','agents'];
    return [header,...(flow?.links||[]).map(row=>[runId,flow.from,flow.to,series.scope,series.group,series.type,series.field,
      row.from.present,row.from.state,row.to.present,row.to.state,row.count])];
  }
  let processRequest=0;
  async function renderProcess(state) {
    const {run_id:runId}=state.stream||{};
    if(!runId){window.DAYAN_NOTICE('请先选择一个已保存的运行。');return;}
    const request=++processRequest, windowSpec=window.DAYAN_ANALYSIS.resolvedWindow(state);
    window.DAYAN_MODAL('主体状态迁移','<p id="processLoading" class="space-note">正在读取完整归档并按真实 ID 对齐…</p>');
    const alive=()=>request===processRequest&&document.querySelector('#processLoading')&&document.querySelector('#modalBackdrop')?.classList.contains('open')&&state.stream?.run_id===runId;
    let history;
    try {
      const query=new URLSearchParams({start:windowSpec.from,end:windowSpec.to,exclusive:windowSpec.exclusive});
      const response=await fetch(`/api/runs/${encodeURIComponent(runId)}/state-transitions?${query}`);
      history=await response.json();
      if(!response.ok)throw new Error(history.detail||'状态流读取失败');
    } catch(error) {
      if(alive())document.querySelector('#modalBody').innerHTML=empty(error.message);
      return;
    }
    if(!alive())return;
    if(!history.series.length){document.querySelector('#modalBody').innerHTML=empty(history.unavailable.map(row=>`${row.group}.${row.field}：${row.reason}`).join('；')||'该归档没有实际状态或类别字段；颜色属性不作为状态推断。');return;}
    const frames=history.times.map(sim_t=>({sim_t}));
    document.querySelector('#modalBody').innerHTML=`<div class="tool-bar"><label>主体状态<select id="processType">${history.series.map((row,i)=>`<option value="${i}">${esc(row.label+' · '+row.field)}</option>`).join('')}</select></label>
      <label>迁移分界帧<select id="processFrame"></select></label><button class="ws-button" id="exportProcess">状态迁移 CSV</button></div>
      <p class="space-note">档案 ${esc(runId)} · 当前时间窗 ${frames.length} 个完整归档时点 · 按稳定 ID 对齐，进入、退出、缺失分别计数</p><div class="process-layout"><div id="processArea" class="chart-host"></div><div id="processFlows" class="chart-host"></div></div>`;
    const type=document.querySelector('#processType'), frame=document.querySelector('#processFrame');
    const current=Math.max(1,frames.findLastIndex(f=>f.sim_t<=state.time));
    frame.replaceChildren(...frames.slice(1).map((f,i)=>new Option(`${nfmt(frames[i].sim_t)} → ${nfmt(f.sim_t)}`,i+1)));
    frame.value=current;
    const stateName=value=>value===null?'（缺失状态）':String(value);
    const selected=()=>history.series[Number(type.value)];
    const scope=()=>selected().scope==='full_population'?'全部归档主体':'该模型已导出的主体';
    let exports=[], exportedFlow=null;
    const draw=()=>{
      const populations=selected().snapshots.map(f=>new Map(f.states.map(row=>[JSON.stringify(row.state),row.count])));
      const total=new Map();
      for(const group of populations)for(const [k,v] of group)total.set(k,(total.get(k)||0)+v);
      const ranking=[...total.keys()].sort((a,b)=>total.get(b)-total.get(a));
      const categories=ranking.slice(0,7), other=new Set(ranking.slice(7));
      const set=other.size?[...categories,null]:categories;
      const stack=Array(frames.length).fill(0);
      const traces=set.map((category,i)=>({
        label:category===null?'其他记录状态':stateName(JSON.parse(category)),kind:'area',lower:true,color:colors[i%colors.length],
        points:frames.map((f,j)=>{
          const value=i<categories.length?(populations[j].get(category)||0):[...other].reduce((n,k)=>n+(populations[j].get(k)||0),0);
          const begin=stack[j];stack[j]+=value;
          return [f.sim_t,stack[j],`此状态 ${value} 个`,begin];
        }),
      }));
      plot(document.querySelector('#processArea'),{title:'各类状态的实际数量',xUnit:state.stream.frames?.[0]?.space?.time_unit||'模型时间',yUnit:'主体数',zero:true,series:traces,
        note:`堆叠高度来自${scope()}，未从画面样本外推。悬停核对独立计数。`});
      drawFlow();
    };
    function drawFlow() {
      const host=document.querySelector('#processFlows'), i=Number(frame.value);
      exportedFlow=selected().transitions[i-1]||null;
      document.querySelector('#exportProcess').disabled=!exportedFlow;
      if(!exportedFlow){host.innerHTML=empty('需要两个以上相邻归档帧。');exports=[];return;}
      const nodeName=(raw,side)=>raw.present?stateName(raw.state):side===0?'（尚未进入）':'（已退出）';
      exports=exportedFlow.links.map(row=>[JSON.stringify(row.from),JSON.stringify(row.to),row.count]);
      if(!exports.length){host.innerHTML=empty('这两个时点没有已归档主体。');return;}
      const side=index=>{
        const counts=new Map();
        for(const row of exports)counts.set(row[index],(counts.get(row[index])||0)+row[2]);
        const highest=[...counts].sort((a,b)=>b[1]-a[1]).slice(0,7)
          .sort((a,b)=>a[0].localeCompare(b[0],undefined,{numeric:true}));
        const overflow=[...counts].filter(([k])=>!highest.some(([name])=>k===name)).reduce((z,[,v])=>z+v,0);
        if(overflow)highest.push(['其他记录状态',overflow]);
        return highest;
      };
      const starts=side(0),ends=side(1);
      const total=exports.reduce((sum,row)=>sum+row[2],0);
      const scale=141/total, axis=(items)=>{let y=34;return new Map(items.map(([k,v],j)=>{const block={y,height:v*scale,offset:y,idx:j};y+=block.height+7;return [k,block];}));};
      const x0=138,x1=492, left=axis(starts),right=axis(ends);
      const paths=exports.map(([a,b,n])=>{
        const u=left.get(a)||left.get('其他记录状态'),v=right.get(b)||right.get('其他记录状态');
        const size=n*scale,top=u.offset+size/2,bottom=v.offset+size/2;
        u.offset+=size;v.offset+=size;
        return `<path d="M${x0} ${top} C280 ${top} 350 ${bottom} ${x1} ${bottom}" stroke="${colors[u.idx%colors.length]}" stroke-width="${size}" opacity=".53" fill="none"><title>${esc(nodeName(JSON.parse(a),0)+' → '+nodeName(JSON.parse(b),1)+' · '+n+' 主体')}</title></path>`;
      }).join('');
      const labels=(rows,x,anchor,side)=>[...rows].map(([k,v])=>{const label=k==='其他记录状态'?k:nodeName(JSON.parse(k),side);return `<text ${textAttr} x="${x}" y="${v.y+v.height/2+4}" text-anchor="${anchor}">${esc(label.length>15?label.slice(0,13)+'…':label)}<title>${esc(label)}</title></text>`;}).join('');
      host.innerHTML=`<svg viewBox="0 0 630 260" role="img" aria-label="相邻实际帧的主体状态流向">
        <rect width="630" height="260" fill="#0d1826"/>${paths}${labels(left,x0-5,'end',0)}${labels(right,x1+5,'start',1)}
        <text ${textAttr} x="${x0}" y="18" text-anchor="end">t=${nfmt(frames[i-1].sim_t)}</text><text ${textAttr} x="${x1}" y="18">t=${nfmt(frames[i].sim_t)}</text></svg>
        <p class="space-note">${scope()}：前后匹配 ${exportedFlow.matched}，进入 ${exportedFlow.entered}，退出 ${exportedFlow.exited}；已知状态改变 ${exportedFlow.changed_known}。流带只描述两个时点的端点，不推断期间路径。</p>`;
    }
    type.oninput=draw;
    frame.oninput=drawFlow;
    document.querySelector('#exportProcess').onclick=()=>{
      csv('DAYAN-state-flow.csv',processCsvRows(runId,selected(),exportedFlow));
    };
    draw();
  }
  window.DAYAN_CHARTS={colors,plot,correlationMatrix,distribution,csv,download,quantile,nfmt,mean,range,renderProcess,processCsvRows};
})();
