<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import type { NavigationGroup } from '@/navigation'

const props = defineProps<{ groups: NavigationGroup[]; active: string; collapsed?: boolean }>()
const emit = defineEmits<{ navigate: [] }>()
const menu = ref<{ open: (index: string) => void }>()
const preferenceKey = 'oa-navigation-groups-v1'
function readOpenGroups(): string[] {
  try {
    const stored = JSON.parse(localStorage.getItem(preferenceKey) || 'null')
    if (Array.isArray(stored)) return stored.filter((value): value is string => typeof value === 'string')
  } catch { /* Invalid preferences do not affect navigation. */ }
  return props.groups.map(group => group.id)
}
const openGroups = ref(readOpenGroups())
function remember(id: string, open: boolean) {
  if (props.collapsed) return
  openGroups.value = open ? [...new Set([...openGroups.value, id])] : openGroups.value.filter(value => value !== id)
  try { localStorage.setItem(preferenceKey, JSON.stringify(openGroups.value)) } catch { /* Storage may be disabled. */ }
}
const onOpen = (id: string) => remember(id, true)
const onClose = (id: string) => remember(id, false)
watch(() => [props.active, props.collapsed, props.groups] as const, async () => {
  if (props.collapsed) return
  const group = props.groups.find(group => group.items.some(item => item.path === props.active))
  if (group) { await nextTick(); menu.value?.open(group.id) }
}, { immediate: true })
</script>

<template>
  <nav aria-label="主导航" class="oa-navigation">
    <el-menu ref="menu" router :default-active="active" :default-openeds="openGroups" :collapse="collapsed"
      :collapse-transition="false" class="oa-navigation-menu" @select="emit('navigate')"
      @open="onOpen" @close="onClose">
      <el-sub-menu v-for="group in groups" :key="group.id" :index="group.id" popper-class="oa-navigation-popover">
        <template #title><el-icon><component :is="group.icon" /></el-icon><span>{{ group.label }}</span></template>
        <el-menu-item v-for="item in group.items" :key="item.path" :index="item.path" :route="item.target || item.path">
          <el-icon><component :is="item.icon" /></el-icon><template #title>{{ item.label }}</template>
        </el-menu-item>
      </el-sub-menu>
    </el-menu>
    <el-empty v-if="!groups.length && !collapsed" description="暂无可访问的功能" :image-size="56" />
  </nav>
</template>
