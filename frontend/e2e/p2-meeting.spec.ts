import { expect, test, type Page } from '@playwright/test'

const segment = { segment_id: 's1', ordinal: 1, start_offset: 0, end_offset: 18, text: '议题：验收。决定：通过。待办：归档。', locator: 'chars:0-18', text_hash: 'a'.repeat(64), summary: '验收' }
const draft = { summary: '验收纪要', topics: ['验收'], source_refs: ['s1'], decisions: [{ text: '通过', source_refs: ['s1'], confidence: 'explicit' }],
  action_items: [{ title: '归档', assignee_candidate: null, due_at_candidate: null, priority: 'medium', source_refs: ['s1'], needs_confirmation: true }] }

async function serveMeeting(page: Page, options: { loseFirstCreate?: boolean; initialPaused?: boolean; loseFirstRetry?: boolean } = {}) {
  let current: any = options.initialPaused ? { meeting_id: 'MTG-E2E-1', thread_id: 'thread-1', title: '暂停的会议', status: 'PAUSED', version: null,
    segments: [segment], draft: null, available_actions: ['retry'], trace_id: 'trace-1', external_writes: false } : null
  let revoked = false
  const createKeys: string[] = [], retryKeys: string[] = [], externalWrites: string[] = [], auditQueries: string[] = []
  const retryResults = new Map<string, any>()
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname, method = request.method()
    const body = request.postDataJSON?.() || {}
    const respond = (data: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ code: status === 200 ? '0' : '404', message: status === 200 ? 'ok' : '会议不存在或无权限', data }) })
    if (path === '/api/meetings' && method === 'GET') return respond({ items: current ? [current] : [], total: current ? 1 : 0, page: 1, page_size: 20 })
    if (path === '/api/meetings' && method === 'POST') {
      createKeys.push(body.idempotency_key)
      if (!current) current = { meeting_id: 'MTG-E2E-1', thread_id: 'thread-1', title: body.title, status: 'CREATED', version: null, segments: [], draft: null, available_actions: ['generate'], trace_id: 'trace-1', external_writes: false }
      if (options.loseFirstCreate && createKeys.length === 1) return route.abort('failed')
      return respond(current)
    }
    if (path === '/api/meetings/MTG-E2E-1' && method === 'GET') return respond(current, current ? 200 : 404)
    if (path === '/api/meetings/MTG-E2E-1/generate' && method === 'POST') {
      current = { ...current, status: 'DRAFT_READY', version: 1, segments: [segment], draft, available_actions: ['edit', 'confirm', 'reject', 'regenerate'] }
      return respond(current)
    }
    if (path === '/api/meetings/MTG-E2E-1/draft' && method === 'PATCH') {
      if (revoked) return respond(null, 403)
      current = { ...current, status: 'REVIEWING', version: 2, draft: body.draft }
      return respond(current)
    }
    if (path === '/api/meetings/MTG-E2E-1/decisions' && method === 'POST') {
      current = { ...current, status: body.action === 'confirm' ? 'CONFIRMED' : 'REJECTED', available_actions: [] }
      return respond(current)
    }
    if (path === '/api/meetings/MTG-E2E-1/retry' && method === 'POST') {
      retryKeys.push(body.idempotency_key)
      if (retryResults.has(body.idempotency_key)) return respond(retryResults.get(body.idempotency_key))
      if (options.loseFirstRetry && retryKeys.length === 1) {
        current = { ...current, status: 'PAUSED', available_actions: ['retry'] }
        retryResults.set(body.idempotency_key, current)
        return route.abort('failed')
      }
      current = { ...current, status: 'DRAFT_READY', version: 1, segments: [segment], draft, available_actions: ['edit', 'confirm', 'reject', 'regenerate'] }
      retryResults.set(body.idempotency_key, current)
      return respond(current)
    }
    if (path === '/api/audit/events' && method === 'GET') {
      auditQueries.push(url.searchParams.get('business_id') || '')
      return respond({ items: [{ id: 1, action: 'meeting_created', business_id: 'MTG-E2E-1', thread_id: 'thread-1', actor_id: 'u_emp_001', trace_id: 'trace-1', result: 'success', created_at: '2026-10-14T00:00:00Z' }], total: 1, page: 1, page_size: 20 })
    }
    if (method !== 'GET') externalWrites.push(path)
    return respond(null, 404)
  })
  return { createKeys, retryKeys, externalWrites, auditQueries, revoke: () => { revoked = true }, getMeeting: () => current }
}

test.beforeEach(async ({ page }) => { await page.addInitScript(() => localStorage.setItem('oa_current_user', 'u_emp_001')) })

test('employee edits and confirms a sourced draft, then recovers it after reload', async ({ page }) => {
  const server = await serveMeeting(page)
  await page.goto('/meetings')
  await page.getByRole('textbox', { name: '会议标题' }).fill('验收会')
  await page.getByRole('textbox', { name: '会议文本' }).fill(segment.text)
  await page.getByTestId('create-meeting').click()
  await expect(page).toHaveURL(/\/meetings\/MTG-E2E-1$/)
  await page.getByRole('button', { name: '生成草稿' }).click()
  await expect(page.getByRole('textbox', { name: '纪要摘要' })).toHaveValue('验收纪要')
  await expect(page.getByText('来源 1').first()).toBeVisible()
  await page.getByRole('textbox', { name: '纪要摘要' }).fill('人工修订的纪要')
  await page.getByTestId('save-meeting').click()
  await expect(page.getByText('草稿 v2')).toBeVisible()
  await page.getByTestId('confirm-meeting').click()
  await page.getByRole('dialog', { name: '确认草稿' }).getByRole('button', { name: 'OK' }).click()
  await expect(page.getByText('已确认', { exact: false }).first()).toBeVisible()
  await page.reload()
  await expect(page.getByRole('textbox', { name: '纪要摘要' })).toHaveValue('人工修订的纪要')
  expect(server.getMeeting().status).toBe('CONFIRMED')
  expect(server.externalWrites).toEqual([])
  await expect(page.getByText('查看审计轨迹')).toHaveCount(0)
})

