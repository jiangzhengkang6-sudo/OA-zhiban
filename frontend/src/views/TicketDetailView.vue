<script setup lang="ts">
/**
 * OA 智能体系统 MVP - 工单详情页面。
 *
 * 展示工单字段、状态、处理时间线与用户反馈。
 */
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ticketApi } from '@/api'
import type { TicketStatusResponse } from '@/types'

const route = useRoute()
const data = ref<TicketStatusResponse | null>(null)
const loading = ref(false)

async function load() {
  const ticketId = route.params.ticketId as string
  if (!ticketId) return
  loading.value = true
  try {
    data.value = await ticketApi.get(ticketId)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <el-card shadow="never" v-loading="loading">
    <template #header><span>工单详情</span></template>

    <template v-if="data">
      <el-descriptions :column="2" border>
        <el-descriptions-item label="工单号">{{ data.ticket.ticket_id }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ data.ticket.status }}</el-descriptions-item>
        <el-descriptions-item label="类别">{{ data.ticket.category }}</el-descriptions-item>
        <el-descriptions-item label="优先级">{{ data.ticket.priority }}</el-descriptions-item>
        <el-descriptions-item label="摘要" :span="2">{{ data.ticket.summary }}</el-descriptions-item>
        <el-descriptions-item label="队列">{{ data.ticket.queue_id || '未分派' }}</el-descriptions-item>
        <el-descriptions-item label="责任人">{{ data.ticket.assignee_id || '待领取' }}</el-descriptions-item>
      </el-descriptions>

      <h4>处理时间线</h4>
      <el-timeline>
        <el-timeline-item
          v-for="(e, i) in data.timeline"
          :key="i"
          :timestamp="e.created_at"
          :type="e.result === 'fail' ? 'danger' : 'primary'"
        >
          {{ e.action }}（{{ e.result }}）
        </el-timeline-item>
      </el-timeline>
      <el-empty v-if="!data.timeline.length" description="暂无处理记录" :image-size="60" />
    </template>
    <el-empty v-else description="工单不存在或无权查看" />
  </el-card>
</template>

<style scoped>
h4 {
  margin: 16px 0 8px;
  color: #374151;
}
</style>
