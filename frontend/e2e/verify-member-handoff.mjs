// Existing-member inspection only: no lifecycle changes or outbound messages.
import { execFileSync } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'

const root = fileURLToPath(new URL('../../', import.meta.url))
const backend = path.join(root, 'backend')
const output = path.join(root, 'output/business-acceptance-private/member-handoff')
const stamp = new Date().toISOString().replace(/[:.]/g, '-')
const receipt = { checked_at: new Date().toISOString(), scope: 'existing_single_member_read_only', department_trial: false, external_delivery: false, checks: [], screenshots: [] }
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
async function fits() {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  for (const element of await page.locator('.el-dialog:visible').all()) {
    const size = await element.evaluate(node => ({ width: node.getBoundingClientRect().width, left: node.getBoundingClientRect().left, scroll: node.scrollWidth, inner: node.clientWidth }))
    expect(size.left).toBeGreaterThanOrEqual(0)
    expect(size.scroll).toBeLessThanOrEqual(size.inner + 1)
  }
}
async function openHandoff() {
  const response = page.waitForResponse(r => /\/api\/organization\/users\/[^/]+\/handoff$/.test(new URL(r.url()).pathname))
  const button = page.getByRole('button', { name: '交接', exact: true }).first()
  await button.scrollIntoViewIfNeeded()
  await button.click()
  const result = await response
  expect(result.ok()).toBe(true)
  const inventory = (await result.json()).data
  receipt.inventory = { total: inventory.total, restricted_count: inventory.restricted_count, counts: inventory.counts }
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByText('成员变更与交接记录', { exact: true })).toBeVisible()
  await expect(page.getByText('未交事项 ' + inventory.total + ' 项', { exact: true })).toBeVisible()
}
try {
  session = JSON.parse(identity('issue'))
  receipt.schema = session.head
  receipt.active_members = session.active_members
  expect(session.head).toBe('0033')
  browser = await chromium.launch({ channel: 'msedge', headless: true })
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
  await context.addCookies([{ name: 'oa_refresh', value: session.refresh, domain: '127.0.0.1', path: '/api/auth', httpOnly: true, secure: false, sameSite: 'Lax' }])
  page = await context.newPage()
  page.on('pageerror', () => errors.push('page_error'))
  page.on('response', response => { if (response.url().includes('/api/') && response.status() >= 400) requests.push({ path: new URL(response.url()).pathname, status: response.status() }) })
  await check('desktop organization and member inventory', async () => {
    const response = page.waitForResponse(r => new URL(r.url()).pathname === '/api/organization')
    await page.goto('http://127.0.0.1:5182/organization')
    expect((await response).ok()).toBe(true)
    await expect(page.getByRole('heading', { name: '组织管理', exact: true })).toBeVisible()
    await openHandoff()
    await fits(); await screenshot('desktop-handoff')
    await page.getByRole('button', { name: '关闭', exact: true }).click()
    await expect(page.getByRole('dialog')).toBeHidden()
  })
  await check('desktop batch changes require explicit choices', async () => {
    await page.locator('.el-table__body-wrapper .el-checkbox').first().click()
    await page.getByRole('button', { name: /批量调整（1）/ }).click()
    await expect(page.getByRole('dialog', { name: '批量调整成员' })).toBeVisible()
    await expect(page.getByRole('checkbox', { name: '调整状态', exact: true })).not.toBeChecked()
    await expect(page.getByRole('combobox', { name: '批量成员状态' })).toBeDisabled()
    await fits(); await screenshot('desktop-batch')
    await page.getByRole('button', { name: '取消', exact: true }).click()
    await expect(page.getByRole('dialog')).toBeHidden()
  })
  await check('handoff tab lists only members awaiting handoff', async () => {
    await page.getByRole('tab', { name: '交接工作台', exact: true }).click()
    await expect(page.getByRole('tab', { name: '交接工作台', exact: true })).toHaveAttribute('aria-selected', 'true')
    await expect(page.getByRole('button', { name: /批量调整/ })).toBeHidden()
    await fits()
    await page.getByRole('tab', { name: '成员', exact: true }).click()
  })
  await check('mobile handoff dialog fits viewport', async () => {
    await page.setViewportSize({ width: 390, height: 844 })
    await openHandoff()
    await fits(); await screenshot('mobile-handoff')
    await page.getByRole('button', { name: '关闭', exact: true }).click()
    await expect(page.getByRole('dialog')).toBeHidden()
  })
  await check('mobile batch dialog fits viewport', async () => {
    await page.locator('.el-table__body-wrapper .el-checkbox').first().click()
    await page.getByRole('button', { name: /批量调整（1）/ }).click()
    await expect(page.getByRole('dialog', { name: '批量调整成员' })).toBeVisible()
    await fits(); await screenshot('mobile-batch')
    await page.getByRole('button', { name: '取消', exact: true }).click()
    await expect(page.getByRole('dialog')).toBeHidden()
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
