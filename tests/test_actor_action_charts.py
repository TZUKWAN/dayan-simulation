"""The actual chart keeps actor identity when decision batches change names."""
import numpy as np
from dayan.research_charts import _actor_action_heatmaps


def chart(records):
    captured=[]
    def save(fig,*args,**evidence):
        captured.append((fig,evidence))
    _actor_action_heatmaps({'manifest':{'actor_decisions':{'records':records}}},{'from':0,'to':3,'exclusive':False},save)
    return captured[0]


def boundary(time,batches):
    return {'descriptor':{'time':time,'key':str(time)},'receipts':[
        {'batch_id':name,'actions':[{'actor_id':actor,'action':action} for actor,action in actions]}
        for name,actions in batches]}


def test_batch_renaming_and_repacking_keep_real_person_on_one_row():
    fig,evidence=chart([boundary(0,[('t0-pack',[('a','walk'),('b','wait')])]),
        boundary(3,[('t3-b',[('b','walk')]),('t3-a',[('a','wait')])])])
    matrix=fig.axes[0].images[0].get_array()
    assert matrix.shape==(2,2) and not np.ma.getmaskarray(matrix).any()
    assert list(fig.axes[0].get_yticklabels()[i].get_text() for i in range(2))==['a','b']
    assert matrix[0,0]==matrix[1,1] and matrix[0,1]==matrix[1,0] and matrix[0,0]!=matrix[0,1]
    assert evidence['action_records']==4 and evidence['total_actors']==2


def test_multiple_real_same_time_actor_decisions_remain_separate():
    fig,evidence=chart([boundary(0,[('channel-1',[('a',1)]),('channel-2',[('a',2)])])])
    matrix=fig.axes[0].images[0].get_array()
    assert matrix.shape==(2,1) and sorted(matrix[:,0])==[1,2]
    assert evidence['action_records']==2
