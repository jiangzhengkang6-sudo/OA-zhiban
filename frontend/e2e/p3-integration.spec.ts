import { expect, test, type Page } from '@playwright/test'

const auth = { Authorization: 'Bearer mock:u_emp_001' }

async function fits(page: Page) {
  await expect(page.locator('.el-skeleton')).toHaveCount(0)
  await expect(page.locator('.el-button.is-loading')).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  await expect(page.locator('.draft-workbench h1')).not.toBeEmpty()
  await page.evaluate(() => {
    window.scrollTo(0, 0)
    document.querySelector('.app-main')?.scrollTo(0, 0)
  })
  await expect(page.locator('.draft-workbench h1')).toBeInViewport()
}
async function saved(page: Page, path: string, action: () => Promise<unknown>) {
  const response = page.waitForResponse(r => new URL(r.url()).pathname.endsWith(path) && ['POST', 'PATCH'].includes(r.request().method()))
  await action()
  expect((await response).status()).toBe(200)
}
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => { if (!localStorage.getItem('oa_current_user')) localStorage.setItem('oa_current_user', 'u_emp_001') })
})

test('business task extracts and manually assigns before completion and archival', async ({ page, request }, info) => {
  const api = 'http://127.0.0.1:8012/api'
  const created = await request.post(api + '/meetings', { headers: auth, data: {
    title: `P3 task source ${Date.now()}-${info.project.name}`,
    content: '议题：P3 验收。决定：保留人工确认。待办：整理验收资料。',
    idempotency_key: `p3-source-${Date.now()}-${info.project.name}`,
  } })
  expect(created.status()).toBe(200)
  const source = (await created.json()).data.meeting_id
  const generated = await request.post(api + `/meetings/${source}/generate`, { headers: auth, data: {
    idempotency_key: `generate-${source}`,
  } })
  expect(generated.status()).toBe(200)
  const meeting = (await generated.json()).data
  const confirmed = await request.post(api + `/meetings/${source}/decisions`, {
    headers: auth, data: { action: 'confirm', expected_version: meeting.version, idempotency_key: `confirm-${source}` },
  })
  expect(confirmed.status()).toBe(200)
  expect((await confirmed.json()).data.status).toBe('CONFIRMED')
  expect(source).toEqual(expect.any(String))
  await page.goto('/work-tasks')
  const sourceType = page.getByRole('combobox', { name: '来源类型', exact: true })
  await sourceType.focus()
  await sourceType.press('Enter')
  await page.getByRole('option', { name: '已确认会议', exact: true }).click()
  await page.getByRole('textbox', { name: '来源编号' }).fill(source)
  await saved(page, '/api/work-tasks/batches', () => page.getByTestId('create-task-batch').click())
  await expect(page).toHaveURL(/\/work-tasks\/WTB-/)
  await saved(page, '/extract', () => page.getByRole('button', { name: '提取候选', exact: true }).click())
  await page.getByRole('textbox', { name: '候选负责人 1' }).fill('u_emp_001')
  await page.getByRole('combobox', { name: '候选截止时间 1' }).fill('2026-10-21 18:00:00')
  await page.getByRole('combobox', { name: '候选截止时间 1' }).press('Tab')
  await saved(page, '/draft', () => page.getByTestId('save-candidates').click())
  await page.getByTestId('metadata-confirmed').check()
  await page.getByTestId('risk-acknowledged').check()
  await fits(page)
  await page.screenshot({ path: info.outputPath('work-task-candidates.png'), fullPage: true })
  await saved(page, '/decisions', () => page.getByTestId('confirm-tasks').click())
  await expect(page.getByRole('button', { name: '任务列表', exact: true })).toBeEnabled()
  await page.getByRole('link', { name: /^WT-/ }).first().click()
  await expect(page).toHaveURL(/\/work-tasks\/WT-/)
  await saved(page, '/commands', () => page.getByRole('button', { name: '开始任务', exact: true }).click())
  await page.getByRole('textbox', { name: '处理备注' }).fill('验收资料已经整理。')
  await saved(page, '/commands', () => page.getByRole('button', { name: '完成任务', exact: true }).click())
  await saved(page, '/commands', () => page.getByRole('button', { name: '归档任务', exact: true }).click())
  await page.reload()
  await expect(page.locator('.heading')).toContainText('已归档')
  await fits(page)
  await page.screenshot({ path: info.outputPath('work-task-archived.png'), fullPage: true })
})

