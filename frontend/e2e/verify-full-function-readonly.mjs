// Inspect actual permitted pages without changing business records or sending messages.
import { execFileSync } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'

const root = fileURLToPath(new URL('../../', import.meta.url))
const backend = path.join(root, 'backend')
const output = path.join(root, 'output/business-acceptance-private/full-function-browser')
const stamp = new Date().toISOString().replace(/[:.]/g, '-')
const receipt = { checked_at: new Date().toISOString(), scope: 'actual_permitted_pages_read_only', external_delivery: false, model_calls: false, department_trial: false, checks: [], unavailable_menus: [], screenshots: [] }
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
            print(json.dumps(dict(refresh=issued.refresh,family=row.family_id,head=head)))
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
const pages = [
  ['我的申请', '/oa/leaves'], ['报销工作台', '/oa/reimbursements'], ['工单工作台', '/oa/tickets'],
  ['通知与站内信', '/oa/notifications'], ['部门公告', '/oa/announcements'], ['审批工作台', '/oa/approvals'],
  ['审批委托', '/oa/delegations'], ['请假额度', '/oa/balances'], ['流程配置', '/oa/workflows'],
  ['流程管理', '/oa/administration'], ['智能助手', '/assistant'], ['我的任务', '/tasks'],
  ['会议管理', '/meetings'], ['文档起草', '/documents'], ['邮件工作台', '/emails'],
  ['业务任务', '/work-tasks'], ['只读报表', '/reports'], ['合同审查', '/contracts'],
  ['组织管理', '/organization'], ['运行告警', '/organization/alerts'], ['智能配置', '/config'],
  ['策略版本', '/config/policies'], ['知识库', '/knowledge'], ['来源治理', '/knowledge/sources'],
  ['审计中心', '/audit'], ['运维观测', '/operations'], ['降级控制', '/degradation'],
]
await mkdir(output, { recursive: true })
let session, browser, page, failure
const errors = [], requests = [], blocked = []
async function inspect(label, pathname, mobile = false) {
  // Use client-side navigation without rotating the session for every page.
  if (new URL(page.url()).pathname !== pathname) {
    if (pathname === '/account') {
      await page.getByRole('button', { name: '账户菜单', exact: true }).click()
      await page.getByRole('menuitem', { name: '个人账户', exact: true }).click()
    } else {
      if (mobile) await page.getByRole('button', { name: '打开导航', exact: true }).click()
      const navigation = page.locator(mobile ? '.oa-nav-drawer' : '.app-aside')
      const item = navigation.getByRole('menuitem', { name: label, exact: true })
      if (!await item.isVisible()) await item.locator('xpath=ancestor::li[contains(@class,"el-sub-menu")][1]').locator(':scope > .el-sub-menu__title').click()
      await item.click()
      if (mobile) await expect(navigation).toBeHidden()
    }
  }
  await expect(page).toHaveURL('http://127.0.0.1:5182' + pathname)
  // Lazy route components can mount after the URL changes and before requests start.
  await expect.poll(async () => (await page.locator('.app-main').innerText()).trim().length).toBeGreaterThan(15)
  await page.waitForLoadState('networkidle')
  await expect(page.locator('.el-loading-mask:visible')).toHaveCount(0)
  expect((await page.locator('.app-main').innerText()).trim().length).toBeGreaterThan(15)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  receipt.checks.push({ name: label, path: pathname, viewport: mobile ? '390x844' : '1440x960', passed: true })
  console.log('PASS ' + (mobile ? 'mobile ' : 'desktop ') + label)
  if (mobile || ['/assistant', '/tasks', '/knowledge', '/organization/alerts'].includes(pathname)) {
    const filename = stamp + (mobile ? '-mobile-' : '-desktop-') + pathname.replaceAll('/', '_') + '.png'
    await page.screenshot({ path: path.join(output, filename), fullPage: true, animations: 'disabled' })
    receipt.screenshots.push(filename)
  }
}
try {
  session = JSON.parse(identity('issue'))
  receipt.schema = session.head
  expect(session.head).toBe('0037')
  browser = await chromium.launch({ channel: 'msedge', headless: true })
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
  await context.addCookies([{ name: 'oa_refresh', value: session.refresh, domain: '127.0.0.1', path: '/api/auth', httpOnly: true, secure: false, sameSite: 'Lax' }])
  await context.route('**/api/**', async route => {
    const request = route.request(), pathname = new URL(request.url()).pathname
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method()) && pathname !== '/api/auth/refresh') {
      blocked.push({ path: pathname, method: request.method() })
      return route.abort()
    }
    return route.continue()
  })
  page = await context.newPage()
  page.on('pageerror', () => errors.push('page_error'))
  page.on('response', response => { if (response.url().includes('/api/') && response.status() >= 400) requests.push({ path: new URL(response.url()).pathname, status: response.status() }) })
  await page.goto('http://127.0.0.1:5182/account')
  await page.waitForLoadState('networkidle')
  await expect(page.locator('.app-aside .el-sub-menu')).toHaveCount(6)
  await page.getByRole('button', { name: '收起侧栏', exact: true }).click()
  await expect(page.locator('.oa-app')).toHaveClass(/is-collapsed/)
  await page.reload()
  await expect(page.getByRole('button', { name: '展开侧栏', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '展开侧栏', exact: true }).click()
  await page.getByRole('button', { name: '账户菜单', exact: true }).click()
  await expect(page.getByRole('menuitem', { name: '个人账户', exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  receipt.checks.push({ name: '桌面侧栏收起、偏好恢复及账户菜单', passed: true })
  for (const group of await page.locator('.app-aside .el-sub-menu').all()) {
    if (await group.getAttribute('aria-expanded') !== 'true') await group.locator(':scope > .el-sub-menu__title').click()
  }
  const visibleMenus = await page.locator('.app-aside .el-menu-item').allTextContents()
  const permitted = pages.filter(([label]) => visibleMenus.some(text => text.trim() === label))
  receipt.unavailable_menus = pages.filter(([label]) => !permitted.some(([name]) => name === label)).map(([name]) => name)
  for (const [label, pathname] of permitted) await inspect(label, pathname)
  await inspect('个人账号', '/account')
  await page.setViewportSize({ width: 390, height: 844 })
  for (const [label, pathname] of permitted.filter(([, url]) => ['/assistant', '/tasks', '/oa/notifications', '/contracts'].includes(url))) await inspect(label, pathname, true)
  await expect(page.locator('.app-aside')).toBeHidden()
  await page.getByRole('button', { name: '打开导航', exact: true }).click()
  const drawer = page.locator('.oa-nav-drawer')
  await expect(drawer).toBeVisible()
  await drawer.getByRole('menuitem', { name: '会议管理', exact: true }).click()
  await expect(page).toHaveURL('http://127.0.0.1:5182/meetings')
  await expect(drawer).toBeHidden()
  await expect(page.locator('.app-breadcrumb')).toContainText('会议管理')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  await page.screenshot({ path: path.join(output, stamp + '-mobile-meetings.png'), fullPage: true, animations: 'disabled' })
  receipt.screenshots.push(stamp + '-mobile-meetings.png')
  receipt.checks.push({ name: '手机导航打开、跳转自动关闭和面包屑', passed: true })

  // Simulate server permission changes without modifying accounts or business records.
  await page.waitForLoadState('networkidle')
  let permissions = []
  await context.route('**/api/auth/me', async route => {
    const response = await route.fetch()
    const body = await response.json()
    return route.fulfill({ json: { ...body, data: { ...body.data, roles: [], permissions } } })
  })
  await page.evaluate(() => window.dispatchEvent(new Event('oa-permissions-changed')))
  await expect(page).toHaveURL('http://127.0.0.1:5182/account')
  await page.getByRole('button', { name: '打开导航', exact: true }).click()
  await expect(drawer.locator('.el-sub-menu')).toHaveCount(0)
  await expect(drawer).toContainText('暂无可访问的功能')
  await page.getByRole('button', { name: '关闭导航', exact: true }).click()
  permissions = [{ resource: 'meeting', action: 'read', scope: 'self' }]
  await page.evaluate(() => window.dispatchEvent(new Event('oa-permissions-changed')))
  await page.getByRole('button', { name: '打开导航', exact: true }).click()
  await expect(drawer.locator('.el-sub-menu')).toHaveCount(1)
  await drawer.getByRole('menuitem', { name: '会议管理', exact: true }).click()
  await expect(page).toHaveURL('http://127.0.0.1:5182/meetings')
  await expect(drawer).toBeHidden()
  receipt.checks.push({ name: '动态权限收缩跳转、空分组隐藏及恢复授权无需重新登录', passed: true })
} catch (error) { failure = error; receipt.error = String(error?.message || error) }
finally {
  if (browser) await browser.close()
  if (session) { try { identity('revoke', session.family); receipt.acceptance_session_revoked = true } catch { receipt.acceptance_session_revoked = false; failure ||= new Error('session_cleanup_failed') } }
  receipt.page_errors = errors; receipt.failed_requests = requests; receipt.blocked_business_writes = blocked
  receipt.passed = !failure && !errors.length && !requests.length && !blocked.length
  await writeFile(path.join(output, 'browser-' + stamp + '.json'), JSON.stringify(receipt, null, 2) + '\n')
}
if (!receipt.passed) throw failure || new Error('browser_errors_or_unexpected_business_writes')
