<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { Back, Check, Close, DocumentChecked, Plus, Refresh } from '@element-plus/icons-vue'
import { contractApi } from '@/api/contract'
import { commandKey, releaseCommandKey } from '@/api/draftCommands'
import { demoUsers } from '@/utils/roles'
import { authState, can } from '@/stores/auth'
import type { ContractResponse, ContractSummary, ContractVersion, RiskDecision } from '@/types/contract'
import '@/styles/drafting.css'

const route = useRoute(), router = useRouter()
const id = computed(() => String(route.params.id || ''))
const record = ref<ContractResponse | null>(null), items = ref<ContractSummary[]>([]), versions = ref<ContractVersion[]>([])
const loading = ref(false), busy = ref(false), error = ref(''), historyError = ref(''), total = ref(0), page = ref(1)
const summary = ref(''), comment = ref(''), decisions = ref<RiskDecision[]>([]), selectedVersion = ref<number>()
const form = reactive({ title: '', reviewer_id: '', text: '', mode: 'text' })
const file = ref<File | null>(null)
const reviewers = ref<{ id: string; name: string }[]>([])
const labels: Record<string, string> = { CREATED: '待审查', PROCESSING: '分析中', DRAFT_READY: '待人工复核', PAUSED: '已暂停', CONFIRMED: '已确认', REJECTED: '已拒绝' }
const dispositionLabels = { accepted: '接受风险', mitigated: '已落实缓解措施', needs_revision: '需修订合同' }
const dirty = computed(() => !!record.value?.draft && summary.value !== record.value.draft.summary)
const decisionDirty = computed(() => !!comment.value || decisions.value.some(d => !!d.comment))
const canDecide = computed(() => !busy.value && !dirty.value && !!comment.value.trim() && decisions.value.length === record.value?.draft?.risks.length && decisions.value.every(d => d.comment.trim()))
const canWrite = computed(() => authState.provider !== 'builtin' || can('contract', 'write'))
const canCreate = computed(() => canWrite.value && !!form.title.trim() && reviewers.value.some(user => user.id === form.reviewer_id) && (form.mode === 'text' ? !!form.text.trim() : !!file.value))
const history = computed(() => versions.value.find(version => version.version === selectedVersion.value))
let generation = 0
function accept(result: ContractResponse) {
  record.value = result; summary.value = result.draft?.summary || ''; comment.value = ''
  decisions.value = (result.draft?.risks || []).map(risk => ({ risk_id: risk.risk_id, action: 'needs_revision', comment: '' }))
}
async function load() {
  const token = ++generation, target = id.value
  loading.value = true; error.value = ''; record.value = null; versions.value = []; historyError.value = ''
  try {
    if (target) {
      const result = await contractApi.get(target)
      if (token !== generation) return
      accept(result)
      try { const rows = await contractApi.versions(target); if (token === generation) versions.value = rows } catch { if (token === generation) historyError.value = '版本记录加载失败' }
    } else {
      reviewers.value = []
      const [result, people] = await Promise.all([contractApi.list({ page: page.value, page_size: 20 }),
        !canWrite.value ? Promise.resolve([]) : authState.provider === 'builtin' ? contractApi.reviewers() : Promise.resolve(demoUsers.filter(user => user.roles.some(role => ['approver', 'admin'].includes(role))))])
      if (token === generation) {
        items.value = result.items; total.value = result.total; reviewers.value = people
        if (!people.some(user => user.id === form.reviewer_id)) form.reviewer_id = ''
      }
    }
  } catch (err) { if (token === generation) error.value = err instanceof Error ? err.message : '合同加载失败' }
  finally { if (token === generation) loading.value = false }
}
async function leave() {
  if (busy.value) return false
  if (!dirty.value && !decisionDirty.value) return true
  try { await ElMessageBox.confirm('当前修订或复核意见尚未提交，是否离开？', '未提交修改', { confirmButtonText: '离开', cancelButtonText: '继续编辑' }); return true } catch { return false }
}
onBeforeRouteLeave(leave); onBeforeRouteUpdate(leave)
function unload(event: BeforeUnloadEvent) { if (dirty.value || decisionDirty.value) { event.preventDefault(); event.returnValue = '' } }
window.addEventListener('beforeunload', unload)
onBeforeUnmount(() => { generation++; window.removeEventListener('beforeunload', unload) })
watch(id, () => { selectedVersion.value = undefined; void load() }, { immediate: true })
function chooseFile(event: Event) { file.value = (event.target as HTMLInputElement).files?.[0] || null }
async function create() {
  if (!canCreate.value || busy.value) return
  busy.value = true; error.value = ''
  const payload = { title: form.title, reviewer_id: form.reviewer_id, text: form.mode === 'text' ? form.text : '', file_name: file.value?.name, file_size: file.value?.size, file_modified: file.value?.lastModified }
  try {
    if (file.value && form.mode === 'file' && file.value.size > 5 * 1024 * 1024) throw new Error('文件超过 5 MiB')
    const key = await commandKey('contract-create', payload)
    let result: ContractResponse
    if (form.mode === 'file') {
      const data = new FormData(); data.append('title', form.title); data.append('reviewer_id', form.reviewer_id); data.append('idempotency_key', key); data.append('file', file.value!)
      result = await contractApi.upload(data)
    } else result = await contractApi.create({ title: form.title, reviewer_id: form.reviewer_id, text: form.text, idempotency_key: key })
    await releaseCommandKey('contract-create', payload)
    busy.value = false; await router.push('/contracts/' + encodeURIComponent(result.contract_id))
  } catch (err) { error.value = err instanceof Error ? err.message : '创建失败' } finally { busy.value = false }
}
async function command(action: string) {
  if (!record.value || busy.value || !record.value.available_actions.includes(action)) return
  if (['confirm', 'reject'].includes(action) && !canDecide.value) return
  const target = id.value, token = generation
  const payload = { action, expected_version: record.value.version, ...(action === 'save' ? { summary: summary.value } : {}),
    ...(['confirm', 'reject'].includes(action) ? { comment: comment.value, dispositions: decisions.value.map(d => ({ ...d })) } : {}) }
  busy.value = true; error.value = ''
  try {
    const result = await contractApi.command(target, { ...payload, idempotency_key: await commandKey('contract-' + target, payload) })
    await releaseCommandKey('contract-' + target, payload)
    if (token !== generation) return
    accept(result)
    try { versions.value = await contractApi.versions(target) } catch { historyError.value = '版本记录加载失败' }
  } catch (err) { error.value = err instanceof Error ? err.message : '操作失败' } finally { busy.value = false }
}
function evidence(riskId: string) {
  const paragraph = record.value?.draft?.risks.find(risk => risk.risk_id === riskId)?.evidence.paragraph
  if (paragraph) document.getElementById('contract-paragraph-' + paragraph)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}
