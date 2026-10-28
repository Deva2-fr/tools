from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: str = "sqlite:///./dev.db"
    secret_key: str  # signe les sessions (JWT)
    encryption_key: str  # chiffre les secrets stockés en base
    base_url: str = "http://localhost:8080"  # URL publique du Hub (sert aux redirections OAuth)
    admin_email: str = ""
    admin_password: str = ""
    webhook_token: str = ""  # jeton pour les alertes envoyées par des outils externes
    cookie_secure: bool = True
    data_dir: str = "./data"
    timezone: str = "Europe/Paris"
    session_minutes: int = 8 * 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
