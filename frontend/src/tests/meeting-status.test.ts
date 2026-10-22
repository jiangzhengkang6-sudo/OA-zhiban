import { describe, expect, it } from 'vitest'
import { STATUS_MAP, statusOf } from '@/utils/status'

describe('meeting status tags', () => {
  it('renders meeting processing and review states in Chinese', () => {
    expect(statusOf('CREATED').label).toBe('待生成')
    expect(statusOf('PROCESSING').label).toBe('生成中')
    expect(statusOf('DRAFT_READY').label).toBe('待审阅')
    expect(statusOf('REVIEWING').label).toBe('已编辑 · 待审阅')
    expect(statusOf('CONFIRMED').label).toBe('已确认')
  })

  it('keeps business states out of the thread-status filter choices', () => {
    expect(STATUS_MAP.DRAFT_READY).toBeUndefined()
    expect(STATUS_MAP.REVIEWING).toBeUndefined()
    expect(STATUS_MAP.CONFIRMED).toBeUndefined()
    expect(STATUS_MAP.WAITING_HUMAN).toBeDefined()
  })

  it('renders P3 business statuses in Chinese without adding them to task filters', () => {
    expect(statusOf('PUBLISHED').label).toBe('已发布')
    expect(statusOf('ARCHIVED').label).toBe('已归档')
    expect(statusOf('IN_PROGRESS').label).toBe('进行中')
    expect(STATUS_MAP.PUBLISHED).toBeUndefined()
  })
})
