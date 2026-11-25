"""Turn genuine implementation failures into audited revisions of the same research."""
from copy import deepcopy
from datetime import datetime, timezone
import uuid

from ..access import data_root
from ..collection.storage import atomic_json, file_lock, read_json
from .design_checkpoint import digest


class ImplementationMismatch(ValueError):
    requires_design_revision = True

    def __init__(self, message, evidence, definition):
        super().__init__(message)
        self.evidence = evidence
        self.definition = definition


def _inherit_failure_feedback(child, parent_id):
    """Keep every rejected response, but give an explicit revision its own budget."""
    for rows in child.get("stage_failures", {}).values():
        for row in rows:
            if row.get("kind") == "validation":
                row.setdefault("attempt_design_id", parent_id)


def record_feedback(design, definition, error, audit=()):
    record = {"design_id": design["design_id"], "plan_sha256": design["plan_sha256"],
              "source_fingerprint": design["source_fingerprint"], "error": str(error),
              "evidence": error.evidence, "definition": definition, "llm_calls": list(audit)}
    ident = digest(record)
    folder = data_root() / "model_design_feedback" / design["design_id"]
    with file_lock(folder / "feedback.lock", timeout=.1):
        atomic_json(folder / (ident + ".json"), {"feedback_id": ident, "record": record})
        atomic_json(folder / "latest.json", {"feedback_id": ident})
    from ..research.model_memory import remember_failure
    remember_failure(design,ident,record)
    return ident


def fork_revision(parent_id, source, execution, session_id, memory_scope, *, revise_proposal=False):
    from .model_design import approved_plan,load_design,_path
    parent=load_design(parent_id,session_id)
    if revise_proposal:
        return _fork_proposal_revision(parent,source,execution,session_id,memory_scope)
    if parent.get('status')=='blocked':
        return _fork_blocked_revision(parent,source,execution,session_id,memory_scope)
    parent = approved_plan(parent_id, source, execution, session_id,record=parent)
    if parent.get("memory_scope") != memory_scope:
        raise ValueError("修订方案的研究记忆归属与原方案不一致")
    folder = data_root() / "model_design_feedback" / parent_id
    if not (folder / "latest.json").is_file():
        raise ValueError('该获批方案尚无已保存的实际编译/预检否决反馈；先按同design_id执行validate_model或build_model，'
                         '收到revision_required后沿其next_action修订，不能无依据复审或重建缩减任务')
    ident = read_json(folder / "latest.json")["feedback_id"]
    if not isinstance(ident, str) or len(ident) != 64 or any(c not in "0123456789abcdef" for c in ident):
        raise ValueError("无有效的实际编译反馈编号")
    evidence = read_json(folder / (ident + ".json"))
    feedback = evidence["record"]
    if (evidence.get("feedback_id") != ident or digest(feedback) != ident or feedback["design_id"] != parent_id
            or feedback["plan_sha256"] != parent["plan_sha256"]
            or feedback["source_fingerprint"] != parent["source_fingerprint"]):
        raise ValueError("实际编译反馈校验失败，不能据此修订方案")
    index = folder / ("revision-" + ident + ".json")
    with file_lock(index.with_suffix(".lock"), timeout=.1):
        if index.exists():
            return read_json(index)["design_id"]
        child = deepcopy(parent)
        _inherit_failure_feedback(child, parent_id)
        for key in ("plan", "plan_sha256", "review", "approval_scope", "error", "pause_reason", "last_error", "inflight"):
            child.pop(key, None)
        child.update(design_id="MD-" + uuid.uuid4().hex, status="reviewing", resume_available=True,
                     created_at=datetime.now(timezone.utc).isoformat(), revision_of=parent_id,
                     implementation_feedback={"feedback_id": ident, **feedback, "prior_plan": parent["plan"]})
        child["llm_calls"] = list({row["call_id"]: row for row in [*child.get("llm_calls", []),
                                                                *feedback.get("llm_calls", [])]}.values())
        child["stages"] = [stage for stage in child["stages"] if stage["step"] not in ("plan", "review")]
        atomic_json(_path(child["design_id"]), child)
        atomic_json(index, {"design_id": child["design_id"]})
        return child["design_id"]


