<script setup lang="ts">
import { computed } from 'vue'
import type { TaskSummary } from '@/types'
import StatusTag from './StatusTag.vue'
import { SCENE_MAP } from '@/utils/status'
import { displayTime } from '@/utils/leave'
const props = defineProps<{ task: TaskSummary; busy?: boolean }>()
defineEmits<{ open: []; action: [action: string] }>()
const actions: Record<string, string> = { handoff: '转人工', retry: '安全重试', reconcile: '核对结果' }
const waiting = computed(() => {
  const since = props.task.responsibility.waiting_since
  if (!since) return ''
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(since).getTime()) / 60000))
  return minutes < 60 ? minutes + ' 分钟' : Math.floor(minutes / 60) + ' 小时'
})
</script>
<template>
  <article class="task-card">
    <div class="task-heading"><span class="eyebrow">{{ SCENE_MAP[task.task_type] || task.task_type }}</span><StatusTag :status="task.business_status" /></div>
    <h3>{{ task.business_id || '会话 ' + task.task_id.slice(0, 8) }}</h3>
    <p>当前责任人：{{ task.responsibility.display_name || task.responsibility.user_id || '待分派' }}<span v-if="waiting"> · 已等待 {{ waiting }}</span></p>
    <p v-if="task.pause_reason" class="pause-reason">{{ task.pause_reason.msg || task.pause_reason.message }}（{{ task.pause_reason.code }}）</p>
    <div class="task-footer"><small>更新于 {{ displayTime(task.updated_at) }}</small><div class="actions">
      <el-button v-for="action in task.available_actions.filter(a => actions[a])" :key="action" :disabled="busy" @click="$emit('action', action)">{{ actions[action] }}</el-button>
      <el-button type="primary" plain data-testid="open-task" @click="$emit('open')">{{ task.available_actions.includes('approve') ? '处理审批' : '打开任务' }}</el-button>
    </div></div>
  </article>
</template>
