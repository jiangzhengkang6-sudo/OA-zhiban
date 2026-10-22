<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { taskApi } from '@/api'
import { getCurrentUserId } from '@/api/client'
import { hasRole } from '@/utils/roles'
import type { TaskSummary } from '@/types'
import SummaryCard from '@/components/TaskSummary.vue'
const route = useRoute(), router = useRouter()
const items = ref<TaskSummary[]>([]), total = ref(0), page = ref(1), loading = ref(false), error = ref('')
const allowed = hasRole(getCurrentUserId(), 'approver')
async function load() {
  if (!allowed) return
  loading.value = true; error.value = ''
  try {
    const data = await taskApi.list({ inbox: true, scene: 'leave', status: 'WAITING_HUMAN', page: page.value, page_size: 20 })
    items.value = data.items; total.value = data.total
  } catch { items.value = []; error.value = '审批待办加载失败，请重试' } finally { loading.value = false }
}
watch(() => route.query.page, value => { page.value = Math.max(1, Number(value) || 1); void load() }, { immediate: true })
</script>
<template>
  <section class="workbench"><div class="page-heading"><div><p class="eyebrow">审批工作台</p><h1>审批待办</h1><p class="muted">仅显示当前节点由你负责的申请，共 {{ total }} 条。</p></div><el-button :loading="loading" @click="load">刷新</el-button></div>
    <el-result v-if="!allowed" icon="warning" title="当前角色没有审批待办权限" /><el-skeleton v-else-if="loading" :rows="6" animated /><el-result v-else-if="error" icon="warning" :title="error"><template #extra><el-button @click="load">重试</el-button></template></el-result>
    <div v-else-if="items.length" class="task-grid"><SummaryCard v-for="task in items" :key="task.task_id" :task="task" @open="router.push('/leave/' + task.task_id)" /></div><el-empty v-else description="暂无待处理审批" />
    <el-pagination v-if="total > 20" :current-page="page" :page-size="20" :total="total" layout="prev, pager, next" @current-change="router.replace({ query: { page: String($event) } })" />
  </section>
</template>
