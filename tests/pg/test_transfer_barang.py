"""Transfer lokasi umum: pemilik, saldo fisik, audit dan transaksi tetap konsisten."""
import asyncio,uuid
from decimal import Decimal as D
import pytest
from sqlalchemy import select,func
from app.models import (User,Warehouse,FinishedGoodsStock,ByproductStock,PackagingPurchase,
    PermintaanTransferBarang,TransferBarang,TransferBarangItem,Peristiwa)
from app.services import transfer_barang as s,transfer_barang_sumber as sumber
from tests.pg.test_kepemilikan_koreksi import world
pytestmark=pytest.mark.asyncio


@pytest.fixture
async def lokasi(pg,world):
    w=world
    async with pg() as db:
        target=await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi=='g1'))
        op=User(nama='Operator asal transfer',role='operator',status='aktif',default_warehouse_id=w['wh'])
        penerima=User(nama='Operator penerima transfer',role='operator',status='aktif',default_warehouse_id=target.id)
        db.add_all([op,penerima])
        from hmu_core.organisasi import Perusahaan,LokasiPabrik,PenempatanGudang
        company=Perusahaan(kode='TRANSFER',nama='Perusahaan Transfer');db.add(company);await db.flush()
        sites=[LokasiPabrik(company_id=company.id,kode='ASAL',nama='Pabrik Asal'),LokasiPabrik(company_id=company.id,kode='TUJUAN',nama='Pabrik Tujuan')]
        db.add_all(sites);await db.flush()
        db.add_all([PenempatanGudang(warehouse_id=w['wh'],company_id=company.id,lokasi_pabrik_id=sites[0].id),PenempatanGudang(warehouse_id=target.id,company_id=company.id,lokasi_pabrik_id=sites[1].id)])
        await db.commit()
        return dict(**w,target=target.id,operator=op.id,penerima=penerima.id)


async def minta(pg,w,jenis,id,n,**kw):
    async with pg() as db:
        r=await s.minta(db,user=await db.get(User,kw.get('user',w['user'])),jenis=jenis,id=str(id),tujuan_id=kw.get('target',w['target']),jumlah=str(n),kunci_kiriman=kw.get('key',uuid.uuid4().hex))
        return -r['id']


async def approve(pg,w,rid,n):
    async with pg() as db:
        return await s.setujui_banyak(db,user=await db.get(User,w['user']),items=[dict(permintaan_id=rid,berat_kg=str(n),tujuan='gudang:'+str(w['target']))])


async def catat(pg,w,rid,n,key=None,user=None):
    async with pg() as db:
        return await s.buat(db,user=await db.get(User,user or w['operator']),items=[dict(permintaan_id=rid,berat_kg=str(n))],kunci_kiriman=key or uuid.uuid4().hex)


