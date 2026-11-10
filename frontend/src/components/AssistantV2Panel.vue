<script setup lang="ts">
/**
 * 统一 OA 智能助手 V2 第一阶段面板。
 *
 * 提供今日总览、统一知识检索、日报/周报草稿、自然语言任务/会议草稿。
 * 本组件不直接执行高影响写操作。
 */

import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Search, Document, MagicStick, CopyDocument } from '@element-plus/icons-vue'
import {
  assistantV2Api,
  type AssistantOverview,
  type DraftParseResponse,
  type KnowledgeSearchResponse,
  type ReportDraftResponse,
} from '@/api/assistantV2'

const overview = ref<AssistantOverview | null>(null)
const overviewLoading = ref(false)
const knowledgeQuery = ref('')
const knowledgeLoading = ref(false)
const knowledgeResult = ref<KnowledgeSearchResponse | null>(null)
const reportLoading = ref(false)
const reportResult = ref<ReportDraftResponse | null>(null)
const draftText = ref('')
const draftType = ref<'auto' | 'task' | 'meeting'>('auto')
const draftLoading = ref(false)
const draftResult = ref<DraftParseResponse | null>(null)

const statCards = computed(() => {
  const sections = overview.value?.sections || []
  return [
    { key: 'tasks', title: '今日待办', count: sections.find(s => s.key === 'tasks')?.count || 0, tone: 'teal' },
    { key: 'meetings', title: '今日会议', count: sections.find(s => s.key === 'meetings')?.count || 0, tone: 'blue' },
    { key: 'notifications', title: '未读通知', count: sections.find(s => s.key === 'notifications')?.count || 0, tone: 'amber' },
    { key: 'emails', title: '待处理邮件', count: sections.find(s => s.key === 'emails')?.count || 0, tone: 'violet' },
  ]
})

function formatTime(value?: string | null, dateStyle: 'time' | 'datetime' = 'time') {
  if (!value) return '—'
  return new Date(value).toLocaleString('zh-CN', {
    dateStyle: dateStyle === 'datetime' ? 'short' : undefined,
    timeStyle: 'short',
    hour12: false,
  } as Intl.DateTimeFormatOptions)
}

async function loadOverview() {
  overviewLoading.value = true
  try {
    overview.value = await assistantV2Api.overview()
  } finally {
    overviewLoading.value = false
  }
}

async function searchKnowledge() {
  const query = knowledgeQuery.value.trim()
  if (!query) {
    ElMessage.warning('请输入要检索的问题或关键词。')
    return
  }
  knowledgeLoading.value = true
  try {
    knowledgeResult.value = await assistantV2Api.searchKnowledge(query)
  } finally {
    knowledgeLoading.value = false
  }
}

async function createReport(type: 'daily' | 'weekly') {
  reportLoading.value = true
  try {
    reportResult.value = await assistantV2Api.createReportDraft(type)
  } finally {
    reportLoading.value = false
  }
}

async function parseDraft() {
  const text = draftText.value.trim()
  if (!text) {
    ElMessage.warning('请输入任务或会议的自然语言描述。')
    return
  }
  draftLoading.value = true
  try {
    draftResult.value = await assistantV2Api.parseDraft(text, draftType.value)
  } finally {
    draftLoading.value = false
  }
}

async function copyText(text: string, message = '已复制。') {
  await navigator.clipboard.writeText(text)
  ElMessage.success(message)
}

const draftRows = computed(() => {
  if (!draftResult.value) return []
  const draft = draftResult.value.draft
  if (draftResult.value.draft_type === 'meeting') {
    return [
      { label: '会议主题', value: draft.title || '—' },
      { label: '开始时间', value: formatTime(draft.starts_at, 'datetime') },
      { label: '结束时间', value: formatTime(draft.ends_at, 'datetime') },
      { label: '主持人', value: draft.host_name || draft.host_id || '—' },
      { label: '记录人', value: draft.recorder_name || draft.recorder_id || '—' },
      { label: '参会人员', value: (draft.attendee_names || []).join('、') || '需人工选择' },
      { label: '地点', value: draft.location || (draft.video_enabled ? '视频会议' : '—') },
      { label: '在线链接', value: draft.online_url || '—' },
    ]
  }
  return [
    { label: '任务标题', value: draft.title || '—' },
    { label: '负责人', value: draft.assignee_name || draft.assignee_id || '需人工选择' },
    { label: '截止时间', value: formatTime(draft.due_at, 'datetime') },
      { label: '优先级', value: { low: '低', normal: '普通', high: '高' }[draft.priority as 'low' | 'normal' | 'high'] || draft.priority },
  ]
})

onMounted(() => {
  // 测试环境中由用例显式触发，避免挂载专项助手时产生未模拟的网络请求。
  if (import.meta.env.MODE !== 'test') {
    void loadOverview()
  }
})
</script>

