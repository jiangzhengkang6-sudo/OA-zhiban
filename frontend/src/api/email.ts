import client from './client'
import type { EmailDraft, EmailInput, EmailResponse, EmailSummary, DraftCommand, DraftDecision, DraftPage, DraftVersion } from '@/types/drafting'
export const emailApi = {
  list(params = {}): Promise<DraftPage<EmailSummary>> { return client.get('/emails', { params }) },
  get(id: string): Promise<EmailResponse> { return client.get(`/emails/${encodeURIComponent(id)}`) },
  versions(id: string): Promise<DraftVersion<EmailDraft>[]> { return client.get(`/emails/${encodeURIComponent(id)}/versions`) },
  create(payload: EmailInput): Promise<EmailResponse> { return client.post('/emails', payload) },
  analyze(id: string, payload: DraftCommand): Promise<EmailResponse> { return client.post(`/emails/${encodeURIComponent(id)}/analyze`, payload) },
  retry(id: string, payload: DraftCommand): Promise<EmailResponse> { return client.post(`/emails/${encodeURIComponent(id)}/retry`, payload) },
  save(id: string, payload: DraftCommand & { draft: EmailDraft }): Promise<EmailResponse> { return client.patch(`/emails/${encodeURIComponent(id)}/draft`, payload) },
  decide(id: string, payload: DraftDecision): Promise<EmailResponse> { return client.post(`/emails/${encodeURIComponent(id)}/decisions`, payload) },
}
