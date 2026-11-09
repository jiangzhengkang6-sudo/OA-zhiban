import { beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox, type MessageBoxData } from 'element-plus'
import View from '@/views/PublicMailboxView.vue'
import { publicMailApi as api } from '@/api/publicMail'
import { authState } from '@/stores/auth'

const push = vi.hoisted(() => vi.fn())
vi.mock('vue-router', () => ({ useRouter: () => ({ push }), onBeforeRouteLeave: vi.fn() }))
vi.mock('@/api/publicMail', () => ({ publicMailApi: Object.fromEntries(
  ['status', 'list', 'get', 'save', 'action', 'sync', 'import', 'task', 'members', 'saveMembers'].map(k => [k, vi.fn()])) }))
vi.mock('@/stores/auth', () => ({ can: () => true, authState: { aiEnabled: true } }))
vi.mock('@/api/draftCommands', () => ({ replayable: vi.fn(async (_scope, _payload, command) => command('stable-key')) }))
const status = { authorized: true, provisioned: true, enabled: true, can_setup: false, id: 'box', name: '综合办公公共邮箱',
  address: 'office@example.com', user_id: 'u1', revision: 1, can_process: true, can_send: true, can_manage: true }
const message = { id: 'm1', subject: '验收邮件', sender: 'client@example.com', recipients: ['office@example.com'],
  body: '请准备报告', direction: 'incoming', status: 'NEW', version: 1, attachments: [], claimed_by: null }
beforeEach(() => {
  vi.clearAllMocks()
  authState.aiEnabled = true
  vi.mocked(api.status).mockResolvedValue(status)
  vi.mocked(api.list).mockResolvedValue({ items: [message], total: 1, page: 1 } as any)
  vi.mocked(api.get).mockResolvedValue(message as any)
})
function mounted() { return mount(View, { global: { plugins: [ElementPlus] } }) }
it('read-only members can read but cannot compose, sync, manage or convert', async () => {
  vi.mocked(api.status).mockResolvedValue({ ...status, can_process: false, can_send: false, can_manage: false })
  const w = mounted(); await flushPromises()
  await w.get('.mail-list-row').trigger('click'); await flushPromises()
  expect(w.text()).toContain('请准备报告')
  for (const label of ['写邮件', '同步收信', '录入并分析', '转为任务', '回复']) expect(w.text()).not.toContain(label)
  expect(w.find('[aria-label="成员授权"]').exists()).toBe(false)
  w.unmount()
})
it('requires saving a draft and explicit confirmation before sending', async () => {
  const w = mounted(); await flushPromises()
  await w.findAll('button').find(b => b.text() === '写邮件')!.trigger('click')
  await w.get('[aria-label="邮件收件人"]').setValue('receiver@example.com')
  await w.get('[aria-label="邮件主题"]').setValue('测试主题')
  await w.get('[aria-label="邮件正文"]').setValue('测试正文')
  expect(w.get('[data-testid="send-public-mail"]').attributes('disabled')).toBeDefined()
  const saved = { ...message, direction: 'outgoing', status: 'DRAFT', subject: '测试主题', body: '测试正文', recipients: ['receiver@example.com'], reply_to_id: null }
  vi.mocked(api.save).mockResolvedValue(saved as any)
  await w.get('[data-testid="save-public-draft"]').trigger('click'); await flushPromises()
  expect(api.save).toHaveBeenCalledOnce()
  const confirm = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as MessageBoxData)
  vi.mocked(api.action).mockResolvedValue({ ...saved, status: 'ACCEPTED', version: 3 } as any)
  await w.get('[data-testid="send-public-mail"]').trigger('click'); await flushPromises()
  expect(confirm).toHaveBeenCalledOnce()
  expect(api.action).toHaveBeenCalledWith('m1', { action: 'send', expected_version: 1, confirmed: true })
  expect(w.text()).toContain('邮件服务器已接收')
  confirm.mockRestore(); w.unmount()
})
it('opens existing analysis without importing it again', async () => {
  vi.mocked(api.get).mockResolvedValue({ ...message, analysis_id: 'email-1', claimed_by: 'someone-else' } as any)
  const w = mounted(); await flushPromises()
  await w.get('.mail-list-row').trigger('click'); await flushPromises()
  await w.findAll('button').find(b => b.text() === '查看分析')!.trigger('click'); await flushPromises()
  expect(push).toHaveBeenCalledWith('/emails/email-1')
  expect(api.import).not.toHaveBeenCalled()
  w.unmount()
})
it('keeps normal mail controls and hides analysis while AI is disabled', async () => {
  authState.aiEnabled = false
  const w = mounted(); await flushPromises()
  await w.get('.mail-list-row').trigger('click'); await flushPromises()
  expect(w.text()).toContain('写邮件')
  expect(w.text()).toContain('同步收信')
  expect(w.text()).not.toContain('分析记录')
  expect(w.text()).not.toContain('录入并分析')
  w.unmount()
})
