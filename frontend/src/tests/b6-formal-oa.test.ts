import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import ReimbursementView from '@/views/ReimbursementWorkbenchView.vue'
import TicketView from '@/views/TicketFormalWorkbenchView.vue'
import NotificationView from '@/views/NotificationWorkbenchView.vue'
import { oaApi } from '@/api/oa'
import { authState } from '@/stores/auth'

vi.mock('@/api/oa', () => ({ oaApi: {
  reimbursements: vi.fn(), reimbursement: vi.fn(), workflows: vi.fn(), saveReimbursement: vi.fn(), createReimbursement: vi.fn(), submitReimbursement: vi.fn(), withdrawReimbursement: vi.fn(), archiveReimbursement: vi.fn(), uploadReimbursement: vi.fn(),
  tickets: vi.fn(), ticket: vi.fn(), prepareTicket: vi.fn(), createTicket: vi.fn(), handleTicket: vi.fn(),
  notifications: vi.fn(), readNotification: vi.fn(), deliveries: vi.fn(), retryDelivery: vi.fn(), contact: vi.fn(), saveContact: vi.fn(),
} }))

const reimbursement = { id: 'rb-1', scene: 'reimbursement', business_no: 'BX-001', applicant_id: 'employee', department_id: 'dept', workflow_definition_id: 'wf-rb', revision: 2, submission_version: 0, state: 'DRAFT', fields: { purpose: '客户拜访交通费', expense_date: '2026-10-18', category: '交通', amount: '128.50', currency: 'CNY', attachment_ids: [] }, allowed_actions: ['edit', 'submit', 'upload'], attachments: [], history: [], versions: [] }
const ticket = { id: 'tk-1', business_no: 'TK-001', applicant_id: 'employee', department_id: 'dept', summary: '无法登录系统', category: '系统故障', priority: 'high', impact: '个人', state: 'OPEN', revision: 1, queue: 'IT', assignee_id: null, allowed_actions: ['handle'], merged_requests: [], feedback: [] }
const notification = { id: 'n-1', title: '报销已提交', body: '你的报销已进入审批', source_kind: 'reimbursement', created_at: '2026-10-19T08:00:00Z', read_at: null, inbox_state: 'ACCEPTED', smtp_state: 'UNKNOWN' }

function setIdentity(perms: any[] = [{ resource: 'reimbursement', action: 'read', scope: 'self' }, { resource: 'reimbursement', action: 'write', scope: 'self' }, { resource: 'ticket', action: 'read', scope: 'self' }, { resource: 'notification', action: 'read', scope: 'self' }]) {
  Object.assign(authState, { provider: 'builtin', manualOA: true, aiEnabled: true, user: { user_id: 'employee', display_name: '员工', roles: [], depts: ['dept'], permissions: perms } })
}
async function render(component: any, path: string) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/oa/:pathMatch(.*)*', component }] })
  await router.push(path); await router.isReady()
  const wrapper = mount(component, { global: { plugins: [router, ElementPlus], stubs: { transition: false, 'el-dialog': { template: '<div class="el-dialog"><slot /></div>' } } } })
  await flushPromises(); return wrapper
}
beforeEach(() => {
  vi.clearAllMocks(); setIdentity()
  vi.mocked(oaApi.reimbursements).mockResolvedValue([structuredClone(reimbursement)] as any); vi.mocked(oaApi.reimbursement).mockResolvedValue(structuredClone(reimbursement) as any); vi.mocked(oaApi.workflows).mockResolvedValue([{ id: 'wf-rb', name: '费用审批', published_version: 1, form: { reason_max_length: 2000 } }] as any)
  vi.mocked(oaApi.tickets).mockResolvedValue([structuredClone(ticket)] as any); vi.mocked(oaApi.ticket).mockResolvedValue(structuredClone(ticket) as any); vi.mocked(oaApi.notifications).mockResolvedValue([structuredClone(notification)] as any); vi.mocked(oaApi.contact).mockResolvedValue({ user_id: 'employee', email: '', enabled: false })
})

