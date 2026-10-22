import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import TicketDetailView from '@/views/TicketDetailView.vue'
import KnowledgeSourceView from '@/views/KnowledgeSourceView.vue'
import { ticketApi, knowledgeApi } from '@/api'

vi.mock('vue-router', () => ({ useRoute: () => ({ params: { ticketId: 'TK-001' } }) }))
vi.mock('@/api', () => ({
  ticketApi: { get: vi.fn() },
  knowledgeApi: { preview: vi.fn(), uploadVersion: vi.fn(), publishVersion: vi.fn() },
}))

beforeEach(() => {
  vi.mocked(ticketApi.get).mockResolvedValue({ ticket: { ticket_id: 'TK-001', status: 'open', category: 'IT设备', priority: 'medium', summary: '无法开机', queue_id: 'q_it', assignee_id: 'u_cs_001' }, timeline: [] })
  vi.mocked(knowledgeApi.preview).mockResolvedValue({ format: 'md', blocks: [] } as any)
  vi.mocked(knowledgeApi.uploadVersion).mockResolvedValue({ id: 'v1', version: 1, status: 'draft' } as any)
})

describe('manual feedback regressions', () => {
  it('shows assignment fields on the employee ticket detail', async () => {
    const wrapper = mount(TicketDetailView, { global: { plugins: [ElementPlus] } })
    await flushPromises()
    expect(wrapper.text()).toContain('队列')
    expect(wrapper.text()).toContain('q_it')
    expect(wrapper.text()).toContain('责任人')
    expect(wrapper.text()).toContain('u_cs_001')
    wrapper.unmount()
  })

  it('previews and drafts the file selected in the upload control', async () => {
    const wrapper = mount(KnowledgeSourceView, { global: { plugins: [ElementPlus] } })
    const file = new File(['# 员工手册'], 'handbook.md', { type: 'text/markdown' })
    const input = wrapper.get('input[type=file]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })
    await input.trigger('change')
    await wrapper.get('input[placeholder="如：员工手册"]').setValue('员工手册')
    await wrapper.findAll('button').find(button => button.text() === '预览解析')!.trigger('click')
    await flushPromises()
    expect(knowledgeApi.preview).toHaveBeenCalledWith(file)
    await wrapper.findAll('button').find(button => button.text() === '创建草稿')!.trigger('click')
    await flushPromises()
    const form = vi.mocked(knowledgeApi.uploadVersion).mock.calls[0]?.[0]
    expect(form?.get('file')).toBe(file)
    wrapper.unmount()
  })
})
