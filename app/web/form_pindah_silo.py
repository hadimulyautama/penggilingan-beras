"""Pratinjau dryer → silo. Pembaca saja; penggabungan milik masuk_silo."""
from sqlalchemy import select
from app.models import DryingLot, Dryer, Jasa, SiloStorage
from app.penggilingan.gudang1.services import drying, silo as si
from app.penggilingan.gudang1.services.bobot import jumlah
from app.penggilingan.silo_policy import boleh_masuk
from app.services.jasa import cocok_pemilik, nama_pemilik
from app.services.proses_aktif import _waktu


async def ringkasan(db, *, kode_lot, silo=""):
    if not kode_lot.strip():
        raise si.SiloError("Pilih pengeringan dulu.")
    lot = await drying.get_lot_by_kode(db, kode_lot)
    if lot is None:
        raise si.SiloError("Pengeringan tidak ditemukan.")
    mesin = await db.get(Dryer, lot.dryer_id) if lot.dryer_id else None
    batches = await drying._lot_batches(db, lot.id)
    bobot = await si._lot_bobot(db, lot.id)
    simpan = (await db.scalars(select(SiloStorage).where(
        SiloStorage.drying_lot_id == lot.id, SiloStorage.status == "terisi"))).first()
    siap = lot.status == "selesai" and lot.waktu_selesai_pendinginan is not None and simpan is None
    status = "Sudah di silo" if simpan else "Sudah dingin" if siap else "Belum selesai pendinginan"
    pesanan = await db.get(Jasa, lot.jasa_id) if lot.jasa_id else None
    data = dict(kode_lot=lot.kode_lot, dryer=mesin.nama if mesin else "Dryer belum tercatat",
        pemilik=await nama_pemilik(db, lot.jasa_id) if lot.jasa_id else "Pabrik",
        kepemilikan="Titipan jasa" if lot.jasa_id else "Milik pabrik",
        pesanan=pesanan.kode if pesanan else None, jumlah_batch=len(batches),
        status=status, siap=siap, dingin=_waktu(lot.waktu_selesai_pendinginan),
        bobot=bobot.teks() if batches else "Bobot belum tersedia", keadaan_bobot=bobot.keadaan,
        detail=f"/riwayat-pengeringan/{lot.id}", tujuan=None, peringatan=[])
    if not silo.strip():
        return data
    tujuan = await si.get_g1_silo(db, silo)
    if tujuan is None:
        raise si.SiloError("Silo tujuan Gudang 1 tidak ditemukan atau tidak aktif.")
    rinci = await si.isi_silo(db, tujuan.id)
    isi = await si._silo_content_bobot(db, tujuan.id)
    giling = await si.giling_berjalan_untuk_silo(db, tujuan.id)
    pemilik = list(dict.fromkeys(x.pemilik or "Pabrik" for x in rinci))
    cocok = all([await cocok_pemilik(db, lot.jasa_id, x.jasa_id) for x in rinci])
    komoditas = boleh_masuk(tujuan, "gabah_kering", "g1")
    # Bobot sesudah memakai helper yang sama, termasuk kepastian dan pengurang
    # pemakaian giling/kemasan. Tak ada hitungan susut atau saldo frontend.
    sesudah = (jumlah([isi, bobot]) if rinci else bobot).teks() if batches else "Belum dapat dihitung"
    data['tujuan'] = dict(nama=tujuan.nama_silo, isi=isi.teks(),
        pemilik=" · ".join(pemilik) if rinci else "Belum ada isi",
        kegiatan=f"Digiling · {giling.kode_proses}" if giling else "Tidak sedang digiling",
        kapasitas=si._fmt_kg(si._silo_cap_kg(tujuan)) if si._silo_cap_kg(tujuan) is not None else "Belum tercatat",
        sesudah=(sesudah if cocok and komoditas else "Belum dapat digabung") if siap else "Pemindahan tidak tersedia", cocok=cocok and komoditas)
    if not komoditas:
        data['peringatan'].append("Silo ini tidak menerima gabah kering menurut filter komoditasnya.")
    if not cocok:
        data['peringatan'].append("Kepemilikan berbeda tidak boleh digabung. Pilih silo yang sesuai; server memeriksa isi terbaru saat menyimpan.")
    else:
        if rinci:
            data['peringatan'].append("Silo sudah berisi; seluruh lot akan digabung dengan isi yang tercatat.")
        if lot.jasa_id is None and any(x.asal == "beli_kering" for x in rinci):
            data['peringatan'].append("Hasil pengeringan pabrik akan bercampur dengan gabah yang dibeli kering.")
        if lot.jasa_id and any(x.jasa_id != lot.jasa_id for x in rinci):
            data['peringatan'].append("Pesanan berbeda milik pelanggan yang sama mengikuti penggabungan otomatis saat pemindahan disimpan.")
        if giling:
            data['peringatan'].append(f"Silo sedang digiling ({giling.kode_proses}). Lot masuk sebagai bahan tambahan; giling tetap berjalan.")
    return data
