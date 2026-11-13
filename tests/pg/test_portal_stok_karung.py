import json
from pathlib import Path

import pytest
import pytest_asyncio
from bs4 import BeautifulSoup
from sqlalchemy import select

from app.database import now_local
from app.models import (User,Warehouse,Silo,PackagingMaterial,PackageSize,Brand,PackagingPurchase,
    ProductSku,RiceQualityStandard,FinishedGoodsStock,PkPurchaseBatch)
from tests.pg.test_portal_pelanggan import portal,client  # noqa: F401
from tests.pg.test_riwayat_qc_detail import qc  # noqa: F401
from tests.pg.test_portal_alur_hp import alur  # noqa: F401
from tests.pg.test_portal_transaksi_detail import transaksi  # noqa: F401
from tests.pg.test_portal_catatan import catatan  # noqa: F401

pytestmark=pytest.mark.asyncio


@pytest_asyncio.fixture
async def stok_karung(pg,portal,alur):
    from app.penggilingan.gudang2 import service as g2
    paths=dict(alur)
    async with pg() as db:
        mat=await db.scalar(select(PackagingMaterial).where(PackagingMaterial.kode=='laminasi'))
        if mat is None:mat=PackagingMaterial(kode='laminasi',nama='Karung laminasi');db.add(mat)
        size=await db.scalar(select(PackageSize).where(PackageSize.ukuran_kg==50))
        if size is None:size=PackageSize(ukuran_kg=50);db.add(size)
        brands=[Brand(nama='Cap Mitra A'),Brand(nama='Cap Privat B')];db.add_all(brands);await db.flush()
        for n,(owner,brand,lembar) in enumerate([(portal.owners[0].id,brands[0],300),
            (portal.owners[1].id,brands[1],987),(None,brands[0],555)]):
            db.add(PackagingPurchase(kode='PKP-PORTAL-'+str(n),packaging_material_id=mat.id,
                package_size_id=size.id,brand_id=brand.id,jumlah_lembar=lembar,pelanggan_id=owner,
                tanggal=now_local().date(),waktu=now_local(),input_by=1))
        std=await db.scalar(select(RiceQualityStandard).where(RiceQualityStandard.kode=='medium'))
        if std is None:std=RiceQualityStandard(kode='medium',nama='Medium');db.add(std)
        sku=ProductSku(kategori='beras_putih',brand_id=brands[0].id,
            packaging_material_id=mat.id,package_size_id=size.id);db.add(sku);await db.flush()
        warehouse=await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi=='g2'))
        db.add(FinishedGoodsStock(product_sku_id=sku.id,rice_quality_standard_id=std.id,
            source_type='polishing',source_id=portal.process[0]['sosoh'],jasa_id=portal.orders[0].id,
            jumlah_karung=20,berat_total_kg=1000,waktu=now_local(),input_by=1,warehouse_id=warehouse.id))
        user=await db.get(User,1);user.default_warehouse_id=warehouse.id
        silo=Silo(nama_silo='Silo Karung Portal',warehouse_id=warehouse.id,jenis_isi='pk',status='kosong')
        db.add(silo);await db.commit()
        for suffix,weight,source in [('TIMBANG',10140,'timbangan'),('BELUM',None,'menunggu')]:
            code='PKB-ISI-'+suffix
            batch=PkPurchaseBatch(kode_batch=code,jasa_id=portal.orders[0].id,jumlah_karung=128,
                ukuran_karung_kg=80,berat_total_kg=weight,sumber_berat=source,
                tanggal_pembelian=now_local().date(),waktu_pembelian=now_local(),input_by=1)
            db.add(batch);await db.commit()
            received=await g2.masukkan_pk_luar(db,user=user,kode=code)
            if weight is not None:await g2.pindah_tumpukan_ke_silo(db,user=user,intake_id=received.intake.id,
                nama_silo=silo.nama_silo,jumlah_karung=126)
            paths['pk_karung_'+suffix.lower()]='/pelanggan/stok/pk/detail?gudang=g2&id='+str(received.intake.id)
    return paths


