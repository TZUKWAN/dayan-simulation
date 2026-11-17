import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const context = { window: {}, Intl };
vm.runInNewContext(await readFile(new URL('../site/console/analysis.js',import.meta.url),'utf8'),context);
const { savedEvents }=context.window.DAYAN_ANALYSIS;

test('constant decimal observations have undefined correlation instead of a floating-point false one',()=>{
  const {correlation}=context.window.DAYAN_ANALYSIS;
  const rows=Array.from({length:251},(_,i)=>({density:.8,flux:i}));
  assert.equal(correlation(rows,'density','density').value,null);
  assert.equal(correlation(rows,'density','flux').value,null);
  assert.ok(Math.abs(correlation(rows.map(r=>({...r,opposite:-r.flux})),'flux','opposite').value+1)<1e-12);
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
