import os
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# repo root, so the .env is found no matter where uvicorn/pytest was started from
ROOT = Path(__file__).resolve().parent.parent


def _package_version() -> str:
    try:
        return version("flightmd-core")
    except PackageNotFoundError:
        return "0.0.0+local"


class Settings(BaseSettings):
    # extra="ignore": the shared .env also carries the frontend's NEXT_PUBLIC_* keys
    model_config = SettingsConfigDict(env_file=ROOT / ".env", case_sensitive=False, extra="ignore")

    max_file_size_mb: int = 50
    rate_limit_per_hour: int = 10
    ask_rate_limit_per_hour: int = 30
    pdf_rate_limit_per_hour: int = 30
    max_concurrent_analyses: int = 2
    cors_origins: str = "http://localhost:3000,http://localhost:3001,http://localhost:3100,http://127.0.0.1:3000,http://127.0.0.1:3001,http://127.0.0.1:3100"
    app_version: str = _package_version()

    # Comma-separated IPs/CIDRs of reverse proxies whose X-Forwarded-For we believe.
    # Empty = use the socket peer address, which is right when nothing sits in front.
    trusted_proxies: str = ""

    # https only unless a self-hoster really wants plain http webhooks
    allow_http_webhooks: bool = False

    # SQLite db, upload spool, export cache and (unless S3 is set) contributed logs.
    # Relative paths are taken from the working dir, same as the engine's topic cache.
    flightmd_data_dir: str = "data"

    # Contributed raw logs go to S3 (or anything S3-compatible) when a bucket is set.
    # Credentials come from the usual AWS_* variables.
    flightmd_s3_bucket: str = ""
    flightmd_s3_prefix: str = "contributions/"
    flightmd_s3_endpoint_url: str = ""
    flightmd_s3_region: str = ""

    # Set to hand analyses to arq workers through Redis instead of the in-process queue
    flightmd_redis_url: str = ""

    # When set, GET /metrics needs "Authorization: Bearer <token>"
    metrics_token: str = ""

    # AI is optional. groq is the default because its free tier costs the
    # operator nothing; anthropic is there for anyone with a key.
    ai_provider: str = "groq"
    groq_api_key: str = ""
    anthropic_api_key: str = ""

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def data_dir(self) -> str:
        return os.path.abspath(self.flightmd_data_dir)

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def trusted_proxies_list(self) -> list[str]:
        return [p.strip() for p in self.trusted_proxies.split(",") if p.strip()]

    @property
    def ai_configured(self) -> bool:
        provider = self.ai_provider.lower().strip()
        if provider == "groq":
            return bool(self.groq_api_key)
        if provider == "anthropic":
            return bool(self.anthropic_api_key)
        return False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
