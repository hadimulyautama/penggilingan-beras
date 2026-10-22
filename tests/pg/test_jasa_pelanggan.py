"""Pembaca pelanggan harus seimbang dengan Stok, tanpa menulis ulang transaksi."""
import pytest
from sqlalchemy import select,text
from tests.pg.test_konsolidasi_stok import stok_lengkap  # noqa: F401
from tests.pg.test_stok_produk_jasa import sosoh_jasa  # noqa: F401
from tests.pg.test_stok_pk_g1_polesan import _klien
from tests.pg.test_retur_integrasi import konteks  # noqa: F401

pytestmark=pytest.mark.asyncio


async def test_skenario_campuran_12000_10000_dan_pengambilan_2000(pg,pemakai):
    from tests.pg.skenario_jasa_pelanggan import buat
    from app.services import jasa_pelanggan as svc,stok
    from pathlib import Path
    import json
    data=await buat(pg,pemakai)
    async with pg() as db:
        d=await svc.pelanggan(db,data['pelanggan_id'])
        assert d['pk_kg']==2000
        assert d['beras_kg']==4500
        assert d['samping_kg']==3200
        pol=next(p for p in d['proses'] if p['jenis']=='sosoh')
        assert sorted(float(x['kg']) for x in pol['sumber'])==[2500,3500,4000]
        assert sum(float(x['kg']) for x in pol['sumber'])==pol['hasil']['bahan']==10000
        assert sum(pol['hasil']['jenis'].values())==9700 and pol['hasil']['susut']==300
        assert len(d['penerimaan'])==3 and len(d['pesanan'])==3 and len(d['pengiriman'])==1
        assert d['pengiriman'][0]['status']=='selesai'
        assert sorted(float(c['berat']) for t in d['penerimaan'] for c in t['catatan'])==[5000,6000,6000]
        out=Path('output/jasa392');out.mkdir(exist_ok=True,parents=True)
        (out/'campuran.json').write_text(json.dumps({'akun':'Uji superadmin',**data,'saldo':{k:d[k] for k in ('pk_kg','beras_kg','samping_kg')},'proses':pol,'stok':d['stok'],'penerimaan':d['penerimaan'],'pengiriman':d['pengiriman']},default=str,indent=2))
    async with await _klien(pg,role='superadmin') as c:
        links=[x['href'] for x in d['stok']+d['penerimaan']+d['proses']+d['pengiriman'] if x['href']]
        links += [s['href'] for r in d['proses'] for s in r['sumber'] if s['href']]
        links += [f'/jasa/{j}/nota' for j in data['jasa_ids']]
        for url in set(links):
            r=await c.get(url)
            assert r.status_code==200,(url,r.text[:1000])


async def test_saldo_pelanggan_memakai_pembaca_stok_tanpa_menulis(pg,stok_lengkap):
    from app.services import jasa_pelanggan as svc,stok
    from app.models import Jasa
    async with pg() as db:
        ids=list((await db.scalars(select(Jasa.id).where(Jasa.pelanggan_id==stok_lengkap['pelanggan_id']))).all())
        hasil=await stok.stok_produk(db,jasa_id=ids)
        d=await svc.pelanggan(db,stok_lengkap['pelanggan_id'])
        assert d['pk_kg']==3500
        assert d['beras_kg']==sum(x.sisa_kg for x in hasil if stok.adalah_beras(x.jenis))==5000
        assert not any('LAIN' in x['kode'] or 'PABRIK' in x['kode'] for x in d['stok'])
        pol=next(p for p in d['proses'] if p['jenis']=='sosoh')
        assert pol['hasil']['susut']==0
        assert 'Keterkaitan sumber belum tersedia' not in str(pol['sumber'])
        await db.rollback()


