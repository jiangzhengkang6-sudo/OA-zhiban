<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Message, EditPen, Refresh, Search, Setting, Check, Upload, Document, User, Close, Back, Position } from '@element-plus/icons-vue'
import { publicMailApi as api, type MailboxStatus, type PublicMessage, type MailMembers, type MailMember } from '@/api/publicMail'
import { replayable } from '@/api/draftCommands'
import { authState, can } from '@/stores/auth'

const router = useRouter()
const box = ref<MailboxStatus | null>(null), rows = ref<PublicMessage[]>([]), selected = ref<PublicMessage | null>(null)
const busy = ref(false), loading = ref(true), error = ref(''), folder = ref('inbox'), search = ref(''), page = ref(1), total = ref(0)
const composing = ref(false), baseline = ref(''), membersOpen = ref(false), memberData = ref<MailMembers | null>(null)
const memberRows = ref<(MailMember & { name: string; writable: boolean; selected: boolean })[]>([])
const form = reactive({ subject: '', recipients: '', body: '', reply_to_id: null as string | null })
const labels: Record<string, string> = { NEW: '待处理', PROCESSING: '处理中', DONE: '已处理', DRAFT: '草稿',
  SENDING: '发送中 / 待核实', ACCEPTED: '服务器已接收', FAILED: '发送失败', UNKNOWN: '发送结果待核实' }
const folders = [ { value: 'inbox', label: '收件箱', icon: Message }, { value: 'pending', label: '待处理', icon: User },
  { value: 'drafts', label: '草稿箱', icon: EditPen }, { value: 'sent', label: '发件记录', icon: Position } ]
const dirty = computed(() => composing.value && JSON.stringify(form) !== baseline.value)
const addresses = computed(() => form.recipients.split(/[,;，；\n]/).map(v => v.trim()).filter(Boolean))
const valid = computed(() => form.subject.trim() && form.body.trim() && addresses.value.length > 0 && addresses.value.length <= 30 &&
  addresses.value.every(v => /^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$/.test(v)))
