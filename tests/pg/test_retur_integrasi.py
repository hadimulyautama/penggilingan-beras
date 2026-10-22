"""Rincian Produksi mendahului timbang kedua; stok baru ada sesudah verifikasi."""
from types import SimpleNamespace
from urllib.parse import unquote
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select, text, func

from app.models import User, ProductSku, PackagingMaterial, PackageSize, CustomerReturn, FinishedGoodsStock
from app.penggilingan.inventory.models import ReturRincian
from app.web import layar_retur, internal
from app.web.security import butuh_akun
from app.peran import PERAN_ADMIN_KEATAS

PERAN_ADMIN = PERAN_ADMIN_KEATAS[-1]

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def konteks(pg, monkeypatch):
    async with pg() as db:
        user = User(nama='Penerima retur', role=PERAN_ADMIN, status='aktif')
        material = PackagingMaterial(kode='uji-retur', nama='Karung retur', aktif=True)
        size = PackageSize(ukuran_kg=25, aktif=True)
        db.add_all([user, material, size]); await db.flush()
        sku = ProductSku(kategori='menir', packaging_material_id=material.id,
                         package_size_id=size.id, aktif=True)
        db.add(sku); await db.flush()
        # Rantai Timbangan (0029) memiliki pelebaran arah, bukan Produksi.
        await db.execute(text('ALTER TABLE timbangan_transaksi ALTER COLUMN arah TYPE varchar(16)'))
        tid = await db.scalar(text('''INSERT INTO timbangan_transaksi
            (kode,tanggal,arah,jenis_kode,timbang1_kg,status_tiket,status_transaksi,nomor_polisi)
            VALUES ('RTP-UJI',CURRENT_DATE,'RETUR_MASUK','RETUR_PELANGGAN',9000,'TERBUKA','AKTIF','AD 9 ZZ') RETURNING id'''))
        await db.commit()
        uid, sid = user.id, sku.id
    app = FastAPI()
    app.include_router(layar_retur.router); app.include_router(internal.router)
    app.dependency_overrides[butuh_akun] = lambda: SimpleNamespace(user=SimpleNamespace(id=uid, role=PERAN_ADMIN))
    monkeypatch.setattr(internal.settings, 'internal_api_token', 'token-uji')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://uji', follow_redirects=False) as c:
        yield c, tid, sid


def form(tid, sid, aksi='rincian', **ubah):
    return dict(timbangan_transaksi_id=str(tid), sku_id=str(sid), quality_id='',
                jumlah_karung='120', berat_kg='3000', tara_per_karung_kg='0.25',
                catatan_item='', aksi=aksi, **ubah)


async def test_rincian_sebelum_timbang_kedua_dan_stok_tepat_sekali(pg, konteks):
    c, tid, sid = konteks
    r = await c.post('/retur/terima', data=form(tid, sid))
    assert 'Rincian' in unquote(r.headers['location'])
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(ReturRincian)) == 1
        assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock)) == 0
        tickets, _, _, _ = await layar_retur._siapkan(db)
        assert tickets[0]['rincian'][0]['jumlah_karung'] == 120
    r = await c.get(f'/internal/retur/tiket/{tid}/muatan', headers={'X-Internal-Token': 'token-uji'})
    assert r.status_code == 200
    assert r.json()['muatan'][0]['tara_per_karung_kg'] == '0'
    # Belum ditimbang kosong: penerimaan stok ditolak.
    r = await c.post('/retur/terima', data=form(tid, sid, 'terima'))
    assert 'gagal=' in r.headers['location']
    async with pg() as db:
        await db.execute(text('''UPDATE timbangan_transaksi SET status_tiket='SELESAI',
            timbang2_kg=6000, berat_barang_kg=3000, jumlah_karung=100,total_tara_kg=0 WHERE id=:id'''), {'id':tid})
        await db.commit()
    r = await c.post('/retur/terima', data=form(tid, sid, 'terima'))
    assert 'gagal=' in r.headers['location'], r.headers['location']
    r = await c.post('/retur/terima', data=form(tid, sid, 'terima'))
    assert 'gagal=' in r.headers['location']
    async with pg() as db:
        stocks = (await db.scalars(select(FinishedGoodsStock))).all()
        # Endpoint lama tidak lagi boleh menerima stok tanpa asal.
        assert not stocks


