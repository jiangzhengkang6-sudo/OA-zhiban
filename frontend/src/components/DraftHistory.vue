<script setup lang="ts">
import { computed, ref } from 'vue'
const props = defineProps<{ versions: { version: number; draft: unknown }[]; current: string; textOf: (draft: any) => string }>()
const selected = ref<number | null>(null)
const previous = computed(() => props.versions.find(item => item.version === selected.value))
</script>
<template>
  <section class="draft-history"><h2>版本比较</h2><el-select v-model="selected" aria-label="比较历史版本" placeholder="选择历史版本" clearable><el-option v-for="version in versions" :key="version.version" :label="`v${version.version}`" :value="version.version" /></el-select>
    <div v-if="previous" class="version-columns"><div><h3>历史 v{{ previous.version }}</h3><pre>{{ textOf(previous.draft) }}</pre></div><div><h3>当前草稿</h3><pre>{{ current }}</pre></div></div>
  </section>
</template>
<style scoped>
.draft-history { border-top: 1px solid #dce3e7; margin-top: 24px; padding-top: 20px; }
h2 { font-size: 17px; } h3 { font-size: 14px; } .el-select { width: 180px; }
.version-columns { display: grid; grid-template-columns: minmax(0,1fr) minmax(0,1fr); gap: 24px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; line-height: 1.7; background: #f4f6f7; padding: 16px; }
@media(max-width: 700px) { .version-columns { grid-template-columns: 1fr; } }
</style>
