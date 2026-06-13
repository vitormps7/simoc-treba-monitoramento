from __future__ import annotations

from datetime import datetime, timedelta
import os
import streamlit as st
from jose import jwt
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
ALGORITHM = "HS256"
BCRYPT_MAX_BYTES = 72


def secret_key() -> str:
    try:
        return st.secrets.get("SECRET_KEY") or os.getenv("SECRET_KEY", "dev-secret-change-me")
    except Exception:
        return os.getenv("SECRET_KEY", "dev-secret-change-me")


def _bcrypt_safe_password(password: object) -> str:
    """Normaliza senha para o limite aceito pelo bcrypt.

    O bcrypt aceita no maximo 72 bytes. Em ambientes Streamlit/Supabase,
    erros de colagem em Secrets podem inserir strings longas; esta funcao
    evita que o app caia e limita de forma deterministica antes do hash.
    """
    value = "" if password is None else str(password)
    encoded = value.encode("utf-8")[:BCRYPT_MAX_BYTES]
    return encoded.decode("utf-8", errors="ignore")


def hash_password(password: object) -> str:
    return pwd_context.hash(_bcrypt_safe_password(password))


def verify_password(password: object, hashed: str) -> bool:
    return pwd_context.verify(_bcrypt_safe_password(password), hashed)


def create_token(subject: str, minutes: int = 480) -> str:
    payload = {"sub": subject, "exp": datetime.utcnow() + timedelta(minutes=minutes)}
    return jwt.encode(payload, secret_key(), algorithm=ALGORITHM)


def decode_token(token: str) -> str | None:
    try:
        return jwt.decode(token, secret_key(), algorithms=[ALGORITHM]).get("sub")
    except Exception:
        return None
