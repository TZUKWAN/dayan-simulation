"""Durable, input-bound stages for research design; never substitute a failed stage."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import time

from ..collection.storage import atomic_json
from ..limits import limits
from .stage_json import stage_object


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def stage_identity_inputs(inputs):
    """Canonical identity for machine JSON messages, without changing prompts.

    Ordinary object key order is not part of execution identity. DSL stock
    initializers are explicitly evaluated in declaration order, so retain that
    order. Keep arrays, literal user text, code and non-machine messages exact.
    Type tags avoid collisions between objects and arrays in this hash-only form.
    """
    def value_identity(value, *, ordered=False):
        if isinstance(value,dict):
            keys=list(value) if ordered else sorted(value)
            return ['object',[[key,value_identity(value[key],ordered=key=='initial_state')] for key in keys]]
        if isinstance(value,list):return ['array',[value_identity(item) for item in value]]
        return ['literal',value]

    if not isinstance(inputs,list):return inputs
    messages=deepcopy(inputs)
    for message in messages:
        if not isinstance(message,dict) or message.get('role')!='user' or not isinstance(message.get('content'),str):continue
        try:payload=json.loads(message['content'])
        except ValueError:continue
        if not isinstance(payload,dict) or 'original_request' not in payload:continue
        message['content']=json.dumps(value_identity(payload),ensure_ascii=False,allow_nan=False,separators=(',',':'))
    return messages


class PendingStage(Exception):
    """The next call can continue with the same request, design and execution settings."""


class DesignCheckpoint:
    def __init__(self, record, path, audit, deadline):
        self.record, self.path, self.audit, self.deadline = record, path, audit, deadline
        self.prior_audit = deepcopy(record.get("llm_calls", []))
        self.audit_start = len(audit)
        # A stage gets a fresh meaningful budget, not the few seconds left by five prior calls.
        from ..limits import authoring_wall_seconds
        budget=min(authoring_wall_seconds(),max(22.,deadline-time.monotonic()+20))
        self.stage_seconds=max(2.,(budget-20)*.8)

    def save(self):
        self.record["llm_calls"] = self.prior_audit + self.audit[self.audit_start:]
        self.record["updated_at"] = datetime.now(timezone.utc).isoformat()
        atomic_json(self.path, self.record)

    def cached(self, key, inputs):
        ident = digest({"step": key, "inputs": stage_identity_inputs(inputs)})
        for row in self.record["stages"]:
            if row.get("stage_id") == ident:
                if row.get("output_sha256") != digest(row["output"]):
                    raise ValueError("已保存阶段的内容校验失败：" + key)
                return ident, deepcopy(row["output"]), True
        return ident, None, False

    def begin(self, key, ident, seconds):
        self.record.update(current_stage=key, current_stage_id=ident)
        self.save()
        if self.deadline - time.monotonic() < seconds + 2:
            self.record["pause_reason"] = "next_stage_budget"
            raise PendingStage("本次剩余时间不足以完整执行下一阶段；已保存阶段将在续接时复用")
        self.record.update(status="reviewing", inflight={"step": key, "stage_id": ident,
                           "started_at": datetime.now(timezone.utc).isoformat(), "timeout_s": seconds})
        self.record.pop("pause_reason", None)
        self.save()

    def store(self, key, ident, value, call_id=None):
        self.record["stages"].append({"step": key, "stage_id": ident, "output": value,
                                      "output_sha256": digest(value), "call_id": call_id})
        self.record.pop("inflight", None)
        self.save()
        return deepcopy(value)

    def operation(self, key, inputs, run, *, seconds=None):
        ident, value, present = self.cached(key, inputs)
        if present:
            return value
        seconds = self.stage_seconds if seconds is None else seconds
        self.begin(key, ident, seconds)
        value = run(min(self.deadline - 2, time.monotonic() + seconds))
        return self.store(key, ident, value)

    def call(self, key, messages, validate, complete, *, purpose=None, thinking=None, feedback=None):
        ident, value, present = self.cached(key, messages)
        if present:
            return value
        failures = self.record.setdefault("stage_failures", {}).setdefault(ident, [])
        prior_invalid = [row for row in failures if row["kind"] == "validation"]
        scope = self.record.get("design_id")
        invalid = [row for row in prior_invalid if row.get("attempt_design_id", scope) == scope]
        attempts = 3 if key == "plan" else 2
        feedback = feedback or self.feedback
        messages = deepcopy(messages)
        for failure in prior_invalid:
            messages += [{"role": "assistant", "content": failure["response"]},
                         {"role": "user", "content": feedback(failure["error"])}]
        while len(invalid) < attempts:
            self.begin(key, ident, self.stage_seconds)
            try:
                raw = complete(messages, timeout=self.stage_seconds,
                               purpose=purpose or f"model-design-{key}", audit=self.audit,
                               thinking=True if thinking is None else thinking)
            except Exception as exc:
                transient = isinstance(exc, (TimeoutError, ConnectionError)) or bool(getattr(exc, "retryable", False))
                failure = {"kind": "transport" if transient else "provider", "error": f"{type(exc).__name__}: {exc}",
                           "step": key, "call_id": self.audit[-1].get("call_id") if self.audit else None}
                failures.append(failure)
                self.record.pop("inflight", None)
                self.save()
                if transient:
                    self.record["pause_reason"] = "transient_provider_error"
                    self.record["last_error"] = failure
                    raise PendingStage(failure["error"]) from exc
                raise
            obj = None
            try:
                obj, formatting = stage_object(raw)
                if formatting:
                    self.audit[-1]['json_format_recovery'] = formatting
                    failures.append({'kind': 'format_normalization', 'step': key, 'response': raw,
                                     'error': formatting['original_error'], 'normalization': formatting,
                                     'call_id': self.audit[-1].get('call_id')})
                if isinstance(obj.get("error"), str) and obj["error"].strip():
                    raise ValueError(obj["error"])
                value = validate(obj)
            except (ValueError, TypeError, KeyError, SyntaxError) as exc:
                if getattr(exc, "requires_design_revision", False):
                    self.record.pop("inflight", None)
                    self.record["implementation_error"] = str(exc)
                    self.save()
                    raise
                failure = {"kind": "validation", "error": f"{type(exc).__name__}: {exc}",
                           "step": key, "response": raw, "call_id": self.audit[-1].get("call_id"),
                           "attempt_design_id": scope}
                failures.append(failure)
                invalid.append(failure)
                self.audit[-1]["design_validation_error"] = str(exc)
                if isinstance(obj, dict):
                    self.audit[-1]["response_field_types"] = {name: type(item).__name__ for name, item in obj.items()}
                self.record.pop("inflight", None)
                self.save()
                if len(invalid) >= attempts:
                    raise ValueError("阶段定向修复后仍未通过：" + failure["error"]) from exc
                messages += [{"role": "assistant", "content": raw},
                             {"role": "user", "content": feedback(failure["error"])}]
                continue
            return self.store(key, ident, value, self.audit[-1]["call_id"])
        raise ValueError("阶段定向修复次数已耗尽，不能跳过未通过的阶段")

    @staticmethod
    def feedback(error):
        return f"回执校验：{error}。保持对同一问题的判断，输出所有必需顶层字段，逐字段修正后返回完整JSON对象。"
