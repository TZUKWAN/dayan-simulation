"""3D trajectories and complete floor occupancy from archived program populations."""
from collections import Counter
import numpy as np
from .research_charts import figure,axis_grid,COLORS,SPACE
from .population_groups import decode_attribute


def render(frames,record,save):
    frames=[f for f in frames if f.get('space',{}).get('vertical_bounds')]
    if not frames:return
    unit=frames[0]['space']['unit'];traces={};counts=[]
    for frame in frames:
        current=Counter()
        for group in frame.get('population',{}).get('groups',[]):
            if 'floor_id' in group['columns']:
                current.update(str(v) for v in decode_attribute(group['columns']['floor_id'],group['count']))
        counts.append(dict(current))
        for entity in frame.get('entities',[])[:24]:
            if all(type(entity.get(k)) in (int,float) for k in ('x','y','z')):
                traces.setdefault(str(entity['id']),[]).append([frame['sim_t'],entity['x'],entity['y'],entity['z']])
    if traces:
        fig,axes=figure(3.2);ax=axes[0,0]
        for i,(ident,trace) in enumerate(traces.items()):
            ax.plot([p[0] for p in trace],[p[3] for p in trace],c=COLORS[i%len(COLORS)],lw=1.2,label=ident if i<8 else None)
        ax.set(xlabel='模型时间（'+record['manifest']['model_definition']['time_unit']+'）',ylabel='实际z高度（'+unit+'）');axis_grid(ax)
        if len(traces)<=8:ax.legend(frameon=False,fontsize=7,ncol=2)
        save(fig,'主体真实高度随时间变化','vertical_trajectories',SPACE,
            f'显示实际归档预览中的{len(traces)}名主体；高度直接来自完整x/y/z状态，不由楼层标签补造。线段仅连接保存时点。',
            traces=traces,unit=unit)
        fig,axes=figure(3.6);axes[0,0].remove();ax=fig.add_subplot(111,projection='3d')
        for i,(ident,trace) in enumerate(traces.items()):
            ax.plot([p[1] for p in trace],[p[2] for p in trace],[p[3] for p in trace],c=COLORS[i%len(COLORS)],lw=1.4)
        for connection in frames[0]['space'].get('connectors',[]):
            route=np.array(connection['polyline']);ax.plot(route[:,0],route[:,1],route[:,2],c='#a98951',ls='--',lw=1)
        ax.set(xlabel='x / '+unit,ylabel='y / '+unit,zlabel='z / '+unit)
        save(fig,'三维真实轨迹与通行连接','spatial_3d_paths',SPACE,
            '轨迹取同号运行真实状态；虚线为模型声明的通行连接，几何布局的现实依据见方案和数据来源。',entities=len(traces),space=frames[0]['space'])
    names=list(dict.fromkeys(key for row in counts for key in row))
    if names:
        shown=names[:29]+(['其他'] if len(names)>29 else [])
        matrix=np.array([[row.get(key,0) if key!='其他' else sum(v for k,v in row.items() if k not in names[:29]) for row in counts] for key in shown])
        fig,axes=figure(max(2.4,len(shown)*.3+1.))
        ax=axes[0,0];image=ax.imshow(matrix,aspect='auto',interpolation='nearest',cmap='YlGnBu')
        ax.set_yticks(range(len(shown)),shown)
        ticks=list(range(0,len(frames),max(1,len(frames)//7)));ax.set_xticks(ticks,[f'{frames[i]["sim_t"]:g}' for i in ticks])
        ax.set_xlabel('实际归档时刻');fig.colorbar(image,ax=ax,label='完整人口数')
        save(fig,'楼层、地形与通道的主体流转','floor_occupancy',SPACE,
            '按全量人口floor_id逐帧计数；不是显示采样计数。超过29个位置时其余合并显示，事实保留全部。',
            times=[f['sim_t'] for f in frames],full_counts=counts,scope='full_population')
