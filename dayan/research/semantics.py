"""Source-reviewed semantic mappings; never infer physical equivalence from names."""
from functools import lru_cache
import json
from pathlib import Path
import re


@lru_cache(maxsize=1)
def registry():
    return json.loads((Path(__file__).resolve().parents[2]/'data/model_semantics.json').read_text(encoding='utf-8'))['models']


def candidates(request):
    from ..model_index import ALL_INDEX
    from ..output_contract import output_contract
    required=set(request['mechanisms'])
    text=request.get('positive_text',request['original_text'])
    rows=[]
    for mid, semantic in registry().items():
        covered=set(semantic['mechanisms'])
        if mid not in ALL_INDEX or not required or not (required & covered):continue
        schema=output_contract(mid)
        requested=request.get('metric')
        matches=list(re.finditer(semantic.get('match','(?!)'),text,re.I))
        missing=sorted(required-covered)
        score=10*len(required & covered)-20*len(missing)+len(matches)
        rows.append({'model_id':mid,'runnable':True,'mechanism':sorted(covered),
                     'missing_mechanisms':missing,'score':score,'matched_terms':[m.group() for m in matches],
                     'description':semantic['description'],'clock':semantic['clock'],
                     'output_fields':list(schema['fields']),'requested_metric_supported':not requested or requested in schema['fields'],
                     'required_data':semantic.get('required_data',[]),
                     'fidelity':'unverified','basis':'源码语义映射；运行工厂与静态输出合同不构成科学有效性证明'})
    return sorted(rows,key=lambda r:(-r['score'],r['model_id']))


def port(mid,field,direction):
    return registry().get(mid,{}).get(direction,{}).get(field)
