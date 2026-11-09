<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { organizationApi, type OperationalSnapshot, type OperationalIncident } from '@/api/organization'

const snapshot = ref<OperationalSnapshot | null>(null)
const loading = ref(false)
const error = ref('')
let timer: ReturnType<typeof setInterval> | undefined
let disposed = false
const current = computed(() => snapshot.value?.incidents.filter(row => !row.resolved_at) || [])
const history = computed(() => snapshot.value?.incidents.filter(row => row.resolved_at) || [])
const states = {running:'巡检运行中',stale:'巡检已中断',unconfigured:'尚未启动巡检',invalid:'巡检记录不可用'}
const labels = {PASS:'正常',WARN:'待核对',FAIL:'故障'}
const deliveries: Record<string,string> = {ACCEPTED:'服务已受理',TEMPORARY:'暂时失败',PERMANENT:'发送失败',UNKNOWN:'结果待核对'}
function time(value: string | null) { return value ? new Date(value).toLocaleString('zh-CN', {hour12:false}) : '暂无记录' }
function delivery(row: OperationalIncident) {
  const values = Object.entries(row.deliveries).map(([key,value]) => `${key.endsWith(':smtp')?'邮件':'企业微信'}${key.startsWith('recovery:')?'恢复':'故障'}：${deliveries[value.status] || '结果待核对'}`)
  return values.join('；') || '暂无投递记录'
}
async function refresh() {
  if (loading.value || disposed) return
  loading.value = true
  try {
    const data = await organizationApi.alerts()
    if (!disposed) { snapshot.value = data; error.value = '' }
  } catch { if (!disposed) error.value = '运行告警读取失败，请稍后刷新' }
  finally { if (!disposed) loading.value = false }
}
onMounted(() => { void refresh(); timer = setInterval(() => void refresh(), 30000) })
onBeforeUnmount(() => { disposed = true; clearInterval(timer) })
</script>

<template>
  <main class="alerts-page" v-loading="loading">
    <header class="page-heading"><h1>运行告警</h1><el-tooltip content="刷新" placement="left"><el-button :icon="Refresh" circle aria-label="刷新运行告警" :loading="loading" @click="refresh" /></el-tooltip></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <template v-if="snapshot">
      <div class="monitor-status"><el-tag :type="snapshot.state==='running'?'success':'warning'">{{ states[snapshot.state] }}</el-tag><span>最近巡检：{{ time(snapshot.checked_at) }}</span><strong>未恢复 {{ current.length }} 项</strong></div>
      <el-alert v-if="snapshot.state==='stale'" title="巡检记录已超过三分钟，当前数据可能过期" type="error" :closable="false" show-icon />
      <el-alert v-else-if="snapshot.state==='invalid'" title="巡检记录损坏或归属不符，请联系管理员核对" type="error" :closable="false" show-icon />
      <el-alert v-if="!snapshot.delivery_enabled" title="外部告警通知尚未启用" type="info" :closable="false" />
      <el-alert v-else-if="!snapshot.channels?.length" title="外部告警已启用，但没有可用的通知渠道" type="warning" :closable="false" />
      <section aria-labelledby="checks-title"><h2 id="checks-title">检查项目</h2>
        <el-table :data="snapshot.checks" empty-text="暂无巡检记录">
          <el-table-column prop="name" label="检查项目" min-width="145" />
          <el-table-column label="状态" width="95"><template #default="{row}"><el-tag :type="row.status==='PASS'?'success':row.status==='FAIL'?'danger':'warning'">{{ labels[row.status as keyof typeof labels] }}</el-tag></template></el-table-column>
          <el-table-column label="检查结果" min-width="240"><template #default="{row}">{{ row.message }}<span v-if="typeof row.count==='number'">（{{ row.count }} 项）</span><span v-if="row.last_success_at"> · 最近成功：{{ time(row.last_success_at) }}</span></template></el-table-column>
        </el-table>
      </section>
      <section aria-labelledby="current-title"><h2 id="current-title">当前故障</h2>
        <el-table :data="current" empty-text="暂无未恢复故障">
          <el-table-column prop="name" label="故障项目" min-width="145" />
          <el-table-column prop="message" label="故障说明" min-width="215" />
          <el-table-column label="首次发现" min-width="175"><template #default="{row}">{{ time(row.opened_at) }}</template></el-table-column>
          <el-table-column label="告警通知" min-width="270"><template #default="{row}">{{ delivery(row) }}</template></el-table-column>
        </el-table>
      </section>
      <section aria-labelledby="history-title"><h2 id="history-title">恢复记录</h2>
        <el-table :data="history" empty-text="暂无恢复记录">
          <el-table-column prop="name" label="故障项目" min-width="145" />
          <el-table-column label="首次发现" min-width="175"><template #default="{row}">{{ time(row.opened_at) }}</template></el-table-column>
          <el-table-column label="恢复时间" min-width="175"><template #default="{row}">{{ time(row.resolved_at) }}</template></el-table-column>
          <el-table-column label="告警通知" min-width="270"><template #default="{row}">{{ delivery(row) }}</template></el-table-column>
        </el-table>
      </section>
    </template>
  </main>
</template>

<style scoped>
.alerts-page { max-width: 1500px; min-width: 0; margin: 0 auto; }
.page-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
h1 { font-size: 22px; line-height: 1.4; margin: 0; }
h2 { font-size: 16px; margin: 24px 0 12px; }
.monitor-status { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; margin: 16px 0; font-size: 14px; }
.monitor-status span { overflow-wrap: anywhere; }
.el-alert { margin-bottom: 12px; }
section { min-width: 0; }
:deep(.el-table .cell) { overflow-wrap: anywhere; }
@media (max-width: 600px) { .monitor-status { gap: 10px; } h1 { font-size: 20px; } }
</style>
