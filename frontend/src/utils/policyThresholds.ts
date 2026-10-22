export type PolicyThresholds = Record<string, number>

type ThresholdField = {
  key: 'faq_answer' | 'intent_confidence' | 'nudge_after_seconds' | 'escalate_after_seconds'
  label: string
  unit: 'percent' | 'minutes'
}

const confidenceFields: ThresholdField[] = [
  { key: 'faq_answer', label: '问答可信度阈值', unit: 'percent' },
  { key: 'intent_confidence', label: '意图识别置信度', unit: 'percent' },
]

const timingFields: ThresholdField[] = [
  { key: 'nudge_after_seconds', label: '催办等待时间', unit: 'minutes' },
  { key: 'escalate_after_seconds', label: '升级等待时间', unit: 'minutes' },
]

const labels: Record<string, string> = Object.fromEntries(
  [...confidenceFields, ...timingFields].map((field) => [field.key, field.label]),
)

const legacyAliases: Record<string, keyof typeof labels> = {
  faq_answer_threshold: 'faq_answer',
  intent_confidence_threshold: 'intent_confidence',
}

export function thresholdFieldsForScene(scene: string): ThresholdField[] {
  return scene === 'faq' ? confidenceFields : timingFields
}

export function defaultThresholds(scene: string): PolicyThresholds {
  return scene === 'faq'
    ? { faq_answer: 0.6, intent_confidence: 0.6 }
    : { nudge_after_seconds: 300, escalate_after_seconds: 900 }
}

export function validateThresholds(scene: string, thresholds: PolicyThresholds): string | null {
  for (const field of thresholdFieldsForScene(scene)) {
    const value = thresholds[field.key]
    if (!Number.isFinite(value)) return `请填写${field.label}`
    if (field.unit === 'percent' && (value < 0 || value > 1)) return `${field.label}应在 0% 到 100% 之间`
    if (field.unit === 'minutes' && value < 0) return `${field.label}不能小于 0 分钟`
  }

  const nudge = thresholds.nudge_after_seconds
  const escalate = thresholds.escalate_after_seconds
  if (nudge !== undefined && escalate !== undefined && escalate < nudge) {
    return '升级等待时间不能早于催办等待时间'
  }
  return null
}

export function formatThresholds(thresholds: Record<string, unknown>): Array<{ label: string; value: string }> {
  const normalized: Record<string, unknown> = { ...thresholds }
  for (const [legacyKey, key] of Object.entries(legacyAliases)) {
    if (normalized[key] === undefined && normalized[legacyKey] !== undefined) normalized[key] = normalized[legacyKey]
  }

  const items = [...confidenceFields, ...timingFields]
    .filter((field) => normalized[field.key] !== undefined)
    .map((field) => ({ label: field.label, value: formatThresholdValue(field.key, normalized[field.key]) }))

  const knownKeys = new Set([...Object.keys(labels), ...Object.keys(legacyAliases)])
  const otherCount = Object.keys(thresholds).filter((key) => !knownKeys.has(key)).length
  if (otherCount) items.push({ label: '其他规则', value: `已配置 ${otherCount} 项` })
  return items
}

function formatThresholdValue(key: string, value: unknown): string {
  if (typeof value !== 'number') return '未设置'
  if (key === 'faq_answer' || key === 'intent_confidence') return `${Math.round(value * 100)}%`
  if (key.endsWith('_seconds')) return `${formatMinutes(value / 60)} 分钟`
  return String(value)
}

function formatMinutes(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}
