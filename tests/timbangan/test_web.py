"""Uji alur lewat HTTP: petugas benar-benar bisa menyelesaikan pekerjaannya.

Uji layanan membuktikan aturannya benar; uji ini membuktikan aturan itu
sampai ke layar — rute terdaftar, template tidak salah nama, formulir kembali
lagi ke server dengan nama kolom yang benar, dan halaman yang seharusnya
tertutup memang tertutup.
"""
from __future__ import annotations

import re

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.gudang1.models  # noqa: F401
import app.gudang2.models  # noqa: F401
import app.models  # noqa: F401
from app import database
from app.database import Base
from app.models import Supplier
from app.timbangan import service
from app.timbangan.models import (
    ROLE_ADMIN,
    ROLE_PENGAWAS,
    ROLE_PETUGAS,
    TimbanganAkun,
)
from app.timbangan.security import hash_sandi
from app.timbangan.web import PREFIX, pasang

SANDI = "rahasia123"
TELEPON_UJI = "+62 851-7416-7950"


@pytest_asyncio.fixture
async def app_uji(monkeypatch):
    """Satu aplikasi + satu DB SQLite sementara per uji."""
    mesin = create_async_engine("sqlite+aiosqlite://")
    async with mesin.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Sesi = async_sessionmaker(mesin, expire_on_commit=False)
    # Modul mengambil SessionLocal lewat `app.database`, bukan meng-import
    # objeknya — justru supaya bisa dialihkan seperti ini.
    monkeypatch.setattr(database, "SessionLocal", Sesi)

    async with Sesi() as db:
        await service.pastikan_jenis(db)
        db.add_all([
            TimbanganAkun(username="budi", nama="Budi", role=ROLE_PETUGAS,
                          password_hash=hash_sandi(SANDI), perangkat_kode="P1"),
            TimbanganAkun(username="miftah", nama="Miftah", role=ROLE_PENGAWAS,
                          password_hash=hash_sandi(SANDI), perangkat_kode="P9"),
            TimbanganAkun(username="wahid", nama="Wahid", role=ROLE_ADMIN,
                          password_hash=hash_sandi(SANDI), perangkat_kode="P0"),
            Supplier(nama_supplier="H. Anton"),
        ])
        await db.commit()

    aplikasi = FastAPI()
    pasang(aplikasi)
    yield aplikasi
    await mesin.dispose()


@pytest_asyncio.fixture
async def klien(app_uji):
    async with AsyncClient(
        transport=ASGITransport(app=app_uji), base_url="http://uji",
        follow_redirects=True,
    ) as c:
        yield c


async def login(klien: AsyncClient, siapa: str = "budi") -> None:
    r = await klien.post(
        f"{PREFIX}/masuk",
        data={"username": siapa, "sandi": SANDI, "perangkat": "P1", "tujuan": ""},
    )
    assert r.status_code == 200, r.text


def kode_dari(html: str) -> str:
    cocok = re.search(r'name="kode" value="(TRX-[^"]+)"', html)
    assert cocok, "nomor transaksi tidak ada di formulir"
    return cocok.group(1)


# ─────────────────── Penjaga akses ───────────────────

async def test_belum_login_diarahkan_ke_halaman_masuk(klien):
    r = await klien.get(f"{PREFIX}/")
    assert r.status_code == 200
    assert "Kata sandi" in r.text


async def test_sandi_salah_tidak_membocorkan_yang_mana(klien):
    r = await klien.post(
        f"{PREFIX}/masuk",
        data={"username": "budi", "sandi": "salah", "perangkat": "", "tujuan": ""},
    )
    assert "Nama pengguna atau kata sandi salah" in r.text

    r = await klien.post(
        f"{PREFIX}/masuk",
        data={"username": "tidakada", "sandi": "apa saja", "perangkat": "",
              "tujuan": ""},
    )
    assert "Nama pengguna atau kata sandi salah" in r.text


async def test_petugas_tidak_bisa_membuka_halaman_pengawas(klien):
    await login(klien)
    r = await klien.get(f"{PREFIX}/laporan")
    assert r.status_code == 403
    assert "Pengawas" in r.text


