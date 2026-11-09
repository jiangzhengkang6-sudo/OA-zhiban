import { beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import View from '@/views/OABalancesView.vue'
import { oaApi } from '@/api/oa'
import { authState } from '@/stores/auth'
vi.mock('@/api/oa',()=>({oaApi:{options:vi.fn(),balances:vi.fn(),adjust:vi.fn()}}))
beforeEach(()=>{
  vi.clearAllMocks()
  Object.assign(authState,{provider:'builtin',manualOA:true,user:{user_id:'admin',display_name:'张翔',roles:[],depts:['operations'],permissions:[{resource:'leave_balance',action:'read',scope:'department'},{resource:'leave_balance',action:'write',scope:'department'}]}})
  vi.mocked(oaApi.options).mockResolvedValue({users:[{id:'admin',name:'张翔'},{id:'legal',name:'郑晓华'}],departments:[],roles:[]})
  vi.mocked(oaApi.balances).mockResolvedValue([])
})
it('loads balance-specific manageable members and queries the selected member',async()=>{
  const wrapper=mount(View,{global:{plugins:[ElementPlus]}})
  await flushPromises()
  expect(oaApi.options).toHaveBeenCalledWith('leave_balance','write')
  await wrapper.get('[data-testid=adjust-balance]').trigger('click');await flushPromises()
  const selectors=wrapper.findAllComponents({name:'ElSelect'})
  const person=selectors[1]!
  expect(person.findAllComponents({name:'ElOption'}).map(option=>option.props('label'))).toEqual(['张翔','郑晓华'])
  person.vm.$emit('update:modelValue','legal');await flushPromises()
  expect(oaApi.balances).toHaveBeenLastCalledWith('legal')
  wrapper.unmount()
})

it('uses a Chinese leave selector and preserves the revision of an existing label account',async()=>{
  vi.mocked(oaApi.balances).mockResolvedValue([{id:'balance',user_id:'admin',leave_type:'年假',year:new Date().getFullYear(),total:7,used:0,reserved:0,available:7,revision:3}])
  vi.mocked(oaApi.adjust).mockResolvedValue({result:{}} as any)
  const wrapper=mount(View,{global:{plugins:[ElementPlus]}})
  await flushPromises()
  await wrapper.get('[data-testid=adjust-balance]').trigger('click');await flushPromises()
  const kind=wrapper.findAllComponents({name:'ElSelect'}).find(select=>select.props('ariaLabel')==='额度假种')
  expect(kind).toBeDefined()
  expect(kind!.findAllComponents({name:'ElOption'}).map(option=>option.props('label'))).toContain('年假')
  expect(wrapper.get('[aria-label="总天数"]').element).toHaveProperty('value','7')
  await wrapper.get('[aria-label="调整原因"]').setValue('核对额度')
  await wrapper.get('[data-testid=save-balance]').trigger('click');await flushPromises()
  expect(oaApi.adjust).toHaveBeenCalledWith(expect.objectContaining({leave_type:'annual',expected_revision:3,total:7}))
  wrapper.unmount()
})
