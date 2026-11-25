"""State-flow report figures use the same complete archive analysis as the UI."""
import json

import numpy as np

from .research_charts import COLORS, SPACE, _clock, axis_grid, figure
from .state_transitions import state_history


def _label(node, side):
    if not node['present']:
        return '尚未进入' if side == 0 else '已退出'
    return '缺失状态' if node['state'] is None else str(node['state'])


def state_figures(frames, record, view, save):
    if len(frames) < 2:
        return
    history = state_history(frames)
    for series in history['series']:
        if not any(row['changed_known'] or row['entered'] or row['exited'] or
                   any(link['from']['state'] != link['to']['state'] for link in row['links'])
                   for row in series['transitions']):
            continue
        flow = next((row for row in series['transitions'] if row['to'] == view['frame_time']), None)
        if flow is None:
            if view['frame_explicit']:
                continue
            flow = series['transitions'][-1]
        key = lambda value: json.dumps(value, ensure_ascii=False, sort_keys=True)
        snapshots = series['snapshots']
        categories = {key(row['state']): row['state'] for snap in snapshots for row in snap['states']}
        totals = {label: sum(row['count'] for snap in snapshots for row in snap['states'] if key(row['state']) == label)
                  for label in categories}
        shown = sorted(categories, key=lambda label: -totals[label])[:7]
        rest = set(categories)-set(shown)
        traces = [[sum(row['count'] for row in snap['states'] if key(row['state']) == label) for snap in snapshots]
                  for label in shown]
        names = ['缺失状态' if categories[label] is None else str(categories[label]) for label in shown]
        if rest:
            traces.append([sum(row['count'] for row in snap['states'] if key(row['state']) in rest) for snap in snapshots])
            names.append('其他状态')
        fig, axes = figure(3.3, columns=2)
        area, matrix = axes[0]
        area.stackplot([snap['sim_t'] for snap in snapshots], *traces, labels=names,
                       colors=[COLORS[i%len(COLORS)] for i in range(len(names))], alpha=.85)
        area.set(xlabel=_clock(record), ylabel='主体数', title='各状态数量')
        area.legend(fontsize=7, loc='upper left')
        axis_grid(area)
        labels, maps = [], []
        all_nodes = {key(row[side]): row[side] for row in flow['links'] for side in ('from', 'to')}
        def order(node):
            value = all_nodes[node]['state']
            return (not all_nodes[node]['present'], value is None,
                    0 if isinstance(value, (int, float)) else 1,
                    value if isinstance(value, (int, float)) else str(value))
        common_order = {node: i for i, node in enumerate(sorted(all_nodes, key=order))}
        for side in ('from', 'to'):
            nodes = {key(row[side]): row[side] for row in flow['links']}
            totals = {node: sum(row['count'] for row in flow['links'] if key(row[side]) == node) for node in nodes}
            ordered = sorted(nodes, key=lambda node: -totals[node])[:7]
            ordered.sort(key=common_order.get)
            labels.append([_label(nodes[node], int(side == 'to')) for node in ordered]
                          + (['其他状态'] if len(nodes)>7 else []))
            maps.append({node: ordered.index(node) if node in ordered else len(ordered) for node in nodes})
        values = np.zeros((len(labels[0]), len(labels[1])), dtype=np.int64)
        for row in flow['links']:
            values[maps[0][key(row['from'])], maps[1][key(row['to'])]] += row['count']
        if values.size:
            heat = matrix.imshow(values, cmap='viridis', aspect='auto', vmin=0)
            fig.colorbar(heat, ax=matrix, label='实际主体数', shrink=.8)
            matrix.set_xticks(range(len(labels[1])), labels[1], rotation=45, ha='right', fontsize=7)
            matrix.set_yticks(range(len(labels[0])), labels[0], fontsize=7)
            for (i, j), value in np.ndenumerate(values):
                if value:
                    matrix.text(j, i, str(value), ha='center', va='center', fontsize=7,
                                color='black' if value > values.max()*.65 else 'white')
        matrix.set(xlabel=f"t={flow['to']:g} 状态", ylabel=f"t={flow['from']:g} 状态", title='相邻归档端点迁移')
        scope = '完整人口' if series['scope'] == 'full_population' else '模型已导出的主体'
        save(fig, f"主体状态演变 · {series['label']} · {series['field']}", 'state_transitions', SPACE,
             f"使用{scope}按稳定ID核对。前后匹配{flow['matched']}，进入{flow['entered']}，退出{flow['exited']}；"
             f"已知状态改变{flow['changed_known']}。缺失不补零，两个归档时点之间的具体路径未推断。",
             scope=series['scope'], group=series['group'], field=series['field'],
             snapshots=snapshots, transition=flow, interpolated=False)
