"""Identitas nomor polisi dipakai bersama oleh Timbangan dan Operasional."""
from sqlalchemy import select


async def test_nomor_polisi_menautkan_ke_master_armada_yang_sama(pg):
    from app.models import Armada
    from app.services.armada import armada_dari_nomor_polisi

    async with pg() as db:
        pertama = await armada_dari_nomor_polisi(db, "  ad 1234 xy ")
        kedua = await armada_dari_nomor_polisi(db, "AD 1234 XY")
        assert pertama is not None and kedua is not None
        assert pertama.id == kedua.id
        assert pertama.nomor_polisi == "AD 1234 XY"

        tersimpan = (await db.execute(
            select(Armada).where(Armada.nomor_polisi == "AD 1234 XY")
        )).scalar_one()
        assert tersimpan.id == pertama.id
        await db.commit()
