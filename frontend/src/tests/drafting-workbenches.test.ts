import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import { ElMessageBox } from 'element-plus'
import DocumentView from '@/views/DocumentView.vue'
import EmailView from '@/views/EmailView.vue'
import { documentApi } from '@/api/document'
import { emailApi } from '@/api/email'
import { commandKey, releaseCommandKey } from '@/api/draftCommands'

vi.mock('@/api/document', () => ({ documentApi: { get: vi.fn(), list: vi.fn(), templates: vi.fn(), versions: vi.fn(),
  create: vi.fn(), generate: vi.fn(), save: vi.fn(), decide: vi.fn(), retry: vi.fn() } }))
vi.mock('@/api/email', () => ({ emailApi: { get: vi.fn(), list: vi.fn(), versions: vi.fn(),
  create: vi.fn(), analyze: vi.fn(), save: vi.fn(), decide: vi.fn(), retry: vi.fn() } }))
vi.mock('@/api/draftCommands', () => ({ commandKey: vi.fn(async () => 'stable-key'), releaseCommandKey: vi.fn() }))

const actions = ['edit', 'confirm', 'reject', 'regenerate']
const document = { document_id: 'DOC-1', thread_id: 't1', subject: '通知', status: 'DRAFT_READY', version: 1,
  available_actions: actions, template: { id: 'notice', name: '通知', kind: 'notice', version: 1, sections: ['通知事项'] },
  recipient: '项目组', deadline: '周五', classification: 'internal', distribution: '项目组',
  sources: [{ ref: 'input:1', title: '提交材料', content: '验收材料', source_location: 'input', content_hash: 'hash', kind: 'input' }],
  draft: { body: '# 通知\n## 通知事项\n验收', source_refs: ['input:1'] }, checks: [], external_writes: false }
const email = { email_id: 'MAIL-1', thread_id: 't2', subject: '验收邮件', status: 'DRAFT_READY', version: 1,
  available_actions: actions, sender: 'a@test.com', recipients: ['b@test.com'], body: '请提交验收材料',
  external_contact: true, attachments: [], sources: [{ ref: 'line:1', text: '请提交验收材料', locator: 'line:1', content_hash: 'hash' }],
  draft: { category: 'work', priority: 'normal', summary: '验收', reply_subject: 'Re: 验收', reply_body: '收到', source_refs: ['line:1'], action_items: [] },
  checks: [{ code: 'EXTERNAL_CONTACT', severity: 'warning', message: '外部联系人' }], secondary_confirmation_required: true, external_writes: false }

async function render(component: any, prefix: string, path: string) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: `/${prefix}/:id?`, component }] })
  await router.push(path); await router.isReady()
  const wrapper = mount({ template: '<router-view />' }, { global: { plugins: [router, ElementPlus] } })
  await flushPromises()
  return { wrapper, router }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(documentApi.get).mockResolvedValue(structuredClone(document) as any)
  vi.mocked(documentApi.list).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 })
  vi.mocked(documentApi.templates).mockResolvedValue([document.template])
  vi.mocked(documentApi.versions).mockResolvedValue([{ version: 1, draft: document.draft, checks: [], edited_by: null, created_at: '' }])
  vi.mocked(documentApi.save).mockResolvedValue({ ...document, version: 2, status: 'REVIEWING' } as any)
  vi.mocked(documentApi.decide).mockResolvedValue({ ...document, status: 'CONFIRMED', available_actions: [] } as any)
  vi.mocked(emailApi.get).mockResolvedValue(structuredClone(email) as any)
  vi.mocked(emailApi.list).mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 })
  vi.mocked(emailApi.versions).mockResolvedValue([{ version: 1, draft: email.draft, checks: [], edited_by: null, created_at: '' }] as any)
  vi.mocked(emailApi.save).mockResolvedValue({ ...email, version: 2, status: 'REVIEWING' } as any)
  vi.mocked(emailApi.decide).mockResolvedValue({ ...email, status: 'CONFIRMED', available_actions: [] } as any)
})

