<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { operationsApi } from '@/api'
import type { DegradationState } from '@/types'

const rows = ref<DegradationState[]>([])
const busy = ref(false)
const form = reactive({ scene: 'faq', scope_type: 'tenant', scope_value: '', new_task_action: 'fallback', inflight_action: 'continue', reason: '' })
async function load() { rows.value = await operationsApi.degradations() }
async function create() {
  if (!form.reason.trim()) { ElMessage.warning('请填写降级原因'); return }
  busy.value = true
  try { await operationsApi.createDegradation({ ...form, scope_value: form.scope_value || null }); ElMessage.success('降级已生效'); form.reason = ''; await load() } finally { busy.value = false }
}
async function restore(row: DegradationState) {
  await ElMessageBox.confirm('确认恢复 ' + row.scene + ' 场景吗？', '恢复降级', { type: 'warning' })
  await operationsApi.restoreDegradation(row.id); ElMessage.success('已恢复'); await load()
}
onMounted(load)
</script>

<template>
  <div class="workbench">
    <div class="page-heading"><div><span class="eyebrow">DEGRADATION CONTROL</span><h1>降级控制</h1><p class="muted">仅管理员可操作。新任务和在途任务策略分别生效，并保留恢复记录。</p></div><el-button @click="load">刷新</el-button></div>
    <el-card shadow="never" class="surface"><template #header><span>创建降级开关</span></template>
      <el-form label-position="top" class="form-grid">
        <el-form-item label="场景"><el-select v-model="form.scene"><el-option label="问答" value="faq"/><el-option label="请假" value="leave"/><el-option label="工单" value="ticket"/><el-option label="文档起草" value="document"/><el-option label="邮件" value="email"/><el-option label="业务任务" value="work_task"/><el-option label="报表" value="report"/><el-option label="合同" value="contract"/></el-select></el-form-item>
        <el-form-item label="作用域"><el-select v-model="form.scope_type"><el-option label="全局" value="global"/><el-option label="租户" value="tenant"/><el-option label="部门" value="dept"/><el-option label="用户" value="user"/></el-select></el-form-item>
        <el-form-item label="作用域值"><el-input v-model="form.scope_value" placeholder="全局时留空" /></el-form-item>
        <el-form-item label="新任务"><el-select v-model="form.new_task_action"><el-option label="回退人工" value="fallback"/><el-option label="拒绝请求" value="reject"/></el-select></el-form-item>
        <el-form-item label="在途任务"><el-select v-model="form.inflight_action"><el-option label="继续执行" value="continue"/><el-option label="暂停任务" value="pause"/></el-select></el-form-item>
        <el-form-item label="原因"><el-input v-model="form.reason" placeholder="例如：知识服务维护" /></el-form-item>
        <el-form-item class="form-actions"><el-button type="primary" :loading="busy" @click="create">立即降级</el-button></el-form-item>
      </el-form>
    </el-card>
    <el-card shadow="never" class="surface"><template #header><span>降级记录</span></template>
      <el-table :data="rows" size="small"><el-table-column prop="scene" label="场景" width="90"/><el-table-column label="作用域" width="150"><template #default="{ row }">{{ row.scope_type }}{{ row.scope_value ? ' · ' + row.scope_value : '' }}</template></el-table-column><el-table-column prop="reason" label="原因" min-width="180"/><el-table-column label="新任务" width="110"><template #default="{ row }"><el-tag size="small">{{ row.new_task_action }}</el-tag></template></el-table-column><el-table-column label="在途" width="100"><template #default="{ row }"><el-tag size="small" type="warning">{{ row.inflight_action }}</el-tag></template></el-table-column><el-table-column label="状态" width="90"><template #default="{ row }"><el-tag size="small" :type="row.enabled ? 'danger' : 'info'">{{ row.enabled ? '生效中' : '已恢复' }}</el-tag></template></el-table-column><el-table-column label="操作" width="90"><template #default="{ row }"><el-button v-if="row.enabled" link type="primary" @click="restore(row)">恢复</el-button></template></el-table-column></el-table>
      <el-empty v-if="!rows.length" description="暂无降级记录" />
    </el-card>
  </div>
</template>
