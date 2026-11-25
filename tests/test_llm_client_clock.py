"""Actual local HTTP transport; controlled response, not a cloud/model claim."""
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import threading

from dayan import llm_client
from dayan.llm_limits import allocation


def test_runtime_clock_reaches_request_budget_and_audit_without_changing_simulation_messages(tmp_path,monkeypatch):
    received=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            body={'data':[{'id':'controlled-clock-transport','context_window':1000000,'max_output_tokens':393216}]}
            self.send_response(200);self.end_headers();self.wfile.write(json.dumps(body).encode())
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            body={'id':'controlled-clock-response','choices':[{'message':{'content':'{}'},'finish_reason':'stop'}]}
            self.send_response(200);self.end_headers();self.wfile.write(json.dumps(body).encode())
    service=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=service.serve_forever,daemon=True);thread.start()
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    monkeypatch.setattr(llm_client,'configuration',lambda:{'api_key':'controlled-fixture-key',
        'base_url':f'http://127.0.0.1:{service.server_port}','model_id':'controlled-clock-transport'})
    try:
        for messages in ([{'role':'system','content':'情境时期1900年，模型t=0是1900年初。只返回JSON。'},
                          {'role':'user','content':'模拟1900—1905年，保持原文。'}],
                         [{'role':'user','content':'模型时间从0推进到10年。'}]):
            original=deepcopy(messages);audit=[];before=datetime.now(timezone.utc)
            assert llm_client.complete(messages,audit=audit)=='{}'
            after=datetime.now(timezone.utc);payload=received[-1];record=audit[0]
            assert messages==original
            now=datetime.fromisoformat(record['runtime_clock_utc'])
            assert before.replace(microsecond=0)<=now<=after
            assert payload['messages'][0]['role']=='system'
            assert record['runtime_clock_utc'] in payload['messages'][0]['content']
            assert '不是仿真时间' in payload['messages'][0]['content']
            assert payload['messages'][-1]==original[-1]
            if original[0]['role']=='system':assert payload['messages'][0]['content'].startswith(original[0]['content'])
            expected=allocation(payload['messages'],{'context_window':1000000,'max_output_tokens':393216,'source':'fixture'})
            assert record['input_token_upper_bound']==expected['input_token_upper_bound']
            assert payload['max_tokens']==393216
            assert record['request_sha256']==hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
            saved=json.loads((tmp_path/'llm_calls'/(record['call_id']+'.json')).read_text(encoding='utf-8'))
            assert saved['runtime_clock_utc']==record['runtime_clock_utc'] and saved['ok'] is True
    finally:
        service.shutdown();thread.join(2);service.server_close()
