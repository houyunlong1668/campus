import http from 'k6/http'

import { BASE_URL, PASSWORD } from './env.js'

// k6 禁止在 init 上下文造 cookie jar：
//   GoError: Making cookie jars in the init context is not supported
// 模块级代码跑在 init 上下文（每 VU 一次），所以 jar 必须延迟到第一次真正发
// 请求时（VU 上下文）再建。VU 之间 JS 状态互不共享，因此每 VU 各有一个 jar
// 这点仍然成立——只是创建时机从"模块加载"挪到"首次请求"。
let jar = null

function ensureJar() {
  if (jar === null) {
    jar = http.cookieJar()
  }
  return jar
}

export function login(studentId) {
  return http.post(`${BASE_URL}/auth/login`,
    JSON.stringify({ student_id: studentId, password: PASSWORD }),
    { headers: { 'Content-Type': 'application/json' }, jar: ensureJar(), tags: { name: 'login' } })
}

export function get(path, name) {
  return http.get(`${BASE_URL}${path}`, { jar: ensureJar(), tags: { name } })
}

export function post(path, body, opts = {}) {
  return http.post(`${BASE_URL}${path}`, JSON.stringify(body), {
    headers: { 'Content-Type': 'application/json' },
    jar: ensureJar(),
    ...opts,
  })
}

export function json(res) {
  try {
    return res.json()
  } catch (e) {
    return null
  }
}