describe('B6 formal OA workbenches', () => {
  it('群通知拦截与合并原因使用中文展示', async () => {
    setIdentity([{resource:'notification',action:'read',scope:'self'},{resource:'notification_admin',action:'read',scope:'department'}])
    const codes=['wecom_policy_blocked','wecom_history_isolated','wecom_event_merged','wecom_nudge_cooldown','wecom_group_interval','wecom_probe_cleanup']
    vi.mocked(oaApi.deliveries).mockResolvedValue(codes.map((last_code,index)=>({id:String(index),notification_id:'n',recipient_id:'employee',channel:'wecom',state:'CANCELLED',attempt_count:0,last_code,next_attempt_at:null,reviews:[]})))
    const wrapper=await render(NotificationView,'/oa/notifications')
    await wrapper.get('[id$="-delivery"]').trigger('click');await flushPromises()
    for (const text of ['不在群通知白名单内','历史消息已隔离','同一事件已合并','不足两小时','等待合并发送','测试已结束']) expect(wrapper.text()).toContain(text)
    for (const code of codes) expect(wrapper.text()).not.toContain(code)
    wrapper.unmount()
  })
  it('企微授权独立于邮件，保存时不清空现有邮箱', async () => {
    vi.mocked(oaApi.contact).mockResolvedValue({user_id:'employee',email:'existing@example.test',enabled:false,wecom_enabled:false,wecom_available:true})
    vi.mocked(oaApi.saveContact).mockResolvedValue({result:{}} as any)
    const wrapper=await render(NotificationView,'/oa/notifications')
    await wrapper.get('[id$="-contact"]').trigger('click');await flushPromises()
    await wrapper.get('[aria-label="授权企业微信群提醒"]').trigger('click')
    await wrapper.findAll('button').find(button=>button.text().includes('保存授权配置'))!.trigger('click');await flushPromises()
    expect(oaApi.saveContact).toHaveBeenCalledWith('employee',expect.objectContaining({email:'existing@example.test',enabled:false,wecom_enabled:true}))
    wrapper.unmount()
  })
  it('未接通部门显示禁用状态，保存失败保留错误', async () => {
    vi.mocked(oaApi.saveContact).mockRejectedValue(new Error('保存失败'))
    const wrapper=await render(NotificationView,'/oa/notifications')
    await wrapper.get('[id$="-contact"]').trigger('click');await flushPromises()
    expect(wrapper.get('[aria-label="授权企业微信群提醒"]').attributes('aria-disabled')).toBe('true')
    await wrapper.findAll('button').find(button=>button.text().includes('保存授权配置'))!.trigger('click');await flushPromises()
    expect(wrapper.text()).toContain('保存失败')
    wrapper.unmount()
  })
  it('投递状态区分邮件和企微并显示中文结果', async () => {
    setIdentity([{resource:'notification_admin',action:'read',scope:'dept'}])
    vi.mocked(oaApi.deliveries).mockResolvedValue([{id:'d',notification_id:'n',recipient_id:'employee',channel:'wecom',state:'UNKNOWN',attempt_count:1,last_code:'wecom_unknown',next_attempt_at:null,reviews:[]}])
    const wrapper=await render(NotificationView,'/oa/notifications')
    await wrapper.get('[id$="-delivery"]').trigger('click');await flushPromises()
    expect(wrapper.text()).toContain('企业微信')
    expect(wrapper.text()).toContain('结果不明，需人工核对')
    expect(wrapper.text()).not.toContain('wecom_unknown')
    wrapper.unmount()
  })
  it('从助手链接进入正式工单时加载并选中目标工单，切换地址重新核验权限', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes: [
      { path: '/oa/tickets/:ticketId?', component: TicketView },
    ] })
    await router.push('/oa/tickets/tk-1')
    const wrapper = mount(TicketView, { global: { plugins: [router, ElementPlus] } })
    await flushPromises()
    expect(oaApi.ticket).toHaveBeenCalledWith('tk-1')
    expect(wrapper.findAll('h2').some(item => item.text() === 'TK-001')).toBe(true)
    vi.mocked(oaApi.ticket).mockRejectedValueOnce(new Error('无权查看此工单'))
    await router.push('/oa/tickets/other-ticket')
    await flushPromises()
    expect(oaApi.ticket).toHaveBeenCalledWith('other-ticket')
    expect(wrapper.text()).toContain('无权查看此工单')
    expect(wrapper.findAll('h2').some(item => item.text() === 'TK-001')).toBe(false)
    wrapper.unmount()
  })
  it('工单请求失败后用相同操作编号重试，修改内容需要重新确认', async () => {
    vi.mocked(oaApi.prepareTicket).mockResolvedValue({confirmation_id:'confirm-retry',duplicate_candidates:[]})
    vi.mocked(oaApi.createTicket).mockRejectedValue(new Error('响应中断'))
    const wrapper=await render(TicketView,'/oa/tickets')
    await wrapper.findAll('button').find(button=>button.text().includes('新建工单'))!.trigger('click');await flushPromises()
    const dialog=wrapper.find('.el-dialog')
    await dialog.find('textarea').setValue('需要人工协助')
    await dialog.findAll('button').find(button=>button.text().includes('检查重复工单'))!.trigger('click');await flushPromises()
    for(let i=0;i<2;i++){
      await dialog.findAll('button').find(button=>button.text().includes('确认创建工单'))!.trigger('click');await flushPromises()
    }
    expect(oaApi.createTicket).toHaveBeenCalledTimes(2)
    expect(vi.mocked(oaApi.createTicket).mock.calls[0]![0].operation_id).toBe(vi.mocked(oaApi.prepareTicket).mock.calls[0]![0].operation_id)
    expect(vi.mocked(oaApi.createTicket).mock.calls[0]![0].operation_id).toBe(vi.mocked(oaApi.createTicket).mock.calls[1]![0].operation_id)
    await dialog.find('textarea').setValue('修改后需要重新确认');await flushPromises()
    expect(dialog.text()).toContain('检查重复工单')
    expect(dialog.text()).not.toContain('确认创建工单')
    wrapper.unmount()
  })
  it('loads, saves, uploads, and submits a reimbursement draft', async () => {
    let current = structuredClone(reimbursement)
    vi.mocked(oaApi.reimbursements).mockImplementation(async () => [structuredClone(current)] as any)
    vi.mocked(oaApi.reimbursement).mockImplementation(async () => structuredClone(current) as any)
    const saved = { ...structuredClone(reimbursement), revision: 3, fields: { ...reimbursement.fields, purpose: '更新后的交通费' } }
    const submitted = { ...saved, revision: 4, submission_version: 1, state: 'IN_REVIEW', allowed_actions: ['withdraw'] }
    vi.mocked(oaApi.saveReimbursement).mockImplementation(async () => { current = structuredClone(saved); return { result: saved } as any })
    vi.mocked(oaApi.submitReimbursement).mockImplementation(async () => { current = structuredClone(submitted); return { result: submitted } as any })
    vi.mocked(oaApi.uploadReimbursement).mockResolvedValue({ result: { revision: 3, attachment: { id: 'att-1', filename: '发票.pdf', scan_status: 'CLEAN' } } } as any)
    const wrapper = await render(ReimbursementView, '/oa/reimbursements')
    expect(wrapper.text()).toContain('BX-001')
    await wrapper.get('.oa-list-item').trigger('click'); await flushPromises()
    await wrapper.find('textarea').setValue('更新后的交通费')
    await wrapper.findAll('button').find(button => button.text().includes('保存草稿'))!.trigger('click'); await flushPromises()
    expect(oaApi.saveReimbursement).toHaveBeenCalledWith('rb-1', expect.objectContaining({ expected_revision: 2, fields: expect.objectContaining({ purpose: '更新后的交通费' }) }))
    const file = new File(['invoice'], 'invoice.pdf', { type: 'application/pdf' })
    const input = wrapper.get('input[type=file]').element as HTMLInputElement
    Object.defineProperty(input, 'files', { value: [file] })
    await wrapper.get('input[type=file]').trigger('change'); await flushPromises()
    expect(oaApi.uploadReimbursement).toHaveBeenCalledWith('rb-1', expect.any(FormData))
    await wrapper.findAll('button').find(button => button.text().includes('提交审批'))!.trigger('click'); await flushPromises()
    expect(oaApi.submitReimbursement).toHaveBeenCalledWith('rb-1', expect.objectContaining({ expected_revision: 3, requested_submission_version: 1 }))
    wrapper.unmount()
  })
  it('checks duplicate tickets before creating and sends the confirmation id', async () => {
    vi.mocked(oaApi.prepareTicket).mockResolvedValue({ confirmation_id: 'confirm-1', duplicate_candidates: [{ id: 'tk-old', summary: '旧登录问题', score: 0.82 }] })
    vi.mocked(oaApi.createTicket).mockResolvedValue({ result: { ...ticket, id: 'tk-2', business_no: 'TK-002' } } as any)
    const wrapper = await render(TicketView, '/oa/tickets')
    await wrapper.findAll('button').find(button => button.text().includes('新建工单'))!.trigger('click'); await flushPromises()
    const dialog = wrapper.find('.el-dialog'); await dialog.find('textarea').setValue('重复登录问题')
    await dialog.findAll('button').find(button => button.text().includes('检查重复工单'))!.trigger('click'); await flushPromises()
    expect(oaApi.prepareTicket).toHaveBeenCalledWith(expect.objectContaining({ summary: '重复登录问题' }))
    await dialog.findAll('button').find(button => button.text().includes('确认创建工单'))!.trigger('click'); await flushPromises()
    expect(oaApi.createTicket).toHaveBeenCalledWith(expect.objectContaining({ confirmation_id: 'confirm-1', summary: '重复登录问题', operation_id: expect.any(String) }))
    wrapper.unmount()
  })
  it('handles a ticket and gates delivery list by notification permission', async () => {
    setIdentity([{ resource: 'ticket', action: 'read', scope: 'self' }, { resource: 'ticket_handle', action: 'read', scope: 'dept' }, { resource: 'ticket_handle', action: 'write', scope: 'dept' }, { resource: 'notification', action: 'read', scope: 'self' }])
    vi.mocked(oaApi.handleTicket).mockResolvedValue({ result: { ...ticket, state: 'RESOLVED', revision: 2 } } as any)
    const wrapper = await render(TicketView, '/oa/tickets'); await wrapper.findAll('button').find(button => button.text().includes('工单处理列表'))!.trigger('click'); await flushPromises(); await wrapper.find('.oa-list-item').trigger('click'); await wrapper.find('textarea').setValue('已恢复登录'); await wrapper.findAll('button').find(button => button.text().includes('领取'))!.trigger('click'); await flushPromises()
    expect(oaApi.handleTicket).toHaveBeenCalledWith('tk-1', expect.objectContaining({ action: 'claim' })); wrapper.unmount()
    setIdentity([{ resource: 'notification', action: 'read', scope: 'self' }]); const notificationWrapper = await render(NotificationView, '/oa/notifications'); expect(notificationWrapper.text()).toContain('报销已提交'); await notificationWrapper.findAll('button').find(button => button.text().includes('标记已读'))!.trigger('click'); await flushPromises(); expect(oaApi.readNotification).toHaveBeenCalledWith('n-1'); expect(oaApi.deliveries).not.toHaveBeenCalled(); notificationWrapper.unmount()
  })
})
