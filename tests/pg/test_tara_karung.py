"""Tara karung DIPOTONG — keluhan pemilik 21 September 2026, QA 24 Sep (c) 2b.

Angka pemilik: timbang pertama 13.000, truk kosong 3.000 → netto 10.000 kg.
200 karung × 0,25 kg = 50 kg tara karung → BARANGNYA 9.950 kg. Pos Timbang
menyebut 9.950 di layarnya, dan membandingkan NOTA dengan angka itu
(`timbangan/logic.py`: `barang = netto - total_tara`, `selisih = barang -
acuan`). Produksi mengambil 10.000.

Sebabnya bukan hitungan yang salah melainkan kolom yang tak pernah dibaca:
sampai 24 September 2026 `berat_barang_kg` muncul TEPAT SATU KALI di seluruh
repo produksi — di data contoh mode uji. Seluruh jalur bobot (layar pilihan
tiket, pembentukan batch, poller, rekonsiliasi) berdiri di atas
`netto_timbangan_kg`, yaitu berat TRUKNYA.

Yang dijaga berkas ini ada tiga, dan ketiganya harus tetap sejalan: layar yang
menawarkan tiket, batch yang lahir dari tiket, dan poller yang mengisi bobot
belakangan. Basis yang berbeda di salah satunya berarti angka yang berubah
sendiri sesudah truknya pergi.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select, text

pytestmark = pytest.mark.asyncio

#: Tiket ditulis SQL mentah: tabelnya milik repo timbangan, tak ada di
#: metadata app ini (lihat `test_kontrak_timbangan`). `jumlah_karung` &
#: `total_tara_kg` ikut disebut karena dari situlah angka 9.950 itu lahir —
#: uji yang hanya menyetel `berat_barang_kg` tidak menirukan tiket sungguhan.
_SQL_TIKET = text("""
    INSERT INTO timbangan_transaksi
        (kode, tanggal, arah, jenis_kode, cara_timbang, supplier_id, pihak_nama,
         nomor_polisi, timbang1_kg, timbang1_waktu, timbang2_kg, timbang2_waktu,
         berat_kosong_kg, netto_timbangan_kg, jumlah_karung, total_tara_kg,
         berat_barang_kg, berat_acuan_kg, status_tiket, status_transaksi)
    VALUES
        (:kode, :tanggal, 'MASUK', :jenis, 'DUA_KALI', :supplier_id, :pihak,
         :nopol, :t1, :waktu, :t2, :waktu2, :kosong, :netto, :karung, :tara,
         :barang, :nota, :status_tiket, 'AKTIF')
    RETURNING id
