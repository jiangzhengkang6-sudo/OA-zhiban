from email.message import EmailMessage
from app.providers.public_mail import parse_message, send_message


def test_imap_is_readonly_resets_validity_and_uses_header_for_large_mail(monkeypatch):
    from app.providers import public_mail
    from app.core.config import Settings
    from unittest.mock import Mock
    client = Mock()
    client.select.return_value = ('OK', [b'2'])
    client.response.return_value = ('UIDVALIDITY', [b'2'])
    raw = b'From: client@example.com\r\nTo: office@example.com\r\nSubject: Test\r\n\r\n'
    def uid(command, *args):
        if command == 'search':
            return 'OK', [b'1 2']
        if args[1] == '(RFC822.SIZE)':
            return 'OK', [b'1 (RFC822.SIZE 900000)']
        assert args[1] == '(BODY.PEEK[HEADER])'
        return 'OK', [(b'header', raw), b')']
    client.uid.side_effect = uid
    monkeypatch.setattr(public_mail.imaplib, 'IMAP4_SSL', lambda *a, **kw: client)
    result = public_mail.receive(Settings(_env_file=None, smtp_username='office@example.com', smtp_password='test'), '1', 90)
    assert result['last_uid'] == 2 and result['messages'][0]['remote_key'] == '2:1'
    assert '安全同步大小限制' in result['messages'][0]['body']
    client.select.assert_called_once_with('INBOX', readonly=True)
    assert client.uid.call_args_list[0].args == ('search', None, 'UID 1:*')
    client.logout.assert_called_once()


def test_imap_star_search_does_not_reimport_older_uid(monkeypatch):
    from app.providers import public_mail
    from app.core.config import Settings
    from unittest.mock import Mock
    client = Mock()
    client.select.return_value = ('OK', [b'1'])
    client.response.return_value = ('UIDVALIDITY', [b'1'])
    client.uid.return_value = ('OK', [b'4'])
    monkeypatch.setattr(public_mail.imaplib, 'IMAP4_SSL', lambda *a, **kw: client)
    result = public_mail.receive(Settings(_env_file=None), '1', 4)
    assert result['messages'] == [] and result['last_uid'] == 4
    assert client.uid.call_count == 1


def test_mime_is_plain_text_and_attachments_remain_metadata():
    message = EmailMessage()
    message['Subject'] = '项目材料'
    message['From'] = 'Client <client@example.com>'
    message['To'] = 'office@example.com'
    message.set_content('<p>周五前提交</p><script>bad()</script>', subtype='html')
    message.add_attachment(b'private', maintype='application', subtype='pdf', filename='合同.pdf')
    result = parse_message(message.as_bytes())
    assert result['sender'] == 'client@example.com'
    assert '周五前提交' in result['body']
    assert '<script>' not in result['body'] and 'bad()' not in result['body']
    assert result['attachments'] == [{'name': '合同.pdf', 'sensitive': False}]
    assert 'private' not in str(result)


def test_partial_recipient_refusal_never_sends_data(monkeypatch):
    from app.providers import public_mail
    from types import SimpleNamespace
    from unittest.mock import Mock
    client = Mock()
    client.mail.return_value = (250, b'ok')
    client.rcpt.side_effect = [(250, b'ok'), (550, b'no')]
    monkeypatch.setattr(public_mail, 'smtp_client', lambda settings: client)
    assert send_message(SimpleNamespace(smtp_from='office@example.com'), {
        'recipients': ['a@example.com', 'b@example.com'], 'subject': 'test', 'body': 'text',
        'message_id': '<stable@example.com>', 'in_reply_to': None,
    }) == 'FAILED'
    client.data.assert_not_called()


def test_malformed_nul_in_mime_does_not_poison_database_sync():
    import json
    raw = (b'Subject: Bad\x00subject\r\nFrom: client@example.com\r\n'
           b'To: office@example.com\r\nMessage-ID: <id\x00@example.com>\r\n'
           b'Content-Type: text/plain; charset=utf-8\r\n\r\nBody\x00text')
    result = parse_message(raw)
    assert result['subject'] == 'Badsubject'
    assert result['body'] == 'Bodytext'
    assert '\\u0000' not in json.dumps(result)


def test_disconnect_during_data_is_unknown(monkeypatch):
    from app.providers import public_mail
    from types import SimpleNamespace
    from unittest.mock import Mock
    client = Mock()
    client.mail.return_value = client.rcpt.return_value = (250, b'ok')
    client.data.side_effect = OSError('disconnected')
    monkeypatch.setattr(public_mail, 'smtp_client', lambda settings: client)
    assert send_message(SimpleNamespace(smtp_from='office@example.com'), {
        'recipients': ['a@example.com'], 'subject': 'test', 'body': 'text',
        'message_id': '<stable@example.com>', 'in_reply_to': None,
    }) == 'UNKNOWN'
