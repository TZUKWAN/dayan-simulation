"""OpenAI-compatible legacy experiment client: adaptive capacity, cache and retries.

The default model remains configurable Qwen3.5-4B. Capacity is read from the
actual provider/loaded LM Studio instance; no implicit 200-token ceiling or
synthetic assistant thinking prefill is appended. Failed/truncated responses
are disclosed by caller fallback accounting and never cached as success.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests


class LMStudioClient:
    def __init__(self, base_url: str = "http://127.0.0.1:1234/v1",
                 model: str = "qwen3.5-4b",
                 cache_path: str | None = None,
                 max_workers: int = 6,
                 timeout: int = 300,
                 retries: int = 2,
                 default_max_tokens: int | None = None,
                 log_path: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.cache_path = Path(cache_path) if cache_path else None
        self.max_workers = max_workers
        self.timeout = timeout
        self.retries = retries
        self.default_max_tokens = default_max_tokens
        self.log_path = Path(log_path) if log_path else None
        self._cache: dict[str, str] = {}
        self._lock = threading.Lock()
        self.n_calls_http = 0
        self.n_cache_hits = 0
        self.n_fallbacks = 0
        if self.cache_path and self.cache_path.exists():
            with open(self.cache_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                        self._cache[rec["k"]] = rec["c"]
                    except Exception:
                        continue

    # ---------- 单次调用 ----------

    def chat(self, messages: list[dict], temperature: float = 0.2,
             max_tokens: int | None = None) -> str:
        requested = self.default_max_tokens if max_tokens is None else max_tokens
        messages = list(messages)
        from dayan.llm_limits import discover, allocation
        budget=allocation(messages,discover({'base_url':self.base_url,'model_id':self.model,'api_key':''}),requested)
        max_tokens=budget['max_tokens']
        key = self._key(messages, temperature, max_tokens)
        with self._lock:
            if key in self._cache:
                self.n_cache_hits += 1
                return self._cache[key]
        content = self._http(messages, temperature, max_tokens, budget)
        if not content:return ''  # Failed/truncated generations are never persisted as successful cache entries.
        with self._lock:
            self._cache[key] = content
            if self.cache_path:
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.cache_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"k": key, "c": content},
                                       ensure_ascii=False) + "\n")
        return content

    def _http(self, messages: list[dict], temperature: float,
              max_tokens: int | None, budget=None) -> str:
        payload = {"model": self.model, "messages": messages,
                   "temperature": temperature,
                   "stream": False}
        if max_tokens is not None:payload['max_tokens']=max_tokens
        last_err = None
        for attempt in range(self.retries + 1):
            try:
                with self._lock:self.n_calls_http += 1
                r = requests.post(f"{self.base_url}/chat/completions",
                                  json=payload, timeout=self.timeout)
                r.raise_for_status()
                data = r.json()
                msg = data["choices"][0]["message"]
                content = msg.get("content") or ""
                reasoning = msg.get("reasoning_content") or ""
                if self.log_path:
                    self._log(payload, content, reasoning, budget, data.get('usage'), data['choices'][0].get('finish_reason'))
                if data['choices'][0].get('finish_reason')=='length':
                    return ''  # The decider records a fallback; a truncated action is not a valid decision.
                if not content and reasoning:
                    # 思考耗尽预算：返回空，由上层回退规则
                    return ""
                return content
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(2 * (attempt + 1))
        if self.log_path:
            self._log(payload, f"__ERROR__:{last_err}", "")
        return ""

    def _log(self, payload: dict, content: str, reasoning: str, budget=None, usage=None, finish_reason=None):
        with self._lock:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "t": time.time(), "model": self.model,
                    "messages": payload["messages"],
                    "temperature": payload["temperature"],
                    "content": content, "reasoning": reasoning,
                    'allocation':budget,'usage':usage,'finish_reason':finish_reason,
                }, ensure_ascii=False) + "\n")

    def _key(self, messages, temperature, max_tokens) -> str:
        blob = json.dumps({"m": self.model, "msg": messages,
                           "t": temperature, "x": max_tokens},
                          ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()

    # ---------- 批量 ----------
    def batch(self, jobs: list[dict]) -> list[str]:
        """jobs: [{"messages": [...], "temperature":.., "max_tokens":..}, ...]
        返回与 jobs 等长的 content 列表（失败为空串）。"""
        if not jobs:
            return []
        if self.max_workers <= 1:
            return [self.chat(j["messages"], j.get("temperature", 0.2),
                              j.get("max_tokens")) for j in jobs]
        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            return list(ex.map(lambda j: self.chat(
                j["messages"], j.get("temperature", 0.2), j.get("max_tokens")), jobs))
