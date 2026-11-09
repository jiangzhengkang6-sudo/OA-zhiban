import { readFile, writeFile, mkdir } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, expect } from '@playwright/test'

const root = fileURLToPath(new URL('../../', import.meta.url))
const output = path.join(root, 'output/formal-oa-private')
const base = 'http://127.0.0.1:5182'
const credentials = JSON.parse(await readFile(path.join(output, 'department-demo-accounts.json'), 'utf8')).accounts
const roster = JSON.parse(await readFile(path.join(output, 'department-demo-setup.json'), 'utf8'))
const env = await readFile(path.join(output, 'initial-admin.env'), 'utf8')
const adminPassword = env.split(/\r?\n/).find(line => line.startsWith('OA_INITIAL_ADMIN_PASSWORD=')).split('=').slice(1).join('=').replace(/^['"]|['"]$/g, '')
const accounts = [{ username: 'oa_admin', display_name: '张翔', password: adminPassword }, ...credentials]
const receipt = { checked_at: new Date().toISOString(), checks: [], screenshots: [], page_errors: [], failed_requests: [], business_writes: [] }
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: 'msedge', headless: true })
let failure = false, current = ''
try {
  for (const account of accounts) {
    current = account.username
    const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
    const page = await context.newPage()
    let csrf, token, loggedIn = false, logoutDone = false
    const expectedUser = roster.users.find(u => u.username === account.username)
    const manager = expectedUser.role_ids.some(id => roster.roles.find(r => r.id === id)?.code === 'department_manager')
    page.on('pageerror', () => receipt.page_errors.push(current))
    await context.route('**/api/**', route => {
      const request = route.request(), pathname = new URL(request.url()).pathname
      if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method()) && !pathname.startsWith('/api/auth/')) {
        receipt.business_writes.push({ user: current, path: pathname })
        return route.abort()
      }
      return route.continue()
    })
    page.on('response', response => {
      if (response.url().includes('/api/') && response.status() >= 400 && !response.url().endsWith('/auth/refresh')) receipt.failed_requests.push({ user: current, path: new URL(response.url()).pathname, status: response.status() })
    })
    try {
      await page.goto(base + '/login')
      await page.locator('input[autocomplete="username"]').fill(account.username)
      await page.locator('input[autocomplete="current-password"]').fill(account.password)
      const loginResponse = page.waitForResponse(r => new URL(r.url()).pathname === '/api/auth/login')
      await page.getByRole('button', { name: '登录', exact: true }).click()
      const response = await loginResponse
      expect(response.status()).toBe(200)
      const grant = (await response.json()).data
      token = grant.access_token
      loggedIn = true
      expect(grant.user.user_id).toBe(expectedUser.id)
      expect(grant.user.depts).toEqual([expectedUser.department_id])
      expect(new Set(grant.user.roles)).toEqual(new Set(roster.roles.filter(r => expectedUser.role_ids.includes(r.id)).map(r => r.code)))
      await expect(page.getByRole('button', { name: '退出登录', exact: true })).toBeVisible()
      await expect(page.getByRole('menuitem', { name: '审批工作台', exact: true })).toHaveCount(account.username === 'oa_admin' || manager ? 1 : 0)
      await expect(page.getByRole('menuitem', { name: '组织管理', exact: true })).toHaveCount(account.username === 'oa_admin' ? 1 : 0)
      const headers = { Authorization: 'Bearer ' + token }
      const me = await context.request.get(base + '/api/auth/me', { headers })
      expect(me.status()).toBe(200)
      expect((await me.json()).data.user_id).toBe(expectedUser.id)
      const organization = await context.request.get(base + '/api/organization', { headers })
      expect(organization.status()).toBe(account.username === 'oa_admin' ? 200 : 403)
      const workflows = await context.request.get(base + '/api/oa/workflows', { headers })
      expect(workflows.status()).toBe(account.username === 'oa_admin' || manager ? 200 : 403)
      if (manager) {
        const options = await context.request.get(base + '/api/oa/workflows/options', { headers })
        expect(options.status()).toBe(200)
        const data = (await options.json()).data
        expect(data.departments.map(d => d.id)).toEqual([expectedUser.department_id])
        expect(new Set(data.users.map(u => u.id))).toEqual(new Set(roster.users.filter(u => u.department_id === expectedUser.department_id).map(u => u.id)))
      }
      const knowledge = await context.request.get(base + '/api/admin/knowledge/sources', { headers })
      expect(knowledge.status()).toBe(200)
      if (account.username === 'oa_admin') {
        await page.goto(base + '/organization')
        await expect(page.locator('.el-table__body-wrapper tbody tr')).toHaveCount(9)
        for (const user of roster.users) await expect(page.locator('.el-table__body-wrapper tbody').getByText(user.display_name, { exact: true })).toBeVisible()
        await page.screenshot({ path: path.join(output, 'department-roster-desktop.png'), fullPage: true })
        receipt.screenshots.push('department-roster-desktop.png')
        await page.getByRole('tab', { name: '部门', exact: true }).click()
        await expect(page.locator('.el-table__body-wrapper tbody tr')).toHaveCount(8)
      }
      if (account.username === 'chen_chen') {
        await page.setViewportSize({ width: 390, height: 844 })
        await page.goto(base + '/oa/leaves/new')
        await expect(page.getByText('本部门暂无已发布的请假流程', { exact: true })).toBeVisible()
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
        await page.screenshot({ path: path.join(output, 'department-employee-mobile.png'), fullPage: true })
        receipt.screenshots.push('department-employee-mobile.png')
      }
      receipt.checks.push({ user: account.username, login: true, identity: true, permission_menu: true, api_scope: true })
    } finally {
      if (loggedIn) {
        csrf = (await (await context.request.get(base + '/api/auth/csrf')).json()).data.token
        const logout = await context.request.post(base + '/api/auth/logout', { headers: { Origin: base, 'X-CSRF-Token': csrf } })
        expect(logout.status()).toBe(200)
        logoutDone = true
        if (token) expect((await context.request.get(base + '/api/auth/me', { headers: { Authorization: 'Bearer ' + token } })).status()).toBe(401)
      }
      receipt.checks.push({ user: account.username, logged_out: logoutDone })
      await context.close()
    }
  }
} catch { failure = true; receipt.failure_at_user = current }
finally {
  await browser.close()
  receipt.passed = !failure && !receipt.page_errors.length && !receipt.failed_requests.length && !receipt.business_writes.length
  await writeFile(path.join(output, 'department-roster-browser.json'), JSON.stringify(receipt, null, 2) + '\n')
}
console.log(JSON.stringify(receipt))
if (!receipt.passed) process.exitCode = 1
