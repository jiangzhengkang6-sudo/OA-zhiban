<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { organizationApi, type Member, type MemberHandoff, type HandoffItem, type HandoffKind } from '@/api/organization'
import { can } from '@/stores/auth'
import { replayable } from '@/api/draftCommands'
import { Refresh } from '@element-plus/icons-vue'
const props=defineProps<{member:Member|null}>()
const emit=defineEmits<{close:[];changed:[]}>()
const data=ref<MemberHandoff|null>(null),loading=ref(false),saving=ref(false),error=ref('')
const selected=ref<HandoffItem|null>(null),candidates=ref<{id:string;name:string}[]>([]),candidatesLoading=ref(false)
const target=ref(''),reason=ref(''),completeReason=ref(''),risk=ref(false)
const names:Record<HandoffKind,string>={workflow:'审批席位',ticket:'待办工单',work_task:'业务任务',ticket_rule:'分派规则',reporting_line:'直属下级'}
let request=0,candidateRequest=0
const writable=computed(()=>can('organization','write'))
async function load(){
  const member=props.member,seq=++request;if(!member)return
  loading.value=true;error.value='';selected.value=null;candidateRequest++
  try{const value=await organizationApi.handoff(member.id);if(seq===request)data.value=value}
  catch(e:any){if(seq===request)error.value=e.message||'交接事项加载失败'}finally{if(seq===request)loading.value=false}
}
watch(()=>props.member,member=>{data.value=null;selected.value=null;reason.value='';completeReason.value='';if(member)load();else{request++;candidateRequest++}},{immediate:true})
async function choose(item:HandoffItem){
  selected.value=item;target.value='';reason.value='';risk.value=false;error.value='';candidates.value=[]
  const member=props.member,seq=++candidateRequest;if(!member)return
  candidatesLoading.value=true
  try{const value=await organizationApi.handoffCandidates(member.id,item);if(seq===candidateRequest)candidates.value=value}
  catch(e:any){if(seq===candidateRequest)error.value=e.message||'接收人加载失败'}finally{if(seq===candidateRequest)candidatesLoading.value=false}
}
async function transfer(){
  if(saving.value||!props.member||!data.value||!selected.value)return
  if(!target.value||!reason.value.trim()){error.value='请选择接收人并填写交接原因';return}
  saving.value=true;error.value=''
  const memberId=props.member.id,payload={expected_version:data.value.member.version,kind:selected.value.kind,item_id:selected.value.id,expected_revision:selected.value.revision,target_user_id:target.value,reason:reason.value.trim(),risk_acknowledged:risk.value}
  try{await replayable(`organization:handoff:${memberId}`,payload,key=>organizationApi.transfer(memberId,{operation_id:key,...payload}));await load();emit('changed')}
  catch(e:any){error.value=e.message||'转交失败，请刷新后重试'}finally{saving.value=false}
}
async function complete(){
  if(saving.value||!props.member||!data.value)return
  if(!completeReason.value.trim()){error.value='请填写交接确认说明';return}
  saving.value=true;error.value=''
  const memberId=props.member.id,payload={expected_version:data.value.member.version,reason:completeReason.value.trim()}
  try{await replayable(`organization:complete:${memberId}`,payload,key=>organizationApi.completeHandoff(memberId,{operation_id:key,...payload}));await load();emit('changed')}
  catch(e:any){error.value=e.message||'确认失败，请刷新后重试'}finally{saving.value=false}
}
</script>
<template>
  <el-dialog :model-value="!!member" :title="`${member?.display_name||''}的交接工作台`" class="member-handoff-dialog" width="min(940px, calc(100vw - 32px))" :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving" @update:model-value="emit('close')">
    <div v-loading="loading" class="handoff-content">
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon/>
      <template v-if="data">
        <div class="handoff-summary"><el-tag :type="data.member.handoff_pending?'warning':'success'">{{data.member.handoff_pending?'待确认交接':'无待确认交接'}}</el-tag><span>未交事项 {{data.total}} 项</span><el-tooltip content="刷新交接事项"><el-button aria-label="刷新交接事项" :disabled="saving" @click="load"><el-icon><Refresh/></el-icon></el-button></el-tooltip></div>
        <dl class="handoff-counts"><div v-for="(label,key) in names" :key="key"><dt>{{label}}</dt><dd>{{data.counts[key]}}</dd></div></dl>
        <el-alert v-if="data.restricted_count" :title="`另有 ${data.restricted_count} 项需要相应业务管理员处理，完成前不能确认交接。`" type="warning" :closable="false" show-icon/>
        <div class="handoff-table"><el-table :data="data.items" empty-text="暂无可见的未交接事项" row-key="id">
          <el-table-column prop="kind_name" label="类别" width="120"/><el-table-column prop="title" label="事项" min-width="200"/>
          <el-table-column label="处理" width="160"><template #default="{row}"><el-button v-if="row.can_transfer&&writable" link type="primary" :disabled="saving||loading" @click="choose(row)">选择接收人</el-button><router-link v-else-if="row.blocked_reason" :to="row.link">流程管理处理</router-link><span v-else>需业务管理权限</span></template></el-table-column>
        </el-table></div>
        <el-form v-if="selected" class="handoff-form" label-position="top" @submit.prevent="transfer">
          <h3>{{selected.kind_name}}交接：{{selected.title}}</h3>
          <el-form-item label="接收人"><el-select v-model="target" filterable :loading="candidatesLoading" placeholder="选择符合办理条件的成员" aria-label="交接接收人"><el-option v-for="c in candidates" :key="c.id" :value="c.id" :label="c.name"/></el-select></el-form-item>
          <el-alert v-if="!candidatesLoading&&!candidates.length" title="当前没有符合条件的接收人，请先配置成员部门和业务权限。" type="warning" :closable="false"/>
          <el-form-item label="交接原因"><el-input v-model="reason" type="textarea" :rows="2" maxlength="500"/></el-form-item>
          <el-checkbox v-if="selected.kind==='work_task'" v-model="risk" class="risk-confirm">确认接收人可根据任务内容继续办理，原始材料权限保留原有范围</el-checkbox>
          <div class="handoff-actions"><el-button :disabled="saving" @click="selected=null;candidateRequest++">取消选择</el-button><el-button type="primary" :loading="saving" :disabled="!target||!reason.trim()||candidatesLoading||(selected.kind==='work_task'&&!risk)" @click="transfer">确认转交</el-button></div>
        </el-form>
        <div v-if="writable&&data.member.handoff_pending" class="handoff-signoff">
          <el-input v-model="completeReason" placeholder="交接确认说明" maxlength="500" aria-label="交接确认说明"/>
          <el-button type="primary" :loading="saving" :disabled="data.total>0||loading||!completeReason.trim()" @click="complete">确认交接完成</el-button>
        </div>
        <div class="handoff-history"><h3>成员变更与交接记录</h3><el-empty v-if="!data.history.length" description="暂无记录" :image-size="60"/>
          <div v-for="h in data.history" :key="h.id" class="history-row"><time>{{new Date(h.created_at).toLocaleString('zh-CN')}}</time><strong>{{h.action}}</strong><span>{{h.reason||'已保留操作记录'}}</span></div>
        </div>
      </template>
    </div>
    <template #footer><el-button :disabled="saving" @click="emit('close')">关闭</el-button></template>
  </el-dialog>