@pytest.mark.parametrize('role,gudang,code',[('superadmin',None,200),('admin',None,200),('operator','g1',403),('operator','g2',403)])
async def test_rute_lama_baru_dan_peran(pg,stok_lengkap,role,gudang,code):
    pid=stok_lengkap['pelanggan_id']
    async with await _klien(pg,role=role,gudang_id=stok_lengkap['gudang'].get(gudang)) as c:
        for href in ['/jasa',*[f'/jasa/pelanggan/{pid}?tab={t}' for t in ['ringkasan','penerimaan','proses','stok']],f'/jasa/{stok_lengkap["jasa_id"]}/nota']:
            r=await c.get(href)
            assert r.status_code==code,(href,r.text[:1000])
        if code==200:
            r=await c.get('/jasa')
            assert r.text.count('class="kartu jasa-pelanggan"')==2
            assert 'Barang titipan di gudang' not in r.text
            r=await c.get(f'/jasa/pelanggan/{pid}?tab=stok')
            assert '5.000 kg' in r.text and '3.500 kg' in r.text
            assert 'Saldo per pelanggan; tidak dibagi per pesanan' in r.text


async def test_banyak_pesanan_historis_nama_sama_tetap_id_terpisah(pg,stok_lengkap):
    from app.models import Jasa
    from app.services import jasa_pelanggan as svc
    async with pg() as db:
        db.add(Jasa(kode='JAS-LAMA-392',pelanggan_id=stok_lengkap['pelanggan_id'],status='dibatalkan'))
        await db.commit()
        d=await svc.pelanggan(db,stok_lengkap['pelanggan_id'])
        assert len(d['pesanan'])==2
        assert d['beras_kg']==5000 and d['pk_kg']==3500
        a=await svc.daftar(db,status='dibatalkan')
        assert len(a['kartu'])==1 and a['kartu'][0]['id']==stok_lengkap['pelanggan_id']
        a=await svc.daftar(db,cari='JAS-LAMA-392')
        assert len(a['kartu'])==1


async def test_tautan_tidak_menebak_alokasi_silo_lama(pg,stok_lengkap):
    from app.services import jasa_pelanggan as svc
    async with pg() as db:
        d=await svc.pelanggan(db,stok_lengkap['pelanggan_id'])
        p=next(p for p in d['proses'] if p['jenis']=='sosoh')
        assert p['sumber'][0]['kg']==5000
        assert 'alokasi lot belum tersedia' in p['sumber'][0]['ket']
        assert not any(x['href'] and x['kg']==5000 for x in p['sumber'])


async def test_konteks_pelanggan_dan_gerbang_izin_operasional(pg,stok_lengkap):
    from urllib.parse import urlencode
    pid=stok_lengkap['pelanggan_id']
    async with await _klien(pg,role='admin') as c:
        for path in ['/stok?tab=produk&pemilik=jasa','/barang-masuk?status=diterima','/pekerjaan?tab=berjalan']:
            r=await c.get(path+'&'+urlencode(dict(pelanggan_id=pid,kembali_jasa=f'/jasa/pelanggan/{pid}?tab=stok')))
            assert r.status_code==200,r.text
            assert 'Kembali ke pelanggan jasa' in r.text
        r=await c.get('/stok?tab=produk&pemilik=jasa&kembali_jasa=https://contoh.invalid/jasa')
        assert 'data-kembali-jasa=' not in r.text
        r=await c.get(f'/jasa/pelanggan/{pid}?tab=tidak-sah')
        assert r.status_code==422
        assert (await c.get('/jasa/pelanggan/987654')).status_code==404


@pytest.mark.parametrize('lihat',['operator:g1','operator:g2'])
async def test_lihat_sebagai_tidak_melewati_gerbang_jasa(pg,stok_lengkap,lihat):
    from tests.pg.formulir import cap_formulir
    async with await _klien(pg,role='superadmin') as c:
        r=await c.post('/lihat-sebagai',data={'peran':lihat,'_csrf':cap_formulir(c)})
        assert r.status_code==303
        assert (await c.get('/jasa')).status_code==403
        assert (await c.get(f'/jasa/pelanggan/{stok_lengkap["pelanggan_id"]}')).status_code==403