async def test_dua_ukuran_karung_mempertahankan_berat_setiap_kelompok(pg,portal,stok_karung):
    from app.models import PolishingOutputLog,PolishingSiloUsage
    async with pg() as db:
        old=await db.scalar(select(ProductSku).join(Brand,Brand.id==ProductSku.brand_id).where(Brand.nama=='Cap Mitra A'))
        size=await db.scalar(select(PackageSize).where(PackageSize.ukuran_kg==25))
        if size is None:size=PackageSize(ukuran_kg=25);db.add(size);await db.flush()
        sku=ProductSku(kategori='beras_putih',brand_id=old.brand_id,packaging_material_id=old.packaging_material_id,package_size_id=size.id)
        db.add(sku);await db.flush()
        std=await db.scalar(select(RiceQualityStandard).where(RiceQualityStandard.kode=='medium'))
        db.add(FinishedGoodsStock(product_sku_id=sku.id,rice_quality_standard_id=std.id,
            source_type='polishing',source_id=portal.process[0]['sosoh'],jasa_id=portal.orders[0].id,
            jumlah_karung=4,berat_total_kg=100,kemasan_mengurangi_stok=False,waktu=now_local(),input_by=1))
        db.add(PolishingOutputLog(polishing_process_id=portal.process[0]['sosoh'],jenis='medium',berat_kg=100,waktu_update=now_local(),input_by=1))
        usage=await db.scalar(select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id==portal.process[0]['sosoh']))
        usage.berat_awal_kg=1100
        await db.commit()
    async with client(portal.accounts[0]) as c:
        response=await c.get(stok_karung['produk']);assert response.status_code==200
        s=BeautifulSoup(response.text,'html.parser')
        assert '1.100 kg' in s.select_one('.pk-detail__weight').get_text()
        groups=s.select('.pelanggan-kemasan-baris');assert len(groups)==2
        text=[r.get_text(' ',strip=True) for r in groups]
        assert any('20 karung' in t and '50 kg' in t and '1.000 kg' in t for t in text)
        assert any('4 karung' in t and '25 kg' in t and '100 kg' in t for t in text)
        out=Path('output/portal-jumlah-curah-20261101');out.mkdir(parents=True,exist_ok=True)
        (out/'multi.html').write_text(response.text)


async def test_curah_tanpa_karung_dan_sisa_otomatis_tidak_dianggap_karung_tercatat(pg,portal,stok_karung):
    from sqlalchemy import delete
    from app.models import PolishingOutputLog
    async with pg() as db:
        await db.execute(delete(FinishedGoodsStock).where(FinishedGoodsStock.jasa_id==portal.orders[0].id))
        await db.execute(delete(PolishingOutputLog).where(PolishingOutputLog.polishing_process_id==portal.process[0]['sosoh'],PolishingOutputLog.jenis=='medium'))
        db.add(PolishingOutputLog(polishing_process_id=portal.process[0]['sosoh'],jenis='medium',berat_kg=175.25,waktu_update=now_local(),input_by=1))
        db.add(PolishingOutputLog(polishing_process_id=portal.process[0]['sosoh'],jenis='broken',berat_kg=275,waktu_update=now_local(),input_by=1))
        size=await db.scalar(select(PackageSize).where(PackageSize.ukuran_kg==50))
        mat=await db.scalar(select(PackagingMaterial).where(PackagingMaterial.kode=='laminasi'))
        brand=await db.scalar(select(Brand).where(Brand.nama=='Cap Mitra A'))
        sku=ProductSku(kategori='broken',brand_id=brand.id,packaging_material_id=mat.id,package_size_id=size.id)
        db.add(sku);await db.flush()
        db.add(FinishedGoodsStock(product_sku_id=sku.id,source_type='polishing',source_id=portal.process[0]['sosoh'],jasa_id=portal.orders[0].id,jumlah_karung=2,berat_total_kg=100,waktu=now_local(),input_by=1,kemasan_mengurangi_stok=False))
        await db.commit()
    out=Path('output/portal-jumlah-curah-20261101');out.mkdir(parents=True,exist_ok=True)
    async with client(portal.accounts[0]) as c:
        r=await c.get(stok_karung['produk']);assert r.status_code==200
        s=BeautifulSoup(r.text,'html.parser');hero=s.select_one('.pk-detail__hero')
        assert '175,25' in hero.get_text() and 'Barang curah' in hero.get_text()
        assert not hero.select('.pelanggan-jumlah-berisi,.pelanggan-ukuran-nominal')
        (out/'curah.html').write_text(r.text)
        r=await c.get('/pelanggan/stok-produk-jasa/detail?jenis=broken');assert r.status_code==200
        s=BeautifulSoup(r.text,'html.parser');hero=s.select_one('.pk-detail__hero')
        assert '275' in hero.select_one('.pk-detail__weight').get_text()
        groups=[x.get_text(' ',strip=True) for x in hero.select('.pelanggan-kemasan-baris')]
        assert any('Setara sekitar 3 karung' in t and '150 kg' in t for t in groups)
        assert any('2 karung tercatat' in t and '100 kg' in t for t in groups)
        assert any('Perkiraan sisa curah' in t and '25 kg' in t and 'karung' not in t for t in groups)
        assert 'Cap Privat B' not in s.main.get_text()
        (out/'campuran.html').write_text(r.text)


