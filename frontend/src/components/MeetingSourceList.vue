<script setup lang="ts">
import type { MeetingSegment } from '@/types'
defineProps<{ segments: MeetingSegment[] }>()
</script>

<template>
  <section class="source-list" aria-label="会议来源片段">
    <div class="section-title"><h2>原文与来源</h2><span>{{ segments.length }} 个片段</span></div>
    <p class="hint">草稿中的来源编号对应下方原文，可逐条核对。</p>
    <article v-for="segment in segments" :id="`source-${segment.segment_id}`" :key="segment.segment_id" class="source-card">
      <div class="source-head"><strong>来源 {{ segment.ordinal }}</strong><small>{{ segment.locator }}</small></div>
      <p>{{ segment.text }}</p>
    </article>
    <el-empty v-if="!segments.length" description="创建会议后将显示来源片段" />
  </section>
</template>

<style scoped>
.source-list { min-width: 0; }
.section-title,.source-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.section-title h2 { margin: 0; font-size: 18px; color: #17324d; }
.section-title span,.hint,.source-head small { color: #657e91; font-size: 13px; }
.hint { margin: 8px 0 18px; }
.source-card { border: 1px solid #dce8ed; background: #fff; border-radius: 12px; padding: 16px; margin: 0 0 12px; scroll-margin-top: 24px; }
.source-card:target { border-color: #318b9a; box-shadow: 0 0 0 3px #d8eff0; }
.source-head strong { color: #246e7b; font-size: 13px; }
.source-card p { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.75; color: #284258; margin: 12px 0 0; }
</style>
