import { beforeEach, expect, it } from 'vitest'
import { authState, canAccessPath } from '@/stores/auth'
import { navigationGroups, navigationEntry } from '@/navigation'

beforeEach(() => {
  Object.assign(authState, { provider: 'builtin', aiEnabled: true, manualOA: true,
    user: { user_id: 'employee', display_name: '员工', roles: [], depts: [], permissions: [] } })
})
function grant(...resources: string[]) {
  authState.user!.permissions = resources.map(resource => ({ resource, action: 'read', scope: 'self' }))
}
it('only shows granted functions and removes empty categories', () => {
  grant('meeting', 'document')
  const groups = navigationGroups()
  expect(groups.map(group => group.label)).toEqual(['协同办公'])
  expect(groups[0]!.items.map(item => item.path)).toEqual(['/meetings', '/documents'])
  grant()
  expect(navigationGroups()).toEqual([])
})
it('keeps manual work and approval tasks when AI is disabled', () => {
  grant('meeting', 'approval', 'thread', 'document', 'announcement')
  authState.aiEnabled = false
  const paths = navigationGroups().flatMap(group => group.items.map(item => item.path))
  expect(paths).toEqual(expect.arrayContaining(['/tasks', '/oa/approvals', '/meetings', '/oa/announcements']))
  expect(paths).not.toContain('/assistant')
  expect(paths).not.toContain('/documents')
})
it('keeps the public mailbox available without AI but blocks analysis pages', () => {
  grant('email')
  authState.aiEnabled = false
  expect(canAccessPath('/emails')).toBe(true)
  expect(canAccessPath('/emails/manual-entry')).toBe(false)
  expect(canAccessPath('/emails/analysis-id')).toBe(false)
  expect(navigationGroups().flatMap(group => group.items.map(item => item.path))).toContain('/emails')
})
it('uses the most specific page for nested links and meeting aliases', () => {
  grant('knowledge', 'policy', 'organization', 'meeting')
  authState.user!.roles = ['admin']
  expect(navigationEntry('/knowledge/sources/source/versions/version')?.item.path).toBe('/knowledge/sources')
  expect(navigationEntry('/config/policies')?.item.path).toBe('/config/policies')
  expect(navigationEntry('/organization/alerts')?.item.path).toBe('/organization/alerts')
  expect(navigationEntry('/meeting-events/event')?.item.path).toBe('/meetings')
})
it('allows ticket handlers but not ungranted organization administrators', () => {
  grant('ticket_handle')
  expect(canAccessPath('/oa/tickets/item')).toBe(true)
  expect(navigationGroups().flatMap(g => g.items).some(i => i.path === '/oa/tickets')).toBe(true)
  grant('organization')
  expect(canAccessPath('/organization/alerts')).toBe(false)
  expect(navigationGroups().flatMap(g => g.items).some(i => i.path === '/organization/alerts')).toBe(false)
})
