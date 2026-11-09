"""HTTP aplikasi asli: spek beras dan hasil samping baru dalam satu kiriman."""
import os,re
from uuid import uuid4
import httpx
import pytest
from sqlalchemy import select,text
from app.models import User,ProductSku,RiceQualityStandard,PolishingProcess,PolishingOutputLog
from app.database import now_local
from app.services import spesifikasi_beras as beras,jenis_hasil_samping as hs,stok,barang_keluar as bk
from app.penggilingan.inventory.finished_goods import catat_packing
from tests.pg.test_barang_keluar import gudang,_pelanggan
from tests.pg.test_kiriman_pelanggan import _buat,_muat
from tests.pg.test_teraflow_kiriman import _skema_head,servers,akun,profil

pytestmark=[pytest.mark.asyncio,pytest.mark.dua_aplikasi]

async def test_master_baru_pengiriman_dan_verifikasi_satu_saldo(pg,gudang):
    g=gudang;pid=await _pelanggan(pg,'Penerima master dinamis')
    async with pg() as db:
        u=await db.get(User,g['adm']);grade=await beras.simpan(db,user=u,nama='Ramos baru integrasi',broken='5',sosoh='110')
        kode=await hs.simpan(db,user=u,aksi='tambah',nama='Samping baru integrasi',bentuk='karung',kg_karung='37')
        proc=await db.scalar(select(PolishingProcess));std=grade.id;rice=grade.kode
        db.add_all([PolishingOutputLog(polishing_process_id=proc.id,jenis=rice,berat_kg=300,waktu_update=now_local(),input_by=u.id),PolishingOutputLog(polishing_process_id=proc.id,jenis=kode,berat_kg=600,waktu_update=now_local(),input_by=u.id)]);await db.commit()
        await catat_packing(db,user=u,kode_pol=proc.kode_proses,kategori='beras_putih',grade=rice,material_kode='biasa',ukuran=25,jumlah_karung=4)
    rs=await _buat(pg,g,dict(kelompok=[dict(pelanggan=str(pid),barang=[dict(pilih=f'bj:{g["sku"]}|{std}',jumlah='2'),dict(pilih='cr:'+kode,jumlah='100')])],metode='diantar',nama_ekspedisi='Armada master'))
    aid=await akun(pg,g)
    def saldo(cards):return {k.jenis:k.sisa_kg for k in cards if k.jenis in (rice,kode)}
    with servers(os.environ['UJI_PG_URL']) as (tf,pf):
        await profil(pg,aid)
        async with httpx.AsyncClient(base_url=tf,timeout=30,follow_redirects=False) as c:
            r=await c.post('/timbangan/masuk',data={'username':'uji_lintas','sandi':'uji-lintas-aman','perangkat':'UT'});assert r.status_code==303
            r=await c.post('/timbangan/timbang/PENGIRIMAN',data=dict(kunci=str(uuid4()),berat_kg='5000',nomor_polisi='B 1234 XY',nama_sopir='Sopir integrasi'))
            assert r.status_code==303 and '/transaksi/' in r.headers.get('location',''),r.headers
            tid=int(re.search(r'/transaksi/(\d+)',r.headers['location'])[1])
            async with pg() as db:await bk.pilih_tiket_armada(db,user=await db.get(User,g['adm']),rec_id=rs[0].rec.id,tiket_id=tid)
            await _muat(pg,g,rs)
            async with pg() as db:before=saldo(await stok.stok_produk(db))
            assert before=={rice:250,kode:500}
            async with httpx.AsyncClient(base_url=pf,timeout=30) as pc:
                r=await pc.get(f'/internal/pengiriman/tiket/{tid}/muatan',headers={'X-Internal-Token':'uji-lintas-kiriman'})
                assert r.status_code==200,r.text
                payload=r.json();rows=payload['muatan']
                assert any(x['jenis_kode']==kode.upper() and x['nama'].startswith('Samping baru integrasi') for x in rows)
                assert any(x['kualitas_id']==std and 'Ramos baru integrasi' in x['nama'] for x in rows)
            gross=5000+sum(float(x['berat_kg'])+x['jumlah_karung']*float(x['tara_per_karung_kg']) for x in rows)
            r=await c.post(f'/timbangan/tiket/{tid}',data={'berat_kg':str(gross),'aksi':'selesai'})
            assert r.status_code==303 and 'err=' not in r.headers.get('location',''),r.headers
            for _ in range(2):
                r=await c.get(f'/timbangan/transaksi/{tid}');assert r.status_code==200 and 'Samping baru integrasi' in r.text and 'Ramos baru integrasi' in r.text
            async with pg() as db:
                assert saldo(await stok.stok_produk(db))==before
                snap=await db.scalar(text('SELECT pengiriman_snapshot FROM timbangan_transaksi WHERE id=:id'),{'id':tid})
                assert snap and await db.scalar(text('SELECT count(*) FROM timbangan_transaksi'))==1
