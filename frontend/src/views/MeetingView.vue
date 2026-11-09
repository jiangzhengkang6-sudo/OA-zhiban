<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'
import { meetingApi } from '@/api/meeting'
import type { MeetingDraft, MeetingResponse, MeetingSummary } from '@/types'
import MeetingDraftEditor from '@/components/MeetingDraftEditor.vue'
import MeetingSourceList from '@/components/MeetingSourceList.vue'
import { getCurrentUserId } from '@/api/client'
import { hasRole } from '@/utils/roles'
import { can } from '@/stores/auth'
import { workTaskApi } from '@/api/workTask'
import { replayable as replayTask } from '@/api/draftCommands'
import { List } from '@element-plus/icons-vue'

const route = useRoute(), router = useRouter()
const title = ref(''), content = ref(''), meeting = ref<MeetingResponse | null>(null)
const draft = ref<MeetingDraft | null>(null), items = ref<MeetingSummary[]>([])
const busy = ref(false), loading = ref(false), error = ref('')
const canCreate = computed(() => !!title.value.trim() && !!content.value.trim() && !busy.value)
const editable = computed(() => !!meeting.value?.available_actions.includes('edit'))
const dirty = computed(() => !!meeting.value?.draft && !!draft.value && JSON.stringify(draft.value) !== JSON.stringify(meeting.value.draft))
const validDraft = computed(() => {
  if (!draft.value || !meeting.value || !draft.value.summary.trim()) return false
  const ids = new Set(meeting.value.segments.map(segment => segment.segment_id))
  const validRefs = (refs: string[]) => refs.length > 0 && refs.every(id => ids.has(id))
  return validRefs(draft.value.source_refs) &&
    draft.value.decisions.every(item => !!item.text.trim() && validRefs(item.source_refs)) &&
    draft.value.action_items.every(item => !!item.title.trim() && validRefs(item.source_refs))
})
const meetingId = computed(() => String(route.params.meetingId || ''))
const canAudit = computed(() => hasRole(getCurrentUserId(), 'admin'))
let loadSerial = 0
const statusName: Record<string, string> = { CREATED: '待生成', PROCESSING: '生成中', DRAFT_READY: '待审阅', REVIEWING: '已编辑 · 待审阅', PAUSED: '生成已暂停', CONFIRMED: '已确认', REJECTED: '已拒绝' }
function apply(result: MeetingResponse) {
  const schedule=meeting.value?.meeting_id===result.meeting_id?meeting.value.schedule_id:null
  meeting.value = { ...result, schedule_id:result.schedule_id||schedule }
  draft.value = result.draft ? structuredClone(result.draft) : null
}
function problem(err: unknown) {
  const message = (axios.isAxiosError(err) && err.response?.data?.message) || (err instanceof Error ? err.message : '操作未完成，请刷新后重试')
  error.value = /降级|关闭/.test(message) ? `降级阻断：${message}。当前草稿未改变，恢复后可重试。` : message
}
async function load() {
  const serial = ++loadSerial, target = meetingId.value
  loading.value = true; error.value = ''
  meeting.value = null; draft.value = null; items.value = []
  try {
    if (target) { const result = await meetingApi.get(target); if (serial === loadSerial && meetingId.value === target) apply(result) }
    else { const result = await meetingApi.list(); if (serial === loadSerial && !meetingId.value) items.value = result.items }
  } catch (err) { if (serial === loadSerial) problem(err) } finally { if (serial === loadSerial) loading.value = false }
}
watch(meetingId, () => { void load() }, { immediate: true })
async function perform(target: string, command: () => Promise<MeetingResponse>) {
  if (busy.value || !target || meetingId.value !== target || meeting.value?.meeting_id !== target) return
  busy.value = true; error.value = ''
  try { const result = await command(); if (meetingId.value === target) apply(result) }
  catch (err) { if (meetingId.value === target) problem(err) }
  finally { busy.value = false }
}
async function replayable(scope: string, payload: unknown, command: (idempotency_key: string) => Promise<MeetingResponse>) {
  const idempotency_key = await meetingApi.commandKey(scope, payload)
  const result = await command(idempotency_key)
  await meetingApi.releaseCommandKey(scope, payload)
  return result
}
async function create() {
  if (!canCreate.value) return
  busy.value = true; error.value = ''
  try {
    const payload = { title: title.value.trim(), content: content.value, source_type: 'paste' as const }
    const result = await replayable('meeting-create', payload, idempotency_key => meetingApi.create({ ...payload, idempotency_key }))
    if (!meetingId.value) {
      apply(result)
      await router.push(`/meetings/${result.meeting_id}`)
    }
  } catch (err) { problem(err) } finally { busy.value = false }
}
async function generate() {
  const id = meeting.value?.meeting_id
  if (id) await perform(id, () => replayable('meeting-generate', { id }, idempotency_key => meetingApi.generate(id, { idempotency_key })))
}
async function retry() {
  const id = meeting.value?.meeting_id
  if (id) await perform(id, () => replayable('meeting-retry', { id, status: meeting.value?.status, version: meeting.value?.version },
    idempotency_key => meetingApi.retry(id, { idempotency_key })))
}
async function save() {
  if (!meeting.value?.version || !draft.value || !validDraft.value || !dirty.value) return
  const id = meeting.value.meeting_id, payload = { draft: JSON.parse(JSON.stringify(draft.value)) as MeetingDraft, expected_version: meeting.value.version }
  await perform(id, () => replayable('meeting-edit', { id, ...payload }, idempotency_key => meetingApi.save(id, { ...payload, idempotency_key })))
}
async function decide(action: 'confirm' | 'reject' | 'regenerate') {
  if (!meeting.value?.version) return
  if (dirty.value) { error.value = '草稿有未保存的修改，请先保存新版本后再操作。'; return }
  const id = meeting.value.meeting_id, expected_version = meeting.value.version
  let reason: string | null = null
  try {
    if (action === 'reject') reason = (await ElMessageBox.prompt('请填写拒绝原因', '拒绝会议草稿', { inputValidator: value => !!value.trim() || '请填写拒绝原因' })).value
    else await ElMessageBox.confirm(action === 'confirm' ? '确认当前版本的纪要草稿？本阶段只保存平台内确认记录。' : '重新生成将保留旧版本并创建新的草稿。', action === 'confirm' ? '确认草稿' : '重新生成')
  } catch { return }
  if (meetingId.value !== id || meeting.value?.meeting_id !== id || meeting.value.version !== expected_version) return
  const payload = { action, reason, expected_version }
  await perform(id, () => replayable(`meeting-${action}`, { id, ...payload }, idempotency_key => meetingApi.decide(id, { ...payload, idempotency_key })))
  if (!error.value) ElMessage.success(action === 'confirm' ? '已确认' : action === 'reject' ? '已拒绝' : '已重新生成')
  if (!error.value && action==='confirm') await load()
}
async function createTasks(){
  if(!meeting.value?.can_create_tasks||busy.value||!can('work_task','write'))return
  const target=meeting.value.meeting_id,version=meeting.value.version
  busy.value=true;error.value=''
  try{
    const payload={source_type:'meeting' as const,source_id:target,source_version:version||undefined}
    const result=await replayTask('meeting-task:'+target+':'+version,payload,key=>workTaskApi.create({...payload,idempotency_key:key}))
    if(meetingId.value===target)await router.push('/work-tasks/'+result.batch_id)
  }catch(e){problem(e)}finally{busy.value=false}
}
</script>

