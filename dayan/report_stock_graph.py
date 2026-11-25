"""Show only dependencies actually referenced by the archived stock equations."""
import ast
from collections import defaultdict
from math import cos, pi, sin


def stock_dependency_graph(definition, make_figure, colors, ink):
    from matplotlib.patches import FancyArrowPatch
    fields=list(definition["initial_state"])
    if not 2 <= len(fields) <= 10:
        return None
    parents=defaultdict(set)
    for target,expression in definition["rates"].items():
        refs={node.id for node in ast.walk(ast.parse(str(expression),mode="eval")) if isinstance(node,ast.Name)}
        parents[target].update(name for name in fields if name in refs and name!=target)
    links=[(name,target) for target in fields for name in fields if name in parents[target]]
    if not links:
        return None
    layers=[]
    placed=set()
    while len(placed)<len(fields):
        nodes=[name for name in fields if name not in placed and parents[name]<=placed]
        if not nodes:
            break
        layers.append(nodes)
        placed.update(nodes)
    if len(placed)==len(fields):
        pos={name:((i+1)/(len(layers)+1),1-(j+1)/(len(layer)+1))
             for i,layer in enumerate(layers) for j,name in enumerate(layer)}
    else:
        pos={name:(.5+.36*cos(2*pi*i/len(fields)),.5+.35*sin(2*pi*i/len(fields))) for i,name in enumerate(fields)}
    fig,axes=make_figure(2.35 if len(fields)<5 else 3.2)
    ax=axes[0,0]
    ax.set(xlim=(0,1),ylim=(0,1))
    ax.set_axis_off()
    for source,target in links:
        two_way=(target,source) in links
        ax.add_patch(FancyArrowPatch(pos[source],pos[target],transform=ax.transAxes,arrowstyle="-|>",
                                     connectionstyle="arc3,rad=.14" if two_way else "arc3",
                                     shrinkA=37,shrinkB=37,mutation_scale=12,color=ink,alpha=.65,zorder=1))
    for i,name in enumerate(fields):
        color=colors[i%len(colors)]
        ax.text(*pos[name],name,transform=ax.transAxes,ha="center",va="center",color=color,zorder=2,fontsize=9.3,
                bbox={"boxstyle":"round,pad=.55","facecolor":"#f0f5f7","edgecolor":color,"linewidth":1.05})
    return fig,[{"source":source,"target":target} for source,target in links]
