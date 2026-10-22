import { reactive } from 'vue'

export interface Permission { resource: string; action: string; scope: string }
export interface Identity { user_id: string; display_name: string; roles: string[]; depts: string[]; permissions: Permission[] }
interface Grant { access_token: string; user: Identity }
export const authState = reactive({ provider: 'mock', initialized: false, aiEnabled:true, manualOA:false, user: null as Identity | null, accessToken: '' })
let configuration: Promise<void> | null = null
let refreshing: Promise<void> | null = null
let csrfToken = ''
let epoch = 0
let closing: Promise<void> | null = null
export const sessionRevision = () => epoch

function clearDrafts() {
  localStorage.removeItem('oa_assistant_draft_v1')
  for (const key of Object.keys(sessionStorage)) if (/^(oa[_-]|meeting-|draft-)/.test(key)) sessionStorage.removeItem(key)
  window.dispatchEvent(new Event('oa-identity-changed'))
}
export function clearSession() {
  epoch++
  authState.accessToken = ''
  authState.user = null
  csrfToken = ''
  clearDrafts()
}
function accept(grant: Grant) {
  if (authState.user?.user_id !== grant.user.user_id) clearDrafts()
  authState.accessToken = grant.access_token
  authState.user = grant.user
}
async function request(path: string, data?: unknown, method = 'POST'): Promise<any> {
  const response = await fetch('/api/auth/' + path, {
    method, credentials: 'include', cache: 'no-store',
    headers: { 'Content-Type': 'application/json', ...(csrfToken ? {'X-CSRF-Token': csrfToken} : {}),
      ...(authState.accessToken ? {Authorization: 'Bearer ' + authState.accessToken} : {}) },
    ...(data !== undefined ? {body: JSON.stringify(data)} : {}),
  })
  const body = await response.json()
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
  const started = epoch
  let user:Identity
  try { user=await request('me',undefined,'GET') }
  catch(e:any) {
    if(e.status!==401 || started!==epoch) throw e
    try { await refreshSession() } catch(e) { window.dispatchEvent(new Event('oa-session-expired')); throw e }
    user=await request('me',undefined,'GET')
  }
  if(started===epoch) authState.user=user
}
export function can(resource: string, action = 'read') {
  if (!authState.aiEnabled && !['organization','leave','approval','workflow','leave_balance','workflow_admin','reimbursement','ticket','ticket_handle','ticket_admin','notification','notification_admin'].includes(resource)) return false
  return authState.provider === 'mock' || !!authState.user?.permissions.some(p => p.resource === resource && p.action === action)
}
export function routeResource(path: string): string | null {
  if(path.startsWith('/oa/')) return ({leaves:'leave',reimbursements:'reimbursement',tickets:'ticket',notifications:'notification',approvals:'approval',workflows:'workflow',balances:'leave_balance',administration:'workflow_admin'} as Record<string,string>)[path.split('/')[2]] || null
  const prefix = path.split('/')[1]
  return ({organization:'organization',meetings:'meeting',documents:'document',emails:'email','work-tasks':'work_task',
    reports:'report',contracts:'contract',tasks:'task',assistant:'thread',knowledge:'knowledge',config:'policy',
    audit:'audit',operations:'operations',degradation:'operations'} as Record<string,string>)[prefix] || null
}
export function homePath() {
  return [...(authState.manualOA ? ['/oa/leaves','/oa/reimbursements','/oa/tickets','/oa/notifications','/oa/approvals','/oa/balances','/oa/workflows','/oa/administration']:[]),'/tasks','/organization','/meetings','/documents','/emails','/work-tasks','/reports','/contracts','/knowledge','/audit','/operations']
    .find(path => can(routeResource(path)!)) || '/account'
}
export function safeRedirect(value: unknown) {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//') || /[\\\u0000-\u0020]/.test(value) || /%2f|%5c/i.test(value)) return '/tasks'
  return value.startsWith('/login') ? '/tasks' : value
}
