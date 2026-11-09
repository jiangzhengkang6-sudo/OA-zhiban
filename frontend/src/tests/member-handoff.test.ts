import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, it, expect, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import MemberBatchDialog from '@/components/MemberBatchDialog.vue'
import MemberHandoffDialog from '@/components/MemberHandoffDialog.vue'
import { organizationApi, type Member, type HandoffItem, type MemberHandoff } from '@/api/organization'
import { authState } from '@/stores/auth'

vi.mock('@/api/organization',()=>({organizationApi:{batch:vi.fn(),handoff:vi.fn(),handoffCandidates:vi.fn(),transfer:vi.fn(),completeHandoff:vi.fn()}}))
const member:Member={id:'owner',username:'owner',display_name:'交接成员',status:'disabled',handoff_pending:true,version:7,department_id:'dept',position_id:null,manager_id:null,role_ids:['role']}
const item:HandoffItem={kind:'work_task',id:'task',revision:4,title:'月度工作',kind_name:'业务任务',link:'/work-tasks',can_transfer:true,blocked_reason:''}
const inventory=(overrides:Partial<MemberHandoff>={}):MemberHandoff=>({member,counts:{workflow:0,ticket:0,work_task:1,ticket_rule:0,reporting_line:0},total:1,items:[item],restricted_count:0,history:[],...overrides})
const organization={users:[member],departments:[],positions:[],roles:[],resources:[]}
beforeEach(()=>{
  vi.resetAllMocks()
  Object.assign(authState,{provider:'builtin',aiEnabled:true,user:{user_id:'admin',depts:['dept'],roles:[],permissions:[{resource:'organization',action:'read',scope:'department'},{resource:'organization',action:'write',scope:'department'}]}})
  vi.mocked(organizationApi.handoff).mockResolvedValue(inventory())
  vi.mocked(organizationApi.handoffCandidates).mockResolvedValue([{id:'receiver',name:'接收成员'}])
})
async function setup(component:any=MemberHandoffDialog,props:Record<string,unknown>={member}){
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/:pathMatch(.*)*',component:{template:'<div />'}}]})
  await router.push('/organization')
  const wrapper=mount(component,{props,attachTo:document.body,global:{plugins:[router,ElementPlus]}})
  await flushPromises()
  return wrapper
}
const button=(wrapper:any,text:string)=>wrapper.findAll('button').find((b:any)=>b.text()===text)!
const dialog=(wrapper:any)=>wrapper.findComponent({name:'ElDialog'})
async function batchSetup(){return setup(MemberBatchDialog,{modelValue:true,members:[member],organization})}
async function selectTask(wrapper:any){await button(dialog(wrapper),'选择接收人').trigger('click');await flushPromises()}

it('submits only selected batch fields and displayed member versions',async()=>{
  const wrapper=await batchSetup(),d=dialog(wrapper)
  d.findAllComponents({name:'ElCheckbox'})[0].vm.$emit('update:modelValue',true)
  await d.get('textarea').setValue('  离职停用  ')
  await button(d,'确认批量调整').trigger('click');await flushPromises()
  await vi.waitFor(()=>expect(organizationApi.batch).toHaveBeenCalledWith({operation_id:expect.any(String),members:[{user_id:'owner',expected_version:7}],changes:{status:'disabled'},reason:'离职停用'}))
  await vi.waitFor(()=>expect(wrapper.emitted('saved')).toHaveLength(1))
  wrapper.unmount()
})

