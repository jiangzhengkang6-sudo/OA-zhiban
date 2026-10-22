import { expect, test, type Page, type Route } from '@playwright/test'

// These browser checks isolate UI behavior; PostgreSQL integration has its own suite.
const user = {
  user_id: 'assistant-browser-user', display_name: '测试申请人', roles: [], depts: ['department-1'],
  permissions: ['thread', 'leave', 'ticket'].flatMap(resource =>
    ['read', 'write'].map(action => ({ resource, action, scope: 'self' }))),
}
const leave = () => ({
  thread_id: 'leave-thread', scene: 'leave', business_id: 'leave-1', status: 'WAITING_HUMAN',
  current_interrupt_id: 'leave-interrupt', messages: [], approval_status: 'DRAFT', error: null,
  form_snapshot: { business_no: 'LV-20261019-001', leave_type: 'annual', start_date: '2026-10-20',
    end_date: '2026-10-21', reason: '家庭事务，请审核这份申请。', revision: 1 },
})
async function fulfill(route: Route, data: unknown, status = 200, message = 'ok') {
  await route.fulfill({ status, json: { code: status === 200 ? '0' : '409', message, data } })
}
async function setup(page: Page, detail: () => unknown, resume: (route: Route) => Promise<void>) {
  const unexpected: string[] = []
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/auth/config') return fulfill(route, { provider: 'builtin', capabilities: { ai: true, manual_oa: true } })
    if (path === '/api/auth/csrf') return fulfill(route, { token: 'ui-test-csrf' })
    if (path === '/api/auth/refresh') return fulfill(route, { access_token: 'ui-test-token', user })
    if (path === '/api/auth/me') return fulfill(route, user)
    if (path.startsWith('/api/agent/threads/')) return fulfill(route, detail())
    if (path.startsWith('/api/agent/interrupts/') && path.endsWith('/resume')) return resume(route)
    unexpected.push(path)
    return fulfill(route, null, 404, 'Unexpected browser fixture request')
  })
  return unexpected
}
async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(1)
}

test('正式请假确认展示中文内容并防止重复提交', async ({ page }, info) => {
  let detail: Record<string, unknown> = leave()
  const decisions: unknown[] = []
  const unexpected = await setup(page, () => detail, async route => {
    decisions.push(route.request().postDataJSON())
    await new Promise(resolve => setTimeout(resolve, 250))
    detail = { ...detail, status: 'COMPLETED', current_interrupt_id: null, approval_status: 'IN_REVIEW' }
    await fulfill(route, { status: 'COMPLETED', trace_id: 'browser' })
  })
  await page.goto('/assistant/leave-thread')
  await expect(page.locator('.leave-review')).toContainText('年假')
  await expect(page.locator('.leave-review')).toContainText('2026-10-20 至 2026-10-21')
  await expect(page.getByRole('button', { name: '发送', exact: true })).toBeDisabled()
  const confirm = page.getByRole('button', { name: '确认提交请假', exact: true })
  await expect(confirm).toBeVisible()
  await noOverflow(page)
  await page.screenshot({ path: info.outputPath('leave-review.png'), fullPage: true })
  await confirm.evaluate(element => { (element as HTMLButtonElement).click(); (element as HTMLButtonElement).click() })
  await expect(page.locator('.leave-review')).toContainText('审批中')
  await expect(confirm).toHaveCount(0)
  expect(decisions).toHaveLength(1)
  expect(decisions[0]).toMatchObject({ action: 'confirm' })
  await page.reload()
  await expect(page.locator('.leave-review')).toContainText('审批中')
  await expect(confirm).toHaveCount(0)
  expect(decisions).toHaveLength(1)
  expect(unexpected).toEqual([])
})

