"""Uji lapisan layanan: alur timbang dua tahap, idempotensi, koreksi, audit.

Yang dijaga di sini adalah janji-janji operasional modul, bukan rumusnya
(rumus diuji di `test_logic.py`):

  · timbang pertama membuka tiket, timbang kedua menutup dan menilai
  · kiriman ulang dari antrean offline tidak melahirkan transaksi kembar
  · arah barang menentukan mana angka bermuatan dan mana angka kosong
  · tanggal mengikuti timbang kedua
  · petugas timbang pertama & kedua keduanya tercatat
  · data tidak pernah hilang: batal & tutup paksa meninggalkan jejak
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.timbangan import logic, service
from app.timbangan.models import (
    CARA_SEKALI,
    PEMERIKSAAN_DIBUKA,
    PEMERIKSAAN_SELESAI,
    TIKET_DITUTUP_PAKSA,
    TIKET_SELESAI,
    TIKET_TERBUKA,
    TRX_VOID,
    TimbanganAudit,
    TimbanganJenis,
    TimbanganPemeriksaan,
    TimbanganTransaksi,
)
from app.timbangan.service import InputMuatan, InputTimbang

pytestmark = pytest.mark.usefixtures("jenis_tersemai")


def masuk_gabah(kode: str, supplier_id: int | None, berat: float) -> InputTimbang:
    return InputTimbang(
        kode=kode,
        arah=logic.MASUK,
        jenis_kode="GABAH_BASAH",
        berat_kg=berat,
        supplier_id=supplier_id,
        nomor_polisi=" ad 1234 xy ",
        muatan=[InputMuatan(
            jenis_kode="GABAH_BASAH", jumlah_karung=120,
            tara_per_karung_kg=0.25, berat_acuan_kg=10_048,
            nomor_acuan="NOTA-01",
        )],
        perangkat_kode="P1",
    )


# ─────────────────── Penyemaian master ───────────────────

async def test_penyemaian_tidak_menimpa_aturan_yang_sudah_disetel(db):
    """Aturan yang sudah diubah manajemen di DB tidak boleh dikembalikan."""
    baris = (await db.execute(
        select(TimbanganJenis).where(TimbanganJenis.kode == "GABAH_BASAH")
    )).scalars().one()
    baris.ambang_nilai = 3.0
    await db.commit()

    assert await service.pastikan_jenis(db) == 0
    aturan = await service.aturan_untuk(db, "GABAH_BASAH")
    assert aturan.ambang_nilai == 3.0


async def test_aturan_dibaca_dari_db_bukan_dari_kode(db):
    peta = await service.peta_aturan(db)
    assert set(peta) == {a.kode for a in logic.JENIS_AWAL}


# ─────────────────── Alur dua tahap ───────────────────

async def test_timbang_pertama_membuka_tiket(db, petugas, supplier):
    trx = await service.simpan_timbang_pertama(
        db, akun=petugas, data=masuk_gabah("TRX-20260830-P1-001", supplier.id, 13_600)
    )
    assert trx.status_tiket == TIKET_TERBUKA
    assert trx.timbang1_petugas_id == petugas.id
    assert trx.timbang2_kg is None
    assert trx.status_kontrol is None        # belum dinilai — belum lengkap
    assert trx.nomor_polisi == "AD 1234 XY"  # dinormalkan
    assert len(trx.muatan) == 1

    terbuka = await service.tiket_terbuka(db)
    assert [b.trx.kode for b in terbuka] == ["TRX-20260830-P1-001"]


async def test_timbang_kedua_menutup_dan_menilai(db, petugas, petugas2, supplier):
    """Contoh Anton: netto kontrol 10.000 vs nota 10.048 → perlu pemeriksaan."""
    await service.simpan_timbang_pertama(
        db, akun=petugas, data=masuk_gabah("TRX-20260830-P1-002", supplier.id, 13_600)
    )
    trx = await service.simpan_timbang_kedua(
        db, akun=petugas2, kode="TRX-20260830-P1-002", berat_kg=3_570
    )

    assert trx.status_tiket == TIKET_SELESAI
    assert trx.berat_bermuatan_kg == 13_600      # masuk: datang penuh
    assert trx.berat_kosong_kg == 3_570
    assert trx.netto_timbangan_kg == 10_030
    assert trx.berat_barang_kg == 10_000
    assert trx.selisih_kg == -48
    assert trx.status_kontrol == logic.PERLU_PEMERIKSAAN
    # Dua orang berbeda, keduanya tercatat; yang tertera di bukti yang kedua.
    assert trx.timbang1_petugas_id == petugas.id
    assert trx.timbang2_petugas_id == petugas2.id
    assert trx.petugas_bukti_id == petugas2.id


async def test_arah_keluar_membalik_urutan_angka(db, petugas, supplier):
    """Pengiriman: truk datang kosong, pergi bermuatan."""
    data = InputTimbang(
        kode="TRX-20260830-P1-003",
        arah=logic.KELUAR,
        jenis_kode="BEKATUL",
        berat_kg=6_200,                       # timbang pertama = KOSONG
        supplier_id=supplier.id,
        nomor_polisi="AD 9 ZZ",
        muatan=[InputMuatan(
            jenis_kode="BEKATUL", jumlah_karung=240,
            tara_per_karung_kg=0.05, berat_acuan_kg=12_000,
            nomor_acuan="SJ-77",
        )],
    )
    await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    trx = await service.simpan_timbang_kedua(
        db, akun=petugas, kode=data.kode, berat_kg=18_220
    )

    assert trx.berat_kosong_kg == 6_200
    assert trx.berat_bermuatan_kg == 18_220
    assert trx.netto_timbangan_kg == 12_020
    assert trx.berat_barang_kg == 12_008
    assert trx.status_kontrol == logic.NORMAL
    assert trx.batas_bawah_kg == 0            # kiriman tidak boleh kurang


async def test_pengiriman_kurang_dari_surat_jalan_ditandai(db, petugas, supplier):
    data = InputTimbang(
        kode="TRX-20260830-P1-004", arah=logic.KELUAR, jenis_kode="BEKATUL",
        berat_kg=6_200, supplier_id=supplier.id,
        muatan=[InputMuatan(
            jenis_kode="BEKATUL", jumlah_karung=240,
            tara_per_karung_kg=0.05, berat_acuan_kg=12_000,
        )],
    )
    await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    trx = await service.simpan_timbang_kedua(
        db, akun=petugas, kode=data.kode, berat_kg=18_200
    )
    assert trx.status_kontrol == logic.KURANG


async def test_tanggal_mengikuti_timbang_kedua(db, petugas, supplier):
    """Truk masuk menjelang tengah malam tercatat di hari ia selesai."""
    data = masuk_gabah("TRX-20260830-P1-005", supplier.id, 13_600)
    data.waktu_operator = datetime(2026, 8, 30, 23, 40)
    await service.simpan_timbang_pertama(db, akun=petugas, data=data)

    trx = await service.simpan_timbang_kedua(
        db, akun=petugas, kode=data.kode, berat_kg=3_570,
        waktu_operator=datetime(2026, 8, 31, 1, 15),
    )
    assert trx.tanggal.isoformat() == "2026-08-31"


async def test_jasa_timbang_sekali_langsung_selesai(db, petugas):
    trx = await service.simpan_timbang_pertama(db, akun=petugas, data=InputTimbang(
        kode="TRX-20260830-P1-006", arah=logic.BEBAS, jenis_kode="BEBAS",
        berat_kg=12_850, cara_timbang=CARA_SEKALI,
        pihak_nama="CV Sumber Rejeki",
    ))
    assert trx.status_tiket == TIKET_SELESAI
    assert trx.netto_timbangan_kg == 12_850
    assert trx.status_kontrol == logic.TANPA_KONTROL
    assert trx.berat_kosong_kg is None


# ─────────────────── Ketahanan offline ───────────────────

async def test_kiriman_ulang_tidak_melahirkan_transaksi_kembar(db, petugas, supplier):
    """Antrean offline boleh mengirim ulang berkali-kali tanpa akibat."""
    data = masuk_gabah("TRX-20260830-P1-007", supplier.id, 13_600)
    for _ in range(3):
        await service.simpan_timbang_pertama(db, akun=petugas, data=data)

    jumlah = (await db.execute(
        select(func.count(TimbanganTransaksi.id))
    )).scalar_one()
    assert jumlah == 1
    # Muatan juga tidak menumpuk.
    trx = await service.ambil_kode(db, data.kode)
    assert len(trx.muatan) == 1


async def test_kiriman_ulang_tidak_memundurkan_transaksi_yang_sudah_selesai(
    db, petugas, supplier
):
    data = masuk_gabah("TRX-20260830-P1-008", supplier.id, 13_600)
    await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    await service.simpan_timbang_kedua(
        db, akun=petugas, kode=data.kode, berat_kg=3_570
    )

    trx = await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    assert trx.status_tiket == TIKET_SELESAI
    assert trx.timbang2_kg == 3_570


async def test_timbang_kedua_berulang_diabaikan(db, petugas, supplier):
    data = masuk_gabah("TRX-20260830-P1-009", supplier.id, 13_600)
    await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    await service.simpan_timbang_kedua(db, akun=petugas, kode=data.kode, berat_kg=3_570)
    trx = await service.simpan_timbang_kedua(
        db, akun=petugas, kode=data.kode, berat_kg=9_999
    )
    assert trx.timbang2_kg == 3_570


# ─────────────────── Pemeriksaan ───────────────────

async def test_status_wajib_periksa_membuka_lembar_pemeriksaan(
    db, petugas, supplier
):
    data = masuk_gabah("TRX-20260830-P1-010", supplier.id, 13_600)
    await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    trx = await service.simpan_timbang_kedua(
        db, akun=petugas, kode=data.kode, berat_kg=3_570
    )
    lembar = await service.pemeriksaan_transaksi(db, trx.id)
    assert lembar is not None and lembar.status == PEMERIKSAAN_DIBUKA


async def test_pemeriksaan_selesai_dengan_catatan_resolusi(
    db, petugas, pengawas, supplier
):
    """Selesai berarti sudah ditelusuri dan tercatat — bukan berarti bersih."""
    data = masuk_gabah("TRX-20260830-P1-011", supplier.id, 13_600)
    await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    trx = await service.simpan_timbang_kedua(
        db, akun=petugas, kode=data.kode, berat_kg=3_570
    )
    lembar = await service.pemeriksaan_transaksi(db, trx.id)

    selesai = await service.selesaikan_pemeriksaan(
        db, akun=pengawas, lembar=lembar,
        langkah={"langkah_ulang_timbang": "Ditimbang ulang, angka sama."},
        kategori_hasil="SUSUT_PERJALANAN",
        catatan_resolusi="Hujan di perjalanan, karung basah lalu menyusut.",
        dilaporkan_ke="Miftah",
    )
    assert selesai.status == PEMERIKSAAN_SELESAI
    assert selesai.ditutup_oleh_id == pengawas.id


async def test_petugas_tidak_boleh_menutup_pemeriksaan(db, petugas, supplier):
    data = masuk_gabah("TRX-20260830-P1-012", supplier.id, 13_600)
    await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    trx = await service.simpan_timbang_kedua(
        db, akun=petugas, kode=data.kode, berat_kg=3_570
    )
    lembar = await service.pemeriksaan_transaksi(db, trx.id)
    with pytest.raises(service.LayananError, match="Pengawas"):
        await service.selesaikan_pemeriksaan(
            db, akun=petugas, lembar=lembar, langkah={},
            kategori_hasil="SELISIH_WAJAR", catatan_resolusi="aman",
        )


async def test_resolusi_wajib_beralasan(db, petugas, pengawas, supplier):
    data = masuk_gabah("TRX-20260830-P1-013", supplier.id, 13_600)
    await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    trx = await service.simpan_timbang_kedua(
        db, akun=petugas, kode=data.kode, berat_kg=3_570
    )
    lembar = await service.pemeriksaan_transaksi(db, trx.id)
    with pytest.raises(service.LayananError, match="resolusi"):
        await service.selesaikan_pemeriksaan(
            db, akun=pengawas, lembar=lembar, langkah={},
            kategori_hasil="SELISIH_WAJAR", catatan_resolusi="   ",
        )


# ─────────────────── Koreksi, batal, tutup paksa ───────────────────

async def test_koreksi_menghitung_ulang_dan_meninggalkan_jejak(
    db, petugas, supplier
):
    data = masuk_gabah("TRX-20260830-P1-014", supplier.id, 13_600)
    await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    trx = await service.simpan_timbang_kedua(
        db, akun=petugas, kode=data.kode, berat_kg=3_570
    )
    assert trx.status_kontrol == logic.PERLU_PEMERIKSAAN

    # Salah ketik: nota sebenarnya 10.010, bukan 10.048.
    trx = await service.koreksi_transaksi(
        db, akun=petugas, trx=trx,
        perubahan={},
        muatan=[InputMuatan(
            jenis_kode="GABAH_BASAH", jumlah_karung=120,
            tara_per_karung_kg=0.25, berat_acuan_kg=10_010,
            nomor_acuan="NOTA-01",
        )],
        alasan="Salah ketik berat nota",
    )
    assert trx.selisih_kg == -10
    assert trx.status_kontrol == logic.NORMAL
    assert trx.jumlah_revisi == 1

    jejak = (await db.execute(
        select(TimbanganAudit).where(TimbanganAudit.aksi == "KOREKSI")
    )).scalars().all()
    assert len(jejak) == 1
    assert "10048" in jejak[0].nilai_sebelum.replace(".0", "")


async def test_void_menyimpan_data_dan_menuntut_alasan(db, petugas, pengawas, supplier):
    data = masuk_gabah("TRX-20260830-P1-015", supplier.id, 13_600)
    trx = await service.simpan_timbang_pertama(db, akun=petugas, data=data)

    with pytest.raises(service.LayananError, match="Pengawas"):
        await service.void_transaksi(db, akun=petugas, trx=trx, alasan="salah")
    with pytest.raises(service.LayananError, match="alasan"):
        await service.void_transaksi(db, akun=pengawas, trx=trx, alasan="  ")

    trx = await service.void_transaksi(
        db, akun=pengawas, trx=trx, alasan="Truk salah masuk antrean"
    )
    assert trx.status_transaksi == TRX_VOID
    # Barisnya tetap ada — tidak pernah dihapus permanen.
    assert (await db.execute(select(func.count(TimbanganTransaksi.id)))).scalar_one() == 1


async def test_tutup_paksa_tiket_yang_tidak_jadi_bongkar(db, petugas, supplier):
    data = masuk_gabah("TRX-20260830-P1-016", supplier.id, 13_600)
    trx = await service.simpan_timbang_pertama(db, akun=petugas, data=data)

    trx = await service.tutup_paksa(
        db, akun=petugas, trx=trx, alasan="Truk batal bongkar, mutu ditolak"
    )
    assert trx.status_tiket == TIKET_DITUTUP_PAKSA
    assert trx.status_kontrol is None
    assert not await service.tiket_terbuka(db)

    with pytest.raises(service.LayananError, match="terbuka"):
        await service.tutup_paksa(db, akun=petugas, trx=trx, alasan="lagi")


async def test_timbang_kedua_ditolak_setelah_tutup_paksa(db, petugas, supplier):
    data = masuk_gabah("TRX-20260830-P1-017", supplier.id, 13_600)
    trx = await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    await service.tutup_paksa(db, akun=petugas, trx=trx, alasan="batal")
    with pytest.raises(service.LayananError, match="ditutup paksa"):
        await service.simpan_timbang_kedua(
            db, akun=petugas, kode=data.kode, berat_kg=3_570
        )


# ─────────────────── Tara standar ───────────────────

async def test_sampling_baru_mengganti_bukan_menimpa(db, pengawas, supplier):
    pertama = await service.simpan_tara_standar(
        db, akun=pengawas, supplier_id=supplier.id, jenis_kode="BERAS_PK",
        jumlah_sampel=20, total_berat_kg=1.8,
    )
    assert pertama.tara_per_karung_kg == pytest.approx(0.09)

    kedua = await service.simpan_tara_standar(
        db, akun=pengawas, supplier_id=supplier.id, jenis_kode="BERAS_PK",
        jumlah_sampel=20, total_berat_kg=2.0, alasan="Ganti jenis karung",
    )
    await db.refresh(pertama)
    assert pertama.status == "DIGANTI"
    assert kedua.status == "BERLAKU"

    berlaku = await service.tara_berlaku(
        db, supplier_id=supplier.id, jenis_kode="BERAS_PK"
    )
    assert berlaku.id == kedua.id


async def test_tara_khusus_pihak_menang_atas_tara_umum(db, pengawas, supplier):
    await service.simpan_tara_standar(
        db, akun=pengawas, supplier_id=None, jenis_kode="BERAS_PK",
        jumlah_sampel=20, total_berat_kg=2.0,          # umum → 0,10
    )
    await service.simpan_tara_standar(
        db, akun=pengawas, supplier_id=supplier.id, jenis_kode="BERAS_PK",
        jumlah_sampel=20, total_berat_kg=1.7,          # khusus → 0,085
    )
    aturan = await service.aturan_untuk(db, "BERAS_PK")
    tara, asal = await service.tara_disarankan(
        db, supplier_id=supplier.id, aturan=aturan
    )
    assert tara == pytest.approx(0.085)
    assert asal is not None and asal.supplier_id == supplier.id


async def test_tara_bawaan_dipakai_bila_belum_ada_sampling(db, supplier):
    aturan = await service.aturan_untuk(db, "BERAS_PK")
    tara, asal = await service.tara_disarankan(
        db, supplier_id=supplier.id, aturan=aturan
    )
    assert tara == aturan.tara_default()
    assert asal is None


# ─────────────────── Cetak ───────────────────

async def test_cetak_ulang_wajib_beralasan(db, petugas, supplier):
    data = masuk_gabah("TRX-20260830-P1-018", supplier.id, 13_600)
    trx = await service.simpan_timbang_pertama(db, akun=petugas, data=data)

    pertama = await service.catat_cetak(db, akun=petugas, trx=trx)
    assert pertama.urutan == 1 and not pertama.ulang

    with pytest.raises(service.LayananError, match="alasan"):
        await service.catat_cetak(db, akun=petugas, trx=trx)

    kedua = await service.catat_cetak(
        db, akun=petugas, trx=trx, alasan="Kertas tersangkut"
    )
    assert kedua.urutan == 2 and kedua.ulang


# ─────────────────── Ringkasan ───────────────────

async def test_ringkasan_menghitung_tiket_dan_pemeriksaan(db, petugas, supplier):
    selesai = masuk_gabah("TRX-20260830-P1-019", supplier.id, 13_600)
    await service.simpan_timbang_pertama(db, akun=petugas, data=selesai)
    await service.simpan_timbang_kedua(
        db, akun=petugas, kode=selesai.kode, berat_kg=3_570
    )
    await service.simpan_timbang_pertama(
        db, akun=petugas,
        data=masuk_gabah("TRX-20260830-P1-020", supplier.id, 12_000),
    )

    r = await service.ringkasan_dashboard(db, service.FilterTransaksi())
    assert r.jumlah == 2
    assert r.tiket_terbuka == 1
    assert r.perlu_periksa == 1
    assert r.pemeriksaan_terbuka == 1


async def test_transaksi_void_tidak_ikut_terhitung(db, petugas, pengawas, supplier):
    data = masuk_gabah("TRX-20260830-P1-021", supplier.id, 13_600)
    trx = await service.simpan_timbang_pertama(db, akun=petugas, data=data)
    await service.void_transaksi(db, akun=pengawas, trx=trx, alasan="salah antrean")

    assert await service.hitung_transaksi(db, service.FilterTransaksi()) == 0
    assert await service.hitung_transaksi(
        db, service.FilterTransaksi(sertakan_void=True)
    ) == 1
