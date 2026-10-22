import { beforeEach, describe, expect, it } from 'vitest'
import { meetingApi } from '@/api/meeting'
import { setCurrentUserId } from '@/api/client'

beforeEach(() => { sessionStorage.clear(); setCurrentUserId('u_emp_001') })

describe('meeting command keys', () => {
  it('reuses a pending key across view reloads until a result is acknowledged', async () => {
    const payload = { title: '周会', content: '确认验收', source_type: 'paste' }
    const first = await meetingApi.commandKey('meeting-create', payload)
    expect(await meetingApi.commandKey('meeting-create', { ...payload })).toBe(first)
    expect(sessionStorage.length).toBe(1)
    await meetingApi.releaseCommandKey('meeting-create', payload)
    expect(await meetingApi.commandKey('meeting-create', payload)).not.toBe(first)
  })

  it('separates commands by user, operation, and payload', async () => {
    const payload = { id: 'MTG-1' }
    const first = await meetingApi.commandKey('meeting-generate', payload)
    expect(await meetingApi.commandKey('meeting-generate', { id: 'MTG-2' })).not.toBe(first)
    expect(await meetingApi.commandKey('meeting-edit', payload)).not.toBe(first)
    setCurrentUserId('u_admin_001')
    expect(await meetingApi.commandKey('meeting-generate', payload)).not.toBe(first)
  })
})
