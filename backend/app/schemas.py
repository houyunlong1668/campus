from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)
    # 身份与会话标识一律不从请求体来：只认 Cookie 里的会话（spec 6.1）。
    # extra="forbid" 让客户端塞 session_id / student_id 直接 422，而不是被静默忽略。
