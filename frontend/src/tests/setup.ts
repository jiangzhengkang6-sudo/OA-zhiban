import { beforeEach } from 'vitest'
import { authState, clearSession } from '@/stores/auth'
beforeEach(() => { localStorage.clear(); sessionStorage.clear(); clearSession(); authState.provider='mock'; authState.initialized=true })
globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }
