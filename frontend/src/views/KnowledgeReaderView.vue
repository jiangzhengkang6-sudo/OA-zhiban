<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { knowledgeApi } from '@/api'
import type { KnowledgeReading } from '@/types'
import { sourceLocation } from '@/utils/source-location'
import { authState } from '@/stores/auth'

const route = useRoute()
const document = ref<KnowledgeReading | null>(null)
const busy = ref(false)
const error = ref('')
let generation = 0
async function locate() {
  await nextTick()
  if (route.hash.startsWith('#chunk-')) window.document.getElementById(route.hash.slice(1))?.scrollIntoView({ block: 'center' })
}
async function load() {
  const current = ++generation
  document.value = null
  error.value = ''
  busy.value = true
  try {
    const value = await knowledgeApi.readVersion(String(route.params.sourceId), String(route.params.versionId))
    if (current !== generation) return
    document.value = value
    await locate()
  } catch {
    if (current === generation) error.value = '资料无法读取，可能已下线、过期或访问权限已变更。'
  } finally {
    if (current === generation) busy.value = false
  }
}
watch(() => [route.params.sourceId, route.params.versionId, authState.user?.user_id], load, { immediate: true })
watch(() => route.hash, locate)
onBeforeUnmount(() => { generation++ })
</script>

<template>
  <section class="knowledge-reading" aria-label="知识资料正文">
    <nav><router-link to="/knowledge">知识库</router-link></nav>
    <el-skeleton v-if="busy" :rows="6" animated />
    <template v-else-if="document">
      <header><h1>{{ document.title }}</h1><span class="version">第 {{ document.version }} 版 · 已发布</span></header>
      <article v-for="block in document.blocks" :id="'chunk-' + block.id" :key="block.id"
        class="reading-block" :class="{ cited: route.hash === '#chunk-' + block.id }">
        <h2>{{ sourceLocation(block.source_location) }}</h2>
        <p>{{ block.text }}</p>
      </article>
      <el-empty v-if="!document.blocks.length" description="暂无可读内容" />
    </template>
    <el-alert v-else-if="error" :title="error" type="warning" :closable="false" show-icon />
    <el-button v-if="error" @click="load">重新加载</el-button>
  </section>
</template>

<style scoped>
.knowledge-reading { max-width: 900px; margin: 0 auto; min-width: 0; }
nav { margin-bottom: 20px; }
nav a { color: var(--el-color-primary); }
header { border-bottom: 1px solid #dfe5e8; padding-bottom: 20px; margin-bottom: 12px; }
h1 { margin: 0 0 12px; font-size: 24px; line-height: 1.5; overflow-wrap: anywhere; }
.version { color: #606970; font-size: 13px; }
.reading-block { padding: 18px 16px; border-bottom: 1px solid #e4e8eb; scroll-margin-top: 24px; }
.reading-block.cited { background: #eef8f3; border-left: 3px solid #16856b; }
h2 { margin: 0 0 10px; font-size: 14px; color: #4f6260; overflow-wrap: anywhere; }
p { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 14px; line-height: 1.9; }
.el-button { margin-top: 16px; }
@media (max-width: 600px) { h1 { font-size: 20px; } .reading-block { padding: 16px 8px; } }
</style>
