<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Document, ArrowLeft, Edit, Promotion, VideoPlay, CircleCheck, Close, Link } from '@element-plus/icons-vue'
import { meetingEventsApi as api, type MeetingEvent, type MeetingFields, type MeetingPerson } from '@/api/meetingEvents'
import { replayable } from '@/api/draftCommands'
import { authState, can, sessionRevision } from '@/stores/auth'
import MeetingView from './MeetingView.vue'
import MeetingVideoRoom from '@/components/MeetingVideoRoom.vue'
import MeetingTranscription from '@/components/MeetingTranscription.vue'
import '@/styles/drafting.css'

const route=useRoute(), router=useRouter()
const id=computed(()=>String(route.params.id||'')), formal=computed(()=>authState.provider==='builtin')
const items=ref<MeetingEvent[]>([]), meeting=ref<MeetingEvent|null>(null), users=ref<MeetingPerson[]>([]), departments=ref<{id:string;name:string}[]>([])
const loading=ref(false),busy=ref(false),error=ref(''),mode=ref('all'),search=ref(''),dialog=ref(false),editing=ref(false),department=ref('')
const optionsLoading=ref(false),optionsError=ref(''),replyValue=ref('ACCEPTED'),replyNote=ref(''),minutesText=ref('')
const form=reactive<MeetingFields>({title:'',agenda:'',starts_at:'',ends_at:'',host_id:'',recorder_id:'',attendee_ids:[],location:'',online_url:'',video_enabled:false})
const labels:Record<string,string>={DRAFT:'草稿',SCHEDULED:'已安排',IN_PROGRESS:'进行中',ENDED:'已结束',CANCELLED:'已取消',PENDING:'未回复',ACCEPTED:'参加',DECLINED:'不参加',TENTATIVE:'待定'}
const deliveryLabels:Record<string,string>={PENDING:'待投递',PROCESSING:'投递中',ACCEPTED:'已送达',FAILED:'失败',UNKNOWN:'结果待核对',CANCELLED:'已停止'}
const historyLabels:Record<string,string>={'meeting.save':'保存或更新安排','meeting.publish':'发送邀请','meeting.start':'开始会议','meeting.end':'结束会议','meeting.cancel':'取消会议','meeting.reply':'回复邀请','meeting.minutes':'创建会议纪要','meeting.retry':'重试失败通知','meeting.transcription_start':'开启会议转写','meeting.transcription_stop':'停止会议转写','meeting.transcription_retry':'重试整理纪要'}
const person=(uid:string)=>meeting.value?.attendees.find(x=>x.user_id===uid)?.display_name||users.value.find(x=>x.id===uid)?.display_name||'成员'
const date=(value:string)=>new Date(value).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})
const allowed=(action:string)=>!!meeting.value?.available_actions.includes(action)
const filtered=computed(()=>items.value.filter(x=>!search.value||x.title.includes(search.value)).sort((a,b)=>{
  const active=(x:MeetingEvent)=>['SCHEDULED','IN_PROGRESS'].includes(x.state)?0:x.state==='DRAFT'?1:2
  return active(a)-active(b)||(active(a)===0?Date.parse(a.starts_at)-Date.parse(b.starts_at):Date.parse(b.starts_at)-Date.parse(a.starts_at))
}))
const visibleUsers=computed(()=>users.value.filter(x=>!department.value||x.department_id===department.value||form.attendee_ids.includes(x.id)))
const valid=computed(()=>form.title.trim()&&form.agenda.trim()&&form.starts_at&&form.ends_at&&Date.parse(form.ends_at)>Date.parse(form.starts_at)&&form.host_id&&form.recorder_id&&form.attendee_ids.length&&(form.location.trim()||form.online_url.trim()||form.video_enabled))
const isOrganizer=computed(()=>meeting.value?.organizer_id===authState.user?.user_id)
let serial=0
function problem(e:any){error.value=e?.response?.data?.message||e?.message||'操作未完成，请重试'}
async function load(){
  if(!formal.value)return
  const token=++serial,target=id.value;loading.value=true;error.value='';items.value=[]
  if(meeting.value?.id!==target)meeting.value=null
  try{if(target){const result=await api.get(target);if(token===serial){meeting.value=result;const own=result.attendees.find(x=>x.user_id===authState.user?.user_id);replyValue.value=own?.response==='PENDING'?'ACCEPTED':own?.response||'ACCEPTED';replyNote.value=own?.note||''}}
    else{const result=await api.list(mode.value);if(token===serial)items.value=result}}
  catch(e:any){if(token===serial){if([401,403,404].includes(e?.response?.status))meeting.value=null;problem(e)}}finally{if(token===serial)loading.value=false}
}
watch([id,mode,formal],()=>{dialog.value=false;minutesText.value='';void load()},{immediate:true})
async function loadOptions(){optionsLoading.value=true;optionsError.value='';try{const result=await api.options();users.value=result.users;departments.value=result.departments}catch(e:any){optionsError.value=e?.response?.data?.message||'人员加载失败'}finally{optionsLoading.value=false}}
async function openForm(edit=false){
  editing.value=edit;department.value='';optionsError.value='';users.value=[];dialog.value=true
  if(edit&&meeting.value){const m=meeting.value;Object.assign(form,{title:m.title,agenda:m.agenda,starts_at:m.starts_at,ends_at:m.ends_at,host_id:m.host_id,recorder_id:m.recorder_id,attendee_ids:m.attendees.map(x=>x.user_id),location:m.location,online_url:m.online_url,video_enabled:m.video_enabled??false})}
  else Object.assign(form,{title:'',agenda:'',starts_at:'',ends_at:'',host_id:authState.user?.user_id||'',recorder_id:authState.user?.user_id||'',attendee_ids:[],location:'',online_url:'',video_enabled:false})
  await loadOptions()
}
function fields():MeetingFields{return {...form,title:form.title.trim(),agenda:form.agenda.trim(),starts_at:new Date(form.starts_at).toISOString(),ends_at:new Date(form.ends_at).toISOString(),attendee_ids:[...form.attendee_ids],location:form.location.trim(),online_url:form.online_url.trim()}}
async function confirmConflicts(payload:MeetingFields,exclude?:string){const conflicts=await api.conflicts(payload,exclude);if(!conflicts.length)return true;try{await ElMessageBox.confirm(conflicts.map(x=>`${x.display_name}（${x.count} 场）`).join('、')+'在该时段已有会议，仍要继续安排吗？','参会时间冲突',{confirmButtonText:'继续安排',cancelButtonText:'返回修改',type:'warning'});return true}catch{return false}}
async function save(){
  if(!valid.value||busy.value||optionsLoading.value||optionsError.value)return
  busy.value=true;error.value=''
  try{const data=fields(),target=editing.value?meeting.value?.id:undefined
    if(editing.value&&meeting.value?.state==='SCHEDULED'&&!await confirmConflicts(data,target))return
    const payload={...data,...(target?{expected_revision:meeting.value!.revision}:{})}
    const result=await replayable('meeting-event-save:'+ (target||'new'),payload,key=>api.save({...payload,operation_id:key},target))
    dialog.value=false;ElMessage.success(target?'会议安排已更新':'会议草稿已保存')
    if(id.value===result.result.id)await load();else await router.push('/meeting-events/'+result.result.id)
  }catch(e){problem(e)}finally{busy.value=false}
}
async function command(action:string,extra:Record<string,unknown>={}){
  if(!meeting.value||busy.value)return
  const row=meeting.value,target=row.id,token=serial
  busy.value=true;error.value=''
  try{
    if(action==='publish'){
      const data:MeetingFields={title:row.title,agenda:row.agenda,starts_at:row.starts_at,ends_at:row.ends_at,host_id:row.host_id,recorder_id:row.recorder_id,attendee_ids:row.attendees.map(x=>x.user_id),location:row.location,online_url:row.online_url,video_enabled:row.video_enabled??false}
      if(!await confirmConflicts(data,target))return
      try{await ElMessageBox.confirm('确认向所选参会人发送会议邀请？','发送会议邀请',{confirmButtonText:'发送邀请',cancelButtonText:'取消'})}catch{return}
    }
    if(action==='cancel'){try{const result=await ElMessageBox.prompt('请输入取消原因','取消会议',{inputValidator:value=>!!value?.trim()||'请填写取消原因',confirmButtonText:'确认取消会议',cancelButtonText:'返回'});extra={reason:result.value.trim()}}catch{return}}
    if(action==='end'){try{await ElMessageBox.confirm('确认结束本次会议？','结束会议',{confirmButtonText:'结束会议',cancelButtonText:'返回'})}catch{return}}
    const payload={expected_revision:row.revision,...extra}
    await replayable('meeting-event:'+target+':'+action,payload,key=>api.command(target,action,{...payload,operation_id:key}))
    if(token===serial&&target===id.value){await load();ElMessage.success(action==='reply'?'参会反馈已提交':'操作完成')}
  }catch(e){if(token===serial)problem(e)}finally{busy.value=false}
}
let videoRefreshSerial=0
async function refreshVideoState(){
  const target=meeting.value?.id, identity=sessionRevision(), request=++videoRefreshSerial, page=serial
  if(!target)return
  try{
    const fresh=await api.get(target)
    if(target===id.value&&identity===sessionRevision()&&request===videoRefreshSerial&&page===serial)meeting.value=fresh
  }catch(e){if(target===id.value&&identity===sessionRevision()&&request===videoRefreshSerial&&page===serial)problem(e)}
}
</script>

