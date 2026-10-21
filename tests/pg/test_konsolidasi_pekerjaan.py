"""Penerimaan konsolidasi. Seluruh transaksi hanya pada database uji lokal."""
import json
from dataclasses import asdict
from pathlib import Path
from collections import Counter
from sqlalchemy import select,text,func
import pytest
import pytest_asyncio
from tests.pg.test_tiket_antrean_produksi import _tiket,_klien
from tests.pg.test_stok_produk_jasa import sosoh_jasa
from tests.pg.test_konsolidasi_stok import stok_lengkap
from tests.pg.formulir import cap_formulir
from app.models import PurchaseBatch,PkPurchaseBatch,FinishedGoodsStock,ByproductStock,ActivityLog,User
from app.services import berjalan as svc
from app.services.kelompok_kerja import bagi,penerimaan,dapat_ditindak

pytestmark=pytest.mark.asyncio
OUT=Path('output/konsolidasi-kerja391');OUT.mkdir(parents=True,exist_ok=True)
JENIS=('GABAH_BASAH','GABAH_KERING','BERAS_PK','BERAS_MASUK','BROKEN_MASUK')

@pytest_asyncio.fixture
async def lengkap(pg,stok_lengkap):
    from app.models import Dryer
    async with pg() as db:
        if not await db.scalar(select(Dryer.id)):
            db.add(Dryer(nama='Dryer Uji',warehouse_id=stok_lengkap['gudang']['g1']))
        ids={}
        for kind in JENIS:
            ids[kind]=await _tiket(db,'TRX-391-'+kind,kind)
        await db.commit()
    return {**stok_lengkap,'tiket':ids}

@pytest.mark.parametrize('role,gudang,lihat',[
 ('superadmin',None,None),('admin',None,None),
 ('operator','g1',None),('operator','g2',None),
 ('superadmin',None,'operator:g1'),('superadmin',None,'operator:g2'),
])
async def test_partisi_tanpa_kehilangan_kartu_dan_izin(pg,lengkap,role,gudang,lihat):
    async with await _klien(pg,role=role,gudang_id=lengkap['gudang'].get(gudang)) as c:
        if lihat:
            assert (await c.post('/lihat-sebagai',data={'peran':lihat,'_csrf':cap_formulir(c)})).status_code==303
        for path in ('/barang-masuk','/pekerjaan','/pekerjaan?tab=berjalan','/barang-masuk?status=diterima'):
            r=await c.get(path);assert r.status_code==200,(path,r.text[-1500:])
        h=(await c.get('/barang-masuk')).text
        kerja=(await c.get('/pekerjaan')).text
        for kind,tid in lengkap['tiket'].items():
            kode='TRX-391-'+kind
            scope=lihat.split(':')[-1] if lihat else gudang
            harus=(kind.startswith('GABAH') if scope=='g1' else kind=='BERAS_PK' if scope=='g2' else True)
            assert (kode in h)==harus,(role,scope,kind)
            assert kode not in kerja
            d=await c.get(f'/barang-masuk/{tid}')
            assert d.status_code==(403 if scope=='g1' and not kind.startswith('GABAH') or scope=='g2' and kind.startswith('GABAH') else 200)
        if gudang=='g2' or lihat=='operator:g2':
            assert 'buka=catat_pk_luar' not in h and 'dicatat Admin' in h
        else:
            assert ('buka=catat_pk_luar' in h)==(gudang is None and lihat is None)
        # Menunggu keputusan/QC lama tetap menolak operator langsung.
        for path in ('/keputusan','/mutu'):
            assert (await c.get(path)).status_code==(403 if gudang or lihat else 200)
    # Kartu sintetis membuktikan kasus grup campuran dan informasi: seluruh
    # atribut objek dipertahankan, bukan hanya kode yang kebetulan sama.
    a=svc.Baris('t','tiket','',aksi='gabah_masuk')
    p=svc.Baris('p','sudah diterima','',aksi='pindah_tumpukan')
    q=svc.Baris('q','mutu','',aksi='qc_giling')
    j=svc.Baris('j','aktif','',aksi='hasil_giling')
    i=svc.Baris('i','informasi','')
    t=svc.Baris('s','siap','',aksi='mulai_giling')
    lama=svc.Berjalan(menunggu=[a,p,i],transit=[t],berjalan=[j],meja=[q])
    k=bagi(lama)
    assert k.masuk==[a] and k.tindakan==[p,t,q] and k.berjalan==[j] and k.informasi==[i]
    assert Counter(map(id,k.masuk+k.tindakan+k.berjalan+k.informasi))==Counter(map(id,[a,p,i,t,j,q]))
    assert lama.lencana()['PEKERJAAN']==3 and lama.lencana()['BARANG_MASUK']==1