async def test_petugas_tidak_bisa_membuka_halaman_admin(klien):
    await login(klien)
    assert (await klien.get(f"{PREFIX}/pengguna")).status_code == 403


async def test_admin_bisa_membuka_semuanya(klien):
    await login(klien, "wahid")
    for jalur in ("/laporan", "/monitoring", "/tara", "/pengguna",
                  "/aturan", "/pengaturan"):
        r = await klien.get(PREFIX + jalur)
        assert r.status_code == 200, f"{jalur} → {r.status_code}"


# ─────────────────── Halaman utama ───────────────────

async def test_beranda_menawarkan_tiga_arah(klien):
    await login(klien)
    r = await klien.get(f"{PREFIX}/")
    assert r.status_code == 200
    assert "Barang masuk" in r.text
    assert "Pengiriman" in r.text
    assert "Jasa timbang" in r.text


async def test_daftar_komoditas_berbeda_menurut_arah(klien):
    """Menir, bekatul, dan reject tidak pernah dibeli — jangan ditawarkan."""
    await login(klien)
    masuk = (await klien.get(f"{PREFIX}/pilih/MASUK")).text
    keluar = (await klien.get(f"{PREFIX}/pilih/KELUAR")).text

    assert "Gabah Basah" in masuk
    assert "Bekatul" not in masuk
    assert "Menir" not in masuk

    assert "Bekatul" in keluar
    assert "Gabah Basah" not in keluar


# ─────────────────── Alur lengkap ───────────────────

async def test_alur_lengkap_masuk_sampai_hasil(klien):
    await login(klien)

    form = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
    kode = kode_dari(form)
    assert kode.startswith("TRX-") and "-P1-" in kode

    r = await klien.post(f"{PREFIX}/timbang/GABAH_BASAH", data={
        "kode": kode, "berat_kg": "13.600", "cara_timbang": "DUA_KALI",
        "supplier_id": "1", "nomor_polisi": "ad 1234 xy", "nama_sopir": "Slamet",
        "nomor_acuan": "NOTA-01", "jumlah_karung": "120",
        "tara_per_karung_kg": "0,25", "berat_acuan_kg": "10.048",
        "tara_lain_kg": "0", "waktu": "", "catatan": "", "pihak_nama": "",
    })
    assert r.status_code == 200
    assert "Menunggu timbang kedua" in r.text
    assert "AD 1234 XY" in r.text

    # Tiket muncul di beranda dan di daftar tiket.
    assert "AD 1234 XY" in (await klien.get(f"{PREFIX}/")).text
    tiket = await klien.get(f"{PREFIX}/tiket")
    assert "AD 1234 XY" in tiket.text

    trx_id = int(re.search(r"/tiket/(\d+)", tiket.text).group(1))
    r = await klien.post(f"{PREFIX}/tiket/{trx_id}", data={
        "berat_kg": "3570", "jumlah_karung": "", "tara_per_karung_kg": "",
        "berat_acuan_kg": "", "nomor_acuan": "", "waktu": "", "catatan": "",
    })
    assert r.status_code == 200
    assert "PERLU PEMERIKSAAN" in r.text
    assert "10.000 kg" in r.text     # berat barang
    assert "-48 kg" in r.text        # selisih


async def test_angka_dengan_koma_maupun_titik_diterima(klien):
    """Petugas mengetik apa adanya; sistem yang menyesuaikan diri."""
    await login(klien)
    for berat, harapan in (("13.600", "13.600"), ("13600", "13.600"),
                           ("13600,7", "13.601")):
        form = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
        r = await klien.post(f"{PREFIX}/timbang/GABAH_BASAH", data={
            "kode": kode_dari(form), "berat_kg": berat,
            "cara_timbang": "DUA_KALI", "supplier_id": "1",
            "nomor_polisi": "AD 1 A", "jumlah_karung": "10",
            "tara_per_karung_kg": "0,25", "berat_acuan_kg": "1000",
            "tara_lain_kg": "0", "waktu": "", "catatan": "",
            "nomor_acuan": "", "nama_sopir": "", "pihak_nama": "",
        })
        assert harapan in r.text, f"{berat} → tidak muncul {harapan}"


