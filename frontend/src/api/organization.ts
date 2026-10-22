import client from './client'
import type { Permission } from '@/stores/auth'
export interface Department { id: string; name: string; parent_id: string | null; enabled: boolean }
export interface Position { id: string; name: string; enabled: boolean }
export interface Member { id: string; username: string; display_name: string; status: string; handoff_pending: boolean; department_id: string | null; position_id: string | null; manager_id: string | null; role_ids: string[] }
export interface Role { id: string; code: string; name: string; permissions: Permission[] }
export interface Organization { users: Member[]; departments: Department[]; positions: Position[]; roles: Role[]; resources: string[] }
export const organizationApi = {
  overview(): Promise<Organization> { return client.get('/organization') },
  save(kind: string, payload: unknown, id?: string): Promise<unknown> { return id ? client.put(`/organization/${kind}/${id}`, payload) : client.post(`/organization/${kind}`, payload) },
  resetPassword(id: string, password: string): Promise<unknown> { return client.post(`/organization/users/${id}/reset-password`, {password}) },
}
