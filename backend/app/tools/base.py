import time
from typing import Any, Awaitable, Callable, Protocol

from pydantic import BaseModel, ConfigDict, create_model


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
    # student_id：服务端注入位（裁决 A：丢弃→校验→注入三步，见各实现的
    # call_tool）。模型侧 schema 永远看不到这列；CompositeRegistry 分派时透传。
    async def call_tool(self, name: str, args: dict[str, Any],
                        student_id: str | None = None) -> ToolResult: ...


TRUSTED_ARGS: dict[str, set[str]] = {"run_sql": {"student_id"}}


def with_trusted_args(name: str, args: dict[str, Any],
                      student_id: str | None) -> dict[str, Any]:
    """一面丢弃、一面注入（spec 7.4）：模型塞的同名字段先被剔掉，
    再由服务端按会话写入。两面缺一个就有洞。"""
    trusted = TRUSTED_ARGS.get(name)
    if not trusted:
        return args
    out = {k: v for k, v in args.items() if k not in trusted}
    if student_id is not None:
        out["student_id"] = student_id
    return out


def strip_trusted(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    """给模型看的 schema 必须剔除受信列，否则等于教它"这里有身份列"。"""
    trusted = TRUSTED_ARGS.get(name)
    props = schema.get("properties")
    if not trusted or not props:
        return schema
    out = dict(schema)
    out["properties"] = {k: v for k, v in props.items() if k not in trusted}
    if "required" in out:
        out["required"] = [r for r in out["required"] if r not in trusted]
    return out


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
    # extra="forbid"：schema 未声明的键一律拒绝。S3 要把会话里的 student_id
    # 注入工具参数，靠的就是"模型自己塞的同名字段先被拒掉"这道底线。
    return create_model("ToolArgs", __config__=ConfigDict(extra="forbid"), **fields)


def validate_args(schema: dict[str, Any], args: dict[str, Any]) -> tuple[bool, str | None]:
    try:
        _args_model(schema)(**args)
        return True, None
    except Exception as exc:
        return False, f"参数校验失败: {exc}"
