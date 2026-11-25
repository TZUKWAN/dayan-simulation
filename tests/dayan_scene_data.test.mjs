import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const context = { window: {}, Intl };
vm.runInNewContext(await readFile(new URL('../site/console/analysis.js',import.meta.url),'utf8'),context);
const { savedEvents }=context.window.DAYAN_ANALYSIS;
vm.runInNewContext(await readFile(new URL('../site/console/scene-studio.js',import.meta.url),'utf8'),context);
const { resolve, compositionFor, wallRuns, personPose }=context.window.DAYAN_SCENE_STUDIO;

test('grouped fields retain labels and units, and mixed coordinate units do not share a scene',()=>{
  const groups=[{id:'workers',label:'工作人员',count:3,units:{income:'CNY',x:'m',y:'m'}},
    {id:'sites',label:'站点',count:2,units:{x:'km',y:'km'}}];
  const frame={population:{format:'dayan-populations-v1',groups},space:{unit:'m'},
    entities:[{id:'workers:a',group:'workers',type:'person',x:1,y:2},{id:'sites:a',group:'sites',type:'facility',x:1,y:2}]};
  const A=context.window.DAYAN_ANALYSIS,S=context.window.DAYAN_SCENE_STUDIO;
  assert.equal(A.populationField(frame,'workers.income').title,'工作人员 · 收入（CNY）');
  assert.equal(S.inSceneSpace(frame.entities[0],frame),true);
  assert.equal(S.inSceneSpace(frame.entities[1],frame),false);
  assert.equal(S.inSceneSpace(frame.entities[0],{...frame,space:{}}),false);
  assert.equal(S.resolve({provenance:'lattice',frames:[frame]}).kind,'spatial');
});

test('constant decimal observations have undefined correlation instead of a floating-point false one',()=>{
  const {correlation}=context.window.DAYAN_ANALYSIS;
  const rows=Array.from({length:251},(_,i)=>({density:.8,flux:i}));
  assert.equal(correlation(rows,'density','density').value,null);
  assert.equal(correlation(rows,'density','flux').value,null);
  assert.ok(Math.abs(correlation(rows.map(r=>({...r,opposite:-r.flux})),'flux','opposite').value+1)<1e-12);
});

test('adaptive metrics keep explicit choices and correlation panels require real paired variation',async()=>{
  const A=context.window.DAYAN_ANALYSIS;
  const rows=[0,1,2,3].map(i=>({sim_t:i,population:4096,mean_speed:2,cash:10+i,capital:20-i}));
  const before=JSON.stringify(rows);
  assert.deepEqual(Array.from(A.correlationFields(rows)),['cash','capital']);
  assert.deepEqual(Array.from(A.correlationFields(rows.map(({cash,...r})=>r))),[]);
  assert.deepEqual(Array.from(A.correlationFields([{a:1,b:null},{a:2,b:null},{a:3,b:2},{a:null,b:3},{a:null,b:4}])) ,[]);
  assert.deepEqual(Array.from(A.correlationFields(rows.slice(0,2))),[]);
  const ui={window:{DAYAN_ANALYSIS:A,DAYAN_CHARTS:{colors:[]}},document:{querySelector:()=>({}),addEventListener:()=>{}}};
  vm.runInNewContext(await readFile(new URL('../site/console/workbench-live.js',import.meta.url),'utf8'),ui);
  const live=ui.window.DAYAN_LIVE,run={model_id:'test',observations:rows,manifest:{}};
  assert.equal(live.chooseMetric(run,'',A.numericFields(rows)),'cash');
  assert.equal(live.chooseMetric(run,'',A.numericFields(rows),'population'),'population');
  assert.equal(live.chooseMetric(run,'观察人口是否守恒',A.numericFields(rows)),'population');
  assert.deepEqual(Array.from(live.fields(rows,['mean_speed'])),['mean_speed','cash','capital','population']);
  assert.equal(JSON.stringify(rows),before);
});

