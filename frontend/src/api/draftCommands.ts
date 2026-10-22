import { getCurrentUserId } from './client'

async function slot(scope: string, payload: unknown) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify([getCurrentUserId(), scope, payload])))
  return `oa-draft-command:${Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')}`
}
export async function commandKey(scope: string, payload: unknown) {
  const storageKey = await slot(scope, payload)
  const existing = sessionStorage.getItem(storageKey)
  if (existing) return existing
  const key = crypto.randomUUID()
  sessionStorage.setItem(storageKey, key)
  return key
}
export async function releaseCommandKey(scope: string, payload: unknown) { sessionStorage.removeItem(await slot(scope, payload)) }
export async function replayable<R>(scope: string, payload: unknown, command: (key: string) => Promise<R>) {
  const result = await command(await commandKey(scope, payload))
  await releaseCommandKey(scope, payload)
  return result
}
