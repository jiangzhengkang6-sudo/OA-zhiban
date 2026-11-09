<script setup lang="ts">
import {computed,ref,watch,onBeforeUnmount} from 'vue'
import {useRoute,useRouter,onBeforeRouteLeave,onBeforeRouteUpdate} from 'vue-router'
import {ElMessageBox} from 'element-plus'
import {Plus,Refresh,DocumentChecked,Upload} from '@element-plus/icons-vue'
import {oaApi} from '@/api/oa'
import {authState} from '@/stores/auth'
import {canOA,oaLabel,useOACommands,messageOf,downloadOA,fileId} from '@/utils/oa'
import type {Leave,LeaveFields,Workflow} from '@/types/oa'
const route=useRoute(),router=useRouter(),{busy,error,run}=useOACommands()
const rows=ref<Leave[]>([]),workflows=ref<Workflow[]>([]),detail=ref<Leave|null>(null),loading=ref(false),workflow=ref(''),file=ref<File|null>(null)
const fields=ref<LeaveFields>({leave_type:'',start_date:'',end_date:'',reason:'',attachment_ids:[]})
const saved=ref('');let loadRevision=0
const loadFailed=ref(false)
const creating=computed(()=>route.params.id==='new'&&!detail.value),dirty=computed(()=>JSON.stringify(fields.value)!==saved.value)
const writable=computed(()=>canOA('leave','write'))
const canConfigureWorkflow=computed(()=>canOA('workflow')&&canOA('workflow','write'))
const missingWorkflow=computed(()=>creating.value&&!loading.value&&!loadFailed.value&&!workflows.value.length)
const workflowPlaceholder=computed(()=>loading.value?'正在加载请假流程…':loadFailed.value?'加载失败，请刷新重试':'暂无可用请假流程')
const typePlaceholder=computed(()=>loading.value?'正在加载假种…':loadFailed.value?'加载失败，请刷新重试':'暂无可用假种')
const editable=computed(()=>writable.value&&(creating.value||!!detail.value?.allowed_actions.includes('edit')))
const types=computed(()=>workflows.value.find(w=>w.id===(detail.value?.workflow_definition_id||workflow.value))?.form?.leave_types||[fields.value.leave_type].filter(Boolean))
const days=computed(()=>{const value=(Date.parse(fields.value.end_date)-Date.parse(fields.value.start_date))/86400000+1;return Number.isFinite(value)&&value>0?value:0})
const valid=computed(()=>!loading.value&&!loadFailed.value&&!!fields.value.leave_type&&days.value>0&&!!fields.value.reason.trim()&&fields.value.reason.length<=2000)
async function load(){
  const request=++loadRevision;detail.value=null;error.value='';loading.value=true;loadFailed.value=false;saved.value='';workflows.value=[];workflow.value=''
  if(!canOA('leave')){error.value='当前账号没有申请读取权限';loadFailed.value=true;loading.value=false;return}
  try{
    const [list,available]=await Promise.all([oaApi.leaves(),oaApi.workflows(true)])
    if(request!==loadRevision)return
    rows.value=list;workflows.value=available
    const id=String(route.params.id||'')
    if(id==='new'){
      workflow.value=available[0]?.id||''
      fields.value={leave_type:available[0]?.form?.leave_types?.[0]||'',start_date:'',end_date:'',reason:'',attachment_ids:[]}
    }else if(id){
      const value=await oaApi.leave(id);if(request!==loadRevision)return
      detail.value=value;fields.value=structuredClone(value.fields)
    }
    saved.value=JSON.stringify(fields.value)
  }catch(e){if(request===loadRevision){error.value=messageOf(e);loadFailed.value=true}}finally{if(request===loadRevision)loading.value=false}
}
async function save(){
  if(!editable.value||!valid.value)return
  const snapshot=JSON.parse(JSON.stringify(fields.value)) as LeaveFields
  const id=detail.value?.id
  const result=creating.value?await run('create',{workflow_definition_id:workflow.value,fields:snapshot},oaApi.createLeave)
    :await run('save:'+id,{expected_revision:detail.value!.revision,fields:snapshot},p=>oaApi.saveLeave(id!,p))
  if(result){
    detail.value={...detail.value,...result.result};saved.value=JSON.stringify(snapshot)
    if(!dirty.value){await router.replace('/oa/leaves/'+result.result.id);await load()}
    else{try{detail.value=await oaApi.leave(result.result.id)}catch(e){error.value=messageOf(e)}}
  }
}
async function command(action:'submit'|'withdraw'|'archive'){
  const value=detail.value
  if(!value||!writable.value||!value.allowed_actions.includes(action)||dirty.value)return
  if(action!=='submit'){try{await ElMessageBox.confirm(action==='withdraw'?'确认撤回这份申请？':'确认归档这份申请？','确认操作',{type:'warning'})}catch{return}}
  const data={expected_revision:value.revision,...(action==='submit'?{requested_submission_version:value.submission_version+1}:{})}
  const result=await run(action+value.id,data,p=>oaApi[action](value.id,p))
  if(result)await load()
}
async function upload(){
  if(!file.value||!detail.value||!editable.value||dirty.value)return
  const value=detail.value,selected=file.value
  const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await selected.arrayBuffer()))).map(n=>n.toString(16).padStart(2,'0')).join('')
  const result=await run('upload:'+value.id,{expected_revision:value.revision,filename:selected.name,digest},p=>{
    const form=new FormData();form.append('file',selected);form.append('operation_id',p.operation_id);form.append('expected_revision',String(p.expected_revision));return oaApi.upload(value.id,form)
  })
  if(result){file.value=null;await load()}
}
async function rescan(id:string){
  if(!detail.value||!editable.value)return
  const value=detail.value,result=await run('scan:'+id,{expected_revision:value.revision},p=>oaApi.rescan(value.id,id,p))
  if(result)await load()
}
async function download(id:string,name:string){try{await downloadOA(`/oa/leaves/${detail.value!.id}/attachments/${id}/content`,name)}catch(e){error.value=messageOf(e)}}
async function guard(){if(busy.value)return false;if(dirty.value&&(creating.value||editable.value)){try{await ElMessageBox.confirm('尚有未保存修改，确认离开？','离开申请')}catch{return false}}return true}
onBeforeRouteLeave(guard);onBeforeRouteUpdate(guard)
watch(()=>route.params.id,()=>void load(),{immediate:true})
onBeforeUnmount(()=>{loadRevision++})
</script>
<template>
  <main class="workbench manual-oa" v-loading="loading">
    <header class="page-heading"><h1>我的申请</h1><div class="actions"><el-button :icon="Refresh" :disabled="busy||dirty&&!!detail" @click="load">刷新</el-button><el-button v-if="writable" type="primary" :icon="Plus" @click="router.push('/oa/leaves/new')">新建请假</el-button></div></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-table :data="rows" empty-text="暂无申请"><el-table-column prop="business_no" label="申请编号" min-width="190"/><el-table-column label="假种" min-width="90"><template #default="{row}">{{oaLabel(row.fields.leave_type)}}</template></el-table-column><el-table-column label="日期" min-width="200"><template #default="{row}">{{row.fields.start_date}} 至 {{row.fields.end_date}}</template></el-table-column><el-table-column label="状态" min-width="130"><template #default="{row}">{{row.archived_at?'已归档 · ':''}}{{oaLabel(row.state)}}</template></el-table-column><el-table-column label="操作" width="80" fixed="right"><template #default="{row}"><el-button link type="primary" @click="router.push('/oa/leaves/'+row.id)">详情</el-button></template></el-table-column></el-table>
    <section v-if="creating||detail" class="oa-section">
      <h2>{{creating?'新建请假':detail?.business_no}}</h2>
      <el-alert v-if="missingWorkflow" title="本部门暂无已发布的请假流程" type="warning" :closable="false" show-icon>
        <p>{{canConfigureWorkflow?'请假流程发布后，才可选择流程及假种。':'请联系本部门流程管理员配置并发布请假流程。'}}</p>
        <el-button v-if="canConfigureWorkflow" data-testid="configure-leave-workflow" link type="primary" @click="router.push('/oa/workflows')">配置流程</el-button>
      </el-alert>
      <el-alert v-if="detail?.pause_reason" :title="detail.pause_reason" type="warning" :closable="false"/>
      <el-form label-position="top" @submit.prevent="save">
        <div class="oa-grid">
          <label v-if="creating">请假流程<select v-model="workflow" aria-label="请假流程" :disabled="!editable||loading||loadFailed||!workflows.length" @change="fields.leave_type=types[0]||''"><option v-if="loading||loadFailed||!workflows.length" value="" disabled>{{workflowPlaceholder}}</option><option v-for="w in workflows" :key="w.id" :value="w.id">{{w.name}}</option></select></label>
          <label>假种<select v-model="fields.leave_type" aria-label="假种" :disabled="!editable||loading||loadFailed||!types.length"><option v-if="loading||loadFailed||!types.length" :value="fields.leave_type" disabled>{{typePlaceholder}}</option><option v-for="t in types" :key="t" :value="t">{{oaLabel(t)}}</option></select></label>
          <label>开始日期<input v-model="fields.start_date" type="date" aria-label="开始日期" :disabled="!editable"/></label>
          <label>结束日期<input v-model="fields.end_date" type="date" aria-label="结束日期" :min="fields.start_date" :disabled="!editable"/></label>
          <div class="oa-stat"><span>日历天数</span><strong>{{days}} 天</strong></div>
        </div>
        <el-form-item label="请假事由"><el-input v-model="fields.reason" type="textarea" aria-label="请假事由" :rows="3" :maxlength="2000" :disabled="!editable"/></el-form-item>
        <div class="actions"><el-button v-if="editable" data-testid="save-leave" native-type="button" type="primary" :disabled="busy||!valid||creating&&!workflow" :icon="DocumentChecked" @click="save">保存草稿</el-button>
          <el-button v-if="writable&&detail?.allowed_actions.includes('submit')" data-testid="submit-leave" :disabled="busy||dirty||!valid" @click="command('submit')">提交审批</el-button>
          <el-button v-if="writable&&detail?.allowed_actions.includes('withdraw')" :disabled="busy" @click="command('withdraw')">撤回申请</el-button>
          <el-button v-if="writable&&detail?.allowed_actions.includes('archive')" :disabled="busy||dirty" @click="command('archive')">归档</el-button>
        </div>
      </el-form>
      <section v-if="detail" class="attachment-panel"><h2>证明材料</h2>
        <div v-if="editable" class="attachment-upload"><input type="file" accept=".pdf,.png,.jpg,.jpeg" aria-label="证明材料" :disabled="busy||dirty" @change="file=($event.target as HTMLInputElement).files?.[0]||null"/><el-button :icon="Upload" :disabled="busy||dirty||!file" @click="upload">上传材料</el-button></div>
        <ul class="attachment-list"><li v-for="a in detail.attachments" :key="fileId(a)" class="attachment-row"><span>{{a.filename}} · {{oaLabel(a.scan_status||'PENDING')}}</span><div class="actions"><el-button v-if="a.scan_status==='CLEAN'" link @click="download(fileId(a),a.filename)">下载</el-button><el-button v-else-if="editable&&!detail.versions?.some(v=>v.attachments.some(f=>fileId(f)===fileId(a)))" link :disabled="busy" @click="rescan(fileId(a))">重新扫描</el-button></div></li></ul>
        <el-empty v-if="!detail.attachments?.length" description="暂无证明材料" :image-size="42"/>
      </section>
      <section v-if="detail?.versions?.length" class="oa-section"><h2>提交版本与处理历史</h2><el-collapse><el-collapse-item v-for="version in detail.versions" :key="version.version" :title="'第 '+version.version+' 次提交'"><p>{{oaLabel(version.fields.leave_type)}} · {{version.fields.start_date}} 至 {{version.fields.end_date}}</p><p>{{version.fields.reason}}</p><p v-for="(change,key) in version.differences" :key="key">{{oaLabel(String(key))}}：{{Array.isArray(change.before)?'原材料':change.before}} → {{Array.isArray(change.after)?'修订材料':change.after}}</p></el-collapse-item></el-collapse><p v-for="(h,i) in detail.history" :key="i">{{new Date(h.created_at).toLocaleString('zh-CN')}} · {{oaLabel(h.action)}} · {{h.note||oaLabel(h.reason_code||'other')}}</p></section>
    </section>
  </main>
</template>
