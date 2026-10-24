"""Lima tab memindahkan penyajian; saldo, transaksi dan batas pelanggan tetap."""
import json
import os
from pathlib import Path
from urllib.parse import urlencode

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select, text

from tests.pg.test_stok_produk_jasa import sosoh_jasa  # noqa: F401
from tests.pg.test_konsolidasi_stok import stok_lengkap  # noqa: F401
from tests.pg.test_stok_pk_g1_polesan import _klien
from tests.pg.test_riwayat_qc_detail import qc  # noqa: F401
from tests.pg.test_portal_pelanggan import portal, client as portal_client  # noqa: F401

pytestmark = pytest.mark.asyncio
TAB = ('ringkasan','penerimaan','proses','stok','pengambilan')


def bukti(nama, isi):
    folder=os.environ.get('BUKTI_JASA')
    if folder:
        p=Path(folder);p.mkdir(parents=True,exist_ok=True)
        (p/nama).write_text(isi)


async def cuplik(pg):
    tabel=('jasa','purchase_batches','pk_purchase_batches','drying_lots',
        'milling_process','polishing_process','polishing_silo_usage','polishing_output_logs',
        'finished_goods_stock','byproduct_stock','outgoing_records','outgoing_items',
        'customer_returns','customer_return_items','pk_gudang2_intakes','internal_transfers',
        'activity_logs','peristiwa')
    async with pg() as db:
        return {t:await db.scalar(text(f"SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY id),'[]'::jsonb)::text FROM {t} x")) for t in tabel}


async def test_lima_tab_skenario_campuran_saldo_dan_sumber_tidak_berubah(pg,pemakai):
    from tests.pg.skenario_jasa_pelanggan import buat
    from app.services import jasa_pelanggan as svc
    data=await buat(pg,pemakai)
    pid=data['pelanggan_id']
    async with await _klien(pg,role='superadmin') as c:
        async with pg() as db:awal=await svc.pelanggan(db,pid)
        sebelum=await cuplik(pg)
        asal={'status':'dibatalkan','cari':'Catur campuran','halaman':'2'}
        for tab in TAB:
            r=await c.get(f'/jasa/pelanggan/{pid}?'+urlencode(dict(tab=tab,**asal)))
            assert r.status_code==200,r.text[:1000]
            s=BeautifulSoup(r.text,'html.parser')
            links=s.select('.jasa-detail-tab a')
            assert len(links)==5 and len(s.select('.jasa-detail-tab a[aria-current=page]'))==1
            assert all('cari=Catur' in a['href'] and 'halaman=2' in a['href'] for a in links)
            if tab=='ringkasan':
                assert [n.get_text(strip=True) for n in s.select('.jasa-detail-angka strong')]==['2.000 kg','4.500 kg','3.200 kg']
                assert 'Pesanan & rekap barang' in r.text
                assert s.find(id='pesanan-'+str(data['jasa_ids'][0]))
                assert not s.select('details.jasa-catatan ul')  # Item pengiriman dipindah ke tab khusus.
            elif tab=='proses':
                assert all(str(n) in r.text.replace('.','') for n in (2500,3500,4000))
            elif tab=='stok':
                assert 'Rincian asal' in r.text and 'bukan tambahan saldo' in r.text
            elif tab=='pengambilan':
                for pengiriman in awal['pengiriman']:
                    assert pengiriman['kode'] in r.text
                    assert all(svc.kg_rinci(x['kg']) in r.text for x in pengiriman['item'])
            bukti('campuran-'+tab+'.html',r.text)
        for jid in data['jasa_ids']:
            assert (await c.get(f'/jasa/{jid}/nota')).status_code==200
            old=await c.get(f'/jasa/{jid}')
            assert old.status_code==303 and f'#pesanan-{jid}' in old.headers['location']
        async with pg() as db:akhir=await svc.pelanggan(db,pid)
        assert awal==akhir
        assert sebelum==await cuplik(pg)
        saldo={k:akhir[k] for k in ('pk_kg','beras_kg','samping_kg')}
        pol=next(p for p in akhir['proses'] if p['jenis']=='sosoh')
        assert pol['hasil']['bahan']==10000 and sum(pol['hasil']['jenis'].values())==9700
        assert pol['hasil']['susut']==300
        bukti('campuran-perbandingan.json',json.dumps({'saldo_sebelum':{k:awal[k] for k in saldo},'saldo_sesudah':saldo,'sumber':pol['sumber'],'hasil':pol['hasil'],'pesanan_sebelum':awal['pesanan'],'pesanan_sesudah':akhir['pesanan'],'database_tetap':True},default=str,indent=2))
        if os.environ.get('BUKTI_JASA'):
            bukti('sesi.json',json.dumps({'pid':pid,'cookies':{x.name:x.value for x in c.cookies.jar}}))


