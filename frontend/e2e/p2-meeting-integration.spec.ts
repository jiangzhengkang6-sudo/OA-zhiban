import { expect, test } from '@playwright/test'

test('real API creates, generates, edits and confirms a meeting across reload', async ({ page }) => {
  const unique = `P2-integration-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  const title = `会议 ${unique}`
  const content = `议题：${unique} 验收。决定：通过本地联调。待办：整理测试记录。`
  const summary = `人工核对 ${unique} 的纪要`
  const requests: string[] = []
  page.on('request', request => {
    if (new URL(request.url()).pathname.startsWith('/api/')) requests.push(`${request.method()} ${new URL(request.url()).pathname}`)
  })
  await page.addInitScript(() => localStorage.setItem('oa_current_user', 'u_emp_001'))

  await page.goto('/meetings')
  await page.getByRole('textbox', { name: '会议标题' }).fill(title)
  await page.getByRole('textbox', { name: '会议文本' }).fill(content)
  const created = page.waitForResponse(response => response.url().endsWith('/api/meetings') && response.request().method() === 'POST')
  await page.getByTestId('create-meeting').click()
  expect((await created).status()).toBe(200)
  await expect(page).toHaveURL(/\/meetings\/[\w-]+$/)

  const generated = page.waitForResponse(response => response.url().endsWith('/generate') && response.request().method() === 'POST')
  await page.getByRole('button', { name: '生成草稿' }).click()
  expect((await generated).status()).toBe(200)
  await expect(page.getByRole('textbox', { name: '纪要摘要' })).not.toBeEmpty()
  await expect(page.locator('[id^="source-"]')).not.toHaveCount(0)
  await expect(page.locator('.draft-editor .refs a').first()).toHaveAttribute('href', /^#source-/)

  await page.getByRole('textbox', { name: '纪要摘要' }).fill(summary)
  const saved = page.waitForResponse(response => response.url().endsWith('/draft') && response.request().method() === 'PATCH')
  await page.getByTestId('save-meeting').click()
  expect((await saved).status()).toBe(200)
  await expect(page.getByText('草稿 v2')).toBeVisible()

  const confirmed = page.waitForResponse(response => response.url().endsWith('/decisions') && response.request().method() === 'POST')
  await page.getByTestId('confirm-meeting').click()
  await page.getByRole('dialog', { name: '确认草稿' }).getByRole('button', { name: 'OK' }).click()
  const response = await confirmed
  expect(response.status()).toBe(200)
  expect((await response.json()).data).toMatchObject({ status: 'CONFIRMED', version: 2, external_writes: false })
  await page.reload()
  await expect(page.getByRole('textbox', { name: '纪要摘要' })).toHaveValue(summary)
  await expect(page.getByText('已确认', { exact: false }).first()).toBeVisible()
  expect(requests).toContain('POST /api/meetings')
  expect(requests.some(request => request.includes('/api/tasks') || request.includes('/api/calendar') || request.includes('/api/mail'))).toBe(false)
})
