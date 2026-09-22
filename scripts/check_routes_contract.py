"""契约检查：PAGE_REGISTRY 与前端 router 路径双向对应、教务页与 /api/* 一一对应、
迁移文件名集合双方言相同。一条命令、任一断言失败即非零退出。"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "mcp_servers" / "navigation"))

from server import PAGE_REGISTRY  # noqa: E402

router_src = (ROOT / "frontend" / "src" / "router" / "index.ts").read_text(encoding="utf-8")
router_paths = set(re.findall(r"""path:\s*['"]([^'"]+)['"]""", router_src))
registry_paths = {entry.path for entry in PAGE_REGISTRY}

missing = sorted(registry_paths - router_paths)
# 非教务页面、因此不在 PAGE_REGISTRY 里的路由：首页与登录页
NON_PAGE_ROUTES = {"/", "/login"}
extra = sorted(router_paths - registry_paths - NON_PAGE_ROUTES)

if missing or extra:
    if missing:
        print("FAIL: PAGE_REGISTRY 路径未在前端 router 注册:", missing)
    if extra:
        print("FAIL: 前端 router 存在未注册页面（首页除外）:", extra)
    sys.exit(1)

# 页面与其数据源一一对应：教务页存在但没有 /api/* 端点、或端点挂了却没页面，都算错位
PAGE_TO_API = {
    "/academic/schedule": "/api/schedule",
    "/academic/grades": "/api/grades",
    "/academic/makeup": "/api/makeup",
    "/library": "/api/loans",
}
api_src = (ROOT / "backend" / "app" / "api" / "academic.py").read_text(encoding="utf-8")
# 端点的真实路径 = APIRouter(prefix=...) + 装饰器里的路径（Task 5 用前缀声明 /api）
prefix_m = re.search(r'APIRouter\(\s*prefix="([^"]*)"', api_src)
prefix = prefix_m.group(1) if prefix_m else ""
api_paths = {prefix + p for p in re.findall(r'@router\.get\("([^"]+)"\)', api_src)}
unmapped_pages = sorted(p for p in registry_paths if p not in PAGE_TO_API)
missing_apis = sorted({PAGE_TO_API[p] for p in registry_paths if p in PAGE_TO_API} - api_paths)
extra_apis = sorted(api_paths - set(PAGE_TO_API.values()))
if unmapped_pages or missing_apis or extra_apis:
    print("FAIL: 页面与 /api/* 端点错位:", unmapped_pages, missing_apis, extra_apis)
    sys.exit(1)
print(f"OK: {len(registry_paths)} 个教务页与 /api/* 一一对应")

# 迁移文件名集合双方言必须相同：只改一边立刻红（spec 6.3）
mig = ROOT / "backend" / "app" / "db" / "migrations"
mysql_files = {p.name for p in (mig / "mysql").glob("*.sql")}
sqlite_files = {p.name for p in (mig / "sqlite").glob("*.sql")}
if mysql_files != sqlite_files:
    print("FAIL: 迁移文件双方言不一致: 仅 mysql", sorted(mysql_files - sqlite_files),
          "仅 sqlite", sorted(sqlite_files - mysql_files))
    sys.exit(1)
print(f"OK: 迁移文件双方言同名 {len(mysql_files)} 个")

print(f"OK: PAGE_REGISTRY {len(registry_paths)} 条路径与 router 一一对应")
