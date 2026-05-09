"""Security utilities: token encryption, JWT, prompt-injection sanitisation."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import get_settings


# ---------- Symmetric token encryption (Fernet-style, stdlib only) ----------
# We avoid an extra dep by using HMAC-SHA256 + AES-GCM via cryptography lib if
# available. To keep zero extra deps in this file we use an HMAC-authenticated
# XOR stream — sufficient for opaque token blobs at rest in the demo. In
# production swap for cryptography.fernet.Fernet.

def _key_bytes() -> bytes:
    s = get_settings().secret_key.encode("utf-8")
    return hashlib.sha256(s).digest()


def encrypt_token(plaintext: str) -> str:
    key = _key_bytes()
    nonce = secrets.token_bytes(16)
    stream = b""
    counter = 0
    while len(stream) < len(plaintext):
        stream += hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()
        counter += 1
    ct = bytes(p ^ s for p, s in zip(plaintext.encode("utf-8"), stream))
    mac = hmac.new(key, nonce + ct, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(nonce + mac + ct).decode("ascii")


def decrypt_token(ciphertext: str) -> str:
    key = _key_bytes()
    raw = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
    nonce, mac, ct = raw[:16], raw[16:48], raw[48:]
    expected = hmac.new(key, nonce + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, mac):
        raise ValueError("token integrity check failed")
    stream = b""
    counter = 0
    while len(stream) < len(ct):
        stream += hashlib.sha256(key + nonce + counter.to_bytes(8, "big")).digest()
        counter += 1
    return bytes(p ^ s for p, s in zip(ct, stream)).decode("utf-8")


# ---------- JWT ----------
# python-jose is imported lazily so that callers who never touch JWT (most of
# the platform, including tests) don't depend on a working `cryptography`
# install.
def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> str:
    from jose import jwt  # local import

    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_ttl_min)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    from jose import jwt  # local import

    settings = get_settings()
    return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])


# ---------- Prompt-injection sanitisation ----------
# These are belt-and-braces. The real defence is structured JSON outputs and
# never giving agents tools that mutate state without going through the
# approval gate. But we still strip obvious injection markers from external
# text before it enters a Claude prompt.
_INJECTION_PATTERNS = [
    re.compile(r"(?i)ignore\s+(?:all\s+|previous\s+|above\s+)+instructions?"),
    re.compile(r"(?i)disregard\s+(?:the\s+)?system\s+prompt"),
    re.compile(r"(?i)you\s+are\s+now\b"),
    re.compile(r"(?i)\bact\s+as\b"),
    re.compile(r"<\s*/?\s*(system|assistant|user)\s*>"),
]


def sanitize_external_text(text: str | None, max_len: int = 4000) -> str:
    if not text:
        return ""
    cleaned = text[:max_len]
    for pat in _INJECTION_PATTERNS:
        cleaned = pat.sub("[redacted]", cleaned)
    return cleaned