describe('document review', () => {
  it('creates a document and opens its generated record despite the busy route guard', async () => {
    vi.mocked(documentApi.create).mockResolvedValue({ ...document, status: 'CREATED', version: null, draft: null, available_actions: ['generate'] } as any)
    const { wrapper, router } = await render(DocumentView, 'documents', '/documents')
    await wrapper.get('input[aria-label="标题"]').setValue('创建验收')
    await wrapper.get('input[aria-label="接收对象"]').setValue('项目组')
    await wrapper.get('textarea[aria-label="核心要点"]').setValue('验收材料')
    await wrapper.get('input[aria-label="分发范围"]').setValue('内部')
    await wrapper.get('[data-testid=create-draft]').trigger('click'); await flushPromises()
    expect(documentApi.create).toHaveBeenCalledOnce()
    expect(router.currentRoute.value.path).toBe('/documents/DOC-1')
    expect(documentApi.get).toHaveBeenCalledWith('DOC-1')
    wrapper.unmount()
  })

  it('blocks unsaved edits and requires metadata before confirming the saved version', async () => {
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    const { wrapper } = await render(DocumentView, 'documents', '/documents/DOC-1')
    expect(wrapper.text()).toContain('验收材料')
    await wrapper.get('[data-testid=draft-body] textarea').setValue('# 通知\n## 通知事项\n修订')
    expect(wrapper.get('[data-testid=confirm-draft]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-testid=save-draft]').trigger('click'); await flushPromises()
    expect(documentApi.save).toHaveBeenCalledWith('DOC-1', expect.objectContaining({ expected_version: 1 }))
    expect(wrapper.get('[data-testid=confirm-draft]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-testid=metadata-confirmed] input').setValue(true)
    await wrapper.get('[data-testid=confirm-draft]').trigger('click'); await flushPromises()
    expect(documentApi.decide).toHaveBeenCalledWith('DOC-1', expect.objectContaining({ expected_version: 2, metadata_confirmed: true }))
    confirm.mockRestore(); wrapper.unmount()
  })

  it('ignores a stale response after navigation and offers no create on a missing detail', async () => {
    let resolveOld!: (value: any) => void
    vi.mocked(documentApi.get).mockImplementation(id => id === 'A' ? new Promise(resolve => { resolveOld = resolve })
      : Promise.resolve({ ...document, document_id: 'B', subject: '文档 B' } as any))
    const { wrapper, router } = await render(DocumentView, 'documents', '/documents/A')
    await router.push('/documents/B'); await flushPromises()
    resolveOld({ ...document, document_id: 'A', subject: '文档 A' }); await flushPromises()
    expect(wrapper.text()).toContain('文档 B'); expect(wrapper.text()).not.toContain('文档 A')
    vi.mocked(documentApi.get).mockRejectedValue(new Error('无权访问'))
    await router.push('/documents/missing'); await flushPromises()
    expect(wrapper.text()).toContain('无权访问')
    expect(wrapper.find('[data-testid=create-draft]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('preserves edits and command keys on a failed save, and cancels dirty navigation and reload', async () => {
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockRejectedValue('cancel')
    vi.mocked(documentApi.save).mockRejectedValueOnce(new Error('版本冲突，请核对历史'))
    const { wrapper, router } = await render(DocumentView, 'documents', '/documents/DOC-1')
    const editor = wrapper.get('[data-testid=draft-body] textarea')
    await editor.setValue('# 通知\n## 通知事项\n保留未保存的修改')
    await wrapper.get('[data-testid=save-draft]').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('版本冲突')
    expect(releaseCommandKey).not.toHaveBeenCalled()
    expect(commandKey).toHaveBeenCalledWith('document-edit', expect.objectContaining({ expected_version: 1 }))
    await router.push('/documents'); await flushPromises()
    expect(router.currentRoute.value.path).toBe('/documents/DOC-1')
    await wrapper.findAll('button').find(button => button.text() === '重新加载')!.trigger('click'); await flushPromises()
    expect((editor.element as HTMLTextAreaElement).value).toContain('保留未保存的修改')
    expect(documentApi.get).toHaveBeenCalledTimes(1)
    await wrapper.get('[data-testid=save-draft]').trigger('click'); await flushPromises()
    expect(documentApi.save).toHaveBeenCalledTimes(2)
    expect(releaseCommandKey).toHaveBeenCalledOnce()
    confirm.mockRestore(); wrapper.unmount()
  })

  it('shows immutable history and hides commands on a terminal record', async () => {
    vi.mocked(documentApi.get).mockResolvedValue({ ...document, status: 'CONFIRMED', available_actions: [] } as any)
    const { wrapper } = await render(DocumentView, 'documents', '/documents/DOC-1')
    expect(wrapper.text()).toContain('已确认')
    expect(wrapper.text()).toContain('版本比较')
    expect(wrapper.find('[data-testid=confirm-draft]').exists()).toBe(false)
    expect(wrapper.find('[data-testid=save-draft]').exists()).toBe(false)
    expect(wrapper.get('[data-testid=draft-body] textarea').attributes('disabled')).toBeDefined()
    expect(documentApi.versions).toHaveBeenCalledWith('DOC-1')
    wrapper.unmount()
  })
})

describe('mail review', () => {
  it('creates a mail record and navigates to its review', async () => {
    vi.mocked(emailApi.create).mockResolvedValue(email as any)
    const { wrapper, router } = await render(EmailView, 'emails', '/emails')
    await wrapper.get('input[aria-label="主题"]').setValue('验收邮件')
    await wrapper.get('input[aria-label="发件人"]').setValue('a@test.com')
    await wrapper.get('textarea[aria-label="收件人"]').setValue('b@test.com; c@test.com')
    await wrapper.get('textarea[aria-label="邮件原文"]').setValue('请核对')
    await wrapper.get('[data-testid=create-draft]').trigger('click'); await flushPromises()
    expect(emailApi.create).toHaveBeenCalledWith(expect.objectContaining({ recipients: ['b@test.com', 'c@test.com'] }))
    expect(router.currentRoute.value.path).toBe('/emails/MAIL-1')
    wrapper.unmount()
  })

  it('requires warning acknowledgment and a separate secondary confirmation', async () => {
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    const { wrapper } = await render(EmailView, 'emails', '/emails/MAIL-1')
    await wrapper.get('[data-testid=metadata-confirmed] input').setValue(true)
    await wrapper.get('[data-testid=warnings-acknowledged] input').setValue(true)
    await wrapper.get('[data-testid=confirm-draft]').trigger('click'); await flushPromises()
    expect(confirm).toHaveBeenCalledTimes(2)
    expect(emailApi.decide).toHaveBeenCalledWith('MAIL-1', expect.objectContaining({ secondary_confirmed: true, expected_version: 1 }))
    confirm.mockRestore(); wrapper.unmount()
  })

  it('blocks confirmation for an unsaved reply and saves a new revision', async () => {
    const { wrapper } = await render(EmailView, 'emails', '/emails/MAIL-1')
    await wrapper.get('[data-testid=draft-body] textarea').setValue('新回复')
    expect(wrapper.get('[data-testid=confirm-draft]').attributes('disabled')).toBeDefined()
    await wrapper.get('[data-testid=save-draft]').trigger('click'); await flushPromises()
    expect(emailApi.save).toHaveBeenCalledWith('MAIL-1', expect.objectContaining({ expected_version: 1, draft: expect.objectContaining({ reply_body: '新回复' }) }))
    wrapper.unmount()
  })
})
