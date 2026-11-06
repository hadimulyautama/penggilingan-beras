"""Navigasi baru memakai master, writer, dan penjaga lama pada Postgres terpisah."""
import re
import pytest
from sqlalchemy import select, text, func
from app.models import Dryer, LiniProduksi, JenisProsesProduksi, Warehouse, Silo, AuditFasilitas
from hmu_identitas import peran as P
from tests.pg.test_pengaturan_usulan import master, klien, kirim
from tests.pg.test_qc_berjalan import giling

pytestmark = pytest.mark.asyncio
PAGES = ('mesin', 'silo', 'jenis-proses', 'gudang')

async def mesin(pg):
    async with pg() as db:
        d=await db.scalar(select(Dryer).order_by(Dryer.id))
        l=await db.scalar(select(LiniProduksi).where(LiniProduksi.dryer_id==d.id))
        return d.id, l.id

async def fisik(pg):
    # Konfigurasi boleh berubah; penerimaan, proses, stok, timbang dan peristiwa tidak.
    names=('purchase_batches','pk_purchase_batches','finished_goods_stock','byproduct_stock',
        'drying_lots','milling_process','polishing_process','timbangan_transaksi','peristiwa')
    async with pg() as db:
        return {t:(await db.execute(text(f'SELECT count(*), md5(coalesce(string_agg(row_to_json(t)::text, \'\' ORDER BY row_to_json(t)::text),\'\')) FROM {t} t'))).one() for t in names}

async def test_lima_kelompok_tanpa_tabel_akses_dan_sidebar_sama(pg,master,giling):
    c,_,_=await klien(pg,P.SUPERADMIN)
    before=await fisik(pg)
    async with c:
        home=await c.get('/pengaturan')
        headings=re.findall(r'<h2 id="pg-[^"]+">(.*?)</h2>',home.text)
        assert headings==['Akun &amp; perangkat','Perusahaan &amp; fasilitas','Operasional','Pengguna &amp; hak akses','Sistem &amp; koneksi']
        assert '<table' not in home.text and 'href="/pengaturan/alat"' not in home.text
        assert 'href="/pengaturan/fasilitas"' not in home.text
        assert '<table' in (await c.get('/pengaturan/akses')).text
        did,lid=await mesin(pg)
        for path in ['/pengaturan/'+x for x in PAGES]+['/pengaturan/perusahaan',f'/pengaturan/mesin/{lid}']:
            r=await c.get(path);assert r.status_code==200,r.text
            # Salinan sidebar lama tidak muncul pada halaman perusahaan/fasilitas.
            for href in ('/stok-produk','/stok-produk-jasa','/stok-pk-jasa','/stok-karung','/stok-karung-jasa'):
                assert f'href="{href}"' not in r.text
            assert 'Perusahaan &amp; fasilitas' in r.text
        assert (await c.get('/pengaturan/fasilitas')).headers['location']=='/pengaturan/mesin'
        old=await c.get('/pengaturan/alat');assert '/pengaturan/mesin' in old.text and '/pengaturan/silo' in old.text
    assert before==await fisik(pg)

@pytest.mark.parametrize('role,view,allow',[(P.SUPERADMIN,None,True),(P.SUPERADMIN,'operator:g2',False),(P.SUPERADMIN,P.ADMIN,False),(P.ADMIN,None,False),(P.OPERATOR,None,False)])
async def test_otorisasi_halaman_dan_post_lama_baru(pg,master,role,view,allow):
    from app.web.lihat_sebagai import NAMA_KUKI
    # Super aktif menutup jaring pengaman Admin.
    superc,_,_=await klien(pg,P.SUPERADMIN,username='super_guard')
    await superc.aclose()
    c,_,_=await klien(pg,role,'Gudang 2' if P.operator_saja(role) else None)
    if view:c.cookies.set(NAMA_KUKI,view)
    did,lid=await mesin(pg)
    async with c:
        for path in ['/pengaturan/'+x for x in PAGES]+[f'/pengaturan/mesin/{lid}','/pengaturan/perusahaan']:
            assert (await c.get(path)).status_code==(200 if allow else 403)
        if not allow:
            for path,data in [('/pengaturan/fasilitas',{'objek':'jenis','kode':'nouveau','nama':'Tidak boleh'}),('/pengaturan/alat/dryer/edit',{'dryer_id':did,'nama':'Tidak boleh','kapasitas_kg':'20000','target_kadar_air':'15'})]:
                assert (await kirim(c,path,data)).status_code==403

