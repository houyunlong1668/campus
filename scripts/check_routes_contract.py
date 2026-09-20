"""PAGE_REGISTRY 与前端 router 路径的双向契约检查。"""

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
extra = sorted(p for p in router_paths - registry_paths if p != "/")

if missing or extra:
    if missing:
        print("FAIL: PAGE_REGISTRY 路径未在前端 router 注册:", missing)
    if extra:
        print("FAIL: 前端 router 存在未注册页面（首页除外）:", extra)
    sys.exit(1)

print(f"OK: PAGE_REGISTRY {len(registry_paths)} 条路径与 router 一一对应")
