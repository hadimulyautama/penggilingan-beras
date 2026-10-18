"""Regresi jeda: kejadian aktual, kondisi, identitas, pengiriman ulang dan konkurensi."""
from datetime import timedelta
from unittest.mock import AsyncMock
import asyncio
import uuid
import pytest
from sqlalchemy import select,func
from app.database import now_local
from app.models import User,MillingProcess,JedaProses,JedaCatatan
from app.penggilingan.gudang1.services import jeda as j
from tests.pg.test_giling_beberapa_silo import silos,_mulai
from tests.pg.test_gudang2_operator_pg import gudang2
pytestmark=pytest.mark.asyncio


async def _giling(pg,silos):
    r=await _mulai(pg,silos,['A','B'])
    async with pg() as db:
        p=await db.get(MillingProcess,r.proc.id);p.waktu_mulai=now_local()-timedelta(days=2);await db.commit()
    return r.proc.kode_proses,r.proc.id


async def _dasar(db,jenis,kode):return (await j.ringkasan_jeda(db,jenis=jenis,kode=kode))['dasar']


async def test_hasil_saat_jeda_tidak_melanjutkan_atau_mengubah_interval(pg,silos,gudang2):
    from app.penggilingan.gudang1.services.milling import log_progress
    from app.penggilingan.gudang2.polishing import mulai_penyosohan,catat_output
    from app.services.berjalan import untuk_gudang1,untuk_operator_gudang2
    kode,pid=await _giling(pg,silos)
    async with pg() as db:
        u=await db.get(User,silos['user'])
        await j.hentikan(db,user=u,jenis='giling',kode=kode,sebab='Listrik padam')
        sebelum=await j.jeda_terbuka(db,'giling',pid);awal=sebelum.mulai
        await log_progress(db,user=u,kode_proses=kode,berat_kumulatif=500)
        sesudah=await j.jeda_terbuka(db,'giling',pid)
        assert sesudah.id==sebelum.id and sesudah.mulai==awal and sesudah.selesai is None
        kartu=next(x for x in (await untuk_gudang1(db)).berjalan if x.kode==kode)
        assert 'hasil_giling' in [p[0] for p in kartu.pilihan]
        assert 'ubah_kondisi_proses' in [p[0] for p in kartu.pilihan]
        p=(await mulai_penyosohan(db,user=gudang2['user'],nama_silos=['B'])).proc
        await j.hentikan(db,user=gudang2['user'],jenis='penyosohan',kode=p.kode_proses,sebab='Listrik padam')
        jeda=await j.jeda_terbuka(db,'penyosohan',p.id);awal=jeda.mulai
        await catat_output(db,user=gudang2['user'],kode=p.kode_proses,jenis='medium',berat_kumulatif=300)
        assert jeda.selesai is None and jeda.mulai==awal
        kartu=next(x for x in (await untuk_operator_gudang2(db)).berjalan if x.kode==p.kode_proses)
        assert 'hasil_penyosohan' in [p[0] for p in kartu.pilihan]


async def test_terlambat_lintas_hari_dan_operator_dengan_riwayat_identitas(pg,silos):
    from app.services.riwayat_jeda import riwayat_jeda
    kode,pid=await _giling(pg,silos)
    t=now_local()-timedelta(days=1,hours=2)
    async with pg() as db:
        u=await db.get(User,silos['user'])
        kedua=User(nama='Pelanjut berbeda',role=u.role,status='aktif');db.add(kedua);await db.commit()
        await j.hentikan(db,user=u,jenis='giling',kode=kode,sebab='Listrik padam',waktu_kejadian=t,alasan_terlambat='HP diisi daya')
        await j.lanjutkan(db,user=kedua,jenis='giling',kode=kode,waktu_kejadian=t+timedelta(hours=3),alasan_terlambat='Baru kembali ke kantor')
        assert await j.tertahan_detik(db,'giling',pid)==10800
        rows=(await db.scalars(select(JedaCatatan).order_by(JedaCatatan.id))).all()
        assert rows[0].waktu_kejadian==t and rows[0].dicatat_pada>t
        assert rows[0].dicatat_oleh==u.id and rows[1].dicatat_oleh==kedua.id
        riwayat=await riwayat_jeda(db,jenis='giling',id_=pid)
        assert any('Dihentikan oleh: '+u.nama==r['petugas'] for r in riwayat['items'])
        assert any('Dilanjutkan oleh: Pelanjut berbeda'==r['petugas'] for r in riwayat['items'])
        assert rows[0].alasan_terlambat=='HP diisi daya'