const owned = computed(() => !selected.value?.claimed_by || selected.value.claimed_by === box.value?.user_id)
let serial = 0
function problem(e: any) { error.value = e?.response?.data?.message || e?.message || '操作失败，请重试' }
function time(value?: string | null) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—' }
async function guard() {
  if (busy.value) return false
  if (!dirty.value) return true
  try { await ElMessageBox.confirm('当前邮件尚未保存，确认放弃修改？', '未保存的邮件'); return true } catch { return false }
}
onBeforeRouteLeave(guard)
async function list() {
  const token = ++serial
  const result = await api.list({ folder: folder.value, search: search.value, page: page.value })
  if (token === serial) { rows.value = result.items; total.value = result.total }
}
async function run(work: () => Promise<void>) {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { await work() } catch (e) { problem(e) } finally { busy.value = false }
}
async function load() {
  loading.value = true; error.value = ''
  try { box.value = await api.status(); if (box.value.authorized) await list() }
  catch (e) { problem(e) } finally { loading.value = false }
}
onMounted(load)
async function setup() { await run(async () => { box.value = await api.setup(); await list() }) }
async function refresh() {
  if (!await guard()) return
  await run(async () => { await load(); if (selected.value) apply(await api.get(selected.value.id)) })
}
async function changeFolder(value: string) {
  if (!await guard()) return
  folder.value = value; page.value = 1; selected.value = null; composing.value = false
  await run(list)
}
function apply(value: PublicMessage) {
  selected.value = value
  composing.value = value.status === 'DRAFT' && !!box.value?.can_send
  if (composing.value) {
    Object.assign(form, { subject: value.subject, recipients: value.recipients.join('; '), body: value.body || '', reply_to_id: value.reply_to_id })
    baseline.value = JSON.stringify(form)
  }
}
async function open(row: PublicMessage) {
  if (!await guard()) return
  await run(async () => { apply(await api.get(row.id)) })
}
async function compose(reply = false, all = false, forward = false) {
  if (!await guard()) return
  const source = selected.value
  if ((reply || forward) && !source) return
  if (forward) {
    try { await ElMessageBox.confirm('仅转发文字正文，不包含附件，是否继续？', '转发邮件') } catch { return }
  }
  Object.assign(form, {
    subject: source && (reply || forward) ? (forward ? '转发：' : '回复：') + source.subject : '',
    recipients: reply && source ? [...new Set([source.sender, ...(all ? source.recipients : [])])]
      .filter(a => a.toLowerCase() !== box.value?.address?.toLowerCase()).join('; ') : '',
    body: forward && source ? `\n\n发件人：${source.sender}\n主题：${source.subject}\n\n${source.body || ''}`.slice(0, 30000) : '',
    reply_to_id: reply && source ? source.id : null,
  })
  selected.value = null; composing.value = true; baseline.value = JSON.stringify(form)
}
async function save() {
  if (!valid.value) return
  await run(async () => {
    const payload = { subject: form.subject, recipients: addresses.value, body: form.body,
      reply_to_id: form.reply_to_id, expected_version: selected.value?.version || 0 }
    const result = await replayable('public-mail-draft-' + (selected.value?.id || 'new'), payload,
      key => api.save({ ...payload, idempotency_key: key }, selected.value?.id))
    apply(result); await list(); ElMessage.success('草稿已保存')
  })
}
async function command(action: string) {
  if (!selected.value || busy.value) return
  if (action === 'send') {
    if (dirty.value) return
    try { await ElMessageBox.confirm(`收件人：${selected.value.recipients.join('；')}\n主题：${selected.value.subject}\n确认以公共邮箱发送此邮件？`,
      '确认发送', { confirmButtonText: '确认发送', cancelButtonText: '取消' }) } catch { return }
  }
  await run(async () => {
    apply(await api.action(selected.value!.id, { action, expected_version: selected.value!.version, confirmed: action === 'send' }))
    await list()
  })
}
async function sync() { await run(async () => {
  const result = await api.sync(); box.value = await api.status(); await list()
  ElMessage.success(`本次新增 ${result.added} 封邮件${result.has_more ? '，还有邮件可继续同步' : ''}`)
}) }
async function convert(kind: 'analysis' | 'task') {
  if (!selected.value) return
  let target = ''
  await run(async () => {
    if (kind === 'analysis') target = '/emails/' + (selected.value!.analysis_id || (await api.import(selected.value!.id)).email_id)
    else target = '/work-tasks/' + (await api.task(selected.value!.id)).batch_id
  })
  if (target) await router.push(target)
}
async function editMembers() {
  if (!await guard()) return
  await run(async () => {
    memberData.value = await api.members()
    memberRows.value = memberData.value.users.map(u => ({ ...u, selected: memberData.value!.members.some(m => m.user_id === u.user_id),
      can_process: false, can_send: false, can_manage: false, ...memberData.value!.members.find(m => m.user_id === u.user_id) }))
    membersOpen.value = true
  })
}
async function saveMembers() {
  await run(async () => {
    await api.saveMembers({ expected_revision: memberData.value!.revision, members: memberRows.value.filter(m => m.selected)
      .map(({ user_id, can_process, can_send, can_manage }) => ({ user_id, can_process, can_send, can_manage })) })
    membersOpen.value = false; selected.value = null; composing.value = false; await load()
  })
}
function closeMembers(done: () => void) { if (!busy.value) done() }
</script>