@pytest.mark.parametrize('jenis,field,n',[('barang','source','20'),('curah','broken','1200.25'),('curah','bekatul','2345.67'),('karung','pack','200')])
async def test_transfer_memindahkan_lokasi_tanpa_mengubah_pemilik_atau_total(pg,lokasi,jenis,field,n):
    w=lokasi;id=w[field];M=sumber.MODEL[jenis]
    async with pg() as db:
        before=await db.get(M,id);owner=before.pelanggan_id if jenis=='karung' else before.jasa_id
        total_before=await db.scalar(select(func.sum(M.jumlah_lembar if jenis=='karung' else M.jumlah_karung if jenis=='barang' else M.berat_kg)))
        if jenis=='barang':before.berat_total_kg=D('4990');await db.commit()
    rid=await minta(pg,w,jenis,id,n)
    async with pg() as db:
        assert (await db.get(M,id)).warehouse_id==before.warehouse_id
        assert await db.scalar(select(func.count()).select_from(TransferBarang))==0
    await approve(pg,w,rid,n)
    result=await catat(pg,w,rid,n)
    async with pg() as db:
        item=await db.scalar(select(TransferBarangItem));dest=await db.get(M,item.dampak['tujuan_id'])
        assert (dest.pelanggan_id if jenis=='karung' else dest.jasa_id)==owner
        assert await db.scalar(select(func.sum(M.jumlah_lembar if jenis=='karung' else M.jumlah_karung if jenis=='barang' else M.berat_kg)))==total_before
        assert (await db.get(PermintaanTransferBarang,rid)).status=='selesai'
        assert await db.scalar(select(func.count()).select_from(Peristiwa).where(Peristiwa.jenis.in_(['pindah_kepemilikan_rinci','pindah_kepemilikan_detail'])))==0
        if jenis=='karung':
            from app.penggilingan.inventory.packaging import hitung_stok_kemasan
            assert await db.scalar(select(func.count()).select_from(PackagingPurchase))==1
            assert (await db.get(PackagingPurchase,id)).jumlah_lembar==1200
            assert await hitung_stok_kemasan(db,w['material'],w['size'],warehouse_id=w['wh'])==1000
            assert await hitung_stok_kemasan(db,w['material'],w['size'],warehouse_id=w['target'])==200
            assert await hitung_stok_kemasan(db,w['material'],w['size'])==1200
        else:
            assert dest.warehouse_id==w['target']
            assert sumber.jumlah(dest,jenis)==D(n)
            if jenis=='barang':assert dest.berat_total_kg==D('998')
        extra=await s.tambahan(db,user=await db.get(User,w['penerima']))
        assert len(extra['permintaan'])==1 and len(extra['pengiriman'])==1


async def test_retry_dan_balapan_hanya_memindahkan_satu_kali(pg,lokasi):
    w=lokasi;rid=await minta(pg,w,'barang',w['source'],30);await approve(pg,w,rid,30)
    key=uuid.uuid4().hex
    a,b=await asyncio.gather(catat(pg,w,rid,20,key),catat(pg,w,rid,20,key))
    assert a['id']==b['id']
    with pytest.raises(s.Error,match='berbeda'):await catat(pg,w,rid,21,key)
    results=await asyncio.gather(catat(pg,w,rid,10),catat(pg,w,rid,10),return_exceptions=True)
    assert sum(isinstance(x,s.Error) for x in results)==1
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(TransferBarang))==2
        assert await db.scalar(select(func.sum(TransferBarangItem.jumlah)))==30
        assert (await db.get(FinishedGoodsStock,w['source'])).jumlah_karung==70


async def test_persetujuan_memperhitungkan_sisa_persetujuan_lain(pg,lokasi):
    w=lokasi
    a=await minta(pg,w,'barang',w['source'],80);b=await minta(pg,w,'barang',w['source'],80)
    await approve(pg,w,a,80)
    with pytest.raises(s.Error,match='tidak cukup'):await approve(pg,w,b,80)
    async with pg() as db:
        assert (await db.get(PermintaanTransferBarang,b)).status=='diminta'
        assert (await db.get(FinishedGoodsStock,w['source'])).jumlah_karung==100


async def test_operator_tujuan_tidak_bisa_mencatat_atau_menyetujui(pg,lokasi):
    w=lokasi
    # Barang jasa di gudang lain tetap tertutup bagi operator penerima.
    with pytest.raises(PermissionError):await minta(pg,w,'barang',w['source'],10,user=w['penerima'])
    rid=await minta(pg,w,'barang',w['source'],10)
    async with pg() as db:
        with pytest.raises(PermissionError):await s.setujui_banyak(db,user=await db.get(User,w['operator']),items=[dict(permintaan_id=rid,berat_kg='10')])
    await approve(pg,w,rid,10)
    with pytest.raises(PermissionError):await catat(pg,w,rid,10,user=w['penerima'])
    async with pg() as db:assert await db.scalar(select(func.count()).select_from(TransferBarang))==0


