"""Penyajian proses sosoh; mutasi tetap melalui layanan domain yang sudah ada."""
from app.services.fasilitas import label_fasilitas
from app.web.api import _is_jenis_operator
import hashlib
import hmac
import json
from pydantic import BaseModel, ConfigDict, FiniteFloat
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, or_
from app.database import SessionLocal, now_local
from app.models import (PolishingProcess, PolishingSiloUsage, PolishingOutputLog,
                        Silo, User, ActivityLog, JedaProses, JedaCatatan)
from app.penggilingan.gudang2 import polishing as p
from app.penggilingan.gudang1.services import jeda
from app.web import form_selesai_penyosohan as selesai
from app.web import form_tambah_silo_sosoh as mix
from app.web.security import _kunci
from app.web.deps import pengguna_aksi
from app.web.tampilan import render_laci
from app.web.api import _is_g2_operator
from app.services.stok import nama_produk

router=APIRouter()

async def izin(user,kode=None):
    if not await _is_jenis_operator(user,'penyosohan'):
        raise HTTPException(403,'Penyosohan mengikuti akses Gudang 2 yang sedang berlaku.')
    if kode:
     from app.services.cakupan_fasilitas import batas
     async with SessionLocal() as db:
      if not await db.scalar(select(PolishingProcess.id).where(PolishingProcess.kode_proses==kode,batas(user,PolishingProcess))):raise HTTPException(403,'Proses berada di luar gudang kerja Anda.')


def _raw(row):
    return [getattr(row,c.name) for c in row.__table__.columns]


def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()


async def sidik(db,proc):
    usages=list((await db.scalars(select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id==proc.id).order_by(PolishingSiloUsage.id).execution_options(populate_existing=True))).all())
    logs=list((await db.scalars(select(PolishingOutputLog).where(PolishingOutputLog.polishing_process_id==proc.id).order_by(PolishingOutputLog.id))).all())
    pauses=list((await db.scalars(select(JedaProses).where(JedaProses.polishing_process_id==proc.id).order_by(JedaProses.id).execution_options(populate_existing=True))).all())
    events=list((await db.scalars(select(JedaCatatan).where(JedaCatatan.jeda_id.in_([r.id for r in pauses] or [-1])).order_by(JedaCatatan.id))).all())
    # Bobot sumber dinamis dibaca dengan fungsi lama, tidak disinkronkan/ditulis.
    from app.penggilingan.gudang2.karung import bobot_pemakaian
    bobot=bobot_pemakaian(usages)
    return _hash([_raw(proc),[_raw(u) for u in usages],[_raw(r) for r in logs],
        [_raw(r) for r in pauses],[_raw(r) for r in events],bobot.teks(),bobot.pasti,
        [[_raw(m),_raw(m.batch)] for u in usages for m in u.pemindahan_karung if m.batch is not None]])


