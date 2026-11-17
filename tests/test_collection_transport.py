"""Transport fixtures verify SSRF boundaries; no fake live source success."""
import socket
import sys
from pathlib import Path
import unittest
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dayan.datasets import _public_url,_PinnedHTTPSConnection,_PinnedHTTPSHandler,_Redirect


class CollectionTransport(unittest.TestCase):
    def test_handler_uses_supported_python_https_constructor_arguments(self):
        import urllib.request
        handler=_PinnedHTTPSHandler()
        with patch.object(handler,'do_open',return_value='unit transport') as opened:
            self.assertEqual(handler.https_open(urllib.request.Request('https://unit.example')),'unit transport')
            self.assertNotIn('check_hostname',opened.call_args.kwargs)

    def test_rebinding_is_checked_at_connect_before_any_private_socket(self):
        public=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))]
        private=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))]
        with patch('socket.getaddrinfo',side_effect=[public,private]),patch('socket.create_connection') as connect:
            _public_url('https://unit.example/data')
            with self.assertRaisesRegex(ValueError,'内网'):_PinnedHTTPSConnection('unit.example').connect()
            connect.assert_not_called()

    def test_connection_uses_literal_public_ip_and_original_tls_name(self):
        public=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))]
        sock=MagicMock();sock.getpeername.return_value=('93.184.216.34',443)
        context=MagicMock();connection=_PinnedHTTPSConnection('unit.example',timeout=3,context=context)
        with patch('socket.getaddrinfo',return_value=public),patch('socket.create_connection',return_value=sock) as connect:
            connection.connect()
            self.assertEqual(connect.call_args.args[0],('93.184.216.34',443))
            context.wrap_socket.assert_called_once_with(sock,server_hostname='unit.example')

    def test_redirect_cannot_downgrade_or_target_private_network(self):
        import urllib.request
        req=urllib.request.Request('https://unit.example')
        for url in ('http://example.org','https://127.0.0.1/','https://user:secret@example.org/'):
            with self.subTest(url=url),self.assertRaises(ValueError):
                _Redirect().redirect_request(req,None,302,'fixture',{},url)


if __name__=='__main__':unittest.main(verbosity=2)