<template>
  <main class="meeting-page">
    <header class="heading"><div><p class="eyebrow">会议文本 · 工作台</p><h1>{{ meeting?.title || '整理一场会议' }}</h1><p class="subhead">{{ meeting ? `${meeting.meeting_id} · ${statusName[meeting.status]}${meeting.version ? ` · 草稿 v${meeting.version}` : ''}` : '粘贴会议文字，生成可以逐条核对来源的纪要草稿。' }}</p></div><el-button @click="router.push(meeting?.schedule_id?'/meeting-events/'+meeting.schedule_id:'/meetings')">{{meeting?.schedule_id?'返回会议安排':'返回会议列表'}}</el-button></header>
    <el-alert v-if="error" :title="error" type="warning" show-icon :closable="false" class="error" />
    <el-skeleton v-if="loading" :rows="8" animated />
    <template v-else-if="meetingId && !meeting">
      <el-result icon="warning" :title="error || '会议暂时无法加载'"><template #extra><el-button @click="load">重新加载</el-button><el-button @click="router.push('/meetings')">返回会议列表</el-button></template></el-result>
    </template>
    <template v-else-if="!meeting">
      <div class="start-layout"><section class="start-card"><h2>创建会议任务</h2><p>支持粘贴的会议文字。创建后可生成、编辑和确认草稿。</p><label for="meeting-title">会议标题</label><el-input id="meeting-title" v-model="title" aria-label="会议标题" maxlength="255" placeholder="例如：项目验收周会" /><label for="meeting-content">会议文本</label><el-input id="meeting-content" v-model="content" aria-label="会议文本" type="textarea" :rows="10" placeholder="粘贴议题、讨论、决策和待办内容" /><div class="start-footer"><span>内容只用于本平台会议草稿。</span><el-button type="primary" data-testid="create-meeting" :disabled="!canCreate" :loading="busy" @click="create">创建会议</el-button></div></section>
        <section class="recent"><h2>最近会议</h2><el-empty v-if="!items.length" description="尚无会议任务" /><button v-for="item in items" :key="item.meeting_id" class="meeting-row" @click="router.push(`/meetings/${item.meeting_id}`)"><span><strong>{{ item.title }}</strong><small>{{ item.meeting_id }}</small></span><span>{{ statusName[item.status] }} →</span></button></section></div>
    </template>
    <template v-else>
      <el-button v-if="meeting.can_create_tasks&&can('work_task','write')" :icon="List" :loading="busy" @click="createTasks">提取业务任务</el-button>
      <div class="notice"><span class="notice-dot" /> {{ meeting.schedule_id ? '确认后发布纪要并通知参会人员；业务任务须另行核对并确认创建。' : '人工确认只保存会议记录，不会写入 OA、任务、日历或邮件。' }}</div>
      <div class="toolbar"><div><el-button v-if="meeting.available_actions.includes('generate')" type="primary" :loading="busy" @click="generate">生成草稿</el-button><el-button v-if="meeting.available_actions.includes('retry')" type="primary" data-testid="retry-meeting" :loading="busy" @click="retry">从恢复点重试</el-button><el-button v-if="editable" data-testid="save-meeting" :disabled="!validDraft || !dirty || busy" @click="save">保存新版本</el-button><el-button v-if="meeting.available_actions.includes('confirm')" type="primary" data-testid="confirm-meeting" :disabled="busy || dirty" @click="decide('confirm')">确认草稿</el-button><el-button v-if="meeting.available_actions.includes('reject')" :disabled="busy || dirty" @click="decide('reject')">拒绝</el-button><el-button v-if="meeting.available_actions.includes('regenerate')" :disabled="busy || dirty" @click="decide('regenerate')">重新生成</el-button></div><el-button v-if="canAudit" text @click="router.push({ path: '/audit', query: { business_id: meeting.meeting_id } })">查看审计轨迹</el-button></div>
      <p v-if="dirty" class="pause-note">有未保存的草稿修改。先保存新版本，再确认、拒绝或重新生成。</p>
      <p v-if="meeting.status === 'PAUSED'" class="pause-note">生成依赖失败，任务已安全暂停。每次点击重试会发起一次新尝试；若场景被运维降级阻断，当前草稿保持原状。</p>
      <div class="review-layout"><MeetingSourceList :segments="meeting.segments" /><MeetingDraftEditor v-if="draft" v-model="draft" :segments="meeting.segments" :editable="editable" /><section v-else class="empty-draft"><h2>纪要草稿</h2><p>生成后可在此审阅纪要、决策和待办。</p></section></div>
    </template>
  </main>
