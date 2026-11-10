import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import AssistantV2Panel from '@/components/AssistantV2Panel.vue'
import { assistantV2Api } from '@/api/assistantV2'

vi.mock('@/api/assistantV2', () => ({
  assistantV2Api: {
    overview: vi.fn(),
    searchKnowledge: vi.fn(),
    createReportDraft: vi.fn(),
    parseDraft: vi.fn(),
  },
}))

const overview = {
  generated_at: '2026-11-10T09:00:00+08:00',
  date: '2026-11-10',
  weekday: '星期二',
  summary: '今日有 1 项待办、1 场会议、2 条未读通知、3 封待处理邮件。',
  safety_notice: '助手仅汇总、检索和起草。',
  sections: [
    {
      key: 'tasks',
      title: '我的今日待办',
      available: true,
      count: 1,
      message: '',
      cards: [
        {
          id: 'WT-1',
          type: 'task',
          title: '整理会议材料',
          subtitle: '截止 15:00',
          status: '待开始',
          time: '2026-11-10T15:00:00+08:00',
          link: '/work-tasks/WT-1',
        },
      ],
    },
    { key: 'meetings', title: '我的今日会议', available: true, count: 1, message: '', cards: [] },
    { key: 'notifications', title: '未读通知', available: true, count: 2, message: '', cards: [] },
    { key: 'emails', title: '待处理邮件', available: true, count: 3, message: '', cards: [] },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(assistantV2Api.overview).mockResolvedValue(overview as any)
})

async function render() {
  const wrapper = mount(AssistantV2Panel, {
    global: {
      plugins: [ElementPlus],
      stubs: {
        RouterLink: {
          props: ['to'],
          template: '<a><slot /></a>',
        },
      },
    },
  })
  await (wrapper.vm as any).loadOverview()
  await flushPromises()
  return wrapper
}

describe('统一智能助手 V2 面板', () => {
  it('展示今日总览和安全边界', async () => {
    const wrapper = await render()

    expect(wrapper.text()).toContain('今日有 1 项待办')
    expect(wrapper.text()).toContain('整理会议材料')
    expect(wrapper.text()).toContain('助手仅汇总、检索和起草')
  }, 15000)

  it('把自然语言解析为会议结构化草稿且不直接提交', async () => {
    vi.mocked(assistantV2Api.parseDraft).mockResolvedValue({
      draft_type: 'meeting',
      confidence: 'medium',
      draft: {
        title: '项目',
        starts_at: '2026-11-11T15:00:00+08:00',
        ends_at: '2026-11-11T16:00:00+08:00',
        host_name: '张三',
        recorder_name: '张三',
        attendee_names: ['李四'],
        location: '三楼会议室',
        online_url: '',
        video_enabled: false,
      },
      missing_required: [],
      warnings: ['参会人员需人工选择'],
      confirmation_notice: '当前结果只是草稿。',
    } as any)
    const wrapper = await render()

    await wrapper.get('textarea').setValue('明天下午3点和李四开项目复盘会')
    const button = wrapper.findAll('button').find(item => item.text().includes('生成结构化草稿'))!
    await button.trigger('click')
    await flushPromises()

    expect(assistantV2Api.parseDraft).toHaveBeenCalledWith('明天下午3点和李四开项目复盘会', 'auto')
    expect(wrapper.text()).toContain('会议草稿')
    expect(wrapper.text()).toContain('参会人员需人工选择')
    expect(wrapper.text()).toContain('当前结果只是草稿')
  }, 15000)
})