async def baca(db,kode):
    proc=await db.scalar(select(PolishingProcess).where(PolishingProcess.kode_proses==kode).execution_options(populate_existing=True))
    if not proc or proc.status not in ('proses','selesai'):raise HTTPException(404,'Proses penyosohan tidak ditemukan.')
    # Ambil acuan sebelum merangkai isi; perubahan selama pembacaan tidak
    # boleh menghasilkan token baru untuk angka tampilan yang lebih lama.
    dasar=await sidik(db,proc)
    data=await selesai.ringkasan(db,kode_proses=kode)
    logs=list((await db.scalars(select(PolishingOutputLog).where(PolishingOutputLog.polishing_process_id==proc.id).order_by(PolishingOutputLog.id))).all())
    pauses=list((await db.scalars(select(JedaProses).where(JedaProses.polishing_process_id==proc.id).order_by(JedaProses.id))).all())
    events=list((await db.scalars(select(JedaCatatan).where(JedaCatatan.jeda_id.in_([r.id for r in pauses] or [-1])).order_by(JedaCatatan.id))).all())
    people={r.id:r.nama for r in (await db.scalars(select(User).where(User.id.in_(
        {proc.created_by}|{r.input_by for r in logs})))).all()}
    akhir=proc.waktu_selesai if proc.status=='selesai' else now_local()
    from app.services.berjalan import lama_kata
    durasi=max(0,(akhir-proc.waktu_mulai).total_seconds()) if akhir and proc.waktu_mulai else None
    tertahan=await jeda.tertahan_detik(db,'penyosohan',proc.id,sampai=akhir) if akhir else None
    aktif=await jeda.jeda_terbuka(db,'penyosohan',proc.id)
    penutup=await db.scalar(select(ActivityLog).where(ActivityLog.table_name=='polishing_process',ActivityLog.record_id==proc.id,ActivityLog.aksi=='akhiri_penyosohan',ActivityLog.dibatalkan_pada.is_(None)).order_by(ActivityLog.id.desc()).limit(1)) if proc.status=='selesai' else None
    closer=await db.get(User,penutup.changed_by) if penutup and penutup.changed_by else None
    data['proses_id']=proc.id
    data.update(dasar=dasar,aktif=proc.status=='proses',gudang=await label_fasilitas(db,proc),
        waktu=dict(mulai=proc.waktu_mulai.isoformat() if proc.waktu_mulai else None,
            selesai=proc.waktu_selesai.isoformat() if proc.waktu_selesai else None,
            durasi=lama_kata(durasi) if durasi is not None else 'Belum tersedia',
            jeda='Belum tersedia' if tertahan is None else lama_kata(tertahan) if tertahan else '0 menit',
            aktif=lama_kata(max(0,durasi-tertahan)) if durasi is not None and tertahan is not None else 'Belum tersedia'),
        jeda=dict(sebab=aktif.sebab,mulai=aktif.mulai.isoformat()) if aktif else None,
        petugas_selesai=closer.nama if closer else None,
        riwayat_hasil=[dict(id=r.id,jenis=r.jenis,nama=nama_produk(r.jenis),kg=float(r.berat_kg),spek=r.spek,waktu=r.waktu_update.isoformat(),petugas=people.get(r.input_by,'Tidak tercatat')) for r in logs],
        riwayat_jeda=[dict(id=r.id,mulai=r.mulai.isoformat(),selesai=r.selesai.isoformat() if r.selesai else None,sebab=r.sebab,dibatalkan=bool(r.dibatalkan_pada)) for r in pauses],
        kiriman_jeda=[r.kunci_kiriman for r in events if r.kunci_kiriman],siap=False,penghalang=None)
    from app.penggilingan.gudang2.karung import bobot_pemakaian
    usages=list((await db.scalars(select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id==proc.id))).all())
    data['sumber_final']=bobot_pemakaian(usages).pasti
    for h in data['hasil']:h['tercatat']=h['kg'] is not None
    from app.services.riwayat_jeda import riwayat_jeda
    data['jejak_jeda']=await riwayat_jeda(db,jenis='penyosohan',id_=proc.id,semua=True)
    data['komposisi']=[]
    data['kelompok_sumber']=[]
    from app.services import berjalan
    if data['aktif']:
        cards=await berjalan._kartu_penyosohan_g2(db,None,kode_proses=kode,lengkap=True)
        if cards:
            data['komposisi']=[dict(judul=title,baris=[list(x) for x in rows]) for title,rows in cards[0].anak_grup if title!='Hasil sosoh keluar']
            data['fakta']=cards[0].fakta
            # Penyajian memakai pengelompokan lama; urutan diperiksa menurut
            # ID siklus agar pemakaian ulang silo tidak tergabung karena nama.
            from app.services.proses_aktif import kelompok_bahan_silo
            ordered=sorted(usages,key=lambda u:u.id)
            names=dict((await db.execute(select(Silo.id,Silo.nama_silo).where(Silo.id.in_([u.silo_id for u in ordered])))).all())
            for title,rows in cards[0].anak_grup:
                if title=='Bahan baku masuk per silo':
                    groups=kelompok_bahan_silo(rows,[(u,names[u.silo_id]) for u in ordered])
                    data['kelompok_sumber']=[dict(g,id=u.id) for g,u in zip(groups,ordered)]
            # Neraca sementara tetap dari kartu lama; tidak disamakan dengan
            # bahan terpakai final sebelum semua sisa diperiksa.
            n=cards[0].neraca
            if n and all(x['awal'] is not None and x['tambahan'] is not None for x in data['sumber']) and not any(x['dinamis'] for x in data['sumber']):
                data['sementara']=dict(bahan=n.bahan_kg,selisih=n.susut.kg,rendemen=cards[0].rendemen_sementara if data['ada_hasil'] else None,timpang=n.timpang)
    else:
        cards=(await p.riwayat_sosoh(db,batas=1,process_id=proc.id))[0]
        if cards:
            data['komposisi']=[dict(judul=u.nama,baris=[list(x) for x in u.asal]) for u in cards[0].silo]
    usage_ids=[x['id'] for x in data['sumber']]
    query=select(ActivityLog).where(or_(
        (ActivityLog.table_name=='polishing_process')&(ActivityLog.record_id==proc.id),
        (ActivityLog.table_name=='polishing_silo_usage')&(ActivityLog.record_id.in_(usage_ids or [-1])),
        (ActivityLog.table_name=='polishing_output_logs')&(ActivityLog.record_id.in_([r.id for r in logs] or [-1]))
    )).order_by(ActivityLog.id)
    audits=list((await db.scalars(query)).all())
    users={r.id:r.nama for r in (await db.scalars(select(User).where(User.id.in_({r.changed_by for r in audits} or {-1})))).all()}
    data['jejak']=[dict(id=a.id,aksi=a.aksi or a.action,medan=a.field_name,sebelum=a.old_value,sesudah=a.new_value,
        alasan=a.alasan_perubahan,petugas=users.get(a.changed_by,'Tidak tercatat'),waktu=a.waktu_perubahan.isoformat() if a.waktu_perubahan else None,
        dibatalkan=bool(a.dibatalkan_pada)) for a in audits]
    if proc.status=='proses':
        from app.services.penyelesaian_proses import ringkasan_selesai
        try:data['pemeriksaan_selesai']=await ringkasan_selesai(db,jenis='sosoh',kode=kode);data['siap']=True
        except ValueError as e:data['penghalang']=str(e)
    b = bobot_pemakaian(usages) if data['sisa_lengkap'] else None
    if b and b.diketahui and b.tak_diketahui == 0:
        data['basis_neraca_kg'] = b.angka()
    else:
        data['basis_neraca_kg'] = data.get('sementara',{}).get('bahan') if not data['sisa_lengkap'] else None
    data['neraca_lembar'] = neraca_lembar(data)
    return data


