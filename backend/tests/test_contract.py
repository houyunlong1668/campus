import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_routes_contract.py"


def test_PAGE_REGISTRY_与前端_router_一一对应():
    """脚本此前只能靠人记得去跑；挂进 pytest 才有失败即红的效力。"""
    result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    # 三条 OK = 页面↔router、页面↔/api/*、迁移文件双方言同集；少一条说明某项检查被悄悄删掉
    ok_lines = [line for line in result.stdout.splitlines() if line.startswith("OK: ")]
    assert len(ok_lines) == 3, result.stdout


def test_四个教务端点确实挂在_app_上():
    """删掉 main.py 里那行 include_router(academic_router) 时，其余后端测试照样绿——这条补住。

    只构造 app、不进 TestClient 上下文，因此 lifespan 不跑：不需要 Docker，也不拉 MCP 子进程。
    """
    from app.main import create_app

    paths = _route_paths(create_app().routes)
    assert {"/api/grades", "/api/schedule", "/api/makeup", "/api/loans"} <= paths


def _route_paths(routes: list) -> set[str]:
    """这版 FastAPI 把 include_router 存成惰性 _IncludedRouter，app.routes 不再摊平，
    所以要顺着 original_router 往下走才能看到 /api/* 的真路径。"""
    out: set[str] = set()
    for route in routes:
        nested = getattr(route, "routes", None)
        if nested is None:
            nested = getattr(getattr(route, "original_router", None), "routes", None)
        if nested is not None:
            out |= _route_paths(list(nested))
        path = getattr(route, "path", None)
        if path:
            out.add(path)
    return out
