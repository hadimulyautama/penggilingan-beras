"""Batas retur bersamaan memakai Postgres, bukan tiruan kunci di SQLite."""
import asyncio
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text

from app.database import now_local
from app.models import (FinishedGoodsStock, KemasanTara, OutgoingItem,
                        OutgoingRecord, PackageSize, PackagingMaterial,
                        Pelanggan, ProductSku, User, Warehouse, CustomerReturn, CustomerReturnItem)
from app.peran import PERAN_ADMIN_KEATAS
from app.penggilingan.inventory.models import ReturRincian, ReturPemeriksaanLog
from app.services import retur_pengajuan as layanan

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def asal(pg):
    async with pg() as db:
        orang = User(nama='Pemeriksa retur', role=PERAN_ADMIN_KEATAS[-1], status='aktif')
        pelanggan = Pelanggan(nama_pelanggan='Pemilik pengiriman')
        bahan = PackagingMaterial(kode='uji-retur', nama='Karung', aktif=True)
        ukuran = PackageSize(ukuran_kg=25, aktif=True)
        gudang = Warehouse(nama_gudang='Gudang 2', kode_fungsi='g2', aktif=True)
        g1 = Warehouse(nama_gudang='Gudang 1', kode_fungsi='g1', aktif=True)
        db.add_all([orang, pelanggan, bahan, ukuran, gudang, g1]); await db.flush()
        sku = ProductSku(kategori='menir', packaging_material_id=bahan.id,
                         package_size_id=ukuran.id, aktif=True)
        db.add(sku); await db.flush()
        db.add(KemasanTara(packaging_material_id=bahan.id, package_size_id=ukuran.id,
                           tara_per_karung_kg=Decimal('.10')))
        now = now_local()
        pengiriman = OutgoingRecord(kode='OUT-UJI-RETUR', pelanggan_id=pelanggan.id,
            tanggal=now.date(), waktu=now, input_by=orang.id, status='selesai')
        db.add(pengiriman); await db.flush()
        item = OutgoingItem(outgoing_record_id=pengiriman.id, item_type='finished_goods',
            product_sku_id=sku.id, jumlah_karung=20, berat_kg=500)
        db.add(item); await db.flush()
        await db.execute(text('ALTER TABLE timbangan_transaksi ALTER COLUMN arah TYPE varchar(16)'))
        tiket = []
        for kode in ['RTP-UJI-A', 'RTP-UJI-B']:
            tiket.append(await db.scalar(text('''INSERT INTO timbangan_transaksi
                (kode,tanggal,arah,jenis_kode,timbang1_kg,status_tiket,status_transaksi,pelanggan_id)
                VALUES (:kode,CURRENT_DATE,'RETUR_MASUK','RETUR_PELANGGAN',9000,'TERBUKA','AKTIF',:pid)
                RETURNING id'''), {'kode': kode, 'pid': pelanggan.id}))
        await db.commit()
        return dict(uid=orang.id, pid=pelanggan.id, oid=pengiriman.id, iid=item.id, tiket=tiket)


async def simpan(pg, asal, n, tiket=0, **opsi):
    async with pg() as db:
        r = await layanan.simpan(db, pengiriman_id=asal['oid'],
            tiket_id=asal['tiket'][tiket], jumlah={asal['iid']: str(n)},
            pelaku_id=asal['uid'], **opsi)
        await db.commit()
        return r


async def test_tunggu_timbang_tidak_menambah_stok(pg, asal):
    r = await simpan(pg, asal, 10)
    assert r.status_pemeriksaan == 'menunggu_timbang'
    assert r.muatan[0]['outgoing_item_id'] == asal['iid']
    assert r.muatan[0]['berat_kg'] == '250'
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock)) == 0
        assert await db.scalar(select(func.count()).select_from(ReturPemeriksaanLog)) == 1


@pytest.mark.parametrize('n', ['0', '-1', '21', '1.5', 'NaN'])
async def test_tolak_jumlah_tidak_sah(pg, asal, n):
    with pytest.raises(ValueError):
        await simpan(pg, asal, n)


async def test_bertahap_memperhitungkan_pengajuan_tertunda(pg, asal):
    await simpan(pg, asal, 12)
    with pytest.raises(ValueError, match='kumulatif'):
        await simpan(pg, asal, 9, tiket=1)
    await simpan(pg, asal, 8, tiket=1)


