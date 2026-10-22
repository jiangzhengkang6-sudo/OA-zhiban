<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { leaveApi } from '@/api'
import type { LeaveApplication } from '@/types'
import StatusTag from '@/components/StatusTag.vue'
import { displayTime } from '@/utils/leave'
const route = useRoute(), router = useRouter()
const items = ref<LeaveApplication[]>([]), total = ref(0), page = ref(1), status = ref(''), loading = ref(false), error = ref('')
async function load() {
  loading.value = true; error.value = ''
  try { const data = await leaveApi.list({ page: page.value, page_size: 20, status: status.value || undefined }); items.value = data.items; total.value = data.total }
  catch { items.value = []; error.value = '请假列表加载失败，请重试' } finally { loading.value = false }
}
watch(() => route.query, value => { page.value = Math.max(1, Number(value.page) || 1); status.value = String(value.status || ''); void load() }, { immediate: true })
</script>
<template>
  <section class="workbench"><div class="page-heading"><div><p class="eyebrow">员工服务</p><h1>我的请假</h1><p class="muted">保存草稿、查看进度，修改后重新提交。</p></div><el-button type="primary" @click="router.push('/leaves/new')">新建请假</el-button></div>
    <div class="filters"><el-select v-model="status" placeholder="全部状态" clearable @change="router.replace({ query: { status: status || undefined } })"><el-option label="草稿" value="DRAFT" /><el-option label="待补充" value="NEEDS_FIX" /><el-option label="审批中" value="SUBMITTED" /><el-option label="已驳回" value="REJECTED" /><el-option label="已批准" value="APPROVED" /></el-select><span class="muted">共 {{ total }} 条</span><el-button @click="load">刷新</el-button></div>
    <el-skeleton v-if="loading" :rows="6" animated /><el-result v-else-if="error" icon="warning" :title="error"><template #extra><el-button @click="load">重试</el-button></template></el-result>
    <el-table v-else-if="items.length" :data="items" class="surface"><el-table-column label="申请单" min-width="180"><template #default="{ row }"><el-link type="primary" @click="router.push('/leaves/' + row.application_id)">{{ row.business_id }}</el-link></template></el-table-column><el-table-column label="原因" min-width="180"><template #default="{ row }">{{ row.fields.reason || '—' }}</template></el-table-column><el-table-column label="状态" width="120"><template #default="{ row }"><StatusTag :status="row.status" /></template></el-table-column><el-table-column prop="version" label="版本" width="80" /><el-table-column label="更新时间" min-width="180"><template #default="{ row }">{{ displayTime(row.updated_at) }}</template></el-table-column></el-table><el-empty v-else description="还没有请假申请，点击新建请假开始填写" />
    <el-pagination v-if="total > 20" :current-page="page" :page-size="20" :total="total" layout="prev, pager, next" @current-change="router.replace({ query: { ...route.query, page: String($event) } })" />
  </section>
</template>
