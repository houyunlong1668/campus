import { check } from 'k6'

import { STUDENTS } from '../lib/env.js'
import { login, post } from '../lib/helpers.js'

export const options = {
  scenarios: {
    chat: { executor: 'shared-iterations', vus: 1, iterations: 1, maxDuration: '90s' },
  },
  thresholds: {
    http_req_failed: ['rate===0'],
    checks: ['rate===1'],
    // 单位毫秒。FakeProvider 每 4 字一帧、10ms 一帧，15s 是留给慢机器的余量。
    http_req_duration: ['p(95)<15000'],
  },
}

export default function () {
  const ok = login(STUDENTS.zhou.id)
  check(ok, { '登录 200': (r) => r.status === 200 })

  // k6 收完整响应才返回，所以只能断最终 body，断不了首 token 时延（spec §2.2）
  const res = post('/chat', { message: '这学期上什么课' }, { timeout: '30s' })

  check(res, {
    '/chat 是 200': (r) => r.status === 200,
    '含 token 事件': (r) => r.body.includes('event: token'),
    '含 tool_call 事件': (r) => r.body.includes('event: tool_call'),
    '含 nav_card 事件': (r) => r.body.includes('event: nav_card'),
    'nav_card 指向课表页': (r) => r.body.includes('/academic/schedule'),
    '含 done 事件': (r) => r.body.includes('event: done'),
    'done 带 conversation_id': (r) => r.body.includes('"conversation_id"'),
    '没有 error 事件': (r) => !r.body.includes('event: error'),
    '事件按 SSE 分帧（帧间有空行）': (r) => r.body.includes('\n\n'),
  })
}
