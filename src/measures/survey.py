"""阶级意识问卷（H9a，遮蔽版）+ 商品拜物教话语测量（H9b）。

遮蔽设计：问题与评定标准中不出现任何理论词汇；
"意识/拜物教"只存在于测量端命名。
"""
from __future__ import annotations

import re

from ..ledger.economy import Agent, World

# ---------- H9a 阶级意识问卷（4 题开放作答 + LLM 评定） ----------
SURVEY_SYSTEM = ("你是微型社会模拟中的居民。根据亲身经历简要回答四个问题，"
                 "只输出JSON：{\"q1\":\"...\",\"q2\":\"...\",\"q3\":\"...\",\"q4\":\"...\"}，"
                 "每题一两句话。")

SURVEY_Q = {
    "q1": "你觉得现在干活的报酬和你的付出相比，公平吗？",
    "q2": "镇上有人赚的钱比他们付出的劳动多。你觉得这多出来的部分是从哪儿来的？",
    "q3": "你和东家（或者帮工、合伙人）之间，利益是一致的还是有矛盾？",
    "q4": "你觉得五年后自己的处境会比现在好吗？",
}

SURVEY_JUDGE_SYSTEM = ("你是测评员。根据四条回答按1-5打分，只输出JSON："
                       "{\"fairness\":n,\"conflict\":n,\"optimism\":n,\"attribution\":\"labor|luck_skill|structure\"}。"
                       "标准：fairness=报酬公平感（1=非常不公平，5=非常公平）；"
                       "conflict=感知到的利益矛盾强度（1=完全一致，5=尖锐对立）；"
                       "optimism=未来改善预期（1=不可能更好，5=一定会更好）；"
                       "attribution=对'多出来的钱'的归因：labor=靠经营者自己的劳动，"
                       "luck_skill=靠运气或本事，structure=靠别人干活/制度安排。")


def build_survey_prompt(ag: Agent, world: World) -> list[dict]:
    pos_desc = {
        "worker": "受雇干活", "self": "自己干自己的活", "employer": "雇人经营",
        "member": "生产合作社社员", "unemployed": "暂时没有活计",
    }.get(ag.position, ag.position)
    msg = f"你的身份：{pos_desc}；上期到手{ag.income:.1f}；积蓄{ag.savings:.1f}。\n" + \
        "\n".join(f"{k}. {v}" for k, v in SURVEY_Q.items())
    return [{"role": "system", "content": SURVEY_SYSTEM},
            {"role": "user", "content": msg}]


def build_survey_judge_prompt(answers: dict) -> list[dict]:
    body = "\n".join(f"{k}. {answers.get(k, '')}" for k in SURVEY_Q)
    return [{"role": "system", "content": SURVEY_JUDGE_SYSTEM},
            {"role": "user", "content": body}]


def parse_survey_judge(text: str) -> dict | None:
    if not text:
        return None
    m = re.search(r"\{[^{}]*\}", re.sub(r"```(?:json)?", "", text), re.S)
    if not m:
        return None
    import json
    try:
        d = json.loads(m.group(0))
    except Exception:
        return None
    out = {}
    for k in ("fairness", "conflict", "optimism"):
        try:
            v = int(float(d.get(k)))
            if not 1 <= v <= 5:
                return None
            out[k] = v
        except (TypeError, ValueError):
            return None
    attr = str(d.get("attribution", "")).strip().lower()
    out["attribution"] = attr if attr in ("labor", "luck_skill", "structure") else "uncoded"
    return out


# ---------- H9b 拜物教话语（交易叙事 → 物化评分，指示器） ----------
TRANS_SYSTEM = ("你是微型社会模拟中的居民。用第一人称写两三句话，描述你最近一次买卖"
                "或者和东家/帮工/社员结算的经历：东西和钱怎么易手的，对方是个什么样的人。"
                "只输出正文，不要说明。")

FET_JUDGE_SYSTEM = ("你是测评员。按1-5评定这段陈述的\"物化程度\""
                    "（1=完全从人的关系与选择讲这件事，5=几乎只讲物和钱在流转、"
                    "人像物件一样被带过）。只输出JSON：{\"fetishism\":n}")


def build_transaction_prompt(ag: Agent, world: World) -> list[dict]:
    pos_desc = {
        "worker": "你是帮工", "self": "你自营", "employer": "你是经营者",
        "member": "你是合作社社员", "unemployed": "你暂时没有活计",
    }.get(ag.position, ag.position)
    msg = f"{pos_desc}；上期到手{ag.income:.1f}；市场参考物价{world.p_ref:.2f}/件。请写两三句。"
    return [{"role": "system", "content": TRANS_SYSTEM},
            {"role": "user", "content": msg}]


def build_fet_judge_prompt(narrative: str) -> list[dict]:
    return [{"role": "system", "content": FET_JUDGE_SYSTEM},
            {"role": "user", "content": f"陈述：{narrative}\n\n只输出JSON。"}]


def parse_fet(text: str) -> dict | None:
    if not text:
        return None
    m = re.search(r"\{[^{}]*\}", re.sub(r"```(?:json)?", "", text), re.S)
    if not m:
        return None
    import json
    try:
        d = json.loads(m.group(0))
        v = int(float(d.get("fetishism")))
        if 1 <= v <= 5:
            return {"fetishism": v}
    except Exception:
        return None
    return None
