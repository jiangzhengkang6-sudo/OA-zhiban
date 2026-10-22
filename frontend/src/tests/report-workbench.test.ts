import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus, { ElMessageBox } from 'element-plus'
import ReportView from '@/views/ReportView.vue'
import { reportApi } from '@/api/report'
import { authState } from '@/stores/auth'

vi.mock('@/api/report', () => ({ reportApi: { metrics: vi.fn(), list: vi.fn(), get: vi.fn(), versions: vi.fn(),
  create: vi.fn(), approve: vi.fn(), retry: vi.fn(), save: vi.fn(), publish: vi.fn() } }))
vi.mock('@/api/draftCommands', () => ({ commandKey: vi.fn(async () => 'report-key'), releaseCommandKey: vi.fn() }))

const metric = { metric_id: 'ticket_volume', version: 1, name: '工单量', unit: '条', definition: '创建日统计',
  source: 'ticket_record', time_field: 'created_at', current: 2, previous: 0, change_percent: null,
  comparison_available: false, anomaly_candidate: false, status_counts: { open: 2 },
  buckets: [{ day: '2026-10-01', value: 2 }], source_ids: [] }
const record = { report_id: 'RPT-1', thread_id: 'thread', subject: '周报告', status: 'DRAFT_READY', version: 2,
  available_actions: ['edit', 'publish'], plan: { metrics: ['ticket_volume'], start: '2026-09-30T16:00:00Z',
    end: '2026-10-07T16:00:00Z', grain: 'day', scope: 'own', metric_version: 1 },
  snapshot: { metrics: [metric], queried_at: '2026-10-14T00:00:00Z', timezone: 'Asia/Shanghai', interval: '[start,end)' },
  draft: { summary: '工单量本期数据已汇总。', metric_refs: ['ticket_volume'], possible_causes: [] },
  publication: null, plan_confirmation: {}, error: null, external_writes: false, created_at: '', updated_at: '' }

async function render(path = '/reports/RPT-1') {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/reports/:id?', component: ReportView }] })
  await router.push(path); await router.isReady()
  const wrapper = mount({ template: '<router-view />' }, { global: { plugins: [router, ElementPlus] } })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  vi.clearAllMocks()
  authState.provider = 'mock'
  authState.user = null
  vi.mocked(reportApi.metrics).mockResolvedValue([metric] as any)
  vi.mocked(reportApi.list).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 })
  vi.mocked(reportApi.get).mockResolvedValue(structuredClone(record) as any)
  vi.mocked(reportApi.versions).mockResolvedValue([{ version: 2, draft: record.draft, snapshot: record.snapshot, edited_by: null, created_at: '' }] as any)
  vi.mocked(reportApi.save).mockImplementation(async (_, payload) => ({ ...record, version: 3, draft: payload.draft, status: 'REVIEWING' } as any))
})

