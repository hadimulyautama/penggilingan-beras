"""Keputusan 22 Oktober: karung per partai, tanpa bobot hantu di susut."""
from decimal import Decimal

import pytest
from sqlalchemy import select, func, text
from app.database import now_local
from app.models import (PkPurchaseBatch, PkGudang2Intake, PkTumpukanToSilo,
                        PolishingSiloUsage, Silo, Supplier, User, Warehouse)
from app.penggilingan.gudang2 import service as g2
from app.penggilingan.gudang2 import polishing as sosoh
from app.penggilingan.gudang2.karung import bobot_per_karung
from hmu_identitas import peran as P

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def dunia(pg):
    async with pg() as db:
        gudang = Warehouse(nama_gudang='Gudang karung', kode_fungsi='g2')
        pemasok = Supplier(nama_supplier='Pemasok karung')
        db.add_all([gudang, pemasok])
        await db.flush()
        user = User(nama='Operator karung', role=P.OPERATOR, status='aktif', default_warehouse_id=gudang.id)
        db.add_all([user, Silo(nama_silo='Silo A', warehouse_id=gudang.id),
                    Silo(nama_silo='Silo B', warehouse_id=gudang.id)])
        await db.commit()
        return user.id, pemasok.id


async def batch_baru(db, dunia, n=128, w=10140, kode='PKB-KARUNG-01', sumber='timbangan'):
    user = await db.get(User, dunia[0])
    b = PkPurchaseBatch(kode_batch=kode, supplier_id=dunia[1], jumlah_karung=n,
        ukuran_karung_kg=80, berat_total_kg=w, sumber_berat=sumber,
        berat_perkiraan_kg=w if sumber == 'perkiraan' else None, jenis_pk='kl',
        tanggal_pembelian=now_local().date(), waktu_pembelian=now_local(), input_by=user.id)
    db.add(b)
    await db.commit()
    it = (await g2.masukkan_pk_luar(db, user=user, kode=kode)).intake
    return user, b, it


async def pindah(db, u, it, k, silo='A', **lain):
    return await g2.pindah_tumpukan_ke_silo(db, user=u, intake_id=it.id,
        nama_silo=silo, jumlah_karung=k, **lain)


async def habiskan(db, u, silo='A', hasil=100):
    mulai = await sosoh.mulai_penyosohan(db, user=u, nama_silos=[silo])
    await sosoh.catat_output(db, user=u, kode=mulai.proc.kode_proses, jenis='medium', berat_kumulatif=hasil)
    selesai = await sosoh.selesai_penyosohan(db, user=u, kode=mulai.proc.kode_proses, nama_silo=silo, sisa_kg=0)
    await sosoh.akhiri_penyosohan(db, user=u, kode=mulai.proc.kode_proses)
    return selesai


async def test_kasus_lapangan_126_dan_sisa_2(pg, dunia):
    async with pg() as db:
        u,b,it = await batch_baru(db,dunia)
        r = await pindah(db,u,it,126)
        assert round(r.berat_kg,1) == 9981.6
        assert round(r.sisa_tumpukan_intake,1) == 158.4
        assert round(await g2.hitung_stok_tumpukan(db),1) == 158.4
        raw = (await db.execute(text('SELECT jumlah_karung, berat_kg FROM pk_tumpukan_to_silo'))).one()
        assert raw == (126, None)
        assert '2 karung' in await g2.ringkasan_karung(db,it)
        from app.services.stok import pk_gudang2
        kartu = (await pk_gudang2(db))[0]
        assert round(kartu.tersedia,1) == 158.4
        assert '158,4 kg' in kartu.ringkasan_karung
        assert 'Pemasok karung' in kartu.selisih_kiriman


@pytest.mark.parametrize('n,w',[(128,10140),(127,10001)])
async def test_seluruh_karung_tepat_nol_tanpa_drift(pg,dunia,n,w):
    async with pg() as db:
        u,b,it = await batch_baru(db,dunia,n,w)
        for _ in range(n):
            await pindah(db,u,it,1)
        assert await g2._sisa_tumpukan_intake(db,it.id) == 0
        assert await g2.hitung_stok_tumpukan(db) == 0
        silo = await g2.get_g2_silo(db,'A')
        assert await g2.hitung_stok_silo(db,silo.id) == w


