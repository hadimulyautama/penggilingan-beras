"""Layar Riwayat sosoh — siapa yang boleh melihatnya, dan apa yang tergambar.

Keputusan pemilik 2 Oktober 2026, dua kalimat yang menentukan berkas ini:

  · *"berisi kartu proses sosoh yang selesai berikut seluruh informasinya dan
    hasilnya. terkhusus berapa persen yang jadi beras, berapa persen broken,
    berapa persen menir, berapa persen bekatul, lalu berapa persen susut
    debu/bobot."*
  · *"riwayat sosoh hanya super admin, admin dan operator gudang 2 yang bisa
    lihat."*

Rumusnya sendiri diuji atas angka telanjang di `tests/test_neraca_sosoh.py` —
di sini yang diuji JALUR SUNGGUHANNYA: proses dibuat lewat `mulai_penyosohan`
dan ditutup lewat `selesai_penyosohan`, lalu halamannya dirender lewat HTTP.
Penjaga yang memanggil fungsinya saja akan lulus pada hari templatnya berhenti
menggambar angkanya — kelas kerusakan yang sudah dibayar sekali di repo ini
(`TempatPk.pemilik` dihitung lalu tak pernah disebut markup-nya).
"""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy.orm import selectinload

pytestmark = pytest.mark.asyncio


async def _silo_berisi(pg, huruf: str, kg: float, uid: int) -> None:
    """PK masuk langsung ke silo Gudang 2 — bahan baku penyosohannya."""
    from app.database import now_local
    from app.models import PkGudang2Intake
    from app.penggilingan.gudang2.service import get_g2_silo

    async with pg() as db:
        silo = await get_g2_silo(db, huruf)
        db.add(PkGudang2Intake(
            sumber_tipe="luar", tujuan="silo", silo_id=silo.id, berat_kg=kg,
            tanggal_masuk=now_local().date(), waktu_masuk=now_local(),
            input_by=uid))
        await db.commit()


async def _sosoh_selesai(pg, uid: int, *, huruf="A", masuk=10_000.0,
                         hasil=(("medium", 6_500), ("broken", 1_200),
                                ("menir", 700), ("bekatul", 1_500)),
                         sisa=0.0, spek=None) -> str:
    """Satu penyosohan dari awal sampai DITUTUP, lewat jalur sungguhannya."""
    from app.models import User
    from app.penggilingan.gudang2.polishing import (catat_output,
                                                    mulai_penyosohan,
                                                    selesai_penyosohan)
    from app.services.seed import seed_master

    await seed_master()
    await _silo_berisi(pg, huruf, masuk, uid)
    async with pg() as db:
        u = await db.get(User, uid)
        kode = (await mulai_penyosohan(db, user=u,
                                       nama_silos=[huruf])).proc.kode_proses
    for jenis, kg in hasil:
        async with pg() as db:
            u = await db.get(User, uid)
            await catat_output(db, user=u, kode=kode, jenis=jenis,
                               berat_kg=kg, spek=spek)
    async with pg() as db:
        u = await db.get(User, uid)
        await selesai_penyosohan(db, user=u, kode=kode, nama_silo=huruf,
                                 sisa_kg=sisa)
    return kode


async def _klien(pg, *, peran: str, gudang: str | None = None,
                lihat: str | None = None) -> httpx.AsyncClient:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.main import app
    from app.models import ProduksiAkun, User, Warehouse
    from app.web import csrf, security
    from hmu_identitas import sandi as S
    from hmu_identitas.model import mode_bawaan

    async with pg() as db:
        wid = None
        if gudang:
            w = (await db.execute(select(Warehouse).where(
                Warehouse.nama_gudang.like(gudang + "%")))).scalars().first()
            wid = w.id if w else None
        u = User(nama=f"Uji {peran}", role=peran, status="aktif",
                 default_warehouse_id=wid)
        db.add(u)
        await db.flush()
        a = ProduksiAkun(user_id=u.id, username=f"rs{u.id}",
                         password_hash=S.hash_sandi("rahasia123"),
                         status="aktif", mode_perangkat=mode_bawaan(peran))
        db.add(a)
        await db.commit()
        tok = security.buat_token(a)
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://uji", follow_redirects=True)
    c.cookies.set(security.NAMA_COOKIE, tok)
    c.cookies.set(csrf.NAMA_COOKIE, csrf.terbitkan_baru())
    if lihat:
        c.headers["X-Meja-Lihat"] = lihat
    return c


