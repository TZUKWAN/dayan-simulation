"""Actual browser-equivalent local session bootstrap for API integration tests."""
from fastapi.testclient import TestClient


def local_client(app, **kwargs):
    kwargs.setdefault('base_url','http://127.0.0.1')
    kwargs.setdefault('client',('127.0.0.1',50000))
    client=TestClient(app,**kwargs)
    response=client.get('/')
    if response.status_code!=200 or 'dayan_session' not in client.cookies:
        raise AssertionError('Local workbench session bootstrap failed')
    return client
