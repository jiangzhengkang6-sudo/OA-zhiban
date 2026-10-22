<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ticketApi } from '@/api'
const route = useRoute(), router = useRouter(), loading = ref(false), error = ref('')
const ticket = ref<Record<string, any> | null>(null), timeline = ref<Record<string, any>[]>([])
onMounted(async () => { loading.value = true; try { const data = await ticketApi.get(String(route.params.ticketId)); ticket.value = data.ticket; timeline.value = data.timeline } catch { error.value = '工单加载失败' } finally { loading.value = false } })
</script>
<template><section class="workbench"><div class="page-heading"><div><p class="eyebrow">工单工作台</p><h1>{{ ticket?.ticket_id || route.params.ticketId }}</h1><p class="muted">查看处理上下文与状态时间线。</p></div><el-button @click="router.push('/support')">返回客服队列</el-button></div><el-skeleton v-if="loading" :rows="6" animated /><el-alert v-else-if="error" type="error" :title="error" /><div v-else class="ticket-panel"><el-tag>{{ ticket?.status }}</el-tag><h2>{{ ticket?.summary || '未提供摘要' }}</h2><p class="muted">队列：{{ ticket?.queue_id || '未分派' }} · 责任人：{{ ticket?.assignee_id || '待领取' }}</p><el-divider /><h3>处理时间线</h3><el-empty v-if="!timeline.length" description="暂无时间线记录" /><el-timeline v-else><el-timeline-item v-for="(event,index) in timeline" :key="index" :timestamp="event.created_at">{{ event.action || event.result || '状态更新' }}</el-timeline-item></el-timeline></div></section></template>
<style scoped>.ticket-panel{max-width:820px;padding:26px;border:1px solid var(--oa-border);border-radius:14px;background:#fff}.ticket-panel h2{margin:20px 0 8px}.ticket-panel h3{font-size:15px}</style>
