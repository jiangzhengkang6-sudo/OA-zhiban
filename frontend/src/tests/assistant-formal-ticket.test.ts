import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import AssistantView from '@/views/AssistantView.vue'
import { interruptApi, threadApi, ticketApi } from '@/api'
import { authState } from '@/stores/auth'

vi.mock('@/api', () => ({
  threadApi: { get: vi.fn(), create: vi.fn(), sendMessage: vi.fn() },
  interruptApi: { resume: vi.fn() },
  ticketApi: { updateDraft: vi.fn() },
}))

const draft = () => ({
  thread_id: 'thread-1', scene: 'ticket', status: 'WAITING_HUMAN', current_interrupt_id: 'interrupt-1',
  ticket_candidates: [], ticket_review: { mode: 'new', expired: false, changed: false },
  messages: [], ticket_draft: { thread_id: 'thread-1', status: 'PENDING',
    fields: { category: '系统故障', priority: 'medium', impact: '个人', summary: '无法登录' } },
})
const button = (wrapper: any, text: string) => wrapper.findAll('button').find((item: any) => item.text() === text)!
async function render(value: any = draft()) {
  vi.mocked(threadApi.get).mockResolvedValue(value)
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/assistant/:threadId?', component: AssistantView },
    { path: '/oa/tickets/:ticketId', component: { template: '<div />' } },
    { path: '/ticket/:ticketId', component: { template: '<div />' } },
  ] })
  await router.push('/assistant/thread-1')
  const wrapper = mount(AssistantView, { global: { plugins: [router, createPinia(), ElementPlus],
    stubs: { 'el-dialog': { props: ['modelValue'], template: '<div v-if="modelValue" class="el-dialog"><slot /><slot name="footer" /></div>' } } } })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  vi.resetAllMocks()
  Object.assign(authState, { provider: 'builtin', manualOA: true, aiEnabled: true })
  vi.mocked(interruptApi.resume).mockResolvedValue({ status: 'WAITING_HUMAN', trace_id: 'test' })
})

