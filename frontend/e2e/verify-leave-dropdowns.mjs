import { execFileSync } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'

const root = fileURLToPath(new URL('../../', import.meta.url))
const backend = path.join(root, 'backend')
const output = path.join(root, 'output/business-acceptance-private/leave-dropdowns')
const stamp = new Date().toISOString().replace(/[:.]/g, '-')
const base = 'http://127.0.0.1:5182'
const receipt = { checked_at: new Date().toISOString(), checks: [], screenshots: [], business_writes: [], page_errors: [], failed_requests: [] }
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
        actor=await actor_for_import(db,'oa_admin')
        user=await db.get(OAUser,actor.user_id)
        if sys.argv[1]=='issue':
            issued=await identity.issue(db,user,get_settings(),expires=identity.utcnow()+timedelta(minutes=20))
            row=await db.scalar(select(OAAuthSession).where(OAAuthSession.refresh_digest==identity.digest(issued.refresh)))
            identity.audit(db,user.id,'identity.acceptance_session',row.family_id)
            await db.commit()
            print(json.dumps(dict(refresh=issued.refresh,family=row.family_id)))
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
let session, browser, failure
try {
  session = JSON.parse(identity('issue'))
  browser = await chromium.launch({ channel: 'msedge', headless: true })
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
  await context.addCookies([{ name: 'oa_refresh', value: session.refresh, domain: '127.0.0.1', path: '/api/auth', httpOnly: true, secure: false, sameSite: 'Lax' }])
  await context.route('**/api/**', async route => {
    const request = route.request(), pathname = new URL(request.url()).pathname
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method()) && pathname !== '/api/auth/refresh') {
      receipt.business_writes.push({ path: pathname, method: request.method() })
      return route.abort()
    }
    return route.continue()
  })
  const page = await context.newPage()
  page.on('pageerror', () => receipt.page_errors.push('page_error'))
  page.on('response', response => { if (response.url().includes('/api/') && response.status() >= 400) receipt.failed_requests.push({ path: new URL(response.url()).pathname, status: response.status() }) })
  for (const mobile of [false, true]) {
    await page.setViewportSize(mobile ? { width: 390, height: 844 } : { width: 1440, height: 960 })
    const responsePromise = page.waitForResponse(response => new URL(response.url()).pathname === '/api/oa/workflows' && new URL(response.url()).searchParams.get('available') === 'true')
    await page.goto(base + '/oa/leaves/new')
    const response = await responsePromise
    expect(response.status()).toBe(200)
    expect((await response.json()).data).toEqual([])
    await expect(page.getByText('本部门暂无已发布的请假流程', { exact: true })).toBeVisible()
    await expect(page.getByLabel('请假流程', { exact: true })).toBeDisabled()
    await expect(page.getByLabel('假种', { exact: true })).toBeDisabled()
    await expect(page.getByLabel('请假流程', { exact: true }).locator('option')).toHaveText(['暂无可用请假流程'])
    await expect(page.getByLabel('假种', { exact: true }).locator('option')).toHaveText(['暂无可用假种'])
    await expect(page.getByTestId('save-leave')).toBeDisabled()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    const filename = stamp + (mobile ? '-mobile' : '-desktop') + '.png'
    await page.screenshot({ path: path.join(output, filename), fullPage: true, animations: 'disabled' })
    receipt.screenshots.push(filename)
    receipt.checks.push({ name: 'actual_empty_configuration', viewport: mobile ? '390x844' : '1440x960', passed: true })
    await page.getByTestId('configure-leave-workflow').click()
    await expect(page).toHaveURL(base + '/oa/workflows')
    await expect(page.getByTestId('new-workflow')).toBeVisible()
  }
  await context.route('**/api/oa/workflows?available=true', route => route.fulfill({ json: { code: '0', data: [
    { id: 'fixture-annual', name: '年假流程', published_version: 1, form: { leave_types: ['annual'] } },
    { id: 'fixture-sick', name: '病假流程', published_version: 1, form: { leave_types: ['sick', '事假'] } },
  ] } }))
  for (const mobile of [false, true]) {
    await page.setViewportSize(mobile ? { width: 390, height: 844 } : { width: 1440, height: 960 })
    await page.goto(base + '/oa/leaves/new')
    const workflow = page.getByLabel('请假流程', { exact: true }), types = page.getByLabel('假种', { exact: true })
    await expect(workflow).toBeEnabled()
    await expect(workflow.locator('option')).toHaveText(['年假流程', '病假流程'])
    await expect(types.locator('option')).toHaveText(['年假'])
    await workflow.selectOption('fixture-sick')
    await expect(types.locator('option')).toHaveText(['病假', '事假'])
    await expect(types).toHaveValue('sick')
    await types.selectOption('事假')
    await expect(types).toHaveValue('事假')
    await expect(page.getByText('本部门暂无已发布的请假流程', { exact: true })).toHaveCount(0)
    receipt.checks.push({ name: 'intercepted_published_options_and_selection', viewport: mobile ? '390x844' : '1440x960', passed: true })
  }
} catch (error) { failure = error; receipt.error = String(error?.message || error) }
finally {
  if (browser) await browser.close()
  if (session) { try { identity('revoke', session.family); receipt.session_revoked = true } catch { failure ||= new Error('session_cleanup_failed') } }
  receipt.passed = !failure && !receipt.business_writes.length && !receipt.page_errors.length && !receipt.failed_requests.length
  await writeFile(path.join(output, 'browser-' + stamp + '.json'), JSON.stringify(receipt, null, 2) + '\n')
}
console.log(JSON.stringify(receipt))
if (!receipt.passed) throw failure || new Error('browser_verification_failed')
