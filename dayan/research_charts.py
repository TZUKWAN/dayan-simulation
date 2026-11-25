"""Charts for report windows, calculated from the same archive as report facts."""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import threading

import numpy as np

from .view_analysis import in_window, metric_info, number

_LOCK = threading.RLock()
COLORS = ("#176d78", "#8760aa", "#b36832", "#437bae", "#ad5879", "#627c66")
INK = "#183548"
GRID = "#dce6eb"
RESULTS, SPACE, EVIDENCE = "结果与演变", "场地与主体", "输入与校核"
DRILL_EVENTS = {"drill_fall", "aid_started", "aid_completed"}


def figure(height=2.65, *, columns=1, rows=1, sharex=False):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    result = Figure(figsize=(7.4, height), layout="constrained")
    FigureCanvasAgg(result)
    return result, result.subplots(rows, columns, sharex=sharex, squeeze=False)


def axis_grid(axis, *, which="y"):
    axis.grid(axis=which, color=GRID, lw=.65, alpha=.85)
    axis.set_axisbelow(True)


def units_label(info):
    return f"{info['name']}（{info['unit']}）" if info["unit"] != "原模型单位" else info["name"]


def _name(record):
    return record.get("view_group", record.get("view_label", record["model_id"]))


def _clock(record):
    manifest = record.get("manifest") or {}
    return (manifest.get("actual") or {}).get("time_unit") or (manifest.get("model_definition") or {}).get("time_unit") or "模型时间"


def _values(rows, key):
    return np.array([row[key] if number(row.get(key)) else np.nan for row in rows], dtype=float)


def _short(text, limit=24):
    return text if len(text) <= limit else text[:limit-1]+"…"


def _overview(records, rows_by_run, view, selected, save):
    metric, window = view["metric"], view["window"]
    group_names = list(dict.fromkeys(_name(record) for record in records))
    by_group = {name: COLORS[i % len(COLORS)] for i, name in enumerate(group_names)}
    supporting = [record for record in records if record["run_id"] != selected["run_id"]]
    ordered = [selected, *supporting]
    shown = [r for r in ordered if np.isfinite(_values(rows_by_run[r["run_id"]], metric)).any()][:12]
    fig, axes = figure()
    ax = axes[0, 0]
    seen = set()
    for record in shown:
        name, rows = _name(record), rows_by_run[record["run_id"]]
        vals = _values(rows, metric)
        ax.plot([r["sim_t"] for r in rows], vals, c=by_group[name], lw=1.45,
                marker="o" if np.isfinite(vals).sum() == 1 else None,
                alpha=.65 if len(shown) > len(group_names) else 1,
                label=_short(name) if name not in seen else None)
        seen.add(name)
    interventions = {iv["actual_t"] for record in shown for iv in record.get("manifest", {}).get("interventions", [])
                     if iv.get("applied") and number(iv.get("actual_t")) and window["from"]<=iv["actual_t"]<=window["to"]}
    for j,t in enumerate(sorted(interventions)):
        ax.axvline(t, color="#687782", ls="--", lw=.85, label="干预时点" if not j else None)
    events = sorted({e["sim_t"] for record in shown for e in record.get("events", [])
                     if e.get("etype") in DRILL_EVENTS and number(e.get("sim_t")) and in_window(e["sim_t"], window)})
    for j,t in enumerate(events):
        ax.axvline(t, color=COLORS[2], ls=":", lw=.9, label="演练阶段转换" if not j else None)
    ax.set(xlabel=_clock(selected), ylabel=units_label(view["metric_info"]))
    axis_grid(ax)
    ax.legend(loc="best", ncol=2, fontsize=8, frameon=False)
    save(fig,f"{view['metric_info']['name']}的时间过程","comparison_time_series",RESULTS,
         f"记录范围使用所选分析窗口。图中画出 {len(shown)} 条归档曲线，报告关联 {len(records)} 次运行。",
         run_ids=[r["run_id"] for r in shown], field=metric)


