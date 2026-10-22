import { computed, ref, shallowRef, watch, type Ref } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import axios from 'axios'
import { commandKey, releaseCommandKey } from '@/api/draftCommands'
import type { DraftCheck, DraftRecord, DraftSummary, DraftCommand, DraftDecision, DraftPage, DraftVersion } from '@/types/drafting'

interface ReviewApi<D, R> {
  get(id: string): Promise<R>; list(params: { page: number; page_size: number }): Promise<DraftPage<DraftSummary>>
  versions(id: string): Promise<DraftVersion<D>[]>; save(id: string, payload: DraftCommand & { draft: D }): Promise<R>
  decide(id: string, payload: DraftDecision): Promise<R>; retry(id: string, payload: DraftCommand): Promise<R>
}
export const draftStatus: Record<string, string> = { CREATED: '待生成', DRAFT_READY: '待审阅', REVIEWING: '已修订',
  PAUSED: '已暂停', CONFIRMED: '已确认', REJECTED: '已拒绝' }
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value))

export function useDraftReview<D, R extends DraftRecord<D>>(scope: string, api: ReviewApi<D, R>,
  valid: (draft: D, record: R) => boolean, secondary: (record: R) => boolean = () => false) {
  const route = useRoute()
  const id = computed(() => String(route.params.id || ''))
  const record = shallowRef<R | null>(null), draft = ref(null) as Ref<D | null>
  const items = shallowRef<DraftSummary[]>([]), versions = shallowRef<DraftVersion<D>[]>([])
  const busy = ref(false), loading = ref(false), error = ref(''), historyError = ref('')
  const page = ref(1), total = ref(0), metadata = ref(false), warnings = ref(false)
  let serial = 0
  const dirty = computed(() => !!record.value?.draft && JSON.stringify(draft.value) !== JSON.stringify(record.value.draft))
  const editable = computed(() => !!record.value?.available_actions.includes('edit'))
  const validDraft = computed(() => !!draft.value && !!record.value && valid(draft.value, record.value))
  const hasWarnings = computed(() => !!record.value?.checks.some((item: DraftCheck) => item.severity === 'warning'))
  const canConfirm = computed(() => !!record.value?.available_actions.includes('confirm') && !busy.value && !dirty.value && validDraft.value && metadata.value &&
    (!hasWarnings.value || warnings.value) && !record.value.checks.some((item: DraftCheck) => item.severity === 'error'))
  function problem(err: unknown) { error.value = axios.isAxiosError(err) ? err.response?.data?.message || err.message : err instanceof Error ? err.message : '操作失败，请重试' }
  function apply(result: R) { record.value = result; draft.value = result.draft ? clone(result.draft) : null; metadata.value = false; warnings.value = false }
  async function history(target: string, token: number) {
    try { const result = await api.versions(target); if (serial === token && id.value === target) versions.value = result }
    catch { if (serial === token) historyError.value = '历史版本加载失败' }
  }
  async function load() {
    const token = ++serial, target = id.value
    loading.value = true; error.value = ''; historyError.value = ''; record.value = null; draft.value = null; versions.value = []; items.value = []
    try {
      if (target) { const result = await api.get(target); if (serial === token && id.value === target) { apply(result); await history(target, token) } }
      else { const result = await api.list({ page: page.value, page_size: 20 }); if (serial === token && !id.value) { items.value = result.items; total.value = result.total } }
    } catch (err) { if (serial === token) problem(err) } finally { if (serial === token) loading.value = false }
  }
  watch(id, () => { page.value = 1; void load() }, { immediate: true })
  async function leave() {
    if (busy.value) return false
    if (!dirty.value) return true
    try { await ElMessageBox.confirm('当前修改尚未保存，确认离开？', '未保存的修改'); return true } catch { return false }
  }
  onBeforeRouteLeave(leave)
  onBeforeRouteUpdate(leave)
  async function reload() { if (await leave()) await load() }
  async function execute(action: string, payload: object, command: (key: string) => Promise<R>) {
    if (busy.value || !record.value) return
    const target = id.value, token = serial, data = { id: target, ...payload }
    busy.value = true; error.value = ''
    try {
      const key = await commandKey(`${scope}-${action}`, data)
      const result = await command(key)
      await releaseCommandKey(`${scope}-${action}`, data)
      if (serial === token && id.value === target) { apply(result); await history(target, token) }
    } catch (err) { if (serial === token) problem(err) } finally { busy.value = false }
  }
  async function save() {
    if (!editable.value || !dirty.value || !validDraft.value || !draft.value || !record.value) return
    const target = id.value, payload = { expected_version: record.value.version, draft: clone(draft.value) }
    await execute('edit', payload, key => api.save(target, { ...payload, idempotency_key: key }))
  }
  async function start(generate: (id: string, payload: DraftCommand) => Promise<R>, retry = false) {
    if (!record.value) return
    const target = id.value, payload = { expected_version: record.value.version }
    await execute(retry ? 'retry' : 'generate', payload, key => retry ? api.retry(target, { ...payload, idempotency_key: key })
      : generate(target, { ...payload, idempotency_key: key }))
  }
  async function decide(action: DraftDecision['action']) {
    if (!record.value || dirty.value || busy.value || (action === 'confirm' && !canConfirm.value)) return
    const target = id.value, token = serial, expected_version = record.value.version
    const metadata_confirmed = metadata.value, warnings_acknowledged = warnings.value
    let reason: string | null = null, secondary_confirmed = false
    try {
      if (action === 'reject') reason = (await ElMessageBox.prompt('请填写拒绝原因', '拒绝草稿', { inputValidator: value => !!value.trim() || '请填写原因' })).value
      else {
        await ElMessageBox.confirm(action === 'confirm' ? '确认当前草稿版本并保存平台内记录？' : '重新生成并保留已有版本？', action === 'confirm' ? '确认草稿' : '重新生成')
        if (action === 'confirm' && secondary(record.value)) {
          await ElMessageBox.confirm('请再次核对外部联系人和敏感附件标记。确认仅保存内部记录。', '二次确认')
          secondary_confirmed = true
        }
      }
    } catch { return }
    if (serial !== token || id.value !== target || record.value?.version !== expected_version || dirty.value || busy.value) return
    if (action === 'confirm' && !canConfirm.value) return
    const payload = { action, reason, expected_version, metadata_confirmed, warnings_acknowledged,
      ...(scope === 'email' ? { secondary_confirmed } : {}) }
    await execute(action, payload, key => api.decide(target, { ...payload, idempotency_key: key }))
  }
  return { id, record, draft, items, versions, busy, loading, error, historyError, page, total,
    metadata, warnings, dirty, editable, validDraft, hasWarnings, canConfirm, apply, problem, load, reload, save, start, decide }
}
