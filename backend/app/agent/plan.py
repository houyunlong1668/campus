from typing import Literal

from pydantic import BaseModel, Field


class ThresholdCondition(BaseModel):
    mode: Literal["threshold"] = "threshold"
    column: str
    op: Literal["lt", "le", "gt", "ge", "eq", "ne"] = "lt"
    value: float


class LlmCondition(BaseModel):
    mode: Literal["llm"] = "llm"
    condition_text: str


class OrchestrationPlan(BaseModel):
    """grader 的输入：怎么判、判中了再干什么。followup 为空 = 纯分支无后续。"""

    condition: ThresholdCondition | LlmCondition = Field(discriminator="mode")
    followup_user_input: str | None = None


class WriteIntent(BaseModel):
    action: Literal["makeup_register"] = "makeup_register"
    course_code: str
    course_name: str = ""
    summary: str = ""


class PlanBundle(BaseModel):
    orchestration: OrchestrationPlan | None = None
    write: WriteIntent | None = None
