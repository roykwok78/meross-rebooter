import os
from cryptography.fernet import Fernet

def get_fernet() -> Fernet:
    key = os.getenv("MEROSS_TOKEN_ENC_KEY", "").strip()
    if not key:
        raise RuntimeError("MEROSS_TOKEN_ENC_KEY not set. Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")
    return Fernet(key.encode("utf-8") if isinstance(key, str) else key)

def encrypt_str(value: str) -> str:
    f = get_fernet()
    token = f.encrypt(value.encode("utf-8"))
    return token.decode("utf-8")

def decrypt_str(value_enc: str) -> str:
    f = get_fernet()
    raw = f.decrypt(value_enc.encode("utf-8"))
    return raw.decode("utf-8")