async def test_jasa_timbang_sekali_langsung_ada_hasil(klien):
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/BEBAS")).text
    r = await klien.post(f"{PREFIX}/timbang/BEBAS", data={
        "kode": kode_dari(form), "berat_kg": "12850",
        "cara_timbang": "SEKALI", "pihak_nama": "CV Sumber Rejeki",
        "nomor_polisi": "AD 9 ZZ", "tara_lain_kg": "0", "supplier_id": "",
        "jumlah_karung": "0", "tara_per_karung_kg": "0", "berat_acuan_kg": "0",
        "waktu": "", "catatan": "", "nomor_acuan": "", "nama_sopir": "",
    })
    assert r.status_code == 200
    assert "JASA TIMBANG" in r.text
    assert "12.850 kg" in r.text


async def test_tutup_paksa_tiket_lewat_halaman(klien):
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
    await klien.post(f"{PREFIX}/timbang/GABAH_BASAH", data={
        "kode": kode_dari(form), "berat_kg": "13600", "cara_timbang": "DUA_KALI",
        "supplier_id": "1", "nomor_polisi": "AD 7 QQ", "jumlah_karung": "10",
        "tara_per_karung_kg": "0,25", "berat_acuan_kg": "1000",
        "tara_lain_kg": "0", "waktu": "", "catatan": "", "nomor_acuan": "",
        "nama_sopir": "", "pihak_nama": "",
    })
    tiket = await klien.get(f"{PREFIX}/tiket")
    trx_id = int(re.search(r"/tiket/(\d+)", tiket.text).group(1))

    r = await klien.post(f"{PREFIX}/tiket/{trx_id}/tutup",
                         data={"alasan": "Mutu ditolak, truk kembali"})
    assert "ditutup beserta alasannya" in r.text
    assert "Tidak ada truk yang sedang menunggu" in \
        (await klien.get(f"{PREFIX}/tiket")).text


# ─────────────────── Kerahasiaan pada bukti cetak ───────────────────

async def _selesaikan(klien, jenis: str, **beda) -> int:
    form = (await klien.get(f"{PREFIX}/timbang/{jenis}")).text
    data = {
        "kode": kode_dari(form), "berat_kg": "13600", "cara_timbang": "DUA_KALI",
        "supplier_id": "1", "nomor_polisi": "AD 5 BB", "jumlah_karung": "120",
        "tara_per_karung_kg": "0,25", "berat_acuan_kg": "10000",
        "tara_lain_kg": "0", "waktu": "", "catatan": "", "nomor_acuan": "N-1",
        "nama_sopir": "Slamet", "pihak_nama": "",
    }
    data.update(beda)
    await klien.post(f"{PREFIX}/timbang/{jenis}", data=data)
    tiket = await klien.get(f"{PREFIX}/tiket")
    trx_id = int(re.search(r"/tiket/(\d+)", tiket.text).group(1))
    await klien.post(f"{PREFIX}/tiket/{trx_id}", data={
        "berat_kg": "3570", "jumlah_karung": "", "tara_per_karung_kg": "",
        "berat_acuan_kg": "", "nomor_acuan": "", "waktu": "", "catatan": "",
    })
    return trx_id


async def test_bukti_gabah_tidak_memuat_selisih(klien):
    """SOP butir 8: hasil kontrol gabah adalah data internal."""
    await login(klien)
    trx_id = await _selesaikan(klien, "GABAH_BASAH")
    cetak = (await klien.get(f"{PREFIX}/transaksi/{trx_id}/cetak")).text
    assert "BERAT BARANG" in cetak
    assert "Selisih" not in cetak
    assert "Menurut dokumen" not in cetak


