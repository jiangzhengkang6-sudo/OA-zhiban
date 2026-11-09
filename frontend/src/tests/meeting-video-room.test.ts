import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import MeetingVideoRoom from '@/components/MeetingVideoRoom.vue'
import { meetingEventsApi as api, type MeetingEvent } from '@/api/meetingEvents'
import { authState } from '@/stores/auth'

const sdk = vi.hoisted(() => ({ join: vi.fn(), destroy: vi.fn(), exited: undefined as undefined | ((event: any) => void) }))
vi.mock('@tencentcloud/roomkit-web-vue3', () => ({ RoomKit: {
  getInstance: () => ({ setUIConfig: vi.fn(), join: sdk.join, on: (_: string, callback: any) => { sdk.exited = callback; return vi.fn() } }),
  destroyInstance: sdk.destroy,
} }))
vi.mock('@/api/meetingEvents', () => ({ meetingEventsApi: { get: vi.fn(), command: vi.fn(), videoSession: vi.fn() } }))

const active = { id: 'event', state: 'IN_PROGRESS', revision: 3, video_enabled: true, available_actions: [] } as unknown as MeetingEvent
let wrapper: VueWrapper
beforeEach(() => {
  vi.useFakeTimers(); vi.resetAllMocks(); sdk.exited = undefined
  vi.stubGlobal('isSecureContext', true)
  vi.mocked(api.videoSession).mockResolvedValue({ sdkAppId: 1, userId: 'member', userName: 'Member', userSig: 'test', roomId: 'room', password: '123456', expiresAt: new Date(Date.now() + 3600000).toISOString() })
  vi.mocked(api.get).mockResolvedValue({ ...active })
})
afterEach(() => { wrapper?.unmount(); vi.useRealTimers(); vi.unstubAllGlobals() })
async function enter(meeting = active) {
  wrapper = mount(MeetingVideoRoom, { props: { meeting }, global: { plugins: [ElementPlus] } })
  await wrapper.get('button').trigger('click'); await flushPromises()
  expect(sdk.exited).toBeDefined()
}

it('blocks re-entry on room dismissal and keeps syncing until the OA end transaction commits', async () => {
  await enter()
  sdk.exited!({ reason: 'RoomDismiss', roomId: 'room' }); await flushPromises()
  expect(wrapper.get('button').attributes('disabled')).toBeDefined()
  vi.mocked(api.get).mockResolvedValue({ ...active, state: 'ENDED', revision: 4 })
  await vi.advanceTimersByTimeAsync(10000); await flushPromises()
  expect(api.get).toHaveBeenCalledWith('event')
  expect(wrapper.emitted('changed')).toBeTruthy()
  expect(api.command).not.toHaveBeenCalled()
})

it('accepts a concurrent OA end instead of showing a false state-sync error', async () => {
  await enter({ ...active, available_actions: ['end'] })
  vi.mocked(api.get).mockResolvedValueOnce({ ...active }).mockResolvedValue({ ...active, state: 'ENDED', revision: 4 })
  vi.mocked(api.command).mockRejectedValue({ response: { status: 409 } })
  sdk.exited!({ reason: 'RoomDismiss', roomId: 'room' }); await flushPromises()
  expect(wrapper.text()).not.toContain('会议状态同步失败')
  expect(wrapper.emitted('changed')).toBeTruthy()
})

it('allows an ordinary member to leave and rejoin without ending the meeting', async () => {
  await enter()
  expect(wrapper.text()).toContain('已加入视频会议')
  await wrapper.get('button').trigger('click'); await flushPromises()
  expect(wrapper.text()).toContain('尚未加入视频')
  expect(wrapper.get('button').attributes('disabled')).toBeUndefined()
  expect(api.command).not.toHaveBeenCalled()
  await wrapper.get('button').trigger('click'); await flushPromises()
  expect(sdk.join).toHaveBeenCalledTimes(2)
})
it('distinguishes an active business meeting from joining its video room', async () => {
  wrapper = mount(MeetingVideoRoom, { props: { meeting: active }, global: { plugins: [ElementPlus] } })
  expect(wrapper.text()).toContain('你尚未入会')
  expect(wrapper.text()).toContain('尚未加入视频')
  expect(api.videoSession).not.toHaveBeenCalled()
  expect(sdk.join).not.toHaveBeenCalled()
})

