"""异化测量管道：叙事生成（LLM）→ Seeman 五维量表打分（LLM 评定员 + 关键词回退）。

说明：
- Seeman 五维（1959, ASR）：无力感 powerlessness、无意义感 meaninglessness、
  无规范感 normlessness、孤立感 isolation、自我疏离 self-estrangement。
- 打分由同一本地模型担任评定员（LLM-as-judge）；4B 模型的评定信度有限，
  因此：每条记录标注 source=llm_judge | keyword_fallback，报告层给出两种
  来源的组间对比与信度提示；抽样引入人工复核通道（人工结果另行录入）。
- 量表词汇只出现在测量端，不进入 agent 的叙事输入（遮蔽设计）。
"""
from __future__ import annotations

import re

from ..agents.decisions import (build_judge_prompt, build_narrative_prompt,
                                parse_scores)
from ..ledger.economy import Agent, World

DIM_KEYS = ["powerlessness", "meaninglessness", "normlessness",
            "isolation", "self_estrangement"]

# 关键词回退计分（极简启发式，仅在评定失败时使用并标注）
KW = {
    "powerlessness": ["没办法", "不得不", "做不了主", "由不得", "只能听", "身不由己", "轮不到我"],
    "meaninglessness": ["没意思", "不知道图什么", "白干", "没有意义", "瞎忙", "为什么而做"],
    "normlessness": ["各顾各", "没个准", "规矩没用", "看运气", "钻空子", "没章法"],
    "isolation": ["没人", "一个人", "孤单", "生分", "靠不上", "没人商量"],
    "self_estrangement": ["不像自己", "麻木", "耗着", "无所谓", "不像我想做的", "熬"],
}


def keyword_fallback_scores(narrative: str) -> dict:
    out = {}
    for k, words in KW.items():
        score = 1
        for w in words:
            if w in narrative:
                score += 2
                break
        # 句子越短且含消极词，分略升（简化）
        out[k] = min(5, score)
    return out


class AlienationPipeline:
    def __init__(self, client):
        self.client = client

    def run_round(self, ags: list[Agent], world: World, tick: int) -> list[dict]:
        if not ags:
            return []
        # 1) 叙事
        jobs = [{"messages": build_narrative_prompt(a, world),
                 "temperature": 0.8,
                 "max_tokens": self.client.default_max_tokens} for a in ags]
        narratives = self.client.batch(jobs)
        # 2) 评定
        jjobs = []
        for n in narratives:
            n_clean = _clean(n)
            jjobs.append({"messages": build_judge_prompt(n_clean),
                          "temperature": 0.1,
                          "max_tokens": self.client.default_max_tokens})
        judgements = self.client.batch(jjobs)
        rows = []
        for a, n_raw, j_raw in zip(ags, narratives, judgements):
            narr = _clean(n_raw)
            if not narr:
                continue
            scores = parse_scores(j_raw)
            source = "llm_judge"
            if scores is None:
                scores = keyword_fallback_scores(narr)
                source = "keyword_fallback"
            row = {"tick": tick, "agent": a.id, "position": a.position,
                   "skill": round(a.skill, 3), "income": round(a.income, 2),
                   "savings": round(a.savings, 2),
                   "narrative": narr, "source": source, **scores,
                   "total": sum(scores[k] for k in DIM_KEYS)}
            rows.append(row)
        return rows


def _clean(text: str) -> str:
    if not text:
        return ""
    t = text.strip()
    t = re.sub(r"^[\s\"'“”]+|[\s\"'“”]+$", "", t)
    return t[:300]
