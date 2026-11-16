"""遮蔽审计器（v2 设计·决策5 内建件，T8 产品化）。

扫描 LLM 交互文本中的理论词汇——命中即表示遮蔽设计被破坏（agent 可能
"表演理论"而非"涌现行为"）。设计承诺：理论词汇只出现在测量端，
永不出现在 agent 输入（prompt）中。

用法：
  from src.kernel.masking_audit import audit_texts, audit_llm_log
  hits = audit_llm_log(Path("results/.../llm_log.jsonl"))
"""
from __future__ import annotations

import json
from pathlib import Path

# 理论词汇黑名单（与 v0/v1 审计一致；马理论场景专用，其他学科包可扩展）
FORBIDDEN_DEFAULT = [
    "资本", "剥削", "剩余价值", "阶级", "异化", "拜物教", "马克思",
    "劳动价值", "商品拜物", "无产阶级", "资产阶级", "价值规律",
    "上层建筑", "经济基础", "历史唯物",
]


def audit_texts(texts: list[str], forbidden: list[str] | None = None) -> dict[str, int]:
    """返回 {命中词: 次数}；空 dict = 通过。"""
    forbidden = forbidden or FORBIDDEN_DEFAULT
    hits: dict[str, int] = {}
    blob = "\n".join(t for t in texts if t)
    for w in forbidden:
        n = blob.count(w)
        if n:
            hits[w] = n
    return hits


def audit_llm_log(log_path: str | Path,
                  forbidden: list[str] | None = None) -> dict[str, int]:
    """审计 LMStudioClient 的全量日志：所有 prompt 消息内容。"""
    texts: list[str] = []
    p = Path(log_path)
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            for m in rec.get("messages", []):
                texts.append(str(m.get("content", "")))
    return audit_texts(texts, forbidden)


def audit_agent_visibility(world_or_agents, forbidden: list[str] | None = None) -> dict[str, int]:
    """审计 agent 可见的一切处境文本（persona + 制度参数派生的描述）。

    polecon 类包：检查 persona trait 与决策情境中可能混入的理论词。
    """
    texts = []
    for a in world_or_agents:
        persona = getattr(a, "persona", None)
        if persona:
            texts.append(str(persona.get("trait", "")))
            texts.append(str(persona.get("name", "")))
    return audit_texts(texts, forbidden)