<template>
  <section class="assistant-v2" v-loading="overviewLoading">
    <header class="v2-hero">
      <div>
        <p class="eyebrow">统一 OA 智能助手 V2</p>
        <h2>{{ overview?.date }} {{ overview?.weekday }}</h2>
        <p>{{ overview?.summary || '正在汇总今日工作...' }}</p>
      </div>
      <el-button :icon="Refresh" :loading="overviewLoading" @click="loadOverview">刷新总览</el-button>
    </header>

    <div class="stat-grid">
      <article v-for="stat in statCards" :key="stat.key" class="stat-card" :class="`tone-${stat.tone}`">
        <span>{{ stat.title }}</span>
        <strong>{{ stat.count }}</strong>
      </article>
    </div>

    <el-alert
      class="safety-alert"
      :title="overview?.safety_notice"
      type="info"
      :closable="false"
      show-icon
    />

    <div class="overview-grid">
      <article v-for="section in overview?.sections" :key="section.key" class="business-section">
        <header>
          <h3>{{ section.title }}</h3>
          <span class="section-count">{{ section.count }}</span>
        </header>
        <el-alert v-if="!section.available" :title="section.message" type="warning" :closable="false" />
        <p v-else-if="!section.cards.length" class="empty-text">暂无需要处理的事项。</p>
        <ul v-else class="card-list">
          <li v-for="card in section.cards" :key="`${card.type}-${card.id}`">
            <router-link v-if="card.link" class="business-card" :to="card.link">
              <span class="card-main">
                <strong>{{ card.title }}</strong>
                <small>{{ card.subtitle }}</small>
              </span>
              <span class="card-meta">
                <em>{{ card.status }}</em>
                <time>{{ formatTime(card.time) }}</time>
              </span>
            </router-link>
            <div v-else class="business-card">
              <span class="card-main">
                <strong>{{ card.title }}</strong>
                <small>{{ card.subtitle }}</small>
              </span>
            </div>
          </li>
        </ul>
      </article>
    </div>

    <div class="tool-grid">
      <article class="tool-card">
        <header>
          <el-icon><Search /></el-icon>
          <div>
            <h3>统一知识检索</h3>
            <p>检索当前账号有权访问的已发布资料。</p>
          </div>
        </header>
        <div class="tool-action">
          <el-input v-model="knowledgeQuery" maxlength="500" clearable placeholder="例如：业务任务如何确认负责人和截止时间？" @keyup.enter="searchKnowledge" />
          <el-button type="primary" :loading="knowledgeLoading" @click="searchKnowledge">检索</el-button>
        </div>
        <div v-if="knowledgeResult" class="knowledge-result">
          <p class="result-preview">{{ knowledgeResult.answer_preview }}</p>
          <article v-for="item in knowledgeResult.results" :key="item.chunk_id" class="evidence">
            <header>
              <strong>{{ item.title || item.source_location || '资料片段' }}</strong>
              <span>相似度 {{ item.similarity }}</span>
            </header>
            <p>{{ item.content }}</p>
            <small>{{ item.source_location }} · 版本 {{ item.version }}</small>
          </article>
          <p class="evidence-note">{{ knowledgeResult.evidence_notice }}</p>
        </div>
      </article>

      <article class="tool-card">
        <header>
          <el-icon><Document /></el-icon>
          <div>
            <h3>日报 / 周报草稿</h3>
            <p>依据本人有权访问的任务和会议数据起草。</p>
          </div>
        </header>
        <div class="button-row">
          <el-button :loading="reportLoading" @click="createReport('daily')">生成日报草稿</el-button>
          <el-button :loading="reportLoading" @click="createReport('weekly')">生成周报草稿</el-button>
          <el-button v-if="reportResult" text :icon="CopyDocument" @click="copyText(reportResult.markdown, '草稿已复制。')">复制草稿</el-button>
        </div>
        <el-alert
          v-for="warning in reportResult?.warnings"
          :key="warning"
          :title="warning"
          type="warning"
          :closable="false"
        />
        <pre v-if="reportResult" class="markdown-preview">{{ reportResult.markdown }}</pre>
      </article>

      <article class="tool-card draft-tool">
        <header>
          <el-icon><MagicStick /></el-icon>
          <div>
            <h3>自然语言创建草稿</h3>
            <p>先结构化任务或会议，不直接提交业务数据。</p>
          </div>
        </header>
        <el-select v-model="draftType" class="draft-type" aria-label="草稿类型">
          <el-option label="自动判断" value="auto" />
          <el-option label="任务草稿" value="task" />
          <el-option label="会议草稿" value="meeting" />
        </el-select>
        <el-input
          v-model="draftText"
          type="textarea"
          :rows="4"
          maxlength="3000"
          placeholder="例如：明天下午3点和李四开项目复盘会，地点三楼会议室"
        />
        <el-button type="primary" :loading="draftLoading" @click="parseDraft">生成结构化草稿</el-button>

        <div v-if="draftResult" class="draft-result">
          <header>
            <strong>{{ draftResult.draft_type === 'meeting' ? '会议草稿' : '任务草稿' }}</strong>
            <el-tag size="small" type="success">可信度：{{ { high: '高', medium: '中', low: '低' }[draftResult.confidence] }}</el-tag>
          </header>
          <el-alert
            v-if="draftResult.missing_required.length"
            :title="`还需补充：${draftResult.missing_required.join('、')}`"
            type="warning"
            :closable="false"
          />
          <el-alert
            v-for="warning in draftResult.warnings"
            :key="warning"
            :title="warning"
            type="info"
            :closable="false"
          />
          <dl>
            <template v-for="row in draftRows" :key="row.label">
              <dt>{{ row.label }}</dt>
              <dd>{{ row.value }}</dd>
            </template>
          </dl>
          <el-button text :icon="CopyDocument" @click="copyText(JSON.stringify(draftResult.draft, null, 2), '草稿 JSON 已复制。')">复制 JSON</el-button>
          <p class="confirmation-note">{{ draftResult.confirmation_notice }}</p>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.assistant-v2 {
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.v2-hero {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  align-items: flex-start;
}
.eyebrow {
  color: var(--oa-primary);
  font-size: 12px;
  font-weight: 700;
  margin: 0 0 8px;
}
.v2-hero h2 {
  margin: 0 0 8px;
  font: 600 24px/1.4 var(--oa-heading-font);
}
.v2-hero p:last-child {
  margin: 0;
  color: var(--oa-muted);
}
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}
.stat-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 18px;
  border: 1px solid var(--oa-border);
  border-radius: 10px;
  background: var(--oa-surface);
}
.stat-card span {
  color: var(--oa-muted);
}
.stat-card strong {
  font-size: 28px;
}
.tone-teal strong { color: #0f766e; }
.tone-blue strong { color: #2563eb; }
.tone-amber strong { color: #b77918; }
.tone-violet strong { color: #7c3aed; }
.safety-alert {
  border-radius: 8px;
}
.overview-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
.business-section,
.tool-card {
  border: 1px solid var(--oa-border);
  border-radius: 10px;
  background: var(--oa-surface);
  padding: 18px;
  min-width: 0;
}
.business-section > header,
.tool-card > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}
.tool-card > header {
  justify-content: flex-start;
}
.tool-card > header .el-icon {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  background: #e7f1ef;
  color: var(--oa-primary);
  font-size: 20px;
}
.business-section h3,
.tool-card h3 {
  margin: 0;
  font-size: 16px;
}
.tool-card p {
  margin: 4px 0 0;
  color: var(--oa-muted);
  font-size: 13px;
}
.section-count {
  display: grid;
  place-items: center;
  min-width: 28px;
  height: 28px;
  border-radius: 999px;
  background: #e7f1ef;
  color: var(--oa-primary);
  font-weight: 700;
}
.card-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.business-card {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  padding: 12px;
  border: 1px solid var(--oa-border);
  border-radius: 8px;
  color: var(--oa-text);
  text-decoration: none;
}
.business-card:hover {
  border-color: #87bab4;
  background: #f7fbfa;
}
.card-main {
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
}
.card-main strong,
.card-main small {
  overflow-wrap: anywhere;
}
.card-main small {
  color: var(--oa-muted);
}
.card-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  flex-shrink: 0;
  color: var(--oa-muted);
  font-size: 12px;
}
.card-meta em {
  font-style: normal;
}
.empty-text {
  color: var(--oa-muted);
  margin: 0;
}
.tool-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
.draft-tool {
  grid-column: span 2;
}
.tool-action,
.button-row {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}
.tool-action {
  margin-bottom: 14px;
}
.tool-action .el-input {
  flex: 1;
}
.result-preview,
.markdown-preview,
.confirmation-note {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.7;
}
.evidence {
  border-top: 1px solid var(--oa-border);
  padding: 14px 0;
}
.evidence header {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}
.evidence p {
  color: var(--oa-text);
  margin-bottom: 8px;
}
.evidence small,
.evidence-note {
  color: var(--oa-muted);
}
.markdown-preview {
  max-height: 520px;
  overflow: auto;
  border: 1px solid var(--oa-border);
  border-radius: 8px;
  padding: 16px;
  background: #f8faf9;
  margin-top: 14px;
}
.draft-type {
  width: 180px;
  margin-bottom: 12px;
}
.draft-result {
  margin-top: 16px;
  border-top: 1px solid var(--oa-border);
  padding-top: 16px;
}
.draft-result > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.draft-result dl {
  display: grid;
  grid-template-columns: 110px minmax(0, 1fr);
  gap: 8px 12px;
  margin: 14px 0;
}
.draft-result dt {
  color: var(--oa-muted);
}
.draft-result dd {
  margin: 0;
  overflow-wrap: anywhere;
}
@media (max-width: 1000px) {
  .stat-grid,
  .overview-grid,
  .tool-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 680px) {
  .v2-hero,
  .business-card {
    flex-direction: column;
  }
  .stat-grid,
  .overview-grid,
  .tool-grid {
    grid-template-columns: 1fr;
  }
  .draft-tool {
    grid-column: span 1;
  }
  .card-meta {
    align-items: flex-start;
  }
  .draft-result dl {
    grid-template-columns: 1fr;
  }
}
</style>