async def test_bersamaan_tidak_melebihi_jumlah_asal(pg, asal):
    hasil = await asyncio.gather(simpan(pg, asal, 12),
        simpan(pg, asal, 12, tiket=1), return_exceptions=True)
    assert sum(isinstance(h, ReturRincian) for h in hasil) == 1
    assert sum(isinstance(h, ValueError) for h in hasil) == 1


async def test_tiket_tidak_bisa_dipakai_dua_pengajuan(pg, asal):
    hasil = await asyncio.gather(simpan(pg, asal, 5),
                                simpan(pg, asal, 5), return_exceptions=True)
    assert sum(isinstance(h, ReturRincian) for h in hasil) == 1
    assert sum(isinstance(h, ValueError) for h in hasil) == 1


async def test_pelanggan_tiket_harus_sesuai(pg, asal):
    async with pg() as db:
        await db.execute(text('UPDATE timbangan_transaksi SET pelanggan_id=NULL WHERE id=:id'),
                         {'id': asal['tiket'][0]})
        await db.commit()
    with pytest.raises(ValueError, match='pelanggan'):
        await simpan(pg, asal, 5)


async def test_koreksi_diaudit_dan_syarat_manual_melekat(pg, asal):
    async with pg() as db:
        await db.execute(text('''UPDATE timbangan_transaksi SET status_tiket='SELESAI',
            timbang2_kg=8750,berat_barang_kg=250 WHERE id=:id'''), {'id': asal['tiket'][0]})
        await db.commit()
    r = await simpan(pg, asal, 9)
    assert r.status_pemeriksaan == 'perlu_koreksi' and r.wajib_manual
    r = await simpan(pg, asal, 10, pengajuan_id=r.id, alasan='Satu karung terlewat dalam rincian.')
    assert r.status_pemeriksaan == 'calon_manual' and r.wajib_manual
    async with pg() as db:
        logs = (await db.scalars(select(ReturPemeriksaanLog).order_by(ReturPemeriksaanLog.id))).all()
        assert len(logs) == 2
        assert logs[-1].sebelum['muatan'][0]['jumlah_karung'] == 9
        assert logs[-1].sesudah['muatan'][0]['jumlah_karung'] == 10
        assert logs[-1].pelaku_id == asal['uid']
        assert logs[-1].alasan


async def selesai(pg, asal, kg=250):
    async with pg() as db:
        await db.execute(text('''UPDATE timbangan_transaksi SET status_tiket='SELESAI',
            timbang2_kg=9000-:kg,berat_barang_kg=:kg WHERE id=:id'''),
            {'id': asal['tiket'][0], 'kg': kg})
        await db.commit()


async def terima(pg, identitas, **opsi):
    from app.services.retur_penerimaan import periksa_dan_terima
    async with pg() as db:
        hasil = await periksa_dan_terima(db, identitas, **opsi)
        await db.commit()
        return hasil


async def test_penerimaan_otomatis_bersamaan_tepat_sekali(pg, asal):
    r = await simpan(pg, asal, 10)
    assert await terima(pg, r.id) is None
    await selesai(pg, asal)
    hasil = await asyncio.gather(terima(pg, r.id), terima(pg, r.id))
    assert hasil[0].id == hasil[1].id
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(CustomerReturn)) == 1
        assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock)) == 1
        assert await db.scalar(select(func.count()).select_from(CustomerReturnItem)) == 1
        stok = await db.scalar(select(FinishedGoodsStock))
        assert stok.berat_total_kg == Decimal('250')
        assert stok.kemasan_mengurangi_stok is False
        item = await db.get(OutgoingItem, asal['iid'])
        assert item.jumlah_karung == 20 and item.berat_kg == 500


async def test_koreksi_tetap_manual_dan_alasan_saja_tidak_meloloskan(pg, asal):
    await selesai(pg, asal)
    r = await simpan(pg, asal, 9)
    assert await terima(pg, r.id) is None
    r = await simpan(pg, asal, 9, pengajuan_id=r.id, alasan='Sudah diperiksa.')
    async with pg() as db:
        pelaku = await db.get(User, asal['uid'])
    assert await terima(pg, r.id, manual=True, pelaku=pelaku) is None
    r = await simpan(pg, asal, 10, pengajuan_id=r.id, alasan='Koreksi satu karung terlewat.')
    assert await terima(pg, r.id) is None
    assert await terima(pg, r.id, manual=True, pelaku=pelaku)


