"""Static assets retain correct media types and never expose sibling sources."""
import asyncio
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from dayan import server


class StaticDelivery(unittest.TestCase):
    def test_webp_and_windows_traversal(self):
        c=TestClient(server.app,base_url='http://127.0.0.1',client=('127.0.0.1',50000))
        response=c.get('/console/assets/city-simulation.webp')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['content-type'],'image/webp')
        self.assertTrue(response.content.startswith(b'RIFF'))
        for path in ('..%5Cindex.html','..%5C..%5C..%5Cdayan%5Cconfig.json','city-simulation.webp%00'):
            self.assertEqual(c.get('/console/assets/'+path).status_code,404)

    def test_startup_and_html_response_do_not_write_source(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'DAYAN_DATA_DIR':str(Path(td)/'runtime'),'DAYAN_API_KEY':''}):
            root=Path(td);target=root/'site/console/index.html';target.parent.mkdir(parents=True)
            target.write_text('<html><script src="/app.js?v=123"></script></html>',encoding='utf-8')
            original=target.read_bytes()
            target.chmod(0o444)
            try:
                with patch.object(server,'ROOT',root):
                    asyncio.run(server.startup())
                    response=asyncio.run(server.index())
                self.assertEqual(target.read_bytes(),original)
                self.assertNotIn(b'v=123',response.body)
            finally:target.chmod(0o600)


if __name__=='__main__':unittest.main(verbosity=2)
