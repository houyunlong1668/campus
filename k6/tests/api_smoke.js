import http from 'k6/http'
import { check } from 'k6'

import { BASE_URL, STUDENTS } from '../lib/env.js'
import { get, json, login } from '../lib/helpers.js'

// 阈值单位是毫秒。三个成功路径文件都要这三条（spec §4.1）。
export const options = {
  scenarios: {
    smoke: { executor: 'shared-iterations', vus: 1, iterations: 1, maxDuration: '60s' },
  },
  thresholds: {
    http_req_failed: ['rate===0'],
    checks: ['rate===1'],
    http_req_duration: ['p(95)<1000'],
  },
}

function keysOf(body) {
  return body ? JSON.stringify(Object.keys(body).sort()) : 'null'
}

export default function () {
  const health = http.get(`${BASE_URL}/health`)
  check(health, { '/health 是 200': (r) => r.status === 200 })

  const me = login(STUDENTS.zhou.id)
  check(me, { '登录 200': (r) => r.status === 200 })

  const grades = json(get('/api/grades', 'grades'))
  check(grades, {
    'grades 顶层键只有 grades': (b) => keysOf(b) === '["grades"]',
    // 标签走模板字符串自同步（裁决 R7）：曾因写死数字与 env.js 失联成 13/14/15 三个值
    [`grades ${STUDENTS.zhou.grades} 行`]: (b) => b && b.grades.length === STUDENTS.zhou.grades,
    '成绩行键集合同': (b) => b && b.grades.length > 0 &&
      JSON.stringify(Object.keys(b.grades[0]).sort()) ===
        '["code","credits","name","score","term"]',
  })

  const schedule = json(get('/api/schedule', 'schedule'))
  check(schedule, {
    'schedule 顶层键只有 courses': (b) => keysOf(b) === '["courses"]',
    'schedule 12 门': (b) => b && b.courses.length === STUDENTS.zhou.schedule,
    '课表行键集合同': (b) => b && b.courses.length > 0 &&
      JSON.stringify(Object.keys(b.courses[0]).sort()) ===
        '["code","credits","day","domain","kind","name","periods","room","teacher","weeks"]',
  })

  const makeup = json(get('/api/makeup', 'makeup'))
  check(makeup, {
    'makeup 顶层键只有 items': (b) => keysOf(b) === '["items"]',
    [`makeup ${STUDENTS.zhou.makeups} 条`]: (b) => b && b.items.length === STUDENTS.zhou.makeups,
    '补考行键集合同': (b) => b && b.items.length > 0 &&
      JSON.stringify(Object.keys(b.items[0]).sort()) ===
        '["code","course","place","reason","seats","status","type","when"]',
  })

  const loans = json(get('/api/loans', 'loans'))
  check(loans, {
    'loans 顶层键只有 items': (b) => keysOf(b) === '["items"]',
    'loans 4 本': (b) => b && b.items.length === STUDENTS.zhou.loans,
    '借阅行键集合同': (b) => b && b.items.length > 0 &&
      JSON.stringify(Object.keys(b.items[0]).sort()) ===
        '["callNo","daysLeft","due","place","title"]',
  })
}
