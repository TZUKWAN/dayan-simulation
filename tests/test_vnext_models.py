"""Bounded source-mechanism tests. Their synthetic inputs are test fixtures."""
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dayan.datasets import ingest
from dayan.runtime import run_model_full, param_contract
from dayan.source_version import source_fingerprint


def digest(rows):
    return hashlib.sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


class CoreMechanisms(unittest.TestCase):
    receipt = {}

    @classmethod
    def tearDownClass(cls):
        path = os.environ.get("DAYAN_CORE_REVIEW_RECEIPT")
        if path:
            Path(path).write_text(json.dumps({
                "source_fingerprint":source_fingerprint(),"reviews":cls.receipt,
            }, ensure_ascii=False,indent=2),encoding="utf-8")

    def check_case(self,mid,params,variant,*,dt=.1,ticks=30,states=False):
        def run(p,seed):
            return run_model_full(mid,p,ticks=ticks,dt=dt,seed=seed,strict=True,capture_state=states)
        first=run(params,7)
        duplicate=run(params,7)
        second=run(params,23)
        changed=run(params | variant,7)
        self.assertEqual(first.observations,duplicate.observations,mid)
        if states:
            self.assertEqual([{k:v for k,v in f.items() if k!="run_id"} for f in first.state_frames],
                             [{k:v for k,v in f.items() if k!="run_id"} for f in duplicate.state_frames],mid)
        for result in (first,second,changed):
            self.assertEqual(result.manifest['source_fingerprint'],source_fingerprint(),mid)
            self.assertGreaterEqual(len(result.observations),2,mid)
            self.assertEqual(result.observations[0]["sim_t"],0,mid)
            self.assertTrue(all(a["sim_t"]<b["sim_t"] for a,b in zip(result.observations,result.observations[1:])),mid)
        self.receipt[mid]={"same_seed_repeat":True,"seeds":[7,23],"steps":ticks,"dt":dt,
                           "parameters":params,"variant":variant,"base_sha256":digest(first.observations),
                           "second_seed_sha256":digest(second.observations),
                           "variant_sha256":digest(changed.observations),"mechanism_assertions":False}
        self.assertNotEqual(first.observations,changed.observations,mid)
        return first,changed

    def passed(self,mid):
        self.receipt[mid]["mechanism_assertions"]=True

    def test_growth_and_macro_mechanisms(self):
        a=[[.1,.25],[.2,.1]]
        d=[1.,2.]
        base, changed=self.check_case("ECO001",{"A":a,"d":d,"sectors":2},{"d":[2.,4.]})
        solution=np.linalg.solve(np.eye(2)-np.array(a),d)
        np.testing.assert_allclose(base.observations[-1]["x"],solution,rtol=1e-10)
        np.testing.assert_allclose(changed.observations[-1]["x"],2*solution,rtol=1e-10)
        self.passed("ECO001")

        run,changed=self.check_case("ECO015",{"k0":2.},{"s":.34})
        self.assertEqual(run.observations[0]["k"],2)
        self.assertAlmostEqual(run.observations[-1]["k_star"],5**(1/.7))
        self.assertGreater(changed.observations[-1]["k"],run.observations[-1]["k"])
        self.passed("ECO015")

        run,changed=self.check_case("ECO017",{"k0":2.},{"A":.5})
        for row in run.observations:
            self.assertAlmostEqual(row["k_proj"],2*math.exp(row["g_theory"]*row["sim_t"]),places=10)
            self.assertAlmostEqual(row["k"],2*(1+.025*.1)**round(row["sim_t"]/.1),places=10)
        self.assertGreater(changed.observations[-1]["k"],run.observations[-1]["k"])
        self.passed("ECO017")

        run,changed=self.check_case("ECO019",{"x0":[.3,.6]},{"a":.05})
        self.assertTrue(all(r["wage_share"]>0 and r["employment"]>0 for r in run.observations))
        self.assertNotAlmostEqual(run.observations[-1]["wage_share"],changed.observations[-1]["wage_share"])
        self.passed("ECO019")

    def test_compartment_models_for_rates_mass_and_cohort_relationships(self):
        a,b=self.check_case("NET052",{"i0":.1,"N":100.},{"beta":0.})
        self.assertGreater(a.observations[-1]["I"],b.observations[-1]["I"])
        self.assertAlmostEqual(b.observations[-1]["I_frac"],.1*math.exp(-.2*3),places=5)
        self.passed("NET052")
        for mid in ("NET053","NET055"):
            a,b=self.check_case(mid,{"N":1000.,"I0":10.},{"beta":0.})
            self.assertTrue(all(abs(r["total"]-1000.)<1e-7 for r in a.observations))
            self.assertGreater(a.observations[-1]["I"],b.observations[-1]["I"])
            self.assertEqual(b.observations[-1]["S"],b.observations[0]["S"])
            self.passed(mid)
        a,b=self.check_case("NET061",{"N_per":400},{"beta":0.},states=True)
        self.assertAlmostEqual(a.observations[1]["E_total"],.1*.15*(8*390+4*400+400)*10/400)
        self.assertEqual(b.observations[-1]["E_total"],0.)
        for r in a.observations:
            self.assertAlmostEqual(sum(r[k] for k in ("S_total","E_total","I_total","R_total")),1200.)
        self.assertEqual(len(a.state_frames[0]["relations"]),9)
        self.passed("NET061")

    def test_motion_and_behavior(self):
        a,b=self.check_case("NET106",{"cells":80,"density":.28,"p":0.},{"p":1.},dt=1,states=True)
        self.assertGreater(a.observations[-1]["flux"],b.observations[-1]["flux"])
        ids={e["id"] for e in a.state_frames[0]["entities"]}
        for f in a.state_frames:
            entities=f["entities"]
            self.assertEqual({e["id"] for e in entities},ids)
            self.assertEqual(len({e["x"] for e in entities}),len(ids))
        self.passed("NET106")

        a,b=self.check_case("NET113",{"n":14,"v_des":1.2},{"v_des":.6},dt=.075,states=True)
        self.assertEqual(len(a.state_frames[0]["entities"]),14)
        self.assertTrue(all(o["alive"]+o["evacuated"]==14 for o in a.observations))
        self.assertNotEqual(a.state_frames[-1]["entities"],b.state_frames[-1]["entities"])
        self.passed("NET113")

        a,b=self.check_case("BEH001",{"size":13,"threshold":.4},{"threshold":0.},states=True)
        self.assertEqual(b.observations[-1]["unhappy_frac"],0.)
        self.assertEqual({e["id"] for e in a.state_frames[0]["entities"]},{e["id"] for e in a.state_frames[-1]["entities"]})
        self.passed("BEH001")

        a,b=self.check_case("BEH005",{"size":18,"n_agents":90,"n_cops":12,"legitimacy":.65},{"legitimacy":1.},states=True)
        self.assertTrue(all(o["mean_grievance"]==0 for o in b.observations))
        self.assertGreater(a.observations[-1]["mean_grievance"],0.)
        self.passed("BEH005")

        a,b=self.check_case("BEH016",{"n":24,"g":.2},{"g":1.},dt=1.)
        self.assertEqual(b.observations[0]["opinions"],b.observations[-1]["opinions"])
        self.assertLess(a.observations[-1]["spread"],a.observations[0]["spread"])
        self.passed("BEH016")

        a,b=self.check_case("BEH018",{"n":24,"d":1.,"mu":.25},{"mu":0.},dt=1.)
        self.assertEqual(b.observations[0]["opinions"],b.observations[-1]["opinions"])
        self.assertAlmostEqual(a.observations[0]["mean"],a.observations[-1]["mean"])
        self.assertLess(a.observations[-1]["spread"],a.observations[0]["spread"])
        self.passed("BEH018")

    def test_queue_mechanisms_and_conservation(self):
        a,b=self.check_case("SYS002",{"c":3,"lam":2.,"mu":1.},{"c":4},ticks=120)
        self.assertGreater(a.observations[-1]["Wq_erlangc"],b.observations[-1]["Wq_erlangc"])
        self.assertTrue(all(o["n_served"]<=o["n_service_starts"]<=o["n_arrived"] for o in a.observations))
        self.passed("SYS002")
        a,b=self.check_case("SYS003",{"c":2,"lam":3.,"mu":1.},{"c":4},ticks=120)
        self.assertAlmostEqual(a.observations[-1]["B_formula"],4.5/8.5)
        self.assertTrue(all(0<=o["blocked"]<=o["total"] for o in a.observations))
        self.assertLess(b.observations[-1]["B_formula"],a.observations[-1]["B_formula"])
        self.passed("SYS003")
        a,b=self.check_case("SYS006",{"lam":4.,"mu":2.},{"mu":1.},ticks=120)
        self.assertEqual(a.observations[-1]["L_little"],2.)
        self.assertEqual(b.observations[-1]["L_little"],4.)
        self.passed("SYS006")
        a,b=self.check_case("SYS007",{"lam":.55,"mu":1.},{"lam":.65},ticks=300)
        self.assertAlmostEqual(a.observations[-1]["Wq_md1"],.55/(2*.45))
        self.assertTrue(all(o["n_service_starts"]+o["n_waiting"]==o["n_arrived"] for o in a.observations))
        self.assertLess(a.observations[-1]["Wq_md1"],b.observations[-1]["Wq_md1"])
        self.passed("SYS007")
        a,b=self.check_case("SYS024",{"lam":3.,"mu":1.},{"lam":0.},ticks=150)
        self.assertTrue(all(o["conserv"]==0 for o in a.observations))
        self.assertEqual(b.observations[-1]["arrived"],0)
        self.passed("SYS024")

    def test_new_registration_and_explicit_numeric_models(self):
        ids="BEH074 BEH081 ECO038 ECO045 ECO067 ECO114 SYS005 SYS014 SYS026 SYS032 SYS040 SYS041".split()
        for mid in ids:
            self.assertEqual(param_contract(mid)["model_id"],mid)
        a=run_model_full("SYS005",{"lam":5.,"mu":1.,"c":1},ticks=150,dt=.1,seed=7).observations
        self.assertGreater(a[-1]["reneged"],0)
        self.assertTrue(all(r["served"]+r["waiting"]+r["reneged"]+r["in_service"]==r["arrived"] for r in a))
        a=run_model_full("SYS026",{"growth":[.2,0],"rates":[0,0]},ticks=10,dt=.1).observations
        self.assertAlmostEqual(a[-1]["stock"],math.exp(.2))
        a=run_model_full("SYS032",{"alpha":0.,"lam0":3.,"t_max":1.},ticks=20,dt=.1).observations
        self.assertEqual(a[-1]["E_integral"],3.)
        self.assertEqual(a[-1]["count"],a[10]["count"])
        a=run_model_full("ECO114",{"B0":20.,"E0":4.8},ticks=50,dt=.1).observations
        self.assertAlmostEqual(a[-1]["B"],20.)
        self.assertAlmostEqual(a[-1]["E"],4.8)
        with tempfile.TemporaryDirectory() as t, patch.dict(os.environ,{"DAYAN_DATA_DIR":t}):
            obs=[{"date":i,"x":x,"return":x/10} for i,x in enumerate([3,2,1,4,3,2,5,2])]
            ds=ingest(json.dumps(obs).encode(),name="numeric protocol fixture",format="json",source="offline test fixture")["dataset_id"]
            rr=run_model_full("ECO038",{"dataset_id":ds,"fields":["x"]},ticks=3)
            fit=np.linalg.lstsq([[1,o["x"]] for o in obs[:-1]],[o["x"] for o in obs[1:]],rcond=None)[0]
            self.assertAlmostEqual(rr.observations[1]["prediction"][0],fit[0]+fit[1]*obs[-1]["x"])
            self.assertEqual(rr.manifest["data_bindings"][0]["dataset_id"],ds)
            rr=run_model_full("ECO045",{"dataset_id":ds,"omega":.1,"alpha":.2,"beta":.4},ticks=3)
            self.assertAlmostEqual(rr.observations[0]["conditional_variance"],.25)
            self.assertAlmostEqual(rr.observations[1]["conditional_variance"],.1+.2*.3**2+.4*.25)
            with self.assertRaisesRegex(ValueError,"观测间隔"):
                run_model_full("ECO045",{"dataset_id":ds},ticks=1,dt=.2)


if __name__=="__main__":
    unittest.main(verbosity=2)
