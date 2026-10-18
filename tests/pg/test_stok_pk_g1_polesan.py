"""PK Gudang 1 terlihat oleh operator Gudang 2 — di layar Stok, dan hanya di sana.

Keputusan pemilik 24 September 2026. PK yang sudah jadi di Gudang 1 adalah BAHAN
BAKU operator polesan: yang memutuskan "hari ini menyosoh apa" perlu tahu ada KS
atau KL berapa di sebelah, mutunya bagaimana, dan dari gabah siapa. Selama ia tak
bisa melihatnya, satu-satunya cara mengetahuinya adalah bertanya lewat telepon —
dan yang ditanya lewat telepon tak pernah tercatat.

Yang dijaga berkas ini justru sisi SEBALIKNYA, sebab di situlah kerusakan yang
tak kelihatan: membuka satu blok tak boleh ikut membuka gudang orang lain.
Silo & dryer Gudang 1, stok karung Gudang 1, dan halaman `/gudang/g1` tetap
tertutup. Melihat bahan bukan memegang gudangnya.

Dan totalnya tak boleh menyatu: operator yang mengira barang ini sudah ada di
gudangnya akan menghitung stok yang tak ia pegang.
"""
from __future__ import annotations

from datetime import date

import httpx
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def pabrik(pg):
    """Satu lot giling SELESAI yang PK-nya masih utuh di Gudang 1, satu silo
    Gudang 1 yang berisi (yang TAK boleh terlihat), dan stok karung kedua
    gudang."""
    from app.database import now_local
    from app.models import (MillingProcess, MillingProgressLog, PurchaseBatch, Silo,
                            Supplier, User, Warehouse)
    from app.services.seed import seed_master

    # Master kemasan (bahan & ukuran karung) lahir dari penyemai yang sama
    # dengan produksi — uji stok karung di bawah memerlukannya.
    await seed_master()
    async with pg() as db:
        from sqlalchemy import select as _select

        g1 = (await db.execute(_select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 1%")))).scalars().first()
        g2 = (await db.execute(_select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 2%")))).scalars().first()
        if g1 is None:
            g1 = Warehouse(nama_gudang="Gudang 1 - Selepan", kode_fungsi="g1")
            db.add(g1)
        if g2 is None:
            g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan", kode_fungsi="g2")
            db.add(g2)
        await db.flush()
        silo_g1 = Silo(nama_silo="Silo Selepan Rahasia", warehouse_id=g1.id)
        db.add(silo_g1)
        for nama in ("Silo A", "Silo B"):
            ada = (await db.execute(_select(Silo).where(
                Silo.nama_silo == nama, Silo.warehouse_id == g2.id))).scalars().first()
            if ada is None:
                db.add(Silo(nama_silo=nama, warehouse_id=g2.id))
        u1 = User(nama="Operator Selepan", role="operator", status="aktif",
                  default_warehouse_id=g1.id)
        u2 = User(nama="Operator Polesan", role="operator", status="aktif",
                  default_warehouse_id=g2.id)
        s = Supplier(nama_supplier="Pak Tani Sumber")
        db.add_all([u1, u2, s])
        await db.flush()

        # Gabah → lot giling selesai, hasilnya dicatat operator: inilah PK yang
        # harus terlihat, berikut asal gabahnya.
        b = PurchaseBatch(kode_batch="GB-BAHAN-01", supplier_id=s.id,
                          berat_total_kg=10_000, kondisi_gabah="kering",
                          tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
                          input_by=u1.id, flag_unverified=False, sumber_berat="manual")
        db.add(b)
        await db.flush()
        p = MillingProcess(kode_proses="LOT-BAHAN-01", status="selesai",
                           silo_id=silo_g1.id, berat_gabah_masuk_kg=10_000,
                           waktu_mulai=now_local(), waktu_selesai=now_local(),
                           created_by=u1.id, purchase_batch_id=b.id)
        db.add(p)
        await db.flush()
        db.add(MillingProgressLog(milling_process_id=p.id, berat_kumulatif_kg=6_500,
                                  waktu_update=now_local(), input_by=u1.id))
        await db.commit()
        return {"g1": g1.id, "g2": g2.id, "u1": u1.id, "u2": u2.id}


async def _klien(pg, *, gudang_id: int | None = None, role: str = "operator") -> httpx.AsyncClient:
    from app.main import app
    from app.models import ProduksiAkun, User
    from app.web import csrf, security
    from hmu_identitas import sandi as S
    from hmu_identitas.model import mode_bawaan

    async with pg() as db:
        u = User(nama=f"Uji {role} {gudang_id}", role=role, status="aktif",
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


async def test_operator_polesan_melihat_pk_gudang1(pg, pabrik):
    c = await _klien(pg, gudang_id=pabrik["g2"])
    async with c:
        r = await c.get("/stok")
        assert r.status_code == 200
        t = r.text
        assert "PK · Gudang 1" in t, "blok bahan tak digambar"
        assert "LOT-BAHAN-01" in t
        # Daftar ringkas menuju detail; asal gabah harus tetap dapat dibaca
        # melalui tautan lot yang ditawarkan kepada operator.
        import re
        from html import unescape
        href = next(unescape(h) for h in re.findall(r'href="([^"]+)"', t)
                    if h.startswith("/stok/pk/detail?") and "LOT-BAHAN-01" in h)
        detail = await c.get(href)
        assert detail.status_code == 200
        t = detail.text

    assert "LOT-BAHAN-01" in t
    # Yang dibaca orang saat memutuskan apa yang disosoh hari ini: berapa,
    # kelasnya apa, dan dari gabah siapa.
    assert "6.500" in t, "jumlah PK-nya tak terbaca"
    assert "Pak Tani Sumber" in t, "asal gabahnya tak terbaca"


async def test_membuka_pk_tak_ikut_membuka_gudang_sebelah(pg, pabrik):
    """Inilah sisi yang rusaknya tak kelihatan. Melihat bahan bukan memegang
    gudangnya."""
    c = await _klien(pg, gudang_id=pabrik["g2"])
    async with c:
        t = (await c.get("/stok")).text
        g1 = await c.get("/gudang/g1")

    assert "Silo Selepan Rahasia" not in t, "silo Gudang 1 ikut terbuka"
    assert g1.status_code == 403, "halaman gudang sebelah ikut terbuka"


async def test_stok_karung_gudang1_tetap_tertutup(pg, pabrik):
    """Gerbang stok karung berdiri SENDIRI, dan tetap tertutup.

    Karung PK disimpan di Gudang 1 (`packaging.kemasan_gudang`) dan yang
    memesannya Admin. Membuka blok PK tak boleh ikut membukanya — dua gerbang,
    dua pertanyaan berbeda. Diuji dengan baris karung PK yang BENAR-BENAR ada:
    gerbang yang diuji tanpa data membuktikan nol.

    `_karung()` PINDAH jadi bagian `layar_produk.halaman_stok_karung` (7
    Oktober 2026, karung dapat halamannya sendiri) — diuji lewat HTTP
    sekarang, bukan memanggil fungsinya langsung."""
    from datetime import date as _date

    from sqlalchemy import select

    from app.database import now_local
    from app.models import User
    from app.penggilingan.inventory.models import (PackageSize, PackagingMaterial,
                                                   PackagingPurchase)

    async with pg() as db:
        mat = (await db.execute(select(PackagingMaterial).where(
            PackagingMaterial.kode == "karung_pk"))).scalars().first()
        uk = (await db.execute(select(PackageSize))).scalars().first()
        assert mat is not None and uk is not None, "master kemasan belum tersemai"
        db.add(PackagingPurchase(kode="PKP-UJI-01", packaging_material_id=mat.id,
                                 package_size_id=uk.id, jumlah_lembar=500,
                                 tanggal=_date.today(), waktu=now_local(),
                                 input_by=pabrik["u1"]))
        await db.commit()

    c_super = await _klien(pg, role="superadmin")
    async with c_super:
        super_ = (await c_super.get("/stok-karung")).text
    assert "Karung PK" in super_, "premis: karung G1 memang ada"

    c_polesan = await _klien(pg, gudang_id=pabrik["g2"])
    async with c_polesan:
        polesan = (await c_polesan.get("/stok-karung")).text
    assert "Karung PK" not in polesan, \
        "stok karung Gudang 1 ikut terbuka untuk operator polesan"


async def test_totalnya_tidak_menyatu_dengan_stok_gudang_dua(pg, pabrik):
    """Dua blok, dua judul, dua total. Operator yang mengira barang ini sudah
    ada di gudangnya akan menghitung stok yang tak ia pegang.

    Blok Gudang 2 kini cuma tampil bila Tumpukan benar-benar berisi (silo
    dikeluarkan dari kartu Stok sejak 4 Oktober 2026) — jadi uji ini butuh
    satu pemasukan tumpukan sungguhan, bukan sekadar silo master yang kosong."""
    from app.models import User
    from app.penggilingan.gudang2.service import _add_intake

    async with pg() as db:
        u2 = await db.get(User, pabrik["u2"])
        await _add_intake(db, user=u2, sumber_tipe="beli_luar", tujuan="ditumpuk",
                          berat_kg=2_000, hpp_per_kg=None, tanggal=None, jam=None)

    c = await _klien(pg, gudang_id=pabrik["g2"])
    async with c:
        t = (await c.get("/stok")).text

    # Ringkasan gabungan di desktop tetap mempunyai blok per gudang pada
    # ponsel: jangan menyatukan asal dan jumlah fisik di dua tempat.
    assert t.count("PK · Gudang 1") == 1 and t.count("PK · Gudang 2") == 1
    assert "6.500 kg" in t and "2.000 kg" in t


async def test_operator_selepan_tak_berubah(pg, pabrik):
    """Yang sudah benar tak boleh ikut bergeser: operator selepan tetap melihat
    gudangnya sendiri, dan TIDAK melihat silo Gudang 2."""
    c = await _klien(pg, gudang_id=pabrik["g1"])
    async with c:
        t = (await c.get("/stok")).text

    assert "PK · Gudang 1" in t and "LOT-BAHAN-01" in t
    assert "PK · Gudang 2" not in t, "operator selepan ikut melihat Gudang 2"
    assert "Silo A" not in t


async def test_lot_yang_habis_tak_tampil(pg, pabrik):
    """Daftar yang memuat lot kosong menyuruh orang memilih bahan yang tak ada."""
    from sqlalchemy import select

    from app.database import now_local
    from app.models import InternalTransfer, MillingProcess, User

    async with pg() as db:
        p = (await db.execute(select(MillingProcess).where(
            MillingProcess.kode_proses == "LOT-BAHAN-01"))).scalars().one()
        u = await db.get(User, pabrik["u1"])
        db.add(InternalTransfer(kode_transfer="TRF-HABIS-01", milling_process_id=p.id,
                                berat_kg=6_500, status="terkirim", lokasi_tujuan="silo_a",
                                waktu=now_local(), created_by=u.id))
        await db.commit()

    c = await _klien(pg, gudang_id=pabrik["g2"])
    async with c:
        t = (await c.get("/stok")).text
    assert "LOT-BAHAN-01" not in t, "lot yang sudah habis terkirim masih ditawarkan"
