"""Read-only assistant responses grounded in actual run context and live tool capabilities."""
import json


def explain(request,last_run=None,history=None):
    from ..llm_client import complete
    context={};source_id=None
    if last_run and last_run.get('run_id'):
        from ..run_store import get_store
        record=get_store().load(last_run['run_id']);source_id=record['run_id']
        rows=record.get('observations') or []
        context={'run_id':source_id,'model_id':record['model_id'],'manifest':record['manifest'],
                 'first_observation':rows[0] if rows else None,'last_observation':rows[-1] if rows else None,
                 'observations_count':len(rows)}
    if any(word in request for word in ('你能做什么','支持哪些功能','有哪些功能','你是谁','你好')):
        from .tools import TOOL_IMPL
        from ..model_index import ALL_INDEX
        return {'ok':True,'payload':{'reply':f'大衍助手当前登记{len(ALL_INDEX)}个模型运行入口（包含原型与方法例题）。可执行的工具有：'+
                 '、'.join(sorted(TOOL_IMPL))+ '。具体空间建模会检查主体、设施、行为及画面对应关系；模型科学适用性需另行验证。',
                 'source_run_id':source_id,'llm_calls':[],'mode':'capability_facts'}}
    audit=[]
    reply=complete([{'role':'system','content':'你是大衍的只读研究解释助手。依据所提供的真实归档回答，清楚区分观察、机制假设与因果结论。未提供的结果不能编造，不能声称重新运行、创建模型、采集数据或改变了画面。没有数据时只能解释一般方法。用简洁中文。'},
                    {'role':'user','content':json.dumps({'question':request,'history':(history or [])[-8:],'actual_context':context},ensure_ascii=False)}],
                   max_tokens=2200,timeout=60,purpose='explain-archived-result',audit=audit)
    return {'ok':True,'payload':{'reply':reply,'source_run_id':source_id,'llm_calls':audit,'mode':'explanation'}}
