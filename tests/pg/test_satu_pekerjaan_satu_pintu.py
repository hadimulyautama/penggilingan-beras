"""Satu pekerjaan, satu pintu — katalog tak boleh menawarkan yang sudah berkartu.

Aturannya ditetapkan pemilik 21 September 2026: "Dua pintu untuk satu pekerjaan
membuat orang bertanya yang mana yang benar; dan katalog memang untuk yang tak
berwujud benda di gudang."

Ini KETIGA KALINYA aturan itu harus ditegakkan ulang — terakhir 28 September
2026, ketika QA mengukur 12 pekerjaan berpintu ganda: aturannya dipakai untuk
Gudang 1 dan kembarannya di Gudang 2 tak pernah ikut. `mulai_giling`
disembunyikan, `mulai_penyosohan` tidak. Tak ada yang memutuskan itu — ia
menumpuk sendiri.

Maka pagar ini menguji PERILAKU, bukan teks sumber: kartunya BENAR-BENAR
dibangun lewat `berjalan.untuk()` di atas data uji, lalu aksi yang ditawarkan
kartu-kartu itu diadu dengan aksi yang digambar katalog.

⚠ JANGAN menggantinya dengan regex atas `pilihan=[...]` di sumber. QA sudah
mencobanya dan meleset: cabang `if/else` pada `pilihan=` membuat regex hanya
menangkap satu sisi, dan tiga aksi terlewat.
"""
from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def pabrik(pg, pemakai, pemasok):
    """Pabrik kecil yang MEMBUAT KARTU di ketiga layar.

    Data yang kosong membuat pagar ini lulus tanpa menguji apa pun: tak ada
    kartu berarti tak ada irisan. Jadi isinya sengaja melahirkan kartu di
    kedua gudang — lot PK yang sudah selesai di Gudang 1, dan silo berisi PK
    di Gudang 2.
    """
    from sqlalchemy import select

    from app.database import now_local
    from app.models import (MillingProcess, MillingProgressLog, PurchaseBatch,
                            Silo, User, Warehouse)
    from app.penggilingan.gudang2.models import PkPurchaseBatch
    from app.penggilingan.gudang2.service import masukkan_pk_luar
    from app.services.seed import seed_master

    await seed_master()
    async with pg() as db:
        g1 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 1%")))).scalars().first()
        if g1 is None:
            g1 = Warehouse(nama_gudang="Gudang 1 - Selepan")
            db.add(g1)
        g2 = (await db.execute(select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 2%")))).scalars().first()
        if g2 is None:
            g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
            db.add(g2)
        await db.flush()
        silo_g1 = Silo(nama_silo="Silo Selepan", warehouse_id=g1.id)
        db.add(silo_g1)
        for huruf in ("A", "B"):
            db.add(Silo(nama_silo=f"Silo {huruf}", warehouse_id=g2.id,
                        status="kosong"))
        op1 = await db.get(User, pemakai.id)
        op1.default_warehouse_id = g1.id
        op2 = User(nama="Operator Polesan", role="operator", status="aktif",
                   default_warehouse_id=g2.id)
        admin = User(nama="Admin Uji", role="admin", status="aktif")
        db.add_all([op2, admin])
        await db.flush()
        b = PurchaseBatch(kode_batch="GB-PINTU-01", supplier_id=pemasok.id,
                          berat_total_kg=10_000, kondisi_gabah="kering",
                          tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
                          input_by=op1.id, flag_unverified=False,
                          sumber_berat="timbangan")
        db.add(b)
        await db.flush()
        proc = MillingProcess(kode_proses="LOT-PINTU-01", status="selesai",
                              silo_id=silo_g1.id, berat_gabah_masuk_kg=10_000,
                              waktu_mulai=now_local(), waktu_selesai=now_local(),
                              created_by=op1.id, purchase_batch_id=b.id)
        db.add(proc)
        await db.flush()
        db.add(MillingProgressLog(milling_process_id=proc.id,
                                  berat_kumulatif_kg=6_000,
                                  waktu_update=now_local(), input_by=op1.id))
        db.add(PkPurchaseBatch(
            kode_batch="PKB-PINTU-01", supplier_id=pemasok.id,
            berat_total_kg=8_000, tanggal_pembelian=date.today(),
            waktu_pembelian=now_local(), input_by=op2.id,
            status_batch="diterima", flag_unverified=True, sumber_berat="manual"))
        await db.commit()
        await db.refresh(op2)
        await masukkan_pk_luar(db, user=op2, kode="PKB-PINTU-01", tujuan="silo_a")
        return {"op1": op1.id, "op2": op2.id, "admin": admin.id,
                "lot": "LOT-PINTU-01"}


def _aksi_kartu(b) -> set[str]:
    """Aksi yang ditawarkan kartu-kartu sebuah `Berjalan` — dari SEMUA daftarnya."""
    keluar: set[str] = set()
    for daftar in (b.menunggu, b.berjalan, b.transit, b.meja):
        for baris in daftar:
            if getattr(baris, "aksi", None):
                keluar.add(baris.aksi)
            for p in getattr(baris, "pilihan", None) or []:
                if p and p[0]:
                    keluar.add(p[0])
    return keluar


async def _katalog(user) -> set[str]:
    """Aksi yang DIGAMBAR katalog untuk orang ini — `kartu` bukan True."""
    from app.web.api import actions_menu

    return {a["id"] for a in await actions_menu(user=user) if not a.get("kartu")}


async def test_katalog_tak_menawarkan_yang_sudah_berkartu(pg, pabrik):
    """Himpunan yang digambar katalog dan himpunan yang ditawarkan kartu tidak
    boleh beririsan — untuk TIAP peran, atas data yang benar-benar ada."""
    from app.models import User
    from app.services.berjalan import untuk

    for peran in ("admin", "op1", "op2"):
        async with pg() as db:
            u = await db.get(User, pabrik[peran])
            b = await untuk(db, u)
            kartu = _aksi_kartu(b)
            katalog = await _katalog(u)
        tumpang = kartu & katalog
        assert not tumpang, (
            f"{peran}: aksi ini punya DUA pintu — kartu dan katalog: "
            + ", ".join(sorted(tumpang)))


async def test_yang_tak_berkartu_tetap_punya_pintunya(pg, pabrik):
    """Sisi lain, dan ia wajib ada: "buang yang berkartu" mudah dikerjakan
    dengan cara yang salah — menandai SEMUANYA berkartu, lalu katalognya kosong
    dan pekerjaan yang tak punya kartu hilang sama sekali."""
    from app.models import User

    async with pg() as db:
        u = await db.get(User, pabrik["admin"])
        katalog = await _katalog(u)
    # `harga_byproduct` dicoret 28 September 2026: aksinya DIHAPUS bersama
    # seluruh harga (keputusan pemilik), jadi ia tak lagi butuh pintu.
    #
    # Tiga aksi keluar — `kirim_bekatul`, `kirim_barang_jadi`, `jual_pk` —
    # dicoret hari yang sama dan sebabnya BERBEDA: bukan kehilangan alasan,
    # melainkan diganti. Barang keluar kini berperintah, dan ketiganya adalah
    # pintu belakang yang membuat rantai itu sukarela. Penggantinya yang kini
    # wajib berpintu — ia belum berkartu, jadi katalog memang satu-satunya
    # jalannya.
    for wajib in ("catat_bekatul", "beli_kemasan",
                  "transfer_pk", "rekonsiliasi_timbang",
                  "perintah_keluar", "tambah_barang_keluar",
                  "batal_perintah_keluar", "verifikasi_keluar"):
        assert wajib in katalog, f"{wajib} kehilangan satu-satunya pintunya"


async def test_kedua_belas_yang_dicabut_tetap_terkirim_di_menu(pg, pabrik):
    """Ditandai berkartu BUKAN dibuang: lembar yang dibuka dari kartu dibangun
    dari spesifikasi yang sama. Aksi yang hilang dari menu berarti kartunya
    membuka lembar kosong."""
    from app.models import User
    from app.web.api import actions_menu

    async with pg() as db:
        u = await db.get(User, pabrik["admin"])
        menu = {a["id"]: a for a in await actions_menu(user=u)}
    for aksi in ("mulai_penyosohan", "hasil_penyosohan", "hentikan_penyosohan",
                 "lanjutkan_penyosohan", "selesai_penyosohan",
                 "pindah_tumpukan_silo", "catat_packing", "masukkan_pk",
                 # `harga_pk_luar` dicoret 28 September 2026 — DIHAPUS, jadi
                 # tak perlu lagi disembunyikan dari katalog.
                 "catat_pk_luar", "qc_pk_luar",
                 "betulkan_bobot_giling"):
        assert aksi in menu, f"{aksi} hilang dari menu — kartunya jadi buntu"
        assert menu[aksi]["kartu"] is True, f"{aksi} masih digambar di katalog"
