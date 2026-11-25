"""Destination catalog on the native shell, with real tenant/Monitoring guards.

No source-page allowlist, stock reader replacement, grant or business write.
"""
import json
import pytest
from bs4 import BeautifulSoup
from hmu_identitas.ruang_data import pasang_pagar
from tests.pg.test_ruang_perusahaan import siapkan, aktifkan, konfigurasi
from tests.pg.test_konsolidasi_pekerjaan import lengkap, stok_lengkap, sosoh_jasa
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_halaman_bertahap import _sidik

pytestmark = pytest.mark.asyncio

async def test_stok_destination_available_on_fresh_native_shells(pg, lengkap, monkeypatch):
    clients = [
        ("admin", await _klien(pg, role="admin"), ("/", "/riwayat-sosoh", "/riwayat-giling", "/riwayat-pengeringan", "/pengaturan"), {"bahan", "produk", "karung"}),
        ("operator_g2", await _klien(pg, role="operator", gudang_id=lengkap["gudang"]["g2"]), ("/", "/riwayat-sosoh", "/pengaturan"), {"bahan", "produk", "karung"}),
        ("operator_g1", await _klien(pg, role="operator", gudang_id=lengkap["gudang"]["g1"]), ("/", "/riwayat-giling"), {"bahan", "produk", "karung"}),
        ("operator_no_location", await _klien(pg, role="operator"), ("/",), {"bahan"}),
    ]
    space = await siapkan(pg)
    await aktifkan(pg, space)
    konfigurasi(monkeypatch, space)
    pasang_pagar(pg.kw["bind"], wajib=True)
    from app.web.stok_kerangka_langsung import sah_descriptor
    from app.services import stok
    def forbidden(*args, **kwargs):
        pytest.fail("Destination prototypes must not read stock balances")
    before = await _sidik(pg)
    try:
        for role, client, sources, expected in clients:
            for path in sources:
                # Stub only while the additional catalog is built. The
                # source's own authorized native reader stays unchanged.
                from app.web import stok_kerangka_langsung
                original = stok_kerangka_langsung.susun
                async def checked(*args, **kwargs):
                    with monkeypatch.context() as m:
                        for name in ("pk", "produk", "karung"):
                            if hasattr(stok, name):
                                m.setattr(stok, name, forbidden)
                        return await original(*args, **kwargs)
                with monkeypatch.context() as m:
                    m.setattr(stok_kerangka_langsung, "susun", checked)
                    response = await client.get(path, headers={"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"})
                assert response.status_code == 200, (role, path, response.status_code)
                doc = BeautifulSoup(response.text, "html.parser")
                host = doc.select_one("#padi-stok-kerangka")
                assert host is not None, (role, path, "fresh document lost destination Stok")
                descriptor = json.loads(host.string)
                assert sah_descriptor(descriptor) and set(descriptor["frames"]) == expected
                base = json.loads(doc.select_one("#padi-kerangka-langsung").string)
                assert all(descriptor[k] == base[k] for k in ("cap", "sesi", "konteks"))
                for kind, refs in descriptor["frames"].items():
                    frame = BeautifulSoup("".join(descriptor["potongan"][i] for i in refs), "html.parser")
                    root = frame.select_one('[data-kind="stok"]')
                    assert root is not None and len(root.select("thead th")) >= 6
                    assert root["data-url"] == "/api/halaman-bertahap/stok?tab=" + kind + "&pemilik=semua"
                    assert not root.select(".antrian-item,.benda[data-cari],[data-post],[data-kirim]")
                    assert root.select_one('select[name="pelanggan_id"]').has_attr("disabled")
                assert len(doc.select('script[src^="/monitoring/aktivitas.js"]')) == 1
                # Partial refreshes remain native, without another catalog.
                partial = await client.get(path, headers={"X-Pindah": "1"})
                assert partial.status_code == 200
                assert BeautifulSoup(partial.text, "html.parser").select_one("#padi-stok-kerangka") is None
        no_location = clients[-1][1]
        assert (await no_location.get("/api/halaman-bertahap/stok?tab=produk")).status_code == 403
        assert (await no_location.get("/api/halaman-bertahap/stok?tab=karung")).status_code == 403
        assert (await no_location.get("/api/halaman-bertahap/stok?tab=bahan")).status_code == 200
    finally:
        for _, client, _, _ in clients:
            await client.aclose()
    assert await _sidik(pg) == before
