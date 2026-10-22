<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { authState, changePassword, logout } from '@/stores/auth'
const router = useRouter()
const oldPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const loading = ref(false)
async function save() {
  if (newPassword.value.length < 12) { ElMessage.error('新密码至少需要 12 个字符'); return }
  if (newPassword.value !== confirmPassword.value) { ElMessage.error('两次输入的新密码不一致'); return }
  loading.value = true
  try { await changePassword(oldPassword.value, newPassword.value); ElMessage.success('密码已修改，请重新登录'); await router.replace('/login') }
  catch (e: any) { ElMessage.error(e.message) }
  finally { oldPassword.value=''; newPassword.value=''; confirmPassword.value=''; loading.value=false }
}
async function exit() { try { await logout() } finally { await router.replace('/login') } }
</script>
<template>
  <section class="account-page">
    <h2>个人账号</h2>
    <p>{{ authState.user?.display_name }}</p>
    <el-form label-position="top" @submit.prevent="save">
      <el-form-item label="当前密码"><el-input v-model="oldPassword" type="password" autocomplete="current-password" show-password /></el-form-item>
      <el-form-item label="新密码"><el-input v-model="newPassword" type="password" autocomplete="new-password" show-password maxlength="1024" /></el-form-item>
      <el-form-item label="确认新密码"><el-input v-model="confirmPassword" type="password" autocomplete="new-password" show-password maxlength="1024" /></el-form-item>
      <el-button type="primary" native-type="submit" :loading="loading">修改密码</el-button>
      <el-button @click="exit">退出登录</el-button>
    </el-form>
  </section>
</template>
<style scoped>.account-page { max-width:420px; } h2 { font-size:22px; } p { color:#68727b; margin-bottom:28px; }</style>
