<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { Back, Check, Delete, DocumentChecked, Plus, Refresh } from '@element-plus/icons-vue'
import { reportApi } from '@/api/report'
import { authState } from '@/stores/auth'
import { commandKey, releaseCommandKey } from '@/api/draftCommands'
import type { MetricDefinition, ReportDraft, ReportPlan, ReportRecord, ReportSummary, ReportVersion } from '@/types/report'
import MetricChart from '@/components/p3/MetricChart.vue'
import DraftHistory from '@/components/DraftHistory.vue'
import '@/styles/drafting.css'

const route = useRoute(), router = useRouter()
const id = computed(() => String(route.params.id || ''))
const record = ref<ReportRecord | null>(null), draft = ref<ReportDraft | null>(null), items = ref<ReportSummary[]>([])
const versions = ref<ReportVersion[]>([]), metrics = ref<MetricDefinition[]>([])
const busy = ref(false), loading = ref(false), error = ref(''), historyError = ref(''), metricsError = ref('')
const page = ref(1), total = ref(0), planConfirmed = ref(false), definitions = ref(false), causes = ref(false)
const form = reactive({ subject: '', plan: { metrics: ['ticket_volume'], start: '', end: '', grain: 'day', scope: 'own', metric_version: 1 } as ReportPlan })
const status: Record<string, string> = { PLAN_READY: '待确认计划', DRAFT_READY: '待审阅', REVIEWING: '已修订', PAUSED: '已暂停', PUBLISHED: '已发布' }
const scopeLabels = { own: '本人创建或负责的数据', department: '本部门可访问的数据', tenant: '租户汇总' }
const canReadDepartment = computed(() => authState.provider === 'builtin' &&
  authState.user?.permissions.some(permission => permission.resource === 'report' && permission.action === 'read' && permission.scope === 'department'))
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value))
const dirty = computed(() => !!record.value?.draft && JSON.stringify(draft.value) !== JSON.stringify(record.value.draft))
const editable = computed(() => record.value?.available_actions.includes('edit'))
const validDraft = computed(() => !!draft.value?.summary.trim() && draft.value.summary.length <= 8000 &&
  draft.value.metric_refs.length > 0 && draft.value.metric_refs.every(ref => record.value?.plan.metrics.includes(ref)) &&
  draft.value.possible_causes.length <= 5 && draft.value.possible_causes.every(cause => cause.trim() && cause.length <= 500))
const canPublish = computed(() => record.value?.available_actions.includes('publish') && !dirty.value && !busy.value && validDraft.value && definitions.value && causes.value)
const canCreate = computed(() => !!form.subject.trim() && form.plan.metrics.length > 0 &&
  form.plan.metrics.every(metric => metrics.value.some(definition => definition.metric_id === metric)) &&
  !!form.plan.start && !!form.plan.end && Date.parse(form.plan.end) > Date.parse(form.plan.start) &&
  Date.parse(form.plan.end) - Date.parse(form.plan.start) <= 366 * 86400000)
