import { check } from 'k6'

import { STUDENTS, THROWAWAY_ID } from '../lib/env.js'
import { get, json, login, post } from '../lib/helpers.js'

// 关键：这里故意打 401/422/429。k6 把 4xx 计入 http_req_failed，
// 设 `http_req_failed: rate===0` 会必红且红得莫名其妙（spec §4.0 第 1 条）。
// 所以只看 checks 的通过率。
export const options = {
  scenarios: {
    authz: { executor: 'shared-iterations', vus: 1, iterations: 1, maxDuration: '60s' },
  },
  thresholds: {
    checks: ['rate===1'],
    http_req_duration: ['p(95)<1000'],
  },
}

export default function () {
  // 1) 未登录 → 401
  const noCookie = get('/api/grades', 'grades-no-cookie')
  check(noCookie, {
    '未登录打 /api/grades 是 401': (r) => r.status === 401,
    '401 body 是 unauthenticated': (r) => r.body.includes('unauthenticated'),
  })

  const noCookieChat = post('/chat', { message: '这学期上什么课' }, { timeout: '30s' })
  check(noCookieChat, {
    '未登录打 /chat 是 401': (r) => r.status === 401,
    'chat 的 401 不是 422': (r) => r.status !== 422,
  })

  // S4 新端点：无 Cookie 同样 401（会话是身份唯一来源）。
  // 必须排在首次 login 之前——jar 惰性创建，login 后 jar 持有 sid Cookie，
  // 之后再打就不是"无 Cookie"了。
  const noCookieConfirm = post('/confirm', { action_id: 'x'.repeat(32) })
  check(noCookieConfirm, {
    '未登录打 /confirm 是 401': (r) => r.status === 401,
  })

  const noCookieReplay = post('/replay', null)
  check(noCookieReplay, {
    '未登录打 /replay 是 401': (r) => r.status === 401,
  })

  // 2) 登录后在请求体塞身份/会话标识 → 422（extra="forbid"）
  const ok = login(STUDENTS.zhou.id)
  check(ok, { '登录 200': (r) => r.status === 200 })

  // 登录后打不存在的动作：404（不区分不存在/过期/别人——k6 只验状态码）
  const confirmMissing = post('/confirm', { action_id: '0'.repeat(32) })
  check(confirmMissing, {
    'confirm 不存在动作是 404': (r) => r.status === 404,
  })

  const withStudent = post('/chat',
    { message: '查成绩', student_id: '20230007' }, { timeout: '30s' })
  check(withStudent, {
    '请求体塞 student_id 是 422': (r) => r.status === 422,
  })

  const withSession = post('/chat',
    { message: '查成绩', session_id: 's-forged' }, { timeout: '30s' })
  check(withSession, {
    '请求体塞 session_id 是 422': (r) => r.status === 422,
  })

  // 3) 同一学号错 5 次 → 第 6 次 429。
  //    用炮灰号：它不在 seed 里 → 前 5 次是 401 且同样计数；锁它不影响真账号。
  let last
  for (let i = 0; i < 6; i++) {
    last = post('/auth/login', { student_id: THROWAWAY_ID, password: 'definitely-wrong' })
  }
  check(last, {
    '第 6 次错密码是 429': (r) => r.status === 429,
    '429 body 是 too_many_attempts': (r) => r.body.includes('too_many_attempts'),
  })

  // 4) 锁了炮灰号之后，真账号必须仍能登录——否则"限速"就是误伤
  const stillOk = login(STUDENTS.zhou.id)
  check(stillOk, {
    '锁完炮灰号后真账号仍能登录': (r) => r.status === 200,
  })
}
