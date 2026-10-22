import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus, { ElMessageBox } from 'element-plus'
import WorkTaskView from '@/views/WorkTaskView.vue'
import { workTaskApi } from '@/api/workTask'

vi.mock('@/api/workTask', () => ({ workTaskApi: { list: vi.fn(), batches: vi.fn(), get: vi.fn(), batch: vi.fn(),
  versions: vi.fn(), notifications: vi.fn(), create: vi.fn(), extract: vi.fn(), save: vi.fn(), decide: vi.fn(),
  update: vi.fn(), command: vi.fn(), events: vi.fn(), read: vi.fn() } }))
vi.mock('@/api/draftCommands', () => ({ replayable: vi.fn(async (_s, _p, command) => command('stable-key')) }))
const batch = { batch_id: 'WTB-1', thread_id: 't', source_type: 'ticket', source_id: 'T-1', source_version: 'hash',
  source: { ref: 'ticket:T-1:hash', content: 'Repair printer', title: 'T-1' }, status: 'DRAFT_READY', version: 1,
  draft: { candidates: [{ candidate_id: 'c1', title: 'Repair printer', assignee_id: 'u_emp_001',
    due_at: '2026-10-20T10:00:00+08:00', priority: 'high', sensitive: false, source_refs: ['ticket:T-1:hash'] }] },
  available_actions: ['edit', 'confirm', 'reject'], task_ids: [], error: null, created_at: '', updated_at: '' }

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(workTaskApi.list).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 })
  vi.mocked(workTaskApi.batches).mockResolvedValue([])
  vi.mocked(workTaskApi.batch).mockResolvedValue(structuredClone(batch) as any)
  vi.mocked(workTaskApi.versions).mockResolvedValue([])
  vi.mocked(workTaskApi.notifications).mockResolvedValue([])
  vi.mocked(workTaskApi.events).mockResolvedValue([])
})
async function render(path: string) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/work-tasks/:id?', component: WorkTaskView },
    { path: '/ticket/:id', component: { template: '<div />' } }, { path: '/meetings/:id', component: { template: '<div />' } }] })
  await router.push(path); await router.isReady()
  const wrapper = mount({ template: '<router-view />' }, { global: { plugins: [router, ElementPlus] } })
  await flushPromises()
  return { wrapper, router }
}
describe('work task candidate review', () => {
  it('requires saved candidate metadata and risk acknowledgment', async () => {
    const { wrapper } = await render('/work-tasks/WTB-1')
    const confirm = wrapper.get('[data-testid=confirm-tasks]')
    expect(confirm.attributes('disabled')).toBeDefined()
    await wrapper.get('[data-testid=metadata-confirmed] input').setValue(true)
    await wrapper.get('[data-testid=risk-acknowledged] input').setValue(true)
    expect(confirm.attributes('disabled')).toBeUndefined()
    await wrapper.get('input[aria-label="候选标题 1"]').setValue('Edited task')
    expect(confirm.attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid=save-candidates]').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })
  it('creates a real extraction batch and navigates to the record', async () => {
    vi.mocked(workTaskApi.create).mockResolvedValue({ ...batch, status: 'CREATED', draft: null, available_actions: ['extract'] } as any)
    const { wrapper, router } = await render('/work-tasks')
    await wrapper.get('input[aria-label="来源编号"]').setValue('T-1')
    await wrapper.get('[data-testid=create-task-batch]').trigger('click'); await flushPromises()
    expect(workTaskApi.create).toHaveBeenCalledOnce()
    expect(router.currentRoute.value.path).toBe('/work-tasks/WTB-1')
    wrapper.unmount()
  })
  it('confirms only the independently selected candidates', async () => {
    const second = { ...batch.draft.candidates[0], candidate_id: 'c2', title: 'Check stock' }
    vi.mocked(workTaskApi.batch).mockResolvedValue({ ...batch, draft: { candidates: [batch.draft.candidates[0], second] } } as any)
    vi.mocked(workTaskApi.decide).mockResolvedValue({ ...batch, status: 'CONFIRMED', available_actions: [], task_ids: ['WT-1'] } as any)
    const { wrapper } = await render('/work-tasks/WTB-1')
    await wrapper.findAll('.candidate-row input[type="checkbox"]')[0].setValue(false)
    await wrapper.get('[data-testid=metadata-confirmed] input').setValue(true)
    await wrapper.get('[data-testid=risk-acknowledged] input').setValue(true)
    await wrapper.get('[data-testid=confirm-tasks]').trigger('click'); await flushPromises()
    expect(workTaskApi.decide).toHaveBeenCalledWith('WTB-1', expect.objectContaining({
      selected_candidate_ids: ['c2'], metadata_confirmed: true, risk_acknowledged: true, idempotency_key: 'stable-key' }))
    expect(wrapper.find('[data-testid=confirm-tasks]').exists()).toBe(false)
    wrapper.unmount()
  })
  it('keeps unsaved changes when leaving is cancelled', async () => {
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValue('cancel')
    const { wrapper, router } = await render('/work-tasks/WTB-1')
    await wrapper.get('input[aria-label="候选标题 1"]').setValue('Unsaved title')
    await router.push('/work-tasks'); await flushPromises()
    expect(router.currentRoute.value.path).toBe('/work-tasks/WTB-1')
    expect(confirm).toHaveBeenCalledOnce()
    expect((wrapper.get('input[aria-label="候选标题 1"]').element as HTMLInputElement).value).toBe('Unsaved title')
    wrapper.unmount(); confirm.mockRestore()
  })
  it('drops a late batch response after navigation', async () => {
    let resolveFirst!: (value: any) => void
    vi.mocked(workTaskApi.batch).mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve }))
    vi.mocked(workTaskApi.batch).mockResolvedValueOnce({ ...batch, batch_id: 'WTB-2', source: { ...batch.source, title: 'Current source' } } as any)
    const { wrapper, router } = await render('/work-tasks/WTB-1')
    await router.push('/work-tasks/WTB-2'); await flushPromises()
    resolveFirst({ ...batch, source: { ...batch.source, title: 'Stale source' } }); await flushPromises()
    expect(wrapper.text()).toContain('Current source')
    expect(wrapper.text()).not.toContain('Stale source')
    wrapper.unmount()
  })
  it('retains edited values and command identity when saving fails', async () => {
    vi.mocked(workTaskApi.save).mockRejectedValueOnce(new Error('Temporary outage'))
      .mockResolvedValueOnce({ ...batch, version: 2, draft: { candidates: [{ ...batch.draft.candidates[0], title: 'Changed' }] } } as any)
    const { wrapper } = await render('/work-tasks/WTB-1')
    await wrapper.get('input[aria-label="候选标题 1"]').setValue('Changed')
    await wrapper.get('[data-testid=save-candidates]').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('Temporary outage')
    expect((wrapper.get('input[aria-label="候选标题 1"]').element as HTMLInputElement).value).toBe('Changed')
    await wrapper.get('[data-testid=save-candidates]').trigger('click'); await flushPromises()
    expect(vi.mocked(workTaskApi.save).mock.calls[0][1]).toEqual(vi.mocked(workTaskApi.save).mock.calls[1][1])
    wrapper.unmount()
  })
  it('shows assignee progress actions without exposing a private source', async () => {
    const record = { task_id: 'WT-1', batch_id: 'WTB-1', title: 'Repair printer', creator_id: 'u_emp_001',
      assignee_id: 'u_mgr_001', due_at: '2026-10-20T10:00:00+08:00', priority: 'normal', sensitive: false,
      status: 'IN_PROGRESS', progress: 25, version: 2, deadline_version: 1, source: null, source_refs: [],
      available_actions: ['progress', 'complete'], created_at: '', updated_at: '' }
    vi.mocked(workTaskApi.get).mockResolvedValue(record as any)
    vi.mocked(workTaskApi.command).mockResolvedValue({ ...record, status: 'COMPLETED', progress: 100, version: 3, available_actions: [] } as any)
    const { wrapper } = await render('/work-tasks/WT-1')
    expect(wrapper.find('input[aria-label="任务标题"]').exists()).toBe(false)
    expect(wrapper.find('.source').exists()).toBe(false)
    const complete = wrapper.findAll('button').find(button => button.text() === '完成任务')!
    await complete.trigger('click'); await flushPromises()
    expect(workTaskApi.command).toHaveBeenCalledWith('WT-1', expect.objectContaining({ action: 'complete', expected_version: 2 }))
    expect(wrapper.findAll('button').some(button => button.text() === '完成任务')).toBe(false)
    wrapper.unmount()
  })
  it('renders stored meeting JSON and task events in natural language', async () => {
    vi.mocked(workTaskApi.get).mockResolvedValue({ task_id: 'WT-1', batch_id: 'WTB-1',
      title: '整理验收资料', creator_id: 'u_emp_001', assignee_id: 'u_emp_001',
      due_at: '2026-10-20T10:00:00+08:00', priority: 'normal', sensitive: false,
      status: 'ARCHIVED', progress: 100, version: 4, deadline_version: 1, source_refs: ['meeting:MTG-1:1'],
      source: { ref: 'meeting:MTG-1:1', source_type: 'meeting', source_id: 'MTG-1', title: '验收会议',
        content: JSON.stringify({ summary: '保留人工确认', action_items: [{ title: '整理验收资料',
          priority: 'medium', source_refs: ['internal-segment-id'], assignee_candidate: null,
          due_at_candidate: null, needs_confirmation: true }] }) },
      available_actions: [], created_at: '', updated_at: '',
    })
    vi.mocked(workTaskApi.events).mockResolvedValue(['created', 'start', 'complete', 'archive'].map((action, i) => ({
      action, version: i + 1, actor_id: 'u_emp_001', details: {}, created_at: '',
    })))
    const { wrapper } = await render('/work-tasks/WT-1')
    const text = wrapper.text()
    for (const expected of ['保留人工确认', '待办事项', '普通', '未提供', '需要人工核实', '会议 MTG-1 · 第 1 版',
      '张三创建任务', '张三开始任务', '张三完成任务', '张三归档任务']) expect(text).toContain(expected)
    for (const raw of ['action_items', 'source_refs', 'internal-segment-id', 'meeting:MTG-1:1', 'u_emp_001',
      'created', 'archive', 'null', 'true']) expect(text).not.toContain(raw)
    expect(wrapper.get('.source a').attributes('href')).toBe('/meetings/MTG-1')
    wrapper.unmount()
  })
  it('keeps plain ticket content readable in the candidate source', async () => {
    const { wrapper } = await render('/work-tasks/WTB-1')
    expect(wrapper.get('.source').text()).toContain('Repair printer')
    expect(wrapper.get('.source').text()).toContain('工单 T-1')
    expect(wrapper.text()).not.toContain('ticket:T-1:hash')
    wrapper.unmount()
  })
})
