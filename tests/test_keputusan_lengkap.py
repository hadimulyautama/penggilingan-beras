"""Setiap jenis keputusan yang DIKIRIM ke `b.meja` punya bloknya di layar.

Tiga kali dalam satu hari (23 September 2026) ditemukan pekerjaan yang ada di
DATA tetapi tak digambar di layar mana pun: tiket PK yang jenisnya tak dipetakan,
daftar asal silo yang sudah habis, dan — di sini — tiga dari enam jenis keputusan.

Yang ketiga paling lama tak terlihat. `keputusan.html` memegang daftar bloknya
sendiri, berisi tiga id aksi yang diketik tangan, sementara `berjalan.untuk()`
mengirim enam. Harga PK luar & mutu PK luar masih terbaca di aplikasi Meja;
`betulkan_bobot_giling` — korban P6-03 dan tiket yang direvisi sengaja — tak
terbaca di mana pun sejak ia lahir. Pekerjaan yang menahan uang, tak tertagih,
tanpa satu pun tanda.

Uji ini membaca SUMBERNYA: tiap `aksi="…"` yang benar-benar di-append ke
`b.meja`, lalu menuntut tiap satunya punya blok. Jenis ketujuh yang lahir nanti
menjatuhkan uji ini, bukan menghilang diam-diam.

Sejak 24 September 2026 layarnya DUA — "Menunggu keputusan" dan "Mutu & QC"
(permintaan pemilik) — dan tuntutannya ikut berubah bentuk, bukan melemah:

    tiap aksi yang dikirim ke `b.meja` punya blok di TEPAT SATU dari dua layar.

Nol berarti pekerjaan yang tak tergambar di mana pun — kelas galat yang berkas
ini lahir untuk menutup. Dua berarti kartu yang sama ditagih di dua tempat,
lalu dikerjakan dua kali.
"""
from __future__ import annotations

import inspect
import re

from app.services import berjalan as svc
from app.web.layar_keputusan import AKSI_DIKENAL, JENIS_KEPUTUSAN, JENIS_MUTU


def _aksi_yang_dikirim_ke_meja() -> set[str]:
    """Id aksi pada tiap `b.meja.append(Baris(...))` di seluruh `berjalan`.

    Dibaca dari sumbernya, bukan didaftar tangan: daftar tangan di dalam uji
    adalah salinan kedua yang bisa ketinggalan persis seperti yang di templat.
    """
    sumber = inspect.getsource(svc)
    keluar = set()
    for m in re.finditer(r"b\.meja\.append\(", sumber):
        # Cukup sampai penutup append-nya; `aksi=` selalu di dalamnya.
        potongan = sumber[m.end():m.end() + 1200]
        a = re.search(r'aksi="([a-z_]+)"', potongan)
        if a:
            keluar.add(a.group(1))
    return keluar


def _blok_per_aksi() -> dict[str, list[str]]:
    """aksi → layar mana saja yang menggambarnya. Nol dan dua sama-sama salah."""
    keluar: dict[str, list[str]] = {}
    for layar, daftar in (("keputusan", JENIS_KEPUTUSAN), ("mutu", JENIS_MUTU)):
        for aksi, _ in daftar:
            keluar.setdefault(aksi, []).append(layar)
    return keluar


def test_tiap_jenis_yang_dikirim_punya_bloknya_di_tepat_satu_layar():
    from app.services import keputusan as K

    dikirim = _aksi_yang_dikirim_ke_meja()
    # Premisnya: uji ini benar-benar menemukan sesuatu untuk diperiksa. Angkanya
    # dari sumbernya, bukan diketik — jenis yang dihapus (verify_output, 24
    # September 2026) tak boleh menjatuhkan premis ini, dan jenis yang lahir
    # nanti harus ikut menaikkannya.
    assert len(dikirim) >= len(K.SEMUA), f"pembaca sumber tak menemukan append: {dikirim}"

    blok = _blok_per_aksi()
    hilang = dikirim - set(blok)
    assert not hilang, (
        f"jenis keputusan tanpa blok di layar mana pun: {sorted(hilang)}. "
        "Tambahkan ke `services.keputusan.JENIS` — pekerjaan yang tak tampil "
        "tak akan ada yang mencarinya.")
    dua = {a: l for a, l in blok.items() if len(l) > 1}
    assert not dua, f"jenis yang digambar dua layar sekaligus: {dua}"
    # `AKSI_DIKENAL` — yang dipakai jaring penangkap — harus GABUNGAN keduanya.
    # Kalau ia cuma daftar satu layar, jaringnya akan menangkap kembali jenis
    # yang sebenarnya sudah punya blok di layar sebelah.
    assert sorted(AKSI_DIKENAL) == sorted(blok)

    # Ketiga yang dulu hilang disebut namanya, supaya perbaikannya tak
    # tergulung balik tanpa ada yang menyadarinya.
    for aksi in ("harga_pk_luar", "qc_pk_luar", "betulkan_bobot_giling"):
        assert aksi in AKSI_DIKENAL, aksi


