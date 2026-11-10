/** 统一 OA 智能助手 V2 接口访问层。 */

import client from './client'

export interface AssistantV2Card {
  id: string
  type: string
  title: string
  subtitle?: string
  description?: string
  status?: string
  priority?: string
  time?: string | null
  link?: string
  metadata?: Record<string, any>
}

export interface AssistantV2Section {
  key: string
  title: string
  available: boolean
  count: number
  message?: string
  cards: AssistantV2Card[]
}

export interface AssistantOverview {
  generated_at: string
  date: string
  weekday: string
  summary: string
  sections: AssistantV2Section[]
  safety_notice: string
}

export interface KnowledgeSearchResult {
  chunk_id: string
  version_id?: string
  source_id?: string
  version?: number
  content: string
  source_location?: string
  similarity?: number
  title?: string
}

export interface KnowledgeSearchResponse {
  query: string
  results: KnowledgeSearchResult[]
  answer_preview: string
  evidence_notice: string
}

export interface ReportDraftResponse {
  title: string
  report_type: 'daily' | 'weekly' | 'monthly'
  period_start: string
  period_end: string
  markdown: string
  sources: Array<Record<string, any>>
  warnings: string[]
}

export interface DraftParseResponse {
  draft_type: 'task' | 'meeting'
  confidence: 'high' | 'medium' | 'low'
  draft: Record<string, any>
  missing_required: string[]
  warnings: string[]
  confirmation_notice: string
}

export interface SavedAssistantDraft {
  id: string
  draft_type: 'task' | 'meeting'
  status: 'DRAFT' | 'CONFIRMED' | 'CANCELLED'
  payload: Record<string, any>
  missing_required: string[]
  warnings: string[]
  result: Record<string, any>
  notes?: string
  created_at: string
  updated_at: string
}

export interface TaskActionDraft {
  operation: 'complete' | 'cancel'
  task_id: string
  expected_version: number
  comment?: string
}

export interface MeetingActionDraft {
  operation: 'cancel'
  meeting_id: string
  expected_revision: number
  reason: string
}

export interface AssistantExistingItem {
  id: string
  title: string
  status: string
  version: number
  time?: string | null
  available_actions: string[]
}

export interface AssistantPersonOption {
  id: string
  display_name: string
  department_id?: string | null
}

export const assistantV2Api = {
  overview(date?: string): Promise<AssistantOverview> {
    return client.post('/assistant-v2/overview', { date: date || null })
  },
  searchKnowledge(query: string, topK = 5): Promise<KnowledgeSearchResponse> {
    return client.post('/assistant-v2/knowledge/search', { query, top_k: topK })
  },
  createReportDraft(reportType: 'daily' | 'weekly' | 'monthly', date?: string): Promise<ReportDraftResponse> {
    return client.post('/assistant-v2/reports/draft', {
      report_type: reportType,
      date: date || null,
    })
  },
  parseDraft(text: string, draftType: 'auto' | 'task' | 'meeting' = 'auto'): Promise<DraftParseResponse> {
    return client.post('/assistant-v2/drafts/parse', { text, draft_type: draftType })
  },
  peopleOptions(draftType: 'task' | 'meeting'): Promise<{ users: AssistantPersonOption[] }> {
    return client.get('/assistant-v2/options', { params: { draft_type: draftType } })
  },
  existingItems(draftType: 'task' | 'meeting'): Promise<AssistantExistingItem[]> {
    return client.get('/assistant-v2/items', { params: { draft_type: draftType } })
  },
  saveDraft(draftType: 'task' | 'meeting', draft: Record<string, any>): Promise<SavedAssistantDraft> {
    return client.post('/assistant-v2/drafts', { draft_type: draftType, draft })
  },
  listDrafts(): Promise<SavedAssistantDraft[]> {
    return client.get('/assistant-v2/drafts')
  },
  getDraft(id: string): Promise<SavedAssistantDraft> {
    return client.get(`/assistant-v2/drafts/${id}`)
  },
  confirmDraft(
    id: string,
    payload: {
      operation_id: string
      metadata_confirmed: boolean
      risk_acknowledged: boolean
    },
  ): Promise<SavedAssistantDraft> {
    return client.post(`/assistant-v2/drafts/${id}/confirm`, payload)
  },
  cancelDraft(id: string, reason = ''): Promise<SavedAssistantDraft> {
    return client.post(`/assistant-v2/drafts/${id}/cancel`, { reason })
  },
}

