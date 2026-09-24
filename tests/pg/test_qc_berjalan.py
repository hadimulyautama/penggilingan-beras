"""Mutu dicatat SELAGI giling berjalan, dan hasilnya dirata-rata.

Keputusan pemilik 24 September 2026: "pencatatan juga bisa dilakukan saat proses
berlangsung dari kartu proses yang sedang berlangsung. nanti hasilnya di
rata-rata." Contohnya memang diambil dari beras yang baru keluar mesin, bukan
dari tumpukan yang sudah ditutup berjam-jam sebelumnya.

Dua hal yang sudah ada sebelum ini, dan satu yang tidak:

  · `milling_qc_logs` SUDAH tambah-saja — tiap pencatatan menyimpan baris baru
    berikut jam dan pencatatnya. Jadi beberapa kali catat dalam satu proses
    memang tersimpan, bukan saling menimpa;
  · borangnya HANYA menawarkan giling yang sudah selesai;
  · dan tak ada satu pun tempat yang membaca angka-angka itu kembali. Di
    seluruh repo tabel itu cuma ditulis, dihitung jumlahnya, dan diperiksa
    "sudah ada atau belum". Yang dicatat tanpa pernah terbaca sama saja dengan
    yang tak dicatat, kecuali ia memakan waktu orang.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def giling(pg, pemakai, pemasok):
    """Satu proses giling yang SEDANG BERJALAN, berikut gabah masuknya."""
    from sqlalchemy import select

    from app.database import now_local
    from app.models import Silo, User, Warehouse
    from app.penggilingan.gudang1.models import MillingProcess
    from app.services.seed import seed_master

    await seed_master()
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        g1 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 1%")))).scalars().first()
        silo = (await db.execute(select(Silo).where(
            Silo.warehouse_id == g1.id))).scalars().first()
        if silo is None:
            silo = Silo(nama_silo="Silo Uji", warehouse_id=g1.id)
            db.add(silo)
            await db.flush()
        p = MillingProcess(kode_proses="LOT-QC-01", status="proses", silo_id=silo.id,
                           berat_gabah_masuk_kg=10_000, waktu_mulai=now_local(),
                           created_by=u.id)
        db.add(p)
        await db.commit()
        await db.refresh(p)
        return {"id": p.id, "kode": p.kode_proses, "user": u.id}


async def _catat(pg, giling, **nilai):
    from app.models import User
    from app.penggilingan.gudang1.services.milling import log_qc_milling

    async with pg() as db:
        u = await db.get(User, giling["user"])
        return await log_qc_milling(db, user=u, kode_proses=giling["kode"],
                                    kondisi=None, **{"kadar_air": None, "broken": None,
                                                     "susut": None, **nilai})


async def test_proses_yang_masih_berjalan_boleh_dicatat_mutunya(pg, giling):
    """Dulu `log_qc_milling` tak menolaknya, tetapi tak ada satu pintu pun yang
    menawarkannya — daftarnya hanya memuat yang berstatus selesai."""
    r = await _catat(pg, giling, kadar_air=13.0)
    assert r.proc.status == "proses"
    assert r.qc_count == 1


async def test_rata_rata_dari_beberapa_catatan(pg, giling):
    from app.penggilingan.gudang1.services.milling import qc_rata

    await _catat(pg, giling, kadar_air=13.0, broken=4.0)
    await _catat(pg, giling, kadar_air=14.0, broken=6.0)
    r = await _catat(pg, giling, kadar_air=15.0, broken=5.0)

    async with pg() as db:
        rata = await qc_rata(db, giling["id"])
    assert rata.n == 3
    assert rata.kadar_air == pytest.approx(14.0)
    assert rata.broken == pytest.approx(5.0)
    # Balasan aksinya membawa rata-rata SESUDAH catatan itu masuk: angka yang
    # baru diketik sudah diketahui orangnya, yang belum ia tahu adalah ke mana
    # angka itu menggeser rata-ratanya.
    assert r.rata is not None and r.rata.kadar_air == pytest.approx(14.0)
    assert "rata-rata 3 catatan" in r.rata.teks()


async def test_kolom_kosong_tak_menyeret_rata_rata_kolom_lain(pg, giling):
    """Borangnya menerima "isi minimal salah satu" — dan itulah jebakannya.

    Catatan yang cuma menyebut broken tak boleh dihitung sebagai "kadar air 0"
    maupun ikut membagi rata-rata kadar air. Dirata-rata bersama, dua tusukan
    kadar air 13 dan 15 ditambah satu catatan broken saja akan keluar 9,3% —
    angka yang tak pernah diukur siapa pun, dan tampak masuk akal.
    """
    from app.penggilingan.gudang1.services.milling import qc_rata

    await _catat(pg, giling, kadar_air=13.0)
    await _catat(pg, giling, kadar_air=15.0)
    await _catat(pg, giling, broken=8.0)

    async with pg() as db:
        rata = await qc_rata(db, giling["id"])
    assert rata.kadar_air == pytest.approx(14.0), "kolom kosong ikut membagi"
    assert rata.n_kadar_air == 2 and rata.n_broken == 1 and rata.n == 3
    assert rata.susut is None and rata.n_susut == 0


async def test_kartu_giling_berjalan_menyebut_rata_ratanya(pg, giling, pemakai):
    """Angka yang tersimpan tanpa pernah terbaca sama saja dengan yang tak
    dicatat. Kartunya juga yang menawarkan tombol mencatat berikutnya."""
    from app.services.berjalan import untuk_gudang1

    await _catat(pg, giling, kadar_air=13.0)
    await _catat(pg, giling, kadar_air=15.0)

    async with pg() as db:
        b = await untuk_gudang1(db, boleh_qc=True)
    kartu = next(x for x in b.berjalan if x.kode == "LOT-QC-01")
    mutu = dict(kartu.fakta).get("Mutu")
    assert mutu and "KA 14,0%" in mutu and "2 catatan" in mutu
    assert any(p[0] == "qc_giling" for p in kartu.pilihan), "tombol catat mutu tak ada"

    # Tanpa wewenang: kartunya tetap menyebut mutunya (itu kabar), tetapi tak
    # menawarkan tombol yang akan ditolak rutenya.
    async with pg() as db:
        b2 = await untuk_gudang1(db)
    kartu2 = next(x for x in b2.berjalan if x.kode == "LOT-QC-01")
    assert dict(kartu2.fakta).get("Mutu")
    assert not any(p[0] == "qc_giling" for p in kartu2.pilihan)


async def test_semuanya_padam_saat_pencatatan_mutu_dimatikan(pg, giling, pemakai):
    from app.models import User
    from app.services.berjalan import untuk_gudang1
    from app.services.setelan import set_fitur_mutu

    await _catat(pg, giling, kadar_air=13.0)
    async with pg() as db:
        await set_fitur_mutu(db, False, user=await db.get(User, giling["user"]))

    async with pg() as db:
        b = await untuk_gudang1(db, boleh_qc=True)
    kartu = next(x for x in b.berjalan if x.kode == "LOT-QC-01")
    assert "Mutu" not in dict(kartu.fakta), "baris mutu tak ikut padam"
    assert not any(p[0] == "qc_giling" for p in kartu.pilihan), "tombol tak ikut padam"


async def test_giling_berjalan_ditawarkan_borangnya(pg, giling, pemakai):
    """Ujung ke ujung lewat sumber yang dibaca borang — bukan cuma layanannya."""
    from app.models import User
    from app.web.api import milling_noqc

    async with pg() as db:
        u = await db.get(User, pemakai.id)
        u.role = "superadmin"
        await db.commit()
        await db.refresh(u)
    daftar = await milling_noqc(user=u)
    kode = [x["value"] for x in daftar]
    assert "LOT-QC-01" in kode, "giling yang sedang berjalan tak ditawarkan"
    label = next(x["label"] for x in daftar if x["value"] == "LOT-QC-01")
    assert "sedang digiling" in label
    # Nilainya tetap kode prosesnya apa adanya — penguncian penunjuk dari kartu
    # mencocokkan `value`, bukan `label`.
    assert daftar[0]["value"] == "LOT-QC-01", "yang sedang berjalan tak di atas"


async def _pk_sudah_keluar(pg, giling, kg: float = 6_000) -> None:
    """Catat hasil giling supaya lotnya punya PK dan muncul di layar Stok."""
    from app.database import now_local
    from app.models import MillingProgressLog

    async with pg() as db:
        db.add(MillingProgressLog(milling_process_id=giling["id"], berat_kumulatif_kg=kg,
                                  waktu_update=now_local(), input_by=giling["user"]))
        await db.commit()


async def test_kartu_stok_menyebut_rata_rata_bukan_catatan_terakhir(pg, giling):
    """Satu lot, satu angka mutu — di layar mana pun ia dibaca.

    Sampai 24 September 2026 kartu Stok menggambar catatan TERBARU sementara
    tombolnya dan kartu giling berjalan menyebut rata-rata. Jadi orang yang
    mencatat kadar air 12 sesudah 14 diberi tahu "13,0%" lalu melihat "12,0%"
    untuk lot yang sama di layar berikutnya, dan tak ada yang keliru cukup jelas
    untuk dilaporkan. Temuan QA T-2; pemilik memilih rata-rata, sesuai janji
    tombolnya.
    """
    from app.services.stok import pk_gudang1

    await _pk_sudah_keluar(pg, giling)
    await _catat(pg, giling, kadar_air=14.0)
    await _catat(pg, giling, kadar_air=12.0)

    async with pg() as db:
        lot = next(l for l in await pk_gudang1(db) if l.kode == "LOT-QC-01")
    assert dict(lot.mutu).get("Kadar air") == "13,0%", \
        f"kartu Stok tak memakai rata-rata: {lot.mutu}"


async def test_kartu_stok_tak_menyeret_kolom_yang_tak_diisi(pg, giling):
    """Jebakan yang sama seperti di `qc_rata`, dan ia harus tertutup di kartu
    juga: catatan yang cuma menyebut broken tak boleh ikut membagi rata-rata
    kadar air, dan kolom yang belum pernah diisi tak digambar sebagai 0%."""
    from app.services.stok import pk_gudang1

    await _pk_sudah_keluar(pg, giling)
    await _catat(pg, giling, kadar_air=13.0)
    await _catat(pg, giling, kadar_air=15.0)
    await _catat(pg, giling, broken=8.0)

    async with pg() as db:
        lot = next(l for l in await pk_gudang1(db) if l.kode == "LOT-QC-01")
    m = dict(lot.mutu)
    assert m.get("Kadar air") == "14,0%", f"kolom kosong ikut membagi: {lot.mutu}"
    assert m.get("Butir patah") == "8,0%"
    assert "Susut" not in m, "kolom yang tak pernah diisi digambar juga"