async def test_dryer_null_fallback_hubungan_terpisah_dan_isian_gagal(pg,master):
    c,_,_=await klien(pg,P.SUPERADMIN);did,lid=await mesin(pg)
    async with pg() as db:
        d=await db.get(Dryer,did);d.target_kadar_air=None
        l=await db.get(LiniProduksi,lid);line=dict(objek='lini',id=lid,versi=l.versi,nama=l.nama,kode=l.kode,warehouse_id=l.warehouse_id,jenis_proses_id=l.jenis_proses_id,dryer_id=did,aktif='on',kembali_pengaturan=f'/pengaturan/mesin/{lid}')
        await db.commit()
    before=await fisik(pg)
    async with c:
        r=await c.get(f'/pengaturan/mesin/{lid}');assert 'Gunakan target umum' in r.text and 'value="None"' not in r.text
        assert 'name="kapasitas_kg"' in r.text and 'name="tungku"' in r.text and 'Hubungan proses &amp; kode' in r.text
        assert (await kirim(c,'/pengaturan/fasilitas',line)).status_code==303
        async with pg() as db:assert (await db.get(Dryer,did)).target_kadar_air is None
        data=dict(dryer_id=did,nama='Pengering teruji',kapasitas_kg='28000',target_kadar_air='14,5',target_umum='1',tungku='Tungku uji',kembali_pengaturan=f'/pengaturan/mesin/{lid}')
        assert (await kirim(c,'/pengaturan/alat/dryer/edit',data)).headers['location'].startswith(f'/pengaturan/mesin/{lid}')
        async with pg() as db:
            d=await db.get(Dryer,did);assert d.target_kadar_air is None and d.kapasitas_kg==28000
        data.pop('target_umum');await kirim(c,'/pengaturan/alat/dryer/edit',data)
        async with pg() as db:assert float((await db.get(Dryer,did)).target_kadar_air)==14.5
        data['kapasitas_kg']='bukan angka';data['nama']='Nama harus tetap'
        r=await kirim(c,'/pengaturan/alat/dryer/edit',data)
        assert r.status_code==200 and 'role="alert"' in r.text and 'value="Nama harus tetap"' in r.text
        async with pg() as db:assert (await db.get(Dryer,did)).nama=='Pengering teruji'
    assert before==await fisik(pg)

async def test_silo_semua_jenis_tujuan_gabah_dan_validasi_dipertahankan(pg,master):
    c,_,_=await klien(pg,P.SUPERADMIN)
    async with pg() as db:
        silos=list((await db.scalars(select(Silo).where(Silo.aktif.is_(True)))).all())
        w=await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi=='g2'));wid=w.id
        sid=silos[0].id
    async with c:
        page=await c.get('/pengaturan/silo')
        for silo in silos:assert silo.nama_silo in page.text
        r=await kirim(c,'/pengaturan/alat/silo',dict(nama='Gabah G2 uji',warehouse_id=wid,jenis_isi='gabah',kembali_pengaturan='/pengaturan/silo'))
        assert r.headers['location'].startswith('/pengaturan/silo')
        async with pg() as db:
            added=await db.scalar(select(Silo).where(Silo.nama_silo=='Silo Gabah G2 uji'))
            assert added.warehouse_id==wid and added.jenis_isi=='gabah'
        r=await kirim(c,'/pengaturan/alat/silo/edit',dict(silo_id=sid,nama='Nama tetap di isian',komoditas='tidak-sah',kembali_pengaturan='/pengaturan/silo'))
        assert r.status_code==200 and 'Pilih komoditas yang valid' in r.text and 'Nama tetap di isian' in r.text
        r=await kirim(c,'/pengaturan/alat/silo/edit',dict(silo_id=sid,nama='Tidak ada pilihan',kembali_pengaturan='/pengaturan/silo'))
        assert r.status_code==200 and '"komoditas": []' in r.text