@pytest.mark.parametrize('kind',JENIS)
@pytest.mark.parametrize('jasa',[False,True])
async def test_penerimaan_lima_jenis_saldo_kepemilikan_tiket_dan_duplikat(pg,lengkap,kind,jasa):
    tid=lengkap['tiket'][kind]
    if jasa:
        async with pg() as db:
            await db.execute(text('UPDATE timbangan_transaksi SET jasa=true,pelanggan_id=:p,jasa_id=:j WHERE id=:i'),{'p':lengkap['pelanggan_id'],'j':lengkap['jasa_id'],'i':tid});await db.commit()
    async with await _klien(pg,role='superadmin') as c:
        c.headers['X-CSRF-Token']=cap_formulir(c)
        if kind.startswith('GABAH'):
            endpoint='gabah-masuk';payload={'timbangan_transaksi_id':tid,'tujuan':'tumpuk'};model=PurchaseBatch
            if jasa and kind=='GABAH_BASAH':
                from app.models import Dryer
                async with pg() as db:
                    payload['tujuan']='dryer:'+str(await db.scalar(select(Dryer.id).order_by(Dryer.id)))
        elif kind=='BERAS_PK':
            endpoint='catat-pk-luar';payload={'timbangan_transaksi_id':tid,'jenis_pk':'ks'};model=PkPurchaseBatch
        else:
            endpoint='catat-produk-timbang-masuk';payload={'timbangan_transaksi_id':tid};model=FinishedGoodsStock if kind=='BERAS_MASUK' else ByproductStock
        from app.models import DryingLot,MillingProcess,PolishingProcess
        async with pg() as db:
            kol=model.timbangan_transaksi_id if kind in JENIS[:3] else model.source_id
            assert not (await db.scalars(select(model).where(kol==tid))).all()
            proses_awal=[await db.scalar(select(func.count()).select_from(m)) for m in (DryingLot,MillingProcess,PolishingProcess)]
        old=(await c.get('/api/actions/menu')).json()
        awal=await c.get('/barang-masuk',params={'jenis':{'GABAH_BASAH':'gabah_basah','GABAH_KERING':'gabah_kering','BERAS_PK':'pk','BERAS_MASUK':'beras','BROKEN_MASUK':'broken'}[kind]})
        assert 'TRX-391-'+kind in awal.text
        assert old==(await c.get('/api/actions/menu')).json()
        r=await c.post('/api/actions/'+endpoint,json=payload);assert r.status_code==200,r.text
        q=await c.post('/api/actions/'+endpoint,json=payload)
        assert q.status_code in (200,400,409),q.text
        async with pg() as db:
            kol=model.timbangan_transaksi_id if kind in JENIS[:3] else model.source_id
            rows=(await db.scalars(select(model).where(kol==tid))).all()
            assert len(rows)==1
            row=rows[0];assert row.jasa_id==(lengkap['jasa_id'] if jasa else None)
            berat=getattr(row,'berat_total_kg',getattr(row,'berat_kg',None));assert float(berat)==9800
            logs=(await db.scalars(select(ActivityLog).where(ActivityLog.changed_by==await db.scalar(select(User.id).where(User.nama=='Uji superadmin'))))).all()
            assert logs
            proses_akhir=[await db.scalar(select(func.count()).select_from(m)) for m in (DryingLot,MillingProcess,PolishingProcess)]
            assert proses_awal==proses_akhir, 'Penerimaan tidak memulai proses otomatis'
            if kind.startswith('GABAH'):
                lokasi='dryer' if row.dryer_id else row.status_batch
                assert lokasi==('dryer' if jasa and kind=='GABAH_BASAH' else 'ditumpuk')
            elif kind=='BERAS_PK':
                from app.models import PkGudang2Intake
                it=await db.scalar(select(PkGudang2Intake).where(PkGudang2Intake.pk_purchase_batch_id==row.id))
                assert it and it.silo_id is None and it.tujuan=='ditumpuk'
                assert float(it.berat_kg)==9800 and it.jasa_id==row.jasa_id
                lokasi='Tumpukan Gudang 2'
            else:
                if kind=='BERAS_MASUK':
                    assert row.warehouse_id==lengkap['gudang']['g2']
                else:
                    assert row.jenis_produk=='broken' and row.source_type=='timbangan'
                lokasi='Stok produk Gudang 2'
        assert 'TRX-391-'+kind not in (await c.get('/barang-masuk')).text
        riw=await c.get('/barang-masuk?status=diterima');assert 'TRX-391-'+kind in riw.text
        from app.services.barang_masuk import riwayat
        async with pg() as db:
            tampak=(await riwayat(db,g1=True,g2=True,tid=tid))[0]
            assert float(tampak['berat_diterima'])==float(berat)
            assert tampak['keterangan_berat']==''
            if jasa:
                assert tampak['nama']=='Bu Sri'
        assert 'Bobot diterima' in riw.text and 'masuk-bobot' in riw.text
        detail=await c.get(f'/barang-masuk/{tid}');assert detail.status_code==200,detail.text
        assert '9.800' in detail.text and 'TRX-391-'+kind in detail.text
        assert 'Catatan penerimaan' in detail.text
        import re, html
        for url in re.findall(r'href="([^"]+)"',detail.text):
            url=html.unescape(url)
            if url.startswith(('/stok?', '/stok-pk/', '/proses-aktif/', '/riwayat-')):
                tujuan=await c.get(url)
                assert tujuan.status_code in (200,303),(kind,url,tujuan.status_code)
        # Sesudah penerimaan pilihan mesin/tiket boleh berubah sesuai kondisi lama.
        (OUT/f'terima-{kind}-{jasa}.json').write_text(json.dumps({'jenis':kind,'jasa':jasa,'tid':tid,'berat':float(berat),'catatan':len(rows),'audit':len(logs),'status_ulang':q.status_code,'akun':'Uji superadmin','kode_tiket':'TRX-391-'+kind,'sebelum':{'catatan':0,'proses':proses_awal},'sesudah':{'catatan':1,'kg':float(berat),'jasa_id':row.jasa_id,'lokasi':lokasi,'proses':proses_akhir}}))