async def test_sosoh_seluruh_partai_bahan_10140_susut_fisik(pg,dunia):
    async with pg() as db:
        u,b,it = await batch_baru(db,dunia)
        await pindah(db,u,it,128)
        r = await habiskan(db,u,hasil=10038.6)
        neraca = sosoh.neraca_sosoh(r.pk_terpakai_total,r.outputs)
        assert neraca.bahan_kg == 10140
        assert round(neraca.susut.kg,1) == 101.4
        silo = await g2.get_g2_silo(db,'A')
        assert await g2.hitung_stok_silo(db,silo.id) == 0


async def test_dua_silo_tidak_memikul_seluruh_selisih(pg,dunia):
    async with pg() as db:
        u,b,it = await batch_baru(db,dunia)
        await pindah(db,u,it,126)
        await pindah(db,u,it,2,'B')
        a = await habiskan(db,u,'A',9881.8)
        b = await habiskan(db,u,'B',156.8)
        assert round(a.pk_terpakai_total,1) == 9981.6
        assert round(b.pk_terpakai_total,1) == 158.4
        assert sosoh.neraca_sosoh(a.pk_terpakai_total,a.outputs).susut.kg > 0
        assert sosoh.neraca_sosoh(b.pk_terpakai_total,b.outputs).susut.kg > 0
        assert a.pk_terpakai_total+b.pk_terpakai_total == 10140


async def test_koreksi_w_mengalir_ke_pindahan_dan_bahan_sosoh(pg,dunia):
    async with pg() as db:
        u,b,it = await batch_baru(db,dunia,w=10240)
        await pindah(db,u,it,126)
        mulai = await sosoh.mulai_penyosohan(db,user=u,nama_silos=['A'])
        b.berat_total_kg = 10140
        await db.commit()
        m = (await db.scalars(select(PkTumpukanToSilo))).one()
        assert round(float(m.berat_kg),1) == 9981.6
        r = await sosoh.selesai_penyosohan(db,user=u,kode=mulai.proc.kode_proses,nama_silo='A',sisa_kg=0)
        assert round(r.pk_terpakai_total,1) == 9981.6
        assert round(await g2._sisa_tumpukan_intake(db,it.id),1) == 158.4


async def test_koreksi_w_tidak_mengubah_hasil_dan_barang_keluar(pg,dunia):
    from app.models import OutgoingRecord, OutgoingItem
    async with pg() as db:
        u,b,it = await batch_baru(db,dunia,w=10240)
        await pindah(db,u,it,126)
        hasil = await habiskan(db,u,hasil=9800)
        rec = OutgoingRecord(kode='OUT-KARUNG-01', tanggal=now_local().date(), waktu=now_local(), input_by=u.id)
        db.add(rec)
        await db.flush()
        item = OutgoingItem(outgoing_record_id=rec.id,item_type='pk_g2',berat_kg=100)
        db.add(item)
        await db.commit()
        b.berat_total_kg=10140
        await db.commit()
        await db.refresh(item)
        assert item.berat_kg == 100
        assert (await sosoh._output_map(db,hasil.proc.id))['medium'] == 9800
        usage = (await db.scalars(select(PolishingSiloUsage))).one()
        assert round(float(usage.berat_terpakai_kg),1) == 9981.6


@pytest.mark.parametrize('w',[None,10240])
async def test_karung_boleh_sebelum_timbang_kedua_lalu_final(pg,dunia,w):
    async with pg() as db:
        u,b,it = await batch_baru(db,dunia,w=w,sumber='perkiraan')
        r = await pindah(db,u,it,126)
        assert r.jumlah_karung == 126 and not r.bobot_final
        if w is None:
            assert r.berat_kg is None
        else:
            assert r.berat_kg == 10080
            assert '± ' in await g2.ringkasan_karung(db,it)
        b.berat_total_kg=10140
        b.sumber_berat='timbangan'
        await db.commit()
        await g2.resinkron_intake_g2(db)
        assert it.bobot_final
        assert round(await g2._sisa_tumpukan_intake(db,it.id),1) == 158.4
        m = (await db.scalars(select(PkTumpukanToSilo))).one()
        assert round(float(m.berat_kg),1) == 9981.6


async def test_hasil_timbang_tetap_dan_bagian_karung(pg,dunia):
    async with pg() as db:
        u,b,it = await batch_baru(db,dunia,w=10240)
        await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=it.id,nama_silo='A',berat=50,hasil_timbang=True)
        b.berat_total_kg=10140
        await db.commit()
        m = (await db.scalars(select(PkTumpukanToSilo))).one()
        assert m.berat_kg == 50 and m.jumlah_karung is None
        await pindah(db,u,it,127)
        assert 'kurang dari 1 karung' in await g2.ringkasan_karung(db,it)
        with pytest.raises(g2.Gudang2Error,match='karung'):
            await pindah(db,u,it,1)


