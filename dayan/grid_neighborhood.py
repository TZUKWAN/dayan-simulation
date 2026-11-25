"""Bounded local reductions over fixed-location declarative agents."""

from collections import deque

import numpy as np

from .lattice import periodic_offsets


OPS = {"sum": np.sum, "mean": np.mean, "min": np.min, "max": np.max}


def shift_field(source, spec, dy, dx, *, outside=0):
    """Cell-centred ghosts: wrap, reflect at faces, or a fixed external value.

    For a one-cell stencil, reflecting at cell faces duplicates the edge cell
    (NumPy's symmetric extension, not its edge-excluding 'reflect' mode).
    """
    shaped = source.reshape(spec['rows'], spec['columns'])
    boundary = spec.get('boundary', 'periodic')
    if boundary == 'periodic':
        return np.roll(shaped, (-dy,-dx), axis=(0,1)).ravel()
    rows = np.arange(spec['rows'], dtype=np.int32) + dy
    cols = np.arange(spec['columns'], dtype=np.int32) + dx
    shifted = shaped[np.clip(rows,0,spec['rows']-1)[:,None], np.clip(cols,0,spec['columns']-1)]
    if boundary == 'absorbing':
        shifted[(rows < 0) | (rows >= spec['rows']), :] = outside
        shifted[:, (cols < 0) | (cols >= spec['columns'])] = outside
    return shifted.ravel()


def reduce_grid(spec, read):
    """One semantics for scalar and columnar execution, including tie order."""
    result, computed = {}, {}
    offsets = periodic_offsets(spec['degree'])
    for name, rule in spec['reductions'].items():
        op, field, lag = rule['op'], rule['field'], rule.get('lag',0)
        signature = (op,field,lag,rule.get('by'))
        if signature in computed:
            result[name] = computed[signature]
            continue
        def shifted(key, offset, selecting=False):
            outside = -np.inf if selecting else spec.get('boundary_values', {}).get(key, 0)
            return shift_field(read(key,lag), spec, *offset, outside=outside)
        aggregate = shifted(field, offsets[0])
        if op == 'pick_max':
            # Ghost cells are not agents. Absorbing ghosts never win imitation,
            # even when all actual neighbor payoffs are negative.
            best = shifted(rule['by'], offsets[0], True)
            for offset in offsets[1:]:
                payoff = shifted(rule['by'], offset, True)
                wins = payoff > best
                np.copyto(best, payoff, where=wins)
                np.copyto(aggregate, shifted(field, offset), where=wins)
        else:
            merge = {'sum':np.add,'mean':np.add,'min':np.minimum,'max':np.maximum}[op]
            for offset in offsets[1:]:
                merge(aggregate, shifted(field, offset), out=aggregate)
            if op == 'mean':
                aggregate /= len(offsets)
        computed[signature] = result[name] = aggregate
    return result


class GridNeighborhood:
    def __init__(self, spec):
        self.spec = spec
        self.reductions = spec["reductions"]
        self.columns = spec["columns"]
        self.fields = sorted({rule[key] for rule in self.reductions.values()
                              for key in ("field", "by") if key in rule})
        self.history = deque(maxlen=1 + max(rule.get("lag", 0) for rule in self.reductions.values()))

    def before_step(self, agents):
        self.history.append({key: np.fromiter((agent[key] for agent in agents), dtype=float, count=len(agents))
                             for key in self.fields})
        return reduce_grid(self.spec, lambda field,lag:self.history[max(0,len(self.history)-1-lag)][field])

    def context(self, index, local_values=None):
        row, col = divmod(index, self.columns)
        return {"row": row, "col": col, **{key: values[index] for key, values in (local_values or {}).items()}}

    def saved_history(self):
        return [{key: values.tolist() for key, values in snapshots.items()} for snapshots in self.history]

    def restore_history(self, snapshots):
        self.history.extend({key: np.asarray(values, dtype=float) for key, values in states.items()}
                            for states in snapshots)