async def test_detail_dan_filter_konteks_tetap_dan_get_tidak_menulis(pg,lengkap):
    async with await _klien(pg,role='superadmin') as c:
        async with pg() as db:
            sebelum=await db.scalar(select(func.count()).select_from(ActivityLog))
        for path in ('/barang-masuk?jenis=pk&kepemilikan=pabrik&gudang=g2','/pekerjaan?tab=tindakan&jenis=packing&kepemilikan=jasa&gudang=g2','/aksi?buka=catat_pk_luar&nilai='+str(lengkap['tiket']['BERAS_PK']),'/berjalan?gudang=g2','/mutu?buka=qc_giling&nilai=LOT-STOK-PABRIK','/keputusan?kategori=acc_permintaan_pk'):
            r=await c.get(path);assert r.status_code==200,(path,r.text[-1000:])
        r=await c.get('/barang-masuk?jenis=pk');assert 'TRX-391-BERAS_PK' in r.text and 'TRX-391-GABAH' not in r.text
        async with pg() as db:
            assert await db.scalar(select(func.count()).select_from(ActivityLog))==sebelum

@pytest.mark.parametrize('kind',JENIS)
async def test_tiket_terbuka_tanpa_bobot_final_memakai_aturan_lama(pg,lengkap,kind):
    tid=lengkap['tiket'][kind]
    async with pg() as db:
        await db.execute(text("UPDATE timbangan_transaksi SET status_tiket='TERBUKA',netto_timbangan_kg=NULL,berat_barang_kg=NULL,berat_acuan_kg=0 WHERE id=:id"),{'id':tid});await db.commit()
    async with await _klien(pg,role='superadmin') as c:
        c.headers['X-CSRF-Token']=cap_formulir(c)
        h=await c.get('/barang-masuk');assert 'TRX-391-'+kind in h.text
        detail=await c.get(f'/barang-masuk/{tid}');assert 'Berat belum final' in detail.text
        if kind.startswith('GABAH'):
            r=await c.post('/api/actions/gabah-masuk',json={'timbangan_transaksi_id':tid,'tujuan':'tumpuk'})
        elif kind=='BERAS_PK':
            r=await c.post('/api/actions/catat-pk-luar',json={'timbangan_transaksi_id':tid,'jenis_pk':'ks'})
        else:
            r=await c.post('/api/actions/catat-produk-timbang-masuk',json={'timbangan_transaksi_id':tid})
        # Gabah/PK lama menerima tanpa bobot. Beras/broken lama meminta bobot
        # tersedia; bukan kewajiban timbang akhir baru dari konsolidasi.
        assert r.status_code==(200 if kind in JENIS[:3] else 400),r.text
        if kind in JENIS[:3]:
            from app.services.barang_masuk import riwayat
            async with pg() as db:
                tampak=(await riwayat(db,g1=True,g2=True,tid=tid))[0]
                assert tampak['berat_diterima'] is None
                assert tampak['keterangan_berat']=='Belum diukur'

