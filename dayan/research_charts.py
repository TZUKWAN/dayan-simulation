"""Data-conditional research figures from saved runs, never synthetic trajectories."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import threading
import numpy as np

from .view_analysis import NAMES, number

_LOCK = threading.RLock()
COLORS = ["#087f86", "#8057bd", "#ba7629", "#397ab0", "#b05f7d"]


def build_charts(records, view, directory: Path, tag):
    with _LOCK:
        return _build(records, view, directory, tag)


def _build(records, view, directory, tag):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch
    from .fonts import configure_matplotlib
    configure_matplotlib()
    figures = []
    def save(fig, caption, kind):
        fig.tight_layout(pad=1.1)
        path = directory / f"research_{tag}_{len(figures)+1}.png"
        fig.savefig(path, dpi=170, facecolor="white")
        plt.close(fig)
        figures.append({"path": str(path), "caption": caption, "kind": kind})
    metric, window = view["metric"], view["window"]
    names = list(dict.fromkeys(r.get("view_group", r.get("view_label", r["model_id"])) for r in records))
    fig, ax = plt.subplots(figsize=(7.4, 2.65))
    seen = set()
    for record in records:
        name = record.get("view_group", record.get("view_label", record["model_id"]))
        color = COLORS[names.index(name) % len(COLORS)]
        rows = record["observations"]
        ax.plot([r["sim_t"] for r in rows], [r.get(metric) if number(r.get(metric)) else np.nan for r in rows],
                color=color, lw=1.3, alpha=.65 if len(records)>len(names) else 1,
                label=name if name not in seen else None)
        seen.add(name)
    if window["mode"] != "all":
        ax.axvspan(window["from"], window["to"], alpha=.08, color=COLORS[0], label="分析窗口")
    times = {iv["actual_t"] for r in records for iv in r.get("manifest", {}).get("interventions", []) if iv.get("applied")}
    for t in sorted(times):
        ax.axvline(t, color="#6f7f86", ls="--", lw=.8)
    ax.set(xlabel="模型时间 sim_t", ylabel=f"{view['metric_info']['name']}（{view['metric_info']['unit']}）")
    ax.grid(alpha=.18)
    ax.legend(fontsize=8, loc="best", ncol=min(3,len(names)+1))
    save(fig, "同一指标的各方案过程与分析窗口  虚线标出实际干预时点", "comparison_time_series")

    groups = [g for g in view["groups"] if number(g["mean"])]
    if len(records)>1:
        fig, ax = plt.subplots(figsize=(7.4, max(2.0, len(groups)*.35+.8)))
        y=np.arange(len(groups));values=[g["mean"] for g in groups]
        ax.barh(y,values,color=[COLORS[i%len(COLORS)] for i in range(len(groups))],height=.55)
        ax.set_yticks(y,[g["name"] for g in groups]);ax.invert_yaxis();ax.axvline(0,color="#9aabb2",lw=.6)
        ax.set_xlabel(f"{view['metric_info']['name']}窗口均值")
        ax.margins(x=.18)
        for i,g in enumerate(groups):
            ax.text(g["mean"],i,f"  {g['mean']:.5g}  n={g['n']}",va="center",fontsize=9)
        ax.grid(axis="x",alpha=.18)
        save(fig,"先对每次运行计算窗口均值 再按方案汇总  n为运行数", "window_comparison")

    record=next(r for r in records if r["run_id"]==view["selected_run_id"])
    frame=next((f for f in record.get("state_frames",[]) if f["sim_t"]==view["frame_time"]),None)
    entities=frame.get("entities",[]) if frame else []
    field=view["distribution"].get("field")
    if field:
        fig,ax=plt.subplots(figsize=(7.4,2.45))
        vals=[e[field] for e in entities if field in e and (number(e[field]) or isinstance(e[field],(str,bool)))]
        if vals and all(number(v) for v in vals):
            unique=sorted(set(vals))
            if len(unique)<=12 and all(float(x).is_integer() for x in unique):
                ax.bar([str(x) for x in unique],[vals.count(x) for x in unique],color=COLORS[0])
            else:
                ax.hist(vals,bins=8,color=COLORS[0],rwidth=.85)
        else:
            counts=Counter(str(x) for x in vals);items=counts.most_common(10)
            if len(counts)>10:items.append(("其他",sum(counts.values())-sum(v for _,v in items)))
            ax.bar([str(k) for k,_ in items],[v for _,v in items],color=COLORS[0])
        ax.set(xlabel=NAMES.get(field,field),ylabel="主体数量")
        ax.grid(axis="y",alpha=.18)
        save(fig,f"所选运行在 sim_t={view['frame_time']:g} 的{NAMES.get(field,field)}分布  使用实际主体状态", "entity_distribution")

    road=next((f for f in (frame or {}).get("facilities",[]) if f.get("type")=="road" and number(f.get("length"))),None)
    frames=record.get("state_frames",[])
    if road and 0<road["length"]<=2000 and entities and all(number(e.get("x")) and number(e.get("speed")) for e in entities):
        cells=int(road["length"]);stride=max(1,(len(frames)+299)//300);shown=frames[::stride]
        if shown[-1] is not frames[-1]:shown.append(frames[-1])
        data=np.full((len(shown),cells),np.nan)
        for i,f in enumerate(shown):
            for e in f.get("entities",[]):
                if number(e.get("x")) and number(e.get("speed")) and 0<=e["x"]<cells:
                    data[i,int(e["x"])]=0 if e["speed"]==0 else 1
        ts=np.asarray([f["sim_t"] for f in shown],float)
        edges=np.r_[ts[0]-(ts[1]-ts[0])/2,(ts[:-1]+ts[1:])/2,ts[-1]+(ts[-1]-ts[-2])/2] if len(ts)>1 else np.array([ts[0]-.5,ts[0]+.5])
        fig,ax=plt.subplots(figsize=(7.4,2.8));ax.set_facecolor("#edf2f5")
        ax.pcolormesh(np.arange(cells+1),edges,data,cmap=ListedColormap(["#c38839",COLORS[0]]),vmin=0,vmax=1,shading="flat")
        ax.invert_yaxis();ax.set(xlabel="道路位置（格）",ylabel="模型时间 sim_t")
        ax.legend(handles=[Patch(color=COLORS[0],label="行驶"),Patch(color="#c38839",label="停车 速度为零"),Patch(color="#edf2f5",label="空格")],fontsize=8,ncol=3,loc="upper center",bbox_to_anchor=(.5,1.2))
        save(fig,f"所选运行的停车位置与时间过程  显示{len(shown)}帧 共{len(frames)}帧", "road_space_time")
    elif entities and any(number(e.get("x")) and number(e.get("y")) for e in entities):
        shown=[e for e in entities if number(e.get("x")) and number(e.get("y"))][:3000]
        fig,ax=plt.subplots(figsize=(7.4,2.7));ax.scatter([e["x"] for e in shown],[e["y"] for e in shown],s=9,c=COLORS[0],alpha=.7)
        ax.set(xlabel="模型横向位置 x",ylabel="模型纵向位置 y");ax.grid(alpha=.18)
        save(fig,f"当前实际主体位置  显示{len(shown)}个主体 共{len(entities)}个", "entity_positions")
    elif not entities:
        keys=[k for k in record["observations"][-1] if k not in ("sim_t",metric) and len({r.get(k) for r in record["observations"] if number(r.get(k))})>1][:3]
        if keys:
            fig,axes=plt.subplots(len(keys),1,figsize=(7.4,1.5*len(keys)),squeeze=False)
            for key,ax in zip(keys,axes.flat):
                ax.plot([r["sim_t"] for r in record["observations"]],[r.get(key,np.nan) for r in record["observations"]],c=COLORS[0],lw=1.2)
                ax.set(ylabel=NAMES.get(key,key),xlabel="模型时间 sim_t");ax.grid(alpha=.18)
            save(fig,"其他实际观测量的过程  各图使用独立纵轴", "other_observations")

    if view["entity_id"]:
        trace=[(f["sim_t"],next((e for e in f.get("entities",[]) if str(e.get("id"))==view["entity_id"]),{})) for f in frames]
        key=view.get("entity_metric") or next((k for k in ("speed","wealth","income","x","y") if any(number(e.get(k)) for _,e in trace)),None)
        if key:
            fig,ax=plt.subplots(figsize=(7.4,2.35));ax.plot([t for t,_ in trace],[e.get(key,np.nan) for _,e in trace],c=COLORS[0],lw=1.3)
            ax.set(xlabel="模型时间 sim_t",ylabel=NAMES.get(key,key));ax.grid(alpha=.18)
            save(fig,f"主体 {view['entity_id']} 的实际属性轨迹  缺失帧不插值", "selected_entity_trace")
    return figures