def test_daftar_blok_tak_menyebut_jenis_yang_tak_pernah_dikirim():
    """Kebalikannya juga dijaga: blok yang tak pernah berisi apa-apa adalah
    judul yang menagih pekerjaan yang tak ada, dan tagihan semacam itu
    mengajari orang mengabaikan tagihan."""
    dikirim = _aksi_yang_dikirim_ke_meja()
    asing = set(AKSI_DIKENAL) - dikirim
    assert not asing, f"blok untuk jenis yang tak pernah dikirim: {sorted(asing)}"


def test_daftarnya_di_kode_bukan_di_templat():
    """Templat yang memegang daftarnya sendiri tak bisa diuji terhadap data —
    dan itulah yang membuat ketiga jenis hilang selama berminggu-minggu.

    Dua templat sekarang, dan keduanya diperiksa: layar kedua yang mulai
    mengetik daftarnya sendiri mengulang kesalahan yang sama, cuma di tempat
    yang belum pernah dilihat orang.
    """
    import pathlib

    akar = pathlib.Path(__file__).resolve().parents[1] / "app/web/templates"
    for berkas, gelung, daftar in (
            ("keputusan.html", "{% for aksi, judul in JENIS_KEPUTUSAN %}", JENIS_KEPUTUSAN),
            ("mutu.html", "{% for aksi, judul in JENIS_MUTU %}", JENIS_MUTU)):
        tpl = (akar / berkas).read_text()
        assert gelung in tpl, berkas
        for aksi, _ in daftar:
            assert f'"{aksi}"' not in tpl, f"id aksi {aksi} diketik lagi di {berkas}"
        for _, judul in daftar:
            assert judul not in tpl, f"judul blok diketik lagi di {berkas}: {judul}"


def test_pembagian_dua_layar_dari_satu_sumber():
    """Kedua daftar dipotong dari `services.keputusan.JENIS` — bukan dua tupel
    yang ditulis tangan lalu dijaga cocok oleh ingatan orang."""
    from app.services import keputusan as K
    from app.web import layar_keputusan

    kode = inspect.getsource(layar_keputusan)
    assert "K.blok(mutu=False)" in kode and "K.blok(mutu=True)" in kode
    assert "AKSI_DIKENAL: tuple[str, ...] = K.SEMUA" in kode
    # Dan golongan mutu memang yang pindah — bukan tebakan dari nama id-nya.
    assert sorted(a for a, _ in JENIS_MUTU) == sorted(K.GOLONGAN[K.MUTU])


def test_ada_jaring_untuk_jenis_yang_belum_punya_blok():
    """Uji di atas menjaga saat build; jaring ini menjaga saat jalan. Keduanya
    perlu: yang satu menuntut orang menambah blok, yang lain memastikan kartunya
    tetap terlihat sebelum orang itu sempat."""
    import pathlib

    akar = pathlib.Path(__file__).resolve().parents[1] / "app/web/templates"
    tpl = (akar / "keputusan.html").read_text()
    assert 'rejectattr("aksi", "in", AKSI_DIKENAL)' in tpl
    assert "Keputusan lain" in tpl
    # Jaringnya menyaring SELURUH kerja meja, bukan cuma yang digambar layar
    # ini — jenis tak dikenal yang kebetulan bergolongan mutu tetap tertangkap.
    assert 'semua_meja|rejectattr' in tpl
    # Dan jaringnya SATU. Dua jaring akan menggambar jenis ketujuh dua kali:
    # sekali di tiap layar, sebagai dua pekerjaan yang sebenarnya satu.
    mutu = (akar / "mutu.html").read_text()
    assert "rejectattr" not in mutu, "layar mutu tak boleh punya jaring kedua"


