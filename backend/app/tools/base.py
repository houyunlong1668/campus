import time
from typing import Any, Awaitable, Callable, Protocol

from pydantic import BaseModel, create_model


class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]


class ToolResult(BaseModel):
    ok: bool
    data: Any | None = None
    error: str | None = None
    latency_ms: int


class ToolRegistry(Protocol):
    async def list_tools(self) -> list[ToolSpec]: ...
    async def call_tool(self, name: str, args: dict[str, Any]) -> ToolResult: ...


async def timed_call(fn: Callable[[], Awaitable[Any]]) -> ToolResult:
    start = time.perf_counter()
    try:
        data = await fn()
        return ToolResult(ok=True, data=data, latency_ms=int((time.perf_counter() - start) * 1000))
    except Exception as exc:  # 统一降级点：任何工具异常不向上抛
        return ToolResult(
            ok=False, error=f"{type(exc).__name__}: {exc}",
            latency_ms=int((time.perf_counter() - start) * 1000),
        )


_TYPE_MAP = {
    "string": str, "integer": int, "number": float,
    "boolean": bool, "object": dict, "array": list,
}


def _args_model(schema: dict[str, Any]):
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    fields = {}
    for name, spec in props.items():
        json_type = spec.get("type")
        # 复合 schema（anyOf/oneOf/$ref）与未知类型一律放行：
        # 早先默认落成 str，真实模型传 {semester: "current"} 会被判成参数非法
        py_type = _TYPE_MAP.get(json_type, Any) if isinstance(json_type, str) else Any
        if name not in required:
            py_type = py_type | None
        default = ... if name in required else None
        fields[name] = (py_type, default)
    return create_model("ToolArgs", **fields)


def validate_args(schema: dict[str, Any], args: dict[str, Any]) -> tuple[bool, str | None]:
    try:
        _args_model(schema)(**args)
        return True, None
    except Exception as exc:
        return False, f"参数校验失败: {exc}"