async def test_get_seluruh_tautan_tidak_menulis_transaksi(pg,stok_lengkap):
    import json
    from app.models import Jasa
    pid=stok_lengkap['pelanggan_id']
    tabel=['jasa','purchase_batches','drying_lots','milling_process','polishing_process',
           'polishing_output_logs','finished_goods_stock','byproduct_stock','outgoing_records',
           'outgoing_items','pk_gudang2_intakes','internal_transfers','activity_logs','peristiwa']
    async def cuplik():
        async with pg() as db:
            return {t:(await db.execute(text(f'SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY id),\'[]\'::jsonb)::text FROM {t} x'))).scalar() for t in tabel}
    async with await _klien(pg,role='admin') as c:
        awal=await cuplik()
        for url in ['/jasa',f'/jasa/{stok_lengkap["jasa_id"]}',*[f'/jasa/pelanggan/{pid}?tab={t}' for t in ('ringkasan','penerimaan','proses','stok')],
                    f'/pekerjaan?pelanggan_id={pid}',f'/barang-masuk?pelanggan_id={pid}&status=diterima',f'/stok?tab=produk&pemilik=jasa&pelanggan_id={pid}',f'/barang-keluar?pelanggan_id={pid}']:
            r=await c.get(url)
            assert r.status_code in (200,303),(url,r.text)
        assert await cuplik()==awal


async def test_batal_pesanan_satu_saja_dan_validasi_saldo_tetap(pg,stok_lengkap):
    from app.models import Jasa,User
    from app.services import jasa,jasa_pelanggan as svc
    async with pg() as db:
        pid=stok_lengkap['pelanggan_id']
        j=Jasa(kode='JAS-BATAL-392',pelanggan_id=pid,status='berjalan');db.add(j);await db.commit()
        u=await db.get(User,stok_lengkap['user'])
        sebelum=await svc.pelanggan(db,pid)
        with pytest.raises(jasa.JasaError):await jasa.batalkan_pesanan(db,user=u,jasa_id=j.id,sebab='')
        await jasa.batalkan_pesanan(db,user=u,jasa_id=j.id,sebab='Contoh salah pesanan')
        assert (await db.get(Jasa,stok_lengkap['jasa_id'])).status=='berjalan'
        sesudah=await svc.pelanggan(db,pid)
        assert sesudah['beras_kg']==sebelum['beras_kg']==5000
        assert sesudah['pk_kg']==sebelum['pk_kg']==3500
        with pytest.raises(jasa.JasaError):await jasa.tutup_pesanan(db,user=u,jasa_id=stok_lengkap['jasa_id'])


async def test_tiket_jasa_belum_punya_pesanan_tidak_membaca_stok_pabrik(pg,stok_lengkap):
    from tests.pg.test_tiket_antrean_produksi import _tiket
    from app.models import Pelanggan
    from app.services import jasa_pelanggan as svc
    async with pg() as db:
        p=Pelanggan(nama_pelanggan='Pelanggan armada belum diterima');db.add(p);await db.flush()
        tid=await _tiket(db,'TRX-J392-BARU','GABAH_KERING')
        await db.execute(text('UPDATE timbangan_transaksi SET jasa=TRUE,pelanggan_id=:p WHERE id=:t'),{'p':p.id,'t':tid})
        await db.commit()
        d=await svc.pelanggan(db,p.id)
        assert d['pesanan']==[] and d['stok']==[] and d['beras_kg']==0
    async with await _klien(pg,role='admin') as c:
        r=await c.get(f'/jasa/pelanggan/{p.id}?tab=penerimaan')
        assert r.status_code==200 and 'TRX-J392-BARU' in r.text and 'Belum diterima' in r.text


async def test_pengambilan_dibatalkan_ringkasan_pulih_tanpa_mengubah_sumber(pg,pemakai):
    from tests.pg.skenario_jasa_pelanggan import buat
    from app.services import barang_keluar as bk,jasa_pelanggan as svc
    from app.models import OutgoingItem
    data=await buat(pg,pemakai)
    async with pg() as db:
        d=await svc.pelanggan(db,data['pelanggan_id'])
        assert d['beras_kg']==4500
        item=await db.scalar(select(OutgoingItem).where(OutgoingItem.outgoing_record_id==data['keluar_id']))
        await bk.balik_verifikasi(db,rec_id=data['keluar_id']);await db.commit()
        await bk.balik_muat(db,rec_id=data['keluar_id'],diisi=[item.id]);await db.commit()
        d=await svc.pelanggan(db,data['pelanggan_id'])
        assert d['beras_kg']==6500 and d['pk_kg']==2000 and d['samping_kg']==3200