async def test_perubahan_kondisi_tidak_menciptakan_waktu_berjalan(pg,silos):
    kode,pid=await _giling(pg,silos);t=now_local()-timedelta(hours=4)
    async with pg() as db:
        u=await db.get(User,silos['user'])
        await j.hentikan(db,user=u,jenis='giling',kode=kode,sebab='Listrik padam',waktu_kejadian=t,alasan_terlambat='Belum sempat')
        await j.perbarui_kondisi(db,user=u,jenis='giling',kode=kode,sebab='Mesin giling rusak',catatan='Listrik pulih, motor macet',waktu_kejadian=t+timedelta(hours=1),alasan_terlambat='Sedang perbaikan')
        await j.lanjutkan(db,user=u,jenis='giling',kode=kode,waktu_kejadian=t+timedelta(hours=3),alasan_terlambat='Sedang bekerja')
        assert await db.scalar(select(func.count()).select_from(JedaProses))==1
        assert await j.tertahan_detik(db,'giling',pid)==10800
        events=(await db.scalars(select(JedaCatatan).order_by(JedaCatatan.id))).all()
        assert [e.sebab for e in events][:2]==['Listrik padam','Mesin giling rusak']
        rekap={r.sebab:r.detik for r in await j.rekap_berhenti(db,sejak=t-timedelta(minutes=1))}
        assert rekap=={'Listrik padam':3600,'Mesin giling rusak':7200}


async def test_urutan_negatif_tumpang_tindih_dan_batas_proses_ditolak(pg,silos):
    kode,pid=await _giling(pg,silos);t=now_local()-timedelta(hours=3)
    async with pg() as db:
        u=await db.get(User,silos['user'])
        with pytest.raises(j.JedaError,match='sebelum proses'):
            await j.hentikan(db,user=u,jenis='giling',kode=kode,sebab='Listrik padam',waktu_kejadian=t-timedelta(days=3),alasan_terlambat='Uji')
        with pytest.raises(j.JedaError,match='masa depan'):
            await j.hentikan(db,user=u,jenis='giling',kode=kode,sebab='Listrik padam',waktu_kejadian=now_local()+timedelta(days=1),alasan_terlambat='Uji')
        with pytest.raises(j.JedaError,match='alasan'):
            await j.hentikan(db,user=u,jenis='giling',kode=kode,sebab='Listrik padam',waktu_kejadian=t)
        await j.hentikan(db,user=u,jenis='giling',kode=kode,sebab='Listrik padam',waktu_kejadian=t,alasan_terlambat='Uji')
        with pytest.raises(j.JedaError,match='mendahului'):
            await j.lanjutkan(db,user=u,jenis='giling',kode=kode,waktu_kejadian=t-timedelta(seconds=1),alasan_terlambat='Uji')
        await j.lanjutkan(db,user=u,jenis='giling',kode=kode,waktu_kejadian=t+timedelta(hours=1),alasan_terlambat='Uji')
        with pytest.raises(j.JedaError,match='tumpang tindih'):
            await j.hentikan(db,user=u,jenis='giling',kode=kode,sebab='Listrik padam',waktu_kejadian=t+timedelta(minutes=1),alasan_terlambat='Uji')


async def test_sebab_per_jenis_dijaga_server_dan_lainnya(pg,silos,monkeypatch):
    from app.web import api
    kode,pid=await _giling(pg,silos)
    monkeypatch.setattr(api,'_is_g1_operator',AsyncMock(return_value=True))
    async with pg() as db:
        u=await db.get(User,silos['user'])
        opsi=await api.pilihan_sebab_jeda(induk='giling:'+kode,user=u)
        assert 'Lainnya' in {r['value'] for r in opsi} and 'Mesin dryer rusak' not in {r['value'] for r in opsi}
        with pytest.raises(j.JedaError,match='jenis proses'):
            await j.hentikan(db,user=u,jenis='giling',kode=kode,sebab='Mesin dryer rusak')
        await j.hentikan(db,user=u,jenis='giling',kode=kode,sebab='Lainnya',sebab_lain='Sabuk lepas')
        assert (await j.jeda_terbuka(db,'giling',pid)).sebab=='Sabuk lepas'


