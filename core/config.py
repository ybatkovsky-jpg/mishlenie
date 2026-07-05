"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the Mishlenie bot."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # DeepSeek API
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"

    # Telegram
    telegram_bot_token: str = ""

    # Database
    database_url: str = "sqlite+aiosqlite:///mishlenie.db"

    # App
    log_level: str = "INFO"

    @property
    def deepseek_chat_model(self) -> str:
        return "deepseek-chat"

    @property
    def deepseek_reasoner_model(self) -> str:
        return "deepseek-reasoner"


settings = Settings()
