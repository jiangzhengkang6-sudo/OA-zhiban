<script setup lang="ts">
/**
 * 统一智能助手 V3。
 *
 * 单一对话入口统一调度知识、任务、会议、报表、工单和请假技能；
 * 写入类动作继续采用草稿、权限复核和用户确认。
 */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ChatDotRound,
  Check,
  CopyDocument,
  Promotion,
  Refresh,
  Warning,
} from '@element-plus/icons-vue'
import { assistantV3Api, type AssistantV3ChatResponse, type V3Skill } from '@/api/assistantV3'
import { assistantV2Api, type SavedAssistantDraft } from '@/api/assistantV2'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  result?: AssistantV3ChatResponse
}

const emit = defineEmits<{
  legacyRouted: [result: AssistantV3ChatResponse]
}>()

const router = useRouter()
const input = ref('')
const selectedSkill = ref<V3Skill>('auto')
const busy = ref(false)
const messages = ref<ChatMessage[]>([
  {
    role: 'assistant',
    content:
      '你好，我是统一智能助手。可以直接问制度、生成日报、安排任务或会议，也可以描述电脑故障和请假需求；高影响操作我会先生成草稿并请你确认。',
  },
])

const skillOptions: Array<{ value: V3Skill; label: string }> = [
  { value: 'auto', label: '自动判断' },
  { value: 'knowledge', label: '知识检索' },
  { value: 'task', label: '任务技能' },
  { value: 'meeting', label: '会议技能' },
  { value: 'report', label: '日报/周报' },
  { value: 'ticket', label: '工单技能' },
  { value: 'leave', label: '请假技能' },
  { value: 'overview', label: '工作总览' },
]

const quickPrompts = [
  '给我今天的工作总览',
  '帮我生成一份日报草稿',
  '请假申请需要准备哪些信息？',
  '我的电脑无法开机，帮我报修',
]

const savedDrafts = ref<Record<number, SavedAssistantDraft>>({})
const confirmFlags = ref<Record<number, { metadata: boolean; risk: boolean; operationId: string }>>({})

const canSend = computed(() => !busy.value && !!input.value.trim())

async function send(text = input.value.trim(), skill: V3Skill = selectedSkill.value) {
  if (!text || busy.value) return
  busy.value = true
  messages.value.push({ role: 'user', content: text })
  input.value = ''
  try {
    const history = messages.value
      .slice(-20)
      .map(item => ({ role: item.role, content: item.content }))
    const result = await assistantV3Api.chat({ message: text, history, requested_skill: skill })
    messages.value.push({ role: 'assistant', content: result.reply, result })
    if (result.legacy) emit('legacyRouted', result)
  } finally {
    busy.value = false
    selectedSkill.value = 'auto'
  }
}

function draftRows(result: AssistantV3ChatResponse): Array<{ label: string; value: string }> {
const draft = result.draft_proposal?.draft || {}
if (result.draft_proposal?.draft_type === 'schedule') {
return [
  { label: '周期事项', value: draft.title || '—' },
  { label: '执行频率', value: draft.frequency || '—' },
  { label: '执行时间', value: draft.run_time || '—' },
  { label: '结束条件', value: draft.ends_at || draft.max_occurrences || '长期有效' },
]
}
return [
  { label: '标题', value: draft.title || '—' },
  { label: '负责人', value: draft.assignee_name || draft.assignee_id || '待选择' },
  { label: '时间', value: draft.due_at || draft.starts_at || '待补充' },
  { label: '优先级', value: draft.priority || '普通' },
  { label: '操作', value: draft.operation || '创建' },
]
}

async function saveProposal(index: number, result: AssistantV3ChatResponse) {
  if (!result.draft_proposal) return
  const proposal = result.draft_proposal
  const saved = await assistantV2Api.saveDraft(proposal.draft_type, proposal.draft)
  savedDrafts.value[index] = saved
  confirmFlags.value[index] = {
    metadata: false,
    risk: false,
    operationId: globalThis.crypto.randomUUID(),
  }
  ElMessage.success('草稿已保存，尚未写入正式数据。')
}

async function confirmDraft(index: number) {
  const saved = savedDrafts.value[index]
  const flags = confirmFlags.value[index]
  if (!saved || !flags || !flags.metadata) return
  const updated = await assistantV2Api.confirmDraft(saved.id, {
    operation_id: flags.operationId,
    metadata_confirmed: flags.metadata,
    risk_acknowledged: flags.risk,
  })
  savedDrafts.value[index] = updated
  ElMessage.success('已确认并写入。')
}

async function cancelDraft(index: number) {
  const saved = savedDrafts.value[index]
  if (!saved) return
  savedDrafts.value[index] = await assistantV2Api.cancelDraft(saved.id, '用户在统一助手中取消草稿')
}

async function copyText(text: string) {
  await navigator.clipboard.writeText(text)
  ElMessage.success('已复制。')
}

async function followUp(text: string) {
  const pathMatch = text.match(/([A-Za-z]:)?\/[\w/-]+/)
  const candidate = pathMatch?.[0] || ''
  if (candidate.startsWith('/')) {
    await router.push(candidate)
    return
  }
  await send(text, 'auto')
}