describe('report workbench', () => {
  it('offers department scope only with a formal department report grant and submits it unchanged', async () => {
    authState.provider = 'builtin'
    authState.user = { user_id: 'member', display_name: '成员', roles: [], depts: ['department'],
      permissions: [{ resource: 'report', action: 'read', scope: 'department' }] }
    vi.mocked(reportApi.create).mockResolvedValue({ ...record, plan: { ...record.plan, scope: 'department' } } as any)
    const { wrapper } = await render('/reports')
    const options = wrapper.findAllComponents({ name: 'ElOption' }).map(option => option.props('value'))
    expect(options).toContain('department')
    expect(options).not.toContain('tenant')
    await wrapper.get('input[aria-label="报告标题"]').setValue('部门报告')
    wrapper.findAllComponents({ name: 'ElDatePicker' })[0]!.vm.$emit('update:modelValue', '2026-10-01')
    wrapper.findAllComponents({ name: 'ElDatePicker' })[1]!.vm.$emit('update:modelValue', '2026-10-08')
    const scope = wrapper.findAllComponents({ name: 'ElSelect' }).find(select => select.props('ariaLabel') === '统计范围')!
    scope.vm.$emit('update:modelValue', 'department')
    await flushPromises()
    await wrapper.get('[data-testid=create-report]').trigger('click'); await flushPromises()
    expect(reportApi.create).toHaveBeenCalledWith(expect.objectContaining({ plan: expect.objectContaining({ scope: 'department' }) }))
    wrapper.unmount()
  })

  it('hides department and tenant choices from a formal self-scoped account', async () => {
    authState.provider = 'builtin'
    authState.user = { user_id: 'member', display_name: '成员', roles: [], depts: ['department'],
      permissions: [{ resource: 'report', action: 'read', scope: 'self' }] }
    const { wrapper } = await render('/reports')
    const options = wrapper.findAllComponents({ name: 'ElOption' }).map(option => option.props('value'))
    expect(options).not.toContain('department')
    expect(options).not.toContain('tenant')
    wrapper.unmount()
  })

  it('labels saved department plans in Chinese', async () => {
    vi.mocked(reportApi.get).mockResolvedValue({ ...record, plan: { ...record.plan, scope: 'department' } } as any)
    const { wrapper } = await render()
    expect(wrapper.text()).toContain('本部门可访问的数据')
    wrapper.unmount()
  })

  it('renders snapshot numbers and blocks publication until saved and acknowledged', async () => {
    const { wrapper } = await render()
    expect(wrapper.text()).toContain('无对比数据')
    expect(wrapper.text()).toContain('创建日统计')
    expect(wrapper.find('[data-testid=publish-report]').attributes('disabled')).toBeDefined()
    await wrapper.get('textarea[aria-label="报表摘要"]').setValue('工单量本期 2 条。需要核查。')
    await wrapper.get('[data-testid=definitions-confirmed] input').setValue(true)
    await wrapper.get('[data-testid=causes-confirmed] input').setValue(true)
    expect(wrapper.find('[data-testid=publish-report]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-testid=save-report]').trigger('click'); await flushPromises()
    expect(reportApi.save).toHaveBeenCalledWith('RPT-1', expect.objectContaining({ expected_version: 2 }))
    expect(wrapper.find('[data-testid=publish-report]').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('requires plan confirmation before querying and exposes no editing before results', async () => {
    vi.mocked(reportApi.get).mockResolvedValue({ ...record, status: 'PLAN_READY', version: 1,
      available_actions: ['approve'], draft: null, snapshot: null } as any)
    vi.mocked(reportApi.approve).mockResolvedValue(record as any)
    const { wrapper } = await render()
    expect(wrapper.get('[data-testid=approve-report-plan]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-testid=save-report]').exists()).toBe(false)
    await wrapper.get('[data-testid=plan-confirmed] input').setValue(true)
    await wrapper.get('[data-testid=approve-report-plan]').trigger('click'); await flushPromises()
    expect(reportApi.approve).toHaveBeenCalledWith('RPT-1', expect.objectContaining({ expected_version: 1, plan_confirmed: true }))
    expect(wrapper.find('[data-testid=save-report]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('preserves dirty content on cancelled navigation and failed save', async () => {
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValue('cancel')
    vi.mocked(reportApi.save).mockRejectedValue(new Error('版本冲突'))
    const { wrapper, router } = await render()
    await wrapper.get('textarea[aria-label="报表摘要"]').setValue('未保存的内容')
    await wrapper.get('[data-testid=save-report]').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('版本冲突')
    await router.push('/reports'); await flushPromises()
    expect(router.currentRoute.value.path).toBe('/reports/RPT-1')
    expect((wrapper.get('textarea[aria-label="报表摘要"]').element as HTMLTextAreaElement).value).toBe('未保存的内容')
    confirm.mockRestore(); wrapper.unmount()
  })

  it('hides write controls on published reports and displays immutable history', async () => {
    vi.mocked(reportApi.get).mockResolvedValue({ ...record, status: 'PUBLISHED', available_actions: [] } as any)
    const { wrapper } = await render()
    expect(wrapper.text()).toContain('已发布')
    expect(wrapper.text()).toContain('版本比较')
    expect(wrapper.find('[data-testid=publish-report]').exists()).toBe(false)
    expect(wrapper.get('textarea[aria-label="报表摘要"]').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })
})
