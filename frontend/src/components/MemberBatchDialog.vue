<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { organizationApi, type Member, type Organization } from '@/api/organization'
import { replayable } from '@/api/draftCommands'
const props=defineProps<{modelValue:boolean;members:Member[];organization:Organization}>()
const emit=defineEmits<{'update:modelValue':[boolean];saved:[]}>()
const form=reactive({status:false,statusValue:'disabled',department:false,departmentId:null as string|null,position:false,positionId:null as string|null,manager:false,managerId:null as string|null,roles:false,roleIds:[] as string[],reason:''})
const saving=ref(false),error=ref('')
watch(()=>props.modelValue,open=>{if(open){Object.assign(form,{status:false,statusValue:'disabled',department:false,departmentId:null,position:false,positionId:null,manager:false,managerId:null,roles:false,roleIds:[],reason:''});error.value=''}},{immediate:true})
async function save(){
  if(saving.value)return
  const changes:Record<string,unknown>={}
  if(form.status)changes.status=form.statusValue
  if(form.department)changes.department_id=form.departmentId
  if(form.position)changes.position_id=form.positionId
  if(form.manager)changes.manager_id=form.managerId
  if(form.roles)changes.role_ids=form.roleIds
  if(!Object.keys(changes).length||!form.reason.trim()){error.value='请选择调整项并填写调整原因';return}
  saving.value=true;error.value=''
  const payload={members:props.members.map(m=>({user_id:m.id,expected_version:m.version})),changes,reason:form.reason.trim()}
  try{await replayable('organization:batch',payload,key=>organizationApi.batch({operation_id:key,...payload}));emit('update:modelValue',false);emit('saved')}
  catch(e:any){error.value=e.message||'批量调整失败，请刷新后重试'}finally{saving.value=false}
}
</script>
<template>
  <el-dialog :model-value="modelValue" title="批量调整成员" class="member-batch-dialog" width="min(620px, calc(100vw - 32px))" :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving" @update:model-value="emit('update:modelValue',$event)">
    <p class="selection">已选择 {{ members.length }} 位成员：{{ members.map(m=>m.display_name).join('、') }}</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-alert v-if="form.status&&form.statusValue==='disabled'" title="停用后立即撤销登录和办理权限，未完成事项进入待交接。" type="warning" :closable="false" />
    <el-form label-position="top" @submit.prevent="save">
      <div class="change-row"><el-checkbox v-model="form.status">调整状态</el-checkbox><el-select v-model="form.statusValue" :disabled="!form.status" aria-label="批量成员状态"><el-option label="停用" value="disabled"/><el-option label="启用" value="active"/></el-select></div>
      <div class="change-row"><el-checkbox v-model="form.department">调整部门</el-checkbox><el-select v-model="form.departmentId" :disabled="!form.department" clearable placeholder="未分配" aria-label="批量成员部门"><el-option v-for="d in organization.departments.filter(d=>d.enabled)" :key="d.id" :label="d.name" :value="d.id"/></el-select></div>
      <div class="change-row"><el-checkbox v-model="form.position">调整岗位</el-checkbox><el-select v-model="form.positionId" :disabled="!form.position" clearable placeholder="未分配" aria-label="批量成员岗位"><el-option v-for="p in organization.positions.filter(p=>p.enabled)" :key="p.id" :label="p.name" :value="p.id"/></el-select></div>
      <div class="change-row"><el-checkbox v-model="form.manager">调整上级</el-checkbox><el-select v-model="form.managerId" :disabled="!form.manager" clearable filterable placeholder="无直属上级" aria-label="批量直属上级"><el-option v-for="u in organization.users.filter(u=>u.status==='active'&&!members.some(m=>m.id===u.id))" :key="u.id" :label="u.display_name" :value="u.id"/></el-select></div>
      <div class="change-row"><el-checkbox v-model="form.roles">替换角色</el-checkbox><el-select v-model="form.roleIds" :disabled="!form.roles" multiple aria-label="批量角色"><el-option v-for="r in organization.roles" :key="r.id" :label="r.name" :value="r.id"/></el-select></div>
      <el-form-item label="调整原因"><el-input v-model="form.reason" type="textarea" :rows="2" maxlength="500" show-word-limit/></el-form-item>
    </el-form>
    <template #footer><el-button :disabled="saving" @click="emit('update:modelValue',false)">取消</el-button><el-button type="primary" :loading="saving" :disabled="!members.length||members.length>100" @click="save">确认批量调整</el-button></template>
  </el-dialog>
</template>
<style scoped>
.selection{margin-top:0;line-height:1.7;overflow-wrap:anywhere;color:#4b5563}.change-row{display:grid;grid-template-columns:120px minmax(0,1fr);gap:12px;align-items:center;margin:16px 0}.el-select{width:100%}.el-alert{margin-bottom:12px} :deep(.el-dialog__body){max-height:65vh;overflow:auto}
@media(max-width:480px){.change-row{grid-template-columns:1fr;gap:4px}}
</style>
