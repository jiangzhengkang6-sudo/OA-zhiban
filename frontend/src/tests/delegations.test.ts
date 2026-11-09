import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { beforeEach, it, expect, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import OADelegationsView from '@/views/OADelegationsView.vue'
import OAApprovalsView from '@/views/OAApprovalsView.vue'
import { delegationApi, type Delegation } from '@/api/delegation'
import { oaApi } from '@/api/oa'
import { authState } from '@/stores/auth'

vi.mock('@/api/delegation',()=>({delegationApi:{list:vi.fn(),candidates:vi.fn(),create:vi.fn(),revoke:vi.fn()}}))
vi.mock('@/api/oa',()=>({oaApi:{approvals:vi.fn(),node:vi.fn(),decide:vi.fn()}}))
const row:Delegation={id:'delegation',delegator_id:'owner',delegate_id:'delegate',delegator_name:'委托成员',delegate_name:'受托成员',scene:'leave',
  starts_at:'2026-10-23T01:00:00Z',ends_at:'2026-10-24T01:00:00Z',revoked_at:null,reason:'出差期间委托',revision:1,state:'ACTIVE'}
beforeEach(()=>{
  vi.resetAllMocks()
  Object.assign(authState,{provider:'builtin',manualOA:true,aiEnabled:false,user:{user_id:'owner',depts:['dept'],roles:[],permissions:[
    {resource:'approval',action:'read',scope:'self'},{resource:'approval',action:'write',scope:'self'}]}})
  vi.mocked(delegationApi.list).mockResolvedValue([row,{...row,id:'incoming',delegator_id:'other',delegate_id:'owner',delegator_name:'另一委托人'}])
  vi.mocked(delegationApi.candidates).mockResolvedValue([{id:'delegate',name:'受托成员'}])
  vi.mocked(oaApi.approvals).mockResolvedValue([])
})
async function setup(component:any=OADelegationsView){
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/:pathMatch(.*)*',component:{template:'<div />'}}]})
  await router.push('/oa/delegations')
  const wrapper=mount(component,{attachTo:document.body,global:{plugins:[router,ElementPlus]}})
  await flushPromises()
  return wrapper
}
const button=(wrapper:any,text:string)=>wrapper.findAll('button').find((b:any)=>b.text()===text)!

it('separates incoming and outgoing records and uses Chinese statuses with AI disabled',async()=>{
  const wrapper=await setup()
  expect(wrapper.text()).toContain('受托成员')
  expect(wrapper.text()).toContain('生效中')
  expect(wrapper.text()).not.toContain('另一委托人')
  await wrapper.findComponent({name:'ElRadioGroup'}).vm.$emit('update:modelValue','incoming');await flushPromises()
  expect(wrapper.text()).toContain('另一委托人')
  expect(button(wrapper,'撤销')).toBeUndefined()
  wrapper.unmount()
})

it('read only users cannot create delegations or request candidates',async()=>{
  authState.user!.permissions=authState.user!.permissions.filter(p=>p.action==='read')
  const wrapper=await setup()
  expect(button(wrapper,'新建委托')).toBeUndefined()
  expect(delegationApi.candidates).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('shows the empty candidate reason and disables saving',async()=>{
  vi.mocked(delegationApi.candidates).mockResolvedValue([])
  const wrapper=await setup()
  await button(wrapper,'新建委托').trigger('click');await flushPromises()
  expect(document.body.textContent).toContain('当前没有同部门且具备审批读写资格的其他成员')
  expect(document.querySelector<HTMLButtonElement>('.delegation-dialog .el-button--primary')!.disabled).toBe(true)
  wrapper.unmount()
})

it('keeps input and operation id on a failed save, then reloads on success',async()=>{
  vi.mocked(delegationApi.create).mockRejectedValueOnce(new Error('暂时失败')).mockResolvedValueOnce({result:row,replayed:false} as any)
  const wrapper=await setup()
  await button(wrapper,'新建委托').trigger('click');await flushPromises()
  const dialog=wrapper.findComponent({name:'ElDialog'})
  const selects=dialog.findAllComponents({name:'ElSelect'})
  selects[0].vm.$emit('update:modelValue','delegate')
  await dialog.find('textarea').setValue('出差期间委托')
  await button(dialog,'保存委托').trigger('click');await flushPromises()
  expect(dialog.text()).toContain('暂时失败')
  expect((dialog.find('textarea').element as HTMLTextAreaElement).value).toBe('出差期间委托')
  await button(dialog,'保存委托').trigger('click');await flushPromises()
  const calls=vi.mocked(delegationApi.create).mock.calls
  expect(calls).toHaveLength(2)
  expect(calls[0][0].operation_id).toBe(calls[1][0].operation_id)
  expect(calls[0][0]).toMatchObject({scene:'leave',delegate_id:'delegate',reason:'出差期间委托'})
  expect(delegationApi.list).toHaveBeenCalledTimes(2)
  wrapper.unmount()
})

it('revocation uses the displayed revision after explicit confirmation',async()=>{
  const confirm=vi.spyOn(ElMessageBox,'confirm').mockResolvedValue('confirm' as Awaited<ReturnType<typeof ElMessageBox.confirm>>)
  vi.mocked(delegationApi.revoke).mockResolvedValue({result:{...row,state:'REVOKED',revision:2},replayed:false} as any)
  const wrapper=await setup()
  await button(wrapper,'撤销').trigger('click');await flushPromises()
  expect(confirm).toHaveBeenCalledOnce()
  expect(delegationApi.revoke).toHaveBeenCalledWith('delegation',expect.objectContaining({expected_revision:1,operation_id:expect.any(String)}))
  confirm.mockRestore();wrapper.unmount()
})

it('approval pending, detail and history retain the delegated label',async()=>{
  const approval={node_id:'node',business_no:'请假-1',submission_version:1,revision:1,state:'IN_REVIEW',seat_state:'PENDING',is_delegated:true}
  vi.mocked(oaApi.approvals).mockResolvedValue([approval])
  vi.mocked(oaApi.node).mockResolvedValue({...approval,attachments:[],allowed_actions:[]})
  const wrapper=await setup(OAApprovalsView)
  expect(wrapper.text()).toContain('代批')
  await button(wrapper,'办理').trigger('click');await flushPromises()
  expect(wrapper.get('.oa-section').text()).toContain('代批')
  vi.mocked(oaApi.approvals).mockResolvedValue([{...approval,seat_state:'APPROVED',decision_delegation_id:'delegation',is_delegated:false}])
  await wrapper.get('[data-testid="tab-done"]').trigger('click');await flushPromises()
  expect(wrapper.text()).toContain('代批')
  wrapper.unmount()
})