let serial = 0
function problem(err: any) { error.value = err?.response?.data?.message || err?.message || '操作失败，请重试' }
function apply(result: ReportRecord) { record.value = result; draft.value = result.draft ? clone(result.draft) : null; planConfirmed.value = definitions.value = causes.value = false }
function dateLabel(value: string) { return new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(value)) }
async function loadMetrics() { metricsError.value = ''; try { metrics.value = await reportApi.metrics() } catch { metricsError.value = '指标目录加载失败' } }
onMounted(loadMetrics)
async function history(target: string, token: number) {
  try { const result = await reportApi.versions(target); if (token === serial && target === id.value) versions.value = result }
  catch { if (token === serial) historyError.value = '历史版本加载失败' }
}
async function load() {
  const token = ++serial, target = id.value
  loading.value = true; error.value = ''; historyError.value = ''; record.value = null; draft.value = null; versions.value = []; items.value = []
  try {
    if (target) { const result = await reportApi.get(target); if (token === serial && id.value === target) { apply(result); await history(target, token) } }
    else { const result = await reportApi.list({ page: page.value, page_size: 20 }); if (token === serial && !id.value) { items.value = result.items; total.value = result.total } }
  } catch (err) { if (token === serial) problem(err) } finally { if (token === serial) loading.value = false }
}
watch(id, () => { page.value = 1; void load() }, { immediate: true })
async function leave() {
  if (busy.value) return false
  if (!dirty.value) return true
  try { await ElMessageBox.confirm('当前修改尚未保存，确认离开？', '未保存的修改'); return true } catch { return false }
}
onBeforeRouteLeave(leave); onBeforeRouteUpdate(leave)
async function reload() { if (await leave()) await load() }
async function create() {
  if (!canCreate.value || busy.value) return
  busy.value = true; error.value = ''
  const payload = clone(form)
  try {
    const result = await reportApi.create({ ...payload, idempotency_key: await commandKey('report-create', payload) })
    await releaseCommandKey('report-create', payload)
    busy.value = false
    await router.push('/reports/' + encodeURIComponent(result.report_id))
  } catch (err) { problem(err) } finally { busy.value = false }
}
async function execute(action: 'approve' | 'retry' | 'edit' | 'publish') {
  if (!record.value || busy.value) return
  if (action === 'approve' && (!planConfirmed.value || !record.value.available_actions.includes('approve'))) return
  if (action === 'retry' && !record.value.available_actions.includes('retry')) return
  if (action === 'edit' && (!editable.value || !dirty.value || !validDraft.value)) return
  if (action === 'publish' && !canPublish.value) return
  const target = id.value, token = serial, version = record.value.version
  if (action === 'publish') {
    try { await ElMessageBox.confirm('确认发布当前保存版本并保留统计快照？', '发布报表') } catch { return }
    if (target !== id.value || token !== serial || record.value?.version !== version || !canPublish.value) return
  }
  const payload = { expected_version: version, ...(action === 'approve' ? { plan_confirmed: true } : {}),
    ...(action === 'edit' ? { draft: clone(draft.value!) } : {}),
    ...(action === 'publish' ? { definitions_confirmed: true, causes_acknowledged: true } : {}) }
  const data = { id: target, ...payload }
  busy.value = true; error.value = ''
  try {
    const key = await commandKey('report-' + action, data)
    const command = { ...payload, idempotency_key: key }
    let result: ReportRecord
    if (action === 'approve') result = await reportApi.approve(target, { ...command, plan_confirmed: true })
    else if (action === 'retry') result = await reportApi.retry(target, command)
    else if (action === 'edit') result = await reportApi.save(target, { ...command, draft: clone(draft.value!) })
    else result = await reportApi.publish(target, { ...command, definitions_confirmed: true, causes_acknowledged: true })
    await releaseCommandKey('report-' + action, data)
    if (target === id.value && token === serial) { apply(result); await history(target, token) }
  } catch (err) { if (token === serial) problem(err) } finally { busy.value = false }
}
</script>