def _fork_proposal_revision(parent,source,execution,session_id,memory_scope):
    """Explicitly revise Agent choices; user constraints and research stay frozen."""
    from .model_design import _path
    from ..source_version import source_fingerprint
    from ..research.requirements import extract_request
    if (parent.get('status') not in ('approved','blocked') or parent.get('request')!=source
            or parent.get('session_id')!=session_id or parent.get('memory_scope')!=memory_scope
            or parent.get('source_fingerprint')!=source_fingerprint()):
        raise ValueError('提案修订须保留原文、会话、研究归属和当前平台版本')
    previous=parent['execution']
    if digest(previous)!=parent['execution_sha256']:
        raise ValueError('父方案执行设置校验失败')
    if previous.get('research') or execution.get('research'):
        raise ValueError('已冻结科研协议不能用提案修订改变参数、网格、种子或检验规则')
    mutable={'parameters','ticks','dt','seed','seeds','effective_inputs'}
    if {k:v for k,v in previous.items() if k not in mutable}!={k:v for k,v in execution.items() if k not in mutable}:
        raise ValueError('提案修订只调整自主参数与采样设置；数据/场景/来源/干预合同不能悄然替换')
    parsed=extract_request(source)
    for key,value in parsed['options'].items():
        if key in mutable and execution.get(key)!=value:
            raise ValueError('不能改变用户原话明确指定的运行设置：'+key)
    for key,value in parsed['parameters'].items():
        if execution.get('parameters',{}).get(key)!=value:
            raise ValueError('不能改变用户原话明确指定的参数：'+key)
    changes={key:{'before':previous.get(key),'after':execution.get(key)} for key in mutable
             if previous.get(key)!=execution.get(key)}
    if not changes:
        raise ValueError('自主运行设置没有变化；实际编译/方案否决沿普通revise_from修订')
    if parent.get('plan') and digest(parent['plan'])!=parent.get('plan_sha256'):
        raise ValueError('父方案内容校验失败')
    for stage in parent.get('stages',[]):
        if digest(stage['output'])!=stage['output_sha256']:
            raise ValueError('父方案阶段内容校验失败')
    feedback={'design_id':parent['design_id'],'phase':'execution_proposal_revision',
              'parent_sha256':digest(parent),'source_fingerprint':parent['source_fingerprint'],
              'error':'自主提出的运行设置已显式修订；重新核对方案与数值检验，保留完整原话和用户固定值',
              'evidence':{'changes':changes,'previous_execution_sha256':parent['execution_sha256'],
                          'current_execution_sha256':digest(execution)},'prior_plan':parent.get('plan'),'llm_calls':[]}
    ident=digest(feedback)
    folder=data_root()/'model_design_feedback'/parent['design_id']
    index=folder/('proposal-'+ident+'.json')
    with file_lock(index.with_suffix('.lock'),timeout=.1):
        if index.exists():return read_json(index)['design_id']
        child=deepcopy(parent)
        _inherit_failure_feedback(child, parent['design_id'])
        for key in ('plan','plan_sha256','review','approval_scope','error','pause_reason','last_error','inflight',
                    'continuation_note','current_stage','current_stage_id'):
            child.pop(key,None)
        child.update(design_id='MD-'+uuid.uuid4().hex,status='reviewing',resume_available=True,
                     created_at=datetime.now(timezone.utc).isoformat(),revision_of=parent['design_id'],
                     execution=deepcopy(execution),execution_sha256=digest(execution),
                     implementation_feedback={'feedback_id':ident,**feedback})
        child['stages']=[s for s in child['stages'] if s['step'].startswith('literature_')]
        atomic_json(folder/(ident+'.json'),{'feedback_id':ident,'record':feedback})
        atomic_json(_path(child['design_id']),child)
        atomic_json(index,{'design_id':child['design_id']})
        return child['design_id']


def _fork_blocked_revision(parent,source,execution,session_id,memory_scope):
    """Revise saved design rejection, preserving the original task and valid work."""
    from .model_design import check_design_context,_path
    parent_id=parent['design_id']
    extension=check_design_context(parent,parent_id,source,execution,session_id,allow_source_evidence=True)
    if parent.get('memory_scope')!=memory_scope:raise ValueError('修订方案的研究记忆归属与原方案不一致')
    review=parent.get('review',{})
    reasons=review.get('issues') or ([parent['error']] if parent.get('error') else [])
    if not reasons or review.get('approved'):
        raise ValueError('修订须有已保存的实际方案否决，不能无依据重复审查')
    if parent.get('plan') and parent.get('plan_sha256')!=digest(parent['plan']):
        raise ValueError('被否决方案内容校验失败')
    for stage in parent.get('stages',[]):
        if stage.get('output_sha256')!=digest(stage.get('output')):
            raise ValueError('被否决方案已保存阶段内容校验失败')
    feedback={'design_id':parent_id,'phase':'design_review_rejection','source_fingerprint':parent['source_fingerprint'],
        'parent_sha256':digest(parent),'error':'；'.join(reasons),'evidence':{'review':review,'error':parent.get('error')},
        'prior_plan':parent.get('plan'),'llm_calls':[]}
    if extension:feedback['source_context_extension']=extension
    ident=digest(feedback)
    folder=data_root()/'model_design_feedback'/parent_id
    index=folder/('revision-'+ident+'.json')
    with file_lock(index.with_suffix('.lock'),timeout=.1):
        if index.exists():return read_json(index)['design_id']
        child=deepcopy(parent)
        _inherit_failure_feedback(child, parent_id)
        for key in ('plan','plan_sha256','review','approval_scope','error','pause_reason','last_error','inflight',
                    'continuation_note','current_stage','current_stage_id'):
            child.pop(key,None)
        child.update(design_id='MD-'+uuid.uuid4().hex,status='reviewing',resume_available=True,
            created_at=datetime.now(timezone.utc).isoformat(),revision_of=parent_id,
            implementation_feedback={'feedback_id':ident,**feedback})
        child['execution']=deepcopy(execution);child['execution_sha256']=digest(execution)
        child['stages']=[] if extension else [stage for stage in child['stages']
                         if stage['step'] not in ('revision','evidence_recheck','plan','review')]
        atomic_json(folder/(ident+'.json'),{'feedback_id':ident,'record':feedback})
        atomic_json(_path(child['design_id']),child)
        atomic_json(index,{'design_id':child['design_id']})
        return child['design_id']
