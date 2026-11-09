import { reactive } from 'vue'

export interface Permission { resource: string; action: string; scope: string }
export interface Identity { user_id: string; display_name: string; roles: string[]; depts: string[]; permissions: Permission[] }
interface Grant { access_token: string; user: Identity }
export const authState = reactive({ provider: 'mock', initialized: false, aiEnabled:true, manualOA:false, user: null as Identity | null, accessToken: '', authorizationRevision: 0 })
let configuration: Promise<void> | null = null
let refreshing: Promise<void> | null = null
let csrfToken = ''
let epoch = 0
let closing: Promise<void> | null = null
let checking: { epoch: number; promise: Promise<void> } | null = null
let checkedAt = -Infinity
let checkedEpoch = -1
export const sessionRevision = () => epoch

function accessSignature(user: Identity) {
  return JSON.stringify([user.user_id, [...user.roles].sort(), [...user.depts].sort(),
    user.permissions.map(p => `${p.resource}:${p.action}:${p.scope}`).sort()])
}
function applyIdentity(user: Identity) {
  const previous = authState.user
  const changed = previous !== null && accessSignature(previous) !== accessSignature(user)
  authState.user = user
  if (changed) {
    authState.authorizationRevision++
    clearDrafts()
    window.dispatchEvent(new Event('oa-access-updated'))
  }
}