test('a lost create response reuses its key after page reload', async ({ page }) => {
  const server = await serveMeeting(page, { loseFirstCreate: true })
  await page.goto('/meetings')
  await page.getByRole('textbox', { name: '会议标题' }).fill('验收会')
  await page.getByRole('textbox', { name: '会议文本' }).fill(segment.text)
  await page.getByTestId('create-meeting').click()
  await expect(page.locator('main').getByRole('alert')).toContainText('Network Error')
  await page.reload()
  await page.getByRole('textbox', { name: '会议标题' }).fill('验收会')
  await page.getByRole('textbox', { name: '会议文本' }).fill(segment.text)
  await page.getByTestId('create-meeting').click()
  await expect(page).toHaveURL(/\/meetings\/MTG-E2E-1$/)
  expect(server.createKeys).toHaveLength(2)
  expect(server.createKeys[1]).toBe(server.createKeys[0])
  expect(server.getMeeting().meeting_id).toBe('MTG-E2E-1')
})

test('unavailable meeting details do not turn into a create form', async ({ page }) => {
  await serveMeeting(page)
  await page.goto('/meetings/MTG-E2E-1')
  await expect(page.getByText('会议不存在或无权限').first()).toBeVisible()
  await expect(page.getByTestId('create-meeting')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '重新加载' })).toBeVisible()
})

test('employee rejects with a reason without external writes', async ({ page }) => {
  const server = await serveMeeting(page)
  await page.goto('/meetings')
  await page.getByRole('textbox', { name: '会议标题' }).fill('验收会')
  await page.getByRole('textbox', { name: '会议文本' }).fill(segment.text)
  await page.getByTestId('create-meeting').click()
  await page.getByRole('button', { name: '生成草稿' }).click()
  await page.getByRole('button', { name: '拒绝', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '拒绝会议草稿' })
  await dialog.getByRole('textbox').fill('纪要信息不完整')
  await dialog.getByRole('button', { name: 'OK' }).click()
  await expect(page.getByText('已拒绝', { exact: false }).first()).toBeVisible()
  expect(server.getMeeting().status).toBe('REJECTED')
  expect(server.externalWrites).toEqual([])
})

test('paused meeting retries with the same key after a lost response and reload', async ({ page }) => {
  const server = await serveMeeting(page, { initialPaused: true, loseFirstRetry: true })
  await page.goto('/meetings/MTG-E2E-1')
  await expect(page.getByText('生成已暂停')).toBeVisible()
  await page.getByTestId('retry-meeting').click()
  await expect(page.locator('main').getByRole('alert')).toContainText('Network Error')
  await page.reload()
  const replay = page.waitForResponse(response => response.url().endsWith('/retry') && response.status() === 200)
  await page.getByTestId('retry-meeting').click()
  await replay
  await expect(page.getByText('生成已暂停')).toBeVisible()
  expect(server.retryKeys).toHaveLength(2)
  expect(server.retryKeys[1]).toBe(server.retryKeys[0])
  await expect(page.getByTestId('retry-meeting')).toBeEnabled()
  await page.getByTestId('retry-meeting').click()
  await expect(page.getByRole('textbox', { name: '纪要摘要' })).toHaveValue('验收纪要')
  expect(server.retryKeys).toHaveLength(3)
  expect(server.retryKeys[2]).not.toBe(server.retryKeys[1])
  expect(server.externalWrites).toEqual([])
})

test('revoked access prevents saving an edited draft', async ({ page }) => {
  const server = await serveMeeting(page)
  await page.goto('/meetings')
  await page.getByRole('textbox', { name: '会议标题' }).fill('验收会')
  await page.getByRole('textbox', { name: '会议文本' }).fill(segment.text)
  await page.getByTestId('create-meeting').click()
  await page.getByRole('button', { name: '生成草稿' }).click()
  await page.getByRole('textbox', { name: '纪要摘要' }).fill('无权提交的编辑')
  server.revoke()
  await page.getByTestId('save-meeting').click()
  await expect(page.locator('main').getByRole('alert')).toContainText('会议不存在或无权限')
  expect(server.getMeeting().version).toBe(1)
  await expect(page.getByTestId('confirm-meeting')).toBeDisabled()
})

test('admin opens the meeting audit trail with its business id', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('oa_current_user', 'u_admin_001'))
  const server = await serveMeeting(page, { initialPaused: true })
  await page.goto('/meetings/MTG-E2E-1')
  await page.getByRole('button', { name: '查看审计轨迹' }).click()
  await expect(page).toHaveURL(/\/audit\?business_id=MTG-E2E-1/)
  await expect(page.getByRole('textbox', { name: '业务号' })).toHaveValue('MTG-E2E-1')
  await expect(page.locator('.el-table__body').getByText('会议创建')).toBeVisible()
  expect(server.auditQueries).toEqual(['MTG-E2E-1'])
})
