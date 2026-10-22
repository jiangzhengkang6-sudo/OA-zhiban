<script setup lang="ts">
import { computed } from 'vue'
import { thresholdFieldsForScene, type PolicyThresholds } from '@/utils/policyThresholds'

const props = defineProps<{ scene: string; modelValue: PolicyThresholds }>()
const emit = defineEmits<{ 'update:modelValue': [value: PolicyThresholds] }>()

const fields = computed(() => thresholdFieldsForScene(props.scene))

function displayValue(key: string, unit: 'percent' | 'minutes') {
  const value = props.modelValue[key]
  if (unit === 'percent') return value === undefined ? undefined : value * 100
  return value === undefined ? undefined : value / 60
}

function updateValue(key: string, unit: 'percent' | 'minutes', value: number | null | undefined) {
  const next = { ...props.modelValue }
  if (value === null || value === undefined) {
    delete next[key]
  } else {
    next[key] = unit === 'percent' ? value / 100 : value * 60
  }
  emit('update:modelValue', next)
}
</script>

<template>
  <div class="threshold-fields">
    <el-form-item v-for="field in fields" :key="field.key" :label="field.label">
      <el-input-number
        :model-value="displayValue(field.key, field.unit)"
        :min="0"
        :max="field.unit === 'percent' ? 100 : undefined"
        :step="field.unit === 'percent' ? 1 : 1"
        :precision="field.unit === 'percent' ? 0 : 0"
        controls-position="right"
        @update:model-value="updateValue(field.key, field.unit, $event)"
      />
      <span class="threshold-unit">{{ field.unit === 'percent' ? '%' : '分钟' }}</span>
    </el-form-item>
  </div>
</template>

<style scoped>
.threshold-fields { display: contents; }
.threshold-unit { margin-left: 8px; color: #64748b; }
</style>