async def ubah(pg,w,jenis,ident,aksi='jumlah',jumlah='10',**extra):
    from app.services import koreksi_transfer_barang as k
    req=dict(aksi=aksi,berat_kg=str(jumlah),tujuan=None,alasan='Sesuai pemeriksaan fisik',kunci=uuid.uuid4().hex,**extra)
    async with pg() as db:
        pre=await k.periksa(db,jenis=jenis,ident=ident,user=await db.get(User,w['user']),req=req)
        assert await db.scalar(select(func.count()).select_from(Peristiwa).where(Peristiwa.jenis=='koreksi_transfer_barang'))==0
    req.update(pemeriksaan=pre['pemeriksaan'],konfirmasi=True)
    async with pg() as db:
        result=await k.simpan(db,jenis=jenis,ident=ident,user=await db.get(User,w['user']),req=req)
    return result,req


@pytest.mark.parametrize('jenis,field,n,baru',[('barang','source',40,30),('curah','broken','2500.25','2000.15'),('karung','pack',400,300)])
async def test_koreksi_diperiksa_dahulu_dan_replay_tidak_mengganda(pg,lokasi,jenis,field,n,baru):
    from app.services import koreksi_transfer_barang as k
    w=lokasi;rid=await minta(pg,w,jenis,w[field],n);await approve(pg,w,rid,n);await catat(pg,w,rid,n)
    async with pg() as db:i=await db.scalar(select(TransferBarangItem));iid=i.id
    result,body=await ubah(pg,w,'transfer',iid,jumlah=baru)
    async with pg() as db:
        i=await db.get(TransferBarangItem,iid);assert i.jumlah==D(str(baru))
        assert (await db.get(PermintaanTransferBarang,rid)).status=='dikirim'
        before=raw_stok=await db.scalar(select(func.count()).select_from(Peristiwa))
        retry=await k.simpan(db,jenis='transfer',ident=iid,user=await db.get(User,w['user']),req=body)
        assert retry['ulang'] and retry['peristiwa_id']==result['peristiwa_id']
        assert await db.scalar(select(func.count()).select_from(Peristiwa))==before
        if jenis=='karung':
            from app.penggilingan.inventory.packaging import hitung_stok_kemasan
            assert await hitung_stok_kemasan(db,w['material'],w['size'],warehouse_id=w['target'])==300
            assert (await db.get(PackagingPurchase,w['pack'])).jumlah_lembar==1200
        else:
            assert sumber.jumlah(await db.get(sumber.MODEL[jenis],i.dampak['tujuan_id']),jenis)==D(str(baru))


async def test_koreksi_persetujuan_dan_buka_sisa_tidak_memindahkan_barang(pg,lokasi):
    w=lokasi;rid=await minta(pg,w,'barang',w['source'],40);await approve(pg,w,rid,40)
    result,body=await ubah(pg,w,'permintaan',rid,aksi='persetujuan',jumlah='30')
    async with pg() as db:
        assert (await db.get(PermintaanTransferBarang,rid)).jumlah_setuju==30
        assert (await db.get(FinishedGoodsStock,w['source'])).jumlah_karung==100
        assert await db.scalar(select(func.count()).select_from(TransferBarang))==0
        await s.keputusan(db,user=await db.get(User,w['user']),rid=rid,aksi='tutup-sisa',alasan='Belum jadi dipindah')
    # Helper di atas memeriksa nol koreksi pada setiap sesi; panggil periksa/simpan langsung untuk koreksi berikutnya.
    from app.services import koreksi_transfer_barang as k
    req=dict(aksi='buka',berat_kg=None,tujuan=None,alasan='Kebutuhan dilanjutkan',kunci=uuid.uuid4().hex)
    async with pg() as db:pre=await k.periksa(db,jenis='permintaan',ident=rid,user=await db.get(User,w['user']),req=req)
    req.update(pemeriksaan=pre['pemeriksaan'],konfirmasi=True)
    async with pg() as db:
        await k.simpan(db,jenis='permintaan',ident=rid,user=await db.get(User,w['user']),req=req)
        assert (await db.get(PermintaanTransferBarang,rid)).status=='disetujui'
        assert (await db.get(FinishedGoodsStock,w['source'])).jumlah_karung==100


