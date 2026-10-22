import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import { ElMessageBox } from 'element-plus'
import MeetingView from '@/views/MeetingView.vue'
import { meetingApi } from '@/api/meeting'
import { setCurrentUserId } from '@/api/client'

vi.mock('@/api/meeting', () => ({ meetingApi: {
  create: vi.fn(), get: vi.fn(), list: vi.fn(), generate: vi.fn(), save: vi.fn(), decide: vi.fn(), retry: vi.fn(), freshKey: vi.fn(() => crypto.randomUUID()),
  commandKey: vi.fn(async () => 'stable-key'), releaseCommandKey: vi.fn(),
} }))

const segment = { segment_id: 's1', ordinal: 1, start_offset: 0, end_offset: 12,
  text: '议题：验收。决定：通过。', locator: 'chars:0-12', text_hash: 'a'.repeat(64), summary: '验收' }
const draft = { summary: '验收纪要', topics: ['验收'], source_refs: ['s1'],
  decisions: [{ text: '通过', source_refs: ['s1'], confidence: 'explicit' as const }],
  action_items: [{ title: '完成验收', assignee_candidate: null, due_at_candidate: null,
    priority: 'medium' as const, source_refs: ['s1'], needs_confirmation: true }] }
const meeting = { meeting_id: 'MTG-1', thread_id: 't1', title: '验收会', status: 'DRAFT_READY' as const,
  version: 1, segments: [segment], draft, available_actions: ['edit', 'confirm', 'reject', 'regenerate'],
  external_writes: false, trace_id: 'trace1' }

async function render(path = '/meetings') {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/meetings/:meetingId?', component: MeetingView },
    { path: '/audit', component: { template: '<div>审计入口</div>' } },
  ] })
  await router.push(path); await router.isReady()
  const wrapper = mount(MeetingView, { global: { plugins: [router, ElementPlus], stubs: { transition: false } } })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  vi.clearAllMocks()
  setCurrentUserId('u_emp_001')
  vi.mocked(meetingApi.get).mockResolvedValue({ ...meeting })
  vi.mocked(meetingApi.list).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 })
  vi.mocked(meetingApi.create).mockResolvedValue({ ...meeting, status: 'CREATED', version: null, draft: null, available_actions: ['generate'] })
  vi.mocked(meetingApi.generate).mockResolvedValue({ ...meeting })
  vi.mocked(meetingApi.save).mockResolvedValue({ ...meeting, status: 'REVIEWING', version: 2 })
  vi.mocked(meetingApi.decide).mockResolvedValue({ ...meeting, status: 'CONFIRMED', available_actions: [] })
  vi.mocked(meetingApi.retry).mockResolvedValue({ ...meeting })
})

