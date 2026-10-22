<script setup lang="ts">
/**
 * OA 智能体系统 MVP - 状态标签组件。
 *
 * 根据状态码渲染对应中文文案与颜色的 Element Plus 标签。
 */
import { computed } from 'vue'
import { statusOf } from '@/utils/status'

const props = defineProps<{ status?: string | null }>()

const info = computed(() => statusOf(props.status))
</script>

<template>
  <el-tag :type="info.type" size="small">{{ info.label }}</el-tag>
</template>