async def test_dua_operator_form_basi_dan_kirim_ulang(pg,silos):
    kode,pid=await _giling(pg,silos)
    async with pg() as db:
        u=await db.get(User,silos['user']);u2=User(nama='Operator dua',role=u.role,status='aktif');db.add(u2);await db.commit();uid2=u2.id
        dasar=await _dasar(db,'giling',kode)
    async def kirim(uid,kunci):
        async with pg() as db:
            try:
                r=await j.hentikan(db,user=await db.get(User,uid),jenis='giling',kode=kode,sebab='Listrik padam',dasar=dasar,kunci_kiriman=kunci)
                return r
            except j.JedaError as e:
                await db.rollback();return str(e)
    kunci=str(uuid.uuid4())
    hasil=await asyncio.gather(kirim(silos['user'],kunci),kirim(uid2,str(uuid.uuid4())))
    assert sum(isinstance(x,j.JedaResult) for x in hasil)==1
    berhasil=next(i for i,r in enumerate(hasil) if isinstance(r,j.JedaResult))
    uid,k= (silos['user'],kunci) if berhasil==0 else (uid2,None)
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(JedaProses))==1
        event=await db.scalar(select(JedaCatatan));k=event.kunci_kiriman;uid=event.dicatat_oleh
    ulang=await kirim(uid,k)
    assert isinstance(ulang,j.JedaResult)
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(JedaCatatan))==1
        with pytest.raises(j.JedaError,match='sudah dipakai'):
            await j.hentikan(db,user=await db.get(User,uid),jenis='giling',kode=kode,sebab='Jam kerja habis',dasar=dasar,kunci_kiriman=k)


async def test_batal_kondisi_lanjut_dan_hentikan_tetap_berjejak(pg,silos):
    kode,pid=await _giling(pg,silos)
    async with pg() as db:
        u=await db.get(User,silos['user'])
        await j.hentikan(db,user=u,jenis='giling',kode=kode,sebab='Listrik padam')
        awal=await db.scalar(select(JedaCatatan))
        await j.perbarui_kondisi(db,user=u,jenis='giling',kode=kode,sebab='Jam kerja habis')
        kondisi=await db.scalar(select(JedaCatatan).order_by(JedaCatatan.id.desc()))
        await j.batalkan_kejadian(db,event_id=kondisi.id,user=u)
        assert (await j.jeda_terbuka(db,'giling',pid)).sebab=='Listrik padam'
        await j.lanjutkan(db,user=u,jenis='giling',kode=kode)
        lanjut=await db.scalar(select(JedaCatatan).order_by(JedaCatatan.id.desc()))
        await j.batalkan_kejadian(db,event_id=lanjut.id,user=u)
        assert await j.jeda_terbuka(db,'giling',pid)
        await j.batalkan_kejadian(db,event_id=awal.id,user=u)
        assert await j.jeda_terbuka(db,'giling',pid) is None
        assert await j.tertahan_detik(db,'giling',pid)==0
        assert await db.scalar(select(func.count()).select_from(JedaCatatan))==3


async def test_lanjut_bersamaan_dan_kondisi_basi_tidak_menambah_interval(pg,silos):
    kode,pid=await _giling(pg,silos)
    async with pg() as db:
        u=await db.get(User,silos['user'])
        await j.hentikan(db,user=u,jenis='giling',kode=kode,sebab='Listrik padam')
        dasar=await _dasar(db,'giling',kode)
    async def lanjut():
        async with pg() as db:
            try:
                return await j.lanjutkan(db,user=await db.get(User,silos['user']),jenis='giling',kode=kode,
                    dasar=dasar,kunci_kiriman=str(uuid.uuid4()))
            except j.JedaError as e:
                await db.rollback();return str(e)
    hasil=await asyncio.gather(lanjut(),lanjut())
    assert sum(isinstance(r,j.JedaResult) for r in hasil)==1
    async with pg() as db:
        with pytest.raises(j.JedaError,match='berubah'):
            await j.perbarui_kondisi(db,user=await db.get(User,silos['user']),jenis='giling',kode=kode,
                sebab='Mesin giling rusak',dasar=dasar,kunci_kiriman=str(uuid.uuid4()))
        assert await db.scalar(select(func.count()).select_from(JedaProses))==1
        assert await db.scalar(select(func.count()).select_from(JedaCatatan))==2