async def test_pekerja_latar_tidak_memerlukan_halaman_dibuka(pg, asal):
    from app.services.retur_pekerja import sekali
    r = await simpan(pg, asal, 10)
    await sekali()
    async with pg() as db:
        assert (await db.get(ReturRincian, r.id)).customer_return_id is None
    await selesai(pg, asal)
    await sekali()
    await sekali()
    async with pg() as db:
        assert (await db.get(ReturRincian, r.id)).customer_return_id
        assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock)) == 1


async def test_http_formulir_dan_pengajuan_dari_detail_asal(pg, asal):
    import re
    from tests.pg.test_barang_keluar import _klien
    from app.web import csrf
    c = await _klien(pg, asal['uid'], 'pemeriksa_retur_http')
    async with c:
        r = await c.get(f'/barang-keluar/{asal["oid"]}/retur')
        assert r.status_code == 200, r.text[:200]
        assert 'Barang yang benar-benar dikirim' in r.text and 'RTP-UJI-A' in r.text
        assert 'Jumlah retur (karung)' in r.text
        token = re.search(r'name="formulir-sesi" content="([^"]+)"', r.text).group(1)
        r = await c.post(f'/barang-keluar/{asal["oid"]}/retur', data={
            '_csrf': token, 'item_id': str(asal['iid']),
            'jumlah': '10', 'tiket_id': str(asal['tiket'][0]), 'catatan': 'Kemasan asli kembali.'})
        assert r.status_code == 303
        assert '/retur/pengajuan/' in r.headers['location']
        detail = await c.get(r.headers['location'])
        assert detail.status_code == 200
        assert 'Menunggu timbang kedua' in detail.text
        daftar = await c.get('/retur')
        assert daftar.status_code == 200 and 'OUT-UJI-RETUR' in daftar.text
        asal_html = await c.get(f'/barang-keluar/{asal["oid"]}')
        assert asal_html.status_code == 200 and 'Retur barang' in asal_html.text
    # Jalur HTTP dari pengiriman asal menyimpan relasi otomatis, sampai stok
    # diterima; tidak ada langkah penautan manual atau pencocokan nama/bobot.
    async with pg() as db:
        pengajuan = await db.scalar(select(ReturRincian))
        assert pengajuan.outgoing_record_id == asal['oid']
        assert pengajuan.muatan[0]['outgoing_item_id'] == asal['iid']
    await selesai(pg, asal)
    penerimaan = await terima(pg, pengajuan.id)
    assert penerimaan is not None
    async with pg() as db:
        kembali = await db.scalar(select(CustomerReturnItem).where(
            CustomerReturnItem.customer_return_id == penerimaan.id))
        assert kembali.outgoing_item_id == asal['iid']
        sumber = await db.get(OutgoingItem, kembali.outgoing_item_id)
        assert sumber.outgoing_record_id == asal['oid']
        assert (await db.get(ReturRincian, pengajuan.id)).customer_return_id == penerimaan.id


@pytest.mark.parametrize('gudang_kerja', ['g1', 'g2'])
async def test_http_operator_ditolak_pada_formulir_dan_endpoint(pg, asal, gudang_kerja):
    from tests.pg.test_barang_keluar import _klien
    from app.web import csrf
    from hmu_identitas.peran import OPERATOR
    pengajuan = await simpan(pg, asal, 1)
    async with pg() as db:
        gudang = await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi == gudang_kerja))
        operator = User(nama='Operator uji', role=OPERATOR, status='aktif', default_warehouse_id=gudang.id)
        db.add(operator); await db.commit()
    c = await _klien(pg, operator.id, 'operator_retur_http', mode='operator')
    async with c:
        token = (await c.get('/api/sesi-formulir')).json()['token']
        if gudang_kerja == 'g2':
            daftar_keluar = await c.get('/barang-keluar')
            assert daftar_keluar.status_code == 200 and 'href="/retur"' not in daftar_keluar.text
        for path in ['/retur', f'/barang-keluar/{asal["oid"]}/retur']:
            assert (await c.get(path)).status_code == 403
        assert (await c.post(f'/barang-keluar/{asal["oid"]}/retur', data={
            '_csrf': token, 'item_id': str(asal['iid']),
            'jumlah': '1', 'tiket_id': str(asal['tiket'][0])})).status_code == 403
        assert (await c.post(f'/retur/pengajuan/{pengajuan.id}/verifikasi',
                            data={'_csrf': token})).status_code == 403


