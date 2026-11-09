<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { delegationApi, type Delegation } from '@/api/delegation'
import { authState } from '@/stores/auth'
import { canOA, messageOf, useOACommands } from '@/utils/oa'
import type { Named } from '@/types/oa'
import { displayTime } from '@/utils/leave'
const { busy, error, run } = useOACommands()
const rows=ref<Delegation[]>([]), candidates=ref<Named[]>([]), loading=ref(false), editor=ref(false)
const direction=ref('outgoing'), loadError=ref('')
const writable=computed(()=>canOA('approval','write'))
const items=computed(()=>rows.value.filter(row=>direction.value==='outgoing' ? row.delegator_id===authState.user?.user_id : row.delegate_id===authState.user?.user_id))
const form=reactive({delegate_id:'',scene:'leave' as 'leave'|'reimbursement',starts_at:new Date(),ends_at:new Date(Date.now()+86400000),reason:''})
const states={SCHEDULED:'尚未生效',ACTIVE:'生效中',EXPIRED:'已到期',REVOKED:'已撤销',INELIGIBLE:'资格已失效'}
let generation=0
async function load() {
  const request=++generation
  loading.value=true; loadError.value=''; rows.value=[]; candidates.value=[]
  try {
    const [list,people]=await Promise.all([delegationApi.list(),writable.value ? delegationApi.candidates() : Promise.resolve([])])
    if(request===generation){rows.value=list;candidates.value=people}
  } catch(e) { if(request===generation)loadError.value=messageOf(e) }
  finally { if(request===generation)loading.value=false }
}
function openEditor() {
  Object.assign(form,{delegate_id:'',scene:'leave',starts_at:new Date(),ends_at:new Date(Date.now()+86400000),reason:''})
  error.value='';editor.value=true
}
async function save() {
  if(!writable.value || busy.value)return
  const start=form.starts_at,end=form.ends_at
  if(!form.delegate_id || !form.reason.trim() || !(start instanceof Date) || !(end instanceof Date) || !Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || end<=start || end.getTime()-start.getTime()>90*86400000 || end.getTime()<=Date.now()) {
    ElMessage.warning('请选择受托人、填写原因，并设置不超过 90 天的有效期限');return
  }
  const result=await run('delegation.create',{delegate_id:form.delegate_id,scene:form.scene,starts_at:start.toISOString(),ends_at:end.toISOString(),reason:form.reason},delegationApi.create)
  if(result){editor.value=false;await load();ElMessage.success('委托已保存')}
}
async function revoke(row:Delegation) {
  if(busy.value || row.delegator_id!==authState.user?.user_id)return
  try { await ElMessageBox.confirm('撤销后受托人将立即失去此项代批资格，已完成的审批记录会保留。','撤销委托',{confirmButtonText:'确认撤销',cancelButtonText:'取消',type:'warning'}) } catch { return }
  const result=await run('delegation.revoke:'+row.id,{expected_revision:row.revision},data=>delegationApi.revoke(row.id,data))
  if(result){await load();ElMessage.success('委托已撤销')}
}
onMounted(load)
onBeforeUnmount(()=>generation++)
</script>
<template>
  <main class="workbench manual-oa delegations" v-loading="loading">
    <header class="page-heading"><h1>审批委托</h1><div class="delegation-actions"><el-button :icon="Refresh" :disabled="busy||loading" @click="load">刷新</el-button><el-button v-if="writable" type="primary" :icon="Plus" :disabled="busy||loading" @click="openEditor">新建委托</el-button></div></header>
    <p class="delegation-policy">委托限同部门、指定业务与期限。原审批人仍可本人办理，同一审批席位只处理一次。</p>
    <el-radio-group v-model="direction" :disabled="busy" class="delegation-direction"><el-radio-button value="outgoing">我发出的委托</el-radio-button><el-radio-button value="incoming">我收到的委托</el-radio-button></el-radio-group>
    <el-alert v-if="loadError||error" :title="loadError||error" type="error" :closable="false"/>
    <el-table :data="items" empty-text="暂无委托记录">
      <el-table-column :label="direction==='outgoing'?'受托人':'委托人'" min-width="140"><template #default="{row}">{{direction==='outgoing'?row.delegate_name:row.delegator_name}}</template></el-table-column>
      <el-table-column label="业务范围" min-width="100"><template #default="{row}">{{row.scene==='leave'?'请假审批':'报销审批'}}</template></el-table-column>
      <el-table-column label="状态" min-width="120"><template #default="{row}"><el-tag :type="row.state==='ACTIVE'?'success':'info'">{{states[row.state as keyof typeof states]}}</el-tag></template></el-table-column>
      <el-table-column label="生效时间" min-width="175"><template #default="{row}">{{displayTime(row.starts_at)}}</template></el-table-column>
      <el-table-column label="到期时间" min-width="175"><template #default="{row}">{{displayTime(row.ends_at)}}</template></el-table-column>
      <el-table-column prop="reason" label="原因" min-width="180"/>
      <el-table-column v-if="direction==='outgoing'&&writable" label="操作" width="90" fixed="right"><template #default="{row}"><el-button v-if="!row.revoked_at&&row.state!=='EXPIRED'" link type="danger" :disabled="busy" @click="revoke(row)">撤销</el-button></template></el-table-column>
    </el-table>
    <el-dialog v-model="editor" title="新建审批委托" width="540px" :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy" class="delegation-dialog">
      <el-alert v-if="!candidates.length" title="当前没有同部门且具备审批读写资格的其他成员" type="info" :closable="false"/>
      <el-alert v-if="error" :title="error" type="error" :closable="false"/>
      <el-form label-position="top" :disabled="busy" @submit.prevent="save">
        <el-form-item label="受托人" required><el-select v-model="form.delegate_id" placeholder="选择成员"><el-option v-for="person in candidates" :key="person.id" :label="person.name" :value="person.id"/></el-select></el-form-item>
        <el-form-item label="业务范围" required><el-select v-model="form.scene"><el-option label="请假审批" value="leave"/><el-option label="报销审批" value="reimbursement"/></el-select></el-form-item>
        <el-form-item label="生效时间" required><el-date-picker v-model="form.starts_at" type="datetime" placeholder="选择生效时间"/></el-form-item>
        <el-form-item label="到期时间" required><el-date-picker v-model="form.ends_at" type="datetime" placeholder="选择到期时间"/></el-form-item>
        <el-form-item label="委托原因" required><el-input v-model="form.reason" type="textarea" :rows="3" maxlength="500" show-word-limit/></el-form-item>
      </el-form>
      <template #footer><el-button :disabled="busy" @click="editor=false">取消</el-button><el-button type="primary" :loading="busy" :disabled="!candidates.length" @click="save">保存委托</el-button></template>
    </el-dialog>
  </main>
</template>
<style scoped>
.delegation-actions{display:flex;gap:12px;flex-wrap:wrap}.delegation-policy{color:#59616b;line-height:1.7;margin:0 0 20px;overflow-wrap:anywhere}.delegation-direction{margin-bottom:20px}.delegations :deep(.el-alert){margin-bottom:16px}.delegations :deep(.el-table .cell){overflow-wrap:anywhere}.delegations :deep(.el-dialog){max-width:calc(100vw - 24px)}.delegations :deep(.el-date-editor),.delegations :deep(.el-select){width:100%}@media(max-width:640px){.delegations .page-heading{align-items:flex-start;flex-direction:column;gap:12px}}
</style>