@pytest.mark.parametrize('role,gudang,lihat',[
 ('superadmin',None,None),('admin',None,None),('operator','g1',None),('operator','g2',None),
 ('superadmin',None,'operator:g1'),('superadmin',None,'operator:g2'),
])
async def test_izin_penerimaan_langsung_dan_input_tidak_sah(pg,lengkap,role,gudang,lihat):
    async with await _klien(pg,role=role,gudang_id=lengkap['gudang'].get(gudang)) as c:
        if lihat:
            assert (await c.post('/lihat-sebagai',data={'peran':lihat,'_csrf':cap_formulir(c)})).status_code==303
        c.headers['X-CSRF-Token']=cap_formulir(c)
        scope=lihat.split(':')[-1] if lihat else gudang
        before=[]
        async with pg() as db:
            for m in (PurchaseBatch,PkPurchaseBatch,FinishedGoodsStock,ByproductStock,ActivityLog):before.append(await db.scalar(select(func.count()).select_from(m)))
        for ep,payload,allow in [
          ('gabah-masuk',{'timbangan_transaksi_id':-1,'tujuan':'tidak-sah'},scope!='g2'),
          ('catat-pk-luar',{'timbangan_transaksi_id':-1,'jenis_pk':'tidak-sah'},scope is None),
          ('catat-produk-timbang-masuk',{'timbangan_transaksi_id':-1},scope is None),
        ]:
            r=await c.post('/api/actions/'+ep,json=payload)
            assert r.status_code in ({400,404,422} if allow else {403}),(ep,scope,r.status_code,r.text)
        async with pg() as db:
            after=[]
            for m in (PurchaseBatch,PkPurchaseBatch,FinishedGoodsStock,ByproductStock,ActivityLog):after.append(await db.scalar(select(func.count()).select_from(m)))
            assert before==after

async def test_qc_nonaktif_dan_tautan_legacy_tidak_memperluas_izin(pg,lengkap):
    from app.services.setelan import set_fitur_mutu
    async with await _klien(pg,role='superadmin') as c:
        c.headers['X-CSRF-Token']=cap_formulir(c)
        async with pg() as db:
            u=await db.scalar(select(User).where(User.nama=='Uji superadmin'))
            await set_fitur_mutu(db,False,user=u)
        r=await c.get('/pekerjaan?jenis=qc');assert 'Pencatatan mutu dimatikan' in r.text
        assert 'buka=qc_giling' not in r.text and 'buka=qc_pk_luar' not in r.text
        assert (await c.post('/api/actions/qc-giling',json={'kode_proses':'LOT-STOK-PABRIK','kadar_air':13})).status_code==400
        async with pg() as db:await set_fitur_mutu(db,True,user=await db.get(User,u.id))
        r=await c.get('/pekerjaan?jenis=qc');assert 'buka=qc_giling' in r.text
        for uri in ('/mutu?buka=qc_giling&nilai=LOT-STOK-PABRIK','/keputusan?kategori=tidak-ada'):
            assert (await c.get(uri)).status_code==200

async def test_pk_ditolak_tiket_ditutup_paksa_tetap_bisa_dibaca_tanpa_diterima_lagi(pg,lengkap):
    tid=lengkap['tiket']['BERAS_PK']
    async with pg() as db:
        await db.execute(text("UPDATE timbangan_transaksi SET status_tiket='TERBUKA' WHERE id=:id"),{'id':tid});await db.commit()
    async with await _klien(pg,role='superadmin') as c:
        c.headers['X-CSRF-Token']=cap_formulir(c)
        r=await c.post('/api/actions/tolak-pk-luar',json={'timbangan_transaksi_id':tid,'alasan':'Mutu tidak sesuai, data uji'})
        assert r.status_code==200,r.text
        detail=await c.get(f'/barang-masuk/{tid}')
        assert detail.status_code==200,detail.text
        assert 'ditolak' in detail.text and 'Tiket ditutup paksa.' in detail.text
        assert 'TRX-391-BERAS_PK' not in (await c.get('/barang-masuk')).text
        assert (await c.post('/api/actions/catat-pk-luar',json={'timbangan_transaksi_id':tid,'jenis_pk':'ks'})).status_code in (400,409)