async def test_tolak_melebihi_sisa_dengan_pesan_karung(pg,dunia):
    async with pg() as db:
        u,b,it = await batch_baru(db,dunia)
        await pindah(db,u,it,126)
        with pytest.raises(g2.Gudang2Error,match='Tinggal 2 karung, tak bisa memasukkan 5 karung'):
            await pindah(db,u,it,5)


async def test_dua_batch_fifo_memakai_r_masing_masing(pg,dunia):
    async with pg() as db:
        u,b,a = await batch_baru(db,dunia,n=127,w=10001)
        _,_,b = await batch_baru(db,dunia,n=128,w=10140,kode='PKB-KARUNG-02')
        r = await g2.pindah_tumpukan(db,user=u,nama_silo='A',jumlah_karung=255)
        assert r.moved_kg == 20141
        moves = list((await db.scalars(select(PkTumpukanToSilo).order_by(PkTumpukanToSilo.id))).all())
        assert [m.pk_gudang2_intake_id for m in moves] == [a.id,b.id]
        assert [m.jumlah_karung for m in moves] == [127,128]
        assert await g2.hitung_stok_tumpukan(db) == 0


async def test_batch_lama_tanpa_n_tetap_kg(pg,dunia):
    async with pg() as db:
        u,b,it = await batch_baru(db,dunia,n=None)
        r=await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=it.id,nama_silo='A',berat=10080)
        assert r.berat_kg == 10080 and r.sisa_tumpukan_intake == 60
        assert bobot_per_karung(b) is None


async def test_pemasukan_baru_mewariskan_jumlah_karung_dari_borang(pg,dunia):
    from tests.pg.test_peristiwa_pk_luar import _tiket
    from app.web.api import CatatPkLuarReq
    tid = await _tiket(pg,'TKT-KARUNG-01',dunia[1])
    async with pg() as db:
        u=await db.get(User,dunia[0]);u.role=P.ADMIN
        await db.commit()
        req=CatatPkLuarReq(timbangan_transaksi_id=tid,jenis_pk='kl',jumlah_karung=128,ukuran_karung_kg=80)
        r=await g2.create_pk_purchase_dari_timbang(db,user=u,**req.model_dump(exclude={'kunci_kiriman'}))
        assert r.batch.jumlah_karung == 128 and r.batch.ukuran_karung_kg == 80


async def test_koreksi_w_saat_dua_silo_dan_tambah_selama_proses(pg,dunia):
    async with pg() as db:
        u,b,it=await batch_baru(db,dunia,w=10240,sumber='perkiraan')
        await pindah(db,u,it,100)
        mulai=await sosoh.mulai_penyosohan(db,user=u,nama_silos=['A'])
        await pindah(db,u,it,26)
        await pindah(db,u,it,2,'B')
        b.berat_total_kg=10140;b.sumber_berat='timbangan'
        await db.commit()
        await g2.resinkron_intake_g2(db)
        usage=(await db.scalars(select(PolishingSiloUsage))).one()
        assert round(float(usage.berat_awal_kg),1) == 7921.9
        assert round(float(usage.berat_masuk_kg),1) == 2059.7
        r=await sosoh.selesai_penyosohan(db,user=u,kode=mulai.proc.kode_proses,nama_silo='A',sisa_kg=0)
        assert round(r.pk_terpakai_total,1) == 9981.6
        assert await g2.hitung_stok_tumpukan(db) == 0


async def test_tampilan_detail_karung_menyebut_satuan_dan_pemasok(pg,dunia):
    from tests.pg.test_riwayat_giling import _klien
    async with pg() as db:
        u,b,it=await batch_baru(db,dunia)
        await pindah(db,u,it,126)
        iid=it.id
    async with await _klien(pg,peran=P.SUPERADMIN) as klien:
        halaman=await klien.get(f'/stok/pk/detail?gudang=g2&id={iid}')
        assert halaman.status_code == 200
        assert 'sisa 2 karung' in halaman.text and '158,4 kg' in halaman.text
        assert 'Pemasok karung' in halaman.text and '0,98%' in halaman.text
        assert 'pindah_tumpukan_silo' in halaman.text


from tests.pg.test_stok_g2_per_kode import dunia as dunia_g1


