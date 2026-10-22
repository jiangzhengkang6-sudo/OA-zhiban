<script setup lang="ts">
import {computed,ref,watch,onBeforeUnmount} from 'vue'
import {Refresh,Check} from '@element-plus/icons-vue'
import {oaApi} from '@/api/oa'
import {canOA,oaLabel,useOACommands,messageOf,downloadOA,fileId} from '@/utils/oa'
import type {Approval} from '@/types/oa'
const {busy,error,run}=useOACommands(),kind=ref<'pending'|'done'|'cc'>('pending'),items=ref<Approval[]>([]),node=ref<Approval|null>(null),loading=ref(false)
const action=ref('approve'),note=ref(''),reason=ref('other'),corrections=ref<string[]>([]),approvalNote=ref('')
const reimbursementFields=computed(()=>node.value?.scene==='reimbursement'&&node.value.fields&&'purpose' in node.value.fields?node.value.fields:null)
const leaveFields=computed(()=>node.value?.fields&&'leave_type' in node.value.fields?node.value.fields:null)
const correctionFields=computed(()=>node.value?.scene==='reimbursement'?['purpose','expense_date','category','amount','currency','attachment_ids']:['leave_type','start_date','end_date','reason','attachment_ids'])
let revision=0
async function load(){const request=++revision;node.value=null;items.value=[];error.value='';if(!canOA('approval')){error.value='当前账号没有审批读取权限';return}loading.value=true;try{const rows=await oaApi.approvals(kind.value);if(request===revision)items.value=rows}catch(e){if(request===revision)error.value=messageOf(e)}finally{if(request===revision)loading.value=false}}
async function open(id:string){if(kind.value!=='pending')return;const request=++revision;node.value=null;error.value='';try{const value=await oaApi.node(id);if(request!==revision)return;node.value=value;action.value='approve';note.value='';corrections.value=[];approvalNote.value=''}catch(e){if(request===revision)error.value=messageOf(e)}}
async function decide(){const value=node.value;if(!value||!canOA('approval','write')||!value.allowed_actions?.includes(action.value))return
  const result=await run('decide:'+value.node_id,{expected_revision:value.revision,action:action.value,note:note.value,reason_code:reason.value,corrections:action.value==='return_for_correction'?corrections.value:[],...(action.value==='approve'?{approval_note:approvalNote.value}:{})},p=>oaApi.decide(value.node_id,p))
  if(result)await load()
}
async function download(id:string,name:string){try{await downloadOA(`/oa/approvals/nodes/${node.value!.node_id}/attachments/${id}/content`,name)}catch(e){error.value=messageOf(e)}}
watch(kind,()=>void load(),{immediate:true});onBeforeUnmount(()=>revision++)
</script>
<template>
  <main class="workbench manual-oa" v-loading="loading"><header class="page-heading"><h1>审批工作台</h1><el-button :icon="Refresh" :disabled="busy" @click="load">刷新</el-button></header>
    <div class="actions oa-tabs" role="tablist"><el-button v-for="(label,key) in {pending:'待办',done:'已办',cc:'抄送'}" :key="key" :data-testid="'tab-'+key" :type="kind===key?'primary':'default'" :disabled="busy" role="tab" :aria-selected="kind===key" @click="kind=key as typeof kind">{{label}}</el-button></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <el-table :data="items" empty-text="暂无记录"><el-table-column prop="business_no" label="申请编号" min-width="190"/><el-table-column prop="submission_version" label="提交轮次" width="100"/><el-table-column label="状态" min-width="130"><template #default="{row}">{{oaLabel(row.seat_state)}}</template></el-table-column><el-table-column label="截止时间" min-width="170"><template #default="{row}">{{row.due_at?new Date(row.due_at).toLocaleString('zh-CN'):'无'}}</template></el-table-column><el-table-column v-if="kind==='pending'" label="操作" width="80" fixed="right"><template #default="{row}"><el-button link type="primary" data-testid="open-node" @click="open(row.node_id)">办理</el-button></template></el-table-column><el-table-column v-else prop="decision_note" label="处理意见" min-width="180"/></el-table>
    <section v-if="node" class="oa-section"><h2>{{node.business_no}}</h2>
      <template v-if="reimbursementFields"><dl class="oa-grid"><div><dt>报销金额</dt><dd>{{reimbursementFields.amount}} 元</dd></div><div><dt>费用日期</dt><dd>{{reimbursementFields.expense_date}}</dd></div><div><dt>费用类别</dt><dd>{{reimbursementFields.category}}</dd></div><div><dt>币种</dt><dd>{{reimbursementFields.currency==='CNY'?'人民币':reimbursementFields.currency}}</dd></div></dl><p class="oa-prose">{{reimbursementFields.purpose}}</p></template>
      <template v-else-if="leaveFields"><dl class="oa-grid"><div><dt>假种</dt><dd>{{oaLabel(leaveFields.leave_type)}}</dd></div><div><dt>日期</dt><dd>{{leaveFields.start_date}} 至 {{leaveFields.end_date}}</dd></div></dl><p class="oa-prose">{{leaveFields.reason}}</p></template>
      <ul class="attachment-list"><li v-for="a in node.attachments" :key="fileId(a)" class="attachment-row"><span>{{a.filename}}</span><el-button link @click="download(fileId(a),a.filename)">下载材料</el-button></li></ul>
      <p v-for="(entry,i) in node.approval_notes" :key="i">补充说明：{{entry.approval_note||entry.note}}</p>
      <el-form v-if="canOA('approval','write')" label-position="top" @submit.prevent="decide">
        <div class="oa-grid"><label>审批决定<select v-model="action" aria-label="审批决定"><option v-for="a in node.allowed_actions" :key="a" :value="a">{{oaLabel(a)}}</option></select></label><label v-if="action!=='approve'">原因分类<select v-model="reason" aria-label="原因分类"><option v-for="r in ['materials_incomplete','date_issue','quota_issue','other']" :key="r" :value="r">{{oaLabel(r)}}</option></select></label></div>
        <fieldset v-if="action==='return_for_correction'" class="oa-checks"><legend>待修正内容</legend><label v-for="field in correctionFields" :key="field"><input v-model="corrections" type="checkbox" :value="field"/>{{oaLabel(field)}}</label></fieldset>
        <el-form-item label="处理意见"><el-input v-model="note" type="textarea" aria-label="处理意见" :maxlength="2000" :rows="3"/></el-form-item>
        <el-form-item v-if="action==='approve'" label="补充审批说明"><el-input v-model="approvalNote" aria-label="补充审批说明" :maxlength="2000"/></el-form-item>
        <el-button data-testid="decide-node" native-type="button" type="primary" :icon="Check" :disabled="busy||action!=='approve'&&!note.trim()||action==='return_for_correction'&&!corrections.length" @click="decide">确认{{oaLabel(action)}}</el-button>
      </el-form>
    </section>
  </main>
</template>