async def test_peralihan_fase_selesai_tetap_membawa_konteks_daftar():
    from starlette.requests import Request
    from urllib.parse import urlencode,parse_qs,urlsplit
    from app.web.layar_berjalan import _alih_proses
    asal='/pekerjaan?tab=berjalan&gudang=g1&kepemilikan=jasa&cari=LOT-01'
    req=Request({'type':'http','method':'GET','path':'/proses-aktif/giling/LOT-01','query_string':urlencode({'kembali_kerja':asal}).encode(),'headers':[]})
    r=await _alih_proses(req,'/riwayat-giling/1')
    assert r.status_code==303
    assert parse_qs(urlsplit(r.headers['location']).query)['kembali_kerja']==[asal]

async def test_tombol_semua_terkunci_tidak_dihitung_sebagai_tindakan():
    from app.services.berjalan import Baris,Tombol,Berjalan
    from app.services.kelompok_kerja import dapat_ditindak
    b=Baris('t','Tiket jasa basah','',aksi='gabah_masuk',tombol=[Tombol('Dryer','Penuh','/api/actions/gabah-masuk',{},mati='Mesin penuh')])
    assert not dapat_ditindak(b)
    assert Berjalan(menunggu=[b]).lencana()['BARANG_MASUK']==0


async def test_pemilik_detail_mengikuti_catatan_bukan_tiket_yang_diedit(pg,lengkap):
    tid=lengkap['tiket']['BERAS_MASUK']
    async with pg() as db:
        await db.execute(text('UPDATE timbangan_transaksi SET jasa=true,pelanggan_id=:p,jasa_id=:j WHERE id=:i'),{'p':lengkap['pelanggan_id'],'j':lengkap['jasa_id'],'i':tid});await db.commit()
    async with await _klien(pg,role='superadmin') as c:
        c.headers['X-CSRF-Token']=cap_formulir(c)
        r=await c.post('/api/actions/catat-produk-timbang-masuk',json={'timbangan_transaksi_id':tid});assert r.status_code==200,r.text
        async with pg() as db:
            await db.execute(text('UPDATE timbangan_transaksi SET jasa=false,pelanggan_id=NULL,jasa_id=NULL WHERE id=:i'),{'i':tid});await db.commit()
        h=(await c.get(f'/barang-masuk/{tid}')).text
        assert 'identitas-barang__label--jasa' in h and 'JAS-' in h and 'Bu Sri</p>' in h
        assert 'tab=produk&amp;pemilik=jasa' in h


