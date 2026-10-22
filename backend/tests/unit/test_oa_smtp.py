"""Loopback SMTP protocol capture; never contacts a real mail service."""
from contextlib import contextmanager
from email import policy
from email.parser import BytesParser
import socketserver
import threading
from types import SimpleNamespace
import pytest


@contextmanager
def capture_smtp(*,recipient_code=250,data_code=250,disconnect=False):
    messages=[]
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.connection.settimeout(5)
            self.wfile.write(b'220 local capture\r\n')
            while line:=self.rfile.readline():
                verb=line.split(b' ',1)[0].strip().upper()
                if verb in {b'EHLO',b'HELO',b'MAIL',b'RSET'}:
                    self.wfile.write(b'250 local\r\n')
                elif verb==b'RCPT':
                    self.wfile.write(str(recipient_code).encode()+b' local\r\n')
                elif verb==b'DATA':
                    self.wfile.write(b'354 data\r\n')
                    lines=[]
                    while (part:=self.rfile.readline()) not in {b'.\r\n',b''}: lines.append(part)
                    messages.append(b''.join(lines))
                    if disconnect: return
                    self.wfile.write(str(data_code).encode()+b' local\r\n')
                elif verb==b'QUIT':
                    self.wfile.write(b'221 bye\r\n')
                    return
                else: self.wfile.write(b'500 unsupported\r\n')
    with socketserver.ThreadingTCPServer(('127.0.0.1',0),Handler) as server:
        server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try: yield server.server_address[1],messages
        finally:
            server.shutdown()
            thread.join(timeout=5)


def settings(port):
    return SimpleNamespace(smtp_enabled=True,smtp_host='127.0.0.1',smtp_port=port,smtp_from='oa@example.test',
        smtp_starttls=False,smtp_username='',smtp_password='',smtp_timeout_seconds=2)


@pytest.mark.parametrize('recipient_code,data_code,disconnect,outcome',[
    (250,250,False,'ACCEPTED'),(450,250,False,'TEMPORARY'),(550,250,False,'PERMANENT'),
    (250,450,False,'TEMPORARY'),(250,550,False,'PERMANENT'),(250,250,True,'UNKNOWN')])
def test_local_smtp_acceptance_and_failure_boundary(monkeypatch,recipient_code,data_code,disconnect,outcome):
    from app.providers import smtp
    with capture_smtp(recipient_code=recipient_code,data_code=data_code,disconnect=disconnect) as (port,messages):
        monkeypatch.setattr(smtp,'get_settings',lambda:settings(port))
        assert smtp.send(dict(recipient='recipient@example.test',message_id='<stable@notification.invalid>',
            body='您有新的 OA 业务提醒，请登录系统查看。'))==outcome
        if messages:
            parsed=BytesParser(policy=policy.default).parsebytes(messages[0])
            assert parsed['Message-ID']=='<stable@notification.invalid>'
            assert parsed['To']=='recipient@example.test'
            assert '请登录系统查看' in parsed.get_content()


def test_disabled_smtp_never_opens_connection(monkeypatch):
    from app.providers import smtp
    monkeypatch.setattr(smtp,'get_settings',lambda:SimpleNamespace(smtp_enabled=False))
    assert smtp.send({})=='PERMANENT'
