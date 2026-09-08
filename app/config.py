"""Konfigurasi aplikasi — dibaca dari environment (.env)."""
from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Database
    database_url: str = "postgresql+asyncpg://milluser:millpass@localhost:5432/penggilingan"

    @field_validator("database_url")
    @classmethod
    def _use_asyncpg(cls, v: str) -> str:
        """Pastikan driver async. Railway/Heroku memberi 'postgres://' atau
        'postgresql://' (driver sync); kita butuh 'postgresql+asyncpg://'.
        Juga buang query 'sslmode' yang tidak dikenal asyncpg."""
        if v.startswith("postgres://"):
            v = "postgresql+asyncpg://" + v[len("postgres://"):]
        elif v.startswith("postgresql://"):
            v = "postgresql+asyncpg://" + v[len("postgresql://"):]
        if v.startswith("postgresql+asyncpg://") and "sslmode=" in v:
            # asyncpg pakai parameter 'ssl', bukan 'sslmode' (punya psycopg2).
            import re
            v = re.sub(r"[?&]sslmode=[^&]*", "", v)
        return v

    # Telegram — TIDAK ADA LAGI. Bot produksi dibubarkan; operasional dan
    # timbangan dicatat di aplikasinya, dan satu-satunya bot yang tersisa
    # adalah Kantor AI di service-nya sendiri. Variabel BOT_*_TOKEN mungkin
    # masih menempel di Railway; tidak dibaca di sini adalah justru maksudnya,
    # karena token yang dibaca berarti bot yang bisa menyala kembali.

    # Claude — model dipilih per SURFACE:
    anthropic_api_key: str = ""
    # BOT (percakapan): butuh paham nuansa → Sonnet (Haiku sering "tidak nyambung").
    claude_model: str = "claude-sonnet-5"
    # AGENT (loop reasoning multi-tool untuk pertanyaan bebas/analitik) → Sonnet.
    agent_model: str = "claude-sonnet-5"
    # MINI APP (UI terstruktur, tugas AI ringan spt input cepat) → Haiku (murah).
    miniapp_model: str = "claude-haiku-4-5"
    # Batas iterasi tool-loop agent (jaring anti-loop tak berujung).
    agent_max_iterations: int = 6
    # Router domain agen Kantor: pangkas tool ke domain relevan (deterministik,
    # 0 token). Default OFF (bundel penuh + prompt-cache utuh). Nilai utama: akurasi.
    router_aktif: bool = False

    # Auto-watch invoice: pantau _TRANSIT → usul (arsip + update IT) lewat gerbang.
    # Default OFF (jaga biaya OCR/LLM; nyalakan setelah divalidasi, mis. saat GajiHub).
    invoice_auto: bool = False

    # Aplikasi
    app_timezone: str = "Asia/Jakarta"
    undo_window_minutes: int = 15

    # Token rahasia untuk buka dashboard web (/dashboard?token=...). Kosong =
    # dashboard web dinonaktifkan (hanya versi Telegram yang jalan).
    dashboard_token: str = ""

    # ── Webapp produksi (Fase B) ──
    # Kunci penanda-tangan cookie sesi. WAJIB diisi di produksi — bila kosong,
    # dipakai kunci acak per proses dan semua sesi hangus tiap kali restart.
    secret_key: str = ""
    # Umur sesi untuk perangkat PRIBADI (HP sendiri): panjang, supaya membuka
    # aplikasi lagi tak pernah meminta sandi.
    sesi_hari: int = 30
    # Umur sesi untuk akun bermode 'bersama' (perangkat dipakai bergantian):
    # pendek, supaya pekerjaan tak tercatat atas nama pemakai sebelumnya.
    sesi_bersama_menit: int = 45
    # Akun webapp PERTAMA. Diisi sekali saat menyiapkan sistem: bila belum ada
    # akun sama sekali, dibuatkan akun untuk user ber-ADMIN_TELEGRAM_ID dengan
    # sandi ini, dan pemiliknya WAJIB menggantinya saat pertama masuk.
    # Kosongkan lagi setelah akun jadi.
    admin_username: str = "admin"
    admin_sandi_awal: str = ""

    # ── Seam Kantor ↔ Produksi (dua repo/service, satu DB) ──
    # Sisi PRODUKSI: token API internal (/internal/produksi/*). Kosong = API mati.
    internal_api_token: str = ""
    # Sisi KANTOR: alamat + token service produksi yang dipanggil klien_produksi.
    # Selama masih satu proses, isi produksi_api_url dengan http://127.0.0.1:8000.
    produksi_api_url: str = ""
    produksi_api_token: str = ""
    produksi_api_timeout: float = 120.0   # agent pabrik bisa lama (loop multi-tool)

    # Kapasitas tumpukan PK Gudang 2 (maks). Lewat batas → notifikasi.
    g2_tumpukan_maks_kg: int = 60_000
    # Tumpukan PK Gudang 1 — hasil giling yang belum dikirim ke penyosohan.
    # BATAS FISIK LANTAI, bukan kebijakan: itu sebabnya ia di sini dan bukan di
    # halaman Pengaturan. Lantai tidak berubah menurut musim.
    g1_pk_tumpukan_maks_kg: int = 80_000

    # MODE UJI — menyalakan halaman "hapus data uji" (Super Admin saja).
    # Dimatikan secara bawaan, dan mematikannya bukan sekadar menyembunyikan
    # tombol: endpointnya ikut menolak. Setelah pabrik berjalan, biarkan mati.
    mode_uji: bool = False

    # Stok kemasan minimum (lembar) — di bawah ini beri notifikasi/warning.
    min_kemasan_lembar: int = 1_000

    # Ambang "nyangkut" (jam) — item diam lebih lama dari ini disorot.
    nyangkut_fisik_jam: float = 12    # langkah fisik tersendat (proses/pindah)
    nyangkut_verif_jam: float = 24    # verifikasi/QC tertunda

    # Admin awal (di-seed otomatis ke DB kosong saat startup).
    # Kosongkan admin_telegram_id bila tidak ingin auto-seed user.
    admin_telegram_id: int | None = None
    admin_name: str = "Admin"

    # Pengeringan
    drying_late_hours: float = 5.0  # batas keterlambatan log kadar air
    drying_check_interval_seconds: int = 900  # frekuensi cek scheduler (15 mnt)
    # Toleransi/spare kapasitas dryer: boleh terisi melebihi kapasitas nominal
    # sampai (kapasitas + toleransi). Mis. nominal 30 ton + 3 ton = 33 ton.
    dryer_toleransi_kg: int = 3000

    # Kadar air yang dituju sebuah pengeringan. Dipakai HANYA untuk menghitung
    # kemajuan di layar — bukan untuk menghentikan mesin sendiri: yang
    # memutuskan gabah sudah cukup kering tetap orang yang memegang alat tes.
    kadar_air_target_persen: float = 14

    # ── Biaya operasional (Rp), untuk HPP penuh. Semua bisa diubah via env. ──
    biaya_bongkar_per_kg_gabah: float = 20        # tenaga bongkar gabah datang
    # Operator: FLAT per sekali proses milling (bukan per kg).
    biaya_operator_per_proses: float = 400_000
    biaya_tenaga_milling_per_kg_pk: float = 25    # tenaga saat milling, per kg PK
    biaya_pengeringan_basah_per_kg: float = 100   # gabah basah dikeringkan
    biaya_pengeringan_kering_per_kg: float = 15   # gabah kering tetap dikeringkan
    biaya_listrik_milling_per_kg_gabah: float = 20  # listrik/mesin saat milling
    # Rubber roll mesin pecah kulit: 1 set per N ton gabah, harga per set.
    rubber_roll_harga_per_set: float = 2_000_000
    rubber_roll_umur_ton: float = 100

    # ── Biaya PENYOSOHAN (PK → beras putih). Basis: kg PK yang disosoh. Crew
    #    penyosohan TERPISAH dari crew milling. Semua masuk HPP beras. ──
    biaya_penyosohan_per_kg_pk: float = 100          # sosoh, per kg PK (Rp1jt/10 ton)
    biaya_tenaga_penyosohan_per_kg_pk: float = 50    # tenaga crew sosoh, per kg PK
    biaya_transport_penyosohan_per_kg_pk: float = 50  # transport inbound, per kg PK (Rp500rb/10 ton)
    biaya_operator_penyosohan: float = 300_000       # FLAT per proses penyosohan
    # Marketing = BEBAN PENJUALAN, BUKAN HPP. Untuk laporan margin/harga jual,
    # jangan dimasukkan ke hitung_hpp_beras.
    biaya_marketing_per_kg_beras: float = 50

    # Asumsi kapasitas teoritis (utk analitik utilisasi). Bisa via env.
    kapasitas_siklus_dryer_per_hari: float = 1     # ~1 siklus (sore-besok sore)
    kapasitas_hari_kerja_per_bulan: int = 26
    rendemen_asumsi_persen: float = 64             # dipakai bila belum ada data

settings = Settings()
