"""Identitas fasilitas dan penjaga penggunaan; semua perubahan mengikuti transaksi pemanggil."""
import re
from sqlalchemy import select, or_
from app.models import (Warehouse, Dryer, DryingLot, MillingProcess, PolishingProcess,
                        JenisProsesProduksi, LiniProduksi, AuditFasilitas)

PENJALAN = {'pengeringan': DryingLot, 'penggilingan': MillingProcess, 'penyosohan': PolishingProcess}

class FasilitasError(ValueError):
    pass


class LiniSedangDipakai(FasilitasError):
    """Kondisi operasional yang sah, bukan kegagalan membaca daftar bahan."""
    def __init__(self, lini, proses):
        kode = ', '.join(p['kode'] for p in proses)
        pesan = f'{lini.nama} masih digunakan proses yang belum selesai'
        if kode:
            pesan += f': {kode}'
        pesan += '. Selesaikan proses yang berjalan sebelum memulai proses baru pada alat ini.'
        super().__init__(pesan)
        self.detail = dict(kode='alat_sedang_dipakai', pesan=pesan,
                          alat=dict(id=lini.id, nama=lini.nama), proses=proses)


async def proses_pemakai_lini(db, lini, user):
    """Identitas proses penghalang dengan cakupan baca aktor yang sama.

    Tidak menulis atau mengira-ngira alokasi bahan. Proses lama tanpa ID line
    tetap mengikuti penjaga konservatif di sedang_dipakai, pada gudang yang
    sama; identitas tersebut membantu operator membuka proses yang dimaksud.
    """
    from app.services.cakupan_fasilitas import batas, lokasi
    jenis = await db.get(JenisProsesProduksi, lini.jenis_proses_id)
    hasil = []
    for kode_jenis, model in PENJALAN.items():
        cocok = model.lini_produksi_id == lini.id
        if kode_jenis == jenis.kode:
            if model is DryingLot:
                cocok = or_(cocok, (model.dryer_id == lini.dryer_id) &
                            model.waktu_selesai_pendinginan.is_(None) & (model.status != 'dibatalkan'))
            else:
                cocok = or_(cocok, model.lini_produksi_id.is_(None) &
                            (lokasi(model) == lini.warehouse_id))
        aktif = model.status == 'proses'
        if model is DryingLot and kode_jenis == jenis.kode:
            aktif = or_(aktif, (model.dryer_id == lini.dryer_id) &
                        model.waktu_selesai_pendinginan.is_(None) & (model.status != 'dibatalkan'))
        for p in await db.scalars(select(model).where(cocok, aktif, batas(user, model)).order_by(model.id)):
            kode = p.kode_lot if model is DryingLot else p.kode_proses
            fase = ('pendinginan' if p.status == 'selesai' else 'pengeringan') if model is DryingLot else 'giling' if model is MillingProcess else 'sosoh'
            hasil.append(dict(kode=kode, href=f'/proses-aktif/{fase}/{kode}'))
    return hasil

async def boleh_kelola(db,user):
    from hmu_identitas import peran as P
    from hmu_identitas.masuk import ada_superadmin_aktif
    return P.super_saja(user.role) or (P.normal(user.role)==P.ADMIN and not await ada_superadmin_aktif(db))

def snapshot(row):
    return {c: getattr(row,c) for c in ('id','kode','nama','aktif','versi') +
            (('warehouse_id','jenis_proses_id','dryer_id') if isinstance(row,LiniProduksi) else ())}

def izin_gudang(user, warehouse_id):
    from hmu_identitas import peran as P
    role = P.normal(user.role)
    if P.admin_keatas(role):
        return True
    return role == P.OPERATOR and warehouse_id is not None and user.default_warehouse_id == warehouse_id

