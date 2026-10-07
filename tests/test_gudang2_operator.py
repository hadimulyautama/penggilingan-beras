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
from app.web import api
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
    assert ids[:7] == ["pindah_tumpukan_silo", "pindah_broken_silo",
                       "mulai_penyosohan", "hasil_penyosohan",
                       "hentikan_penyosohan", "lanjutkan_penyosohan", "selesai_penyosohan"]
    assert "masukkan_pk" not in ids and "undo" in ids
    # Keenam yang lama TETAP di menu — lembar kartunya dibangun dari
    # spesifikasi yang sama — tetapi sejak 28 September 2026 ditandai `kartu`,
    # jadi katalog "Catat pekerjaan lain" melewatkannya. Pagar ini dulu
    # menuntut kelompok "Gudang 2 · penyosohan", yaitu DIGAMBAR di katalog;
    # itu pintu kedua ke pekerjaan yang sudah punya kartu, dan aturannya sudah
    # ditetapkan pemilik 21 September untuk Gudang 1 — Gudang 2 cuma
    # tertinggal.
    _BERKARTU = ["pindah_tumpukan_silo", "mulai_penyosohan", "hasil_penyosohan",
                "hentikan_penyosohan", "lanjutkan_penyosohan", "selesai_penyosohan"]
    for a in menu:
        if a["id"] in _BERKARTU:
            assert a["kartu"] is True and a["wh"] == "g2", a["id"]
    # `pindah_broken_silo` (6 Oktober 2026) BELUM punya kartu tersendiri di
    # Stok — tetap digambar di katalog "Catat pekerjaan lain" supaya tetap
    # terjangkau. Beda sengaja dari enam di atas, bukan yang terlewat.
    broken_silo = next(a for a in menu if a["id"] == "pindah_broken_silo")
    assert not broken_silo.get("kartu") and broken_silo["wh"] == "g2"
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
    """Antrean = silo; berjalan = mesin; tak ada kerja meja.

    Tumpukan (per intake, boleh dipindah sebagian) KELUAR dari antrean ini
    sejak 5 Oktober 2026 (keputusan pemilik: *"operator memilih bahan dari
    halaman stok untuk masuk ke silo. tidak perlu lagi dari antrian
    tunggu"*) — kartunya `_kartu_tumpukan_g2` MASIH ADA (dipakai picker
    `/actions/tumpukan-sisa`), tapi tak lagi ditambahkan ke `b.menunggu`
    di sini; tombol "Masukkan ke silo" sekarang ada di kartu PK-nya sendiri
    di layar Stok.

    TRANSIT: pagar ini semula menuntutnya KOSONG, dan niat itu benar untuk apa
    yang ada saat itu — stok miliknya sendiri adalah antrean, bukan barang yang
    dipantau (keputusan pemilik 12 September 2026). Sejak 25 September ada satu
    hal yang memang bukan stoknya: permintaan PK dari Gudang 1.

    Yang dijaga BUKAN "dipakai sekali", melainkan APA yang boleh masuk: Transit
    hanya untuk permintaan PK, dan stok Gudang 2 sendiri tak pernah masuk ke
    sana. Pagar ini dulu menghitung pemakaian `b.transit` dan menuntutnya
    TEPAT SATU — hitungan itu memang benar saat ditulis, tetapi ia menjaga
    angka, bukan aturan, dan angkanya patah 26 September 2026 ketika permintaan
    yang BERAKHIR TANPA BARANG (ditolak, gugur) mendapat kabarnya di sini juga.
    Keduanya permintaan; aturannya utuh. Jadi yang diperiksa sekarang
    aturannya: setiap pemakaian `b.transit` berdiri di dalam kode yang
    berurusan dengan `PermintaanPk`, dan tak satu pun kartu stok masuk.
    """
    kode = kode_saja(berjalan.untuk_operator_gudang2)
    assert "_kartu_silo_g2(db, asal_silo)" in kode
    # Dipindah ke tombol di kartu Stok — lihat docstring di atas. Memanggilnya
    # DI SINI lagi akan mendaftarkan PK yang sama dua kali: sekali sebagai
    # kartu Stok yang bertombol, sekali sebagai kartu Antrian tunggu.
    assert "_kartu_tumpukan_g2(db)" not in kode
    assert "b.menunggu +=" in kode and "b.berjalan +=" in kode
    assert "b.meja" not in kode
    # Transit hanya untuk permintaan PK — diperiksa pada SETIAP pemakaiannya,
    # bukan pada jumlahnya. Yang mendahului tiap pemakaian harus kode yang
    # berurusan dengan permintaan; kartu stok tak boleh sampai ke sana.
    pakai = [i for i in range(len(kode)) if kode.startswith("b.transit", i)]
    assert pakai, "Transit tak dipakai sama sekali — kabar permintaan hilang"
    for i in pakai:
        awal = kode.rfind("for ", 0, i)
        assert "PermintaanPk" in kode[:i] and awal != -1 and (
            "_pmt." in kode[awal:i] or "PermintaanPk" in kode[awal:i]), \
            "Transit diisi sesuatu selain permintaan"
    for stok in ("_kartu_tumpukan_g2", "_kartu_silo_g2", "_kartu_beras_curah"):
        assert f"b.transit.append({stok}" not in kode and \
            f"b.transit += await {stok}" not in kode, \
            "stok Gudang 2 sendiri masuk ke Transit"
    tumpuk = kode_saja(berjalan._kartu_tumpukan_g2)
    assert "kelompok='tumpukan'" in tumpuk and "'pindah_tumpukan_silo'" in tumpuk
    sosoh = kode_saja(berjalan._kartu_penyosohan_g2)
    assert "'Penyosohan dijeda'" in sosoh and "'lanjutkan_penyosohan'" in sosoh
    assert "'Ditambah'" in sosoh
    # `untuk()` mengarahkan operator G2 (yang bukan meja) ke layar ini.
    untuk = kode_saja(berjalan.untuk)
    assert "untuk_operator_gudang2(db)" in untuk
    assert untuk.index("can_see_financials(user)") < untuk.index("untuk_operator_gudang2(db)")


