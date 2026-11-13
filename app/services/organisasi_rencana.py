"""Pratinjau penetapan data lama. Modul ini tidak menyediakan jalur penerapan."""
from dataclasses import dataclass
from sqlalchemy import select, func
from hmu_core import Perusahaan,LokasiPabrik,PenempatanGudang,Warehouse,Silo,Dryer
from app.models import LiniProduksi
from app.services.organisasi_master import OrganisasiError


@dataclass(frozen=True)
class BarisRencana:
    warehouse_id:int
    nama:str
    keadaan:str
    tujuan_lama:str
    silo:int
    dryer:int
    lini:int


@dataclass(frozen=True)
class RencanaPenetapan:
    company_id:int
    lokasi_pabrik_id:int
    perusahaan:str
    lokasi:str
    gudang:tuple[BarisRencana,...]


async def fasilitas(db):
    with db.no_autoflush:
        wh=list(await db.scalars(select(Warehouse).order_by(Warehouse.nama_gudang,Warehouse.id)))
        counts={}
        for model in (Silo,Dryer,LiniProduksi):
            counts[model]=dict((await db.execute(select(model.warehouse_id,func.count()).group_by(model.warehouse_id))).all())
    return wh,counts


async def pratinjau(db,*,lokasi_pabrik_id,warehouse_ids):
    if type(lokasi_pabrik_id) is not int or lokasi_pabrik_id<=0:
        raise OrganisasiError('Pilih lokasi pabrik tujuan.')
    ids=set(warehouse_ids)
    if not ids or len(ids)>1000 or any(type(i) is not int or i<=0 for i in ids):
        raise OrganisasiError('Pilih minimal satu gudang yang tersedia.')
    with db.no_autoflush:
        tujuan=(await db.execute(select(LokasiPabrik,Perusahaan).join(Perusahaan,LokasiPabrik.company_id==Perusahaan.id)
          .where(LokasiPabrik.id==lokasi_pabrik_id,LokasiPabrik.aktif.is_(True),Perusahaan.aktif.is_(True)))).one_or_none()
        if tujuan is None:raise OrganisasiError('Lokasi pabrik atau perusahaan tujuan tidak aktif atau tidak tersedia.')
        site,company=tujuan
        wh,counts=await fasilitas(db)
        if ids-{w.id for w in wh}:raise OrganisasiError('Daftar gudang sudah berubah. Periksa pilihan kembali.')
        lama={p.warehouse_id:(p,s,c) for p,s,c in (await db.execute(select(PenempatanGudang,LokasiPabrik,Perusahaan)
          .join(LokasiPabrik,PenempatanGudang.lokasi_pabrik_id==LokasiPabrik.id)
          .join(Perusahaan,PenempatanGudang.company_id==Perusahaan.id))).all()}
        rows=[]
        for w in wh:
            if w.id not in ids:continue
            old=lama.get(w.id)
            keadaan='Belum ditetapkan' if not old else 'Sudah sesuai' if old[0].lokasi_pabrik_id==site.id and old[0].company_id==company.id else 'Lokasi berbeda — perlu ditinjau'
            if not w.aktif:keadaan='Gudang nonaktif — perlu ditinjau'
            rows.append(BarisRencana(w.id,w.nama_gudang,keadaan,
                f'{old[2].nama} / {old[1].nama}' if old else 'Belum ditetapkan',
                counts[Silo].get(w.id,0),counts[Dryer].get(w.id,0),counts[LiniProduksi].get(w.id,0)))
        return RencanaPenetapan(company.id,site.id,company.nama,site.nama,tuple(rows))
