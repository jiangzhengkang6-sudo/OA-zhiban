<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { Refresh, Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { departmentApi } from '@/api/department'
import { authState, can } from '@/stores/auth'
import type { Announcement } from '@/types/department'
import { displayTime } from '@/utils/leave'
const route = useRoute(), router = useRouter()
const items = ref<Announcement[]>([]), selected = ref<Announcement | null>(null)
const manage = ref(false), loading = ref(false), busy = ref(false), error = ref(''), readingError = ref('')
const editor = ref(false), editing = ref(''), createKey = ref('')
const editingRevision = ref(0)
const form = reactive({ title: '', body: '', department_id: '' })
const writable = computed(() => can('announcement', 'write') && !!authState.user?.permissions.some(p => p.resource==='announcement' && p.action==='write' && p.scope==='department'))
const labels = { DRAFT: '草稿', PUBLISHED: '已发布', WITHDRAWN: '已撤回' }
let generation = 0, readingGeneration = 0
const operations = new Map<string, string>()
function operation(key: string) { if (!operations.has(key)) operations.set(key, crypto.randomUUID()); return operations.get(key)! }
async function load() {
  const request = ++generation
  loading.value = true; error.value = ''; items.value = []
  try { const result = await departmentApi.announcements(manage.value); if (request===generation) items.value=result }
  catch { if (request===generation) error.value='公告加载失败，请重试' }
  finally { if (request===generation) loading.value=false }
}
async function read(id: string) {
  const request = ++readingGeneration
  selected.value=null; readingError.value=''
  if (!id) return
  try { const result=await departmentApi.announcement(id); if (request===readingGeneration) selected.value=result }
  catch { if (request===readingGeneration) readingError.value='公告不存在、已撤回或无权查看' }
}
function openEditor(row?: Announcement) {
  editing.value=row?.id || ''; createKey.value=crypto.randomUUID()
  editingRevision.value=row?.revision || 0
  Object.assign(form, { title:row?.title || '', body:row?.body || '', department_id:row?.department_id || authState.user?.depts[0] || '' })
  editor.value=true
}
async function save() {
  if (!form.title.trim() || !form.body.trim() || !form.department_id) { ElMessage.warning('请填写标题、正文并确认所属部门'); return }
  busy.value=true
  try {
    const result = editing.value
      ? await departmentApi.save(editing.value, { title:form.title, body:form.body, expected_revision:editingRevision.value, operation_id:operation('save:'+editing.value+':'+editingRevision.value) })
      : await departmentApi.create({ ...form, operation_id:createKey.value })
    editor.value=false; manage.value=true
    await router.replace({ query:{ id:result.result.id } }); await read(result.result.id); await load()
    ElMessage.success('草稿已保存')
  } catch { /* 请求错误由统一客户端展示，保留输入以供重试。 */ }
  finally { busy.value=false }
}
async function transition(action: 'publish' | 'withdraw') {
  const row=selected.value
  if (!row || busy.value) return
  const request=readingGeneration
  try { await ElMessageBox.confirm(action==='publish' ? '确认将此公告发布至所属部门？' : '确认撤回此公告？撤回后成员将无法查看。', action==='publish' ? '发布公告' : '撤回公告', { type:'warning', confirmButtonText:'确认', cancelButtonText:'取消' }) } catch { return }
  if (request!==readingGeneration) return
  busy.value=true
  try {
    const result=await departmentApi.transition(row.id,action,{ expected_revision:row.revision, operation_id:operation(action+':'+row.id+':'+row.revision) })
    if (request===readingGeneration) selected.value=result.result
    await load(); ElMessage.success(action==='publish' ? '公告已发布' : '公告已撤回')
  } catch { if (request===readingGeneration) await read(row.id) } finally { busy.value=false }
}
async function markRead() {
  const row=selected.value
  if (!row || busy.value) return
  const request=readingGeneration
  busy.value=true
  try { const result=await departmentApi.read(row.id); if (request===readingGeneration) selected.value=result; await load() }
  catch { if (request===readingGeneration) await read(row.id) } finally { busy.value=false }
}
watch(manage, load)
watch(() => route.query.id, id => { void read(typeof id==='string' ? id : '') }, { immediate:true })
onMounted(load)
onBeforeUnmount(() => { generation++; readingGeneration++ })
</script>
<template>
  <section class="workbench announcements"><div class="page-heading"><h1>部门公告</h1><div class="announcement-tools"><el-switch v-if="writable" v-model="manage" active-text="管理公告"/><el-button :icon="Refresh" :loading="loading" aria-label="刷新公告" title="刷新公告" @click="load"/><el-button v-if="writable" :icon="Plus" type="primary" @click="openEditor()">新建公告</el-button></div></div>
    <el-skeleton v-if="loading" :rows="5" animated/>
    <el-result v-else-if="error" icon="warning" :title="error"><template #extra><el-button @click="load">重新加载</el-button></template></el-result>
    <el-empty v-else-if="!items.length" description="暂无公告"/>
    <ul v-else class="announcement-list"><li v-for="item in items" :key="item.id"><button class="announcement-link" @click="router.push({query:{id:item.id}})"><span class="announcement-title">{{ item.title }}</span><span class="muted">{{ labels[item.state] }} · {{ item.read_at ? '已读' : '未读' }}<span v-if="item.published_at"> · {{ displayTime(item.published_at) }}</span></span></button></li></ul>
    <el-dialog :model-value="!!route.query.id" title="公告详情" width="min(760px, calc(100vw - 32px))" @close="router.replace({query:{}})">
      <el-alert v-if="readingError" :title="readingError" type="warning" :closable="false"/>
      <article v-else-if="selected" class="announcement-reading"><h2>{{ selected.title }}</h2><p class="muted">{{ labels[selected.state] }} · 第 {{ selected.revision }} 版<span v-if="selected.read_at"> · 已读 {{ displayTime(selected.read_at) }}</span></p><p class="announcement-body">{{ selected.body }}</p><div class="announcement-actions"><el-button v-if="selected.state==='PUBLISHED' && !selected.read_at" :loading="busy" @click="markRead">标为已读</el-button><el-button v-if="selected.can_manage && selected.state==='DRAFT'" :disabled="busy" @click="openEditor(selected)">编辑草稿</el-button><el-button v-if="selected.can_manage && selected.state==='DRAFT'" type="primary" :loading="busy" @click="transition('publish')">发布</el-button><el-button v-if="selected.can_manage && selected.state==='PUBLISHED'" type="danger" plain :loading="busy" @click="transition('withdraw')">撤回</el-button></div></article>
      <el-skeleton v-else :rows="5" animated/>
    </el-dialog>
    <el-dialog v-model="editor" :title="editing ? '编辑公告草稿' : '新建公告'" width="min(680px, calc(100vw - 32px))" :close-on-click-modal="false"><el-form label-position="top"><el-form-item label="公告标题" required><el-input v-model="form.title" maxlength="200" show-word-limit/></el-form-item><el-form-item label="公告正文" required><el-input v-model="form.body" type="textarea" :rows="12" maxlength="20000" show-word-limit/></el-form-item></el-form><template #footer><el-button :disabled="busy" @click="editor=false">取消</el-button><el-button type="primary" :loading="busy" @click="save">保存草稿</el-button></template></el-dialog>
  </section>
</template>
<style scoped>
.announcement-tools,.announcement-actions{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.announcement-list{list-style:none;margin:0;padding:0}.announcement-list li{border-bottom:1px solid #dfe5e9}.announcement-link{display:flex;flex-direction:column;gap:10px;width:100%;border:0;background:transparent;padding:20px 0;text-align:left;cursor:pointer;font:inherit;color:inherit}.announcement-link:hover{color:#0f766e}.announcement-title{font-size:16px;font-weight:600;overflow-wrap:anywhere}.announcement-reading h2{font-size:20px;line-height:1.5;overflow-wrap:anywhere}.announcement-body{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.85;margin:24px 0}.announcement-actions{justify-content:flex-end}@media(max-width:720px){.announcements .page-heading{align-items:flex-start;flex-direction:column;gap:12px}}
</style>
