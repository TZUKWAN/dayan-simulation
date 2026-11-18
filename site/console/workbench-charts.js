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
  const textAttr = 'font-family="system-ui,sans-serif" font-size="11" fill="#a7bdd1"';
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
    const w=650,h=spec.height||274,L=68,R=w-18,T=25,B=h-48;
    const x=v=>L+(v-loX)/(hiX-loX)*(R-L),y=v=>B-(v-loY)/(hiY-loY)*(B-T);
    const xTicks=spec.xTicks || Array.from({length:6},(_,i)=>[loX+i*(hiX-loX)/5,nfmt(loX+i*(hiX-loX)/5)]);
    const yTicks=Array.from({length:5},(_,i)=>loY+i*(hiY-loY)/4);
    const axes=yTicks.map(v=>`<line x1="${L}" y1="${y(v)}" x2="${R}" y2="${y(v)}" stroke="#2b4159"/><text x="${L-9}" y="${y(v)+4}" text-anchor="end" ${textAttr}>${esc(nfmt(v))}</text>`).join('')
      +xTicks.map(([v,label])=>`<text x="${x(v)}" y="${B+18}" text-anchor="middle" ${textAttr}>${esc(label)}</text>`).join('');
    const references=(spec.events||[]).filter(e=>finite(e.x)&&e.x>=loX&&e.x<=hiX).slice(0,25).map(e=>`<line x1="${x(e.x)}" x2="${x(e.x)}" y1="${T}" y2="${B}" stroke="#f4c783" stroke-dasharray="3 5"><title>${esc(e.label)} · ${esc(nfmt(e.x))}</title></line>`).join('');
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
      return shape;
    }).join('');
    const legends=series.map((trace,i)=>`<span><i style="background:${trace.color||colors[i%colors.length]}"></i>${esc(trace.label)}</span>`).join('');
    host.innerHTML=`<svg tabindex="0" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="${esc(spec.title)}" xmlns="http://www.w3.org/2000/svg">
      <title>${esc(spec.title)}</title><rect width="${w}" height="${h}" fill="#0d1826"/>${axes}${references}${markers}
      <path d="M${L} ${T}V${B}H${R}" stroke="#627b93" fill="none"/>
      <text x="${L}" y="15" ${textAttr}>${esc(spec.yUnit||'')}</text><text x="${(R+L)/2}" y="${h-8}" text-anchor="middle" ${textAttr}>${esc(spec.xUnit||'')}</text>
      <line data-chart-cursor display="none" y1="${T}" y2="${B}" stroke="#f8fdff" stroke-dasharray="2 4" pointer-events="none"/>
      </svg><div class="chart-legend">${legends}</div><output class="chart-readout">${esc(spec.note||'移动指针或按方向键查看观测。')}</output>`;
    const svg=host.querySelector('svg'), cursor=host.querySelector('[data-chart-cursor]'), info=host.querySelector('output');
    const xs=[...new Set(defined.map(p=>p[0]))].sort((a,b)=>a-b);
    const lookup=series.map(trace=>new Map(trace.points.filter(p=>finite(p[1])).map(p=>[p[0],p])));
    let selected = 0;
    const seek = (raw,broadcast = true) => {
      let a=0,b=xs.length-1;
      while(a<b) {const m=(a+b)>>1;if(xs[m]<raw)a=m+1;else b=m;}
      if(a>0 && Math.abs(raw-xs[a-1])<Math.abs(raw-xs[a]))a--;
      const value=xs[a];selected=a;
      cursor.setAttribute('x1',x(value));cursor.setAttribute('x2',x(value));cursor.removeAttribute('display');
      const details=series.map((trace,i)=>{
        const p=lookup[i].get(value);
        const reading=!p?'—':trace.band?.find(r=>r[0]===value)?.slice(1).map(nfmt).join('–');
        return `${trace.label} ${nfmt(p?.[1])}${reading&&reading!=='—'?' ['+reading+']':''}${p?.[2]?' · '+p[2]:''}`;
      });
      info.textContent=[`${nfmt(value)} ${spec.xUnit||''}`,...details].join('  |  ');
      if(broadcast)spec.onHover?.(value);
    };
    svg.addEventListener('pointermove',e=>{
      const point = new DOMPoint(e.clientX,e.clientY).matrixTransform(svg.getScreenCTM().inverse());
      if(point.x<L||point.x>R||point.y<T||point.y>B)return;
      seek(loX+(point.x-L)/(R-L)*(hiX-loX));
    });
    svg.addEventListener('keydown',e=>{
      if(e.key!=='ArrowRight'&&e.key!=='ArrowLeft')return;
      e.preventDefault();
      seek(xs[Math.max(0,Math.min(xs.length-1,selected+(e.key==='ArrowRight'?1:-1)))]);
    });
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
    const span=max-min||1, bins=Math.min(16,Math.max(3,Math.ceil(Math.sqrt(sorted.length)))), step=span/bins;
    const counts=Array(bins).fill(0);
    for(const val of sorted) counts[Math.min(bins-1,Math.max(0,Math.floor((val-min)/step)))]++;
    const bandwidth = 0.9*Math.min(deviation,(q3-q1)/1.34||deviation)*sorted.length**(-.2);
    const density = bandwidth>0 ? Array.from({length:61},(_,i)=>{
      const x=min-bandwidth+i*(max-min+2*bandwidth)/60;
      return [x,mean(sorted.map(v=>Math.exp(-.5*((x-v)/bandwidth)**2)))/(bandwidth*Math.sqrt(2*Math.PI))];
    }):[];
    return {counts:counts.map((n,i)=>[min+(i+.5)*step,n]),width:step,sorted,quantiles:[min,q1,quantile(sorted,.5),q3,max],density,bandwidth};
  }
  window.DAYAN_CHARTS={colors,plot,correlationMatrix,distribution,csv,download,quantile,nfmt,mean,range};
})();
