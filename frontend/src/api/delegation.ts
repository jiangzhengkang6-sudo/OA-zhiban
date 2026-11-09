import client from './client'
import type { Command, Named, Outcome } from '@/types/oa'
export interface Delegation {
  id:string; delegator_id:string; delegate_id:string; delegator_name:string; delegate_name:string;
  scene:'leave'|'reimbursement'; starts_at:string; ends_at:string; revoked_at:string|null;
  reason:string; revision:number; state:'SCHEDULED'|'ACTIVE'|'EXPIRED'|'REVOKED'|'INELIGIBLE'
}
export interface DelegationInput { delegate_id:string; scene:'leave'|'reimbursement'; starts_at:string; ends_at:string; reason:string }
export const delegationApi = {
  list:():Promise<Delegation[]>=>client.get('/oa/delegations'),
  candidates:():Promise<Named[]>=>client.get('/oa/delegations/candidates'),
  create:(data:DelegationInput&{operation_id:string}):Promise<Outcome<Delegation>>=>client.post('/oa/delegations',data),
  revoke:(id:string,data:Command):Promise<Outcome<Delegation>>=>client.post(`/oa/delegations/${id}/revoke`,data),
}
