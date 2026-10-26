"""Rincian baca saja Menir, memakai saldo dan alokasi layanan simpan lama."""
from sqlalchemy import select
from app.models import Jasa, PolishingProcess, PolishingSiloUsage
from app.penggilingan.gudang2.rencana_hasil_samping import saldo_sumber, alokasikan
from app.penggilingan.gudang2 import service as g2


def pemilik_sah(pemilik):
    pilihan = str(pemilik or '').strip()
    if pilihan != 'pabrik' and not pilihan.isdigit():
        raise ValueError('Pilih pemilik stok menir yang sah.')
    return None if pilihan == 'pabrik' else int(pilihan)


async def rincian(db, pemilik, berat=None, silo=''):
    from app.services.jasa import nama_pemilik
    from app.services.angka import angka_wajar
    owner = pemilik_sah(pemilik)
    if owner is not None and await db.get(Jasa, owner) is None:
        raise ValueError('Pemilik stok jasa tidak ditemukan.')
    data = await saldo_sumber(db, 'menir', owner)
    out = dict(pemilik=await nama_pemilik(db, owner) if owner else 'Milik pabrik',
               jasa_id=owner, saldo_kg=data['saldo_kg'], sumber=data['sumber'],
               keluar_curah=data['keluar_curah'], keluar_kemasan=data['keluar_kemasan'],
               rencana=None, pesan='', peringatan_tujuan='', proses_penerima=[])
    dest = await g2.get_g2_silo(db, silo) if silo else None
    if dest:
        aktif = (await db.execute(select(PolishingProcess.id, PolishingProcess.kode_proses)
            .join(PolishingSiloUsage).where(PolishingSiloUsage.silo_id == dest.id,
                PolishingSiloUsage.berat_akhir_kg.is_(None)))).all()
        out['proses_penerima'] = [dict(id=i, kode=k) for i,k in aktif]
    if berat is None or str(berat).strip() == '':
        return out
    try:
        kg = angka_wajar(berat, 'Berat yang masuk silo')
        rencana = alokasikan(data, 'menir', kg)
    except (ValueError, g2.Gudang2Error) as e:
        out['pesan'] = str(e)
        return out
    saldo = {s['proses_id']:s['tersedia'] for s in data['sumber']}
    rows = [dict(proses_id=p.id, kode=p.kode_proses, kg=w,
                 sisa_kg=max(0.0, saldo[p.id]-w)) for p,w in rencana]
    out['rencana'] = dict(kg=sum(w for _,w in rencana), diminta_kg=kg,
                         sisa_kg=max(0.0,data['saldo_kg']-sum(w for _,w in rencana)), fifo=rows)
    if dest and any(p.id in {i for i,_ in aktif} for p,_ in rencana):
        out['peringatan_tujuan'] = 'Silo tujuan masih dipakai proses sumber menir. Pilih silo lain.'
    return out
