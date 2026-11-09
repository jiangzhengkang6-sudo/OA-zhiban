import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { webcrypto } from 'node:crypto'
import MeetingTranscription from '@/components/MeetingTranscription.vue'
import { meetingTranscriptionApi as api, type TranscriptionStatus } from '@/api/meetingTranscription'
import { authState, clearSession } from '@/stores/auth'

vi.mock('@/api/meetingTranscription', () => ({ meetingTranscriptionApi: { get: vi.fn(), command: vi.fn() } }))
const initial: TranscriptionStatus = { configured: true, state: 'NOT_STARTED', notice: '请核对记录范围', message: '',
  partial: true, expired: false, can_start: true, can_stop: false, can_retry: false, minutes_id: null,
  utterances: [], utterance_count: 0 }
let wrapper: VueWrapper | undefined
beforeEach(() => {
  vi.useFakeTimers(); vi.resetAllMocks(); vi.stubGlobal('crypto', webcrypto)
  vi.mocked(api.get).mockResolvedValue({ ...initial })
  vi.mocked(api.command).mockResolvedValue({})
  vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals() })
async function open() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:pathMatch(.*)*', component: { template: '<div />' } }] })
  await router.push('/meeting-events/event')
  wrapper = mount(MeetingTranscription, { props: { meetingId: 'event', revision: 3, meetingState: 'IN_PROGRESS' },
    global: { plugins: [ElementPlus, router] } })
  await flushPromises()
  return wrapper
}
async function click(text: string) {
  const button = wrapper!.findAll('button').find(button => button.text().includes(text))!
  await button.trigger('click'); await flushPromises()
}
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}
it('requires consent and cancelling confirmation never starts cloud transcription', async () => {
  await open()
  expect(wrapper!.findAll('button').find(b => b.text().includes('开启转写'))!.attributes('disabled')).toBeDefined()
  await wrapper!.get('input[type=checkbox]').setValue(true)
  vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce('cancel')
  await click('开启转写')
  expect(api.command).not.toHaveBeenCalled()
})
it('opens only one confirmation and sends explicit consent once', async () => {
  const confirm = deferred<any>()
  vi.mocked(ElMessageBox.confirm).mockReturnValueOnce(confirm.promise)
  await open(); await wrapper!.get('input[type=checkbox]').setValue(true)
  await click('开启转写'); await click('开启转写')
  expect(ElMessageBox.confirm).toHaveBeenCalledTimes(1)
  confirm.resolve('confirm'); await flushPromises()
  await vi.waitFor(() => expect(api.command).toHaveBeenCalledTimes(1))
  expect(api.command).toHaveBeenCalledWith('event', 'start', expect.objectContaining({ consent: true, expected_revision: 3 }))
})
it('reuses its operation id when a stop response is lost', async () => {
  vi.mocked(api.get).mockResolvedValue({ ...initial, state: 'ACTIVE', can_start: false, can_stop: true })
  vi.mocked(api.command).mockRejectedValueOnce(new Error('网络中断')).mockResolvedValueOnce({})
  await open(); await click('停止转写'); await click('停止转写')
  expect(api.command).toHaveBeenCalledTimes(2)
  expect(vi.mocked(api.command).mock.calls[0]![2].operation_id).toBe(vi.mocked(api.command).mock.calls[1]![2].operation_id)
})
it('does not let an older refresh overwrite the newest transcription', async () => {
  const old = deferred<TranscriptionStatus>()
  await open()
  vi.mocked(api.get).mockReturnValueOnce(old.promise).mockResolvedValueOnce({ ...initial, message: '较新的记录' })
  await wrapper!.get('button[aria-label="刷新转写状态"]').trigger('click')
  await wrapper!.get('button[aria-label="刷新转写状态"]').trigger('click'); await flushPromises()
  old.resolve({ ...initial, message: '过期的记录' }); await flushPromises()
  expect(wrapper!.text()).toContain('较新的记录')
  expect(wrapper!.text()).not.toContain('过期的记录')
})
it('clears private sentences on an authorization change and ignores the old response', async () => {
  const old = deferred<TranscriptionStatus>(), fresh = deferred<TranscriptionStatus>()
  vi.mocked(api.get).mockResolvedValueOnce({ ...initial, utterances: [{ id: 'one', speaker: '张翔', start_ms: 1000,
    end_ms: 2000, text: '受限会议内容', late: false }], utterance_count: 1 })
  await open(); expect(wrapper!.text()).toContain('受限会议内容')
  vi.mocked(api.get).mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise)
  await wrapper!.get('button[aria-label="刷新转写状态"]').trigger('click')
  authState.authorizationRevision++; await flushPromises()
  expect(wrapper!.text()).not.toContain('受限会议内容')
  old.resolve({ ...initial, message: '旧账号内容' }); await flushPromises()
  expect(wrapper!.text()).not.toContain('旧账号内容')
  fresh.resolve({ ...initial, can_start: false }); await flushPromises()
})
it('does not start if the session changes while consent confirmation is open', async () => {
  const confirm = deferred<any>()
  vi.mocked(ElMessageBox.confirm).mockReturnValueOnce(confirm.promise)
  await open(); await wrapper!.get('input[type=checkbox]').setValue(true); await click('开启转写')
  clearSession(); await flushPromises(); confirm.resolve('confirm'); await flushPromises()
  expect(api.command).not.toHaveBeenCalled()
})
it('renders read-only notices and late labels without management controls', async () => {
  vi.mocked(api.get).mockResolvedValue({ ...initial, state: 'DRAFT_READY', can_start: false, message: '草稿待审阅',
    utterance_count: 1, utterances: [{ id: 'late', speaker: '记录人', start_ms: 1000, end_ms: 2000, text: '补充讨论', late: true }] })
  await open()
  expect(wrapper!.text()).toContain('未纳入当前纪要')
  expect(wrapper!.text()).toContain('请核对记录范围')
  expect(wrapper!.find('input[type=checkbox]').exists()).toBe(false)
  expect(wrapper!.text()).not.toContain('停止转写')
})
it('polls every five seconds and stops polling after unmount', async () => {
  await open(); expect(api.get).toHaveBeenCalledTimes(1)
  await vi.advanceTimersByTimeAsync(5000); await flushPromises()
  expect(api.get).toHaveBeenCalledTimes(2)
  wrapper!.unmount(); wrapper = undefined
  await vi.advanceTimersByTimeAsync(15000); await flushPromises()
  expect(api.get).toHaveBeenCalledTimes(2)
})