async def test_tambah_dryer_line_jenis_baru_tidak_memulai_proses(pg,master):
    c,_,_=await klien(pg,P.SUPERADMIN)
    async with pg() as db:wid=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi=='g2'))
    before=await fisik(pg)
    async with c:
        r=await kirim(c,'/pengaturan/alat/dryer',dict(nama='Dryer tambahan uji',warehouse_id=wid,kapasitas_kg='24000',kembali_pengaturan='/pengaturan/mesin'))
        assert r.headers['location'].startswith('/pengaturan/mesin')
        async with pg() as db:
            d=await db.scalar(select(Dryer).where(Dryer.nama=='Dryer tambahan uji'))
            l=await db.scalar(select(LiniProduksi).where(LiniProduksi.dryer_id==d.id))
            assert l.warehouse_id==wid
        r=await kirim(c,'/pengaturan/fasilitas',dict(objek='jenis',nama='Jenis uji saja',kode='uji-saja',aktif='on',kembali_pengaturan='/pengaturan/jenis-proses'))
        assert r.headers['location'].startswith('/pengaturan/jenis-proses')
        assert 'belum ada layanan pelaksana' in (await c.get('/pengaturan/jenis-proses')).text or 'dukungan bahan' in (await c.get('/pengaturan/jenis-proses')).text
    assert before==await fisik(pg)

async def test_gudang_gagal_dan_target_umum_memakai_konfigurasi_lama(pg,master,giling):
    from app.services.setelan import target_kadar_air
    c,_,_=await klien(pg,P.SUPERADMIN)
    did,lid=await mesin(pg)
    async with pg() as db:
        d=await db.get(Dryer,did);d.target_kadar_air=13.5;await db.commit()
    before=await fisik(pg)
    async with c:
        r=await kirim(c,'/pengaturan/gudang/tambah',dict(nama='Isian gudang utuh',alamat='Alamat uji utuh',latitude='999',longitude='106',kembali_pengaturan='/pengaturan/gudang'))
        assert r.status_code==200 and 'Koordinat di luar batas' in r.text
        assert 'Isian gudang utuh' in r.text and 'Alamat uji utuh' in r.text
        r=await kirim(c,'/pengaturan/target-kadar-air',dict(nilai='15,2',kembali_pengaturan='/pengaturan/mutu'))
        assert r.headers['location']=='/pengaturan/mutu?pesan=target-diubah'
        async with pg() as db:
            assert await target_kadar_air(db)==15.2
            assert float((await db.get(Dryer,did)).target_kadar_air)==13.5
        assert '15.2' in (await c.get('/pengaturan/mutu')).text
    assert before==await fisik(pg)

async def test_penjaga_mesin_dan_silo_dipakai_tetap_berlaku(pg,master,giling):
    from app.models import DryingLot, MillingProcess
    c,_,uid=await klien(pg,P.SUPERADMIN)
    did,lid=await mesin(pg)
    async with pg() as db:
        db.add(DryingLot(kode_lot='PGR-UJI-TERPAKAI',dryer_id=did,created_by=uid,status='proses'))
        p=await db.get(MillingProcess,giling['id']);sid=p.silo_id
        await db.commit()
    before=await fisik(pg)
    async with c:
        r=await kirim(c,'/pengaturan/alat/dryer/status',dict(dryer_id=did,kembali_pengaturan=f'/pengaturan/mesin/{lid}'))
        assert r.status_code==200 and 'kosongkan dulu' in r.text
        r=await kirim(c,'/pengaturan/alat/silo/hapus',dict(silo_id=sid,kembali_pengaturan='/pengaturan/silo'))
        assert r.status_code==200 and 'Silo sedang dipakai proses berjalan' in r.text
    async with pg() as db:
        assert (await db.get(Dryer,did)).status=='aktif'
        assert (await db.get(Silo,sid)).aktif
    assert before==await fisik(pg)
