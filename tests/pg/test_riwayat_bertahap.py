"""History read shells reuse exact native guards/readers; no business write."""
import json
import pytest
from bs4 import BeautifulSoup
from hmu_identitas.ruang_data import pasang_pagar
from tests.pg.test_ruang_perusahaan import siapkan, aktifkan, konfigurasi
from tests.pg.test_konsolidasi_pekerjaan import lengkap, stok_lengkap, sosoh_jasa
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_halaman_bertahap import _sidik, _isi

pytestmark = pytest.mark.asyncio

async def test_history_shell_permission_native_parity_and_cursor(pg, lengkap, monkeypatch):
    from app.web.riwayat_bertahap import TUJUAN
    clients = [
        ("admin", await _klien(pg,role="admin"), set(TUJUAN)),
        ("operator_g2", await _klien(pg,role="operator",gudang_id=lengkap["gudang"]["g2"]), {"riwayat-sosoh"}),
        ("operator_g1", await _klien(pg,role="operator",gudang_id=lengkap["gudang"]["g1"]), {"riwayat-giling","riwayat-pengeringan"}),
        ("operator_no_location", await _klien(pg,role="operator"), set()),
    ]
    space=await siapkan(pg); await aktifkan(pg,space); konfigurasi(monkeypatch,space); pasang_pagar(pg.kw["bind"],wajib=True)
    before=await _sidik(pg)
    try:
        for role,client,allowed in clients:
            response=await client.get("/",headers={"Sec-Fetch-Mode":"navigate","Sec-Fetch-Dest":"document"})
            assert response.status_code==200
            doc=BeautifulSoup(response.text,"html.parser");host=doc.select_one("#padi-riwayat-kerangka")
            if not allowed:
                assert host is None
            else:
                assert host is not None,(role,"Missing shared destination catalog")
                data=json.loads(host.string);base=json.loads(doc.select_one("#padi-kerangka-langsung").string)
                assert set(data["frames"])=={TUJUAN[k]["path"] for k in allowed}
                assert all(data[k]==base[k] for k in ("cap","konteks","sesi"))
                default=await client.get("/riwayat")
                assert default.status_code==303
                assert data["default"]==default.headers["location"]
                for path,refs in data["frames"].items():
                    frame=BeautifulSoup("".join(data["potongan"][i] for i in refs),"html.parser")
                    kind=path[1:];root=frame.select_one("[data-halaman-bertahap]")
                    assert root["data-kind"]==kind and root["data-stamp"]==base["konteks"]+"|"+path
                    assert [v.text for v in root.select(".rpd-stats strong")]==["—"]*3
                    assert not root.select("form[method=post],[data-rg-proses],.riwayat-desktop-row")
                    assert frame.select_one("[data-lk-cetak]").has_attr("disabled")
                    assert frame.select_one('script[data-riwayat-aset-native="halaman-bertahap.js"]')
                    assert frame.select_one('style[data-riwayat-aset-native="riwayat.css"]')
            for kind,config in TUJUAN.items():
                if kind not in allowed:
                    assert (await client.get(config["path"])).status_code==403
                    assert (await client.get("/api/halaman-bertahap/"+kind)).status_code==403
                    continue
                for query in ("","?sebelum=999999","?sebelum=abc"):
                    shell=await client.get(config["path"]+query,headers={"Sec-Fetch-Mode":"navigate","Sec-Fetch-Dest":"document"})
                    native=await client.get(config["path"]+query,headers={"X-Pindah":"1"})
                    data=await client.get("/api/halaman-bertahap/"+kind+query)
                    assert shell.status_code==native.status_code==data.status_code==200
                    dom=BeautifulSoup(shell.text,"html.parser");root=dom.select_one("[data-halaman-bertahap]")
                    assert root and root["data-stamp"]==data.json()["stamp"]
                    assert _isi(native.text)==_isi(data.json()["html"])
                    fresh=BeautifulSoup(native.text,"html.parser")
                    columns=lambda d:[c.text.strip() for c in d.select(".riwayat-desktop-list>.riwayat-desktop-head>span,.riwayat-desktop-list>table>thead th")]
                    assert columns(dom)==columns(fresh)==config["columns"]
                    assert [s.text for s in root.select(".rpd-stats>div>span")]==[s.text for s in fresh.select(".rpd-stats>div>span")]
                    assert fresh.select_one("[data-halaman-bertahap]") is None
                    assert dom.select_one(".riwayat-empty") is None
            assert await _sidik(pg)==before
    finally:
        for _,client,_ in clients:await client.aclose()


async def test_history_prototypes_never_call_history_readers(pg,lengkap,monkeypatch):
    from app.web import riwayat_bertahap as history
    from app.penggilingan.gudang2 import polishing
    from app.penggilingan.gudang1.services import milling,drying
    client=await _klien(pg,role="admin")
    def deny(*args,**kwargs):pytest.fail("Skeleton must not read process history")
    for module,name in [(polishing,"riwayat_sosoh"),(milling,"riwayat_giling"),(drying,"riwayat_pengeringan")]:
        monkeypatch.setattr(module,name,deny)
    before=await _sidik(pg)
    try:
        for config in history.TUJUAN.values():
            response=await client.get(config["path"],headers={"X-Kerangka-Halaman":"1"})
            assert response.status_code==200 and 'data-halaman-bertahap' in response.text
        assert await _sidik(pg)==before
    finally:await client.aclose()


@pytest.mark.parametrize("status",[503,403])
async def test_optional_history_failure_keeps_native_permission_boundary(pg,lengkap,monkeypatch,status):
    from fastapi import HTTPException
    from app.web import riwayat_bertahap as history
    async def unavailable(*args,**kwargs):raise HTTPException(status,"Synthetic unavailable")
    monkeypatch.setattr(history,"susun",unavailable)
    async with await _klien(pg,role="admin") as client:
        before=await _sidik(pg)
        response=await client.get("/",headers={"Sec-Fetch-Mode":"navigate","Sec-Fetch-Dest":"document"})
        doc=BeautifulSoup(response.text,"html.parser")
        assert response.status_code==200 and doc.select_one("#padi-riwayat-kerangka") is None
        assert bool(doc.select_one("#padi-kerangka-langsung"))==(status==503)
        assert await _sidik(pg)==before
