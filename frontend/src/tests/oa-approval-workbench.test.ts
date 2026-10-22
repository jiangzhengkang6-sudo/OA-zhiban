import { mount,flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach,it,expect,vi } from 'vitest'
import View from '@/views/OAApprovalsView.vue'
import { oaApi } from '@/api/oa'
import { authState } from '@/stores/auth'
vi.mock('@/api/oa',()=>({oaApi:{approvals:vi.fn(),node:vi.fn(),decide:vi.fn(),download:vi.fn()}}))
beforeEach(()=>{
  vi.clearAllMocks()
  Object.assign(authState,{provider:'builtin',manualOA:true,user:{user_id:'a',display_name:'审批人',roles:[],depts:[],permissions:[{resource:'approval',action:'read',scope:'self'},{resource:'approval',action:'write',scope:'self'}]}})
  vi.mocked(oaApi.approvals).mockResolvedValue([{node_id:'n',business_no:'请假一',revision:3,state:'IN_REVIEW',seat_state:'PENDING',submission_version:1}] as any)
  vi.mocked(oaApi.node).mockResolvedValue({node_id:'n',business_no:'请假一',revision:3,state:'IN_REVIEW',fields:{leave_type:'年假',start_date:'2026-11-01',end_date:'2026-11-01',reason:'本轮材料'},attachments:[],allowed_actions:['approve','reject','return_for_correction'],approval_notes:[]} as any)
})
it('uses only current node context and requires structured corrections before returning',async()=>{
  vi.mocked(oaApi.decide).mockRejectedValue(new Error('权限已变化'))
  const wrapper=mount(View,{global:{plugins:[ElementPlus]}});await flushPromises()
  await wrapper.get('[data-testid="open-node"]').trigger('click');await flushPromises()
  expect(wrapper.get('[data-testid="decide-node"]').attributes('type')).toBe('button')
  expect(wrapper.text()).toContain('本轮材料');expect(wrapper.text()).not.toContain('余额')
  await wrapper.get('select[aria-label="审批决定"]').setValue('return_for_correction')
  await wrapper.get('textarea[aria-label="处理意见"]').setValue('补充原因')
  expect(wrapper.get('[data-testid="decide-node"]').attributes('disabled')).toBeDefined()
  await wrapper.get('input[value="reason"]').setValue(true)
  await wrapper.get('[data-testid="decide-node"]').trigger('click');await flushPromises()
  expect(oaApi.decide).toHaveBeenCalledWith('n',expect.objectContaining({expected_revision:3,action:'return_for_correction',corrections:['reason']}))
  expect(wrapper.text()).toContain('权限已变化')
  wrapper.unmount()
})
it('done and copied lists never load node materials',async()=>{
  const wrapper=mount(View,{global:{plugins:[ElementPlus]}});await flushPromises()
  await wrapper.get('[data-testid="tab-done"]').trigger('click');await flushPromises()
  expect(oaApi.approvals).toHaveBeenLastCalledWith('done')
  expect(wrapper.find('[data-testid="open-node"]').exists()).toBe(false)
  expect(oaApi.node).not.toHaveBeenCalled();wrapper.unmount()
})
it('报销审批展示金额和费用字段，退回只提供报销修正项',async()=>{
  vi.mocked(oaApi.node).mockResolvedValue({node_id:'n',business_no:'BX-001',scene:'reimbursement',revision:3,state:'IN_REVIEW',fields:{purpose:'差旅费用',expense_date:'2026-10-19',category:'交通',amount:'128.50',currency:'CNY',attachment_ids:[]},attachments:[],allowed_actions:['approve','return_for_correction']} as any)
  vi.mocked(oaApi.decide).mockResolvedValue({result:{}} as any)
  const wrapper=mount(View,{global:{plugins:[ElementPlus]}});await flushPromises()
  await wrapper.get('[data-testid="open-node"]').trigger('click');await flushPromises()
  expect(wrapper.text()).toContain('128.50')
  expect(wrapper.text()).toContain('差旅费用')
  expect(wrapper.text()).not.toContain('假种')
  await wrapper.get('select[aria-label="审批决定"]').setValue('return_for_correction')
  expect(wrapper.find('input[value="leave_type"]').exists()).toBe(false)
  await wrapper.get('input[value="amount"]').setValue(true)
  await wrapper.get('textarea[aria-label="处理意见"]').setValue('请核对金额')
  await wrapper.get('[data-testid="decide-node"]').trigger('click');await flushPromises()
  expect(oaApi.decide).toHaveBeenCalledWith('n',expect.objectContaining({corrections:['amount']}))
  wrapper.unmount()
})
