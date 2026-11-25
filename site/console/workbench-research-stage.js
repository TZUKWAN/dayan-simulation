/* Non-spatial stage: real run observations and the same saved study/seed only. */
(() => {
  'use strict';
  const finite = Number.isFinite;
  const roles = {training:'训练实测',validation:'验证实测',holdout:'留出实测'};
  const roleColors = {training:'#64b9ba',validation:'#b7a0dd',holdout:'#edb16b'};
  function reading(run,metric,time,kind,facts) {
    if(kind!=='observations'||!run||!metric)return null;
    const rows=(run.observations||[]).filter(row=>finite(row.sim_t)&&finite(row[metric]));
    if(!rows.length)return null;
    const current=rows.findLast(row=>row.sim_t<=time)||rows[0];
    const definition=run.manifest?.model_definition||{};
    const unit=definition.observable_units?.[metric]||definition.observables?.[metric]?.unit;
    const seed=run.manifest?.rng?.seed;
    const same=!!run.run_id&&facts?.result_run?.run_id===run.run_id
      &&facts?.protocol?.evaluation?.model?.model_id===run.model_id
      &&seed!==undefined&&(!unit||facts.protocol.evaluation.model.observables?.[metric]?.unit===unit);
    const times=new Set(rows.map(row=>row.sim_t));
    const points=same?(facts.selected_predictions||[]).filter(point=>point.observable===metric&&point.seed===seed
      &&roles[point.role]&&finite(point.value)&&finite(point.residual_predicted_minus_observed)
      &&(!unit||point.unit===unit)&&times.has(point.actual_model_time??point.time))
      .map(point=>({sim_t:point.actual_model_time??point.time,[metric]:point.value,
        residual:point.residual_predicted_minus_observed,role:point.role})):[];
    return {rows,current,start:rows[0],metric,unit,time:current.sim_t,change:current[metric]-rows[0][metric],
      run_id:run.run_id||null,study_id:same?facts.study_id:null,points,
      split:same?facts.protocol.evaluation.targets.split:null};
  }
  function kindFor(stream,resolve) {
    if(!stream?.frames?.length)return null;
    if(stream.frames[0].lattice)return 'lattice';
    return resolve?resolve(stream).kind:stream.provenance==='aggregate'?'observations':null;
  }
  window.DAYAN_RESEARCH_STAGE_DATA={reading,kindFor};
  if(typeof document==='undefined')return;
  const $=selector=>document.querySelector(selector),A=window.DAYAN_ANALYSIS;
  let latest=null,scheduled=false;
  const number=value=>finite(value)?value.toLocaleString('zh-CN',{maximumFractionDigits:3}):'—';
  function hide() {
    $('#researchStage').hidden=true;
    delete $('#simulationSurface').dataset.researchStage;
    latest=null;
  }
  function draw(run,metric,time,kind,facts,clock) {
    const data=reading(run,metric,time,kind,facts);
    if(!data){hide();return;}
    latest={run,metric,time,kind,facts,clock};
    const host=$('#researchStage');host.hidden=false;
    $('#simulationSurface').dataset.researchStage='active';
    host.dataset.runId=data.run_id||'';host.dataset.studyId=data.study_id||'';
    host.dataset.time=String(data.time);host.dataset.value=String(data.current[metric]);
    host.dataset.observations=String(data.points.length);
    const info=A.metricInfo(run.model_id,metric,run.manifest||{});
    $('#researchStageMode').textContent=data.points.length?'研究结果':'指标演化';
    $('#researchStageTitle').textContent=info.name||metric;
    $('#researchStageTime').textContent=(clock||'模型时间')+' '+number(data.time);
    $('#researchStageValue').textContent=number(data.current[metric]);
    $('#researchStageValue').title=String(data.current[metric])+' '+(data.unit||info.unit);
    $('#researchStageChange').textContent=(data.change>0?'+':'')+number(data.change);
    $('#researchStageUnit').textContent=data.unit||info.unit;
    const groups=Object.keys(roles).filter(role=>data.points.some(p=>p.role===role));
    const series=[{rows:data.rows,color:'#6ee0dd'},...groups.map(role=>({
      rows:data.points.filter(p=>p.role===role),color:roleColors[role],pointsOnly:true}))];
    const limits=[data.rows[0].sim_t,data.rows.at(-1).sim_t];
    const cut=data.split,bands=cut?[
      {from:limits[0],to:cut.training_end,color:'#64b9ba12',label:'训练'},
      {from:cut.training_end,to:cut.validation_end,color:'#b7a0dd12',label:'验证'},
      {from:cut.validation_end,to:limits[1],color:'#edb16b12',label:'留出'}]:[];
    A.drawLine($('#researchStageChart'),series,metric,data.time,limits,[],null,
      data.unit||info.unit,clock||'模型时间',{zeroBaseline:false,bands});
    $('#researchStageLegend').innerHTML='<span><i style="background:#6ee0dd"></i>实际模型轨迹</span>'
      +groups.map(role=>'<span><i style="background:'+roleColors[role]+'"></i>'+roles[role]+'</span>').join('')
      +'<span class="research-stage-scale">纵轴按实际范围</span>';
    $('#researchStageResidual').hidden=!data.points.length;
    if(data.points.length) {
      const residuals=groups.map(role=>({rows:data.points.filter(p=>p.role===role),color:roleColors[role],pointsOnly:true}));
      A.drawLine($('#researchResidualChart'),residuals,'residual',data.time,limits,[],null,
        data.unit||info.unit,clock||'模型时间',{zeroBaseline:false,includeZero:true});
    }
  }
  function archive(state) {
    const run=state?.runs?.[state.selected];
    if(state?.stream?.run_id!==run?.run_id){hide();return;}
    draw(run,state?.metric,state?.time,kindFor(state?.stream,window.DAYAN_SCENE_STUDIO?.resolve),
      window.DAYAN_STUDY_FACTS,run?.manifest?.actual?.time_unit||'模型时间');
  }
  function sample(run,metric,time,clock,frame) {
    const stream={frames:[frame],model_id:run.model_id,manifest:run.manifest,
      provenance:frame?.provenance||(frame?.entities?.length?'entity':'aggregate')};
    draw(run,metric,time,kindFor(stream,window.DAYAN_SCENE_STUDIO?.resolve),null,clock);
  }
  function repaint() {
    if(scheduled)return;scheduled=true;
    requestAnimationFrame(()=>{scheduled=false;if(latest){const a=latest;draw(a.run,a.metric,a.time,a.kind,a.facts,a.clock);}});
  }
  window.addEventListener('dayan:study-facts',()=>archive(window.DAYAN_RESULTS));
  window.addEventListener('dayan:page',event=>{if(event.detail==='overview')requestAnimationFrame(()=>archive(window.DAYAN_RESULTS));});
  if(window.ResizeObserver)new ResizeObserver(repaint).observe($('#mapViewport'));
  window.DAYAN_RESEARCH_STAGE={archive,sample,hide,kindFor:stream=>kindFor(stream,window.DAYAN_SCENE_STUDIO?.resolve)};
})();