@pytest.mark.parametrize('kind,field,n,unit',[('barang','source','20','karung'),('karung','pack','200','lembar'),('curah','broken','125.25','kg')])
async def test_operator_meminta_admin_menyetujui_operator_mencatat_dengan_satuan_sumber(pg,lokasi,kind,field,n,unit):
    from playwright.async_api import expect
    from tests.pg.test_transfer_pk_halaman import browser_app, BASE
    w=lokasi
    async with browser_app(pg,peran='operator',gudang='Gudang 2') as (page,_,_):
        await page.goto(BASE+'/transfer-bertahap')
        await page.locator('#tb-buka').click()
        await page.locator('#tb-cari-form [name=jenis]').select_option(kind)
        await page.locator('#tb-cari-form').get_by_role('button',name='Cari sumber').click()
        code='PKP-KOR-01' if kind=='karung' else 'Baris stok #'+str(w[field])
        source=page.locator('#tb-sumber article').filter(has_text=code)
        await source.get_by_role('button',name='Pilih sumber ini').click()
        await expect(page.locator('#tb-jumlah-label')).to_have_text('Jumlah diminta ('+unit+')')
        await expect(page.locator('#tb-asal')).to_contain_text('Pabrik Asal')
        await page.locator('#tb-form [name=jumlah]').fill(n)
        assert await page.locator('#tb-form').evaluate('e=>e.checkValidity()')
        await page.locator('#tb-simpan').click()
        await expect(page.locator('#tb-panel')).not_to_be_visible()
        await expect(page.locator('#pk-daftar article')).to_have_count(1)
    async with pg() as db:
        r=await db.scalar(select(PermintaanTransferBarang));rid=r.id
        assert r.status=='diminta' and r.jumlah_minta==D(n)
        assert await db.scalar(select(func.count()).select_from(TransferBarang))==0
    async with browser_app(pg,peran='admin',gudang=None) as (page,_,_):
        await page.goto(BASE+'/transfer-bertahap')
        await page.locator('[data-catatan]').click()
        await expect(page.locator('#pk-form')).to_contain_text('Setujui ('+unit+')')
        assert await page.locator('#pk-catatan').evaluate('e=>e.checkValidity()')
        await page.locator('#pk-simpan').click()
        await expect(page.locator('#pk-pesan')).to_contain_text('telah disetujui')
    async with browser_app(pg,peran='operator',gudang='Gudang 2') as (page,_,_):
        await page.goto(BASE+'/transfer-bertahap')
        await page.locator('[data-catatan]').click()
        await expect(page.locator('#pk-form')).to_contain_text('Jumlah dipindahkan ('+unit+')')
        assert await page.locator('#pk-catatan').evaluate('e=>e.checkValidity()')
        await page.locator('#pk-simpan').click()
        await expect(page.locator('#pk-pesan')).to_contain_text('Stok asal dan tujuan sudah diperbarui')
        await expect(page.locator('#pk-jalan .riwayat-list article')).to_have_count(1)
        await expect(page.locator('#pk-history-stats')).to_contain_text(unit if unit!='karung' else 'kg')
    async with pg() as db:
        assert (await db.get(PermintaanTransferBarang,rid)).status=='selesai'
        assert (await db.scalar(select(TransferBarangItem))).jumlah==D(n)
        assert await db.scalar(select(func.count()).select_from(Peristiwa).where(Peristiwa.jenis.in_(['pindah_kepemilikan','pindah_kepemilikan_detail'])))==0


