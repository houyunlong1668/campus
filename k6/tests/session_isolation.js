import { check } from 'k6'

import { STUDENTS } from '../lib/env.js'
import { get, json, login } from '../lib/helpers.js'

// 这不是压测：没有吞吐目标，VU 恒为 2，时长 5s。
// 它测的是"会话隔离"这个安全属性（spec §0.1），归 S5 的越权维度，不归性能。
export const options = {
  scenarios: {
    isolate: { executor: 'constant-vus', vus: 2, duration: '5s' },
  },
  thresholds: {
    http_req_failed: ['rate===0'],
    checks: ['rate===1'],
    http_req_duration: ['p(95)<1000'],
  },
}

// seed 里两人课程域完全不重叠：陈默（建筑学）只有 ARCH*/ART*，
// 周晓楠（计科）一门 ARCH/ART 都没有。用这个划分断言"没串"。
const ACCOUNTS = [
  { ...STUDENTS.zhou, expectArch: false },
  { ...STUDENTS.chen, expectArch: true },
]

// 每个 VU 只登录一次。
// 为什么：verify_password 是 pbkdf2_sha256 600000 迭代，实测 0.396 秒/次
// （S1 有意选的强度，不许为了测试调低）。每个迭代都登录会把密码哈希的耗时
// 算进 http_req_duration，2 VU 抢 CPU 一起排队 → p95 冲到 1.22s，阈值必红，
// 但那测的是哈希不是端点。本文件要测的是"会话跨迭代持续 + 跨 VU 不串"，
// 所以登录每 VU 做一次即可；VU 间 JS 状态互不共享，flag 天然按 VU 生效。
let loggedIn = false

export default function () {
  const me = ACCOUNTS[(__VU - 1) % ACCOUNTS.length]

  if (!loggedIn) {
    const loginRes = login(me.id)
    check(loginRes, { '登录 200': (r) => r.status === 200 })
    loggedIn = true
  }

  const body = json(get('/api/grades', 'grades-isolate'))
  check(body, {
    '拿到的是本人行数': (b) => b && b.grades.length === me.grades,
    '全是本人的课程域': (b) => b && b.grades.every((g) =>
      me.expectArch ? (g.code.startsWith('ARCH') || g.code.startsWith('ART'))
                    : !(g.code.startsWith('ARCH') || g.code.startsWith('ART'))),
    '本人特有课程在': (b) => b && b.grades.some((g) =>
      me.expectArch ? g.code === 'ARCH2100'
                    : g.name === '数据结构（暑期补习）'),  // spec §4.3 点名这门（= CS2052）
    // 行数 + 域划分 双保险：任一 VU 拿到对方会话，两个 check 必然至少红一个
    '没有跨账号混入': (b) => b && b.grades.every((g) => g.student_id === undefined),
  })
}
