import client from './client'
import type { Permission } from '@/stores/auth'
export interface Department { id: string; name: string; parent_id: string | null; enabled: boolean }
export interface Position { id: string; name: string; enabled: boolean }
export interface Member { id: string; username: string; display_name: string; status: string; handoff_pending: boolean; version: number; department_id: string | null; position_id: string | null; manager_id: string | null; role_ids: string[] }
export interface Role { id: string; code: string; name: string; permissions: Permission[] }
export interface Organization { users: Member[]; departments: Department[]; positions: Position[]; roles: Role[]; resources: string[] }
export interface OperationalCheck { key:string; name:string; status:'PASS'|'WARN'|'FAIL'; message:string; count?:number; last_success_at?:string }
export interface OperationalIncident { id:string; key:string; name:string; message:string; opened_at:string; last_seen_at:string; resolved_at:string|null; deliveries:Record<string,{status:string;attempted_at:string;attempt_count:number}> }
export interface OperationalSnapshot { state:'running'|'stale'|'unconfigured'|'invalid'; checked_at:string|null; checks:OperationalCheck[]; incidents:OperationalIncident[]; delivery_enabled:boolean; channels?:string[] }
export type HandoffKind = 'workflow' | 'ticket' | 'work_task' | 'ticket_rule' | 'reporting_line'
export interface HandoffItem {kind:HandoffKind; id:string; revision:number; title:string; kind_name:string; link:string; can_transfer:boolean; blocked_reason:string}
export interface MemberHandoff {member:Member; counts:Record<HandoffKind,number>; total:number; items:HandoffItem[]; restricted_count:number; history:{id:number;action:string;reason:string;created_at:string}[]}
export const organizationApi = {
  alerts(): Promise<OperationalSnapshot> { return client.get('/organization/operational-alerts') },
  overview(): Promise<Organization> { return client.get('/organization') },
  save(kind: string, payload: unknown, id?: string): Promise<unknown> { return id ? client.put(`/organization/${kind}/${id}`, payload) : client.post(`/organization/${kind}`, payload) },
  resetPassword(id: string, password: string): Promise<unknown> { return client.post(`/organization/users/${id}/reset-password`, {password}) },
  batch(payload: unknown): Promise<Member[]> { return client.post('/organization/users/batch', payload) },
  handoff(id:string):Promise<MemberHandoff> { return client.get(`/organization/users/${id}/handoff`) },
  handoffCandidates(id:string,item:HandoffItem):Promise<{id:string;name:string}[]> {return client.get(`/organization/users/${id}/handoff/candidates`,{params:{kind:item.kind,item_id:item.id}})},
  transfer(id:string,payload:unknown):Promise<{user_id:string;remaining:number}> {return client.post(`/organization/users/${id}/handoff/transfer`,payload)},
  completeHandoff(id:string,payload:unknown):Promise<Member> {return client.post(`/organization/users/${id}/handoff/complete`,payload)},
}