# ═════════════════ 1 · SIAPA YANG BOLEH MELIHAT ═════════════════

@pytest.mark.parametrize("peran,gudang,lihat", [
    ("superadmin", None, None),
    ("admin", None, None),
    ("operator", "Gudang 2", "operator:g2"),
])
async def test_tiga_yang_boleh(pg, pemakai, peran, gudang, lihat):
    """⭐ "hanya super admin, admin dan operator gudang 2 yang bisa lihat."

    Ketiganya diuji, bukan satu yang mewakili: gerbangnya satu panggilan
    (`_is_g2_operator`) tetapi yang menentukan hasilnya tiga jalan berbeda di
    dalamnya — tangga peran untuk dua yang pertama, dan gudang yang SEDANG
    dikerjakan untuk yang ketiga.
    """
    await _sosoh_selesai(pg, pemakai.id)
    c = await _klien(pg, peran=peran, gudang=gudang, lihat=lihat)
    try:
        r = await c.get("/riwayat-sosoh")
    finally:
        await c.aclose()
    assert r.status_code == 200, (peran, r.status_code)
    assert "Susut debu" in r.text, f"{peran} tak melihat barisnya"


async def test_operator_gudang_satu_ditolak_rutenya_bukan_cuma_pintunya(pg, pemakai):
    """⭐ 403 di RUTENYA — menyembunyikan pintu bukan penjagaan.

    Alamatnya tetap bisa diketik atau ditempel, dan `pindah.js` membuat halaman
    di ponsel berumur panjang: tab yang terbuka sejak sebelum perannya berubah
    akan tetap memanggil alamat ini.
    """
    await _sosoh_selesai(pg, pemakai.id)
    c = await _klien(pg, peran="operator", gudang="Gudang 1")
    try:
        r = await c.get("/riwayat-sosoh")
        beranda = await c.get("/")
    finally:
        await c.aclose()
    assert r.status_code == 403
    # Dan pintunya pun tak ditawarkan — bukan pengganti penjaga di atas,
    # melainkan supaya ia tak menekan pintu yang akan menolaknya.
    assert beranda.status_code == 200
    assert "/riwayat-sosoh" not in beranda.text


# ═════════════════ 2 · APA YANG TERGAMBAR ═════════════════

async def test_kartu_menggambar_kelima_persen_yang_diminta(pg, pemakai):
    """⭐ Angka contoh pemilik, dirender sungguhan.

    Bahan 10.000 kg, hasil 9.900 kg → susut 1%. Dan kelima persennya tergambar:
    beras 65%, broken 12%, menir 7%, bekatul 15%, susut 1% — jumlahnya 100%.

    Persennya dicari dalam bentuk INDONESIA ("1,0%"), bukan "1.0%": titik
    desimal di layar berbahasa Indonesia dibaca sebagai pemisah ribuan, dan
    pada angka susut selisihnya seribu kali.
    """
    kode = await _sosoh_selesai(pg, pemakai.id)
    c = await _klien(pg, peran="admin")
    try:
        r = await c.get("/riwayat-sosoh")
    finally:
        await c.aclose()
    t = r.text
    assert kode in t
    for persen in ("65,0%", "12,0%", "7,0%", "15,0%", "1,0%"):
        assert persen in t, f"{persen} tak tergambar"
    # Baris penutup yang membuktikan pembagiannya utuh.
    assert "100,0%" in t
    assert "Jumlah" in t
    # Bahan bakunya dan asalnya per silo — penyebut seluruh persen di atas.
    assert "bahan baku" in t and "Silo A" in t
    # Batang neracanya tergambar, bukan cuma angkanya.
    assert 'class="neraca"' in t


