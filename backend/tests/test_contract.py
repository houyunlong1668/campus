import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_routes_contract.py"


def test_PAGE_REGISTRY_与前端_router_一一对应():
    """脚本此前只能靠人记得去跑；挂进 pytest 才有失败即红的效力。"""
    result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
