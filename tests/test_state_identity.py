"""Actual queue customer identity, clock consistency and checkpoint continuation."""
import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dayan.models.sys_models import MMCQueueModel
from dayan.runtime import run_model_full,resume_from_checkpoint
from dayan.stateframe import state_frame_of


class StateIdentity(unittest.TestCase):
    def test_resident_identity_follows_moves_and_preserves_population(self):
        result=run_model_full('BEH001',parameters={'size':12,'density':.8,'threshold':.7},
                              ticks=8,dt=1.,seed=7,capture_state=True)
        frames=result.state_frames
        first={e['id']:e for e in frames[0]['entities']}
        moved=set()
        for frame in frames[1:]:
            current={e['id']:e for e in frame['entities']}
            self.assertEqual(set(current),set(first))
            self.assertEqual(len(current),len(frame['entities']))
            for key,entity in current.items():
                self.assertEqual(entity['state'],first[key]['state'])
                if (entity['x'],entity['y'])!=(first[key]['x'],first[key]['y']):moved.add(key)
        self.assertTrue(moved,'Resident identities must travel with actual relocations')

    def test_customer_ids_and_server_assignments_remain_actual(self):
        model=MMCQueueModel(c=2,lam=3.,mu=2.)
        model.initialize(None,{},None,None,np.random.default_rng(7))
        finished=set();previous=set()
        for k in range(200):
            model.step(k*.05,.05);frame=state_frame_of(model,(k+1)*.05)
            customers=[e for e in frame['entities'] if e['type']=='customer']
            current={e['id'] for e in customers}
            self.assertFalse(current & finished,'Completed customer ID was reused for a different arrival')
            finished.update(previous-current);previous=current
            self.assertEqual(model.n_arrived,model.n_served+len(model.q)+model.busy)
            for e in customers:
                if e['state']=='in_service':
                    index=int(e['server_id'].split('_')[-1])
                    self.assertEqual(model.slots[index]['id'],e['id'])
        self.assertGreater(len(finished),0)

    def test_queue_snapshot_and_pending_intervention_match_uninterrupted_run(self):
        options=dict(parameters={'c':2,'lam':3.,'mu':2.},dt=.05,seed=7,capture_state=True,
            interventions=[{'at_t':1.,'params':{'mu':3.}}])
        full=run_model_full('SYS002',ticks=60,**options)
        first=run_model_full('SYS002',ticks=60,checkpoint_at=10,**options)
        continued=resume_from_checkpoint(first.checkpoint,50,.05,capture_state=True,with_initial=True)
        self.assertEqual(continued.observations,full.observations[10:])
        strip=lambda frames:[{k:v for k,v in f.items() if k!='run_id'} for f in frames]
        self.assertEqual(strip(continued.state_frames),strip(full.state_frames[10:]))

    def test_invalid_frame_identity_time_and_coordinates_are_rejected(self):
        class Invalid:
            def __init__(self,frame):self.frame=frame
            def state_frame(self):return self.frame
        cases=[{'sim_t':1.,'entities':[]},
               {'entities':[{'id':1,'x':0},{'id':'1','x':2}]},
               {'entities':[{'id':'a','x':float('nan')}]},
               {'entities':[{'x':0}]}]
        for frame in cases:
            with self.assertRaises(ValueError):state_frame_of(Invalid(frame),0.)

    def test_continuation_retains_all_observations_and_samples_state_frames(self):
        first=run_model_full('NET106',ticks=1,seed=7,capture_state=True)
        rr=resume_from_checkpoint(first.checkpoint,400,.1,capture_state=True,with_initial=True)
        self.assertEqual(len(rr.observations),401)
        self.assertLessEqual(len(rr.state_frames),201)
        self.assertEqual(rr.state_frames[-1]['sim_t'],rr.observations[-1]['sim_t'])
        sampled=run_model_full('NET106',parameters={'cells':100},ticks=250,seed=7,state_every=3,capture_state=True)
        self.assertEqual(sampled.state_frames[-1]['sim_t'],sampled.observations[-1]['sim_t'])
        self.assertEqual(sampled.state_frames[-1]['aggregates']['flux'],sampled.observations[-1]['flux'])


if __name__=='__main__':unittest.main(verbosity=2)