async def test_kartu_merinci_asal_lot_pk_dan_penambahan_broken(pg, pemakai, pemasok):
    """⭐ Keluhan pemilik 11 Oktober 2026: riwayat berhenti di tingkat silo,
    tak merinci lot/batch PK-nya — beda dari kartu "Sedang berjalan" yang
    sudah merinci asal lot per silo.

    Dua rupa asal dicoba sekaligus, sebangun kartu berjalan: PK beli luar
    (nama pemasok + kode batch) dan broken yang ditambahkan ke silo broken
    (kode pindah `BKS-...`).
    """
    from datetime import date as _date

    from sqlalchemy import select

    from app.models import ByproductStock, Silo, User, Warehouse
    from app.penggilingan.gudang2.models import PkPurchaseBatch
    from app.penggilingan.gudang2.polishing import (catat_output,
                                                    mulai_penyosohan,
                                                    selesai_penyosohan)
    from app.penggilingan.gudang2.service import (masukkan_pk_luar,
                                                   pindah_broken_ke_silo,
                                                   pindah_tumpukan_ke_silo)
    from app.penggilingan.inventory.finished_goods import catat_broken
    from app.services.seed import seed_master
    from app.database import now_local

    await seed_master()
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        # `seed_master()` cuma menyediakan Silo A/B Gudang 2 (keduanya PK) —
        # Silo C (broken) ditambahkan sendiri, sebangun `dunia` di
        # `test_silo_broken.py`.
        g2 = (await db.execute(select(Warehouse)
             .where(Warehouse.nama_gudang.like("Gudang 2%")))).scalars().first()
        db.add(Silo(nama_silo="Silo C", warehouse_id=g2.id, jenis_isi="broken"))
        db.add(PkPurchaseBatch(
            kode_batch="PKB-RIWAYAT-01", supplier_id=pemasok.id,
            berat_total_kg=6_000, tanggal_pembelian=_date.today(),
            waktu_pembelian=now_local(), input_by=u.id, status_batch="diterima",
            flag_unverified=True, sumber_berat="manual"))
        await db.commit()
        ri = await masukkan_pk_luar(db, user=u, kode="PKB-RIWAYAT-01",
                                    tujuan="ditumpuk")
        await pindah_tumpukan_ke_silo(db, user=u, intake_id=ri.intake.id,
                                      nama_silo="A", berat=6_000)
        kode = (await mulai_penyosohan(db, user=u, nama_silos=["A"])).proc.kode_proses
        await catat_output(db, user=u, kode=kode, jenis="premium", berat_kg=1_000)
        await catat_output(db, user=u, kode=kode, jenis="broken", berat_kg=1_000)
        await catat_broken(db, user=u, kode_pol=kode, berat_kg=1_000)
        row_broken = (await db.execute(
            select(ByproductStock).where(ByproductStock.jenis_produk == "broken")
        )).scalars().one()
        await selesai_penyosohan(db, user=u, kode=kode, nama_silo="A", sisa_kg=4_000)
        await pindah_broken_ke_silo(db, user=u, byproduct_stock_id=row_broken.id,
                                    nama_silo="C", berat=1_000)

        # P2: sosoh ulang broken dari Silo C, supaya ia MUNCUL di riwayat.
        kode2 = (await mulai_penyosohan(db, user=u, nama_silos=["C"])).proc.kode_proses
        await catat_output(db, user=u, kode=kode2, jenis="menir", berat_kg=900)
        await selesai_penyosohan(db, user=u, kode=kode2, nama_silo="C", sisa_kg=0)

    c = await _klien(pg, peran="admin")
    try:
        r = await c.get("/riwayat-sosoh")
    finally:
        await c.aclose()
    t = r.text
    assert kode in t and kode2 in t
    # P1 (Silo A, PK beli luar): nama pemasok + kode batch tertera.
    assert "Pemasok Uji" in t and "PKB-RIWAYAT-01" in t
    # P2 (Silo C, broken yang disosoh ulang): kode pindah tertera, berjudul
    # "Giling sendiri" (bukan titipan).
    assert "Giling sendiri · BKS-" in t


