"""Pil penyaring gudang di layar Sedang berjalan — Pos Produksi.

Celah ke-4 menjelang app meja & gudang2 dihapus: Meja bisa menyaring per gudang,
Pos Produksi tidak. Bagi pemegang KEDUA gudang itu bukan kenyamanan — daftarnya
memuat mesin dua gudang bercampur, dan pertanyaan yang dibawa orang ke layar ini
hampir selalu tentang satu gudang.

Yang dijaga: penyaringnya benar-benar MENYARING (bukan cuma tergambar), ia
membaca gudang yang dicap penyusun kartunya sendiri, dan ia TIDAK ditawarkan
kepada operator — pil tunggal bernama "Semua" tak membedakan apa pun.
"""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def pabrik(pg):
    """Satu kartu dari MASING-MASING gudang, dan itu syarat mutlak uji ini.

    Penyaring hanya bisa dibuktikan menyaring kalau ada yang tersisa DAN ada
    yang hilang. Dengan kartu satu gudang saja, "?gudang=g1 tak memuat kartu
    G2" juga benar untuk penyaring yang mengosongkan layar apa pun — dan
    itulah bentuk kegagalan yang paling mudah lolos.

    G1: satu lot yang sudah selesai didinginkan tetapi belum masuk silo — kartu
    TRANSIT (`_lot(pendinginan_selesai=True)`). G2: satu penyosohan berjalan.
    """
    from datetime import date

    from app.database import now_local
    from app.models import Dryer, Silo, Supplier, User, Warehouse
    from app.penggilingan.gudang2.models import PkPurchaseBatch
    from app.penggilingan.gudang2.polishing import mulai_penyosohan
    from app.penggilingan.gudang2.service import masukkan_pk_luar, pindah_tumpukan_ke_silo

    async with pg() as db:
        g1 = Warehouse(nama_gudang="Gudang 1 - Selepan", kode_fungsi="g1")
        g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan", kode_fungsi="g2")
        db.add_all([g1, g2])
        await db.flush()
        db.add_all([Dryer(nama="Dryer 1", warehouse_id=g1.id, kapasitas_kg=20000),
                    Silo(nama_silo="Silo A", warehouse_id=g2.id),
                    Silo(nama_silo="Silo B", warehouse_id=g2.id)])
        u = User(nama="Operator Polesan", role="operator", status="aktif",
                 default_warehouse_id=g2.id)
        s = Supplier(nama_supplier="UD Sumber Rejeki")
        db.add_all([u, s])
        await db.flush()
        db.add(PkPurchaseBatch(
            kode_batch="PKB-UJI-01", supplier_id=s.id, berat_total_kg=9800,
            tanggal_pembelian=date.today(), waktu_pembelian=now_local(), input_by=u.id,
            status_batch="diterima", flag_unverified=True, sumber_berat="manual"))
        await db.commit()
        await db.refresh(u)
        r1 = await masukkan_pk_luar(db, user=u, kode="PKB-UJI-01", tujuan="ditumpuk")
        await pindah_tumpukan_ke_silo(db, user=u, intake_id=r1.intake.id,
                                      nama_silo="A", berat=9800)
        r = await mulai_penyosohan(db, user=u, nama_silos=["A"])

    # Kartu Gudang 1: lot yang sudah dingin, dryer-nya perlu dikosongkan.
    async with pg() as db:
        from app.penggilingan.gudang1.models.gudang1 import DryingLot
        from sqlalchemy import select as sel

        dryer = (await db.execute(sel(Dryer))).scalars().first()
        lot = DryingLot(kode_lot="LOT-UJI-G1", dryer_id=dryer.id, status="selesai",
                        waktu_mulai_pengeringan=now_local(),
                        waktu_selesai_pengeringan=now_local(),
                        waktu_mulai_pendinginan=now_local(),
                        waktu_selesai_pendinginan=now_local(),
                        created_by=u.id)
        db.add(lot)
        await db.commit()

    return {"g1": g1.id, "g2": g2.id, "kode_sosoh": r.proc.kode_proses,
            "kode_lot": "LOT-UJI-G1"}


async def _klien(pg, *, role: str, gudang_id: int | None = None) -> httpx.AsyncClient:
    from app.main import app
    from app.models import ProduksiAkun, User
    from app.web import csrf, security
    from hmu_identitas import sandi as S
    from hmu_identitas.model import mode_bawaan

    async with pg() as db:
        u = User(nama=f"Uji {role}", role=role, status="aktif",
                 default_warehouse_id=gudang_id)
        db.add(u)
        await db.flush()
        a = ProduksiAkun(user_id=u.id, username=f"uji{u.id}",
                         password_hash=S.hash_sandi("rahasia123"), status="aktif",
                         mode_perangkat=mode_bawaan(role))
        db.add(a)
        await db.commit()
        token = security.buat_token(a)
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://uji")
    c.cookies.set(security.NAMA_COOKIE, token)
    c.cookies.set(csrf.NAMA_COOKIE, csrf.terbitkan_baru())
    return c


async def test_pil_tergambar_dan_menyaring_untuk_super(pg, pabrik):
    kode = pabrik["kode_sosoh"]
    c = await _klien(pg, role="superadmin")
    async with c:
        lot = pabrik["kode_lot"]
        semua = (await c.get("/berjalan")).text
        assert "Gudang 1" in semua and "Gudang 2" in semua      # pilnya ada
        assert kode in semua and lot in semua                  # kedua gudang

        hanya_g2 = (await c.get("/berjalan?gudang=g2")).text
        assert kode in hanya_g2 and lot not in hanya_g2
        hanya_g1 = (await c.get("/berjalan?gudang=g1")).text
        assert lot in hanya_g1, "penyaring mengosongkan layar, bukan menyaring"
        assert kode not in hanya_g1, "penyaring tergambar tapi tak menyaring"
        # Pil yang sedang menyala menyebut dirinya — tanpa itu orang tak tahu
        # daftarnya sedang disaring, lalu menyimpulkan gudangnya kosong.
        assert "pil--on" in hanya_g1


async def test_operator_tak_ditawari_penyaring(pg, pabrik):
    """Ia sudah diberi satu gudang lewat view-nya."""
    c = await _klien(pg, role="operator", gudang_id=pabrik["g2"])
    async with c:
        t = (await c.get("/berjalan")).text
    assert "pil-baris" not in t
    # Dan kartunya tetap ada — yang hilang penyaringnya, bukan isinya.
    assert pabrik["kode_sosoh"] in t


async def test_gudang_karangan_dari_url_diabaikan(pg, pabrik):
    """Alamat diketik orang. `?gudang=g9` harus jatuh kembali ke "Semua",
    bukan mengosongkan layar — layar kosong terbaca sebagai pabrik yang
    berhenti, dan itu kalimat yang paling mahal untuk salah."""
    c = await _klien(pg, role="superadmin")
    async with c:
        t = (await c.get("/berjalan?gudang=g9")).text
    assert pabrik["kode_sosoh"] in t


async def test_kartu_dicap_gudang_oleh_penyusunnya(pg, pabrik):
    """Penyaring membaca `Baris.gudang`, dan kartu yang lupa dicap akan hilang
    dari kedua pil tanpa satu tanda pun."""
    from app.services import berjalan as svc

    async with pg() as db:
        g2 = await svc.untuk_gudang2(db)
    semua = g2.menunggu + g2.berjalan + g2.transit + g2.meja
    assert semua, "tak ada kartu untuk diperiksa — semaian uji ini yang salah"
    assert all(b.gudang == "g2" for b in semua), \
        [b.kode for b in semua if b.gudang != "g2"]