# ── Lencana: tiap layar menjanjikan tepat yang digambarnya ──
#
# QA 24c/24e menemukan galat kelas ini hidup di app Meja: lencananya 8, layarnya
# 7. Pemisahan layar adalah kesempatan paling besar untuk melahirkannya lagi di
# Pos Produksi — pintu yang berjanji 8 sementara layarnya menggambar 6.

def test_lencana_tiap_layar_sama_dengan_isinya():
    from app.services.berjalan import Baris, Berjalan

    meja = [Baris(kode=a, isi="", keadaan="", aksi=a) for a in AKSI_DIKENAL]
    b = Berjalan(meja=meja)
    n = b.lencana()
    assert n["KEPUTUSAN"] == len(JENIS_KEPUTUSAN)
    assert n["MUTU"] == len(JENIS_MUTU)
    # Tak ada yang hilang di antara keduanya, dan tak ada yang terhitung dua kali.
    assert n["KEPUTUSAN"] + n["MUTU"] == len(meja)


def test_pintu_mutu_padam_saat_pencatatan_mutu_dimatikan():
    """Pabrik yang mematikan pencatatan mutu tak boleh ditawari pintu yang
    isinya SELALU nol — lencana yang tak pernah bisa dinolkan mengajari orang
    mengabaikan lencana. Halamannya tetap bisa dibuka lewat alamat, dan di sana
    ia menyebut sebabnya."""
    from app.services.berjalan import Berjalan

    assert Berjalan().lencana()["PINTU_MATI"] == ()
    assert Berjalan(mutu_aktif=False).lencana()["PINTU_MATI"] == ("mutu",)

    import pathlib
    tpl = (pathlib.Path(__file__).resolve().parents[1]
           / "app/web/templates/mutu.html").read_text()
    assert "{% if not MUTU_AKTIF %}" in tpl
    assert "Pencatatan mutu dimatikan" in tpl
    assert "/pengaturan" in tpl, "sebabnya disebut tanpa jalan membetulkannya"


def test_laci_menawarkan_mutu_hanya_ke_view_meja():
    """Operator tidak melihat halaman ini sama sekali (pemilik, 24 September
    2026): yang ia lihat adalah mutu BARANGNYA, di kartu Stok dan kartu proses.
    Menilai mutu dan menagih penilaiannya dua pekerjaan berbeda."""
    from app.web.layar import MEJA
    from app.web.nav import JUDUL, TAB

    baris = [t for t in TAB if t[0] == "mutu"]
    assert len(baris) == 1, "pintu Mutu & QC tak ada di laci"
    kunci, alamat, nama, ket, view = baris[0]
    assert alamat == "/mutu" and view is MEJA
    assert nama == "Mutu & QC"
    # Keterangan menyebut PEKERJAANNYA, bukan mengulang judulnya.
    assert ket and ket != nama and nama.lower() not in ket.lower()
    # Judul bilah atas diturunkan dari daftar yang sama — nama layar tak pernah
    # berbeda antara pintu dan judulnya.
    assert JUDUL["mutu"] == nama


def test_gerbang_halaman_mutu_sama_dengan_keputusan():
    """Memisahkan layarnya tidak memindahkan wewenangnya."""
    from app.web import layar_keputusan as L

    for fungsi in (L.halaman_keputusan, L.halaman_mutu):
        tanda = inspect.signature(fungsi).parameters["akun"].default
        assert getattr(tanda, "dependency", None) is not None
        assert tanda.dependency.__name__ == "butuh_admin", fungsi.__name__


