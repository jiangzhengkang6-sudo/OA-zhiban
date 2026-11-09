<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { organizationApi, type Organization, type Member, type Department, type Position, type Role } from '@/api/organization'
import { can, reloadIdentity } from '@/stores/auth'
import MemberBatchDialog from '@/components/MemberBatchDialog.vue'
import MemberHandoffDialog from '@/components/MemberHandoffDialog.vue'
const data = ref<Organization>({users:[],departments:[],positions:[],roles:[],resources:[]})
const tab = ref('users')
const search = ref('')
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const dialog = ref(false)
const kind = ref('users')
const editing = ref('')
const passwordTarget = ref<Member | null>(null)
const resetPassword = ref('')
const selectedMembers = ref<Member[]>([])
const batchDialog = ref(false)
const handoffMember = ref<Member|null>(null)
const editingVersion = ref<number>()
const form = reactive({username:'',display_name:'',password:'',status:'active',department_id:null as string|null,position_id:null as string|null,manager_id:null as string|null,role_ids:[] as string[],name:'',parent_id:null as string|null,enabled:true,code:'',permissions:[] as {resource:string;action:string;scope:string}[]})
const resourceNames: Record<string,string> = {meeting:'会议文本',document:'文档起草',email:'邮件工作台',work_task:'业务任务',report:'只读报表',contract:'合同审查',thread:'智能助手',task:'我的任务',organization:'组织管理',knowledge:'知识库',policy:'智能配置',audit:'审计中心',operations:'运维管理',leave:'请假申请',approval:'请假审批',workflow:'流程配置',leave_balance:'请假额度',workflow_admin:'流程管理'}
Object.assign(resourceNames, {announcement:'部门公告', reimbursement:'报销管理', ticket:'工单查询', ticket_handle:'工单办理', ticket_admin:'工单规则', notification:'站内消息', notification_admin:'通知管理'})
const kindNames: Record<string,string> = {users:'成员',departments:'部门',positions:'岗位',roles:'角色'}
const writable = computed(() => can('organization','write'))
const members = computed(() => data.value.users.filter(u => `${u.username} ${u.display_name}`.includes(search.value.trim()) && (tab.value!=='handoffs'||u.handoff_pending)))
const departmentName = (id:string|null) => data.value.departments.find(d=>d.id===id)?.name || '未分配'
const positionName = (id:string|null) => data.value.positions.find(d=>d.id===id)?.name || '未分配'
const roleName = (id:string) => data.value.roles.find(r=>r.id===id)?.name || '未知角色'
async function load() {
  loading.value=true; error.value=''
  try { data.value=await organizationApi.overview();selectedMembers.value=[] } catch(e:any) { error.value=e.message || '加载失败' }
  finally { loading.value=false }
}
function open(type:string, row?:Member|Department|Position|Role) {
  kind.value=type; editing.value=row?.id || ''
  editingVersion.value=type==='users'&&row ? (row as Member).version : undefined
  Object.assign(form,{username:'',display_name:'',password:'',status:'active',department_id:null,position_id:null,manager_id:null,role_ids:[],name:'',parent_id:null,enabled:true,code:'',permissions:[]})
  if(row) Object.assign(form,JSON.parse(JSON.stringify(row)))
  dialog.value=true
}
async function save() {
  if (kind.value==='users' && (!form.display_name.trim() || (!editing.value && (!form.username.trim() || form.password.length<12)))) { ElMessage.error('请填写姓名、账号及至少 12 个字符的密码'); return }
  if (kind.value!=='users' && !form.name.trim()) { ElMessage.error('请填写名称'); return }
  if (kind.value==='roles' && !/^[a-z][a-z0-9_]{0,63}$/.test(form.code)) { ElMessage.error('角色标识须以小写字母开头，仅含小写字母、数字和下划线'); return }
  if (kind.value==='roles' && form.permissions.some(p=>p.action==='write' && !form.permissions.some(r=>r.resource===p.resource && r.action==='read' && (r.scope==='department' || r.scope===p.scope)))) { ElMessage.error('编辑权限须同时配置相同或更大范围的查看权限'); return }
  if (editing.value && kind.value==='users' && form.status==='disabled') {
    try { await ElMessageBox.confirm('停用后该成员将立即退出，未完成业务保留为待交接。是否继续？','停用成员',{type:'warning',confirmButtonText:'停用',cancelButtonText:'取消'}) } catch { return }
  }
  saving.value=true
  try {
    let payload:unknown
    if(kind.value==='users') payload={display_name:form.display_name,status:form.status,department_id:form.department_id,position_id:form.position_id,manager_id:form.manager_id,...(editing.value ? {role_ids:form.role_ids,expected_version:editingVersion.value} : {username:form.username,password:form.password,...(form.role_ids.length ? {role_ids:form.role_ids} : {})})}
    else if(kind.value==='departments') payload={name:form.name,parent_id:form.parent_id,enabled:form.enabled}
    else if(kind.value==='positions') payload={name:form.name,enabled:form.enabled}
    else payload={name:form.name,code:form.code,permissions:form.permissions}
    await organizationApi.save(kind.value,payload,editing.value || undefined)
    dialog.value=false; form.password=''; ElMessage.success('已保存')
    await reloadIdentity(); await load()
    if(!can('organization')) window.dispatchEvent(new Event('oa-permissions-changed'))
  } catch { /* HTTP 客户端显示服务端错误。 */ }
  finally { saving.value=false }
}
async function reset() {
  if (!passwordTarget.value || resetPassword.value.length<12) { ElMessage.error('密码至少需要 12 个字符'); return }
  saving.value=true
  try { await organizationApi.resetPassword(passwordTarget.value.id,resetPassword.value); passwordTarget.value=null; ElMessage.success('密码已重置，原会话已撤销') }
  catch { /* HTTP 客户端显示服务端错误。 */ }
  finally { resetPassword.value=''; saving.value=false }
}
onMounted(load)
async function memberChanged(){await reloadIdentity();await load();if(!can('organization'))window.location.assign('/')}
</script>
<template>
  <section class="organization-page">
    <header><h1>组织管理</h1><el-button :loading="loading" @click="load"><el-icon><Refresh /></el-icon><span>刷新</span></el-button></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-tabs v-model="tab">
      <el-tab-pane label="成员" name="users" />
      <el-tab-pane label="部门" name="departments" />
      <el-tab-pane label="岗位" name="positions" />
      <el-tab-pane label="角色权限" name="roles" />
      <el-tab-pane label="交接工作台" name="handoffs" />
    </el-tabs>
    <div class="toolbar"><el-input v-if="tab==='users'||tab==='handoffs'" v-model="search" placeholder="搜索姓名或账号" clearable aria-label="搜索成员" /><el-button v-if="writable&&tab==='users'" :disabled="!selectedMembers.length||selectedMembers.length>100" @click="batchDialog=true">批量调整（{{selectedMembers.length}}）</el-button><el-button v-if="writable&&tab!=='handoffs'" type="primary" @click="open(tab)"><el-icon><Plus /></el-icon><span>新增{{ kindNames[tab] }}</span></el-button></div>
    <div v-loading="loading" class="table-wrap">
      <el-table v-if="tab==='users'||tab==='handoffs'" :data="members" :empty-text="tab==='handoffs'?'暂无待交接成员':'暂无成员'" row-key="id" @selection-change="selectedMembers=$event">
        <el-table-column v-if="writable&&tab==='users'" type="selection" width="44"/>
        <el-table-column prop="display_name" label="姓名" min-width="120" /><el-table-column prop="username" label="账号" min-width="140" />
        <el-table-column label="部门" min-width="120"><template #default="{row}">{{ departmentName(row.department_id) }}</template></el-table-column>
        <el-table-column label="岗位" min-width="110"><template #default="{row}">{{ positionName(row.position_id) }}</template></el-table-column>
        <el-table-column label="角色" min-width="140"><template #default="{row}">{{ row.role_ids.map(roleName).join('、') || '未分配' }}</template></el-table-column>
        <el-table-column label="状态" min-width="150"><template #default="{row}"><el-tag :type="row.status==='active'?'success':'info'">{{ row.status==='active'?'启用':'停用' }}</el-tag><el-tag v-if="row.handoff_pending" type="warning">待交接</el-tag></template></el-table-column>
        <el-table-column label="操作" :width="writable?225:90"><template #default="{row}"><el-button v-if="writable" link type="primary" @click="open('users',row)">编辑</el-button><el-button link type="primary" @click="handoffMember=row">交接</el-button><el-button v-if="writable" link type="primary" @click="passwordTarget=row; resetPassword=''">重置密码</el-button></template></el-table-column>
      </el-table>
      <el-table v-else-if="tab==='departments'" :data="data.departments" empty-text="暂无部门"><el-table-column prop="name" label="部门" min-width="160" /><el-table-column label="上级部门" min-width="160"><template #default="{row}">{{ row.parent_id ? departmentName(row.parent_id) : '无' }}</template></el-table-column><el-table-column label="状态" width="100"><template #default="{row}">{{ row.enabled?'启用':'停用' }}</template></el-table-column><el-table-column v-if="writable" label="操作" width="90"><template #default="{row}"><el-button link type="primary" @click="open('departments',row)">编辑</el-button></template></el-table-column></el-table>
      <el-table v-else-if="tab==='positions'" :data="data.positions" empty-text="暂无岗位"><el-table-column prop="name" label="岗位" min-width="180" /><el-table-column label="状态" width="100"><template #default="{row}">{{ row.enabled?'启用':'停用' }}</template></el-table-column><el-table-column v-if="writable" label="操作" width="90"><template #default="{row}"><el-button link type="primary" @click="open('positions',row)">编辑</el-button></template></el-table-column></el-table>
      <el-table v-else :data="data.roles" empty-text="暂无角色"><el-table-column prop="name" label="角色名称" min-width="140" /><el-table-column label="授权" min-width="260"><template #default="{row}">{{ [...new Set(row.permissions.map((p:any)=>resourceNames[p.resource] || p.resource))].join('、') || '无权限' }}</template></el-table-column><el-table-column v-if="writable" label="操作" width="90"><template #default="{row}"><el-button link type="primary" @click="open('roles',row)">编辑</el-button></template></el-table-column></el-table>
    </div>
    <el-dialog v-model="dialog" :title="`${editing?'编辑':'新增'}${kindNames[kind]}`" width="min(620px, calc(100vw - 32px))" :close-on-click-modal="false" @closed="form.password=''">
      <el-form label-position="top" @submit.prevent="save">
        <template v-if="kind==='users'">
          <el-form-item label="姓名"><el-input v-model="form.display_name" maxlength="128" /></el-form-item>
          <el-form-item label="账号"><el-input v-model="form.username" :disabled="!!editing" maxlength="128" autocomplete="off" /></el-form-item>
          <el-form-item v-if="!editing" label="初始密码"><el-input v-model="form.password" type="password" show-password autocomplete="new-password" maxlength="1024" /></el-form-item>
          <el-form-item label="部门"><el-select v-model="form.department_id" clearable @change="form.position_id=null;form.manager_id=null"><el-option v-for="d in data.departments.filter(d=>d.enabled)" :key="d.id" :label="d.name" :value="d.id" /></el-select></el-form-item>
          <el-form-item label="岗位"><el-select v-model="form.position_id" clearable :disabled="!form.department_id"><el-option v-for="p in data.positions.filter(p=>p.enabled)" :key="p.id" :label="p.name" :value="p.id" /></el-select></el-form-item>
          <el-form-item label="直属上级"><el-select v-model="form.manager_id" clearable filterable :disabled="!form.department_id"><el-option v-for="u in data.users.filter(u=>u.status==='active' && u.id!==editing)" :key="u.id" :label="u.display_name" :value="u.id" /></el-select></el-form-item>
          <el-form-item label="角色"><el-select v-model="form.role_ids" multiple :placeholder="editing?'请选择角色':'默认员工角色'"><el-option v-for="r in data.roles" :key="r.id" :label="r.name" :value="r.id" /></el-select></el-form-item>
          <el-form-item v-if="editing" label="账号状态"><el-radio-group v-model="form.status"><el-radio-button value="active">启用</el-radio-button><el-radio-button value="disabled">停用</el-radio-button></el-radio-group></el-form-item>
        </template>
        <template v-else>
          <el-form-item label="名称"><el-input v-model="form.name" maxlength="128" /></el-form-item>
          <template v-if="kind==='roles'">
            <el-form-item label="角色标识"><el-input v-model="form.code" :disabled="!!editing" maxlength="64" /></el-form-item>
            <div class="permission-header"><span>资源权限</span><el-button @click="form.permissions.push({resource:'meeting',action:'read',scope:'self'})"><el-icon><Plus /></el-icon><span>添加权限</span></el-button></div>
            <div v-for="(p,i) in form.permissions" :key="i" class="permission-row">
              <el-select v-model="p.resource" aria-label="权限资源"><el-option v-for="r in data.resources" :key="r" :label="resourceNames[r] || r" :value="r" /></el-select>
              <el-select v-model="p.action" aria-label="操作权限"><el-option label="查看" value="read" /><el-option label="编辑" value="write" /></el-select>
              <el-select v-model="p.scope" aria-label="数据范围"><el-option label="本人" value="self" /><el-option label="本部门" value="department" /></el-select>
              <el-tooltip content="移除权限"><el-button aria-label="移除权限" @click="form.permissions.splice(i,1)"><el-icon><Delete /></el-icon></el-button></el-tooltip>
            </div>
          </template>
          <template v-else>
            <el-form-item v-if="kind==='departments'" label="上级部门"><el-select v-model="form.parent_id" clearable><el-option v-for="d in data.departments.filter(d=>d.enabled && d.id!==editing)" :key="d.id" :label="d.name" :value="d.id" /></el-select></el-form-item>
            <el-form-item label="启用"><el-switch v-model="form.enabled" /></el-form-item>
          </template>
        </template>
      </el-form>
      <template #footer><el-button @click="dialog=false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存</el-button></template>
    </el-dialog>
    <MemberBatchDialog v-model="batchDialog" :members="selectedMembers" :organization="data" @saved="memberChanged"/>
    <MemberHandoffDialog :member="handoffMember" @close="handoffMember=null" @changed="memberChanged"/>
    <el-dialog :model-value="!!passwordTarget" title="重置密码" width="min(440px, calc(100vw - 32px))" :close-on-click-modal="false" @update:model-value="passwordTarget=null" @closed="resetPassword=''">
      <el-form label-position="top" @submit.prevent="reset"><el-form-item :label="`${passwordTarget?.display_name || ''}的新密码`"><el-input v-model="resetPassword" type="password" show-password autocomplete="new-password" maxlength="1024" /></el-form-item></el-form>
      <template #footer><el-button @click="passwordTarget=null">取消</el-button><el-button type="primary" :loading="saving" @click="reset">重置密码</el-button></template>
    </el-dialog>
  </section>
</template>
<style scoped>
.organization-page { max-width:1280px; margin:auto; }
header,.toolbar,.permission-header { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:20px; }
h1 { font-size:24px; margin:0; color:#24313c; }
.toolbar { justify-content:flex-end; } .toolbar .el-input { max-width:300px; margin-right:auto; }
.table-wrap { background:white; border-top:1px solid #dce3e8; overflow:auto; min-height:180px; }
.el-tag + .el-tag { margin-left:6px; } .el-select { width:100%; }
.permission-row { display:grid; grid-template-columns:minmax(110px,1.5fr) minmax(70px,1fr) minmax(80px,1fr) 40px; gap:8px; margin-bottom:10px; }
:deep(.el-dialog) { max-width:calc(100vw - 32px); } :deep(.el-dialog__body) { max-height:65vh; overflow:auto; }
@media(max-width:600px) { .permission-row { grid-template-columns:minmax(100px,1fr) minmax(72px,1fr) 40px; } .permission-row .el-select:first-child { grid-column:1 / -1; } .toolbar { flex-wrap:wrap; } .toolbar .el-input { max-width:none; } }
</style>