async def test_pk_giling_sendiri_tidak_diskalakan_satu_kilo_pun(pg,dunia_g1):
    async with pg() as db:
        it=await db.get(PkGudang2Intake,dunia_g1['giling_intake_id'])
        sebelum=it.berat_kg
        r=await g2.pindah_tumpukan_ke_silo(db,user=dunia_g1['user'],intake_id=it.id,nama_silo='A',berat=1234)
        assert r.berat_kg == 1234
        assert r.sisa_tumpukan_intake == float(sebelum)-1234
        m=(await db.scalars(select(PkTumpukanToSilo))).one()
        assert m.jumlah_karung is None
        assert m.berat_timbang_kg == 1234


async def test_penyesuaian_stok_lama_bertanggal_bersebab_tanpa_ubah_bukti(pg,dunia):
    from app.penggilingan.gudang2.models import PkPenyesuaianStok
    async with pg() as db:
        u,b,it=await batch_baru(db,dunia,n=None)
        await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=it.id,nama_silo='A',berat=10080)
        u.role=P.ADMIN
        await db.commit()
        awal_batch=b.berat_total_kg;awal_intake=it.berat_kg
        koreksi=await g2.sesuaikan_stok_pk_lama(db,user=u,intake_id=it.id,selisih_kg=98.4,
            tanggal=now_local().date(),alasan='Koreksi pembebanan selisih partai lama berdasarkan temuan pemilik')
        assert koreksi.tanggal == now_local().date() and koreksi.alasan
        assert b.berat_total_kg == awal_batch and it.berat_kg == awal_intake
        assert round(await g2.hitung_stok_tumpukan(db),1) == 158.4
        from app.services.stok import pk_gudang2
        assert round((await pk_gudang2(db))[0].tersedia,1) == 158.4
        assert (await db.scalar(select(func.count()).select_from(PkPenyesuaianStok))) == 1
        with pytest.raises(g2.Gudang2Error,match='tanggal, alasan'):
            await g2.sesuaikan_stok_pk_lama(db,user=u,intake_id=it.id,selisih_kg=1,tanggal=None,alasan='')


async def test_nota_tidak_menggantikan_w_karung_dan_revisi_tiket_mengalir(pg,dunia):
    from tests.pg.test_peristiwa_pk_luar import _tiket
    from app.penggilingan.gudang1.services.timbang_link import resinkron_bobot_berubah
    tid=await _tiket(pg,'TKT-KARUNG-02',dunia[1])
    async with pg() as db:
        u=await db.get(User,dunia[0]);u.role=P.ADMIN
        await db.execute(text('UPDATE timbangan_transaksi SET berat_acuan_kg=7000, netto_timbangan_kg=8000 WHERE id=:id'),{'id':tid})
        await db.commit()
        b=(await g2.create_pk_purchase_dari_timbang(db,user=u,timbangan_transaksi_id=tid,jenis_pk='kl',jumlah_karung=100,ukuran_karung_kg=80)).batch
        assert b.berat_total_kg == 8000 and b.sumber_berat == 'timbangan'
        it=(await g2.masukkan_pk_luar(db,user=u,kode=b.kode_batch)).intake
        await pindah(db,u,it,50)
        await db.execute(text('UPDATE timbangan_transaksi SET netto_timbangan_kg=7900 WHERE id=:id'),{'id':tid})
        await db.commit()
        await resinkron_bobot_berubah(db)
        await db.refresh(b)
        assert b.berat_total_kg == 7900
        m=(await db.scalars(select(PkTumpukanToSilo))).one()
        assert m.berat_kg == 3950


async def test_kirim_ulang_karung_terakhir_tidak_memindah_dua_kali(pg,dunia):
    async with pg() as db:
        u,b,it=await batch_baru(db,dunia)
        a=await pindah(db,u,it,128,kunci_kiriman='uji-karung-idempoten')
        b=await pindah(db,u,it,128,kunci_kiriman='uji-karung-idempoten')
        assert a.kode_pindah == b.kode_pindah
        assert (await db.scalar(select(func.count()).select_from(PkTumpukanToSilo))) == 1
        assert await g2.hitung_stok_tumpukan(db) == 0


async def test_dua_operator_tidak_bisa_mengambil_karung_yang_sama(pg,dunia):
    import asyncio
    async with pg() as db:
        u,b,it=await batch_baru(db,dunia)
        iid=it.id
    async def ambil():
        async with pg() as db:
            u=await db.get(User,dunia[0])
            try:
                await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=iid,nama_silo='A',jumlah_karung=100)
                return 'berhasil'
            except g2.Gudang2Error as e:
                return str(e)
    hasil=await asyncio.gather(ambil(),ambil())
    assert hasil.count('berhasil') == 1
    assert any('Tinggal 28 karung' in h for h in hasil)


