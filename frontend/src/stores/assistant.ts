/**
 * OA 智能体系统 - 智能助手待办状态。
 *
 * 会话可能需要跨页面执行步骤，因此将当前草稿持久化到 localStorage，
 * 避免切换导航后 AssistantView 卸载导致任务回到初始状态。
 */
import { defineStore } from 'pinia'
import type { ThreadDetail } from '@/types'
import { getCurrentUserId } from '@/api/client'
import { authState } from '@/stores/auth'

export interface ChatLine {
  role: string
  content: string
}

interface PersistedAssistantState {
  ownerId: string
  scene: string
  businessId: string
  threadId: string | null
  input: string
  detail: ThreadDetail | null
  chatLines: ChatLine[]
}

const STORAGE_KEY = 'oa_assistant_draft_v1'

function getInitialState(): PersistedAssistantState {
  const fallback: PersistedAssistantState = {
    ownerId: getCurrentUserId(),
    scene: 'faq',
    businessId: '',
    threadId: null,
    input: '',
    detail: null,
    chatLines: [],
  }

  if (typeof window === 'undefined') return fallback
  if (authState.provider === 'builtin') return fallback

  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (!stored) return fallback
    const parsed = JSON.parse(stored) as Partial<PersistedAssistantState>
    if (parsed.ownerId !== getCurrentUserId()) return fallback
    const restored = {
      ...fallback,
      ...parsed,
      chatLines: Array.isArray(parsed.chatLines) ? parsed.chatLines : [],
    }
    // 旧版本曾把 LV-OK-001 作为默认值。尚未创建任务时自动移除该误导值；
    // 已有会话则保留，避免破坏用户正在处理的待办。
    if (!restored.threadId && restored.businessId === 'LV-OK-001') {
      restored.businessId = ''
    }
    return restored
  } catch {
    // 损坏的本地草稿不应阻断应用启动，回退到空白状态即可。
    return fallback
  }
}

export const useAssistantStore = defineStore('assistant', {
  state: getInitialState,
  actions: {
    persist() {
      if (typeof window === 'undefined') return
      if (authState.provider === 'builtin') return
      const snapshot: PersistedAssistantState = {
        ownerId: getCurrentUserId(),
        scene: this.scene,
        businessId: this.businessId,
        threadId: this.threadId,
        input: this.input,
        detail: this.detail,
        chatLines: this.chatLines,
      }
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(snapshot))
    },
    resetConversation() {
      this.threadId = null
      this.detail = null
      this.chatLines.splice(0, this.chatLines.length)
      this.input = ''
      this.persist()
    },
    clearDraft() {
      this.resetConversation()
      if (typeof window !== 'undefined') window.localStorage.removeItem(STORAGE_KEY)
    },
  },
})
