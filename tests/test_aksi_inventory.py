"""Uji aksi inventory di layar: kemasan, barang jadi, barang keluar (Fase B3).

Layanannya sudah lama diuji lewat jalur bot. Yang baru — dan yang bisa rusak
diam-diam — adalah lapisan yang menerjemahkan aturan pabrik menjadi pilihan di
layar. Tiga hal dijaga di sini:

  · daftar kemasan di layar DITURUNKAN dari aturan, bukan disalin. Salinan akan
    berumur panjang dan menyimpang tanpa ada yang tahu;
  · isian yang datang dari perangkat tetap diperiksa, meski daftar pilihannya
    tadi berasal dari server;
  · tiap aksi punya gudang yang ditetapkan eksplisit — yang terlupa akan
    muncul di tab yang salah tanpa pesan kesalahan apa pun.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.penggilingan.inventory import packaging as kms
from app.web import aksi_inventory as inv
from app.web import miniapp


# ─────────────────────── Kombinasi kemasan ───────────────────────

def test_kombinasi_diturunkan_dari_aturan_bukan_disalin():
    """Setiap kombinasi yang ditawarkan harus lolos validasi aturan itu sendiri.

    Bila suatu hari `KEMASAN_VALID` berubah, uji ini ikut berubah artinya —
    itulah gunanya: daftar di layar tidak boleh punya kebenarannya sendiri.
    """
    semua = inv.kombinasi_kemasan()
    assert semua, "daftar kemasan tidak boleh kosong"
    for kategori, material, ukuran in semua:
        kms._validate_kemasan(kategori, material, ukuran)   # tak boleh melempar


def test_beras_menawarkan_seluruh_ukuran_yang_sah():
    """Aturan beras menulis ukuran sebagai None = 'semua ukuran beras'.

    Menerjemahkan None jadi satu baris tanpa ukuran akan membuat operator
    tidak bisa memilih 5 kg sama sekali.
    """
    ukuran = {u for k, _, u in inv.kombinasi_kemasan() if k == "beras_putih"}
    assert ukuran == kms._BERAS_SIZES


def test_kombinasi_mustahil_tidak_pernah_ditawarkan():
    """Broken hanya boleh karung putih 50 kg atau polos 25 kg — bukan campurannya."""
    broken = {(m, u) for k, m, u in inv.kombinasi_kemasan() if k == "broken"}
    assert broken == {("putih", 50), ("polos", 25)}
    assert ("putih", 25) not in broken


def test_penyaringan_kategori_tidak_mengubah_isinya():
    for kategori in kms.KEMASAN_VALID:
        saring = inv.kombinasi_kemasan(kategori)
        assert saring == [t for t in inv.kombinasi_kemasan() if t[0] == kategori]


# ─────────────────────── Isian dari perangkat ───────────────────────

def test_pilihan_kemasan_yang_sah_terurai_utuh():
    assert inv._urai_triple("beras_putih|laminasi|25") == ("beras_putih", "laminasi", 25)


@pytest.mark.parametrize("nilai", [
    "", "beras_putih", "beras_putih|laminasi", "beras_putih|laminasi|25|extra",
    "beras_putih|laminasi|duapuluhlima",
])
def test_pilihan_berbentuk_aneh_ditolak_dengan_pesan_yang_bisa_dibaca(nilai):
    with pytest.raises(HTTPException) as e:
        inv._urai_triple(nilai)
    assert e.value.status_code == 400
    assert "kemasan" in str(e.value.detail).lower()


def test_kombinasi_mustahil_tetap_ditolak_walau_bentuknya_benar():
    """Daftar pilihan memang datang dari server — tetapi yang mengirim POST
    adalah perangkat, dan itu bukan alasan melewatkan pemeriksaan."""
    with pytest.raises(HTTPException) as e:
        inv._urai_triple("menir|laminasi|10")
    assert e.value.status_code == 400


# ─────────────────────── Menu per peran ───────────────────────

def test_operator_gudang2_tak_pernah_melihat_aksi_uang():
    ids = {a["id"] for a in inv.spesifikasi(g2=True, fin=False)}
    assert ids == {"catat_packing", "catat_bekatul"}
    for terlarang in ("beli_kemasan", "kirim_barang_jadi", "jual_pk", "harga_byproduct"):
        assert terlarang not in ids


def test_yang_tak_berperan_apa_pun_tak_mendapat_aksi():
    assert inv.spesifikasi(g2=False, fin=False) == []


def test_staff_mendapat_pembelian_dan_pengiriman():
    ids = {a["id"] for a in inv.spesifikasi(g2=False, fin=True)}
    assert {"beli_kemasan", "kirim_barang_jadi", "kirim_bekatul",
            "jual_pk", "harga_byproduct"} <= ids


# ─────────────────────── Bentuk spesifikasi ───────────────────────

def _semua_aksi():
    return inv.spesifikasi(g2=True, fin=True)


def test_tiap_aksi_punya_gudang_yang_ditetapkan_eksplisit():
    """Aksi tanpa entri gudang jatuh ke 'g1' diam-diam — muncul di tab yang
    salah, tanpa kesalahan apa pun yang bisa dilihat siapa pun."""
    for a in _semua_aksi():
        assert a["id"] in miniapp._ACTION_WH, f"{a['id']} belum dipetakan ke gudang"


def test_tiap_aksi_menunjuk_alamat_kirim_dan_punya_isian():
    for a in _semua_aksi():
        assert a["post"].startswith("/miniapp/actions/")
        assert a["fields"], f"{a['id']} tanpa isian"
        for f in a["fields"]:
            assert f["type"] in ("text", "number", "select", "remote")
            if f["type"] == "remote":
                assert f["source"].startswith("/miniapp/actions/")


def test_pilihan_yang_hanya_berlaku_sebagian_ditandai_boleh_kosong():
    """Merk hanya milik beras, mutu hanya milik beras putih. Memaksanya wajib
    membuat orang mengarang jawaban untuk bekatul dan menir."""
    for a in _semua_aksi():
        for f in a["fields"]:
            if f["name"] in ("merk", "grade"):
                assert f.get("optional"), f"{a['id']}.{f['name']} harus boleh kosong"


def test_alamat_kirim_tiap_aksi_benar_benar_ada_di_router():
    terdaftar = {r.path for r in inv.router.routes}
    for a in _semua_aksi():
        assert a["post"] in terdaftar, f"{a['id']} menunjuk alamat yang tidak ada"
        for f in a["fields"]:
            if f["type"] == "remote":
                assert f["source"] in terdaftar, f"{f['source']} tidak ada"


def test_tak_ada_batas_batch_per_hari():
    """Pemilik: "tidak ada batas berapa batch per hari."

    Dulu ada — tiga — dan ia menolak dengan melemparkan ANGKA-nya saja, jadi
    operator truk keempat berhenti bekerja di depan lembar galat bertuliskan
    "3". Berapa truk yang datang hari itu ditentukan panen, bukan aplikasi.
    """
    import inspect

    from app import config
    from app.penggilingan.gudang1.services import purchase

    assert not hasattr(purchase, "DailyLimitReached")
    assert not hasattr(config.settings, "max_purchase_batch_per_day")
    sumber = inspect.getsource(purchase)
    assert "max_purchase_batch_per_day" not in sumber
    # `count_batches_on` tetap ada — ia dipakai penomoran kode batch harian,
    # dan itu memang harus menghitung per hari.
    assert hasattr(purchase, "count_batches_on")


def test_galat_menolak_argumen_yang_bukan_kalimat():
    """Penjaga umum, supaya kesalahan berikutnya yang membawa angka tak
    mengulangi hal yang sama."""
    from app.web.aksi_umum import galat

    assert galat(ValueError(7), "Gagal mencatat gabah.").detail == "Gagal mencatat gabah."
    assert galat(ValueError(""), "bawaan").detail == "bawaan"
    assert galat(ValueError("Silo penuh."), "bawaan").detail == "Silo penuh."