@pytest.mark.parametrize('role,gudang,status',[('admin',None,200),('superadmin',None,200),('operator','g1',403),('operator','g2',403)])
async def test_tab_baru_mengikuti_gerbang_backend_lama(pg,stok_lengkap,role,gudang,status):
    async with await _klien(pg,role=role,gudang_id=stok_lengkap['gudang'].get(gudang)) as c:
        for tab in TAB:
            r=await c.get(f'/jasa/pelanggan/{stok_lengkap["pelanggan_id"]}?tab={tab}')
            assert r.status_code==status


async def test_tab_portal_baca_saja_tidak_membocorkan_pelanggan_lain(pg,portal):
    pid=portal.owners[0].id
    async with portal_client(portal.accounts[0]) as c:
        for tab in TAB:
            r=await c.get(f'/pelanggan/jasa/pelanggan/{pid}?tab={tab}')
            assert r.status_code==200,r.text[:500]
            assert 'Rahasia Pelanggan B' not in r.text and 'LOT-RAHASIA-B' not in r.text
            s=BeautifulSoup(r.text,'html.parser')
            assert len(s.select('.jasa-detail-tab a'))==5
            assert not s.select('dialog,[data-kirim],[data-post]')
            assert 'Tutup pesanan' not in r.text and 'Batalkan pesanan' not in r.text
            assert not any('buka=' in a['href'] for a in s.select('a[href]'))
            assert all(a['href'].startswith(('/pelanggan','#')) for a in s.select('a[href]'))
            bukti('portal-'+tab+'.html',r.text)
            assert (await c.get(f'/pelanggan/jasa/pelanggan/{portal.owners[1].id}?tab={tab}')).status_code==404


@pytest.mark.parametrize('keadaan',['tanpa-saldo','belum-diterima','lama-aktif','historis'])
async def test_lima_tab_data_kosong_lama_dan_bobot_belum_diketahui(pg,stok_lengkap,keadaan):
    from app.models import Pelanggan,Jasa,PurchaseBatch,PolishingProcess
    from app.database import now_local
    from app.services import jasa_pelanggan as svc
    from tests.pg.test_tiket_antrean_produksi import _tiket
    pid=stok_lengkap['pelanggan_id']
    async with pg() as db:
        if keadaan in ('tanpa-saldo','belum-diterima'):
            asli=await db.get(Pelanggan,pid)
            # Nama sama persis sengaja dipakai: identitas tetap dibatasi ID.
            p=Pelanggan(nama_pelanggan=asli.nama_pelanggan);db.add(p);await db.flush();pid=p.id
            if keadaan=='tanpa-saldo':db.add(Jasa(kode='JAS-LIMA-KOSONG',pelanggan_id=pid,status='berjalan'))
            else:
                tid=await _tiket(db,'TRX-LIMA-BELUM','GABAH_KERING')
                await db.execute(text("UPDATE timbangan_transaksi SET jasa=TRUE,pelanggan_id=:p,status_tiket='TERBUKA' WHERE id=:t"),{'p':pid,'t':tid})
        elif keadaan=='lama-aktif':
            db.add(PurchaseBatch(kode_batch='GB-LIMA-LAMA',jasa_id=stok_lengkap['jasa_id'],kondisi_gabah='kering',status_batch='baru',berat_total_kg=None,sumber_berat='timbangan',tanggal_pembelian=now_local().date(),waktu_pembelian=now_local(),input_by=stok_lengkap['user']))
            pol=await db.scalar(select(PolishingProcess).where(PolishingProcess.kode_proses==stok_lengkap['kode_jasa']))
            pol.status='proses';pol.waktu_selesai=None
        else:
            for n,status in enumerate(('selesai','dibatalkan','digabung')):
                db.add(Jasa(kode=f'JAS-LIMA-HIST-{n}',pelanggan_id=pid,status=status,digabung_ke_id=stok_lengkap['jasa_id'] if status=='digabung' else None))
        await db.commit()
        awal=await svc.pelanggan(db,pid)
        if keadaan in ('tanpa-saldo','belum-diterima'):
            assert awal['pk_kg']==awal['beras_kg']==awal['samping_kg']==0
        if keadaan=='lama-aktif':assert any(s['kg'] is None and not s['final'] for s in awal['stok'])
    async with await _klien(pg,role='admin') as c:
        sebelum=await cuplik(pg)
        for tab in TAB:
            r=await c.get(f'/jasa/pelanggan/{pid}?tab={tab}')
            assert r.status_code==200 and len(BeautifulSoup(r.text,'html.parser').select('.jasa-detail-tab a'))==5
            if keadaan=='lama-aktif' and tab=='stok':assert 'Belum diukur' in r.text
            if keadaan=='lama-aktif' and tab=='ringkasan':assert 'Sebagian bobot belum diukur' in r.text
            if keadaan=='historis' and tab=='ringkasan':
                for kata in ('Selesai','Dibatalkan','Digabung','rekap pesanan gabungan'):assert kata in r.text
            bukti(keadaan+'-'+tab+'.html',r.text)
        assert await cuplik(pg)==sebelum
        async with pg() as db:assert await svc.pelanggan(db,pid)==awal


