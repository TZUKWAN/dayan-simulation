"""Resolve client context from its immutable run archive before planning or compiling."""


def canonical_context(last_run):
    context=dict(last_run or {})
    if not context.get('run_id'):return context
    from ..run_store import get_store
    actual=get_store().load(context['run_id']);manifest=actual['manifest']
    return {'run_id':actual['run_id'],'model_id':actual['model_id'],'manifest':manifest,
            'params':manifest.get('actual',{}).get('effective_parameters',{}),
            'ticks':manifest.get('requested',{}).get('ticks'),'dt':manifest.get('requested',{}).get('dt'),
            'seed':manifest.get('rng',{}).get('seed')}