function confidenceLabel(value: string) {
  return { high: '高', medium: '中', low: '低' }[value] || value
}

function similarity(value: unknown) {
  if (typeof value !== 'number') return '—'
  return `${Math.round(value * 100)}%`
}
</script>

<template>
  <section class="assistant-v3">
    <header class="v3-hero">
      <div>
        <p class="eyebrow"><el-icon><ChatDotRound /></el-icon> 统一智能助手</p>
        <h2>一个入口，调度全部 OA 技能</h2>
        <p>知识、任务、会议、报表、工单、请假会按当前目标自动编排；写入操作必须确认。</p>
      </div>
      <el-button :icon="Refresh" @click="messages = messages.slice(0, 1)">清空对话</el-button>
    </header>

    <div class="quick-prompts">
      <el-button
        v-for="prompt in quickPrompts"
        :key="prompt"
        size="small"
        round
        @click="send(prompt, 'auto')"
      >{{ prompt }}</el-button>
    </div>

    <div class="conversation" aria-live="polite">
      <article
        v-for="(message, index) in messages"
        :key="index"
        class="message-row"
        :class="message.role"
      >
        <div class="avatar">{{ message.role === 'user' ? '我' : 'AI' }}</div>
        <div class="message-card">
          <p class="message-text">{{ message.content }}</p>

          <template v-if="message.result">
            <div class="meta-line">
              <el-tag size="small" effect="plain">{{ message.result.skill }}</el-tag>
              <span>置信度：{{ confidenceLabel(message.result.confidence) }}</span>
            </div>

            <el-alert
              :title="message.result.safety_notice"
              type="info"
              :closable="false"
              class="safety-alert"
            />

            <div v-if="message.result.citations.length" class="citations">
              <h4>引用资料（标准模板试运行）</h4>
              <details
                v-for="(item, citationIndex) in message.result.citations"
                :key="item.chunk_id || citationIndex"
                class="citation"
              >
                <summary>
                  <strong>{{ item.title || item.source_location || '资料片段' }}</strong>
                  <span>相似度 {{ similarity(item.similarity) }} · 版本 {{ item.version }}</span>
                </summary>
                <p>{{ item.content }}</p>
                <small>{{ item.source_location }}</small>
              </details>
            </div>

            <div v-if="message.result.draft_proposal" class="action-panel">
              <header>
                <h4>{{ message.result.draft_proposal.draft_type }} 草稿</h4>
                <el-tag size="small" type="success">
                  可信度 {{ confidenceLabel(message.result.draft_proposal.confidence) }}
                </el-tag>
              </header>
              <el-alert
                v-for="warning in message.result.draft_proposal.warnings"
                :key="warning"
                :title="warning"
                type="warning"
                :closable="false"
              />
              <el-alert
                v-if="message.result.draft_proposal.missing_required.length"
                :title="`还需补充：${message.result.draft_proposal.missing_required.join('、')}`"
                type="warning"
                :closable="false"
              />
              <dl class="draft-rows">
                <template v-for="row in draftRows(message.result)" :key="row.label">
                  <dt>{{ row.label }}</dt>
                  <dd>{{ row.value }}</dd>
                </template>
              </dl>

              <template v-if="savedDrafts[index]">
                <div class="saved-draft" :class="savedDrafts[index].status.toLowerCase()">
                  <el-icon><Check v-if="savedDrafts[index].status === 'CONFIRMED'" /><Warning v-else /></el-icon>
                  <span>
                    草稿状态：
                    {{
                      {
                        DRAFT: '待确认',
                        CONFIRMED: '已写入',
                        CANCELLED: '已取消',
                      }[savedDrafts[index].status]
                    }}
                  </span>
                </div>
                <template v-if="savedDrafts[index].status === 'DRAFT'">
                  <label class="confirm-check">
                    <input v-model="confirmFlags[index].metadata" type="checkbox" />
                    我已核对内容、人员、时间和权限
                  </label>
                  <label v-if="savedDrafts[index].warnings.length" class="confirm-check">
                    <input v-model="confirmFlags[index].risk" type="checkbox" />
                    我已知晓跨部门、高优先级或敏感事项风险
                  </label>
                  <div class="action-buttons">
                    <el-button @click="cancelDraft(index)">取消草稿</el-button>
                    <el-button
                      type="primary"
                      :disabled="!confirmFlags[index]?.metadata"
                      @click="confirmDraft(index)"
                    >确认并写入</el-button>
                  </div>
                </template>
                <router-link
                  v-if="savedDrafts[index].result.task_id"
                  :to="`/work-tasks/${savedDrafts[index].result.task_id}`"
                >查看任务</router-link>
                <router-link
                  v-if="savedDrafts[index].result.meeting_id"
                  :to="`/meeting-events/${savedDrafts[index].result.meeting_id}`"
                >查看会议</router-link>
              </template>
              <el-button
                v-else
                type="primary"
                plain
                @click="saveProposal(index, message.result)"
              >保存为可确认草稿</el-button>
            </div>

            <div v-if="message.result.report" class="action-panel">
              <header>
                <h4>{{ message.result.report.title }}</h4>
                <el-button text :icon="CopyDocument" @click="copyText(message.result.report.markdown)">复制</el-button>
              </header>
              <pre class="markdown-preview">{{ message.result.report.markdown }}</pre>
            </div>

            <div v-if="message.result.overview" class="overview-grid">
              <article v-for="section in message.result.overview.sections" :key="section.key">
                <strong>{{ section.count }}</strong>
                <span>{{ section.title }}</span>
                <template v-for="card in section.cards.slice(0, 2)" :key="card.id">
                  <router-link v-if="card.link" :to="card.link">{{ card.title }}</router-link>
                </template>
              </article>
            </div>

            <div v-if="message.result.legacy" class="legacy-notice">
              <el-icon><Promotion /></el-icon>
              <span>已调度 {{ message.result.legacy.scene }} 专项技能，请在下方“技能执行与确认”卡片中处理。</span>
            </div>

            <div v-if="message.result.follow_ups.length" class="followups">
              <el-button
                v-for="item in message.result.follow_ups"
                :key="item"
                size="small"
                @click="followUp(item)"
              >{{ item }}</el-button>
            </div>
          </template>
        </div>
      </article>
    </div>

    <footer class="composer">
      <el-select v-model="selectedSkill" class="skill-select" aria-label="选择技能">
        <el-option v-for="item in skillOptions" :key="item.value" :value="item.value" :label="item.label" />
      </el-select>
      <el-input
        v-model="input"
        maxlength="3000"
        placeholder="直接描述目标，例如：明天下午3点和李四开项目复盘会"
        @keyup.enter="send()"
      />
      <el-button type="primary" :disabled="!canSend" :loading="busy" @click="send()">发送</el-button>
    </footer>
  </section>
