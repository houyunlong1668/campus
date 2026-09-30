/** @vitest-environment jsdom */
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ConfirmCard from '../src/components/chat/ConfirmCard.vue'

describe('ConfirmCard', () => {
  beforeEach(() => { vi.resetAllMocks(); vi.unstubAllGlobals() })

  it('点击确认后 POST /confirm 并展示结果', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200,
      json: async () => ({ ok: true, result: { status: 'registered', course: '高等数学（下）', kind: '补考' } }) })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(ConfirmCard, { props: { card: {
      action_id: 'abc', action: 'makeup_register', title: '确认报名',
      summary: '为「高等数学（下）」提交补考/重修报名' } } })
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(fetchMock).toHaveBeenCalledWith('/confirm', expect.objectContaining({ method: 'POST' }))
    expect(wrapper.text()).toContain('报名成功')
    expect(wrapper.get('button').attributes('disabled')).toBeDefined()  // 一次性：确认后禁点
  })

  it('失败时展示错误文案', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 404,
      json: async () => ({ detail: '确认请求不存在或已过期' }) })
    vi.stubGlobal('fetch', fetchMock)
    const wrapper = mount(ConfirmCard, { props: { card: {
      action_id: 'gone', action: 'makeup_register', title: '确认报名', summary: 'x' } } })
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('确认请求不存在或已过期')  // 注 3：不断言计划注释的多余后缀
    expect(wrapper.get('button').attributes('disabled')).toBeDefined()  // 失败也不给二次点击（一次性语义）
  })
})
