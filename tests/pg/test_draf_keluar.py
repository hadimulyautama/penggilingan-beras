"""Draf tidak memengaruhi stok; terbit atomik dan tahan pengiriman ulang."""
from uuid import uuid4
import asyncio
import re
import pytest
from sqlalchemy import select, func
from app.models import DrafKeluar, OutgoingRecord, User
from app.web.draf_keluar import simpan, terbitkan, SimpanDraf, TerbitDraf
from fastapi import HTTPException
from tests.pg.test_barang_keluar import gudang, _klien, _stok, _pelanggan

pytestmark = pytest.mark.asyncio

async def _isi(pg,g):
    from app.models import Pelanggan
    async with pg() as db:
        p=Pelanggan(nama_pelanggan='Pembeli draf', kledo_contact_id=363)
        db.add(p);await db.commit()
        return dict(pelanggan=str(p.id),barang=[dict(pilih=f"bj:{g['sku']}|{g['std']}",jumlah='2')])

async def _user(pg,g):
    async with pg() as db:return await db.get(User,g['adm'])

async def test_draf_parsial_bertahan_tanpa_stok_dan_antrean(pg,gudang):
    u=await _user(pg,gudang); ident=uuid4(); awal=await _stok(pg,gudang)
    isi=dict(pelanggan='',barang=[dict(pilih='',jumlah='')])
    req=SimpanDraf(revisi=0,kiriman=uuid4(),isi=isi)
    r=await simpan(ident,req,u);assert r['revisi']==1
    assert (await simpan(ident,req,u))['revisi']==1
    async with pg() as db:
        assert (await db.get(DrafKeluar,str(ident))).isi==isi
        assert await db.scalar(select(func.count()).select_from(OutgoingRecord))==0
    assert await _stok(pg,gudang)==awal
    with pytest.raises(HTTPException):await terbitkan(ident,TerbitDraf(revisi=1),u)
    async with pg() as db:assert (await db.get(DrafKeluar,str(ident))).isi==isi

async def test_dua_tab_tidak_saling_menimpa(pg,gudang):
    u=await _user(pg,gudang);ident=uuid4()
    a=SimpanDraf(revisi=0,kiriman=uuid4(),isi={'pelanggan':'A'})
    b=SimpanDraf(revisi=0,kiriman=uuid4(),isi={'pelanggan':'B'})
    hasil=await asyncio.gather(simpan(ident,a,u),simpan(ident,b,u),return_exceptions=True)
    assert sum(isinstance(x,HTTPException) and x.status_code==409 for x in hasil)==1
    async with pg() as db:
        d=await db.get(DrafKeluar,str(ident));assert d.revisi==1; assert d.isi['pelanggan'] in ('A','B')
    with pytest.raises(HTTPException):await terbitkan(ident,TerbitDraf(revisi=0),u)

async def test_terbit_tanpa_armada_idempoten_dan_stok_tetap(pg,gudang):
    u=await _user(pg,gudang);ident=uuid4();isi=await _isi(pg,gudang);awal=await _stok(pg,gudang)
    await simpan(ident,SimpanDraf(revisi=0,kiriman=uuid4(),isi=isi),u)
    a,b=await asyncio.gather(terbitkan(ident,TerbitDraf(revisi=1),u),terbitkan(ident,TerbitDraf(revisi=1),u))
    assert a['tujuan']==b['tujuan']
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(OutgoingRecord))==1
        rec=await db.get(OutgoingRecord,int(a['tujuan'].split('/')[-1]));assert rec.status=='perintah';assert rec.timbangan_transaksi_id is None
    assert await _stok(pg,gudang)==awal
    with pytest.raises(HTTPException):await simpan(ident,SimpanDraf(revisi=1,kiriman=uuid4(),isi={}),u)

