import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { authState, clearSession, reloadIdentity, syncIdentity, startIdentitySync } from '@/stores/auth'

const user = { user_id: 'member', display_name: '成员', roles: ['employee'], depts: ['product'],
  permissions: [{ resource: 'meeting', action: 'read', scope: 'self' }] }
beforeEach(() => {
  vi.useFakeTimers()
  Object.assign(authState, { provider: 'builtin', initialized: true, accessToken: 'current', user: structuredClone(user) })
})
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })
function serve(value = user) {
  const fetch = vi.fn(async () => ({ ok: true, json: async () => ({ code: '0', data: value }) }))
  vi.stubGlobal('fetch', fetch)
  return fetch
}
it('deduplicates checks and does not invalidate unchanged permissions', async () => {
  const fetch = serve()
  const revision = authState.authorizationRevision
  await Promise.all([reloadIdentity(), reloadIdentity(), reloadIdentity()])
  expect(fetch).toHaveBeenCalledOnce()
  expect(authState.authorizationRevision).toBe(revision)
  await syncIdentity()
  expect(fetch).toHaveBeenCalledOnce()
})
it('detects changes to data scope, resets authorization and publishes once', async () => {
  serve({ ...user, permissions: [{ resource: 'meeting', action: 'read', scope: 'department' }] })
  const listener = vi.fn()
  window.addEventListener('oa-access-updated', listener)
  const revision = authState.authorizationRevision
  await reloadIdentity()
  expect(authState.authorizationRevision).toBe(revision + 1)
  expect(listener).toHaveBeenCalledOnce()
  expect(authState.user!.permissions[0]!.scope).toBe('department')
  window.removeEventListener('oa-access-updated', listener)
})
it('ignores a late identity response after logout', async () => {
  let resolve!: (value: unknown) => void
  vi.stubGlobal('fetch', vi.fn(() => new Promise(r => { resolve = r })))
  const pending = reloadIdentity()
  clearSession()
  resolve({ ok: true, json: async () => ({ code: '0', data: user }) })
  await pending
  expect(authState.user).toBeNull()
})
it('clears an expired identity when me is still unauthorized after refresh', async () => {
  const expired = vi.fn()
  window.addEventListener('oa-session-expired', expired)
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({
    ok: !url.endsWith('/me'), status: url.endsWith('/me') ? 401 : 200,
    json: async () => url.endsWith('/me') ? { code: '401', message: 'expired' }
      : { code: '0', data: url.endsWith('/csrf') ? { token: 'csrf' } : { access_token: 'renewed', user } },
  })))
  try {
    await expect(reloadIdentity()).rejects.toThrow('expired')
    expect(authState.user).toBeNull()
    expect(authState.accessToken).toBe('')
    expect(expired).toHaveBeenCalledOnce()
  } finally { window.removeEventListener('oa-session-expired', expired) }
})
it('ignores permission array ordering and preserves identity on a transient failure', async () => {
  const ordered = { ...user, roles: ['employee', 'reviewer'], depts: ['product', 'qa'], permissions: [
    ...user.permissions, { resource: 'document', action: 'read', scope: 'department' },
  ] }
  authState.user = structuredClone(ordered)
  serve({ ...ordered, roles: [...ordered.roles].reverse(), depts: [...ordered.depts].reverse(), permissions: [...ordered.permissions].reverse() })
  const revision = authState.authorizationRevision
  await reloadIdentity()
  expect(authState.authorizationRevision).toBe(revision)
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
  await expect(reloadIdentity()).rejects.toThrow('offline')
  expect(authState.user?.user_id).toBe(user.user_id)
  expect(authState.authorizationRevision).toBe(revision)
})
it('checks on a visible interval and focus, and removes listeners when stopped', async () => {
  const fetch = serve()
  const stop = startIdentitySync()
  await vi.advanceTimersByTimeAsync(30000)
  expect(fetch).toHaveBeenCalledOnce()
  await vi.advanceTimersByTimeAsync(16000)
  window.dispatchEvent(new Event('focus'))
  await vi.advanceTimersByTimeAsync(0)
  expect(fetch).toHaveBeenCalledTimes(2)
  stop()
  await vi.advanceTimersByTimeAsync(60000)
  window.dispatchEvent(new Event('focus'))
  expect(fetch).toHaveBeenCalledTimes(2)
})
