<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Back, Plus, Refresh, Check, Close, DocumentChecked } from '@element-plus/icons-vue'
import { documentApi } from '@/api/document'
import { commandKey, releaseCommandKey } from '@/api/draftCommands'
import { useDraftReview, draftStatus } from '@/composables/useDraftReview'
import DraftHistory from '@/components/DraftHistory.vue'
import type { DocumentDraft, DocumentResponse, DocumentInput, DocumentTemplate, DocumentSummary } from '@/types/drafting'
import '@/styles/drafting.css'

const router = useRouter()
const review = useDraftReview<DocumentDraft, DocumentResponse>('document', documentApi,
  (draft, record) => !!draft.body.trim() && draft.body.length <= 40000 && draft.source_refs.length > 0 &&
    draft.source_refs.every(ref => record.sources.some(source => source.ref === ref)))
const { id, record, draft, versions, busy, loading, error, historyError, page, total,
  metadata, warnings, dirty, editable, validDraft, hasWarnings, canConfirm } = review
const items = computed(() => review.items.value as DocumentSummary[])
const templates = ref<DocumentTemplate[]>([]), templateError = ref('')
const form = reactive<DocumentInput>({ template_id: 'notice', subject: '', recipient: '', deadline: '', basis: '',
  key_points: '', classification: 'internal', distribution: '', use_knowledge: false })
const canCreate = computed(() => templates.value.some(t => t.id === form.template_id) &&
  [form.subject, form.recipient, form.key_points, form.distribution].every(v => v.trim()))
const classification: Record<string, string> = { public: '公开', internal: '内部', confidential: '保密' }
async function loadTemplates() {
  templateError.value = ''
  try { templates.value = await documentApi.templates() } catch { templateError.value = '模板加载失败' }
}
onMounted(loadTemplates)
async function create() {
  if (!canCreate.value || busy.value) return
  busy.value = true; error.value = ''
  const payload = { ...form }
  try {
    const result = await documentApi.create({ ...payload, idempotency_key: await commandKey('document-create', payload) })
    await releaseCommandKey('document-create', payload)
    busy.value = false
    await router.push('/documents/' + encodeURIComponent(result.document_id))
  } catch (err) { review.problem(err) } finally { busy.value = false }
}
</script>

