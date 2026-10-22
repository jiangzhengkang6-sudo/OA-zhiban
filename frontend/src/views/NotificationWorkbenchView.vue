<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { oaApi } from '@/api/oa'
import { authState, can } from '@/stores/auth'
import { messageOf, useOACommands } from '@/utils/oa'
import type { NotificationDelivery, NotificationItem } from '@/types/oa'

const { busy, error, run } = useOACommands()
const items = ref<NotificationItem[]>([]), deliveries = ref<NotificationDelivery[]>([])
const loading = ref(false), tab = ref<'inbox'|'delivery'|'contact'>('inbox'), note = ref('')
const contact = reactive({ email:'', enabled:false, wecom_enabled:false, wecom_available:false })
const isAdmin = computed(() => can('notification_admin','read'))
const unread = computed(() => items.value.filter(item => !item.read_at).length)
const states: Record<string,string> = { PENDING:'待发送', PROCESSING:'发送中', ACCEPTED:'服务已接收', FAILED:'发送失败', UNKNOWN:'结果不明', CANCELLED:'已取消' }
const codes: Record<string,string> = {
  contact_not_configured:'未授权邮件收件', source_unavailable:'业务来源或权限已失效',
  preflight_unavailable:'发送前授权核对未通过', destination_or_consent_unavailable:'群路由或本人授权已失效',
  wecom_rate_limited:'群机器人发送限流，稍后重试', lease_expired_possible_acceptance:'发送超时，需核对是否已接收',
  manual_retry_possible_duplicate:'人工核对后重试，可能重复',
}
function stateText(state?:string|null) { return state ? states[state] || '待核对' : '未启用' }
function codeText(code:string|null) {
  if (!code) return '暂无'
  if (codes[code]) return codes[code]
  const result = code.replace(/^(smtp|wecom)_/, '')
  return ({ accepted:'服务已接收', temporary:'暂时失败，等待重试', permanent:'投递被拒绝', unknown:'结果不明，需人工核对' } as Record<string,string>)[result] || '待核对'
}
async function load() {
  loading.value = true; error.value = ''
  try {
    if (tab.value === 'inbox') items.value = await oaApi.notifications()
    if (tab.value === 'delivery' && isAdmin.value) deliveries.value = await oaApi.deliveries()
    if (tab.value === 'contact') Object.assign(contact, {wecom_enabled:false,wecom_available:false}, await oaApi.contact(authState.user?.user_id || ''))
  } catch(e) { error.value = messageOf(e) } finally { loading.value = false }
}
async function read(item:NotificationItem) {
  if (item.read_at) return
  try { await oaApi.readNotification(item.id); item.read_at = new Date().toISOString() } catch(e) { error.value = messageOf(e) }
}
async function retry(row:NotificationDelivery) {
  const result = await run('notification:retry', {operation_id:crypto.randomUUID(),note:note.value || '已核对收件人、群消息和业务来源，确认可能重复'}, p => oaApi.retryDelivery(row.id,p))
  if (result) { note.value = ''; await load() }
}
async function saveContact() {
  const id = authState.user?.user_id
  if (!id) return
  const result = await run('notification:contact', {operation_id:crypto.randomUUID(),email:contact.email.trim(),enabled:contact.enabled,wecom_enabled:contact.wecom_enabled}, p => oaApi.saveContact(id,p))
  if (result) await load()
}
onMounted(load)
</script>

<template>
  <main class="workbench manual-oa notification-page" v-loading="loading">
    <header class="page-heading"><div><p class="eyebrow">正式 OA · 消息中心</p><h1>通知与站内信</h1></div><el-button :icon="Refresh" @click="load">刷新</el-button></header>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <el-tabs v-model="tab" @tab-change="load">
      <el-tab-pane name="inbox"><template #label>站内信<span v-if="unread" class="count">{{unread}}</span></template></el-tab-pane>
      <el-tab-pane v-if="isAdmin" name="delivery" label="投递状态"/>
      <el-tab-pane name="contact" label="授权核对"/>
    </el-tabs>
    <section v-if="tab==='inbox'" class="oa-section">
      <el-empty v-if="!items.length" description="暂无站内信"/>
      <article v-for="item in items" :key="item.id" class="notice-row" :class="{unread:!item.read_at}">
        <div><strong>{{item.title}}</strong><p class="muted">{{new Date(item.created_at).toLocaleString('zh-CN')}}</p><p class="muted">站内信：{{item.inbox_state==='ACCEPTED'?'已送达':'未送达'}} · 邮件：{{stateText(item.smtp_state)}} · 企业微信：{{stateText(item.wecom_state)}}</p></div>
        <el-button v-if="!item.read_at" @click="read(item)">标记已读</el-button><el-tag v-else type="info">已读</el-tag>
      </article>
    </section>
    <section v-else-if="tab==='delivery'" class="oa-section">
      <el-table :data="deliveries" empty-text="暂无投递记录">
        <el-table-column prop="recipient_id" label="收件人" min-width="160"/>
        <el-table-column label="渠道" width="100"><template #default="{row}">{{row.channel==='wecom'?'企业微信':'邮件'}}</template></el-table-column>
        <el-table-column label="状态" width="110"><template #default="{row}">{{stateText(row.state)}}</template></el-table-column>
        <el-table-column prop="attempt_count" label="尝试次数" width="100"/>
        <el-table-column label="结果说明" min-width="200"><template #default="{row}">{{codeText(row.last_code)}}</template></el-table-column>
        <el-table-column label="操作" width="120"><template #default="{row}"><el-button v-if="row.state==='UNKNOWN'" link type="primary" @click="retry(row)">核对并重试</el-button></template></el-table-column>
      </el-table>
      <el-input v-model="note" class="review-note" placeholder="人工核对备注"/>
    </section>
    <section v-else class="oa-section">
      <el-alert title="企业微信群内所有成员均可看到提醒；群消息不包含业务正文。" type="warning" :closable="false"/>
      <el-form label-position="top" class="contact-form">
        <el-form-item label="收件邮箱"><el-input v-model="contact.email" type="email"/></el-form-item>
        <el-form-item label="启用邮件通知"><el-switch v-model="contact.enabled" aria-label="启用邮件通知"/></el-form-item>
        <el-form-item label="授权企业微信群提醒"><el-switch v-model="contact.wecom_enabled" :disabled="!contact.wecom_available && !contact.wecom_enabled" aria-label="授权企业微信群提醒"/><el-tag v-if="!contact.wecom_available" type="info" class="route-state">本部门尚未接通</el-tag></el-form-item>
        <el-button type="primary" :loading="busy" :disabled="contact.enabled && !contact.email.trim()" @click="saveContact">保存授权配置</el-button>
      </el-form>
    </section>
  </main>
</template>

<style scoped>
.notification-page .notice-row{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:18px 0;border-bottom:1px solid var(--oa-border)}
.notification-page .notice-row>div{min-width:0;overflow-wrap:anywhere}
.notification-page .notice-row.unread{border-left:3px solid var(--oa-primary);padding-left:14px}
.notification-page .count{display:inline-flex;min-width:20px;height:20px;align-items:center;justify-content:center;margin-left:6px;border-radius:10px;background:#c44b33;color:#fff;font-size:12px}
.review-note{max-width:520px;margin-top:16px}.contact-form{max-width:520px;margin-top:20px}.route-state{margin-left:12px}
@media(max-width:600px){.notification-page .notice-row{align-items:flex-start;flex-direction:column}}
</style>
