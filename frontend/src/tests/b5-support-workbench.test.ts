import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import SupportQueueView from '@/views/SupportQueueView.vue'
import SupportWorkItemView from '@/views/SupportWorkItemView.vue'
import TicketWorkbenchView from '@/views/TicketWorkbenchView.vue'
import { supportApi, ticketApi } from '@/api'

vi.mock('@/api', () => ({
  supportApi: { list: vi.fn(), get: vi.fn(), accept: vi.fn(), assign: vi.fn(), complete: vi.fn() },
  ticketApi: { get: vi.fn() },
}))

const item = {
  queue_item_id: 'q1', tenant_id: 't_001', thread_id: 'thread-1', user_id: 'u_emp_001',
  scene: 'ticket', reason_code: 'FAQ_NO_EVIDENCE', status: 'OPEN', assignee_id: null,
  context_summary: '用户无法登录', snapshot: { summary: '用户无法登录', feedback: '仍然无法登录' },
  ticket_id: 'TK-001', ticket_status: 'open', sla_status: 'pending',
}

async function render(component: any, path: string) {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/support', component: SupportQueueView },
    { path: '/support/:itemId', component: SupportWorkItemView },
    { path: '/support/ticket/:ticketId', component: TicketWorkbenchView },
  ] })
  await router.push(path); await router.isReady()
  const wrapper = mount(component, { global: { plugins: [router, ElementPlus], stubs: { transition: false } } })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  localStorage.setItem('oa_current_user', 'u_cs_001')
  vi.mocked(supportApi.list).mockResolvedValue({ items: [item], total: 1, page: 1, page_size: 20 })
  vi.mocked(supportApi.get).mockResolvedValue(item)
  vi.mocked(supportApi.accept).mockResolvedValue({ ...item, status: 'IN_PROGRESS', assignee_id: 'u_cs_001' })
  vi.mocked(supportApi.assign).mockResolvedValue({ ...item, status: 'IN_PROGRESS', assignee_id: 'u_cs_002' })
  vi.mocked(supportApi.complete).mockResolvedValue({ ...item, status: 'RESOLVED', ticket_status: 'resolved' })
  vi.mocked(ticketApi.get).mockResolvedValue({ ticket: { ticket_id: 'TK-001', status: 'resolved', summary: '用户无法登录' }, timeline: [] })
})

describe('B5 support workbench', () => {
  it('loads queue scope and opens a handoff item', async () => {
    const { wrapper, router } = await render(SupportQueueView, '/support')
    expect(supportApi.list).toHaveBeenCalled()
    expect(wrapper.text()).toContain('用户无法登录')
    expect(wrapper.text()).toContain('知识库未找到可靠依据')
    expect(wrapper.text()).toContain('查看上下文快照')
    await wrapper.get('[data-testid=open-support-item]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/support/q1')
    wrapper.unmount()
  })

  it('accepts, transfers, and completes a work item', async () => {
    const { wrapper } = await render(SupportWorkItemView, '/support/q1')
    expect(supportApi.get).toHaveBeenCalledWith('q1')
    expect(wrapper.text()).toContain('上下文快照')
    expect(wrapper.text()).toContain('知识库未找到可靠依据')
    await wrapper.get('[data-testid=accept-item]').trigger('click'); await flushPromises()
    expect(supportApi.accept).toHaveBeenCalledWith('q1')
    await wrapper.get('[data-testid=assign-item]').trigger('click'); await flushPromises()
    expect(supportApi.assign).toHaveBeenCalledWith('q1', 'u_cs_002')
    await wrapper.find('textarea').setValue('已重置账号并恢复登录')
    await wrapper.get('[data-testid=complete-item]').trigger('click'); await flushPromises()
    expect(supportApi.complete).toHaveBeenCalledWith('q1', expect.objectContaining({ status: 'resolved' }))
    wrapper.unmount()
  })

  it('shows linked ticket context in the ticket workbench', async () => {
    const { wrapper } = await render(TicketWorkbenchView, '/support/ticket/TK-001')
    expect(ticketApi.get).toHaveBeenCalledWith('TK-001')
    expect(wrapper.text()).toContain('TK-001')
    expect(wrapper.text()).toContain('用户无法登录')
    wrapper.unmount()
  })

  it('presents the handoff snapshot as readable fields and conversation', async () => {
    vi.mocked(supportApi.get).mockResolvedValue({ ...item, snapshot: {
      scene: 'ticket', thread_id: 'private-thread-reference', reason_code: 'TICKET_HUMAN',
      summary: '我的电脑无法开机', feedback: '仍未恢复',
      messages: [{ role: 'user', content: '请帮忙维修' }, { role: 'assistant', content: '已转交人工处理' }],
      extracted_fields: { category: 'IT设备', priority: 'medium', impact: '个人' },
    } })
    const { wrapper } = await render(SupportWorkItemView, '/support/q1')
    expect(wrapper.text()).toContain('张三')
    expect(wrapper.text()).toContain('待受理')
    expect(wrapper.text()).toContain('历史对话')
    expect(wrapper.text()).toContain('智能助手')
    expect(wrapper.text()).toContain('请帮忙维修')
    expect(wrapper.text()).toContain('问题类别')
    expect(wrapper.text()).toContain('IT设备')
    expect(wrapper.text()).toContain('普通')
    expect(wrapper.text()).toContain('仍未恢复')
    for (const raw of ['extracted_fields', 'thread_id', 'private-thread-reference', 'medium', 'OPEN']) {
      expect(wrapper.text()).not.toContain(raw)
    }
    expect(wrapper.find('pre').exists()).toBe(false)
    wrapper.unmount()
  })
})