async def test_sisa_pk_pecahan_tetap_ekuivalen_dan_berat_sementara_dekat_angka(pg,portal,stok_karung):
    from urllib.parse import urlsplit,parse_qs
    from datetime import datetime,timezone
    from app.models import PkGudang2Intake,OutgoingItem
    ident=int(parse_qs(urlsplit(stok_karung['pk_karung_timbang']).query)['id'][0])
    out=Path('output/portal-jumlah-curah-20261101');out.mkdir(parents=True,exist_ok=True)
    async with pg() as db:
        batch=await db.scalar(select(PkPurchaseBatch).where(PkPurchaseBatch.kode_batch=='PKB-ISI-TIMBANG'))
        batch.sumber_berat='perkiraan'
        intake=await db.get(PkGudang2Intake,ident);intake.waktu_masuk=datetime(2000,1,1,tzinfo=timezone.utc)
        outgoing=(await db.scalars(select(OutgoingItem).where(OutgoingItem.jasa_id==portal.orders[0].id,OutgoingItem.item_type=='pk_g2'))).all()
        for item in outgoing:item.berat_kg=0
        item_id=outgoing[0].id;outgoing[0].berat_kg=58.438
        await db.commit()
    async with client(portal.accounts[0]) as c:
        r=await c.get(stok_karung['pk_karung_timbang']);assert r.status_code==200
        s=BeautifulSoup(r.text,'html.parser');hero=s.select_one('.pk-detail__hero')
        assert 'Setara sekitar 1,26 karung' in hero.get_text()
        assert 'Berat sementara' in hero.select_one('.pk-detail__weight').get_text()
        assert 'Jumlah fisik karung bisa berbeda' in hero.get_text()
        assert not hero.select('.pelanggan-kemasan-baris')
        (out/'pecahan.html').write_text(r.text)
    async with pg() as db:
        item=await db.get(OutgoingItem,item_id);item.berat_kg=133.063
        await db.commit()
    async with client(portal.accounts[0]) as c:
        r=await c.get(stok_karung['pk_karung_timbang']);assert r.status_code==200
        s=BeautifulSoup(r.text,'html.parser')
        assert 'Setara kurang dari 1 karung' in s.select_one('.pk-detail__hero').get_text()
        (out/'kurang-satu.html').write_text(r.text)


