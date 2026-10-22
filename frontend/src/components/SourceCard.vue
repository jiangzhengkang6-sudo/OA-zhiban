<script setup lang="ts">
/**
 * OA 智能体系统 MVP - 来源卡片组件。
 *
 * 展示 FAQ 回答的可定位来源（文档标题、段落位置、相似度）。
 */
defineProps<{
  sources?: Array<{ document_id?: string; title?: string; source_location?: string; similarity?: number }>
}>()
</script>

<template>
  <div class="source-card">
    <el-divider content-position="left">来源引用</el-divider>
    <el-timeline v-if="sources && sources.length">
      <el-timeline-item
        v-for="(s, i) in sources"
        :key="i"
        :timestamp="`相似度 ${(s.similarity ?? 0).toFixed(2)}`"
        placement="top"
        type="primary"
      >
        <div class="src-title">{{ s.title || '未命名文档' }}</div>
        <div class="src-loc">{{ s.source_location || '-' }}</div>
      </el-timeline-item>
    </el-timeline>
    <el-empty v-else description="无来源" :image-size="60" />
  </div>
</template>

<style scoped>
.source-card {
  margin-top: 12px;
}
.src-title {
  font-weight: 600;
}
.src-loc {
  color: #909399;
  font-size: 12px;
}</style>