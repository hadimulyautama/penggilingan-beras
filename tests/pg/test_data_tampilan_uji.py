"""Seluruh contoh harus sah menurut layanan dan aman bila dipanggil ulang."""
import json

import pytest
from sqlalchemy import select, text
from app.models import User, SetelanPabrik, OutgoingRecord, PermintaanPk, CustomerReturn
from app.config import settings
from app.services.seed import seed_master
from scripts import isi_tampilan_uji as contoh


@pytest.mark.asyncio
async def test_skenario_lengkap_dan_tidak_menghapus_data(pg, monkeypatch):
    monkeypatch.setattr(settings, 'mode_uji', True)
    monkeypatch.setattr(contoh, 'SessionLocal', pg)
    monkeypatch.setattr(contoh, 'engine', pg.kw['bind'])
    # Kontak sintetis memenuhi sumber Kledo yang diwajibkan formulir baru.
    master_asli = contoh.Pengisi.master
    async def master_kledo(self):
        data = await master_asli(self)
        from app.models import Pelanggan
        async with pg() as db:
            for p in (await db.scalars(select(Pelanggan).where(Pelanggan.id.in_(data['pelanggan'])))).all():
                p.kledo_contact_id = 1000000 + p.id
            await db.commit()
        return data
    monkeypatch.setattr(contoh.Pengisi, 'master', master_kledo)
    await seed_master()
    async with pg() as db:
        from hmu_identitas.peran import SUPERADMIN
        user=User(nama='Pemilik uji',role=SUPERADMIN,status='aktif')
        db.add(user)
        await db.execute(text('ALTER TABLE timbangan_transaksi ALTER COLUMN arah TYPE varchar(16)'))
        lama=await db.scalar(text("INSERT INTO timbangan_transaksi (kode,tanggal,arah,jenis_kode,timbang1_kg,status_tiket) VALUES ('DATA-SEBELUM-CONTOH',CURRENT_DATE,'MASUK','GABAH_KERING',15000,'TERBUKA') RETURNING id"))
        await db.commit()
    pratinjau=await contoh.jalankan(False)
    assert not pratinjau['langkah']
    async with pg() as db:
        assert await db.get(SetelanPabrik,contoh.KUNCI) is None
    hasil=await contoh.jalankan(True)
    assert hasil['selesai']
    async with pg() as db:
        from app.models import ProduksiAkun, Jasa
        db.add(ProduksiAkun(user_id=user.id,username='uji-tampilan',password_hash='tidak-dipakai-untuk-login',status='aktif',mode_perangkat='pribadi'))
        await db.commit()
        statuses=set((await db.scalars(select(OutgoingRecord.status))).all())
        assert {'perintah','dimuat','selesai','batal'} <= statuses
        assert {'diminta','disetujui','dikirim','selesai','ditolak','gugur'} <= set((await db.scalars(select(PermintaanPk.status))).all())
        assert len((await db.scalars(select(CustomerReturn))).all())==2
        assert await db.scalar(text('SELECT timbang1_kg FROM timbangan_transaksi WHERE id=:id AND kode=\'DATA-SEBELUM-CONTOH\''),{'id':lama})==15000
        assert {'berjalan','selesai','dibatalkan'} <= set((await db.scalars(select(Jasa.status))).all())
        sebelum=await db.scalar(text('SELECT count(*) FROM timbangan_transaksi'))
    hasil2=await contoh.jalankan(True)
    assert hasil2==hasil
    async with pg() as db:
        assert await db.scalar(text('SELECT count(*) FROM timbangan_transaksi'))==sebelum
    halaman=await contoh.periksa_halaman('/tmp/hmu-data-halaman')
    assert len(halaman)>=35


@pytest.mark.asyncio
async def test_mode_uji_wajib_sebelum_membuka_database(monkeypatch):
    monkeypatch.setattr(settings,'mode_uji',False)
    with pytest.raises(ValueError,match='MODE_UJI'):
        await contoh.jalankan(True)
