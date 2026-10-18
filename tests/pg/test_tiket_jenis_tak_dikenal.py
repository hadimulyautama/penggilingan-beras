"""Tiket yang ditimbang tetapi jenisnya belum dipetakan produksi tetap TERLIHAT.

Ditemukan pemilik 23 September 2026 dengan cara terburuk: PK sudah ditimbang,
barangnya di halaman, dan tak ada satu layar pun yang menyebutnya. Sebabnya dua
penyaring yang masing-masing benar tetapi bersama meninggalkan lubang:

  · `berjalan._tiket_belum_ditaut` hanya memancarkan `model == "gabah"`
    ("PK & lainnya punya alurnya sendiri");
  · `berjalan._tiket_pk_luar` hanya memancarkan `is_pk`.

Jenis yang TIDAK dipetakan sama sekali tak diambil siapa pun. Hanya laporan
Rekonsiliasi menyebutnya — dan laporan dibuka orang sesudah ia curiga.

Dan lubangnya bukan sementara: `JENIS_UJI_ASING` & `BROKEN_MASUK` memang belum
dipetakan (keputusan pemiliknya sudah ada sejak 24 Sep 2026 — pembelian,
tanpa antrean giling — tapi jalurnya belum dibangun), dan taksonomi jenis di Pos
Timbang berbasis DATA, jadi jenis baru bisa lahir di sana tanpa produksi tahu.

Kedua pemancar PINDAH dari `web/meja_api.py` ke `services/berjalan.py` pada 24
September 2026: yang di meja_api hanya dipanggil app Meja, jadi Pos Produksi
tetap bisu — dan tangkapan layar pemilik semuanya Pos Produksi. Uji di berkas ini
ikut pindah ke sumbernya; yang menjaga sisi Pos Produksi ada di
`test_tiket_antrean_produksi.py`. (App Meja sendiri dihapus hari itu juga,
beberapa jam kemudian — keputusan pemilik.)
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
        g1 = Warehouse(nama_gudang="Gudang 1 - Selepan", kode_fungsi="g1")
        g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan", kode_fungsi="g2")
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
    from app.services import berjalan as svc

    async with pg() as db:
        await _tiket(db, "TRX-UJI-TDK-01", "JENIS_UJI_ASING")     # belum dipetakan
        await _tiket(db, "TRX-UJI-PK-01", "BERAS_PK")         # dipetakan → jalur PK
        await _tiket(db, "TRX-UJI-GB-01", "GABAH_KERING")     # dipetakan → jalur gabah
        await db.commit()

    async with pg() as db:
        tak_dikenal = await svc._tiket_jenis_tak_dikenal(db)
        pk = await svc._tiket_pk_luar(db, boleh_catat=True)

    # Hanya yang TAK dipetakan, dan tepat satu.
    assert [k.kode for k in tak_dikenal] == ["TRX-UJI-TDK-01"]
    # Jalur PK tak berubah: ia tetap mengambil PK-nya, bukan yang ini.
    assert [k.kode for k in pk] == ["TRX-UJI-PK-01"]

    kartu = tak_dikenal[0]
    # ── DIAM: tak ada yang bisa ditekan ──
    # `_benda.html` memilih <details> bila `tombol`, <a href=?buka=> bila
    # `aksi`, dan kartu diam bila keduanya kosong. Borang mana pun akan
    # menolak jenis yang tak dikenalnya, dan kartu yang menjanjikan lalu
    # menolak lebih buruk daripada kartu yang diam.
    assert not kartu.aksi and kartu.tombol == [] and kartu.pilihan == []
    # ── Tetapi ia MENJELASKAN dirinya ──
    assert "JENIS_UJI_ASING" in kartu.keadaan and "belum dikenal" in kartu.keadaan
    assert ("Jenis timbang", "JENIS_UJI_ASING") in kartu.fakta
    # Bobot & pemasoknya terbaca — itu yang dipakai orang mengenali truk mana.
    assert kartu.judul == "UD Sumber Tani"
    assert kartu.utama and kartu.utama[1] == "kg"
    # Dan ia duduk di blok "Tiket timbang belum dicatat", bersama tiket PK.
    assert kartu.kelompok == "tiket"


async def test_ikut_antrean_dan_lencananya(pg, admin, pabrik):
    """Bukan cuma fungsinya benar — ia benar-benar sampai ke layar.

    Dulu lewat `meja_api._susun`, perakit daftar app Meja. App itu dihapus 24
    September 2026; yang merakit sekarang `berjalan.untuk()`, satu-satunya
    perakit yang tersisa — dan justru itu yang dipakai layar Pos Produksi,
    tempat tangkapan layar pemilik berasal.
    """
    from app.models import User
    from app.services.berjalan import untuk

    async with pg() as db:
        await _tiket(db, "TRX-UJI-TDK-02", "BROKEN_MASUK")
        await db.commit()

    async with pg() as db:
        b = await untuk(db, await db.get(User, admin.user_id))

    kode = [k.kode for k in b.menunggu]
    assert "TRX-UJI-TDK-02" in kode, "tiket tak dikenal tak sampai ke antrean"
    assert b.jumlah_menunggu == len(b.menunggu)
    assert b.jumlah_menunggu >= 1, "lencana tak menghitungnya"


async def test_tiket_yang_sudah_dicatat_keluar_dari_antrean(pg, admin):
    """Jaring ini tak boleh jadi daftar yang tak pernah habis: begitu tiketnya
    tertaut batch yang hidup, `tiket_masuk_aktif` berhenti menawarkannya —
    aturan yang sama dengan tiket gabah & PK, bukan aturan baru."""
    from app.services import berjalan as svc

    async with pg() as db:
        tid = await _tiket(db, "TRX-UJI-TDK-03", "JENIS_UJI_ASING")
        await db.commit()

    async with pg() as db:
        assert [k.kode for k in await svc._tiket_jenis_tak_dikenal(db)] \
            == ["TRX-UJI-TDK-03"]

    # Tiket dibatalkan di Pos Timbang → hilang dari antrean, bukan menetap.
    async with pg() as db:
        await db.execute(text("UPDATE timbangan_transaksi SET status_transaksi = 'DIBATALKAN' "
                              "WHERE id = :i"), {"i": tid})
        await db.commit()

    async with pg() as db:
        assert await svc._tiket_jenis_tak_dikenal(db) == []
