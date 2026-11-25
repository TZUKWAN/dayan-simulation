"""Static, non-executing evidence for program interfaces and state observations.

This is a structural dependency check, not a proof of the model's mathematics.
Opaque observations must expose their named state dependencies at the interface;
the numerical algorithm itself remains ordinary isolated Python.
"""
import ast
from dataclasses import dataclass, field


def functions(definition):
    source=definition['source']
    return {node.name:node for node in ast.parse(source).body if isinstance(node,ast.FunctionDef)}


def fragments(definition):
    return {name:ast.get_source_segment(definition['source'],node) for name,node in functions(definition).items()}


def reachable(definition, entry):
    funcs=functions(definition)
    seen=set()
    def visit(name):
        if name in seen or name not in funcs:return
        seen.add(name)
        for node in ast.walk(funcs[name]):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name):visit(node.func.id)
    visit(entry)
    return seen


@dataclass
class Value:
    deps: set = field(default_factory=set)
    roots: set = field(default_factory=set)
    members: dict = field(default_factory=dict)
    literals: set = field(default_factory=set)
    items: tuple | None = None


def union(values):
    values=list(values)
    keys=set().union(*(v.members.keys() for v in values))
    items=None
    if values and all(v.items is not None for v in values):
        lengths={len(v.items) for v in values}
        if len(lengths)==1:
            items=tuple(union(v.items[index] for v in values) for index in range(next(iter(lengths))))
    return Value(set().union(*(v.deps for v in values)),set().union(*(v.roots for v in values)),
                 {key:union(v.members[key] for v in values if key in v.members) for key in keys},
                 set().union(*(v.literals for v in values)),items)


