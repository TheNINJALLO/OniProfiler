"""Validated deployment settings. Secrets are never given hard-coded defaults."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import os
from urllib.parse import urlsplit

@dataclass(frozen=True)
class Settings:
    data_dir: Path
    public_origin: str = "http://127.0.0.1:8080"
    allow_http_loopback: bool = False
    session_hours: int = 12
    report_limit: int = 500
    history_hours: int = 24
    max_json_bytes: int = 2 * 1024 * 1024
    max_profile_bytes: int = 64 * 1024 * 1024
    discord_webhook: str = ""

    def __post_init__(self) -> None:
        parsed = urlsplit(self.public_origin)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
            raise ValueError("ONI_PUBLIC_ORIGIN must be a plain origin without credentials, path, query or fragment")
        if not parsed.hostname:
            raise ValueError("ONI_PUBLIC_ORIGIN needs a hostname")
        if parsed.scheme != "https":
            if not (self.allow_http_loopback and parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")):
                raise ValueError("HTTPS is required. Local development alone may use --allow-http-loopback")
        if not 1 <= self.session_hours <= 72 or not 10 <= self.report_limit <= 2000 or not 1 <= self.history_hours <= 168:
            raise ValueError("Session, report, or history retention is outside the supported range")
        if self.discord_webhook:
            hook = urlsplit(self.discord_webhook)
            if hook.scheme != "https" or hook.hostname != "discord.com" or not hook.path.startswith("/api/webhooks/") or hook.query or hook.fragment:
                raise ValueError("Discord webhook must be an https://discord.com/api/webhooks/... endpoint")

    @property
    def origin(self) -> str:
        return self.public_origin.rstrip("/")

    @property
    def secure_cookie(self) -> bool:
        return urlsplit(self.origin).scheme == "https"

    @classmethod
    def environment(cls) -> "Settings":
        return cls(Path(os.getenv("ONI_DATA_DIR", "./oni-data")).resolve(),
                   os.getenv("ONI_PUBLIC_ORIGIN", "https://profiler.example.invalid"),
                   os.getenv("ONI_ALLOW_HTTP_LOOPBACK") == "1",
                   discord_webhook=os.getenv("ONI_DISCORD_WEBHOOK", ""))
