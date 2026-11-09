import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, it, expect, vi } from 'vitest'
import OperationalAlertsView from '@/views/OperationalAlertsView.vue'
import { organizationApi, type OperationalSnapshot } from '@/api/organization'

vi.mock('@/api/organization',()=>({organizationApi:{alerts:vi.fn()}}))
const snapshot = (changes:Partial<OperationalSnapshot>={}):OperationalSnapshot => ({state:'running',checked_at:'2026-10-23T03:00:00Z',delivery_enabled:false,channels:[],
  checks:[{key:'database',name:'数据库',status:'PASS',message:'检查通过'},{key:'text_model',name:'主文字模型',status:'WARN',message:'未启用主动探测'}],incidents:[],...changes})
let wrapper:ReturnType<typeof mount>|undefined
beforeEach(()=>{vi.useFakeTimers();vi.resetAllMocks();vi.mocked(organizationApi.alerts).mockResolvedValue(snapshot())})
afterEach(()=>{wrapper?.unmount();wrapper=undefined;vi.useRealTimers()})
async function setup(){wrapper=mount(OperationalAlertsView,{global:{plugins:[ElementPlus]}});await flushPromises();return wrapper}

it('shows checked and unprobed states in Chinese with opt-in disabled',async()=>{
  const view=await setup()
  expect(view.text()).toContain('巡检运行中')
  expect(view.text()).toContain('未启用主动探测')
  expect(view.text()).toContain('外部告警通知尚未启用')
  expect(view.text()).not.toContain('PASS')
})
it.each(['stale','invalid','unconfigured'] as const)('does not present %s as healthy',async(state)=>{
  vi.mocked(organizationApi.alerts).mockResolvedValue(snapshot({state}))
  const view=await setup()
  expect(view.text()).toContain({stale:'巡检已中断',invalid:'巡检记录不可用',unconfigured:'尚未启动巡检'}[state])
})
it('separates active faults from recovery and translates transport outcomes',async()=>{
  const base={id:'first',key:'backup',name:'备份任务',message:'最近一次备份失败',opened_at:'2026-10-23T02:00:00Z',last_seen_at:'2026-10-23T03:00:00Z',resolved_at:null,deliveries:{'failure:smtp':{status:'UNKNOWN',attempted_at:'2026-10-23T02:00:00Z',attempt_count:1}}}
  vi.mocked(organizationApi.alerts).mockResolvedValue(snapshot({incidents:[base,{...base,id:'second',name:'数据库',resolved_at:'2026-10-23T03:00:00Z',deliveries:{'recovery:wecom':{status:'ACCEPTED',attempted_at:'2026-10-23T03:00:00Z',attempt_count:1}}}]}))
  const view=await setup()
  expect(view.text()).toContain('未恢复 1 项')
  const sections=view.findAll('section')
  expect(sections[1].text()).toContain('邮件故障：结果待核对')
  expect(sections[2].text()).toContain('企业微信恢复：服务已受理')
  expect(sections[2].text()).not.toContain('最近一次备份失败')
})
it('keeps prior data with an error when refresh fails and allows retry',async()=>{
  const view=await setup()
  vi.mocked(organizationApi.alerts).mockRejectedValueOnce(new Error('private server data'))
  await view.get('[aria-label="刷新运行告警"]').trigger('click');await flushPromises()
  expect(view.text()).toContain('读取失败')
  expect(view.text()).toContain('数据库')
  expect(view.text()).not.toContain('private server data')
  await view.get('[aria-label="刷新运行告警"]').trigger('click');await flushPromises()
  expect(view.text()).not.toContain('读取失败')
})
it('warns when opted in without any configured channel',async()=>{
  vi.mocked(organizationApi.alerts).mockResolvedValue(snapshot({delivery_enabled:true}))
  expect((await setup()).text()).toContain('没有可用的通知渠道')
})
it('avoids overlapping reads and stops polling after leaving',async()=>{
  let release!:(value:OperationalSnapshot)=>void
  vi.mocked(organizationApi.alerts).mockReturnValue(new Promise(resolve=>{release=resolve}))
  const view=await setup()
  await vi.advanceTimersByTimeAsync(60000)
  expect(organizationApi.alerts).toHaveBeenCalledTimes(1)
  view.unmount();wrapper=undefined
  release(snapshot());await flushPromises()
  await vi.advanceTimersByTimeAsync(60000)
  expect(organizationApi.alerts).toHaveBeenCalledTimes(1)
})
