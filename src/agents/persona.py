"""中性人设生成器（遮蔽设计：人设不含任何理论/阶级词汇）。"""
from __future__ import annotations

import random

NAMES = ["居民", "镇民", "街坊", "坊民"]
BG = [
    "住在小镇边缘，喜欢在傍晚散步",
    "早年学过一门手艺，闲时喜欢修补旧物",
    "喜欢看市场里的新鲜事，偶尔记账",
    "家里有几件老工具，动手能力强",
    "喜欢安静，做事仔细",
    "爱和人聊天，消息灵通",
    "习惯早起，生活规律",
    "对新东西好奇，愿意尝试",
    "节俭，习惯把东西用到坏再换",
    "做事求稳，不太喜欢冒险",
    "性子急，想到就做",
    "喜欢攒东西，柜子总塞得满满",
]


def make_personas(n: int, rng: random.Random) -> list[dict]:
    out = []
    for i in range(n):
        out.append({
            "name": f"{rng.choice(NAMES)}{i:03d}",
            "age": rng.randint(20, 58),
            "trait": rng.choice(BG),
        })
    return out
