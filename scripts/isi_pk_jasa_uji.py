"""Contoh PK jasa yang masih tersisa di kedua gudang, khusus MODE_UJI.

Tidak mereset data. Memakai silo contoh tersendiri dan layanan aplikasi yang
sama. Checkpoint terpisah membuat pengulangan tidak menggandakan lot atau QC.
Jalankan dengan --terapkan untuk mengisi; tanpa itu hanya membaca inventaris.
"""
import argparse
import asyncio
import json

from sqlalchemy import select, text
from app.config import settings
from app.database import SessionLocal, engine
from app.models import SetelanPabrik, Silo, User, Warehouse
from app.services import stok, transfer
from app.penggilingan.gudang1.services import milling, silo
from hmu_identitas.peran import super_saja
from scripts import isi_tampilan_uji as seed

KUNCI = "uji_pk_jasa_detail_20261018_v1"
SILO = "Silo UJI-PK-JASA"


class PengisiPkJasa(seed.Pengisi):
    async def simpan(self):
        # Checkpoint dasar tetap utuh; tambahan ini memiliki penandanya sendiri.
        async with SessionLocal() as db:
            rec = await db.get(SetelanPabrik, KUNCI)
            if rec is None:
                rec = SetelanPabrik(kunci=KUNCI,nilai="{}",diubah_oleh=self.pelaku_id)
                db.add(rec)
            rec.nilai = json.dumps(self.state,ensure_ascii=False)
            await db.commit()


async def jalankan(terapkan=False):
    if not settings.mode_uji:
        raise ValueError("Contoh ini hanya dapat diisi saat MODE_UJI aktif.")
    async with engine.connect() as lock:
        if not await lock.scalar(text("SELECT pg_try_advisory_lock(20261017, 17858)")):
            raise ValueError("Pengisian data contoh lain sedang berjalan.")
        try:
            async with SessionLocal() as db:
                dasar = await db.get(SetelanPabrik, "uji_tampilan_20261017_v1")
                if not dasar:
                    raise ValueError("Data uji tampilan dasar belum tersedia.")
                master = json.loads(dasar.nilai)["master"]
                actor = next(u for u in (await db.scalars(select(User).where(
                    User.status == "aktif").order_by(User.id))).all() if super_saja(u.role))
                saved = await db.get(SetelanPabrik, KUNCI)
                state = json.loads(saved.nilai) if saved else {
                    "langkah": {}, "master": master, "penanda": seed.AWALAN}
                if terapkan:
                    g1 = await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi == "g1"))
                    tempat = await db.scalar(select(Silo).where(
                        Silo.warehouse_id == g1.id, Silo.nama_silo == SILO))
                    if tempat is None:
                        db.add(Silo(nama_silo=SILO, warehouse_id=g1.id, status="kosong"))
                        await db.commit()
            if terapkan:
                # Pengisi menyimpan setiap langkah ke checkpoint khusus ini.
                p = PengisiPkJasa(actor.id, state)
                batch = await p.gabah("pk-jasa-detail", kg=12000, jasa_barang=True, qc=2)
                await p.langkah("pk-jasa-detail:silo", silo.masuk_silo,
                                nama_silo="UJI-PK-JASA", kode_lot=None, kode_batch=batch["kode_batch"])
                r = await p.langkah("pk-jasa-detail:giling", milling.start_milling,
                                    nama_silo="UJI-PK-JASA")
                kode = r["proc"]["kode_proses"]
                for i, (ka, broken, susut, kuning, gabah, merang) in enumerate([
                    (14.4,28,14,"sedikit","bersih","bersih"),
                    (13.8,22,13,"sedang","sedikit","sedikit"),
                    (13.2,18,12,"banyak","sedikit","parah"),
                ], 1):
                    await p.langkah(f"pk-jasa-detail:hasil:{i}", milling.log_progress,
                                    kode_proses=kode, berat_kumulatif=2880*i)
                    await p.langkah(f"pk-jasa-detail:qc-giling:{i}", milling.log_qc_milling,
                        kode_proses=kode, kadar_air=ka, broken=broken, susut=susut, kondisi=None,
                        butir_kuning=kuning, gabah=gabah, merang=merang,
                        catatan_lab=seed.AWALAN+f"PK jasa · pemeriksaan {i} dari 3")
                await p.langkah("pk-jasa-detail:silo-diperiksa", milling.tutup_silo_giling,
                                kode_proses=kode, nama_silo="UJI-PK-JASA", sisa_kg=0)
                await p.langkah("pk-jasa-detail:selesai", milling.finish_milling,
                                kode_proses=kode, berat_akhir=8640)
                await p.langkah("pk-jasa-detail:verifikasi", milling.verify_milling_output,
                                kode_proses=kode, berat_output=8640)
                await p.langkah("pk-jasa-detail:transfer", transfer.create_internal_transfer,
                                kode_proses=kode, lokasi_tujuan="ditumpuk", berat=3500)
            hasil = {"mode_uji":True,"diisi":terapkan,"g1":[],"g2":[]}
            async with SessionLocal() as db:
                for gudang, fn in [("g1",stok.pk_gudang1),("g2",stok.pk_gudang2)]:
                    for k in await fn(db):
                        if k.jasa_id is None:
                            continue
                        href = (f"/stok/pk/detail?gudang=g1&jasa=1&kode={k.kode}" if gudang=="g1" else
                                f"/stok/pk/detail?gudang=g2&jasa=1&id={k.intake_id}")
                        hasil[gudang].append(dict(kode=k.kode,kg=k.tersedia,pemilik=k.pemilik,
                            nilai=k.nilai_kualitas,kelas=k.kelas_kualitas,detail=href))
            return hasil
        finally:
            await lock.execute(text("SELECT pg_advisory_unlock(20261017, 17858)"))


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--terapkan",action="store_true")
    print(json.dumps(asyncio.run(jalankan(parser.parse_args().terapkan)),ensure_ascii=False))