async def test_hanya_yang_selesai_yang_masuk_riwayat(pg, pemakai):
    """Proses yang MASIH menyala tak didaftar.

    Persen yang dihitung dari hasil yang masih bertambah akan dibaca sebagai
    hasil akhir, lalu dipakai menilai mesin. Yang berjalan sudah punya
    pintunya di `/berjalan`.
    """
    from sqlalchemy import select
    from hmu_core.proses_db import ProsesTerpadu
    from app.models import User
    from app.penggilingan.gudang2.polishing import (catat_output,
                                                    mulai_penyosohan,
                                                    riwayat_sosoh)
    from app.services.seed import seed_master

    selesai = await _sosoh_selesai(pg, pemakai.id)
    async with pg() as db:
        bersama = (await db.execute(select(ProsesTerpadu).options(
            selectinload(ProsesTerpadu.arus)).where(
            ProsesTerpadu.tabel_sumber == "polishing_process",
            ProsesTerpadu.kode == selesai,
        ))).scalar_one()
        assert bersama.status == "selesai"
        assert any(arus.arah == "hasil" and arus.komoditas == "beras_putih"
                   and arus.atribut_produk.get("kualitas") == "medium"
                   for arus in bersama.arus)
    # Dan satu lagi yang dibiarkan terbuka.
    await seed_master()
    await _silo_berisi(pg, "B", 5_000, pemakai.id)
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        jalan = (await mulai_penyosohan(db, user=u,
                                        nama_silos=["B"])).proc.kode_proses
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await catat_output(db, user=u, kode=jalan, jenis="medium", berat_kg=900)

    async with pg() as db:
        kartu, _ = await riwayat_sosoh(db)
    kode = [k.kode for k in kartu]
    assert selesai in kode
    assert jalan not in kode, "proses berjalan masuk riwayat — persennya belum final"


async def test_pemilik_jasa_disebut_di_kartunya(pg, pemakai):
    """Rendemen barang titipan tak boleh ikut menilai mesin pabrik.

    Bahan bakunya datang dari gudang orang lain dan mutunya tak dipilih
    pabrik — jadi kartunya wajib menyebut pemiliknya, bukan berdiri sama rupa
    dengan lot pabrik.
    """
    from sqlalchemy import select

    from app.models import Jasa, Pelanggan, PkGudang2Intake, PolishingProcess
    from app.penggilingan.gudang2.polishing import riwayat_sosoh

    kode = await _sosoh_selesai(pg, pemakai.id)
    # Barangnya ditandai milik sebuah pesanan — intake-nya DAN prosesnya,
    # sebab `pemilik_silo_g2` membaca dari intake dan kartunya dari proses.
    async with pg() as db:
        pel = Pelanggan(nama_pelanggan="Pak Budi")
        db.add(pel)
        await db.flush()
        j = Jasa(kode="JAS-2610-009", pelanggan_id=pel.id, dibuat_oleh_id=pemakai.id)
        db.add(j)
        await db.flush()
        proc = (await db.execute(select(PolishingProcess).where(
            PolishingProcess.kode_proses == kode))).scalars().one()
        proc.jasa_id = j.id
        for it in (await db.execute(select(PkGudang2Intake))).scalars().all():
            it.jasa_id = j.id
        await db.commit()

    async with pg() as db:
        kartu, _ = await riwayat_sosoh(db)
    k = next(x for x in kartu if x.kode == kode)
    assert k.pemilik and "Pak Budi" in k.pemilik and "JAS-" in k.pemilik

    c = await _klien(pg, peran="admin")
    try:
        r = await c.get("/riwayat-sosoh")
    finally:
        await c.aclose()
    assert "Pak Budi" in r.text, "pemilik dihitung tapi tak tergambar"


async def test_hasil_melebihi_bahan_dikatakan_di_layarnya(pg, pemakai):
    """⚠ Susut negatif = salah catat, dan kartunya harus mengatakannya.

    Yang dipangkas jadi 0% tak pernah terbaca oleh siapa pun, dan yang tak
    terbaca tak pernah dibetulkan.
    """
    await _sosoh_selesai(pg, pemakai.id, masuk=5_000,
                         hasil=(("premium", 2_000),), sisa=4_000)
    c = await _klien(pg, peran="admin")
    try:
        r = await c.get("/riwayat-sosoh")
    finally:
        await c.aclose()
    assert "melebihi" in r.text
    # Dan batang neracanya TIDAK digambar: ruas selebar persen negatif tak
    # punya bentuk, dan batang yang dipaksa penuh menyembunyikan justru hal
    # yang harus terbaca.
    assert 'class="neraca"' not in r.text


# ═════════════════ 3 · BEBAN KUERI ═════════════════

