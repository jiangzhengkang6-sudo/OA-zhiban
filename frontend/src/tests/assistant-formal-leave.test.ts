import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import AssistantView from '@/views/AssistantView.vue'
import { interruptApi, threadApi } from '@/api'
import { authState } from '@/stores/auth'

vi.mock('@/api', () => ({
  threadApi: { get: vi.fn(), create: vi.fn(), sendMessage: vi.fn() },
  interruptApi: { resume: vi.fn() }, ticketApi: { updateDraft: vi.fn() },
}))
const review = () => ({
  thread_id: 'thread-1', scene: 'leave', business_id: 'leave-1', status: 'WAITING_HUMAN',
  current_interrupt_id: 'interrupt-1', messages: [], approval_status: 'DRAFT',
  form_snapshot: { business_no: 'LV-001', leave_type: 'annual', start_date: '2026-10-20',
    end_date: '2026-10-21', reason: '家庭事务', revision: 1 },
})
const button = (wrapper: any, text: string) => wrapper.findAll('button').find((item: any) => item.text() === text)!
async function render(value: any = review()) {
  vi.mocked(threadApi.get).mockResolvedValue(value)
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/assistant/:threadId?', component: AssistantView },
    { path: '/oa/leaves/:id?', component: { template: '<div />' } },
    { path: '/leaves/new', component: { template: '<div />' } },
  ] })
  await router.push('/assistant/thread-1')
  const wrapper = mount(AssistantView, { global: { plugins: [router, createPinia(), ElementPlus] } })
  await flushPromises()
  return { wrapper, router }
}
beforeEach(() => {
  vi.resetAllMocks()
  Object.assign(authState, { provider: 'builtin', manualOA: true, aiEnabled: true })
  vi.mocked(interruptApi.resume).mockResolvedValue({ status: 'COMPLETED', trace_id: 'test' })
})
describe('正式请假助手', () => {
  it('展示正式草稿并阻止待确认会话继续发送，连续确认只提交一次', async () => {
    const { wrapper } = await render()
    expect(wrapper.text()).toContain('家庭事务')
    expect(wrapper.text()).toContain('年假')
    expect(wrapper.text()).toContain('2026-10-20')
    expect(button(wrapper, '发送').attributes('disabled')).toBeDefined()
    let release!: (value: any) => void
    vi.mocked(interruptApi.resume).mockImplementation(() => new Promise(resolve => { release = resolve }))
    await button(wrapper, '确认提交请假').trigger('click')
    await button(wrapper, '确认提交请假').trigger('click')
    expect(interruptApi.resume).toHaveBeenCalledTimes(1)
    expect(interruptApi.resume).toHaveBeenCalledWith('interrupt-1', expect.objectContaining({ action: 'confirm' }))
    release({ status: 'COMPLETED', trace_id: 'test' })
    await flushPromises()
    wrapper.unmount()
  })
  it('在正式工作台编辑草稿，通过当前中断刷新审核内容', async () => {
    const { wrapper, router } = await render()
    await button(wrapper, '刷新审核内容').trigger('click')
    await flushPromises()
    expect(interruptApi.resume).toHaveBeenCalledWith('interrupt-1', expect.objectContaining({ action: 'edit' }))
    expect(vi.mocked(interruptApi.resume).mock.calls[0]![1]).not.toHaveProperty('edited_data')
    await button(wrapper, '打开请假单').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/oa/leaves/leave-1')
    wrapper.unmount()
  })
  it('恢复只发送对账动作，已保存决定不再显示提交按钮', async () => {
    const { wrapper } = await render({ ...review(), error: { code: 'GRAPH_RECOVERY', msg: '业务决定已保存' } })
    expect(button(wrapper, '确认提交请假')).toBeUndefined()
    await button(wrapper, '恢复处理').trigger('click')
    await flushPromises()
    expect(interruptApi.resume).toHaveBeenCalledWith('interrupt-1', { action: 'reconcile' })
    wrapper.unmount()
  })
  it('提交失败保留错误并允许重试相同决定，取消不附带草稿', async () => {
    const { wrapper } = await render()
    vi.mocked(interruptApi.resume).mockRejectedValueOnce(new Error('内容已变化'))
    await button(wrapper, '确认提交请假').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('内容已变化')
    await button(wrapper, '确认提交请假').trigger('click')
    await flushPromises()
    expect(vi.mocked(interruptApi.resume).mock.calls[1]).toEqual(vi.mocked(interruptApi.resume).mock.calls[0])
    await button(wrapper, '取消本次提交').trigger('click')
    await flushPromises()
    expect(interruptApi.resume).toHaveBeenLastCalledWith('interrupt-1', expect.objectContaining({ action: 'cancel' }))
    wrapper.unmount()
  })
  it('已结束会话不显示提交操作且不能追加消息', async () => {
    const { wrapper } = await render({ ...review(), status: 'COMPLETED', current_interrupt_id: null, approval_status: 'IN_REVIEW' })
    expect(button(wrapper, '确认提交请假')).toBeUndefined()
    expect(wrapper.text()).toContain('审批中')
    expect(button(wrapper, '发送').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })
  it.each(['builtin', 'mock'])('%s 身份进入对应的请假入口', async provider => {
    authState.provider = provider as 'builtin' | 'mock'
    const { wrapper, router } = await render()
    await button(wrapper, '填写请假申请').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe(provider === 'builtin' ? '/oa/leaves/new' : '/leaves/new')
    wrapper.unmount()
  })
})