async def test_superadmin_membuka_dan_mengajukan_retur(pg, asal):
    from tests.pg.test_barang_keluar import _klien
    from hmu_identitas.peran import SUPERADMIN
    async with pg() as db:
        (await db.get(User, asal['uid'])).role = SUPERADMIN
        await db.commit()
    c=await _klien(pg,asal['uid'],'uji_superadmin_retur')
    async with c:
        r=await c.get(f'/barang-keluar/{asal["oid"]}/retur')
        assert r.status_code == 200
        token=(await c.get('/api/sesi-formulir')).json()['token']
        r=await c.post(f'/barang-keluar/{asal["oid"]}/retur',data=dict(
            _csrf=token,item_id=str(asal['iid']),jumlah='1',tiket_id=str(asal['tiket'][0])))
        assert r.status_code == 303 and '/retur/pengajuan/' in r.headers['location']


async def test_retur_curah_memakai_stok_curah_tanpa_sku_buatan(pg, asal):
    from app.models import ByproductStock
    async with pg() as db:
        item = await db.get(OutgoingItem, asal['iid'])
        item.item_type = 'byproduct_curah'
        item.product_sku_id = None
        item.jenis_byproduct = 'bekatul'
        item.jumlah_karung = None
        await db.commit()
    await selesai(pg, asal, 100)
    r = await simpan(pg, asal, 100)
    receipt = await terima(pg, r.id)
    assert receipt
    from tests.pg.test_barang_keluar import _klien
    c=await _klien(pg,asal['uid'],'uji_detail_curah')
    async with c:
        detail=await c.get(f'/retur/{receipt.id}')
        assert detail.status_code == 200 and 'Stok bahan / curah' in detail.text
    async with pg() as db:
        stock = await db.scalar(select(ByproductStock))
        assert stock.berat_kg == 100 and stock.jenis_produk == 'bekatul'
        assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock)) == 0
        assert (await db.scalar(select(CustomerReturnItem))).product_sku_id is None


async def test_retur_pk_g2_masuk_melalui_peristiwa_intake_lama(pg, asal):
    from app.models import PkGudang2Intake
    from app.penggilingan.gudang2.service import hitung_stok_tumpukan
    async with pg() as db:
        bahan = PackagingMaterial(kode='karung_pk', nama='Karung PK', aktif=True)
        ukuran = PackageSize(ukuran_kg=50, aktif=True)
        db.add_all([bahan, ukuran]); await db.flush()
        db.add(KemasanTara(packaging_material_id=bahan.id, package_size_id=ukuran.id,
                           tara_per_karung_kg=Decimal('.07')))
        item = await db.get(OutgoingItem, asal['iid'])
        item.item_type = 'pk_g2'; item.product_sku_id = None; item.jumlah_karung = 10
        now = now_local()
        db.add(PkGudang2Intake(sumber_tipe='beli_luar', tujuan='ditumpuk',
            berat_kg=1000, tanggal_masuk=now.date(), waktu_masuk=now, input_by=asal['uid']))
        await db.commit()
        awal = await hitung_stok_tumpukan(db)
    await selesai(pg, asal, 100)
    r = await simpan(pg, asal, 100, karung_item={asal['iid']: 2})
    assert await terima(pg, r.id)
    assert await terima(pg, r.id)
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(PkGudang2Intake).where(PkGudang2Intake.sumber_tipe == 'retur')) == 1
        intake = await db.scalar(select(PkGudang2Intake).where(PkGudang2Intake.sumber_tipe == 'retur'))
        assert intake.sumber_tipe == 'retur' and intake.peristiwa_id
        assert (await hitung_stok_tumpukan(db)) - awal == 100


