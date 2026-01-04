from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://uw_app:uw_password@127.0.0.1:5433/uw_eod"
    app_name: str = "UWD Regime EOD"
    log_level: str = "INFO"
    anomaly_ml_enabled: bool = False

    class Config:
        env_file = ".env"
        env_prefix = "UW_"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
