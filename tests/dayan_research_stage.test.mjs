/* Explicit protocol/arithmetic fixtures, not real research or a browser proof. */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const context={window:{},Number,Set};
vm.runInNewContext(fs.readFileSync(new URL('../site/console/workbench-research-stage.js',import.meta.url),'utf8'),context);
const reading=context.window.DAYAN_RESEARCH_STAGE_DATA.reading;
const kindFor=context.window.DAYAN_RESEARCH_STAGE_DATA.kindFor;
const plain=value=>JSON.parse(JSON.stringify(value));
function fixture(){
  const run={run_id:'controlled-run',model_id:'controlled-model',observations:[{sim_t:0,stock:10},{sim_t:1,stock:12}],
    manifest:{rng:{seed:0},model_definition:{observable_units:{stock:'件'}}}};
  const point={observable:'stock',seed:0,role:'training',time:1,actual_model_time:1,value:11,
    predicted:12,unit:'件',residual_predicted_minus_observed:1};
  const facts={study_id:'controlled-study',result_run:{run_id:run.run_id},
    protocol:{evaluation:{model:{model_id:run.model_id,observables:{stock:{unit:'件'}}},
      targets:{split:{training_end:0,validation_end:1}}}},selected_predictions:[point,{...point,seed:7,value:9000},
      {...point,actual_model_time:2,time:2,value:8000}]};
  return {run,facts};
}
test('nonspatial reading follows actual saved frames and same seed without changing inputs',()=>{
  const {run,facts}=fixture(),before=JSON.stringify({run,facts});
  const mid=reading(run,'stock',.5,'observations',facts);
  assert.equal(mid.current.stock,10);assert.equal(mid.time,0);assert.equal(mid.change,0);
  const end=plain(reading(run,'stock',1,'observations',facts));
  assert.equal(end.current.stock,12);assert.equal(end.change,2);assert.equal(end.study_id,'controlled-study');
  assert.deepEqual(end.points,[{sim_t:1,stock:11,residual:1,role:'training'}]);
  assert.equal(JSON.stringify({run,facts}),before);
});
test('different runs models units or seeds never supply empirical overlays and space is preserved',()=>{
  const {run,facts}=fixture();
  for(const bad of [
    {...facts,result_run:{run_id:'another-run'}},
    {...facts,protocol:{evaluation:{...facts.protocol.evaluation,model:{...facts.protocol.evaluation.model,model_id:'another-model'}}}},
    {...facts,protocol:{evaluation:{...facts.protocol.evaluation,model:{...facts.protocol.evaluation.model,observables:{stock:{unit:'kg'}}}}}}
  ])assert.equal(reading(run,'stock',1,'observations',bad).points.length,0);
  const other={...run,manifest:{...run.manifest,rng:{seed:9}}};
  assert.equal(reading(other,'stock',1,'observations',facts).points.length,0);
  for(const kind of ['physical','spatial','lattice','network'])assert.equal(reading(run,'stock',1,kind,facts),null);
  assert.equal(reading(run,'absent',1,'observations',facts),null);
  assert.equal(reading(null,'stock',1,'observations',facts),null);
  assert.equal(kindFor({frames:[{lattice:{width:2,height:2}}]},()=>({kind:'observations'})),'lattice');
  assert.equal(kindFor({frames:[{entities:[{x:1,y:2}]}],provenance:'entity'},()=>({kind:'spatial'})),'spatial');
  assert.equal(kindFor(null,()=>({kind:'observations'})),null);
});