async def test_pemilik_dua_pesanan_jasa_diturunkan_per_item(pg, asal):
    from app.models import Jasa
    async with pg() as db:
        a = Jasa(kode='JAS-UJI-A', pelanggan_id=asal['pid'])
        b = Jasa(kode='JAS-UJI-B', pelanggan_id=asal['pid'])
        db.add_all([a, b]); await db.flush()
        item = await db.get(OutgoingItem, asal['iid'])
        item.jasa_id = a.id
        item2 = OutgoingItem(outgoing_record_id=asal['oid'], item_type='finished_goods',
            product_sku_id=item.product_sku_id, jumlah_karung=20, berat_kg=500, jasa_id=b.id)
        db.add(item2); await db.commit()
        item2id, aid, bid = item2.id, a.id, b.id
    await selesai(pg, asal, 250)
    async with pg() as db:
        r = await layanan.simpan(db, pengiriman_id=asal['oid'], tiket_id=asal['tiket'][0],
            jumlah={asal['iid']: '6', item2id: '4'}, pelaku_id=asal['uid'])
        await db.commit()
    assert await terima(pg, r.id)
    async with pg() as db:
        stocks = (await db.scalars(select(FinishedGoodsStock))).all()
        assert {s.jasa_id: s.jumlah_karung for s in stocks} == {aid: 6, bid: 4}
        assert (await db.get(OutgoingRecord, asal['oid'])).jasa_id is None


async def test_tiket_dibatalkan_setelah_pengajuan_ditahan_dengan_jelas(pg, asal):
    r = await simpan(pg, asal, 10)
    async with pg() as db:
        await db.execute(text("UPDATE timbangan_transaksi SET status_transaksi='DIBATALKAN' WHERE id=:id"),
                         {'id': asal['tiket'][0]})
        await db.commit()
    assert await terima(pg, r.id) is None
    async with pg() as db:
        r = await db.get(ReturRincian, r.id)
        assert r.status_pemeriksaan == 'tertahan'
        assert 'tiket RTP aktif' in r.hasil_pemeriksaan['alasan']
        assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock)) == 0


@pytest.mark.parametrize('tipe', ['pk_langsung', 'gabah_langsung'])
async def test_retur_bahan_g1_menambah_saldo_tanpa_mengubah_keluar(pg, asal, tipe):
    from app.models import (Silo, MillingProcess, MillingProcessVerification,
        Supplier, PurchaseBatch, SiloStorage, GabahKeringLot)
    from app.services.transfer import saldo_pk
    from app.penggilingan.gudang1.services.gabah_kering import saldo_gabah_kering
    from app.penggilingan.gudang1.services.milling import _pk_breakdown, pk_breakdown_banyak
    async with pg() as db:
        g1 = await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi == 'g1'))
        silo = Silo(nama_silo='Silo A', warehouse_id=g1.id, status='kosong')
        bahan = PackagingMaterial(kode='karung_pk' if tipe == 'pk_langsung' else 'biasa',
                                  nama='Karung bahan', aktif=True)
        ukuran = PackageSize(ukuran_kg=50, aktif=True)
        db.add_all([silo, bahan, ukuran]); await db.flush()
        db.add(KemasanTara(packaging_material_id=bahan.id, package_size_id=ukuran.id,
                           tara_per_karung_kg=Decimal('.07')))
        item = await db.get(OutgoingItem, asal['iid'])
        item.item_type = tipe; item.product_sku_id = None; item.jumlah_karung = 10
        now = now_local()
        if tipe == 'pk_langsung':
            proc = MillingProcess(kode_proses='LOT-UJI-RETUR', silo_id=silo.id,
                waktu_mulai=now, created_by=asal['uid'], status='selesai')
            db.add(proc); await db.flush()
            db.add(MillingProcessVerification(milling_process_id=proc.id, berat_output_final_kg=1000))
            item.milling_process_id=proc.id; sumber_id=proc.id
        else:
            supplier = Supplier(nama_supplier='Pemasok historis')
            db.add(supplier); await db.flush()
            batch = PurchaseBatch(kode_batch='GB-UJI-RETUR', supplier_id=supplier.id,
                berat_total_kg=1000,kondisi_gabah='kering',tanggal_pembelian=now.date(),
                waktu_pembelian=now,input_by=asal['uid'])
            db.add(batch); await db.flush()
            storage = SiloStorage(silo_id=silo.id,purchase_batch_id=batch.id,
                tipe_masuk='langsung_kering',tanggal_masuk=now,input_by=asal['uid'])
            db.add(storage); await db.flush()
            lot = GabahKeringLot(kode_lot='GKR-UJI-RETUR',silo_storage_id=storage.id,
                berat_timbang_kg=1000,tanggal=now.date(),waktu_timbang=now,input_by=asal['uid'])
            db.add(lot); await db.flush()
            item.gabah_kering_lot_id=lot.id; sumber_id=lot.id
        material_id=bahan.id
        await db.commit()
    await selesai(pg, asal, 100)
    r = await simpan(pg, asal, 100, kemasan_item={asal['iid']: material_id},
                     karung_item={asal['iid']: 2})
    penerimaan = await terima(pg, r.id)
    assert penerimaan
    async with pg() as db:
        assert penerimaan.warehouse_id == (await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi == 'g1'))).id
        if tipe == 'pk_langsung':
            assert await saldo_pk(db, sumber_id) == 600
            assert (await _pk_breakdown(db, sumber_id)).tersedia == 600
            assert (await pk_breakdown_banyak(db, [sumber_id]))[sumber_id].tersedia == 600
        else:
            assert await saldo_gabah_kering(db, sumber_id) == 600
        assert (await db.get(OutgoingItem, asal['iid'])).berat_kg == 500
        assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock)) == 0


