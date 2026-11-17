"""Reproduce the audit's six model-internal controlled experiments.
No external observations are synthesized or labelled as empirical data.
Run: python docs/verification/20261118/run_scenarios.py --output <private-empty-dir>
"""
import argparse,json,math,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--output',type=Path,required=True)
 args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
 os.environ['DAYAN_DATA_DIR']=str(out/'data')
 from dayan.research.specs import ExperimentSpec
 from dayan.research.experiment import run_experiment
 from dayan.run_store import get_store
 from dayan.source_version import source_fingerprint
 cases=[
  ('epidemic','NET052',{'beta':.4,'gamma':.2},40,.1,'I',{'label':'t2 beta halved','interventions':[{'at_t':2.,'params':{'beta':.2}}]},'Homogeneous SIS fractions; no empirical calibration'),
  ('evacuation','NET113',{'n':37,'v_des':.8},250,.05,'evacuated',{'label':'desired speed 1.6','params':{'v_des':1.6}},'Synthetic single room, social-force approximation; no city topology or real population'),
  ('queue','SYS002',{'c':2,'lam':1.5,'mu':1.},600,.1,'Wq_sim',{'label':'service rate 1.5','params':{'mu':1.5}},'Fixed-step M/M/2 approximation; no measured arrival/service records'),
  ('network_spread','NET063',{'n':100,'k_avg':6,'beta':.3,'gamma':.1,'n_seed':3},100,.1,'I',{'label':'edge infection rate .1','params':{'beta':.1}},'Synthetic fixed seed-0 adjacency with possible repeated edges; infection/recovery use the paired experiment RNG; no measured social network'),
  ('economy','ECO019',{'nu':2.5,'delta':.03,'a':.045,'b':.06,'x0':[.87875,.7875]},200,.1,'employment',{'label':'depreciation .05','params':{'delta':.05}},'Positive classical Goodwin equations; common explicit initial state, no clipping and no claim all orbits stay below one'),
  ('multi_agent','BEH001',{'size':12,'density':.8,'threshold':.4},40,1.,'segregation',{'label':'similarity threshold .7','params':{'threshold':.7}},'Periodic two-type Schelling grid with batch relocation; no real residential calibration')]
 receipt={'version':1,'scope':'Actual model-internal paired counterfactual computations, not empirical validation or real-world causal identification','aggregation':'window_mean is the arithmetic mean of recorded observations; jump-process event samples are not a duration-weighted time average','source_fingerprint':source_fingerprint(),'cases':[]}
 for label,mid,params,ticks,dt,metric,arm,limits in cases:
  spec=ExperimentSpec(model_id=mid,title='Audit '+label,baseline_params=params,arms=[arm],seeds=[7,8],ticks=ticks,dt=dt,primary_metric=metric,purpose='mechanism').finalize()
  assert not spec.validate(),spec.validate()
  result=run_experiment(spec,persist=True)
  assert result.ok,result.warnings
  assert len(result.runs)==4
  get_store().save_experiment(result,intent=spec.title)
  evidence=[]
  for item in result.runs:
   record=get_store().load(item['run_id'])
   assert record['manifest']['source_fingerprint']==receipt['source_fingerprint']
   assert record['manifest']['rng']['seed']==item['seed']
   expected={**params,**(arm.get('params',{}) if item['arm']!='基线' else {})}
   actual=record['manifest']['actual']['effective_parameters']
   for key,value in expected.items():assert actual[key]==value,(label,key,value,actual.get(key))
   obs=record['observations'];assert len(obs)>1 and all(math.isfinite(float(row[metric])) for row in obs)
   frames=record['state_frames'];assert frames and frames[-1]['sim_t']==obs[-1]['sim_t']
   assert math.isclose(obs[-1]['sim_t'],ticks*dt,abs_tol=1e-8)
   if label=='network_spread':assert all(row['S']+row['I']+row['R']==100 for row in obs)
   if label=='multi_agent':
    first={e['id']:e['state'] for e in frames[0]['entities']}
    for frame in frames:
     assert {e['id']:e['state'] for e in frame['entities']}==first
   if label=='evacuation':assert all(row['alive']+row['evacuated']==37 for row in obs)
   metadata=json.loads((get_store().directory/item['run_id']/'metadata.json').read_text('utf8'))
   evidence.append({'arm':item['arm'],'seed':item['seed'],'run_id':item['run_id'],'effective_parameters':actual,'requested':record['manifest']['requested'],'initial_observation':obs[0],'final_observation':obs[-1],'observation_count':len(obs),'saved_frames':len(frames),'entity_count_initial':len(frames[0].get('entities',[])),'artifact_hashes':metadata['files'],'code_archive_sha256':record['manifest']['code_archive_sha256']})
  if label=='epidemic':
   base=result.observations['基线'];changed=result.observations[arm['label']]
   for b,a in zip(base,changed):
    assert [row for row in b if row['sim_t']<=2]==[row for row in a if row['sim_t']<=2]
    assert a[-1]['I']<b[-1]['I']
  assert abs(result.analysis['arms'][arm['label']]['paired_diff']['mean'])>1e-12,label
  receipt['cases'].append({'case':label,'model_id':mid,'spec':spec.to_dict(),'runs':evidence,'analysis':result.analysis,'validity_scope':limits,'checks_passed':['four actual archived runs','paired seed IDs and effective parameters','artifact hashes loaded and verified','actual final time and saved frame agree','finite requested metric','explicit counterfactual effect']})
  print('[PASS]',label,mid,'runs=4',flush=True)
 (out/'representative_scenarios.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
 print('Saved',out/'representative_scenarios.json',flush=True)
 return 0

if __name__=='__main__':raise SystemExit(main())
