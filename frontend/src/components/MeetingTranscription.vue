<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { Microphone, VideoPause, Refresh, Document } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { meetingTranscriptionApi as api, type TranscriptionStatus } from '@/api/meetingTranscription'
import { authState, sessionRevision } from '@/stores/auth'
import { replayable } from '@/api/draftCommands'
const props=defineProps<{meetingId:string;revision:number;meetingState:string}>()
const emit=defineEmits<{changed:[]}>()
const router=useRouter(), status=ref<TranscriptionStatus|null>(null), error=ref(''), busy=ref(false), consent=ref(false)
let timer:ReturnType<typeof setTimeout>|undefined, epoch=0, requestSerial=0, closed=false
const labels:Record<string,string>={NOT_STARTED:'尚未开启',QUEUED:'等待开启',STARTING:'正在开启',ACTIVE:'正在转写',STOPPING:'正在停止',
  FINALIZING:'等待剩余文本',READY:'等待整理',GENERATING:'正在生成纪要',DRAFT_READY:'草稿待审阅',REVIEW_REQUIRED:'需要人工处理',
  FAILED:'开启失败',UNKNOWN:'结果待核对',CANCELLED:'已停止'}
const recording=computed(()=>status.value&&['QUEUED','STARTING','ACTIVE','STOPPING','UNKNOWN'].includes(status.value.state))
const clock=(ms:number)=>new Date(ms).toLocaleTimeString('zh-CN',{hour12:false})
async function load(token=epoch){
  if(closed||token!==epoch)return
  clearTimeout(timer)
  const identity=sessionRevision(), request=++requestSerial
  try{
    const data=await api.get(props.meetingId)
    if(closed||token!==epoch||identity!==sessionRevision()||request!==requestSerial)return
    const previous=status.value
    status.value=data;error.value=''
    if(previous&&(previous.state!==data.state||previous.minutes_id!==data.minutes_id))emit('changed')
  }catch(e){if(token===epoch&&!closed&&identity===sessionRevision()&&request===requestSerial){status.value=null;error.value=e instanceof Error?e.message:'会议转写状态加载失败'}}
  finally{if(!closed&&token===epoch&&request===requestSerial)timer=setTimeout(()=>load(token),5000)}
}
async function act(action:string){
  if(busy.value)return
  const token=epoch, identity=sessionRevision(), meetingId=props.meetingId, revision=props.revision
  if(action==='start'&&!consent.value)return
  busy.value=true
  if(action==='start'){
    try{await ElMessageBox.confirm('开启后会将房间音频发送至腾讯语音识别服务。请确认已告知参会人并取得记录授权，转写可能产生费用。','开启会议转写',{confirmButtonText:'确认开启',cancelButtonText:'取消',type:'warning'})}
    catch{if(token===epoch)busy.value=false;return}
  }
  if(closed||token!==epoch||identity!==sessionRevision())return
  busy.value=true;error.value=''
  try{
    const payload={expected_revision:revision,...(action==='start'?{consent:true}:{})}
    await replayable('meeting-transcription-'+meetingId+'-'+action,payload,
      key=>{
        if(closed||token!==epoch||identity!==sessionRevision())throw new Error('登录状态已变化')
        return api.command(meetingId,action,{...payload,operation_id:key})
      })
    if(token===epoch&&!closed){emit('changed');await load(token)}
  }catch(e){if(token===epoch&&!closed)error.value=e instanceof Error?e.message:'操作失败，请刷新后重试'}
  finally{if(token===epoch)busy.value=false}
}
watch(()=>[props.meetingId,authState.user?.user_id,authState.authorizationRevision,authState.accessToken],()=>{
  epoch++;status.value=null;error.value='';consent.value=false;busy.value=false;void load(epoch)
},{immediate:true})
watch(()=>props.meetingState,()=>{void load(epoch)})
onBeforeUnmount(()=>{closed=true;epoch++;clearTimeout(timer);status.value=null})
</script>

<template>
  <section class="oa-section transcription" aria-label="会议转写">
    <div class="transcription-bar"><h2>会议转写 <el-tag v-if="status" :type="recording?'warning':'info'">{{labels[status.state]||'待核对'}}</el-tag></h2>
      <div class="transcription-actions"><el-button v-if="status?.can_stop" :icon="VideoPause" :loading="busy" @click="act('stop')">停止转写</el-button>
        <el-button v-if="status?.can_retry" :icon="Refresh" :loading="busy" @click="act('retry')">重试整理纪要</el-button>
        <el-button v-if="status?.minutes_id" :icon="Document" @click="router.push('/meetings/'+status.minutes_id)">审阅纪要</el-button>
        <el-button :icon="Refresh" circle aria-label="刷新转写状态" title="刷新转写状态" @click="load(epoch)"/></div></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <template v-if="status">
      <el-alert v-if="recording" title="本场会议已开启语音记录，音频会发送至语音识别服务。" type="warning" :closable="false"/>
      <p v-if="!status.configured&&status.state==='NOT_STARTED'" class="muted">会议转写尚未配置，请联系管理员。</p>
      <p v-if="status.message" class="transcription-notice">{{status.message}}</p>
      <p v-if="status.state!=='NOT_STARTED'&&status.notice!==status.message" class="muted">{{status.notice}}</p>
      <p v-if="status.expired" class="muted">临时转写列表已到保存期限；已存入纪要的来源文本和草稿按纪要权限保留。</p>
      <div v-if="status.can_start" class="transcription-consent"><el-checkbox v-model="consent">已告知参会人并取得记录授权；原始转写仅发起人、主持人和记录人可查阅。</el-checkbox>
        <el-button type="primary" :icon="Microphone" :disabled="!consent" :loading="busy" @click="act('start')">开启转写</el-button></div>
      <div v-if="status.utterances.length" class="utterances" aria-label="转写文本">
        <article v-for="line in status.utterances" :key="line.id"><div class="utterance-meta"><strong>{{line.speaker}}</strong><time>{{clock(line.start_ms)}} - {{clock(line.end_ms)}}</time><el-tag v-if="line.late" size="small" type="warning">未纳入当前纪要</el-tag></div><p>{{line.text}}</p></article>
      </div>
      <p v-if="status.utterance_count>status.utterances.length" class="muted">共 {{status.utterance_count}} 条转写，当前展示前 {{status.utterances.length}} 条；整理纪要时会读取全部已保存文本。</p>
    </template>
  </section>
</template>

<style scoped>
.transcription{min-width:0}.transcription-bar,.transcription-actions{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.transcription-bar{justify-content:space-between}.transcription h2{font-size:17px;margin:0 0 12px;display:flex;align-items:center;gap:12px}.transcription-notice{line-height:1.7;overflow-wrap:anywhere}.transcription-consent{display:flex;flex-direction:column;align-items:flex-start;gap:12px;margin-top:16px}.transcription-consent :deep(.el-checkbox){white-space:normal;height:auto;align-items:flex-start}.transcription-consent :deep(.el-checkbox__label){white-space:normal;line-height:1.6}.utterances{max-height:420px;overflow-y:auto;margin-top:16px}.utterances article{padding:12px 0;border-bottom:1px solid var(--oa-border)}.utterance-meta{display:flex;gap:12px;align-items:center;flex-wrap:wrap;font-size:13px}.utterance-meta time{color:var(--oa-muted)}.utterances p{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.8;margin:8px 0 0}@media(max-width:600px){.transcription-bar{align-items:flex-start}.transcription-actions{gap:8px}.transcription-actions .el-button{margin-left:0}}
</style>