async def test_satu_tiket_banyak_catatan_pesanan_tetap_terbaca(pg,stok_lengkap):
    from app.models import Jasa,FinishedGoodsStock
    from app.database import now_local
    from app.services import jasa_pelanggan as svc
    from tests.pg.test_tiket_antrean_produksi import _tiket
    from tests.pg.test_stok_produk_jasa import _packing
    await _packing(pg,stok_lengkap,kode_pol=stok_lengkap['kode_jasa'],karung=1)
    pid=stok_lengkap['pelanggan_id']
    async with pg() as db:
        ref=await db.scalar(select(FinishedGoodsStock).where(FinishedGoodsStock.jasa_id==stok_lengkap['jasa_id']))
        kedua=Jasa(kode='JAS-LIMA-CATATAN-2',pelanggan_id=pid,status='berjalan');db.add(kedua);await db.flush()
        tid=await _tiket(db,'TRX-LIMA-BANYAK','BERAS_MASUK')
        await db.execute(text('UPDATE timbangan_transaksi SET jasa=TRUE,pelanggan_id=:p,jasa_id=:j WHERE id=:t'),{'p':pid,'j':stok_lengkap['jasa_id'],'t':tid})
        for jid,jumlah in [(stok_lengkap['jasa_id'],8),(kedua.id,12)]:
            db.add(FinishedGoodsStock(product_sku_id=ref.product_sku_id,rice_quality_standard_id=ref.rice_quality_standard_id,source_type='timbangan',source_id=tid,jumlah_karung=jumlah,berat_total_kg=jumlah*25,warehouse_id=ref.warehouse_id,waktu=now_local(),input_by=stok_lengkap['user'],jasa_id=jid))
        await db.commit()
        awal=await svc.pelanggan(db,pid)
        tiket=next(t for t in awal['penerimaan'] if t['id']==tid)
        assert len(tiket['catatan'])==2
        assert sorted(float(x['berat']) for x in tiket['catatan'])==[200,300]
    async with await _klien(pg,role='admin') as c:
        sebelum=await cuplik(pg)
        r=await c.get(f'/jasa/pelanggan/{pid}?tab=penerimaan')
        assert r.status_code==200 and 'TRX-LIMA-BANYAK' in r.text
        assert '200 kg' in r.text and '300 kg' in r.text
        assert await cuplik(pg)==sebelum
        async with pg() as db:assert await svc.pelanggan(db,pid)==awal


