<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { oaApi } from '@/api/oa'
import { canOA, messageOf, useOACommands } from '@/utils/oa'
import type { FormalTicket } from '@/types/oa'
const {busy,error,run}=useOACommands();const rows=ref<FormalTicket[]>([]),selected=ref<FormalTicket|null>(null),loading=ref(false),mode=ref<'mine'|'handling'>('mine'),showCreate=ref(false),candidate=ref<Record<string,unknown>|null>(null),note=ref('')
const form=reactive({summary:'',category:'其他',priority:'medium',impact:'个人'});const labels:Record<string,string>={OPEN:'待处理',IN_PROGRESS:'处理中',RESOLVED:'已解决',CLOSED:'已关闭',low:'低',medium:'中',high:'高'};const uid=()=>crypto.randomUUID()
const canHandle=computed(()=>canOA('ticket_handle','write'))
const route=useRoute()
let loadRevision=0
async function load(){
  const revision=++loadRevision
  if(!canOA(mode.value==='handling'?'ticket_handle':'ticket')){selected.value=null;rows.value=[];error.value='当前账号没有工单读取权限';return}
  loading.value=true;error.value=''
  const target=String(route.params.ticketId||selected.value?.id||'')
  selected.value=null
  try{
    const list=await oaApi.tickets(mode.value==='handling')
    const current=target?await oaApi.ticket(target):null
    if(revision!==loadRevision)return
    rows.value=list;selected.value=current
  }catch(e){if(revision===loadRevision){selected.value=null;error.value=messageOf(e)}}
  finally{if(revision===loadRevision)loading.value=false}
}
watch(form,()=>{candidate.value=null},{flush:'sync'})
async function prepare(){if(!form.summary.trim())return;const snapshot={...form},operation_id=uid();try{const result=await oaApi.prepareTicket({operation_id,...snapshot});if(JSON.stringify(snapshot)===JSON.stringify(form))candidate.value={...result,operation_id}}catch(e){error.value=messageOf(e)}}
async function create(){if(!candidate.value)return;const confirmation_id=String(candidate.value.confirmation_id||''),operation_id=String(candidate.value.operation_id||'');if(!confirmation_id||!operation_id){error.value='确认信息已失效，请重新准备';return};const result=await run('ticket:create',{...form,thread_id:null,confirmation_id},p=>oaApi.createTicket(p),operation_id);if(result){showCreate.value=false;candidate.value=null;Object.assign(form,{summary:'',category:'其他',priority:'medium',impact:'个人'});await load()}}
async function handle(action:'claim'|'start'|'resolve'|'reassign'){if(!selected.value||!canHandle.value)return;const result=await run('ticket:'+action,{expected_revision:selected.value.revision,action,note:note.value},p=>oaApi.handleTicket(selected.value!.id,p));if(result){selected.value=result.result;note.value='';await load()}}
watch(()=>route.params.ticketId,()=>{selected.value=null;load()},{immediate:true})
</script>
<template><main class="workbench manual-oa ticket-page" v-loading="loading"><header class="page-heading"><div><p class="eyebrow">正式 OA · 服务管理</p><h1>工单工作台</h1><p class="muted">查看本人提交的工单，或处理当前部门的人工工单。</p></div><div class="actions"><el-button @click="load">刷新</el-button><el-button type="primary" @click="showCreate=true">新建工单</el-button></div></header><el-alert v-if="error" :title="error" type="error" :closable="false"/><div class="actions oa-tabs"><el-button :type="mode==='mine'?'primary':'default'" @click="mode='mine';load()">本人工单</el-button><el-button v-if="canOA('ticket_handle')" :type="mode==='handling'?'primary':'default'" @click="mode='handling';load()">工单处理列表</el-button></div><div class="oa-two-pane"><section class="oa-section"><el-empty v-if="!rows.length" description="暂无工单"/><button v-for="row in rows" :key="row.id" class="oa-list-item" :class="{active:selected?.id===row.id}" @click="selected=row"><strong>{{row.business_no}}</strong><span>{{row.summary}}</span><span>{{labels[row.state]||row.state}} · {{row.priority}}</span></button></section><section class="oa-section"><el-empty v-if="!selected" description="选择工单查看详情"/><template v-else><div class="node-heading"><h2>{{selected.business_no}}</h2><el-tag>{{labels[selected.state]||selected.state}}</el-tag></div><p>{{selected.summary}}</p><dl class="oa-grid"><div><dt>类别</dt><dd>{{selected.category}}</dd></div><div><dt>影响范围</dt><dd>{{selected.impact}}</dd></div><div><dt>队列</dt><dd>{{selected.queue||'待分派'}}</dd></div><div><dt>负责人</dt><dd>{{selected.assignee_id||'待领取'}}</dd></div></dl><p v-if="selected.assignment_error" class="muted">{{selected.assignment_error}}</p><el-divider v-if="mode==='handling'"/><el-input v-if="mode==='handling'" v-model="note" type="textarea" :rows="3" placeholder="填写办理说明"/><div v-if="mode==='handling'" class="actions form-actions"><el-button v-if="selected.state==='OPEN'" :disabled="busy" @click="handle('claim')">领取</el-button><el-button v-if="selected.state==='IN_PROGRESS'" :disabled="busy" @click="handle('start')">开始办理</el-button><el-button v-if="['OPEN','IN_PROGRESS'].includes(selected.state)" type="primary" :disabled="busy||!note.trim()" @click="handle('resolve')">完成工单</el-button></div><el-divider/><h3>重复候选与反馈</h3><el-empty v-if="!selected.merged_requests?.length&&!selected.feedback?.length" description="暂无关联记录"/><p v-for="item in selected.merged_requests||[]" :key="String(item.operation_id)">已合并请求：{{item.summary}}</p><p v-for="item in selected.feedback||[]" :key="String(item.id)">{{item.resolved?'用户确认已解决':'用户反馈未解决'}}：{{item.comment}}</p></template></section></div><el-dialog v-model="showCreate" title="新建工单" width="min(560px, calc(100vw - 32px))"><el-form label-position="top"><el-form-item label="问题描述"><el-input v-model="form.summary" type="textarea" :rows="4"/></el-form-item><el-form-item label="类别"><el-select v-model="form.category"><el-option label="其他" value="其他"/><el-option label="账号与权限" value="账号与权限"/><el-option label="系统故障" value="系统故障"/></el-select></el-form-item><el-form-item label="优先级"><el-select v-model="form.priority"><el-option label="低" value="low"/><el-option label="中" value="medium"/><el-option label="高" value="high"/></el-select></el-form-item><el-button v-if="!candidate" type="primary" :disabled="!form.summary.trim()" @click="prepare">检查重复工单</el-button><template v-else><el-alert title="已完成重复候选检查，请确认提交" type="info"/><p v-for="item in (candidate.duplicate_candidates as any[])||[]" :key="item.id" class="muted">候选：{{item.summary}}（相似度 {{item.score}}）</p><el-button type="primary" @click="create">确认创建工单</el-button></template></el-form></el-dialog></main></template>
<style scoped>.ticket-page .oa-section{min-width:0}.ticket-page .el-dialog{max-width:calc(100vw - 32px)}</style>