test('report approves plan, shows actual chart, saves and publishes immutable record', async ({ page }, info) => {
  await page.goto('/reports')
  await page.getByRole('textbox', { name: '报告标题' }).fill(`统计验收 ${Date.now()}`)
  await page.getByRole('combobox', { name: '报表开始日期' }).fill('2026-10-01')
  await page.getByRole('combobox', { name: '报表开始日期' }).press('Tab')
  await page.getByRole('combobox', { name: '报表结束日期' }).fill('2026-10-15')
  await page.getByRole('combobox', { name: '报表结束日期' }).press('Tab')
  await saved(page, '/api/reports', () => page.getByTestId('create-report').click())
  await expect(page).toHaveURL(/\/reports\/RPT-/)
  await expect(page.getByTestId('approve-report-plan')).toBeDisabled()
  await page.getByTestId('plan-confirmed').check()
  await saved(page, '/approve-plan', () => page.getByTestId('approve-report-plan').click())
  const editor = page.getByRole('textbox', { name: '报表摘要' })
  await expect(editor).not.toBeEmpty()
  await editor.fill('统计结果已核对，原因候选仍待人工核查。')
  await expect(page.getByTestId('publish-report')).toBeDisabled()
  await saved(page, '/draft', () => page.getByTestId('save-report').click())
  await page.getByTestId('definitions-confirmed').check()
  await page.getByTestId('causes-confirmed').check()
  await fits(page)
  await page.screenshot({ path: info.outputPath('report-review.png'), fullPage: true })
  const chart = page.locator('.chart-scroll').first()
  await expect(chart).toBeVisible()
  expect(await chart.locator('.bar').evaluateAll(bars => bars.some(bar => bar.getBoundingClientRect().height > 0))).toBe(true)
  const labelGaps = await chart.locator('.bar-column > small').evaluateAll(labels => {
    const boxes = labels.map(label => label.getBoundingClientRect())
    return boxes.slice(1).map((box, index) => box.left - boxes[index].right)
  })
  expect(labelGaps.every(gap => gap >= 2)).toBe(true)
  if (info.project.name === 'mobile') {
    await chart.scrollIntoViewIfNeeded()
    const position = await chart.evaluate(element => {
      element.scrollLeft = element.scrollWidth
      return { left: element.scrollLeft, width: element.clientWidth, total: element.scrollWidth }
    })
    expect(position.total).toBeGreaterThan(position.width)
    expect(position.left).toBeGreaterThan(0)
    await expect(chart.locator('.bar-column').last()).toBeInViewport()
    await chart.screenshot({ path: info.outputPath('report-chart-scrolled.png') })
  }
  await saved(page, '/publish', async () => {
    await page.getByTestId('publish-report').click()
    await page.getByRole('dialog', { name: '发布报表', exact: true }).getByRole('button', { name: 'OK', exact: true }).click()
  })
  await page.reload()
  await expect(page.locator('.heading')).toContainText('已发布')
  await expect(editor).toBeDisabled()
})

test('private contract reviews, saves, compares and designated reviewer decides', async ({ page }, info) => {
  await page.goto('/contracts')
  await page.getByRole('textbox', { name: '合同名称' }).fill(`合同验收 ${Date.now()}`)
  await page.getByRole('textbox', { name: '合同原文' }).fill('付款条款：30日付款。\n违约责任：赔偿。\n终止条款：提前通知。\n争议解决：法院。')
  await saved(page, '/api/contracts', () => page.getByTestId('create-contract').click())
  await expect(page).toHaveURL(/\/contracts\/CON-/)
  await saved(page, '/commands', () => page.getByRole('button', { name: '开始审查', exact: true }).click())
  const editor = page.getByRole('textbox', { name: '审查摘要' })
  await editor.fill('人工核对条款，保留内部审查意见。')
  await saved(page, '/commands', () => page.getByTestId('save-contract').click())
  await page.getByRole('combobox', { name: '历史审查版本' }).focus()
  await page.getByRole('combobox', { name: '历史审查版本' }).press('Enter')
  await page.getByRole('option', { name: /^v1/ }).click()
  await expect(page.locator('.history-summary')).not.toHaveText(await editor.inputValue())
  await fits(page)
  await page.screenshot({ path: info.outputPath('contract-review.png'), fullPage: true })
  const url = page.url()
  await page.evaluate(() => localStorage.setItem('oa_current_user', 'u_mgr_001'))
  await page.goto(url)
  await expect(editor).toBeDisabled()
  await expect(page.getByTestId('confirm-contract')).toBeDisabled()
  for (const id of ['payment', 'breach', 'termination', 'dispute']) {
    await page.getByRole('textbox', { name: '处理意见 ' + id }).fill('已人工核对原文和建议。')
  }
  await page.getByRole('textbox', { name: '最终复核意见' }).fill('内部审查完成。')
  await saved(page, '/commands', () => page.getByTestId('confirm-contract').click())
  await page.reload()
  await expect(page.locator('.heading')).toContainText('已确认')
  await expect(page.getByTestId('confirm-contract')).toHaveCount(0)
  await fits(page)
  await page.screenshot({ path: info.outputPath('contract-confirmed.png'), fullPage: true })
})
