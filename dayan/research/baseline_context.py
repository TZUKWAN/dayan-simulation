"""Restore the inputs and clock of a verified baseline for diagnostic evaluations."""
from copy import deepcopy
from types import SimpleNamespace


def restore(run_id):
    from .model_study_entry import baseline_proof
    from ..agent.model_design import load_design
    from ..agent.verification import _structured_execution
    from ..structured_inputs import binding_schema, prepare_bindings
    from ..custom_models import factory
    from ..solvers.codec import digest
    proof,saved=baseline_proof(run_id,allow_interventions=True)
    manifest=proof['manifest'];definition=manifest['model_definition']
    if digest(factory(proof['model_id']).definition)!=digest(definition):
        raise ValueError('当前模型与已审基线方程不同')
    execution=load_design(proof['design_id'])['execution']
    keys=set().union(*(branch['properties'] for branch in binding_schema()['oneOf']))
    bindings=[{key:value for key,value in row.items() if key in keys and value is not None}
              for row in execution.get('data_bindings',[])]
    bound,ports,evidence=prepare_bindings(bindings,proof['model_id'],definition.get('input_ports',{}))
    issues,_=_structured_execution(SimpleNamespace(manifest=manifest,checkpoint=saved.get('checkpoint')),
        {'data_bindings':evidence,'structured_inputs':{k:{'contract':p['contract'],'count':p['count']} for k,p in ports.items()}})
    params=deepcopy(manifest['actual']['effective_parameters'])
    if ([r for r in evidence if 'port' not in r]!=[r for r in manifest.get('data_bindings',[]) if 'port' not in r]
            or any(params.get(k)!=v for k,v in bound.items())):
        issues.append('同源真实输入的来源、转换或数值已变化')
    if issues:raise ValueError('；'.join(issues))
    return {'proof':proof,'definition':definition,'bound':bound,'parameters':params,
        'options':{'parameters':params,'data_bindings':bindings,
                   'interventions':deepcopy(execution.get('interventions',[])),
                   'ticks':manifest['actual']['n_steps'],'dt':manifest['actual']['dt_used'],
                   'experiment':manifest['requested']['experiment']}}
