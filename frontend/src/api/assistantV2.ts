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
  report_type: 'daily' | 'weekly'
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

export const assistantV2Api = {
  overview(date?: string): Promise<AssistantOverview> {
    return client.post('/assistant-v2/overview', { date: date || null })
  },
  searchKnowledge(query: string, topK = 5): Promise<KnowledgeSearchResponse> {
    return client.post('/assistant-v2/knowledge/search', { query, top_k: topK })
  },
  createReportDraft(reportType: 'daily' | 'weekly', date?: string): Promise<ReportDraftResponse> {
    return client.post('/assistant-v2/reports/draft', {
      report_type: reportType,
      date: date || null,
    })
  },
  parseDraft(text: string, draftType: 'auto' | 'task' | 'meeting' = 'auto'): Promise<DraftParseResponse> {
    return client.post('/assistant-v2/drafts/parse', { text, draft_type: draftType })
  },
}