async def test_rincian_terkunci_setelah_timbang_dan_api_bertoken(pg, konteks):
    c, tid, sid = konteks
    assert (await c.get(f'/internal/retur/tiket/{tid}/muatan')).status_code == 403
    r = await c.get(f'/internal/retur/tiket/{tid}/muatan', headers={'X-Internal-Token':'token-uji'})
    assert r.status_code == 409
    await c.post('/retur/terima', data=form(tid, sid))
    async with pg() as db:
        await db.execute(text("UPDATE timbangan_transaksi SET status_tiket='SELESAI', jumlah_karung=100,total_tara_kg=0,berat_barang_kg=3000 WHERE id=:id"), {'id':tid})
        await db.commit()
    data = form(tid,sid,'terima'); data['jumlah_karung']='0'
    r = await c.post('/retur/terima', data=data)
    assert 'gagal=' in r.headers['location']
    r = await c.post('/retur/terima', data=form(tid,sid))
    assert 'gagal=' in r.headers['location']
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(CustomerReturn)) == 0


@pytest.mark.parametrize('nilai', ['NaN', 'Infinity', '-1', '1001'])
async def test_tara_dari_halaman_lama_diabaikan(pg,konteks,nilai):
    c,tid,sid=konteks
    data=form(tid,sid);data['tara_per_karung_kg']=nilai
    r=await c.post('/retur/terima',data=data)
    assert 'pesan=' in r.headers['location']
    async with pg() as db:
        rincian=await db.scalar(select(ReturRincian))
        assert rincian.muatan[0]['tara_per_karung_kg']=='0'



async def test_layar_retur_memuat_tiket_terbuka_dan_rincian(pg,konteks):
    c,tid,sid=konteks
    await c.post('/retur/terima',data=form(tid,sid))
    r=await c.get('/retur')
    assert r.status_code == 200
    assert 'Rincian lama belum terhubung' in r.text
    assert 'name="tara_per_karung_kg"' not in r.text
    assert 'RTP-UJI' in r.text
    assert 'Buka riwayat pengiriman' in r.text


async def test_rincian_beberapa_kemasan_dan_revisi_sebelum_timbang(pg,konteks):
    c,tid,sid=konteks
    data = {k: [v, v] for k,v in form(tid,sid).items()
            if k not in ('aksi','timbangan_transaksi_id')}
    data.update(aksi='rincian',timbangan_transaksi_id=str(tid))
    data['jumlah_karung']=['40','20']
    data['tara_per_karung_kg']=['0.25','0.1']
    data['berat_kg']=['1988','1000']
    r=await c.post('/retur/terima',data=data)
    assert 'pesan=' in r.headers['location']
    r=await c.get(f'/internal/retur/tiket/{tid}/muatan',headers={'X-Internal-Token':'token-uji'})
    items=r.json()['muatan']
    assert [Decimal(m['berat_kg']) for m in items]==[Decimal('1000'),Decimal('500')]
    assert sum(m['jumlah_karung']*Decimal(m['tara_per_karung_kg']) for m in items) == 0
    data['jumlah_karung']=['41','20']
    await c.post('/retur/terima',data=data)
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(ReturRincian)) == 1
        assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock)) == 0


async def test_tara_baku_sesuai_keputusan_dan_tidak_ditimpa(pg):
    from app.models import KemasanTara
    from app.services.seed import seed_master
    await seed_master()
    async with pg() as db:
        pairs=(await db.execute(select(KemasanTara,PackagingMaterial.kode,PackageSize.ukuran_kg)
            .join(PackagingMaterial,PackagingMaterial.id==KemasanTara.packaging_material_id)
            .join(PackageSize,PackageSize.id==KemasanTara.package_size_id))).all()
        nyata = {(material,size): row.tara_per_karung_kg for row,material,size in pairs}
        harapan = {
            ('biasa', 5): Decimal('0.03'),
            ('biasa', 10): Decimal('0.05'),
            ('biasa', 20): Decimal('0.05'),
            ('biasa', 25): Decimal('0.05'),
            ('biasa', 40): Decimal('0.07'),
            ('biasa', 48): Decimal('0.07'),
            ('biasa', 50): Decimal('0.07'),
            ('laminasi', 5): Decimal('0.03'),
            ('laminasi', 10): Decimal('0.05'),
            ('laminasi', 20): Decimal('0.07'),
            ('laminasi', 25): Decimal('0.08'),
            ('putih', 50): Decimal('0.07'),
            ('polos', 25): Decimal('0.05'),
            ('bekas', 20): Decimal('0.05'),
            ('bekas', 40): Decimal('0.07'),
            ('bekas', 50): Decimal('0.07'),
            ('karung_pk', 50): Decimal('0.07'),
        }
        assert nyata == harapan
        row = next(r for r,m,u in pairs if (m,u)==('laminasi',25))
        row.tara_per_karung_kg=Decimal('0.09')
        await db.commit()
    await seed_master()
    async with pg() as db:
        assert await db.scalar(select(KemasanTara.tara_per_karung_kg).join(PackagingMaterial).join(PackageSize).where(PackagingMaterial.kode=='laminasi', PackageSize.ukuran_kg==25))==Decimal('0.09')


