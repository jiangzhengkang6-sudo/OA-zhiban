<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Back, Plus, Refresh, Check, Close, Delete, DocumentChecked } from '@element-plus/icons-vue'
import { emailApi } from '@/api/email'
import { commandKey, releaseCommandKey } from '@/api/draftCommands'
import { useDraftReview, draftStatus } from '@/composables/useDraftReview'
import DraftHistory from '@/components/DraftHistory.vue'
import type { EmailDraft, EmailInput, EmailResponse, EmailSummary } from '@/types/drafting'
import '@/styles/drafting.css'

const router = useRouter()
const review = useDraftReview<EmailDraft, EmailResponse>('email', emailApi, (draft, record) => {
  const refs = (values: string[]) => values.length > 0 && values.every(ref => record.sources.some(s => s.ref === ref))
  return !!draft.summary.trim() && !!draft.reply_subject.trim() && !!draft.reply_body.trim() && refs(draft.source_refs) &&
    draft.action_items.every(item => !!item.title.trim() && refs(item.source_refs))
}, record => record.secondary_confirmation_required)
const { id, record, draft, versions, busy, loading, error, historyError, page, total,
  metadata, warnings, dirty, editable, validDraft, hasWarnings, canConfirm } = review
const items = computed(() => review.items.value as EmailSummary[])
const form = reactive<EmailInput>({ subject: '', sender: '', recipients: [], body: '', external_contact: false, attachments: [] })
const recipients = ref('')
const recipientValues = computed(() => recipients.value.split(/[,;，；\n]/).map(v => v.trim()).filter(Boolean))
const canCreate = computed(() => [form.subject, form.sender, form.body].every(v => v.trim()) &&
  recipientValues.value.length > 0 && recipientValues.value.length <= 30 && recipientValues.value.every(v => v.length <= 320) &&
  form.attachments.every(a => a.name.trim()))
const categories = { work: '工作事项', approval: '审批', meeting: '会议', notification: '通知', other: '其他' }
const priorities = { high: '高', normal: '普通', low: '低' }
async function create() {
  if (!canCreate.value || busy.value) return
  busy.value = true; error.value = ''
  const payload = { ...form, attachments: form.attachments.map(a => ({ ...a })), recipients: [...recipientValues.value] }
  try {
    const result = await emailApi.create({ ...payload, idempotency_key: await commandKey('email-create', payload) })
    await releaseCommandKey('email-create', payload)
    busy.value = false
    await router.push('/emails/' + encodeURIComponent(result.email_id))
  } catch (err) { review.problem(err) } finally { busy.value = false }
}
function addTodo() {
  if (!draft.value || !record.value || draft.value.action_items.length >= 100) return
  draft.value.action_items.push({ title: '', assignee_candidate: null, due_at_candidate: null,
    source_refs: record.value.sources.slice(0, 1).map(s => s.ref), needs_confirmation: true })
}
function comparison(d: EmailDraft) {
  const actions = d.action_items.map((item, index) => [
    `${index + 1}. ${item.title}`,
    `负责人候选：${item.assignee_candidate || '待确认'}`,
    `截止时间候选：${item.due_at_candidate || '待确认'}`,
    `来源：${item.source_refs.join('、')}`,
  ].join('\n')).join('\n\n')
  return [`分类：${categories[d.category]}`, `优先级：${priorities[d.priority]}`,
    `摘要\n${d.summary}`, `待办候选\n${actions || '暂无待办候选'}`,
    `回复主题\n${d.reply_subject}`, `回复正文\n${d.reply_body}`,
    `引用来源：${d.source_refs.join('、')}`].join('\n\n')
}
</script>

