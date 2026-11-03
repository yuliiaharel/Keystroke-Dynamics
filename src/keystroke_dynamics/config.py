"""Application settings, loaded from the environment (and a .env file
in local development)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+psycopg://localhost/keystroke_dynamics"
    session_secret: str = "change-me"
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 8000


settings = Settings()
