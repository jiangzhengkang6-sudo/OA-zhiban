import { describe, it, expect, vi, beforeEach } from 'vitest'
import { authState, safeRedirect, refreshSession, clearSession, configureAuth, logout, can, homePath } from '@/stores/auth'

beforeEach(() => { clearSession(); authState.initialized=false; authState.provider='mock'; authState.aiEnabled=true; authState.manualOA=false; vi.restoreAllMocks() })

describe('正式会话', () => {
  it('认证接口返回空响应时显示服务异常提示', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, {status:500})))
    try {
      await expect(configureAuth()).rejects.toThrow('登录服务暂时不可用')
      expect(authState.initialized).toBe(false)
      expect(authState.user).toBeNull()
    } finally { vi.unstubAllGlobals() }
  })
  it('AI 关闭保留显式授权的 M3 人工业务，仍拒绝 AI 入口和未授权操作', () => {
    authState.provider = 'builtin'
    authState.aiEnabled = false
    authState.manualOA = true
    authState.user = { user_id:'employee', display_name:'申请员工', roles:[], depts:[], permissions:
      ['reimbursement','ticket','ticket_handle','ticket_admin','notification','notification_admin','thread']
        .map(resource => ({resource, action:'read', scope:'self'})) }
    for (const resource of ['reimbursement','ticket','ticket_handle','ticket_admin','notification','notification_admin']) {
      expect(can(resource)).toBe(true)
      expect(can(resource, 'write')).toBe(false)
    }
    expect(can('thread')).toBe(false)
    expect(can('approval')).toBe(false)
    expect(homePath()).toBe('/oa/reimbursements')
    authState.user.permissions = []
    expect(can('reimbursement')).toBe(false)
    expect(homePath()).toBe('/account')
  })
  it('退出期间返回的刷新结果不能恢复旧身份，仍撤销服务端会话', async () => {
    let release!: (value:unknown)=>void
    const grant = new Promise(resolve=>{ release=resolve })
    const calls:string[]=[]
    vi.stubGlobal('fetch',vi.fn(async(path:string)=>{
      calls.push(path)
      return {ok:true,json:async()=>({code:'0',data:path.endsWith('/csrf')?{token:'csrf'}:
        path.endsWith('/refresh')?await grant:null})}
    }))
    const refreshing=refreshSession().catch(()=>{})
    await vi.waitFor(()=>expect(calls).toContain('/api/auth/refresh'))
    const closing=logout()
    expect(authState.user).toBeNull()
    release({access_token:'old-refresh',user:{user_id:'old',roles:[],depts:[],permissions:[],display_name:'旧账号'}})
    await Promise.all([refreshing,closing])
    expect(authState.user).toBeNull()
    expect(authState.accessToken).toBe('')
    expect(calls.at(-1)).toBe('/api/auth/logout')
  })
  it('只允许站内重定向', () => {
    expect(safeRedirect('//external.test')).toBe('/tasks')
    expect(safeRedirect('/\\external.test')).toBe('/tasks')
    expect(safeRedirect('https://external.test')).toBe('/tasks')
    expect(safeRedirect('/meetings?id=1')).toBe('/meetings?id=1')
  })
  it('刷新单飞，令牌只留内存', async () => {
    let refreshCalls = 0
    vi.stubGlobal('fetch', vi.fn(async (path: string) => {
      if (path.endsWith('/refresh')) refreshCalls++
      return { ok: true, json: async () => ({ code:'0', data: path.endsWith('/csrf') ? {token:'csrf'} :
        path.endsWith('/config') ? {provider:'builtin'} : {access_token:'access-only-memory', user:{user_id:'u1',roles:[],depts:[],permissions:[],display_name:'用户'}} }) }
    }))
    await configureAuth()
    refreshCalls = 0
    await Promise.all([refreshSession(), refreshSession(), refreshSession()])
    expect(refreshCalls).toBe(1)
    expect(authState.accessToken).toBe('access-only-memory')
    expect(JSON.stringify(localStorage)).not.toContain('access-only-memory')
    expect(JSON.stringify(sessionStorage)).not.toContain('access-only-memory')
    clearSession()
    expect(authState.user).toBeNull()
  })
})
