<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { VideoCamera, SwitchButton } from '@element-plus/icons-vue'
import type { RoomKit, ExitedPayload } from '@tencentcloud/roomkit-web-vue3'
import { meetingEventsApi as api, type MeetingEvent } from '@/api/meetingEvents'
import { authState, sessionRevision } from '@/stores/auth'
import { destroyVideoRoom, pendingVideoCleanup } from '@/utils/meeting-video-lifecycle'

const props=defineProps<{meeting:MeetingEvent}>()
const emit=defineEmits<{changed:[]}>()
const container=ref<HTMLElement>(), busy=ref(false), joined=ref(false), roomClosed=ref(false), error=ref('')
const progress=ref(''), connectionWarning=ref('')
const videoStatus = computed(() => joined.value ? '已加入视频会议' : busy.value ? '正在连接' : roomClosed.value || ['ENDED', 'CANCELLED'].includes(props.meeting.state) ? '视频已关闭' : error.value ? '连接失败' : '尚未加入视频')
let generation=0, disposed=false, room:RoomKit|undefined, sdk:typeof import('@tencentcloud/roomkit-web-vue3')|undefined
let off:(()=>void)|undefined, poll:ReturnType<typeof setInterval>|undefined, expiry:ReturnType<typeof setTimeout>|undefined
let checking=false, accessFailures=0, joinAttempt=0

async function bounded<T>(task:Promise<T>,milliseconds:number,message:string):Promise<T>{
  let timer:ReturnType<typeof setTimeout>|undefined
  try{return await Promise.race([task,new Promise<never>((_,reject)=>{timer=setTimeout(()=>reject(new Error(message)),milliseconds)})])}
  finally{clearTimeout(timer)}
}

function clearTimers(){clearInterval(poll);clearTimeout(expiry);poll=undefined;expiry=undefined}
async function release(){
  generation++;joined.value=false;connectionWarning.value='';accessFailures=0;clearTimers();off?.();off=undefined
  const instance=room, library=sdk;room=undefined
  if(instance&&library)await destroyVideoRoom(library)
}
async function leave(){
  if(busy.value)return
  busy.value=true
  try{await bounded(release(),15000,'退出超时')}catch{error.value='退出未完成，请关闭当前页面后重新进入'}finally{busy.value=false}
}
function revoked(){void release().catch(()=>{});busy.value=false}
async function checkAccess(){
  if(checking||(!joined.value&&!roomClosed.value))return
  const token=generation,meetingId=props.meeting.id,identity=sessionRevision()
  const valid=()=>!disposed&&token===generation&&identity===sessionRevision()&&meetingId===props.meeting.id
  checking=true
  try{
    const current=await api.get(meetingId)
    if(!valid())return
    accessFailures=0;connectionWarning.value=''
    if(current.state!=='IN_PROGRESS'||!current.video_enabled){error.value='';await release();emit('changed')}
  }catch(e:any){if(valid()){
    const status=e?.response?.status
    if([401,403,404].includes(status)||++accessFailures>=3){
      error.value='会议访问校验失败，已退出视频，请刷新后重试'
      void release().catch(()=>{})
    }else connectionWarning.value='会议状态暂时无法同步，正在重试'
  }}finally{checking=false}
}
async function exited(event:ExitedPayload){
  const dismissed=event.reason==='RoomDismiss', own=props.meeting.available_actions.includes('end')
  const meetingId=props.meeting.id,identity=sessionRevision()
  if(dismissed)roomClosed.value=true
  const releasing=release().catch(()=>{}),token=generation
  const current=()=>!disposed&&token===generation&&identity===sessionRevision()&&meetingId===props.meeting.id
  await releasing
  if(!current())return
  if(dismissed&&own){
    try{
      const latest=await api.get(meetingId)
      if(!current())return
      if(latest.state==='IN_PROGRESS')await api.command(meetingId,'end',{expected_revision:latest.revision,operation_id:crypto.randomUUID()})
    }catch{
      // The REST end transaction may commit after Tencent broadcasts RoomDismiss.
      const latest=await api.get(meetingId).catch(()=>null)
      if(!current())return
      if(!latest||!['ENDED','CANCELLED'].includes(latest.state))error.value='视频房间已关闭，会议状态同步失败，请点击“结束会议”重试'
    }
  }else if(!['RoomLeave','RoomDismiss'].includes(event.reason)){
    error.value=event.reason==='UserSigExpired'?'入会凭证已过期，请重新加入':'已离开视频会议，请刷新后重试'
  }
  if(dismissed&&current()){
    if(props.meeting.state==='IN_PROGRESS')poll=setInterval(()=>{void checkAccess()},10000)
    emit('changed')
  }
}
async function join(){
  if(busy.value||joined.value||roomClosed.value||props.meeting.state!=='IN_PROGRESS')return
  if(!window.isSecureContext){error.value='视频会议需要通过 HTTPS 或本机地址访问';return}
  const token=++generation, attempt=++joinAttempt, identity=sessionRevision(), meetingId=props.meeting.id
  const current=()=>!disposed&&token===generation&&identity===sessionRevision()&&meetingId===props.meeting.id
  busy.value=true;error.value='';connectionWarning.value=''
  try{
    await bounded((async()=>{
    progress.value='正在清理上次连接'
    await pendingVideoCleanup()
    if(!current())return
    progress.value='正在获取入会凭证'
    const credentials=await api.videoSession(meetingId)
    if(!current())return
    progress.value='正在加载视频组件'
    sdk=await import('@tencentcloud/roomkit-web-vue3')
    await pendingVideoCleanup()
    if(!current()||!container.value)return
    progress.value='正在连接腾讯视频会议'
    room=sdk.RoomKit.getInstance({sdkAppId:credentials.sdkAppId,userId:credentials.userId,userSig:credentials.userSig,userName:credentials.userName})
    room.setUIConfig({language:'zh-CN',theme:{themeStyle:'light',primaryColor:'#18745b'},shareLink:'',contactList:()=>[]})
    off=room.on('exited',event=>{if(current())void exited(event)})
    await room.join({roomId:credentials.roomId,password:credentials.password,container:{appendTo:container.value,width:'100%',height:'100%'}})
    if(!current())return
    joined.value=true
    poll=setInterval(()=>{void checkAccess()},10000)
    expiry=setTimeout(()=>{revoked();error.value='入会凭证已到期，请重新加入'},Math.max(0,Date.parse(credentials.expiresAt)-Date.now()))
    })(),60000,'视频连接超时，请重试；若仍无法连接，请刷新页面')
  }catch(e:any){
    if(current()){
      error.value=e?.response?.data?.message||(e?.message?.startsWith('视频连接超时')?e.message:'入会失败，请检查浏览器音视频权限及网络后重试')
      void release().catch(()=>{})
    }
  }finally{if(!disposed&&attempt===joinAttempt){busy.value=false;progress.value=''}}
}
watch(()=>props.meeting.state,value=>{if(value!=='IN_PROGRESS')revoked()})
watch([()=>authState.user?.user_id,()=>authState.provider],revoked)
for(const name of ['oa-session-expired','oa-permissions-changed','oa-identity-changed'])window.addEventListener(name,revoked)
onBeforeUnmount(()=>{
  disposed=true
  for(const name of ['oa-session-expired','oa-permissions-changed','oa-identity-changed'])window.removeEventListener(name,revoked)
  revoked()
})
</script>

