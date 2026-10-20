"""Papan Beranda dibuka lewat HTTP — yang digambar, bukan yang dihitung.

Uji sumbernya ada di `tests/test_papan_beranda.py`. Yang di sini membuktikan
halamannya benar-benar menyebutnya, dan — yang lebih penting — bahwa operator
TIDAK melihatnya: penyimpangan gudang sebelah adalah kabar yang tak bisa ia
tindaklanjuti, dan layar yang menawarkannya mengajari orang berhenti membaca
baris teratas.
"""
from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def pabrik(pg):
    """Dua gudang, dan SATU penyimpangan sungguhan: harga gabah yang menggantung
    lebih dari dua hari. Tanpa penyimpangan, blok "Perlu perhatian" tak digambar
    sama sekali — dan uji yang tak menyemainya membuktikan nol."""
    from app.database import now_local
    from app.models import PurchaseBatch, Silo, Supplier, User, Warehouse

    async with pg() as db:
        g1 = Warehouse(nama_gudang="Gudang 1 - Selepan", kode_fungsi="g1")
        g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan", kode_fungsi="g2")
        db.add_all([g1, g2])
        await db.flush()
        db.add_all([Silo(nama_silo="Silo A", warehouse_id=g2.id),
                    Silo(nama_silo="Silo B", warehouse_id=g2.id)])
        u = User(nama="Operator", role="operator", status="aktif", default_warehouse_id=g1.id)
        s = Supplier(nama_supplier="Pak Tani")
        db.add_all([u, s])
        await db.flush()
        lama = now_local() - timedelta(days=5)
        b = PurchaseBatch(kode_batch="GB-MENGGANTUNG-01", supplier_id=s.id,
                          berat_total_kg=8000, kondisi_gabah="kering", tanggal_pembelian=date.today(),
                          waktu_pembelian=now_local(), input_by=u.id, flag_unverified=True)
        db.add(b)
        await db.flush()
        # `created_at` diisi server; dipaksa ke masa lalu supaya syarat "lebih
        # dari dua hari" benar-benar terpenuhi, bukan diandaikan.
        from sqlalchemy import text

        await db.execute(text("UPDATE purchase_batches SET created_at = :t WHERE id = :i"),
                         {"t": lama, "i": b.id})
        await db.commit()
        return {"g1": g1.id, "g2": g2.id}


async def _klien(pg, *, role: str, gudang_id: int | None = None) -> httpx.AsyncClient:
    from app.main import app
    from app.models import ProduksiAkun, User
    from app.web import csrf, security
    from hmu_identitas import sandi as S
    from hmu_identitas.model import mode_bawaan

    async with pg() as db:
        u = User(nama=f"Uji {role}", role=role, status="aktif", default_warehouse_id=gudang_id)
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


async def test_admin_melihat_tiga_blok_papan(pg, pabrik):
    """QC dan keputusan tertagih sekali melalui pintu Pekerjaan."""
    import re
    async with await _klien(pg,role='superadmin') as c:
        t=(await c.get('/')).text
        daftar=(await c.get('/pekerjaan?jenis=qc')).text
    assert 'GB-MENGGANTUNG-01' not in t
    kartu=re.search(r'<a class="tindakan [^>]*href="/pekerjaan"[^>]*>(.*?)</a>',t,re.S)
    assert kartu and re.search(r'lencana[^>]*>\s*[1-9][0-9]*\s*<',kartu.group(1))
    assert 'href="/mutu"' not in t and 'href="/keputusan"' not in t
    assert 'buka=qc_' in daftar
    assert 'href="/gudang/g1"' in t and 'href="/gudang/g2"' in t


async def test_operator_tak_melihat_papan(pg, pabrik):
    c = await _klien(pg, role="operator", gudang_id=pabrik["g1"])
    async with c:
        t = (await c.get("/")).text
    assert "Perlu perhatian" not in t
    assert "GB-MENGGANTUNG-01" not in t
    assert 'href="/gudang/g2"' not in t, "operator ditawari gudang sebelah"
    # Yang tetap ada: petaknya sendiri. Halaman yang kosong terbaca sebagai
    # aplikasi rusak, bukan sebagai peran yang lebih sempit.
    assert 'class="beranda-gudang-padat"' in t
    assert "Gudang 1 — Selepan" in t
    assert "Gabah masuk" in t


async def test_harga_yang_masih_baru_tak_masuk_perhatian(pg):
    """Dua hari itu batas yang disengaja: harga yang baru masuk pagi ini memang
    belum diverifikasi, dan menyebutnya penyimpangan membuat blok ini selalu
    berisi — lalu diabaikan."""
    from app.database import now_local
    from app.models import PurchaseBatch, Supplier, User, Warehouse

    async with pg() as db:
        g1 = Warehouse(nama_gudang="Gudang 1 - Selepan", kode_fungsi="g1")
        db.add(g1)
        await db.flush()
        u = User(nama="Op", role="operator", status="aktif", default_warehouse_id=g1.id)
        s = Supplier(nama_supplier="Pak Tani")
        db.add_all([u, s])
        await db.flush()
        db.add(PurchaseBatch(kode_batch="GB-BARU-01", supplier_id=s.id, berat_total_kg=8000, kondisi_gabah="kering",
                             tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
                             input_by=u.id, flag_unverified=True))
        await db.commit()

    c = await _klien(pg, role="superadmin")
    async with c:
        t = (await c.get("/")).text
    assert "GB-BARU-01" not in t
    assert "Perlu perhatian" not in t, "blok digambar padahal tak ada yang menyimpang"
