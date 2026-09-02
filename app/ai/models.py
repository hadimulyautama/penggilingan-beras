"""Tabel fondasi lapisan AI: konfigurasi runtime & jejak pemakaian LLM.

Dipakai oleh `app.ai.guard` (kill-switch, spend-cap, pencatatan biaya) — bukan
milik domain mana pun. Ditaruh di `app.ai` supaya pengaman biaya bisa ikut ke
repo Kantor maupun Produksi tanpa saling mengimpor domain.

Nama tabel TETAP `kantor_config` / `kantor_llm_usage` (peninggalan saat kedua
sistem masih satu repo) — tabelnya dipakai bersama di DB yang sama, jadi
mengganti nama tabel tidak ada untungnya dan hanya menambah risiko migrasi.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class KantorConfig(Base):
    """Konfigurasi runtime key-value — bisa diubah TANPA deploy (Tahap 0).

    Kunci yang dipakai pengaman biaya:
      - 'kill_switch'          : 'on'/'off' → matikan semua panggilan LLM sementara.
      - 'spend_cap_usd_bulan'  : angka (mis. '50') → hentikan LLM bila spend bulan
                                 berjalan ≥ nilai ini. '0'/kosong = tanpa batas.
    """

    __tablename__ = "kantor_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    kunci: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    nilai: Mapped[str | None] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class KantorLLMUsage(Base):
    """Jejak pemakaian LLM per panggilan → dasar spend-cap & pantauan biaya.

    Dicatat best-effort oleh app.ai.guard; kegagalan pencatatan tak boleh
    menghambat panggilan utama.
    """

    __tablename__ = "kantor_llm_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    model: Mapped[str] = mapped_column(String(60), nullable=False)
    pemanggil: Mapped[str] = mapped_column(String(60), default="?")  # label call-site/agen
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    est_biaya_usd: Mapped[float] = mapped_column(Numeric(12, 6), default=0)
    status: Mapped[str] = mapped_column(String(12), default="ok")  # ok / error / blocked
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
