// Local acceptance only: credentials stay in memory and the exact session family is revoked.
import { execFileSync } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { chromium, expect } from '@playwright/test'

const root = fileURLToPath(new URL('../../', import.meta.url))
const backend = path.join(root, 'backend')
const python = path.join(backend, '.venv', 'Scripts', 'python.exe')
const output = path.join(root, 'output/business-acceptance-private/public-company-knowledge')
const base = 'http://127.0.0.1:5182'
const previousThread = 'def92a92-6f3b-4ba3-9931-217a1ca76348'
const stamp = new Date().toISOString().replace(/[:.]/g, '-')
const receipt = { checked_at: new Date().toISOString(), authentication: 'audited_short_session_and_normal_browser_refresh',
  password_login_verified: false, production_acceptance: false, scheduler_paused: true, checks: [], screenshots: [] }
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
    settings = get_settings()
    async with async_session_factory() as db:
        actor = await actor_for_import(db, 'oa_admin')
        user = await db.get(OAUser, actor.user_id)
        if sys.argv[1] == 'issue':
            issued = await identity.issue(db, user, settings, expires=identity.utcnow() + timedelta(minutes=20))
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
let session, browser
let failure
const errors = [], failures = []
async function check(name, action) {
  await action()
  receipt.checks.push({ name, passed: true })
  console.log('PASS ' + name)
}
async function screenshot(page, name) {
  const filename = `browser-${stamp}-${name}.png`
  await page.screenshot({ path: path.join(output, filename), fullPage: true })
  receipt.screenshots.push(filename)
}
async function fits(page) {
  const dimensions = await page.evaluate(() => ({ viewport: innerWidth, content: document.documentElement.scrollWidth }))
  expect(dimensions.content).toBeLessThanOrEqual(dimensions.viewport + 1)
  for (const element of await page.locator('.chat-area, .answer, .bubble, .reading-block').all()) {
    const size = await element.evaluate(node => ({ content: node.scrollWidth, box: node.clientWidth }))
    expect(size.content, 'text must wrap within its container').toBeLessThanOrEqual(size.box + 1)
  }
}
try {
  session = JSON.parse(identity('issue'))
  browser = await chromium.launch({ channel: 'msedge', headless: true })
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
  await context.addCookies([{ name: 'oa_refresh', value: session.refresh, domain: '127.0.0.1',
    path: '/api/auth', httpOnly: true, secure: false, sameSite: 'Lax' }])
  const page = await context.newPage()
  page.on('pageerror', () => errors.push('unhandled_page_error'))
  page.on('response', response => {
    if (response.status() >= 400 && new URL(response.url()).pathname !== '/api/admin/knowledge/sources/00000000-0000-0000-0000-000000000000/versions/00000000-0000-0000-0000-000000000000') {
      failures.push({ path: new URL(response.url()).pathname, status: response.status() })
    }
  })
  for (const [name, viewport] of [['desktop', { width: 1440, height: 960 }], ['mobile', { width: 390, height: 844 }]]) {
    await page.setViewportSize(viewport)
    await check(`${name}: published formal list`, async () => {
      await page.goto(base + '/knowledge')
      await expect(page.locator('.source-link')).toHaveCount(6)
      await expect(page.getByText('已发布知识资料', { exact: true })).toBeVisible()
      await fits(page)
      await screenshot(page, name + '-list')
    })
    await check(`${name}: source reader and direct refresh`, async () => {
      await page.locator('.source-link').first().click()
      await expect(page.locator('.reading-block').first()).toBeVisible()
      await page.reload()
      await expect(page.locator('.reading-block').first()).toBeVisible()
      await fits(page)
    })
    await check(`${name}: persisted FAQ and exact citation`, async () => {
      await page.goto(base + '/assistant/' + previousThread)
      await expect(page.locator('.answer')).toContainText('GitLab', { timeout: 20000 })
      const link = page.locator('.source-card a').first()
      await expect(link).toBeVisible()
      const href = await link.getAttribute('href')
      expect(href).toMatch(/^\/knowledge\/sources\/[\w-]+\/versions\/[\w-]+#chunk-[\w-]+$/)
      await fits(page)
      await link.scrollIntoViewIfNeeded()
      await screenshot(page, name + '-faq')
      await link.click()
      await expect(page).toHaveURL(base + href)
      await expect(page.locator('.reading-block.cited')).toBeVisible()
      expect((await page.locator('.reading-block.cited p').innerText()).length).toBeGreaterThan(30)
      await fits(page)
      await screenshot(page, name + '-citation')
      await page.goBack()
      await expect(page.locator('.answer')).toBeVisible()
    })
  }
  await check('fresh real FAQ through browser', async () => {
    await page.getByRole('button', { name: '新建会话', exact: true }).click()
    await expect(page.locator('.answer')).toHaveCount(0)
    await page.getByPlaceholder('请输入你的问题或描述...').fill('根据 GitLab 公开报销规则，商务出差预订前要做什么？')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await expect(page.locator('.answer')).toContainText('批准', { timeout: 90000 })
    await expect(page.locator('.source-card a').first()).toBeVisible()
    receipt.fresh_thread_id = new URL(page.url()).pathname.split('/').pop()
    receipt.fresh_answer = await page.locator('.answer').innerText()
    await fits(page)
    await page.locator('.source-card a').first().scrollIntoViewIfNeeded()
    await screenshot(page, 'mobile-fresh-faq')
  })
  await check('invalid source clears previous content with safe error', async () => {
    await page.locator('.source-card a').first().click()
    await expect(page.locator('.reading-block.cited')).toBeVisible()
    await page.goto(base + '/knowledge/sources/00000000-0000-0000-0000-000000000000/versions/00000000-0000-0000-0000-000000000000')
    await expect(page.getByText('资料无法读取，可能已下线、过期或访问权限已变更。', { exact: true })).toBeVisible()
    await expect(page.locator('.reading-block')).toHaveCount(0)
    await screenshot(page, 'mobile-denied-source')
  })
  await check('no unexpected browser errors or failed HTTP responses', async () => {
    expect(errors).toEqual([])
    expect(failures).toEqual([])
  })
} catch (error) {
  failure = error
  receipt.failure = { name: error.name, message: String(error.message).slice(0, 1500) }
} finally {
  if (browser) await browser.close()
  if (session) {
    try { identity('revoke', session.family); receipt.acceptance_session_revoked = true }
    catch { receipt.acceptance_session_revoked = false; failure ??= new Error('acceptance_session_cleanup_failed') }
  }
  receipt.page_errors = errors
  receipt.failed_responses = failures
  receipt.passed = !failure
  const filename = `browser-${stamp}.json`
  await writeFile(path.join(output, filename), JSON.stringify(receipt, null, 2) + '\n')
  console.log('Evidence: ' + filename)
}
if (failure) { console.error(receipt.failure?.message || failure.message); process.exitCode = 1 }