async def test_satu_tiket_diperebutkan_dua_pengiriman(pg, asal):
    async with pg() as db:
        now = now_local()
        o = OutgoingRecord(kode='OUT-UJI-LAIN',pelanggan_id=asal['pid'],
            tanggal=now.date(),waktu=now,input_by=asal['uid'],status='selesai')
        db.add(o); await db.flush()
        i = await db.get(OutgoingItem, asal['iid'])
        j = OutgoingItem(outgoing_record_id=o.id,item_type='finished_goods',
            product_sku_id=i.product_sku_id,jumlah_karung=20,berat_kg=500)
        db.add(j); await db.commit()
        lain = dict(asal, oid=o.id, iid=j.id)
    hasil = await asyncio.gather(simpan(pg, asal, 5), simpan(pg, lain, 5), return_exceptions=True)
    assert sum(isinstance(h, ReturRincian) for h in hasil) == 1
    assert sum(isinstance(h, ValueError) for h in hasil) == 1


async def test_koreksi_bobot_dengan_audit_pos_timbang_tetap_manual(pg, asal):
    await selesai(pg, asal, 250)
    r = await simpan(pg, asal, 9)
    assert r.wajib_manual
    async with pg() as db:
        await db.execute(text('''UPDATE timbangan_transaksi SET timbang2_kg=8775,
            berat_barang_kg=225 WHERE id=:id'''), {'id': asal['tiket'][0]})
        await db.execute(text('''INSERT INTO timbangan_audit
            (aksi,entitas,entitas_id,akun_nama,ringkasan,nilai_sebelum,nilai_sesudah)
            VALUES ('KOREKSI','transaksi','RTP-UJI-A','Petugas timbang','Koreksi bacaan kedua',
                    '250','225')'''))
        await db.commit()
        pelaku=await db.get(User, asal['uid'])
    assert await terima(pg, r.id) is None
    assert await terima(pg, r.id, manual=True, pelaku=pelaku)
    async with pg() as db:
        logs = (await db.scalars(select(ReturPemeriksaanLog))).all()
        hasil = [l.sesudah.get('hasil') for l in logs if l.sesudah.get('hasil')]
        assert any(h.get('koreksi_timbang', {}).get('nama') == 'Petugas timbang'
                   for h in hasil if h.get('koreksi_timbang'))


async def test_tara_master_belum_lengkap_tidak_menerima_stok(pg, asal):
    async with pg() as db:
        await db.execute(text('DELETE FROM kemasan_tara'))
        await db.commit()
    await selesai(pg, asal)
    r = await simpan(pg, asal, 10)
    assert r.status_pemeriksaan == 'tertahan'
    assert r.hasil_pemeriksaan['toleransi_kg'] is None
    assert await terima(pg, r.id) is None
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock)) == 0


async def test_endpoint_lama_tidak_dapat_menimpa_rincian_berasal(pg, asal):
    from tests.pg.test_barang_keluar import _klien
    r = await simpan(pg, asal, 10)
    c = await _klien(pg, asal['uid'], 'uji_endpoint_lama')
    async with pg() as db:
        sku_id=(await db.get(OutgoingItem, asal['iid'])).product_sku_id
    async with c:
        token=(await c.get('/api/sesi-formulir')).json()['token']
        hasil=await c.post('/retur/terima',data=dict(_csrf=token,
            timbangan_transaksi_id=str(asal['tiket'][0]),sku_id=str(sku_id),quality_id='',
            jumlah_karung='12',catatan_item='',aksi='rincian'))
        assert 'gagal=' in hasil.headers['location']
    async with pg() as db:
        assert (await db.get(ReturRincian, r.id)).muatan[0]['jumlah_karung'] == 10


