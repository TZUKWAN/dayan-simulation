"""LLM 管线集成测试（MockClient，零网络）：
决策解析回退、叙事-评定管线、问卷管线、双通道落盘、守恒。
运行：python tests/test_pipeline.py
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.decisions import LLMBatchDecider  # noqa: E402
from src.agents.persona import make_personas  # noqa: E402
from src.ledger.economy import Agent, Params, World  # noqa: E402
from src.measures.alienation import AlienationPipeline  # noqa: E402
from src.measures.transaction import SurveyPipeline, TransactionPipeline  # noqa: E402


class MockClient:
    """按 prompt 内容返回罐头输出的假客户端。"""

    def __init__(self):
        self.default_max_tokens = 200
        self.calls = 0

    def batch(self, jobs):
        out = []
        for j in jobs:
            self.calls += 1
            sysmsg = j["messages"][0]["content"]
            user = j["messages"][-1]["content"]
            if "居民。根据处境做决定" in sysmsg or "经营者" in sysmsg and "JSON" in sysmsg \
                    and "wage" in user:
                out.append('{"action":"self"}')
            elif "第一人称写" in sysmsg and "买卖" not in sysmsg:
                out.append("我觉得活是自己安排的，心里踏实。")
            elif "买卖" in sysmsg or "结算" in sysmsg:
                out.append("昨天把货拉到集市，钱货两清，各拿各的。")
            elif "测评员" in sysmsg and "物化" in sysmsg:
                out.append('{"fetishism":3}')
            elif "测评员" in sysmsg and "五" in sysmsg or "五个心理方面" in sysmsg:
                out.append('{"powerlessness":2,"meaninglessness":2,"normlessness":1,'
                           '"isolation":1,"self_estrangement":2}')
            elif "四个问题" in sysmsg:
                out.append('{"q1":"还行","q2":"靠本事","q3":"没什么矛盾","q4":"会更好"}')
            elif "四条回答" in sysmsg:
                out.append('{"fairness":3,"conflict":2,"optimism":4,'
                           '"attribution":"luck_skill"}')
            else:
                out.append("")
        return out


def make_world(n=10, **pkw):
    rng = random.Random(1)
    personas = make_personas(n, rng)
    agents = []
    for i in range(n):
        agents.append(Agent(i, personas[i], 0.8 + 0.04 * i, 15.0, llm=True,
                            dec_offset=i % 4))
    return World(Params(**pkw), agents)


def main():
    world = make_world()
    client = MockClient()
    decider = LLMBatchDecider(client, stats={"llm": 0, "fallback": 0})
    from src.agents.decisions import rule_decision
    for t in range(6):
        req = world.collect_decision_requests(t)
        dec = decider.decide_batch([world.agent(i) for i in req], world)
        for a in world.agents:
            if a.id not in dec:
                dec[a.id] = rule_decision(a, world)
        world.apply_decisions(dec)
        led = world.step(t)
        assert abs(led["sum_savings_after"] - led["sum_savings_before"]) < 1e-6
    assert decider.stats["fallback"] == 0, "mock 合法输出不应触发回退"
    print(f"[PASS] 决策管线：{decider.stats['llm']} 次 LLM 决策，0 回退，守恒 OK")

    # 坏输出回退
    class BadClient(MockClient):
        def batch(self, jobs):
            return ["不是JSON", "", "{{{"][: len(jobs)]
    w2 = make_world()
    d2 = LLMBatchDecider(BadClient(), stats={"llm": 0, "fallback": 0})
    d2.decide_batch([w2.agent(i) for i in range(3)], w2)
    assert d2.stats["fallback"] == 3, "坏输出应全部回退"
    print("[PASS] 坏输出回退：3/3 回退到规则策略")

    # 叙事-评定管线
    alien = AlienationPipeline(MockClient()).run_round(world.agents[:4], world, 5)
    assert len(alien) == 4 and all(r["source"] == "llm_judge" for r in alien)
    assert all(1 <= r["total"] <= 25 for r in alien)
    print("[PASS] 异化管线：4 条叙事全部 LLM-judge 评定")

    fet = TransactionPipeline(MockClient()).run_round(world.agents[:4], world, 5)
    assert len(fet) == 4 and all(1 <= r["fetishism"] <= 5 for r in fet)
    print("[PASS] 交易叙事管线：4 条物化评分")

    sv = SurveyPipeline(MockClient()).run(world.agents[:4], world, 5)
    assert len(sv) == 4 and all(r["attribution"] in ("labor", "luck_skill",
                                                     "structure", "uncoded")
                                for r in sv)
    assert all(r["fairness"] is not None for r in sv)
    print("[PASS] 问卷管线：4 份问卷评定+归因编码")

    print("全部通过")


if __name__ == "__main__":
    main()
