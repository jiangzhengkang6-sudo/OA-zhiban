// Explicit opt-in real Tencent dual-client acceptance.
import { execFileSync } from 'node:child_process'
import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { randomUUID } from 'node:crypto'
import { chromium, expect } from '@playwright/test'
if (process.env.OA_VIDEO_LIVE_ACCEPTANCE !== '1') throw new Error('live_opt_in_required')
const root = fileURLToPath(new URL('../../', import.meta.url)), backend = path.join(root, 'backend')
const output = path.join(root, 'output/business-acceptance-private/meeting-video')
const stamp = new Date().toISOString().replace(/[:.]/g, '-')
const hostId = '3f6ad0fd-11d3-4ca5-888c-7765f836f358', memberId = '183067e2-3156-453a-8b0e-2e18d4df8e58'
const database = 'oa_tuiroom_acceptance_20261025_test'
const env = { ...process.env, DATABASE_URL: `postgresql+asyncpg://oa:oa@localhost:5433/${database}`,
  DATABASE_SYNC_URL: `postgresql+psycopg://oa:oa@localhost:5433/${database}`,
  CHECKPOINTER_URL: `postgresql://oa:oa@localhost:5433/${database}`,
  AUTH_PROVIDER: 'builtin', OA_PROVIDER: 'builtin', SMTP_ENABLED: 'false', WECOM_ENABLED: 'false', LLM_PROVIDER: 'mock', EMBEDDING_PROVIDER: 'mock' }
