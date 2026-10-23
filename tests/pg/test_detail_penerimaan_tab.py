"""Tab memindahkan penyajian, bukan sumber data penerimaan atau transaksi."""
import json
import os
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode

import pytest
from sqlalchemy import select, text, func

from app.models import PurchaseBatch, PkPurchaseBatch, FinishedGoodsStock, ByproductStock, ActivityLog, User
from tests.pg.test_konsolidasi_pekerjaan import lengkap, JENIS, stok_lengkap, sosoh_jasa
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.formulir import cap_formulir

pytestmark = pytest.mark.asyncio


def tindakan(html):
    class P(HTMLParser):
        def __init__(self): super().__init__(); self.hasil=[]
        def handle_starttag(self, tag, attrs):
            d=dict(attrs)
            if 'data-kirim' in d:
                self.hasil.append(('post',d.get('data-post'),json.loads(d['data-kirim']),'disabled' in d))
            elif tag=='a' and 'buka=' in d.get('href',''):
                self.hasil.append(('form',d['href']))
    p=P();p.feed(html);return p.hasil



def bukti(nama, html):
    if os.environ.get('BUKTI_PENERIMAAN'):
        folder=Path(os.environ['BUKTI_PENERIMAAN']);folder.mkdir(parents=True,exist_ok=True)
        (folder/(nama+'.html')).write_text(html)


