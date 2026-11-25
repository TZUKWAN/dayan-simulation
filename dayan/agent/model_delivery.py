"""Existing platform delivery interfaces supplied to every model-review phase."""


def delivery_contract(research=None):
    empirical=bool(research and research.get('research_intent_id'))
    result={
        'report_tool':'research_report' if empirical else 'report_run',
        'report_input':('same MS study_id after research_finalize' if empirical else
                        'actual accepted run_id; full comparison reports also pass experiment_id or analysis_id, exclusively'),
        'report_phase':('after actual calibration, diagnostics, holdout and selected-result run' if empirical
                        else 'after accepted run is archived'),
        'format':'Word DOCX with actual equations, observations and same-result figures',
        'replay':{
            'state_url':'/api/runs/{display_run_id}/state?sample_every=1',
            'run_url':'/api/runs/{display_run_id}',
            'workbench_url':'/?run={display_run_id}',
            'controller':'DAYAN_RESULTS.restore(display_run_id, {userRequested:true})',
            'display_run_id':('run_id actually returned by research_finalize, not the default-parameter baseline'
                              if empirical else 'actual accepted run_id'),
            'source':'same run_id archived state_frames and observations; viewer does not create model dynamics',
            'limits':'bounded playback may sample display times/entities; complete saved states remain in the run archive/bundle',
            'scene_scope':'render actual model coordinates/facilities/actions when present; stocks-only results do not invent people or terrain'
        },
        'bundle_url':'/api/runs/{display_run_id}/bundle.zip',
        'bundle_contents':['manifest.json','observations.json','state_frames.json','events.json','checkpoint.json'],
        'archive_policy':'实际运行通过原定验收后归档；回放、图、报告和运行包核对同一结果run_id，不能用基线代替所选参数结果',
        'evidence_phase':'这些是已实现的接口合同；具体run_id、状态、报告及实际可用性仍须运行后核验'
    }
    if empirical:
        result['research']={
            'study_url':'/api/research/studies/{study_id}',
            'report_index':'reports in the same study response contain actual report_id, file hashes and figure assets',
            'file_url':'/api/research/studies/{study_id}/reports/{report_id}/files/{filename}',
            'files':['research.docx','research.md','research.facts.json','predictions.csv',
                     'candidate_trials.csv','diagnostics.csv','reproducibility.zip'],
            'optional_files':{'source_evidence.json':'published when actual source text is attached through research_model_context'},
            'reproducibility_contents':['actual study protocol and state','actual candidate/seed trials and failures',
                'diagnostic protocol, reports and actual trial files','target/input original files and dataset records',
                'selected_result actual archive files','reports, same-evidence figures and CSVs',
                'attached source text, hashes and original files when present'],
            'hash_verification':'check each downloaded file against its actual SHA256 in the report index',
            'limits':'attach source text through research_model_context before approval; collecting a separate DS alone does not add it to this study'
        }
    else:
        from ..limits import limits
        result['comparisons']={
            'experiment_tool':'experiment',
            'experiment_inputs':['model_id','parameters','ticks','dt','seeds','interventions','metric','data_bindings'],
            'experiment_output':'actual experiment_id and member run_ids; paired seed comparisons',
            'new_model_arguments':{'baseline_run_id':'actual accepted baseline run_id','arms':'[{label,params,interventions}]',
                'metric':'actual model observable','seeds':'selected paired seeds within the resource contract'},
            'new_model_dispatch':{'action':'execute','tool':'experiment'},
            'baseline_scope':'同一已审基线恢复方程、时钟、数据与原干预；参数对照明确列为处理，不另选预置模型；MI研究沿原冻结科研流程',
            'report_tool':'report_run',
            'report_arguments':{'run_id':'actual member run_id','experiment_id':'returned experiment_id'},
            'analysis_report_arguments':{'run_id':'actual member run_id','analysis_id':'saved analysis group ID'},
            'configured_max_seeds':limits().seeds,
            'scope':'报告读取同组全部实际运行与程序分析；单个成员用于选择场景，不以单条轨迹冒充重复均值或区间',
            'hypotheses':'零效应/负效应均如实交付；研究假设是否成立与模型代码/输入/数值约束是否正确分开，不能强迫结果符合预期方向',
            'planning':'写明实际多seed/多情景接口及报告归属；数量按资源合同选择，先完成可执行方案，额外重复可分批扩展'
        }
    return result