async def test_undo_karung_bobot_belum_diketahui(pg,dunia):
    from app.services.undo import _undo_pindah_tumpukan
    async with pg() as db:
        u,b,it=await batch_baru(db,dunia,w=None,sumber='perkiraan')
        await pindah(db,u,it,126)
        m=(await db.scalars(select(PkTumpukanToSilo))).one()
        pesan=await _undo_pindah_tumpukan(db,m.id)
        await db.commit()
        assert '126 karung' in pesan
        assert '128 karung' in await g2.ringkasan_karung(db,it)


async def test_fifo_seluruhnya_tetap_menyimpan_karung_sebelum_w(pg,dunia):
    async with pg() as db:
        u,b,it=await batch_baru(db,dunia,w=None,sumber='perkiraan')
        r=await g2.pindah_tumpukan(db,user=u,nama_silo='A')
        assert r.moved_kg is None
        m=(await db.scalars(select(PkTumpukanToSilo))).one()
        assert m.jumlah_karung == 128 and m.berat_timbang_kg is None
        assert await g2._sisa_tumpukan_intake(db,it.id) == 0
        from app.services.stok import pk_gudang2
        assert await pk_gudang2(db) == []
        b.berat_total_kg=10140;b.sumber_berat='timbangan'
        await db.commit()
        assert await g2.hitung_stok_tumpukan(db) == 0


async def test_hitung_ulang_susut_diberi_nama_dan_laporan_penutupan_tetap_ada(pg,dunia):
    async with pg() as db:
        u,b,it=await batch_baru(db,dunia,w=10240)
        await pindah(db,u,it,128)
        selesai=await habiskan(db,u,hasil=10000)
        b.berat_total_kg=10140
        await db.commit()
        kartu,_=await sosoh.riwayat_sosoh(db,process_id=selesai.proc.id)
        assert kartu[0].neraca_tercatat.bahan_kg == 10240
        assert kartu[0].neraca_tercatat.susut.kg == 240
        assert kartu[0].neraca.bahan_kg == 10140
        assert kartu[0].neraca.susut.kg == 140
        from app.web.laporan_sosoh import ambil_data
        laporan=await ambil_data(selesai.proc.id)
        assert laporan['neraca_tercatat'].bahan_kg == 10240
        assert laporan['balance'].bahan_kg == 10140


async def test_kg_yang_sudah_keluar_tidak_dikredit_lagi_ke_silo(pg,dunia):
    from app.models import OutgoingRecord, OutgoingItem
    async with pg() as db:
        u,b,it=await batch_baru(db,dunia)
        rec=OutgoingRecord(kode='OUT-KARUNG-02',tanggal=now_local().date(),waktu=now_local(),input_by=u.id)
        db.add(rec)
        await db.flush()
        db.add(OutgoingItem(outgoing_record_id=rec.id,item_type='pk_g2',berat_kg=100))
        await db.commit()
        with pytest.raises(g2.Gudang2Error,match='karung'):
            await pindah(db,u,it,128)
        await pindah(db,u,it,126)
        assert round(await g2._sisa_tumpukan_intake(db,it.id),1) == 58.4
        assert 'kurang dari 1 karung' in await g2.ringkasan_karung(db,it)


async def test_sisa_jasa_ikut_w_terkini_tanpa_menyisakan_barang_hantu(pg,dunia):
    from app.models import Jasa, Pelanggan
    from app.services.jasa import sisa_jasa
    async with pg() as db:
        u,b,it=await batch_baru(db,dunia,w=10240)
        pelanggan=Pelanggan(nama_pelanggan='Pemilik PK karung')
        db.add(pelanggan)
        await db.flush()
        jasa=Jasa(kode='JAS-KARUNG-01',pelanggan_id=pelanggan.id)
        db.add(jasa)
        await db.flush()
        b.supplier_id=None;b.jasa_id=jasa.id;it.jasa_id=jasa.id
        await db.commit()
        await pindah(db,u,it,128)
        b.berat_total_kg=10140
        await db.commit()
        assert (await sisa_jasa(db,jasa.id)).pk_g2_kg == 10140
        await habiskan(db,u,hasil=10000)
        assert (await sisa_jasa(db,jasa.id)).pk_g2_kg == 0
