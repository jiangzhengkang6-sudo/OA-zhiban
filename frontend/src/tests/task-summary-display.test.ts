import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import TaskSummary from '@/components/TaskSummary.vue'

describe('task summary display', () => {
  it('renders P3 task types and statuses with Chinese labels', () => {
    const wrapper = mount(TaskSummary, {
      props: {
        task: {
          task_id: 'task-001',
          task_type: 'contract',
          business_id: 'CON-001',
          business_status: 'PUBLISHED',
          responsibility: { role: 'owner', user_id: 'u_emp_001' },
          available_actions: [],
          updated_at: '2026-10-15T00:00:00Z',
        },
      },
      global: {
        stubs: {
          'el-button': { template: '<button><slot /></button>' },
          'el-tag': { template: '<span><slot /></span>' },
        },
      },
    })

    expect(wrapper.text()).toContain('合同审查')
    expect(wrapper.text()).toContain('已发布')
    expect(wrapper.text()).not.toContain('PUBLISHED')
    expect(wrapper.text()).not.toContain('contract')
  })
})
