<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { policyVersionApi } from '@/api'
import PolicyThresholdFields from '@/components/PolicyThresholdFields.vue'
import type { PolicyVersion } from '@/types'
import { defaultThresholds, formatThresholds, validateThresholds } from '@/utils/policyThresholds'

const form = reactive({ scene: 'faq', scope_type: 'global', scope_value: '', enabled: true, rule_version: 'v1', thresholds: defaultThresholds('faq') })
const versions = ref<PolicyVersion[]>([])
const busy = ref(false)

async function createDraft() {
  const validationError = validateThresholds(form.scene, form.thresholds)
  if (validationError) { ElMessage.error(validationError); return }
  busy.value = true
  try { const row = await policyVersionApi.create({ ...form, scope_value: form.scope_value || null }); versions.value.unshift(row); ElMessage.success('策略草稿已创建') } finally { busy.value = false }
}
async function publish(row: PolicyVersion) {
  busy.value = true
  try { const updated = await policyVersionApi.publish(row.id); versions.value = versions.value.map(item => item.id === updated.id ? updated : (item.scene === updated.scene && item.scope_type === updated.scope_type ? { ...item, status: 'offline' } : item)); ElMessage.success('策略已发布') } finally { busy.value = false }
}
async function rollback(row: PolicyVersion) {
  busy.value = true
  try { const updated = await policyVersionApi.rollback(row.id); versions.value = [{ ...updated }, ...versions.value.map(item => item.status === 'published' ? { ...item, status: 'offline' } : item)]; ElMessage.success('已生成回滚版本') } finally { busy.value = false }
}
async function load() { versions.value = await policyVersionApi.list() }
watch(() => form.scene, (scene) => { form.thresholds = defaultThresholds(scene) })
onMounted(load)
</script>

<template>
  <div class="governance-page">
    <div class="page-heading"><span class="eyebrow">POLICY RELEASES</span><h1>策略版本</h1><p>发布后不可覆盖，回滚会生成新的可追溯版本。</p></div>
    <el-card class="governance-card" shadow="never"><el-form label-position="top" class="policy-form"><el-form-item label="场景"><el-select v-model="form.scene"><el-option label="请假" value="leave"/><el-option label="问答" value="faq"/><el-option label="工单" value="ticket"/><el-option label="文档起草" value="document"/><el-option label="邮件" value="email"/></el-select></el-form-item><el-form-item label="作用域"><el-select v-model="form.scope_type"><el-option label="全局" value="global"/><el-option label="租户" value="tenant"/><el-option label="部门" value="dept"/><el-option label="用户" value="user"/></el-select></el-form-item><el-form-item label="作用域值"><el-input v-model="form.scope_value" placeholder="可选" /></el-form-item><el-form-item label="规则版本"><el-input v-model="form.rule_version" /></el-form-item><PolicyThresholdFields v-model="form.thresholds" :scene="form.scene"/><el-form-item><el-button type="primary" :loading="busy" @click="createDraft">创建策略草稿</el-button></el-form-item></el-form></el-card>
    <el-card class="governance-card" shadow="never"><template #header><span>本页会话中的版本时间线</span></template><el-empty v-if="!versions.length" description="创建草稿后显示版本"/><div v-else class="timeline"><div v-for="row in versions" :key="row.id" class="timeline-row"><div><strong>{{ row.scene }} · {{ row.scope_type }} · v{{ row.version }}</strong><div class="threshold-summary"><el-tag v-for="item in formatThresholds(row.thresholds)" :key="item.label" size="small" effect="plain">{{ item.label }}：{{ item.value }}</el-tag></div></div><div class="row-actions"><el-tag :type="row.status === 'published' ? 'success' : row.status === 'offline' ? 'info' : 'warning'">{{ row.status }}</el-tag><el-button v-if="row.status === 'draft'" size="small" type="primary" @click="publish(row)">发布</el-button><el-button v-if="row.status === 'published'" size="small" @click="rollback(row)">回滚为新版本</el-button></div></div></div></el-card>
  </div>
</template>

<style scoped>
.governance-page { max-width: 980px; margin: 0 auto; }
.page-heading { margin-bottom: 20px; }
.eyebrow { color: #0f766e; font-size: 11px; font-weight: 700; letter-spacing: .14em; }
h1 { margin: 6px 0; color: #17324d; font-size: 28px; }
p { color: #64788b; margin: 0; }
.governance-card { margin-bottom: 16px; border: 1px solid #e1eaf0; border-radius: 14px; }
.policy-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.policy-form > :last-child { grid-column: 1 / -1; }
.timeline { display: grid; gap: 10px; }
.timeline-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 14px 16px; background: #f7fafc; border-radius: 10px; }
.timeline-row strong { color: #17324d; }
.threshold-summary { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.row-actions { display: flex; align-items: center; gap: 8px; }
@media (max-width: 720px) { .policy-form { grid-template-columns: 1fr; } .timeline-row { align-items: flex-start; flex-direction: column; } }
</style>