async def test_bukti_beras_pk_memuat_selisih(klien):
    """Sistem Tara butir 9: nota PK justru wajib diberikan ke pengirim."""
    await login(klien)
    trx_id = await _selesaikan(
        klien, "BERAS_PK", tara_per_karung_kg="0,085", berat_acuan_kg="9990"
    )
    cetak = (await klien.get(f"{PREFIX}/transaksi/{trx_id}/cetak")).text
    assert "Selisih" in cetak
    assert "Menurut dokumen" in cetak


async def test_bukti_memuat_petugas_dan_identitas_perusahaan(klien):
    await login(klien)
    trx_id = await _selesaikan(klien, "GABAH_BASAH")
    cetak = (await klien.get(f"{PREFIX}/transaksi/{trx_id}/cetak")).text
    assert "PT Hadi Mulya Utama" in cetak
    assert "Masaran, Kab. Sragen" in cetak
    assert "Budi" in cetak                      # petugas timbang
    assert TELEPON_UJI in cetak
    # Alamat surel sengaja tidak ikut dicetak — Direksi memutuskan bukti
    # timbang cukup memuat alamat dan nomor telepon.
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", cetak)


# ─────────────────── Tidak ada harga di mana pun ───────────────────

@pytest.mark.parametrize("jalur", [
    "/", "/pilih/MASUK", "/pilih/KELUAR", "/timbang/GABAH_BASAH",
    "/tiket", "/transaksi", "/aturan", "/pengaturan",
])
async def test_tidak_ada_kata_harga_di_layar_petugas(klien, jalur):
    """Operator pos timbang tidak boleh tahu harga — termasuk di tampilan."""
    await login(klien)
    teks = (await klien.get(PREFIX + jalur)).text.lower()
    for kata in ("harga", "rupiah", " rp", "potongan", "refaksi"):
        assert kata not in teks, f"{jalur} memuat '{kata}'"


# ─────────────────── Koreksi lewat halaman ───────────────────

async def test_koreksi_lewat_halaman_menghitung_ulang(klien):
    await login(klien)
    trx_id = await _selesaikan(klien, "GABAH_BASAH", berat_acuan_kg="10048")

    rincian = (await klien.get(f"{PREFIX}/transaksi/{trx_id}")).text
    assert "PERLU PEMERIKSAAN" in rincian

    r = await klien.post(f"{PREFIX}/transaksi/{trx_id}/koreksi", data={
        "alasan": "Salah ketik berat nota", "timbang1_kg": "", "timbang2_kg": "",
        "nomor_polisi": "", "nama_sopir": "", "supplier_id": "",
        "jumlah_karung": "120", "tara_per_karung_kg": "0,25",
        "berat_acuan_kg": "10010", "nomor_acuan": "N-1", "catatan": "",
    })
    assert "Koreksi tersimpan" in r.text
    assert "NORMAL" in r.text


async def test_koreksi_wajib_beralasan(klien):
    await login(klien)
    trx_id = await _selesaikan(klien, "GABAH_BASAH")
    r = await klien.post(f"{PREFIX}/transaksi/{trx_id}/koreksi", data={
        "alasan": "   ", "berat_acuan_kg": "9000",
    })
    assert "harus disertai alasan" in r.text


# ─────────────────── Ekspor ───────────────────

async def test_ekspor_csv_tanpa_kolom_uang(klien):
    await login(klien, "wahid")
    await _selesaikan(klien, "GABAH_BASAH")
    r = await klien.get(f"{PREFIX}/ekspor.csv")
    assert r.status_code == 200
    kepala = r.text.splitlines()[0].lower()
    for kata in ("harga", "rp", "nilai", "biaya", "potongan"):
        assert kata not in kepala
    assert "selisih_kg" in kepala


# ─────────────────── Pembacaan angka yang diketik petugas ───────────────────