<template>
  <main class="draft-workbench">
    <header class="heading"><div><h1>{{ record?.subject || '邮件工作台' }}</h1><p class="muted">{{ record ? `${draftStatus[record.status] || record.status} · ${record.version ? 'v' + record.version : '尚无版本'}` : '邮件审阅与回复草稿' }}</p></div><el-button v-if="id" :icon="Back" :disabled="busy" @click="router.push('/emails')">邮件列表</el-button><el-button v-else :icon="Refresh" :loading="loading" @click="review.load">刷新</el-button></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" /><el-button v-if="error" :disabled="busy" @click="review.reload">重新加载</el-button>
    <el-skeleton v-if="loading" :rows="8" animated />
    <div v-else-if="!id" class="draft-layout">
      <section><h2>录入邮件</h2><el-form label-position="top" :disabled="busy">
        <el-form-item label="主题" required><el-input v-model="form.subject" aria-label="主题" maxlength="255" /></el-form-item><el-form-item label="发件人" required><el-input v-model="form.sender" aria-label="发件人" maxlength="320" /></el-form-item><el-form-item label="收件人" required><el-input v-model="recipients" aria-label="收件人" type="textarea" :rows="2" placeholder="多个收件人以分号分隔" /></el-form-item><el-form-item label="正文" required><el-input v-model="form.body" aria-label="邮件原文" type="textarea" :rows="10" maxlength="30000" /></el-form-item>
        <el-form-item label="涉及外部联系人"><el-switch v-model="form.external_contact" aria-label="涉及外部联系人" /></el-form-item>
        <h3>附件信息</h3><div v-for="(attachment, index) in form.attachments" :key="index" class="attachment-row"><el-input v-model="attachment.name" aria-label="附件名称" maxlength="255" /><el-checkbox v-model="attachment.sensitive">敏感</el-checkbox><el-tooltip content="移除附件信息"><el-button :icon="Delete" aria-label="移除附件信息" @click="form.attachments.splice(index, 1)" /></el-tooltip></div>
        <el-button :icon="Plus" :disabled="form.attachments.length >= 20" @click="form.attachments.push({ name: '', sensitive: false })">添加附件信息</el-button>
        <div class="toolbar"><el-button data-testid="create-draft" type="primary" :icon="Plus" :disabled="!canCreate" :loading="busy" @click="create">创建审阅记录</el-button></div>
      </el-form></section>
      <section><h2>我的邮件 <small class="muted">{{ total }} 条</small></h2><button v-for="item in items" :key="item.email_id" class="record-row" @click="router.push('/emails/' + encodeURIComponent(item.email_id))"><span>{{ item.subject }}<small>{{ item.updated_at?.slice(0, 10) }}</small></span><span>{{ draftStatus[item.status] || item.status }}<small>{{ item.version ? 'v' + item.version : '尚无版本' }}</small></span></button><el-empty v-if="!items.length" description="暂无邮件" /><el-pagination v-if="total > 20" v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next" @current-change="review.load" /></section>
    </div>
    <template v-else-if="record">
      <el-alert v-if="record.error" :title="record.error.message" :description="'追踪编号：' + record.error.trace_id" type="error" :closable="false" />
      <div class="draft-layout">
        <section><h2>邮件原文</h2><dl class="metadata-list"><dt>发件人</dt><dd>{{ record.sender }}</dd><dt>收件人</dt><dd>{{ record.recipients.join('；') }}</dd><dt>联系人</dt><dd>{{ record.external_contact ? '包含外部联系人' : '内部' }}</dd></dl><p class="mail-body">{{ record.body }}</p><h3 v-if="record.attachments.length">附件信息</h3><p v-for="(a, i) in record.attachments" :key="i">{{ a.name }} <el-tag v-if="a.sensitive" type="warning">敏感</el-tag></p><h3>来源定位</h3><article v-for="s in record.sources" :key="s.ref" class="source"><small>{{ s.locator }} · {{ s.ref }}</small><p>{{ s.text }}</p></article></section>
        <section><h2>审阅与回复</h2><el-alert v-for="check in record.checks" :key="check.code" :title="check.message" :type="check.severity" :closable="false" />
          <template v-if="draft"><el-form label-position="top" :disabled="!editable || busy">
            <div class="todo-grid"><el-form-item label="分类"><el-select v-model="draft.category" aria-label="分类"><el-option v-for="(label, value) in categories" :key="value" :label="label" :value="value" /></el-select></el-form-item><el-form-item label="优先级"><el-select v-model="draft.priority" aria-label="优先级"><el-option v-for="(label, value) in priorities" :key="value" :label="label" :value="value" /></el-select></el-form-item></div>
            <el-form-item label="摘要"><el-input v-model="draft.summary" aria-label="摘要" type="textarea" :rows="3" maxlength="4000" /></el-form-item>
            <h3>待办候选</h3><div v-for="(todo, i) in draft.action_items" :key="i" class="todo-row"><el-input v-model="todo.title" aria-label="待办事项" maxlength="2000" /><div class="todo-grid"><div><label class="field-label">负责人候选</label><el-input v-model="todo.assignee_candidate" aria-label="负责人候选" maxlength="255" /></div><div><label class="field-label">截止时间候选</label><el-input v-model="todo.due_at_candidate" aria-label="截止时间候选" maxlength="100" /></div></div><label class="field-label">待办来源</label><el-select v-model="todo.source_refs" multiple aria-label="待办来源"><el-option v-for="s in record.sources" :key="s.ref" :label="s.locator" :value="s.ref" /></el-select><div class="toolbar"><el-tooltip content="移除待办候选"><el-button :icon="Delete" aria-label="移除待办候选" @click="draft.action_items.splice(i, 1)" /></el-tooltip></div></div>
            <el-button v-if="editable" :icon="Plus" :disabled="draft.action_items.length >= 100" @click="addTodo">添加待办候选</el-button>
            <el-form-item label="回复主题"><el-input v-model="draft.reply_subject" maxlength="300" /></el-form-item><el-form-item label="回复正文"><div class="full-width" data-testid="draft-body"><el-input v-model="draft.reply_body" aria-label="回复正文" type="textarea" :rows="10" maxlength="20000" /></div></el-form-item><el-form-item label="引用来源"><el-select v-model="draft.source_refs" multiple aria-label="引用来源"><el-option v-for="s in record.sources" :key="s.ref" :label="s.locator" :value="s.ref" /></el-select></el-form-item>
          </el-form>
          <p v-if="dirty" class="muted">修改尚未保存</p>
          <div v-if="record.available_actions.includes('confirm')" class="acknowledgments"><el-checkbox v-model="metadata" data-testid="metadata-confirmed" :disabled="busy || dirty">已核对联系人、待办候选、回复和附件信息</el-checkbox><el-checkbox v-if="hasWarnings" v-model="warnings" data-testid="warnings-acknowledged" :disabled="busy || dirty">已核对并接受上述风险提示</el-checkbox></div>
          <div class="toolbar"><el-button v-if="editable" data-testid="save-draft" :icon="DocumentChecked" :disabled="!dirty || !validDraft" :loading="busy" @click="review.save">保存修订</el-button><el-button v-if="record.available_actions.includes('confirm')" data-testid="confirm-draft" type="primary" :icon="Check" :disabled="!canConfirm" @click="review.decide('confirm')">确认内部记录</el-button><el-button v-if="record.available_actions.includes('regenerate')" :icon="Refresh" :disabled="dirty || busy" @click="review.decide('regenerate')">重新分析</el-button><el-button v-if="record.available_actions.includes('reject')" :icon="Close" :disabled="dirty || busy" @click="review.decide('reject')">拒绝</el-button></div>
          <el-alert v-if="historyError" :title="historyError" type="warning" :closable="false" /><DraftHistory :key="id" :versions="versions" :current="comparison(draft)" :text-of="comparison" />
          </template><el-empty v-else description="尚无分析草稿" />
          <div class="toolbar"><el-button v-if="record.available_actions.includes('analyze')" type="primary" :icon="Plus" :loading="busy" @click="review.start(emailApi.analyze)">分析邮件</el-button><el-button v-if="record.available_actions.includes('retry')" :icon="Refresh" :loading="busy" @click="review.start(emailApi.analyze, true)">重试分析</el-button></div>
        </section>
      </div>
    </template>
  </main>
</template>
