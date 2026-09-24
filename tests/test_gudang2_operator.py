"""Aturan operator Gudang 2 menurut pemilik (12 September 2026).

Aplikasi operator Gudang 2 (repo `gudang2/`) tipis di atas repo ini, jadi
aturannya harus hidup DI SINI. Yang dijaga: pembagian tugas (tumpukan→silo
= operator, menempatkan PK datang = Admin), silo yang dipoles boleh diisi,
tumpukan tak berbatas, penyosohan bisa berhenti, dan bentuk layar operator
(antrean = stok PK, berjalan = mesin). Perilakunya di Postgres ada di
tests/pg/test_gudang2_operator.py; di sini kontrak kodenya.
"""
from __future__ import annotations

import inspect

from app.penggilingan.gudang1.services import jeda
from app.penggilingan.inventory import packaging as kms
from app.penggilingan.gudang2 import polishing, service as g2
from app.services import berjalan
from app.web import api, gudang2_api
from tests.bantu import kode_saja


def test_penyosohan_punya_daftar_sebab_berhenti_sendiri():
    assert "penyosohan" in jeda.SEBAB
    assert "Mesin sosoh rusak" in jeda.SEBAB["penyosohan"]
    assert "Mesin pendukung rusak" in jeda.SEBAB["penyosohan"]
    assert "Bahan bakar habis" not in jeda.SEBAB["penyosohan"]
    # Kolom penunjuknya ada, dan dipilih lewat satu peta — bukan if berantai.
    from app.models import JedaProses
    assert "polishing_process_id" in {c.name for c in JedaProses.__table__.columns}
    assert "penyosohan" in jeda._KOLOM
    assert "_kolom(jenis)" in kode_saja(jeda.jeda_terbuka)
    assert "_kolom(jenis)" in kode_saja(jeda.tertahan_detik)


def test_bahan_terpakai_menghitung_pk_yang_ditambahkan_selama_proses():
    """Silo yang dipoles boleh diisi lagi (keputusan pemilik). Yang dituang
    selama proses bukan sisa — ia bahan, dan ikut jadi penyebut rendemen."""
    from app.penggilingan.gudang2.models import PolishingSiloUsage
    assert "berat_masuk_kg" in {c.name for c in PolishingSiloUsage.__table__.columns}
    kode = kode_saja(polishing.selesai_penyosohan)
    assert "berat_masuk_kg" in kode
    assert "tersedia - float(sisa_kg)" in kode
    # Penjaga lama (menolak intake ke silo yang dipoles) benar-benar hilang.
    assert not hasattr(g2, "_tolak_silo_sedang_dipoles")
    # Sejak Tahap 3 kedua pemindahan tumpukan menulis lewat satu titik,
    # `_catat_pindah`, dan di sanalah tuangan ke proses yang berjalan dicatat.
    for fn in (g2._add_intake, g2._catat_pindah):
        assert "_catat_masuk_selama_proses(" in kode_saja(fn), fn.__name__
    for fn in (g2.pindah_tumpukan_ke_silo, g2.pindah_tumpukan):
        assert "_catat_pindah(" in kode_saja(fn), fn.__name__


def test_tumpukan_gudang2_tanpa_batas_secara_bawaan():
    from app.config import Settings
    assert Settings.__dataclass_fields__["g2_tumpukan_maks_kg"].default == 0 \
        if hasattr(Settings, "__dataclass_fields__") else True
    kode = kode_saja(g2._guard_kapasitas_tumpukan)
    # Bobot yang belum diketahui (None) pun tak ditolak — pagar yang tak bisa
    # menilai tumpukan tanpa batas memang tak menolak apa pun (QA P6-02).
    assert "if not cap or tambahan_kg is None:" in kode and "return" in kode


def test_jeda_penyosohan_ditutup_saat_prosesnya_selesai():
    """P-K-17 berlaku juga di penyosohan: jam tertahan tak boleh terus
    berjalan pada proses yang sudah tidak ada."""
    assert "jeda_terbuka(db, 'penyosohan', proc.id)" in kode_saja(polishing.selesai_penyosohan)


