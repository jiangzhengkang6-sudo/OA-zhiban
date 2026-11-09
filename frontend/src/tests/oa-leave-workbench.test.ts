import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createRouter, createMemoryHistory } from 'vue-router'
import { beforeEach, it, expect, vi } from 'vitest'
import View from '@/views/OALeavesView.vue'
import { oaApi } from '@/api/oa'
import { authState, can, routeResource, homePath } from '@/stores/auth'
vi.mock('@/api/oa', () => ({oaApi:{leaves:vi.fn(),leave:vi.fn(),workflows:vi.fn(),saveLeave:vi.fn(),createLeave:vi.fn(),submit:vi.fn(),withdraw:vi.fn(),archive:vi.fn(),upload:vi.fn()}}))
const row = {id:'leave-1',business_no:'请假一',applicant_id:'employee',workflow_definition_id:'wf',revision:2,submission_version:0,state:'DRAFT',fields:{leave_type:'年假',start_date:'2026-11-01',end_date:'2026-11-02',reason:'原事由',attachment_ids:[]},allowed_actions:['edit','submit','upload'],versions:[],attachments:[]}
beforeEach(() => {
  vi.clearAllMocks()
  Object.assign(authState, {provider:'builtin',aiEnabled:false,manualOA:true,user:{user_id:'employee',display_name:'员工',roles:[],depts:['dept'],permissions:[{resource:'leave',action:'read',scope:'self'},{resource:'leave',action:'write',scope:'self'}]}})
  vi.mocked(oaApi.leaves).mockResolvedValue([structuredClone(row)] as any)
  vi.mocked(oaApi.leave).mockResolvedValue(structuredClone(row) as any)
  vi.mocked(oaApi.workflows).mockResolvedValue([{id:'wf',name:'普通请假',published_version:1,form:{leave_types:['年假'],reason_max_length:2000}}] as any)
})
async function render(path='/oa/leaves/leave-1',wait=true) {
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/oa/leaves/:id?',component:View}]})
  await router.push(path);await router.isReady()
  const wrapper=mount({template:'<router-view />'},{global:{plugins:[router,ElementPlus]}})
  if(wait)await flushPromises();return wrapper
}
it('explains missing published workflows instead of showing blank dropdowns',async()=>{
  vi.mocked(oaApi.workflows).mockResolvedValue([])
  const wrapper=await render('/oa/leaves/new')
  expect(wrapper.text()).toContain('本部门暂无已发布的请假流程')
  expect(wrapper.text()).toContain('请联系本部门流程管理员')
  for(const label of ['请假流程','假种']){
    const select=wrapper.get(`select[aria-label="${label}"]`)
    expect(select.attributes('disabled')).toBeDefined()
    expect(select.findAll('option')).toHaveLength(1)
    expect(select.text()).toContain('暂无可用')
  }
  expect(wrapper.find('[data-testid="configure-leave-workflow"]').exists()).toBe(false)
  expect(wrapper.get('[data-testid="save-leave"]').attributes('disabled')).toBeDefined()
  wrapper.unmount()
})
it('offers configuration only to users with workflow read and write permission',async()=>{
  vi.mocked(oaApi.workflows).mockResolvedValue([])
  authState.user!.permissions.push({resource:'workflow',action:'read',scope:'department'},{resource:'workflow',action:'write',scope:'department'})
  const wrapper=await render('/oa/leaves/new')
  expect(wrapper.get('[data-testid="configure-leave-workflow"]').text()).toBe('配置流程')
  authState.user!.permissions=authState.user!.permissions.filter(p=>p.resource!=='workflow'||p.action!=='write')
  await flushPromises()
  expect(wrapper.find('[data-testid="configure-leave-workflow"]').exists()).toBe(false)
  wrapper.unmount()
})
it('shows loading separately from missing configuration',async()=>{
  let finish!:(value:any)=>void
  vi.mocked(oaApi.workflows).mockImplementation(()=>new Promise(resolve=>{finish=resolve}))
  const wrapper=await render('/oa/leaves/new',false)
  expect(wrapper.get('select[aria-label="请假流程"]').text()).toContain('正在加载')
  expect(wrapper.get('select[aria-label="请假流程"]').attributes('disabled')).toBeDefined()
  expect(wrapper.text()).not.toContain('本部门暂无已发布')
  finish([]);await flushPromises()
  expect(wrapper.text()).toContain('本部门暂无已发布')
  wrapper.unmount()
})
it('keeps load failures distinct and restores options on retry',async()=>{
  vi.mocked(oaApi.workflows).mockRejectedValueOnce(new Error('流程服务暂时不可用'))
  const wrapper=await render('/oa/leaves/new')
  expect(wrapper.text()).toContain('流程服务暂时不可用')
  expect(wrapper.get('select[aria-label="请假流程"]').text()).toContain('加载失败')
  expect(wrapper.text()).not.toContain('本部门暂无已发布')
  await wrapper.findAll('button').find(button=>button.text()==='刷新')!.trigger('click');await flushPromises()
  expect(wrapper.get('select[aria-label="请假流程"]').text()).toBe('普通请假')
  expect(wrapper.get('select[aria-label="请假流程"]').attributes('disabled')).toBeUndefined()
  expect(wrapper.get('select[aria-label="假种"]').text()).toBe('年假')
  wrapper.unmount()
})
it('updates leave types when the selected published workflow changes',async()=>{
  vi.mocked(oaApi.workflows).mockResolvedValue([
    {id:'annual',name:'年假流程',form:{leave_types:['annual']}},
    {id:'sick',name:'病假流程',form:{leave_types:['sick','事假']}},
  ] as any)
  const wrapper=await render('/oa/leaves/new')
  expect(wrapper.get('select[aria-label="假种"]').text()).toBe('年假')
  await wrapper.get('select[aria-label="请假流程"]').setValue('sick')
  expect(wrapper.get('select[aria-label="假种"]').findAll('option').map(option=>option.text())).toEqual(['病假','事假'])
  expect((wrapper.get('select[aria-label="假种"]').element as HTMLSelectElement).value).toBe('sick')
  wrapper.unmount()
})
it('updates the first draft after edits made while creation is pending',async()=>{
  let finishCreate!:(value:any)=>void
  vi.mocked(oaApi.createLeave).mockImplementation(()=>new Promise(resolve=>{finishCreate=resolve}))
  vi.mocked(oaApi.saveLeave).mockRejectedValue(new Error('保留第二次编辑'))
  const wrapper=await render('/oa/leaves/new')
  await wrapper.get('input[aria-label="开始日期"]').setValue('2026-11-01')
  await wrapper.get('input[aria-label="结束日期"]').setValue('2026-11-02')
  await wrapper.get('textarea').setValue('首次保存的事由')
  await wrapper.get('[data-testid="save-leave"]').trigger('click')
  await wrapper.get('textarea').setValue('请求期间继续编辑')
  finishCreate({result:structuredClone(row)});await flushPromises()
  expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('请求期间继续编辑')
  await wrapper.get('[data-testid="save-leave"]').trigger('click');await flushPromises()
  expect(oaApi.createLeave).toHaveBeenCalledTimes(1)
  expect(oaApi.saveLeave).toHaveBeenCalledWith('leave-1',expect.objectContaining({expected_revision:2,fields:expect.objectContaining({reason:'请求期间继续编辑'})}))
  expect(wrapper.find('select[aria-label="请假流程"]').exists()).toBe(false)
  wrapper.unmount()
})
it('failed save preserves edits and reuses the operation only for identical payloads',async()=>{
  vi.mocked(oaApi.saveLeave).mockRejectedValue(new Error('暂时失败'))
  const wrapper=await render()
  expect(wrapper.get('[data-testid="save-leave"]').attributes('type')).toBe('button')
  await wrapper.get('textarea[aria-label="请假事由"]').setValue('修改事由')
  expect(wrapper.get('[data-testid="submit-leave"]').attributes('disabled')).toBeDefined()
  await wrapper.get('[data-testid="save-leave"]').trigger('click');await flushPromises()
  await wrapper.get('[data-testid="save-leave"]').trigger('click');await flushPromises()
  const calls=vi.mocked(oaApi.saveLeave).mock.calls
  expect(calls).toHaveLength(2);expect(calls[0][1]).toEqual(calls[1][1])
  expect(calls[0][1]).toMatchObject({expected_revision:2,fields:{reason:'修改事由'}})
  expect(wrapper.get('textarea').element.value).toBe('修改事由')
  await wrapper.get('textarea').setValue('再次修改')
  await wrapper.get('[data-testid="save-leave"]').trigger('click');await flushPromises()
  expect(vi.mocked(oaApi.saveLeave).mock.calls[2][1].operation_id).not.toBe(calls[0][1].operation_id)
  wrapper.unmount()
})
it('permission revocation removes write actions and formal routes obey capabilities',async()=>{
  const wrapper=await render()
  authState.user!.permissions=authState.user!.permissions.filter(p=>p.action==='read')
  await flushPromises()
  expect(wrapper.find('[data-testid="save-leave"]').exists()).toBe(false)
  expect(routeResource('/oa/leaves/leave-1')).toBe('leave')
  expect(homePath()).toBe('/oa/leaves');expect(can('thread')).toBe(false)
  wrapper.unmount()
})