</template>
<style scoped>
.handoff-content{min-height:180px;max-height:65vh;overflow:auto}.handoff-summary{display:flex;align-items:center;gap:16px;margin:4px 0 20px}.handoff-summary .el-button{margin-left:auto}.handoff-counts{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));margin:0 0 20px;border-bottom:1px solid #dce3e8;padding-bottom:16px;gap:12px}dt{font-size:13px;color:#66717b}dd{margin:8px 0 0;font-size:22px;font-weight:600;color:#263740}.handoff-table{overflow:auto}.handoff-form{padding:20px 0;border-bottom:1px solid #dce3e8}.el-select{width:100%}.el-alert{margin-bottom:12px}h3{font-size:16px;margin:0 0 16px;overflow-wrap:anywhere}.handoff-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:16px}.handoff-signoff{display:flex;gap:12px;padding:20px 0}.handoff-history{margin-top:20px}.history-row{display:grid;grid-template-columns:160px 110px minmax(0,1fr);gap:12px;padding:12px 0;border-bottom:1px solid #edf0f2;font-size:13px}.history-row time{color:#66717b}.history-row span{overflow-wrap:anywhere}.risk-confirm{height:auto;white-space:normal;align-items:flex-start}:deep(.risk-confirm .el-checkbox__label){white-space:normal;line-height:1.5}
@media(max-width:600px){.handoff-counts{grid-template-columns:repeat(3,minmax(0,1fr))}.handoff-signoff{flex-direction:column}.history-row{grid-template-columns:1fr;gap:6px}.handoff-summary{gap:8px;flex-wrap:wrap}.handoff-actions{flex-wrap:wrap}}
</style>
