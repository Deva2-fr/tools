import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet

from app.core.config import get_settings


def _fernet() -> Fernet:
    # Accepte n'importe quelle longue chaîne : on en dérive une clé Fernet valide.
    raw = hashlib.sha256(get_settings().encryption_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def encrypt_json(data: dict[str, Any]) -> str:
    return encrypt(json.dumps(data))


def decrypt_json(token: str) -> dict[str, Any]:
    return json.loads(decrypt(token))
