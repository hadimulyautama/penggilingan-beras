"""Satu kunci yang sama harus menghasilkan satu pemindahan walau dikirim ulang."""
from uuid import uuid4
import pytest
from sqlalchemy import select,func
from app.models import BrokenKeSilo,HasilSampingKeSilo
from tests.pg.test_form_menir_silo import sosoh
from tests.pg.test_form_menir_silo import menir
from tests.pg.test_barang_keluar import _klien
from tests.pg.formulir import cap_formulir

@pytest.mark.parametrize('jenis',['menir','reject'])
async def test_menir_reject_kunci_sama_hanya_satu_pemindahan(pg,menir,jenis):
    async with await _klien(pg,menir['user'],'samping-kunci',mode='admin') as c:
        body=dict(pemilik='pabrik',silo='Campuran Timur',berat_kg=75,kunci_kiriman=uuid4().hex)
        for _ in range(2):
            r=await c.post('/api/actions/masukkan-'+jenis+'-silo',json=body,headers={'X-CSRF-Token':cap_formulir(c)})
            assert r.status_code==200,r.text
    async with pg() as db:assert await db.scalar(select(func.sum(HasilSampingKeSilo.berat_kg)).where(HasilSampingKeSilo.jenis==jenis))==75

@pytest.mark.parametrize('jenis',['menir','reject'])
async def test_ulangi_setelah_seluruh_stok_habis_tetap_hasil_asli(pg,menir,jenis):
    async with await _klien(pg,menir['user'],'samping-habis',mode='admin') as c:
        payload=dict(pemilik='pabrik',silo='Campuran Timur',berat_kg=950,kunci_kiriman=uuid4().hex)
        hasil=[]
        for _ in range(2):
            r=await c.post('/api/actions/masukkan-'+jenis+'-silo',json=payload,headers={'X-CSRF-Token':cap_formulir(c)})
            assert r.status_code==200,r.text
            hasil.append(r.json()['rincian_'+jenis]['codes'])
        assert hasil[0]==hasil[1]
    async with pg() as db:
        assert await db.scalar(select(func.sum(HasilSampingKeSilo.berat_kg)).where(HasilSampingKeSilo.jenis==jenis))==950

@pytest.mark.parametrize('kunci',[None,'','pendek','spasi tidak sah di kunci','x'*81])
async def test_kunci_hilang_atau_tidak_sah_ditolak_tanpa_mutasi(pg,menir,kunci):
    async with await _klien(pg,menir['user'],'samping-kunci-tidak-sah',mode='admin') as c:
        payload=dict(pemilik='pabrik',silo='Campuran Timur',berat_kg=75,kunci_kiriman=kunci)
        for jenis in ['menir','reject']:
            r=await c.post('/api/actions/masukkan-'+jenis+'-silo',json=payload,headers={'X-CSRF-Token':cap_formulir(c)})
            assert r.status_code==400 and 'Kunci kiriman' in r.text,r.text
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(HasilSampingKeSilo))==0

@pytest.mark.parametrize('perubahan',[{'berat_kg':76},{'silo':'A'},{'pemilik':'99999'}, {'jenis':'reject'}])
async def test_kunci_sama_isian_berbeda_ditolak(pg,menir,perubahan):
    async with await _klien(pg,menir['user'],'samping-benturan',mode='admin') as c:
        payload=dict(pemilik='pabrik',silo='Campuran Timur',berat_kg=75,kunci_kiriman=uuid4().hex)
        r=await c.post('/api/actions/masukkan-menir-silo',json=payload,headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==200,r.text
        ubah=dict(perubahan);jenis=ubah.pop('jenis','menir')
        r=await c.post('/api/actions/masukkan-'+jenis+'-silo',json=dict(payload,**ubah),headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==400 and 'sudah dipakai' in r.text,r.text
    async with pg() as db:assert await db.scalar(select(func.sum(HasilSampingKeSilo.berat_kg)))==75

async def test_kunci_diikat_petugas_dan_izin_diperiksa_ulang(pg,menir):
    from app.models import User
    async with await _klien(pg,menir['user'],'samping-petugas-asal',mode='admin') as c:
        payload=dict(pemilik='pabrik',silo='Campuran Timur',berat_kg=75,kunci_kiriman=uuid4().hex)
        r=await c.post('/api/actions/masukkan-menir-silo',json=payload,headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==200,r.text
        async with pg() as db:
            u=User(nama='Petugas kedua',role='superadmin',status='aktif');db.add(u);await db.commit();uid=u.id
        async with await _klien(pg,uid,'samping-petugas-beda',mode='admin') as lain:
            r=await lain.post('/api/actions/masukkan-menir-silo',json=payload,headers={'X-CSRF-Token':cap_formulir(lain)})
            assert r.status_code==400 and 'petugas lain' in r.text,r.text
        async with pg() as db:
            u=await db.get(User,menir['user']);u.role='admin';await db.commit()
        r=await c.post('/api/actions/masukkan-menir-silo',json=payload,headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code in (401,403),r.text

async def test_kiriman_paralel_kunci_sama_satu_tanda_terima(pg,menir):
    import asyncio
    from app.models import User,Peristiwa
    from app.penggilingan.gudang2 import service as g2
    from app.services.kiriman_samping_silo import simpan,JENIS
    key=uuid4().hex
    async def kirim():
        async with pg() as db:
            u=await db.get(User,menir['user'])
            isian=dict(jenis='menir',jasa_id=None,nama_silo='Campuran Timur',berat_kg=75)
            return await simpan(db,user=u,kunci=key,aksi='menir',isian=isian,
                kerjakan=lambda:g2.masukkan_hasil_samping_ke_silo(db,user=u,**isian,commit=False))
    hasil=await asyncio.gather(*(kirim() for _ in range(4)))
    assert all(x==hasil[0] for x in hasil)
    async with pg() as db:
        assert await db.scalar(select(func.sum(HasilSampingKeSilo.berat_kg)))==75
        assert await db.scalar(select(func.count()).select_from(Peristiwa).where(Peristiwa.jenis==JENIS))==1

async def test_gagal_menyimpan_tanda_terima_membatalkan_mutasi_dan_audit(pg,menir,monkeypatch):
    from app.models import User,Peristiwa,ActivityLog
    from app.penggilingan.gudang2 import service as g2
    from app.services import kiriman_samping_silo as ks
    async def gagal(*args,**kwargs):raise RuntimeError('tanda terima gagal')
    monkeypatch.setattr(ks.buku,'catat',gagal)
    async with pg() as db:
        u=await db.get(User,menir['user'])
        isian=dict(jenis='menir',jasa_id=None,nama_silo='Campuran Timur',berat_kg=75)
        with pytest.raises(RuntimeError,match='tanda terima gagal'):
            await ks.simpan(db,user=u,kunci=uuid4().hex,aksi='menir',isian=isian,
                kerjakan=lambda:g2.masukkan_hasil_samping_ke_silo(db,user=u,**isian,commit=False))
        await db.commit() # Bahkan pemanggil yang commit setelah galat tidak membocorkan child.
        assert await db.scalar(select(func.count()).select_from(HasilSampingKeSilo))==0
        assert await db.scalar(select(func.count()).select_from(Peristiwa))==0
        assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.table_name=='hasil_samping_ke_silo'))==0