async def test_stok_produk_dan_karung_mengikuti_gudang_tujuan(pg,lokasi):
    from tests.pg.test_riwayat_giling import _klien
    from app.services.stok import stok_produk
    from app.penggilingan.inventory.packaging import stok_kemasan_rinci
    w=lokasi
    async with pg() as db:
        (await db.get(FinishedGoodsStock,w['source'])).berat_total_kg=4990
        await db.commit()
    rid=await minta(pg,w,'barang',w['source'],20);await approve(pg,w,rid,20);await catat(pg,w,rid,20)
    rid=await minta(pg,w,'karung',w['pack'],200);await approve(pg,w,rid,200);await catat(pg,w,rid,200)
    async with pg() as db:
        source=await stok_produk(db,jasa_id=w['owners'][0],user=await db.get(User,w['operator']))
        target=await stok_produk(db,jasa_id=w['owners'][0],user=await db.get(User,w['penerima']))
        assert sum(D(str(k.sisa_kg)) for k in source if k.jenis=='beras_putih')==D('3992')
        assert sum(D(str(k.sisa_kg)) for k in target if k.jenis=='beras_putih')==D('998')
        bags=await stok_kemasan_rinci(db,user=await db.get(User,w['penerima']))
        assert [(b['warehouse_id'],b['lembar']) for b in bags if b['kode']=='biasa']==[(w['target'],200)]
    async with await _klien(pg,peran='operator',gudang='Gudang 1') as c:
        products=await c.get('/stok?tab=produk&pemilik=jasa&pelanggan_id='+str(w['customers'][0]))
        assert products.status_code==200,products.text
        assert '3.992' not in products.text and '998' in products.text
        bags=await c.get('/stok?tab=karung&pemilik=pabrik')
        assert bags.status_code==200,bags.text
        assert '200' in bags.text and '1.000' not in bags.text


async def test_barang_yang_baru_tiba_tidak_dikonsumsi_pengeluaran_lama_gudang_tujuan(pg,lokasi):
    from datetime import timedelta
    from app.database import now_local
    from app.models import OutgoingRecord,OutgoingItem
    from app.penggilingan.inventory.finished_goods import sisa_karung_per_sumber
    w=lokasi;now=now_local()
    async with pg() as db:
        src=await db.get(FinishedGoodsStock,w['source']);src.waktu=now-timedelta(days=10)
        old=FinishedGoodsStock(product_sku_id=w['sku'],source_type='retur',jumlah_karung=50,berat_total_kg=2500,warehouse_id=w['target'],waktu=now-timedelta(days=5),input_by=w['user'],jasa_id=w['owners'][0],kemasan_mengurangi_stok=False)
        db.add(old);await db.flush();old_id=old.id
        out=OutgoingRecord(kode='OUT-SEBELUM-TRANSFER',nama_pembeli='Pelanggan A',metode='diambil',tanggal=now.date(),waktu=now-timedelta(days=2),input_by=w['user'],warehouse_id=w['target'])
        db.add(out);await db.flush()
        db.add(OutgoingItem(outgoing_record_id=out.id,item_type='finished_goods',product_sku_id=w['sku'],jasa_id=w['owners'][0],jumlah_karung=50,berat_kg=2500))
        await db.commit()
    rid=await minta(pg,w,'barang',w['source'],20);await approve(pg,w,rid,20);await catat(pg,w,rid,20)
    async with pg() as db:
        i=await db.scalar(select(TransferBarangItem));target_id=i.dampak['tujuan_id']
        stock=await db.get(FinishedGoodsStock,target_id)
        assert stock.waktu==now-timedelta(days=10)
        assert stock.waktu_penempatan>now
        rows=await sisa_karung_per_sumber(db,w['sku'],None,jasa_id=w['owners'][0],source_type=None)
        available={r.id:n for r,n,kg in rows}
        assert available.get(old_id,0)==0 and available[target_id]==20