test('saved interventions appear once across event log and manifest without losing real simultaneous events',()=>{
  const stream={events:[{etype:'bus_arrival',sim_t:2,bus_id:1},{etype:'bus_arrival',sim_t:2,bus_id:2},
    {etype:'intervention',sim_t:1,params:{beta:.2,gamma:.1},label:'actual event'}],
    manifest:{interventions:[{applied:true,actual_t:1,params:{gamma:.1,beta:.2},label:'manifest mirror'},
      {applied:false,actual_t:3,params:{beta:1}}]}};
  const before=JSON.stringify(stream),events=savedEvents(stream);
  assert.equal(events.length,3);
  assert.equal(events.filter(e=>e.etype==='intervention').length,1);
  assert.equal(events[0].sim_t,1);
  assert.equal(JSON.stringify(stream),before,'saved input must not be modified by view normalization');
});

test('legacy manifest-only actual interventions are retained and invalid times never enter HTML attributes',()=>{
  const events=savedEvents({events:[{etype:'bad',sim_t:'" onclick="alert(1)'}],
    manifest:{interventions:[{applied:true,actual_t:0,params:{p:.2}}]}});
  assert.equal(events.length,1);assert.equal(events[0].sim_t,0);assert.equal(events[0].applied,true);
});

test('SIS maps complementary population shares and keeps its equilibrium separate',()=>{
  const final={I:.5278815542548143,I_frac:.5278815542548143,I_star:.6};
  const profile=resolve({model_id:'NET052',provenance:'aggregate',frames:[{aggregates:final}]});
  assert.equal(profile.kind,'observations');
  const read=(data,population)=>compositionFor('NET052',{aggregates:data},population);
  const end=read(final);
  assert.equal(end.nodes.map(node=>node.key).join(','),'S,I');
  assert.equal(end.shares.I,final.I_frac);
  assert.equal(end.shares.S+end.shares.I,1);
  assert.equal(end.reference,.6);
  assert.equal(read({I:5},10).shares.I,.5);
  assert.equal(read({I:5}),null);
  assert.equal(read({I_frac:1.1}),null);
});

test('scene dispatch uses documented states or recorded entities',()=>{
  const frame={aggregates:{S:90,I:10,R:0}};
  const sir=resolve({model_id:'NET-SIR',provenance:'aggregate',frames:[frame]});
  assert.equal(sir.kind,'observations');
  assert.equal(compositionFor('NET-SIR',frame).shares.R,0);
  assert.equal(resolve({model_id:'USR_UNKNOWN',provenance:'aggregate',frames:[frame]}).kind,'observations');
  assert.equal(resolve({model_id:'NET053',provenance:'aggregate',frames:[{aggregates:{I:10}}]}).kind,'observations');
  const road={entities:[{type:'car',x:3}],facilities:[{type:'road',length:100}]};
  assert.equal(resolve({model_id:'NET106',provenance:'entity',frames:[road]}).kind,'ring-road');
});

test('a recorded doorway leaves an open span in the corresponding room wall',()=>{
  const room={x:10,y:10,width:12,depth:10};
  const gate={kind:'exit',x:4,y:10,width:1,depth:2};
  const edge=wallRuns(room,[gate]).filter(piece=>piece.axis==='y'&&piece.at===4);
  assert.equal(edge.map(piece=>[piece.start,piece.end].join('-')).join(','),'5-9,11-15');
});

test('live declarations resolve people and actual action states take priority over motion fallback',()=>{
  const frame={entities:[{id:0,type:'agent',x:1,y:2,activity:0}],
    presentation:{visualization:{glyph:'person',action_by:'activity',action_poses:{0:'idle',1:'walk'}}}};
  const profile=resolve({provenance:'entity',frames:[frame]});
  assert.equal(profile.glyph,'person');
  assert.equal(personPose(frame.entities[0],profile,true),'idle');
  assert.equal(personPose({activity:1},profile,false),'walk');
  assert.equal(personPose({state:'fallen'},profile,true),'down');
  assert.equal(personPose({},profile,true),'walk');
});