@pytest.mark.parametrize('jumlah',['0','-1','1.5','NaN','Infinity',''])
async def test_jumlah_draf_salah_tetap_utuh_dan_tidak_terbit(pg,gudang,jumlah):
    u=await _user(pg,gudang);ident=uuid4();isi=await _isi(pg,gudang);isi['barang'][0]['jumlah']=jumlah
    await simpan(ident,SimpanDraf(revisi=0,kiriman=uuid4(),isi=isi),u)
    with pytest.raises(HTTPException):await terbitkan(ident,TerbitDraf(revisi=1),u)
    async with pg() as db:
        assert (await db.get(DrafKeluar,str(ident))).isi==isi
        assert await db.scalar(select(func.count()).select_from(OutgoingRecord))==0

async def test_halaman_baru_tanpa_modal_dan_identitas_draf_dipagari(pg,gudang):
    u=await _user(pg,gudang);ident=uuid4()
    await simpan(ident,SimpanDraf(revisi=0,kiriman=uuid4(),isi={'pelanggan':'1'}),u)
    c=await _klien(pg,gudang['adm'],'draf-admin')
    async with c:
        page=await c.get('/barang-keluar/baru');assert page.status_code==200
        assert 'data-editor-perintah' in page.text;assert 'id="draf-terbitkan"' in page.text
        assert 'id="lembar"' not in page.text
        daftar=await c.get('/barang-keluar')
        assert str(ident) in daftar.text
        assert 'Hapus draf' in daftar.text
        page=await c.get(f'/barang-keluar/draf/{ident}');assert page.status_code==200
        r=await c.put(f'/api/actions/draf-perintah/{ident}',json={'isi':{},'revisi':1,'kiriman':str(uuid4())})
        assert r.status_code==403
        # Tanpa token CSRF tidak boleh tersimpan.
        async with pg() as db:assert (await db.get(DrafKeluar,str(ident))).revisi==1
    async with pg() as db:
        u2=User(nama='Admin lain',role=u.role,status='aktif');db.add(u2);await db.commit()
    with pytest.raises(HTTPException) as e:await simpan(ident,SimpanDraf(revisi=1,kiriman=uuid4(),isi={}),u2)
    assert e.value.status_code==404

async def test_http_sesi_lama_ditolak_dan_penerbitan_memakai_pembuka(pg,gudang):
    from app.web import csrf
    ident=uuid4();isi=await _isi(pg,gudang)
    a=await _klien(pg,gudang['adm'],'draf-pembuka')
    async with a:
        halaman=await a.get('/barang-keluar/baru')
        token=re.search(r'name="formulir-sesi" content="([^"]+)"',halaman.text).group(1)
        body=dict(revisi=0,kiriman=str(uuid4()),isi=isi)
        r=await a.put(f'/api/actions/draf-perintah/{ident}',json=body,headers={csrf.NAMA_HEADER:token})
        assert r.status_code==200,r.text
        # Akun berbeda masuk di perangkat/tab lain; header formulir A tetap lama.
        u=await _user(pg,gudang)
        async with pg() as db:
            buser=User(nama='Admin pengganti',role=u.role,status='aktif');db.add(buser);await db.commit();bid=buser.id
        b=await _klien(pg,bid,'draf-pengganti')
        async with b:
            await b.get('/barang-keluar/baru')
            r=await b.post(f'/api/actions/draf-perintah/{ident}/terbitkan',json={'revisi':1},headers={csrf.NAMA_HEADER:token})
            assert r.status_code==403
        r=await a.post(f'/api/actions/draf-perintah/{ident}/terbitkan',json={'revisi':1},headers={csrf.NAMA_HEADER:token})
        assert r.status_code==200,r.text
        async with pg() as db:
            rec=await db.get(OutgoingRecord,int(r.json()['tujuan'].split('/')[-1]));assert rec.diperintah_oleh==gudang['adm']

