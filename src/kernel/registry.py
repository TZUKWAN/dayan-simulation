"""R5 规约注册表（实验可引用，v2 设计 §7 R5）。

场景规约一旦用于产生实验结果，即应登记入册：
- 可引用：每个规约有唯一句柄（sha256 短哈希），论文/报告引用 `msim://spec/<handle>`
- 可检索：按包名/关键词/作者过滤
- 可审计：登记即固化内容哈希，后续改动即句柄变化（内容寻址）
- 幂等：同内容重复登记返回既有句柄

用法：
  from src.kernel.registry import register_spec, find_spec, get_spec, cite
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_DB = Path(os.environ.get('DAYAN_DATA_DIR', Path(__file__).resolve().parents[2] / 'data')) / 'spec_registry.json'


def _canonical(obj: Any) -> str:
    """规范化序列化（键排序，保证同内容同哈希）。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def spec_handle(canonical_str: str) -> str:
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()[:16]


@dataclass
class SpecEntry:
    handle: str
    name: str
    pack: str
    registered_at: float
    author: str
    tags: list[str]
    canonical: str          # 规范化内容（内容寻址）
    summary: str = ""
    n_experiments: int = 0  # 引用计数（实验登记时累加）

    def cite(self) -> str:
        return f"msim://spec/{self.handle}"


class SpecRegistry:
    """规约注册表：JSON 持久化，句柄=内容哈希。"""

    def __init__(self, db_path: Path | None = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB
        self._entries: dict[str, SpecEntry] = {}
        self._load()

    def _load(self):
        if self.db_path.exists():
            raw = json.loads(self.db_path.read_text(encoding="utf-8"))
            for h, d in raw.get("entries", {}).items():
                self._entries[h] = SpecEntry(**d)

    def _save(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path.write_text(json.dumps(
            {"entries": {h: vars(e) for h, e in self._entries.items()}},
            ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- 登记 ----------
    def register(self, scenario_yaml: str | dict, author: str = "msim",
                 tags: list[str] | None = None,
                 summary: str = "") -> SpecEntry:
        """登记规约（幂等：同内容返回既有句柄）。"""
        if isinstance(scenario_yaml, str):
            raw = yaml.safe_load(scenario_yaml)
        else:
            raw = scenario_yaml
        canon = _canonical(raw)
        handle = spec_handle(canon)
        if handle in self._entries:
            return self._entries[handle]  # 幂等
        entry = SpecEntry(
            handle=handle,
            name=raw.get("scenario", "未命名"),
            pack=raw.get("pack", "政治经济学包"),
            registered_at=time.time(),
            author=author,
            tags=tags or [],
            canonical=canon,
            summary=summary,
        )
        self._entries[handle] = entry
        self._save()
        return entry

    # ---------- 检索 ----------
    def get(self, handle: str) -> SpecEntry | None:
        return self._entries.get(handle)

    def find(self, pack: str | None = None, keyword: str | None = None,
             author: str | None = None) -> list[SpecEntry]:
        out = []
        for e in self._entries.values():
            if pack and e.pack != pack:
                continue
            if author and e.author != author:
                continue
            if keyword:
                blob = e.name + e.summary + " ".join(e.tags) + e.canonical
                if keyword not in blob:
                    continue
            out.append(e)
        return sorted(out, key=lambda e: e.registered_at)

    def cite(self, handle: str) -> str:
        e = self._entries[handle]
        return e.cite()

    def record_experiment(self, handle: str):
        """实验运行时累加引用计数。"""
        if handle in self._entries:
            self._entries[handle].n_experiments += 1
            self._save()

    def __len__(self):
        return len(self._entries)


# 便捷单例
_default: SpecRegistry | None = None


def default_registry() -> SpecRegistry:
    global _default
    if _default is None:
        _default = SpecRegistry()
    return _default
