from functools import lru_cache
from urllib.parse import urlsplit

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


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def public_base_url(request=None) -> str:
    """URL publique du Hub, sans « / » final (adresses de retour OAuth, redirections).

    BASE_URL fait foi, sauf s'il est resté sur localhost alors que le Hub est ouvert depuis un vrai
    domaine : on prend alors l'adresse de la requête (le proxy transmet https et le domaine).
    """
    base = get_settings().base_url.rstrip("/")
    if request is not None and urlsplit(base).hostname in LOCAL_HOSTS:
        if request.url.hostname not in LOCAL_HOSTS:
            return str(request.base_url).rstrip("/")
    return base
