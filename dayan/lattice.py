"""Vectorized periodic grid topology and local strategy imitation."""

import numpy as np


def periodic_offsets(degree: int):
    offsets = ((-1, 0), (1, 0), (0, -1), (0, 1))
    if degree == 8:
        offsets += ((-1, -1), (-1, 1), (1, -1), (1, 1))
    return offsets


def periodic_neighbors(height: int, width: int, degree: int) -> np.ndarray:
    """Return one row of distinct neighboring cell indices per cell."""
    if min(height, width) < 3 or degree not in (4, 8):
        raise ValueError("周期网格每边至少3格，邻域须为4或8")
    ids = np.arange(height * width).reshape(height, width)
    return np.stack([np.roll(ids, (-dy, -dx), axis=(0, 1)).ravel()
                     for dy, dx in periodic_offsets(degree)], axis=1)


def imitate_best(strategy, own_payoff, peer_strategy, peer_payoff, neighbors, payoff_span, rng):
    """Only a better same-role neighbor can be imitated; inputs stay unchanged."""
    if payoff_span <= 0:
        return strategy
    local_payoffs = peer_payoff[neighbors]
    cells = np.arange(len(strategy))
    local_best = neighbors[cells, local_payoffs.argmax(axis=1)]
    chance = np.clip((peer_payoff[local_best] - own_payoff) / payoff_span, 0, 1)
    return np.where(rng.random(len(strategy)) < chance, peer_strategy[local_best], strategy)