async def test_hapus_draf_pribadi_tanpa_stok_dan_tidak_bisa_hidup_kembali(pg,gudang):
    from app.web.draf_keluar import hapus, daftar_draf
    ident=uuid4();u=await _user(pg,gudang);isi=await _isi(pg,gudang);stok=await _stok(pg,gudang)
    await simpan(ident,SimpanDraf(revisi=0,kiriman=uuid4(),isi=isi),u)
    async with pg() as db:
        daftar=await daftar_draf(db,u);assert daftar[0]['pelanggan']=='Pembeli draf';assert daftar[0]['jumlah']==1
    with pytest.raises(HTTPException) as e:await hapus(ident,TerbitDraf(revisi=0),u)
    assert e.value.status_code==409
    assert (await hapus(ident,TerbitDraf(revisi=1),u))['ok']
    assert (await hapus(ident,TerbitDraf(revisi=1),u))['ok']
    with pytest.raises(HTTPException):await simpan(ident,SimpanDraf(revisi=1,kiriman=uuid4(),isi=isi),u)
    with pytest.raises(HTTPException):await terbitkan(ident,TerbitDraf(revisi=1),u)
    async with pg() as db:
        assert await daftar_draf(db,u)==[]
        assert (await db.get(DrafKeluar,str(ident))).isi==isi
        assert await db.scalar(select(func.count()).select_from(OutgoingRecord))==0
    assert await _stok(pg,gudang)==stok

async def test_draf_orang_lain_dan_perintah_terbit_tidak_boleh_dihapus(pg,gudang):
    from app.web.draf_keluar import hapus, daftar_draf
    ident=uuid4();u=await _user(pg,gudang);isi=await _isi(pg,gudang)
    await simpan(ident,SimpanDraf(revisi=0,kiriman=uuid4(),isi=isi),u)
    async with pg() as db:
        b=User(nama='Admin draf lain',role=u.role,status='aktif');db.add(b);await db.commit()
        assert await daftar_draf(db,b)==[]
    with pytest.raises(HTTPException) as e:await hapus(ident,TerbitDraf(revisi=1),b)
    assert e.value.status_code==404
    terbit=await terbitkan(ident,TerbitDraf(revisi=1),u)
    with pytest.raises(HTTPException) as e:await hapus(ident,TerbitDraf(revisi=1),u)
    assert e.value.status_code==409
    async with pg() as db:
        assert await daftar_draf(db,u)==[]
        assert (await db.get(OutgoingRecord,int(terbit['tujuan'].split('/')[-1]))).status=='perintah'

async def test_hapus_berlomba_dengan_tab_menyimpan(pg,gudang):
    from app.web.draf_keluar import hapus
    ident=uuid4();u=await _user(pg,gudang)
    await simpan(ident,SimpanDraf(revisi=0,kiriman=uuid4(),isi={'pelanggan':'1'}),u)
    hasil=await asyncio.gather(hapus(ident,TerbitDraf(revisi=1),u),simpan(ident,SimpanDraf(revisi=1,kiriman=uuid4(),isi={'pelanggan':'2'}),u),return_exceptions=True)
    assert sum(isinstance(x,HTTPException) for x in hasil)==1
    async with pg() as db:
        d=await db.get(DrafKeluar,str(ident))
        assert (d.dihapus_pada is not None and d.revisi==1) or (d.dihapus_pada is None and d.revisi==2)

async def test_hapus_berlomba_dengan_penerbitan_tidak_menghapus_perintah(pg,gudang):
    from app.web.draf_keluar import hapus
    ident=uuid4();u=await _user(pg,gudang);isi=await _isi(pg,gudang)
    await simpan(ident,SimpanDraf(revisi=0,kiriman=uuid4(),isi=isi),u)
    hasil=await asyncio.gather(hapus(ident,TerbitDraf(revisi=1),u),terbitkan(ident,TerbitDraf(revisi=1),u),return_exceptions=True)
    assert sum(isinstance(x,HTTPException) for x in hasil)==1
    async with pg() as db:
        d=await db.get(DrafKeluar,str(ident))
        assert bool(d.dihapus_pada) != bool(d.perintah_id)
        if d.perintah_id:assert (await db.get(OutgoingRecord,d.perintah_id)).status=='perintah'
    assert await _stok(pg,gudang)==10000
