import { describe, expect, it, vi } from 'vitest'
import { useAuth } from '../src/composables/useAuth'

function respond(body: unknown, status = 200) {
  return vi.fn(async () => ({ status, ok: status < 400, json: async () => body }))
}

const student = {
  student_id: '20230001', name: '周晓楠', major: '计算机科学与技术',
  class_name: '计科 2301', college: '信息科学与工程学院',
}

describe('useAuth', () => {
  it('bootstrap 成功则状态为 authed 并带出姓名', async () => {
    vi.stubGlobal('fetch', respond(student))
    const { bootstrap, status, user } = useAuth()
    await bootstrap()

    expect(status.value).toBe('authed')
    expect(user.value?.name).toBe('周晓楠')
  })

  it('bootstrap 拿到 401 则状态为 anonymous 且 user 清空', async () => {
    vi.stubGlobal('fetch', respond({ detail: { code: 'unauthenticated' } }, 401))
    const { bootstrap, status, user } = useAuth()
    await bootstrap()

    expect(status.value).toBe('anonymous')
    expect(user.value).toBeNull()
  })

  it('bootstrap 网络异常不抛出，按未登录处理', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('boom') }))
    const { bootstrap, status } = useAuth()
    await bootstrap()

    expect(status.value).toBe('anonymous')
  })

  it('登录成功置为 authed 并返回 ok', async () => {
    vi.stubGlobal('fetch', respond(student))
    const { login, status, user } = useAuth()
    const r = await login('20230001', 'demo1234')

    expect(r.ok).toBe(true)
    expect(status.value).toBe('authed')
    expect(user.value?.student_id).toBe('20230001')
  })

  it('登录失败返回后端文案且不置为 authed', async () => {
    vi.stubGlobal('fetch', respond(
      { detail: { code: 'bad_credentials', message: '学号或密码不正确' } }, 401))
    const { login, status } = useAuth()
    const r = await login('20230001', 'wrong')

    expect(r).toEqual({ ok: false, code: 'bad_credentials', message: '学号或密码不正确' })
    expect(status.value).toBe('anonymous')
  })

  it('429 透出 too_many_attempts', async () => {
    vi.stubGlobal('fetch', respond(
      { detail: { code: 'too_many_attempts', message: '尝试次数过多，请 60 秒后再试' } }, 429))
    const { login } = useAuth()
    const r = await login('20230001', 'demo1234')

    expect(r.ok).toBe(false)
    expect((r as { code: string }).code).toBe('too_many_attempts')
  })

  it('请求带 credentials，Cookie 才会被发送', async () => {
    const spy = respond(student)
    vi.stubGlobal('fetch', spy)
    const { login } = useAuth()
    await login('20230001', 'demo1234')

    expect(spy.mock.calls[0][1]).toMatchObject({ credentials: 'include' })
  })

  it('signOut 只清本地状态不发请求', async () => {
    const spy = respond(student)
    vi.stubGlobal('fetch', spy)
    const { signOut, status, user } = useAuth()
    signOut()

    expect(status.value).toBe('anonymous')
    expect(user.value).toBeNull()
    expect(spy).not.toHaveBeenCalled()
  })
})