@pytest.mark.parametrize("ketikan, harapan", [
    # Titik sebagai pemisah ribuan
    ("13.600", 13600.0),
    ("13600", 13600.0),
    ("1.234.567", 1234567.0),
    ("10.048", 10048.0),
    # Titik sebagai desimal — angka di depan titik nol
    ("0.250", 0.25),
    ("0.085", 0.085),
    ("0.05", 0.05),
    ("0.070", 0.07),
    # Koma selalu desimal
    ("0,25", 0.25),
    ("13.600,5", 13600.5),
    ("13600,7", 13600.7),
    # Bukan angka → nilai bawaan
    ("", 0.0),
    ("abc", 0.0),
])
def test_membaca_angka_yang_diketik(ketikan, harapan):
    """Regresi: tara '0.250' pernah terbaca 250 kg.

    Satu titik dengan tiga angka di belakangnya ambigu — '13.600' berarti tiga
    belas ribu enam ratus, '0.250' berarti seperempat kilogram. Angka di depan
    titik yang membedakan. Salah menebak membuat setiap transaksi gabah
    ditolak sebagai mustahil, karena taranya membengkak seribu kali lipat.
    """
    from app.timbangan.routes.pos import _angka
    assert _angka(ketikan) == pytest.approx(harapan)


async def test_tara_prasetel_bertahan_melintasi_dua_tahap(klien):
    """Nilai tara yang disodorkan sistem harus bisa dibaca ulang oleh sistem.

    Formulir tahap kedua mengisi ulang tara dari transaksi ('0.250'); bila
    pembacaannya berbeda dari saat menulisnya, penimbangan gagal di tahap
    terakhir — persis ketika truk sudah selesai bongkar.
    """
    await login(klien)
    form = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
    assert 'value="0.250"' in form          # disodorkan server apa adanya

    await klien.post(f"{PREFIX}/timbang/GABAH_BASAH", data={
        "kode": kode_dari(form), "berat_kg": "13.600",
        "cara_timbang": "DUA_KALI", "supplier_id": "1",
        "nomor_polisi": "AD 1234 XY", "nama_sopir": "Slamet",
        "nomor_acuan": "NOTA-01", "jumlah_karung": "120",
        "tara_per_karung_kg": "0.250",     # persis seperti yang disodorkan
        "berat_acuan_kg": "10.048", "tara_lain_kg": "0", "waktu": "",
        "catatan": "", "pihak_nama": "",
    })

    tiket = await klien.get(f"{PREFIX}/tiket")
    trx_id = int(re.search(r"/tiket/(\d+)", tiket.text).group(1))
    tahap2 = (await klien.get(f"{PREFIX}/tiket/{trx_id}")).text
    assert 'value="0.250"' in tahap2

    r = await klien.post(f"{PREFIX}/tiket/{trx_id}", data={
        "berat_kg": "3570", "jumlah_karung": "120",
        "tara_per_karung_kg": "0.250", "berat_acuan_kg": "10048",
        "nomor_acuan": "NOTA-01", "waktu": "", "catatan": "",
    })
    assert "Tara lebih besar" not in r.text
    assert "10.000 kg" in r.text        # berat barang, tara 30 kg bukan 30.000


# ─────────────────── Halaman pengaturan ───────────────────

async def test_pengaturan_mendaftar_parameter_beserta_nilainya(klien):
    """Katalog harus menyebut nilai yang benar-benar berlaku, bukan contoh."""
    await login(klien, "wahid")
    teks = (await klien.get(f"{PREFIX}/pengaturan")).text

    # Admin melihatnya sebagai kotak isian berisi angka mentah.
    assert "Kapasitas jembatan timbang" in teks
    assert 'value="20000"' in teks
    assert "TIMBANGAN_KAPASITAS_KG" in teks
    assert "Transaksi terkunci setelah" in teks and 'value="24"' in teks
    assert "Tiket ditandai lama setelah" in teks and 'value="12"' in teks
    assert "Ukuran maksimum satu foto" in teks and 'value="4"' in teks
    assert TELEPON_UJI in teks
    assert "11 komoditas aktif" in teks


async def test_bukan_admin_melihat_nilai_terbaca_tanpa_kotak_isian(klien):
    """Petugas boleh tahu batas yang berlaku, tetapi tidak mengubahnya."""
    await login(klien)                       # budi — petugas
    teks = (await klien.get(f"{PREFIX}/pengaturan")).text
    assert "20.000 kg" in teks               # pemisah ribuan, mudah dibaca
    assert 'name="nilai"' not in teks
    assert "Hanya Admin yang dapat mengubah bagian ini." in teks