async def _menu_g2(monkeypatch):
    """Katalog aksi seperti yang dilihat operator Gudang 2 — tanpa basis data.

    Satu tempat karena dua uji membacanya: isi katalognya, dan bentuk medan di
    dalamnya. Dua penyiapan yang hampir sama akan menyimpang, dan yang
    menyimpang diam-diam adalah yang tak menguji apa pun lagi.
    """
    from types import SimpleNamespace

    async def ya(_u):
        return True

    async def tidak(_u):
        return False

    monkeypatch.setattr(api, "_is_g1_operator", tidak)
    monkeypatch.setattr(api, "_is_g2_operator", ya)
    monkeypatch.setattr(api, "can_see_financials", lambda u: False)

    class _Db:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(api, "SessionLocal", lambda: _Db())

    async def sebab_palsu(db):
        return {k: list(v) for k, v in jeda.SEBAB.items()}

    async def mutu_palsu(db):
        return True

    from app.services import setelan
    monkeypatch.setattr(setelan, "sebab_jeda", sebab_palsu)
    monkeypatch.setattr(setelan, "target_kadar_air", lambda db: _nilai(14.0))
    monkeypatch.setattr(setelan, "fitur_mutu", mutu_palsu)
    from app.web import aksi_inventory
    monkeypatch.setattr(aksi_inventory, "spesifikasi", lambda **k: [])

    return await api.actions_menu(SimpleNamespace(id=1, role="operator", nama="Uji"))


async def test_katalog_operator_gudang2_dan_entry_admin(monkeypatch):
    """Operator: pindah tumpukan→silo, mulai, hasil, hentikan, lanjutkan,
    selesai, packing, bekatul, undo. BUKAN masukkan PK — itu entry Admin."""
    menu = await _menu_g2(monkeypatch)
    ids = [a["id"] for a in menu]
    assert ids[:6] == ["pindah_tumpukan_silo", "mulai_penyosohan", "hasil_penyosohan",
                       "hentikan_penyosohan", "lanjutkan_penyosohan", "selesai_penyosohan"]
    assert "masukkan_pk" not in ids and "undo" in ids
    for a in menu:
        if a["id"] in ids[:6]:
            assert a["grup"] == "Gudang 2 · penyosohan" and a["wh"] == "g2"
    sebab = next(a for a in menu if a["id"] == "hentikan_penyosohan")["fields"][1]
    assert ["Mesin sosoh rusak", "Mesin sosoh rusak"] in sebab["options"]
    assert [jeda.SEBAB_LAIN, "Lainnya — tulis sendiri"] in sebab["options"]


async def test_silo_selesai_dibaca_dari_prosesnya_bukan_daftar_mati(monkeypatch):
    """Keluhan pemilik 24 September 2026 07:14 — QA 24 Sep (c) butir 4.

    Borang "Selesai penyosohan" menuliskan pilihan silonya DENGAN TANGAN
    (`type: select`, daftar mati A/B) padahal medan tepat di atasnya sudah
    menyebut prosesnya. Jadi ia menawarkan Silo A kepada orang yang menyosoh di
    Silo B; yang menekannya dijawab 400 "Sebutkan silo mana yang selesai
    (A/B)" — pesan yang tak masuk akal bagi orang yang BARU SAJA menyebutkan
    silo. Sekarang medannya `remote` dengan `induk`: daftarnya silo milik proses
    yang dipilih, dan daftar sepanjang satu terisi sendiri di klien.

    Uji ini juga menjaga aturan umum `induk`: ia harus menyebut medan LAIN di
    borang yang sama, dan medan itu harus digambar DI ATASNYA — klien memuat
    daftar anak dari nilai induknya, jadi induk yang ada di bawah menyuruh
    orang mengisi borangnya dari bawah ke atas.
    """
    menu = await _menu_g2(monkeypatch)
    aksi = next(a for a in menu if a["id"] == "selesai_penyosohan")
    silo = next(f for f in aksi["fields"] if f["name"] == "silo")
    assert silo["type"] == "remote" and silo["induk"] == "kode_proses"
    assert silo["source"] == "/api/actions/sosoh-silo"
    assert "options" not in silo, "daftar mati A/B kembali"

    for a in menu:
        nama = [f["name"] for f in a["fields"]]
        for i, f in enumerate(a["fields"]):
            if not f.get("induk"):
                continue
            assert f["type"] == "remote", f"{a['id']}.{f['name']}: induk cuma untuk remote"
            assert f["induk"] in nama, f"{a['id']}.{f['name']}: induk tak ada di borangnya"
            assert nama.index(f["induk"]) < i, f"{a['id']}.{f['name']}: induk di bawahnya"


