"""Loopback workbench authentication, origin checks, and bounded request bodies.

The local page bootstraps an HttpOnly SameSite cookie. Native DSH reads the same
private capability file and sends a Bearer header. No secret is put in a URL/HTML.
The DSH desktop frame uses a separate partitioned cookie.
"""
from __future__ import annotations
import hmac
import ipaddress
import os
import secrets
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from starlette.responses import JSONResponse
from .limits import limits

ROOT=Path(__file__).resolve().parents[1]
COOKIE='dayan_session'
DESKTOP_COOKIE='__Host-dayan_dsh_session'
DESKTOP_ORIGIN='dsh-app://app'
TOKEN_FILE='.workbench-token'


def data_root():
    return Path(os.environ.get('DAYAN_DATA_DIR',ROOT/'data')).resolve()


def access_token():
    configured=os.environ.get('DAYAN_ACCESS_TOKEN','')
    if configured:
        if len(configured)<32:raise ValueError('DAYAN_ACCESS_TOKEN至少32字符')
        return configured
    base=data_root();base.mkdir(parents=True,exist_ok=True);path=base/TOKEN_FILE
    if path.is_symlink():raise ValueError('访问令牌文件不能是软链接')
    try:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:
        for _ in range(25):
            token=path.read_text(encoding='utf-8').strip()
            if len(token)>=32:return token
            time.sleep(.01)
        raise ValueError('访问令牌文件为空或损坏；没有自动替换身份')
    with os.fdopen(fd,'w',encoding='utf-8') as stream:
        token=secrets.token_urlsafe(32);stream.write(token+'\n')
    return token


def _loopback(value):
    if value=='localhost':return True
    try:return ipaddress.ip_address(value).is_loopback
    except ValueError:return False


def _desktop_frame_entry(query_string, headers):
    if headers.get('sec-fetch-mode') != 'navigate' or headers.get('sec-fetch-dest') != 'iframe':
        return False
    try:
        query = parse_qs(query_string.decode('latin-1'), keep_blank_values=True, max_num_fields=16)
    except ValueError:
        return False
    sessions = query.get('dsh_session', [])
    return (query.get('embed') == ['dsh'] and query.get('parent_origin') == [DESKTOP_ORIGIN]
            and len(sessions) == 1 and bool(sessions[0]))


def _desktop_capability(token):
    return hmac.digest(token.encode(), b'dayan:dsh-desktop-session:v1', 'sha256').hex()


class WorkbenchAccess:
    def __init__(self,app):
        self.app=app;self.active=0

    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        headers={k.decode().lower():v.decode('latin-1') for k,v in scope['headers']}
        method=scope['method'];path=scope['path'];host=headers.get('host','')
        async def reject(status,message):
            return await JSONResponse({'detail':message},status_code=status,headers={'Cache-Control':'no-store'})(scope,receive,send)
        try:
            address=urlsplit(scope.get('scheme','http')+'://'+host)
            hostname=address.hostname;address.port
        except ValueError:return await reject(400,'Host格式错误')
        extra=set(filter(None,os.environ.get('DAYAN_ALLOWED_HOSTS','').split(',')))
        if address.username or address.password or not hostname or not (_loopback(hostname) or hostname in extra):
            return await reject(403,'Host不在允许列表，拒绝DNS重绑定/非授权主机')
        own=scope.get('scheme','http')+'://'+host
        origin=headers.get('origin')
        allowed={own}|set(filter(None,os.environ.get('DAYAN_ALLOWED_ORIGINS','').split(',')))
        if origin and origin not in allowed:return await reject(403,'Origin不在明确允许列表')
        loopback_entry = (path == '/' and method == 'GET' and _loopback(hostname)
                          and _loopback((scope.get('client') or [''])[0]))
        desktop_frame = False
        if headers.get('sec-fetch-site')=='cross-site' and not origin:
            desktop_frame = loopback_entry and _desktop_frame_entry(scope['query_string'], headers)
            if not desktop_frame:
                return await reject(403,'拒绝跨站本地工作台访问')
        if method=='OPTIONS':
            response=JSONResponse({},status_code=200,headers={
                'Access-Control-Allow-Origin':origin or own,'Access-Control-Allow-Credentials':'true',
                'Access-Control-Allow-Methods':'GET, POST, PATCH, DELETE, OPTIONS',
                'Access-Control-Allow-Headers':'Content-Type, Authorization','Vary':'Origin'})
            return await response(scope,receive,send)
        protected=(path.startswith('/api/') and path!='/api/health') or path.startswith('/reports/')
        if protected:
            cookies = dict(item.strip().split('=', 1) for item in headers.get('cookie', '').split(';') if '=' in item)
            auth = headers.get('authorization', '')
            bearer = auth.startswith('Bearer ')
            candidate = auth[7:] if bearer else cookies.get(COOKIE, '')
            desktop_cookie = cookies.get(DESKTOP_COOKIE) if not bearer and headers.get('sec-fetch-site') == 'same-origin' else None
            authenticated = False
            if candidate or desktop_cookie:
                token = access_token()
                authenticated = hmac.compare_digest(candidate.encode(), token.encode())
                if not authenticated and desktop_cookie:
                    authenticated = hmac.compare_digest(desktop_cookie.encode(), _desktop_capability(token).encode())
            if not authenticated:
                return await reject(401,'需要工作台会话或DSH本机访问令牌')
        if protected and self.active>=16:return await reject(429,'并发请求预算已满，请稍后重试')
        body=b''
        if method in ('POST','PUT','PATCH','DELETE'):
            cap=limits().body_bytes
            try:declared=int(headers.get('content-length','0'))
            except ValueError:return await reject(400,'Content-Length非法')
            if declared<0 or declared>cap:return await reject(413,'请求体超过大小预算')
            while True:
                message=await receive()
                if message['type']=='http.disconnect':return
                body+=message.get('body',b'')
                if len(body)>cap:return await reject(413,'请求体超过大小预算')
                if not message.get('more_body'):break
        sent=False
        async def replay():
            nonlocal sent
            if method in ('POST','PUT','PATCH','DELETE') and not sent:
                sent=True;return {'type':'http.request','body':body,'more_body':False}
            return await receive()
        async def guarded_send(message):
            if message['type']=='http.response.start':
                extra_headers=[(b'x-content-type-options',b'nosniff'),(b'referrer-policy',b'no-referrer')]
                response_headers = message.get('headers', [])
                if protected:extra_headers.append((b'cache-control',b'no-store'))
                if desktop_frame:
                    # Browser-enforced ancestor check. The query string is not proof of origin.
                    extra_headers.append((b'content-security-policy', f'frame-ancestors {DESKTOP_ORIGIN}'.encode()))
                    if message['status'] == 200:
                        response_headers = [(key, value) for key, value in response_headers if key.lower() != b'cache-control']
                        extra_headers.append((b'cache-control', b'no-store'))
                        cookie = f'{DESKTOP_COOKIE}={_desktop_capability(access_token())}; Path=/; HttpOnly; SameSite=None; Secure; Partitioned'
                        extra_headers.append((b'set-cookie', cookie.encode()))
                elif loopback_entry:
                    extra_headers.append((b'set-cookie',(COOKIE+'='+access_token()+'; Path=/; HttpOnly; SameSite=Strict').encode()))
                if origin:extra_headers.extend([(b'access-control-allow-origin',origin.encode()),(b'access-control-allow-credentials',b'true'),(b'vary',b'Origin')])
                message={**message,'headers':response_headers+extra_headers}
            await send(message)
        if protected:self.active+=1
        try:return await self.app(scope,replay,guarded_send)
        finally:
            if protected:self.active-=1