async def test_detail_menampilkan_timbang_lengkap_dan_qc_batch_yang_tepat(pg,lengkap):
    from app.penggilingan.gudang1.services.qc_gabah import catat_qc_gabah
    tid=lengkap['tiket']['GABAH_KERING']
    async with pg() as db:
        aid=await db.scalar(text("INSERT INTO timbangan_akun (username,nama,role,password_hash,status) VALUES ('petugas396','Petugas Timbang Uji 396','PETUGAS','uji','aktif') RETURNING id"))
        await db.execute(text("""UPDATE timbangan_transaksi SET timbang2_kg=2200,timbang2_waktu=timbang1_waktu,
          timbang1_petugas_id=:a,timbang2_petugas_id=:a,berat_bermuatan_kg=12000,
          berat_kosong_kg=2200,netto_timbangan_kg=9800,jumlah_karung=40,total_tara_kg=15,
          tara_lain_kg=5,berat_barang_kg=9785,keterangan='Catatan timbang uji lengkap'
          WHERE id=:t"""),{'a':aid,'t':tid})
        await db.execute(text("""INSERT INTO timbangan_muatan (transaksi_id,urutan,jenis_kode,nomor_acuan,jumlah_karung,tara_per_karung_kg,berat_acuan_kg)
          VALUES (:t,1,'GABAH_KERING','NOTA-UJI-396',40,0.25,9785)"""),{'t':tid})
        await db.commit()
    async with await _klien(pg,role='superadmin') as c:
        c.headers['X-CSRF-Token']=cap_formulir(c)
        r=await c.post('/api/actions/gabah-masuk',json={'timbangan_transaksi_id':tid,'tujuan':'tumpuk'})
        assert r.status_code==200,r.text
        async with pg() as db:
            u=await db.scalar(select(User).where(User.nama=='Uji superadmin'))
            b=await db.scalar(select(PurchaseBatch).where(PurchaseBatch.timbangan_transaksi_id==tid))
            for a1,a2 in ((13,14),(14,15)):
                await catat_qc_gabah(db,user=u,kode_batch=b.kode_batch,kadar_air_1=a1,kadar_air_2=a2,biji_hijau='sedikit',densiti='padat')
            awal=await db.scalar(select(func.count()).select_from(ActivityLog))
        h=(await c.get(f'/barang-masuk/{tid}')).text
        for nilai in ('Hasil QC','Kadar air 1','Kadar air 2','13%','15%','2/5 pemeriksaan','Pemeriksaan 2',
                      'Timbang pertama','Timbang kedua','12.000 kg','2.200 kg','9.800 kg','9.785 kg',
                      'Total potongan tara','15 kg','Tara lain','5 kg','Petugas Timbang Uji 396',
                      'NOTA-UJI-396','Catatan timbang uji lengkap'):
            assert nilai in h,nilai
        async with pg() as db:
            assert await db.scalar(select(func.count()).select_from(ActivityLog))==awal
            assert float((await db.get(PurchaseBatch,b.id)).berat_total_kg)==9785
        # Riwayat dan tabel harus tetap dapat dibaca operator gudang asal.
    async with await _klien(pg,role='operator',gudang_id=lengkap['gudang']['g1']) as c:
        assert 'Hasil QC' in (await c.get(f'/barang-masuk/{tid}')).text
    async with await _klien(pg,role='operator',gudang_id=lengkap['gudang']['g2']) as c:
        assert (await c.get(f'/barang-masuk/{tid}')).status_code==403


@pytest.mark.parametrize('lama',[False,True])
async def test_qc_pk_penerimaan_membaca_riwayat_dan_tidak_menebak_pencatat_lama(pg,lengkap,lama):
    from app.models import PkPurchaseQcLog,PkPurchaseVerification
    from app.database import now_local
    from app.services.barang_masuk import hasil_qc,riwayat
    tid=lengkap['tiket']['BERAS_PK']
    async with await _klien(pg,role='superadmin') as c:
        c.headers['X-CSRF-Token']=cap_formulir(c)
        r=await c.post('/api/actions/catat-pk-luar',json={'timbangan_transaksi_id':tid,'jenis_pk':'ks'})
        assert r.status_code==200,r.text
        async with pg() as db:
            b=await db.scalar(select(PkPurchaseBatch).where(PkPurchaseBatch.timbangan_transaksi_id==tid))
            u=await db.scalar(select(User).where(User.nama=='Uji superadmin'))
            if lama:
                db.add(PkPurchaseVerification(pk_purchase_batch_id=b.id,kadar_air=13,broken_persen=7,
                    penyusutan_persen=5,verified_by=u.id,waktu_verifikasi=now_local()))
            else:
                for air in (13,14):
                    db.add(PkPurchaseQcLog(pk_purchase_batch_id=b.id,kadar_air=air,broken_persen=7,
                        susut_persen=5,waktu=now_local(),input_by=u.id))
            await db.commit()
            cs=(await riwayat(db,g1=True,g2=True,tid=tid))[0]['catatan']
            q=(await hasil_qc(db,cs))[0]
            assert len(q['putaran'])==(1 if lama else 2)
            assert ('Broken','7%') in q['putaran'][0]['hasil']
            if lama:
                assert q['putaran'][0]['petugas']=='Tidak tercatat'
                assert q['putaran'][0]['waktu'] is None
                assert q['url'] is None
            else:
                assert q['putaran'][0]['petugas']=='Uji superadmin'
                assert q['url'].endswith(b.kode_batch)
        h=(await c.get(f'/barang-masuk/{tid}')).text
        assert 'Hasil QC' in h and '7%' in h