async def test_pengiriman_menggunakan_master_tara_per_kemasan(pg,konteks,monkeypatch):
    from app.models import KemasanTara
    c,tid,sid=konteks
    async with pg() as db:
        sku=await db.get(ProductSku,sid)
        db.add(KemasanTara(packaging_material_id=sku.packaging_material_id,
                           package_size_id=sku.package_size_id,tara_per_karung_kg=Decimal('0.08')))
        await db.commit()
    async def cocok(db,tid):
        return None,SimpleNamespace(kode='OUT-UJI',nama_pembeli='Toko Uji',no_polisi='AD 9 ZZ'),[
            SimpleNamespace(item_type='finished_goods',product_sku_id=sid,rice_quality_standard_id=None,berat_kg=2500,jumlah_karung=100),
            SimpleNamespace(item_type='byproduct_curah',jenis_byproduct='bekatul',berat_kg=500,jumlah_karung=None),
        ]
    monkeypatch.setattr(internal,'_cocokkan_pengiriman_tiket',cocok)
    r=await c.get(f'/internal/pengiriman/tiket/{tid}/muatan',headers={'X-Internal-Token':'token-uji'})
    assert r.status_code==200
    muatan=r.json()['muatan']
    assert muatan[0]['tara_per_karung_kg']=='0.0800'
    assert muatan[0]['jumlah_karung']==100
    assert muatan[1]['tara_per_karung_kg']=='0'
    async with pg() as db:
        await db.execute(text('UPDATE kemasan_tara SET tara_per_karung_kg=0.09'))
        await db.commit()
    r=await c.get(f'/internal/pengiriman/tiket/{tid}/muatan',headers={'X-Internal-Token':'token-uji'})
    assert Decimal(r.json()['muatan'][0]['tara_per_karung_kg'])==Decimal('0.09')


@pytest.mark.parametrize('jenis',['pk_langsung','gabah_langsung'])
async def test_pengiriman_karung_lima_puluh_dan_tara_berbeda(pg,konteks,monkeypatch,jenis):
    from app.services.seed import seed_master
    await seed_master()
    c,tid,sid=konteks
    async def cocok(db,tid):
        return None,SimpleNamespace(kode='OUT-UJI',nama_pembeli='Toko Uji',no_polisi='AD 9 ZZ'),[
            SimpleNamespace(item_type=jenis,berat_kg=1000,jumlah_karung=20)]
    monkeypatch.setattr(internal,'_cocokkan_pengiriman_tiket',cocok)
    r=await c.get(f'/internal/pengiriman/tiket/{tid}/muatan',headers={'X-Internal-Token':'token-uji'})
    assert r.status_code==200
    assert Decimal(r.json()['muatan'][0]['tara_per_karung_kg'])==Decimal('0.07')
    if jenis=='gabah_langsung':
        async with pg() as db:
            await db.execute(text("UPDATE kemasan_tara SET tara_per_karung_kg=0.1 WHERE packaging_material_id=(SELECT id FROM packaging_materials WHERE kode='putih')"))
            await db.commit()
        r=await c.get(f'/internal/pengiriman/tiket/{tid}/muatan',headers={'X-Internal-Token':'token-uji'})
        assert r.status_code==409


async def test_terima_retur_setelah_timbang_tanpa_rincian_awal_atau_tara(pg,konteks):
    c,tid,sid=konteks
    async with pg() as db:
        await db.execute(text("UPDATE timbangan_transaksi SET status_tiket='SELESAI',timbang2_kg=6000,berat_barang_kg=3000,jumlah_karung=0,total_tara_kg=0 WHERE id=:id"),{'id':tid})
        await db.commit()
    data=form(tid,sid,'terima')
    data.pop('tara_per_karung_kg')
    r=await c.post('/retur/terima',data=data)
    assert 'gagal=' in r.headers['location']
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock)) == 0