def test_pencocokan_output_tak_lagi_ditagih_tetapi_koreksinya_tetap_ada():
    """Keputusan pemilik 24 September 2026: "pencocokan hasil giling hapus saja.
    yang mencatat hasil giling hanya operator. jika ada kesalahan sudah ada di
    perbaiki hasil giling."

    Yang hilang TAGIHANNYA — kartu "Output belum diverifikasi" yang tumbuh satu
    baris tiap giling ditutup. Yang TETAP adalah aksinya: tombol "Perbaiki hasil
    giling" di kartu layar Stok memanggil `verify_output`, dan menghapus aksinya
    berarti menghapus satu-satunya jalan membetulkan angka yang salah catat.
    """
    import pathlib

    from app.services import keputusan as K

    assert "verify_output" not in K.SEMUA, "tagihan pencocokan output kembali"
    assert "verify_output" not in _aksi_yang_dikirim_ke_meja(), \
        "kartunya kembali dikirim ke meja"

    akar = pathlib.Path(__file__).resolve().parents[1]
    # Aksinya tetap hidup, dan tetap dipanggil dari kartu Stok.
    api = (akar / "app/web/api.py").read_text()
    assert '"id": "verify_output"' in api and "/api/actions/verify-output" in api
    stok = (akar / "hmu_tampilan/templates/stok.html").read_text()
    assert "buka=verify_output" in stok, "tombol Perbaiki hasil giling ikut hilang"
    # Namanya sama di kedua tempat: dua nama untuk satu pekerjaan membuat orang
    # mengira ada dua pekerjaan.
    assert "Perbaiki hasil giling" in api and "Perbaiki hasil giling" in stok


def test_hpp_pk_tak_lagi_menuntut_verifikasi():
    """Kalau tuntutan itu tinggal, HPP PK berhenti terisi diam-diam.

    `hpp_per_kg_pk` dulu menjawab None tanpa `berat_output_final_kg` — aman
    selama tiap giling ditagih verifikasi. Begitu tagihannya dihapus, hampir
    tak ada lot yang punya angka itu, dan HPP yang kosong tak menjatuhkan apa
    pun: ia cuma hilang dari laporan. Sumbernya kini sama dengan stok —
    terverifikasi bila ada, selain itu progres terakhir operator.
    """
    from app.services import transfer

    kode = inspect.getsource(transfer.hpp_per_kg_pk)
    assert "MillingProcessVerification" not in kode, "tuntutan verifikasi kembali"
    assert "bd.hpp_penuh" in kode


def test_gerbang_permintaan_pk_dua_arah():
    """Bagian kedua keputusan pemilik 24 September 2026: operator Gudang 2 boleh
    MEMINTA lot PK Gudang 1; yang memindahkan tetap Admin.

    Dua arah, dan keduanya di RUTE — menyembunyikan pintu bukan penjagaan:
    alamatnya bisa diketik, dan lembar yang masih terbuka di layar orang lain
    masih bisa mengirim.
    """
    from app.web import api

    minta = inspect.getsource(api.act_minta_pk_g1)
    # Operator Gudang 2 — dan BUKAN admin: ia bisa memindahkan langsung, dan
    # permintaan kepada diri sendiri cuma satu baris yang harus ditutup sendiri.
    assert "_is_g2_operator(user) and not can_see_financials(user)" in minta

    tolak = inspect.getsource(api.act_tolak_permintaan_pk)
    assert "can_transfer_pk(user)" in tolak, "menolak permintaan bukan wewenang operator"

    # Dan izin memindahkan TIDAK berubah: yang lahir permintaan, bukan izin.
    from app.peran import can_transfer_pk

    class _Op:
        role = "operator"

    assert not can_transfer_pk(_Op()), "operator mendadak boleh memindahkan PK"


def test_tombol_minta_hanya_untuk_view_polesan():
    """Operator selepan tak boleh melihatnya (bukan pekerjaannya), Admin tak
    membutuhkannya."""
    import pathlib

    from app.web import layar_stok

    assert "boleh_minta=view == POLESAN" in inspect.getsource(layar_stok.halaman_stok)
    tpl = (pathlib.Path(__file__).resolve().parents[1]
           / "hmu_tampilan/templates/stok.html").read_text()
    assert "{% if boleh_minta and not l.berjalan %}" in tpl
    # Yang sudah diminta menyebut keadaannya, bukan menawarkan tombol kedua.
    assert "{% if l.diminta_oleh %}" in tpl
    assert "buka=minta_pk_g1" in tpl
