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
    peopleOptions: vi.fn(),
    existingItems: vi.fn(),
    saveDraft: vi.fn(),
    listDrafts: vi.fn(),
    getDraft: vi.fn(),
    confirmDraft: vi.fn(),
    cancelDraft: vi.fn(),
    listSchedules: vi.fn(),
    cancelSchedule: vi.fn(),
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
  vi.mocked(assistantV2Api.peopleOptions).mockResolvedValue({
    users: [
      { id: 'u_li', display_name: '李四' },
      { id: 'u_zhang', display_name: '张三' },
    ],
  })
  vi.mocked(assistantV2Api.existingItems).mockResolvedValue([])
  vi.mocked(assistantV2Api.listSchedules).mockResolvedValue([])
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

  it('保存任务草稿，复核确认后才写入正式任务', async () => {
    const draft = {
      title: '整理客户合同',
      assignee_id: 'u_li',
      due_at: '2026-11-11T18:00:00+08:00',
      priority: 'normal',
      sensitive: false,
    }
    vi.mocked(assistantV2Api.parseDraft).mockResolvedValue({
      draft_type: 'task',
      confidence: 'high',
      draft,
      missing_required: [],
      warnings: [],
      confirmation_notice: '当前结果只是草稿。',
    } as any)
    vi.mocked(assistantV2Api.saveDraft).mockResolvedValue({
      id: 'draft-1',
      draft_type: 'task',
      status: 'DRAFT',
      payload: draft,
      missing_required: [],
      warnings: [],
      result: {},
      notes: '',
      created_at: '2026-11-10T10:00:00+08:00',
      updated_at: '2026-11-10T10:00:00+08:00',
    } as any)
    vi.mocked(assistantV2Api.confirmDraft).mockResolvedValue({
      id: 'draft-1',
      draft_type: 'task',
      status: 'CONFIRMED',
      payload: draft,
      missing_required: [],
      warnings: [],
      result: { task_id: 'WT-123' },
      notes: '',
      created_at: '2026-11-10T10:00:00+08:00',
      updated_at: '2026-11-10T10:00:00+08:00',
    } as any)

    const wrapper = await render()
    await wrapper.get('textarea').setValue('明天提醒李四整理客户合同')
    const parseButton = wrapper.findAll('button').find(item => item.text().includes('生成结构化草稿'))!
    await parseButton.trigger('click')
    await flushPromises()

    const saveButton = wrapper.findAll('button').find(item => item.text().includes('保存可确认草稿'))!
    await saveButton.trigger('click')
    await flushPromises()
    expect(assistantV2Api.saveDraft).toHaveBeenCalledWith('task', draft)

    await wrapper.get('.confirm-form input[type="checkbox"]').setValue(true)
    const confirmButton = wrapper.findAll('button').find(item => item.text().includes('确认并写入'))!
    await confirmButton.trigger('click')
    await flushPromises()

    expect(assistantV2Api.confirmDraft).toHaveBeenCalledWith(
      'draft-1',
      expect.objectContaining({
        metadata_confirmed: true,
        risk_acknowledged: false,
      }),
    )
    expect(wrapper.text()).toContain('查看业务任务：WT-123')
  }, 15000)

  it('完成已有任务前先选择事项并复核确认', async () => {
    vi.mocked(assistantV2Api.parseDraft).mockResolvedValue({
      draft_type: 'task',
      confidence: 'medium',
      draft: {
        operation: 'complete',
        task_id: '',
        expected_version: 0,
        comment: '请完成任务',
      },
      missing_required: ['目标任务'],
      warnings: [],
      confirmation_notice: '当前结果只是草稿。',
    } as any)
    vi.mocked(assistantV2Api.existingItems).mockResolvedValue([
      {
        id: 'WT-456',
        title: '核对合同',
        status: 'IN_PROGRESS',
        version: 2,
        available_actions: ['complete'],
      },
    ])
    vi.mocked(assistantV2Api.saveDraft).mockResolvedValue({
      id: 'draft-2',
      draft_type: 'task',
      status: 'DRAFT',
      payload: {
        operation: 'complete',
        task_id: 'WT-456',
        expected_version: 2,
      },
      missing_required: [],
      warnings: [],
      result: {},
      notes: '',
      created_at: '2026-11-10T10:00:00+08:00',
      updated_at: '2026-11-10T10:00:00+08:00',
    } as any)
    vi.mocked(assistantV2Api.confirmDraft).mockResolvedValue({
      id: 'draft-2',
      draft_type: 'task',
      status: 'CONFIRMED',
      payload: {},
      missing_required: [],
      warnings: [],
      result: { task_id: 'WT-456', state: 'COMPLETED' },
      notes: '',
      created_at: '2026-11-10T10:00:00+08:00',
      updated_at: '2026-11-10T10:00:00+08:00',
    } as any)

    const wrapper = await render()
    await wrapper.get('textarea').setValue('把核对合同任务完成')
    const parseButton = wrapper.findAll('button').find(item => item.text().includes('生成结构化草稿'))!
    await parseButton.trigger('click')
    await flushPromises()

    ;(wrapper.vm as any).selectExistingItem({
      id: 'WT-456',
      title: '核对合同',
      status: 'IN_PROGRESS',
      version: 2,
      available_actions: ['complete'],
    })

    const saveButton = wrapper.findAll('button').find(item => item.text().includes('保存可确认草稿'))!
    expect((wrapper.vm as any).parsedDraftReady).toBe(true)
    await (wrapper.vm as any).saveParsedDraft()
    await flushPromises()

    await wrapper.get('.confirm-form input[type="checkbox"]').setValue(true)
    const confirmButton = wrapper.findAll('button').find(item => item.text().includes('确认并写入'))!
    await confirmButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('查看业务任务：WT-456')
  }, 15000)

  it('把周期提醒保存为规则草稿，确认后才启用', async () => {
    const draft = {
      title: '检查工单',
      frequency: 'daily',
      day_of_week: null,
      day_of_month: null,
      run_time: '09:00:00+08:00',
      starts_at: null,
      ends_at: null,
      max_occurrences: 2,
      priority: 'normal',
      sensitive: false,
    }
    vi.mocked(assistantV2Api.parseDraft).mockResolvedValue({
      draft_type: 'schedule',
      confidence: 'high',
      draft,
      missing_required: [],
      warnings: [],
      confirmation_notice: '当前结果只是周期规则草稿。',
    } as any)
    vi.mocked(assistantV2Api.saveDraft).mockResolvedValue({
      id: 'schedule-draft-1',
      draft_type: 'schedule',
      status: 'DRAFT',
      payload: draft,
      missing_required: [],
      warnings: [],
      result: {},
      notes: '',
      created_at: '2026-11-11T10:00:00+08:00',
      updated_at: '2026-11-11T10:00:00+08:00',
    } as any)
    vi.mocked(assistantV2Api.confirmDraft).mockResolvedValue({
      id: 'schedule-draft-1',
      draft_type: 'schedule',
      status: 'CONFIRMED',
      payload: draft,
      missing_required: [],
      warnings: [],
      result: {
        schedule_id: 'schedule-rule-1',
        next_run_at: '2026-11-12T09:00:00+08:00',
      },
      notes: '',
      created_at: '2026-11-11T10:00:00+08:00',
      updated_at: '2026-11-11T10:00:00+08:00',
    } as any)
    vi.mocked(assistantV2Api.listSchedules).mockResolvedValue([
      {
        id: 'schedule-rule-1',
        status: 'ACTIVE',
        title: '检查工单',
        frequency: 'daily',
        run_time: '09:00:00+08:00',
        next_run_at: '2026-11-12T09:00:00+08:00',
        occurrence_count: 0,
        template: {},
        created_at: '2026-11-11T10:00:00+08:00',
        updated_at: '2026-11-11T10:00:00+08:00',
      },
    ] as any)

    const wrapper = await render()
    await wrapper.get('textarea').setValue('每天上午9点提醒我检查工单，共2次')
    const parseButton = wrapper.findAll('button').find(item => item.text().includes('生成结构化草稿'))!
    await parseButton.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('周期任务草稿')
    expect(wrapper.text()).toContain('共 2 次')
    const saveButton = wrapper.findAll('button').find(item => item.text().includes('保存可确认草稿'))!
    await saveButton.trigger('click')
    await flushPromises()
    expect(assistantV2Api.saveDraft).toHaveBeenCalledWith('schedule', draft)

    await wrapper.get('.confirm-form input[type="checkbox"]').setValue(true)
    const confirmButton = wrapper.findAll('button').find(item => item.text().includes('确认并写入'))!
    await confirmButton.trigger('click')
    await flushPromises()

    expect(assistantV2Api.confirmDraft).toHaveBeenCalledWith(
      'schedule-draft-1',
      expect.objectContaining({ metadata_confirmed: true }),
    )
    expect(wrapper.text()).toContain('周期规则已创建')
    expect(wrapper.text()).toContain('我的周期规则')
  }, 15000)
})