async def test_pengaturan_tidak_pernah_menampilkan_kunci_sesi(klien):
    """Kunci penanda sesi hanya boleh dilaporkan ada atau tidak."""
    import os
    from app.timbangan.config import tsettings

    await login(klien, "wahid")
    teks = (await klien.get(f"{PREFIX}/pengaturan")).text
    assert "Kunci penanda sesi" in teks
    if tsettings.secret_key:
        assert tsettings.secret_key not in teks
        assert "sudah diset" in teks
    else:
        assert "BELUM DISET" in teks


async def test_pengaturan_menyembunyikan_baris_di_luar_peran(klien):
    """Petugas melihat akunnya dan aturan; tidak melihat pintu admin."""
    await login(klien)                       # budi — petugas
    teks = (await klien.get(f"{PREFIX}/pengaturan")).text

    assert "Akun ini" in teks
    assert "Aturan komoditas" in teks
    assert "Pengguna &amp; perangkat" not in teks
    assert "Tara standar" not in teks
    assert "Sesi &amp; keamanan" not in teks


async def test_pengaturan_memuat_tombol_keluar(klien):
    await login(klien)
    teks = (await klien.get(f"{PREFIX}/pengaturan")).text
    assert f'action="{PREFIX}/keluar"' in teks
    assert ">Keluar<" in teks


async def test_keluar_dari_pengaturan_benar_benar_mengakhiri_sesi(klien):
    await login(klien)
    r = await klien.post(f"{PREFIX}/keluar")
    assert "Kata sandi" in r.text            # kembali ke halaman masuk
    # Membuka beranda lagi harus meminta login, bukan menampilkan isi.
    assert "Kata sandi" in (await klien.get(f"{PREFIX}/")).text


async def test_tautan_akun_lama_mengarah_ke_pengaturan(klien):
    await login(klien)
    r = await klien.get(f"{PREFIX}/akun")
    assert str(r.url).endswith("/pengaturan")
    assert "Akun ini" in r.text


# ─────────────────── Setelan operasional benar-benar berdampak ───────────────────

async def test_admin_menyetel_kapasitas_dan_langsung_berlaku(klien):
    """Bukti bahwa setelan dipakai, bukan sekadar tersimpan.

    Kapasitas diturunkan ke 12 ton; truk 13,6 ton yang tadinya sah kini
    ditolak — tanpa menyalakan ulang service.
    """
    await login(klien, "wahid")

    form = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
    r = await klien.post(f"{PREFIX}/timbang/GABAH_BASAH", data={
        "kode": kode_dari(form), "berat_kg": "13600", "cara_timbang": "DUA_KALI",
        "supplier_id": "1", "nomor_polisi": "AD 1 A", "jumlah_karung": "10",
        "tara_per_karung_kg": "0.250", "berat_acuan_kg": "1000",
        "tara_lain_kg": "0", "waktu": "", "catatan": "", "nomor_acuan": "",
        "nama_sopir": "", "pihak_nama": "",
    })
    assert "Melebihi kapasitas" not in r.text

    r = await klien.post(f"{PREFIX}/pengaturan", data={
        "kunci": "kapasitas_jembatan_kg", "nilai": "12000", "aksi": "simpan",
    })
    assert "kini 12.000 kg" in r.text

    form = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
    assert "12.000 kg" in form              # bantuan di layar ikut berubah
    r = await klien.post(f"{PREFIX}/timbang/GABAH_BASAH", data={
        "kode": kode_dari(form), "berat_kg": "13600", "cara_timbang": "DUA_KALI",
        "supplier_id": "1", "nomor_polisi": "AD 2 B", "jumlah_karung": "10",
        "tara_per_karung_kg": "0.250", "berat_acuan_kg": "1000",
        "tara_lain_kg": "0", "waktu": "", "catatan": "", "nomor_acuan": "",
        "nama_sopir": "", "pihak_nama": "",
    })
    assert "Melebihi kapasitas jembatan timbang (12000 kg)" in r.text


