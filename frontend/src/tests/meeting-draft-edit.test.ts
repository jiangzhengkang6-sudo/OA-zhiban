import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import MeetingDraftEditor from '@/components/MeetingDraftEditor.vue'
import type { MeetingDraft, MeetingSegment } from '@/types'

const segments = [
  { segment_id: 's1', ordinal: 1, text: '议题一', start_offset: 0, end_offset: 3, locator: 'chars:0-3', text_hash: 'a'.repeat(64), summary: '议题一' },
  { segment_id: 's2', ordinal: 2, text: '议题二', start_offset: 3, end_offset: 6, locator: 'chars:3-6', text_hash: 'b'.repeat(64), summary: '议题二' },
] satisfies MeetingSegment[]
const draft: MeetingDraft = { summary: '纪要', topics: [], source_refs: ['s1'], decisions: [], action_items: [] }

describe('meeting draft editing', () => {
  it('adds and removes candidates while retaining valid source anchors', async () => {
    const wrapper = mount(MeetingDraftEditor, { props: { modelValue: draft, segments, editable: true }, global: { plugins: [ElementPlus] } })
    await wrapper.get('[data-testid=add-topic]').trigger('click')
    expect(wrapper.emitted('update:modelValue')!.at(-1)![0]).toMatchObject({ topics: ['新议题'] })
    await wrapper.setProps({ modelValue: wrapper.emitted('update:modelValue')!.at(-1)![0] as MeetingDraft })
    await wrapper.get('[data-testid=add-decision]').trigger('click')
    const changed = wrapper.emitted('update:modelValue')!.at(-1)![0] as MeetingDraft
    expect(changed.decisions[0]).toMatchObject({ source_refs: ['s1'], confidence: 'needs_confirmation' })
    await wrapper.setProps({ modelValue: changed })
    await wrapper.get('[data-testid=add-action]').trigger('click')
    const withAction = wrapper.emitted('update:modelValue')!.at(-1)![0] as MeetingDraft
    expect(withAction.action_items[0]).toMatchObject({ source_refs: ['s1'], needs_confirmation: true })
    await wrapper.setProps({ modelValue: withAction })
    await wrapper.get('[data-testid=remove-decision-0]').trigger('click')
    expect((wrapper.emitted('update:modelValue')!.at(-1)![0] as MeetingDraft).decisions).toEqual([])
    wrapper.unmount()
  })

  it('lets the reviewer replace summary source references', async () => {
    const wrapper = mount(MeetingDraftEditor, { props: { modelValue: draft, segments, editable: true }, global: { plugins: [ElementPlus] } })
    const sourcePicker = wrapper.findAllComponents({ name: 'ElSelect' })[0]
    expect(sourcePicker.exists()).toBe(true)
    sourcePicker.vm.$emit('update:modelValue', ['s2'])
    expect(wrapper.emitted('update:modelValue')!.at(-1)![0]).toMatchObject({ source_refs: ['s2'] })
    wrapper.unmount()
  })
})
