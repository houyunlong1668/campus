// frontend/tests/useResource.test.ts
import { beforeEach, describe, expect, it, vi } from 'vitest'

const signOut = vi.fn()
const push = vi.fn()

beforeEach(() => {
  vi.unstubAllGlobals()
  vi.resetModules()
  signOut.mockClear()
  push.mockClear()
  vi.doMock('../src/composables/useAuth', () => ({ useAuth: () => ({ signOut }) }))
  vi.doMock('../src/router', () => ({
    default: { push, currentRoute: { value: { fullPath: '/academic/grades' } } },
  }))
})

async function use() {
  const { useResource } = await import('../src/composables/useResource')
  return useResource<{ grades: { name: string }[] }>('/api/grades')
}

describe('useResource', () => {
  it('成功时填充 data、清空 error、结束 loading', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      status: 200, ok: true, json: async () => ({ grades: [{ name: '高等数学' }] }),
    })))
    const r = await use()
    await r.reload()
    expect(r.data.value?.grades[0].name).toBe('高等数学')
    expect(r.error.value).toBe('')
    expect(r.loading.value).toBe(false)
  })

  it('非 2xx 时置错误文案且 data 保持空', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ status: 500, ok: false })))
    const r = await use()
    await r.reload()
    expect(r.data.value).toBeNull()
    expect(r.error.value).toContain('加载失败')
    expect(r.loading.value).toBe(false)
  })

  it('网络异常同样进错误态不抛出', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('boom') }))
    const r = await use()
    await expect(r.reload()).resolves.toBeUndefined()
    expect(r.error.value).toContain('加载失败')
  })

  it('401 清登录态并跳登录页，带上 next', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ status: 401, ok: false })))
    const r = await use()
    await r.reload()
    expect(signOut).toHaveBeenCalledTimes(1)
    expect(push).toHaveBeenCalledWith({ path: '/login', query: { next: '/academic/grades' } })
    expect(r.error.value).toBe('')
    expect(r.loading.value).toBe(false)
  })

  it('请求带 credentials: include', async () => {
    const fetchMock = vi.fn(async () => ({ status: 200, ok: true, json: async () => ({ grades: [] }) }))
    vi.stubGlobal('fetch', fetchMock)
    const r = await use()
    await r.reload()
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ credentials: 'include' })
  })
})