<template>
  <MeetingView v-if="!formal"/>
  <main v-else class="workbench manual-oa meeting-management" v-loading="loading">
    <header class="page-heading"><div><p class="eyebrow">部门协作</p><h1>{{meeting?.title||'会议管理'}}</h1></div>
      <div class="toolbar"><el-button v-if="id" :icon="ArrowLeft" @click="router.push('/meetings')">会议列表</el-button><el-button :icon="Refresh" :disabled="busy" @click="load">刷新</el-button><el-button v-if="!id" :icon="Document" @click="router.push('/meeting-texts')">整理已有会议文本</el-button><el-button v-if="!id&&can('meeting','write')" type="primary" :icon="Plus" @click="openForm()">发起会议</el-button></div>
    </header>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <template v-if="!id">
      <div class="list-tools"><el-radio-group v-model="mode" aria-label="会议范围"><el-radio-button value="all">全部会议</el-radio-button><el-radio-button value="organized">我发起的</el-radio-button><el-radio-button value="invited">邀请我的</el-radio-button></el-radio-group><el-input v-model="search" clearable aria-label="搜索会议" placeholder="搜索会议主题" class="meeting-search"/></div>
      <el-empty v-if="!filtered.length&&!loading" description="暂无会议"/>
      <div class="meeting-list"><button v-for="item in filtered" :key="item.id" class="meeting-list-row" @click="router.push('/meeting-events/'+item.id)"><span class="meeting-title">{{item.title}}<small>{{date(item.starts_at)}} — {{date(item.ends_at)}} · {{item.location||'在线会议'}}</small></span><span class="row-status"><el-tag :type="item.state==='CANCELLED'?'info':item.state==='IN_PROGRESS'?'success':'primary'">{{labels[item.state]}}</el-tag><small>{{item.attendees.length}} 人</small></span></button></div>
    </template>
    <template v-else-if="meeting">
      <MeetingVideoRoom v-if="meeting.video_enabled" :key="meeting.id" :meeting="meeting" @changed="refreshVideoState"/>
      <MeetingTranscription v-if="meeting.video_enabled&&authState.aiEnabled" :key="'transcription-'+meeting.id" :meeting-id="meeting.id" :revision="meeting.revision" :meeting-state="meeting.state" @changed="refreshVideoState"/>
      <el-alert v-else class="meeting-video-notice" title="未启用内置视频会议" :description="meeting.online_url ? '本次会议使用外部会议链接。' : '本次会议为线下或通知会议，开始会议不会连接音视频。'" type="info" :closable="false"/>
      <section class="oa-section"><div class="detail-bar"><el-tag>{{labels[meeting.state]}}</el-tag><div class="toolbar"><el-button v-if="allowed('edit')" :icon="Edit" :disabled="busy" @click="openForm(true)">修改安排</el-button><el-button v-if="allowed('publish')" type="primary" :icon="Promotion" :loading="busy" @click="command('publish')">发送邀请</el-button><el-button v-if="allowed('start')" type="primary" :icon="VideoPlay" :loading="busy" @click="command('start')">开始会议</el-button><el-button v-if="allowed('end')" type="primary" :icon="CircleCheck" :loading="busy" @click="command('end')">结束会议</el-button><el-button v-if="allowed('cancel')" type="danger" plain :icon="Close" :disabled="busy" @click="command('cancel')">取消会议</el-button></div></div>
        <dl class="meeting-facts"><div><dt>会议时间</dt><dd>{{date(meeting.starts_at)}} — {{date(meeting.ends_at)}}</dd></div><div><dt>地点</dt><dd>{{meeting.location||'在线会议'}}</dd></div><div><dt>发起人</dt><dd>{{person(meeting.organizer_id)}}</dd></div><div><dt>主持人 / 记录人</dt><dd>{{person(meeting.host_id)}} / {{person(meeting.recorder_id)}}</dd></div></dl>
        <el-link v-if="meeting.online_url" :href="meeting.online_url" target="_blank" rel="noopener noreferrer" type="primary" :icon="Link">进入在线会议</el-link><h2>会议议题</h2><p class="agenda">{{meeting.agenda}}</p><el-alert v-if="meeting.cancel_reason" :title="'取消原因：'+meeting.cancel_reason" type="warning" :closable="false"/>
      </section>
      <section class="oa-section"><h2>参会人员 <span class="muted">{{meeting.attendees.filter(x=>x.response==='ACCEPTED').length}} / {{meeting.attendees.length}} 人已确认参加</span></h2><div class="attendee-grid"><div v-for="a in meeting.attendees" :key="a.user_id" class="attendee"><strong>{{a.display_name}}</strong><el-tag size="small" :type="a.response==='ACCEPTED'?'success':a.response==='DECLINED'?'danger':'info'">{{labels[a.response]}}</el-tag><small v-if="a.note">{{a.note}}</small></div></div>
        <el-form v-if="allowed('reply')" class="reply-form" label-position="top"><el-form-item label="我的参会反馈"><el-radio-group v-model="replyValue"><el-radio value="ACCEPTED">参加</el-radio><el-radio value="DECLINED">不参加</el-radio><el-radio value="TENTATIVE">待定</el-radio></el-radio-group></el-form-item><el-form-item label="备注"><el-input v-model="replyNote" maxlength="500" placeholder="选填"/></el-form-item><el-button :loading="busy" type="primary" @click="command('reply',{invitation_version:meeting.invitation_version,response:replyValue,note:replyNote})">提交反馈</el-button></el-form>
      </section>
      <section v-if="meeting.state==='ENDED'&&authState.aiEnabled" class="oa-section"><h2>会议纪要</h2><el-button v-if="meeting.minutes_id&&meeting.minutes_accessible" :icon="Document" type="primary" @click="router.push('/meetings/'+meeting.minutes_id)">查看会议纪要</el-button><template v-else-if="!meeting.minutes_id&&allowed('minutes')"><el-input v-model="minutesText" type="textarea" :rows="7" maxlength="100000" aria-label="会后会议文本" placeholder="录入会议讨论、决策和待办"/><el-button class="minutes-create" type="primary" :disabled="!minutesText.trim()" :loading="busy" :icon="Document" @click="command('minutes',{content:minutesText})">创建纪要</el-button></template><el-empty v-else description="纪要尚未发布"/></section>
      <section v-if="isOrganizer&&meeting.deliveries?.length" class="oa-section"><div class="detail-bar"><h2>邀请与变更通知</h2><el-button v-if="meeting.deliveries.some(x=>x.state==='FAILED')" :icon="Refresh" :loading="busy" @click="command('retry-notifications')">重试失败通知</el-button></div><el-table :data="meeting.deliveries"><el-table-column label="收件人" min-width="100"><template #default="{row}">{{person(row.recipient_id)}}</template></el-table-column><el-table-column label="渠道" width="100"><template #default="{row}">{{row.channel==='inbox'?'站内信':row.channel==='smtp'?'邮件':'企业微信'}}</template></el-table-column><el-table-column label="状态" min-width="130"><template #default="{row}">{{deliveryLabels[row.state]}}</template></el-table-column></el-table></section>
      <section class="oa-section"><h2>变更记录</h2><p v-for="(event,index) in meeting.history" :key="index" class="history-row"><time>{{date(event.created_at)}}</time><span>{{person(event.actor_id)}} · {{historyLabels[event.action]||'更新会议'}}</span></p><p v-if="!meeting.history?.length" class="muted">暂无变更记录</p></section>
    </template>
    <el-dialog v-model="dialog" :title="editing?'修改会议安排':'发起会议'" width="680px" class="meeting-form-dialog" :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy">
      <el-alert v-if="optionsError" :title="optionsError" type="error" :closable="false"/><el-button v-if="optionsError" :icon="Refresh" @click="loadOptions">重新加载人员</el-button><el-alert v-if="error" :title="error" type="error" :closable="false"/>
      <el-form label-position="top" v-loading="optionsLoading"><el-form-item label="会议主题" required><el-input v-model="form.title" maxlength="255" aria-label="会议主题"/></el-form-item><el-form-item label="会议议题" required><el-input v-model="form.agenda" type="textarea" :rows="3" maxlength="20000" aria-label="会议议题"/></el-form-item>
        <div class="form-columns"><el-form-item label="开始时间" required><el-date-picker v-model="form.starts_at" type="datetime" aria-label="开始时间" placeholder="选择开始时间" format="YYYY-MM-DD HH:mm"/></el-form-item><el-form-item label="结束时间" required><el-date-picker v-model="form.ends_at" type="datetime" aria-label="结束时间" placeholder="选择结束时间" format="YYYY-MM-DD HH:mm"/></el-form-item></div>
        <div class="form-columns"><el-form-item label="主持人" required><el-select v-model="form.host_id" filterable aria-label="主持人"><el-option v-for="u in users" :key="u.id" :value="u.id" :label="u.display_name"/></el-select></el-form-item><el-form-item label="记录人" required><el-select v-model="form.recorder_id" filterable aria-label="记录人"><el-option v-for="u in users" :key="u.id" :value="u.id" :label="u.display_name"/></el-select></el-form-item></div>
        <el-form-item label="按部门筛选人员"><el-select v-model="department" clearable aria-label="筛选参会部门" placeholder="全部部门"><el-option v-for="d in departments" :key="d.id" :value="d.id" :label="d.name"/></el-select></el-form-item><el-form-item label="参会人员" required><el-select v-model="form.attendee_ids" multiple filterable aria-label="参会人员" placeholder="选择参会人员"><el-option v-for="u in visibleUsers" :key="u.id" :value="u.id" :label="u.display_name"/></el-select></el-form-item>
        <el-form-item label="视频会议"><el-switch v-model="form.video_enabled" aria-label="启用视频会议" active-text="启用腾讯视频会议"/></el-form-item>
        <el-form-item label="会议地点"><el-input v-model="form.location" maxlength="255" aria-label="会议地点"/></el-form-item><el-form-item label="在线会议链接"><el-input v-model="form.online_url" maxlength="2000" aria-label="在线会议链接" placeholder="https://"/></el-form-item>
      </el-form><template #footer><el-button :disabled="busy" @click="dialog=false">取消</el-button><el-button type="primary" :disabled="!valid||optionsLoading||!!optionsError" :loading="busy" @click="save">{{editing?'保存安排':'保存草稿'}}</el-button></template>
    </el-dialog>
  </main>
