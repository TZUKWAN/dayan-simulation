"""Local transport fixtures test allocation, not scientific/live LLM quality."""
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dayan.llm_limits import allocation, discover
from dayan.llm_client import complete


class LLMLimits(unittest.TestCase):
    def test_local_profile_uses_loaded_context_not_theoretical_maximum(self):
        class MetadataFixture(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                data = {'data': [{'id':'loaded-model'}]} if self.path == '/v1/models' else {
                    'models':[{'key':'loaded-model','max_context_length':1000000,
                               'loaded_instances':[{'id':'loaded-model','config':{'context_length':65536}}]}]}
                self.send_response(200);self.end_headers();self.wfile.write(json.dumps(data).encode())
        service=ThreadingHTTPServer(('127.0.0.1',0),MetadataFixture)
        thread=threading.Thread(target=service.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'DAYAN_DATA_DIR':td}):
                profile=discover({'api_key':'','base_url':'http://127.0.0.1:'+str(service.server_port)+'/v1','model_id':'loaded-model'})
                self.assertEqual(profile['context_window'],65536)
                self.assertEqual(profile['source'],'lmstudio-loaded-context')
                self.assertLess(allocation([{'role':'user','content':'fixture'}],profile)['max_tokens'],65536)
        finally:service.shutdown();thread.join(2);service.server_close()

    def test_actual_request_uses_discovered_capacity_above_old_32768_cap(self):
        requests=[]
        class TransportFixture(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                body=json.dumps({'data':[{'id':'unit-fixture','context_window':1000000,'max_output_tokens':393216}]}).encode()
                self.send_response(200);self.end_headers();self.wfile.write(body)
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                body=json.dumps({'id':'unit-transport','choices':[{'message':{'content':'fixture transport response'},'finish_reason':'stop'}],
                                 'usage':{'prompt_tokens':10,'completion_tokens':4}}).encode()
                self.send_response(200);self.end_headers();self.wfile.write(body)
        service=ThreadingHTTPServer(('127.0.0.1',0),TransportFixture)
        thread=threading.Thread(target=service.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'DAYAN_DATA_DIR':td,'DAYAN_API_KEY':'unit-key',
                'DAYAN_BASE_URL':'http://127.0.0.1:'+str(service.server_port),'DAYAN_MODEL':'unit-fixture'}):
                audit=[]
                result=complete([{'role':'user','content':'transport fixture'}],audit=audit)
                self.assertEqual(result,'fixture transport response')
                self.assertEqual(requests[-1]['max_tokens'],393216)
                self.assertEqual(audit[0]['context_window'],1000000)
                self.assertEqual(audit[0]['usage']['completion_tokens'],4)
                self.assertEqual(audit[0]['limit_source'],'provider-model-metadata')
        finally:service.shutdown();thread.join(2);service.server_close()

    def test_context_room_and_unknown_limits_are_not_fabricated(self):
        profile={'context_window':10000,'max_output_tokens':9000,'source':'unit-fixture'}
        messages=[{'role':'user','content':'x'*3000}]
        budget=allocation(messages,profile)
        self.assertEqual(budget['max_tokens'],10000-budget['input_token_upper_bound'])
        self.assertEqual(messages[0]['content'],'x'*3000)
        unknown=allocation(messages,{'context_window':None,'max_output_tokens':None,'source':'provider-default-unverified'})
        self.assertIsNone(unknown['max_tokens'])
        with self.assertRaisesRegex(ValueError,'未截断'):
            allocation([{'role':'user','content':'x'*10000}],profile)


if __name__=='__main__':unittest.main(verbosity=2)