it('does not synchronize an old room after the identity changes during SDK cleanup', async () => {
  await enter({ ...active, available_actions: ['end'] })
  let finish!: () => void
  sdk.destroy.mockReturnValue(new Promise<void>(resolve => { finish = resolve }))
  sdk.exited!({ reason: 'RoomDismiss', roomId: 'room' }); await flushPromises()
  window.dispatchEvent(new Event('oa-identity-changed'))
  finish(); await flushPromises()
  expect(api.get).not.toHaveBeenCalled()
  expect(api.command).not.toHaveBeenCalled()
})

it('keeps video connected through a transient meeting-status error and clears the warning on recovery', async () => {
  await enter()
  vi.mocked(api.get).mockRejectedValueOnce({ response: { status: 503 } })
  await vi.advanceTimersByTimeAsync(10000); await flushPromises()
  expect(wrapper.text()).toContain('已加入视频会议')
  expect(wrapper.text()).toContain('正在重试')
  expect(sdk.destroy).not.toHaveBeenCalled()
  await vi.advanceTimersByTimeAsync(10000); await flushPromises()
  expect(wrapper.text()).not.toContain('正在重试')
  expect(wrapper.text()).toContain('已加入视频会议')
})

it('keeps video connected when the same identity snapshot or access token is refreshed', async () => {
  authState.user = { user_id: 'member', display_name: 'Member', roles: [], depts: [], permissions: [] }
  await enter()
  authState.user = { ...authState.user }
  authState.accessToken = 'refreshed-token'
  await flushPromises()
  expect(sdk.destroy).not.toHaveBeenCalled()
  expect(wrapper.text()).toContain('已加入视频会议')
})

it('still leaves immediately when the account actually changes', async () => {
  authState.user = { user_id: 'member', display_name: 'Member', roles: [], depts: [], permissions: [] }
  await enter()
  authState.user = { ...authState.user, user_id: 'other-member' }
  await flushPromises()
  expect(sdk.destroy).toHaveBeenCalledTimes(1)
  expect(wrapper.text()).not.toContain('已加入视频会议')
})

it.each([403, 404])('immediately leaves on permanent access failure %s', async status => {
  await enter()
  vi.mocked(api.get).mockRejectedValue({ response: { status } })
  await vi.advanceTimersByTimeAsync(10000); await flushPromises()
  expect(sdk.destroy).toHaveBeenCalledTimes(1)
  expect(wrapper.text()).toContain('已退出视频')
})

it('leaves after three consecutive status failures rather than keeping an unchecked connection', async () => {
  await enter()
  vi.mocked(api.get).mockRejectedValue(new Error('network'))
  await vi.advanceTimersByTimeAsync(30000); await flushPromises()
  expect(sdk.destroy).toHaveBeenCalledTimes(1)
  expect(wrapper.text()).toContain('已退出视频')
})

it('bounds a stalled SDK join and ignores a late success', async () => {
  let finish!: () => void
  sdk.join.mockReturnValueOnce(new Promise<void>(resolve => { finish = resolve }))
  await enter()
  expect(wrapper.text()).toContain('正在连接腾讯视频会议')
  await vi.advanceTimersByTimeAsync(60000); await flushPromises()
  expect(wrapper.text()).toContain('视频连接超时')
  expect(wrapper.get('button').classes()).not.toContain('is-loading')
  expect(sdk.destroy).toHaveBeenCalledTimes(1)
  finish(); await flushPromises()
  expect(wrapper.text()).not.toContain('已加入视频会议')
  await wrapper.get('button').trigger('click'); await flushPromises()
  expect(wrapper.text()).toContain('已加入视频会议')
})

it('waits for the previous component to destroy the singleton before joining a new room', async () => {
  await enter()
  let finish!: () => void
  sdk.destroy.mockReturnValueOnce(new Promise<void>(resolve => { finish = resolve }))
  wrapper.unmount(); await flushPromises()
  wrapper = mount(MeetingVideoRoom, { props: { meeting: active }, global: { plugins: [ElementPlus] } })
  await wrapper.get('button').trigger('click'); await flushPromises()
  expect(sdk.join).toHaveBeenCalledTimes(1)
  finish(); await flushPromises()
  expect(sdk.join).toHaveBeenCalledTimes(2)
  expect(wrapper.text()).toContain('已加入视频会议')
})
