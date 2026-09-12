"""At-rest encryption for third-party OAuth tokens (Fernet/AES-128-CBC+HMAC).

Never store an OAuth access/refresh token in plaintext. This wraps
cryptography.Fernet so the rest of the app just calls encrypt()/decrypt().
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


def _fernet() -> Fernet:
    settings = get_settings()
    # Accept either a real Fernet key or an arbitrary secret string (derived
    # into a valid 32-byte urlsafe-base64 key) so local dev doesn't require
    # generating a key before the app will boot.
    raw = settings.encryption_key.encode("utf-8")
    try:
        return Fernet(raw)
    except (ValueError, InvalidToken, Exception):  # noqa: BLE001
        derived = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
        return Fernet(derived)


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