def _run_comparisons(view, save):
    groups = [g for g in view["groups"] if number(g["mean"])]
    if len(view["per_run"]) < 2 or not groups:
        return
    groups = groups[:16]
    items = defaultdict(list)
    for item in view["per_run"]:
        if number(item["mean"]):
            items[item["group"]].append(item)
    fig, axes = figure(min(5.65, max(2.0, .31*len(groups)+1.1)))
    ax = axes[0, 0]
    for i, group in enumerate(groups):
        color = COLORS[i % len(COLORS)]
        vals = [item["mean"] for item in items[group["name"]]]
        ax.scatter(vals, np.full(len(vals), i), color=color, alpha=.62, s=18, zorder=3)
        ax.scatter(group["mean"], i, color=color, marker="D", edgecolor="white", s=50, zorder=4)
    ax.set_yticks(range(len(groups)), [_short(group["name"]) for group in groups])
    ax.invert_yaxis()
    ax.set_xlabel(units_label(view["metric_info"])+"的窗口均值")
    axis_grid(ax, which="x")
    save(fig,"各方案的运行分布","window_comparison",RESULTS,
         f"圆点是单次运行的窗口均值，菱形是方案均值。图中显示 {len(groups)} 个方案或运行组。",
         run_ids=[item["run_id"] for g in groups for item in items[g["name"]]], field=view["metric"])

    paired = [comparison for comparison in view["comparisons"] if comparison["paired_n"]]
    if not paired:
        return
    fig, axes = figure(min(5.65, max(2.15, .43*min(10, len(paired))+1.25)))
    ax = axes[0, 0]
    notes, ids, labels = [], [], []
    for i, item in enumerate(paired[:10]):
        base = {row["seed"]:row for row in reversed(items[item["baseline"]])}
        differences = []
        for row in items[item["group"]]:
            match = base.get(row["seed"])
            if match is not None:
                differences.append(row["mean"]-match["mean"])
                ids.extend([row["run_id"], match["run_id"]])
        if not differences:
            continue
        labels.append((_short(item["group"]), i))
        color = COLORS[i % len(COLORS)]
        ax.scatter(differences, np.full(len(differences),i), c=color, s=26, alpha=.78)
        ax.scatter(item["difference"], i, marker="D", c=color, edgecolor="white", s=51, zorder=4)
        notes.append({"group":item["group"],"baseline":item["baseline"],"n":len(differences),
                      "minimum":min(differences),"maximum":max(differences),"mean":item["difference"]})
    if not labels:
        return
    ax.set_yticks([v for _,v in labels],[k for k,_ in labels])
    ax.invert_yaxis()
    ax.axvline(0, ls="--", lw=.9, color=INK)
    ax.set_xlabel("方案减配对基线（"+view["metric_info"]["unit"]+"）")
    axis_grid(ax, which="x")
    save(fig,"同种子下的方案差值","paired_effects",RESULTS,
         "每点来自一对种子，菱形是配对均值。散点描述本次运行组的差异。",
         run_ids=list(dict.fromkeys(ids)), field=view["metric"], pairs=notes)


def _ensemble_bands(records, rows_by_run, view, record, save):
    if view["kind"] != "ensemble":
        return
    series = [{row["sim_t"]:row[view["metric"]] for row in rows_by_run[r["run_id"]]
               if number(row.get(view["metric"]))} for r in records]
    common = sorted(set.intersection(*(set(item) for item in series))) if len(series)>=3 else []
    if len(common)<2:
        return
    low, mid, high = np.quantile([[item[t] for t in common] for item in series], [.25,.5,.75],axis=0)
    fig, axes = figure()
    ax = axes[0,0]
    ax.fill_between(common, low, high, color=COLORS[0], alpha=.18, label="种子间第 25 至 75 百分位")
    ax.plot(common, mid, color=COLORS[0], lw=1.8, label="种子间中位数")
    ax.set(xlabel=_clock(record), ylabel=units_label(view["metric_info"]))
    axis_grid(ax)
    ax.legend(frameon=False, fontsize=8)
    save(fig,"多种子运行的分布带","ensemble_bands",RESULTS,
         f"按 {len(series)} 次运行共有的 {len(common)} 个时点统计经验分位数。",
         run_ids=view["run_ids"], field=view["metric"])


