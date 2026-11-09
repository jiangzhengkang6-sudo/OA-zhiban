"""Opt-in self-addressed mailbox roundtrip; never analyze existing personal mail."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from app.core.config import get_settings
from app.db.session import async_session_factory, engine
from app.models.public_mail import PublicMailMessage
from app.schemas.public_mail import MailAction, MailDraft
from app.services import public_mail_service as mail
from scripts.import_public_company_knowledge import actor_for_import


async def main(options):
    receipt = dict(smtp_accepted=False, imap_connected=False, roundtrip=False, duplicate_added=None)
    try:
        async with async_session_factory() as db:
            actor = await actor_for_import(db, 'oa_admin')
            status = await mail.status(db, actor)
            if not status['provisioned']:
                status = await mail.setup(db, actor)
                await db.commit()
            assert status['authorized'], 'Mailbox manager authorization required'
            receipt['address'] = status['address']
            marker = 'OA公共邮箱自测-' + uuid4().hex[:12]
            if options.send_self:
                saved = await mail.save_draft(db, actor, MailDraft(subject=marker,
                    recipients=[status['address']], body='这是一封综合办公公共邮箱验收邮件，无需回复。\n待办：整理项目验收报告，截止时间由经办人核实。',
                    idempotency_key=marker))
                await db.commit()
                sent = await mail.action(db, actor, saved['id'], MailAction(action='send',
                    expected_version=saved['version'], confirmed=True))
                await db.commit()
                receipt['smtp_status'] = sent['status']
                receipt['smtp_accepted'] = sent['status'] == 'ACCEPTED'
            for attempt in range(12 if options.send_self else 1):
                result = await mail.sync(db, actor)
                await db.commit()
                receipt['imap_connected'] = True
                row = await db.scalar(select(PublicMailMessage).where(PublicMailMessage.mailbox_id == status['id'],
                    PublicMailMessage.direction == 'incoming', PublicMailMessage.subject == marker))
                if row:
                    assert '综合办公公共邮箱验收邮件' in row.body
                    receipt['roundtrip'] = True
                    receipt['test_message_id'] = row.id
                    result = await mail.sync(db, actor)
                    await db.commit()
                    receipt['duplicate_added'] = result['added']
                    if options.analyze:
                        analysis = await mail.import_analysis(db, actor, row.id)
                        await db.commit()
                        from app.services import email_service
                        detail = await email_service.get_email(db, actor, analysis['email_id'])
                        receipt['analysis_status'] = detail.status
                        receipt['analysis_id'] = analysis['email_id']
                    break
                if not options.send_self:
                    break
                if not result['has_more']:
                    await asyncio.sleep(5)
            receipt['passed'] = receipt['imap_connected'] and (not options.send_self or
                receipt['smtp_accepted'] and receipt['roundtrip'])
            print(json.dumps(receipt, ensure_ascii=False))
            return 0 if receipt['passed'] else 1
    finally:
        await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--send-self', action='store_true', help='Send one labeled test mail to the configured mailbox itself')
    parser.add_argument('--analyze', action='store_true', help='Analyze only this newly generated synthetic test message')
    sys.exit(asyncio.run(main(parser.parse_args())))