<template>
  <main class="draft-workbench report-workbench">
    <header class="heading"><div><h1>{{ record?.subject || '报表分析' }}</h1><p class="muted">{{ record ? `${status[record.status] || record.status} · v${record.version}` : '业务指标与运营结果' }}</p></div><el-button v-if="id" :icon="Back" :disabled="busy" @click="router.push('/reports')">报表列表</el-button><el-button v-else :icon="Refresh" :loading="loading" @click="load">刷新</el-button></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" /><el-button v-if="error" :disabled="busy" @click="reload">重新加载</el-button>
    <el-skeleton v-if="loading" :rows="8" animated />
    <div v-else-if="!id" class="draft-layout">
      <section><h2>新建统计计划</h2><el-alert v-if="metricsError" :title="metricsError" type="error" :closable="false" /><el-button v-if="metricsError" @click="loadMetrics">重试指标目录</el-button>
        <el-form label-position="top" :disabled="busy"><el-form-item label="报告标题" required><el-input v-model="form.subject" aria-label="报告标题" maxlength="255" /></el-form-item>
          <el-form-item label="指标" required><el-select v-model="form.plan.metrics" multiple aria-label="报表指标"><el-option v-for="metric in metrics" :key="metric.metric_id" :label="metric.name" :value="metric.metric_id" /></el-select></el-form-item>
          <div class="date-fields"><el-form-item label="开始日期（上海）" required><el-date-picker v-model="form.plan.start" type="date" value-format="YYYY-MM-DD" aria-label="报表开始日期" /></el-form-item><el-form-item label="结束日期（不含）" required><el-date-picker v-model="form.plan.end" type="date" value-format="YYYY-MM-DD" aria-label="报表结束日期" /></el-form-item></div>
          <el-form-item label="统计范围"><el-select v-model="form.plan.scope" aria-label="统计范围"><el-option :label="scopeLabels.own" value="own" /><el-option v-if="canReadDepartment" :label="scopeLabels.department" value="department" /><el-option v-if="authState.provider !== 'builtin'" label="租户汇总（需权限）" value="tenant" /></el-select></el-form-item>
          <div v-for="metric in metrics.filter(item => form.plan.metrics.includes(item.metric_id))" :key="metric.metric_id" class="metric-catalog"><strong>{{ metric.name }} · v{{ metric.version }}</strong><p>{{ metric.definition }}</p><small>{{ metric.source }} · {{ metric.time_field }}</small></div>
          <el-button data-testid="create-report" type="primary" :icon="Plus" :disabled="!canCreate" :loading="busy" @click="create">保存查询计划</el-button>
        </el-form>
      </section>
      <section><h2>我的报表 <small class="muted">{{ total }} 条</small></h2><button v-for="item in items" :key="item.report_id" class="record-row" @click="router.push('/reports/' + encodeURIComponent(item.report_id))"><span>{{ item.subject }}<small>{{ item.updated_at.slice(0, 10) }}</small></span><span>{{ status[item.status] || item.status }}<small>v{{ item.version }}</small></span></button><el-empty v-if="!items.length" description="暂无报表" /><el-pagination v-if="total > 20" v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next" @current-change="load" /></section>
    </div>
    <template v-else-if="record">
      <el-alert v-if="record.error" :title="record.error.message" :description="'追踪编号：' + record.error.trace_id" type="error" :closable="false" />
      <section class="plan-overview"><h2>已保存统计计划</h2><dl class="metadata-list"><dt>统计区间</dt><dd>{{ dateLabel(record.plan.start) }} 至 {{ dateLabel(record.plan.end) }}（结束日不含）</dd><dt>统计范围</dt><dd>{{ scopeLabels[record.plan.scope] }}</dd><dt>指标版本</dt><dd>v{{ record.plan.metric_version }} · {{ record.plan.metrics.map(id => metrics.find(metric => metric.metric_id === id)?.name || id).join('、') }}</dd><dt>时间口径</dt><dd>Asia/Shanghai · 按日 · 与前一等长区间对比</dd><template v-if="record.snapshot"><dt>查询时间</dt><dd>{{ new Date(record.snapshot.queried_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) }}</dd></template></dl>
        <template v-if="record.available_actions.includes('approve')"><el-checkbox v-model="planConfirmed" data-testid="plan-confirmed" :disabled="busy">已确认指标、时间范围及统计口径</el-checkbox><div class="toolbar"><el-button data-testid="approve-report-plan" type="primary" :icon="Check" :disabled="!planConfirmed" :loading="busy" @click="execute('approve')">确认并查询</el-button></div></template>
      </section>
      <div v-if="record.snapshot" class="draft-layout"><section><h2>统计结果</h2><MetricChart v-for="metric in record.snapshot.metrics" :key="metric.metric_id" :metric="metric" /><p v-if="record.snapshot.anomaly_rule" class="muted">异常口径 v{{ record.snapshot.anomaly_rule.version }}：{{ record.snapshot.anomaly_rule.definition }}</p></section>
        <section><h2>摘要审阅</h2><template v-if="draft"><el-input v-model="draft.summary" aria-label="报表摘要" type="textarea" :rows="10" maxlength="8000" :disabled="!editable || busy" /><label class="field-label">引用指标</label><el-select v-model="draft.metric_refs" multiple aria-label="摘要引用指标" :disabled="!editable || busy"><el-option v-for="metric in record.snapshot.metrics" :key="metric.metric_id" :value="metric.metric_id" :label="metric.name" /></el-select>
          <h3>原因候选（待核查）</h3><div v-for="(_, index) in draft.possible_causes" :key="index" class="cause-row"><el-input v-model="draft.possible_causes[index]" :aria-label="'原因候选 ' + (index + 1)" maxlength="500" :disabled="!editable || busy" /><el-tooltip v-if="editable" content="移除原因候选"><el-button :icon="Delete" aria-label="移除原因候选" :disabled="busy" @click="draft.possible_causes.splice(index, 1)" /></el-tooltip></div><el-button v-if="editable" :icon="Plus" :disabled="busy || draft.possible_causes.length >= 5" @click="draft.possible_causes.push('')">添加候选</el-button><p v-else-if="!draft.possible_causes.length" class="muted">暂无原因候选</p>
          <p v-if="dirty" class="muted">修改尚未保存</p><div v-if="record.available_actions.includes('publish')" class="acknowledgments"><el-checkbox v-model="definitions" data-testid="definitions-confirmed" :disabled="dirty || busy">已核对统计来源、时间与指标定义</el-checkbox><el-checkbox v-model="causes" data-testid="causes-confirmed" :disabled="dirty || busy">已确认原因候选仅为待核查假设</el-checkbox></div>
          <div class="toolbar"><el-button v-if="editable" data-testid="save-report" :icon="DocumentChecked" :disabled="!dirty || !validDraft" :loading="busy" @click="execute('edit')">保存摘要</el-button><el-button v-if="record.available_actions.includes('publish')" data-testid="publish-report" type="primary" :icon="Check" :disabled="!canPublish" @click="execute('publish')">发布内部记录</el-button></div><el-alert v-if="historyError" :title="historyError" type="warning" :closable="false" /><DraftHistory :key="id" :versions="versions" :current="draft.summary" :text-of="(value: ReportDraft) => value.summary" />
        </template><el-empty v-else description="摘要尚未生成" /></section>
      </div>
      <div class="toolbar"><el-button v-if="record.available_actions.includes('retry')" :icon="Refresh" :loading="busy" @click="execute('retry')">重试报表</el-button></div>
      <el-alert v-if="record.publication" title="已保存平台内发布记录" type="success" :closable="false" />
    </template>
  </main>
</template>

<style scoped>
.date-fields { display: grid; grid-template-columns: minmax(0,1fr) minmax(0,1fr); gap: 16px; }
.date-fields :deep(.el-date-editor) { width: 100%; min-width: 0; }
.metric-catalog { padding: 12px 0; border-top: 1px solid #dce3e7; font-size: 13px; line-height: 1.6; }
.metric-catalog p { margin: 6px 0; } .metric-catalog small { color: #667782; }
.plan-overview { border-bottom: 1px solid #dce3e7; padding-bottom: 20px; margin-bottom: 24px; }
.plan-overview :deep(.el-checkbox) { white-space: normal; height: auto; min-height: 32px; }
.plan-overview :deep(.el-checkbox__label) { white-space: normal; line-height: 1.6; }
.cause-row { display: flex; gap: 8px; margin-bottom: 12px; min-width: 0; }
@media(max-width:600px) { .date-fields { grid-template-columns: 1fr; gap: 0; } }
</style>