async def test_retur_lama_tetap_pabrik_tanpa_menambah_titipan(pg,konteks):
    from app.models import Jasa,Pelanggan,PolishingProcess,PolishingOutputLog,User
    from app.services.seed import seed_master
    from app.services import jasa_pelanggan as svc,stok
    from app.database import now_local
    from tests.pg.test_retur_integrasi import form
    c,tid,sid=konteks
    await seed_master()
    async with pg() as db:
        u=await db.scalar(select(User))
        p=Pelanggan(nama_pelanggan='Pemilik retur J392');db.add(p);await db.flush()
        j=Jasa(kode='JAS-392-RET',pelanggan_id=p.id,status='berjalan');db.add(j);await db.flush()
        pol=PolishingProcess(kode_proses='POL-392-RET',status='selesai',jasa_id=j.id,waktu_mulai=now_local(),waktu_selesai=now_local(),created_by=u.id)
        db.add(pol);await db.flush()
        db.add(PolishingOutputLog(polishing_process_id=pol.id,jenis='medium',berat_kg=1000,waktu_update=now_local(),input_by=u.id))
        await db.execute(text("UPDATE timbangan_transaksi SET pelanggan_id=:p,status_tiket='SELESAI',timbang2_kg=6000,berat_barang_kg=3000,total_tara_kg=0 WHERE id=:t"),{'p':p.id,'t':tid})
        await db.commit()
        awal=await svc.pelanggan(db,p.id)
    # Fakta historis sebelum asal pengiriman diwajibkan. Jangan mengarang
    # hubungan ke Jasa hanya karena pelanggan penerimaan kebetulan sama.
    from app.models import CustomerReturn,CustomerReturnItem,FinishedGoodsStock
    async with pg() as db:
        now=now_local()
        retur=CustomerReturn(kode='RET-J392-LAMA',timbangan_transaksi_id=tid,
            kode_tiket='RTP-UJI',pelanggan_id=p.id,berat_tiket_kg=3000,
            berat_rincian_kg=3000,selisih_kg=0,input_by=u.id,waktu=now)
        db.add(retur);await db.flush()
        stock=FinishedGoodsStock(product_sku_id=sid,source_type='retur',source_id=retur.id,
            jumlah_karung=120,berat_total_kg=3000,waktu=now,input_by=u.id,
            jasa_id=None,kemasan_mengurangi_stok=False)
        db.add(stock);await db.flush()
        db.add(CustomerReturnItem(customer_return_id=retur.id,product_sku_id=sid,
            jumlah_karung=120,berat_total_kg=3000,jasa_id=None,finished_goods_stock_id=stock.id))
        await db.commit()
    async with pg() as db:
        akhir=await svc.pelanggan(db,p.id)
        assert akhir['beras_kg']==awal['beras_kg']==1000 and akhir['samping_kg']==0
        assert len(akhir['retur'])==1 and 'Milik pabrik' in akhir['retur'][0]['status']
        assert (await c.get(akhir['retur'][0]['href'])).status_code==200


