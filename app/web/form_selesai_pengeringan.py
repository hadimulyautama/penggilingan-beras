"""Konteks baca saja; penyelesaian tetap sepenuhnya milik finish_drying."""
from sqlalchemy import func, select

from app.database import now_local
from app.models import DryingMoistureLog
from app.penggilingan.gudang1.services import drying as dr
from app.services.proses_aktif import _persen, _waktu
from app.web.form_kadar_air import ringkasan as konteks_pengeringan


async def ringkasan(db, *, kode_lot):
    data = await konteks_pengeringan(db, kode_lot=kode_lot)
    lot = await dr.get_lot_by_kode(db, kode_lot)
    # Masing-masing alat mencari catatan terakhir yang benar-benar berisi
    # bacaannya. Log akhir berisi mesin saja tidak menghapus alat tes terakhir.
    async def terakhir(kolom):
        return await db.scalar(select(DryingMoistureLog).where(
            DryingMoistureLog.drying_lot_id == lot.id, kolom.is_not(None)
        ).order_by(DryingMoistureLog.waktu_update.desc(),
                   DryingMoistureLog.id.desc()).limit(1))

    mesin = await terakhir(DryingMoistureLog.kadar_air_indikator)
    tes = await terakhir(DryingMoistureLog.kadar_air_tes_manual)
    terbaru = await dr._latest_log(db, lot.id)
    mulai = lot.waktu_mulai_pengeringan
    akhir = lot.waktu_selesai_pengeringan or now_local()
    jam = dr._hours(akhir, mulai) if mulai else None
    data.update(
        dapat_diselesaikan=lot.status == 'proses',
        mulai=_waktu(mulai),
        durasi=f'{jam:.1f} jam'.replace('.', ',') if jam is not None else 'Belum dapat dihitung',
        selesai=_waktu(lot.waktu_selesai_pengeringan),
        mulai_pendinginan=_waktu(lot.waktu_mulai_pendinginan),
        log_terakhir=terbaru.id if terbaru else None,
        jumlah_log=await db.scalar(select(func.count()).select_from(DryingMoistureLog).where(
            DryingMoistureLog.drying_lot_id == lot.id)),
        mesin_terakhir=_persen(mesin.kadar_air_indikator) if mesin else 'Belum diukur',
        mesin_waktu=_waktu(mesin.waktu_update) if mesin else 'Belum diukur',
        tes_terakhir=_persen(tes.kadar_air_tes_manual) if tes else 'Belum diukur',
        tes_waktu=_waktu(tes.waktu_update) if tes else 'Belum diukur',
    )
    return data