</template>

<style scoped>
.meeting-page { max-width: 1440px; margin: 0 auto; padding: 20px clamp(16px, 3vw, 44px) 70px; color: #24445b; }
.heading { display: flex; justify-content: space-between; align-items: flex-start; gap: 20px; margin-bottom: 25px; }
.eyebrow { font-size: 12px; font-weight: 700; letter-spacing: .12em; color: #287987; margin: 0 0 10px; }
h1 { font-size: clamp(25px, 2.4vw, 34px); color: #17324d; letter-spacing: -.02em; margin: 0 0 8px; }
.subhead { color: #647d91; margin: 0; line-height: 1.6; }
.error { margin-bottom: 18px; }
.notice { display: flex; align-items: center; gap: 10px; padding: 12px 16px; border: 1px solid #cde7e3; border-radius: 10px; background: #eff9f6; color: #286b68; font-size: 13px; }
.notice-dot { width: 7px; height: 7px; border-radius: 50%; background: #31a394; }
.toolbar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin: 20px 0; }
.toolbar > div { display: flex; flex-wrap: wrap; gap: 8px; }
.toolbar :deep(.el-button + .el-button) { margin-left: 0; }
.pause-note { background: #fff6e8; border-left: 3px solid #d39a43; padding: 12px 16px; line-height: 1.7; }
.review-layout { display: grid; grid-template-columns: minmax(280px, .9fr) minmax(420px, 1.1fr); align-items: start; gap: 28px; }
.review-layout > :last-child, .start-card, .recent { border: 1px solid #dde9ed; border-radius: 14px; background: #fff; padding: 24px; box-shadow: 0 8px 32px rgba(36,68,91,.04); }
.review-layout > :first-child { background: #f3f8fa; border: 1px solid #e1ecef; border-radius: 14px; padding: 24px; }
.empty-draft h2,.start-card h2,.recent h2 { font-size: 18px; color: #17324d; margin: 0 0 13px; }
.empty-draft p,.start-card p { color: #647d91; line-height: 1.7; }
.start-layout { display: grid; grid-template-columns: minmax(400px, 1.25fr) minmax(280px, .75fr); gap: 24px; align-items: start; }
.start-card label { display: block; font-weight: 600; margin: 22px 0 8px; }
.start-footer { display: flex; justify-content: space-between; align-items: center; margin-top: 20px; gap: 15px; font-size: 13px; color: #738b9b; }
.meeting-row { width: 100%; border: 0; border-top: 1px solid #e2ebee; padding: 15px 0; background: none; cursor: pointer; display: flex; justify-content: space-between; gap: 16px; align-items: center; text-align: left; color: #247888; }
.meeting-row:hover { color: #125866; }
.meeting-row strong { display: block; font-size: 14px; color: #284258; }
.meeting-row small { display: block; margin-top: 5px; color: #8498a6; }
@media (max-width: 1000px) { .review-layout,.start-layout { grid-template-columns: 1fr; } }
@media (max-width: 600px) { .heading,.start-footer { flex-direction: column; align-items: flex-start; } .review-layout > :first-child,.review-layout > :last-child,.start-card,.recent { padding: 17px; } }
</style>
