// Read-only live roster verification; temporary audited sessions are always revoked.
import { execFileSync } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'

const root = fileURLToPath(new URL('../../', import.meta.url))
const backend = path.join(root, 'backend')
const output = path.join(root, 'output/business-acceptance-private/management-people')
const stamp = new Date().toISOString().replace(/[:.]/g, '-')
const program = `
import asyncio,json,sys
from datetime import timedelta
from sqlalchemy import select,update
from app.core.config import get_settings
from app.db.session import async_session_factory,engine
from app.models.identity import OAUser,OAAuthSession,OAMembership,OADepartment
from app.services import identity_service as identity
from scripts.import_public_company_knowledge import actor_for_import
async def main():
    async with async_session_factory() as db:
        admin=await actor_for_import(db,'oa_admin')
        if sys.argv[1]=='revoke':
            family=sys.argv[2]
            await db.execute(update(OAAuthSession).where(OAAuthSession.tenant_id==admin.tenant_id,
                OAAuthSession.family_id==family).values(revoked_at=identity.utcnow()))
            identity.audit(db,admin.user_id,'identity.acceptance_closed',family)
            await db.commit()
            assert await db.scalar(select(OAAuthSession.id).where(OAAuthSession.family_id==family,
                OAAuthSession.revoked_at.is_(None))) is None
        else:
            user=await db.get(OAUser,admin.user_id) if sys.argv[2]=='admin' else await db.scalar(select(OAUser).where(
                OAUser.tenant_id==admin.tenant_id,OAUser.display_name==sys.argv[2],OAUser.status=='active'))
            assert user is not None
            actor=await identity.current_identity(db,user)
            people=(await db.execute(select(OAUser.id,OAUser.display_name,OAMembership.department_id).join(OAMembership,
                (OAMembership.tenant_id==OAUser.tenant_id)&(OAMembership.user_id==OAUser.id)).join(OADepartment,
                (OADepartment.tenant_id==OAMembership.tenant_id)&(OADepartment.id==OAMembership.department_id)).where(
                OAUser.tenant_id==admin.tenant_id,OAUser.status=='active',OADepartment.enabled.is_(True)))).all()
            issued=await identity.issue(db,user,get_settings(),expires=identity.utcnow()+timedelta(minutes=20))
            row=await db.scalar(select(OAAuthSession).where(OAAuthSession.refresh_digest==identity.digest(issued.refresh)))
            identity.audit(db,user.id,'identity.acceptance_session',row.family_id)
            result=json.dumps(dict(refresh=issued.refresh,family=row.family_id,
                people=[dict(id=p.id,name=p.display_name,department=p.department_id) for p in people],departments=actor.depts))
            await db.commit()
            print(result)
    await engine.dispose()
asyncio.run(main())
`
function identity(action, value) {
  try { return execFileSync(path.join(backend, '.venv/Scripts/python.exe'), ['-c', program, action, value],
    { cwd: backend, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim() }
  catch { throw new Error('acceptance_identity_failed') }
}
const receipt = { checked_at: new Date().toISOString(), business_writes: false, checks: [], screenshots: [], revoked: [] }
const sessions = [], errors = [], failed = [], blocked = []
let browser, failure
await mkdir(output, { recursive: true })
try {
  browser = await chromium.launch({ channel: 'msedge', headless: true })
  for (const [name, route] of [['admin', '/oa/balances'], ['郑晓华', '/contracts'], ['赵国华', '/oa/balances']]) {
    const session = JSON.parse(identity('issue', name)); sessions.push(session)
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
    await context.addCookies([{ name: 'oa_refresh', value: session.refresh, domain: '127.0.0.1', path: '/api/auth', httpOnly: true, secure: false, sameSite: 'Lax' }])
    await context.route('**/api/**', async request => {
      if (!['GET', 'HEAD', 'OPTIONS'].includes(request.request().method()) && !request.request().url().endsWith('/api/auth/refresh')) {
        blocked.push(new URL(request.request().url()).pathname); return request.abort()
      }
      return request.continue()
    })
    const page = await context.newPage()
    page.on('pageerror', error => errors.push(String(error)))
    page.on('response', response => { if (response.url().includes('/api/') && response.status() >= 400) failed.push({ path: new URL(response.url()).pathname, status: response.status() }) })
    await page.goto('http://127.0.0.1:5182' + route)
    await page.waitForLoadState('networkidle')
    await expect(page.locator('main h1')).toHaveText(name === '郑晓华' ? '合同审查' : '请假额度')
    if (name === '郑晓华') {
      const select = page.getByRole('combobox', { name: '指定复核人' })
      await expect(select).toHaveValue('')
      await select.locator('xpath=ancestor::div[contains(@class,"el-select__wrapper")][1]').click()
      const options = page.locator('.el-select-dropdown:visible .el-select-dropdown__item')
      await expect(options.filter({ hasText: '郑晓华' })).toHaveCount(1)
      const names = (await options.allTextContents()).map(value => value.trim())
      expect(names).not.toContain('李四'); expect(names).not.toContain('王五'); expect(names).not.toContain('管理员')
      receipt.checks.push({ name: '法务复核人读取现有成员且无旧演示人员、无默认旧账号', passed: true, candidates: names })
    } else if (name === '赵国华') {
      await expect(page.getByTestId('adjust-balance')).toHaveCount(0)
      receipt.checks.push({ name: '未授予额度管理权的部门经理不显示调整入口', passed: true })
    } else {
      await page.getByTestId('adjust-balance').click()
      const dialog = page.getByRole('dialog')
      await dialog.locator('.el-select__wrapper').click()
      const options = page.locator('.el-select-dropdown:visible .el-select-dropdown__item')
      const expected = name === 'admin' ? session.people : session.people.filter(person => session.departments.includes(person.department))
      await expect(options).toHaveCount(expected.length)
      expect((await options.allTextContents()).map(value => value.trim()).sort()).toEqual(expected.map(person => person.name).sort())
      if (name === 'admin') {
        const balanceRequest = page.waitForResponse(response => response.url().includes('/api/oa/balances?user_id=') && response.ok())
        await options.filter({ hasText: '郑晓华' }).click()
        await balanceRequest
        await expect(dialog.locator('.el-select__placeholder')).toHaveText('郑晓华')
      }
      receipt.checks.push({ name: name === 'admin' ? '管理员可选择全部有效组织成员并读取法务成员额度' : '产品部门经理仍仅能选择本部门成员', passed: true, people_count: expected.length })
    }
    const screenshot = stamp + (name === 'admin' ? '-admin-balances.png' : name === '郑晓华' ? '-legal-reviewers.png' : '-manager-balances.png')
    await page.screenshot({ path: path.join(output, screenshot), fullPage: true, animations: 'disabled' })
    receipt.screenshots.push(screenshot)
    await context.close()
  }
} catch (error) { failure = error; receipt.error = String(error?.message || error) }
finally {
  if (browser) await browser.close()
  for (const session of sessions) {
    try { identity('revoke', session.family); receipt.revoked.push(true) }
    catch { receipt.revoked.push(false); failure ||= new Error('session_cleanup_failed') }
  }
  receipt.page_errors = errors; receipt.failed_requests = failed; receipt.blocked_writes = blocked
  receipt.passed = !failure && !errors.length && !failed.length && !blocked.length
  await writeFile(path.join(output, 'verification-' + stamp + '.json'), JSON.stringify(receipt, null, 2) + '\n')
}
if (!receipt.passed) throw failure || new Error('browser_verification_failed')
console.log(JSON.stringify({ passed: true, checks: receipt.checks, temporary_sessions_revoked: receipt.revoked.every(Boolean), output }))