async def test_transfer_beda_perusahaan_ditolak_tanpa_mengubah_stok(pg,lokasi):
    from hmu_core.organisasi import Perusahaan,LokasiPabrik,PenempatanGudang
    w=lokasi
    async with pg() as db:
        binding=await db.get(PenempatanGudang,w['target'])
        other=Perusahaan(kode='LAIN',nama='Perusahaan Lain');db.add(other);await db.flush()
        site=LokasiPabrik(company_id=other.id,kode='LAIN',nama='Pabrik Lain');db.add(site);await db.flush()
        binding.company_id=other.id;binding.lokasi_pabrik_id=site.id;await db.commit()
    with pytest.raises(s.Error,match='satu perusahaan'):
        await minta(pg,w,'barang',w['source'],10)
    async with pg() as db:
        assert (await db.get(FinishedGoodsStock,w['source'])).jumlah_karung==100
        assert await db.scalar(select(func.count()).select_from(PermintaanTransferBarang))==0


async def test_gabah_utuh_batal_dan_pulihkan_tanpa_mengganti_bobot_asal(pg,lokasi):
    from app.database import now_local
    from app.models import PurchaseBatch
    from app.services import koreksi_transfer_barang as k
    w=lokasi;now=now_local()
    async with pg() as db:
        lot=PurchaseBatch(kode_batch='GB-TRANSFER-01',jasa_id=w['owners'][0],warehouse_id=w['wh'],berat_total_kg=D('1234.56'),kondisi_gabah='kering',tanggal_pembelian=now.date(),waktu_pembelian=now,input_by=w['user'],status_batch='baru',sumber_berat='manual')
        db.add(lot);await db.commit();lid=lot.id
    with pytest.raises(s.Error,match='utuh'):await minta(pg,w,'gabah',lid,'100')
    rid=await minta(pg,w,'gabah',lid,'1234.56');await approve(pg,w,rid,'1234.56');await catat(pg,w,rid,'1234.56')
    async with pg() as db:
        item=await db.scalar(select(TransferBarangItem));iid=item.id
        assert (await db.get(PurchaseBatch,lid)).warehouse_id==w['target']
    for n,wh in [('0',w['wh']),('1234.56',w['target'])]:
        req=dict(aksi='jumlah',berat_kg=n,tujuan=None,alasan='Pemeriksaan fisik lot utuh',kunci=uuid.uuid4().hex)
        async with pg() as db:pre=await k.periksa(db,jenis='transfer',ident=iid,user=await db.get(User,w['user']),req=req)
        req.update(pemeriksaan=pre['pemeriksaan'],konfirmasi=True)
        async with pg() as db:
            await k.simpan(db,jenis='transfer',ident=iid,user=await db.get(User,w['user']),req=req)
            row=await db.get(PurchaseBatch,lid)
            assert row.warehouse_id==wh and row.berat_total_kg==D('1234.56') and row.jasa_id==w['owners'][0]
            assert await db.scalar(select(func.count()).select_from(PurchaseBatch))==1


async def test_koreksi_barang_yang_sudah_dipindah_lagi_ditolak_tanpa_mutasi(pg,lokasi):
    from app.services import koreksi_transfer_barang as k
    w=lokasi;rid=await minta(pg,w,'barang',w['source'],40);await approve(pg,w,rid,40);await catat(pg,w,rid,40)
    async with pg() as db:
        item=await db.scalar(select(TransferBarangItem));iid=item.id;target=await db.get(FinishedGoodsStock,item.dampak['tujuan_id'])
        target.jasa_id=w['owners'][2];await db.commit()
    req=dict(aksi='jumlah',berat_kg='30',tujuan=None,alasan='Tidak boleh mengambil hak pemilik baru',kunci=uuid.uuid4().hex)
    async with pg() as db:
        with pytest.raises(s.Error,match='pemilik'):await k.periksa(db,jenis='transfer',ident=iid,user=await db.get(User,w['user']),req=req)
        assert (await db.get(TransferBarangItem,iid)).jumlah==40
        assert (await db.get(FinishedGoodsStock,w['source'])).jumlah_karung==60


