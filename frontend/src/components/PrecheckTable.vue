<script setup lang="ts">
/**
 * OA 智能体系统 MVP - 预检结果表组件。
 *
 * 展示请假预检逐项结果（检查项、判定、原因、建议）。
 */
import { computed } from 'vue'
import { PRECHECK_ITEM_MAP } from '@/utils/status'

const props = defineProps<{
  precheck?: { results?: Array<{ item: string; result: string; reason?: string; suggestion?: string }>; items?: Array<{ item: string; result: string; reason?: string; suggestion?: string }>; passed?: boolean; rule_version?: string } | null
}>()

const items = computed(() => props.precheck?.results || props.precheck?.items || [])
</script>

<template>
  <div>
    <el-alert
      v-if="precheck"
      :title="`预检${precheck.passed ? '通过' : '未通过'}（规则版本 ${precheck.rule_version || '-'}）`"
      :type="precheck.passed ? 'success' : 'warning'"
      :closable="false"
      show-icon
    />
    <el-table :data="items" size="small" border style="margin-top: 12px">
      <el-table-column label="检查项" width="120">
        <template #default="{ row }">{{ PRECHECK_ITEM_MAP[row.item] || row.item }}</template>
      </el-table-column>
      <el-table-column label="结果" width="90">
        <template #default="{ row }">
          <el-tag :type="row.result === 'pass' ? 'success' : 'danger'" size="small">
            {{ row.result === 'pass' ? '通过' : '失败' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="原因" prop="reason" show-overflow-tooltip />
      <el-table-column label="修改建议" prop="suggestion" show-overflow-tooltip />
    </el-table>
  </div>
</template>
