"""Tiket yang ditimbang tetapi jenisnya belum dipetakan produksi tetap TERLIHAT.

Ditemukan pemilik 23 September 2026 dengan cara terburuk: PK sudah ditimbang,
barangnya di halaman, dan tak ada satu layar pun yang menyebutnya. Sebabnya dua
penyaring yang masing-masing benar tetapi bersama meninggalkan lubang:

  · `berjalan._tiket_belum_ditaut` hanya memancarkan `model == "gabah"`
    ("PK & lainnya punya alurnya sendiri");
  · `meja_api._tiket_pk_luar` hanya memancarkan `is_pk`.

Jenis yang TIDAK dipetakan sama sekali tak diambil siapa pun. Hanya laporan
Rekonsiliasi menyebutnya — dan laporan dibuka orang sesudah ia curiga.

Dan lubangnya bukan sementara: `BERAS_MASUK` & `BROKEN_MASUK` memang belum
dipetakan (menunggu keputusan pemilik), dan taksonomi jenis di Pos Timbang
berbasis DATA, jadi jenis baru bisa lahir di sana tanpa produksi tahu.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text

pytestmark = pytest.mark.asyncio

_SQL_TIKET = text("""
    INSERT INTO timbangan_transaksi
        (kode, tanggal, arah, jenis_kode, cara_timbang, pihak_nama,
         nomor_polisi, timbang1_kg, timbang1_waktu, netto_timbangan_kg,
         berat_acuan_kg, status_tiket, status_transaksi)
    VALUES
        (:kode, :tanggal, 'MASUK', :jenis, 'DUA_KALI', :pihak,
         :nopol, 12000, :waktu, :netto, 0, 'SELESAI', 'AKTIF')
    RETURNING id
""")


async def _tiket(db, kode, jenis, *, pihak="UD Sumber Tani"):
    from app.database import now_local

    return (await db.execute(_SQL_TIKET, {
        "kode": kode, "tanggal": now_local().date(), "jenis": jenis,
        "pihak": pihak, "nopol": "B 9911 XY",
        "waktu": datetime.now(timezone.utc), "netto": 9800,
    })).scalar_one()


@pytest_asyncio.fixture
async def pabrik(pg):
    """Dua gudang + silo G2 — `_susun` memanggil `untuk_gudang1`/`untuk_gudang2`,
    dan keduanya menolak basis data tanpa master gudang."""
    from app.models import Silo, Warehouse

    async with pg() as db:
        g1 = Warehouse(nama_gudang="Gudang 1 - Selepan")
        g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
        db.add_all([g1, g2])
        await db.flush()
        db.add_all([Silo(nama_silo="Silo A", warehouse_id=g2.id),
                    Silo(nama_silo="Silo B", warehouse_id=g2.id)])
        await db.commit()


@pytest_asyncio.fixture
async def admin(pg):
    """Antrean meja hanya terbuka untuk admin ke atas."""
    from app.models import ProduksiAkun, User
    from app.peran import PERAN_ADMIN_KEATAS
    from hmu_identitas import sandi as S

    async with pg() as db:
        u = User(nama="Elfira Uji", role=sorted(PERAN_ADMIN_KEATAS)[0], status="aktif")
        db.add(u)
        await db.flush()
        a = ProduksiAkun(user_id=u.id, username="elfirauji",
                         password_hash=S.hash_sandi("rahasia123"),
                         status="aktif", mode_perangkat="pribadi")
        db.add(a)
        await db.commit()
        await db.refresh(a)
        return a


async def test_jenis_tak_dipetakan_muncul_sebagai_kartu_diam(pg, admin):
    from app.web import meja_api

    async with pg() as db:
        await _tiket(db, "TRX-UJI-TDK-01", "BERAS_MASUK")     # belum dipetakan
        await _tiket(db, "TRX-UJI-PK-01", "BERAS_PK")         # dipetakan → jalur PK
        await _tiket(db, "TRX-UJI-GB-01", "GABAH_KERING")     # dipetakan → jalur gabah
        await db.commit()

    async with pg() as db:
        tak_dikenal = await meja_api._tiket_jenis_tak_dikenal(db)
        pk = await meja_api._tiket_pk_luar(db)

    # Hanya yang TAK dipetakan, dan tepat satu.
    assert [k["kode"] for k in tak_dikenal] == ["TRX-UJI-TDK-01"]
    # Jalur PK tak berubah: ia tetap mengambil PK-nya, bukan yang ini.
    assert [k["kode"] for k in pk] == ["TRX-UJI-PK-01"]

    kartu = tak_dikenal[0]
    # ── DIAM: tak ada yang bisa ditekan ──
    # `_benda.html` memilih <details> bila `tombol`, <a href=?buka=> bila
    # `aksi`, dan kartu diam bila keduanya kosong. Borang mana pun akan
    # menolak jenis yang tak dikenalnya, dan kartu yang menjanjikan lalu
    # menolak lebih buruk daripada kartu yang diam.
    assert kartu["aksi"] == "" and kartu["tombol"] == [] and kartu["pilihan"] == []
    # ── Tetapi ia MENJELASKAN dirinya ──
    assert "BERAS_MASUK" in kartu["keadaan"] and "belum dikenal" in kartu["keadaan"]
    assert ["Jenis timbang", "BERAS_MASUK"] in kartu["fakta"]
    # Bobot & pemasoknya terbaca — itu yang dipakai orang mengenali truk mana.
    assert kartu["judul"] == "UD Sumber Tani"
    assert kartu["utama"] and kartu["utama"][1] == "kg"
    # Gudang tak ditebak: jenis yang belum dipetakan belum punya tujuan.
    assert kartu["gudang"] is None
    # Dan ia duduk di blok "Tiket timbang belum dicatat", bersama tiket PK.
    assert kartu["kelompok"] == "tiket"


async def test_ikut_antrean_dan_lencana_meja(pg, admin, pabrik):
    """Bukan cuma fungsinya benar — ia benar-benar sampai ke layar."""
    from app.web import meja_api

    async with pg() as db:
        await _tiket(db, "TRX-UJI-TDK-02", "BROKEN_MASUK")
        await db.commit()

    async with pg() as db:
        d = await meja_api._susun(db, admin)

    kode = [k["kode"] for k in d["menunggu"]]
    assert "TRX-UJI-TDK-02" in kode, "tiket tak dikenal tak sampai ke antrean"
    assert d["lencana"]["MENUNGGU"] == len(d["menunggu"])
    assert d["lencana"]["MENUNGGU"] >= 1, "lencana tak menghitungnya"


async def test_tiket_yang_sudah_dicatat_keluar_dari_antrean(pg, admin):
    """Jaring ini tak boleh jadi daftar yang tak pernah habis: begitu tiketnya
    tertaut batch yang hidup, `tiket_masuk_aktif` berhenti menawarkannya —
    aturan yang sama dengan tiket gabah & PK, bukan aturan baru."""
    from app.web import meja_api

    async with pg() as db:
        tid = await _tiket(db, "TRX-UJI-TDK-03", "BERAS_MASUK")
        await db.commit()

    async with pg() as db:
        assert [k["kode"] for k in await meja_api._tiket_jenis_tak_dikenal(db)] \
            == ["TRX-UJI-TDK-03"]

    # Tiket dibatalkan di Pos Timbang → hilang dari antrean, bukan menetap.
    async with pg() as db:
        await db.execute(text("UPDATE timbangan_transaksi SET status_transaksi = 'DIBATALKAN' "
                              "WHERE id = :i"), {"i": tid})
        await db.commit()

    async with pg() as db:
        assert await meja_api._tiket_jenis_tak_dikenal(db) == []
