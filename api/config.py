"""
FastAPI app configuration — loaded from environment variables.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    max_file_size_mb: int = 50
    rate_limit_per_hour: int = 10
    cors_origins: str = "http://localhost:3000,http://localhost:3001"
    app_version: str = "1.0.0"

    # Optional — enables AI-polished executive summaries and the AI Q&A
    # assistant. The platform is fully functional without any of this set.
    # "groq" is the recommended default: a free tier with no cost to whoever
    # runs this instance. "anthropic" is available for those who want Claude
    # and have a key.
    ai_provider: str = "groq"
    groq_api_key: str = ""
    anthropic_api_key: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = False

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache()
def get_settings() -> Settings:
    return Settings()
