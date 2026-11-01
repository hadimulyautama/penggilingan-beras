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


async def test_barang_saya_memisahkan_karung_kosong_dari_karung_berisi_dan_detail_milik_sendiri(pg,portal,stok_karung):
    out=Path('output/portal-stok-karung-20261101');out.mkdir(parents=True,exist_ok=True)
    async with client(portal.accounts[0]) as c:
        home=BeautifulSoup((await c.get('/pelanggan/barang-saya')).text,'html.parser')
        assert not home.select('nav[aria-label="Rincian stok"]')
        assert 'Rincian stok & karung' not in home.main.get_text()
        empty=home.select_one('#karung-kosong')
        assert '280' in empty.get_text() and 'lembar kosong' in empty.get_text()
        assert 'Cap Mitra A' in empty.get_text() and 'Cap Privat B' not in home.main.get_text()
        assert '2 karung' in home.select_one('#komoditas-pk').get_text()
        for name,path in stok_karung.items():
            response=await c.get(path);assert response.status_code==200,(name,response.text[:200])
            s=BeautifulSoup(response.text,'html.parser')
            assert len(s.select('main h1'))==1 and 'Cap Privat B' not in s.main.get_text()
            assert not s.select('nav[aria-label="Jenis barang"],nav[aria-label="Lokasi stok"]')
            (out/(name+'.html')).write_text(response.text)
        for suffix in ('timbang','belum'):
            s=BeautifulSoup((await c.get(stok_karung['pk_karung_'+suffix])).text,'html.parser')
            assert 'Karung berisi' in s.main.get_text()
            assert s.select_one('h1').get_text()=='Beras pecah kulit (PK)'
            if suffix=='belum':
                assert 'Belum ditimbang' in s.select_one('.pk-detail__weight').get_text()
                assert '128 karung' in s.main.get_text()
                assert '0 kg' not in s.select_one('.pk-detail__weight').get_text()
            else:assert '158,438' in s.select_one('.pk-detail__weight').get_text() and 'sisa 2 karung' in s.main.get_text()
        product=BeautifulSoup((await c.get(stok_karung['produk'])).text,'html.parser')
        packing=product.select_one('.pelanggan-kemasan-barang')
        assert '20 karung' in packing.get_text() and '50 kg' in packing.get_text() and '1.000 kg' in packing.get_text()
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