describe('正式工单助手', () => {
  it('重复候选先更新办理方式，再通过新的中断确认合并', async () => {
    const candidate = { id: 'existing-1', business_no: 'T-001', summary: '无法登录', revision: 3,
      state: 'OPEN', score: 1, reason: '摘要完全一致' }
    const value = { ...draft(), ticket_candidates: [candidate] }
    const { wrapper } = await render(value)
    expect(wrapper.text()).toContain('摘要完全一致')
    vi.mocked(threadApi.get).mockResolvedValue({ ...value, current_interrupt_id: 'interrupt-2',
      ticket_review: { mode: 'merge', target_ticket_id: candidate.id, expected_revision: 3,
        business_no: 'T-001', summary: '无法登录', expired: false, changed: false } } as any)
    await wrapper.get('input[type="radio"][value="existing-1"]').setValue()
    await flushPromises()
    expect(interruptApi.resume).toHaveBeenCalledWith('interrupt-1', expect.objectContaining({ action: 'edit',
      edited_data: { merge_ticket_id: 'existing-1', expected_revision: 3 } }))
    expect(button(wrapper, '确认创建工单')).toBeUndefined()
    await button(wrapper, '确认合并工单').trigger('click')
    await flushPromises()
    expect(vi.mocked(interruptApi.resume).mock.calls[1]).toEqual(['interrupt-2', expect.objectContaining({ action: 'confirm' })])
    wrapper.unmount()
  })

  it.each(['changed', 'expired'])('审核内容%s时禁用确认，允许重新核对', async (field) => {
    const value = { ...draft(), ticket_review: { ...draft().ticket_review, [field]: true } }
    const { wrapper } = await render(value)
    expect(button(wrapper, '确认创建工单').attributes('disabled')).toBeDefined()
    await button(wrapper, '重新核对工单').trigger('click')
    await flushPromises()
    expect(interruptApi.resume).toHaveBeenCalledWith('interrupt-1', expect.objectContaining({ action: 'edit', edited_data: {} }))
    wrapper.unmount()
  })

  it('已合并工单展示合并结果并保留正式详情入口', async () => {
    const { wrapper, router } = await render({ ...draft(), current_interrupt_id: null,
      ticket: { id: 'existing-1', ticket_id: 'existing-1', business_no: 'T-001', merged: true } })
    expect(wrapper.text()).toContain('已合并到工单')
    await wrapper.get('.el-link').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/oa/tickets/existing-1')
    wrapper.unmount()
  })

  it('缺少正式审核内容时禁止确认，仍可重新核对或取消', async () => {
    const { wrapper } = await render({ ...draft(), ticket_review: null })
    expect(button(wrapper, '确认创建工单').attributes('disabled')).toBeDefined()
    expect(button(wrapper, '重新核对工单').attributes('disabled')).toBeUndefined()
    await button(wrapper, '取消').trigger('click')
    await flushPromises()
    expect(interruptApi.resume).toHaveBeenCalledWith('interrupt-1', expect.objectContaining({ action: 'cancel' }))
    wrapper.unmount()
  })

  it('合并目标已不在候选中时重新核对切回新建工单', async () => {
    const value = { ...draft(), ticket_review: { mode: 'merge', target_ticket_id: 'closed-ticket',
      business_no: 'T-002', summary: '已结束的问题', expected_revision: 2, changed: true, expired: false } }
    const { wrapper } = await render(value)
    expect(wrapper.text()).toContain('目标工单已变化')
    expect(button(wrapper, '确认合并工单').attributes('disabled')).toBeDefined()
    await button(wrapper, '重新核对工单').trigger('click')
    await flushPromises()
    expect(interruptApi.resume).toHaveBeenCalledWith('interrupt-1', expect.objectContaining({ action: 'edit', edited_data: {} }))
    wrapper.unmount()
  })

  it('通过当前中断编辑草稿，失败重试沿用相同决定且不调用旧接口', async () => {
    const { wrapper } = await render()
    await button(wrapper, '编辑草稿').trigger('click')
    await flushPromises()
    await wrapper.get('.el-dialog textarea').setValue('显示器无法点亮')
    vi.mocked(interruptApi.resume).mockRejectedValueOnce(new Error('网络中断'))
    await button(wrapper, '保存修改').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('网络中断')
    await button(wrapper, '保存修改').trigger('click')
    await flushPromises()
    expect(interruptApi.resume).toHaveBeenCalledTimes(2)
    const [id, request] = vi.mocked(interruptApi.resume).mock.calls[0]!
    expect(id).toBe('interrupt-1')
    expect(request).toMatchObject({ action: 'edit', edited_data: { summary: '显示器无法点亮', priority: 'medium' } })
    expect(request.idempotency_key).toBeTruthy()
    expect(vi.mocked(interruptApi.resume).mock.calls[1]).toEqual([id, request])
    expect(ticketApi.updateDraft).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('取消的工单不再显示确认操作，禁止继续向已结束会话发消息', async () => {
    const value = draft()
    value.status = 'COMPLETED'
    value.current_interrupt_id = ''
    value.ticket_draft.status = 'CANCELLED'
    const { wrapper } = await render(value)
    expect(wrapper.text()).toContain('工单创建已取消')
    expect(button(wrapper, '确认创建工单')).toBeUndefined()
    expect(button(wrapper, '编辑草稿')).toBeUndefined()
    expect(button(wrapper, '发送').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('等待确认时禁用发送和转人工，连续确认只发出一次请求', async () => {
    const { wrapper } = await render()
    expect(button(wrapper, '发送').attributes('disabled')).toBeDefined()
    expect(button(wrapper, '转人工').attributes('disabled')).toBeDefined()
    let release!: (value: any) => void
    vi.mocked(interruptApi.resume).mockImplementation(() => new Promise(resolve => { release = resolve }))
    const confirm = button(wrapper, '确认创建工单')
    await confirm.trigger('click')
    await confirm.trigger('click')
    expect(interruptApi.resume).toHaveBeenCalledTimes(1)
    release({ status: 'WAITING_HUMAN', trace_id: 'test' })
    await flushPromises()
    wrapper.unmount()
  })

  it('已创建工单跳转到正式工作台的对应工单', async () => {
    const { wrapper, router } = await render({ ...draft(), current_interrupt_id: null,
      ticket: { id: 'ticket-1', ticket_id: 'ticket-1', business_no: 'TK-001' } })
    await wrapper.get('.el-link').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/oa/tickets/ticket-1')
    wrapper.unmount()
  })

  it('Mock 工单仍跳转到原详情页', async () => {
    authState.provider = 'mock'
    const { wrapper, router } = await render({ ...draft(), ticket: { ticket_id: 'TK-MOCK' } })
    await wrapper.get('.el-link').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/ticket/TK-MOCK')
    wrapper.unmount()
  })

  it('重新加载后可恢复服务端已保存的决定，不重新确认或发送草稿', async () => {
    const { wrapper } = await render({ ...draft(), error: { code: 'GRAPH_RECOVERY', msg: '业务决定已保存' },
      ticket_draft: { ...draft().ticket_draft, status: 'CONFIRMED' }, ticket: { ticket_id: 'ticket-1' } })
    await button(wrapper, '恢复处理').trigger('click')
    await flushPromises()
    expect(interruptApi.resume).toHaveBeenCalledWith('interrupt-1', { action: 'reconcile' })
    expect(button(wrapper, '确认创建工单')).toBeUndefined()
    wrapper.unmount()
  })
})
