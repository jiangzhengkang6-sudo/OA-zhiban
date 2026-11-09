// All API traffic is fulfilled locally; this never reaches cloud services or the business DB.
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { chromium, expect } from '@playwright/test'

const output = fileURLToPath(new URL('../../output/business-acceptance-private/meeting-transcription/', import.meta.url))
await mkdir(output, { recursive: true })
const user = { user_id: 'fixture-host', display_name: '会议发起人', roles: [], depts: ['fixture'],
  permissions: ['read', 'write'].map(action => ({ resource: 'meeting', action, scope: 'self' })) }
const meeting = { id: 'fixture-meeting', title: '项目验收协调会', agenda: '核对交付进度、验收安排与后续待办。',
  starts_at: '2026-10-27T02:00:00Z', ends_at: '2026-10-27T03:00:00Z', organizer_id: user.user_id,
  host_id: user.user_id, recorder_id: user.user_id, location: '线上会议', online_url: '', state: 'IN_PROGRESS',
  revision: 3, invitation_version: 1, minutes_id: null, minutes_accessible: false, minutes_status: null,
  cancel_reason: '', video_enabled: true, available_actions: [], history: [], deliveries: [],
  attendees: [{ user_id: user.user_id, display_name: user.display_name, response: 'ACCEPTED', note: '', replied_at: null }] }
const initial = { configured: true, state: 'NOT_STARTED', notice: '仅记录开启后的已收到音频，请核对后发布纪要。',
  message: '', partial: true, expired: false, can_start: true, can_stop: false, can_retry: false,
  minutes_id: null, utterances: [], utterance_count: 0 }
let status = { ...initial }
const receipt = { checked_at: new Date().toISOString(), scope: 'mocked_api_only', checks: [], screenshots: [], errors: [],
  cloud_calls: false, business_database_writes: false }
const browser = await chromium.launch({ channel: 'msedge', headless: true })
try {
  const context = await browser.newContext()
  await context.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (!path.startsWith('/api/')) return route.continue()
    let data
    if (path === '/api/auth/config') data = { provider: 'builtin', capabilities: { ai: true, manual_oa: true } }
    else if (path === '/api/auth/csrf') data = { token: 'fixture-csrf' }
    else if (path === '/api/auth/refresh') data = { access_token: 'fixture-token', user }
    else if (path === '/api/auth/me') data = user
    else if (path === '/api/meeting-events/' + meeting.id) data = meeting
    else if (path === '/api/meeting-transcriptions/' + meeting.id) data = status
    else if (path === '/api/meeting-transcriptions/' + meeting.id + '/start') {
      expect(route.request().postDataJSON()).toMatchObject({ consent: true, expected_revision: 3 })
      status = { ...initial, state: 'ACTIVE', can_start: false, can_stop: true, message: '正在接收会议语音文本',
        utterance_count: 2, utterances: [
          { id: 'one', speaker: '会议发起人', start_ms: Date.parse('2026-10-27T02:01:00Z'), end_ms: Date.parse('2026-10-27T02:01:04Z'), text: '本周五完成验收材料核对。', late: false },
          { id: 'two', speaker: '项目记录人', start_ms: Date.parse('2026-10-27T02:02:00Z'), end_ms: Date.parse('2026-10-27T02:02:04Z'), text: '补充待办：下周一提交复核结果。', late: true },
        ] }
      data = { result: meeting, replayed: false }
    } else throw new Error('Unexpected mocked API request: ' + path)
    await route.fulfill({ json: { code: '0', message: '', data } })
  })
  const page = await context.newPage()
  page.on('pageerror', error => receipt.errors.push(error.message))
  for (const mobile of [false, true]) {
    status = { ...initial }
    const size = mobile ? 'mobile' : 'desktop'
    await page.setViewportSize(mobile ? { width: 390, height: 844 } : { width: 1440, height: 960 })
    await page.goto('http://127.0.0.1:5182/meeting-events/' + meeting.id)
    const section = page.getByRole('region', { name: '会议转写', exact: true })
    await expect(section).toBeVisible()
    await expect(section.getByRole('button', { name: '开启转写', exact: true })).toBeDisabled()
    await section.locator('.el-checkbox').click()
    await expect(section.getByRole('checkbox')).toBeChecked()
    await section.getByRole('button', { name: '开启转写', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '开启会议转写' })
    await expect(dialog).toContainText('转写可能产生费用')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await page.screenshot({ path: output + size + '-consent.png', fullPage: true, animations: 'disabled' })
    receipt.screenshots.push(size + '-consent.png')
    await dialog.getByRole('button', { name: '确认开启', exact: true }).click()
    await expect(dialog).toBeHidden()
    await expect(section).toContainText('本场会议已开启语音记录')
    await expect(section).toContainText('本周五完成验收材料核对')
    await expect(section).toContainText('未纳入当前纪要')
    await section.scrollIntoViewIfNeeded()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    const boxes = await section.locator('button').evaluateAll(buttons => buttons.map(button => {
      const rect = button.getBoundingClientRect()
      return { left: rect.left, right: rect.right, width: rect.width, text: button.innerText }
    }))
    expect(boxes.every(box => box.left >= 0 && box.right <= (mobile ? 390 : 1440))).toBe(true)
    await page.screenshot({ path: output + size + '-active.png', fullPage: true, animations: 'disabled' })
    receipt.screenshots.push(size + '-active.png')
    receipt.checks.push({ name: size + ' consent, notice, speaker text, late label, no horizontal overflow', passed: true })
  }
  expect(receipt.errors).toEqual([])
  receipt.passed = true
} finally {
  await browser.close()
  await writeFile(output + 'browser-receipt.json', JSON.stringify(receipt, null, 2))
}
console.log(JSON.stringify(receipt))
