"""Real middleware requests verify access and limits, without a bypass flag."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi import FastAPI,Request
from fastapi.testclient import TestClient
from dayan.access import WorkbenchAccess,access_token
from api_client import local_client


class APISecurity(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'DAYAN_DATA_DIR':self.temp.name});self.env.start()
        self.app=FastAPI();self.app.add_middleware(WorkbenchAccess)
        @self.app.get('/')
        async def index():return {'page':'local'}
        @self.app.get('/api/private')
        async def private():return {'private':'research'}
        @self.app.post('/api/costly')
        async def costly(request:Request):return {'bytes':len(await request.body())}
    def tearDown(self):self.env.stop();self.temp.cleanup()
    def test_unauthenticated_data_and_writes_are_denied(self):
        client=TestClient(self.app,base_url='http://127.0.0.1',client=('127.0.0.1',50000))
        self.assertEqual(client.get('/api/private').status_code,401)
        self.assertEqual(client.post('/api/costly',json={}).status_code,401)
        client.get('/')
        self.assertEqual(client.get('/api/private').status_code,200)
        cookie=client.get('/').headers['set-cookie']
        self.assertIn('HttpOnly',cookie);self.assertIn('SameSite=Strict',cookie)
    def test_host_origin_and_cross_site_protection(self):
        client=local_client(self.app)
        self.assertEqual(client.get('/api/private',headers={'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(client.get('/api/private',headers={'Host':'evil.example'}).status_code,403)
        self.assertEqual(client.get('/api/private',headers={'Origin':'null'}).status_code,403)
        self.assertEqual(client.get('/api/private',headers={'Sec-Fetch-Site':'cross-site'}).status_code,403)
        preflight=client.options('/api/costly',headers={'Origin':'https://evil.example','Access-Control-Request-Method':'POST'})
        self.assertEqual(preflight.status_code,403)
        self.assertNotEqual(preflight.headers.get('Access-Control-Allow-Origin'),'*')
    def test_dsh_bearer_and_body_limit(self):
        client=TestClient(self.app,base_url='http://127.0.0.1',client=('127.0.0.1',50000))
        headers={'Authorization':'Bearer '+access_token()}
        self.assertEqual(client.get('/api/private',headers=headers).status_code,200)
        with patch.dict(os.environ,{'DAYAN_BODY_BYTES':'1024'}):
            self.assertEqual(client.post('/api/costly',content=b'x'*1025,headers=headers).status_code,413)
            self.assertEqual(client.post('/api/costly',content=b'valid',headers=headers).json()['bytes'],5)


if __name__=='__main__':unittest.main(verbosity=2)