async def _nilai(v):
    return v


def test_masukkan_pk_dan_jeda_dijaga_di_server_bukan_di_menu():
    kode = kode_saja(api.act_masukkan_pk)
    assert "can_see_financials(user)" in kode, "entry Admin harus dijaga peran, bukan cuma disembunyikan"
    for fn in (api.act_hentikan_proses, api.act_lanjutkan_proses):
        k = kode_saja(fn)
        assert "_is_g2_operator if jenis == 'penyosohan' else _is_g1_operator" in k, fn.__name__
    assert "_is_g2_operator" in kode_saja(api.act_pindah_tumpukan_silo)


def test_layar_operator_gudang2_antrean_adalah_stok_pk():
    """Antrean = tumpukan (per intake, boleh dipindah sebagian) + silo;
    berjalan = mesin; tak ada transit dan tak ada kerja meja."""
    kode = kode_saja(berjalan.untuk_operator_gudang2)
    assert "_kartu_tumpukan_g2(db)" in kode and "_kartu_silo_g2(db, asal_silo)" in kode
    assert "b.menunggu +=" in kode and "b.berjalan +=" in kode
    assert "b.transit" not in kode and "b.meja" not in kode
    tumpuk = kode_saja(berjalan._kartu_tumpukan_g2)
    assert "kelompok='tumpukan'" in tumpuk and "'pindah_tumpukan_silo'" in tumpuk
    sosoh = kode_saja(berjalan._kartu_penyosohan_g2)
    assert "'Penyosohan dijeda'" in sosoh and "'lanjutkan_penyosohan'" in sosoh
    assert "'Ditambah'" in sosoh
    # `untuk()` mengarahkan operator G2 (yang bukan meja) ke layar ini.
    untuk = kode_saja(berjalan.untuk)
    assert "untuk_operator_gudang2(db)" in untuk
    assert untuk.index("can_see_financials(user)") < untuk.index("untuk_operator_gudang2(db)")


def test_api_internal_gudang2_memakai_pintu_meja_dan_gerbang_operator():
    """Satu token, satu jalur akun — gudang2 dan Meja adalah dua satelit di
    atas pintu yang sama; gerbang perannya operator Gudang 2."""
    assert gudang2_api.router.prefix == "/internal/gudang2"
    jalur = {r.path for r in gudang2_api.router.routes}
    assert {"/internal/gudang2/beranda", "/internal/gudang2/kartu", "/internal/gudang2/stok"} <= jalur
    assert "_is_g2_operator" in kode_saja(gudang2_api.akun_operator_g2)
    assert "akun_meja" in inspect.getsource(gudang2_api.akun_operator_g2)
    from app.main import app
    assert any(r.path == "/internal/gudang2/kartu" for r in app.routes)


def test_stok_karung_operator_g2_hanya_gudangnya_sendiri():
    """Penyaringnya di SERVER, bukan di templat (keputusan pemilik 23 September
    2026).

    Layar operator Gudang 2 menggambar apa pun yang dikirim `/internal/gudang2/
    stok`; kalau karung Gudang 1 ikut terkirim, ia ikut tergambar. Jadi yang
    menjamin batas gudang adalah baris penyaring di sini — dan tiruan produksi
    di repo `gudang2/` sengaja dibuat sama ketatnya, supaya layarnya tak pernah
    lulus uji pada bentuk yang tak pernah ia terima.
    """
    # `kode_saja` menulis ulang sumbernya dari AST, jadi kutipnya diseragamkan
    # jadi kutip tunggal — pola yang dicari harus tak peduli kutip.
    kode = kode_saja(gudang2_api.stok)
    assert "stok_kemasan_rinci(db)" in kode, "stok karung tak diambil"
    assert "k['gudang'] == 'Gudang 2'" in kode, "karung Gudang 1 tak disaring"
    assert "'karung': karung" in kode
    # Dan tak ada harga yang ikut: satuannya lembar, dan operator tak melihat
    # angka uang. Sumbernya sendiri (`stok_kemasan_rinci`) tak menyusun harga.
    rinci = kode_saja(kms.stok_kemasan_rinci)
    for uang in ("harga", "hpp", "Decimal"):
        assert uang not in rinci, uang
