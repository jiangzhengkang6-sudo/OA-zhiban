import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import LeaveFormView from '@/views/LeaveFormView.vue'
import ApprovalInboxView from '@/views/ApprovalInboxView.vue'
import AssistantView from '@/views/AssistantView.vue'
import LeaveDetailView from '@/views/LeaveDetailView.vue'
import App from '@/App.vue'
import { leaveApi, taskApi, threadApi } from '@/api'
import { useAssistantStore } from '@/stores/assistant'

vi.mock('@/api', () => ({
  leaveApi: { create: vi.fn(), get: vi.fn(), patch: vi.fn(), submit: vi.fn(), versions: vi.fn(), decide: vi.fn(), attachments: vi.fn().mockResolvedValue([]), uploadAttachment: vi.fn(), scanAttachment: vi.fn(), downloadAttachment: vi.fn() },
  taskApi: { list: vi.fn(), handoff: vi.fn(), retry: vi.fn() },
  threadApi: { get: vi.fn(), create: vi.fn(), sendMessage: vi.fn() },
  interruptApi: { resume: vi.fn() }, approvalApi: { retryWrite: vi.fn(), reconcile: vi.fn() },
  ticketApi: { updateDraft: vi.fn() },
}))
const application = { application_id: 'a1', thread_id: 't1', business_id: 'LA-1', user_id: 'u_emp_001',
  status: 'REJECTED', version: 1, fields: { leave_type: 'annual', start_at: '2026-10-20T09:00:00+08:00',
    end_at: '2026-10-20T18:00:00+08:00', reason: '家庭事务', attachments: [] } }
const task = { task_id: 't1', task_type: 'leave', business_id: 'LA-1', business_status: 'WAITING_HUMAN',
  next_action: 'human', responsibility: { role: 'approver', user_id: 'u_mgr_001', display_name: '李四' },
  available_actions: ['approve', 'edit', 'reject'] }
const approval = { thread_id: 't1', application_id: 'a1', scene: 'leave', status: 'WAITING_HUMAN',
  messages: [], form_snapshot: application.fields,
  active_approval_node: { node_id: 'n1', order: 1, approver_id: 'u_mgr_001', approver_name: '李四' },
  approval_route: { nodes: [{ order: 1, approver_id: 'u_mgr_001', approver_name: '李四', is_proxy: false }] } }