test('正式请假冲突保留错误并允许重试同一决定', async ({ page }, info) => {
  let detail: Record<string, unknown> = leave()
  const decisions: unknown[] = []
  const unexpected = await setup(page, () => detail, async route => {
    decisions.push(route.request().postDataJSON())
    if (decisions.length === 1) return fulfill(route, null, 409, '审批路线已变化，请刷新审核内容后再提交')
    detail = { ...detail, status: 'COMPLETED', current_interrupt_id: null, approval_status: 'IN_REVIEW' }
    return fulfill(route, { status: 'COMPLETED', trace_id: 'browser' })
  })
  await page.goto('/assistant/leave-thread')
  await page.getByRole('button', { name: '确认提交请假', exact: true }).click()
  await expect(page.locator('main .el-alert').filter({ hasText: '审批路线已变化' })).toBeVisible()
  await expect(page.getByRole('button', { name: '刷新审核内容', exact: true })).toBeEnabled()
  await noOverflow(page)
  await page.screenshot({ path: info.outputPath('leave-conflict.png'), fullPage: true })
  await page.getByRole('button', { name: '确认提交请假', exact: true }).click()
  await expect(page.locator('.leave-review')).toContainText('审批中')
  expect(decisions).toHaveLength(2)
  expect(decisions[0]).toEqual(decisions[1])
  expect(unexpected).toEqual([])
})

test('正式请假恢复仅发送对账且保留已提交的申请', async ({ page }, info) => {
  let detail: Record<string, unknown> = { ...leave(), approval_status: 'IN_REVIEW',
    error: { code: 'GRAPH_RECOVERY', msg: '业务决定已保存，请恢复处理' } }
  const decisions: unknown[] = []
  const unexpected = await setup(page, () => detail, async route => {
    decisions.push(route.request().postDataJSON())
    detail = { ...detail, status: 'COMPLETED', current_interrupt_id: null, error: null }
    return fulfill(route, { status: 'COMPLETED', trace_id: 'browser' })
  })
  await page.goto('/assistant/leave-thread')
  await expect(page.getByRole('button', { name: '确认提交请假', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '恢复处理', exact: true })).toBeVisible()
  await expect(page.locator('.leave-review')).toContainText('审批中')
  await noOverflow(page)
  await page.screenshot({ path: info.outputPath('leave-recovery.png'), fullPage: true })
  await page.getByRole('button', { name: '恢复处理', exact: true }).click()
  await expect(page.getByRole('button', { name: '恢复处理', exact: true })).toHaveCount(0)
  expect(decisions).toEqual([{ action: 'reconcile' }])
  await expect(page.locator('.leave-review')).toContainText('审批中')
  await expect(page.getByRole('button', { name: '发送', exact: true })).toBeDisabled()
  expect(unexpected).toEqual([])
})

const ticket = () => ({
  thread_id: 'ticket-thread', scene: 'ticket', status: 'WAITING_HUMAN', current_interrupt_id: 'ticket-interrupt',
  messages: [], ticket_draft: { thread_id: 'ticket-thread', status: 'PENDING',
    fields: { category: '系统故障', priority: 'medium', summary: '办公系统无法登录，需要维修处理并核对权限设置' } },
  ticket_candidates: [{ id: 'existing-1', revision: 3, summary: '办公系统无法登录，需要维修处理并核对权限设置',
    state: 'OPEN', score: 1, reason: '摘要完全一致' }],
  ticket_review: { mode: 'new', expired: false, changed: false },
})

test('正式工单选择合并后使用新的确认且避免重复提交', async ({ page }, info) => {
  let detail: Record<string, unknown> = ticket()
  const decisions: unknown[] = []
  const unexpected = await setup(page, () => detail, async route => {
    const request = route.request().postDataJSON()
    decisions.push({ endpoint: new URL(route.request().url()).pathname, ...request })
    await new Promise(resolve => setTimeout(resolve, 200))
    if (request.action === 'edit') detail = { ...detail, current_interrupt_id: 'merge-interrupt',
      ticket_review: { mode: 'merge', target_ticket_id: 'existing-1', expected_revision: 3,
        business_no: 'TK-001', summary: ticket().ticket_candidates[0].summary, expired: false, changed: false } }
    else detail = { ...detail, current_interrupt_id: null, ticket: { ticket_id: 'existing-1', business_no: 'TK-001', merged: true } }
    await fulfill(route, { status: 'WAITING_HUMAN', trace_id: 'browser' })
  })
  await page.goto('/assistant/ticket-thread')
  const candidate = page.locator('input[type="radio"][value="existing-1"]')
  await page.locator('.ticket-choices .el-radio').filter({ has: candidate }).click()
  await expect(candidate).toBeChecked()
  const confirm = page.getByRole('button', { name: '确认合并工单', exact: true })
  await expect(confirm).toBeEnabled()
  await expect(page.locator('.ticket-review')).toContainText('合并目标：TK-001')
  await noOverflow(page)
  await page.screenshot({ path: info.outputPath('ticket-merge-review.png'), fullPage: true })
  await confirm.evaluate(element => { (element as HTMLButtonElement).click(); (element as HTMLButtonElement).click() })
  await expect(page.getByText('已合并到工单', { exact: false })).toBeVisible()
  expect(decisions).toHaveLength(2)
  expect(decisions[0]).toMatchObject({ endpoint: '/api/agent/interrupts/ticket-interrupt/resume', action: 'edit',
    edited_data: { merge_ticket_id: 'existing-1', expected_revision: 3 } })
  expect(decisions[1]).toMatchObject({ endpoint: '/api/agent/interrupts/merge-interrupt/resume', action: 'confirm' })
  await page.reload()
  await expect(page.getByText('已合并到工单', { exact: false })).toBeVisible()
  expect(decisions).toHaveLength(2)
  expect(unexpected).toEqual([])
})

