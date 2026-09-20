import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "mcp_servers" / "navigation"))

from server import PAGE_REGISTRY  # noqa: E402

router_src = (ROOT / "frontend" / "src" / "router" / "index.ts").read_text(encoding="utf-8")

missing = [
    entry.path for entry in PAGE_REGISTRY
    if f'"{entry.path}"' not in router_src
]
if missing:
    print("FAIL: 以下 PAGE_REGISTRY 路径未在前端 router 注册:", missing)
    sys.exit(1)
print(f"OK: {len(PAGE_REGISTRY)} 条页面路径全部已注册")