async def test_dua_sosoh_pengambilan_bertahap_dan_silo_dipakai_ulang_tidak_mengarang_asal(pg,pemakai):
    from tests.pg.skenario_jasa_pelanggan import buat
    from app.models import User,FinishedGoodsStock,PolishingProcess
    from app.services import jasa_pelanggan as svc,transfer,barang_keluar as bk
    from app.penggilingan.gudang2 import polishing as pol
    from app.penggilingan.inventory import finished_goods as fg
    data=await buat(pg,pemakai)
    async with pg() as db:
        u=await db.get(User,data['user'])
        t=await transfer.create_internal_transfer(db,user=u,kode_proses='LOT-392-1',lokasi_tujuan='A',berat=500)
        kedua=await pol.mulai_penyosohan(db,user=u,nama_silos=['A'])
        kode=kedua.proc.kode_proses
        for j,n in [('medium',300),('broken',50),('menir',20),('bekatul',100)]:
            await pol.catat_output(db,user=u,kode=kode,jenis=j,berat_kumulatif=n)
        await pol.selesai_penyosohan(db,user=u,kode=kode,nama_silo='A',sisa_kg=0)
        await pol.akhiri_penyosohan(db,user=u,kode=kode)
        d=await svc.pelanggan(db,data['pelanggan_id'])
        assert d['pk_kg']==1500 and d['beras_kg']==4800 and d['samping_kg']==3370
        lama=next(p for p in d['proses'] if p['kode']==data['kode_pol'])
        # Silo A punya lebih dari satu riwayat intake. Jangan menyebut
        # transfer BARU sebagai sumber proses pertama hanya karena silonya sama.
        assert not any(s['kode']==t.transfer.kode_transfer for s in lama['sumber'])
        assert any('alokasi lot belum tersedia' in s['ket'] for s in lama['sumber'])
        await fg.catat_packing(db,user=u,kode_pol=kode,kategori='beras_putih',grade='medium',brand_nama='Polos',material_kode='biasa',ukuran=50,jumlah_karung=6)
        s=await db.scalar(select(FinishedGoodsStock).where(FinishedGoodsStock.source_id==kedua.proc.id))
        r=await bk.buat_perintah(db,user=u,jasa_id=kedua.proc.jasa_id,baris=[bk.BarisPerintah(tipe='finished_goods',sku_id=s.product_sku_id,std_id=s.rice_quality_standard_id,jumlah_karung=6)])
        await bk.muat_semua(db,user=u,rec_id=r.rec.id)
        d=await svc.pelanggan(db,data['pelanggan_id'])
        assert d['beras_kg']==4500 and d['pk_kg']==1500 and d['samping_kg']==3370
        assert len([r for r in d['proses'] if r['jenis']=='sosoh'])==2 and len(d['pengiriman'])==2


async def test_rebag_dan_sisanya_tidak_menggandakan_saldo_pelanggan(pg,sosoh_jasa):
    from tests.pg.test_kemas_ulang import awal
    from app.services import kemas_ulang,jasa_pelanggan as svc
    from app.models import User
    req,_,_=await awal(pg,sosoh_jasa,jasa=True)
    async with pg() as db:
        user=await db.get(User,sosoh_jasa['user'])
        sebelum=await svc.pelanggan(db,sosoh_jasa['pelanggan_id'])
        r=await kemas_ulang.simpan(db,user=user,**req)
        sesudah=await svc.pelanggan(db,sosoh_jasa['pelanggan_id'])
        assert float(r.sisa_kg)==20 and float(r.berat_baru_kg)==80
        assert sebelum['beras_kg']==sesudah['beras_kg']==5000


async def test_koreksi_hasil_dan_beberapa_kondisi_sekaligus(pg,stok_lengkap):
    from app.models import User,PolishingProcess,PurchaseBatch
    from app.services import jasa_pelanggan as svc
    from app.penggilingan.gudang2 import polishing
    from app.database import now_local
    pid=stok_lengkap['pelanggan_id']
    async with pg() as db:
        u=await db.get(User,stok_lengkap['user'])
        pol=await db.scalar(select(PolishingProcess).where(PolishingProcess.kode_proses==stok_lengkap['kode_jasa']))
        await polishing.koreksi_hasil_sosoh(db,user=u,process_id=pol.id,
            perubahan={j:(4800 if j=='medium' else 0) for j in polishing._ALL_JENIS},dasar={j:(5000 if j=='medium' else 0) for j in polishing._ALL_JENIS},alasan='Uji koreksi berat hasil terukur')
        d=await svc.pelanggan(db,pid)
        assert d['beras_kg']==4800 and d['pk_kg']==3500
        pol.status='proses';pol.waktu_selesai=None
        b=PurchaseBatch(kode_batch='GB-J392-UKUR',jasa_id=pol.jasa_id,kondisi_gabah='kering',
            status_batch='baru',berat_total_kg=None,sumber_berat='timbangan',tanggal_pembelian=now_local().date(),waktu_pembelian=now_local(),input_by=u.id)
        db.add(b);await db.commit()
        d=await svc.pelanggan(db,pid)
        assert all(s in d['kondisi'] for s in ('PK tersisa','Hasil belum diambil','Proses berjalan','Bahan masih di pabrik'))
        assert any(s['kg'] is None and not s['final'] for s in d['stok'])
