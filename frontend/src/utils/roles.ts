import { authState } from '@/stores/auth'
export const demoUsers = [
  { id: 'u_emp_001', name: '张三 · 员工', roles: ['employee'] },
  { id: 'u_mgr_001', name: '李四 · 一级审批', roles: ['employee', 'approver'] },
  { id: 'u_mgr_002', name: '王五 · 二级审批', roles: ['employee', 'approver'] },
  { id: 'u_cs_001', name: '赵六 · 客服', roles: ['employee', 'support'] },
  { id: 'u_admin_001', name: '管理员', roles: ['admin'] },
]
// 开发目录只用于菜单提示，资源与操作权限由后端重新验证。
export function hasRole(userId: string, role: string) {
  if (authState.provider === 'builtin') return authState.user?.user_id === userId && authState.user.roles.includes(role)
  return demoUsers.find(user => user.id === userId)?.roles.includes(role) || false
}
