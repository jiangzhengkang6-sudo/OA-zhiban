export interface DraftCheck { code: string; severity: 'error' | 'warning'; message: string }
export interface DraftCommand { idempotency_key: string; expected_version: number | null }
export interface DraftDecision extends DraftCommand {
  action: 'confirm' | 'reject' | 'regenerate'; reason?: string | null
  metadata_confirmed: boolean; warnings_acknowledged: boolean; secondary_confirmed?: boolean
}
export interface DraftSummary {
  thread_id: string; subject: string; status: string; version: number | null; available_actions: string[]
  created_at?: string; updated_at?: string
}
export interface DraftRecord<D> extends DraftSummary {
  draft: D | null; checks: DraftCheck[]; external_writes: false
  error?: { code: string; trace_id: string; message: string } | null
  confirmation?: Record<string, unknown> | null
}
export interface DraftVersion<D> { version: number; draft: D; checks: DraftCheck[]; edited_by: string | null; created_at: string }
export interface DraftPage<S> { items: S[]; total: number; page: number; page_size: number }
export interface DocumentTemplate { id: string; kind: string; name: string; version: number; sections: string[] }
export interface DocumentDraft { body: string; source_refs: string[] }
export interface DocumentInput {
  template_id: string; subject: string; recipient: string; deadline: string; basis: string; key_points: string
  classification: string; distribution: string; use_knowledge: boolean; idempotency_key?: string
}
export interface DocumentSummary extends DraftSummary { document_id: string }
export interface DocumentResponse extends DraftRecord<DocumentDraft>, DocumentSummary {
  template: DocumentTemplate; recipient: string; deadline: string; classification: string; distribution: string
  sources: { ref: string; kind: string; title: string; content: string; content_hash: string; source_location: string
    source_id?: string; version_id?: string; version?: number }[]
}
export interface EmailAttachment { name: string; sensitive: boolean }
export interface EmailInput {
  subject: string; sender: string; recipients: string[]; body: string; external_contact: boolean
  attachments: EmailAttachment[]; idempotency_key?: string
}
export interface EmailActionItem {
  title: string; assignee_candidate: string | null; due_at_candidate: string | null
  source_refs: string[]; needs_confirmation: true
}
export interface EmailDraft {
  category: 'work' | 'approval' | 'meeting' | 'notification' | 'other'; priority: 'high' | 'normal' | 'low'
  summary: string; action_items: EmailActionItem[]; reply_subject: string; reply_body: string; source_refs: string[]
}
export interface EmailSummary extends DraftSummary { email_id: string }
export interface EmailResponse extends DraftRecord<EmailDraft>, EmailSummary {
  sender: string; recipients: string[]; body: string; external_contact: boolean; attachments: EmailAttachment[]
  sources: { ref: string; text: string; locator: string; content_hash: string }[]
  secondary_confirmation_required: boolean
}