def neraca_lembar(data, hasil=None):
    """Penyajian persen memakai neraca domain; nilai kosong bukan nol."""
    basis = data.get('basis_neraca_kg')
    angka = {h['jenis']: h['kg'] for h in data['hasil'] if h['kg'] is not None}
    if hasil is not None:
        angka.update({h.jenis: h.total for h in hasil})
    tersedia = basis is not None and basis > 0
    n = p.neraca_sosoh(basis if tersedia else 0, angka)
    rows = []
    for h in data['hasil']:
        nilai = angka.get(h['jenis'])
        satu = p.neraca_sosoh(basis if tersedia else 0, {h['jenis']: nilai}) if nilai is not None else None
        bagian = (satu.beras if h['beras'] else next((x for x in satu.samping if x.jenis == h['jenis']), None)) if satu else None
        rows.append(dict(jenis=h['jenis'],kg=nilai,persen=bagian.persen if bagian and tersedia else None))
    return dict(bahan_kg=basis,sementara=data['aktif'] or not data['sumber_final'],
        dasar=data['dasar'],hasil=rows,total_kg=n.keluar_kg if angka else None,
        total_persen=(n.beras.persen + sum(x.persen for x in n.samping)) if tersedia and angka else None,
        susut_kg=n.susut.kg if tersedia and angka else None,
        susut_persen=n.susut.persen if tersedia and angka else None)


