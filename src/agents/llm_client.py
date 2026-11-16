"""LM Studio OpenAI 兼容客户端：缓存 + 重试 + 线程池批量。

要点：
- 只对接本地 LM Studio（默认 http://127.0.0.1:1234/v1），模型固定为
  Qwen3.5-4B（用户指定，机器性能约束，不使用其他模型）。
- 该模型为 reasoning 模型且服务端强制思考：预留思考预算（max_tokens），
  解析 message.content；reasoning_content 一并记录入日志供审计。
- 响应缓存（JSONL）：键 = sha1(model+messages+temp+max_tokens)。
  同一 prompt 重跑命中缓存，保证"可复现性"在实践中可负担。
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
                 default_max_tokens: int = 200,
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
    THINK_PREFILL = "<think>\n\n</think>\n\n"

    def chat(self, messages: list[dict], temperature: float = 0.2,
             max_tokens: int | None = None) -> str:
        max_tokens = max_tokens or self.default_max_tokens
        # 预填充空 think 块：实测使 Qwen3.5 关闭思考（0.2s/6token vs 6-11s/600+token），
        # 属推理加速手段，不改变模型对 prompt 的语义输入（遮蔽设计不受影响）。
        messages = list(messages) + [{"role": "assistant",
                                      "content": self.THINK_PREFILL}]
        key = self._key(messages, temperature, max_tokens)
        with self._lock:
            if key in self._cache:
                self.n_cache_hits += 1
                return self._cache[key]
        content = self._http(messages, temperature, max_tokens)
        with self._lock:
            self._cache[key] = content
            if self.cache_path:
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.cache_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"k": key, "c": content},
                                       ensure_ascii=False) + "\n")
        return content

    def _http(self, messages: list[dict], temperature: float,
              max_tokens: int) -> str:
        payload = {"model": self.model, "messages": messages,
                   "temperature": temperature, "max_tokens": max_tokens,
                   "stream": False}
        last_err = None
        for attempt in range(self.retries + 1):
            try:
                self.n_calls_http += 1
                r = requests.post(f"{self.base_url}/chat/completions",
                                  json=payload, timeout=self.timeout)
                r.raise_for_status()
                data = r.json()
                msg = data["choices"][0]["message"]
                content = msg.get("content") or ""
                reasoning = msg.get("reasoning_content") or ""
                if self.log_path:
                    self._log(payload, content, reasoning)
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

    def _log(self, payload: dict, content: str, reasoning: str):
        with self._lock:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "t": time.time(), "model": self.model,
                    "messages": payload["messages"],
                    "temperature": payload["temperature"],
                    "content": content, "reasoning": reasoning[:4000],
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
