"""Bind frozen scientific diagnostics to independently reviewed model paths.

Preparing a study does not require guessing whether a future model will use a
DSL rate or a managed program function. The scientific declaration remains
immutable; the approved plan supplies the later implementation mapping.
"""
from copy import deepcopy
import re

from ..solvers.codec import digest
from ..structured_inputs import _object,_text


def pending_bindings(specifications):
    return [spec for spec in specifications if spec.get('kind')=='ablation' and 'binding' in spec]


def _dynamic_path(path,kind):
    name=r'[A-Za-z][A-Za-z0-9_]{0,39}'
    if kind=='program':
        return bool(re.fullmatch(r'source\.'+name,path)) and path not in (
            'source.initialize','source.observe','source.frame','source.validate')
    return bool(re.fullmatch(r'(?:rates\.|agents\.update\.)'+name,path))


def plan_bindings(specifications,plan,provided):
    """Check exact diagnostic IDs and real evolution mappings at plan review."""
    required={spec['id'] for spec in pending_bindings(specifications)}
    if not required:
        if provided not in (None,[]):
            raise ValueError('没有待绑定消融，不能添加或替换诊断实现绑定')
        return []
    if not isinstance(provided,list) or len(provided)!=len(required):
        raise ValueError('须在方案diagnostic_bindings逐项绑定全部待定消融ID，不改研究科学声明')
    allowed={path for row in plan.get('rule_refs',[]) for path in row['paths']
             if _dynamic_path(path,plan['kind'])}
    result=[];seen=set()
    for row in provided:
        _object(row,('id','rule_refs','reason'),('id','rule_refs','reason'),'诊断实现绑定')
        ident=row['id']
        if not isinstance(ident,str) or ident not in required or ident in seen:
            raise ValueError('diagnostic_bindings须逐个对应冻结消融ID，不能增加、遗漏或重复')
        seen.add(ident)
        _text(row['reason'],'消融参数、实际方程与观测之间的绑定依据')
        refs=row['rule_refs']
        if (not isinstance(refs,list) or not refs or any(not isinstance(p,str) for p in refs)
                or len(set(refs))!=len(refs) or any(p not in allowed for p in refs)):
            raise ValueError('消融实现路径须属于方案实际演化rule_refs；参数标签、输出/帧和平台研究支撑不能替代动力学')
        result.append(deepcopy(row))
    return result


def resolve_bindings(specifications,plan,definition):
    """Resolve only approved mappings; never infer paths or alter scientific fields."""
    if not pending_bindings(specifications):return deepcopy(specifications),[]
    if not isinstance(plan,dict):
        raise ValueError('待定消融须先取得含diagnostic_bindings的获审方案，不能猜测实现路径')
    rows=plan_bindings(specifications,plan,plan.get('diagnostic_bindings'))
    if plan['kind']!=definition['kind']:
        raise ValueError('诊断实现绑定的模型类型与获审方案不符')
    mappings={row['id']:row for row in rows}
    from ..scene_contract import reference
    reachable=None
    if definition['kind']=='program':
        from ..program_evidence import reachable as program_reachable
        reachable=program_reachable(definition,'advance')
    result=[]
    for declaration in specifications:
        spec=deepcopy(declaration)
        if spec['id'] in mappings:
            refs=mappings[spec['id']]['rule_refs']
            for path in refs:
                reference(definition,path)
                if reachable is not None and path[7:] not in reachable:
                    raise ValueError('消融实现函数必须由实际advance可达，不能插入伪调用或改科学要求：'+path)
            spec.pop('binding')
            spec['rule_refs']=deepcopy(refs)
        result.append(spec)
    return result,rows


def binding_evidence(declarations,resolved,mappings,baseline,definition):
    """Same immutable study records both scientific and implementation versions."""
    return {'version':'dayan-diagnostic-implementation-binding-v1',
        'design_id':baseline['design_id'],'plan_sha256':baseline['plan_sha256'],
        'model_definition_sha256':digest(definition),'declarations_sha256':digest(declarations),
        'resolved_sha256':digest(resolved),'mappings':deepcopy(mappings),
        'scope':'获审方案到真实演化路径的实现映射；科学参数/机制/指标/尺度/判据仍为原事前声明，不证明经验因果'}
