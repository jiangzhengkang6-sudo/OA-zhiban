import { expect, test, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'

type Credential = { username: string; password: string }
const tokens = new WeakMap<Page, string>()

async function signIn(page: Page, employee = false) {
  page.on('response', async response => {
    if (/\/api\/auth\/(login|refresh)$/.test(response.url()) && response.ok()) {
      tokens.set(page, (await response.json()).data.access_token)
    }
  })
  const accounts = JSON.parse(readFileSync('../data/verification/m3/preview-credentials.json', 'utf8'))
  const credentials: Credential = employee ? accounts.employee : accounts
  await page.goto('/login')
  await page.getByLabel('账号', { exact: true }).fill(credentials.username)
  await page.getByLabel('密码', { exact: true }).fill(credentials.password)
  const pending = page.waitForResponse(item => item.url().endsWith('/api/auth/login') && item.request().method() === 'POST')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  const response = await pending
  expect(response.status()).toBe(200)
  tokens.set(page, (await response.json()).data.access_token)
  await expect(page).toHaveURL(employee ? /\/oa\/reimbursements$/ : /\/oa\/leaves$/)
}

async function api(page: Page, path: string) {
  const response = await page.request.get('/api/oa/' + path, { headers: { Authorization: 'Bearer ' + tokens.get(page) } })
  expect(response.status()).toBe(200)
  return (await response.json()).data
}

async function expectNoOverflow(page: Page) {
  await expect(page.locator('.el-loading-mask')).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1)
}

test('AI 关闭仍可从中文菜单进入三个正式工作台', async ({ page }, info) => {
  await signIn(page)
  for (const [path, heading] of [
    ['/oa/reimbursements', '报销工作台'],
    ['/oa/tickets', '工单工作台'],
    ['/oa/notifications', '通知与站内信'],
  ] as const) {
    await page.getByRole('menuitem', { name: heading, exact: true }).click()
    await expect(page).toHaveURL(new RegExp(path + '$'))
    await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible()
    await expectNoOverflow(page)
  }
  await page.screenshot({ path: info.outputPath('formal-oa-workbenches.png'), fullPage: true })
})

test('普通员工可创建修改报销和上传发票，未通过扫描禁止提交', async ({ page }, info) => {
  await signIn(page, true)
  await page.getByRole('button', { name: '新建报销', exact: true }).click()
  const purpose = '人工费用验收 ' + crypto.randomUUID()
  await page.getByLabel('报销事由', { exact: true }).fill(purpose)
  await page.getByRole('combobox', { name: '费用日期', exact: true }).fill('2026-10-19')
  await page.getByRole('combobox', { name: '费用日期', exact: true }).press('Tab')
  await page.getByLabel('金额（元）', { exact: true }).fill('128.50')
  const saving = page.waitForResponse(r => r.url().endsWith('/api/oa/reimbursements') && r.request().method() === 'POST')
  await page.getByRole('button', { name: '创建报销草稿', exact: true }).click()
  const saved = await saving
  expect(saved.status()).toBe(200)
  const row = (await saved.json()).data.result
  await expect(page.getByRole('heading', { name: row.business_no, exact: true })).toBeVisible()
  await page.getByLabel('报销事由', { exact: true }).fill(purpose + ' 已核对')
  const updating = page.waitForResponse(r => r.url().endsWith('/api/oa/reimbursements/' + row.id) && r.request().method() === 'PUT')
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  expect((await updating).status()).toBe(200)
  await expect(page.getByLabel('报销事由', { exact: true })).toHaveValue(purpose + ' 已核对')
  const submitting = page.waitForResponse(r => r.url().endsWith('/submit') && r.request().method() === 'POST')
  await page.getByRole('button', { name: '提交审批', exact: true }).click()
  expect((await submitting).status()).toBe(422)
  await expect(page.locator('main .el-alert')).toContainText('通过扫描的发票')
  expect((await api(page, 'reimbursements/' + row.id)).state).toBe('DRAFT')
  const uploading = page.waitForResponse(r => r.url().includes('/' + row.id + '/attachments') && r.request().method() === 'POST')
  await page.locator('input[type=file]').setInputFiles({
    name: 'invoice.png', mimeType: 'image/png',
    buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAE0lEQVR4nGP8//8/AwMDEwMYAAAkBgMBXaJOiAAAAABJRU5ErkJggg==', 'base64'),
  })
  const uploaded = await uploading
  expect(uploaded.status()).toBe(200)
  expect((await uploaded.json()).data.result.attachment.scan_status).toBe('PENDING')
  await expect(page.locator('.attachment-row')).toContainText('invoice.png')
  const pendingSubmission = page.waitForResponse(r => r.url().endsWith('/submit') && r.request().method() === 'POST')
  await page.getByRole('button', { name: '提交审批', exact: true }).click()
  expect((await pendingSubmission).status()).toBe(422)
  await expect(page.locator('main .el-alert')).toContainText('发票尚未通过安全扫描')
  expect((await api(page, 'reimbursements/' + row.id)).state).toBe('DRAFT')
  await expectNoOverflow(page)
  await page.screenshot({ path: info.outputPath('reimbursement-draft.png'), fullPage: true })
})

