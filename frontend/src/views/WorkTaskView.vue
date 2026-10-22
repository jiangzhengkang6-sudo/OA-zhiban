<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { Back, Plus, Refresh, Check, Close, DocumentChecked } from '@element-plus/icons-vue'
import { workTaskApi, type WorkTask, type WorkTaskBatch, type WorkTaskCandidate, type TaskNotice, type TaskEvent, type TaskVersion } from '@/api/workTask'
import { replayable } from '@/api/draftCommands'
import ReadableContent from '@/components/ReadableContent.vue'
import { businessLabel, personName, readableSource, sourceDescription } from '@/utils/businessLabels'
import '@/styles/drafting.css'

const route = useRoute(), router = useRouter()
const id = computed(() => String(route.params.id || ''))
const isBatch = computed(() => id.value.startsWith('WTB-'))
const batch = ref<WorkTaskBatch | null>(null), task = ref<WorkTask | null>(null)
const candidates = ref<WorkTaskCandidate[]>([]), selected = ref<string[]>([])
const tasks = ref<WorkTask[]>([]), batches = ref<WorkTaskBatch[]>([]), notices = ref<TaskNotice[]>([])
const versions = ref<TaskVersion[]>([]), events = ref<TaskEvent[]>([]), busy = ref(false), loading = ref(false)
const error = ref(''), historyError = ref(''), page = ref(1), total = ref(0), metadata = ref(false), risk = ref(false)
const rejection = ref(''), progress = ref(0), comment = ref(''), activeTab = ref('tasks')
const sourceForm = reactive({ source_type: 'ticket' as 'ticket' | 'meeting' | 'approval', source_id: '', source_version: undefined as number | undefined })
const taskForm = reactive({ title: '', assignee_id: '', due_at: '', priority: 'normal' as 'low' | 'normal' | 'high', sensitive: false })
const labels: Record<string, string> = { CREATED: '待提取', DRAFT_READY: '待确认', PAUSED: '已暂停', CONFIRMED: '已创建', REJECTED: '已拒绝', OPEN: '待开始', IN_PROGRESS: '进行中', COMPLETED: '已完成', CANCELLED: '已取消', ARCHIVED: '已归档' }
const priorities = { low: '低', normal: '普通', high: '高' }
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value))
const taskFields = (value: WorkTask) => ({ title: value.title, assignee_id: value.assignee_id, due_at: value.due_at, priority: value.priority, sensitive: value.sensitive })
const dirty = computed(() => batch.value ? JSON.stringify(candidates.value) !== JSON.stringify(batch.value.draft?.candidates || []) :
  !!task.value && JSON.stringify(taskForm) !== JSON.stringify(taskFields(task.value)))
const validCandidates = computed(() => candidates.value.length > 0 && candidates.value.every(c => c.title.trim() && c.source_refs.length))
const canConfirm = computed(() => !!batch.value?.available_actions.includes('confirm') && !busy.value && !dirty.value && metadata.value && risk.value &&
  selected.value.length > 0 && candidates.value.filter(c => selected.value.includes(c.candidate_id)).every(c => c.assignee_id?.trim() && c.due_at && !Number.isNaN(Date.parse(c.due_at))))