async def test_setelan_di_luar_batas_wajar_ditolak(klien):
    """Kapasitas yang salah ketik akan menolak setiap truk — jangan diterima."""
    await login(klien, "wahid")
    for nilai in ("0", "50", "999999", "abc", ""):
        r = await klien.post(f"{PREFIX}/pengaturan", data={
            "kunci": "kapasitas_jembatan_kg", "nilai": nilai, "aksi": "simpan",
        })
        assert "kini" not in r.text, f"{nilai!r} seharusnya ditolak"


async def test_kembalikan_bawaan_menghapus_setelan(klien):
    await login(klien, "wahid")
    await klien.post(f"{PREFIX}/pengaturan", data={
        "kunci": "jam_kunci_otomatis", "nilai": "48", "aksi": "simpan",
    })
    teks = (await klien.get(f"{PREFIX}/pengaturan")).text
    assert 'value="48"' in teks and "disetel dari layar" in teks

    r = await klien.post(f"{PREFIX}/pengaturan", data={
        "kunci": "jam_kunci_otomatis", "aksi": "bawaan", "nilai": "",
    })
    assert "kembali ke bawaan 24 jam" in r.text
    assert 'value="24"' in (await klien.get(f"{PREFIX}/pengaturan")).text


async def test_bukan_admin_tidak_bisa_menyetel(klien):
    await login(klien)                       # budi — petugas
    r = await klien.post(f"{PREFIX}/pengaturan", data={
        "kunci": "kapasitas_jembatan_kg", "nilai": "12000", "aksi": "simpan",
    })
    assert r.status_code == 403


async def test_perubahan_setelan_tercatat_di_audit(klien, app_uji):
    from sqlalchemy import select
    from app import database
    from app.timbangan.models import TimbanganAudit

    await login(klien, "wahid")
    await klien.post(f"{PREFIX}/pengaturan", data={
        "kunci": "maks_foto_mb", "nilai": "8", "aksi": "simpan",
    })
    async with database.SessionLocal() as db:
        jejak = (await db.execute(
            select(TimbanganAudit).where(TimbanganAudit.aksi == "UBAH_SETELAN")
        )).scalars().all()
    assert len(jejak) == 1
    assert "4" in jejak[0].nilai_sebelum and "8" in jejak[0].nilai_sesudah


# ─────────────── Menambah pengguna: Admin saja ───────────────
#
# Peran menentukan siapa boleh mengoreksi timbangan dan menutup pemeriksaan.
# Siapa pun yang bisa membuat akun, bisa memberi dirinya peran apa pun — jadi
# pintu ini dijaga paling ketat. Pengawas sengaja ikut diuji: ia peran yang
# paling dekat ke Admin, dan paling mungkin keliru diberi akses saat kode
# disalin-tempel di kemudian hari.

async def jumlah_akun(app_uji) -> int:
    from sqlalchemy import func, select
    from app import database

    async with database.SessionLocal() as db:
        return (await db.execute(select(func.count(TimbanganAkun.id)))).scalar_one()


@pytest.mark.parametrize("siapa", ["budi", "miftah"])
async def test_bukan_admin_tidak_bisa_membuka_halaman_pengguna(klien, siapa):
    await login(klien, siapa)
    r = await klien.get(f"{PREFIX}/pengguna")
    assert r.status_code == 403
    assert "hanya untuk Admin" in r.text


@pytest.mark.parametrize("siapa", ["budi", "miftah"])
async def test_bukan_admin_tidak_bisa_membuat_akun(klien, app_uji, siapa):
    """Ditolak, DAN tidak ada akun yang benar-benar terbuat."""
    sebelum = await jumlah_akun(app_uji)
    await login(klien, siapa)

    r = await klien.post(f"{PREFIX}/pengguna", data={
        "username": "penyusup", "nama": "Penyusup", "role": ROLE_ADMIN,
        "sandi": "rahasia123", "perangkat_kode": "PX",
    })
    assert r.status_code == 403
    assert await jumlah_akun(app_uji) == sebelum


