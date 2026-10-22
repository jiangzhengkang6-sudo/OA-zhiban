<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { supportApi } from '@/api'
import type { SupportQueueItem } from '@/types'
import { handoffReason } from '@/utils/handoff'
import ReadableContent from '@/components/ReadableContent.vue'
import { businessLabel, personName } from '@/utils/businessLabels'

const route = useRoute(), router = useRouter()
const item = ref<SupportQueueItem | null>(null)
const error = ref('')
const loading = ref(false), resolution = ref(''), assignee = ref('u_cs_002')
async function load() {
  loading.value = true; error.value = ''
  try { item.value = await supportApi.get(String(route.params.itemId)) }
  catch { item.value = null; error.value = '无法加载交接上下文，请确认权限或返回队列重试' }
  finally { loading.value = false }
}
async function accept() { if (item.value) item.value = await supportApi.accept(item.value.queue_item_id) }
async function assign() { if (item.value) item.value = await supportApi.assign(item.value.queue_item_id, assignee.value) }
async function complete() { if (item.value && resolution.value.trim()) item.value = await supportApi.complete(item.value.queue_item_id, { resolution: resolution.value, status: 'resolved' }) }
const canAccept = computed(() => item.value?.status === 'OPEN')
const context = computed(() => Object.fromEntries(Object.entries(item.value?.snapshot || {})
  .filter(([key]) => !['summary', 'scene', 'thread_id', 'reason_code'].includes(key))))
onMounted(load)
</script>

<template>
  <section class="workbench support-detail"><div class="page-heading"><div><p class="eyebrow">人工处理单</p><h1>{{ item?.ticket_id || '交接项目' }}</h1><p class="muted">把上下文看完整，再执行受理、转派或完成。</p></div><el-button @click="router.push('/support')">返回队列</el-button></div>
    <el-skeleton v-if="loading" :rows="8" animated />
    <el-alert v-else-if="error" :title="error" type="error" show-icon />
    <template v-else-if="item"><div class="detail-grid"><el-card><template #header><div class="card-header"><span>上下文快照</span><el-tag>{{ businessLabel(item.status) }}</el-tag></div></template><h2>{{ item.context_summary || item.snapshot.summary || '未提供摘要' }}</h2><p class="muted">用户：{{ personName(item.user_id) }} · 原因：{{ handoffReason(item.reason_code) }}</p><div class="context-content"><ReadableContent :value="context" /></div></el-card><el-card><template #header>处理动作</template><el-button v-if="canAccept" data-testid="accept-item" type="primary" @click="accept">受理此项</el-button><div class="action-block"><el-input v-model="assignee" placeholder="客服账号" /><el-button data-testid="assign-item" @click="assign">转派</el-button></div><el-input v-model="resolution" type="textarea" :rows="5" placeholder="记录处理结果" /><el-button data-testid="complete-item" type="success" :disabled="!resolution.trim()" @click="complete">完成并回写</el-button><div v-if="item.ticket_id" class="ticket-link"><p class="muted">关联工单：{{ item.ticket_id }} · {{ businessLabel(item.ticket_status || '') }}</p><el-button data-testid="open-ticket-workbench" text type="primary" @click="router.push('/support/ticket/' + item.ticket_id)">打开工单工作台 →</el-button></div></el-card></div></template>
  </section>
</template>

<style scoped>
.detail-grid { display:grid; grid-template-columns:minmax(0,1.2fr) minmax(300px,.8fr); gap:18px; }
.card-header,.action-block { display:flex; justify-content:space-between; align-items:center; gap:10px; }
.action-block { margin:16px 0; }
.action-block .el-input { flex:1; }
.ticket-link { margin-top: 14px; padding-top: 12px; border-top: 1px solid #edf1f5; }
.ticket-link .el-button { margin-top: 0; }
.context-content { margin-top:24px; overflow-wrap:anywhere; }
.detail-grid > * { min-width:0; }
.el-textarea,.el-button { margin-top:14px; }
@media(max-width:760px){.detail-grid{grid-template-columns:1fr}}
</style>
