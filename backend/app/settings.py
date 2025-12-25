from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://uw_app:uw_password@localhost:5432/uw_eod"
    app_name: str = "UWD Regime EOD"
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        env_prefix = "UW_"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
