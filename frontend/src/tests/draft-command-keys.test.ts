import { webcrypto } from 'node:crypto'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { commandKey, releaseCommandKey, replayable } from '@/api/draftCommands'

beforeEach(() => { vi.stubGlobal('crypto', webcrypto); sessionStorage.clear(); localStorage.clear() })
afterEach(() => vi.unstubAllGlobals())

describe('draft command retry identity', () => {
  it('reuses failed attempts, rotates after success and separates actor, command and payload', async () => {
    const payload = { id: 'DOC-1', expected_version: 1 }
    const key = await commandKey('document-edit', payload)
    await expect(replayable('document-edit', payload, async retryKey => {
      expect(retryKey).toBe(key); throw new Error('network lost')
    })).rejects.toThrow('network lost')
    expect(await commandKey('document-edit', payload)).toBe(key)
    expect(await commandKey('document-edit', { ...payload, expected_version: 2 })).not.toBe(key)
    expect(await commandKey('document-confirm', payload)).not.toBe(key)
    localStorage.setItem('oa_current_user', 'u_emp_002')
    expect(await commandKey('document-edit', payload)).not.toBe(key)
    localStorage.removeItem('oa_current_user')
    await expect(replayable('document-edit', payload, async retryKey => retryKey)).resolves.toBe(key)
    expect(await commandKey('document-edit', payload)).not.toBe(key)
    await releaseCommandKey('document-edit', payload)
  })
})
