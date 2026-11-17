"""R7-b GameEngine：正则式博弈 + 均衡解算器 + 复制动态 + LLM 玩家。

- MatrixGame：2 人正则式博弈（收益矩阵 A（行玩家）/B（列玩家））
- pure_nash / mixed_nash_2x2（解析）：解算器做均衡计算（LLM 永不算数学）
- replicator_dynamics（BEH082）：演化动力学
- llm_game_action：LLM 玩家（遮蔽变体：不告知博弈名，测是否自发识别）
"""
from __future__ import annotations

import itertools
from typing import Optional

import numpy as np


class MatrixGame:
    """2 人正则式博弈。A[row, col] 为行玩家收益，B[row, col] 为列玩家收益。"""

    def __init__(self, A: np.ndarray, B: np.ndarray, actions: list[str] | None = None,
                 name: str = "Unnamed matrix game", column_actions: list[str] | None = None):
        self.A = np.asarray(A, dtype=float)
        self.B = np.asarray(B, dtype=float)
        if self.A.ndim != 2 or not self.A.size or self.A.shape != self.B.shape or not np.isfinite(self.A).all() or not np.isfinite(self.B).all():
            raise ValueError("收益矩阵须为同形状、非空、有限的二维数组")
        self.actions = actions or [str(i) for i in range(self.A.shape[0])]
        self.column_actions = column_actions or (list(self.actions) if self.A.shape[0] == self.A.shape[1] else [str(i) for i in range(self.A.shape[1])])
        if len(self.actions) != self.A.shape[0] or len(self.column_actions) != self.A.shape[1]:
            raise ValueError("行/列行动名称数量须与收益矩阵对应")
        self.name = str(name)
        self.last_decision = None

    # ---- 纯策略纳什均衡（枚举）----
    def pure_nash(self) -> list[tuple[int, int]]:
        out = []
        for i in range(self.A.shape[0]):
            for j in range(self.A.shape[1]):
                row_best = self.A[:, j].max() == self.A[i, j]
                col_best = self.B[i, :].max() == self.B[i, j]
                if row_best and col_best:
                    out.append((i, j))
        return out

    # ---- 2x2 混合纳什（解析）----
    def mixed_nash_2x2(self) -> Optional[tuple[np.ndarray, np.ndarray]]:
        """2x2 混合纳什（标准无差异公式）。
        行玩家 mix p 由列玩家收益矩阵 B 的无差异条件决定；
        列玩家 mix q 由行玩家收益矩阵 A 的无差异条件决定。
        退化（分母 0 或概率越界）返回 None。"""
        if self.A.shape != (2, 2) or self.B.shape != (2, 2):
            return None
        a00, a01 = self.A[0, 0], self.A[0, 1]
        a10, a11 = self.A[1, 0], self.A[1, 1]
        den_a = a00 - a01 - a10 + a11
        if abs(den_a) < 1e-12:
            return None
        q0 = (a11 - a01) / den_a          # 列玩家选 col0 概率（行玩家无差异）
        if not (0.0 <= q0 <= 1.0):
            return None
        b00, b01 = self.B[0, 0], self.B[0, 1]
        b10, b11 = self.B[1, 0], self.B[1, 1]
        den_b = b00 - b01 - b10 + b11
        if abs(den_b) < 1e-12:
            return None
        p0 = (b11 - b10) / den_b          # 行玩家选 row0 概率（列玩家无差异）
        if not (0.0 <= p0 <= 1.0):
            return None
        return np.array([p0, 1 - p0]), np.array([q0, 1 - q0])

    # ---- 最优反应 ----
    def best_response_row(self, j_prob: np.ndarray) -> int:
        return int(np.argmax(self.A @ j_prob))

    def best_response_col(self, i_prob: np.ndarray) -> int:
        return int(np.argmax(self.B.T @ i_prob))


