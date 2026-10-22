import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import ContractView from '@/views/ContractView.vue'
import { contractApi } from '@/api/contract'

vi.mock('@/api/contract', () => ({ contractApi: { list: vi.fn(), get: vi.fn(), versions: vi.fn(), create: vi.fn(), upload: vi.fn(), command: vi.fn() } }))
vi.mock('@/api/draftCommands', () => ({ commandKey: vi.fn(async () => 'contract-key'), releaseCommandKey: vi.fn() }))
const record = { contract_id: 'CON-1', thread_id: 'thread', title: '采购合同', owner_id: 'u_emp_001', reviewer_id: 'u_mgr_001', status: 'DRAFT_READY', version: 1,
  available_actions: ['confirm', 'reject'], scan_status: 'CLEAN', source_id: 'source', source_hash: 'hash', source_text: '付款条款：30日付款。',
  paragraphs: [{ paragraph: 1, quote: '付款条款：30日付款。', start: 0, end: 12, page: null }], node_trace: ['extract_clauses','check_rules','analyze_risks','summarize'],
  draft: { summary: '请核对', analysis_engine: 'deepagents', rule_version: 'demo-1', observations: [], risks: [{ risk_id: 'payment', severity: 'medium', missing: false, title: '付款条款', suggestion: '核对', evidence: { paragraph: 1, quote: '付款条款：30日付款。', start: 0, end: 12 } }] }, confirmation: null, error: null }
async function render() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/contracts/:id?', component: ContractView }] })
  await router.push('/contracts/CON-1'); await router.isReady()
  const wrapper = mount({ template: '<router-view />' }, { global: { plugins: [router, ElementPlus] } })
  await flushPromises(); return wrapper
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(contractApi.get).mockResolvedValue(structuredClone(record) as any)
  vi.mocked(contractApi.versions).mockResolvedValue([{ version: 1, draft: record.draft, created_at: '' }] as any)
  vi.mocked(contractApi.list).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 })
})
describe('private contract workbench', () => {
  it('renders grounded evidence and requires each risk decision before confirmation', async () => {
    const wrapper = await render()
    expect(wrapper.text()).toContain('付款条款：30日付款。')
    expect(wrapper.text()).toContain('DeepAgents')
    expect(wrapper.get('[data-testid=confirm-contract]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('[data-testid=risk-evidence]').text()).toContain('第 1 段')
    wrapper.unmount()
  })
  it('hides mutation controls after terminal confirmation', async () => {
    vi.mocked(contractApi.get).mockResolvedValue({ ...record, status: 'CONFIRMED', available_actions: [], confirmation: { actor_id: 'u_mgr_001', version: 1, action: 'confirm', comment: '已人工复核', dispositions: [] } } as any)
    const wrapper = await render()
    expect(wrapper.find('[data-testid=confirm-contract]').exists()).toBe(false)
    expect(wrapper.text()).toContain('已人工复核')
    wrapper.unmount()
  })
})