test('正式工单冲突后重新核对过期内容再提交', async ({ page }, info) => {
  let detail: Record<string, unknown> = ticket()
  const decisions: unknown[] = []
  const unexpected = await setup(page, () => detail, async route => {
    const request = route.request().postDataJSON()
    decisions.push(request)
    if (decisions.length === 1) return fulfill(route, null, 409, '工单内容已变化，请重新核对')
    if (request.action === 'edit') detail = { ...ticket(), current_interrupt_id: 'refreshed-interrupt' }
    else detail = { ...detail, current_interrupt_id: null, ticket: { ticket_id: 'new-1', business_no: 'TK-002', merged: false } }
    await fulfill(route, { status: 'WAITING_HUMAN', trace_id: 'browser' })
  })
  await page.goto('/assistant/ticket-thread')
  await page.getByRole('button', { name: '确认创建工单', exact: true }).click()
  await expect(page.locator('main .el-alert').filter({ hasText: '工单内容已变化' })).toBeVisible()
  detail = { ...detail, ticket_review: { mode: 'new', changed: false, expired: true } }
  await page.reload()
  await expect(page.getByRole('button', { name: '确认创建工单', exact: true })).toBeDisabled()
  await noOverflow(page)
  await page.screenshot({ path: info.outputPath('ticket-expired-review.png'), fullPage: true })
  await page.getByRole('button', { name: '重新核对工单', exact: true }).click()
  await expect(page.getByRole('button', { name: '确认创建工单', exact: true })).toBeEnabled()
  expect(decisions[1]).toMatchObject({ action: 'edit', edited_data: {} })
  await page.getByRole('button', { name: '确认创建工单', exact: true }).click()
  await expect(page.getByText('工单已创建', { exact: false })).toBeVisible()
  expect(decisions).toHaveLength(3)
  expect(unexpected).toEqual([])
})

test('正式工单恢复只对账并保留合并结果', async ({ page }, info) => {
  let detail: Record<string, unknown> = { ...ticket(), ticket_draft: { ...ticket().ticket_draft, status: 'CONFIRMED' },
    ticket: { ticket_id: 'existing-1', business_no: 'TK-001', merged: true },
    error: { code: 'GRAPH_RECOVERY', msg: '业务决定已保存，请恢复处理' } }
  const decisions: unknown[] = []
  const unexpected = await setup(page, () => detail, async route => {
    decisions.push(route.request().postDataJSON())
    detail = { ...detail, current_interrupt_id: null, error: null }
    await fulfill(route, { status: 'WAITING_HUMAN', trace_id: 'browser' })
  })
  await page.goto('/assistant/ticket-thread')
  await expect(page.getByRole('button', { name: '确认合并工单', exact: true })).toHaveCount(0)
  await noOverflow(page)
  await page.screenshot({ path: info.outputPath('ticket-merge-recovery.png'), fullPage: true })
  await page.getByRole('button', { name: '恢复处理', exact: true }).click()
  await expect(page.getByRole('button', { name: '恢复处理', exact: true })).toHaveCount(0)
  await expect(page.getByText('已合并到工单', { exact: false })).toBeVisible()
  expect(decisions).toEqual([{ action: 'reconcile' }])
  expect(unexpected).toEqual([])
})