async def halaman(kode,request,akun):
    await izin(akun.user,kode)
    async with SessionLocal() as db:
        data=await baca(db,kode)
        from app.services.qc_sosoh import data_proses
        qc_sosoh=await data_proses(db,await db.get(PolishingProcess,data['id']))
        from app.services.riwayat_jeda import riwayat_jeda
        jejak=await riwayat_jeda(db,jenis='penyosohan',id_=data['id'],params=request.query_params)
    from hmu_identitas import peran as P
    lembar_operator = P.operator_saja(akun.user.role)
    def halaman_riwayat(parameter,nomor):return str(request.url.include_query_params(**{parameter:nomor}))
    from app.web.layar_pekerjaan import konteks_aman
    return await render_laci(request,'sosoh_ringkas.html',awal=data,qc_sosoh=qc_sosoh,qc_kode=kode,
        kembali=konteks_aman(request.query_params.get('kembali_kerja')) or '/pekerjaan?tab=berjalan',breadcrumb_detail=kode,
        jejak_jeda=jejak,boleh=True,lembar_operator=lembar_operator,halaman_proses=halaman_riwayat,layar='pekerjaan',
        buka=request.query_params.get('buka',''),nilai=request.query_params.get('nilai',''))


@router.get('/api/actions/sosoh-ringkas/{kode}')
async def papan(kode:str,user:User=Depends(pengguna_aksi)):
    await izin(user,kode)
    async with SessionLocal() as db:return JSONResponse(await baca(db,kode),headers={'Cache-Control':'no-store'})


class Hasil(BaseModel):
    model_config=ConfigDict(extra='forbid')
    jenis:str
    total:FiniteFloat

class Permintaan(BaseModel):
    model_config=ConfigDict(extra='forbid')
    dasar:str
    hasil:list[Hasil]=[]
    silos:list[str]=[]
    pemakaian_id:int|None=None
    sisa:FiniteFloat|None=None
    pemeriksaan:str=''
    konfirmasi:bool=False

async def kunci(db,kode,req):
    proc=await db.scalar(select(PolishingProcess).where(PolishingProcess.kode_proses==kode).with_for_update().execution_options(populate_existing=True))
    if not proc:raise HTTPException(404,'Proses tidak ditemukan.')
    usages=list((await db.scalars(select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id==proc.id).order_by(PolishingSiloUsage.id))).all())
    ids={u.silo_id for u in usages}
    for nama in req.silos:
        silo=await p.get_g2_silo(db,nama.upper())
        if not silo:raise HTTPException(400,'Silo yang dipilih tidak ditemukan.')
        ids.add(silo.id)
    for sid in sorted(ids):await p.kunci_silo(db,sid)
    if not req.dasar or req.dasar!=await sidik(db,proc):
        raise HTTPException(409,'Data proses berubah sejak dibaca. Isian dipertahankan; baca data terbaru dan periksa ulang.')
    if proc.status!='proses':raise HTTPException(409,'Proses sudah selesai. Gunakan alur koreksi atau pembatalan yang berlaku.')
    return proc


def cap(user,action,plan):
    raw=json.dumps([user.id,str(user.role),action,plan],sort_keys=True,default=str).encode()
    return hmac.new(_kunci(),raw,hashlib.sha256).hexdigest()

async def rencana(db,kode,req,user,action):
    proc=await kunci(db,kode,req)
    base=dict(kode=kode,dasar=req.dasar,aksi=action)
    if action=='hasil':
        if req.silos or req.pemakaian_id is not None:raise HTTPException(400,'Konteks hasil tidak sesuai.')
        if len({x.jenis for x in req.hasil})!=len(req.hasil):raise HTTPException(400,'Jenis hasil tidak boleh berulang.')
        rows=[]
        for h in req.hasil:
            # Nol yang belum pernah diisi dan total sama tidak menjadi INSERT.
            if h.jenis not in await p.jenis_hasil(db):raise HTTPException(400,'Jenis hasil tidak dikenali.')
            old=await p._total_output(db,proc.id,h.jenis)
            if h.total==old:continue
            d=await p.rencana_total_output(db,proc.id,h.jenis,h.total)
            if d['tambahan']!=0:rows.append(dict(d,nama=nama_produk(h.jenis)))
        if not rows:raise HTTPException(400,'Tidak ada perubahan hasil yang perlu dicatat.')
        base['hasil']=rows
    elif action=='mix':
        if not req.silos or len(req.silos)!=len(set(s.upper() for s in req.silos)):raise HTTPException(400,'Pilih silo yang akan ditambahkan tanpa pengulangan.')
        base['mix']=await mix.ringkasan(db,kode=kode,pilihan=req.silos)
    elif action=='bebaskan':
        usage=await db.get(PolishingSiloUsage,req.pemakaian_id) if req.pemakaian_id else None
        if not usage or usage.polishing_process_id!=proc.id or usage.berat_akhir_kg is not None:
            raise HTTPException(409,'Siklus silo tidak lagi terbuka untuk proses ini.')
        if req.sisa is None:raise HTTPException(400,'Isi sisa fisik di silo.')
        silo=await db.get(Silo,usage.silo_id)
        from app.services.penyelesaian_proses import ringkasan_bebaskan
        base['bebaskan']=await ringkasan_bebaskan(db,jenis='sosoh',kode=kode,silo=silo.nama_silo,sisa=req.sisa)
        from app.web.form_bebaskan_silo_sosoh import ringkasan
        base['rincian']=await ringkasan(db,kode_proses=kode,silo=silo.nama_silo,sisa=req.sisa)
        base.update(pemakaian_id=usage.id,silo=silo.nama_silo,sisa=req.sisa)
    elif action=='selesai':
        from app.services.penyelesaian_proses import ringkasan_selesai
        base['selesai']=await ringkasan_selesai(db,jenis='sosoh',kode=kode)
        base['rincian']=await selesai.ringkasan(db,kode_proses=kode)
    else:raise HTTPException(404,'Tindakan tidak dikenali.')
    return base