async def test_jumlah_kueri_tetap_walau_kartunya_bertambah(pg, pemakai,
                                                           hitung_kueri):
    """⭐ Belasan kueri TETAP, bukan belasan PER KARTU.

    Layar Stok Produk pernah mengeluarkan satu kueri per penyosohan dan
    halamannya 1,77 detik pada 500 proses (temuan QA P-S-02). Halaman ini
    membaca hal yang sama — pemakaian silo, hasil, spek, orangnya, pemiliknya,
    dan sejak 11 Oktober 2026 juga asal lotnya — dan akan menumpuk dengan cara
    yang sama kalau sampai lupa.

    Diuji sebagai PERBANDINGAN, bukan atas satu angka langit-langit: satu kartu
    dibanding enam kartu. Langit-langit tetap bisa dilewati oleh N+1 yang
    kebetulan kecil, sedangkan selisih yang tumbuh bersama jumlah kartu tak
    bisa disembunyikan. Langit-langitnya sendiri dinaikkan (10 → 16) mengikuti
    tujuh kueri borongan baru `_isian_silo_banyak` — kelonggarannya di atas
    sembilan yang terukur di skenario uji ini (PK langsung, tanpa jasa/lot
    giling), sebab skenario lain (silo broken, PK titipan) bisa menambah
    sampai tujuh kueri lagi yang di sini semuanya terlewati (0 baris).
    """
    from app.penggilingan.gudang2.polishing import riwayat_sosoh

    await _sosoh_selesai(pg, pemakai.id, huruf="A", masuk=10_000)
    async with pg() as db:
        async with hitung_kueri() as satu:
            await riwayat_sosoh(db)

    # Lima penyosohan lagi, bergantian silo supaya tiap proses punya barisnya.
    for i in range(5):
        await _sosoh_selesai(pg, pemakai.id, huruf=("A", "B")[i % 2],
                             masuk=2_000, hasil=(("medium", 1_500),
                                                 ("bekatul", 400)),
                             sisa=0, spek=f"Spek {i}")
    async with pg() as db:
        async with hitung_kueri() as enam:
            kartu, _ = await riwayat_sosoh(db)
    assert len(kartu) == 6

    assert enam.jumlah == satu.jumlah, (
        f"kuerinya tumbuh bersama jumlah kartu: {satu.jumlah} → {enam.jumlah}\n"
        + "\n".join(enam.perintah[:12]))
    assert enam.jumlah <= 16, f"{enam.jumlah} kueri untuk satu halaman"


async def test_halaman_berikutnya_memakai_kursor_bukan_nomor(pg, pemakai):
    """Riwayat bertambah di ujung yang SAMA dengan arah bacanya.

    Nomor halaman akan menggeser satu kartu tiap kali ada sosoh baru ditutup —
    dan kartu yang terlewat justru karena orang menekan "muat lagi".
    """
    from app.penggilingan.gudang2.polishing import riwayat_sosoh

    for i in range(3):
        await _sosoh_selesai(pg, pemakai.id, huruf=("A", "B")[i % 2],
                             masuk=2_000, hasil=(("medium", 1_800),), sisa=0)
    async with pg() as db:
        hal1, lagi1 = await riwayat_sosoh(db, batas=2)
        assert lagi1 and len(hal1) == 2
        hal2, lagi2 = await riwayat_sosoh(db, batas=2, sebelum=hal1[-1].id)
    assert not lagi2 and len(hal2) == 1
    # Tak ada yang terhitung dua kali, dan tak ada yang terlewat.
    assert {k.kode for k in hal1} & {k.kode for k in hal2} == set()
    assert len({k.kode for k in hal1} | {k.kode for k in hal2}) == 3


async def test_kursor_ngawur_tak_menjatuhkan_halamannya(pg, pemakai):
    """Alamat yang diketik atau ditempel tak boleh menjawab 422.

    Halaman yang menolak tanpa jalan keluar memaksa orang mengetik ulang
    alamatnya — dan yang membacanya di gudang tak tahu apa itu kursor.
    """
    await _sosoh_selesai(pg, pemakai.id)
    c = await _klien(pg, peran="admin")
    try:
        for buruk in ("abc", "", "-1", "9999999"):
            r = await c.get(f"/riwayat-sosoh?sebelum={buruk}")
            assert r.status_code == 200, (buruk, r.status_code)
    finally:
        await c.aclose()
