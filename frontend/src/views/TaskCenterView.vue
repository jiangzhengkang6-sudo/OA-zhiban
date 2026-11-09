<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { taskApi, approvalApi } from '@/api'
import type { TaskSummary } from '@/types'
import SummaryCard from '@/components/TaskSummary.vue'
import { STATUS_MAP } from '@/utils/status'
import PendingWorkItems from '@/components/PendingWorkItems.vue'
import { authState, can } from '@/stores/auth'
const pendingAllowed = computed(() => authState.provider==='builtin' && (can('approval') || can('work_task')))
const historyAllowed = computed(() => authState.provider!=='builtin' || authState.aiEnabled && !!authState.user?.permissions.some(p => p.resource==='task' && p.action==='read'))
const tab = ref(pendingAllowed.value ? 'pending' : 'history')
watch([pendingAllowed, historyAllowed], () => { if (tab.value==='pending' && !pendingAllowed.value) tab.value='history'; else if (tab.value==='history' && !historyAllowed.value) tab.value='pending' })
const route = useRoute(), router = useRouter()
const items = ref<TaskSummary[]>([]), total = ref(0), loading = ref(false), error = ref(''), busy = ref('')
const page = ref(1), scene = ref(''), status = ref('')
async function load() {
  if (!historyAllowed.value) return
  loading.value = true; error.value = ''
  try {
    const data = await taskApi.list({ page: page.value, page_size: 20, scene: scene.value || undefined, status: status.value || undefined })
    items.value = data.items; total.value = data.total
  } catch { items.value = []; error.value = '任务加载失败，请重试' } finally { loading.value = false }
}
function open(task: TaskSummary) {
  const workbenches: Record<string, string> = { meeting: '/meetings/', document: '/documents/', email: '/emails/',
    work_task: '/work-tasks/', report: '/reports/', contract: '/contracts/' }
  if (workbenches[task.task_type] && task.business_id) {
    router.push(workbenches[task.task_type] + encodeURIComponent(task.business_id)); return
  }
  router.push(task.task_type === 'meeting' && task.business_id ? '/meetings/' + encodeURIComponent(task.business_id)
    : task.task_type === 'leave' ? '/leave/' + task.task_id : '/assistant/' + task.task_id)
}
async function action(task: TaskSummary, command: string) {
  if (busy.value) return
  if (['meeting', 'document', 'email', 'work_task', 'report', 'contract'].includes(task.task_type)) { open(task); return }
  busy.value = task.task_id
  try {
    if (command === 'handoff') await taskApi.handoff(task.task_id)
    else if (command === 'reconcile') await approvalApi.reconcile(task.task_id)
    else await taskApi.retry(task.task_id)
    await load()
  } catch { /* HTTP 客户端展示错误，保留当前任务便于重试。 */ } finally { busy.value = '' }
}
function filter() { router.replace({ query: { scene: scene.value || undefined, status: status.value || undefined, page: '1' } }) }
watch(() => route.query, query => {
  scene.value = String(query.scene || ''); status.value = String(query.status || ''); page.value = Math.max(1, Number(query.page) || 1); void load()
}, { immediate: true })
</script>
<template>
  <section class="workbench"><div class="page-heading"><div><p class="eyebrow">工作台</p><h1>我的任务</h1></div><el-button v-if="tab==='history'" :loading="loading" @click="load">刷新</el-button></div>
    <el-tabs v-model="tab"><el-tab-pane v-if="pendingAllowed" label="待我处理" name="pending"/><el-tab-pane v-if="historyAllowed" label="智能任务记录" name="history"/></el-tabs>
    <PendingWorkItems v-if="tab==='pending' && pendingAllowed"/>
    <template v-else-if="historyAllowed">
    <div class="filters"><el-select v-model="scene" placeholder="全部场景" clearable @change="filter"><el-option label="请假" value="leave" /><el-option label="问答" value="faq" /><el-option label="工单" value="ticket" /><el-option label="会议" value="meeting" /><el-option label="文档" value="document" /><el-option label="邮件" value="email" /><el-option label="业务任务" value="work_task" /><el-option label="报表" value="report" /><el-option label="合同" value="contract" /></el-select>
      <el-select v-model="status" placeholder="全部状态" clearable @change="filter"><el-option v-for="(item, key) in STATUS_MAP" :key="key" :label="item.label" :value="key" /></el-select><span class="muted">共 {{ total }} 条</span></div>
    <el-skeleton v-if="loading" :rows="6" animated /><el-result v-else-if="error" icon="warning" :title="error"><template #extra><el-button @click="load">重新加载</el-button></template></el-result>
    <div v-else-if="items.length" class="task-grid"><SummaryCard v-for="task in items" :key="task.task_id" :task="task" :busy="busy === task.task_id" @open="open(task)" @action="action(task, $event)" /></div><el-empty v-else description="暂时没有任务，可以从智能助手开始" />
    <el-pagination v-if="total > 20" :current-page="page" :page-size="20" :total="total" layout="prev, pager, next" @current-change="router.replace({ query: { ...route.query, page: String($event) } })" />
    </template>
  </section>
</template>
