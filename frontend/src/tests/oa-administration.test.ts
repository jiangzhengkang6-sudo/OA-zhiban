import { mount,flushPromises } from '@vue/test-utils'
import ElementPlus, { ElSelect } from 'element-plus'
import { beforeEach,it,expect,vi } from 'vitest'
import Workflow from '@/views/OAWorkflowView.vue'
import Balances from '@/views/OABalancesView.vue'
import Administration from '@/views/OAAdministrationView.vue'
import { oaApi } from '@/api/oa'
import { authState } from '@/stores/auth'
vi.mock('@/api/oa',()=>({oaApi:{options:vi.fn(),workflows:vi.fn(),saveWorkflow:vi.fn(),publish:vi.fn(),balances:vi.fn(),adjust:vi.fn(),instances:vi.fn(),reconcile:vi.fn(),candidates:vi.fn(),transfer:vi.fn(),resume:vi.fn()}}))
beforeEach(()=>{
  vi.clearAllMocks()
  Object.assign(authState,{provider:'builtin',manualOA:true,user:{user_id:'admin',depts:['dept'],permissions:['workflow','leave_balance','workflow_admin'].flatMap(resource=>['read','write'].map(action=>({resource,action,scope:'department'})))}})
  vi.mocked(oaApi.options).mockResolvedValue({departments:[{id:'dept',name:'研发部'}],users:[{id:'admin',name:'管理员'}],roles:[]} as any)
  vi.mocked(oaApi.workflows).mockResolvedValue([])
  vi.mocked(oaApi.instances).mockResolvedValue([])
  vi.mocked(oaApi.balances).mockResolvedValue([])
  vi.mocked(oaApi.reconcile).mockResolvedValue({ok:true,checked:0,read_only:true,issues:[]})
})
it('builds a structured workflow and retains failed command for retry',async()=>{
  vi.mocked(oaApi.saveWorkflow).mockRejectedValue(new Error('流程版本冲突'))
  const wrapper=mount(Workflow,{global:{plugins:[ElementPlus]}});await flushPromises()
  await wrapper.get('[data-testid="new-workflow"]').trigger('click')
  await wrapper.get('input[aria-label="流程名称"]').setValue('研发请假')
  await wrapper.get('[data-testid="save-workflow"]').trigger('click');await flushPromises()
  expect(oaApi.saveWorkflow).toHaveBeenCalledWith(expect.objectContaining({definition:expect.objectContaining({schema_version:1,nodes:expect.arrayContaining([expect.objectContaining({kind:'approval',selector:{kind:'manager',levels:1}})])})}),undefined)
  expect(wrapper.find('textarea').exists()).toBe(false)
  expect(wrapper.text()).toContain('流程版本冲突');wrapper.unmount()
})
it('retries the identical workflow command with the same operation key',async()=>{
  vi.mocked(oaApi.saveWorkflow).mockRejectedValue(new Error('网络中断'))
  const wrapper=mount(Workflow,{global:{plugins:[ElementPlus]}});await flushPromises()
  await wrapper.get('[data-testid="new-workflow"]').trigger('click')
  await wrapper.get('input[aria-label="流程名称"]').setValue('重试流程')
  await wrapper.get('[data-testid="save-workflow"]').trigger('click');await flushPromises()
  await wrapper.get('[data-testid="save-workflow"]').trigger('click');await flushPromises()
  const calls=vi.mocked(oaApi.saveWorkflow).mock.calls
  expect(calls).toHaveLength(2);expect(calls[0][0]).toEqual(calls[1][0]);wrapper.unmount()
})
it('locks an existing workflow department while allowing a new workflow department to be selected',async()=>{
  vi.mocked(oaApi.options).mockResolvedValue({departments:[{id:'dept',name:'研发部'},{id:'product',name:'产品部'}],users:[],roles:[]} as any)
  vi.mocked(oaApi.workflows).mockResolvedValue([{id:'wf',name:'研发请假',code:'leave_dev',department_id:'dept',revision:1,definition:{schema_version:1,scene:'leave',entry_id:'review',form:{leave_types:['annual'],reason_max_length:2000},rules:{timeout_hours:48,required_attachments:[],calendar:'inclusive_days'},nodes:[{id:'review',kind:'approval',mode:'single',selector:{kind:'manager',levels:1},next_id:'end'},{id:'end',kind:'end'}]}}] as any)
  vi.mocked(oaApi.saveWorkflow).mockRejectedValue(new Error('保留编辑'))
  const wrapper=mount(Workflow,{global:{plugins:[ElementPlus]}});await flushPromises()
  expect(wrapper.get('[aria-label="适用部门"]').attributes('disabled')).toBeDefined()
  expect(wrapper.getComponent(ElSelect).props('modelValue')).toBe('dept')
  await wrapper.get('[data-testid="new-workflow"]').trigger('click');await flushPromises()
  expect(wrapper.get('[aria-label="适用部门"]').attributes('disabled')).toBeUndefined()
  const department=wrapper.getComponent(ElSelect)
  department.vm.$emit('update:modelValue','product');department.vm.$emit('change','product')
  await wrapper.get('input[aria-label="流程名称"]').setValue('产品请假')
  await wrapper.get('[data-testid="save-workflow"]').trigger('click');await flushPromises()
  expect(oaApi.saveWorkflow).toHaveBeenCalledWith(expect.objectContaining({department_id:'product',name:'产品请假'}),undefined)
  wrapper.unmount()
})
it('loads reactive definitions without losing entry, rules or branch and cc nodes',async()=>{
  const definition={schema_version:1,scene:'leave',entry_id:'choice',form:{leave_types:['annual'],reason_max_length:1234},rules:{timeout_hours:24,required_attachments:['annual'],calendar:'inclusive_days'},nodes:[
    {id:'review',kind:'approval',mode:'single',selector:{kind:'users',user_ids:['admin']},next_id:'copy'},
    {id:'choice',kind:'branch',cases:[{field:'days',op:'gt',value:3,next_id:'review'}],default_next_id:'review'},
    {id:'copy',kind:'cc',selector:{kind:'users',user_ids:['admin']},next_id:'end'}, {id:'end',kind:'end'}]}
  vi.mocked(oaApi.workflows).mockResolvedValue([{id:'wf',name:'原流程',code:'original',department_id:'dept',revision:4,definition}] as any)
  vi.mocked(oaApi.saveWorkflow).mockRejectedValue(new Error('保留编辑'))
  const wrapper=mount(Workflow,{global:{plugins:[ElementPlus]}});await flushPromises()
  expect((wrapper.get('input[aria-label="流程名称"]').element as HTMLInputElement).value).toBe('原流程')
  await wrapper.get('[data-testid="save-workflow"]').trigger('click');await flushPromises()
  expect(oaApi.saveWorkflow).toHaveBeenCalledWith(expect.objectContaining({definition}), 'wf')
  expect(wrapper.text()).toContain('条件分支');expect(wrapper.text()).toContain('抄送');wrapper.unmount()
})
it('explicitly initializes a balance and never grants read-only users write controls',async()=>{
  const wrapper=mount(Balances,{global:{plugins:[ElementPlus]}});await flushPromises()
  await wrapper.get('[data-testid="adjust-balance"]').trigger('click')
  await wrapper.get('input[aria-label="额度假种"]').setValue('年假')
  await wrapper.get('input[aria-label="调整原因"]').setValue('年度初始化')
  await wrapper.get('[data-testid="save-balance"]').trigger('click');await flushPromises()
  expect(oaApi.adjust).toHaveBeenCalledWith(expect.objectContaining({user_id:'admin',expected_revision:0,reason:'年度初始化'}))
  authState.user!.permissions=authState.user!.permissions.filter(p=>p.action==='read');await flushPromises()
  expect(wrapper.find('[data-testid="adjust-balance"]').exists()).toBe(false);wrapper.unmount()
})
it('does not fetch management data without permission',async()=>{
  authState.user!.permissions=[]
  const wrapper=mount(Administration,{global:{plugins:[ElementPlus]}});await flushPromises()
  expect(oaApi.instances).not.toHaveBeenCalled();expect(oaApi.reconcile).not.toHaveBeenCalled()
  expect(wrapper.text()).toContain('没有');wrapper.unmount()
})
it('loads the adjustment target balance before using its revision and retries unchanged',async()=>{
  vi.mocked(oaApi.balances).mockImplementation(async id=>id==='admin'?[{user_id:'admin',leave_type:'annual',year:new Date().getFullYear(),revision:7,total:20}] as any:[])
  vi.mocked(oaApi.adjust).mockRejectedValue(new Error('请求中断'))
  const wrapper=mount(Balances,{global:{plugins:[ElementPlus]}});await flushPromises()
  await wrapper.get('[data-testid="adjust-balance"]').trigger('click');await flushPromises()
  await wrapper.get('input[aria-label="调整原因"]').setValue('修正年度额度')
  await wrapper.get('[data-testid="save-balance"]').trigger('click');await flushPromises()
  await wrapper.get('[data-testid="save-balance"]').trigger('click');await flushPromises()
  const calls=vi.mocked(oaApi.adjust).mock.calls
  expect(calls[0][0]).toMatchObject({expected_revision:7})
  expect(calls[0][0]).toEqual(calls[1][0]);wrapper.unmount()
})
it('disables balance saving until the target revision has loaded',async()=>{
  let finishTarget!:(value:any)=>void
  vi.mocked(oaApi.balances).mockImplementation(id=>id?new Promise(resolve=>{finishTarget=resolve}):Promise.resolve([]))
  const wrapper=mount(Balances,{global:{plugins:[ElementPlus]}});await flushPromises()
  await wrapper.get('[data-testid="adjust-balance"]').trigger('click')
  await wrapper.get('input[aria-label="调整原因"]').setValue('年度初始化')
  expect(wrapper.get('[data-testid="save-balance"]').attributes('disabled')).toBeDefined()
  expect(oaApi.adjust).not.toHaveBeenCalled()
  finishTarget([]);await flushPromises()
  expect(wrapper.get('[data-testid="save-balance"]').attributes('disabled')).toBeUndefined()
  wrapper.unmount()
})
it('clears stale transfer selections and hides commands on completed seats',async()=>{
  const instance=(id:string,state='IN_REVIEW')=>({instance_id:id,business_no:id,state,revision:9,route_revision:1,nodes:[{id:'node-'+id,ordinal:0,kind:'approval',state:state==='IN_REVIEW'?'ACTIVE':'COMPLETED',revision:3,seats:[{id:'seat-'+id,state:state==='IN_REVIEW'?'PENDING':'APPROVED',effective_user_id:'admin',original_user_id:'admin',substituted:false}]}]})
  vi.mocked(oaApi.instances).mockResolvedValue([instance('first'),instance('second','APPROVED')] as any)
  vi.mocked(oaApi.candidates).mockResolvedValue([{id:'admin',name:'管理员'}])
  const wrapper=mount(Administration,{global:{plugins:[ElementPlus]}});await flushPromises()
  await wrapper.findAll('tbody tr')[0].trigger('click');await flushPromises()
  expect(wrapper.text()).toContain('转交')
  expect(wrapper.text()).not.toContain('恢复暂停流程')
  await wrapper.get('input[aria-label="操作理由"]').setValue('第一笔的原因')
  await wrapper.findAll('tbody tr')[1].trigger('click');await flushPromises()
  expect(wrapper.text()).not.toContain('转交')
  expect(wrapper.find('input[aria-label="操作理由"]').exists()).toBe(false)
  wrapper.unmount()
})
