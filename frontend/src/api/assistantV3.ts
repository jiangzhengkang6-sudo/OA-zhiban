/** 统一智能助手 V3 接口访问层。 */

import client from './client'
import type { ThreadDetail } from '@/types'
import type {
  DraftParseResponse,
  KnowledgeSearchResponse,
  AssistantOverview,
  ReportDraftResponse,
  SavedAssistantDraft,
} from './assistantV2'

export type V3Skill =
  | 'auto'
  | 'knowledge'
  | 'task'
  | 'meeting'
  | 'report'
  | 'ticket'
  | 'leave'
  | 'overview'
  | 'human'

export type V3Confidence = 'high' | 'medium' | 'low'

export interface V3LegacySkill {
  scene: 'ticket' | 'leave'
  thread_id: string
  detail: ThreadDetail
}

export interface AssistantV3ChatResponse {
  reply: string
  skill: Exclude<V3Skill, 'auto'>
  confidence: V3Confidence
  citations: Array<Record<string, any>>
  draft_proposal: DraftParseResponse | null
  report: ReportDraftResponse | null
  overview: AssistantOverview | null
  knowledge: KnowledgeSearchResponse | null
  legacy: V3LegacySkill | null
  follow_ups: string[]
  safety_notice: string
  generated_at: string
}

export interface AssistantV3ChatRequest {
  message: string
  history: Array<{ role: 'user' | 'assistant'; content: string }>
  requested_skill: V3Skill
}

export type { SavedAssistantDraft }

export const assistantV3Api = {
  chat(payload: AssistantV3ChatRequest): Promise<AssistantV3ChatResponse> {
    return client.post('/assistant-v3/chat', payload)
  },
}

