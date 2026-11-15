"""Pemulihan akun tidak menghidupkan kembali kredensial sesi/tautan lama."""
import pytest
from sqlalchemy import select
from hmu_core import User,KeanggotaanPerusahaan
from hmu_identitas.model import Akun
from hmu_identitas import masuk
from app.models.portal import PortalAccount
from app.services import console_bantuan as bantuan
from tests.pg.test_console_monitoring import orang,action,ALLOWED
from tests.pg.test_koreksi_bahan_berjalan import running,dunia
from tests.pg.test_pengaturan_organisasi import fakta
pytestmark=[pytest.mark.asyncio,pytest.mark.fondasi_multi]

@pytest.mark.parametrize('jenis',['staf','pelanggan'])
async def test_aktivasi_memutus_sesi_dan_cap_lama_tanpa_mengubah_peran_atau_transaksi(pg,orang,jenis):
    x=orang;aid=x['aid'] if jenis=='staf' else x['portal']
    old,_=await action(pg,x,'tautan_sandi',jenis,aid)
    async with pg() as db:
        row=await db.get(Akun if jenis=='staf' else PortalAccount,aid)
        version=row.token_version;password=row.password_hash
        # Status impor/akun lama dapat tersimpan tanpa pencabutan versi.
        if jenis=='staf':row.status='nonaktif'
        else:row.active=False
        await db.commit()
    before=await fakta(pg)
    _,plan=await action(pg,x,'aktifkan_akun',jenis,aid)
    async with pg() as db:
        row=await db.get(Akun if jenis=='staf' else PortalAccount,aid)
        assert row.token_version==version+1 and row.password_hash==password
        if jenis=='staf':
            assert row.aktif and row.user.role=='operator'
            assert await masuk.akun_aktif(db,aid,version) is None
        else:assert row.active
        with pytest.raises(ValueError):await bantuan.periksa_pemulihan(db,old['cap'])
        again=await bantuan.terapkan(db,cid=x['cid'],jenis=jenis,aid=aid,pelaku_id=x['root'],plan_id=plan['id'])
        assert again['sudah'];await db.commit()
        assert row.token_version==version+1
        assert not (await db.get(KeanggotaanPerusahaan,x['mid'])).aktif
    after=await fakta(pg)
    assert {k:v for k,v in before.items() if k not in ALLOWED}=={k:v for k,v in after.items() if k not in ALLOWED}


@pytest.mark.parametrize('produk,tujuan',[('padiflow','/masuk'),('teraflow','https://tf.uji/timbangan/masuk')])
async def test_pemulihan_mengikuti_produk_asal_tanpa_mengubah_izin(pg,orang,monkeypatch,produk,tujuan):
    from app.config import settings
    monkeypatch.setattr(settings,'teraflow_web_url','https://tf.uji')
    async with pg() as db:
        (await db.get(KeanggotaanPerusahaan,orang['mid'])).aktif=True;await db.commit()
        a=await bantuan.m.akun(db,orang['cid'],'staf',orang['aid'])
        before=await fakta(pg)
        assert await bantuan.tujuan_masuk(db,a,produk=produk)==tujuan
        assert await fakta(pg)==before

async def test_produk_pilihan_yang_dicabut_tidak_dialihkan_ke_produk_lain(pg,orang):
    from hmu_core import AksesProdukAnggota,ProdukAplikasiPerusahaan
    async with pg() as db:
        (await db.get(KeanggotaanPerusahaan,orang['mid'])).aktif=True
        db.add(AksesProdukAnggota(company_id=orang['cid'],user_id=orang['uid'],produk='teraflow',aktif=False,peran='operator'));await db.commit()
        a=await bantuan.m.akun(db,orang['cid'],'staf',orang['aid'])
        assert await bantuan.tujuan_masuk(db,a,produk='teraflow') is None
        assert await bantuan.tujuan_masuk(db,a,produk='padiflow')=='/masuk'
