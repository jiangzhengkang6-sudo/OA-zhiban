import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus, { ElMessageBox } from 'element-plus'
import MeetingManagementView from '@/views/MeetingManagementView.vue'
import { meetingEventsApi as api, type MeetingEvent } from '@/api/meetingEvents'
import { authState } from '@/stores/auth'

vi.mock('@/api/meetingEvents',()=>({meetingEventsApi:{list:vi.fn(),get:vi.fn(),options:vi.fn(),conflicts:vi.fn(),save:vi.fn(),command:vi.fn()}}))
const row:MeetingEvent={id:'event',title:'部门协调会',agenda:'讨论产品验收',starts_at:'2026-10-26T02:00:00Z',ends_at:'2026-10-26T03:00:00Z',
  organizer_id:'owner',host_id:'owner',recorder_id:'owner',location:'会议室',online_url:'',state:'DRAFT',revision:1,invitation_version:0,
  minutes_id:null,minutes_accessible:false,minutes_status:null,cancel_reason:'',video_enabled:false,available_actions:['edit','publish','cancel'],
  attendees:[{user_id:'owner',display_name:'发起人',response:'PENDING',note:'',replied_at:null}],history:[],deliveries:[]}
let wrapper:VueWrapper
beforeEach(()=>{
  vi.resetAllMocks();sessionStorage.clear()
  Object.assign(authState,{provider:'builtin',aiEnabled:true,user:{user_id:'owner',roles:[],depts:['product'],permissions:[
    {resource:'meeting',action:'read',scope:'self'},{resource:'meeting',action:'write',scope:'self'}]}})
  vi.mocked(api.list).mockResolvedValue([structuredClone(row)])
  vi.mocked(api.get).mockResolvedValue(structuredClone(row))
  vi.mocked(api.conflicts).mockResolvedValue([])
  vi.mocked(api.options).mockResolvedValue({users:[{id:'owner',display_name:'发起人',department_id:'product'},
    {id:'guest',display_name:'参会人',department_id:'qa'}],departments:[{id:'product',name:'产品部'},{id:'qa',name:'测试部'}]})
})
afterEach(()=>{wrapper?.unmount();vi.restoreAllMocks()})
const button=(name:string)=>wrapper.findAll('button').find(b=>b.text()===name)!
async function render(path='/meetings'){
  const router=createRouter({history:createMemoryHistory(),routes:[
    {path:'/meetings',component:MeetingManagementView},{path:'/meeting-events/:id',component:MeetingManagementView},
    {path:'/meetings/:meetingId',component:{template:'<div>纪要详情</div>'}},{path:'/meeting-texts',component:{template:'<div>会议文本</div>'}},
  ]})
  await router.push(path)
  wrapper=mount(MeetingManagementView,{attachTo:document.body,global:{plugins:[router,ElementPlus]}})
  await flushPromises();return router
}
it('keeps manual scheduling available with AI off and hides creation for readers',async()=>{
  authState.aiEnabled=false
  await render()
  expect(wrapper.text()).toContain('部门协调会')
  expect(button('发起会议')).toBeDefined()
  authState.user!.permissions=authState.user!.permissions.filter(p=>p.action==='read')
  await flushPromises()
  expect(button('发起会议')).toBeUndefined()
  expect(api.options).not.toHaveBeenCalled()
})
it('keeps manual video meetings available without mounting transcription when AI is disabled',async()=>{
  authState.aiEnabled=false
  vi.mocked(api.get).mockResolvedValue({...structuredClone(row),video_enabled:true,state:'IN_PROGRESS'})
  await render('/meeting-events/event')
  expect(wrapper.findComponent({name:'MeetingVideoRoom'}).exists()).toBe(true)
  expect(wrapper.findComponent({name:'MeetingTranscription'}).exists()).toBe(false)
})