async function render(component: any, url: string) {
  const pinia = createPinia(); setActivePinia(pinia)
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/leaves/:applicationId?', component: LeaveFormView },
    { path: '/leave/:threadId', component: LeaveDetailView },
    { path: '/approvals', component: ApprovalInboxView },
    { path: '/assistant/:threadId?', component: AssistantView },
    { path: '/tasks', component: { template: '<div />' } },
  ] })
  await router.push(url); await router.isReady()
  const wrapper = mount(component, { global: { plugins: [pinia, router, ElementPlus], stubs: { transition: false } } })
  await flushPromises()
  return { wrapper, router, pinia }
}
beforeEach(() => {
  vi.mocked(leaveApi.attachments).mockResolvedValue([])
  vi.mocked(leaveApi.get).mockResolvedValue(application)
  vi.mocked(leaveApi.versions).mockResolvedValue([{ version: 1, status: 'SUBMITTED', fields: application.fields }])
  vi.mocked(leaveApi.patch).mockResolvedValue({ ...application, status: 'DRAFT' })
  vi.mocked(leaveApi.create).mockResolvedValue({ ...application, status: 'DRAFT' })
  vi.mocked(leaveApi.submit).mockResolvedValue({ ...application, status: 'SUBMITTED', version: 2 })
  vi.mocked(taskApi.list).mockResolvedValue({ items: [task], total: 1, page: 1, page_size: 20 })
  vi.mocked(threadApi.get).mockResolvedValue(approval as any)
})
describe('B4 workbench', () => {
  it('shows attachment metadata to the approver and blocks unscanned downloads', async () => {
    localStorage.setItem('oa_current_user', 'u_mgr_001')
    vi.mocked(leaveApi.attachments).mockResolvedValue([{ attachment_id: 'file1', filename: 'proof.png', scan_status: 'PENDING', size_bytes: 12, content_type: 'image/png', sha256: 'abc' }])
    const { wrapper } = await render(LeaveDetailView, '/leave/t1')
    expect(leaveApi.attachments).toHaveBeenCalledWith('a1')
    expect(wrapper.text()).toContain('proof.png')
    expect(wrapper.text()).toContain('待扫描')
    expect(wrapper.findAll('button').find(b => b.text() === '下载')!.attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })
  it('keeps approval materials visible when attachments fail to load and offers retry', async () => {
    vi.mocked(leaveApi.attachments).mockRejectedValueOnce(new Error('unavailable'))
    const { wrapper } = await render(LeaveDetailView, '/leave/t1')
    expect(wrapper.text()).toContain('家庭事务')
    expect(wrapper.text()).toContain('无法加载证明材料')
    const retry = wrapper.findAll('button').find(b => b.text() === '重新加载附件')!
    await retry.trigger('click'); await flushPromises()
    expect(wrapper.text()).not.toContain('无法加载证明材料')
    wrapper.unmount()
  })
  it('shows a dependency pause and lets the employee retry precheck', async () => {
    vi.mocked(leaveApi.get).mockResolvedValue({ ...application, status: 'PAUSED', precheck: {
      passed: false, rule_version: 'builtin-v2', status: 'PAUSED', items: [],
      error: { dependency: 'balance', msg: '假期余额暂不可用，申请已安全暂停', code: '50201' },
    } } as any)
    const { wrapper } = await render(LeaveFormView, '/leaves/a1')
    expect(wrapper.text()).toContain('假期余额暂不可用')
    expect(wrapper.get('[data-testid=submit-leave]').attributes('disabled')).toBeUndefined()
    await wrapper.get('[data-testid=submit-leave]').trigger('click'); await flushPromises()
    expect(leaveApi.submit).toHaveBeenCalledWith('a1')
    wrapper.unmount()
  })
  it('does not offer draft edits for an unresolved approval write pause', async () => {
    vi.mocked(leaveApi.get).mockResolvedValue({ ...application, status: 'PAUSED' })
    const { wrapper } = await render(LeaveFormView, '/leaves/a1')
    expect(wrapper.find('[data-testid=save-draft]').exists()).toBe(false)
    expect(wrapper.find('[data-testid=submit-leave]').exists()).toBe(false)
    wrapper.unmount()
  })
  it('saves a new complete employee draft without an OA business number', async () => {
    const { wrapper } = await render(LeaveFormView, '/leaves')
    await wrapper.get('[aria-label=开始时间]').setValue('2026-10-20T09:00')
    await wrapper.get('[aria-label=结束时间]').setValue('2026-10-20T18:00')
    await wrapper.get('[aria-label=请假原因]').setValue('家庭事务')
    await wrapper.get('[data-testid=save-draft]').trigger('click'); await flushPromises()
    expect(leaveApi.create).toHaveBeenCalledWith(expect.objectContaining({ reason: '家庭事务', leave_type: 'annual' }))
    expect(leaveApi.submit).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  it('restores a rejected application, edits it and resubmits from precheck', async () => {
    const { wrapper } = await render(LeaveFormView, '/leaves/a1')
    expect(wrapper.get('[aria-label=请假原因]').element).toHaveProperty('value', '家庭事务')
    await wrapper.get('[aria-label=请假原因]').setValue('补充后的原因')
    await wrapper.get('[data-testid=submit-leave]').trigger('click'); await flushPromises()
    expect(leaveApi.patch).toHaveBeenCalledWith('a1', expect.objectContaining({ reason: '补充后的原因' }))
    expect(leaveApi.submit).toHaveBeenCalledWith('a1')
    expect(wrapper.text()).toContain('版本')
    wrapper.unmount()
  })
  it('requests a server-filtered approval inbox and opens current approval', async () => {
    localStorage.setItem('oa_current_user', 'u_mgr_001')
    const { wrapper, router } = await render(ApprovalInboxView, '/approvals')
    expect(taskApi.list).toHaveBeenCalledWith(expect.objectContaining({ inbox: true, scene: 'leave' }))
    expect(wrapper.text()).toContain('李四')
    await wrapper.get('[data-testid=open-task]').trigger('click'); await flushPromises()
    expect(router.currentRoute.value.path).toBe('/leave/t1')
    wrapper.unmount()
  })
  it('recovers messages from the URL and server without browser conversation cache', async () => {
    vi.mocked(threadApi.get).mockResolvedValue({ thread_id: 'history1', scene: 'faq', status: 'COMPLETED',
      messages: [{ role: 'user', summary: '历史问题', seq: 1 }, { role: 'assistant', summary: '历史答复', seq: 2 }] })
    const { wrapper } = await render(AssistantView, '/assistant/history1')
    expect(threadApi.get).toHaveBeenCalledWith('history1')
    expect(wrapper.text()).toContain('历史问题'); expect(wrapper.text()).toContain('历史答复')
    wrapper.unmount()
  })
  it('permits the current built-in approver without a legacy interrupt and sends one idempotent command', async () => {
    localStorage.setItem('oa_current_user', 'u_mgr_001')
    const { wrapper } = await render(LeaveDetailView, '/leave/t1')
    const button = wrapper.findAll('button').find(b => b.text() === '批准当前级')!
    expect(button.attributes('disabled')).toBeUndefined()
    await button.trigger('click'); await button.trigger('click'); await flushPromises()
    expect(leaveApi.decide).toHaveBeenCalledTimes(1)
    expect(leaveApi.decide).toHaveBeenCalledWith('a1', expect.objectContaining({ action: 'approve', idempotency_key: expect.any(String) }))
    wrapper.unmount()
  })
  it('hides admin menus from employees and exposes inbox to approvers', async () => {
    const { wrapper } = await render(App, '/tasks')
    expect(wrapper.text()).toContain('我的请假'); expect(wrapper.text()).toContain('会议文本'); expect(wrapper.text()).not.toContain('智能配置')
    wrapper.unmount()
    localStorage.setItem('oa_current_user', 'u_mgr_002')
    const manager = await render(App, '/tasks')
    expect(manager.wrapper.text()).toContain('审批待办')
    manager.wrapper.unmount()
  })
  it('drops cached conversation when identity changes', async () => {
    setActivePinia(createPinia()); const store = useAssistantStore()
    store.threadId = 'private1'; store.chatLines.push({ role: 'user', content: '私密' }); store.persist()
    localStorage.setItem('oa_current_user', 'u_mgr_001')
    store.$reset()
    expect(store.threadId).toBeNull(); expect(store.chatLines).toEqual([])
  })
  it('updates the URL when starting a new conversation from history', async () => {
    vi.mocked(threadApi.create).mockResolvedValue({ thread_id: 'new1', status: 'CREATED' })
    vi.mocked(threadApi.get).mockResolvedValue({ thread_id: 'old1', scene: 'faq', status: 'COMPLETED', messages: [] })
    const { wrapper, router } = await render(AssistantView, '/assistant/old1')
    await wrapper.findAll('button').find(b => b.text() === '新建会话')!.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/assistant/new1')
    wrapper.unmount()
  })
  it('creates one conversation and sends once when Enter is pressed twice during creation', async () => {
    let resolveCreate!: (value: any) => void
    vi.mocked(threadApi.create).mockReturnValue(new Promise(resolve => { resolveCreate = resolve }))
    vi.mocked(threadApi.get).mockResolvedValue({ thread_id: 'new1', scene: 'faq', status: 'COMPLETED', messages: [] })
    const { wrapper, router } = await render(AssistantView, '/assistant')
    const input = wrapper.get('.input-area input')
    await input.setValue('年假制度是什么？')
    await input.trigger('keyup.enter')
    await input.trigger('keyup.enter')
    expect(threadApi.create).toHaveBeenCalledTimes(1)
    resolveCreate({ thread_id: 'new1', status: 'CREATED' })
    await flushPromises()
    expect(threadApi.sendMessage).toHaveBeenCalledTimes(1)
    expect(threadApi.sendMessage).toHaveBeenCalledWith('new1', { content: '年假制度是什么？' })
    expect(router.currentRoute.value.path).toBe('/assistant/new1')
    wrapper.unmount()
  })
  it('ignores repeated new conversation clicks while creation is pending', async () => {
    let resolveCreate!: (value: any) => void
    vi.mocked(threadApi.create).mockReturnValue(new Promise(resolve => { resolveCreate = resolve }))
    const { wrapper } = await render(AssistantView, '/assistant')
    const button = wrapper.findAll('button').find(b => b.text() === '新建会话')!
    await button.trigger('click'); await button.trigger('click')
    expect(threadApi.create).toHaveBeenCalledTimes(1)
    resolveCreate({ thread_id: 'new1', status: 'CREATED' })
    await flushPromises()
    wrapper.unmount()
  })
  it('uploads a real file to a saved draft and keeps pending scans unavailable for download', async () => {
    vi.mocked(leaveApi.uploadAttachment).mockResolvedValue({ attachment_id: 'file1', filename: 'proof.png', scan_status: 'PENDING', size_bytes: 12, content_type: 'image/png', sha256: 'abc' })
    const { wrapper } = await render(LeaveFormView, '/leaves/a1')
    const file = new File(['real bytes'], 'proof.png', { type: 'image/png' })
    const input = wrapper.get('[aria-label=上传证明材料]')
    Object.defineProperty(input.element, 'files', { value: [file] })
    await input.trigger('change'); await flushPromises()
    expect(leaveApi.uploadAttachment).toHaveBeenCalledWith('a1', file)
    expect(wrapper.text()).toContain('proof.png')
    expect(wrapper.text()).toContain('待扫描')
    expect(wrapper.findAll('button').find(b => b.text() === '下载')!.attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })
  it('refreshes attachment status after rescan and retains uploaded references when saving', async () => {
    vi.mocked(leaveApi.attachments).mockResolvedValue([{ attachment_id: 'file1', filename: 'proof.png', scan_status: 'PENDING', size_bytes: 12, content_type: 'image/png', sha256: 'abc' }])
    vi.mocked(leaveApi.scanAttachment).mockResolvedValue({ attachment_id: 'file1', filename: 'proof.png', scan_status: 'CLEAN', size_bytes: 12, content_type: 'image/png', sha256: 'abc' })
    const { wrapper } = await render(LeaveFormView, '/leaves/a1')
    await wrapper.findAll('button').find(b => b.text() === '重新扫描')!.trigger('click'); await flushPromises()
    expect(leaveApi.scanAttachment).toHaveBeenCalledWith('a1', 'file1')
    expect(wrapper.text()).toContain('扫描通过')
    await wrapper.get('[data-testid=save-draft]').trigger('click'); await flushPromises()
    expect(leaveApi.patch).toHaveBeenCalledWith('a1', expect.objectContaining({ attachments: ['file1'] }))
    wrapper.unmount()
  })
})
