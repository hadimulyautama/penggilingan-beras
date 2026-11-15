"""PK hasil giling dapat langsung menuju pabrik lain dalam satu perusahaan."""
import uuid
from decimal import Decimal
import pytest
from sqlalchemy import select
from app.models import User,Warehouse,PermintaanPk,InternalTransfer,PkGudang2Intake,Silo
from app.services import transfer_barang as umum,pengiriman_pk as pk
from tests.pg.test_permintaan_empat_langkah import pabrik

pytestmark=pytest.mark.asyncio


@pytest.fixture
async def antar_pabrik(pg,pabrik):
    from hmu_core.organisasi import Perusahaan,LokasiPabrik,PenempatanGudang
    async with pg() as db:
        company=Perusahaan(kode='PK-ANTARPABRIK',nama='Perusahaan PK');db.add(company);await db.flush()
        a=LokasiPabrik(company_id=company.id,kode='ASAL',nama='Pabrik Asal')
        b=LokasiPabrik(company_id=company.id,kode='TUJUAN',nama='Pabrik Tujuan');db.add_all([a,b]);await db.flush()
        target=Warehouse(nama_gudang='Gudang PK Pabrik Tujuan');db.add(target);await db.flush()
        for u,lid in [(pabrik['op1'],a.id),(pabrik['op2'],a.id)]:
            user=await db.get(User,u);db.add(PenempatanGudang(warehouse_id=user.default_warehouse_id,company_id=company.id,lokasi_pabrik_id=lid))
        db.add(PenempatanGudang(warehouse_id=target.id,company_id=company.id,lokasi_pabrik_id=b.id))
        silo=Silo(nama_silo='Silo PK Tujuan',warehouse_id=target.id,aktif=True,komoditas_diizinkan=['pk'],kapasitas_ton=10)
        db.add(silo);await db.commit()
        return dict(**pabrik,target=target.id,silo_tujuan=silo.id,pabrik_tujuan=b.id)


@pytest.mark.parametrize('lokasi',['tumpukan','silo'])
async def test_pk_langsung_ke_pabrik_tujuan_tanpa_melalui_gudang_dua(pg,antar_pabrik,lokasi):
    from app.services.transfer import saldo_pk
    from app.penggilingan.gudang2.service import hitung_stok_tumpukan,hitung_stok_silo
    w=antar_pabrik
    async with pg() as db:
        out=await umum.minta(db,user=await db.get(User,w['op1']),jenis='pk_giling',id=str(w['proses_id'])+'~0',tujuan_id=w['target'],jumlah='1152',kunci_kiriman=uuid.uuid4().hex)
        rid=out['id'];assert rid>0
    async with pg() as db:
        assert await saldo_pk(db,w['proses_id'])==6000
        r=await db.get(PermintaanPk,rid);assert r.tujuan_warehouse_id==w['target']
        await pk.setujui_banyak(db,user=await db.get(User,w['admin']),items=[dict(permintaan_id=rid,berat_kg='1152',tujuan=('gudang:'+str(w['target']) if lokasi=='tumpukan' else 'silo:'+str(w['silo_tujuan'])))])
    async with pg() as db:
        assert await saldo_pk(db,w['proses_id'])==6000
        await pk.buat(db,user=await db.get(User,w['op1']),items=[dict(permintaan_id=rid,berat_kg='1152')],kunci=uuid.uuid4().hex,pakai_kendaraan=False)
    async with pg() as db:
        t=await db.scalar(select(InternalTransfer));i=await db.scalar(select(PkGudang2Intake))
        assert t.tujuan_warehouse_id==i.warehouse_id==w['target']
        assert t.jasa_id==i.jasa_id is None
        assert t.berat_kg==i.berat_kg==Decimal('1152')
        assert t.jumlah_karung==23 and t.berat_curah_kg==2
        assert await saldo_pk(db,w['proses_id'])==4848
        assert await hitung_stok_tumpukan(db)==0
        if lokasi=='tumpukan':assert await hitung_stok_tumpukan(db,warehouse_id=w['target'])==1152
        else:assert await hitung_stok_silo(db,w['silo_tujuan'])==1152