""")


async def _tiket(db, kode, *, nopol="B 1234 UJI", t1=13000, kosong=3000,
                 karung=200, tara=50.0, nota=0, jenis="GABAH_KERING",
                 supplier_id=None, selesai=True):
    """Tiket pemilik: netto 10.000, tara karung 50 kg, barang 9.950."""
    from app.database import now_local

    waktu = datetime.now(timezone.utc)
    netto = t1 - kosong
    return (await db.execute(_SQL_TIKET, {
        "kode": kode, "tanggal": now_local().date(), "jenis": jenis,
        "supplier_id": supplier_id, "pihak": "Pak Uji", "nopol": nopol,
        "t1": t1, "waktu": waktu,
        "t2": (kosong if selesai else None), "waktu2": (waktu if selesai else None),
        "kosong": (kosong if selesai else None),
        "netto": (netto if selesai else None),
        "karung": karung, "tara": tara,
        "barang": (netto - tara if selesai else None), "nota": nota,
        "status_tiket": "SELESAI" if selesai else "TERBUKA",
    })).scalar_one()


@pytest_asyncio.fixture
async def pabrik(pg, pemakai):
    from app.models import User, Warehouse
    from app.services.seed import seed_master

    await seed_master()
    async with pg() as db:
        g1 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 1%")))).scalars().first()
        u = await db.get(User, pemakai.id)
        u.default_warehouse_id = g1.id
        await db.commit()
    return {"g1": g1.id}


async def _batch(pg, pemakai, tid):
    from app.models import User
    from app.penggilingan.gudang1.services.purchase import create_purchase_batch_dari_timbang

    async with pg() as db:
        u = await db.get(User, pemakai.id)
        r = await create_purchase_batch_dari_timbang(
            db, user=u, timbangan_transaksi_id=tid, kondisi_gabah="kering")
        return r.batch.kode_batch


async def _baca(pg, kode):
    from app.models import PurchaseBatch

    async with pg() as db:
        return (await db.execute(select(PurchaseBatch).where(
            PurchaseBatch.kode_batch == kode))).scalars().one()


async def test_batch_memakai_berat_barang_bukan_netto(pg, pemakai, pemasok, pabrik):
    """9.950, bukan 10.000. Inilah selisih 50 kg yang dilaporkan pemilik."""
    async with pg() as db:
        tid = await _tiket(db, "T-TARA-01", supplier_id=pemasok.id)
        await db.commit()

    b = await _baca(pg, await _batch(pg, pemakai, tid))
    assert float(b.berat_total_kg) == 9950, "tara karung 50 kg tak dipotong"
    # Sumbernya tetap 'timbangan': angkanya memang dari timbangan, cuma
    # barangnya — bukan truknya.
    assert b.sumber_berat == "timbangan"


async def test_nota_tetap_menang_atas_barang(pg, pemakai, pemasok, pabrik):
    """Urutannya tidak berubah, hanya cadangannya. Nota 9.800 tetap dipakai —
    keputusan yang sudah berdiri sejak jembatan ini dibuat, dan QA sudah
    membuktikannya benar (24 Sep (c) 2a)."""
    async with pg() as db:
        tid = await _tiket(db, "T-TARA-02", nota=9800, supplier_id=pemasok.id)
        await db.commit()

    b = await _baca(pg, await _batch(pg, pemakai, tid))
    assert (float(b.berat_total_kg), b.sumber_berat) == (9800, "nota")


async def test_tiket_lama_tanpa_snapshot_barang_tetap_memakai_netto(pg, pemakai, pemasok, pabrik):
    """Tiket yang ditutup sebelum kolomnya terisi tak boleh jadi "menunggu".

    `berat_barang_kg` kosong berarti "tak ada angkanya", bukan "nol kilo" —
    alasan yang sama dengan nota (`timbangan/logic.py` menolak menuduh truk
    tanpa nota kehilangan seluruh muatannya)."""
    async with pg() as db:
        tid = await _tiket(db, "T-TARA-03", karung=0, tara=0.0, supplier_id=pemasok.id)
        await db.execute(text("UPDATE timbangan_transaksi SET berat_barang_kg = NULL "
                              "WHERE id = :i"), {"i": tid})
        await db.commit()

    b = await _baca(pg, await _batch(pg, pemakai, tid))
    assert (float(b.berat_total_kg), b.sumber_berat) == (10000, "timbangan")


async def test_poller_mengisi_barang_bukan_netto(pg, pemakai, pemasok, pabrik):
    """Jalur kedua: batch lahir saat tiket masih TERBUKA (bobot menunggu),
    tiketnya ditutup belakangan, poller yang mengisi. Dua jalur satu angka —
    kalau tidak, bobot batch BERUBAH sendiri 50 kg sesudah truknya pergi."""
    from app.penggilingan.gudang1.services.sinkron_bobot import satu_putaran

    async with pg() as db:
        tid = await _tiket(db, "T-TARA-04", nopol="B 777 BARU", selesai=False,
                           supplier_id=pemasok.id)
        await db.commit()

    kode = await _batch(pg, pemakai, tid)
    assert (await _baca(pg, kode)).sumber_berat == "menunggu"

    async with pg() as db:
        await db.execute(text("""
            UPDATE timbangan_transaksi
               SET timbang2_kg = 3000, timbang2_waktu = now(), berat_kosong_kg = 3000,
                   netto_timbangan_kg = 10000, berat_barang_kg = 9950,
                   status_tiket = 'SELESAI'
             WHERE id = :i"""), {"i": tid})
        await db.commit()
    await satu_putaran()

    b = await _baca(pg, kode)
    assert (float(b.berat_total_kg), b.sumber_berat) == (9950, "timbangan")


async def test_rekonsiliasi_memakai_basis_yang_sama(pg, pemakai, pemasok, pabrik):
    """Batch yang sudah benar tak boleh dilaporkan sebagai "bobot tiket berubah".

    Rekonsiliasi yang memakai basis lain akan menandai SETIAP tiket bertara
    karung — daftar penuh pekerjaan yang justru salah bila dikerjakan, dan
    daftar semacam itu berhenti dibaca (alasan yang sama dengan butir ①)."""
    from app.penggilingan.gudang1.services.rekonsiliasi import rekonsiliasi

    async with pg() as db:
        tid = await _tiket(db, "T-TARA-05", supplier_id=pemasok.id)
        await db.commit()
    kode = await _batch(pg, pemakai, tid)

    # Harga diverifikasi → batch ini MEMBEKU: kalau basisnya beda, inilah yang
    # muncul di butir ③ sebagai "tersimpan 9.950 → tiket kini 10.000".
    async with pg() as db:
        from app.models import PurchaseBatch

        b = (await db.execute(select(PurchaseBatch).where(
            PurchaseBatch.kode_batch == kode))).scalars().one()
        b.flag_unverified = False
        await db.commit()

    async with pg() as db:
        d = await rekonsiliasi(db)
    assert [x for x in d.get("revisi", []) if x["kode_batch"] == kode] == []


async def test_layar_pilihan_tiket_menyebut_angka_yang_sama(pg, pemasok, pabrik):
    """Yang dibaca operator di daftar tiket = yang akan tersimpan.

    Daftar yang menyebut 10.000 lalu menyimpan 9.950 membuat orang mengira
    salah satunya rusak — dan yang ia laporkan kelak bukan bobotnya, melainkan
    "aplikasinya aneh"."""
    from app.penggilingan.gudang1.services.timbang_link import tiket_masuk_aktif

    async with pg() as db:
        await _tiket(db, "T-TARA-06", nopol="B 606 XX", supplier_id=pemasok.id)
        await db.commit()

    async with pg() as db:
        tiket = [t for t in await tiket_masuk_aktif(db) if t["kode"] == "T-TARA-06"]
    assert tiket and tiket[0]["berat_hpp_kg"] == 9950
    assert tiket[0]["sumber_berat"] == "timbangan"
