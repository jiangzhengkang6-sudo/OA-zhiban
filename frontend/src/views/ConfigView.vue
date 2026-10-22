<script setup lang="ts">
/**
 * OA 智能体系统 MVP - 智能配置页面。
 *
 * 管理员配置场景开关、灰度范围、阈值与规则版本，并提供 Mock 用户切换以演示不同角色。
 */
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { policyApi } from '@/api'
import PolicyThresholdFields from '@/components/PolicyThresholdFields.vue'
import type { PolicyOut } from '@/types'
import { defaultThresholds, formatThresholds, validateThresholds } from '@/utils/policyThresholds'

const policies = ref<PolicyOut[]>([])
const loading = ref(false)

const form = reactive({
  scene: 'leave',
  scope_type: 'global',
  enabled: true,
  rule_version: 'v1',
  thresholds: defaultThresholds('leave'),
})


async function load() {
  loading.value = true
  try {
    policies.value = await policyApi.list()
  } finally {
    loading.value = false
  }
}


/** 保存策略 */
async function save() {
  const validationError = validateThresholds(form.scene, form.thresholds)
  if (validationError) { ElMessage.error(validationError); return }
  await policyApi.upsert({
    scene: form.scene,
    scope_type: form.scope_type,
    enabled: form.enabled,
    rule_version: form.rule_version,
    thresholds: form.thresholds,
  })
  ElMessage.success('已保存')
  await load()
}

watch(() => form.scene, (scene) => { form.thresholds = defaultThresholds(scene) })
onMounted(load)
</script>

<template>
  <div class="config">

    <el-card shadow="never" style="margin-bottom: 16px">
      <template #header><span>新增/更新场景策略</span></template>
      <el-form label-width="100px">
        <el-form-item label="场景">
          <el-select v-model="form.scene">
            <el-option label="请假" value="leave" />
            <el-option label="问答" value="faq" />
            <el-option label="工单" value="ticket" />
            <el-option label="文档起草" value="document" />
            <el-option label="邮件" value="email" />
            <el-option label="业务任务" value="work_task" />
            <el-option label="报表" value="report" />
            <el-option label="合同" value="contract" />
          </el-select>
        </el-form-item>
        <el-form-item label="作用范围">
          <el-select v-model="form.scope_type">
            <el-option label="全局" value="global" />
            <el-option label="部门" value="dept" />
            <el-option label="用户" value="user" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-form-item label="规则版本">
          <el-input v-model="form.rule_version" style="width: 200px" />
        </el-form-item>
        <PolicyThresholdFields v-model="form.thresholds" :scene="form.scene" />
        <el-form-item>
          <el-button type="primary" @click="save">保存策略</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <template #header><span>现有策略</span></template>
      <el-table :data="policies" v-loading="loading" border size="small">
        <el-table-column prop="scene" label="场景" width="100" />
        <el-table-column prop="scope_type" label="范围" width="100" />
        <el-table-column prop="scope_value" label="范围值" width="120" />
        <el-table-column label="启用" width="90">
          <template #default="{ row }">
            <el-tag :type="row.enabled ? 'success' : 'info'" size="small">
              {{ row.enabled ? '开' : '关' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="rule_version" label="规则版本" width="110" />
        <el-table-column label="阈值">
          <template #default="{ row }">
            <div class="threshold-summary"><el-tag v-for="item in formatThresholds(row.thresholds)" :key="item.label" size="small" effect="plain">{{ item.label }}：{{ item.value }}</el-tag></div>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!policies.length" description="暂无策略" />
    </el-card>
  </div>
</template>

<style scoped>
.row {
  display: flex;
  gap: 12px;
  align-items: center;
}
.threshold-summary { display: flex; flex-wrap: wrap; gap: 6px; }
</style>