@pytest.mark.parametrize('width',[390,1440])
async def test_formulir_pk_antarpabrik_memakai_karung_50_dan_tujuan_silo_yang_benar(pg,antar_pabrik,width):
    from playwright.async_api import expect
    from tests.pg.test_transfer_pk_halaman import browser_app,BASE
    w=antar_pabrik
    async with browser_app(pg,peran='operator',gudang='Gudang PK Pabrik Tujuan',width=width) as (page,_,_):
        await page.goto(BASE+'/transfer-bertahap')
        await page.locator('#tp-minta-konteks').click()
        await expect(page.locator('#tb-pesan')).to_contain_text('sumber tersedia')
        await page.locator('#tb-cari-form [name=jenis]').select_option('pk_giling')
        await page.locator('#tb-cari-form').get_by_role('button',name='Cari sumber').click()
        await page.locator('#tb-sumber article').filter(has_text=w['lot']).get_by_role('button',name='Pilih sumber ini').click()
        await page.locator('#tb-form [name=karung_pk]').fill('23')
        await page.locator('#tb-form [name=curah_pk]').fill('2')
        await expect(page.locator('#tb-bobot')).to_have_text('Total 1.152 kg')
        await expect(page.locator('#tb-form [name=pabrik]')).to_have_value(str(w['pabrik_tujuan']))
        await expect(page.locator('#tb-form [name=pabrik]')).to_be_disabled()
        await expect(page.locator('#tb-form [name=gudang]')).to_have_value(str(w['target']))
        await expect(page.locator('#tb-form [name=gudang]')).to_be_disabled()
        assert await page.locator('#tb-form').evaluate('e=>e.checkValidity()')
        await page.locator('#tb-simpan').click()
        await expect(page.locator('#tb-panel')).not_to_be_visible()
        await expect(page.locator('#pk-daftar')).to_contain_text('Pabrik Tujuan')
    async with browser_app(pg,peran='admin',gudang=None,width=width) as (page,_,_):
        await page.goto(BASE+'/transfer-bertahap')
        await page.locator('[data-catatan]:visible').click()
        await page.locator('#pk-form [name=tujuan]').select_option('silo:'+str(w['silo_tujuan']))
        await page.locator('#pk-simpan').click()
        await expect(page.locator('#pk-pesan')).to_contain_text('telah disetujui')
    async with browser_app(pg,peran='operator',gudang='Gudang 1',width=width) as (page,_,_):
        await page.goto(BASE+'/transfer-bertahap')
        await page.locator('[data-catatan]:visible').click()
        await expect(page.locator('#pk-form [name=jumlah_karung]')).to_have_value('23')
        await expect(page.locator('#pk-form [name=berat_curah_kg]')).to_have_value('2.00')
        await page.locator('#pk-simpan').click()
        await expect(page.locator('#pk-pesan')).to_contain_text('Stok asal dan tujuan sudah diperbarui')
        await expect(page.locator('#pk-jalan')).to_contain_text('Pabrik Tujuan')
        await expect(page.locator('#pk-jalan')).to_contain_text('Silo PK Tujuan')
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')


@pytest.mark.parametrize('masuk_silo',[False,True])
async def test_koreksi_hulu_mengikuti_transfer_lokasi_lanjutan_tanpa_mutasi_ganda(pg,antar_pabrik,masuk_silo):
    from app.models import PengirimanPkItem,TransferBarangItem,PermintaanTransferBarang
    from app.services import koreksi_transfer_pk as correction
    from app.penggilingan.gudang2.service import pindah_tumpukan_ke_silo,hitung_stok_tumpukan,hitung_stok_silo
    w=antar_pabrik
    async with pg() as db:
        operator=User(nama='Operator pabrik tujuan',role='operator',status='aktif',default_warehouse_id=w['target'])
        db.add(operator);await db.commit();operator_id=operator.id
    async with pg() as db:
        r=await umum.minta(db,user=await db.get(User,w['op1']),jenis='pk_giling',id=str(w['proses_id'])+'~0',tujuan_id=w['target'],jumlah='1000',kunci_kiriman=uuid.uuid4().hex)
        rid=r['id']
    async with pg() as db:await pk.setujui_banyak(db,user=await db.get(User,w['admin']),items=[dict(permintaan_id=rid,berat_kg='1000',tujuan='gudang:'+str(w['target']))])
    async with pg() as db:await pk.buat(db,user=await db.get(User,w['op1']),items=[dict(permintaan_id=rid,berat_kg='1000')],kunci=uuid.uuid4().hex,pakai_kendaraan=False)
    async with pg() as db:
        intake=await db.scalar(select(PkGudang2Intake));intake_id=intake.id
        kembali=await db.get(User,w['op2']);warehouse_id=kembali.default_warehouse_id
        r=await umum.minta(db,user=await db.get(User,operator_id),jenis='pk_tumpukan',id=str(intake_id)+'~0',tujuan_id=warehouse_id,jumlah='1000',kunci_kiriman=uuid.uuid4().hex)
        lanjut=-r['id']
    async with pg() as db:await umum.setujui_banyak(db,user=await db.get(User,w['admin']),items=[dict(permintaan_id=lanjut,berat_kg='1000',tujuan='gudang:'+str(warehouse_id))])
    async with pg() as db:await umum.buat(db,user=await db.get(User,operator_id),items=[dict(permintaan_id=lanjut,berat_kg='1000')],kunci_kiriman=uuid.uuid4().hex)
    silo_id=None
    if masuk_silo:
        async with pg() as db:
            silo=await db.scalar(select(Silo).where(Silo.warehouse_id==warehouse_id,Silo.nama_silo=='Silo A'));silo_id=silo.id
            await pindah_tumpukan_ke_silo(db,user=await db.get(User,w['op2']),intake_id=intake_id,nama_silo=silo.nama_silo,berat=1000)
    req=dict(aksi='jumlah',berat_kg='900',alasan='Bobot sumber diperiksa ulang setelah transfer lokasi',kunci=uuid.uuid4().hex)
    async with pg() as db:
        item=await db.scalar(select(PengirimanPkItem));item_id=item.id
        review=await correction.periksa(db,jenis='transfer',ident=item_id,req=req,user=await db.get(User,w['admin']))
        assert len(review['rancangan']['barang_lokasi'])==1
        assert (await db.scalar(select(TransferBarangItem))).jumlah==1000
        assert (await db.get(PkGudang2Intake,intake_id)).berat_kg==1000
    req.update(pemeriksaan=review['pemeriksaan'],konfirmasi=True)
    async with pg() as db:await correction.simpan(db,jenis='transfer',ident=item_id,req=req,user=await db.get(User,w['admin']))
    async with pg() as db:
        assert (await db.scalar(select(TransferBarangItem))).jumlah==900
        assert (await db.get(PkGudang2Intake,intake_id)).berat_kg==900
        assert (await db.get(PermintaanTransferBarang,lanjut)).ditutup
        assert await hitung_stok_tumpukan(db,warehouse_id=w['target'])==0
        if masuk_silo:assert await hitung_stok_silo(db,silo_id)==900
        else:assert await hitung_stok_tumpukan(db,warehouse_id=warehouse_id)==900