async def test_barang_saya_memisahkan_karung_kosong_dari_karung_berisi_dan_detail_milik_sendiri(pg,portal,stok_karung):
    out=Path('output/portal-stok-karung-20261101');out.mkdir(parents=True,exist_ok=True)
    async with client(portal.accounts[0]) as c:
        home=BeautifulSoup((await c.get('/pelanggan/barang-saya')).text,'html.parser')
        assert not home.select('nav[aria-label="Rincian stok"]')
        assert 'Rincian stok & karung' not in home.main.get_text()
        empty=home.select_one('#karung-kosong')
        assert '280' in empty.get_text() and 'lembar kosong' in empty.get_text()
        assert 'Cap Mitra A' in empty.get_text() and 'Cap Privat B' not in home.main.get_text()
        assert 'Setara sekitar 2 karung' in home.select_one('#komoditas-pk').get_text()
        for name,path in stok_karung.items():
            response=await c.get(path);assert response.status_code==200,(name,response.text[:200])
            s=BeautifulSoup(response.text,'html.parser')
            assert len(s.select('main h1'))==1 and 'Cap Privat B' not in s.main.get_text()
            assert not s.select('[data-stok-controls],nav[aria-label="Jenis stok"]')
            (out/(name+'.html')).write_text(response.text)
        for suffix in ('timbang','belum'):
            s=BeautifulSoup((await c.get(stok_karung['pk_karung_'+suffix])).text,'html.parser')
            assert s.select_one('h1').get_text()=='Beras pecah kulit (PK)'
            if suffix=='belum':
                assert 'Berat total belum ditimbang' in s.select_one('.pk-detail__hero').get_text()
                assert '128 karung' in s.select_one('.pk-detail__weight').get_text()
                assert '0 kg' not in s.select_one('.pk-detail__weight').get_text()
            else:
                assert '158,438' in s.select_one('.pk-detail__weight').get_text()
                assert 'Setara sekitar 2 karung' in s.select_one('.pk-detail__hero').get_text()
                assert '158,4 kg' not in s.select_one('.pk-detail__hero').get_text()
        product=BeautifulSoup((await c.get(stok_karung['produk'])).text,'html.parser')
        packing=product.select_one('.pelanggan-kemasan-barang')
        assert '20 karung' in packing.get_text() and 'Ukuran karung: 50 kg (nominal)' in packing.get_text()
        assert '1.000 kg' not in packing.get_text()
        assert '1.000 kg' in product.select_one('.pk-detail__weight').get_text()
        assert packing.find_parent(class_='pk-detail__hero')
        assert 'konfirmasikan' not in product.select_one('.pk-detail__hero').get_text()
        assert product.select_one('.pelanggan-status-berat').find_parent(class_='pk-detail__hero')
        assert product.select_one('.pelanggan-status-berat').find_parent(class_='pk-detail__weight')
        assert '20 karung tercatat' in packing.get_text()
        assert not product.select('.pelanggan-stok-petunjuk')
        assert packing.find_parent('details') is None
        assert not product.select('.stok-produk-kartu summary')
        assert 'Perkiraan asal stok' in product.main.get_text()
        assert (await c.get('/pelanggan/barang-saya?pelanggan_id='+str(portal.owners[1].id))).status_code==404
    async with client(portal.accounts[1]) as c:
        r=await c.get('/pelanggan/barang-saya');s=BeautifulSoup(r.text,'html.parser')
        assert '987' in s.select_one('#karung-kosong').get_text() and 'Cap Mitra A' not in s.main.get_text()
        assert (await c.get(stok_karung['pk_karung_timbang'])).status_code==404
        assert (await c.get(stok_karung['pk_karung_belum'])).status_code==404
    async with client(portal.accounts[2]) as c:
        s=BeautifulSoup((await c.get('/pelanggan/barang-saya')).text,'html.parser')
        assert 'Belum ada karung kosong yang tercatat' in s.select_one('#karung-kosong').get_text()
        assert 'Cap Mitra A' not in s.main.get_text() and 'Cap Privat B' not in s.main.get_text()
    (out/'paths.json').write_text(json.dumps(stok_karung))


@pytest.mark.fondasi_multi
async def test_label_lokasi_portal_mengikuti_master_tanpa_mengubah_stok(pg,portal,stok_karung):
    from tests.pg.test_masuk_detail_timbang import sidik
    async with pg() as db:
        wh=await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi=='g2'))
        before=await sidik(db)
        wh.nama_gudang='Sentra Utara';await db.commit()
        after=await sidik(db)
        assert {k:v for k,v in before.items() if k!='warehouses'} == {k:v for k,v in after.items() if k!='warehouses'}
    async with client(portal.accounts[0]) as c:
        response=await c.get(stok_karung['pk_karung_timbang'])
        assert response.status_code==200
        header=BeautifulSoup(response.text,'html.parser').select_one('.pk-detail__hero')
        assert 'Sentra Utara · Tumpukan' in header.get_text(' ',strip=True)
        assert 'Gudang 2' not in header.get_text()
    async with pg() as db:
        assert await sidik(db)==after