<template>
  <main class="draft-workbench">
    <header class="heading"><div><h1>{{ record?.subject || '文档起草' }}</h1><p class="muted">{{ record ? `${draftStatus[record.status] || record.status} · ${record.version ? 'v' + record.version : '尚无版本'}` : '公文、通知、报告与总结' }}</p></div>
      <el-button v-if="id" :icon="Back" :disabled="busy" @click="router.push('/documents')">文档列表</el-button>
      <el-button v-else :icon="Refresh" :loading="loading" @click="review.load">刷新</el-button>
    </header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" /><el-button v-if="error" :disabled="busy" @click="review.reload">重新加载</el-button>
    <el-skeleton v-if="loading" :rows="8" animated />
    <div v-else-if="!id" class="draft-layout">
      <section><h2>新建文档</h2>
        <el-alert v-if="templateError" :title="templateError" type="error" :closable="false" /><el-button v-if="templateError" @click="loadTemplates">重试模板</el-button>
        <el-form label-position="top" :disabled="busy">
          <el-form-item label="文种"><el-select v-model="form.template_id" aria-label="文种"><el-option v-for="t in templates" :key="t.id" :label="t.name" :value="t.id" /></el-select></el-form-item>
          <el-form-item label="标题" required><el-input v-model="form.subject" aria-label="标题" maxlength="255" /></el-form-item>
          <el-form-item label="接收对象" required><el-input v-model="form.recipient" aria-label="接收对象" maxlength="500" /></el-form-item>
          <el-form-item label="期限"><el-input v-model="form.deadline" aria-label="期限" maxlength="100" /></el-form-item>
          <el-form-item label="依据材料"><el-input v-model="form.basis" aria-label="依据材料" type="textarea" :rows="3" maxlength="10000" /></el-form-item>
          <el-form-item label="核心要点" required><el-input v-model="form.key_points" aria-label="核心要点" type="textarea" :rows="5" maxlength="20000" /></el-form-item>
          <el-form-item label="密级"><el-select v-model="form.classification" aria-label="密级"><el-option v-for="(label, value) in classification" :key="value" :label="label" :value="value" /></el-select></el-form-item>
          <el-form-item label="分发范围" required><el-input v-model="form.distribution" aria-label="分发范围" maxlength="500" /></el-form-item>
          <el-form-item label="引用知识库"><el-switch v-model="form.use_knowledge" aria-label="引用知识库" /></el-form-item>
          <el-button data-testid="create-draft" type="primary" :icon="Plus" :disabled="!canCreate" :loading="busy" @click="create">创建文档</el-button>
        </el-form>
      </section>
      <section><h2>我的文档 <small class="muted">{{ total }} 条</small></h2>
        <button v-for="item in items" :key="item.document_id" class="record-row" @click="router.push('/documents/' + encodeURIComponent(item.document_id))"><span>{{ item.subject }}<small>{{ item.updated_at?.slice(0, 10) }}</small></span><span>{{ draftStatus[item.status] || item.status }}<small>{{ item.version ? 'v' + item.version : '尚无版本' }}</small></span></button>
        <el-empty v-if="!items.length" description="暂无文档" />
        <el-pagination v-if="total > 20" v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next" @current-change="review.load" />
      </section>
    </div>
    <template v-else-if="record">
      <el-alert v-if="record.error" :title="record.error.message" :description="'追踪编号：' + record.error.trace_id" type="error" :closable="false" />
      <div class="draft-layout">
        <section><h2>材料与来源</h2><dl class="metadata-list"><dt>文种</dt><dd>{{ record.template.name }}</dd><dt>接收对象</dt><dd>{{ record.recipient }}</dd><dt>期限</dt><dd>{{ record.deadline || '待核实' }}</dd><dt>密级</dt><dd>{{ classification[record.classification] }}</dd><dt>分发范围</dt><dd>{{ record.distribution }}</dd></dl>
          <article v-for="source in record.sources" :key="source.ref" class="source"><h3>{{ source.title }}</h3><small>{{ source.source_location }} · {{ source.ref }}{{ source.version ? ' · v' + source.version : '' }}</small><p>{{ source.content }}</p></article>
        </section>
        <section><h2>草稿审阅</h2>
          <el-alert v-for="(check, index) in record.checks" :key="check.code + ':' + index" :title="check.message" :type="check.severity" :closable="false" />
          <template v-if="draft">
            <div data-testid="draft-body"><el-input v-model="draft.body" aria-label="文档正文" type="textarea" :rows="20" maxlength="40000" :disabled="!editable || busy" /></div>
            <label class="field-label">引用来源</label><el-select v-model="draft.source_refs" multiple aria-label="引用来源" :disabled="!editable || busy"><el-option v-for="s in record.sources" :key="s.ref" :label="s.title + ' · ' + s.ref" :value="s.ref" /></el-select>
            <p v-if="dirty" class="muted">修改尚未保存</p>
            <div v-if="record.available_actions.includes('confirm')" class="acknowledgments"><el-checkbox v-model="metadata" data-testid="metadata-confirmed" :disabled="busy || dirty">已核对接收对象、期限、密级及分发范围</el-checkbox><el-checkbox v-if="hasWarnings" v-model="warnings" data-testid="warnings-acknowledged" :disabled="busy || dirty">已核对并接受上述风险提示</el-checkbox></div>
            <div class="toolbar"><el-button v-if="editable" data-testid="save-draft" :icon="DocumentChecked" :disabled="!dirty || !validDraft" :loading="busy" @click="review.save">保存修订</el-button><el-button v-if="record.available_actions.includes('confirm')" data-testid="confirm-draft" type="primary" :icon="Check" :disabled="!canConfirm" @click="review.decide('confirm')">确认内部记录</el-button><el-button v-if="record.available_actions.includes('regenerate')" :icon="Refresh" :disabled="dirty || busy" @click="review.decide('regenerate')">重新生成</el-button><el-button v-if="record.available_actions.includes('reject')" :icon="Close" :disabled="dirty || busy" @click="review.decide('reject')">拒绝</el-button></div>
            <el-alert v-if="historyError" :title="historyError" type="warning" :closable="false" />
            <DraftHistory :key="id" :versions="versions" :current="draft.body" :text-of="(d: DocumentDraft) => d.body" />
          </template>
          <el-empty v-else description="尚无草稿" />
          <div class="toolbar"><el-button v-if="record.available_actions.includes('generate')" type="primary" :icon="Plus" :loading="busy" @click="review.start(documentApi.generate)">生成草稿</el-button><el-button v-if="record.available_actions.includes('retry')" :icon="Refresh" :loading="busy" @click="review.start(documentApi.generate, true)">重试生成</el-button></div>
        </section>
      </div>
    </template>
  </main>
</template>