async def test_pk_yang_sudah_beralih_pemilik_bisa_transfer_lokasi_tanpa_mengalihkannya_lagi(pg,antar_pabrik):
    from app.models import Pelanggan,Jasa
    from app.services import pk_kepemilikan as milik,pk_persediaan
    w=antar_pabrik
    async with pg() as db:
        out=await umum.minta(db,user=await db.get(User,w['op1']),jenis='pk_giling',id=str(w['proses_id'])+'~0',tujuan_id=w['target'],jumlah='1000',kunci_kiriman=uuid.uuid4().hex)
        rid=out['id']
    async with pg() as db:await pk.setujui_banyak(db,user=await db.get(User,w['admin']),items=[dict(permintaan_id=rid,berat_kg='1000',tujuan='gudang:'+str(w['target']))])
    async with pg() as db:await pk.buat(db,user=await db.get(User,w['op1']),items=[dict(permintaan_id=rid,berat_kg='1000')],kunci=uuid.uuid4().hex,pakai_kendaraan=False)
    async with pg() as db:
        intake=await db.scalar(select(PkGudang2Intake));iid=intake.id
        c=Pelanggan(nama_pelanggan='Pemilik PK tetap');db.add(c);await db.flush()
        j=Jasa(kode='JAS-TRANSFER-PK',pelanggan_id=c.id,status='berjalan');db.add(j);await db.flush();jid=j.id
        req=dict(sumber='tumpukan:'+str(iid),warehouse_id=w['target'],dari=None,ke=jid,quantity='1000',reason='Pengalihan sebelum transfer lokasi',key=uuid.uuid4().hex)
        review=await milik.periksa_awal(db,user=await db.get(User,w['admin']),req=req)
        req.update(review=review['review'],baseline=review['baseline'],confirm=True)
        await milik.simpan_awal(db,user=await db.get(User,w['admin']),req=req);await db.commit()
        dest=(await db.get(User,w['op2'])).default_warehouse_id
        out=await umum.minta(db,user=await db.get(User,w['admin']),jenis='pk_tumpukan',id=str(iid)+'~'+str(jid),tujuan_id=dest,jumlah='1000',kunci_kiriman=uuid.uuid4().hex);rr=-out['id']
    async with pg() as db:await umum.setujui_banyak(db,user=await db.get(User,w['admin']),items=[dict(permintaan_id=rr,berat_kg='1000',tujuan='gudang:'+str(dest))])
    async with pg() as db:await umum.buat(db,user=await db.get(User,w['admin']),items=[dict(permintaan_id=rr,berat_kg='1000')],kunci_kiriman=uuid.uuid4().hex)
    async with pg() as db:
        intake=await db.get(PkGudang2Intake,iid);source=(await pk_persediaan.baca(db))['tumpukan:'+str(iid)]
        assert intake.warehouse_id==dest and intake.jasa_id is None
        assert source.stok.saldo(jid)==1000 and source.stok.saldo(None)==0


async def test_permintaan_dari_detail_pk_tetap_bisa_disetujui_ke_pabrik_lain(pg,antar_pabrik):
    from app.services import permintaan_pk
    from tests.pg.test_riwayat_giling import _klien
    w=antar_pabrik
    async with pg() as db:
        r=await permintaan_pk.minta(db,user=await db.get(User,w['op2']),kode_proses=w['lot'],berat=1000)
        rid=r.id
    async with await _klien(pg,peran='admin') as c:
        r=await c.get('/api/transfer-bertahap');assert r.status_code==200
        data=r.json();request=next(x for x in data['permintaan'] if x['id']==rid)
        assert request['multilokasi']
        assert any(t['nilai']=='gudang:'+str(w['target']) for t in data['tujuan_pk'])
    async with pg() as db:
        await pk.setujui_banyak(db,user=await db.get(User,w['admin']),items=[dict(permintaan_id=rid,berat_kg='1000',tujuan='gudang:'+str(w['target']))])
        assert (await db.get(PermintaanPk,rid)).tujuan_warehouse_id==w['target']