it('requires an explicit batch change and reason before sending',async()=>{
  const wrapper=await batchSetup(),d=dialog(wrapper)
  await button(d,'确认批量调整').trigger('click');await flushPromises()
  expect(d.text()).toContain('请选择调整项并填写调整原因')
  expect(organizationApi.batch).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('preserves batch input and retry identity but uses a new key for changed content',async()=>{
  vi.mocked(organizationApi.batch).mockRejectedValue(new Error('暂时失败'))
  const wrapper=await batchSetup(),d=dialog(wrapper)
  d.findAllComponents({name:'ElCheckbox'})[4].vm.$emit('update:modelValue',true)
  await d.get('textarea').setValue('移除角色')
  for(let i=0;i<2;i++){
    await button(d,'确认批量调整').trigger('click')
    await vi.waitFor(()=>{
      expect(organizationApi.batch).toHaveBeenCalledTimes(i+1)
      expect(d.text()).toContain('暂时失败')
    })
  }
  expect(d.text()).toContain('暂时失败')
  const calls=vi.mocked(organizationApi.batch).mock.calls as any[]
  expect(calls[0][0].changes).toEqual({role_ids:[]})
  expect(calls[0][0].operation_id).toBe(calls[1][0].operation_id)
  await d.get('textarea').setValue('调整原因已修改')
  await button(d,'确认批量调整').trigger('click');await flushPromises()
  await vi.waitFor(()=>expect(organizationApi.batch).toHaveBeenCalledTimes(3))
  expect(calls[2][0].operation_id).not.toBe(calls[1][0].operation_id)
  wrapper.unmount()
})

it('loads an initially selected member and keeps hidden work blocking completion',async()=>{
  vi.mocked(organizationApi.handoff).mockResolvedValue(inventory({items:[],restricted_count:1}))
  const wrapper=await setup(),d=dialog(wrapper)
  expect(organizationApi.handoff).toHaveBeenCalledWith('owner')
  expect(d.text()).toContain('另有 1 项需要相应业务管理员处理')
  await d.get('[aria-label="交接确认说明"]').setValue('确认')
  expect((button(d,'确认交接完成').element as HTMLButtonElement).disabled).toBe(true)
  expect(organizationApi.completeHandoff).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('explains unavailable recipients and disables transfer',async()=>{
  vi.mocked(organizationApi.handoffCandidates).mockResolvedValue([])
  const wrapper=await setup();await selectTask(wrapper)
  const d=dialog(wrapper)
  expect(d.text()).toContain('当前没有符合条件的接收人')
  expect((button(d,'确认转交').element as HTMLButtonElement).disabled).toBe(true)
  wrapper.unmount()
})

it('requires task confirmation and transfers with both displayed revisions',async()=>{
  const wrapper=await setup();await selectTask(wrapper)
  const d=dialog(wrapper)
  d.findComponent({name:'ElSelect'}).vm.$emit('update:modelValue','receiver')
  await d.get('textarea').setValue('岗位交接')
  expect((button(d,'确认转交').element as HTMLButtonElement).disabled).toBe(true)
  d.findComponent({name:'ElCheckbox'}).vm.$emit('update:modelValue',true);await flushPromises()
  await button(d,'确认转交').trigger('click');await flushPromises()
  expect(organizationApi.transfer).toHaveBeenCalledWith('owner',{operation_id:expect.any(String),expected_version:7,kind:'work_task',item_id:'task',expected_revision:4,target_user_id:'receiver',reason:'岗位交接',risk_acknowledged:true})
  await vi.waitFor(()=>expect(wrapper.emitted('changed')).toHaveLength(1))
  expect(organizationApi.handoff).toHaveBeenCalledTimes(2)
  wrapper.unmount()
})

it('read only members have no transfer or signoff controls',async()=>{
  authState.user!.permissions=authState.user!.permissions.filter(p=>p.action==='read')
  const wrapper=await setup(),d=dialog(wrapper)
  expect(button(d,'选择接收人')).toBeUndefined()
  expect(button(d,'确认交接完成')).toBeUndefined()
  expect(organizationApi.handoffCandidates).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('ignores candidate responses for the previous member',async()=>{
  let resolve!:(value:{id:string;name:string}[])=>void
  vi.mocked(organizationApi.handoffCandidates).mockReturnValueOnce(new Promise(r=>resolve=r))
  const wrapper=await setup()
  await button(dialog(wrapper),'选择接收人').trigger('click')
  await wrapper.setProps({member:{...member,id:'new-owner'}});await flushPromises()
  resolve([{id:'old-target',name:'旧请求接收人'}]);await flushPromises()
  expect(dialog(wrapper).text()).not.toContain('旧请求接收人')
  expect(dialog(wrapper).find('.handoff-form').exists()).toBe(false)
  wrapper.unmount()
})

it('only confirms an empty inventory with a reason and supports an unchanged retry',async()=>{
  vi.mocked(organizationApi.handoff).mockResolvedValue(inventory({items:[],total:0}))
  vi.mocked(organizationApi.completeHandoff).mockRejectedValueOnce(new Error('确认失败')).mockResolvedValueOnce({...member,handoff_pending:false,version:8})
  const wrapper=await setup(),d=dialog(wrapper)
  expect((button(d,'确认交接完成').element as HTMLButtonElement).disabled).toBe(true)
  await d.get('[aria-label="交接确认说明"]').setValue('已逐项核对')
  for(let i=0;i<2;i++){await button(d,'确认交接完成').trigger('click');await flushPromises()}
  const calls=vi.mocked(organizationApi.completeHandoff).mock.calls as any[]
  expect(calls[0][1]).toEqual({operation_id:expect.any(String),expected_version:7,reason:'已逐项核对'})
  expect(calls[0][1].operation_id).toBe(calls[1][1].operation_id)
  await vi.waitFor(()=>expect(wrapper.emitted('changed')).toHaveLength(1))
  wrapper.unmount()
})
