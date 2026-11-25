"""Spatial and individual report figures backed by saved frames."""
from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np

from .research_charts import COLORS, DRILL_EVENTS, INK, RESULTS, SPACE, _clock, axis_grid, figure, units_label
from .view_analysis import in_window, metric_info, number, present_entities

STATES = {
    "waiting":("停留","#7b8e9e"), "fallen":("倒地待助","#ba7336"), "seated":("受助状态","#8d61ac"),
    "walking":("移动","#176d78"),
}
DRILL_STAGES = {"drill_fall":"预定倒地", "aid_started":"协助开始", "aid_completed":"恢复活动"}


def _coords(entities):
    return {str(e["id"]):(e["x"],e["y"]) for e in entities
            if e.get("type") != "age_group" and e.get("id") is not None and number(e.get("x")) and number(e.get("y"))}


def _bounds(frame):
    raw = (frame.get("space") or {}).get("bounds") or []
    return tuple(raw) if len(raw)==4 and all(number(value) for value in raw) and raw[2]>raw[0] and raw[3]>raw[1] else ()


def _map_axes(ax, frame, *, draw_facilities=True):
    from matplotlib.patches import Rectangle
    x0,y0,x1,y1 = _bounds(frame)
    swap = y1-y0 > 1.4*(x1-x0)
    unit = frame["space"].get("unit") or "模型空间单位"
    xlim, ylim = ((y0,y1),(x0,x1)) if swap else ((x0,x1),(y0,y1))
    ax.set(xlim=xlim,ylim=ylim,aspect="equal",facecolor="#eef4f6",
           xlabel=f"{'纵向 y' if swap else '横向 x'}（{unit}）",
           ylabel=f"{'横向 x' if swap else '纵向 y'}（{unit}）")
    ax.tick_params(labelsize=8)
    if draw_facilities:
        for item in frame.get("facilities",[]):
            if item.get("kind") not in ("exit","obstacle","zone","building","destination","service") or not all(
                    number(item.get(key)) for key in ("x","y","width","depth")):
                continue
            x,y,w,h = (item[k] for k in ("x","y","width","depth"))
            if swap:
                x,y,w,h=y,x,h,w
            exit_mark = item.get("kind")=="exit"
            ax.add_patch(Rectangle((x-w/2,y-h/2),w,h,facecolor="#b9e2dd" if exit_mark else "#c4d1d8",
                                   edgecolor=COLORS[0] if exit_mark else "#587485",zorder=2,clip_on=not exit_mark))
    return swap


def _ordered_frames(record, view):
    frames=[]
    for frame in record.get("state_frames") or []:
        t = frame.get("sim_t")
        if number(t) and in_window(t,view["window"]) and (not frames or t>frames[-1]["sim_t"]):
            frames.append(frame)
    return frames


