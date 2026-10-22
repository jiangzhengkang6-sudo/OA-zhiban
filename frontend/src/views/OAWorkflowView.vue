<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { Plus, Refresh, Upload, Delete } from '@element-plus/icons-vue'
import { oaApi } from '@/api/oa'
import { canOA, messageOf, useOACommands, oaLabel } from '@/utils/oa'
import type { Definition, Named, Workflow, WorkflowNode, Selector } from '@/types/oa'

const { busy, error, run } = useOACommands()
const rows = ref<Workflow[]>([]), departments = ref<Named[]>([]), users = ref<Named[]>([]), roles = ref<Named[]>([])
const selected = ref<Workflow | null>(null), dirty = ref(false), entry = ref('review')
const form = ref({ name: '', code: '', department_id: '', leave_types: ['annual'], required_attachments: [] as string[], timeout_hours: 48, reason_max_length: 2000 })
const nodes = ref<WorkflowNode[]>([])
const canRead = computed(() => canOA('workflow')), canWrite = computed(() => canOA('workflow', 'write'))
const canPublish = computed(() => canWrite.value && !!selected.value && !dirty.value)
const leaveTypes = computed(() => [...new Set(['annual','sick','personal','other',...form.value.leave_types])])
const fieldNames: Record<string,string> = {days:'请假天数',leave_type:'假种',start_date:'开始日期',end_date:'结束日期',reason:'请假事由'}
const operatorNames: Record<string,string> = {eq:'等于',ne:'不等于',lt:'小于',le:'不超过',gt:'大于',ge:'不少于',in:'属于以下任一值'}
const clone = <T,>(value:T):T => JSON.parse(JSON.stringify(value))
const title = (node:WorkflowNode) => `${nodes.value.indexOf(node)+1}. ${node.kind==='approval'?'审批':node.kind==='cc'?'抄送':node.kind==='branch'?'条件分支':'结束'}`
const departmentName = (id:string) => departments.value.find(item=>item.id===id)?.name || '所属部门'
function markDirty() { dirty.value=true }
async function mayDiscard() {
  if(busy.value)return false
  if(!dirty.value)return true
  try { await ElMessageBox.confirm('有尚未保存的流程修改，确认放弃？','未保存的修改',{type:'warning'}); return true } catch { return false }
}
function applyWorkflow(row:Workflow) {
  selected.value=clone(row); entry.value=row.definition.entry_id
  form.value={name:row.name,code:row.code,department_id:row.department_id,leave_types:[...(row.definition.form.leave_types||[])],required_attachments:[...row.definition.rules.required_attachments],timeout_hours:row.definition.rules.timeout_hours,reason_max_length:row.definition.form.reason_max_length}
  nodes.value=clone(row.definition.nodes);dirty.value=false
}
async function selectWorkflow(row:Workflow) { if(await mayDiscard())applyWorkflow(row) }
async function newWorkflow() {
  if(!await mayDiscard())return
  selected.value=null;entry.value='review'
  form.value={name:'',code:`leave_${crypto.randomUUID()}`,department_id:departments.value[0]?.id||'',leave_types:['annual'],required_attachments:[],timeout_hours:48,reason_max_length:2000}
  nodes.value=[{id:'review',kind:'approval',mode:'single',selector:{kind:'manager',levels:1},next_id:'end'},{id:'end',kind:'end'}]
  dirty.value=true;error.value=''
}
async function load(force=false) {
  if(!canRead.value){error.value='当前账号没有流程读取权限';return}
  if(!force&&!await mayDiscard())return
  try {
    const [items,options]=await Promise.all([oaApi.workflows(),oaApi.options()])
    rows.value=items;departments.value=options.departments;users.value=options.users;roles.value=options.roles
    const row=items.find(item=>item.id===selected.value?.id)||items[0]
    if(row)applyWorkflow(row)
  }catch(e){error.value=messageOf(e)}
}
function definition():Definition {
  return {schema_version:1,scene:'leave',entry_id:entry.value,form:{leave_types:form.value.leave_types,reason_max_length:form.value.reason_max_length},rules:{timeout_hours:form.value.timeout_hours,required_attachments:form.value.required_attachments,calendar:'inclusive_days'},nodes:clone(nodes.value)}
}
function addNode(kind:'approval'|'cc'|'branch') {
  const end=nodes.value.find(node=>node.kind==='end');if(!end)return
  const id=`node_${crypto.randomUUID()}`
  for(const node of nodes.value){
    if(node.next_id===end.id)node.next_id=id
    if(node.default_next_id===end.id)node.default_next_id=id
    for(const condition of node.cases||[])if(condition.next_id===end.id)condition.next_id=id
  }
  const node:WorkflowNode=kind==='branch'?{id,kind,cases:[{field:'days',op:'gt',value:3,next_id:end.id}],default_next_id:end.id}
    :{id,kind,...(kind==='approval'?{mode:'single' as const}:{}),selector:{kind:'manager',levels:1},next_id:end.id}
  nodes.value.splice(nodes.value.indexOf(end),0,node);markDirty()
}
function removeNode(node:WorkflowNode) {
  if(node.kind==='end'||nodes.value.filter(n=>n.kind==='approval').length===1&&node.kind==='approval')return
  const next=node.next_id||node.default_next_id||nodes.value.find(n=>n.kind==='end')!.id
  for(const other of nodes.value){if(other.next_id===node.id)other.next_id=next;if(other.default_next_id===node.id)other.default_next_id=next;for(const c of other.cases||[])if(c.next_id===node.id)c.next_id=next}
  if(entry.value===node.id)entry.value=next
  nodes.value=nodes.value.filter(n=>n!==node);markDirty()
}
function selectorKind(node:WorkflowNode,event:Event){
  const kind=(event.target as HTMLSelectElement).value as Selector['kind']
  node.selector=kind==='manager'?{kind,levels:1}:kind==='users'?{kind,user_ids:[]}:{kind,role_id:''};markDirty()
}
function fieldChanged(condition:NonNullable<WorkflowNode['cases']>[number]){condition.value=condition.field==='days'?1:'';if(condition.op==='in')condition.value=[condition.value];markDirty()}
function operatorChanged(condition:NonNullable<WorkflowNode['cases']>[number]){condition.value=condition.op==='in'?[Array.isArray(condition.value)?condition.value[0]:condition.value]:Array.isArray(condition.value)?condition.value[0]:condition.value;markDirty()}
function setValue(condition:NonNullable<WorkflowNode['cases']>[number],event:Event,index?:number){const raw=(event.target as HTMLInputElement).value;const value=condition.field==='days'?Number(raw):raw;if(index===undefined)condition.value=value;else (condition.value as unknown[])[index]=value;markDirty()}
async function save(){
  if(!canWrite.value||!form.value.name.trim()||!form.value.department_id)return
  const id=selected.value?.id
  const result=await run(`workflow-save:${id||'new'}`,{expected_revision:selected.value?.revision,name:form.value.name,code:form.value.code,department_id:form.value.department_id,definition:definition()},payload=>oaApi.saveWorkflow(payload,id))
  if(result){selected.value=result;dirty.value=false;await load(true)}
}
async function publish(){
  if(!selected.value||!canPublish.value)return
  const id=selected.value.id
  const result=await run(`workflow-publish:${id}`,{expected_revision:selected.value.revision},payload=>oaApi.publish(id,payload))
  if(result)await load(true)
}
function beforeUnload(e:BeforeUnloadEvent){if(dirty.value){e.preventDefault();e.returnValue=''}}
onMounted(()=>{void load(true);window.addEventListener('beforeunload',beforeUnload)})
onBeforeUnmount(()=>window.removeEventListener('beforeunload',beforeUnload))
onBeforeRouteLeave(mayDiscard)
</script>
<template>
  <main class="workbench manual-oa" v-loading="busy">
    <header class="page-heading"><h1>流程配置</h1><div class="actions"><el-button :icon="Refresh" :disabled="busy" @click="load()">刷新</el-button><el-button v-if="canWrite" data-testid="new-workflow" type="primary" :icon="Plus" @click="newWorkflow">新建流程</el-button></div></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <div class="oa-two-pane"><section class="oa-section"><h2>已配置流程</h2><el-empty v-if="!rows.length" description="暂无流程"/><button v-for="row in rows" :key="row.id" class="oa-list-item" :class="{active:selected?.id===row.id}" :disabled="busy" @click="selectWorkflow(row)"><strong>{{row.name}}</strong><span>{{row.published_version?`已发布第 ${row.published_version} 版`:'未发布'}} · {{departmentName(row.department_id)}}</span></button></section>
      <section class="oa-section" v-if="nodes.length"><h2>{{selected?.name||'新建流程'}}{{dirty?' · 未保存':''}}</h2><el-form label-position="top" :disabled="!canWrite||busy">
        <div class="oa-grid"><el-form-item label="流程名称"><el-input v-model="form.name" aria-label="流程名称" @input="markDirty"/></el-form-item><el-form-item label="适用部门"><el-select v-model="form.department_id" aria-label="适用部门" @change="markDirty"><el-option v-for="item in departments" :key="item.id" :label="item.name" :value="item.id"/></el-select></el-form-item><el-form-item label="超时小时数"><el-input-number v-model="form.timeout_hours" :min="1" :max="8760" @change="markDirty"/></el-form-item><el-form-item label="事由字数上限"><el-input-number v-model="form.reason_max_length" :min="1" :max="2000" @change="markDirty"/></el-form-item></div>
        <el-form-item label="可用假种"><el-select v-model="form.leave_types" multiple filterable allow-create aria-label="可用假种" @change="form.required_attachments=form.required_attachments.filter(t=>form.leave_types.includes(t));markDirty()"><el-option v-for="type in leaveTypes" :key="type" :label="oaLabel(type)" :value="type"/></el-select></el-form-item>
        <el-form-item label="必须提供证明材料的假种"><el-select v-model="form.required_attachments" multiple aria-label="必须提供证明材料的假种" @change="markDirty"><el-option v-for="type in form.leave_types" :key="type" :label="oaLabel(type)" :value="type"/></el-select></el-form-item>
        <div class="node-heading"><h3>审批路线</h3><div class="actions"><el-button data-testid="add-approval" :icon="Plus" @click="addNode('approval')">审批</el-button><el-button data-testid="add-cc" :icon="Plus" @click="addNode('cc')">抄送</el-button><el-button data-testid="add-branch" :icon="Plus" @click="addNode('branch')">条件分支</el-button></div></div>
        <label class="oa-field">起始环节<select v-model="entry" aria-label="起始环节" :disabled="!canWrite||busy" @change="markDirty"><option v-for="node in nodes.filter(n=>n.kind!=='end')" :key="node.id" :value="node.id">{{title(node)}}</option></select></label>
        <div v-for="node in nodes" :key="node.id" class="oa-node"><div class="node-heading"><h3>{{title(node)}}</h3><el-button v-if="node.kind!=='end'" :icon="Delete" title="删除环节" aria-label="删除环节" :disabled="node.kind==='approval'&&nodes.filter(n=>n.kind==='approval').length===1" @click="removeNode(node)"/></div>
          <div v-if="node.kind==='approval'||node.kind==='cc'" class="oa-grid">
            <label v-if="node.kind==='approval'" class="oa-field">审批方式<select v-model="node.mode" aria-label="审批方式" :disabled="!canWrite||busy" @change="markDirty"><option value="single">单人审批</option><option value="all">全部审批</option><option value="any">任一审批</option></select></label>
            <label class="oa-field">{{node.kind==='cc'?'抄送对象':'审批对象'}}<select :value="node.selector?.kind" aria-label="人员选择方式" :disabled="!canWrite||busy" @change="selectorKind(node,$event)"><option value="manager">上级</option><option value="users">指定人员</option><option value="role">角色成员</option></select></label>
            <el-form-item v-if="node.selector?.kind==='manager'" label="上级层数"><el-input-number v-model="node.selector.levels" :min="1" :max="10" @change="markDirty"/></el-form-item>
            <el-form-item v-if="node.selector?.kind==='users'" label="指定人员"><el-select v-model="node.selector.user_ids" multiple aria-label="指定人员" @change="markDirty"><el-option v-for="user in users" :key="user.id" :label="user.name" :value="user.id"/></el-select></el-form-item>
            <el-form-item v-if="node.selector?.kind==='role'" label="角色"><el-select v-model="node.selector.role_id" aria-label="角色" @change="markDirty"><el-option v-for="role in roles" :key="role.id" :label="role.name" :value="role.id"/></el-select></el-form-item>
          </div>
          <template v-if="node.kind==='branch'"><div v-for="(condition,index) in node.cases" :key="index" class="oa-condition"><label class="oa-field">条件字段<select v-model="condition.field" aria-label="条件字段" :disabled="!canWrite||busy" @change="fieldChanged(condition)"><option v-for="(name,key) in fieldNames" :key="key" :value="key">{{name}}</option></select></label><label class="oa-field">比较方式<select v-model="condition.op" aria-label="比较方式" :disabled="!canWrite||busy" @change="operatorChanged(condition)"><option v-for="(name,key) in operatorNames" :key="key" :value="key">{{name}}</option></select></label>
            <div v-if="condition.op==='in'" class="oa-condition-values"><label v-for="(value,i) in (condition.value as unknown[])" :key="i" class="oa-field">条件值 {{i+1}}<input :value="value" :type="condition.field==='days'?'number':condition.field.endsWith('date')?'date':'text'" :disabled="!canWrite||busy" @input="setValue(condition,$event,i)"/></label><el-button @click="(condition.value as unknown[]).push(condition.field==='days'?1:'');markDirty()">增加条件值</el-button></div>
            <label v-else class="oa-field">条件值<input :value="condition.value" aria-label="条件值" :type="condition.field==='days'?'number':condition.field.endsWith('date')?'date':'text'" :disabled="!canWrite||busy" @input="setValue(condition,$event)"/></label>
            <label class="oa-field">满足后进入<select v-model="condition.next_id" aria-label="满足后进入" :disabled="!canWrite||busy" @change="markDirty"><option v-for="next in nodes.filter(n=>n.id!==node.id)" :key="next.id" :value="next.id">{{title(next)}}</option></select></label><el-button :icon="Delete" aria-label="删除条件" title="删除条件" :disabled="node.cases!.length===1" @click="node.cases!.splice(index,1);markDirty()"/></div>
            <el-button :icon="Plus" @click="node.cases!.push({field:'days',op:'gt',value:3,next_id:node.default_next_id!});markDirty()">增加条件</el-button><label class="oa-field">其他情况进入<select v-model="node.default_next_id" aria-label="其他情况进入" :disabled="!canWrite||busy" @change="markDirty"><option v-for="next in nodes.filter(n=>n.id!==node.id)" :key="next.id" :value="next.id">{{title(next)}}</option></select></label>
          </template>
          <label v-else-if="node.kind!=='end'" class="oa-field">下一环节<select v-model="node.next_id" aria-label="下一环节" :disabled="!canWrite||busy" @change="markDirty"><option v-for="next in nodes.filter(n=>n.id!==node.id)" :key="next.id" :value="next.id">{{title(next)}}</option></select></label>
        </div>
        <div class="form-actions actions"><el-button data-testid="save-workflow" type="primary" :disabled="busy||!canWrite" @click="save">保存草稿</el-button><el-button :icon="Upload" :disabled="busy||!canPublish" @click="publish">发布当前版本</el-button></div>
      </el-form></section></div>
  </main>
</template>