</template>

<style scoped>
.meeting-management{min-width:0}.toolbar,.detail-bar,.list-tools{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.detail-bar,.list-tools{justify-content:space-between}.list-tools{margin:22px 0}.meeting-search{max-width:260px}.meeting-list-row{display:flex;justify-content:space-between;gap:16px;width:100%;padding:20px 4px;background:transparent;border:0;border-bottom:1px solid var(--oa-border);cursor:pointer;text-align:left;color:var(--oa-text);font:inherit}.meeting-list-row:hover{background:#f0f8f5}.meeting-title{font-weight:600;min-width:0;overflow-wrap:anywhere}.meeting-title small,.row-status small{display:block;margin-top:8px;color:var(--oa-muted);font-size:13px;font-weight:400}.row-status{flex-shrink:0;text-align:right}.meeting-facts{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin:24px 0}.meeting-facts dt{color:var(--oa-muted);font-size:13px}.meeting-facts dd{margin:6px 0 0;overflow-wrap:anywhere}.agenda{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.8}.attendee-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:12px}.attendee{display:flex;align-items:center;flex-wrap:wrap;gap:8px;border-bottom:1px solid var(--oa-border);padding:12px 0}.attendee small{width:100%;color:var(--oa-muted);overflow-wrap:anywhere}.reply-form{max-width:480px;margin-top:24px}.form-columns{display:grid;grid-template-columns:1fr 1fr;gap:16px}.form-columns :deep(.el-date-editor){width:100%}.minutes-create{margin-top:14px}.history-row{display:flex;gap:16px;font-size:13px}.history-row time{color:var(--oa-muted);flex-shrink:0}h2{font-size:17px;font-weight:600;margin:22px 0 14px}h2 .muted{font-size:13px;font-weight:400;margin-left:8px}
@media(max-width:600px){.page-heading,.list-tools{align-items:flex-start;flex-direction:column}.toolbar{gap:8px}.toolbar .el-button{margin-left:0}.meeting-facts,.form-columns{grid-template-columns:1fr}.meeting-search{max-width:none}.history-row{flex-wrap:wrap;gap:4px 12px}.meeting-list-row{padding:16px 0}.meeting-title small{line-height:1.7}.attendee-grid{grid-template-columns:1fr 1fr}}
</style>
<style>.meeting-form-dialog{max-width:calc(100vw - 24px);border-radius:6px}.meeting-form-dialog .el-select{width:100%}.meeting-form-dialog .el-dialog__body{max-height:70vh;overflow-y:auto}</style>
