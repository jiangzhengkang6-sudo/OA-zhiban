import client from './client'

export interface MailboxStatus {
  provisioned: boolean; authorized: boolean; can_setup: boolean; enabled: boolean
  id?: string; name?: string; address?: string; synced_at?: string; revision?: number
  can_process?: boolean; can_send?: boolean; can_manage?: boolean; user_id?: string
}
export interface PublicMessage {
  id: string; subject: string; sender: string; recipients: string[]; direction: 'incoming' | 'outgoing'
  status: string; version: number; body?: string; attachments?: { name: string }[]; analysis_id?: string
  claimed_by: string | null; claimed_by_name: string | null; created_by_name?: string; sent_by_name?: string
  sent_at: string | null; created_at: string; reply_to_id: string | null
}
export interface MailMember { user_id: string; can_process: boolean; can_send: boolean; can_manage: boolean }
export interface MailMembers { revision: number; users: { user_id: string; name: string; writable: boolean }[]; members: MailMember[] }
export interface MailDraft { subject: string; recipients: string[]; body: string; reply_to_id: string | null; idempotency_key: string; expected_version: number }
const path = (id: string) => `/public-mail/messages/${encodeURIComponent(id)}`
export const publicMailApi = {
  status(): Promise<MailboxStatus> { return client.get('/public-mail/status') },
  setup(): Promise<MailboxStatus> { return client.post('/public-mail/setup') },
  members(): Promise<MailMembers> { return client.get('/public-mail/members') },
  saveMembers(payload: { expected_revision: number; members: MailMember[] }): Promise<{ revision: number }> { return client.put('/public-mail/members', payload) },
  list(params: { folder: string; search: string; page: number }): Promise<{ items: PublicMessage[]; total: number }> { return client.get('/public-mail/messages', { params }) },
  get(id: string): Promise<PublicMessage> { return client.get(path(id)) },
  sync(): Promise<{ added: number; has_more: boolean }> { return client.post('/public-mail/sync', {}, { timeout: 180000 }) },
  save(payload: MailDraft, id?: string): Promise<PublicMessage> { return id ? client.patch(path(id), payload) : client.post('/public-mail/messages', payload) },
  action(id: string, payload: { action: string; expected_version: number; confirmed?: boolean }): Promise<PublicMessage> { return client.post(path(id) + '/actions', payload, { timeout: 90000 }) },
  import(id: string): Promise<{ email_id: string }> { return client.post(path(id) + '/import', {}, { timeout: 90000 }) },
  task(id: string): Promise<{ batch_id: string }> { return client.post(path(id) + '/task') },
}