const program = `
import asyncio,json,sys
from datetime import timedelta
from sqlalchemy import select,update,make_url
from app.core.config import get_settings
from app.db.session import async_session_factory,engine
from app.models.identity import OAUser,OAAuthSession
from app.models.oa_meeting import OAMeeting
from app.services import identity_service as identity,meeting_video_service as video
async def main():
 assert make_url(get_settings().database_url).database=='${database}'
 async with async_session_factory() as db:
  action=sys.argv[1]
  if action=='issue':
   user=await db.get(OAUser,sys.argv[2]); assert user and user.status=='active'
   issued=await identity.issue(db,user,get_settings(),expires=identity.utcnow()+timedelta(minutes=20))
   row=await db.scalar(select(OAAuthSession).where(OAAuthSession.refresh_digest==identity.digest(issued.refresh)))
   await db.commit()
   print(json.dumps(dict(refresh=issued.refresh,access=issued.grant.access_token,family=row.family_id)))
  elif action=='revoke':
   families=json.loads(sys.argv[2])
   await db.execute(update(OAAuthSession).where(OAAuthSession.family_id.in_(families)).values(revoked_at=identity.utcnow()))
   await db.commit()
   assert await db.scalar(select(OAAuthSession.id).where(OAAuthSession.family_id.in_(families),OAAuthSession.revoked_at.is_(None))) is None
   print(json.dumps(dict(sessions_revoked=True)))
  elif action=='rooms':
   rows=(await db.scalars(select(OAMeeting).where(OAMeeting.id==sys.argv[2],OAMeeting.host_id=='${hostId}',OAMeeting.video_enabled.is_(True),OAMeeting.video_room_created.is_(True)))).all()
   result=[]
   for row in rows:
    code=(await video.request('get_room_info',{'RoomId':video.room_id(row)},accepted=(100004,)))['ErrorCode']
    if row.state in ('ENDED','CANCELLED') and code==0:
     await video.close_room(row)
     code=(await video.request('get_room_info',{'RoomId':video.room_id(row)},accepted=(100004,)))['ErrorCode']
    result.append(dict(meeting_id=row.id,state=row.state,provider_code=code))
   print(json.dumps(result))
 await engine.dispose()
asyncio.run(main())
`
function identity(action, value = '') {
  try { return JSON.parse(execFileSync(path.join(backend, '.venv/Scripts/python.exe'), ['-c', program, action, value],
    { cwd: backend, env, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim()) }
  catch { throw new Error(`isolated_${action}_failed`) }
}
const receipt = { checked_at: new Date().toISOString(), database, synthetic_devices: true, checks: [], diagnostics: [], identity_syncs: {} }
const sessions = [], pages = []
let browser, meeting, admin, failure
async function api(route, body) {
  const r = await fetch(`http://127.0.0.1:8016/api${route}`, { method: body ? 'POST' : 'GET', headers: { Authorization: `Bearer ${admin.access}`, 'Content-Type': 'application/json' }, ...(body ? { body: JSON.stringify(body) } : {}) })
  const data = await r.json()
  if (!r.ok) throw new Error(`api_${route}_${r.status}_${data.code || ''}`)
  return data.data
}
async function command(action) { meeting = (await api(`/meeting-events/${meeting.id}/${action}`, { expected_revision: meeting.revision, operation_id: randomUUID() })).result }
async function check(name, run) { await run(); receipt.checks.push({ name, passed: true }); console.log('PASS ' + name) }
function instrument() {
  const peers = [], Original = window.RTCPeerConnection
  window.RTCPeerConnection = new Proxy(Original, { construct(target, args) { const peer = new target(...args); peers.push(peer); return peer } })
  window.__videoAcceptance = async () => {
    const stats = []
    for (const peer of peers) {
      if (peer.connectionState === 'closed') continue
      try { (await peer.getStats()).forEach(s => {
        if (['inbound-rtp', 'outbound-rtp'].includes(s.type) && !s.isRemote) stats.push({ type: s.type, kind: s.kind || s.mediaType,
          bytesSent: s.bytesSent || 0, bytesReceived: s.bytesReceived || 0, framesDecoded: s.framesDecoded || 0, framesEncoded: s.framesEncoded || 0 })
      }) } catch { /* Closed connections are expected after leaving. */ }
    }
    return { peers: peers.length, stats, videos: [...document.querySelectorAll('video')].map(v => ({ width: v.videoWidth,
      height: v.videoHeight, readyState: v.readyState, tracks: v.srcObject?.getTracks?.().map(t => ({ kind: t.kind, readyState: t.readyState, enabled: t.enabled })) || [] })) }
  }
}
async function openPage(userId) {
  const session = identity('issue', userId); sessions.push(session)
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, permissions: ['camera', 'microphone'] })
  await context.addCookies([{ name: 'oa_refresh', value: session.refresh, domain: '127.0.0.1', path: '/api/auth', httpOnly: true, secure: false, sameSite: 'Lax' }])
  await context.addInitScript(instrument)
  const page = await context.newPage(); pages.push(page)
  let admissionFailure
  page.on('pageerror', e => receipt.diagnostics.push({ kind: 'page_error', message: safe(e.message) }))
  page.on('console', m => { if (['error', 'warning'].includes(m.type())) receipt.diagnostics.push({ kind: m.type(), message: safe(m.text()) }) })
  page.on('response', async r => {
    if (new URL(r.url()).pathname === '/api/auth/me' && r.ok()) receipt.identity_syncs[userId] = (receipt.identity_syncs[userId] || 0) + 1
    if (r.url().includes('/api/') && r.status() >= 400) {
      const detail = await r.json().catch(() => ({}))
      receipt.diagnostics.push({ path: new URL(r.url()).pathname, status: r.status(), message: safe(detail.message), detail: safe(JSON.stringify(detail.data)) })
      if (new URL(r.url()).pathname.endsWith('/video-session')) admissionFailure = `admission_${r.status()}: ${safe(detail.message)}`
    }
  })
  await page.goto(`http://127.0.0.1:5183/meeting-events/${meeting.id}`)
  await page.getByRole('button', { name: '加入视频会议', exact: true }).click()
  await expect.poll(async () => {
    if (admissionFailure) throw new Error(admissionFailure)
    const error = await page.locator('.video-meeting .el-alert').innerText().catch(() => '')
    if (error) throw new Error(safe(error))
    return page.getByRole('button', { name: '退出视频', exact: true }).isVisible()
  }, { timeout: 60000 }).toBe(true)
  return page
}
async function enableMedia(page) {
  const room = page.locator('.video-container')
  for (const device of ['麦克风', '摄像头']) {
    const close = room.getByRole('button', { name: `关闭${device}`, exact: true })
    if (!await close.isVisible()) await room.getByRole('button', { name: `打开${device}`, exact: true }).click()
    await expect(close).toBeVisible({ timeout: 20000 })
  }
}
await mkdir(output, { recursive: true })
try {
  admin = identity('issue', hostId); sessions.push(admin)
  meeting = (await api('/meeting-events', { title: `视频双端自动验收 ${stamp}`, agenda: '隔离环境双端媒体收发验收',
    starts_at: new Date(Date.now() + 300000).toISOString(), ends_at: new Date(Date.now() + 3600000).toISOString(),
    host_id: hostId, recorder_id: hostId, attendee_ids: [hostId, memberId], location: '', online_url: '', video_enabled: true, operation_id: randomUUID() })).result
  receipt.meeting_id = meeting.id
  await command('publish'); await command('start')
  browser = await chromium.launch({ channel: 'msedge', headless: true, args: [
    '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream', '--autoplay-policy=no-user-gesture-required',
    // Windows headless hardware capture stalled at a 2x2 frame; software capture produces real test frames.
    '--disable-gpu', '--disable-background-timer-throttling', '--disable-backgrounding-occluded-windows', '--disable-renderer-backgrounding',
  ] })
  await check('host joins room', async () => { const p = await openPage(hostId); await expect(p.getByRole('button', { name: '退出视频', exact: true })).toBeVisible({ timeout: 90000 }) })
  await check('invited member joins room', async () => { const p = await openPage(memberId); await expect(p.getByRole('button', { name: '退出视频', exact: true })).toBeVisible({ timeout: 90000 }) })
  await check('both clients enable microphone and camera', async () => {
    for (const page of pages) await enableMedia(page)
  })
  for (let i = 0; i < pages.length; i++) {
    await pages[i].screenshot({ path: path.join(output, `${stamp}-joined-${i}.png`), fullPage: true })
    receipt.diagnostics.push({ role: i, room_text: safe(await pages[i].locator('.video-container').innerText()),
      buttons: await pages[i].locator('.video-container button').evaluateAll(es => es.map(e => ({ text: e.textContent, label: e.getAttribute('aria-label'), title: e.getAttribute('title') }))) })
  }
  await check('both peers send and receive audio and video', async () => {
    await expect.poll(async () => {
      receipt.media = await Promise.all(pages.map(p => p.evaluate(() => window.__videoAcceptance())))
      return receipt.media.every(m => ['audio', 'video'].every(kind => ['inbound-rtp', 'outbound-rtp'].every(type => m.stats.some(s => s.kind === kind && s.type === type && (type === 'inbound-rtp' ? s.bytesReceived > 0 : s.bytesSent > 0)
        && (kind !== 'video' || (type === 'inbound-rtp' ? s.framesDecoded > 0 : s.framesEncoded > 0)))))
        && m.videos.some(v => v.width >= 160 && v.height >= 120 && v.readyState >= 2))
    }, { timeout: 45000 }).toBe(true)
    for (let i = 0; i < pages.length; i++) await pages[i].screenshot({ path: path.join(output, `${stamp}-media-${i}.png`), fullPage: true })
  })
  await check('background identity refresh keeps both video sessions connected', async () => {
    const before = [hostId, memberId].map(id => receipt.identity_syncs[id] || 0)
    await expect.poll(async () => {
      for (const p of pages) await expect(p.getByRole('button', { name: '退出视频', exact: true })).toBeVisible()
      return [hostId, memberId].every((id, i) => (receipt.identity_syncs[id] || 0) > before[i])
    }, { timeout: 45000, intervals: [1000, 3000] }).toBe(true)
    for (const p of pages) await expect(p.getByRole('button', { name: '退出视频', exact: true })).toBeVisible()
  })
  await check('refresh preserves both live video sessions and media keeps flowing', async () => {
    const before = await Promise.all(pages.map(p => p.evaluate(async () => {
      window.__joinedVideos = [...document.querySelectorAll('.video-container video')]
      return (await window.__videoAcceptance()).stats.filter(s => s.kind === 'video' && s.type === 'inbound-rtp')
        .reduce((count, s) => count + s.framesDecoded, 0)
    })))
    for (const p of pages) {
      const refreshed = p.waitForResponse(r => new URL(r.url()).pathname === `/api/meeting-events/${meeting.id}` && r.request().method() === 'GET' && r.ok())
      await p.getByRole('button', { name: '刷新', exact: true }).click()
      await refreshed
      await expect(p.getByRole('button', { name: '退出视频', exact: true })).toBeVisible()
      expect(await p.evaluate(() => window.__joinedVideos.length > 0 && window.__joinedVideos.every(v => v.isConnected))).toBe(true)
    }
    await expect.poll(async () => {
      const after = await Promise.all(pages.map(p => p.evaluate(async () => (await window.__videoAcceptance()).stats
        .filter(s => s.kind === 'video' && s.type === 'inbound-rtp').reduce((count, s) => count + s.framesDecoded, 0))))
      return after.every((count, i) => count > before[i])
    }, { timeout: 15000 }).toBe(true)
  })
  await check('member leaves without ending meeting', async () => {
    await pages[1].getByRole('button', { name: '退出视频', exact: true }).click()
    await expect(pages[1].getByRole('button', { name: '加入视频会议', exact: true })).toBeVisible()
    expect((await api(`/meeting-events/${meeting.id}`)).state).toBe('IN_PROGRESS')
  })
  for (let round = 1; round <= 3; round++) await check(`member rejoins the existing room, round ${round}`, async () => {
    if (round > 1) {
      await pages[1].getByRole('button', { name: '退出视频', exact: true }).click()
      await expect(pages[1].getByRole('button', { name: '加入视频会议', exact: true })).toBeEnabled()
    }
    await pages[1].getByRole('button', { name: '加入视频会议', exact: true }).click()
    await expect(pages[1].getByRole('button', { name: '退出视频', exact: true })).toBeVisible({ timeout: 60000 })
    await enableMedia(pages[1])
    await expect.poll(async () => {
      const media = await pages[1].evaluate(() => window.__videoAcceptance())
      return media.stats.some(s => s.type === 'inbound-rtp' && s.kind === 'video' && s.framesDecoded > 0)
        && media.videos.some(v => v.width >= 160 && v.height >= 120)
    }, { timeout: 30000 }).toBe(true)
  })
  await check('host ends meeting and both views close', async () => {
    await command('end')
    for (const p of pages) {
      await expect(p.getByRole('button', { name: '退出视频', exact: true })).toHaveCount(0, { timeout: 20000 })
      await expect(p.getByRole('button', { name: '加入视频会议', exact: true })).toBeDisabled({ timeout: 20000 })
      await expect.poll(() => p.evaluate(() => document.querySelectorAll('.video-container video').length)).toBe(0)
      await expect(p.getByText('已结束', { exact: true })).toBeVisible({ timeout: 25000 })
    }
  })
} catch (e) { failure = e; receipt.error = safe(e.message); console.log('FAIL ' + receipt.error) }
finally {
  if (browser) {
    for (let i = 0; i < pages.length; i++) {
      try { receipt.diagnostics.push({ role: i, final_text: safe(await pages[i].locator('.video-container').innerText()), media: await pages[i].evaluate(() => window.__videoAcceptance()) }); await pages[i].screenshot({ path: path.join(output, `${stamp}-final-${i}.png`), fullPage: true }) } catch { /* Best-effort diagnostics. */ }
    }
    await browser.close()
  }
  if (meeting) {
    try { meeting = await api(`/meeting-events/${meeting.id}`); if (meeting.state === 'IN_PROGRESS') await command('end'); else if (['DRAFT', 'SCHEDULED'].includes(meeting.state)) await command('cancel'); receipt.final_state = meeting.state }
    catch { receipt.cleanup_error = 'meeting_cleanup_failed'; failure ||= new Error(receipt.cleanup_error) }
  }
  try { receipt.rooms = identity('rooms', meeting?.id || ''); if ((meeting && receipt.rooms.length !== 1) || receipt.rooms.some(r => !['ENDED', 'CANCELLED'].includes(r.state) || r.provider_code !== 100004)) throw new Error('room_cleanup_incomplete'); receipt.room_cleanup_confirmed = true }
  catch { receipt.room_cleanup_confirmed = false; failure ||= new Error('room_cleanup_failed') }
  try { Object.assign(receipt, identity('revoke', JSON.stringify(sessions.map(s => s.family)))) } catch { failure ||= new Error('session_cleanup_failed') }
  receipt.passed = !failure
  await writeFile(path.join(output, `${stamp}-receipt.json`), JSON.stringify(receipt, null, 2) + '\n')
  console.log(JSON.stringify({ passed: receipt.passed, checks: receipt.checks, cleanup: receipt.room_cleanup_confirmed, sessions_revoked: receipt.sessions_revoked, receipt: `${stamp}-receipt.json` }))
}
if (failure) process.exitCode = 1
function safe(value) { return String(value).replace(/https?:\/\/\S+/g, '[url]').replace(/(userSig|access_token|refresh_token|password|secret|token)\s*[=:]\s*[^,}\s]+/gi, '$1=[redacted]').replace(/[A-Za-z0-9*_.-]{80,}/g, '[redacted]').slice(0, 800) }
