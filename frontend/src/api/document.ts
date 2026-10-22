import client from './client'
import type { DocumentDraft, DocumentInput, DocumentResponse, DocumentSummary, DocumentTemplate, DraftCommand, DraftDecision, DraftPage, DraftVersion } from '@/types/drafting'
export const documentApi = {
  templates(): Promise<DocumentTemplate[]> { return client.get('/documents/templates') },
  list(params = {}): Promise<DraftPage<DocumentSummary>> { return client.get('/documents', { params }) },
  get(id: string): Promise<DocumentResponse> { return client.get(`/documents/${encodeURIComponent(id)}`) },
  versions(id: string): Promise<DraftVersion<DocumentDraft>[]> { return client.get(`/documents/${encodeURIComponent(id)}/versions`) },
  create(payload: DocumentInput): Promise<DocumentResponse> { return client.post('/documents', payload) },
  generate(id: string, payload: DraftCommand): Promise<DocumentResponse> { return client.post(`/documents/${encodeURIComponent(id)}/generate`, payload) },
  retry(id: string, payload: DraftCommand): Promise<DocumentResponse> { return client.post(`/documents/${encodeURIComponent(id)}/retry`, payload) },
  save(id: string, payload: DraftCommand & { draft: DocumentDraft }): Promise<DocumentResponse> { return client.patch(`/documents/${encodeURIComponent(id)}/draft`, payload) },
  decide(id: string, payload: DraftDecision): Promise<DocumentResponse> { return client.post(`/documents/${encodeURIComponent(id)}/decisions`, payload) },
}