describe('meeting workbench', () => {
  it('requires title and text before creation, then opens the durable meeting', async () => {
    const { wrapper, router } = await render()
    expect(wrapper.get('[data-testid=create-meeting]').attributes('disabled')).toBeDefined()
    await wrapper.get('[aria-label=会议标题]').setValue('验收会')
    await wrapper.get('[aria-label=会议文本]').setValue('议题：验收。')
    await wrapper.get('[data-testid=create-meeting]').trigger('click'); await flushPromises()
    expect(meetingApi.create).toHaveBeenCalledWith(expect.objectContaining({ title: '验收会', content: '议题：验收。', idempotency_key: expect.any(String) }))
    expect(router.currentRoute.value.path).toBe('/meetings/MTG-1')
    wrapper.unmount()
  })

  it('shows source anchors and saves an immutable edited version before confirmation', async () => {
    const confirmation = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    const { wrapper } = await render('/meetings/MTG-1')
    expect(wrapper.get('[aria-label=纪要摘要]').element).toHaveProperty('value', '验收纪要')
    expect(wrapper.text()).toContain('来源 1')
    expect(wrapper.get('[aria-label="负责人 1"]').attributes('placeholder')).toBe('负责人待确认')
    expect(wrapper.text()).toContain('不会写入 OA、任务、日历或邮件')
    await wrapper.get('[aria-label=纪要摘要]').setValue('修改后的纪要')
    expect(wrapper.get('[data-testid=confirm-meeting]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-testid=save-meeting]').trigger('click'); await flushPromises()
    expect(meetingApi.save).toHaveBeenCalledWith('MTG-1', expect.objectContaining({
      expected_version: 1, draft: expect.objectContaining({ summary: '修改后的纪要', source_refs: ['s1'] }),
    }))
    await wrapper.get('[data-testid=confirm-meeting]').trigger('click'); await flushPromises()
    expect(meetingApi.decide).toHaveBeenCalledWith('MTG-1', expect.objectContaining({ action: 'confirm', expected_version: 2 }))
    confirmation.mockRestore()
    wrapper.unmount()
  })

  it('replays a lost retry response, then uses a fresh key for a new paused attempt', async () => {
    vi.mocked(meetingApi.commandKey).mockResolvedValueOnce('retry-1').mockResolvedValueOnce('retry-1').mockResolvedValueOnce('retry-2')
    vi.mocked(meetingApi.get).mockResolvedValue({ ...meeting, status: 'PAUSED', draft: null, available_actions: ['retry'] })
    vi.mocked(meetingApi.retry).mockRejectedValueOnce(new Error('网络连接中断'))
    vi.mocked(meetingApi.retry).mockResolvedValueOnce({ ...meeting, status: 'PAUSED', draft: null, available_actions: ['retry'] })
    const { wrapper } = await render('/meetings/MTG-1')
    await wrapper.get('[data-testid=retry-meeting]').trigger('click'); await flushPromises()
    await wrapper.get('[data-testid=retry-meeting]').trigger('click'); await flushPromises()
    expect(vi.mocked(meetingApi.retry).mock.calls[0][1].idempotency_key).toBe(vi.mocked(meetingApi.retry).mock.calls[1][1].idempotency_key)
    await wrapper.get('[data-testid=retry-meeting]').trigger('click'); await flushPromises()
    expect(vi.mocked(meetingApi.retry).mock.calls[1][1].idempotency_key).not.toBe(vi.mocked(meetingApi.retry).mock.calls[2][1].idempotency_key)
    wrapper.unmount()
  })

  it('reuses the same command key when a create response is lost', async () => {
    vi.mocked(meetingApi.create).mockRejectedValueOnce(new Error('网络连接中断'))
    const { wrapper } = await render()
    await wrapper.get('[aria-label=会议标题]').setValue('验收会')
    await wrapper.get('[aria-label=会议文本]').setValue('会议内容')
    await wrapper.get('[data-testid=create-meeting]').trigger('click'); await flushPromises()
    await wrapper.get('[data-testid=create-meeting]').trigger('click'); await flushPromises()
    expect(vi.mocked(meetingApi.create).mock.calls.map(call => call[0].idempotency_key)).toEqual(['stable-key', 'stable-key'])
    expect(meetingApi.releaseCommandKey).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('ignores an old meeting response after navigating to another record', async () => {
    let resolveOld!: (value: any) => void
    vi.mocked(meetingApi.get).mockImplementation(id => id === 'A' ? new Promise(resolve => { resolveOld = resolve }) : Promise.resolve({ ...meeting, meeting_id: 'B', title: '会议 B' }))
    const { wrapper, router } = await render('/meetings/A')
    await router.push('/meetings/B'); await flushPromises()
    resolveOld({ ...meeting, meeting_id: 'A', title: '会议 A' }); await flushPromises()
    expect(wrapper.text()).toContain('会议 B')
    expect(wrapper.text()).not.toContain('会议 A')
    wrapper.unmount()
  })

  it('shows a recoverable detail error without offering creation on a detail route', async () => {
    vi.mocked(meetingApi.get).mockRejectedValue(new Error('会议不存在或无权限'))
    const { wrapper } = await render('/meetings/missing')
    expect(wrapper.text()).toContain('会议不存在或无权限')
    expect(wrapper.find('[data-testid=create-meeting]').exists()).toBe(false)
    expect(wrapper.text()).toContain('重新加载')
    wrapper.unmount()
  })

  it('shows audit navigation only to admins', async () => {
    const employee = await render('/meetings/MTG-1')
    expect(employee.wrapper.text()).not.toContain('查看审计轨迹')
    employee.wrapper.unmount()
    setCurrentUserId('u_admin_001')
    const admin = await render('/meetings/MTG-1')
    expect(admin.wrapper.text()).toContain('查看审计轨迹')
    admin.wrapper.unmount()
  })
})
