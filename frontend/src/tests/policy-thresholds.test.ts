import { describe, expect, it } from 'vitest'
import { defaultThresholds, formatThresholds, validateThresholds } from '@/utils/policyThresholds'

describe('policy thresholds', () => {
  it('uses confidence fields for FAQ policies and timing fields for workflow policies', () => {
    expect(defaultThresholds('faq')).toEqual({ faq_answer: 0.6, intent_confidence: 0.6 })
    expect(defaultThresholds('leave')).toEqual({ nudge_after_seconds: 300, escalate_after_seconds: 900 })
  })

  it('validates confidence ranges and time ordering', () => {
    expect(validateThresholds('faq', { faq_answer: 1.1, intent_confidence: 0.6 })).toContain('0% 到 100%')
    expect(validateThresholds('leave', { nudge_after_seconds: 900, escalate_after_seconds: 300 })).toContain('不能早于')
  })

  it('formats canonical and legacy threshold names as readable labels', () => {
    expect(formatThresholds({ faq_answer_threshold: 0.6, intent_confidence: 0.7 })).toEqual([
      { label: '问答可信度阈值', value: '60%' },
      { label: '意图识别置信度', value: '70%' },
    ])
    expect(formatThresholds({ nudge_after_seconds: 300, escalate_after_seconds: 900 })).toEqual([
      { label: '催办等待时间', value: '5 分钟' },
      { label: '升级等待时间', value: '15 分钟' },
    ])
  })
})