const validTask = computed(() => taskForm.title.trim() && taskForm.assignee_id.trim() && taskForm.due_at && !Number.isNaN(Date.parse(taskForm.due_at)))
const sourceTarget = computed(() => {
  const type = batch.value?.source_type || task.value?.source?.source_type
  const sourceId = batch.value?.source_id || task.value?.source?.source_id
  if (!sourceId) return ''
  return type === 'meeting' ? '/meetings/' + encodeURIComponent(sourceId) : type === 'ticket' ? '/ticket/' + encodeURIComponent(sourceId) : ''
})
let serial = 0
function problem(err: any) { error.value = err?.response?.data?.message || err?.message || '操作失败，请重试' }
function applyBatch(result: WorkTaskBatch) { batch.value = result; candidates.value = clone(result.draft?.candidates || []); selected.value = candidates.value.map(c => c.candidate_id); metadata.value = risk.value = false }
function applyTask(result: WorkTask) { task.value = result; Object.assign(taskForm, taskFields(result)); progress.value = result.progress; metadata.value = risk.value = false }
function toggleCandidate(candidateId: string, checked: boolean) { selected.value = checked ? [...new Set([...selected.value, candidateId])] : selected.value.filter(value => value !== candidateId) }
async function load() {
  const token = ++serial, target = id.value
  loading.value = true; error.value = ''; historyError.value = ''; batch.value = task.value = null; versions.value = []; events.value = []; candidates.value = []
  try {
    if (target) {
      if (target.startsWith('WTB-')) {
        const result = await workTaskApi.batch(target)
        if (token !== serial) return
        applyBatch(result)
        try { const history = await workTaskApi.versions(target); if (token === serial) versions.value = history } catch { if (token === serial) historyError.value = '版本记录加载失败' }
      } else {
        const result = await workTaskApi.get(target)
        if (token !== serial) return
        applyTask(result)
        try { const history = await workTaskApi.events(target); if (token === serial) events.value = history } catch { if (token === serial) historyError.value = '变更记录加载失败' }
      }
    } else {
      const result = await workTaskApi.list({ page: page.value, page_size: 20 })
      if (token !== serial) return
      tasks.value = result.items; total.value = result.total
      const batchList = await workTaskApi.batches()
      if (token !== serial) return
      batches.value = batchList
      const notifications = await workTaskApi.notifications()
      if (token === serial) notices.value = notifications
    }
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
  if (busy.value || !sourceForm.source_id.trim()) return
  const payload = { ...sourceForm }, token = serial
  busy.value = true; error.value = ''
  try {
    const result = await replayable('work-task-create', payload, key => workTaskApi.create({ ...payload, idempotency_key: key }))
    busy.value = false
    if (token === serial) await router.push('/work-tasks/' + result.batch_id)
  } catch (err) { problem(err) } finally { busy.value = false }
}
async function batchCommand(action: 'extract' | 'save' | 'confirm' | 'reject') {
  if (!batch.value || busy.value || (action === 'confirm' && !canConfirm.value) || (action === 'save' && !validCandidates.value)) return
  const target = id.value, token = serial, expected_version = batch.value.version
  const payload = action === 'save' ? { expected_version, draft: { candidates: clone(candidates.value) } } : action === 'extract' ? { expected_version } :
    { expected_version, action, selected_candidate_ids: selected.value, metadata_confirmed: metadata.value, risk_acknowledged: risk.value, reason: rejection.value }
  busy.value = true; error.value = ''
  try {
    const result = await replayable('work-task-' + target + '-' + action, payload, key => action === 'save' ? workTaskApi.save(target, { ...payload, idempotency_key: key } as any) :
      action === 'extract' ? workTaskApi.extract(target, { expected_version, idempotency_key: key }) : workTaskApi.decide(target, { ...payload, idempotency_key: key } as any))
    if (token === serial && id.value === target) {
      applyBatch(result)
      try { const history = await workTaskApi.versions(target); if (token === serial && id.value === target) versions.value = history }
      catch { if (token === serial) historyError.value = '版本记录加载失败' }
    }
  } catch (err) { if (token === serial) problem(err) } finally { busy.value = false }
}
async function taskCommand(action: string) {
  if (!task.value || busy.value || (action === 'edit' && (!validTask.value || !metadata.value || !risk.value))) return
  const target = id.value, token = serial, expected_version = task.value.version
  const payload = action === 'edit' ? { ...taskForm, expected_version, metadata_confirmed: metadata.value, risk_acknowledged: risk.value } :
    { action, expected_version, ...(action === 'progress' ? { progress: progress.value } : {}), comment: comment.value }
  busy.value = true; error.value = ''
  try {
    const result = await replayable('work-task-' + target + '-' + action, payload, key => action === 'edit' ?
      workTaskApi.update(target, { ...payload, idempotency_key: key } as any) : workTaskApi.command(target, { ...payload, idempotency_key: key } as any))
    if (token === serial && id.value === target) {
      applyTask(result)
      try { const history = await workTaskApi.events(target); if (token === serial && id.value === target) events.value = history }
      catch { if (token === serial) historyError.value = '变更记录加载失败' }
    }
  } catch (err) { if (token === serial) problem(err) } finally { busy.value = false }
}
async function markRead(notice: TaskNotice) {
  if (busy.value) return
  busy.value = true
  try {
    const record = await workTaskApi.get(notice.task_id)
    const payload = { expected_version: record.version }
    await replayable('task-notice-' + notice.id, payload, key => workTaskApi.read(notice.id, { ...payload, idempotency_key: key }))
    notice.read_at = new Date().toISOString()
  } catch (err) { problem(err) } finally { busy.value = false }
}
</script>

<template>
  <main class="draft-workbench work-task-workbench">
    <header class="heading"><div><h1>{{ task?.title || (isBatch ? '任务候选审阅' : '工作任务') }}</h1><p v-if="batch || task" class="muted">{{ labels[(batch || task)!.status] }} · v{{ (batch || task)!.version }}</p></div>
      <el-button v-if="id" :icon="Back" :disabled="busy" @click="router.push('/work-tasks')">任务列表</el-button><el-button v-else :icon="Refresh" :loading="loading" @click="reload">刷新</el-button></header>
    <el-alert v-if="error" type="error" :title="error" :closable="false" /><el-button v-if="error" :disabled="busy" @click="reload">重新加载</el-button>
    <el-skeleton v-if="loading" :rows="8" animated />
    <div v-else-if="!id" class="draft-layout">
      <section><h2>新建候选批次</h2><el-form label-position="top" :disabled="busy">
        <el-form-item label="来源类型"><el-select v-model="sourceForm.source_type" aria-label="来源类型"><el-option label="内置工单" value="ticket" /><el-option label="已确认会议" value="meeting" /><el-option label="已结束审批" value="approval" /></el-select></el-form-item>
        <el-form-item label="来源编号" required><el-input v-model="sourceForm.source_id" aria-label="来源编号" maxlength="64" /></el-form-item>
        <el-form-item v-if="sourceForm.source_type !== 'ticket'" label="来源版本"><el-input-number v-model="sourceForm.source_version" :min="1" aria-label="来源版本" /></el-form-item>
        <el-button data-testid="create-task-batch" type="primary" :icon="Plus" :loading="busy" :disabled="!sourceForm.source_id.trim()" @click="create">创建候选批次</el-button>
      </el-form></section>
      <section><el-tabs v-model="activeTab"><el-tab-pane label="我的任务" name="tasks">
        <button v-for="item in tasks" :key="item.task_id" class="record-row" @click="router.push('/work-tasks/' + item.task_id)"><span>{{ item.title }}<small>{{ personName(item.assignee_id) }} · {{ new Date(item.due_at).toLocaleString() }}</small></span><span>{{ labels[item.status] }}<small>{{ item.progress }}%</small></span></button>
        <el-empty v-if="!tasks.length" description="暂无工作任务" /><el-pagination v-if="total > 20" v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next" @current-change="load" />
      </el-tab-pane><el-tab-pane label="候选批次" name="batches"><button v-for="item in batches" :key="item.batch_id" class="record-row" @click="router.push('/work-tasks/' + item.batch_id)"><span>{{ item.source.title }}<small>{{ item.batch_id }}</small></span><span>{{ labels[item.status] }}<small>v{{ item.version }}</small></span></button><el-empty v-if="!batches.length" description="暂无候选批次" /></el-tab-pane>
        <el-tab-pane label="逾期通知" name="notices"><article v-for="notice in notices" :key="notice.id" class="notice-row"><router-link :to="'/work-tasks/' + notice.task_id">{{ notice.title }}</router-link><span>{{ notice.stage === 'escalated' ? '超过 24 小时' : '已逾期' }}</span><el-button :icon="Check" :disabled="busy || !!notice.read_at" @click="markRead(notice)">{{ notice.read_at ? '已读' : '标记已读' }}</el-button></article><el-empty v-if="!notices.length" description="暂无逾期通知" /></el-tab-pane></el-tabs></section>
    </div>
    <template v-else-if="batch">
      <el-alert v-if="batch.error" :title="batch.error.message" :description="'追踪编号：' + batch.error.trace_id" type="error" :closable="false" />
      <div class="draft-layout"><section><h2>来源</h2><article class="source"><h3><router-link v-if="sourceTarget" :to="sourceTarget">{{ batch.source.title }}</router-link><template v-else>{{ batch.source.title }}</template></h3><small>{{ sourceDescription(batch.source.ref) }}</small><div class="source-body"><ReadableContent :value="readableSource(batch.source.content)" /></div></article>
        <h2 v-if="versions.length">保存版本</h2><el-collapse><el-collapse-item v-for="version in versions" :key="version.version" :title="'第 ' + version.version + ' 版 · ' + (version.edited_by ? personName(version.edited_by) : '自动提取')"><p v-for="candidate in version.draft.candidates" :key="candidate.candidate_id">{{ candidate.title }} · {{ candidate.assignee_id ? personName(candidate.assignee_id) : '待核实' }} · {{ candidate.due_at ? new Date(candidate.due_at).toLocaleString() : '待核实' }}</p></el-collapse-item></el-collapse>
        <el-alert v-if="historyError" type="warning" :title="historyError" :closable="false" />
      </section><section><h2>任务候选</h2>
        <article v-for="(candidate, index) in candidates" :key="candidate.candidate_id" class="candidate-row">
          <el-checkbox :model-value="selected.includes(candidate.candidate_id)" :disabled="busy || !batch.available_actions.includes('confirm')" @change="(checked: string | number | boolean) => toggleCandidate(candidate.candidate_id, !!checked)">任务 {{ index + 1 }}</el-checkbox>
          <el-form label-position="top" :disabled="busy || !batch.available_actions.includes('edit')"><el-form-item label="标题" required><el-input v-model="candidate.title" :aria-label="'候选标题 ' + (index + 1)" maxlength="255" /></el-form-item>
            <el-form-item label="负责人编号" required><el-input v-model="candidate.assignee_id" :aria-label="'候选负责人 ' + (index + 1)" maxlength="64" /></el-form-item>
            <el-form-item label="截止时间" required><el-date-picker v-model="candidate.due_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" :aria-label="'候选截止时间 ' + (index + 1)" /></el-form-item>
            <el-form-item label="优先级"><el-select v-model="candidate.priority" :aria-label="'候选优先级 ' + (index + 1)"><el-option v-for="(label, value) in priorities" :key="value" :value="value" :label="label" /></el-select></el-form-item><el-form-item label="敏感任务"><el-switch v-model="candidate.sensitive" :aria-label="'敏感任务 ' + (index + 1)" /></el-form-item>
          </el-form><small class="muted">{{ candidate.source_refs.map(sourceDescription).join('；') }}</small>
        </article><el-empty v-if="!candidates.length" description="尚无任务候选" />
        <p v-if="dirty" class="muted">修改尚未保存</p>
        <div v-if="batch.available_actions.includes('confirm')" class="acknowledgments"><el-checkbox v-model="metadata" data-testid="metadata-confirmed" :disabled="busy || dirty">已核对负责人、截止时间与来源</el-checkbox><el-checkbox v-model="risk" data-testid="risk-acknowledged" :disabled="busy || dirty">已确认跨部门、敏感及高优先级风险</el-checkbox></div>
        <div class="toolbar"><el-button v-if="batch.available_actions.includes('edit')" data-testid="save-candidates" :icon="DocumentChecked" :disabled="busy || !dirty || !validCandidates" @click="batchCommand('save')">保存修订</el-button><el-button v-if="batch.available_actions.includes('confirm')" data-testid="confirm-tasks" type="primary" :icon="Check" :disabled="!canConfirm" @click="batchCommand('confirm')">确认创建任务</el-button>
          <el-button v-if="batch.available_actions.some(a => ['extract', 'retry'].includes(a))" :icon="Refresh" :loading="busy" @click="batchCommand('extract')">{{ batch.status === 'PAUSED' ? '重试提取' : '提取候选' }}</el-button></div>
        <template v-if="batch.available_actions.includes('reject')"><el-input v-model="rejection" aria-label="拒绝原因" type="textarea" maxlength="2000" :disabled="busy" /><el-button :icon="Close" :disabled="busy || dirty || !rejection.trim()" @click="batchCommand('reject')">拒绝候选</el-button></template>
        <p v-for="taskId in batch.task_ids" :key="taskId"><router-link :to="'/work-tasks/' + taskId">{{ taskId }}</router-link></p>
      </section></div>
    </template>
    <template v-else-if="task"><div class="draft-layout"><section><h2>任务详情</h2><dl class="metadata-list"><dt>任务编号</dt><dd>{{ task.task_id }}</dd><dt>创建人</dt><dd>{{ personName(task.creator_id) }}</dd><dt>负责人</dt><dd>{{ personName(task.assignee_id) }}</dd><dt>截止时间</dt><dd>{{ new Date(task.due_at).toLocaleString() }}</dd><dt>优先级</dt><dd>{{ priorities[task.priority] }}</dd></dl><el-progress :percentage="task.progress" />
      <article v-if="task.source" class="source"><h3><router-link v-if="sourceTarget" :to="sourceTarget">{{ task.source.title }}</router-link><template v-else>{{ task.source.title }}</template></h3><small>{{ sourceDescription(task.source.ref) }}</small><div class="source-body"><ReadableContent :value="readableSource(task.source.content)" /></div></article>
      <h2>变更记录</h2><ol class="task-events"><li v-for="event in events" :key="event.version">第 {{ event.version }} 版 · {{ personName(event.actor_id) }}{{ businessLabel(event.action) }}<p v-if="event.details.comment">{{ event.details.comment }}</p></li></ol><el-alert v-if="historyError" type="warning" :title="historyError" :closable="false" />
    </section><section><h2>任务处理</h2>
      <el-form v-if="task.available_actions.includes('edit')" label-position="top" :disabled="busy"><el-form-item label="标题"><el-input v-model="taskForm.title" aria-label="任务标题" maxlength="255" /></el-form-item><el-form-item label="负责人编号"><el-input v-model="taskForm.assignee_id" aria-label="任务负责人" maxlength="64" /></el-form-item><el-form-item label="截止时间"><el-date-picker v-model="taskForm.due_at" aria-label="任务截止时间" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" /></el-form-item><el-form-item label="优先级"><el-select v-model="taskForm.priority" aria-label="任务优先级"><el-option v-for="(label, value) in priorities" :key="value" :value="value" :label="label" /></el-select></el-form-item><el-form-item label="敏感任务"><el-switch v-model="taskForm.sensitive" aria-label="任务敏感性" /></el-form-item>
        <div v-if="dirty" class="acknowledgments"><el-checkbox v-model="metadata">已核对任务变更</el-checkbox><el-checkbox v-model="risk">已确认负责人及风险</el-checkbox><el-button :icon="DocumentChecked" :disabled="!validTask || !metadata || !risk" @click="taskCommand('edit')">保存任务变更</el-button></div>
      </el-form>
      <el-form-item v-if="task.available_actions.includes('progress')" label="进度"><el-slider v-model="progress" :min="task.progress" :max="100" :disabled="busy || dirty" show-input /></el-form-item><el-input v-if="task.available_actions.length" v-model="comment" aria-label="处理备注" type="textarea" :rows="3" maxlength="2000" :disabled="busy || dirty" />
      <div class="toolbar"><el-button v-for="action in task.available_actions.filter(a => a !== 'edit')" :key="action" :icon="action === 'cancel' ? Close : Check" :disabled="busy || dirty" :type="action === 'complete' ? 'primary' : 'default'" @click="taskCommand(action)">{{ ({ start: '开始任务', progress: '更新进度', complete: '完成任务', cancel: '取消任务', archive: '归档任务' } as Record<string, string>)[action] }}</el-button></div>
      <el-empty v-if="!task.available_actions.length" :description="labels[task.status]" />
    </section></div></template>
  </main>
</template>

<style scoped>
.candidate-row { border-bottom: 1px solid #d8dde2; padding: 14px 0 20px; margin-bottom: 12px; }
.candidate-row small { overflow-wrap: anywhere; }
.notice-row { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; padding: 12px 0; border-bottom: 1px solid #d8dde2; }
.notice-row a { flex: 1; min-width: 120px; overflow-wrap: anywhere; }
.task-events { padding-left: 22px; line-height: 1.8; }
.source-body { margin-top: 16px; }
.work-task-workbench :deep(.el-date-editor.el-input) { width: 100%; }
.work-task-workbench :deep(.el-slider__runway) { margin-right: 20px; }
.work-task-workbench :deep(.el-checkbox__label) { white-space: normal; }
.work-task-workbench .toolbar { flex-wrap: wrap; }
.work-task-workbench .heading h1 { overflow-wrap: anywhere; }
</style>