@pytest.mark.parametrize("siapa", ["budi", "miftah"])
async def test_bukan_admin_tidak_bisa_menonaktifkan_akun(klien, app_uji, siapa):
    from sqlalchemy import select
    from app import database

    await login(klien, siapa)
    r = await klien.post(f"{PREFIX}/pengguna/1/status")
    assert r.status_code == 403

    async with database.SessionLocal() as db:
        korban = (await db.execute(
            select(TimbanganAkun).where(TimbanganAkun.id == 1)
        )).scalars().one()
        assert korban.status == "aktif"      # tidak tersentuh


@pytest.mark.parametrize("siapa", ["budi", "miftah"])
async def test_pengaturan_tidak_menawarkan_pintu_pengguna(klien, siapa):
    """Bukan hanya ditolak saat dibuka — tautannya pun tidak ditampilkan."""
    await login(klien, siapa)
    teks = (await klien.get(f"{PREFIX}/pengaturan")).text
    assert "Pengguna &amp; perangkat" not in teks
    assert f"{PREFIX}/pengguna" not in teks


async def test_admin_bisa_membuat_akun(klien, app_uji):
    """Sisi lain dari aturan yang sama — Admin memang harus bisa."""
    sebelum = await jumlah_akun(app_uji)
    await login(klien, "wahid")

    r = await klien.post(f"{PREFIX}/pengguna", data={
        "username": "SARI", "nama": "Sari", "role": ROLE_PETUGAS,
        "sandi": "rahasia123", "perangkat_kode": "p2",
    })
    assert "Akun Sari dibuat" in r.text
    assert await jumlah_akun(app_uji) == sebelum + 1
    # Nama pengguna dijadikan huruf kecil, kode perangkat huruf besar.
    assert "sari" in r.text and "P2" in r.text


async def test_admin_tidak_bisa_menonaktifkan_akun_sendiri(klien):
    """Menutup pintu terakhir bagi diri sendiri harus dicegah."""
    from sqlalchemy import select
    from app import database

    await login(klien, "wahid")
    async with database.SessionLocal() as db:
        aku = (await db.execute(
            select(TimbanganAkun).where(TimbanganAkun.username == "wahid")
        )).scalars().one()

    r = await klien.post(f"{PREFIX}/pengguna/{aku.id}/status")
    assert "tidak bisa menonaktifkan akun sendiri" in r.text


# ─────────────── Daftar supplier: yang sering datang di atas ───────────────

async def test_supplier_sering_datang_didahulukan(klien, app_uji):
    """Daftar dari Kledo memuat ratusan vendor; petugas hanya butuh belasan.

    Yang pernah dipakai belakangan harus muncul di kelompok atas, supaya
    petugas tidak menggulir ratusan nama sambil truk menunggu.
    """
    from app import database
    from app.models import Supplier

    async with database.SessionLocal() as db:
        db.add_all([Supplier(nama_supplier=f"Vendor Karung {i}") for i in range(5)])
        await db.commit()

    await login(klien)
    # H. Anton (id 1) dipakai pada transaksi ini.
    await _selesaikan(klien, "GABAH_BASAH")

    teks = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
    assert 'label="Sering datang"' in teks and 'label="Lainnya"' in teks
    sering = teks.split('label="Sering datang"')[1].split("</optgroup>")[0]
    assert "H. Anton" in sering
    assert "Vendor Karung 0" not in sering


async def test_supplier_belum_pernah_dipakai_tetap_bisa_dipilih(klien, app_uji):
    """Yang jarang datang tidak boleh hilang — hanya diturunkan urutannya."""
    from app import database
    from app.models import Supplier

    async with database.SessionLocal() as db:
        db.add(Supplier(nama_supplier="Pemasok Musiman"))
        await db.commit()

    await login(klien)
    teks = (await klien.get(f"{PREFIX}/timbang/GABAH_BASAH")).text
    assert "Pemasok Musiman" in teks