@pytest.mark.parametrize('kind',JENIS)
@pytest.mark.parametrize('jasa',[False,True])
async def test_tab_penerimaan_data_sama_formulir_dan_konteks_tetap(pg,lengkap,kind,jasa,monkeypatch):
    from app.web import layar_pekerjaan as layar
    from app.web.tampilan import templates
    from app.database import now_local
    asli=layar.render
    konteks=[]
    lama=templates.env.from_string(Path('hmu_tampilan/templates/barang_masuk_detail.html').read_text())
    def render(*args,**kwargs):
        r=asli(*args,**kwargs)
        if args[1]=='barang_masuk_detail.html':
            konteks.append(r.context)
        return r
    monkeypatch.setattr(layar,'render',render)
    tid=lengkap['tiket'][kind]
    if jasa:
        async with pg() as db:
            await db.execute(text('UPDATE timbangan_transaksi SET jasa=true,pelanggan_id=:p,jasa_id=:j WHERE id=:i'),{'p':lengkap['pelanggan_id'],'j':lengkap['jasa_id'],'i':tid});await db.commit()
    asal='/barang-masuk?status=diterima&jenis='+kind+'&kepemilikan=jasa&gudang=g2&pelanggan_id=1&q=truk&halaman=2'
    nama=kind.lower()+('-jasa' if jasa else '-pabrik')
    async with await _klien(pg,role='superadmin') as c:
        c.headers['X-CSRF-Token']=cap_formulir(c)
        async def tab_semua(status):
            async with pg() as db:awal=await db.scalar(select(func.count()).select_from(ActivityLog))
            for tab in ('ringkasan','tiket','qc','riwayat'):
                r=await c.get(f'/barang-masuk/{tid}?'+urlencode({'tab_detail':tab,'kembali_kerja':asal}))
                assert r.status_code==200,r.text
                assert r.text.count('role="tab"')==4 and r.text.count('role="tabpanel"')==4
                assert f'id="terima-tab-{tab}"' in r.text and f'aria-controls="terima-panel-{tab}"' in r.text
                assert konteks[-1]['kembali']==asal
                assert tindakan(r.text)==tindakan(lama.render(konteks[-1]))
                assert 'harga_hpp' not in r.text
                bukti(nama+'-'+status+'-'+tab,r.text)
            async with pg() as db:assert await db.scalar(select(func.count()).select_from(ActivityLog))==awal
            bukti(nama+'-'+status+'-baseline',lama.render(konteks[-1]))
        await tab_semua('belum')
        assert 'Bobot tiket saat ini' in (await c.get(f'/barang-masuk/{tid}')).text
        assert konteks[-1]['berat_diterima'] is None and not konteks[-1]['catatan']
        if kind.startswith('GABAH'):
            payload={'timbangan_transaksi_id':tid,'tujuan':'tumpuk'};endpoint='gabah-masuk';model=PurchaseBatch
            if jasa and kind=='GABAH_BASAH':
                from app.models import Dryer
                async with pg() as db:payload['tujuan']='dryer:'+str(await db.scalar(select(Dryer.id).order_by(Dryer.id)))
        elif kind=='BERAS_PK':
            payload={'timbangan_transaksi_id':tid,'jenis_pk':'ks','jumlah_karung':196,'ukuran_karung_kg':50};endpoint='catat-pk-luar';model=PkPurchaseBatch
        else:payload={'timbangan_transaksi_id':tid};endpoint='catat-produk-timbang-masuk';model=FinishedGoodsStock if kind=='BERAS_MASUK' else ByproductStock
        r=await c.post('/api/actions/'+endpoint,json=payload);assert r.status_code==200,r.text
        async with pg() as db:
            kol=model.timbangan_transaksi_id if kind in JENIS[:3] else model.source_id
            row=await db.scalar(select(model).where(kol==tid));rid=row.id
            awal=(float(getattr(row,'berat_total_kg',getattr(row,'berat_kg',None))),row.jasa_id)
            if kind.startswith('GABAH'):
                from app.penggilingan.gudang1.services.qc_gabah import catat_qc_gabah
                u=await db.scalar(select(User).where(User.nama=='Uji superadmin'))
                for air in (13,14):
                    await catat_qc_gabah(db,user=u,kode_batch=row.kode_batch,kadar_air_1=air,kadar_air_2=air+1,biji_hijau='sedikit',densiti='padat',**({'lamur':False,'jumlah_sak_lamur':0} if kind=='GABAH_BASAH' else {}))
            elif kind=='BERAS_PK':
                from app.models import PkPurchaseQcLog
                uid=await db.scalar(select(User.id).where(User.nama=='Uji superadmin'))
                for air in (13,14):db.add(PkPurchaseQcLog(pk_purchase_batch_id=rid,kadar_air=air,broken_persen=7,susut_persen=5,butir_kuning='sedikit',gabah='bersih',merang='bersih',catatan_lab='Catatan lab penerimaan uji',waktu=now_local(),input_by=uid))
                await db.commit()
        await tab_semua('diterima')
        ctx=konteks[-1]
        assert float(ctx['berat_diterima'])==awal[0]==9800
        assert len(ctx['catatan'])==1 and ctx['catatan'][0]['jasa_id']==awal[1]
        async with pg() as db:
            row=await db.get(model,rid)
            akhir=(float(getattr(row,'berat_total_kg',getattr(row,'berat_kg',None))),row.jasa_id)
            assert awal==akhir
        if os.environ.get('BUKTI_PENERIMAAN'):
            folder=Path(os.environ['BUKTI_PENERIMAAN']);(folder/(nama+'-nilai.json')).write_text(json.dumps({'sebelum_render':awal,'sesudah_render':akhir,'total_diterima':float(ctx['berat_diterima']),'catatan':len(ctx['catatan'])}))
            Path('/tmp/penerimaan-session.json').write_text(json.dumps({'cookies':{x.name:x.value for x in c.cookies.jar},'tid':tid,'lain':lengkap['tiket']['BERAS_PK']}))


