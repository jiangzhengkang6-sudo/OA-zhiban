import { expect, test } from '@playwright/test'

const roles = [
  { label: '员工', option: '张三 · 员工', userId: 'u_emp_001', visible: ['我的任务', '我的请假'], hidden: ['审批待办', '客服队列', '审计中心'] },
  { label: '一级审批人', option: '李四 · 一级审批', userId: 'u_mgr_001', visible: ['审批待办'], hidden: ['客服队列', '审计中心'] },
  { label: '二级审批人', option: '王五 · 二级审批', userId: 'u_mgr_002', visible: ['审批待办'], hidden: ['客服队列', '审计中心'] },
  { label: '客服', option: '赵六 · 客服', userId: 'u_cs_001', visible: ['客服队列'], hidden: ['审批待办', '审计中心'] },
  { label: '管理员', option: '管理员', userId: 'u_admin_001', visible: ['智能配置', '审计中心', '运维观测', '降级控制'], hidden: ['客服队列'] },
]

test.describe('P1 五类角色入口', () => {
  test.beforeEach(async ({ page }) => {
      await page.route(url => new URL(url).pathname.startsWith('/api/'), async route => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: '0', data: [] }) })
    })
  })

  for (const role of roles) {
    test(`${role.label}菜单按角色显示`, async ({ page }) => {
      await page.goto('/')
      await page.locator('.identity-switch .el-select__wrapper').click()
      await page.getByRole('option', { name: role.option, exact: true }).click()
      await expect(page.getByText('OA 智能助手')).toBeVisible()
      for (const item of role.visible) await expect(page.getByRole('menuitem', { name: item, exact: true })).toBeVisible()
      for (const item of role.hidden) await expect(page.getByRole('menuitem', { name: item, exact: true })).toHaveCount(0)
    })
  }
})
