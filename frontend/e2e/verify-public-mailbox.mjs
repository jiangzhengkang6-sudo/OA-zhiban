// Live UI checks with short-lived audited sessions. Never sends mail or runs AI.
import { execFileSync } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'

const root = fileURLToPath(new URL('../../', import.meta.url))
const backend = path.join(root, 'backend'), output = path.join(root, 'output/business-acceptance-private/public-mailbox')
const program = `
import asyncio,json,sys
from datetime import timedelta
from sqlalchemy import select,update
from app.core.config import get_settings
from app.db.session import async_session_factory,engine
from app.models.identity import OAUser,OAAuthSession
from app.services import identity_service as identity
from scripts.import_public_company_knowledge import actor_for_import
async def main():
    async with async_session_factory() as db:
        admin=await actor_for_import(db,'oa_admin')
        if sys.argv[1]=='revoke':
            await db.execute(update(OAAuthSession).where(OAAuthSession.family_id==sys.argv[2],OAAuthSession.tenant_id==admin.tenant_id).values(revoked_at=identity.utcnow()))
            identity.audit(db,admin.user_id,'identity.acceptance_closed',sys.argv[2])
            await db.commit()
        else:
            user=await db.get(OAUser,admin.user_id) if sys.argv[2]=='admin' else await db.scalar(select(OAUser).where(OAUser.display_name==sys.argv[2],OAUser.tenant_id==admin.tenant_id,OAUser.status=='active'))
            issued=await identity.issue(db,user,get_settings(),expires=identity.utcnow()+timedelta(minutes=20))
            row=await db.scalar(select(OAAuthSession).where(OAAuthSession.refresh_digest==identity.digest(issued.refresh)))
            identity.audit(db,user.id,'identity.acceptance_session',row.family_id)
            await db.commit()
            print(json.dumps(dict(refresh=issued.refresh,family=row.family_id)))
    await engine.dispose()
asyncio.run(main())
`
function session(action, value) {
  try { return execFileSync(path.join(backend, '.venv/Scripts/python.exe'), ['-c', program, action, value],
    { cwd: backend, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim() }
  catch { throw new Error('acceptance_identity_failed') }
}
const sessions = [], errors = [], failures = [], screenshots = []
let browser, failure
await mkdir(output, { recursive: true })
try {
  browser = await chromium.launch({ channel: 'msedge', headless: true })
  for (const [name, width] of [['admin', 1440], ['admin', 390], ['赵国华', 1440]]) {
    const auth = JSON.parse(session('issue', name)); sessions.push(auth)
    const context = await browser.newContext({ viewport: { width, height: 1000 }, reducedMotion: 'reduce' })
    await context.addCookies([{ name: 'oa_refresh', value: auth.refresh, domain: '127.0.0.1', path: '/api/auth', httpOnly: true, secure: false, sameSite: 'Lax' }])
    await context.route('**/api/**', route => {
      const request = route.request(), url = new URL(request.url())
      const allowed = ['GET', 'HEAD', 'OPTIONS'].includes(request.method()) || url.pathname === '/api/auth/refresh'
      return allowed ? route.continue() : route.abort()
    })
    const page = await context.newPage()
    page.on('pageerror', e => errors.push(String(e)))
    page.on('response', r => { if (r.url().includes('/api/') && r.status() >= 400) failures.push({ path: new URL(r.url()).pathname, status: r.status() }) })
    await page.goto('http://127.0.0.1:5182/emails')
    await page.waitForLoadState('networkidle')
    await expect(page.locator('main h1')).toHaveText('综合办公公共邮箱')
    if (name === 'admin') {
      await page.getByRole('textbox', { name: '搜索邮件' }).fill('OA公共邮箱自测-')
      await page.getByRole('textbox', { name: '搜索邮件' }).press('Enter')
      await page.waitForLoadState('networkidle')
      await expect(page.locator('.mail-list-row').first()).toBeVisible()
      await page.locator('.mail-list-row').first().click()
      await expect(page.locator('.mail-body')).toContainText('综合办公公共邮箱验收邮件')
      await expect(page.getByRole('button', { name: /^(录入并分析|查看分析)$/ })).toBeVisible()
      await page.getByRole('button', { name: '成员授权', exact: true }).click()
      const dialog = page.getByRole('dialog', { name: '公共邮箱成员授权' })
      await expect(dialog).toBeVisible()
      await expect(dialog.locator('.el-table__body-wrapper tbody tr')).toHaveCount(9)
      await expect(dialog.locator('.el-dialog')).toHaveCSS('width', width === 390 ? '358px' : '760px')
      for (const control of [dialog.getByRole('button', { name: '保存授权' }), ...['处理', '发送', '管理'].map(name => dialog.getByRole('columnheader', { name, exact: true }))]) {
        const bounds = await control.boundingBox()
        expect(bounds).not.toBeNull()
        expect(bounds.x).toBeGreaterThanOrEqual(0)
        expect(bounds.x + bounds.width).toBeLessThanOrEqual(width)
      }
      await page.evaluate(() => Promise.all(document.getAnimations().map(animation => animation.finished.catch(() => {}))))
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
      await page.screenshot({ path: path.join(output, `members-${width}.png`), fullPage: true, animations: 'disabled' }); screenshots.push(`members-${width}.png`)
      await dialog.getByRole('button', { name: '取消', exact: true }).click()
      await expect(dialog).toBeHidden()
    } else {
      await expect(page.getByText('尚未获得公共邮箱访问授权，请联系邮箱管理员')).toBeVisible()
      await expect(page.getByRole('button', { name: '写邮件', exact: true })).toHaveCount(0)
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.screenshot({ path: path.join(output, `${name === 'admin' ? 'admin' : 'unauthorized'}-${width}.png`), fullPage: true })
    screenshots.push(`${name === 'admin' ? 'admin' : 'unauthorized'}-${width}.png`)
    await context.close()
  }
} catch (e) { failure = e }
finally {
  if (browser) await browser.close()
  for (const auth of sessions) { try { session('revoke', auth.family) } catch { failure ||= new Error('session_cleanup_failed') } }
  await writeFile(path.join(output, 'browser-verification.json'), JSON.stringify({ passed: !failure && !errors.length && !failures.length,
    page_errors: errors, failed_requests: failures, screenshots, sessions_revoked: !failure || !String(failure).includes('cleanup'), error: failure ? String(failure) : null }, null, 2))
}
if (failure || errors.length || failures.length) throw failure || new Error('browser_verification_failed')
console.log(JSON.stringify({ passed: true, viewports: [1440, 390], sessions_revoked: true, output }))