test('本人确认创建工单，管理员办理并读取持久化站内信', async ({ page, browser }, info) => {
  await signIn(page, true)
  await page.goto('/oa/tickets')
  await page.getByRole('button', { name: '新建工单', exact: true }).click()
  const summary = '工单办理验收 ' + crypto.randomUUID()
  const dialog = page.getByRole('dialog', { name: '新建工单', exact: true })
  await dialog.getByLabel('问题描述', { exact: true }).fill(summary)
  await dialog.getByRole('button', { name: '检查重复工单', exact: true }).click()
  await expect(dialog.getByText('已完成重复候选检查，请确认提交')).toBeVisible()
  const creating = page.waitForResponse(r => r.url().endsWith('/api/oa/tickets') && r.request().method() === 'POST')
  await dialog.getByRole('button', { name: '确认创建工单', exact: true }).click()
  const created = await creating
  expect(created.status()).toBe(200)
  const ticket = (await created.json()).data.result
  await expect(dialog).not.toBeVisible()
  await expect(page.locator('.oa-list-item').filter({ hasText: ticket.business_no })).toBeVisible()
  const manager = await browser.newPage({ baseURL: 'http://127.0.0.1:5195', viewport: page.viewportSize()! })
  try {
    await signIn(manager)
    await manager.goto('/oa/tickets')
    await manager.getByRole('button', { name: '工单处理列表', exact: true }).click()
    await manager.locator('.oa-list-item').filter({ hasText: ticket.business_no }).click()
    await expectNoOverflow(manager)
    await expect.poll(async () => (await api(manager, 'notifications')).some((n: any) => n.object_id === ticket.id), { timeout: 25_000 }).toBe(true)
    const inboxLoaded = manager.waitForResponse(r => r.url().endsWith('/api/oa/notifications') && r.request().method() === 'GET')
    await manager.goto('/oa/notifications')
    expect((await inboxLoaded).status()).toBe(200)
    const messages = await api(manager, 'notifications')
    const message = messages.find((n: any) => n.object_id === ticket.id)
    const mark = manager.waitForResponse(r => r.url().endsWith('/' + message.id + '/read') && r.request().method() === 'POST')
    await manager.locator('.notice-row').nth(messages.findIndex((n: any) => n.id === message.id)).getByRole('button', { name: '标记已读', exact: true }).click()
    expect((await mark).status()).toBe(200)
    const inboxReloaded = manager.waitForResponse(r => r.url().endsWith('/api/oa/notifications') && r.request().method() === 'GET')
    await manager.reload()
    expect((await inboxReloaded).status()).toBe(200)
    expect((await api(manager, 'notifications')).find((n: any) => n.id === message.id).read_at).toBeTruthy()
    await expectNoOverflow(manager)
    await manager.screenshot({ path: info.outputPath('notifications-read.png'), fullPage: true })
    await manager.goto('/oa/tickets')
    await manager.getByRole('button', { name: '工单处理列表', exact: true }).click()
    await manager.locator('.oa-list-item').filter({ hasText: ticket.business_no }).click()
    await manager.getByPlaceholder('填写办理说明').fill('已人工检查并恢复服务')
    const handling = manager.waitForResponse(r => r.url().includes('/' + ticket.id + '/handle') && r.request().method() === 'POST')
    await manager.getByRole('button', { name: '完成工单', exact: true }).click()
    expect((await handling).status()).toBe(200)
    expect((await api(page, 'tickets/' + ticket.id)).state).toBe('RESOLVED')
    expect((await api(manager, 'notifications')).some((n: any) => n.id === message.id)).toBe(false)
    await expectNoOverflow(manager)
  } finally { await manager.close() }
})

test('普通员工不能进入审批管理或读取投递管理接口', async ({ page }, info) => {
  await signIn(page, true)
  await expect(page.getByRole('menuitem', { name: '审批工作台', exact: true })).toHaveCount(0)
  await page.goto('/oa/approvals')
  await expect(page).toHaveURL(/\/oa\/reimbursements$/)
  await expect(page.getByRole('heading', { name: '报销工作台', exact: true })).toBeVisible()
  const response = await page.request.get('/api/oa/notifications/deliveries', { headers: { Authorization: 'Bearer ' + tokens.get(page) } })
  expect(response.status()).toBe(403)
  await expectNoOverflow(page)
  await page.screenshot({ path: info.outputPath('employee-scope.png'), fullPage: true })
})