async def sedang_dipakai(db, lini, *, termasuk_bahan=False):
    for model in PENJALAN.values():
        q = select(model.id).where(model.lini_produksi_id == lini.id, model.status == 'proses')
        if (await db.execute(q.limit(1))).first():
            return True
    # Lama belum mempunyai ID line. Jangan mengarang atribusi per run.
    jenis = await db.get(JenisProsesProduksi, lini.jenis_proses_id)
    model = PENJALAN.get(jenis.kode)
    if model is DryingLot:
        from app.penggilingan.gudang1.services.drying import isi_dryer
        if termasuk_bahan and await isi_dryer(db,lini.dryer_id) is not None:return True
        return bool((await db.execute(select(model.id).where(model.dryer_id == lini.dryer_id,
            model.waktu_selesai_pendinginan.is_(None), model.status != 'dibatalkan').limit(1))).first())
    if model:
        # Perlindungan konservatif terhadap run lama yang belum ditautkan.
        from app.services.cakupan_fasilitas import lokasi
        return bool((await db.execute(select(model.id).where(model.lini_produksi_id.is_(None),
            lokasi(model)==lini.warehouse_id,model.status == 'proses').limit(1))).first())
    return False

async def pilih_lini(db, *, user, kode_jenis, lini_id=None, warehouse_id=None, dryer_id=None):
    jenis = await db.scalar(select(JenisProsesProduksi).where(JenisProsesProduksi.kode==kode_jenis).with_for_update())
    if not jenis or not jenis.aktif: raise FasilitasError('Jenis proses tidak tersedia.')
    q = select(LiniProduksi).join(JenisProsesProduksi).join(Warehouse).where(
        JenisProsesProduksi.kode == kode_jenis, JenisProsesProduksi.aktif.is_(True),
        LiniProduksi.aktif.is_(True), Warehouse.aktif.is_(True))
    if lini_id is not None: q = q.where(LiniProduksi.id == lini_id)
    if warehouse_id is not None: q = q.where(LiniProduksi.warehouse_id == warehouse_id)
    if dryer_id is not None: q = q.where(LiniProduksi.dryer_id == dryer_id)
    if not izin_gudang(user, None): q = q.where(LiniProduksi.warehouse_id == user.default_warehouse_id)
    rows = list((await db.execute(q.order_by(LiniProduksi.id).with_for_update(of=LiniProduksi))).scalars())
    if not rows: raise FasilitasError('Line/alat tidak tersedia atau di luar gudang kerja Anda.')
    if len(rows) != 1: raise FasilitasError('Pilih line/alat yang akan digunakan.')
    row = rows[0]
    if await sedang_dipakai(db,row):
        raise LiniSedangDipakai(row, await proses_pemakai_lini(db, row, user))
    return row

async def simpan_jenis(db, *, user, nama, kode, aktif=True, id=None, versi=None):
    from hmu_identitas import peran as P
    if not await boleh_kelola(db,user): raise PermissionError('Tidak berhak mengatur fasilitas.')
    nama, kode = nama.strip(), kode.strip().lower()
    if not 2 <= len(nama) <= 100 or not re.fullmatch(r'[a-z][a-z0-9_-]{1,39}',kode):
        raise FasilitasError('Nama 2–100 karakter; kode 2–40 huruf kecil, angka, tanda - atau _.')
    row = (await db.execute(select(JenisProsesProduksi).where(JenisProsesProduksi.id==id).with_for_update())).scalar_one_or_none() if id else None
    if id and (row is None or row.versi != versi): raise FasilitasError('Data berubah. Periksa ulang sebelum menyimpan.')
    sebelum = snapshot(row) if row else None
    if row and row.kode != kode: raise FasilitasError('Kode jenis tetap untuk menjaga hubungan dan riwayat; nama dapat diubah.')
    if (await db.execute(select(JenisProsesProduksi.id).where(JenisProsesProduksi.kode==kode, JenisProsesProduksi.id != (id or 0)))).first():
        raise FasilitasError('Kode jenis sudah digunakan.')
    if row and not aktif:
        lines = list((await db.execute(select(LiniProduksi).where(LiniProduksi.jenis_proses_id==row.id).with_for_update())).scalars())
        for line in lines:
            if await sedang_dipakai(db,line,termasuk_bahan=True): raise FasilitasError('Jenis proses masih digunakan. Selesaikan proses aktif terlebih dahulu.')
    if row is None:
        row=JenisProsesProduksi(kode=kode,nama=nama,aktif=aktif,versi=1);db.add(row)
    else:
        row.nama=nama;row.aktif=aktif;row.versi+=1
    await db.flush()
    db.add(AuditFasilitas(user_id=user.id,objek='jenis_proses',objek_id=row.id,sebelum=sebelum,sesudah=snapshot(row)))
    return row

