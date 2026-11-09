// Inspect existing business data; only a temporary authentication session is written.
import { execFileSync } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'

const root = fileURLToPath(new URL('../../', import.meta.url))
const backend = path.join(root, 'backend')
const output = path.join(root, 'output/business-acceptance-private/meeting-management')
const stamp = new Date().toISOString().replace(/[:.]/g, '-')
const program = `
import asyncio,json,sys
from datetime import timedelta
from sqlalchemy import select,update,text,make_url
from app.core.config import get_settings
from app.db.session import async_session_factory,engine
from app.models.identity import OAUser,OAAuthSession
from app.services import identity_service as identity
from scripts.import_public_company_knowledge import actor_for_import
async def main():
    assert make_url(get_settings().database_url).database=='oa_agent_test'
    async with async_session_factory() as db:
        actor=await actor_for_import(db,'oa_admin')
        user=await db.get(OAUser,actor.user_id)
        if sys.argv[1]=='issue':
            issued=await identity.issue(db,user,get_settings(),expires=identity.utcnow()+timedelta(minutes=10))
            row=await db.scalar(select(OAAuthSession).where(OAAuthSession.refresh_digest==identity.digest(issued.refresh)))
            identity.audit(db,user.id,'identity.acceptance_session',row.family_id)
            await db.commit()
            head=await db.scalar(text('SELECT version_num FROM alembic_version'))
            counts={table:await db.scalar(text('SELECT count(*) FROM '+table)) for table in ('oa_user','oa_meeting','meeting_record')}
            print(json.dumps(dict(refresh=issued.refresh,family=row.family_id,head=head,counts=counts)))
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
const receipt = { checked_at: new Date().toISOString(), business_writes: false, external_delivery: false, checks: [], screenshots: [] }
await mkdir(output, { recursive: true })
let session, browser, page, failure
const errors = [], failed = [], mutations = []
async function check(name, run) { await run(); receipt.checks.push({ name, passed: true }); console.log('PASS ' + name) }
async function screenshot(name) {
  const filename = stamp + '-live-' + name + '.png'
  await page.screenshot({ path: path.join(output, filename), fullPage: true, animations: 'disabled' })
  receipt.screenshots.push(filename)
}
async function fits() { expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true) }
try {
  session = JSON.parse(identity('issue')); receipt.revision = session.head; receipt.counts = session.counts
  browser = await chromium.launch({ channel: 'msedge', headless: true })
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
  await context.addCookies([{ name: 'oa_refresh', value: session.refresh, domain: '127.0.0.1', path: '/api/auth', httpOnly: true, secure: false, sameSite: 'Lax' }])
  page = await context.newPage()
  page.on('pageerror', error => errors.push(error.message))
  page.on('response', response => { if (response.url().includes('/api/') && response.status() >= 400) failed.push({ path: new URL(response.url()).pathname, status: response.status() }) })
  // Block accidental business mutations even if the UI changes later.
  await page.route('**/api/**', route => {
    const request = route.request(), pathname = new URL(request.url()).pathname
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method()) && !pathname.startsWith('/api/auth/')) {
      mutations.push({ path: pathname, method: request.method() }); return route.abort()
    }
    return route.continue()
  })
  await check('business meeting list loads without writes', async () => {
    const waiting = page.waitForResponse(r => new URL(r.url()).pathname === '/api/meeting-events')
    await page.goto('http://127.0.0.1:5182/meetings')
    expect((await waiting).ok()).toBe(true)
    await expect(page.getByRole('heading', { name: '会议管理', exact: true })).toBeVisible()
    await fits(); await screenshot('desktop-list')
  })
  await check('real organization members and departments load in invitation form', async () => {
    const waiting = page.waitForResponse(r => new URL(r.url()).pathname === '/api/meeting-events/options')
    await page.getByRole('button', { name: '发起会议', exact: true }).click()
    const response = await waiting; expect(response.ok()).toBe(true)
    const options = (await response.json()).data
    expect(options.users.length).toBeGreaterThan(0); expect(options.departments.length).toBeGreaterThan(0)
    receipt.eligible_members = options.users.length; receipt.departments = options.departments.length
    const dialog = page.getByRole('dialog', { name: '发起会议', exact: true })
    await dialog.locator('.el-form-item').filter({ hasText: '参会人员' }).locator('.el-select__wrapper').click()
    await expect(page.getByRole('option', { name: options.users[0].display_name, exact: true }).first()).toBeVisible()
    await fits(); await screenshot('desktop-members')
    await dialog.getByRole('button', { name: '取消', exact: true }).click()
  })
  await check('existing minutes remain available through text workbench', async () => {
    const waiting = page.waitForResponse(r => new URL(r.url()).pathname === '/api/meetings')
    await page.getByRole('button', { name: '整理已有会议文本', exact: true }).click()
    const response = await waiting; expect(response.ok()).toBe(true)
    receipt.accessible_minutes = (await response.json()).data.items.length
    await expect(page.getByRole('heading', { name: '整理一场会议', exact: true })).toBeVisible()
    await fits(); await screenshot('existing-minutes')
  })
  await check('mobile business meeting page fits viewport', async () => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.getByRole('button', { name: '返回会议列表', exact: true }).click()
    await expect(page.getByRole('heading', { name: '会议管理', exact: true })).toBeVisible()
    await fits(); await screenshot('mobile-list')
  })
} catch (error) { failure = error; receipt.error = String(error?.message || error) }
finally {
  if (browser) await browser.close()
  if (session) { try { identity('revoke', session.family); receipt.acceptance_session_revoked = true } catch { receipt.acceptance_session_revoked = false; failure ||= new Error('session_cleanup_failed') } }
  receipt.page_errors = errors; receipt.failed_requests = failed; receipt.blocked_mutations = mutations
  receipt.passed = !failure && !errors.length && !failed.length && !mutations.length
  await writeFile(path.join(output, stamp + '-live-receipt.json'), JSON.stringify(receipt, null, 2) + '\n')
}
if (!receipt.passed) throw failure || new Error('browser_errors_or_unexpected_mutations')
