/* The stage consumes archived observations or samples emitted by the current job. */
(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const A = window.DAYAN_ANALYSIS;
  const {finite, esc, fmt, label, numericFields} = A;
  const colors = window.DAYAN_CHARTS.colors;
  let moments, linkedSelection;

  function write(selector, value) {
    const element = $(selector);
    if (element.textContent !== String(value)) element.textContent = value;
  }

  function fields(rows, preferred = []) {
    const available = numericFields(rows);
    const ordered = [...new Set(preferred.filter(key => available.includes(key)))];
    return [...new Set([...ordered, ...A.varyingFields(rows,available), ...available])];
  }
  function chooseMetric(run, question, metrics, explicit) {
    if(metrics.includes(explicit))return explicit;
    const text=question.toLowerCase();
    const named=metrics.find(key=>{
      const name=A.metricInfo(run.model_id,key,run.manifest).name;
      return name.length>=2&&name!==key&&text.includes(name.toLowerCase());
    });
    if(named)return named;
    const varying=A.varyingFields(run.observations||[],metrics), candidates=varying.length?varying:metrics;
    return ['flux','evacuated','I','I_total','queue_length','gini','population','k'].find(key=>candidates.includes(key))||candidates[0];
  }

  function spark(rows, field, color) {
    const stride = Math.max(1, Math.floor(rows.length / 70));
    const values = rows.filter((_,i) => i % stride === 0 || i === rows.length - 1).map(row => row[field]);
    const valid = values.filter(finite);
    if (!valid.length) return '';
    const min = Math.min(...valid), span = Math.max(...valid) - min;
    let pen = false, path = '';
    values.forEach((value,index) => {
      if (!finite(value)) {pen=false;return;}
      path += (pen ? 'L' : 'M') + (3 + index*114/Math.max(1,values.length-1)).toFixed(1)
        + ' ' + (span ? 25 - (value-min)*20/span : 15).toFixed(1);
      pen = true;
    });
    return '<svg viewBox="0 0 120 30" aria-hidden="true"><path d="'+path+'" fill="none" stroke="'+color+'" stroke-width="1.6"/></svg>';
  }

  function paintScope(parts) {
    [...$('#runScope').children].forEach((node,i) => {
      const part = parts[i] || '';
      node.hidden = !part;
      if (node.textContent !== part) node.textContent = part;
    });
  }

  function cuts(run, state) {
    if (moments?.run === run && moments.events === state.events && moments.metric === state.metric) return moments.items;
    const applied = state.events.filter(event => finite(event.sim_t) && event.applied !== false);
    const visible = applied.sort((a,b) => Number(b.etype==='intervention')-Number(a.etype==='intervention') || a.sim_t-b.sim_t);
    const seen = new Set(), items = [];
    for (const event of visible) {
      const stamp = event.sim_t.toPrecision(12);
      if (seen.has(stamp)) continue;
      seen.add(stamp);
      items.push({time:event.sim_t,text:event.label||A.label(event.etype)||'模型事件',event});
      if (items.length === 3) break;
    }
    const rows = run.observations || [];
    let largest = 0, smallest = Infinity, point;
    for (let i=1;i<rows.length;i++) {
      const before=rows[i-1][state.metric], now=rows[i][state.metric];
      if (!finite(now)||!finite(before)||!finite(rows[i].sim_t)) continue;
      const delta=Math.abs(now-before);
      smallest=Math.min(smallest,delta);
      if(delta>largest){largest=delta;point=rows[i].sim_t;}
    }
    if (point !== undefined && largest-smallest>Math.max(1e-10,largest*1e-9) && !seen.has(point.toPrecision(12))) items.push({time:point,text:label(state.metric)+'最大单步变化'});
    items.sort((a,b)=>a.time-b.time);
    moments = {run,events:state.events,metric:state.metric,items};
    return items;
  }

  function paintArchive(state) {
    const run = state.runs[state.selected];
    const surface=$('#simulationSurface');
    const strip=$('#runMoments');
    const design=$('#modelDesignButton');
    design.dataset.designId=run?.manifest?.scenario_review?.model_design?.design_id||'';
    design.hidden=!design.dataset.designId;
    surface.dataset.dataSource=run?'archive':'empty';
    if (!run) {
      delete surface.dataset.sceneKind;
      write('#runPhase','待开始');
      write('#scenarioModel','');
      $('#researchQuestion').hidden=true;
      paintScope([]);
      strip.hidden=true;
      linkedSelection=null;
      window.DAYAN_RESEARCH_STAGE?.hide();
      return;
    }
    const manifest=run.manifest||{}, requested=manifest.requested||{};
    const savedAt=manifest.created_at||run.created_at;
    const space=state.stream?.frames?.[0]?.space;
    const study=window.DAYAN_STUDY?.run_id===run.run_id?window.DAYAN_STUDY:null;
    const scope=[study?.contract?.country,study?.contract?.date].filter(Boolean).join(' · ');
    const unit=space?.time_unit||manifest.actual?.time_unit||'模型时间';
    const phase=state.context?.history?'历史回放':state.playing?'归档回放中':state.context?.idleArchive?'最近归档':'已归档';
    const coverage=manifest.scenario_review?.coverage;
    write('#runPhase',coverage?.status==='partial'?phase+' · 部分覆盖':phase);
    write('#scenarioModel',run.model_id);
    const presentation=window.DAYAN3D?.presentation;
    const sceneKind=window.DAYAN_RESEARCH_STAGE?.kindFor(state.stream)||presentation?.kind||'';
    surface.dataset.sceneKind=sceneKind;
    write('#sceneViewLabel',sceneKind==='observations'?'研究分析':'仿真现场');
    write('#sceneFullscreen',sceneKind==='observations'?'分析全屏':'场景全屏');
    write('#sceneOptions > summary',sceneKind==='observations'?'布局':'场景设置');
    window.DAYAN_RESEARCH_STAGE?.archive(state);
    write('#scenarioTitle',manifest.model_definition?.scenario?.title || manifest.model_definition?.name
      || (presentation?.kind!=='observations'&&presentation?.title) || state.question || run.label || run.model_id);
    $('#scenarioTitle').title=state.question;
    $('#researchQuestion').hidden=true;
    const date=savedAt&&Number.isFinite(new Date(savedAt).getTime())?window.DAYAN_WORKBENCH.date(savedAt):'';
    paintScope([scope || date,unit+' '+fmt(state.start)+'–'+fmt(state.end),
      manifest.rng?.seed!==undefined?'种子 '+manifest.rng.seed:requested.ticks!==undefined?'请求 '+requested.ticks+' 步':'']);
    const items=cuts(run,state);
    if(linkedSelection?.run!==run)linkedSelection=null;
    strip.hidden=!items.length&&!linkedSelection;
    const host=$('#momentButtons');
    const markup=items.map((item,i)=>'<button type="button" class="moment-chip" data-moment="'+i+
      '" aria-pressed="'+(linkedSelection?.item===item)+'" title="'+esc(item.text)+'"><time>'+fmt(item.time)+'</time> '+esc(item.text)+'</button>').join('');
    if(host.innerHTML!==markup)host.innerHTML=markup;
    $('#askMoment').hidden=!linkedSelection||!run.run_id;
    const jump=items.find(item=>!item.event);
    let tick=$('[data-moment-tick]');
    if (jump && state.end>state.start) {
      if(!tick) {
        tick=document.createElement('button');tick.className='event-tick moment-tick';
        tick.dataset.momentTick='true';$('.timeline-ticks').append(tick);
      }
      tick.style.left=100*(jump.time-state.start)/(state.end-state.start)+'%';
      tick.title=jump.text+' · '+fmt(jump.time);tick.setAttribute('aria-label',tick.title);
      tick.onclick=()=>goToMoment(state,jump);
    } else tick?.remove();
  }

  function paintSample(job, samples, selected) {
    const frame=selected.frame;
    $('#simulationSurface').dataset.dataSource='stream';
    $('#simulationSurface').dataset.sceneKind=window.DAYAN3D?.presentation?.kind||'';
    write('#runPhase','计算中');
    write('#scenarioModel',selected.model_id);
    write('#scenarioTitle',job.question||job.label||selected.model_id+' 计算中');
    $('#researchQuestion').hidden=true;
    paintScope(['已计算 '+selected.step+' / '+selected.requested_steps+' 步',
      (frame.space?.time_unit||'模型时间')+' '+fmt(frame.sim_t),
      frame.lattice && frame.population?.format!=='dayan-populations-v1' ? (frame.population?.count || ((frame.lattice.source_width||frame.lattice.width)*(frame.lattice.source_height||frame.lattice.height))).toLocaleString()+' 个格点'
        : selected.entities_total?'显示 '+frame.entities.length+' / '+selected.entities_total+' 个主体':'汇总状态']);
    const rows=samples.map(reading=>({...reading.frame.aggregates,sim_t:reading.frame.sim_t}));
    const latest={...frame.aggregates,sim_t:frame.sim_t};
    const metricKeys=fields(rows,['flux','evacuated','passengers_waiting','infection_rate','I','K','population','gini','customers','queue_length']);
    const metric=chooseMetric({model_id:selected.model_id,observations:rows,manifest:{}},job.question||'',metricKeys);
    window.DAYAN_RESEARCH_STAGE?.sample({model_id:selected.model_id,observations:rows,manifest:{}},metric,frame.sim_t,
      frame.space?.time_unit||'模型时间',frame);
    const currentCards=metricKeys.filter(key=>finite(latest[key])).slice(0,6);
    const signal=$('#signalDeck');
    const markup=currentCards.map((key,i)=>'<div class="signal-card"><span>'+esc(label(key))+'</span><strong>'+fmt(latest[key])+'</strong>'
      +spark(rows,key,colors[i%colors.length])+'</div>').join('');
    if(signal.innerHTML!==markup)signal.innerHTML=markup;
    write('#signalCount',currentCards.length?currentCards.length+' 项采样指标':'');
    write('#obsModel',selected.model_id);
    write('#obsTick','当前采样时点 '+fmt(frame.sim_t));
    write('#metricDescription',metric?label(metric):'');
    $('#obsLegend').replaceChildren();
    if (metric) {
      const info=A.metricInfo(selected.model_id,metric,{});
      A.drawLine($('#obsChart'),[{rows,color:colors[0]}],metric,frame.sim_t,[rows[0].sim_t,rows.at(-1).sim_t],
        [],null,info.unit,frame.space?.time_unit||'模型时间');
    } else A.clearChart($('#obsChart'),'等待该模型的可绘制指标');
    const entities=frame.entities||[];
    const full=frame.statistics?.distributions;
    const field=['speed','wait','wealth','income','opinion','risk','state','group','type',...Object.keys(full||{})].find(key=>full?full[key]:entities.some(e=>finite(e[key])||typeof e[key]==='string'));
    $('#distributionPanel').hidden=!field;
    if(field) {
      const description=A.populationField(frame,field),stats=full?.[field];
      write('#distributionTitle',description.title+(full?' · 全量分布':' · 当前状态采样'));
      write('#distributionNote',(full?stats.n+' 个有效主体'+(stats.missing?' · 缺失 '+stats.missing:'')+(stats.not_applicable?' · 其他组不适用 '+stats.not_applicable:''):entities.length+' / '+selected.entities_total+' 个主体')+' · 模型时间 '+fmt(frame.sim_t));
      $('#distributionField').parentElement.hidden=true;
      if(full?.[field]?.cdf) A.drawCdf($('#distributionChart'),full[field],description.title,colors[1]);
      else if(full) A.drawBars($('#distributionChart'),Object.entries(full[field].counts||{}).map(([name,count])=>({label:label(name),count})),colors[1]);
      else if (entities.some(e=>finite(e[field]))) A.drawCdf($('#distributionChart'),entities.map(e=>e[field]),label(field),colors[1]);
      else A.drawBars($('#distributionChart'),A.categories(entities,field).bins,colors[1]);
    }
    A.renderStructure({runs:[{label:'引擎状态采样',observations:rows}],selected:0,
      stream:{model_id:selected.model_id,frames:samples.map(sample=>sample.frame)},start:rows[0].sim_t,end:rows.at(-1).sim_t,time:frame.sim_t,metric},frame);
    window.DAYAN_PROCESS_CHARTS?.render(rows,metric,frame.sim_t,selected.model_id,{},frame.space?.time_unit||'模型时间');
  }

  function choose(state, details) {
    const run=state.runs[state.selected];
    if (!run) return;
    linkedSelection=details?{run,...details}:null;
    paintArchive(state);
  }

  function goToMoment(state,item) {
    state.setPlaying(false, false);
    state.seek(item.time);
    if(item.event)window.DAYAN3D?.focusEvent(item.event);
    choose(state,{item});
  }
  $('#momentButtons').onclick = event => {
    const hit=event.target.closest('[data-moment]'), item=hit&&moments?.items[Number(hit.dataset.moment)];
    if (item) goToMoment(window.DAYAN_RESULTS,item);
  };
  $('#askMoment').onclick = () => {
    const state=window.DAYAN_RESULTS, run=state.runs[state.selected];
    if (!run?.run_id || !linkedSelection) return;
    const detail=linkedSelection.entityId ? '，主体 '+linkedSelection.entityId
      : linkedSelection.region ? '，模型空间选区 '+linkedSelection.region : '';
    window.DAYAN_COMMAND.prefill('请根据已保存的运行 '+run.run_id+' 解释模型时间 '+fmt(state.time)+detail+' 的变化，并引用实际观测。');
  };
  document.addEventListener('dayan:entity-selected',event=>choose(window.DAYAN_RESULTS,{entityId:event.detail.id}));
  window.DAYAN_LIVE={fields,chooseMetric,paintArchive,paintSample,choose};
})();