class Dependencies:
    def __init__(self, definition):
        self.functions=functions(definition)
        self.writes=set()
        self.stack=[]

    def call(self, name, args, kwargs=None):
        if name not in self.functions or name in self.stack:return union(args)
        fn=self.functions[name]
        names=[a.arg for a in [*fn.args.posonlyargs,*fn.args.args]]
        env=dict(zip(names,args))
        env.update({key:value for key,value in (kwargs or {}).items() if key in names})
        self.stack.append(name)
        try:
            values=self.block(fn.body,env)
        finally:self.stack.pop()
        result=union(values)
        keys=set().union(*(v.members.keys() for v in values))
        result.members={key:union(v.members[key] for v in values if key in v.members) for key in keys}
        return result

    def expr(self,node,env):
        if node is None:return Value()
        if isinstance(node,ast.Name):return env.get(node.id,Value())
        if isinstance(node,ast.Constant):
            return Value(literals={node.value} if type(node.value) in (str,int,bool) else set())
        if isinstance(node,(ast.List,ast.Tuple)):
            items=tuple(self.expr(child,env) for child in node.elts)
            return Value(union(items).deps,items=items)
        if isinstance(node,ast.Dict):
            members={}
            for key,value in zip(node.keys,node.values):
                val=self.expr(value,env)
                if key is None:members.update(val.members)
                elif isinstance(key,ast.Constant) and isinstance(key.value,str):members[key.value]=val
            return Value(union(members.values()).deps,members=members)
        if isinstance(node,ast.Subscript):
            obj=self.expr(node.value,env)
            keys=self.expr(node.slice,env).literals
            if obj.items is not None:
                chosen=[obj.items[key] for key in keys if type(key) is int and -len(obj.items)<=key<len(obj.items)]
                selected=chosen or obj.items
                return selected[0] if len(selected)==1 else union(selected)
            if keys and all(isinstance(key,str) and key in obj.members for key in keys):
                selected=[obj.members[key] for key in keys]
                return selected[0] if len(selected)==1 else union(selected)
            names={key for key in keys if isinstance(key,str)}
            roots={key if root=='' else root for root in obj.roots for key in names} if names else obj.roots
            return Value({r for r in roots if r}|obj.deps|self.expr(node.slice,env).deps,roots)
        if isinstance(node,ast.Attribute):
            obj=self.expr(node.value,env)
            if node.attr in ('shape','size'):
                return Value({r+'#count' for r in obj.roots if r})
            return obj
        if isinstance(node,ast.IfExp):
            left,right=self.expr(node.body,env),self.expr(node.orelse,env)
            value=union([left,right,self.expr(node.test,env)])
            value.roots=left.roots & right.roots
            return value
        if isinstance(node,ast.BinOp):
            if isinstance(node.op,ast.Mult) and any(isinstance(n,ast.Constant) and n.value==0 for n in (node.left,node.right)):
                return Value()
            return Value(self.expr(node.left,env).deps|self.expr(node.right,env).deps)
        if isinstance(node,ast.Call):
            args=[self.expr(arg,env) for arg in node.args]
            kwargs={kw.arg:self.expr(kw.value,env) for kw in node.keywords if kw.arg is not None}
            allargs=[*args,*kwargs.values()]
            if isinstance(node.func,ast.Name):
                if node.func.id in self.functions:return self.call(node.func.id,args,kwargs)
                if node.func.id=='dict' and len(args)==1:
                    value=args[0]
                    return Value(set(value.deps),set(value.roots),dict(value.members),set(value.literals),value.items)
                if node.func.id=='len' and args:return Value({r+'#count' for r in args[0].roots if r})
                if node.func.id=='enumerate' and len(args)==1 and args[0].items is not None:
                    return Value(items=tuple(Value(items=(Value(literals={index}),item))
                                             for index,item in enumerate(args[0].items)))
            method=self.expr(node.func.value,env) if isinstance(node.func,ast.Attribute) else Value()
            if isinstance(node.func,ast.Attribute):
                if node.func.attr=='update':
                    entries={**(args[0].members if args else {}),**kwargs}
                    for key,value in entries.items():
                        self.assign(ast.Subscript(value=node.func.value,slice=ast.Constant(key),ctx=ast.Store()),value,env)
                    return Value() # dict.update mutates its target and returns None.
                if node.func.attr in ('items','keys','values') and method.members:
                    pairs=tuple(Value(items=(Value(literals={key}),value)) for key,value in method.members.items())
                    return Value(items=pairs if node.func.attr=='items' else tuple(pair.items[0 if node.func.attr=='keys' else 1] for pair in pairs))
                if (node.func.attr in ('tolist','astype')
                        or node.func.attr=='copy' and not args):
                    # These array representations preserve the collection's
                    # cardinality; exporting them cannot turn a fixed count
                    # into evidence for a changing mechanism.
                    return Value(method.deps|union(allargs).deps,set(method.roots),dict(method.members),set(method.literals),method.items)
                if (isinstance(node.func.value,ast.Name) and node.func.value.id=='copy'
                        and node.func.attr in ('copy','deepcopy') and len(args)==1):
                    value=args[0]
                    return Value(set(value.deps),set(value.roots),dict(value.members),set(value.literals),value.items)
            if isinstance(node.func,ast.Attribute) and node.func.attr in ('append','extend','insert','pop','remove','clear','resize'):
                self.writes.update(method.roots|{r+'#count' for r in method.roots if r})
            return Value(union([*allargs,method]).deps)
        if isinstance(node,(ast.ListComp,ast.SetComp,ast.GeneratorExp,ast.DictComp)):
            if isinstance(node,ast.DictComp) and len(node.generators)==1:
                generator=node.generators[0];iterator=self.expr(generator.iter,env)
                if iterator.items is not None and len(iterator.items)<=128:
                    members={}
                    for item in iterator.items:
                        local=dict(env);self.assign(generator.target,item,local)
                        keys=self.expr(node.key,local).literals
                        value=self.expr(node.value,local)
                        for key in keys:
                            if isinstance(key,str):members[key]=value
                    return Value(union(members.values()).deps,members=members)
            local=dict(env)
            inputs=[]
            for gen in node.generators:
                val=self.expr(gen.iter,local)
                self.assign(gen.target,val,local)
                inputs.extend(self.expr(test,local) for test in gen.ifs)
            val=self.expr(node.value if isinstance(node,ast.DictComp) else node.elt,local)
            return Value(union([val,*inputs]).deps)
        return Value(union(self.expr(child,env) for child in ast.iter_child_nodes(node)).deps)

    def assign(self,target,val,env,*,augmented=False):
        if isinstance(target,ast.Name):env[target.id]=val
        elif isinstance(target,(ast.Tuple,ast.List)):
            if val.items is not None and len(val.items)==len(target.elts):
                for part,item in zip(target.elts,val.items):self.assign(part,item,env)
            else:
                for part in target.elts:self.assign(part,val,env)
        elif isinstance(target,ast.Subscript):
            obj=self.expr(target.value,env)
            keys={key for key in self.expr(target.slice,env).literals if isinstance(key,str)}
            roots={key if root=='' else root for root in obj.roots for key in keys} if keys else obj.roots
            changed=roots if augmented else roots-val.roots
            self.writes.update(r for r in changed if r)
            if not augmented and '' in obj.roots:
                self.writes.update(r+'#count' for r in changed if r)
            if keys and not obj.roots:
                for key in keys:obj.members[key]=val
                obj.deps.update(val.deps)

    def block(self,body,env):
        returns=[]
        for node in body:
            if isinstance(node,ast.Assign):
                val=self.expr(node.value,env)
                for target in node.targets:self.assign(target,val,env)
            elif isinstance(node,ast.AnnAssign):self.assign(node.target,self.expr(node.value,env),env)
            elif isinstance(node,ast.AugAssign):
                if isinstance(node.value,ast.Constant) and node.value.value==0 and isinstance(node.op,(ast.Add,ast.Sub)):continue
                val=Value(self.expr(node.target,env).deps|self.expr(node.value,env).deps)
                self.assign(node.target,val,env,augmented=True)
            elif isinstance(node,ast.Return):returns.append(self.expr(node.value,env))
            elif isinstance(node,ast.If):
                left,right=dict(env),dict(env)
                returns+=self.block(node.body,left)+self.block(node.orelse,right)
                for key in left.keys()|right.keys():
                    values=[x[key] for x in (left,right) if key in x]
                    val=union(values)
                    names=set().union(*(v.members.keys() for v in values))
                    val.members={name:union(v.members[name] for v in values if name in v.members) for name in names}
                    env[key]=val
            elif isinstance(node,(ast.For,ast.While)):
                items=self.expr(node.iter,env) if isinstance(node,ast.For) else None
                if items is not None and items.items is not None and len(items.items)<=128:
                    for item in items.items:
                        self.assign(node.target,item,env)
                        returns+=self.block(node.body,env)
                    returns+=self.block(node.orelse,env)
                else:
                    if items is not None:self.assign(node.target,items,env)
                    returns+=self.block(node.body,env)+self.block(node.orelse,env)
            elif isinstance(node,(ast.With,ast.Try)):
                returns+=self.block(node.body,env)
                if isinstance(node,ast.Try):
                    for handler in node.handlers:returns+=self.block(handler.body,env)
                    returns+=self.block(node.orelse,env)+self.block(node.finalbody,env)
            elif isinstance(node,ast.Expr):self.expr(node.value,env)
        return returns


