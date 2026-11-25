"""Real queued native tool execution, with the original question preserved."""
import json
import time
import pytest

from api_client import local_client
from dayan.server import app
from dayan.task_manager import close_managers


@pytest.mark.parametrize('native',[True,False])
def test_native_tools_return_a_durable_job_before_the_actual_model_result(monkeypatch,tmp_path,native):
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    question='用NET052运行3步，随机种子7。'
    body={'async_job':True,'origin':'dsh' if native else 'rest','session_id':'actual-async-owner','original_text':question,
          'arguments':{'model_id':'NET052','ticks':3,'seed':7}}
    try:
        with local_client(app) as client:
            response=client.post('/api/tools/run',json=body)
            assert response.status_code==200,response.text
            submitted=response.json();assert set(submitted)=={'job_id'}
            jid=submitted['job_id'];deadline=time.monotonic()+20
            while True:
                state=client.get('/api/jobs/'+jid).json()
                if state['status'] not in ('running','queued'):break
                assert time.monotonic()<deadline,state
                time.sleep(.03)
            assert state['status']=='done',state
            result=state['result'];assert result['ok'],result
            assert len(result['payload']['observations'])==4
            assert result['payload']['run_id']
            if native:assert result['integration_event']['session_id']==body['session_id']
            else:assert 'integration_event' not in result
            request=json.loads((tmp_path/'tasks'/jid/'request.json').read_text(encoding='utf-8'))
            assert request['arguments']['body']['original_text']==question
            assert request['arguments']['body']['arguments']==body['arguments']
            assert 'async_job' not in request['arguments']['body']
            assert request['preview'] is native
    finally:close_managers()
