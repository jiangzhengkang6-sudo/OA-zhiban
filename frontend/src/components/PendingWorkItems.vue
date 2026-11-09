<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { departmentApi } from '@/api/department'
import type { WorkItem } from '@/types/department'
import { displayTime } from '@/utils/leave'
const router = useRouter()
const source = ref(''), page = ref(1), total = ref(0), loading = ref(false), error = ref('')
const items = ref<WorkItem[]>([])
let generation = 0
async function load() {
  const request = ++generation
  loading.value = true; error.value = ''; items.value = []; total.value = 0
  try {
    const result = await departmentApi.pending({ source: source.value || undefined, page: page.value, page_size: 20 })
    if (request !== generation) return
    items.value = result.items; total.value = result.total
  } catch { if (request === generation) error.value = '待办加载失败，请重试' }
  finally { if (request === generation) loading.value = false }
}
watch(source, () => { page.value = 1; void load() })
onMounted(load)
onBeforeUnmount(() => { generation++ })
</script>
<template>
  <section aria-label="待我处理">
    <div class="pending-toolbar"><el-select v-model="source" aria-label="待办来源" style="width:180px"><el-option label="全部来源" value=""/><el-option label="审批待办" value="approval"/><el-option label="业务任务" value="work_task"/></el-select><span class="muted">共 {{ total }} 条</span><el-button :icon="Refresh" :loading="loading" aria-label="刷新待办" title="刷新待办" @click="load"/></div>
    <el-skeleton v-if="loading" :rows="5" animated/>
    <el-result v-else-if="error" icon="warning" :title="error"><template #extra><el-button @click="load">重新加载</el-button></template></el-result>
    <el-empty v-else-if="!items.length" description="当前没有待处理事项"/>
    <ul v-else class="pending-list"><li v-for="item in items" :key="item.id">
      <div class="pending-text"><el-tag :type="item.source==='approval' ? 'warning' : 'success'">{{ item.source==='approval' ? '审批待办' : '业务任务' }}</el-tag><h3>{{ item.title }}</h3><p class="muted">截止时间：{{ item.due_at ? displayTime(item.due_at) : '未设置' }}</p></div>
      <el-button type="primary" plain @click="router.push(item.href)">去处理</el-button>
    </li></ul>
    <el-pagination v-if="total>20" :current-page="page" :page-size="20" :total="total" layout="prev, pager, next" @current-change="page=$event; load()"/>
  </section>
</template>
<style scoped>
.pending-toolbar{display:flex;align-items:center;gap:12px;margin:16px 0}.pending-list{list-style:none;padding:0;margin:0}.pending-list li{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:18px 0;border-bottom:1px solid #dfe5e9}.pending-text{min-width:0}.pending-text h3{font-size:16px;margin:10px 0;overflow-wrap:anywhere}.pending-text p{margin:0}.pending-list .el-button{flex-shrink:0}
</style>
