"""Research contract checks; synthetic dataset IDs below are not empirical inputs."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dayan.research.compiler import compile_research
from dayan.research.requirements import extract_request
from dayan.research.semantics import registry
from dayan.output_contract import output_contract
from dayan.runtime import param_contract


class ResearchConstraints(unittest.TestCase):
    def test_curated_semantics_refer_to_real_output_and_parameter_fields(self):
        for mid,item in registry().items():
            fields=output_contract(mid)['fields']
            for name in list(item.get('outputs',{}))+([item['primary_metric']] if 'primary_metric' in item else []):
                self.assertIn(name,fields,(mid,name))
            for name in item.get('inputs',{}):self.assertIn(name,param_contract(mid)['params'],(mid,name))

    def test_variants_and_candidate_comparison_do_not_default_to_sis(self):
        for variant,mid in [('SIR','NET053'),('SEIR','NET055'),('SIS','NET052')]:
            result=compile_research(variant+'疫情传播，运行20步，种子7和8')
            self.assertIsNotNone(result.experiment_spec,result.warnings)
            self.assertEqual(result.experiment_spec.model_id,mid)
            self.assertGreater(len(result.candidates),1)
        self.assertIsNone(compile_research('研究疫情传播').experiment_spec)
        wrong=compile_research('NET052 研究SIR疫情传播')
        self.assertIsNone(wrong.experiment_spec)
        self.assertIn('SIR',' '.join(wrong.warnings))

    def test_negation_scope_and_real_multi_mechanism_gaps(self):
        text='武汉老人疏散，不要谣言传播，不要公交接驳，运行20步'
        request=extract_request(text)
        self.assertNotIn('信息传播',request['mechanisms'])
        self.assertNotIn('接驳运力',request['mechanisms'])
        self.assertIn('老年行动差异',request['mechanisms'])
        result=compile_research(text)
        self.assertIsNone(result.experiment_spec)
        self.assertIn('roads_dataset_id',' '.join(result.warnings))
        self.assertEqual(result.research_spec.space_scope,'武汉')
        self.assertIn('老人',result.research_spec.population)
        missing=compile_research('研究SIR疫情与谣言传播的共同演化')
        self.assertIsNone(missing.experiment_spec)
        self.assertTrue(missing.research_spec.mechanisms_missing)

    def test_exclusions_and_windows_are_actual_spec_constraints(self):
        result=compile_research('CPL001 老人疏散，不要谣言传播，不要公交接驳，运行20步',
            parameters={'roads_dataset_id':'UNIT-roads','population_dataset_id':'UNIT-people'})
        self.assertIsNotNone(result.experiment_spec,result.warnings)
        params=result.experiment_spec.baseline_params
        self.assertEqual((params['bus_count'],params['initial_rumor_fraction'],params['rumor_rate']),(0,0.,0.))
        window=compile_research('NET052 运行40步，步长0.1，analysis_window=[1,3]，warmup_ticks=2')
        self.assertEqual(window.experiment_spec.analysis_window,[1,3])
        self.assertNotIn('analysis_window',window.experiment_spec.baseline_params)

    def test_time_units_and_natural_language_routing(self):
        from dayan.agent.intent import plan_rule_based
        plan=plan_rule_based('SIR疫情传播，运行20步，种子7')
        self.assertEqual(plan['plan'][0]['args']['model_id'],'NET053')
        physical=compile_research('NET113行人疏散，持续2秒，步长0.1')
        self.assertEqual(physical.experiment_spec.ticks,20)
        ambiguous=compile_research('SIR疫情传播，持续2小时')
        self.assertIsNone(ambiguous.experiment_spec)
        self.assertIn('时间',' '.join(ambiguous.warnings))
        self.assertIsNone(compile_research('NET052 analysis_window=[3,1]').experiment_spec)


if __name__=='__main__':unittest.main(verbosity=2)