async def test_layar_menunggu_koreksi_manual_dan_diterima(pg, asal):
    """HTML bukti berasal dari rute aplikasi dan data yang sama pada tiap tahap."""
    import os
    from pathlib import Path
    from tests.pg.test_barang_keluar import _klien
    folder = Path(os.environ['BUKTI_RETUR_DIR']) if os.environ.get('BUKTI_RETUR_DIR') else None
    if folder:
        folder.mkdir(parents=True, exist_ok=True)
    def simpan_html(nama, respons):
        assert respons.status_code == 200
        if folder:
            (folder / f'{nama}.html').write_text(respons.text)
    c = await _klien(pg, asal['uid'], 'uji_layar_tahapan')
    async with c:
        simpan_html('pengajuan', await c.get(f'/barang-keluar/{asal["oid"]}/retur'))
        r = await simpan(pg, asal, 9)
        simpan_html('menunggu', await c.get(f'/retur/pengajuan/{r.id}'))
        simpan_html('daftar-pengajuan', await c.get('/retur'))
        await selesai(pg, asal, 250)
        assert await terima(pg, r.id) is None
        tertahan = await c.get(f'/retur/pengajuan/{r.id}')
        simpan_html('perlu-koreksi', tertahan)
        assert 'Perlu Koreksi' in tertahan.text
        assert '<button class="btn" disabled>Verifikasi manual</button>' in tertahan.text
        r = await simpan(pg, asal, 10, pengajuan_id=r.id, alasan='Satu karung terlewat.')
        manual = await c.get(f'/retur/pengajuan/{r.id}')
        simpan_html('siap-manual', manual)
        assert '<button class="btn" >Verifikasi manual</button>' in manual.text
        token = (await c.get('/api/sesi-formulir')).json()['token']
        sukses = await c.post(f'/retur/pengajuan/{r.id}/verifikasi', data={'_csrf': token})
        assert sukses.status_code == 303
        simpan_html('diterima', await c.get(sukses.headers['location']))
        simpan_html('daftar', await c.get('/retur'))
        simpan_html('pengiriman-asal', await c.get(f'/barang-keluar/{asal["oid"]}'))


async def test_batal_pengajuan_tidak_mengubah_stok_dan_melepas_jumlah(pg, asal):
    from tests.pg.test_barang_keluar import _klien
    from app.services import barang_keluar
    r = await simpan(pg, asal, 10)
    c = await _klien(pg, asal['uid'], 'uji_batal_pengajuan')
    async with c:
        token=(await c.get('/api/sesi-formulir')).json()['token']
        hasil=await c.post(f'/retur/pengajuan/{r.id}/batalkan', data={
            '_csrf': token, 'alasan': 'Barang ternyata tidak dikembalikan.'})
        assert 'pesan=' in hasil.headers['location']
    async with pg() as db:
        rincian=await db.get(ReturRincian,r.id)
        assert rincian.status_pemeriksaan == 'dibatalkan'
        assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock)) == 0
        # Undo pengiriman kembali tersedia setelah klaim draf dilepas.
        await barang_keluar.balik_verifikasi(db,rec_id=asal['oid'])
        await db.rollback()
    assert await simpan(pg, asal, 20, tiket=1)


async def test_pembatalan_dan_penerimaan_bersamaan_konsisten(pg, asal):
    await selesai(pg, asal)
    r=await simpan(pg, asal, 10)
    async def batal():
        async with pg() as db:
            pelaku=await db.get(User,asal['uid'])
            hasil=await layanan.batalkan(db,identitas=r.id,pelaku=pelaku,alasan='Batal terima.')
            await db.commit()
            return hasil
    hasil=await asyncio.gather(terima(pg,r.id),batal(),return_exceptions=True)
    assert sum(not isinstance(h, Exception) for h in hasil) == 1
    async with pg() as db:
        rincian=await db.get(ReturRincian,r.id)
        n=await db.scalar(select(func.count()).select_from(FinishedGoodsStock))
        assert (rincian.customer_return_id is not None) == (n == 1)
        if rincian.status_pemeriksaan == 'dibatalkan':
            assert n == 0
