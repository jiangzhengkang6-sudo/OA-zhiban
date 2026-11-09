import { beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import ElementPlus from 'element-plus'
import SourceCard from '@/components/SourceCard.vue'
import KnowledgeView from '@/views/KnowledgeView.vue'
import KnowledgeReaderView from '@/views/KnowledgeReaderView.vue'
import type { KnowledgeReading } from '@/types'
import { knowledgeApi } from '@/api'
import { authState } from '@/stores/auth'

vi.mock('@/api', () => ({ knowledgeApi: { list: vi.fn(), listPublished: vi.fn(), readVersion: vi.fn() } }))

beforeEach(() => {
  vi.resetAllMocks()
  Object.assign(authState, { provider: 'builtin', user: { user_id: 'member', permissions: [] } })
})

it('citation links to the exact version and chunk and displays a readable location', async () => {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:pathMatch(.*)*', component: { template: '<div />' } }] })
  await router.push('/')
  const wrapper = mount(SourceCard, { props: { sources: [{ title: '公开参考', document_id: 'source',
    source_id: 'source', version_id: 'version', chunk_id: 'chunk',
    source_location: 'page=None;section=材料清单;paragraph=2', similarity: .8 }] },
    global: { plugins: [router, ElementPlus] } })
  expect(wrapper.get('a').attributes('href')).toBe('/knowledge/sources/source/versions/version#chunk-chunk')
  expect(wrapper.text()).toContain('材料清单 · 第 2 段')
  expect(wrapper.text()).not.toContain('page=None')
  wrapper.unmount()
})

it('builtin knowledge list uses published formal sources and hides the legacy importer', async () => {
  vi.mocked(knowledgeApi.listPublished).mockResolvedValue([{ source_id: 'source', version_id: 'version', title: '公开参考', version: 1, status: 'published' }])
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/:pathMatch(.*)*', component: { template: '<div />' } }] })
  await router.push('/knowledge')
  const wrapper = mount(KnowledgeView, { global: { plugins: [router, ElementPlus] } })
  await flushPromises()
  expect(knowledgeApi.listPublished).toHaveBeenCalledOnce()
  expect(knowledgeApi.list).not.toHaveBeenCalled()
  expect(wrapper.text()).toContain('公开参考')
  expect(wrapper.text()).not.toContain('导入知识文档')
  expect(wrapper.get('a.source-link').attributes('href')).toBe('/knowledge/sources/source/versions/version')
  wrapper.unmount()
})

const reading = (version: string, text: string): KnowledgeReading => ({ source_id: 'source', version_id: version,
  title: version, version: 1, status: 'published', blocks: [{ id: version, text, source_location: '' }] })
async function reader() {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/knowledge/sources/:sourceId/versions/:versionId', component: KnowledgeReaderView },
    { path: '/knowledge', component: { template: '<div />' } },
  ] })
  await router.push('/knowledge/sources/source/versions/first')
  const wrapper = mount(KnowledgeReaderView, { global: { plugins: [router, ElementPlus] } })
  await flushPromises()
  return { wrapper, router }
}

it('source text stays inert and is cleared when another version cannot be read', async () => {
  vi.mocked(knowledgeApi.readVersion).mockResolvedValueOnce(reading('first', '<img src=x onerror=alert(1)>'))
  const { wrapper, router } = await reader()
  expect(wrapper.text()).toContain('<img src=x onerror=alert(1)>')
  expect(wrapper.find('img').exists()).toBe(false)
  vi.mocked(knowledgeApi.readVersion).mockRejectedValueOnce(new Error('denied'))
  await router.push('/knowledge/sources/source/versions/denied')
  await flushPromises()
  expect(wrapper.find('.reading-block').exists()).toBe(false)
  expect(wrapper.text()).not.toContain('onerror')
  expect(wrapper.text()).toContain('资料无法读取')
  wrapper.unmount()
})

it('a slower previous request cannot overwrite the newly selected version', async () => {
  let resolveFirst!: (value: KnowledgeReading) => void
  vi.mocked(knowledgeApi.readVersion).mockReturnValueOnce(new Promise(resolve => { resolveFirst = resolve }))
  const { wrapper, router } = await reader()
  vi.mocked(knowledgeApi.readVersion).mockResolvedValueOnce(reading('second', '当前资料'))
  await router.push('/knowledge/sources/source/versions/second')
  await flushPromises()
  expect(wrapper.text()).toContain('当前资料')
  resolveFirst(reading('first', '旧资料'))
  await flushPromises()
  expect(wrapper.text()).toContain('当前资料')
  expect(wrapper.text()).not.toContain('旧资料')
  wrapper.unmount()
})