def test_stok_karung_operator_g2_hanya_gudangnya_sendiri():
    """Penyaringnya di SERVER, bukan di templat (keputusan pemilik 23 September
    2026).

    Dulu yang diperiksa `gudang2_api.stok` — pintu app Gudang 2, yang dihapus
    24 September 2026 bersama app-nya. Aturannya tidak ikut hilang: ia
    sempat dipegang `layar_stok._karung`, lalu pindah ke
    `layar_produk.halaman_stok_karung` (7 Oktober 2026, karung dapat
    halamannya sendiri). Yang dijaga tetap sama — karung Gudang 1 tak
    sampai ke layarnya, dan tak ada angka uang yang ikut.
    """
    from app.web import layar_produk

    kode = kode_saja(layar_produk.halaman_stok_karung)
    assert "stok_kemasan_rinci(db" in kode, "stok karung tak diambil"
    assert "gudang1(view)" in kode, "batas gudang tak diperiksa"
    # Dan tak ada harga yang ikut: satuannya lembar, dan operator tak melihat
    # angka uang. Sumbernya sendiri (`stok_kemasan_rinci`) tak menyusun harga.
    rinci = kode_saja(kms.stok_kemasan_rinci)
    for uang in ("harga", "hpp", "Decimal"):
        assert uang not in rinci, uang


def test_kartu_gudang2_memakai_kosakatanya_sendiri():
    """Silo Gudang 2 bukan silo pengering, dan penyosohan bukan giling.

    Laporan pemilik 24 September 2026: kartu silo Gudang 2 berkeping "Transit
    di silo kering", dan kartu berjudul "Penyosohan" berkeping "Proses giling"
    — membantah judulnya sendiri.

    Kunci fase memikul DUA tugas: WARNA kartu (urutannya mengikuti perjalanan
    barang, dan app.css mengikuti urutan yang sama) dan KATANYA. Warnanya
    netral antar gudang; katanya tidak. Jadi kunci baru, warna lama — dan
    kunci tanpa kelas warna akan tampil polos tanpa ada yang memberi tahu.
    """
    import pathlib

    from app.web.tampilan import templates

    FASE = templates.env.globals["FASE"]
    assert FASE["silo_g2"] == "Di silo bahan"
    assert FASE["sosoh"] == "Proses sosoh"
    # Kata Gudang 1 tak ikut berubah — di sana keduanya benar.
    assert FASE["silo"] == "Transit di silo kering" and FASE["giling"] == "Proses giling"

    # Tiap kunci fase WAJIB punya kelas warnanya di kedua bentuk kartu.
    akar = pathlib.Path(__file__).resolve().parents[1] / "hmu_tampilan/static/app.css"
    css = akar.read_text()
    for kunci in FASE:
        for bentuk in ("benda", "padat"):
            assert f".{bentuk}--{kunci}" in css, f"{bentuk}--{kunci} tak punya warna"


def test_kartu_gudang2_tak_lagi_memakai_fase_gudang1():
    """Yang dijaga bukan tiga barisnya, melainkan kelasnya: penyusun kartu
    Gudang 2 tak boleh meminjam kosakata Gudang 1 lagi."""
    import inspect

    from app.services import berjalan

    for fungsi in (berjalan._kartu_silo_g2, berjalan._kartu_penyosohan_g2):
        kode = inspect.getsource(fungsi)
        assert 'fase="silo"' not in kode, fungsi.__name__
        assert 'fase="giling"' not in kode, fungsi.__name__
    # Kartu mutu PK luar duduk di silo Gudang 2 juga.
    g2 = inspect.getsource(berjalan.untuk_gudang2)
    assert 'aksi="qc_pk_luar"' in g2 and 'fase="silo_g2"' in g2