</script>

<template>
  <main class="draft-workbench contract-workbench">
    <header class="heading"><div><h1>{{ record?.title || '合同审查' }}</h1><p class="muted">{{ record ? `${labels[record.status] || record.status} · v${record.version}` : '内部审查记录' }}</p></div><el-button v-if="id" :icon="Back" :disabled="busy" @click="router.push('/contracts')">合同列表</el-button><el-button v-else :icon="Refresh" :loading="loading" @click="load">刷新</el-button></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" /><el-button v-if="error" :disabled="busy" @click="load">重新加载</el-button>
    <el-skeleton v-if="loading" :rows="8" animated />
    <div v-else-if="!id" class="draft-layout">
      <section v-if="canWrite"><h2>新建审查</h2><el-form label-position="top" :disabled="busy">
        <el-form-item label="合同名称" required><el-input v-model="form.title" aria-label="合同名称" maxlength="255" /></el-form-item>
        <el-form-item label="指定复核人" required><el-select v-model="form.reviewer_id" aria-label="指定复核人" filterable placeholder="选择复核人" :no-data-text="error ? '人员加载失败，请重试' : '暂无具备合同复核权限的成员'"><el-option v-for="user in reviewers" :key="user.id" :label="user.name" :value="user.id" /></el-select></el-form-item>
        <el-form-item label="材料"><el-radio-group v-model="form.mode"><el-radio-button value="text">粘贴文本</el-radio-button><el-radio-button value="file">上传文件</el-radio-button></el-radio-group></el-form-item>
        <el-form-item v-if="form.mode === 'text'" label="合同原文" required><el-input v-model="form.text" aria-label="合同原文" type="textarea" :rows="14" maxlength="100000" /></el-form-item>
        <el-form-item v-else label="TXT / 文本型 PDF · 最大 5 MiB"><input aria-label="合同文件" type="file" accept=".txt,.pdf" :disabled="busy" @change="chooseFile" /></el-form-item>
        <el-button data-testid="create-contract" type="primary" :icon="Plus" :disabled="!canCreate" :loading="busy" @click="create">创建审查</el-button>
      </el-form></section>
      <section><h2>合同记录 <small class="muted">{{ total }} 条</small></h2><button v-for="item in items" :key="item.contract_id" class="record-row" @click="router.push('/contracts/' + encodeURIComponent(item.contract_id))"><span>{{ item.title }}<small>{{ item.contract_id }}</small></span><span>{{ labels[item.status] || item.status }}<small>v{{ item.version }}</small></span></button><el-empty v-if="!items.length" description="暂无合同" /><el-pagination v-if="total > 20" v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next" @current-change="load" /></section>
    </div>
    <template v-else-if="record">
      <el-alert v-if="record.error" :title="record.error.message" :description="'追踪编号：' + record.error.trace_id" type="error" :closable="false" />
      <el-alert v-if="record.scan_status !== 'CLEAN'" :title="'文件扫描状态：' + record.scan_status" type="warning" :closable="false" />
      <div class="draft-layout">
        <section><h2>合同原文</h2><dl class="metadata-list"><dt>复核人</dt><dd>{{ record.reviewer_name || (authState.provider !== 'builtin' ? demoUsers.find(user => user.id === record!.reviewer_id)?.name : '') || record.reviewer_id }}</dd><dt>内容校验值</dt><dd>{{ record.source_hash }}</dd></dl>
          <article v-for="paragraph in record.paragraphs" :id="'contract-paragraph-' + paragraph.paragraph" :key="paragraph.paragraph" class="source"><small>{{ paragraph.page ? `第 ${paragraph.page} 页 · ` : '' }}第 {{ paragraph.paragraph }} 段</small><p>{{ paragraph.quote }}</p></article>
        </section>
        <section><h2>审查结果</h2><div class="toolbar"><el-button v-if="record.available_actions.includes('review')" :icon="Plus" :loading="busy" :disabled="dirty || record.scan_status !== 'CLEAN'" @click="command('review')">{{ record.draft ? '重新审查' : '开始审查' }}</el-button><el-button v-if="record.available_actions.includes('retry')" :icon="Refresh" :loading="busy" @click="command('retry')">继续分析</el-button><el-button v-if="record.available_actions.includes('rescan')" :icon="Refresh" :loading="busy" @click="command('rescan')">重新扫描</el-button></div>
          <div v-if="record.node_trace.length" class="muted node-trace">{{ record.node_trace.map(node => ({ extract_clauses: '条款提取', check_rules: '规则核验', analyze_risks: '风险分析', summarize: '结果汇总' }[node] || node)).join(' → ') }}</div>
          <template v-if="record.draft">
            <p class="muted">{{ record.draft.analysis_engine === 'deepagents' ? 'DeepAgents 长合同分析' : '条款规则分析' }} · {{ record.draft.rule_version }}</p>
            <el-input v-model="summary" aria-label="审查摘要" type="textarea" :rows="4" maxlength="8000" :disabled="!record.available_actions.includes('save') || busy" />
            <el-button v-if="record.available_actions.includes('save')" data-testid="save-contract" :icon="DocumentChecked" :disabled="!dirty || !summary.trim()" :loading="busy" @click="command('save')">保存修订</el-button>
            <article v-for="(risk, index) in record.draft.risks" :key="risk.risk_id" class="risk-row">
              <h3>{{ risk.name || risk.title }} <el-tag :type="risk.severity === 'high' ? 'danger' : 'warning'">{{ risk.severity === 'high' ? '高' : '中' }}</el-tag></h3><p>{{ risk.suggestion }}</p><small class="muted">{{ risk.source }}</small>
              <div data-testid="risk-evidence" class="evidence"><span v-if="risk.missing">全文未检出对应条款 · 范围 {{ risk.evidence.start }}–{{ risk.evidence.end }}</span><template v-else><el-button link @click="evidence(risk.risk_id)">{{ risk.evidence.page ? `第 ${risk.evidence.page} 页 · ` : '' }}第 {{ risk.evidence.paragraph }} 段</el-button><blockquote>{{ risk.evidence.quote }}</blockquote></template></div>
              <template v-if="record.available_actions.includes('confirm')"><label class="field-label">人工处理</label><el-select v-model="decisions[index]!.action" :aria-label="'风险处理 ' + risk.risk_id" :disabled="busy"><el-option v-for="(label, value) in dispositionLabels" :key="value" :value="value" :label="label" /></el-select><el-input v-model="decisions[index]!.comment" :aria-label="'处理意见 ' + risk.risk_id" type="textarea" :rows="2" maxlength="2000" :disabled="busy" /></template>
            </article>
            <article v-for="(observation, index) in record.draft.observations" :key="index" class="source"><h3>分析建议 · 第 {{ observation.paragraph }} 段</h3><blockquote>{{ observation.quote }}</blockquote><p>{{ observation.suggestion }}</p></article>
            <template v-if="record.available_actions.includes('confirm')"><label class="field-label">最终复核意见</label><el-input v-model="comment" aria-label="最终复核意见" type="textarea" :rows="3" maxlength="2000" :disabled="busy" /><div class="toolbar"><el-button data-testid="confirm-contract" type="primary" :icon="Check" :disabled="!canDecide" @click="command('confirm')">确认内部审查</el-button><el-button :icon="Close" :disabled="!canDecide" @click="command('reject')">拒绝</el-button></div></template>
            <section v-if="record.confirmation" class="confirmation"><h3>人工决定 · v{{ record.confirmation.version }}</h3><p>{{ record.confirmation.comment }}</p><p v-for="decision in record.confirmation.dispositions" :key="decision.risk_id">{{ decision.risk_id }} · {{ dispositionLabels[decision.action] }} · {{ decision.comment }}</p></section>
            <h3>版本比较</h3><el-alert v-if="historyError" :title="historyError" type="warning" :closable="false" /><el-select v-model="selectedVersion" aria-label="历史审查版本" placeholder="选择历史版本"><el-option v-for="version in versions" :key="version.version" :value="version.version" :label="'v' + version.version + ' · ' + version.created_at.slice(0, 10)" /></el-select><pre v-if="history" class="history-summary">{{ history.draft.summary }}</pre>
          </template><el-empty v-else description="尚无审查结果" />
        </section>
      </div>
    </template>
  </main>
</template>

<style scoped>
.risk-row { border-top: 1px solid #dce3e7; padding: 16px 0; }
.risk-row p, blockquote, .confirmation p { line-height: 1.8; overflow-wrap: anywhere; }
.evidence { margin: 12px 0; color: #56646d; font-size: 13px; }
blockquote { border-left: 3px solid #16796b; margin: 8px 0; padding-left: 12px; white-space: pre-wrap; }
.risk-row .el-textarea { margin-top: 8px; }
.history-summary { white-space: pre-wrap; overflow-wrap: anywhere; font-family: inherit; font-size: 14px; }
.source:target { background: #e8f3ef; }
.node-trace { line-height: 1.8; overflow-wrap: anywhere; }
.confirmation { border-top: 1px solid #dce3e7; padding-top: 16px; }
</style>