<template>
  <section class="oa-section video-meeting" aria-label="视频会议">
    <div class="video-heading"><div class="video-heading-status"><h2>视频会议</h2><el-tag :type="joined ? 'success' : error ? 'danger' : 'info'" role="status" aria-live="polite">{{ videoStatus }}</el-tag></div><el-button v-if="joined" :icon="SwitchButton" :loading="busy" @click="leave">退出视频</el-button><el-button v-else type="primary" :icon="VideoCamera" :loading="busy" :disabled="roomClosed||meeting.state!=='IN_PROGRESS'" @click="join">加入视频会议</el-button></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <el-alert v-if="connectionWarning" :title="connectionWarning" type="warning" :closable="false"/>
    <p v-if="busy&&!joined" class="muted" role="status">{{progress}}</p>
    <p v-if="!joined&&!busy" class="muted">{{roomClosed?'会议已关闭':meeting.state==='IN_PROGRESS'?'会议已开始，你尚未入会。点击“加入视频会议”后连接音视频。':meeting.state==='SCHEDULED'||meeting.state==='DRAFT'?'等待主持人开始会议':'会议已关闭'}}</p>
    <div ref="container" class="video-container" :class="{'is-open':joined||busy}"/>
  </section>
</template>

<style scoped>
.video-meeting{min-width:0}.video-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}.video-heading h2{font-size:17px;margin:18px 0}.video-container{display:none;width:100%;height:650px;max-height:85dvh;min-width:0;position:relative;overflow:hidden;background:#f5f6f7}.video-container.is-open{display:block}.muted{color:var(--oa-muted);font-size:14px}
.video-heading-status{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
@media(max-width:600px){.video-container{height:720px;max-height:85dvh}.video-heading{gap:8px}}
</style>
