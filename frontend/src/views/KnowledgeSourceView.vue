<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { UploadFile } from 'element-plus'
import { knowledgeApi } from '@/api'
import type { KnowledgePreview, KnowledgeVersion } from '@/types'

const sourceName = ref('')
const permissionTags = ref('')
const selectedFile = ref<File | null>(null)
const fileList = ref<UploadFile[]>([])
const preview = ref<KnowledgePreview | null>(null)
const version = ref<KnowledgeVersion | null>(null)
const busy = ref(false)

function choose(file: UploadFile) {
  selectedFile.value = file.raw || null
  fileList.value = [file]
  preview.value = null
  version.value = null
}
function remove() { selectedFile.value = null; fileList.value = []; preview.value = null; version.value = null }
async function previewFile() {
  if (!selectedFile.value) return ElMessage.warning('请先选择文件')
  busy.value = true
  try { preview.value = await knowledgeApi.preview(selectedFile.value); ElMessage.success('解析预览已生成') } finally { busy.value = false }
}
async function createDraft() {
  if (!selectedFile.value || !sourceName.value) return ElMessage.warning('请填写来源名称并选择文件')
  const form = new FormData(); form.append('source_name', sourceName.value); form.append('file', selectedFile.value); form.append('permission_tags', permissionTags.value)
  busy.value = true
  try { version.value = await knowledgeApi.uploadVersion(form); ElMessage.success('已创建草稿版本') } finally { busy.value = false }
}
async function publish() {
  if (!version.value) return
  busy.value = true
  try { version.value = await knowledgeApi.publishVersion(version.value.id); ElMessage.success('版本已发布') } finally { busy.value = false }
}
</script>

<template>
  <div class="governance-page">
    <div class="page-heading"><span class="eyebrow">KNOWLEDGE GOVERNANCE</span><h1>来源与版本</h1><p>先预览解析，再创建草稿，最后显式发布。</p></div>
    <el-card class="governance-card" shadow="never">
      <el-form label-position="top">
        <el-form-item label="来源名称"><el-input v-model="sourceName" placeholder="如：员工手册" /></el-form-item>
        <el-form-item label="权限标签"><el-input v-model="permissionTags" placeholder="employee,manager；留空表示公开" /></el-form-item>
        <el-form-item label="原始文件"><el-upload :auto-upload="false" :file-list="fileList" :on-change="choose" :on-remove="remove" accept=".md,.markdown,.html,.htm,.pdf"><el-button>选择文件</el-button></el-upload></el-form-item>
        <div class="action-row"><el-button :loading="busy" @click="previewFile">预览解析</el-button><el-button type="primary" :loading="busy" @click="createDraft">创建草稿</el-button><el-button type="success" :disabled="!version || version.status === 'published'" :loading="busy" @click="publish">发布版本</el-button></div>
      </el-form>
    </el-card>
    <el-card v-if="preview" class="governance-card" shadow="never"><template #header><div class="card-title"><span>解析预览</span><el-tag>{{ preview.format.toUpperCase() }} · {{ preview.blocks.length }} 个区块</el-tag></div></template><div class="preview-list"><article v-for="(block, index) in preview.blocks" :key="index"><div class="preview-meta">{{ block.section || '正文' }}<span v-if="block.page">第 {{ block.page }} 页</span></div><p>{{ block.text }}</p></article></div></el-card>
    <el-card v-if="version" class="governance-card result-card" shadow="never"><div class="version-state"><div><span class="eyebrow">VERSION {{ version.version }}</span><h2>{{ version.status === 'published' ? '已发布，可参与检索' : '草稿，等待发布' }}</h2></div><el-tag :type="version.status === 'published' ? 'success' : 'warning'">{{ version.status }}</el-tag></div><p class="muted">解析状态：{{ version.parse_status }} · SHA-256：{{ version.content_hash }}</p></el-card>
  </div>
</template>

<style scoped>
.governance-page { max-width: 980px; margin: 0 auto; }
.page-heading { margin-bottom: 20px; }
.eyebrow { color: #0f766e; font-size: 11px; font-weight: 700; letter-spacing: .14em; }
h1 { margin: 6px 0; color: #17324d; font-size: 28px; }
h2 { margin: 6px 0 0; color: #17324d; }
p { color: #64788b; margin: 0; }
.governance-card { margin-bottom: 16px; border: 1px solid #e1eaf0; border-radius: 14px; }
.action-row,.card-title,.version-state { display: flex; align-items: center; gap: 10px; }
.card-title,.version-state { justify-content: space-between; }
.preview-list { display: grid; gap: 12px; }
.preview-list article { padding: 14px 16px; background: #f7fafc; border-radius: 10px; border-left: 3px solid #0f766e; }
.preview-meta { display: flex; gap: 14px; color: #0f766e; font-size: 12px; font-weight: 600; margin-bottom: 6px; }
.preview-meta span { color: #8aa0b2; font-weight: 400; }
.result-card { background: linear-gradient(135deg, #f1fbf8, #fff); }
.muted { font-size: 13px; margin-top: 12px; overflow-wrap: anywhere; }
</style>
