"""Mode Uji: mengosongkan pabrik, di basis data SUNGGUHAN.

Berkas ini ada karena satu kegagalan yang tak mungkin tertangkap di tempat
lain. Uji `tests/test_mode_uji.py` memakai sesi PALSU — ia mencatat SQL yang
disusun, tidak menjalankannya — dan itu memang yang dibutuhkan untuk
membuktikan URUTAN (penjaga sebelum penghapusan). Tetapi sesi yang tak pernah
menjalankan apa pun juga tak pernah ditolak apa pun.

Yang menolak: `peristiwa` dijaga pemicu "tambah-saja" (migrasi 0047) yang
menolak UPDATE dan DELETE. Sejak buku peristiwa lahir 13 September 2026,
tombol "Hapus data uji" berhenti bekerja di basis data mana pun yang sudah
punya satu peristiwa — Internal Server Error di tengah jalan, dan yang
membacanya mengira sistemnya rusak. Dilaporkan pemilik 25 September 2026.

Jadi yang diuji di sini bukan urutannya lagi, melainkan: apakah ia BENAR-BENAR
BISA menghapus — dan apakah pagarnya kembali berdiri sesudahnya.
"""
from __future__ import annotations

from datetime import date

import pytest

pytestmark = pytest.mark.asyncio


async def _peristiwa(pg, kunci: str) -> None:
    """Satu baris di buku besar — inilah yang dulu menghentikan penghapusan."""
    from sqlalchemy import text

    async with pg() as db:
        await db.execute(text("""
            INSERT INTO peristiwa (jenis, waktu, kunci_kiriman, muatan)
            VALUES ('gabah_masuk', now(), :k, '{}'::jsonb)
        """), {"k": kunci})
        await db.commit()


async def test_penghapusan_jalan_walau_ada_buku_peristiwa(pg, pemakai, pemasok):
    """Yang dulu gagal: DELETE pada `peristiwa` ditolak pemicunya."""
    from sqlalchemy import text

    from app.database import now_local
    from app.models import PurchaseBatch, User
    from app.web import mode_uji

    await _peristiwa(pg, "uji-hapus-01")
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        db.add(PurchaseBatch(
            kode_batch="GB-HAPUS-01", supplier_id=pemasok.id, berat_total_kg=1_000,
            kondisi_gabah="kering", tanggal_pembelian=date.today(),
            waktu_pembelian=now_local(), input_by=u.id, flag_unverified=False,
            sumber_berat="manual"))
        await db.commit()

    pesan = await mode_uji._kosongkan()
    assert pesan is None, pesan

    async with pg() as db:
        for tabel in ("peristiwa", "purchase_batches"):
            n = (await db.execute(text(f"select count(*) from {tabel}"))).scalar()
            assert n == 0, f"{tabel} masih berisi {n} baris"


async def test_pemicu_tambah_saja_berdiri_lagi_sesudahnya(pg, pemakai):
    """Pagar yang dipadamkan untuk satu pekerjaan harus menyala lagi sesudah
    pekerjaan itu — kalau tidak, buku besar berhenti jadi buku besar, dan tak
    ada satu layar pun yang akan menyebutkan itu."""
    from sqlalchemy import text

    from app.web import mode_uji

    await _peristiwa(pg, "uji-hapus-02")
    assert await mode_uji._kosongkan() is None

    async with pg() as db:
        aktif = (await db.execute(text("""
            SELECT t.tgenabled FROM pg_trigger t
              JOIN pg_class c ON c.oid = t.tgrelid
             WHERE NOT t.tgisinternal AND c.relname = 'peristiwa'
        """))).scalars().all()
    # 'O' = menyala (origin). 'D' = padam — itu yang tak boleh tertinggal.
    # Datang sebagai satu byte ("char" di Postgres), bukan teks.
    nyala = [x.decode() if isinstance(x, bytes) else x for x in aktif]
    assert nyala and all(x == "O" for x in nyala), f"pemicu tertinggal padam: {nyala}"

    # Dan ia sungguh MENOLAK lagi, bukan sekadar tercatat menyala.
    await _peristiwa(pg, "uji-hapus-03")
    async with pg() as db:
        with pytest.raises(Exception) as e:
            await db.execute(text("DELETE FROM peristiwa"))
            await db.commit()
    assert "hanya bertambah" in str(e.value)


async def test_tiket_timbang_tidak_ikut_terhapus(pg, pemakai):
    """Yang dijanjikan layarnya, dibuktikan di basis data sungguhan: baris
    milik Timbangan bertahan, dan tautannya yang dilepas."""
    from sqlalchemy import text

    from app.web import mode_uji

    async with pg() as db:
        await db.execute(text("""
            INSERT INTO timbangan_transaksi (kode, tanggal, arah, jenis_kode,
                cara_timbang, timbang1_kg, status_tiket, status_transaksi,
                created_at, updated_at)
            VALUES ('MSK-2026-0001', current_date, 'masuk', 'GABAH_KERING',
                    'dua_kali', 7500, 'SELESAI', 'SELESAI', now(), now())
        """))
        await db.commit()

    assert await mode_uji._kosongkan() is None

    async with pg() as db:
        n = (await db.execute(text("select count(*) from timbangan_transaksi"))).scalar()
    assert n == 1, "tiket timbang ikut terhapus"