async def test_selesai_giling_menutup_jeda_tanpa_mengaku_lanjut_dan_batal_memulihkan(pg,silos):
    from app.penggilingan.gudang1.services.milling import finish_milling
    from app.services.undo import _undo_finish_milling
    from app.services.riwayat_jeda import riwayat_jeda
    kode,pid=await _giling(pg,silos)
    async with pg() as db:
        u=await db.get(User,silos['user'])
        await j.hentikan(db,user=u,jenis='giling',kode=kode,sebab='Listrik padam')
        awal=(await j.jeda_terbuka(db,'giling',pid)).mulai
        await finish_milling(db,user=u,kode_proses=kode,berat_akhir=500)
        assert await j.jeda_terbuka(db,'giling',pid) is None
        riwayat=await riwayat_jeda(db,jenis='giling',id_=pid)
        assert any(r['aksi']=='Proses selesai; mesin tidak dilanjutkan' for r in riwayat['items'])
        assert not any(r['aksi']=='Mesin dilanjutkan' for r in riwayat['items'])
        await _undo_finish_milling(db,pid);await db.commit()
        aktif=await j.jeda_terbuka(db,'giling',pid)
        assert aktif and aktif.mulai==awal
        events=(await db.scalars(select(JedaCatatan).order_by(JedaCatatan.id))).all()
        assert events[-1].aksi=='akhir_proses' and events[-1].dibatalkan_pada


async def test_migrasi_identitas_lama_hanya_dari_audit_tunggal_tanpa_tebakan(pg,silos):
    import importlib.util
    from pathlib import Path
    from types import SimpleNamespace
    from sqlalchemy import text
    from app.services.activity_log import log_activity
    kode,pid=await _giling(pg,silos)
    t=now_local()-timedelta(hours=5)
    async with pg() as db:
        uid=silos['user']
        # Dua penutupan berdekatan cocok ke SATU audit: identitasnya ambigu.
        rows=[JedaProses(jenis='giling',milling_process_id=pid,sebab='Listrik padam',
            mulai=t+timedelta(minutes=i*10),selesai=t+timedelta(minutes=30,seconds=s),dicatat_oleh=uid)
            for i,s in enumerate([0,1])]
        rows.append(JedaProses(jenis='giling',milling_process_id=pid,sebab='Listrik padam',
            mulai=t+timedelta(hours=1),selesai=t+timedelta(hours=2),dicatat_oleh=uid))
        db.add_all(rows);await db.flush()
        for akhir in [rows[0].selesai,rows[2].selesai]:
            await log_activity(db,table_name='jeda_proses',record_id=pid,action='UPDATE',
                changed_by=uid,field_name='selesai',new_value=kode+' lanjut — Listrik padam')
            from app.models import ActivityLog
            log=await db.scalar(select(ActivityLog).order_by(ActivityLog.id.desc()).limit(1))
            log.waktu_perubahan=akhir
            await db.flush()
        spec=importlib.util.spec_from_file_location('migrasi_jeda',Path(__file__).parents[2]/'migrations/versions/0101_jeda_kejadian.py')
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        sql=[]
        mod.op=SimpleNamespace(add_column=lambda *a,**k:None,create_table=lambda *a,**k:None,
            create_index=lambda *a,**k:None,execute=sql.append)
        mod.upgrade()
        for perintah in sql:await db.execute(text(perintah))
        events=(await db.scalars(select(JedaCatatan).where(JedaCatatan.aksi!='hentikan')
            .order_by(JedaCatatan.jeda_id))).all()
        assert [e.aksi for e in events]==['penutupan_lama','penutupan_lama','lanjutkan']
        assert [e.dicatat_oleh for e in events]==[None,None,uid]