async def test_pilihan_retur_dari_master_meski_sku_belum_pernah_dibuat(pg,konteks):
    from app.services.seed import seed_master
    from app.models import Brand
    from app.services.retur import katalog
    await seed_master()
    c,tid,sid=konteks
    async with pg() as db:
        sebelum=await db.scalar(select(func.count()).select_from(ProductSku))
        pilihan=await katalog(db)
        assert list(pilihan['jenis'])==['beras_putih','broken','menir','reject']
        assert {k['nilai'] for k in pilihan['kemasan']['broken']}=={'putih:50','polos:25'}
        assert {k['nilai'] for k in pilihan['kemasan']['menir']}=={'putih:50'}
        assert {k['nilai'] for k in pilihan['kemasan']['reject']}=={'bekas:50'}
        assert 'laminasi:25' in {k['nilai'] for k in pilihan['kemasan']['beras_putih']}
        assert 'laminasi:50' not in {k['nilai'] for k in pilihan['kemasan']['beras_putih']}
        assert pilihan['merek']
    r=await c.get('/retur')
    assert r.status_code==200
    assert 'Buka riwayat pengiriman' in r.text
    assert 'name="jenis_barang"' not in r.text  # Jenis baru diturunkan dari item asal.
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(ProductSku))==sebelum


@pytest.mark.parametrize('jenis,kemasan',[
    ('beras_putih','laminasi:25'),('broken','polos:25'),
    ('menir','putih:50'),('reject','bekas:50'),
])
async def test_retur_jenis_kemasan_dan_merek_membuat_sku_saat_disimpan(pg,konteks,jenis,kemasan):
    from app.services.seed import seed_master
    from app.models import Brand,RiceQualityStandard
    await seed_master()
    c,tid,sid=konteks
    nominal=100*int(kemasan.split(':')[1])
    async with pg() as db:
        brand=await db.scalar(select(Brand).where(Brand.aktif.is_(True)))
        quality=await db.scalar(select(RiceQualityStandard).where(RiceQualityStandard.aktif.is_(True)))
        bid,qid=brand.id,quality.id
        await db.commit()
    r=await c.post('/retur/terima',data={
        'timbangan_transaksi_id':str(tid),'aksi':'rincian',
        'jenis_barang':jenis,'kemasan':kemasan,
        'brand_id':str(bid) if jenis=='beras_putih' else '',
        'quality_id':str(qid) if jenis=='beras_putih' else '',
        'jumlah_karung':'100','berat_kg':'3000','catatan_item':'',
    })
    assert 'pesan=' in r.headers['location'],unquote(r.headers['location'])
    async with pg() as db:
        rincian=await db.scalar(select(ReturRincian))
        sku=await db.get(ProductSku,rincian.muatan[0]['sku_id'])
        assert Decimal(rincian.muatan[0]['berat_kg'])==Decimal(nominal)
        assert sku.id!=sid and sku.kategori==jenis
        material=await db.get(PackagingMaterial,sku.packaging_material_id)
        size=await db.get(PackageSize,sku.package_size_id)
        assert f'{material.kode}:{size.ukuran_kg}'==kemasan
        assert sku.brand_id==(bid if jenis=='beras_putih' else None)
        assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock)) == 0


@pytest.mark.parametrize('jenis,kemasan,brand',[
    ('beras_putih','laminasi:25',''),('broken','polos:25','1'),
    ('menir','polos:25',''),('beras_putih','laminasi:50','1'),
    ('pk','karung_pk:50',''),('broken','polos:100',''),
])
async def test_retur_menolak_pilihan_jenis_kemasan_merek_tak_sah(pg,konteks,jenis,kemasan,brand):
    from app.services.seed import seed_master
    await seed_master()
    c,tid,sid=konteks
    r=await c.post('/retur/terima',data={
        'timbangan_transaksi_id':str(tid),'aksi':'rincian',
        'jenis_barang':jenis,'kemasan':kemasan,'brand_id':brand,
        'quality_id':'','jumlah_karung':'100','berat_kg':'3000','catatan_item':'',
    })
    assert 'gagal=' in r.headers['location']
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(ReturRincian))==0
        assert await db.scalar(select(func.count()).select_from(ProductSku))==1