def state_dependencies(definition):
    analyzer=Dependencies(definition)
    initial=analyzer.call('initialize',[Value(),Value(),Value()])
    analyzer.writes.clear()
    root=Value(roots={''},members={key:Value(deps={key},roots={key}) for key in initial.members})
    arguments=[root,Value(),Value(),Value(),Value(),Value()]
    if definition.get('decision_policy') is not None:arguments.append(Value())
    outcome=analyzer.call('advance',arguments)
    # Returning a new state dictionary is as real a transition as in-place writes.
    newstate=outcome.members.get('state',Value())
    replaced=set()
    for key,val in newstate.members.items():
        if key not in val.roots:
            analyzer.writes.add(key)
            replaced.add(key)
    updated=set(analyzer.writes)
    observed=analyzer.call('observe',[root,Value(),Value(),Value()])
    # Replacing a collection in a returned state can change cardinality, just as
    # state[key] = new_collection can. In-place value updates and unchanged
    # carried-forward collections still do not substantiate a count mechanism.
    # This traces a possible dependency, not proof that its length really changed.
    for value in observed.members.values():
        updated.update(dep for dep in value.deps if dep.endswith('#count') and dep[:-6] in replaced)
    # Fixed population column lengths are validated by the runtime at every
    # frame. Copying/replacing their values cannot prove a count mechanism.
    exported=analyzer.call('frame',[root,Value(),Value(),Value()])
    groups=exported.members.get('populations',Value()).items or ()
    fixed={g['id'] for g in definition.get('populations',[]) if not g['dynamic']}
    fixed_roots=set()
    for group in groups:
        if group.members.get('id',Value()).literals & fixed:
            for value in group.members.get('columns',Value()).members.values():fixed_roots.update(value.roots)
    updated.difference_update(key+'#count' for key in fixed_roots if key)
    return {'updated_fields':sorted(updated),
            'observables':{key:sorted(observed.members[key].deps) for key in sorted(observed.members)}}


