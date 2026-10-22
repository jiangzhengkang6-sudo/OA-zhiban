<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { login, safeRedirect, homePath, configureAuth } from '@/stores/auth'
const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')
const route = useRoute()
const router = useRouter()
async function submit() {
  loading.value = true
  error.value = ''
  try {
    await configureAuth()
    await login(username.value, password.value)
    password.value = ''
    await router.replace(route.query.redirect ? safeRedirect(route.query.redirect) : homePath())
  } catch (e: any) { error.value = e.message || '登录失败，请稍后重试' }
  finally { loading.value = false }
}
</script>
<template>
  <main class="login-page">
    <section class="login-form">
      <div class="brand-mark"><el-icon :size="28"><OfficeBuilding /></el-icon></div>
      <h1>OA 工作平台</h1>
      <p class="subtitle">账号登录</p>
      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="账号"><el-input v-model="username" autocomplete="username" maxlength="128" autofocus /></el-form-item>
        <el-form-item label="密码"><el-input v-model="password" type="password" autocomplete="current-password" show-password maxlength="1024" /></el-form-item>
        <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
        <el-button class="submit" type="primary" native-type="submit" :loading="loading" :disabled="!username.trim() || !password">登录</el-button>
      </el-form>
    </section>
  </main>
</template>
<style scoped>
.login-page { min-height:100vh; display:grid; place-items:center; background:#f3f5f7; padding:24px; box-sizing:border-box; }
.login-form { width:100%; max-width:360px; }
.brand-mark { color:#16856b; margin-bottom:20px; }
h1 { font-size:28px; margin:0 0 10px; color:#202830; }
.subtitle { color:#69727d; margin:0 0 30px; }
.submit { width:100%; margin-top:22px; }
</style>