@pytest.mark.parametrize('aktual,selisih',[(2940,-60),(3060,60),(3000,0)])
@pytest.mark.parametrize('kiriman_berat',[None,'1'])
async def test_berat_retur_otomatis_dan_selisih_tiket_dikurangi_rincian(pg,konteks,aktual,selisih,kiriman_berat):
    from app.services.seed import seed_master
    from app.models import Brand,RiceQualityStandard
    await seed_master()
    c,tid,sid=konteks
    async with pg() as db:
        brand=await db.scalar(select(Brand).where(Brand.aktif.is_(True)))
        mutu=await db.scalar(select(RiceQualityStandard).where(RiceQualityStandard.aktif.is_(True)))
        bid,qid=brand.id,mutu.id
        await db.execute(text("UPDATE timbangan_transaksi SET status_tiket='SELESAI',timbang2_kg=6000,berat_barang_kg=:berat WHERE id=:id"),{'id':tid,'berat':aktual})
        await db.commit()
    data={'timbangan_transaksi_id':str(tid),'aksi':'terima',
        'jenis_barang':'beras_putih','kemasan':'biasa:25','brand_id':str(bid),'quality_id':str(qid),
        'jumlah_karung':'120','catatan_item':''}
    if kiriman_berat is not None:
        data['berat_kg']=kiriman_berat
    # Aturan baru menghapus jalan lolos hanya dengan alasan. Penghitungan
    # dan penerimaan beridentitas asal diuji pada test_retur_pengajuan.
    for alasan in ('', 'Isi beberapa karung tidak penuh'):
        data['alasan_selisih']=alasan
        r=await c.post('/retur/terima',data=data)
        assert 'gagal=' in r.headers['location']
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(CustomerReturn)) == 0
        assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock)) == 0


async def test_retur_diterima_tabel_dan_detail_lengkap(pg, konteks):
    from pathlib import Path
    c, tid, sid = konteks
    await c.post('/retur/terima', data=form(tid, sid))
    async with pg() as db:
        await db.execute(text("""UPDATE timbangan_transaksi SET status_tiket='SELESAI',
            timbang2_kg=6010,berat_barang_kg=2990,netto_timbangan_kg=2990,
            nama_sopir='Sopir Retur' WHERE id=:id"""), {'id': tid})
        await db.commit()
    # Histori sebelum hubungan asal diwajibkan tetap harus terbaca. Fixture
    # dibuat langsung sebagai fakta lama; endpoint baru wajib menolak asal kosong.
    from app.database import now_local
    from app.models import CustomerReturnItem
    async with pg() as db:
        retur=CustomerReturn(kode='RET-HISTORI',timbangan_transaksi_id=tid,kode_tiket='RTP-UJI',
            timbang1_kg=9000,timbang2_kg=6010,berat_tiket_kg=2990,
            berat_rincian_kg=3000,selisih_kg=-10,alasan_selisih='Isi karung berkurang',
            catatan='Kemasan diperiksa',input_by=1,waktu=now_local())
        db.add(retur); await db.flush()
        db.add(CustomerReturnItem(customer_return_id=retur.id,product_sku_id=sid,
            jumlah_karung=120,berat_total_kg=3000,catatan='Karung terbuka'))
        await db.commit()
        rid,kode=retur.id,retur.kode
    daftar = await c.get('/retur')
    detail = await c.get(f'/retur/{rid}')
    assert daftar.status_code == detail.status_code == 200
    assert f'href="/retur/{rid}"' in daftar.text
    for isi in [kode,'RTP-UJI','Sopir Retur','Penerima retur','Karung retur',
                'Karung terbuka','Isi karung berkurang','Kemasan diperiksa','120']:
        assert isi in detail.text
    assert 'id="return-form"' not in detail.text
    assert (await c.get('/retur/9999999')).status_code == 404
    Path('/tmp/hmu-retur-daftar.html').write_text(daftar.text)
    Path('/tmp/hmu-retur-detail.html').write_text(detail.text)


async def test_detail_retur_tetap_membutuhkan_admin(konteks):
    c, _, _ = konteks
    c._transport.app.dependency_overrides[butuh_akun] = lambda: SimpleNamespace(
        user=SimpleNamespace(id=1, role='operator'))
    assert (await c.get('/retur/1')).status_code == 403
