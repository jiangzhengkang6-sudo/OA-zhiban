/**
 * OA 智能体系统 MVP - HTTP 客户端封装。
 *
 * 基于 axios，统一注入 Mock 登录态（Authorization）、解包统一响应、
 * 透传 trace_id，并对错误统一提示。
 */
import axios, { type AxiosInstance } from 'axios'
import { ElMessage } from 'element-plus'
import { authState, refreshSession, clearSession, sessionRevision } from '@/stores/auth'

/** 当前 Mock 登录用户（存 localStorage，可在配置页切换以演示不同角色） */
const CURRENT_USER_KEY = 'oa_current_user'

export function getCurrentUserId(): string {
  if (authState.provider === 'builtin') return authState.user?.user_id || ''
  return localStorage.getItem(CURRENT_USER_KEY) || 'u_emp_001'
}

export function setCurrentUserId(userId: string): void {
  if (authState.provider === 'builtin') return
  localStorage.setItem(CURRENT_USER_KEY, userId)
}

/** axios 实例 */
const client: AxiosInstance = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

/** 请求拦截器：注入 Mock 登录态与 trace_id */
client.interceptors.request.use((config) => {
  if (authState.provider === 'builtin') {
    ;(config as any)._identityRevision = sessionRevision()
    if (authState.accessToken) config.headers['Authorization'] = `Bearer ${authState.accessToken}`
  } else config.headers['Authorization'] = `Bearer mock:${getCurrentUserId()}`
  return config
})

/** 响应拦截器：解包统一响应并处理错误 */
client.interceptors.response.use(
  (response) => {
    if ((response.config as any)._identityRevision !== undefined && (response.config as any)._identityRevision !== sessionRevision()) return Promise.reject(new Error('会话已变更'))
    const body = response.data
    if (body && typeof body.code === 'string' && body.code !== '0') {
      ElMessage.error(body.message || '请求失败')
      return Promise.reject(new Error(body.message))
    }
    // 解包 data 字段
    return body && 'data' in body ? body.data : body
  },
  async (error) => {
    const original = error.config
    if(original?._identityRevision !== undefined && original._identityRevision !== sessionRevision()) return Promise.reject(new Error('会话已变更'))
    if (authState.provider === 'builtin' && error?.response?.status === 401 && original && !original._authRetried) {
      original._authRetried = true
      try {
        if(!authState.accessToken || original.headers?.Authorization === `Bearer ${authState.accessToken}`) await refreshSession()
        return await client.request(original)
      }
      catch { clearSession(); window.dispatchEvent(new Event('oa-session-expired')) }
    }
    if (authState.provider === 'builtin' && error?.response?.status === 403) {
      window.dispatchEvent(new Event('oa-permissions-changed'))
    }
    const msg = error?.response?.data?.message || error.message || '网络错误'
    ElMessage.error(msg)
    return Promise.reject(error)
  },
)

export default client
