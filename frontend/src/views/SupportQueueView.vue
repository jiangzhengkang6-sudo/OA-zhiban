<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { supportApi } from '@/api'
import type { SupportQueueItem } from '@/types'
import { handoffReason } from '@/utils/handoff'
import { businessLabel, personName } from '@/utils/businessLabels'

const router = useRouter()
const items = ref<SupportQueueItem[]>([])
const loading = ref(false)
const error = ref('')
const status = ref('')

async function load() {
  loading.value = true; error.value = ''
  try { const result = await supportApi.list({ status: status.value || undefined }); items.value = result.items }
  catch { error.value = '队列加载失败，请重试' }
  finally { loading.value = false }
}
function statusLabel(value: string) { return ({ OPEN: '待受理', IN_PROGRESS: '处理中', RESOLVED: '已解决', CLOSED: '已关闭' } as Record<string, string>)[value] || value }
onMounted(load)
</script>

<template>
  <section class="workbench support-page">
    <div class="page-heading"><div><p class="eyebrow">客服运营 · LIVE QUEUE</p><h1>人工服务队列</h1><p class="muted">接收交接上下文，明确责任人，再把处理结果回写到工单。</p></div><el-button :loading="loading" @click="load">刷新队列</el-button></div>
    <div class="filters"><el-select v-model="status" clearable placeholder="全部状态" @change="load"><el-option label="待受理" value="OPEN" /><el-option label="处理中" value="IN_PROGRESS" /></el-select><span class="muted">当前 {{ items.length }} 项</span></div>
    <el-skeleton v-if="loading" :rows="6" animated />
    <el-alert v-else-if="error" type="error" :title="error" show-icon />
    <el-empty v-else-if="!items.length" description="队列暂时为空" />
    <div v-else class="support-grid">
      <article v-for="item in items" :key="item.queue_item_id" class="support-card">
        <div class="support-card__top"><span class="queue-mark">{{ item.scene === 'ticket' ? '工单' : '问答' }}</span><el-tag :type="item.status === 'OPEN' ? 'warning' : 'success'" effect="plain">{{ statusLabel(item.status) }}</el-tag></div>
        <h2>{{ item.context_summary || item.snapshot.summary || '人工服务请求' }}</h2>
        <p class="muted">原因：{{ handoffReason(item.reason_code) }} · 服务时限：{{ businessLabel(item.sla_status) }}</p>
        <div class="support-card__meta"><span>用户 {{ personName(item.user_id) }}</span><span v-if="item.ticket_id">{{ item.ticket_id }}</span></div>
        <div class="support-card__footer"><span class="muted">{{ item.assignee_id ? '责任人 ' + personName(item.assignee_id) : '等待领取' }}</span><el-button data-testid="open-support-item" type="primary" plain @click="router.push('/support/' + item.queue_item_id)">查看上下文快照</el-button></div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.support-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:16px; }
.support-card { padding:22px; border:1px solid var(--oa-border); border-radius:14px; background:#fff; box-shadow:0 10px 24px rgba(23,50,77,.04); }
.support-card__top,.support-card__footer,.support-card__meta { display:flex; justify-content:space-between; align-items:center; gap:12px; }
.support-card h2 { margin:20px 0 8px; font-size:18px; line-height:1.4; }
.support-card__meta { padding:12px 0; border-top:1px solid #edf1f5; border-bottom:1px solid #edf1f5; color:#365269; font-size:13px; }
.support-card__footer { margin-top:16px; }
.queue-mark { color:#0f766e; font-size:12px; font-weight:700; letter-spacing:.08em; }
</style>