async def simpan_lini(db, *, user, nama, kode, warehouse_id, jenis_proses_id, dryer_id=None, aktif=True, id=None, versi=None):
    from hmu_identitas import peran as P
    if not await boleh_kelola(db,user): raise PermissionError('Tidak berhak mengatur fasilitas.')
    nama,kode=nama.strip(),kode.strip().lower()
    if not 2 <= len(nama) <= 100 or not re.fullmatch(r'[a-z][a-z0-9_-]{1,39}',kode):
        raise FasilitasError('Isi nama dan kode fasilitas yang valid.')
    # Kunci master jenis sebelum line, sama dengan perubahan jenis.
    jenis=(await db.execute(select(JenisProsesProduksi).where(JenisProsesProduksi.id==jenis_proses_id).with_for_update())).scalar_one_or_none()
    wh=await db.get(Warehouse,warehouse_id)
    if not jenis or not jenis.aktif or not wh or not wh.aktif: raise FasilitasError('Jenis proses atau gudang tidak aktif.')
    row=(await db.execute(select(LiniProduksi).where(LiniProduksi.id==id).with_for_update())).scalar_one_or_none() if id else None
    if id and (row is None or row.versi != versi): raise FasilitasError('Data berubah. Periksa ulang sebelum menyimpan.')
    sebelum=snapshot(row) if row else None
    berubah_relasi = bool(row and (row.warehouse_id != warehouse_id or row.jenis_proses_id != jenis_proses_id or row.dryer_id != dryer_id))
    if berubah_relasi:
        terpakai=await sedang_dipakai(db,row,termasuk_bahan=True)
        for model in PENJALAN.values():
            terpakai = terpakai or bool(await db.scalar(select(model.id).where(model.lini_produksi_id==row.id).limit(1)))
        if terpakai:raise FasilitasError('Fasilitas sudah memiliki proses/riwayat. Lokasi, jenis, dan alat tetap; nonaktifkan dan buat fasilitas baru untuk perubahan fisik.')
    if row and not aktif and await sedang_dipakai(db,row,termasuk_bahan=True): raise FasilitasError('Fasilitas masih digunakan proses aktif.')
    if (await db.execute(select(LiniProduksi.id).where(LiniProduksi.warehouse_id==warehouse_id,LiniProduksi.kode==kode,LiniProduksi.id != (id or 0)))).first():
        raise FasilitasError('Kode fasilitas sudah digunakan di gudang ini.')
    if jenis.kode=='pengeringan':
        dryer=(await db.execute(select(Dryer).where(Dryer.id==dryer_id).with_for_update())).scalar_one_or_none()
        if not dryer or dryer.warehouse_id!=warehouse_id: raise FasilitasError('Pilih dryer yang berada di gudang tersebut.')
        if (await db.execute(select(LiniProduksi.id).where(LiniProduksi.dryer_id==dryer_id,LiniProduksi.id != (id or 0)))).first(): raise FasilitasError('Dryer sudah terhubung ke fasilitas lain.')
    elif dryer_id: raise FasilitasError('Dryer hanya untuk fasilitas pengeringan.')
    if row is None:
        row=LiniProduksi(kode=kode,nama=nama,warehouse_id=warehouse_id,jenis_proses_id=jenis_proses_id,dryer_id=dryer_id,aktif=aktif,versi=1);db.add(row)
    else:
        row.kode=kode;row.nama=nama;row.aktif=aktif;row.versi+=1
        row.warehouse_id=warehouse_id;row.jenis_proses_id=jenis_proses_id;row.dryer_id=dryer_id
    await db.flush()
    db.add(AuditFasilitas(user_id=user.id,objek='lini',objek_id=row.id,sebelum=sebelum,sesudah=snapshot(row)))
    return row