async def test_api_validasi_csrf_otorisasi_dan_nonce(pg,lokasi):
    from tests.pg.test_riwayat_giling import _klien
    from app.web import csrf
    w=lokasi
    async with await _klien(pg,peran='operator',gudang='Gudang 2') as client:
        import re
        page=await client.get('/transfer-bertahap')
        token=re.search(r'name="formulir-sesi" content="([^"]+)"',page.text)[1];headers={'x-csrf-token':token}
        body=dict(jenis='karung',sumber_id=str(w['pack']),tujuan_id=w['target'],jumlah='100',kunci=uuid.uuid4().hex)
        assert (await client.post('/api/transfer-barang/permintaan',json=body)).status_code==403
        for bad in [dict(tujuan_id=2**40),dict(jumlah='NaN'),dict(jumlah='1.2'),dict(jenis='lain'),dict(sumber_id=str(2**40)),dict(pemilik_id=None)]:
            response=await client.post('/api/transfer-barang/permintaan',json=body|bad,headers=headers)
            assert response.status_code in (409,422),(response.status_code,response.text[:300])
        response=await client.post('/api/transfer-barang/permintaan',json=body,headers=headers)
        assert response.status_code==200,response.text
        rid=response.json()['id']
        retry=await client.post('/api/transfer-barang/permintaan',json=body,headers=headers)
        assert retry.status_code==200 and retry.json()['ulang']
        response=await client.post('/api/transfer-bertahap/setujui',json={'items':[dict(permintaan_id=rid,berat_kg='100',tujuan='gudang:'+str(w['target']))]},headers=headers)
        assert response.status_code==403,response.text
        for path in [f'/api/transfer-bertahap/koreksi/transfer/{rid}/periksa',f'/api/transfer-bertahap/koreksi/transfer/{2**40}/periksa']:
            response=await client.post(path,json=dict(aksi='jumlah',berat_kg='0',alasan='Uji batas hak',kunci=uuid.uuid4().hex),headers=headers)
            assert response.status_code in (403,422),response.text
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(PermintaanTransferBarang))==1
        assert await db.scalar(select(func.count()).select_from(TransferBarang))==0


async def test_gudang_penyimpanan_tanpa_lini_produksi_bisa_transfer_dan_membaca_stoknya(pg,lokasi):
    from bs4 import BeautifulSoup
    from hmu_core.organisasi import PenempatanGudang
    from tests.pg.test_riwayat_giling import _klien
    w=lokasi
    async with pg() as db:
        wh=Warehouse(nama_gudang='Penyimpanan satelit',kode_fungsi=None,aktif=True);db.add(wh);await db.flush()
        org=await db.scalar(select(PenempatanGudang).where(PenempatanGudang.warehouse_id==w['target']))
        db.add(PenempatanGudang(warehouse_id=wh.id,company_id=org.company_id,lokasi_pabrik_id=org.lokasi_pabrik_id))
        await db.commit();wid=wh.id
    rid=await minta(pg,w,'karung',w['pack'],200,target=wid)
    async with pg() as db:
        await s.setujui_banyak(db,user=await db.get(User,w['user']),items=[dict(permintaan_id=rid,berat_kg='200',tujuan='gudang:'+str(wid))])
    await catat(pg,w,rid,200)
    async with await _klien(pg,peran='operator',gudang='Penyimpanan satelit') as c:
        page=await c.get('/transfer-bertahap');assert page.status_code==200
        link=BeautifulSoup(page.text,'html.parser').select_one('#laci a[href="/transfer-bertahap"]')
        assert link and link.get('aria-disabled')!='true'
        data=(await c.get('/api/transfer-bertahap')).json()
        assert data['permintaan'][0]['boleh_catat'] is False
        assert data['tujuan_barang']
        bags=await c.get('/stok?tab=karung&pemilik=pabrik')
        assert bags.status_code==200 and '200' in bags.text
        assert '1.000' not in bags.text


