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
from dayan.access import COOKIE, DESKTOP_COOKIE, DESKTOP_ORIGIN, WorkbenchAccess, access_token
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

    def test_desktop_frame_bootstraps_only_its_partition(self):
        client = TestClient(self.app, base_url='http://127.0.0.1', client=('127.0.0.1', 50000))
        query = {'embed': 'dsh', 'parent_origin': DESKTOP_ORIGIN, 'dsh_session': 'reserved-session'}
        headers = {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'iframe'}
        response = client.get('/', params=query, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['content-security-policy'], f'frame-ancestors {DESKTOP_ORIGIN}')
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertNotIn('access-control-allow-origin', response.headers)
        cookie = response.headers['set-cookie']
        self.assertTrue(cookie.startswith(f'{DESKTOP_COOKIE}='))
        self.assertTrue({'HttpOnly', 'Secure', 'Partitioned', 'SameSite=None'}.issubset(cookie.split('; ')))
        self.assertNotIn(access_token(), cookie)
        self.assertIsNone(client.cookies.get(COOKIE))

        frame_cookie = {'Cookie': cookie.split(';', 1)[0]}
        same_origin = {**frame_cookie, 'Sec-Fetch-Site': 'same-origin'}
        self.assertEqual(client.get('/api/private', headers=same_origin).status_code, 200)
        self.assertEqual(client.get('/api/private', headers=frame_cookie).status_code, 401)
        self.assertEqual(client.get('/api/private', headers={**same_origin, 'Authorization': 'Bearer invalid'}).status_code, 401)
        self.assertEqual(client.post('/api/costly', headers={**frame_cookie, 'Sec-Fetch-Site': 'cross-site'}).status_code, 403)

    def test_desktop_navigation_exception_does_not_apply_elsewhere(self):
        client = TestClient(self.app, base_url='http://127.0.0.1', client=('127.0.0.1', 50000))
        query = [('embed', 'dsh'), ('parent_origin', DESKTOP_ORIGIN), ('dsh_session', 'reserved-session')]
        headers = {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'iframe'}
        probes = [
            ('/', query, {**headers, 'Sec-Fetch-Dest': 'document'}),
            ('/', query, {**headers, 'Sec-Fetch-Mode': 'cors'}),
            ('/', query, {**headers, 'Origin': 'https://other.example'}),
            ('/', query, {**headers, 'Host': 'bad.example'}),
            ('/', query[:-1], headers),
            ('/', query + [('parent_origin', 'dsh-app://other')], headers),
            ('/api/private', query, headers),
        ]
        for path, params, request_headers in probes:
            with self.subTest(path=path, params=params, headers=request_headers):
                response = client.get(path, params=params, headers=request_headers)
                self.assertEqual(response.status_code, 403)
                self.assertNotIn('set-cookie', response.headers)
        remote = TestClient(self.app, base_url='http://127.0.0.1', client=('192.0.2.10', 50000))
        self.assertEqual(remote.get('/', params=query, headers=headers).status_code, 403)


if __name__=='__main__':unittest.main(verbosity=2)