@router.post('/api/actions/sosoh-ringkas/{kode}/neraca/pratinjau')
async def pratinjau_neraca(kode:str,req:Permintaan,user:User=Depends(pengguna_aksi)):
    await izin(user,kode)
    if req.silos or req.pemakaian_id is not None or req.sisa is not None:
        raise HTTPException(400,'Konteks pratinjau neraca tidak sesuai.')
    if len({h.jenis for h in req.hasil}) != len(req.hasil) or any(h.jenis not in p._ALL_JENIS or h.total < 0 for h in req.hasil):
        raise HTTPException(400,'Jenis hasil atau total pratinjau tidak sah.')
    async with SessionLocal() as db:
        data = await baca(db,kode)
        if data['dasar'] != req.dasar:
            raise HTTPException(409,'Data proses berubah. Baca status terbaru sebelum memeriksa kembali.')
        return JSONResponse(neraca_lembar(data,req.hasil),headers={'Cache-Control':'no-store'})


@router.post('/api/actions/sosoh-ringkas/{kode}/{action}/{langkah}')
async def tindakan(kode:str,action:str,langkah:str,req:Permintaan,user:User=Depends(pengguna_aksi)):
    await izin(user,kode)
    if langkah not in ('periksa','simpan'):raise HTTPException(404,'Langkah tidak dikenali.')
    async with SessionLocal() as db:
        try:
            plan=await rencana(db,kode,req,user,action)
            token=cap(user,action,plan)
            if langkah=='periksa':return dict(rencana=plan,pemeriksaan=token)
            if not req.pemeriksaan or not hmac.compare_digest(req.pemeriksaan,token):
                raise HTTPException(409,'Pemeriksaan berubah atau belum dilakukan. Baca ringkasan terbaru lalu konfirmasi ulang.')
            if not req.konfirmasi:raise HTTPException(400,'Konfirmasikan hasil pemeriksaan sebelum menyimpan.')
            u=await db.get(User,user.id)
            if action=='hasil':
                for h in plan['hasil']:await p.catat_output(db,user=u,kode=kode,jenis=h['jenis'],berat_kumulatif=h['total'],simpan=False)
                await db.commit()
            elif action=='mix':await p.tambah_silo_penyosohan(db,user=u,kode=kode,nama_silos=req.silos)
            elif action=='bebaskan':await p.selesai_penyosohan(db,user=u,kode=kode,nama_silo=plan['silo'],sisa_kg=req.sisa,dasar=plan['bebaskan']['dasar'])
            else:await p.akhiri_penyosohan(db,user=u,kode=kode,dasar=plan['selesai']['dasar'])
            return dict(ok=True,pesan='Perubahan tercatat sesuai layanan penyosohan.',aksi=action)
        except (p.Gudang2Error,ValueError) as e:
            await db.rollback();raise HTTPException(409,str(e))
        except Exception:
            await db.rollback();raise
