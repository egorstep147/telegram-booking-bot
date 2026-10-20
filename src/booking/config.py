from pathlib import Path
from typing import Annotated

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Настройки из переменных окружения и .env. Имена без учёта регистра: BOT_TOKEN → bot_token."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: SecretStr
    database_url: str
    redis_url: str = ""
    niche: str = "barbershop"  # папка в niches/: бизнес, услуги, мастера, правила
    niches_dir: Path = ROOT / "niches"
    webapp_dist: Path = ROOT / "webapp" / "dist"
    admin_ids: Annotated[set[int], NoDecode] = set()
    webapp_url: str = ""
    webhook_url: str = ""
    webhook_secret: SecretStr = SecretStr("")
    polling: bool = True
    payment_token: SecretStr = SecretStr("")  # провайдер карт из @BotFather (ЮKassa) — для предоплаты
    google_credentials_file: str = ""  # JSON сервисного аккаунта Google; пусто — без синхронизации календарей
    host: str = "127.0.0.1"
    port: int = 8085

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _split_ids(cls, v):
        return {int(x) for x in v.split(",") if x.strip()} if isinstance(v, str) else v

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, v: str) -> str:
        return v.replace("postgresql://", "postgresql+asyncpg://", 1) if v.startswith("postgresql://") else v


settings = Settings()
