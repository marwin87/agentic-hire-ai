from pydantic import BaseModel, Field, SecretStr
from typing import Optional


class LLMMixin(BaseModel):
    """LLM provider URLs, API keys, and per-agent model selections."""

    openrouter_base_url: str = Field("https://openrouter.ai/api/v1")
    openrouter_api_key: Optional[SecretStr] = None
    orchestrator_model_name: str = Field("openai/gpt-4o-mini")
    scout_model_name: str = Field("google/gemini-3-flash-preview")
    tailor_model_name: str = Field("openai/gpt-4o-mini")
    vision_model_name: str = Field("openai/gpt-4o")
    validator_model_name: str = Field("openai/gpt-4o")
    embedded_model_name: str = Field("text-embedding-3-small")
    parser_model_name: str = Field(
        "openai/gpt-4o-mini", description="LLM model used by JobParser."
    )
