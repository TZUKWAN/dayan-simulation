"""交易叙事物化测量管道（H9b）与阶级意识问卷管道（H9a）。"""
from __future__ import annotations

import re


from ..ledger.economy import Agent, World
from .alienation import _clean  # 复用清洗
from .survey import (build_fet_judge_prompt, build_survey_judge_prompt,
                     build_survey_prompt, build_transaction_prompt,
                     parse_fet, parse_survey_judge)


def _clean(t: str) -> str:
    if not t:
        return ""
    return re.sub(r"^[\s\"'“”]+|[\s\"'“”]+$", "", t.strip())[:300]


class TransactionPipeline:
    """交易叙事 → 物化评分（LLM-judge，失败回退中性 3 分并标注）。"""

    def __init__(self, client):
        self.client = client

    def run_round(self, ags: list[Agent], world: World, tick: int) -> list[dict]:
        if not ags:
            return []
        jobs = [{"messages": build_transaction_prompt(a, world),
                 "temperature": 0.8,
                 "max_tokens": self.client.default_max_tokens} for a in ags]
        texts = self.client.batch(jobs)
        jjobs = [{"messages": build_fet_judge_prompt(_clean(t)),
                  "temperature": 0.1,
                  "max_tokens": self.client.default_max_tokens} for t in texts]
        jud = self.client.batch(jjobs)
        rows = []
        for a, t_raw, j_raw in zip(ags, texts, jud):
            narr = _clean(t_raw)
            if not narr:
                continue
            sc = parse_fet(j_raw)
            rows.append({"tick": tick, "agent": a.id, "position": a.position,
                         "income": round(a.income, 2), "narrative": narr,
                         "fetishism": sc["fetishism"] if sc else 3,
                         "source": "llm_judge" if sc else "fallback"})
        return rows


class SurveyPipeline:
    """阶级意识问卷（H9a）：4 题开放作答 → 评定（公平感/矛盾感/预期/归因）。"""

    def __init__(self, client):
        self.client = client

    def run(self, ags: list[Agent], world: World, tick: int) -> list[dict]:
        if not ags:
            return []
        jobs = [{"messages": build_survey_prompt(a, world),
                 "temperature": 0.7,
                 "max_tokens": self.client.default_max_tokens} for a in ags]
        answers = self.client.batch(jobs)
        import json as _json
        parsed = []
        for t in answers:
            try:
                m = re.search(r"\{.*\}", re.sub(r"```(?:json)?", "", t or ""), re.S)
                parsed.append(_json.loads(m.group(0)) if m else {})
            except Exception:
                parsed.append({})
        jjobs = [{"messages": build_survey_judge_prompt(p),
                  "temperature": 0.1,
                  "max_tokens": self.client.default_max_tokens} for p in parsed]
        jud = self.client.batch(jjobs)
        rows = []
        for a, ans, j_raw in zip(ags, parsed, jud):
            sc = parse_survey_judge(j_raw) or {}
            rows.append({"tick": tick, "agent": a.id, "position": a.position,
                         "income": round(a.income, 2),
                         "q1": ans.get("q1", ""), "q2": ans.get("q2", ""),
                         "q3": ans.get("q3", ""), "q4": ans.get("q4", ""),
                         "fairness": sc.get("fairness"),
                         "conflict": sc.get("conflict"),
                         "optimism": sc.get("optimism"),
                         "attribution": sc.get("attribution", "uncoded")})
        return rows
