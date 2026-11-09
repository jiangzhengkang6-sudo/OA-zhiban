import { it, expect, vi } from 'vitest'
import { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from 'axios'
import client from '@/api/client'
import { authState, clearSession } from '@/stores/auth'
vi.mock('element-plus', () => ({ ElMessage: {error:vi.fn()} }))
const user = {user_id:'u1',display_name:'员工',roles:[],depts:[],permissions:[]}
const response = (config:InternalAxiosRequestConfig, data:unknown) => ({config,status:200,statusText:'OK',headers:{},data:{code:'0',data}})
function fail(config:InternalAxiosRequestConfig,status:number):never {
  throw new AxiosError('denied',undefined,config,undefined,{...response(config,null),status})
}
it('并发 401 只刷新一次，并将重试绑定到当前会话',async () => {
  authState.provider='builtin'; authState.user=user; authState.accessToken='old'
  let refreshes=0
  vi.stubGlobal('fetch',vi.fn(async (url:string) => ({ok:true,json:async () => ({code:'0',data:url.endsWith('csrf') ? {token:'csrf'} : (refreshes++,{access_token:'new',user})})})))
  const adapter=async (config:InternalAxiosRequestConfig) => {
    if(config.headers.Authorization==='Bearer old') fail(config,401)
    return response(config,'ok')
  }
  const values=await Promise.all([client.get('/a',{adapter}),client.get('/b',{adapter})])
  expect(values).toEqual(['ok','ok']); expect(refreshes).toBe(1)
  vi.unstubAllGlobals()
})
it('403 提示权限变更，不轮换刷新令牌',async () => {
  authState.provider='builtin'; authState.user=user; authState.accessToken='current'
  const fetch=vi.fn(); vi.stubGlobal('fetch',fetch)
  const changed=vi.fn(); window.addEventListener('oa-permissions-changed',changed)
  await expect(client.get('/organization',{adapter:async config=>fail(config,403)})).rejects.toThrow()
  expect(fetch).not.toHaveBeenCalled(); expect(changed).toHaveBeenCalledOnce()
  window.removeEventListener('oa-permissions-changed',changed); vi.unstubAllGlobals()
})
it('退出后到达的业务响应不得写回页面',async () => {
  authState.provider='builtin'; authState.user=user; authState.accessToken='current'
  let finish!:()=>void
  let started!:()=>void
  const ready=new Promise<void>(r=>{started=r})
  const pending=client.get('/documents',{adapter:async config=>{started(); await new Promise<void>(r=>{finish=r}); return response(config,'private')}})
  await ready; clearSession(); finish()
  await expect(pending).rejects.toThrow('会话已变更')
})
it('权限范围更新后到达的旧响应不得写回页面', async () => {
  authState.provider = 'builtin'; authState.user = user; authState.accessToken = 'current'
  let finish!: () => void
  let started!: () => void
  const ready = new Promise<void>(resolve => { started = resolve })
  const pending = client.get('/documents', { adapter: async config => {
    started(); await new Promise<void>(resolve => { finish = resolve }); return response(config, 'private')
  } })
  await ready
  authState.authorizationRevision++
  finish()
  await expect(pending).rejects.toThrow('权限已变更')
})
it('刷新后的业务请求失败不应清除有效登录态', async () => {
  authState.provider = 'builtin'; authState.user = user; authState.accessToken = 'old'
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, json: async () => ({
    code: '0', data: url.endsWith('csrf') ? { token: 'csrf' } : { access_token: 'renewed', user },
  }) })))
  try {
    await expect(client.get('/documents', { adapter: async config => fail(config, config.headers.Authorization === 'Bearer old' ? 401 : 500) })).rejects.toThrow()
    expect(authState.accessToken).toBe('renewed')
    expect(authState.user?.user_id).toBe(user.user_id)
  } finally { vi.unstubAllGlobals() }
})
it('刷新时权限改变不得重放旧业务请求或退出新会话', async () => {
  authState.provider = 'builtin'; authState.user = user; authState.accessToken = 'old'
  const changed = { ...user, permissions: [{ resource: 'meeting', action: 'read', scope: 'self' }] }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, json: async () => ({
    code: '0', data: url.endsWith('csrf') ? { token: 'csrf' } : { access_token: 'renewed', user: changed },
  }) })))
  const adapter = vi.fn(async (config: InternalAxiosRequestConfig) => fail(config, 401))
  try {
    await expect(client.post('/documents', {}, { adapter })).rejects.toThrow('权限已变更')
    expect(adapter).toHaveBeenCalledOnce()
    expect(authState.accessToken).toBe('renewed')
  } finally { vi.unstubAllGlobals() }
})
it('刷新后的令牌仍然未授权时退出过期会话', async () => {
  authState.provider = 'builtin'; authState.user = user; authState.accessToken = 'old'
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, json: async () => ({
    code: '0', data: url.endsWith('csrf') ? { token: 'csrf' } : { access_token: 'renewed', user },
  }) })))
  try {
    await expect(client.get('/documents', { adapter: async config => fail(config, 401) })).rejects.toThrow()
    expect(authState.user).toBeNull()
    expect(authState.accessToken).toBe('')
  } finally { vi.unstubAllGlobals() }
})
