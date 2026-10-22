"""Conservative SMTP outcomes: ACCEPTED is not a delivery receipt."""
from email.message import EmailMessage
import smtplib
import ssl
from ..core.config import get_settings


def send(claim):
    settings=get_settings()
    if not settings.smtp_enabled or not settings.smtp_host or not settings.smtp_from:
        return 'PERMANENT'
    client=None
    data_started=False
    try:
        client=smtplib.SMTP(settings.smtp_host,settings.smtp_port,timeout=settings.smtp_timeout_seconds)
        client.ehlo_or_helo_if_needed()
        if settings.smtp_starttls:
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
        if settings.smtp_username:
            client.login(settings.smtp_username,settings.smtp_password)
        code,_=client.mail(settings.smtp_from)
        if code!=250: return 'TEMPORARY' if 400<=code<500 else 'PERMANENT'
        code,_=client.rcpt(claim['recipient'])
        if code not in {250,251}: return 'TEMPORARY' if 400<=code<500 else 'PERMANENT'
        message=EmailMessage()
        message['From']=settings.smtp_from
        message['To']=claim['recipient']
        message['Subject']='OA 业务提醒'
        message['Message-ID']=claim['message_id']
        message.set_content(claim['body'])
        data_started=True
        code,_=client.data(message.as_bytes())
        return 'ACCEPTED' if code==250 else 'TEMPORARY' if 400<=code<500 else 'PERMANENT'
    except smtplib.SMTPResponseException as error:
        return 'TEMPORARY' if 400<=error.smtp_code<500 else 'PERMANENT'
    except (OSError,smtplib.SMTPException,ValueError):
        return 'UNKNOWN' if data_started else 'TEMPORARY'
    finally:
        if client:
            try: client.close()
            except OSError: pass
