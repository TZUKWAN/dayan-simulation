"""Bounded real chat-completion calls; no scripted response fallback."""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def configuration():
    cfg_path = ROOT / "dayan" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    return {"api_key": os.environ.get("DAYAN_API_KEY", cfg.get("api_key", "")),
            "base_url": os.environ.get("DAYAN_BASE_URL", cfg.get("base_url", "")),
            "model_id": os.environ.get("DAYAN_MODEL", cfg.get("model_id", ""))}


def configured():
    return all(configuration().values())


def json_object(raw):
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


def complete(messages, *, max_tokens=8192, temperature=.2, timeout=60,
             purpose="chat", audit=None, thinking=None):
    cfg = configuration()
    if not all(cfg.values()):
        raise RuntimeError("未配置真实LLM服务；不会使用固定脚本代替")
    if not 1 <= max_tokens <= 32768 or not 0 < timeout <= 180:
        raise ValueError("LLM调用预算超出允许范围")
    payload = {"model": cfg["model_id"], "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens}
    host=urlsplit(cfg["base_url"]).hostname or ""
    structured=purpose in {"planner","build-model","explain-archived-result"}
    mode=thinking if thinking is not None else (False if structured else None)
    if mode is not None and cfg["model_id"].lower().startswith("deepseek-v4"):
        if host.endswith(".maas.aliyuncs.com") or host=="dashscope.aliyuncs.com":
            payload["enable_thinking"]=bool(mode)
        elif host=="api.deepseek.com":
            payload["thinking"]={"type":"enabled" if mode else "disabled"}
    record = {"call_id": "LLM-" + uuid.uuid4().hex, "purpose": purpose,
              "model": cfg["model_id"], "created_at": datetime.now(timezone.utc).isoformat(),
              "request_sha256": hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
              "max_tokens": max_tokens, "ok": False}
    if "enable_thinking" in payload:record["enable_thinking"]=payload["enable_thinking"]
    if "thinking" in payload:record["thinking"]=payload["thinking"]
    started = time.monotonic()
    try:
        req = urllib.request.Request(cfg["base_url"].rstrip("/") + "/chat/completions",
                                     data=json.dumps(payload).encode(), method="POST",
                                     headers={"Authorization": "Bearer " + cfg["api_key"], "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body = response.read(8 * 1024 * 1024 + 1)
                if len(body) > 8 * 1024 * 1024:
                    raise RuntimeError("LLM响应超过8MiB")
                data = json.loads(body)
        except urllib.error.HTTPError as exc:
            # Do not expose credentials, request headers, or provider diagnostic URLs.
            raise RuntimeError(f"LLM服务HTTP {exc.code}") from None
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
