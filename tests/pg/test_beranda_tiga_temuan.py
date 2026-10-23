"""Beranda: kegagalan terpisah, partisi antrean dan tujuan Pengiriman."""
import ast
from pathlib import Path
from dataclasses import asdict
import pytest
from sqlalchemy import select,func
from app.models import User,OutgoingRecord
from app.services import berjalan as svc
from app.services.kelompok_kerja import bagi
from tests.pg.test_barang_keluar import gudang,_perintah
from tests.pg.test_grup_keputusan_http import _klien
from tests.pg.test_konsolidasi_pekerjaan import lengkap,stok_lengkap,sosoh_jasa
from tests.pg.test_proses_aktif_detail import pengeringan,dryer_pabrik

pytestmark=pytest.mark.asyncio
OUT=Path('output/beranda402');OUT.mkdir(parents=True,exist_ok=True)

@pytest.mark.parametrize('gagal',['tidak','pekerjaan','ringkasan','pengiriman','semua'])
async def test_kosong_dan_gagal_terpisah(pg,gudang,monkeypatch,gagal):
    from app import main
    from app.services import barang_keluar
    async def rusak(*a,**kw):raise RuntimeError('DETAIL RAHASIA DATABASE')
    async def kosong(*a,**kw):return svc.Berjalan()
    if gagal in ('pekerjaan','semua'):monkeypatch.setattr(svc,'untuk',rusak)
    else:monkeypatch.setattr(svc,'untuk',kosong)
    if gagal in ('ringkasan','semua'):monkeypatch.setattr(main,'dashboard_data',rusak)
    if gagal in ('pengiriman','semua'):monkeypatch.setattr(barang_keluar,'menunggu_muat',rusak)
    async with await _klien(pg,gudang['adm']) as c:
        for _ in range(2):
            r=await c.get('/');assert r.status_code==200
            assert 'DETAIL RAHASIA' not in r.text
            assert ('Semua sudah ditangani.' in r.text)==(gagal == 'tidak')
            assert ('Tidak ada mesin yang menyala.' in r.text)==(gagal not in ('pekerjaan','semua'))
            if gagal!='tidak':assert 'Coba lagi' in r.text
        OUT.joinpath(f'{gagal}.html').write_text(r.text)
    async with pg() as db:assert await db.scalar(select(func.count()).select_from(OutgoingRecord))==0

async def test_pengiriman_hitungan_transaksi_dan_akses(pg,gudang):
    from app.services import barang_keluar
    a=await _perintah(pg,gudang,karung=10,pembeli='SATU')
    b=await _perintah(pg,gudang,karung=20,pembeli='DUA')
    for role in ('adm','op'):
        async with pg() as db:
            user=await db.get(User,gudang[role]);rows=await barang_keluar.menunggu_muat(db,user)
            assert len(rows)==2
        async with await _klien(pg,gudang[role]) as c:
            h=await c.get('/');r=await c.get('/barang-keluar?status=perintah')
            assert h.status_code==r.status_code==200
            assert '/barang-keluar?status=perintah' in h.text
            import re
            assert re.search(r'href="/barang-keluar\?status=perintah"[^>]*>.*?class="lencana">2</span>',h.text,re.S)
            assert 'SATU' in r.text and 'DUA' in r.text
            assert (await c.get('/pekerjaan?tab=tindakan&grup=muat')).status_code==200
            assert (await c.get(f'/barang-keluar/{a.rec.id}')).status_code==200
    from tests.pg.test_riwayat_giling import _klien as klien_peran
    async with await klien_peran(pg,peran='operator',gudang='Gudang 1') as c:
        assert (await c.get('/barang-keluar?status=perintah')).status_code==403
        assert '/barang-keluar?status=perintah' not in (await c.get('/')).text