</template>

<style scoped>
.assistant-v3 {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.v3-hero {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  padding: 22px;
  border: 1px solid #d7e4e0;
  border-radius: 16px;
  background: linear-gradient(135deg, #f1faf7, #ffffff);
}
.eyebrow {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0 0 8px;
  color: #137a63;
  font-weight: 700;
}
.v3-hero h2 {
  margin: 0 0 8px;
  font-size: 24px;
}
.v3-hero p:last-child {
  margin: 0;
  color: #5e6b67;
}
.quick-prompts,
.followups,
.action-buttons {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.conversation {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.message-row {
  display: flex;
  gap: 10px;
}
.message-row.user {
  justify-content: flex-end;
}
.avatar {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: #e8f4f0;
  color: #137a63;
  font-size: 12px;
  font-weight: 700;
  flex: 0 0 auto;
}
.message-row.user .avatar {
  background: #e7f0ff;
  color: #2264c2;
}
.message-card {
  max-width: min(860px, 88%);
  padding: 14px 16px;
  border: 1px solid #dce5e2;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 8px 28px rgba(22, 82, 68, 0.06);
}
.message-row.user .message-card {
  background: #f5f9ff;
}
.message-text {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.8;
}
.meta-line {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
  color: #6c7773;
  font-size: 12px;
}
.safety-alert,
.action-panel,
.citations,
.legacy-notice {
  margin-top: 12px;
}
.citation {
  margin-top: 8px;
  padding: 10px;
  border: 1px solid #e1e8e6;
  border-radius: 10px;
  background: #fbfdfc;
}
.citation summary {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  cursor: pointer;
  color: #24423a;
}
.citation p {
  margin: 10px 0 6px;
  color: #41504c;
  line-height: 1.8;
}
.citation small {
  color: #7a8582;
}
.action-panel {
  padding: 14px;
  border: 1px solid #d9e7e3;
  border-radius: 12px;
  background: #f8fbfa;
}
.action-panel > header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}
.draft-rows {
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: 8px 12px;
}
.draft-rows dt {
  color: #697672;
}
.draft-rows dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.saved-draft {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 10px 0;
}
.saved-draft.confirmed {
  color: #137a45;
}
.confirm-check {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 8px 0;
}
.markdown-preview {
  max-height: 420px;
  overflow: auto;
  padding: 14px;
  border-radius: 10px;
  background: #fff;
  white-space: pre-wrap;
  line-height: 1.8;
}
.overview-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-top: 12px;
}
.overview-grid article {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px;
  border-radius: 10px;
  background: #f4f8f7;
}
.overview-grid strong {
  font-size: 24px;
  color: #137a63;
}
.legacy-notice {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #8a5a12;
}
.composer {
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr) 88px;
  gap: 10px;
  align-items: center;
  padding: 12px;
  border: 1px solid #d9e7e3;
  border-radius: 14px;
  background: #fff;
  position: sticky;
  bottom: 0;
}
@media (max-width: 900px) {
  .overview-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .composer {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 600px) {
  .v3-hero {
    flex-direction: column;
  }
  .message-card {
    max-width: 100%;
  }
}
</style>