async def seed_fasilitas(db):
    """Instalasi baru saja: isi master hilang, tidak mengaktifkan ulang master lama."""
    dibuat=0
    for kode,nama in (('pengeringan','Pengeringan'),('penggilingan','Penggilingan'),('penyosohan','Penyosohan')):
        j=await db.scalar(select(JenisProsesProduksi).where(JenisProsesProduksi.kode==kode))
        if not j:
            j=JenisProsesProduksi(kode=kode,nama=nama,aktif=True,versi=1);db.add(j);await db.flush();dibuat+=1
        if kode=='pengeringan':
            for d in (await db.execute(select(Dryer))).scalars():
                if not await db.scalar(select(LiniProduksi.id).where(LiniProduksi.dryer_id==d.id)):
                    db.add(LiniProduksi(kode=f'dryer-{d.id}',nama=d.nama,warehouse_id=d.warehouse_id,jenis_proses_id=j.id,dryer_id=d.id,aktif=d.status=='aktif',versi=1));dibuat+=1
        else:
            w=await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi==('g1' if kode=='penggilingan' else 'g2')))
            if w and not await db.scalar(select(LiniProduksi.id).where(LiniProduksi.jenis_proses_id==j.id)):
                db.add(LiniProduksi(kode=kode,nama=nama+' 1',warehouse_id=w.id,jenis_proses_id=j.id,aktif=True,versi=1));dibuat+=1
        await db.flush()
    return dibuat

async def dryer_diizinkan(db, *, user, dryer_id):
    d=await db.get(Dryer,dryer_id) if dryer_id else None
    if not d or not izin_gudang(user,d.warehouse_id):
        raise FasilitasError('Dryer tidak tersedia atau di luar gudang kerja Anda.')
    return d

async def lot_diizinkan(db, *, user, lot):
    if lot is None:raise FasilitasError('Pengeringan tidak tersedia.')
    if lot.dryer_id is None:
        raise FasilitasError('Catatan ini bukan pengeringan dengan dryer.')
    return await dryer_diizinkan(db,user=user,dryer_id=lot.dryer_id)

async def label_fasilitas(db, proc):
    """Label dari relasi nyata; ID line historis yang tidak diketahui tidak ditebak."""
    from app.models import Silo,PolishingSiloUsage
    line=await db.get(LiniProduksi,proc.lini_produksi_id) if proc.lini_produksi_id else None
    wid=line.warehouse_id if line else None
    if wid is None and isinstance(proc,DryingLot):
        dryer=await db.get(Dryer,proc.dryer_id) if proc.dryer_id else None
        wid=dryer.warehouse_id if dryer else None
    if wid is None and isinstance(proc,MillingProcess):
        silo=await db.get(Silo,proc.silo_id) if proc.silo_id else None
        wid=silo.warehouse_id if silo else None
    if wid is None and isinstance(proc,PolishingProcess):
        ids=list((await db.execute(select(Silo.warehouse_id).join(PolishingSiloUsage,PolishingSiloUsage.silo_id==Silo.id).where(PolishingSiloUsage.polishing_process_id==proc.id).distinct())).scalars())
        wid=ids[0] if len(ids)==1 else None
    wh=await db.get(Warehouse,wid) if wid else None
    return ' · '.join(x for x in (wh.nama_gudang if wh else None,line.nama if line else None) if x) or 'Fasilitas historis belum tercatat'
