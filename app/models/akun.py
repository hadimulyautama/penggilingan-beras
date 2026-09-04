"""Kredensial masuk webapp produksi.

Sengaja HANYA kredensial. Identitas orang — nama, peran, gudang bawaan — tetap
tinggal di `users` (master bersama `hmu_core`), dan tabel ini menautnya lewat
`user_id`. Tidak ada kolom peran di sini: begitu peran tersalin di dua tempat,
cepat atau lambat keduanya berbeda dan tak ada yang tahu mana yang benar.

Letaknya di repo produksi, bukan di `hmu_core`, karena model akses lintas
aplikasi belum diputuskan (lihat rancangan Fase B). Bentuknya sudah disiapkan
untuk dinaikkan ke `hmu_core` kelak bila Timbangan dan Produksi hendak berbagi
satu login: yang perlu dilakukan cuma ganti nama tabel dan pindah pemilik chain
migrasi — tidak ada data yang perlu dibentuk ulang.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin
from hmu_core import User


class ProduksiAkun(Base, TimestampMixin):
    """Satu akun masuk untuk satu orang di `users`."""

    __tablename__ = "produksi_akun"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), unique=True, nullable=False
    )
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # aktif | nonaktif — dinonaktifkan, tidak pernah dihapus, agar `created_by`
    # pada catatan lama tetap menunjuk ke orang yang benar.
    status: Mapped[str] = mapped_column(String(20), default="aktif", nullable=False)

    # pribadi | bersama — ditentukan PERAN, bukan selera (lihat mode_bawaan()).
    #   bersama : perangkat milik gudang, dipakai bergantian. Sesi pendek dan
    #             putus saat menganggur, supaya pekerjaan tidak tercatat atas
    #             nama pemakai sebelumnya.
    #   pribadi : perangkat milik orangnya sendiri. Sesi panjang, sekali masuk.
    #
    # Operator memakai perangkat GUDANG: data pabrik — nama supplier, bobot,
    # kode batch — tidak boleh menetap di HP pribadi lalu ikut keluar bersama
    # orangnya. Admin & staff memakai perangkatnya sendiri: merekalah yang
    # memang berhak atas data itu, dan mobilitasnya bagian dari pekerjaannya.
    mode_perangkat: Mapped[str] = mapped_column(
        String(10), default="bersama", nullable=False
    )

    # Sandi awal diberikan admin secara lisan; pemiliknya wajib menggantinya
    # saat pertama masuk supaya admin tidak ikut memegang sandi orang lain.
    harus_ganti_sandi: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    terakhir_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(lazy="joined")

    # ── Peran dibaca dari master, tidak pernah disalin ke sini ──
    @property
    def peran(self) -> str:
        return self.user.role if self.user else ""

    @property
    def nama(self) -> str:
        return self.user.nama if self.user else self.username

    @property
    def is_admin(self) -> bool:
        """Direksi ke atas. Superadmin selalu termasuk — ia di ATAS Direksi,
        dan tangga yang tidak menurun ke bawah bukan tangga."""
        return self.peran in ("admin", "superadmin")

    @property
    def is_super(self) -> bool:
        return self.peran == "superadmin"

    @property
    def is_staff(self) -> bool:
        """Boleh melihat data uang.

        "staff" dipertahankan sebagai peran LAMA: sejak 3 September 2026
        tangganya superadmin / admin / operator, tetapi baris lama di `users`
        mungkin masih menyebut staff, dan orangnya tidak boleh kehilangan
        akses gara-gara namanya berganti.
        """
        return self.peran in ("superadmin", "admin", "staff")

    @property
    def sesi_pendek(self) -> bool:
        return self.mode_perangkat == "bersama"


def mode_bawaan(peran: str) -> str:
    """Jenis perangkat menurut peran — dasar bagi halaman kelola pengguna.

    Operator → 'bersama' (perangkat gudang). Selebihnya → 'pribadi'. Admin
    tetap boleh mengubahnya per akun bila kenyataannya berbeda, tetapi
    bawaannya harus aman: keliru memberi operator sesi panjang di perangkat
    bergantian berarti catatan atas nama orang yang salah.
    """
    return "bersama" if peran == "operator" else "pribadi"
