"""Riwayat kejadian dan petugas: identitas yang tidak diketahui tetap disebut begitu."""
from math import ceil
from sqlalchemy import select, func
from app.models import JedaProses, JedaCatatan, User
from app.database import berzona
from app.penggilingan.gudang1.services.jeda import _kolom


def _jam(w):
    return berzona(w).strftime('%d/%m/%Y %H:%M:%S') if w else 'Tidak tercatat'


async def riwayat_jeda(db, *, jenis, id_, params=None, semua=False):
    params = params or {}
    jumlah = await db.scalar(select(func.count()).select_from(JedaProses).where(_kolom(jenis) == id_))
    akhir = max(1, ceil(jumlah/20))
    try:
        halaman = min(akhir, max(1,int(params.get('halaman_jeda','1'))))
    except (TypeError,ValueError):
        halaman = 1
    query = select(JedaProses).where(_kolom(jenis)==id_).order_by(JedaProses.mulai.desc(),JedaProses.id.desc())
    if not semua:
        query = query.offset((halaman-1)*20).limit(20)
    jedas = (await db.scalars(query)).all()
    ids = [j.id for j in jedas]
    events = (await db.execute(select(JedaCatatan,User.nama)
        .outerjoin(User,User.id==JedaCatatan.dicatat_oleh)
        .where(JedaCatatan.jeda_id.in_(ids or [-1]))
        .order_by(JedaCatatan.waktu_kejadian,JedaCatatan.id))).all()
    nama_awal = dict((await db.execute(select(User.id,User.nama).where(
        User.id.in_([j.dicatat_oleh for j in jedas] or [-1])))).all())
    items=[]
    for j in jedas:
        baris=[(e,n) for e,n in events if e.jeda_id==j.id]
        if not baris:
            # Pembaca juga menerima catatan historis yang belum punya event.
            # dicatat_oleh merupakan penghenti, bukan identitas pelanjut.
            items.append(dict(aksi='Dihentikan',petugas='Dihentikan oleh: '+nama_awal.get(j.dicatat_oleh,'Tidak dapat dipastikan'),
                waktu=_jam(j.mulai),dicatat=_jam(j.created_at),sebab=j.sebab,catatan='',alasan='',
                dibatalkan=bool(j.dibatalkan_pada)))
            if j.selesai:
                items.append(dict(aksi='Penutupan lama',petugas='Dilanjutkan oleh: Tidak dapat dipastikan',
                    waktu=_jam(j.selesai),dicatat='Waktu pencatatan penutupan tidak diketahui',sebab=j.sebab,
                    catatan='Tidak dapat dipastikan apakah mesin dilanjutkan atau proses ditutup.',alasan='',dibatalkan=False))
            continue
        for e,nama in baris:
            nama=nama or 'Tidak dapat dipastikan'
            identitas={'hentikan':'Dihentikan oleh: ','lanjutkan':'Dilanjutkan oleh: ',
                'kondisi':'Kondisi diperbarui oleh: ','akhir_proses':'Ditutup bersama proses oleh: ',
                'penutupan_lama':'Dilanjutkan oleh: '}
            aksi={'hentikan':'Mesin dihentikan','lanjutkan':'Mesin dilanjutkan',
                  'kondisi':'Kondisi berubah; tetap dijeda','akhir_proses':'Proses selesai; mesin tidak dilanjutkan',
                  'penutupan_lama':'Penutupan lama; cara penutupan tidak diketahui'}
            items.append(dict(aksi=aksi.get(e.aksi,e.aksi),petugas=identitas.get(e.aksi,'Dicatat oleh: ')+nama,
                waktu=_jam(e.waktu_kejadian),dicatat=("Tidak dapat dipastikan" if e.aksi=="penutupan_lama" else _jam(e.dicatat_pada)),sebab=e.sebab,
                catatan=e.catatan or '',alasan=e.alasan_terlambat or '',dibatalkan=bool(e.dibatalkan_pada or j.dibatalkan_pada)))
    return dict(items=items,jumlah=jumlah,halaman=halaman,halaman_total=akhir)
