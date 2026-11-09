<script setup lang="ts">
/**
 * OA 智能体系统 MVP - 知识库管理页面。
 *
 * 管理员/知识运营上传文档、查看版本/权限/生效期、下线文档。
 */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { knowledgeApi } from '@/api'
import { authState } from '@/stores/auth'

const docs = ref<any[]>([])
const loading = ref(false)

const form = reactive({
  title: '',
  content: '',
  permission_tags: '',
})

async function load() {
  loading.value = true
  try {
    docs.value = authState.provider === 'builtin' ? await knowledgeApi.listPublished() : await knowledgeApi.list()
  } finally {
    loading.value = false
  }
}

/** 导入文档 */
async function importDoc() {
  if (!form.title || !form.content) {
    ElMessage.warning('请填写标题与内容')
    return
  }
  await knowledgeApi.import({
    title: form.title,
    content: form.content,
    format: 'md',
    permission_tags: form.permission_tags.split(',').map((s) => s.trim()).filter(Boolean),
  })
  ElMessage.success('已导入')
  form.title = ''
  form.content = ''
  await load()
}

/** 下线文档 */
async function offline(row: any) {
  await knowledgeApi.updateStatus(row.id, 'offline')
  ElMessage.success('已下线')
  await load()
}

onMounted(load)
</script>

<template>
  <div>
    <el-card v-if="authState.provider !== 'builtin'" shadow="never" style="margin-bottom: 16px">
      <template #header><span>导入知识文档</span></template>
      <el-form label-width="90px">
        <el-form-item label="标题">
          <el-input v-model="form.title" placeholder="如：请假流程制度" />
        </el-form-item>
        <el-form-item label="内容">
          <el-input v-model="form.content" type="textarea" :rows="4" placeholder="文档正文（Markdown）" />
        </el-form-item>
        <el-form-item label="权限标签">
          <el-input v-model="form.permission_tags" placeholder="以逗号分隔，如 d_rd,d_ops" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="importDoc">导入</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never">
      <template #header><span>{{ authState.provider === 'builtin' ? '已发布知识资料' : '知识文档列表' }}</span></template>
      <el-table :data="docs" v-loading="loading" border size="small">
        <el-table-column label="标题" min-width="200">
          <template #default="{ row }">
            <router-link v-if="authState.provider === 'builtin'" class="source-link"
              :to="`/knowledge/sources/${row.source_id}/versions/${row.version_id}`">{{ row.title }}</router-link>
            <span v-else>{{ row.title }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="version" label="版本" width="70" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 'published' ? 'success' : 'info'" size="small">
              {{ row.status === 'published' ? '已发布' : row.status === 'offline' ? '已下线' : '草稿' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="authState.provider !== 'builtin'" label="权限标签" min-width="140">
          <template #default="{ row }">{{ (row.permission_tags || []).join(', ') || '公开' }}</template>
        </el-table-column>
        <el-table-column v-if="authState.provider !== 'builtin'" prop="owner_id" label="责任人" width="110" />
        <el-table-column v-if="authState.provider !== 'builtin'" label="操作" width="100">
          <template #default="{ row }">
            <el-button v-if="row.status !== 'offline'" type="danger" size="small" @click="offline(row)">
              下线
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.source-link { color: var(--el-color-primary); overflow-wrap: anywhere; text-underline-offset: 3px; }
</style>