async def test_partai_lama_tanpa_tabel_rincian_tidak_gagal_atau_dikarang(pg,lengkap):
    tid=lengkap['tiket']['GABAH_KERING']
    async with pg() as db:
        await db.execute(text("UPDATE timbangan_transaksi SET cara_timbang='PARTAI' WHERE id=:t"),{'t':tid})
        await db.commit()
    async with await _klien(pg,role='superadmin') as c:
        r=await c.get(f'/barang-masuk/{tid}')
        assert r.status_code==200
        assert 'Total partai kecil' in r.text and '9.800 kg' in r.text
        assert 'Rincian setiap penimbangan belum tersedia' in r.text
        assert 'Timbang kedua' not in r.text


@pytest.mark.parametrize('tujuan',['silo','silo:999999'])
async def test_tujuan_silo_tidak_sah_ditolak_sebelum_ada_pencatatan(pg,lengkap,tujuan):
    from app.models import Peristiwa
    tid=lengkap['tiket']['GABAH_KERING']
    async with await _klien(pg,role='superadmin') as c:
        c.headers['X-CSRF-Token']=cap_formulir(c)
        async with pg() as db:
            before=[await db.scalar(select(func.count()).select_from(m)) for m in (PurchaseBatch,ActivityLog,Peristiwa)]
        r=await c.post('/api/actions/gabah-masuk',json={'timbangan_transaksi_id':tid,'tujuan':tujuan})
        assert r.status_code==400 and 'Pilih silo' in r.text
        async with pg() as db:
            after=[await db.scalar(select(func.count()).select_from(m)) for m in (PurchaseBatch,ActivityLog,Peristiwa)]
        assert before==after
        assert 'TRX-391-GABAH_KERING' in (await c.get('/barang-masuk')).text
        (OUT/('tujuan-tidak-sah-'+tujuan.replace(':','-')+'.json')).write_text(json.dumps({'tiket':'TRX-391-GABAH_KERING','akun':'Uji superadmin','tujuan':tujuan,'http':r.status_code,'sebelum':before,'sesudah':after}))


@pytest.mark.parametrize('kind',JENIS)
async def test_tiket_keluar_tidak_masuk_barang_masuk(pg,lengkap,kind):
    tid=lengkap['tiket'][kind]
    async with pg() as db:
        await db.execute(text("UPDATE timbangan_transaksi SET arah='KELUAR' WHERE id=:id"),{'id':tid});await db.commit()
    async with await _klien(pg,role='superadmin') as c:
        assert 'TRX-391-'+kind not in (await c.get('/barang-masuk')).text
        assert (await c.get(f'/barang-masuk/{tid}')).status_code==404


async def test_daftar_panjang_dan_halaman_riwayat_tidak_kehilangan_tiket(pg,lengkap):
    async with pg() as db:
        ids=[await _tiket(db,f'TRX-391-PANJANG-{i:02d}','GABAH_KERING') for i in range(28)]
        await db.commit()
    async with await _klien(pg,role='superadmin') as c:
        c.headers['X-CSRF-Token']=cap_formulir(c)
        awal=(await c.get('/barang-masuk')).text
        assert all(f'TRX-391-PANJANG-{i:02d}' in awal for i in range(28))
        for tid in ids:
            r=await c.post('/api/actions/gabah-masuk',json={'timbangan_transaksi_id':tid,'tujuan':'tumpuk'})
            assert r.status_code==200,r.text
        a=(await c.get('/barang-masuk?status=diterima&jenis=gabah_kering')).text
        b=(await c.get('/barang-masuk?status=diterima&jenis=gabah_kering&halaman=2')).text
        assert a.count('class="masuk-baris"')==25 and b.count('class="masuk-baris"')==3
        assert 'jenis=gabah_kering' in a and 'halaman=2' in a
        assert all((f'TRX-391-PANJANG-{i:02d}' in a) != (f'TRX-391-PANJANG-{i:02d}' in b) for i in range(28))
        kosong=(await c.get('/barang-masuk?status=diterima&jenis=broken')).text
        assert 'Belum ada penerimaan tercatat' in kosong and 'Filter' in kosong
        (OUT/'daftar-panjang.json').write_text(json.dumps({'akun':'Uji superadmin','tiket':'TRX-391-PANJANG-00..27','sebelum':{'pending_tambahan':28,'diterima_tambahan':0},'sesudah':{'pending_tambahan':0,'diterima_tambahan':28,'halaman':[25,3]},'filter_jenis':'gabah_kering'}))