async def test_api_transfer_utuh_dapat_diulang_setelah_commit(pg,lokasi):
    from tests.pg.test_riwayat_giling import _klien
    from tests.pg.formulir import cap_formulir
    w=lokasi;rid=await minta(pg,w,'barang',w['source'],100);await approve(pg,w,rid,100)
    body=dict(items=[dict(permintaan_id=-rid,berat_kg='100')],kunci=uuid.uuid4().hex)
    async with await _klien(pg,peran='operator',gudang='Gudang 2') as c:
        await c.get('/transfer-bertahap');headers={'x-csrf-token':cap_formulir(c)}
        for repeat in [False,True]:
            r=await c.post('/api/transfer-bertahap/pengiriman',json=body,headers=headers)
            assert r.status_code==200,r.text
            assert r.json()['ulang']==repeat
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(TransferBarang))==1
        assert (await db.get(FinishedGoodsStock,w['source'])).warehouse_id==w['target']


async def test_koreksi_barang_dari_browser_memakai_karung_bukan_kg(pg,lokasi):
    from playwright.async_api import expect
    from tests.pg.test_transfer_pk_halaman import browser_app,BASE
    w=lokasi;rid=await minta(pg,w,'barang',w['source'],40);await approve(pg,w,rid,40);await catat(pg,w,rid,40)
    async with browser_app(pg,peran='admin',gudang=None) as (page,_,_):
        await page.goto(BASE+'/transfer-bertahap?tab=riwayat')
        await page.locator('#pk-jalan .riwayat-list article').get_by_role('link',name='Lihat detail lengkap').click()
        await page.locator('[data-koreksi=transfer]').click()
        await expect(page.locator('#pk-koreksi-unit')).to_have_text('Jumlah yang benar (karung)')
        await page.locator('#pk-koreksi [name=berat_kg]').fill('30')
        await page.locator('#pk-koreksi [name=alasan]').fill('Hitung ulang jumlah fisik')
        await page.get_by_role('button',name='Periksa dampak',exact=True).click()
        await expect(page.locator('#pk-koreksi-dampak')).to_contain_text('karung')
        await page.locator('#pk-koreksi [name=konfirmasi]').check()
        await page.get_by_role('button',name='Simpan koreksi',exact=True).click()
        await expect(page.locator('#pk-pesan')).to_contain_text('tersimpan. Saldo')
    async with pg() as db:
        assert (await db.scalar(select(TransferBarangItem))).jumlah==30
        assert (await db.get(FinishedGoodsStock,w['source'])).jumlah_karung==70


async def test_broken_yang_dipindah_tidak_membebaskan_stok_lama_yang_sudah_keluar(pg,lokasi):
    from app.models import OutgoingRecord,OutgoingItem,Silo
    from app.database import now_local
    from app.penggilingan.gudang2 import service as g2
    w=lokasi;rid=await minta(pg,w,'curah',w['broken'],'3000');await approve(pg,w,rid,'3000');await catat(pg,w,rid,'3000')
    async with pg() as db:
        now=now_local();out=OutgoingRecord(kode='OUT-BROKEN-TRANSFER',nama_pembeli='Pemilik',metode='diambil',warehouse_id=w['wh'],tanggal=now.date(),waktu=now,input_by=w['user'])
        silo=Silo(nama_silo='Silo broken asal',warehouse_id=w['wh'],aktif=True,komoditas_diizinkan=['broken'],kapasitas_ton=10)
        db.add_all([out,silo]);await db.flush()
        db.add(OutgoingItem(outgoing_record_id=out.id,item_type='byproduct_curah',jenis_byproduct='broken',berat_kg=D('2000.55'),jasa_id=w['owners'][0]))
        await db.commit()
        with pytest.raises(g2.Gudang2Error,match='habis'):
            await g2.pindah_broken_ke_silo(db,user=await db.get(User,w['operator']),byproduct_stock_id=w['broken'],nama_silo=silo.nama_silo,berat=100)
        assert await g2.hitung_stok_silo(db,silo.id)==0
        assert (await db.get(ByproductStock,w['broken'])).berat_kg==D('2000.55')
