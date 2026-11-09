import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, it, expect, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import AnnouncementView from '@/views/AnnouncementView.vue'
import PendingWorkItems from '@/components/PendingWorkItems.vue'
import OAApprovalsView from '@/views/OAApprovalsView.vue'
import TaskCenterView from '@/views/TaskCenterView.vue'
import { departmentApi } from '@/api/department'
import { oaApi } from '@/api/oa'
import { taskApi } from '@/api'
import { authState, can } from '@/stores/auth'
import type { Announcement } from '@/types/department'

vi.mock('@/api/department', () => ({ departmentApi: { announcements:vi.fn(), announcement:vi.fn(),
  create:vi.fn(), save:vi.fn(), transition:vi.fn(), read:vi.fn(), pending:vi.fn() } }))
vi.mock('@/api/oa', () => ({ oaApi: { approvals:vi.fn(), node:vi.fn(), decide:vi.fn() } }))
vi.mock('@/api', () => ({ taskApi: { list:vi.fn() }, approvalApi:{} }))

const row = (id='first', body='部门维护安排'):Announcement => ({ id, title:'维护公告 '+id, body,
  state:'PUBLISHED', department_id:'dept', author_id:'author', revision:2, read_at:null,
  published_at:'2026-10-22T12:00:00Z', withdrawn_at:null, can_manage:false })
beforeEach(() => {
  vi.resetAllMocks()
  Object.assign(authState, { provider:'builtin', aiEnabled:true, manualOA:true, user:{ user_id:'reader',
    display_name:'阅读成员', roles:[], depts:['dept'], permissions:[{resource:'announcement',action:'read',scope:'self'}] } })
  vi.mocked(departmentApi.announcements).mockResolvedValue([row()])
  vi.mocked(departmentApi.announcement).mockResolvedValue(row())
  vi.mocked(departmentApi.pending).mockResolvedValue({items:[],total:0})
  vi.mocked(oaApi.approvals).mockResolvedValue([])
})
async function setup(component:any, location:string) {
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/:pathMatch(.*)*',component:{template:'<div />'}}]})
  await router.push(location)
  const wrapper=mount(component,{attachTo:document.body,global:{plugins:[router,ElementPlus]}})
  await flushPromises()
  return {router,wrapper}
}
function button(wrapper:any, text:string) { return wrapper.findAll('button').find((b:any)=>b.text()===text)! }

it('renders announcement text safely and only records a read after explicit confirmation',async()=>{
  vi.mocked(departmentApi.announcement).mockResolvedValue(row('first','<img src=x onerror=alert(1)>'))
  vi.mocked(departmentApi.read).mockResolvedValue({...row(),read_at:'2026-10-22T13:00:00Z'})
  const {wrapper}=await setup(AnnouncementView,'/oa/announcements?id=first')
  expect(wrapper.text()).toContain('<img src=x onerror=alert(1)>')
  expect(wrapper.find('img').exists()).toBe(false)
  expect(departmentApi.read).not.toHaveBeenCalled()
  expect(wrapper.text()).not.toContain('新建公告')
  await button(wrapper,'标为已读').trigger('click');await flushPromises()
  expect(departmentApi.read).toHaveBeenCalledWith('first')
  expect(button(wrapper,'标为已读')).toBeUndefined()
  wrapper.unmount()
})

it('late announcement requests and read receipts cannot overwrite a different open announcement',async()=>{
  let resolveRead!:(value:Announcement)=>void
  vi.mocked(departmentApi.read).mockReturnValue(new Promise(resolve=>{resolveRead=resolve}))
  const {wrapper,router}=await setup(AnnouncementView,'/oa/announcements?id=first')
  await button(wrapper,'标为已读').trigger('click')
  vi.mocked(departmentApi.announcement).mockResolvedValue(row('second','当前公告正文'))
  await router.push('/oa/announcements?id=second');await flushPromises()
  resolveRead({...row('first','过期阅读响应'),read_at:'2026-10-22T13:00:00Z'});await flushPromises()
  expect(wrapper.get('.announcement-body').text()).toBe('当前公告正文')
  vi.mocked(departmentApi.announcement).mockRejectedValue(new Error('withdrawn'))
  await router.push('/oa/announcements?id=withdrawn');await flushPromises()
  expect(wrapper.find('.announcement-body').exists()).toBe(false)
  expect(wrapper.text()).toContain('公告不存在、已撤回或无权查看')
  wrapper.unmount()
})

it('draft edit keeps the revision of the draft opened in the editor',async()=>{
  authState.user!.permissions.push({resource:'announcement',action:'write',scope:'department'})
  vi.mocked(departmentApi.announcement).mockResolvedValue({...row(),state:'DRAFT',revision:3,can_manage:true})
  vi.mocked(departmentApi.save).mockResolvedValue({result:{...row(),state:'DRAFT',revision:4},replayed:false} as any)
  const {wrapper,router}=await setup(AnnouncementView,'/oa/announcements?id=first')
  await button(wrapper,'编辑草稿').trigger('click');await flushPromises()
  vi.mocked(departmentApi.announcement).mockResolvedValue({...row('second'),revision:8})
  await router.push('/oa/announcements?id=second');await flushPromises()
  await button(wrapper,'保存草稿').trigger('click');await flushPromises()
  expect(departmentApi.save).toHaveBeenCalledWith('first',expect.objectContaining({expected_revision:3}))
  expect(departmentApi.create).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('pending items preserve their original destination and source filter',async()=>{
  vi.mocked(departmentApi.pending).mockResolvedValue({items:[{id:'approval:node',source:'approval',title:'请假审批',
    business_id:'LEAVE-1',state:'PENDING',due_at:null,href:'/oa/approvals?node_id=node'}],total:1})
  const {wrapper,router}=await setup(PendingWorkItems,'/tasks')
  expect(wrapper.text()).toContain('请假审批')
  await button(wrapper,'去处理').trigger('click');await flushPromises()
  expect(router.currentRoute.value.fullPath).toBe('/oa/approvals?node_id=node')
  await wrapper.findComponent({name:'ElSelect'}).vm.$emit('update:modelValue','work_task');await flushPromises()
  expect(departmentApi.pending).toHaveBeenLastCalledWith({source:'work_task',page:1,page_size:20})
  wrapper.unmount()
})

it('approval links open only a node in the current authorized pending list',async()=>{
  authState.user!.permissions.push({resource:'approval',action:'read',scope:'self'})
  vi.mocked(oaApi.approvals).mockResolvedValue([{node_id:'node',business_no:'LEAVE-1'}] as any)
  vi.mocked(oaApi.node).mockResolvedValue({node_id:'node',business_no:'LEAVE-1',attachments:[],allowed_actions:[]} as any)
  const {wrapper,router}=await setup(OAApprovalsView,'/oa/approvals?node_id=node')
  expect(oaApi.node).toHaveBeenCalledWith('node')
  vi.mocked(oaApi.node).mockClear()
  await router.push('/oa/approvals?node_id=unknown');await flushPromises()
  expect(oaApi.node).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('AI off permits manual pending items in task center without loading AI history',async()=>{
  authState.aiEnabled=false
  authState.user!.permissions.push({resource:'approval',action:'read',scope:'self'})
  expect(can('task')).toBe(true)
  const {wrapper}=await setup(TaskCenterView,'/tasks')
  expect(departmentApi.pending).toHaveBeenCalledOnce()
  expect(taskApi.list).not.toHaveBeenCalled()
  expect(wrapper.text()).not.toContain('智能任务记录')
  wrapper.unmount()
})