async def test_beberapa_catatan_pemilik_tidak_diganti_bobot_tiket(pg,lengkap):
    from app.database import now_local
    tid=lengkap['tiket']['BERAS_MASUK']
    async with await _klien(pg,role='superadmin') as c:
        c.headers['X-CSRF-Token']=cap_formulir(c)
        assert (await c.post('/api/actions/catat-produk-timbang-masuk',json={'timbangan_transaksi_id':tid})).status_code==200
        async with pg() as db:
            a=await db.scalar(select(FinishedGoodsStock).where(FinishedGoodsStock.source_type=='timbangan',FinishedGoodsStock.source_id==tid))
            # Data historis beberapa catatan dalam satu tiket, berbeda pemilik.
            b=FinishedGoodsStock(product_sku_id=a.product_sku_id,rice_quality_standard_id=a.rice_quality_standard_id,source_type='timbangan',source_id=tid,jumlah_karung=40,berat_total_kg=2000,warehouse_id=a.warehouse_id,waktu=now_local(),input_by=a.input_by,jasa_id=lengkap['jasa_id'])
            db.add(b);await db.commit()
        for tab in ('ringkasan','riwayat','tiket'):
            r=await c.get(f'/barang-masuk/{tid}?tab_detail={tab}');assert r.status_code==200
            assert '11.800 kg' in r.text and '2 catatan' in r.text
            assert 'identitas-barang__label--campuran' in r.text
            assert 'Bu Sri' in r.text and 'Milik pabrik' in r.text
            assert 'tab=produk&amp;pemilik=jasa' in r.text and 'tab=produk&amp;pemilik=pabrik' in r.text
            bukti('campuran-diterima-'+tab,r.text)


async def test_partai_semua_titik_tanpa_pasangan_truk_palsu(pg,lengkap):
    tid=lengkap['tiket']['GABAH_KERING']
    async with pg() as db:
        assert await db.scalar(text("SELECT to_regclass('timbangan_penimbangan')")) is None
        await db.execute(text('CREATE TABLE timbangan_penimbangan (id SERIAL PRIMARY KEY,transaksi_id INTEGER,urutan INTEGER,berat_kg NUMERIC(12,2),waktu TIMESTAMPTZ,catatan TEXT,petugas_id INTEGER)'))
        await db.execute(text("UPDATE timbangan_transaksi SET cara_timbang='PARTAI',timbang2_kg=NULL,netto_timbangan_kg=600,berat_barang_kg=600 WHERE id=:t"),{'t':tid})
        for n in (1,2,3):
            await db.execute(text('INSERT INTO timbangan_penimbangan(transaksi_id,urutan,berat_kg,waktu,catatan) VALUES(:t,:n,:kg,now(),:c)'),{'t':tid,'n':n,'kg':n*100,'c':f'Penimbangan partai uji {n}'})
        await db.commit()
    try:
        async with await _klien(pg,role='superadmin') as c:
            r=await c.get(f'/barang-masuk/{tid}?tab_detail=tiket');assert r.status_code==200
            for kata in ('Total partai kecil','600 kg','3 kali','Timbang 1','Timbang 2','Timbang 3','Penimbangan partai uji 3'):assert kata in r.text
            assert 'Timbang pertama' not in r.text and 'Timbang kedua' not in r.text
            bukti('partai-belum-tiket',r.text)
    finally:
        async with pg() as db:await db.execute(text('DROP TABLE timbangan_penimbangan'));await db.commit()


async def test_jenis_belum_dikenal_tetap_terbaca_tanpa_tindakan_baru(pg,lengkap):
    from tests.pg.test_tiket_antrean_produksi import _tiket
    async with pg() as db:
        tid=await _tiket(db,'TRX-JENIS-ASING','JENIS_UJI_ASING');await db.commit()
    async with await _klien(pg,role='superadmin') as c:
        r=await c.get(f'/barang-masuk/{tid}?tab_detail=tiket');assert r.status_code==200
        assert 'JENIS_UJI_ASING' in r.text and 'Gudang belum diketahui' in r.text
        assert 'buka=gabah_masuk' not in r.text and 'buka=catat_pk_luar' not in r.text
        bukti('jenis-lama-belum-tiket',r.text)
        if os.environ.get('BUKTI_PENERIMAAN'):
            Path('/tmp/penerimaan-session.json').write_text(json.dumps({'cookies':{x.name:x.value for x in c.cookies.jar},'tid':lengkap['tiket']['BERAS_PK'],'gabah':lengkap['tiket']['GABAH_KERING']}))
