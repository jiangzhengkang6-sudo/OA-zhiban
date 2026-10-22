"""No external IO: capture the HTTPS transport and verify secret-safe outcomes."""
import json
import pytest
from pydantic import SecretStr
from app.core.config import Settings
from app.providers import wecom


def configured(**overrides):
    return Settings(_env_file=None, wecom_enabled=True,
        wecom_webhook_url=SecretStr('https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=unit-secret'),
        wecom_tenant_id='tenant', wecom_department_id='dept', **overrides)


@pytest.mark.parametrize('url', [
    'http://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x',
    'https://example.test/cgi-bin/webhook/send?key=x',
    'https://qyapi.weixin.qq.com@127.0.0.1/cgi-bin/webhook/send?key=x',
    'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x#bad',
    'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x&key=y',
    'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=',
    'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x&other=y',
    'https://qyapi.weixin.qq.com/cgi-bin/webhook/send/evil?key=x',
])
def test_rejects_untrusted_endpoints(url):
    settings=configured()
    settings.wecom_webhook_url=SecretStr(url)
    assert wecom.endpoint(settings) is None
    assert wecom.destination(settings,'tenant','dept') is None


def test_scope_and_secret_repr():
    settings=configured()
    assert wecom.destination(settings,'other','dept') is None
    assert wecom.destination(settings,'tenant','other') is None
    assert 'unit-secret' not in repr(settings)
    assert len(wecom.destination(settings,'tenant','dept')) == 64


def test_equivalent_url_encodings_share_robot_identity():
    first,second=configured(),configured()
    second.wecom_webhook_url=SecretStr('https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=%75nit-secret')
    assert wecom.endpoint(second)
    assert wecom.destination(first,'tenant','dept')==wecom.destination(second,'tenant','dept')


@pytest.mark.parametrize('status,data,outcome', [
    (200, b'{"errcode":0,"errmsg":"ok"}', 'ACCEPTED'),
    (200, b'{"errcode":-1}', 'TEMPORARY'),
    (200, b'{"errcode":45009}', 'TEMPORARY'),
    (200, b'{"errcode":93000}', 'PERMANENT'),
    (200, b'{"errcode":false}', 'UNKNOWN'),
    (200, b'[]', 'UNKNOWN'), (200, b'not-json', 'UNKNOWN'),
    (200, b'x'*8193, 'UNKNOWN'), (429, b'', 'TEMPORARY'),
    (503, b'', 'UNKNOWN'), (302, b'', 'PERMANENT'), (403, b'', 'PERMANENT'),
])
def test_response_mapping(monkeypatch,caplog,status,data,outcome):
    settings=configured()
    monkeypatch.setattr(wecom,'get_settings',lambda:settings)
    requests=[]
    class Connection:
        def __init__(self,host,timeout): assert host=='qyapi.weixin.qq.com'
        def connect(self): pass
        def request(self,method,path,body,headers): requests.append((method,path,json.loads(body)))
        def getresponse(self): return type('Response',(),{'status':status,'read':lambda self,n:data})()
        def close(self): pass
    monkeypatch.setattr(wecom.http.client,'HTTPSConnection',Connection)
    claim=dict(tenant_id='tenant',department_id='dept',destination_hash=wecom.destination(settings,'tenant','dept'),body='通用提醒')
    assert wecom.send(claim)==outcome
    assert requests[0][2]=={'msgtype':'text','text':{'content':'通用提醒'}}
    assert 'unit-secret' not in caplog.text
    claim['destination_hash']='changed'
    assert wecom.send(claim)=='PERMANENT'
    assert len(requests)==1


@pytest.mark.parametrize('stage,outcome',[('connect','TEMPORARY'),('request','UNKNOWN'),('getresponse','UNKNOWN')])
def test_timeout_distinguishes_possible_acceptance(monkeypatch,stage,outcome):
    settings=configured()
    monkeypatch.setattr(wecom,'get_settings',lambda:settings)
    class Connection:
        def __init__(self,*args,**kwargs): pass
        def connect(self):
            if stage=='connect': raise TimeoutError('private URL must not escape')
        def request(self,*args):
            if stage=='request': raise TimeoutError('private URL must not escape')
        def getresponse(self): raise TimeoutError('private URL must not escape')
        def close(self): pass
    monkeypatch.setattr(wecom.http.client,'HTTPSConnection',Connection)
    assert wecom.send(dict(tenant_id='tenant',department_id='dept',destination_hash=wecom.destination(settings,'tenant','dept'),body='提醒'))==outcome
