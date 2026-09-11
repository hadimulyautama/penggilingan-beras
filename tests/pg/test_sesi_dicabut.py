"""Sesi yang beredar benar-benar bisa ditarik kembali.

Temuan QA P-S-05 & X-11, 11 September 2026. Diuji dengan basis data sungguhan
karena yang dijaga adalah apa yang dilihat `akun_opsional` SESUDAH sebuah baris
berubah — bukan bentuk tokennya, yang sudah diuji terpisah.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class PermintaanPalsu:
    """Request seadanya: `akun_opsional` hanya membaca cookie dan `state`."""

    class _State:
        pass

    def __init__(self, token: str):
        self.cookies = {"produksi_sesi": token}
        self.state = self._State()


async def _akun_uji(pg, *, peran: str = "operator"):
    from app.models import ProduksiAkun, User
    from app.web.security import hash_sandi

    async with pg() as db:
        orang = User(nama="Budi Uji", role=peran, status="aktif")
        db.add(orang)
        await db.flush()
        akun = ProduksiAkun(
            user_id=orang.id, username="budi", password_hash=hash_sandi("rahasia123"),
            mode_perangkat="pribadi", status="aktif",
        )
        db.add(akun)
        await db.commit()
        await db.refresh(akun)
        return akun.id


async def _masih_masuk(token: str) -> bool:
    from app.web.security import akun_opsional

    return await akun_opsional(PermintaanPalsu(token)) is not None


async def _token(pg, akun_id: int) -> str:
    from app.models import ProduksiAkun
    from app.web.security import buat_token

    async with pg() as db:
        return buat_token(await db.get(ProduksiAkun, akun_id))


async def test_sesi_tetap_hidup_selama_tak_ada_yang_berubah(pg):
    """Pagar ini tak boleh memutus orang yang sedang bekerja."""
    aid = await _akun_uji(pg)
    assert await _masih_masuk(await _token(pg, aid)) is True


async def test_keluar_dari_semua_perangkat_memutus_token_lama(pg):
    """Inilah yang dicari orang saat HP-nya hilang. Sampai 11 September 2026
    jalannya tidak ada: "Keluar" hanya menghapus cookie di perangkat yang
    menekannya, dan yang hilang tetap masuk sampai 30 hari."""
    from app.web.auth import naikkan_versi_token

    aid = await _akun_uji(pg)
    token_hp_hilang = await _token(pg, aid)
    assert await _masih_masuk(token_hp_hilang) is True

    await naikkan_versi_token(aid, sebab="uji")
    assert await _masih_masuk(token_hp_hilang) is False
    # Perangkat yang masih di tangan tetap bisa masuk lagi dengan token baru.
    assert await _masih_masuk(await _token(pg, aid)) is True


async def test_dinonaktifkan_di_master_langsung_terputus(pg):
    """`users.status` adalah saklar yang dibaca ketiga aplikasi. Sampai
    sekarang produksi tak pernah melihatnya sama sekali. Temuan QA X-11."""
    from app.models import ProduksiAkun

    aid = await _akun_uji(pg)
    token = await _token(pg, aid)
    async with pg() as db:
        akun = await db.get(ProduksiAkun, aid)
        akun.user.status = "nonaktif"
        await db.commit()

    assert await _masih_masuk(token) is False


async def test_akun_produksi_nonaktif_juga_terputus(pg):
    from app.models import ProduksiAkun

    aid = await _akun_uji(pg)
    token = await _token(pg, aid)
    async with pg() as db:
        akun = await db.get(ProduksiAkun, aid)
        akun.status = "nonaktif"
        await db.commit()

    assert await _masih_masuk(token) is False


async def test_ganti_sandi_memutus_sesi_lama(pg):
    """Sandi yang sudah dicuri tak boleh tetap berguna sesudah diganti — yang
    justru alasan orangnya menggantinya."""
    from app.models import ProduksiAkun
    from app.web.security import hash_sandi

    aid = await _akun_uji(pg)
    token_lama = await _token(pg, aid)
    async with pg() as db:
        akun = await db.get(ProduksiAkun, aid)
        akun.password_hash = hash_sandi("sandibaru123")
        akun.token_version = (akun.token_version or 1) + 1
        await db.commit()

    assert await _masih_masuk(token_lama) is False
