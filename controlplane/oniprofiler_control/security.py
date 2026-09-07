"""Password hashing, opaque revocable sessions, and strict input identities."""
from __future__ import annotations
import hashlib
import hmac
import re
import secrets
import time
import threading

_HASH_SLOTS = threading.BoundedSemaphore(4)

NAME = re.compile(r"^[A-Za-z0-9_.@-]{1,80}$")
IDENTITY = re.compile(r"^[a-f0-9]{32}$")
REPORT_KEY = re.compile(r"^report-[a-z0-9-]{1,100}\.json$")

def now_ms() -> int:
    return time.time_ns() // 1_000_000

def token() -> str:
    return secrets.token_urlsafe(32)

def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def password_hash(password: str, salt: str | None = None) -> tuple[str, str]:
    if not 14 <= len(password) <= 256:
        raise ValueError("Passwords must contain 14 to 256 characters")
    salt = salt or secrets.token_hex(16)
    with _HASH_SLOTS:
        raw = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=32768, r=8, p=1, maxmem=64*1024*1024)
    return salt, raw.hex()

def password_matches(password: str, salt: str, expected: str) -> bool:
    # Unknown accounts run the same work with a dummy salt; no plaintext passwords are stored.
    valid_length = 14 <= len(password) <= 256
    if not valid_length:
        password = "invalid-password-length"
    _, actual = password_hash(password, salt)
    return valid_length and hmac.compare_digest(actual, expected)

def valid_name(value: str) -> str:
    if not isinstance(value,str) or not NAME.fullmatch(value):
        raise ValueError("Names use 1-80 letters, digits, underscore, dot, @ or hyphen")
    return value

def valid_id(value: str) -> str:
    if not isinstance(value,str) or not IDENTITY.fullmatch(value):
        raise ValueError("Invalid identifier")
    return value
