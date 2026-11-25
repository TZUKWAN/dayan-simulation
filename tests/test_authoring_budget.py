"""Separate research waiting from numerical caps; controlled clock, real child."""
from collections import deque
import json
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from dayan.agent.design_checkpoint import DesignCheckpoint
from dayan.limits import Limits,authoring_wall_seconds,limits
from dayan.task_manager import TaskManager


def test_authoring_default_and_explicit_operator_caps_keep_numerical_limits(monkeypatch,tmp_path):
    monkeypatch.delenv('DAYAN_WALL_SECONDS',raising=False)
    monkeypatch.delenv('DAYAN_AUTHORING_WALL_SECONDS',raising=False)
    assert limits().wall_seconds==240 and authoring_wall_seconds()==900
    checkpoint=DesignCheckpoint({},tmp_path/'stages.json',[],time.monotonic()+888)
    assert checkpoint.stage_seconds==704
    monkeypatch.setenv('DAYAN_WALL_SECONDS','240')
    assert authoring_wall_seconds()==240
    assert DesignCheckpoint({},tmp_path/'old.json',[],time.monotonic()+228).stage_seconds==176
    monkeypatch.setenv('DAYAN_AUTHORING_WALL_SECONDS','1200')
    assert authoring_wall_seconds()==1200 and limits().wall_seconds==240
    manager=object.__new__(TaskManager);manager.cap=Limits();manager.explicit_cap=False
    assert manager._wall_budget('api_platform_tool',{'tool_name':'design_model'})==1200
    assert manager._wall_budget('api_platform_tool',{'tool_name':'run'})==240
    manager.explicit_cap=True;manager.cap=Limits(wall_seconds=4)
    assert manager._wall_budget('api_platform_tool',{'tool_name':'design_model'})==4
    monkeypatch.setenv('DAYAN_AUTHORING_WALL_SECONDS','3601')
    with pytest.raises(ValueError,match='3600'):authoring_wall_seconds()


def test_watchdog_uses_recorded_authoring_budget_and_still_stops_its_actual_child(monkeypatch,tmp_path):
    import dayan.task_manager as module
    actual_time=time;clock={'now':400.}
    monkeypatch.setattr(module,'time',SimpleNamespace(monotonic=lambda:clock['now'],time=actual_time.time))
    process=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    manager=object.__new__(TaskManager)
    manager.cap=Limits();manager.lock=threading.RLock();manager.queue=deque();manager.owner=None
    manager._disk=lambda:0;manager._path=lambda key:tmp_path
    row={'job_id':'owned-budget-child','target':'api_platform_tool','status':'running',
         'stages':[],'result':None,'limits':{**vars(manager.cap),'wall_seconds':900}}
    manager.active={'owned-budget-child':{'process':process,'started':0.,'row':row}}
    try:
        manager._tick()
        assert process.poll() is None and 'owned-budget-child' in manager.active
        clock['now']=901.
        manager._tick()
        assert process.poll() is not None and not manager.active
        saved=json.loads((tmp_path/'status.json').read_text(encoding='utf-8'))
        assert saved['terminal_reason']=='wall_timeout' and saved['status']=='error'
    finally:
        if process.poll() is None:module._kill(process)