def replicator_dynamics(A: np.ndarray, x0: np.ndarray, steps: int = 500,
                        dt: float = 0.01) -> np.ndarray:
    """复制动态（BEH082）：dx_i = x_i[(Ax)_i - x·Ax]。"""
    x = np.asarray(x0, dtype=float) / np.asarray(x0).sum()
    for _ in range(steps):
        fit = A @ x
        avg = float(x @ fit)
        x = x + dt * x * (fit - avg)
        x = np.clip(x, 0.0, None)
        x = x / x.sum()
    return x


def hawk_dove_matrix(V: float = 4.0, C: float = 6.0) -> MatrixGame:
    """鹰鸽博弈（对称，B=A 转置）：混合均衡 x_H=V/C。"""
    A = np.array([[(V - C) / 2.0, V], [0.0, V / 2.0]])
    return MatrixGame(A, A.T.copy(), actions=["Hawk", "Dove"], name="Hawk–Dove")


def prisoners_dilemma_matrix() -> MatrixGame:
    """囚徒困境：B = A 的转置（零和错位语义下各取各的收益）。
    T=3 > R=2 > P=1 > S=0：背叛严格占优，唯一纯纳什 (D,D)。"""
    A = np.array([[2.0, 0.0], [3.0, 1.0]])
    return MatrixGame(A, A.T.copy(), actions=["Coop", "Defect"], name="Prisoner's dilemma")


# ---- LLM 玩家（遮蔽变体：prompt 不含博弈名，测自发识别）----
def llm_game_action(client, game: MatrixGame, my_index: int,
                    history: list[tuple[int, int]] | None = None,
                    masked: bool = True, *, rng: np.random.Generator | None = None,
                    audit: list | None = None) -> int:
    """Choose an action. A fallback consumes the caller's persistent RNG stream.

    last_decision/audit distinguish real LLM decisions from random fallbacks.
    No implicit seed is created when a caller has omitted their random stream.
    """
    if my_index not in (0, 1) or isinstance(my_index, bool):
        raise ValueError("my_index 必须为行玩家0或列玩家1")
    labels = (game.actions, game.column_actions)
    mine, other = labels[my_index], labels[1-my_index]
    if masked:
        mine, other = [f"A{i}" for i in range(len(mine))], [f"A{i}" for i in range(len(other))]
    payoff = game.A if my_index == 0 else game.B.T
    acts = "；".join(f"{i}={a}" for i, a in enumerate(mine))
    hist = ""
    if history:
        hist = "历史（你="+("行玩家" if my_index == 0 else "列玩家")+"）：\n" + "\n".join(
            f"  第{k+1}轮：你={mine[pair[my_index]]}，对方={other[pair[1-my_index]]}"
            for k, pair in enumerate(history[-5:]))
    gains = []
    for i in range(len(mine)):
        row = "；".join(f"对方选{other[j]}→你得{payoff[i, j]:g}"
                        for j in range(len(other)))
        gains.append(f"  你选 {mine[i]}：{row}")
    body = ("" if masked else f"博弈名称：{game.name}\n")+f"可选行动：{acts}\n"+"\n".join(gains)
    if hist:
        body += "\n" + hist
    msgs = [
        {"role": "system",
         "content": "你是策略情境中的参与人。只输出JSON：{\"action\": 编号}。"},
        {"role": "user", "content": body + "\n只输出JSON：{\"action\": 编号}"},
    ]
    import json as _json
    try:
        raw = client.chat(msgs, temperature=0.2)
        d = _json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        act = d.get("action")
        if isinstance(act, bool) or not isinstance(act, int) or not 0 <= act < len(mine):
            raise ValueError("LLM行动编号必须为合法整数")
        record = {"source": "llm", "action": act, "player": my_index, "masked": masked}
    except Exception as exc:
        if not isinstance(rng, np.random.Generator):
            raise ValueError("LLM失败后的随机回退必须提供平台派生rng；未创建固定种子替代") from exc
        act = int(rng.integers(len(mine)))
        record = {"source": "rng-fallback", "action": act, "player": my_index,
                  "masked": masked, "error_type": type(exc).__name__}
    game.last_decision = record
    if audit is not None:
        audit.append(record)
    return act