it('preserves the mounted video room while refreshing the same meeting',async()=>{
  authState.aiEnabled=false
  const active={...structuredClone(row),video_enabled:true,state:'IN_PROGRESS' as const}
  vi.mocked(api.get).mockResolvedValue(active)
  await render('/meeting-events/event')
  const video=wrapper.findComponent({name:'MeetingVideoRoom'}).element
  let finish!: (value:MeetingEvent)=>void
  vi.mocked(api.get).mockReturnValueOnce(new Promise(resolve=>{finish=resolve}))
  await button('刷新').trigger('click');await flushPromises()
  expect(wrapper.findComponent({name:'MeetingVideoRoom'}).element).toBe(video)
  finish({...active,revision:2});await flushPromises()
  expect(wrapper.findComponent({name:'MeetingVideoRoom'}).element).toBe(video)
})
it('saves selected organization members and timezone-aware dates before navigating',async()=>{
  const router=await render()
  vi.mocked(api.save).mockResolvedValue({result:row,replayed:false})
  await button('发起会议').trigger('click');await flushPromises()
  const inputs=wrapper.findAllComponents({name:'ElInput'})
  inputs.find(x=>x.props('ariaLabel')==='会议主题')!.vm.$emit('update:modelValue',' 新会议 ')
  inputs.find(x=>x.props('ariaLabel')==='会议议题')!.vm.$emit('update:modelValue',' 讨论验收 ')
  inputs.find(x=>x.props('ariaLabel')==='会议地点')!.vm.$emit('update:modelValue',' 会议室一 ')
  const dates=wrapper.findAllComponents({name:'ElDatePicker'})
  dates[0]!.vm.$emit('update:modelValue',new Date('2026-10-26T02:00:00Z'))
  dates[1]!.vm.$emit('update:modelValue',new Date('2026-10-26T03:00:00Z'))
  const selects=wrapper.findAllComponents({name:'ElSelect'})
  selects[3]!.vm.$emit('update:modelValue',['guest'])
  selects[2]!.vm.$emit('update:modelValue','product')
  await flushPromises()
  expect(selects[3]!.findAllComponents({name:'ElOption'}).map(x=>x.props('value'))).toContain('guest')
  await button('保存草稿').trigger('click');await flushPromises()
  expect(api.save).toHaveBeenCalledWith(expect.objectContaining({title:'新会议',agenda:'讨论验收',location:'会议室一',
    attendee_ids:['guest'],host_id:'owner',starts_at:'2026-10-26T02:00:00.000Z',operation_id:expect.any(String)}),undefined)
  await vi.waitFor(()=>expect(router.currentRoute.value.path).toBe('/meeting-events/event'))
})
it('does not publish if the conflict warning is declined',async()=>{
  vi.mocked(api.conflicts).mockResolvedValue([{user_id:'guest',display_name:'参会人',count:2}])
  const confirm=vi.spyOn(ElMessageBox,'confirm').mockRejectedValue('cancel')
  await render('/meeting-events/event')
  await button('发送邀请').trigger('click');await flushPromises()
  expect(confirm).toHaveBeenCalledWith(expect.stringContaining('参会人（2 场）'),expect.any(String),expect.any(Object))
  expect(api.command).not.toHaveBeenCalled()
})
it('reuses the operation key after a lost reply response',async()=>{
  vi.mocked(api.get).mockResolvedValue({...row,state:'SCHEDULED',revision:3,invitation_version:2,available_actions:['reply']})
  vi.mocked(api.command).mockRejectedValueOnce(new Error('网络连接中断')).mockResolvedValueOnce({result:row,replayed:true})
  await render('/meeting-events/event')
  await button('提交反馈').trigger('click');await flushPromises()
  expect(wrapper.text()).toContain('网络连接中断')
  await button('提交反馈').trigger('click');await flushPromises()
  const calls=vi.mocked(api.command).mock.calls
  expect(calls).toHaveLength(2)
  expect(calls[0]![2]).toMatchObject({expected_revision:3,invitation_version:2,response:'ACCEPTED'})
  expect(calls[0]![2].operation_id).toBe(calls[1]![2].operation_id)
})
it('blocks saving when organization options fail and allows reloading them',async()=>{
  vi.mocked(api.options).mockRejectedValueOnce(new Error('unavailable')).mockResolvedValueOnce({users:[],departments:[]})
  await render();await button('发起会议').trigger('click');await flushPromises()
  expect(wrapper.text()).toContain('人员加载失败')
  expect(button('保存草稿').attributes('disabled')).toBeDefined()
  await button('重新加载人员').trigger('click');await flushPromises()
  expect(api.options).toHaveBeenCalledTimes(2)
  expect(wrapper.text()).not.toContain('人员加载失败')
})
it('offers an explicit opt-in for Tencent video meetings',async()=>{
  await render();await button('发起会议').trigger('click');await flushPromises()
  expect(wrapper.text()).toContain('启用腾讯视频会议')
  expect(wrapper.find('[aria-label="启用视频会议"]').exists()).toBe(true)
})
it('opens associated minutes using the existing minutes route',async()=>{
  vi.mocked(api.get).mockResolvedValue({...row,state:'ENDED',minutes_id:'MTG-1',minutes_accessible:true,minutes_status:'CONFIRMED',available_actions:[]})
  const router=await render('/meeting-events/event')
  await button('查看会议纪要').trigger('click');await flushPromises()
  expect(router.currentRoute.value.path).toBe('/meetings/MTG-1')
})