def _scenes(spatial, events, save):
    picks = [spatial[0]]
    stages = {}
    for i,event in enumerate(events):
        upper = events[i+1]["sim_t"] if i+1<len(events) else float("inf")
        hit = next((frame for frame in spatial if event["sim_t"] <= frame["sim_t"] < upper),None)
        if hit:
            picks.append(hit)
            stages[hit["sim_t"]] = DRILL_STAGES.get(event["etype"], "")
    if len(picks)==1 and len(spatial)>1:
        picks.extend([spatial[len(spatial)//2],spatial[-1]])
    picks = list({frame["sim_t"]:frame for frame in picks}.values())[:4]
    columns = 1 if len(picks)==1 else 2
    rows = (len(picks)+columns-1)//columns
    x0,y0,x1,y1 = _bounds(spatial[0])
    fig, axes = figure((1.65*rows+.35) if y1-y0>1.4*(x1-x0) else 2.7*rows, columns=columns, rows=rows)
    legend={}
    for ax,frame in zip(axes.flat,picks):
        swap = _map_axes(ax,frame)
        groups = defaultdict(list)
        entities = present_entities(frame)
        positions = _coords(entities)
        for entity in entities:
            ident=str(entity.get("id"))
            if ident not in positions:
                continue
            groups[STATES.get(entity.get("state"),("其他在场主体",COLORS[0]))].append(positions[ident])
        for (label,color),pts in groups.items():
            x,y=zip(*pts)
            legend[label]=ax.scatter(y if swap else x,x if swap else y,s=13 if label not in ("倒地待助","受助状态") else 34,
                                     color=color,zorder=4,label=label,alpha=.82)
        stage = stages.get(frame["sim_t"], "")
        ax.set_title(f"{stage}   t = {frame['sim_t']:g}   在图主体 {len(positions)}".lstrip(),loc="left",fontsize=8.7)
    for ax in list(axes.flat)[len(picks):]:
        ax.set_visible(False)
    if legend:
        fig.legend(legend.values(),legend.keys(),loc="outside lower center",frameon=False,fontsize=8,ncol=min(5,len(legend)))
    save(fig,"典型时点的场景快照","scene_sequence",SPACE,
         "图中的圆点来自对应保存帧。设施沿用归档位置；狭长场地以纵向坐标作横轴。",
         frame_times=[frame["sim_t"] for frame in picks])


def _space_density(spatial, coordinates, record, save):
    if len(spatial)<2 or not any(coordinates):
        return
    basis = spatial[0]
    x0,y0,x1,y1 = _bounds(basis)
    nx=max(4,round(18*(x1-x0)/max(x1-x0,y1-y0)))
    ny=max(4,round(18*(y1-y0)/max(x1-x0,y1-y0)))
    xbins,ybins = np.linspace(x0,x1,nx+1),np.linspace(y0,y1,ny+1)
    samples = [np.histogram2d(*zip(*data.values()),bins=[xbins,ybins])[0] if data else np.zeros((nx,ny))
               for data in coordinates]
    average = np.mean(samples,axis=0)
    maximum = float(average.max())
    if maximum<=0:
        return
    fig, axes = figure(2.5 if y1-y0>1.4*(x1-x0) else 3.4)
    ax = axes[0,0]
    swap = _map_axes(ax,basis)
    mesh = ax.pcolormesh(ybins if swap else xbins, xbins if swap else ybins, average if swap else average.T,
                         cmap="YlGnBu",vmin=0,shading="flat",zorder=1)
    fig.colorbar(mesh,ax=ax,label="每帧每格平均主体数",pad=.035)
    save(fig,"空间占用热图","spatial_occupancy",SPACE,
         f"同一场地的 {len(spatial)} 帧等权统计，网格为 {nx} × {ny}。颜色表示网格平均占用。",
         frames=len(spatial),bins=[nx,ny],max_mean_occupancy=maximum)

    if len(spatial)<3:
        return
    fig, axes = figure(2.45)
    ax = axes[0,0]
    times = np.asarray([frame["sim_t"] for frame in spatial])
    # Plot actual frame times instead of evenly spacing sparsely saved frames.
    time_edges = np.r_[times[0],(times[:-1]+times[1:])/2,times[-1]]
    along = [data.sum(axis=0) if y1-y0 >= x1-x0 else data.sum(axis=1) for data in samples]
    distance_edges = ybins if y1-y0 >= x1-x0 else xbins
    mesh = ax.pcolormesh(time_edges, distance_edges, np.asarray(along).T, cmap="YlGnBu",vmin=0,shading="flat")
    unit = basis["space"].get("unit") or "模型空间单位"
    ax.set(xlabel=_clock(record), ylabel=f"{'纵向 y' if y1-y0>=x1-x0 else '横向 x'}（{unit}）")
    fig.colorbar(mesh,ax=ax,label="位置带内的主体数",pad=.025)
    save(fig,"空间占用随时间迁移","spatial_time_occupancy",SPACE,
         f"沿场地长轴分带，逐帧统计真实位置。每列代表一帧，共 {len(spatial)} 帧。",
         frames=len(spatial),position_axis="y" if y1-y0>=x1-x0 else "x")


def _trajectory(spatial, coordinates, events, focus, save):
    counts=Counter(ident for data in coordinates for ident in data)
    usable=sorted(ident for ident,n in counts.items() if n>=3)
    if not usable:
        return
    highlighted=list(dict.fromkeys([focus,*[str(e.get("entity_id")) for e in events]]))
    chosen=[ident for ident in highlighted if ident in usable][:4]
    remaining=[ident for ident in usable if ident not in chosen]
    sample=min(8-len(chosen),len(remaining))
    if sample:
        chosen.extend(remaining[index] for index in np.linspace(0,len(remaining)-1,sample,dtype=int))
    fig, axes = figure(2.5 if _bounds(spatial[0])[3]-_bounds(spatial[0])[1] > 1.4*(_bounds(spatial[0])[2]-_bounds(spatial[0])[0]) else 3.15)
    ax=axes[0,0]
    swap=_map_axes(ax,spatial[0])
    for i,ident in enumerate(chosen):
        first = next(data[ident] for data in coordinates if ident in data)
        xy = np.asarray([data.get(ident,(np.nan,np.nan)) for data in coordinates])
        x,y = (xy[:,1],xy[:,0]) if swap else (xy[:,0],xy[:,1])
        emphasis=ident in highlighted
        color=COLORS[2] if emphasis else COLORS[i%len(COLORS)]
        ax.plot(x,y,c=color,alpha=.9 if emphasis else .6,lw=2 if emphasis else 1.1,
                label=("重点主体 "+ident) if emphasis else None,zorder=4)
        ax.scatter(*first[::-1] if swap else first,c=color,s=13,zorder=5)
    if any(ident in highlighted for ident in chosen):
        ax.legend(loc="best",frameon=False,fontsize=8)
    scope = '显示样本' if any(frame.get('population') for frame in spatial) else '完整归档'
    save(fig,"个体轨迹样本","entity_trajectories",SPACE,
         f"从{scope}的 {len(usable)} 个至少保存三次坐标的主体中显示 {len(chosen)} 条实际轨迹。实心点为首个有效位置，缺失处断线。",
         frames=len(spatial),shown_entities=chosen,eligible_entities=len(usable),selection_scope=scope)


def _speed_band(frames, record, save):
    from .population_groups import is_grouped
    grouped = any(is_grouped(frame.get('population')) for frame in frames)
    if grouped:
        series = {}
        for frame in frames:
            for group in (frame.get('population') or {}).get('groups', []):
                if 'speed' in group['columns']:
                    series[group['id']+'.speed'] = (group['label'],group['units'].get('speed'))
        for field,(label,unit) in series.items():
            _speed_series(frames,record,save,field,label,unit)
        return
    _speed_series(frames,record,save,'speed')


def _speed_series(frames, record, save, field, label=None, unit=None):
    data=[]
    for frame in frames:
        if frame.get('population'):
            from .population_analysis import distribution
            from .population_groups import is_grouped
            population = frame['population']
            if is_grouped(population):
                group_id, name = field.split('.', 1)
                available = any(group['id'] == group_id and name in group['columns']
                                for group in population['groups'])
            else:
                available = field in population['columns']
            # A group can enter or leave. Corrupt columns must still fail rather
            # than being silently reported as an ordinary missing time point.
            summary = distribution(frame, field) if available else {'n':0}
            points = ([summary['quantiles'][q] for q in ('0.25', '0.5', '0.75')]
                      if summary['n'] >= 2 and summary.get('quantiles') else [float('nan')] * 3)
        else:
            speeds=[e["speed"] for e in present_entities(frame) if number(e.get("speed"))]
            points=np.quantile(speeds,[.25,.5,.75]) if len(speeds)>=2 else [float("nan")]*3
        data.append((frame["sim_t"],*points))
    if len(data)<3:
        return
    t, low, mid, high = np.asarray(data).T
    valid=int(np.isfinite(mid).sum())
    if valid<3:
        return
    fig, axes=figure(2.55)
    ax=axes[0,0]
    ax.fill_between(t,low,high,color=COLORS[0],alpha=.19,label="在场主体第 25 至 75 百分位")
    ax.plot(t,mid,color=COLORS[0],lw=1.65,label="在场主体中位数")
    ax.set(xlabel=_clock(record),ylabel=(f'{label} · 速度（{unit or "未知单位"}）' if label else units_label(metric_info(record["model_id"],"speed"))))
    ax.legend(frameon=False,fontsize=8)
    axis_grid(ax)
    save(fig,"速度分布怎样变化"+(f' · {label}' if label else ''),"speed_quantiles",SPACE,
         f"使用 {valid} 个至少有两名有效在场主体的保存帧。带宽描述主体间速度差异。",
         valid_frames=valid,field=field, unit=unit, group_label=label, quantiles=[list(row) for row in data],
         scope='full_population' if all(frame.get('population') for frame in frames) else 'archived_entities')


def _events(events, record, save):
    if len(events)<2:
        return
    fig,axes=figure(2.15)
    ax=axes[0,0]
    labels=[event["label"] if event.get("label") else event["etype"] for event in events]
    times=[event["sim_t"] for event in events]
    i=np.arange(len(events))
    ax.scatter(times,i,c=[COLORS[k%len(COLORS)] for k in i],s=35,zorder=3)
    for t,j in zip(times,i):
        ax.annotate(f"{t:g}",(t,j),xytext=(8,0),textcoords="offset points",fontsize=8,va="center")
    ax.margins(x=.18,y=.35)
    ax.set_yticks(i,labels)
    ax.set_xlabel(_clock(record))
    ax.invert_yaxis()
    axis_grid(ax,which="x")
    save(fig,"演练事件时间线","event_timeline",RESULTS,
         "逐项使用实际归档的阶段转换时间。预设事件与模型计算的状态变化同源。",
         events=[{"type":event["etype"],"sim_t":event["sim_t"]} for event in events])


def _distribution(focus, view, record, save):
    from matplotlib.ticker import PercentFormatter
    if focus and focus.get('population'):
        from .population_analysis import distribution
        field = view['distribution_field'] or view['distribution'].get('field') or focus['population'].get('color_by') or 'group'
        summary = distribution(focus, field, view.get('distribution_region'))
        fig, axes = figure(2.4)
        ax = axes[0,0]
        if summary.get('cdf'):
            curve = np.asarray(summary['cdf'])
            if summary['cdf_complete']:
                ax.step(np.r_[curve[0,0],curve[:,0]], np.r_[0,curve[:,1]], where='post', c=COLORS[0], lw=1.7)
            else:
                ax.plot(curve[:,0], curve[:,1], c=COLORS[0], lw=1.7)
            info = metric_info(record['model_id'],field)
            if 'unit' in summary:
                info = {**info, 'unit':summary['unit'] or '未知单位'}
            ax.set(xlabel=units_label(info), ylabel='累计主体比例', ylim=(0,1.04))
            ax.yaxis.set_major_formatter(PercentFormatter(1))
        else:
            counts = summary.get('counts', {})
            ax.scatter(list(counts.values()), range(len(counts)), c=COLORS[0])
            ax.set_yticks(range(len(counts)), list(counts))
            ax.set_xlabel('主体数')
        axis_grid(ax, which='x')
        scope = f"选区 {view['distribution_region']} 内" if view.get('distribution_region') else '所选人口范围内'
        method = ('累计概率从完整排序计算，曲线最多保留129个真实概率点。'
                  if summary.get('cdf') else '逐类别统计完整归档中的实际主体数。')
        excluded = (f" 缺失值 {summary.get('missing',0)} 个；其他组中不适用该属性的主体 {summary.get('not_applicable',0)} 个，均未补零。"
                    if summary.get('missing') or summary.get('not_applicable') else '')
        save(fig, '全量主体分布', 'entity_distribution', SPACE,
             f"使用 t={focus['sim_t']:g} {scope}该属性全部 {summary['n']:,} 个有效主体。"+method+excluded,
             count=summary['n'], frame_times=[focus['sim_t']], field=field,
             distribution=summary, scope='full_population', region=view.get('distribution_region'))
        return
    field = view["distribution_field"] or view["distribution"].get("field")
    if not field:
        field = next((key for key in ("speed","wealth","income","state","group")
                      if any(key in e for e in present_entities(focus))),None)
    if not field or focus is None:
        return
    entities = present_entities(focus)
    if view.get('distribution_region'):
        x0,y0,x1,y1 = view['distribution_region']
        bounds = focus.get('space', {}).get('bounds', [])
        entities = [e for e in entities if number(e.get('x')) and number(e.get('y')) and
                    x0 <= e['x'] and (e['x'] <= x1 if len(bounds)==4 and x1==bounds[2] else e['x'] < x1) and
                    y0 <= e['y'] and (e['y'] <= y1 if len(bounds)==4 and y1==bounds[3] else e['y'] < y1)]
    vals = [e[field] for e in entities if number(e.get(field)) or isinstance(e.get(field),(str,bool))]
    if not vals:
        return
    fig, axes = figure(2.4)
    ax=axes[0,0]
    label=units_label(metric_info(record["model_id"],field))
    if all(number(value) for value in vals):
        values=np.sort(vals)
        ax.step(np.r_[values[0],values],np.arange(len(values)+1)/len(values),where="post",c=COLORS[0],lw=1.7)
        ax.set(xlabel=label,ylabel="累计主体比例",ylim=(0,1.04))
        ax.yaxis.set_major_formatter(PercentFormatter(1))
    else:
        counts=Counter(map(str,vals))
        shown=counts.most_common(10)
        if len(shown)<len(counts):
            shown.append(("其他",len(vals)-sum(value for _,value in shown)))
        ax.set_yticks(range(len(shown)),[name for name,_ in shown])
        ax.scatter([count for _,count in shown],range(len(shown)),color=COLORS[0],s=27)
        ax.set_xlabel("主体数")
        ax.invert_yaxis()
    axis_grid(ax,which="x")
    outside = "该时点为另外选定的观察帧。" if not in_window(focus["sim_t"], view["window"]) else ""
    save(fig,"单帧主体分布","entity_distribution",SPACE,
         f"使用保存帧 t = {focus['sim_t']:g} 的 {len(vals)} 个有效主体值。"+outside,
         count=len(vals),frame_times=[focus["sim_t"]],field=field)


def _road_heatmap(frames, cells, record, save):
    from matplotlib.colors import ListedColormap
    cells=int(cells)
    if not 0<cells<=2000 or len(frames)<2:
        return
    data=np.full((len(frames),cells),np.nan)
    for index,item in enumerate(frames):
        for entity in present_entities(item):
            x,speed=entity.get("x"),entity.get("speed")
            if number(x) and number(speed) and 0<=x<cells:
                data[index,int(x)]=int(speed>0)
    if not np.isfinite(data).any():
        return
    fig,axes=figure(2.75)
    ax=axes[0,0]
    ts=np.array([item["sim_t"] for item in frames])
    edges=np.r_[ts[0],(ts[:-1]+ts[1:])/2,ts[-1]]
    image=ax.pcolormesh(np.arange(cells+1),edges,data,shading="flat",
                        cmap=ListedColormap(["#b76c41",COLORS[0]]),vmin=0,vmax=1)
    ax.invert_yaxis()
    ax.set(xlabel="道路位置（格）",ylabel=_clock(record),facecolor="#edf3f6")
    fig.colorbar(image,ax=ax,ticks=[0,1],pad=.025).set_ticklabels(["停车","行驶"])
    save(fig,"道路车流时空图","road_space_time",SPACE,
         f"显示窗口内 {len(frames)} 个真实保存帧，浅背景为无车格。",frames=len(frames),road_cells=cells)


def _individual(frames, record, view, save):
    ident=view.get("entity_id")
    if not ident:
        return
    from .population import entity_trace
    all_rows = view.get('entity_trace') or entity_trace(record.get('state_frames') or [], ident)
    by_time = {row['sim_t']:row for row in all_rows}
    series = [by_time.get(frame['sim_t'], {}) for frame in frames]
    key=view.get("entity_metric") or next((k for k in ("speed","wealth","income","x","y")
                                         if any(number(e.get(k)) for e in series)),None)
    if not key or not any(number(e.get(key)) for e in series):
        return
    fig,axes=figure(2.35)
    ax=axes[0,0]
    ax.plot([f["sim_t"] for f in frames],[e[key] if number(e.get(key)) else np.nan for e in series],
            color=COLORS[0],lw=1.35,marker="o" if len(frames)==1 else None)
    ax.set(xlabel=_clock(record),ylabel=units_label(metric_info(record["model_id"],key)))
    axis_grid(ax)
    save(fig,"所选主体的属性轨迹","selected_entity_trace",SPACE,
         f"主体 {ident} 的归档属性。缺失时点保持断线。",entity_id=ident,field=key)


def _lattice_maps(frames, save):
    import base64
    from matplotlib.colors import ListedColormap
    from matplotlib.patches import Patch
    from .population_groups import is_grouped

    picks = list(dict.fromkeys((0, len(frames)//2, len(frames)-1)))
    for index in picks:
        frame = frames[index]
        grid = frame["lattice"]
        layers = grid["layers"]
        fig, axes = figure(2.8, columns=len(layers))
        population = frame.get("population")
        if population and not is_grouped(population):
            from .population import decode_column
            shape = population["grid"]
            field = population["color_by"]
            values = decode_column(population["columns"][field], population["count"])
            axis = axes[0,0]
            map_image = axis.imshow(values.reshape(shape["rows"], shape["columns"]), interpolation="nearest", cmap="viridis")
            fig.colorbar(map_image, ax=axis, label=layers[0]["label"])
            axis.set_xlabel("元胞列")
            axis.set_ylabel("元胞行")
            save(fig, f"完整网格状态 · 第 {frame['sim_t']:g} 步", "lattice_state", SPACE,
                 f"该时点的 {shape['rows']}×{shape['columns']} 元胞从完整状态列直接读取。",
                 sim_t=frame["sim_t"], cells=population["count"], field=field,
                 minimum=float(values.min()), maximum=float(values.max()), total=float(values.sum()))
            continue
        if grid.get('encoding') == 'u8-preview':
            for axis, layer in zip(axes[0], layers):
                values = np.frombuffer(base64.b64decode(layer['values'], validate=True), dtype=np.uint8)
                mesh = axis.imshow(values.reshape(grid['height'], grid['width']),
                                   interpolation='nearest', cmap='viridis', vmin=0, vmax=255)
                axis.set(title=layer['label'], xlabel='显示列', ylabel='显示行')
                fig.colorbar(mesh, ax=axis, label='归档显示强度（0–255）')
            save(fig, f"网格场显示预览 · t={frame['sim_t']:g}", 'lattice_preview', SPACE,
                 f"归档显示预览为 {grid['width']}×{grid['height']}，源网格为 "
                 f"{grid['source_width']}×{grid['source_height']}。显示强度经过聚合与量化，不能用于逐格数值或主体数量统计。",
                 sim_t=frame['sim_t'], preview_only=True, width=grid['width'], height=grid['height'],
                 source_width=grid['source_width'], source_height=grid['source_height'])
            continue
        layers_evidence = {}
        for axis, layer, active in zip(axes[0], layers, ("#c06932", "#207e9a", "#36754c")):
            values = np.frombuffer(layer["values"].encode("ascii"), dtype=np.uint8) - 48
            axis.imshow(values.reshape(grid["height"], grid["width"]),
                        interpolation="nearest", cmap=ListedColormap(["#e6eef1", active]), vmin=0, vmax=1)
            axis.set_title(layer["label"])
            axis.set_xlabel("元胞列")
            if axis is axes[0, 0]:
                axis.set_ylabel("元胞行")
            axis.legend(handles=[Patch(color=c, label=state)
                                 for c, state in zip(("#e6eef1", active), layer["states"])],
                        loc="upper center", bbox_to_anchor=(.5, -.25), ncols=2,
                        frameon=False, fontsize=7)
            layers_evidence[layer["id"]] = int(values.sum())
        save(fig, f"网格状态空间分布 · t={frame['sim_t']:g}", "lattice_state", SPACE,
             f"同一时点的 {grid['width']}×{grid['height']} 完整二元状态格点，各层含义由归档图例给出。",
             sim_t=frame["sim_t"], cells=grid["width"]*grid["height"], layer_counts=layers_evidence)


def _population_density(frame, save, *, group_label=None):
    from .population_analysis import spatial_density
    population = frame["population"]
    summary = spatial_density(frame)
    count = summary['n']
    counts = np.asarray(summary['counts'])
    xs, ys = summary['x_edges'], summary['y_edges']
    fig, axes = figure(2.8, columns=1)
    ax = axes[0, 0]
    display = ax.imshow(counts, extent=[xs[0],xs[-1],ys[0],ys[-1]], origin="lower", cmap="viridis", aspect="auto")
    fig.colorbar(display, ax=ax, label="分区主体数")
    unit = summary.get('unit') or frame.get('space',{}).get('unit')
    ax.set_xlabel(f'x（{unit}）' if unit else 'x')
    ax.set_ylabel(f'y（{unit}）' if unit else 'y')
    save(fig, f"全量主体空间分布 · {group_label+' · ' if group_label else ''}{frame['sim_t']:g}", "population_density", SPACE,
         f"按这一保存时点的全部 {count:,} 个实际坐标分区计数，范围外 {summary['outside_bounds']} 个。"
         + (f" 另有 {summary['not_spatial']} 个无二维坐标主体未放入此图。" if summary.get('not_spatial') else ''),
         entities=count, histogram_total=int(counts.sum()), outside_bounds=summary['outside_bounds'],
         sim_t=frame["sim_t"], density=summary, population_total=population['count'], group_label=group_label)


def _population_density_history(frames, record, save):
    from .population_analysis import spatial_density
    bounds = _bounds(frames[0])
    if len(frames) < 3 or not bounds or any(_bounds(frame)!=bounds for frame in frames):
        return
    summaries = [spatial_density(frame) for frame in frames]
    axis = 'y' if bounds[3]-bounds[1] >= bounds[2]-bounds[0] else 'x'
    profiles = np.array([np.asarray(item['counts']).sum(axis=1 if axis=='y' else 0) for item in summaries])
    times = np.array([frame['sim_t'] for frame in frames])
    edges = np.r_[times[0], (times[:-1]+times[1:])/2, times[-1]]
    positions = summaries[0][axis+'_edges']
    fig, axes = figure(2.7)
    ax = axes[0,0]
    mesh = ax.pcolormesh(edges, positions, profiles.T, cmap='viridis', shading='flat', vmin=0)
    fig.colorbar(mesh, ax=ax, label='位置带内全量主体数')
    ax.set(xlabel=_clock(record), ylabel=f"{axis}（{frames[0]['space'].get('unit') or '模型空间单位'}）")
    save(fig, '全量空间分布随时间变化', 'spatial_time_occupancy', SPACE,
         f'沿场地长轴分带，使用窗口内全部 {len(frames)} 个实际保存帧；每带计数来自完整主体坐标。',
         frames=len(frames), times=times.tolist(), position_axis=axis, scope='full_population',
         population_per_frame=[item['n'] for item in summaries],
         in_bounds_per_frame=[item['count_in_bounds'] for item in summaries])


def spatial_figures(record, view, save):
    from .population_groups import is_grouped
    frames=_ordered_frames(record,view)
    from .report_vertical_charts import render as vertical_charts
    vertical_charts(frames,record,save)
    from .report_state_charts import state_figures
    state_figures(frames, record, view, save)
    grids = [frame for frame in frames if frame.get("lattice")]
    if view["frame_explicit"]:
        selected = next((frame for frame in (record.get("state_frames") or [])
                         if frame.get("lattice") and frame["sim_t"] == view["frame_time"]), None)
        if selected:
            grids = [selected]
    if grids:
        _lattice_maps(grids, save)
        if not any(is_grouped(frame.get('population')) for frame in grids):
            focus = next((frame for frame in record.get('state_frames', []) if frame['sim_t']==view['frame_time']), None)
            if focus and focus.get('population'):
                _distribution(focus, view, record, save)
            _individual(frames, record, view, save)
            return
    population_frames = [frame for frame in frames if frame.get("population")]
    if population_frames:
        focus_frames = record.get('state_frames', []) if view['frame_explicit'] else population_frames
        focus = next((frame for frame in focus_frames if frame['sim_t'] == view['frame_time']), None)
        if focus is None:
            return
        from .population_groups import is_grouped
        if is_grouped(focus['population']):
            from .population_analysis import spatial_density
            try:
                spatial_density(focus)
            except ValueError:
                # Distinct coordinate units cannot share a density plane. Show
                # actual spatial groups separately, without inventing positions.
                from .population_group_analysis import _single
                for group in focus['population']['groups']:
                    if not {'x','y'} <= group['columns'].keys() or not group['count']:
                        continue
                    local = _single(focus,group)
                    local['space'] = {'unit':group['units'].get('x')}
                    if group['units'].get('x') and group['units'].get('x') == group['units'].get('y'):
                        _population_density(local,save,group_label=group['label'])
            else:
                _population_density(focus, save)
                # A changed coordinate contract cannot produce a common history.
                try:
                    for frame in population_frames:
                        spatial_density(frame)
                except ValueError:
                    pass
                else:
                    _population_density_history(population_frames, record, save)
        else:
            _population_density(focus, save)
            _population_density_history(population_frames, record, save)
        _distribution(focus, view, record, save)
        _speed_band(frames, record, save)
        _events([event for event in record.get('events', []) if number(event.get('sim_t'))
                 and in_window(event['sim_t'], view['window'])], record, save)
        _individual(frames, record, view, save)
        if all(_bounds(frame) for frame in population_frames):
            _trajectory(population_frames, [_coords(frame.get('entities', [])) for frame in population_frames],
                        [], view.get('entity_id'), save)
        return
    focus_frames = (record.get("state_frames") or []) if view["frame_explicit"] else frames
    focus=next((frame for frame in reversed(focus_frames) if frame["sim_t"]==view["frame_time"]),None)
    if focus is not None and not present_entities(focus) and not view["frame_explicit"]:
        populated = [frame for frame in frames if present_entities(frame)]
        focus = populated[len(populated)//2] if populated else None
    if not frames:
        _distribution(focus,view,record,save)
        return
    events=sorted([e for e in record.get("events",[]) if e.get("etype") in DRILL_EVENTS and
                   number(e.get("sim_t")) and in_window(e["sim_t"],view["window"])],key=lambda e:e["sim_t"])
    _events(events[:12],record,save)
    road=next((item for frame in frames for item in frame.get("facilities",[])
               if item.get("type")=="road" and number(item.get("length"))),None)
    if road:
        _road_heatmap(frames,road["length"],record,save)
    else:
        suitable=[frame for frame in frames if _bounds(frame)]
        if suitable:
            reference=_bounds(suitable[0])
            spatial=[frame for frame in suitable if _bounds(frame)==reference and
                     (frame["space"].get("unit") or "")== (suitable[0]["space"].get("unit") or "")]
            coordinates=[_coords(present_entities(frame)) for frame in spatial]
            if any(coordinates):
                _scenes(spatial,events,save)
                _space_density(spatial,coordinates,record,save)
                _trajectory(spatial,coordinates,events,view.get("entity_id"),save)
    _distribution(focus,view,record,save)
    if not road:
        _speed_band(frames,record,save)
    _individual(frames,record,view,save)