async def test_informasi_tetap_bisa_ditemukan(pg,gudang,monkeypatch):
    from app.main import app
    from app.services.keputusan import SEMUA
    kartu=[svc.Baris(str(i),a,'',aksi=a) for i,a in enumerate(set(svc._GRUP_AKSI)|set(SEMUA))]
    diam=svc.Baris('INFO-UNIK','Catatan tanpa tindakan','')
    tiket=svc.Baris('TIKET-INFO','Tiket belum diterima','',kelompok='tiket')
    b=svc.Berjalan(menunggu=kartu+[diam,tiket],transit=[svc.Baris('TR','Transit','')])
    k=bagi(b)
    from collections import Counter
    assert Counter(map(id,k.masuk+k.tindakan+k.informasi+k.berjalan))==Counter(map(id,b.menunggu+b.transit))
    assert diam in k.informasi and diam not in k.tindakan and tiket in k.masuk
    async def baca(*a,**kw):return b
    monkeypatch.setattr(svc,'untuk',baca)
    async with await _klien(pg,gudang['adm']) as c:
        h=await c.get('/');r=await c.get('/pekerjaan?tab=berjalan&informasi=1')
        assert 'href="/aksi"' not in h.text and 'informasi=1' in h.text
        assert 'INFO-UNIK' in r.text and 'TR' in r.text
        assert 'Perlu tindakan' in r.text and 'class="kerja-tab__nama">Berjalan</span>' in r.text

async def test_proses_hari_lalu_tetap_aktif_saat_ringkasan_gagal(pg,pengeringan,monkeypatch):
    from app import main
    from app.models import DryingLot
    from datetime import timedelta
    from app.database import now_local
    from tests.pg.test_riwayat_giling import _klien as klien_peran
    async with pg() as db:
        lot=await db.get(DryingLot,pengeringan['id']);lot.waktu_mulai_pengeringan=now_local()-timedelta(days=2);await db.commit()
    async def rusak(*a,**kw):raise RuntimeError('uji')
    monkeypatch.setattr(main,'dashboard_data',rusak)
    async with await klien_peran(pg,peran='operator',gudang='Gudang 1') as c:
        r=await c.get('/');assert pengeringan['kode'] in r.text
        assert 'Ringkasan operasional belum dapat dimuat' in r.text
        assert 'Tidak ada mesin yang menyala' not in r.text
        assert 'buka=kadar_air' in r.text

async def test_pembanding_akun_data_sama(pg,pengeringan,monkeypatch):
    from app import main
    from app.web.tampilan import templates
    from jinja2 import ChoiceLoader,DictLoader
    from tests.pg.test_riwayat_giling import _klien as klien_peran
    import json
    text=Path(__file__).resolve().parents[1].joinpath('fixtures/beranda_sebelum402/main.py.txt').read_text()
    fn=next(x for x in ast.parse(text).body if isinstance(x,ast.AsyncFunctionDef) and x.name=='beranda')
    fn.decorator_list=[]
    rekam=[]
    asli=main.render
    mode=['sebelum']
    def render(request,nama,**kw):
        if nama=='beranda.html':
            rekam.append({k:[asdict(x) for x in kw[k]] for k in ('berjalan','transit')})
            if mode[0]=='sebelum':nama='beranda_402_sebelum.html'
            kw['layar']='beranda'
        return asli(request,nama,**kw)
    env={**main.__dict__,'render':render}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<beranda-sebelum>','exec'),env)
    monkeypatch.setattr(main,'render',render)
    monkeypatch.setattr(templates.env,'loader',ChoiceLoader([DictLoader({'beranda_402_sebelum.html':Path(__file__).resolve().parents[1].joinpath('fixtures/beranda_sebelum402/beranda.html.txt').read_text()}),templates.env.loader]))
    route=next(r for r in main.app.routes if getattr(r,'path',None)=='/')
    async with await klien_peran(pg,peran='admin') as c:
        for theme in ('1','0'):
            c.cookies.set('produksi_terik',theme)
            for tahap in ('sebelum','sesudah'):
                mode[0]=tahap
                monkeypatch.setattr(route.dependant,'call',env['beranda'] if tahap=='sebelum' else main.beranda)
                r=await c.get('/');assert r.status_code==200
                OUT.joinpath(f'aktif-{tahap}-{theme}.html').write_text(r.text)
            assert rekam[-1]==rekam[-2]
    OUT.joinpath('paritas.json').write_text(json.dumps({'proses_dan_transit_identik':True,'kartu':rekam[-1]},default=str,indent=2))
