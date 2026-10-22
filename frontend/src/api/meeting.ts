import client from './client'
import { getCurrentUserId } from './client'
import type { MeetingCreateRequest, MeetingDecisionRequest, MeetingDraftUpdateRequest, MeetingPage, MeetingResponse } from '@/types'

const key = (prefix: string) => `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
// Allow two bounded provider requests (up to 60 seconds each) and checkpoint persistence.
const generationOptions = { timeout: 130000 }

async function commandSlot(scope: string, payload: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(JSON.stringify([getCurrentUserId(), scope, payload]))
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return `oa-meeting-command:${Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')}`
}

async function commandKey(scope: string, payload: unknown): Promise<string> {
  const slot = await commandSlot(scope, payload)
  let value = sessionStorage.getItem(slot)
  if (!value) { value = key(scope); sessionStorage.setItem(slot, value) }
  return value
}

async function releaseCommandKey(scope: string, payload: unknown): Promise<void> {
  sessionStorage.removeItem(await commandSlot(scope, payload))
}

export const meetingApi = {
  list(params: Record<string, any> = {}): Promise<MeetingPage> { return client.get('/meetings', { params }) },
  get(id: string): Promise<MeetingResponse> { return client.get(`/meetings/${id}`) },
  create(payload: MeetingCreateRequest): Promise<MeetingResponse> { return client.post('/meetings', { ...payload, idempotency_key: payload.idempotency_key || key('meeting-create') }) },
  generate(id: string, payload: { idempotency_key: string; expected_version?: number | null }): Promise<MeetingResponse> { return client.post(`/meetings/${id}/generate`, payload, generationOptions) },
  save(id: string, payload: MeetingDraftUpdateRequest): Promise<MeetingResponse> { return client.patch(`/meetings/${id}/draft`, payload) },
  decide(id: string, payload: MeetingDecisionRequest): Promise<MeetingResponse> { return client.post(`/meetings/${id}/decisions`, payload, payload.action === 'regenerate' ? generationOptions : undefined) },
  retry(id: string, payload: { idempotency_key: string; expected_version?: number | null }): Promise<MeetingResponse> { return client.post(`/meetings/${id}/retry`, payload, generationOptions) },
  freshKey(prefix = 'meeting-retry'): string { return key(prefix) },
  commandKey,
  releaseCommandKey,
}
