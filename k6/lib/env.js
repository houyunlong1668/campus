// k6 跑在自带的 Go+JS 运行时（goja），不是 Node——没有 require/fs/process，
// 也没有 npm 解析。这里只能用 ES module 的 import/export。
export const BASE_URL = __ENV.K6_BASE_URL || 'http://127.0.0.1:8300'

// 与 scripts/seed_academic.py 的账号一致。本套件唯一一处写密码
// （spec2 §11 认可的本地例外：demo1234 只因本地仿真成立）。
export const PASSWORD = 'demo1234'

// 计数来自 seed 的实际数据（backend/tests/test_academic_api.py 同源断言）
export const STUDENTS = {
  // S4 86dfe29 给周晓楠补旗舰演示数据（高数（下）56 分 + 补考）后为 15/4，
  // 与 test_academic_api 的同源断言一致（裁决 R7 豁免本次修改）。
  zhou: { id: '20230001', grades: 15, schedule: 12, makeups: 4, loans: 4 },
  chen: { id: '20230002', grades: 6, schedule: 6, makeups: 0, loans: 2 },
}

// 不在 seed 里：登录必 401、同样计入失败计数，专供 429 测试。
// 用真账号会把 20230001 锁 60 秒，后面所有文件全 429（spec §4.0 第 2 条）。
export const THROWAWAY_ID = '20239999'
