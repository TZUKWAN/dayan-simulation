"""Bounded real chat-completion calls; no scripted response fallback."""
from __future__ import annotations

import hashlib
import json
import os
import time
from copy import deepcopy
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LLMServiceError(RuntimeError):
    def __init__(self, message, *, retryable=False):
        super().__init__(message)
        self.retryable = retryable


def configuration():
    cfg_path = ROOT / "dayan" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    return {"api_key": os.environ.get("DAYAN_API_KEY", cfg.get("api_key", "")),
            "base_url": os.environ.get("DAYAN_BASE_URL", cfg.get("base_url", "")),
            "model_id": os.environ.get("DAYAN_MODEL", cfg.get("model_id", "")),
            **{key:cfg[key] for key in ('context_window','max_output_tokens') if key in cfg}}


def configured():
    cfg=configuration()
    return all(cfg.get(k) for k in ('api_key','base_url','model_id'))


def json_object(raw, *, whole=False):
    if whole:
        text = raw.strip().removeprefix("\ufeff")
        if text.startswith(("```json\n", "```\n")) and text.endswith("```"):
            text = text.split("\n", 1)[1][:-3].strip()
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM须返回完整JSON对象。第 {exc.lineno} 行、第 {exc.colno} 列：{exc.msg}") from None
        if not isinstance(value, dict):
            raise ValueError("LLM须返回单个JSON对象")
        return value
    decoder = json.JSONDecoder()
    for pos, char in enumerate(raw):
        if char == "{":
            try:
                value, _ = decoder.raw_decode(raw[pos:])
                if isinstance(value, dict):
                    return value
            except json.JSONDecodeError:
                continue
    raise ValueError("LLM未返回可解析的JSON对象")


def complete(messages, *, max_tokens=None, temperature=.2, timeout=180,
             purpose="chat", audit=None, thinking=None):
    cfg = configuration()
    if not all(cfg.get(k) for k in ('api_key','base_url','model_id')):
        raise RuntimeError("未配置真实LLM服务；不会使用固定脚本代替")
    if not 0 < timeout <= 3600:
        raise ValueError("LLM调用预算超出允许范围")
    if not isinstance(messages,list) or not messages or any(not isinstance(row,dict) for row in messages):
        raise ValueError('LLM messages须为非空消息对象列表')
    messages=deepcopy(messages)
    runtime_clock=datetime.now(timezone.utc).isoformat(timespec='seconds')
    clock_note=('DAYAN平台本次调用的实际系统时钟 UTC='+runtime_clock+'。'
        '这是平台墙上时钟，不是仿真时间；研究时期、模型t=0和历史情境仍按用户原文。'
        '核对采集/文件时间时使用此记录，不以模型内置或训练资料中的当前日期判断数据来自未来。'
        '系统时钟记录不证明源方数据发布时间、当时可得性或时钟已由外部服务校准。')
    if messages[0].get('role')=='system' and isinstance(messages[0].get('content'),str):
        messages[0]['content']+='\n\n'+clock_note
    else:
        messages.insert(0,{'role':'system','content':clock_note})
    from .llm_limits import discover,allocation
    budget=allocation(messages,discover(cfg),max_tokens)
    payload = {"model": cfg["model_id"], "messages": messages,
               "temperature": temperature}
    if budget['max_tokens'] is not None:payload['max_tokens']=budget['max_tokens']
    host=urlsplit(cfg["base_url"]).hostname or ""
    structured=purpose in {"planner","build-model","explain-archived-result"}
    mode=thinking if thinking is not None else (False if structured else None)
    if mode is not None and cfg["model_id"].lower().startswith("deepseek-v4"):
        if host.endswith(".maas.aliyuncs.com") or host=="dashscope.aliyuncs.com":
            payload["enable_thinking"]=bool(mode)
        elif host=="api.deepseek.com":
            payload["thinking"]={"type":"enabled" if mode else "disabled"}
    if (mode is False and (purpose.startswith("model-design-") or purpose=='program-actor-decision')
            and ("enable_thinking" in payload or "thinking" in payload)):
        payload["response_format"] = {"type": "json_object"}
    record = {"call_id": "LLM-" + uuid.uuid4().hex, "purpose": purpose,
              "model": cfg["model_id"], "created_at": datetime.now(timezone.utc).isoformat(),
              "runtime_clock_utc":runtime_clock,"runtime_clock_source":"platform_system_clock",
              "request_sha256": hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
              **budget, "ok": False}
    if "enable_thinking" in payload:record["enable_thinking"]=payload["enable_thinking"]
    if "thinking" in payload:record["thinking"]=payload["thinking"]
    if "response_format" in payload:record["response_format"]=payload["response_format"]
    started = time.monotonic()
    try:
        req = urllib.request.Request(cfg["base_url"].rstrip("/") + "/chat/completions",
                                     data=json.dumps(payload).encode(), method="POST",
                                     headers={"Authorization": "Bearer " + cfg["api_key"], "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                cap=max(8*1024*1024,min(64*1024*1024,(budget['max_tokens'] or 262144)*24))
                body = response.read(cap+1)
                if len(body)>cap:raise RuntimeError('LLM响应超过与模型输出能力匹配的字节预算')
                data = json.loads(body)
        except urllib.error.HTTPError as exc:
            # Do not expose credentials, request headers, or provider diagnostic URLs.
            raise LLMServiceError(f"LLM服务HTTP {exc.code}",
                                  retryable=exc.code in (408, 425, 429, 500, 502, 503, 504)) from None
        except urllib.error.URLError:
            raise LLMServiceError("LLM连接暂时不可用", retryable=True) from None
        choice = data["choices"][0]
        content = choice["message"].get("content")
        record.update(provider_request_id=data.get("id"), usage=data.get("usage"),
                      finish_reason=choice.get("finish_reason"))
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(f"LLM返回空正文（finish_reason={choice.get('finish_reason')}）")
        if choice.get("finish_reason") == "length":
            raise RuntimeError("LLM达到输出预算，结果不完整")
        record.update(ok=True, response_sha256=hashlib.sha256(content.encode()).hexdigest())
        return content
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        record["duration_s"] = round(time.monotonic() - started, 3)
        log_dir = Path(os.environ.get("DAYAN_DATA_DIR", ROOT / "data")) / "llm_calls"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / (record["call_id"] + ".json")).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        if audit is not None:
            audit.append(record)