async def test_portal_ringkasan_dan_tab_tidak_memuat_pengiriman_retur_di_luar_scope(pg,portal):
    from app.models import OutgoingRecord,OutgoingItem,CustomerReturn,CustomerReturnItem
    from app.database import now_local
    from tests.pg.test_tiket_antrean_produksi import _tiket
    async with pg() as db:
        kiriman=[];retur=[]
        for n,owners in enumerate(([portal.orders[0].id],[portal.orders[1].id],[portal.orders[0].id,portal.orders[1].id])):
            o=OutgoingRecord(kode=f'OUT-LIMA-PRIV-{n}',pelanggan_id=portal.owners[0].id,tanggal=now_local().date(),waktu=now_local(),input_by=1,status='selesai')
            db.add(o);await db.flush();kiriman.append(o)
            out_items={}
            for jid in owners:
                item=OutgoingItem(outgoing_record_id=o.id,item_type='byproduct',jasa_id=jid,berat_kg=10)
                db.add(item);await db.flush();out_items[jid]=item.id
            tid=await _tiket(db,f'RTP-LIMA-{n}','BERAS_MASUK')
            r=CustomerReturn(kode=f'RET-LIMA-PRIV-{n}',timbangan_transaksi_id=tid,kode_tiket=f'RTP-LIMA-{n}',pelanggan_id=portal.owners[0].id,berat_tiket_kg=10,berat_rincian_kg=10,selisih_kg=0,input_by=1,waktu=now_local())
            db.add(r);await db.flush();retur.append(r)
            for jid in owners:db.add(CustomerReturnItem(customer_return_id=r.id,jasa_id=jid,jumlah_karung=0,berat_total_kg=10,outgoing_item_id=out_items[jid]))
        await db.commit()
        tid=await _tiket(db,'RTP-LIMA-LAMA','BERAS_MASUK')
        lama=CustomerReturn(kode='RET-LIMA-LAMA-PABRIK',timbangan_transaksi_id=tid,kode_tiket='RTP-LIMA-LAMA',pelanggan_id=portal.owners[0].id,berat_tiket_kg=10,berat_rincian_kg=10,selisih_kg=0,input_by=1,waktu=now_local())
        db.add(lama);await db.flush();retur.append(lama)
        db.add(CustomerReturnItem(customer_return_id=lama.id,jasa_id=None,jumlah_karung=0,berat_total_kg=10));await db.commit()
        from app.services import jasa_pelanggan as svc
        data=await svc.pelanggan(db,portal.owners[0].id)
        for n in range(3):
            row=next(r for r in data['retur'] if r['id']==retur[n].id)
            assert row['asal']==[{'id':kiriman[n].id,'kode':kiriman[n].kode,'href':f'/barang-keluar/{kiriman[n].id}'}]
            assert 'belum tertaut' not in row['status']
    async with portal_client(portal.accounts[0]) as c:
        for tab in TAB:
            r=await c.get(f'/pelanggan/jasa/pelanggan/{portal.owners[0].id}?tab={tab}')
            assert r.status_code==200
            for code in [o.kode for o in kiriman[1:]]+[x.kode for x in retur[1:]]:assert code not in r.text
            if tab=='ringkasan':
                s=BeautifulSoup(r.text,'html.parser')
                pairs={d.dt.get_text(strip=True):d.dd.get_text(strip=True) for d in s.select('.jasa-pasang>div')}
                assert pairs=={'Pengambilan / pengiriman':'1 catatan','Retur terkait':'1 penerimaan retur'}
            if tab=='pengambilan':assert kiriman[0].kode in r.text and retur[0].kode in r.text
            bukti('retur-tertaut-portal-'+tab+'.html',r.text)
        for row in kiriman[1:]:assert (await c.get(f'/pelanggan/barang-keluar/{row.id}')).status_code==404
        for row in retur[1:]:assert (await c.get(f'/pelanggan/retur/{row.id}')).status_code==404
    # Tampilan internal Admin tetap memiliki seluruh fakta yang dibaca layanan.
    async with await _klien(pg,role='admin') as c:
        for tab in TAB:
            r=await c.get(f'/jasa/pelanggan/{portal.owners[0].id}?tab={tab}')
            assert r.status_code==200
            if tab=='pengambilan':assert all(x.kode in r.text for x in retur) and 'Pengeluaran asal belum tertaut' in r.text
            bukti('retur-tertaut-'+tab+'.html',r.text)


async def test_asal_retur_portal_tidak_membuka_pengiriman_campuran(pg,portal):
    from app.models import OutgoingRecord,OutgoingItem,CustomerReturn,CustomerReturnItem
    from app.database import now_local
    from app.services import jasa_pelanggan as svc
    from tests.pg.test_tiket_antrean_produksi import _tiket
    pid=portal.owners[0].id
    async with pg() as db:
        o=OutgoingRecord(kode='OUT-ASAL-TERBATAS',pelanggan_id=pid,tanggal=now_local().date(),waktu=now_local(),input_by=1,status='selesai')
        db.add(o);await db.flush()
        own=OutgoingItem(outgoing_record_id=o.id,item_type='byproduct',jasa_id=portal.orders[0].id,berat_kg=10)
        other=OutgoingItem(outgoing_record_id=o.id,item_type='byproduct',jasa_id=portal.orders[1].id,berat_kg=10)
        db.add_all([own,other]);await db.flush()
        tid=await _tiket(db,'RTP-ASAL-TERBATAS','BERAS_MASUK')
        r=CustomerReturn(kode='RET-ASAL-MILIK',timbangan_transaksi_id=tid,kode_tiket='RTP-ASAL-TERBATAS',pelanggan_id=pid,berat_tiket_kg=10,berat_rincian_kg=10,selisih_kg=0,input_by=1,waktu=now_local())
        db.add(r);await db.flush()
        db.add(CustomerReturnItem(customer_return_id=r.id,jasa_id=portal.orders[0].id,jumlah_karung=0,berat_total_kg=10,outgoing_item_id=own.id));await db.commit()
        d=await svc.pelanggan(db,pid)
        assert next(x for x in d['retur'] if x['id']==r.id)['asal'][0]['id']==o.id
    async with portal_client(portal.accounts[0]) as c:
        page=await c.get(f'/pelanggan/jasa/pelanggan/{pid}?tab=pengambilan')
        assert page.status_code==200 and r.kode in page.text and o.kode not in page.text
        assert (await c.get(f'/pelanggan/barang-keluar/{o.id}')).status_code==404
    async with await _klien(pg,role='admin') as c:
        page=await c.get(f'/jasa/pelanggan/{pid}?tab=pengambilan')
        assert page.status_code==200 and o.kode in page.text and 'Pengiriman asal:' in page.text