function clearDrafts() {
  localStorage.removeItem('oa_assistant_draft_v1')
  for (const key of Object.keys(sessionStorage)) if (/^(oa[_-]|meeting-|draft-)/.test(key)) sessionStorage.removeItem(key)
  window.dispatchEvent(new Event('oa-identity-changed'))
}
export function clearSession() {
  epoch++
  checkedAt = -Infinity
  authState.accessToken = ''
  authState.user = null
  csrfToken = ''
  clearDrafts()
}
function accept(grant: Grant) {
  if (authState.user?.user_id !== grant.user.user_id) clearDrafts()
  authState.accessToken = grant.access_token
  applyIdentity(grant.user)
}
async function request(path: string, data?: unknown, method = 'POST'): Promise<any> {
  const response = await fetch('/api/auth/' + path, {
    method, credentials: 'include', cache: 'no-store',
    headers: { 'Content-Type': 'application/json', ...(csrfToken ? {'X-CSRF-Token': csrfToken} : {}),
      ...(authState.accessToken ? {Authorization: 'Bearer ' + authState.accessToken} : {}) },
    ...(data !== undefined ? {body: JSON.stringify(data)} : {}),
  })
  let body
  try { body = await response.json() } catch {
    throw Object.assign(new Error('登录服务暂时不可用，请稍后重试；如持续出现，请检查后端服务连接'), {status:response.status})
  }
  if (!response.ok || body.code !== '0') throw Object.assign(new Error(body.message || '认证失败，请重新登录'), {status:response.status})
  return body.data
}
async function csrf() { if (!csrfToken) csrfToken = (await request('csrf', undefined, 'GET')).token }
export async function configureAuth() {
  if (authState.initialized) return
  if (!configuration) configuration = (async () => {
    const config = await request('config', undefined, 'GET')
    if (!['mock', 'builtin'].includes(config.provider)) throw new Error('认证配置无效')
    authState.provider = config.provider
    authState.aiEnabled = config.capabilities?.ai !== false
    authState.manualOA = config.provider === 'builtin' && config.capabilities?.manual_oa === true
    if (config.provider === 'builtin') {
      try { await refreshSession() } catch { clearSession() }
    }
    authState.initialized = true
  })().finally(() => { configuration = null })
  return configuration
}
export async function refreshSession() {
  if (!refreshing) {
    const started = epoch
    refreshing = (async () => {
      try {
        await csrf()
        const grant = await request('refresh')
        if (started !== epoch) throw new Error('会话已变更')
        accept(grant)
      } catch (error) { if(started===epoch) clearSession(); throw error }
    })().finally(() => { refreshing = null })
  }
  return refreshing
}
export async function login(username: string, password: string) {
  if(closing) await closing.catch(() => {})
  if(refreshing) await refreshing.catch(() => {})
  const started = ++epoch
  await csrf()
  const grant = await request('login', {username, password})
  if(started!==epoch) throw new Error('会话已变更')
  accept(grant)
}
export async function logout() {
  clearSession()
  if(!closing) closing = (async () => {
    if(refreshing) await refreshing.catch(() => {})
    try { await csrf(); await request('logout') } finally { clearSession() }
  })().finally(() => { closing=null })
  return closing
}
export async function changePassword(current_password: string, new_password: string) {
  await csrf()
  await request('change-password', {current_password, new_password})
  clearSession()
}
export async function reloadIdentity() {
  if (authState.provider !== 'builtin' || !authState.accessToken) return
  if (checking?.epoch === epoch) return checking.promise
  const started = epoch
  const promise = (async () => {
    let user: Identity
    try { user = await request('me', undefined, 'GET') }
    catch (e: any) {
      if (e.status !== 401 || started !== epoch) throw e
      try { await refreshSession() } catch (error) { window.dispatchEvent(new Event('oa-session-expired')); throw error }
      if (started !== epoch) return
      try { user = await request('me', undefined, 'GET') }
      catch (error: any) {
        if (error.status === 401 && started === epoch) {
          clearSession()
          window.dispatchEvent(new Event('oa-session-expired'))
        }
        throw error
      }
    }
    if (started === epoch) {
      applyIdentity(user)
      checkedAt = Date.now()
      checkedEpoch = epoch
    }
  })().finally(() => { if (checking?.promise === promise) checking = null })
  checking = { epoch: started, promise }
  return promise
}
export async function syncIdentity() {
  if (checkedEpoch === epoch && Date.now() - checkedAt < 15000) return
  return reloadIdentity()
}
export function startIdentitySync() {
  const check = () => {
    if (document.visibilityState !== 'hidden') void syncIdentity().catch(() => {})
  }
  const timer = window.setInterval(check, 30000)
  window.addEventListener('focus', check)
  document.addEventListener('visibilitychange', check)
  return () => {
    window.clearInterval(timer)
    window.removeEventListener('focus', check)
    document.removeEventListener('visibilitychange', check)
  }
}
export function can(resource: string, action = 'read') {
  if (resource==='task' && action==='read' && authState.provider==='builtin' && (can('approval') || can('work_task'))) return true
  if (!authState.aiEnabled && !['organization','leave','approval','workflow','leave_balance','workflow_admin','reimbursement','ticket','ticket_handle','ticket_admin','notification','notification_admin','announcement',...(authState.provider==='builtin'?['meeting','email']:[])].includes(resource)) return false
  return authState.provider === 'mock' || !!authState.user?.permissions.some(p => p.resource === resource && p.action === action)
}
export function routeResource(path: string): string | null {
  if(path.startsWith('/oa/')) return ({delegations:'approval',announcements:'announcement',leaves:'leave',reimbursements:'reimbursement',tickets:'ticket',notifications:'notification',approvals:'approval',workflows:'workflow',balances:'leave_balance',administration:'workflow_admin'} as Record<string,string>)[path.split('/')[2]] || null
  const prefix = path.split('/')[1]
  return ({organization:'organization',meetings:'meeting','meeting-events':'meeting','meeting-texts':'meeting',documents:'document',emails:'email','work-tasks':'work_task',
    reports:'report',contracts:'contract',tasks:'task',assistant:'thread',knowledge:'knowledge',config:'policy',
    audit:'audit',operations:'operations',degradation:'operations'} as Record<string,string>)[prefix] || null
}
export function homePath() {
  return [...(authState.manualOA ? ['/oa/leaves','/oa/reimbursements','/oa/tickets','/oa/notifications','/oa/announcements','/oa/approvals','/oa/balances','/oa/workflows','/oa/administration']:[]),'/tasks','/organization','/meetings','/documents','/emails','/work-tasks','/reports','/contracts','/knowledge','/audit','/operations']
    .find(canAccessPath) || '/account'
}
export function canAccessPath(path: string) {
  if (path === '/account') return true
  if (path.startsWith('/oa/') && !authState.manualOA) return false
  if (authState.provider === 'mock') {
    if (!authState.aiEnabled) return false
    const id = localStorage.getItem('oa_current_user') || 'u_emp_001'
    if (['/config', '/knowledge', '/audit', '/operations', '/degradation'].some(p => path === p || path.startsWith(p + '/'))) return id === 'u_admin_001'
    if (path === '/approvals') return ['u_mgr_001', 'u_mgr_002'].includes(id)
    if (path.startsWith('/support')) return id === 'u_cs_001'
    return !path.startsWith('/organization')
  }
  if (!authState.user) return false
  if (!authState.aiEnabled && path.startsWith('/emails/')) return false
  if (path === '/organization/alerts' && !authState.user.roles.includes('admin')) return false
  if (path === '/oa/tickets' || path.startsWith('/oa/tickets/')) return can('ticket') || can('ticket_handle')
  const resource = routeResource(path)
  return resource !== null && can(resource)
}
export function safeRedirect(value: unknown) {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//') || /[\\\u0000-\u0020]/.test(value) || /%2f|%5c/i.test(value)) return '/tasks'
  return value.startsWith('/login') ? '/tasks' : value
}
