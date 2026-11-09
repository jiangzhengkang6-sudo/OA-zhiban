// Read-only inspection with a temporary audited session; no outbound alerts.
import { execFileSync } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'

const root = fileURLToPath(new URL('../../', import.meta.url))
const backend = path.join(root, 'backend')
const output = path.join(root, 'output/business-acceptance-private/operational-alerts')
const stamp = new Date().toISOString().replace(/[:.]/g, '-')
const receipt = { checked_at: new Date().toISOString(), scope: 'read_only_local_monitor', external_delivery: false, department_trial: false, checks: [], screenshots: [] }
const program = `
import asyncio,json,sys
from datetime import timedelta
from sqlalchemy import select,update,text
from app.core.config import get_settings
from app.db.session import async_session_factory,engine
from app.models.identity import OAUser,OAAuthSession
from app.services import identity_service as identity
from scripts.import_public_company_knowledge import actor_for_import
async def main():
    async with async_session_factory() as db:
        actor=await actor_for_import(db,'oa_admin')
        user=await db.get(OAUser,actor.user_id)
        if sys.argv[1]=='issue':
            issued=await identity.issue(db,user,get_settings(),expires=identity.utcnow()+timedelta(minutes=20))
            row=await db.scalar(select(OAAuthSession).where(OAAuthSession.refresh_digest==identity.digest(issued.refresh)))
            identity.audit(db,user.id,'identity.acceptance_session',row.family_id)
            await db.commit()
            head=await db.scalar(text('SELECT version_num FROM alembic_version'))
            members=len((await db.scalars(select(OAUser).where(OAUser.tenant_id==actor.tenant_id,OAUser.status=='active'))).all())
            print(json.dumps(dict(refresh=issued.refresh,family=row.family_id,head=head,active_members=members)))
        else:
            family=sys.argv[2]
            await db.execute(update(OAAuthSession).where(OAAuthSession.tenant_id==actor.tenant_id,OAAuthSession.user_id==user.id,OAAuthSession.family_id==family).values(revoked_at=identity.utcnow()))
            identity.audit(db,user.id,'identity.acceptance_closed',family)
            await db.commit()
            assert await db.scalar(select(OAAuthSession.id).where(OAAuthSession.family_id==family,OAAuthSession.revoked_at.is_(None))) is None
    await engine.dispose()
asyncio.run(main())
`
function identity(action, family) {
  try { return execFileSync(path.join(backend, '.venv/Scripts/python.exe'), ['-c', program, action, ...(family ? [family] : [])], { cwd: backend, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim() }
  catch { throw new Error('acceptance_identity_failed') }
}
await mkdir(output, { recursive: true })
let session, browser, page, failure
const errors = [], requests = []
async function check(name, fn) { await fn(); receipt.checks.push({ name, passed: true }); console.log('PASS ' + name) }
async function screenshot(name) {
  const filename = stamp + '-' + name + '.png'
  await page.screenshot({ path: path.join(output, filename), fullPage: true, animations: 'disabled' })
  receipt.screenshots.push(filename)
}
try {
  session = JSON.parse(identity('issue'))
  receipt.schema = session.head; receipt.active_members = session.active_members
  expect(session.head).toBe('0033')
  browser = await chromium.launch({ channel: 'msedge', headless: true })
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
  await context.addCookies([{ name: 'oa_refresh', value: session.refresh, domain: '127.0.0.1', path: '/api/auth', httpOnly: true, secure: false, sameSite: 'Lax' }])
  page = await context.newPage()
  page.on('pageerror', () => errors.push('page_error'))
  page.on('response', response => { if (response.url().includes('/api/') && response.status() >= 400) requests.push({ path: new URL(response.url()).pathname, status: response.status() }) })
  await check('desktop shows nine actual checks and safe disabled delivery', async () => {
    const response = page.waitForResponse(r => new URL(r.url()).pathname === '/api/organization/operational-alerts')
    await page.goto('http://127.0.0.1:5182/organization/alerts')
    const result = await response
    expect(result.ok()).toBe(true)
    const snapshot = (await result.json()).data
    expect(snapshot.state).toBe('running'); expect(snapshot.checks).toHaveLength(9)
    expect(snapshot.checks.find(row => row.key === 'log_keywords')?.name).toBe('日志关键字')
    expect(snapshot.delivery_enabled).toBe(false)
    receipt.actual_checks = snapshot.checks.map(({key,status,code,count}) => ({key,status,code,...(count === undefined ? {} : {count})}))
    await expect(page.getByRole('heading', { name: '运行告警', exact: true })).toBeVisible()
    await expect(page.getByText('外部告警通知尚未启用', { exact: true })).toBeVisible()
    await expect(page.locator('.alerts-page section').first().locator('.el-table__body-wrapper tbody tr')).toHaveCount(9)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await screenshot('desktop')
  })
  await check('manual refresh completes without failed requests', async () => {
    const response = page.waitForResponse(r => new URL(r.url()).pathname === '/api/organization/operational-alerts')
    await page.getByRole('button', { name: '刷新运行告警', exact: true }).click()
    expect((await response).ok()).toBe(true)
    await expect(page.locator('.el-loading-mask')).toBeHidden()
  })
  await check('mobile layout fits and check table remains scrollable', async () => {
    await page.setViewportSize({ width: 390, height: 844 })
    await expect(page.getByRole('heading', { name: '运行告警', exact: true })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    const scroller = page.locator('.alerts-page section').first().locator('.el-scrollbar__wrap')
    expect(await scroller.evaluate(el => el.scrollWidth > el.clientWidth)).toBe(true)
    await screenshot('mobile')
    await scroller.evaluate(el => { el.scrollLeft = el.scrollWidth })
    expect(await scroller.evaluate(el => el.scrollLeft)).toBeGreaterThan(0)
    await screenshot('mobile-scrolled')
  })
} catch (error) { failure = error; receipt.error = String(error?.message || error) }
finally {
  if (browser) await browser.close()
  if (session) { try { identity('revoke', session.family); receipt.acceptance_session_revoked = true } catch { receipt.acceptance_session_revoked = false; failure ||= new Error('session_cleanup_failed') } }
  receipt.page_errors = errors; receipt.failed_requests = requests
  receipt.passed = !failure && !errors.length && !requests.length
  await writeFile(path.join(output, 'browser-' + stamp + '.json'), JSON.stringify(receipt, null, 2) + '\n')
}
if (!receipt.passed) throw failure || new Error('browser_errors_or_failed_requests')
