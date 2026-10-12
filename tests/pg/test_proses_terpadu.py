from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from hmu_core import (ArusProses, JenisPemilik, JenisProses, PemilikProses,
                      ProsesOperasional, StatusProses, buat_produk)
from hmu_core.proses_db import ArusProsesTerpadu, ProsesTerpadu
from app.services.proses_bersama import simpan_proses_bersama, tutup_proses_bersama


async def test_proses_lintas_aplikasi_menyimpan_identitas_bahan_dan_hasil(pg):
    proses = ProsesOperasional(
        aplikasi="produksi", id=123, kode="LOT-TEST-01",
        jenis=JenisProses.PENGGILINGAN, status=StatusProses.SELESAI,
        pemilik=PemilikProses(JenisPemilik.PABRIK),
        bahan=(ArusProses(buat_produk("gabah", kondisi="kering"),
                          Decimal("1000"), "GB-TEST-01", 1),),
        hasil=(ArusProses(buat_produk("beras_pk"), Decimal("650"),
                          "PK-TEST-01", 2),),
    )
    async with pg() as db:
        row = proses.ke_entitas(tabel_sumber="milling_process", id_sumber=123)
        db.add(row)
        await db.commit()
        saved = (await db.execute(select(ProsesTerpadu).where(
            ProsesTerpadu.kode == "LOT-TEST-01"
        ))).scalar_one()
        assert saved.aplikasi == "produksi"
        assert saved.jenis_pemilik == "pabrik"
        assert [(arus.arah, arus.komoditas, float(arus.berat_kg))
                for arus in saved.arus] == [
                    ("bahan", "gabah", 1000), ("hasil", "beras_pk", 650),
                ]


async def test_arus_proses_menolak_berat_negatif_di_postgres(pg):
    async with pg() as db:
        row = ProsesTerpadu(
            aplikasi="produksi", tabel_sumber="milling_process", id_sumber="bad",
            kode="LOT-TEST-BAD", jenis="penggilingan", status="berjalan",
            jenis_pemilik="pabrik", referensi_asal=[], metadata_domain={},
        )
        row.arus.append(ArusProsesTerpadu(
            arah="bahan", komoditas="gabah", atribut_produk={}, berat_kg=-1,
        ))
        db.add(row)
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()


async def test_penutupan_mempertahankan_bahan_dan_mengganti_hasil(pg):
    async with pg() as db:
        await simpan_proses_bersama(
            db,
            ProsesOperasional(
                aplikasi="produksi", id=124, kode="LOT-TEST-CLOSE",
                jenis=JenisProses.PENGGILINGAN, status=StatusProses.BERJALAN,
                pemilik=PemilikProses(JenisPemilik.PABRIK),
                bahan=(ArusProses(buat_produk("gabah", kondisi="kering"),
                                  Decimal("1000"), "GB-TEST-CLOSE", 1),),
            ),
            tabel_sumber="milling_process", id_sumber=124,
        )
        await tutup_proses_bersama(
            db, tabel_sumber="milling_process", id_sumber=124,
            waktu_selesai=None,
            hasil=(ArusProses(buat_produk("beras_pk"), Decimal("650"),
                              "LOT-TEST-CLOSE"),),
        )
        await db.commit()
        saved = (await db.execute(select(ProsesTerpadu).where(
            ProsesTerpadu.kode == "LOT-TEST-CLOSE"
        ))).scalar_one()
        assert saved.status == "selesai"
        assert [(arus.arah, arus.komoditas, float(arus.berat_kg))
                for arus in saved.arus] == [
                    ("bahan", "gabah", 1000), ("hasil", "beras_pk", 650),
                ]
