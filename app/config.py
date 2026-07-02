"""Konfigurasi aplikasi — dibaca dari environment (.env)."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Database
    database_url: str = "postgresql+asyncpg://milluser:millpass@localhost:5432/penggilingan"

    # Telegram
    bot_gudang1_token: str = ""
    bot_gudang2_token: str = ""
    bot_admin_token: str = ""

    # Claude
    anthropic_api_key: str = ""
    claude_model: str = "claude-haiku-4-5-20251001"

    # Aplikasi
    app_timezone: str = "Asia/Jakarta"
    undo_window_minutes: int = 15
    max_purchase_batch_per_day: int = 3

    # Pengeringan
    drying_late_hours: float = 5.0  # batas keterlambatan log kadar air
    drying_check_interval_seconds: int = 900  # frekuensi cek scheduler (15 mnt)

    @property
    def bot_tokens(self) -> dict[str, str]:
        """Peta nama bot -> token (hanya yang terisi)."""
        raw = {
            "gudang1": self.bot_gudang1_token,
            "gudang2": self.bot_gudang2_token,
            "admin": self.bot_admin_token,
        }
        return {name: token for name, token in raw.items() if token.strip()}


settings = Settings()
