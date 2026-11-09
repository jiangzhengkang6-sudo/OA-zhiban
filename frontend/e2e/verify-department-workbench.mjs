// Local, self-only acceptance; no outbound delivery or synthetic participants.
import { execFileSync } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'

const root = fileURLToPath(new URL('../../', import.meta.url))
const backend = path.join(root, 'backend')
const python = path.join(backend, '.venv/Scripts/python.exe')
const output = path.join(root, 'output/business-acceptance-private/department-workbench')
const base = 'http://127.0.0.1:5182'
const stamp = new Date().toISOString().replace(/[:.]/g, '-')
const receipt = { checked_at: new Date().toISOString(), scope: 'local_self_only',
  production_acceptance: false, department_trial: false, external_delivery: false,
  checks: [], screenshots: [], created: {} }
const identityProgram = `
import asyncio, json, sys
from datetime import timedelta
from sqlalchemy import select, update
from app.core.config import get_settings
from app.db.session import async_session_factory, engine
from app.models.identity import OAUser, OAAuthSession
from app.services import identity_service as identity
from scripts.import_public_company_knowledge import actor_for_import
async def main():
    async with async_session_factory() as db:
        actor = await actor_for_import(db, 'oa_admin')
        user = await db.get(OAUser, actor.user_id)
        if sys.argv[1] == 'issue':
            issued = await identity.issue(db, user, get_settings(), expires=identity.utcnow() + timedelta(minutes=20))
            row = await db.scalar(select(OAAuthSession).where(OAAuthSession.refresh_digest == identity.digest(issued.refresh)))
            identity.audit(db, user.id, 'identity.acceptance_session', row.family_id)
            await db.commit()
            print(json.dumps(dict(refresh=issued.refresh, family=row.family_id)))
        else:
            family = sys.argv[2]
            await db.execute(update(OAAuthSession).where(OAAuthSession.tenant_id == actor.tenant_id,
                OAAuthSession.user_id == user.id, OAAuthSession.family_id == family).values(revoked_at=identity.utcnow()))
            identity.audit(db, user.id, 'identity.acceptance_closed', family)
            await db.commit()
            remaining = await db.scalar(select(OAAuthSession.id).where(OAAuthSession.tenant_id == actor.tenant_id,
                OAAuthSession.user_id == user.id, OAAuthSession.family_id == family, OAAuthSession.revoked_at.is_(None)))
            if remaining is not None: raise RuntimeError('session_cleanup_failed')
    await engine.dispose()
asyncio.run(main())
`
function identity(action, family) {
  try { return execFileSync(python, ['-c', identityProgram, action, ...(family ? [family] : [])],
    { cwd: backend, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim() }
  catch { throw new Error('local_acceptance_identity_operation_failed') }
}
await mkdir(output, { recursive: true })
let session, browser, page, failure, announcementId, taskId
const errors = [], failures = []
async function check(name, action) {
  await action(); receipt.checks.push({ name, passed: true }); console.log('PASS ' + name)
}
async function screenshot(name) {
  const filename = `${stamp}-${name}.png`
  await page.screenshot({ path: path.join(output, filename), fullPage: true, animations: 'disabled' })
  receipt.screenshots.push(filename)
}
async function fits() {
  const dimensions = await page.evaluate(() => ({ viewport: innerWidth, content: document.documentElement.scrollWidth }))
  expect(dimensions.content).toBeLessThanOrEqual(dimensions.viewport + 1)
  for (const element of await page.locator('.announcement-body, .announcement-title, .pending-text, .el-dialog').all()) {
    const size = await element.evaluate(node => ({ content: node.scrollWidth, box: node.clientWidth }))
    expect(size.content, 'text must fit its container').toBeLessThanOrEqual(size.box + 1)
  }
}
async function taskAction(action) {
  return page.evaluate(async ({ id, action }) => {
    const { workTaskApi } = await import('/src/api/workTask.ts')
    const task = await workTaskApi.get(id)
    if (task.available_actions.includes(action)) return workTaskApi.command(id, {
      action, comment: '单人验收任务状态核对', expected_version: task.version, idempotency_key: crypto.randomUUID() })
    return task
  }, { id: taskId, action })
}
try {
  session = JSON.parse(identity('issue'))
  browser = await chromium.launch({ channel: 'msedge', headless: true })
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
  await context.addCookies([{ name: 'oa_refresh', value: session.refresh, domain: '127.0.0.1',
    path: '/api/auth', httpOnly: true, secure: false, sameSite: 'Lax' }])
  page = await context.newPage()
  page.on('pageerror', () => errors.push('unhandled_page_error'))
  page.on('response', response => {
    if (response.status() >= 400) failures.push({ path: new URL(response.url()).pathname, status: response.status() })
  })
  const title = '单人验收公告 ' + stamp
  const body = '设备维护检查，仅用于本机单人验收。\n正文按自然语言显示：<script>测试文本</script>。'
  await check('desktop announcement draft creation', async () => {
    await page.goto(base + '/oa/announcements')
    await expect(page.getByRole('heading', { name: '部门公告', exact: true })).toBeVisible()
    await page.getByRole('button', { name: '新建公告', exact: true }).click()
    const editor = page.getByRole('dialog', { name: '新建公告', exact: true })
    await editor.locator('input').fill(title)
    await editor.locator('textarea').fill(body)
    await editor.getByRole('button', { name: '保存草稿', exact: true }).click()
    await expect(page.locator('.announcement-reading')).toContainText(title)
    announcementId = new URL(page.url()).searchParams.get('id')
    receipt.created.announcement_id = announcementId
    await expect(page.locator('.announcement-reading')).toContainText('草稿')
    await expect(page.locator('.announcement-body')).toHaveText(body)
    await expect(page.locator('.announcement-body script')).toHaveCount(0)
    await fits(); await screenshot('desktop-draft')
  })
  await check('draft edit keeps content and increments revision', async () => {
    await page.getByRole('button', { name: '编辑草稿', exact: true }).click()
    const editor = page.getByRole('dialog', { name: '编辑公告草稿', exact: true })
    await editor.locator('textarea').fill(body + '\n补充：验收完成后撤回。')
    await editor.getByRole('button', { name: '保存草稿', exact: true }).click()
    await expect(page.locator('.announcement-reading')).toContainText('第 2 版')
    await expect(page.locator('.announcement-body')).toContainText('验收完成后撤回')
  })
  await check('publish, explicit read and reload persistence', async () => {
    await page.getByRole('button', { name: '发布', exact: true }).click()
    await page.getByRole('button', { name: '确认', exact: true }).click()
    await expect(page.locator('.announcement-reading')).toContainText('已发布')
    await page.getByRole('button', { name: '标为已读', exact: true }).click()
    await expect(page.locator('.announcement-reading')).toContainText('已读')
    await page.reload()
    await expect(page.locator('.announcement-reading')).toContainText('已读')
    await expect(page.getByRole('button', { name: '标为已读', exact: true })).toHaveCount(0)
    await screenshot('desktop-published-read')
  })
  await check('mobile announcement fits and stays readable', async () => {
    await page.setViewportSize({ width: 390, height: 844 })
    await fits(); await screenshot('mobile-published-read')
    await page.getByRole('dialog', { name: '公告详情', exact: true }).getByRole('button', { name: '关闭此对话框', exact: true }).click()
    await fits(); await screenshot('mobile-announcement-list')
  })
  await check('create self-assigned task from real-model confirmed meeting', async () => {
    const result = await page.evaluate(async stamp => {
      const { meetingApi } = await import('/src/api/meeting.ts')
      const { workTaskApi } = await import('/src/api/workTask.ts')
      const { authState } = await import('/src/stores/auth.ts')
      const key = () => crypto.randomUUID()
      let meeting = await meetingApi.create({ title: '单人验收会议 ' + stamp,
        content: '议题：本机验收。\n决定：仅验证本人操作，不对外通知。\n待办：整理本机验收维护清单，负责人和截止时间待人工确认。',
        source_type: 'paste', idempotency_key: key() })
      meeting = await meetingApi.generate(meeting.meeting_id, { idempotency_key: key() })
      if (!meeting.draft?.action_items.length) throw new Error('meeting_sample_missing_actions')
      meeting = await meetingApi.decide(meeting.meeting_id, { action: 'confirm', expected_version: meeting.version,
        idempotency_key: key(), reason: '实施者核对原文与待办，单人本机验收' })
      let batch = await workTaskApi.create({ source_type: 'meeting', source_id: meeting.meeting_id,
        source_version: meeting.version, idempotency_key: key() })
      batch = await workTaskApi.extract(batch.batch_id, { expected_version: batch.version, idempotency_key: key() })
      if (!batch.draft?.candidates.length) throw new Error('task_sample_missing_candidates:' + batch.status)
      const candidate = { ...batch.draft.candidates[0], title: '单人验收维护清单 ' + stamp,
        assignee_id: authState.user.user_id, due_at: new Date(Date.now() + 86400000).toISOString() }
      batch = await workTaskApi.save(batch.batch_id, { expected_version: batch.version,
        idempotency_key: key(), draft: { candidates: [candidate] } })
      batch = await workTaskApi.decide(batch.batch_id, { action: 'confirm', expected_version: batch.version,
        idempotency_key: key(), selected_candidate_ids: [candidate.candidate_id], metadata_confirmed: true,
        risk_acknowledged: true, reason: '仅分配本人，验收完毕即完成并归档' })
      return { meeting_id: meeting.meeting_id, batch_id: batch.batch_id, task_id: batch.task_ids[0], title: candidate.title }
    }, stamp)
    taskId = result.task_id
    Object.assign(receipt.created, result)
    expect(taskId).toBeTruthy()
  })
  for (const [name, viewport] of [['desktop', { width: 1440, height: 960 }], ['mobile', { width: 390, height: 844 }]]) {
    await check(name + ' unified pending list and original task destination', async () => {
      await page.setViewportSize(viewport)
      await page.goto(base + '/tasks')
      await expect(page.getByRole('tab', { name: '待我处理', exact: true })).toHaveAttribute('aria-selected', 'true')
      const row = page.locator('.pending-list li').filter({ hasText: receipt.created.title })
      await expect(row).toBeVisible()
      await fits(); await screenshot(name + '-pending')
      await row.getByRole('button', { name: '去处理', exact: true }).click()
      await expect(page).toHaveURL(base + '/work-tasks/' + taskId)
      await expect(page.getByRole('button', { name: '开始任务', exact: true })).toBeVisible()
      await fits(); await screenshot(name + '-original-task')
    })
  }
  await check('complete in original workbench and remove from pending', async () => {
    await page.getByRole('button', { name: '开始任务', exact: true }).click()
    await expect(page.getByRole('button', { name: '完成任务', exact: true })).toBeVisible()
    await page.getByRole('button', { name: '完成任务', exact: true }).click()
    await expect(page.getByRole('button', { name: '完成任务', exact: true })).toHaveCount(0)
    const task = await taskAction('archive')
    expect(task.status).toBe('ARCHIVED')
    await page.goto(base + '/tasks')
    await expect(page.locator('.pending-list li').filter({ hasText: receipt.created.title })).toHaveCount(0)
    await expect(page.getByText('当前没有待处理事项', { exact: true })).toBeVisible()
    await fits(); await screenshot('mobile-pending-completed')
  })
  await check('withdraw announcement and remove from published list', async () => {
    await page.goto(base + '/oa/announcements?id=' + announcementId)
    await expect(page.getByRole('button', { name: '撤回', exact: true })).toBeVisible()
    await page.getByRole('button', { name: '撤回', exact: true }).click()
    await page.getByRole('button', { name: '确认', exact: true }).click()
    await expect(page.locator('.announcement-reading')).toContainText('已撤回')
    await screenshot('mobile-withdrawn')
    const loaded = page.waitForResponse(response => new URL(response.url()).pathname === '/api/oa/announcements'
      && response.request().method() === 'GET' && response.ok())
    await page.goto(base + '/oa/announcements')
    await loaded
    await expect(page.locator('.el-skeleton')).toHaveCount(0)
    await expect(page.locator('.announcement-link').filter({ hasText: title })).toHaveCount(0)
  })
  await check('no unexpected page errors or failed requests', async () => {
    expect(errors).toEqual([]); expect(failures).toEqual([])
  })
} catch (error) {
  failure = error
  receipt.failure = { name: error.name, message: String(error.message).slice(0, 1500) }
  if (page) await screenshot('failure').catch(() => {})
} finally {
  if (page && announcementId) {
    try {
      receipt.announcement_cleanup = await page.evaluate(async id => {
        const { departmentApi } = await import('/src/api/department.ts')
        let row = await departmentApi.announcement(id)
        if (row.state === 'PUBLISHED') row = (await departmentApi.transition(id, 'withdraw', {
          expected_revision: row.revision, operation_id: crypto.randomUUID() })).result
        return row.state
      }, announcementId)
    } catch { failure ??= new Error('announcement_cleanup_failed') }
  }
  if (page && taskId) {
    try {
      await taskAction('start'); await taskAction('complete')
      receipt.task_cleanup = (await taskAction('archive')).status
    } catch { failure ??= new Error('task_cleanup_failed') }
  }
  if (browser) await browser.close()
  if (errors.length || failures.length) failure ??= new Error('unexpected_browser_errors_including_cleanup')
  if (session) {
    try { identity('revoke', session.family); receipt.acceptance_session_revoked = true }
    catch { receipt.acceptance_session_revoked = false; failure ??= new Error('session_cleanup_failed') }
  }
  receipt.page_errors = errors; receipt.failed_responses = failures; receipt.passed = !failure
  const filename = `browser-${stamp}.json`
  await writeFile(path.join(output, filename), JSON.stringify(receipt, null, 2) + '\n')
  console.log('Evidence: ' + filename)
}
if (failure) { console.error(receipt.failure?.message || failure.message); process.exitCode = 1 }
