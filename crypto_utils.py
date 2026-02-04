import os
from cryptography.fernet import Fernet


def _get_fernet() -> Fernet:
    key = (os.getenv("MEROSS_TOKEN_ENC_KEY") or "").strip()
    if not key:
        raise RuntimeError("Server misconfigured: MEROSS_TOKEN_ENC_KEY not set.")
    return Fernet(key.encode("utf-8"))


def encrypt_str(plain: str) -> str:
    f = _get_fernet()
    token = f.encrypt((plain or "").encode("utf-8"))
    return token.decode("utf-8")


def decrypt_str(cipher: str) -> str:
    f = _get_fernet()
    plain = f.decrypt((cipher or "").encode("utf-8"))
    return plain.decode("utf-8")