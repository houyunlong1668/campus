import logging

from .base import LLMProvider
from .fake import FakeProvider

logger = logging.getLogger("campus-agent.llm")


def build_provider(settings) -> LLMProvider:
    if settings.llm_provider == "fake":
        logger.info("使用 FakeProvider（规则式，无外部依赖）")
        return FakeProvider()
    if settings.llm_provider == "openai_compat":
        if not settings.openai_api_key:
            raise RuntimeError(
                "LLM_PROVIDER=openai_compat 需要 OPENAI_API_KEY；"
                "请在 backend/.env 配置，或改用 LLM_PROVIDER=fake"
            )
        from .openai_compat import OpenAICompatProvider

        logger.info("使用 OpenAICompatProvider model=%s", settings.openai_model)
        return OpenAICompatProvider(
            base_url=settings.openai_base_url,
            model=settings.openai_model,
            api_key=settings.openai_api_key,
        )
    raise RuntimeError(f"未知 LLM_PROVIDER: {settings.llm_provider}")
