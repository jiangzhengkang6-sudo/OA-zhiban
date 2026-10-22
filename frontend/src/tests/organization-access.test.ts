import { it, expect } from 'vitest'
import { authState, can, routeResource, clearSession } from '@/stores/auth'

it('正式菜单只使用当前权限，组织直达需组织权限', () => {
  authState.provider = 'builtin'
  authState.user = {user_id:'employee',display_name:'员工',roles:['employee'],depts:[],permissions:[{resource:'meeting',action:'read',scope:'self'}]}
  expect(can('meeting')).toBe(true)
  expect(can('organization')).toBe(false)
  expect(routeResource('/organization')).toBe('organization')
  expect(routeResource('/config/policies')).toBe('policy')
  expect(routeResource('/leaves')).toBeNull()
  clearSession()
})