<template>
  <main class="mail-workspace" :aria-busy="busy">
    <header class="mail-heading"><div><h1>{{ box?.name || '综合办公公共邮箱' }}</h1><p>{{ box?.address || '邮件工作台' }}<span v-if="box?.synced_at"> · 最近同步 {{ time(box.synced_at) }}</span></p></div>
      <div class="mail-tools"><el-button v-if="authState.aiEnabled" :icon="Document" :disabled="busy" @click="router.push('/emails/manual-entry')">分析记录</el-button>
        <el-tooltip v-if="box?.can_manage" content="成员授权"><el-button :icon="Setting" aria-label="成员授权" :disabled="busy" @click="editMembers" /></el-tooltip>
        <el-tooltip content="刷新"><el-button :icon="Refresh" aria-label="刷新公共邮箱" :disabled="busy" @click="refresh" /></el-tooltip></div>
    </header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-skeleton v-if="loading" :rows="8" animated />
    <section v-else-if="!box?.authorized" class="mail-empty">
      <el-empty :description="box?.provisioned ? '尚未获得公共邮箱访问授权，请联系邮箱管理员' : '公共邮箱尚未初始化'" />
      <el-button v-if="box?.can_setup" type="primary" :icon="Check" :loading="busy" @click="setup">启用综合办公公共邮箱</el-button>
    </section>
    <div v-else class="mail-columns">
      <nav class="mail-folders" aria-label="邮件文件夹">
        <el-button v-if="box.can_send" type="primary" :icon="EditPen" :disabled="busy" @click="compose()">写邮件</el-button>
        <button v-for="item in folders" :key="item.value" :class="{ active: folder === item.value }" :disabled="busy" @click="changeFolder(item.value)">
          <el-icon><component :is="item.icon" /></el-icon>{{ item.label }}</button>
        <el-button v-if="box.can_process" :icon="Refresh" :loading="busy" @click="sync">同步收信</el-button>
      </nav>
      <section class="mail-list" aria-label="邮件列表">
        <el-input v-model="search" aria-label="搜索邮件" placeholder="搜索主题或发件人" clearable :prefix-icon="Search" :disabled="busy" @keyup.enter="page = 1; run(list)" @clear="page = 1; run(list)" />
        <div class="mail-list-items"><button v-for="row in rows" :key="row.id" class="mail-list-row" :class="{ selected: selected?.id === row.id }" :disabled="busy" @click="open(row)">
          <span class="mail-row-top"><strong>{{ row.direction === 'incoming' ? row.sender : row.recipients.join('；') }}</strong><span>{{ labels[row.status] || row.status }}</span></span>
          <span class="mail-row-subject">{{ row.subject }}</span><small>{{ time(row.sent_at || row.created_at) }}<span v-if="row.claimed_by_name"> · {{ row.claimed_by_name }}</span></small>
        </button><el-empty v-if="!rows.length" description="暂无邮件" :image-size="70" /></div>
        <el-pagination v-if="total > 20" v-model:current-page="page" small layout="prev, pager, next" :pager-count="5" :page-size="20" :total="total" :disabled="busy" @current-change="run(list)" />
      </section>
      <section class="mail-detail" aria-label="邮件详情">
        <template v-if="composing">
          <div class="mail-detail-heading"><h2>{{ form.reply_to_id ? '回复邮件' : selected ? '编辑草稿' : '新邮件' }}</h2><el-tag>草稿</el-tag></div>
          <el-form label-position="top" :disabled="busy"><el-form-item label="发件人"><el-input :model-value="box.address" disabled /></el-form-item>
            <el-form-item label="收件人" required><el-input v-model="form.recipients" aria-label="邮件收件人" placeholder="多个邮箱用分号分隔" /></el-form-item>
            <el-form-item label="主题" required><el-input v-model="form.subject" aria-label="邮件主题" maxlength="255" /></el-form-item>
            <el-form-item label="正文" required><el-input v-model="form.body" aria-label="邮件正文" type="textarea" :rows="13" maxlength="30000" /></el-form-item></el-form>
          <div class="mail-tools"><el-button :icon="Check" :disabled="!valid || busy" data-testid="save-public-draft" @click="save">保存草稿</el-button>
            <el-button type="primary" :icon="Position" :disabled="!selected || dirty || busy" data-testid="send-public-mail" @click="command('send')">发送</el-button>
            <span v-if="dirty" class="mail-muted">未保存</span></div>
        </template>
        <template v-else-if="selected">
          <div class="mail-detail-heading"><h2>{{ selected.subject }}</h2><el-tag>{{ labels[selected.status] || selected.status }}</el-tag></div>
          <dl class="mail-envelope"><dt>发件人</dt><dd>{{ selected.sender }}</dd><dt>收件人</dt><dd>{{ selected.recipients.join('；') }}</dd>
            <dt>时间</dt><dd>{{ time(selected.sent_at || selected.created_at) }}</dd><template v-if="selected.claimed_by_name"><dt>经办人</dt><dd>{{ selected.claimed_by_name }}</dd></template>
            <template v-if="selected.sent_by_name"><dt>发送人</dt><dd>{{ selected.sent_by_name }}</dd></template></dl>
          <el-alert v-if="selected.status === 'ACCEPTED'" title="邮件服务器已接收，不代表对方已送达或已读。" type="success" :closable="false" />
          <el-alert v-if="['UNKNOWN', 'SENDING'].includes(selected.status)" title="发送结果尚未确认，请先在原邮箱或联系收件人核实，不要重复发送。" type="warning" :closable="false" />
          <el-alert v-if="selected.status === 'FAILED'" title="发送失败，未自动重试。请检查收件地址和邮箱服务。" type="error" :closable="false" />
          <div v-if="selected.direction === 'incoming'" class="mail-tools mail-actions">
            <el-button v-if="box.can_send && owned" :icon="Back" :disabled="busy" @click="compose(true)">回复</el-button>
            <el-button v-if="box.can_send && owned" :icon="Back" :disabled="busy" @click="compose(true, true)">回复全部</el-button>
            <el-button v-if="box.can_send" :icon="Position" :disabled="busy" @click="compose(false, false, true)">转发</el-button>
            <el-button v-if="authState.aiEnabled && (selected.analysis_id || (box.can_process && owned))" :icon="Upload" :disabled="busy" @click="convert('analysis')">{{ selected.analysis_id ? '查看分析' : '录入并分析' }}</el-button>
            <el-button v-if="box.can_process && owned && can('work_task', 'write')" :icon="Document" :disabled="busy" @click="convert('task')">转为任务</el-button>
            <el-button v-if="box.can_process && !selected.claimed_by && selected.status !== 'DONE'" :icon="User" :disabled="busy" @click="command('claim')">认领</el-button>
            <el-button v-if="box.can_process && selected.claimed_by && (owned || box.can_manage)" :icon="Close" :disabled="busy" @click="command('release')">释放认领</el-button>
            <el-button v-if="box.can_process && owned && selected.status !== 'DONE'" :icon="Check" :disabled="busy" @click="command('complete')">标记已处理</el-button>
            <el-button v-if="box.can_process && owned && selected.status === 'DONE'" :icon="Refresh" :disabled="busy" @click="command('reopen')">重新打开</el-button>
          </div>
          <p class="mail-body">{{ selected.body }}</p>
          <section v-if="selected.attachments?.length" class="mail-attachments"><h3>附件信息</h3><p class="mail-muted">附件未保存或扫描，请在原邮箱中核验。</p><p v-for="(a, i) in selected.attachments" :key="i"><el-icon><Document /></el-icon> {{ a.name }}</p></section>
        </template>
        <el-empty v-else description="请选择一封邮件" :image-size="100" />
      </section>
    </div>
    <el-dialog v-model="membersOpen" title="公共邮箱成员授权" width="min(760px, calc(100vw - 32px))" :close-on-click-modal="false" :before-close="closeMembers">
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
      <el-table :data="memberRows" max-height="440"><el-table-column label="成员" min-width="110"><template #default="{ row }"><el-checkbox v-model="row.selected" :disabled="busy">{{ row.name }}</el-checkbox></template></el-table-column>
        <el-table-column v-for="field in ([['can_process', '处理'], ['can_send', '发送'], ['can_manage', '管理']] as const)" :key="field[0]" :label="field[1]" width="70"><template #default="{ row }"><el-checkbox v-model="row[field[0]]" :aria-label="row.name + field[1]" :disabled="!row.selected || !row.writable || busy" /></template></el-table-column></el-table>
      <template #footer><el-button :disabled="busy" @click="membersOpen = false">取消</el-button><el-button type="primary" :loading="busy" @click="saveMembers">保存授权</el-button></template>
    </el-dialog>
  </main>
