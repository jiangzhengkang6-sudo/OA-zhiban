<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { leaveApi } from '@/api'
import { getCurrentUserId } from '@/api/client'
import type { LeaveApplication, LeaveVersion, LeaveAttachment } from '@/types'
import { localDateTime, normalizePrecheck } from '@/utils/leave'
import StatusTag from '@/components/StatusTag.vue'
import PrecheckTable from '@/components/PrecheckTable.vue'
import LeaveDiff from '@/components/LeaveDiff.vue'
const route = useRoute(), router = useRouter()
const application = ref<LeaveApplication | null>(null), versions = ref<LeaveVersion[]>([])
const loading = ref(false), saving = ref(false), error = ref(''), comparison = ref(0)
const attachments = ref<LeaveAttachment[]>([])
const uploading = ref(false), scanning = ref(''), downloading = ref(''), attachmentError = ref('')
const busy = computed(() => saving.value || uploading.value || !!scanning.value)
const form = reactive({ leave_type: 'annual', start_at: '', end_at: '', reason: '', attachments: [] as string[] })
const precheckPaused = computed(() => application.value?.status === 'PAUSED' && (application.value.precheck as any)?.status === 'PAUSED')
const editable = computed(() => !application.value || ['DRAFT', 'NEEDS_FIX', 'REJECTED'].includes(application.value.status) || precheckPaused.value)
const duration = computed(() => { const hours = (new Date(form.end_at).getTime() - new Date(form.start_at).getTime()) / 3600000; return hours > 0 ? hours.toFixed(1) : '—' })
const before = computed(() => versions.value.find(v => v.version === comparison.value)?.fields)
function apply(data: LeaveApplication) {
  application.value = data
  form.leave_type = data.fields.leave_type || 'annual'; form.start_at = localDateTime(data.fields.start_at)
  form.end_at = localDateTime(data.fields.end_at); form.reason = data.fields.reason || ''; form.attachments = [...(data.fields.attachments || [])]
}
async function history(id: string) {
  versions.value = await leaveApi.versions(id)
  comparison.value = versions.value.at(-2)?.version || versions.value[0]?.version || 0
}
async function loadAttachments(id: string) {
  attachmentError.value = ''
  try {
    attachments.value = await leaveApi.attachments(id)
    form.attachments = [...new Set([...form.attachments, ...attachments.value.map(item => item.attachment_id)])]
  } catch { attachmentError.value = '无法加载证明材料，请重试' }
}
async function load() {
  const id = String(route.params.applicationId || '')
  attachments.value = []; attachmentError.value = ''
  if (!id || id === 'new') {
    application.value = null; versions.value = []; loading.value = false; error.value = ''
    Object.assign(form, { leave_type: 'annual', start_at: '', end_at: '', reason: '', attachments: [] })
    return
  }
  loading.value = true; error.value = ''; application.value = null
  try { apply(await leaveApi.get(id)); await history(id); await loadAttachments(id) }
  catch { error.value = '无法加载申请，请确认当前账号的访问权限后重试' }
  finally { loading.value = false }
}
function scanLabel(status: string) {
  return ({ PENDING: '待扫描', CLEAN: '扫描通过', INFECTED: '检测到风险', ERROR: '扫描失败' } as Record<string, string>)[status] || '状态未知'
}
function formatBytes(size: number) {
  if (size < 1024) return size + ' B'
  return size < 1024 * 1024 ? (size / 1024).toFixed(1) + ' KB' : (size / 1024 / 1024).toFixed(1) + ' MB'
}
function updateAttachment(item: LeaveAttachment) {
  const index = attachments.value.findIndex(existing => existing.attachment_id === item.attachment_id)
  if (index >= 0) attachments.value.splice(index, 1, item)
  else attachments.value.push(item)
  if (!form.attachments.includes(item.attachment_id)) form.attachments.push(item.attachment_id)
}
async function uploadFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  if (!files.length || busy.value || !editable.value || !application.value) return
  const id = application.value.application_id
  uploading.value = true
  try {
    for (const file of files) updateAttachment(await leaveApi.uploadAttachment(id, file))
    ElMessage.success('证明材料已上传')
  } catch { /* 客户端显示具体错误，已上传的附件继续保留。 */ }
  finally { uploading.value = false }
}
async function rescanAttachment(item: LeaveAttachment) {
  if (!application.value || !editable.value || busy.value) return
  scanning.value = item.attachment_id
  try { updateAttachment(await leaveApi.scanAttachment(application.value.application_id, item.attachment_id)) }
  catch { /* 保留已有扫描状态，客户端显示具体错误。 */ }
  finally { scanning.value = '' }
}
async function downloadAttachment(item: LeaveAttachment) {
  if (!application.value || item.scan_status !== 'CLEAN' || downloading.value) return
  downloading.value = item.attachment_id
  let url = ''
  try {
    const content = await leaveApi.downloadAttachment(application.value.application_id, item.attachment_id)
    url = URL.createObjectURL(content)
    const anchor = document.createElement('a')
    anchor.href = url; anchor.download = item.filename
    document.body.appendChild(anchor); anchor.click(); anchor.remove()
  } catch { /* 客户端显示下载错误。 */ }
  finally { if (url) URL.revokeObjectURL(url); downloading.value = '' }
}
function payload() {
  return { ...form, start_at: new Date(form.start_at).toISOString(), end_at: new Date(form.end_at).toISOString(), attachments: [...form.attachments] }
}
async function save(submit = false) {
  if (busy.value || !editable.value) return
  if (!form.start_at || !form.end_at || Number.isNaN(new Date(form.start_at).getTime()) || Number.isNaN(new Date(form.end_at).getTime())) { ElMessage.warning('请填写开始与结束时间'); return }
  saving.value = true
  try {
    const saved = application.value ? await leaveApi.patch(application.value.application_id, payload()) : await leaveApi.create(payload())
    apply(saved)
    if (submit) {
      apply(await leaveApi.submit(saved.application_id))
      if (application.value?.status === 'SUBMITTED') ElMessage.success('预检通过，已提交审批')
      else if (application.value?.status === 'PAUSED') ElMessage.warning('依赖暂不可用，申请已暂停；服务恢复后可重新预检')
      else ElMessage.warning('请依据预检结果补充申请')
    } else ElMessage.success('草稿已保存')
    await history(saved.application_id)
    if (route.params.applicationId !== saved.application_id) await router.replace('/leaves/' + saved.application_id)
  } catch { /* 请求失败时保留材料，由客户端显示具体错误。 */ } finally { saving.value = false }
}
watch(() => route.params.applicationId, load, { immediate: true })
</script>
<template>
  <section class="workbench"><div class="page-heading"><div><p class="eyebrow">员工服务</p><h1>{{ application ? '请假申请' : '新建请假' }}</h1><p class="muted">{{ application?.business_id || '填写完整表单，保存后可随时继续。' }}</p></div><div class="actions"><StatusTag :status="application?.status || 'DRAFT'" /><el-button @click="router.push('/leaves')">返回列表</el-button></div></div>
    <el-skeleton v-if="loading" :rows="8" animated /><el-result v-else-if="error" icon="warning" :title="error"><template #extra><el-button @click="load">重新加载</el-button></template></el-result>
    <template v-else><el-alert v-if="application?.status === 'REJECTED'" title="申请已驳回。修改后重新提交将生成新版本并重新预检。" type="warning" :closable="false" show-icon />
      <el-alert v-if="application?.status === 'PAUSED'" :title="precheckPaused ? (application.precheck as any)?.error?.msg || '预检依赖暂不可用，申请已安全暂停' : '审批已暂停，请先查看审批进度并核对处理结果'" :description="precheckPaused ? '服务恢复后，可在此重新预检并提交。' : undefined" type="warning" :closable="false" show-icon />
      <el-card shadow="never" class="surface"><el-form label-position="top" :disabled="!editable || busy"><div class="form-grid">
        <el-form-item label="申请人"><el-input :model-value="application?.user_id || getCurrentUserId()" disabled /></el-form-item>
        <el-form-item label="假期类型"><el-select v-model="form.leave_type" aria-label="假期类型"><el-option label="年假" value="annual" /><el-option label="病假" value="sick" /><el-option label="事假" value="personal" /></el-select></el-form-item>
        <el-form-item label="开始时间" required><el-input v-model="form.start_at" type="datetime-local" aria-label="开始时间" /></el-form-item>
        <el-form-item label="结束时间" required><el-input v-model="form.end_at" type="datetime-local" aria-label="结束时间" /></el-form-item>
      </div><p class="muted">时间跨度：{{ duration }} 小时（最终时长按生效规则计算）</p>
      <el-form-item label="请假原因"><el-input v-model="form.reason" type="textarea" :rows="4" maxlength="2000" show-word-limit aria-label="请假原因" /></el-form-item>
      </el-form>
      <section class="attachment-panel" aria-label="证明材料">
        <h2>证明材料</h2>
        <p class="muted">支持 PDF、PNG、JPEG，单个文件不超过 10 MB。病假需要证明材料，所有附件须通过安全扫描后才能下载或提交审批。</p>
        <label v-if="editable" class="attachment-upload">
          <span>上传证明材料</span>
          <input type="file" aria-label="上传证明材料" accept=".pdf,.png,.jpg,.jpeg" multiple :disabled="!application || busy" @change="uploadFiles" />
        </label>
        <p v-if="!application" class="muted">请先保存草稿，再选择文件上传。</p>
        <p v-if="uploading" role="status">正在上传证明材料…</p>
        <div v-if="attachmentError" role="alert" class="actions">{{ attachmentError }}<el-button v-if="application" text @click="loadAttachments(application.application_id)">重新加载附件</el-button></div>
        <p v-else-if="application && !attachments.length" class="muted">暂未上传证明材料。</p>
        <ul v-if="attachments.length" class="attachment-list">
          <li v-for="item in attachments" :key="item.attachment_id" class="attachment-row">
            <div class="attachment-description"><strong>{{ item.filename }}</strong><span class="muted">{{ formatBytes(item.size_bytes) }}</span></div>
            <div class="actions">
              <el-tag :type="item.scan_status === 'CLEAN' ? 'success' : item.scan_status === 'INFECTED' || item.scan_status === 'ERROR' ? 'danger' : 'warning'">{{ scanLabel(item.scan_status) }}</el-tag>
              <el-button size="small" :disabled="item.scan_status !== 'CLEAN' || !!downloading" :loading="downloading === item.attachment_id" @click="downloadAttachment(item)">下载</el-button>
              <el-button v-if="editable" size="small" :disabled="busy" :loading="scanning === item.attachment_id" @click="rescanAttachment(item)">重新扫描</el-button>
            </div>
          </li>
        </ul>
        <p v-if="attachments.some(item => item.scan_status === 'PENDING')" class="muted">附件待扫描，暂不能作为审批依据。扫描服务可用后，请点击重新扫描。</p>
      </section>
      <div class="actions form-actions"><el-button v-if="editable" data-testid="save-draft" :disabled="busy" :loading="saving" @click="save(false)">保存草稿</el-button><el-button v-if="editable" type="primary" data-testid="submit-leave" :disabled="busy" :loading="saving" @click="save(true)">{{ application?.version ? '重新预检并提交' : '预检并提交' }}</el-button><el-button v-if="application?.thread_id" @click="router.push('/leave/' + application.thread_id)">查看审批进度</el-button></div></el-card>
      <el-card v-if="application?.precheck" shadow="never" class="surface"><template #header>预检结果</template><PrecheckTable :precheck="normalizePrecheck(application.precheck)" /></el-card>
      <el-card v-if="versions.length" shadow="never" class="surface"><template #header><div class="page-heading"><span>申请版本 · 当前 v{{ application?.version }}</span><el-select v-model="comparison" aria-label="比较历史版本" style="width: 200px"><el-option v-for="version in versions" :key="version.version" :label="'与版本 ' + version.version + ' 比较'" :value="version.version" /></el-select></div></template><LeaveDiff :before="before" :after="{ ...form, start_at: form.start_at ? new Date(form.start_at).toISOString() : '', end_at: form.end_at ? new Date(form.end_at).toISOString() : '' }" /></el-card>
    </template>
  </section>
</template>
