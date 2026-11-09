"""Read-only bounded IMAP and explicit TLS SMTP. Never log source or credentials."""
from datetime import timezone
from email import policy
from email.parser import BytesParser
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser
import imaplib
import re
import smtplib
import ssl

MAX_MESSAGE_BYTES = 512 * 1024
SYNC_LIMIT = 25


def clean_text(value):
    # PostgreSQL text/JSON reject NUL, including characters decoded from HTML entities.
    return str(value).replace('\x00', '')


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.blocked = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.blocked += 1
        if tag in {'br', 'p', 'div', 'li', 'tr'} and not self.blocked:
            self.text.append('\n')

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.blocked = max(0, self.blocked - 1)

    def handle_data(self, data):
        if not self.blocked:
            self.text.append(data)


def parse_message(raw):
    message = BytesParser(policy=policy.default).parsebytes(raw)
    attachments = []
    for part in message.walk():
        if part.get_filename() or part.get_content_disposition() == 'attachment':
            attachments.append({'name': clean_text(part.get_filename() or '未命名附件')[:255], 'sensitive': False})
    part = message.get_body(preferencelist=('plain', 'html')) if message.is_multipart() else message
    body = ''
    if part and part.get_content_type() in {'text/plain', 'text/html'}:
        try:
            body = part.get_content()
        except (LookupError, UnicodeError):
            body = (part.get_payload(decode=True) or b'').decode('utf-8', errors='replace')
        if part.get_content_type() == 'text/html':
            parser = PlainHTML()
            parser.feed(body)
            body = ''.join(parser.text)
    try:
        sent_at = parsedate_to_datetime(str(message['Date'])) if message['Date'] else None
        if sent_at and not sent_at.tzinfo:
            sent_at = sent_at.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError, OverflowError):
        sent_at = None
    addresses = lambda key: [clean_text(a)[:320] for _, a in getaddresses([str(message.get(key, ''))]) if a][:30]
    return dict(subject=clean_text(message.get('Subject', '无主题'))[:255] or '无主题',
        sender=(addresses('From') or ['未知发件人'])[0], recipients=addresses('To'),
        body=clean_text(body).strip()[:30000] or '（无可读取的文本正文）', attachments=attachments[:20],
        message_id=clean_text(message.get('Message-ID', ''))[:998], sent_at=sent_at)


def receive(settings, validity, last_uid):
    client = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port,
        ssl_context=ssl.create_default_context(), timeout=settings.imap_timeout_seconds)
    try:
        client.login(settings.imap_username or settings.smtp_username,
            settings.imap_password.get_secret_value() or settings.smtp_password)
        status, _ = client.select('INBOX', readonly=True)
        if status != 'OK':
            raise ValueError('Mailbox unavailable')
        value = client.response('UIDVALIDITY')[1]
        current = value[0].decode('ascii') if value and value[0] else ''
        if not current.isdigit():
            raise ValueError('Missing UIDVALIDITY')
        cursor = last_uid if current == validity else 0
        status, data = client.uid('search', None, f'UID {cursor + 1}:*')
        if status != 'OK':
            raise ValueError('Search failed')
        uids = sorted({int(uid) for uid in (data[0] or b'').split() if int(uid) > cursor})
        results = []
        for uid in uids[:SYNC_LIMIT]:
            status, metadata = client.uid('fetch', str(uid), '(RFC822.SIZE)')
            match = re.search(rb'RFC822.SIZE\s+(\d+)', b' '.join(v for v in metadata if isinstance(v, bytes)))
            if status != 'OK' or not match:
                raise ValueError('Size fetch failed')
            oversized = int(match[1]) > MAX_MESSAGE_BYTES
            field = '(BODY.PEEK[HEADER])' if oversized else '(BODY.PEEK[])'
            status, parts = client.uid('fetch', str(uid), field)
            if status != 'OK':
                raise ValueError('Message fetch failed')
            raw = b''.join(p[1] for p in parts if isinstance(p, tuple))
            if len(raw) > MAX_MESSAGE_BYTES:
                raise ValueError('Message too large')
            parsed = parse_message(raw)
            if oversized:
                parsed['body'] = '（邮件超过安全同步大小限制，请在原邮箱查看正文及附件）'
            results.append(dict(remote_key=f'{current}:{uid}', **parsed))
            cursor = uid
        return dict(validity=current, last_uid=cursor, messages=results, has_more=len(uids) > SYNC_LIMIT)
    finally:
        try:
            client.logout()
        except (OSError, imaplib.IMAP4.error):
            pass


def smtp_client(settings):
    if settings.smtp_port == 465:
        client = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port,
            timeout=settings.smtp_timeout_seconds, context=ssl.create_default_context())
    else:
        if not settings.smtp_starttls:
            raise ValueError('TLS required')
        client = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds)
        try:
            client.ehlo()
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
        except Exception:
            client.close()
            raise
    try:
        client.login(settings.smtp_username, settings.smtp_password)
    except Exception:
        client.close()
        raise
    return client


def send_message(settings, payload):
    client, data_started = None, False
    try:
        message = EmailMessage()
        message['From'], message['To'] = settings.smtp_from, ', '.join(payload['recipients'])
        message['Subject'], message['Message-ID'] = payload['subject'], payload['message_id']
        if payload.get('in_reply_to'):
            message['In-Reply-To'] = payload['in_reply_to']
            message['References'] = payload['in_reply_to']
        message.set_content(payload['body'])
        client = smtp_client(settings)
        if client.mail(settings.smtp_from)[0] != 250:
            return 'FAILED'
        # All recipients must be accepted before DATA; no partial send/retry ambiguity.
        for recipient in payload['recipients']:
            if client.rcpt(recipient)[0] not in {250, 251}:
                client.rset()
                return 'FAILED'
        data_started = True
        return 'ACCEPTED' if client.data(message.as_bytes(policy=policy.SMTP))[0] == 250 else 'FAILED'
    except smtplib.SMTPResponseException:
        return 'FAILED'
    except Exception:
        return 'UNKNOWN' if data_started else 'FAILED'
    finally:
        if client:
            try:
                client.close()
            except OSError:
                pass