def _movement(record, rows, save):
    fields = ("evacuated", "moving", "waiting", "fallen", "assisted")
    values = np.array([_values(rows, key) for key in fields])
    totals = values.sum(axis=0)
    if len(rows)<2 or not np.isfinite(values).all() or totals[0]<=0 or (values < 0).any() or not np.equal(totals, totals[0]).all():
        return ()
    fig, axes = figure(2.75)
    ax = axes[0,0]
    times = [item["sim_t"] for item in rows]
    ax.stackplot(times, values, colors=(COLORS[0], COLORS[3], "#b9c9d4", COLORS[2], COLORS[1]),
                 alpha=.9, step="post", labels=[metric_info(record["model_id"], key)["name"] for key in fields])
    ax.set(xlabel=_clock(record),ylabel="人数",ylim=(0,totals[0]))
    fig.legend(loc="outside upper center", ncol=3, fontsize=8, frameon=False)
    axis_grid(ax)
    save(fig,"在场状态与累计离场","state_composition",RESULTS,
         f"将互斥状态按实际人数堆叠。{len(rows)} 个时点的总数均为 {totals[0]:g} 人。",
         fields=list(fields), conserved_total=float(totals[0]))
    return tuple(key for key in fields if key not in ("fallen","assisted"))


def _additional_series(record, rows, primary, excluded, save):
    candidates = list(dict.fromkeys(key for row in rows for key in row if key not in ("sim_t", primary, *excluded)))
    series = []
    for key in candidates:
        vals = _values(rows, key)
        finite = vals[np.isfinite(vals)]
        if not len(finite) or (len(finite)>1 and np.ptp(finite)<=16*np.finfo(float).eps*np.max(np.abs(finite))):
            continue
        series.append((key,vals))
    times = [row["sim_t"] for row in rows]
    for offset in range(0,min(len(series),12),4):
        batch = series[offset:offset+4]
        height = 2.15 if len(batch)==1 else 3.25
        cols = 1 if len(batch)<2 else 2
        fig,axes = figure(height, columns=cols, rows=(len(batch)+cols-1)//cols)
        for i,(ax,(key,vals)) in enumerate(zip(axes.flat,batch)):
            info = metric_info(record["model_id"],key)
            ax.plot(times, vals, color=COLORS[i % len(COLORS)], lw=1.25,
                    marker="o" if np.isfinite(vals).sum()==1 else None)
            ax.set_title(units_label(info))
            if times[0] < times[-1]:
                ax.set_xlim(times[0], times[-1])
            axis_grid(ax)
        for ax in list(axes.flat)[len(batch):]:
            ax.set_visible(False)
        fields = [key for key,_ in batch]
        names = [metric_info(record["model_id"],key)["name"] for key in fields]
        title = "、".join(names[:2])+("等" if len(names)>2 else "")+"的演变"
        fig.supxlabel(_clock(record), fontsize=9)
        save(fig,title,"other_observations",RESULTS,
             "各子图使用自己的纵轴。未记录的数值在曲线中留空。",fields=fields)


def _stock_figures(record, rows, save):
    definition = (record.get("manifest") or {}).get("model_definition") or {}
    if not definition.get("rates"):
        return ()
    names = definition.get("initial_state") or {}
    fields = {expr.strip(): key for key,expr in definition.get("observables",{}).items()
              if isinstance(expr,str) and expr.strip() in names}
    if len(fields)<2 or len(rows)<3:
        return ()
    varying = []
    for name in names:
        if name not in fields:
            continue
        vals = _values(rows, fields[name])
        if np.isfinite(vals).all() and np.ptp(vals)>0:
            varying.append((fields[name], vals))
    if len(varying)>=2:
        (x, a), (y, b) = varying[:2]
        fig, axes = figure(2.75)
        ax = axes[0,0]
        dots = ax.scatter(a,b,c=[row["sim_t"] for row in rows],cmap="viridis",s=14,zorder=3)
        ax.plot(a,b, c=INK,alpha=.38,lw=1)
        ax.scatter([a[0],a[-1]],[b[0],b[-1]],s=39,facecolors="none",edgecolors=INK,zorder=4)
        ax.set(xlabel=x, ylabel=y)
        axis_grid(ax,which="both")
        fig.colorbar(dots,ax=ax,label=_clock(record),pad=.02)
        save(fig,"两个存量的联合演化","stock_phase",RESULTS,
             "每个点是同一保存时点的两个存量值。空心圈标出首末时点。",fields=[x,y])

    from .report_stock_graph import stock_dependency_graph
    graph = stock_dependency_graph(definition, figure, COLORS, INK)
    if graph:
        fig, links = graph
        save(fig,"存量方程的直接依赖","stock_dependencies",EVIDENCE,
             "箭头从被读取的存量指向使用它的其他存量变化率方程。连线根据归档 DSL 表达式解析。",
             links=links)

    # The approved runtime contract or a plain saved sum supplies an explicit identity.
    review = (record.get("manifest") or {}).get("scenario_review") or {}
    verification = (review.get("runtime_checks") or {}).get("verification") or {}
    balance = next((c for c in verification.get("criteria",[]) if c["check"]=="balance" and c["passed"]),None)
    chosen = balance["fields"] if balance else list(fields.values())
    if len(chosen)<2:
        return ()
    values = np.array([_values(rows,key) for key in chosen])
    if not np.isfinite(values).all():
        return ()
    totals = values.sum(axis=0)
    if balance is None and not np.allclose(totals, totals[0], rtol=0, atol=max(1e-12, abs(totals[0])*1e-12)):
        return ()
    expected = balance["target"] if balance else float(totals[0])
    residual = totals - expected
    maximum = float(np.max(np.abs(residual)))
    fig, axes = figure(2.25)
    ax = axes[0,0]
    ax.plot([row["sim_t"] for row in rows], residual, color=COLORS[1], lw=1.4)
    ax.axhline(0,c=INK,lw=.8,ls=":")
    ax.set(xlabel=_clock(record),ylabel="存量合计减参考值")
    axis_grid(ax)
    if maximum == 0:
        ax.set_ylim(-.5,.5)
    label = "事前检验的目标" if balance else "窗口首时点的合计值"
    save(fig,"存量合计的残差","balance_residual",EVIDENCE,
         f"参考量为{label} {expected:.8g}。最大绝对残差 {maximum:.4g}。",fields=chosen,
         reference=expected, max_abs_error=maximum)
    return ()


def _input_series(record):
    from .datasets import load, selected_rows
    samples = []
    for binding in record.get("manifest",{}).get("data_bindings",[]):
        if not all(k in binding for k in ("dataset_id","field","sha256","parameter")):
            continue
        try:
            dataset = load(binding["dataset_id"])
            if dataset["sha256"] != binding["sha256"]:
                continue
            rows = selected_rows(dataset,binding.get("path",""),binding.get("filters"),binding.get("order_by"))
            values = np.asarray([float(row[binding["field"]]) for row in rows])
        except (OSError, KeyError, TypeError, ValueError):
            continue
        if len(values)>1 and np.isfinite(values).all() and len(values)==binding.get("records_used"):
            samples.append((binding, values))
            if len(samples) == 4:
                break
    return samples


def _input_figures(samples, save):
    from matplotlib.ticker import PercentFormatter
    for binding, values in samples:
        vals = np.sort(values)
        fig, axes = figure(2.45)
        ax = axes[0,0]
        ax.step(np.r_[vals[0],vals], np.arange(len(vals)+1)/len(vals), where="post", c=COLORS[0], lw=1.65)
        median = float(np.median(vals))
        ax.axvline(median, c=COLORS[1], ls=":", lw=1, label=f"样本中位数 {median:.5g}")
        ax.yaxis.set_major_formatter(PercentFormatter(1.))
        unit = binding.get("source_unit")
        ax.set(xlabel=f"{binding['field']}（{unit}）" if unit else binding["field"], ylabel="累计样本比例", ylim=(0,1.04))
        ax.legend(frameon=False,fontsize=8)
        axis_grid(ax)
        save(fig,"实际入模数据的经验分布","dataset_ecdf",EVIDENCE,
             f"取绑定使用的 {len(vals)} 条源记录。横轴保留源量纲。数据映射目标为 {binding['parameter']}。",
             dataset_id=binding["dataset_id"], field=binding["field"], count=len(vals), dataset_sha256=binding["sha256"])


def _render(records, view, directory, key, samples):
    from .report_spatial_charts import spatial_figures
    from .collection.storage import atomic_json
    built = []
    selected = next(r for r in records if r["run_id"]==view["selected_run_id"])
    window = view["window"]
    rows_by_run = {r["run_id"]:[row for row in r["observations"] if in_window(row["sim_t"],window)] for r in records}
    rows = rows_by_run[selected["run_id"]]

    def save(fig, title, kind, section, caption, *, run_ids=None, **details):
        path = directory/f"research_{key}_{len(built)+1}.png"
        handle, temporary = tempfile.mkstemp(prefix="research_", suffix=".tmp",dir=directory)
        os.close(handle)
        try:
            fig.savefig(temporary, format="png", dpi=170, facecolor="white")
            os.replace(temporary,path)
        finally:
            Path(temporary).unlink(missing_ok=True)
            fig.clear()
        built.append({"kind":kind,"title":title,"section":section,"caption":caption,
                      "path":str(path),"url":f"/reports/{path.name}",
                      "aspect":float(fig.get_figwidth()/fig.get_figheight()),
                      "evidence":{"run_ids":run_ids or [selected["run_id"]],"window":window,**details}})

    _overview(records, rows_by_run, view, selected, save)
    _run_comparisons(view, save)
    _ensemble_bands(records, rows_by_run, view, selected, save)
    excluded = _movement(selected, rows, save) if selected["model_id"]=="NET121" else ()
    _additional_series(selected, rows, view["metric"], excluded, save)
    spatial_figures(selected, view, save)
    _stock_figures(selected, rows, save)
    _input_figures(samples,save)
    _actor_action_heatmaps(selected,window,save)
    _global_sensitivity_figures(view.get('global_sensitivity'),save)
    # Assign visual numbering after putting figures in their reading order.
    built.sort(key=lambda item:(RESULTS,SPACE,EVIDENCE).index(item["section"]))
    for index,item in enumerate(built,1):
        item["number"]=index
    atomic_json(directory/f"research_{key}.json",built)
    return built


def _global_sensitivity_figures(analysis,save):
    if not analysis:return
    protocol=analysis['protocol'];names=list(protocol['distributions'])
    indices=analysis['indices']
    if analysis['status']=='estimated':
        fig,axes=figure(max(2.5,len(names)*.45+1.))
        ax=axes[0,0]
        for j,row in enumerate(indices):
            for delta,key,interval,color,label in ((-.1,'first_order','first_interval',COLORS[0],'一阶'),(.1,'total_order','total_interval',COLORS[1],'总效应')):
                y=j+delta;value=row[key];bounds=row[interval]
                if bounds and all(number(v) for v in bounds):ax.plot(bounds,[y,y],c=color,lw=2)
                ax.scatter([value],[y],c=color,label=label if j==0 else None,s=25)
        ax.set_yticks(range(len(names)),names);ax.set_xlabel('Sobol指数及95% bootstrap区间（有限样本可越界，未裁剪）')
        ax.axvline(0,c=GRID,lw=1);ax.legend(frameon=False);axis_grid(ax,which='x')
        save(fig,'参数一阶与总效应敏感性','sobol_indices',RESULTS,
             '由全部实际pick-freeze样本计算。总效应含交互；区间只描述抽样误差，不是现实因果识别。',
             indices=indices,n=protocol['n'])
    points=protocol['points'][:protocol['n']];values=analysis['sampling_values'][:protocol['n']]
    fig,axes=figure(2.7*max(1,math.ceil(len(names)/3)),columns=min(3,len(names)),rows=max(1,math.ceil(len(names)/3)))
    for ax,key in zip(axes.flat,names):
        ax.scatter([row['parameters'][key] for row in points],values,s=12,c=COLORS[0],alpha=.7)
        ax.set_xlabel(key);ax.set_ylabel(protocol['metric']+' / '+protocol['statistic']);axis_grid(ax)
    for ax in list(axes.flat)[len(names):]:ax.set_visible(False)
    save(fig,'独立参数采样与真实模型响应','sobol_samples',RESULTS,
        f'展示A矩阵{protocol["n"]}个真实求值；完整A/B/混合矩阵、种子及run_id保存在事实JSON与分析包中。',
        samples=len(points),required_runs=(len(names)+2)*protocol['n']*len(protocol['seeds']))


def _actor_action_heatmaps(selected,window,save):
    audit=(selected.get('manifest') or {}).get('actor_decisions')
    if not audit:return
    values=[]
    for record in audit['records']:
        t=record['descriptor']['time']
        if not in_window(t,window):continue
        for batch in record['receipts']:
            for row in batch['actions']:
                action=row['action']
                fields=action.items() if isinstance(action,dict) else [('action',action)]
                for field,value in fields:
                    if isinstance(value,(str,bool)) or number(value):
                        values.append((field,row['actor_id'],t,value,batch['batch_id']))
    counts=Counter((field,actor,t) for field,actor,t,_,_ in values)
    ambiguous={(field,actor) for (field,actor,_),count in counts.items() if count>1}
    # Batches can be renamed/repacked at every decision boundary. A persistent
    # person must remain on the same row. If the same actor really receives
    # multiple same-field decisions at one time, retain the separate batches.
    values=[(field,actor+'/'+batch if (field,actor) in ambiguous else actor,t,value)
            for field,actor,t,value,batch in values]
    for field in list(dict.fromkeys(row[0] for row in values))[:4]:
        rows=[row for row in values if row[0]==field]
        actors=list(dict.fromkeys(row[1] for row in rows))
        shown=actors[:40]
        times=sorted({row[2] for row in rows})
        by_actor={key:i for i,key in enumerate(shown)}
        by_time={key:i for i,key in enumerate(times)}
        categorical=not all(number(row[3]) for row in rows)
        labels=list(dict.fromkeys(str(row[3]) for row in rows)) if categorical else []
        matrix=np.full((len(shown),len(times)),np.nan)
        for _,actor,t,value in rows:
            if actor in by_actor:matrix[by_actor[actor],by_time[t]]=labels.index(str(value)) if categorical else value
        fig,axes=figure(max(2.6,min(7.,1.1+len(shown)*.18)))
        ax=axes[0,0]
        plotted=ax.imshow(np.ma.masked_invalid(matrix),aspect='auto',interpolation='nearest',cmap='viridis')
        ticks=list(range(0,len(times),max(1,len(times)//7)))
        ax.set_xticks(ticks,[f'{times[i]:g}' for i in ticks]);ax.set_yticks(range(len(shown)),shown,fontsize=7)
        ax.set_xlabel('实际决策时刻（模型时间）');ax.set_ylabel('主体ID（同刻多决策按批次拆分）')
        bar=fig.colorbar(plotted,ax=ax)
        if categorical:
            bar.set_ticks(range(len(labels)),labels=labels)
        else:bar.set_label(field+'（单位以模型动作合同为准）')
        save(fig,'主体决策动作：'+field,'actor_action_heatmap',EVIDENCE,
            f'按实际响应与持久主体ID绘制动作字段{field}，批次改名不切断轨迹；同刻多决策按批次拆分。显示{len(shown)}/{len(actors)}行；空白表示该时点无此动作，未补0。'
            '历史重放来源与本运行新调用在决策审计中分别记录。',
            action_field=field,action_records=len(rows),shown_actors=len(shown),total_actors=len(actors),
            decision_keys=[record['descriptor']['key'] for record in audit['records']])


def build_charts(records, view, directory: Path):
    """Reuse the same exact images for read-only preview and Word export."""
    from matplotlib import rc_context
    from .collection.storage import file_lock
    from .fonts import font_family
    from .source_version import source_fingerprint
    selected = next(record for record in records if record["run_id"] == view["selected_run_id"])
    samples = _input_series(selected)
    signature = {
        "source":source_fingerprint(), "view":{k:v for k,v in view.items() if k!="figures"},
        "archives":[record.get("files", {}) for record in records],
        "inputs":[binding for binding,_ in samples],
    }
    key = hashlib.sha256(json.dumps(signature,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()[:24]
    directory = directory.resolve()
    directory.mkdir(parents=True,exist_ok=True)
    index = directory/f"research_{key}.json"
    with _LOCK, file_lock(directory/".research_figures.lock", timeout=60):
        try:
            old = json.loads(index.read_text(encoding="utf-8"))
            if old and all(Path(item["path"]).parent == directory and Path(item["path"]).is_file() for item in old):
                return old
        except (OSError,ValueError,TypeError,KeyError):
            pass
        with rc_context({"font.sans-serif":[font_family(),"DejaVu Sans"],"axes.unicode_minus":True,
                         "font.size":9.2,"axes.edgecolor":"#a1b2bd","axes.labelcolor":INK,
                         "axes.titlecolor":INK,"axes.spines.top":False,"axes.spines.right":False,
                         "text.color":INK,"xtick.color":"#435963","ytick.color":"#435963"}):
            return _render(records,view,directory,key,samples)