def check_plan(plan, definition):
    from .scene_contract import reference
    from .agent.design_revision import ImplementationMismatch
    active=reachable(definition,'advance')
    if definition.get('decision_policy') is not None:
        active|=reachable(definition,'decision_requests')  # A real runtime entry, not a fabricated call from advance.
    invalid=[]
    for entry in [*plan.get('rule_refs',[]),*plan.get('support_refs',[])]:
        for path in entry['paths']:
            if not path.startswith(('execution.','state_frames.')):
                try:reference(definition,path)
                except ValueError as exc:invalid.append(str(exc))
    if invalid:
        raise ImplementationMismatch('；'.join(dict.fromkeys(invalid))+'；实际顶层函数：'+', '.join(sorted(fragments(definition)))+
                         '。核对获批方案与实际实现，修正全部路径；后续研究职责引用真实execution.research，不在baseline伪造评分函数。',
            {'phase':'program_plan_references','invalid_references':list(dict.fromkeys(invalid)),
             'actual_functions':sorted(fragments(definition)),
             'instruction':'按真实定义和原文定向修订获批方案或实现，保留全部科学要求。不能只改说明、增加空函数或无效调用来满足路径。'},definition)
    for entry in plan.get('rule_refs',[]):
        if not any(path.startswith('source.') and path[7:] in active for path in entry['paths']):
            raise ImplementationMismatch('程序机制没有引用实际advance可达的函数：'+entry['mechanism'],
                {'phase':'program_plan_references','mechanism':entry['mechanism'],'paths':entry['paths'],
                 'advance_reachable_functions':sorted(active),
                 'instruction':'若为模型动力学，修订真实advance实现及其观测验收；若为初始化、观察或后续平台研究，'
                               '修订方案为相应support_refs/coverage职责，研究用实际execution.research。'
                               '保留原文、方程和数值目标，禁止为过路径检查而插入无关计算、零乘状态或无效函数调用。'},definition)
    evidence=state_dependencies(definition)
    changed=set(evidence['updated_fields'])
    criteria={row['id']:row for row in plan['criteria']}
    for row in plan['coverage']:
        if row['role']!='mechanism':continue
        selected=[criteria[cid] for cid in row['criteria']]
        # Event criteria deliberately have no observation fields. Their exact
        # counts/times/payloads are verified against the actual runtime log by
        # agent.verification, not fabricated as observe() state dependencies.
        # Reachable rule references and the separate state criteria still apply.
        if selected and all(c.get('check') in ('event_count','event_time','event_value') for c in selected):continue
        fields={field for criterion in selected for field in criterion['fields']}
        if any(changed & set(evidence['observables'].get(field,[])) for field in fields):continue
        raise ImplementationMismatch('程序机制验收未读取可追踪的实际演化状态：'+row['quote'],
            {'requirement':row['quote'],'criteria':row['criteria'],'state_dependencies':evidence,
             'instruction':'保留原变量含义与数值目标；将observe写为按真实状态求值的具名指标字典，'
                           '可调用纯函数；主体数、时间、常数或0乘状态不能替代动力学验收。'},definition)
    return evidence
