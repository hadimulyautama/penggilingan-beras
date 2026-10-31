"""Pengurai sumber bersama untuk formulir lama dan koreksi pascaverifikasi."""
from dataclasses import replace
from sqlalchemy import select
from app.services import barang_keluar as bk

async def urai(db, pilih: str, jumlah) -> "bk.BarisPerintah":
    """Satu pilihan berawalan + jumlahnya → baris perintah.

    Awalannya yang menentukan SATUAN: `bj:` per karung, `cr:`, `pk:`, dan
    `g2:` per kilogram. Tanpa awalan, "100" pada satu baris berarti 100
    karung dan pada baris lain 100 kg — dan yang membedakan cuma ingatan
    orang yang mengetiknya.

    Akhiran `@<jasa_id>` (dari `_barang_jasa_pelanggan_rows`, keputusan
    pemilik 11 Oktober 2026: pengambilan jasa kini per PELANGGAN, bisa
    menggabung beberapa pesanan aktifnya sekaligus) dibongkar DULUAN,
    sebelum awalan tipe barang diperiksa — nilainya menumpuk di BELAKANG
    ("g2:tumpukan@42"), jadi membongkarnya lebih dulu tak mengganggu
    pengurai lain yang sudah ada. `jasa_id` hasilnya ditempel ke
    `BarisPerintah` APA PUN tipenya — `buat_perintah` yang baru
    memvalidasinya milik pelanggan yang sama.
    """
    from app.models import MillingProcess

    pilih = (pilih or "").strip()
    jasa_asal: int | None = None
    depan, _, akhiran = pilih.rpartition("@")
    if depan and akhiran.isdigit():
        pilih, jasa_asal = depan, int(akhiran)
    from math import isfinite
    if not isfinite(float(jumlah or 0)) or float(jumlah or 0) <= 0:
        raise bk.BarangKeluarError(f"Isi jumlah untuk '{pilih}' lebih dari 0.")
    if pilih.startswith("cr:"):
        # Curah DIKETIK DALAM KG. Jumlahnya tak pernah diturunkan dari karung
        # sebab ia memang tak berkarung; `tersedia()` yang menjaga batasnya,
        # dan penolakannya menyebut angkanya.
        b = bk.BarisPerintah(tipe="byproduct_curah", jenis=pilih[3:].strip(),
                             berat_kg=float(jumlah))
    elif pilih.startswith("pk:"):
        kode = pilih[3:].strip()
        proc = (await db.execute(select(MillingProcess).where(
            MillingProcess.kode_proses == kode))).scalars().first()
        if proc is None:
            raise bk.BarangKeluarError(f"Lot {kode} tidak ditemukan.")
        b = bk.BarisPerintah(tipe="pk_langsung", milling_process_id=proc.id,
                             berat_kg=float(jumlah))
    elif pilih.startswith("gk:"):
        from app.models import GabahKeringLot
        kode = pilih[3:].strip()
        lot = (await db.execute(select(GabahKeringLot).where(
            GabahKeringLot.kode_lot == kode))).scalars().first()
        if lot is None:
            raise bk.BarangKeluarError(f"Gabah kering {kode} tidak ditemukan.")
        b = bk.BarisPerintah(tipe="gabah_langsung", gabah_kering_lot_id=lot.id,
                             berat_kg=float(jumlah))
    elif pilih.startswith("g2:"):
        if pilih != "g2:tumpukan":
            raise bk.BarangKeluarError("PK di silo adalah bahan proses, bukan stok yang bisa diambil.")
        b = bk.BarisPerintah(tipe="pk_g2", silo_id=None, berat_kg=float(jumlah))
    else:
        nilai = pilih[3:] if pilih.startswith("bj:") else pilih
        bagian = nilai.split("|")
        if not bagian or not bagian[0].isdigit():
            raise bk.BarangKeluarError("Pilih barangnya dulu.")
        std = int(bagian[1]) if len(bagian) > 1 and bagian[1].isdigit() else None
        if not float(jumlah).is_integer():
            raise bk.BarangKeluarError("Jumlah karung wajib bilangan bulat.")
        b = bk.BarisPerintah(tipe="finished_goods", sku_id=int(bagian[0]),
                             std_id=std, jumlah_karung=int(jumlah))
    return replace(b, jasa_id=jasa_asal) if jasa_asal is not None else b