</template>

<style scoped>
.mail-workspace { padding: 24px; max-width: 1800px; margin: auto; }
.mail-heading, .mail-detail-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
.mail-heading h1 { font-size: 23px; margin: 0 0 8px; }
.mail-heading p, .mail-muted { color: #69757b; font-size: 13px; margin: 0; overflow-wrap: anywhere; }
.mail-tools { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.mail-tools .el-button + .el-button { margin-left: 0; }
.mail-columns { display: grid; grid-template-columns: 148px 300px minmax(0, 1fr); border-top: 1px solid #dce3e5; min-height: 620px; background: #fff; }
.mail-folders { display: flex; flex-direction: column; gap: 8px; padding: 18px 12px 18px 0; border-right: 1px solid #e2e7e9; }
.mail-folders > button:not(.el-button) { display: flex; align-items: center; gap: 10px; border: 0; padding: 13px 12px; background: transparent; cursor: pointer; text-align: left; font-size: 14px; color: #46535b; border-radius: 4px; }
.mail-folders > button.active { background: #e5f3ed; color: #16764c; font-weight: 600; }
.mail-folders .el-button { margin: 0; }
.mail-list { padding: 18px 0 12px; border-right: 1px solid #e2e7e9; min-width: 0; }
.mail-list > .el-input { width: calc(100% - 24px); margin: 0 12px 12px; }
.mail-list-items { max-height: 650px; overflow-y: auto; }
.mail-list-row { display: flex; flex-direction: column; gap: 8px; width: 100%; min-height: 108px; text-align: left; padding: 16px; border: 0; border-bottom: 1px solid #edf0f1; background: white; cursor: pointer; color: #25333a; }
.mail-list-row:hover, .mail-list-row.selected { background: #f0f6f8; }
.mail-row-top { display: flex; justify-content: space-between; gap: 8px; width: 100%; font-size: 12px; }
.mail-row-top strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.mail-row-top > span { flex-shrink: 0; color: #57717e; }
.mail-row-subject { overflow-wrap: anywhere; font-size: 14px; font-weight: 600; }
.mail-list-row small { color: #78868c; font-size: 11px; }
.mail-detail { padding: 24px; min-width: 0; }
.mail-detail-heading h2 { font-size: 19px; margin: 0; overflow-wrap: anywhere; line-height: 1.5; }
.mail-detail-heading .el-tag { flex-shrink: 0; }
.mail-envelope { display: grid; grid-template-columns: 56px minmax(0,1fr); gap: 8px 12px; font-size: 13px; margin: 0 0 20px; }
.mail-envelope dt { color: #7b878c; }.mail-envelope dd { margin: 0; overflow-wrap: anywhere; }
.mail-body { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.85; font-size: 14px; padding: 20px 0; margin: 0; }
.mail-actions { padding: 18px 0 0; }.mail-attachments { border-top: 1px solid #e2e7e9; padding-top: 12px; }
.mail-attachments h3 { font-size: 14px; }.mail-attachments p { overflow-wrap: anywhere; }.mail-empty { text-align: center; padding: 40px 0; }
@media (max-width: 1200px) { .mail-columns { grid-template-columns: 124px 250px minmax(0,1fr); }.mail-detail { padding: 18px; } }
@media (max-width: 900px) { .mail-workspace { padding: 16px; }.mail-columns { grid-template-columns: 132px minmax(0,1fr); }.mail-detail { grid-column: 1 / -1; border-top: 1px solid #dce3e5; }.mail-list { border-right: 0; }.mail-list-items { max-height: 300px; }.mail-heading { align-items: flex-start; flex-direction: column; } }
@media (max-width: 480px) { .mail-columns { grid-template-columns: 104px minmax(0,1fr); }.mail-folders { padding-right: 8px; }.mail-row-top { flex-direction: column; }.mail-detail { padding: 18px 8px; }.mail-detail-heading { align-items: flex-start; flex-direction: column; } }
</style>
