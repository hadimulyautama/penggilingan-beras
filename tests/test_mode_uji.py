"""Penjaga mode uji.

Fitur ini menghapus data di basis yang DIPAKAI BERSAMA dua aplikasi lain.
Versi pertamanya memakai `TRUNCATE ... CASCADE` dan menyapu seluruh tiket
timbang — 2 menjadi 0 — karena CASCADE merambat keluar lewat foreign key yang
MASUK, ke tabel yang produksi bahkan tak mengenalnya. Uji di sinilah yang
menangkapnya sebelum terkirim.
"""
from __future__ import annotations

import asyncio
import inspect
import re

import pytest

from tests.bantu import kode_saja

from app.database import Base
from app.web import mode_uji


def test_tak_satu_pun_tabel_timbangan_dalam_jangkauan():
    """Sasaran penghapusan hanya tabel yang didefinisikan produksi sendiri."""
    assert not [t for t in Base.metadata.tables if t.startswith("timbangan")]
    assert not [t for t in mode_uji._tabel_dihapus() if t.startswith("timbangan")]


def test_tabel_milik_bersama_dipertahankan():
    """Tiga tabel yang tampak "milik produksi" padahal dipakai aplikasi lain.

    `suppliers` ditunjuk Timbangan dengan kolom WAJIB ISI; `kantor_config` &
    `kantor_llm_usage` memuat kill-switch dan BATAS BIAYA LLM yang dipakai
    bersama layanan Kantor. Tak satu pun terlihat asing dari namanya saja.
    """
    for nama in ("suppliers", "kantor_config", "kantor_llm_usage"):
        assert nama in mode_uji.DIPERTAHANKAN, nama
        assert nama not in mode_uji._tabel_dihapus(), nama


def test_akun_dan_alat_dipertahankan():
    """Menghapus akun berarti mengunci diri sendiri di luar aplikasi."""
    for nama in ("users", "produksi_akun", "warehouses", "silos", "dryers"):
        assert nama in mode_uji.DIPERTAHANKAN, nama


def test_tak_memakai_cascade():
    """CASCADE-lah yang dulu menyapu tiket. Ia tak boleh kembali."""
    kode = kode_saja(mode_uji._kosongkan)
    assert "CASCADE" not in kode.upper()
    assert "DELETE FROM" in kode


def test_urutan_hapus_dari_metadata_bukan_daftar_tangan():
    """Daftar yang ditulis tangan akan basi pada tabel berikutnya."""
    assert "Base.metadata.sorted_tables" in kode_saja(mode_uji._kosongkan)


@pytest.mark.asyncio
async def test_mati_total_saat_mode_uji_padam():
    """Mematikannya bukan menyembunyikan tombol — endpointnya ikut menolak."""
    from fastapi import HTTPException

    from app.config import settings

    asli = settings.mode_uji
    try:
        settings.mode_uji = False
        with pytest.raises(HTTPException) as e:
            mode_uji._wajib_mode_uji()
        assert e.value.status_code == 404
        settings.mode_uji = True
        mode_uji._wajib_mode_uji()      # tidak melempar
    finally:
        settings.mode_uji = asli


def test_setelan_pabrik_tidak_ikut_terhapus():
    """Ia segolongan dengan alat: menggambarkan PABRIKNYA, bukan pekerjaannya.
    Menghapusnya berarti diam-diam mengembalikan target kadar air dan daftar
    sebab berhenti ke bawaan, tanpa satu layar pun menyebutkan itu terjadi."""
    from app.web.mode_uji import DIPERTAHANKAN, _tabel_dihapus

    assert "setelan_pabrik" in DIPERTAHANKAN
    assert "setelan_pabrik" not in _tabel_dihapus()


def test_nomor_urut_hanya_untuk_tabel_berkolom_id():
    """`setelan_pabrik` berkunci `kunci`, bukan `id`. Penjaga
    `pg_get_serial_sequence(...) IS NOT NULL` tak menolong — Postgres sudah
    menyerah saat mencari kolomnya, dan seluruh penghapusan jatuh dengan
    Internal Server Error SESUDAH DELETE-nya terlanjur berjalan."""
    import inspect

    from app.database import Base
    from app.web import mode_uji

    sumber = inspect.getsource(mode_uji._kosongkan)
    assert 'berid = {t.name for t in Base.metadata.sorted_tables if "id" in t.columns}' in sumber
    assert "for nama in [n for n in urut if n in berid]:" in sumber

    # Dan memang ada tabel tanpa `id` di basis data ini — kalau tidak, tesnya
    # menjaga sesuatu yang tak pernah terjadi.
    tanpa_id = {t.name for t in Base.metadata.sorted_tables if "id" not in t.columns}
    assert tanpa_id, "tak ada tabel tanpa id — penjaganya jadi tak berarti"


def test_tombol_kembalikan_data_uji():
    """Pemilik: harus ada tombol reset agar data dummy kembali seperti awal
    dan data entry test bisa terhapus.

    Menghapus saja meninggalkan tiap layar kosong, dan sesudah itu tak ada
    yang bisa dicoba sampai seseorang mengisinya lagi dari laptop.
    """
    import inspect
    import pathlib

    from app.web import mode_uji

    assert hasattr(mode_uji, "ulangi")
    sumber = inspect.getsource(mode_uji.ulangi)
    assert "_wajib_mode_uji()" in sumber, "di luar mode uji tak boleh ada sama sekali"
    assert "akun.is_super" in sumber
    assert "await _kosongkan()" in sumber, "menghapus dulu, baru mengisi"
    assert "data_uji.isi(akun)" in sumber

    # Kalimatnya BERBEDA dari tombol hapus. Dua tombol yang menuntut kalimat
    # sama adalah dua tombol yang bisa tertukar justru saat orangnya sudah
    # hafal mengetiknya.
    assert mode_uji.KALIMAT_ULANG != mode_uji.KALIMAT
    assert f'"{mode_uji.KALIMAT_ULANG}"' in sumber or "KALIMAT_ULANG" in sumber

    html = (pathlib.Path(__file__).resolve().parents[1]
            / "app/web/templates/mode_uji.html").read_text()
    assert 'action="/pengaturan/mode-uji/ulangi"' in html
    assert "Kembalikan data uji" in html


def test_satu_isi_dipakai_skrip_dan_tombol():
    """Kalau skripnya punya salinan pengisiannya sendiri, data yang dibuat
    dari laptop dan data yang dibuat dari layar akan berbeda — dan yang diuji
    orang jadi bukan yang dipakai orang."""
    import pathlib

    from app.services import data_uji

    assert hasattr(data_uji, "isi")
    skrip = (pathlib.Path(__file__).resolve().parents[1]
             / "scripts/isi_dummy.py").read_text()
    assert "data_uji.isi(akun)" in skrip
    assert "IZIN_DUMMY" in skrip, "skripnya tetap berpagar"
    # Akun uji karangan tak dibuat lagi (21 September 2026): app uji coba
    # dipakai dengan akun yang sudah ada. Data boleh karangan, orangnya tidak.
    assert not hasattr(data_uji, "siapkan_akun")
    for kata in ("siapkan_akun", "SANDI_UJI", "hash_sandi"):
        assert kata not in skrip, kata


def test_data_uji_dibuat_lewat_endpoint_bukan_insert():
    """Baris yang disuntikkan langsung bisa saja mustahil menurut aturan
    aplikasinya sendiri, dan data uji yang mustahil membuat layarnya terlihat
    benar padahal menampilkan keadaan yang tak pernah bisa terjadi."""
    import inspect

    from app.services import data_uji

    sumber = inspect.getsource(data_uji.isi)
    # Pemilik: "data uji cukup tiket timbang saja. tidak usah ada proses yang
    # sudah berjalan. dan tidak usah ada data di list audit."
    #
    # Tak ada satu aksi pun yang dijalankan — dan itulah yang membuat List
    # audit tetap kosong: jejak hanya lahir dari aksi. Proses yang dijalankan
    # skrip membuktikan skripnya jalan, bukan membuktikan layarnya bisa
    # dipakai.
    assert "ASGITransport" not in sumber
    assert "/api/actions" not in sumber
    assert "_tiket(db, pemasok)" in sumber
    # Satu-satunya INSERT langsung: tiket timbang, milik aplikasi lain.
    insert = inspect.getsource(data_uji)
    assert insert.count("INSERT INTO") == 2, "hanya pemasok & tiket timbang"
    assert "INSERT INTO timbangan_transaksi" in insert


def test_data_uji_menolak_jembatan_timbang_yang_dipakai():
    """`timbangan_transaksi` milik aplikasi Timbangan, dan aplikasi itu
    membaca basis data yang SAMA. Tiket karangan yang ditulis ke sana tidak
    berhenti di layar Produksi — ia muncul di layar petugas timbang, di antara
    tiket truk yang sungguh datang hari itu. Sekali ini terjadi, dan
    pemiliknya yang menemukannya."""
    import inspect

    from app.services import data_uji
    from app.web import mode_uji

    assert hasattr(data_uji, "JembatanDipakai")
    sumber = inspect.getsource(data_uji.isi)
    assert "jembatan_sungguhan(db)" in sumber
    assert "raise JembatanDipakai(" in sumber
    # Diperiksa SEBELUM satu baris pun ditulis.
    assert sumber.index("jembatan_sungguhan") < sumber.index("_pemasok(db)")

    # Penjaganya menyaring dengan AWALAN KODE, dan awalan itu ditulis di SATU
    # tempat: `AWALAN_TIKET_UJI`. Yang diperiksa di sini bukan kalimat SQL-nya
    # (ia disusun dari daftar itu) melainkan bahwa TIAP awalan pembuat tiket
    # karangan benar-benar ikut disaring — awalan yang tertinggal membuat basis
    # data uji tampak seperti basis data pabrik yang sedang dipakai, dan
    # penjaga ini menolak pekerjaan yang justru harus boleh di sana.
    assert "TRX-UJI-" in data_uji.AWALAN_TIKET_UJI
    assert "TRX-SIM-" in data_uji.AWALAN_TIKET_UJI, "tiket simulasi hari kerja"

    ditanya: list[str] = []

    class _Db:
        async def execute(self, stmt, *a, **k):
            ditanya.append(str(stmt))
            return _Hasil(0)

    asyncio.run(data_uji.jembatan_sungguhan(_Db()))
    assert len(ditanya) == 1
    for awalan in data_uji.AWALAN_TIKET_UJI:
        assert f"kode NOT LIKE '{awalan}%'" in ditanya[0]

    # Dan tombolnya menyampaikan alasannya, bukan jatuh dengan galat 500.
    tombol = inspect.getsource(mode_uji.ulangi)
    assert "data_uji.JembatanDipakai" in tombol
    assert "galat=str(e)" in tombol


# ══════════════════════════════════════════════════════════════════════
# X-05 — penjaga berjalan SEBELUM penghapusan, bukan sesudahnya
# ══════════════════════════════════════════════════════════════════════

class _Hasil:
    """Jawaban kueri secukupnya: `_kosongkan` cuma memakai tiga bentuk ini."""

    def __init__(self, nilai: int = 0, baris: list | None = None):
        self._nilai = nilai
        self._baris = baris or []

    def scalar_one(self) -> int:
        return self._nilai

    def scalar(self) -> int:
        return self._nilai

    def all(self) -> list:
        return self._baris


class _SesiPalsu:
    """Sesi yang MENCATAT apa yang dijalankan, bukan menjalankannya.

    Berkas uji ini tak punya basis data, dan yang perlu dibuktikan justru
    URUTANNYA: penjaga dijalankan sebelum satu baris pun dihapus. Sesi palsu
    menjawab itu dengan pasti — kalau tak ada satu pun `DELETE` yang tercatat,
    tak ada yang terhapus.
    """

    def __init__(self, jejak: list[str], tiket_sungguhan: int,
                 ada_tautan: bool = True):
        self.jejak = jejak
        #: Tiket SUNGGUHAN yang sudah DIBUKUKAN — yang tautannya akan dilepas.
        self.tiket_sungguhan = tiket_sungguhan
        #: Adakah kolom penaut dari `timbangan_transaksi` sama sekali. Basis
        #: data yang jembatannya dipakai TETAPI belum satu pun tiket dibukukan
        #: tetap punya kolomnya; yang kosong isinya, bukan kolomnya.
        self.ada_tautan = ada_tautan

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, klausa, params=None):
        sql = " ".join(str(klausa).split())
        self.jejak.append(sql)
        if "timbangan_transaksi" in sql and "NOT LIKE" in sql:
            return _Hasil(self.tiket_sungguhan)
        # Daftar tautan masuk — dikenali dari kueri katalognya. Tanpa ini
        # penjaga tak punya kolom untuk ditanyai, dan ujinya membuktikan
        # kebalikan dari yang dimaksudkan.
        if "information_schema" in sql or "pg_constraint" in sql or "confrelid" in sql:
            baris = ([("timbangan_transaksi", "purchase_batch_id",
                       "purchase_batches", False)] if self.ada_tautan else [])
            return _Hasil(0, baris)
        return _Hasil(0, [])

    async def commit(self):
        self.jejak.append("COMMIT")


def _jalankan_kosongkan(monkeypatch, tiket_sungguhan: int,
                        ada_tautan: bool = True) -> tuple[str | None, list[str]]:
    """Jalankan `_kosongkan` tanpa basis data; kembalikan pesan & jejak SQL."""
    import asyncio

    from app.services import seed as _seed

    jejak: list[str] = []
    monkeypatch.setattr(mode_uji, "SessionLocal",
                        lambda: _SesiPalsu(jejak, tiket_sungguhan, ada_tautan))
    # `seed_master` di ekor `_kosongkan` membuka sesinya SENDIRI — kalau tak
    # ikut diganti, ujinya menempel ke Postgres sungguhan dan gagal karena
    # alasan yang sama sekali lain.
    async def _diam():
        jejak.append("SEED_MASTER")
    monkeypatch.setattr(_seed, "seed_master", _diam)
    return asyncio.run(mode_uji._kosongkan()), jejak


def test_satu_tiket_sungguhan_membatalkan_SEBELUM_menghapus(monkeypatch):
    """X-05. Penjaga "ada tiket timbang sungguhan" dulu baru berjalan saat
    MENGISI, sesudah `_kosongkan()` selesai. Hasilnya: seluruh batch sungguhan
    dan jejak auditnya terhapus, penolakannya datang belakangan, dan tiket
    aslinya muncul lagi sebagai belum diproses — bisa dibukukan dua kali.

    Satu tiket sungguhan yang SUDAH DIBUKUKAN sudah cukup untuk membatalkan,
    dan pembatalan itu harus terjadi sebelum satu baris pun hilang.

    Yang diuji "sudah dibukukan", bukan "ada" — sejak 25 September 2026 itulah
    pertanyaan penjaganya. Yang dirusak penghapusan ini bukan baris tiketnya
    (ia milik Timbangan dan tak tersentuh) melainkan TANDA bahwa tiket itu
    sudah dibukukan; tanpa satu pun tanda, tak ada yang bisa hilang.
    """
    pesan, jejak = _jalankan_kosongkan(monkeypatch, tiket_sungguhan=1)

    assert pesan, "penghapusan diteruskan padahal ada tiket sungguhan"
    hapus = [s for s in jejak if s.startswith("DELETE FROM")]
    assert not hapus, f"{len(hapus)} tabel sudah dihapus sebelum ditolak"
    # Tautan dari luar pun tak boleh dilepas: melepas `purchase_batch_id`
    # membuat tiket sungguhan kembali tampak belum diproses.
    assert not [s for s in jejak if s.startswith("UPDATE")]
    assert "COMMIT" not in jejak


def test_tanpa_tiket_sungguhan_penghapusan_tetap_jalan(monkeypatch):
    """Penjaga yang menolak segalanya bukan penjaga, ia kerusakan. Di basis
    data yang memang khusus menguji, tombolnya harus tetap bekerja."""
    pesan, jejak = _jalankan_kosongkan(monkeypatch, tiket_sungguhan=0)

    assert pesan is None, pesan
    dihapus = [s for s in jejak if s.startswith("DELETE FROM")]
    assert dihapus
    assert "COMMIT" in jejak

    # Dan yang dihapus memang HANYA milik produksi. Diperiksa dari perintah
    # yang sungguh dijalankan, bukan dari daftar niatnya: daftar bisa benar
    # sementara yang dikirim ke basis data sudah lain.
    nama = {s.split('"')[1] for s in dihapus}
    assert not [n for n in nama if n.startswith(("timbangan_", "kantor_"))]
    assert "activity_logs" not in nama, "jejak audit ikut terhapus"
    assert "produksi_akun" not in nama and "users" not in nama
    assert not [n for n in nama if n.startswith("alembic_version")]


def test_penjaga_dipasang_di_kosongkan_bukan_di_tiap_rute():
    """DUA tombol memanggil `_kosongkan` — "Hapus data uji" dan "Kembalikan
    data uji". Penjaga yang disalin ke tiap rute cepat atau lambat akan
    tertinggal di salah satunya, persis seperti yang sudah terjadi pada
    daftar tabelnya dulu."""
    import inspect

    from tests.bantu import kode_saja

    kode = kode_saja(mode_uji._kosongkan)
    assert "tiket_sungguhan_tertaut" in kode
    # Sebelum tautan dilepas DAN sebelum satu DELETE pun disusun.
    assert kode.index("tiket_sungguhan_tertaut") < kode.index("UPDATE")
    assert kode.index("tiket_sungguhan_tertaut") < kode.index("DELETE FROM")

    # Dan kedua rute memang lewat sana, bukan punya jalannya sendiri.
    for rute in (mode_uji.hapus, mode_uji.ulangi):
        assert "await _kosongkan()" in inspect.getsource(rute), rute.__name__


def test_activity_logs_tak_pernah_ikut_terhapus():
    """Jejak audit bersifat TAMBAH-SAJA. Ia satu-satunya catatan siapa
    mengerjakan apa, dan menghapusnya bersama data uji berarti membuang bukti
    yang justru dipakai menelusuri kesalahan yang sedang diperiksa."""
    from app.web.mode_uji import DIPERTAHANKAN, _tabel_dihapus

    assert "activity_logs" in DIPERTAHANKAN
    assert "activity_logs" not in _tabel_dihapus()


# ══════════════════════════════════════════════════════════════════════
# X-01 — tak ada lagi jalan TRUNCATE ... CASCADE di basis data bersama
# ══════════════════════════════════════════════════════════════════════

def test_skrip_reset_data_sql_sudah_tiada():
    """X-01. Skrip itu men-TRUNCATE ... CASCADE SEMUA tabel kecuali enam, di
    basis data yang dipakai bersama tiga aplikasi. Yang ikut kosong: seluruh
    tabel timbangan, seluruh kantor_* termasuk kill-switch & batas biaya AI,
    `produksi_akun` sehingga tak ada yang bisa masuk, `pelanggan`,
    `setelan_pabrik`, dan tiga tabel versi migrasi.

    Dokumen deploy menyuruh menjalankannya DI BASIS DATA PRODUKSI.
    """
    import pathlib

    akar = pathlib.Path(__file__).resolve().parents[1]
    assert not (akar / "scripts/reset_data.sql").exists()

    # Larangan butanya tak berguna: `simulasi_gabah.py` memang mengosongkan
    # segalanya, dan itu memang gunanya. Yang membedakannya dari skrip yang
    # dibuang adalah PAGARNYA — ia menolak berjalan kecuali alamat basis
    # datanya jelas-jelas milik simulasi, sedangkan yang dibuang justru
    # disuruh dijalankan di basis data produksi oleh dokumennya sendiri.
    #
    # Jadi yang dijaga di sini aturannya, bukan katanya: siapa pun boleh
    # mengosongkan, asal tak bisa salah alamat.
    for berkas in (akar / "scripts").rglob("*.py"):
        isi = berkas.read_text(errors="ignore")
        if "TRUNCATE" not in isi.upper():
            continue
        assert "_IZIN" in isi, (
            f"{berkas.name} mengosongkan tabel tanpa pagar alamat basis data")
        # Isi pagarnya HANYA alamat loopback. Satu entri yang menunjuk ke
        # mesin lain sudah cukup membuat pagarnya jadi hiasan, dan itu tak
        # akan terlihat dari nama berkasnya.
        tuple_izin = re.search(r"_IZIN\s*=\s*\(([^)]*)\)", isi)
        assert tuple_izin, f"{berkas.name}: _IZIN tak terbaca"
        alamat = re.findall(r"[\"']([^\"']+)[\"']", tuple_izin.group(1))
        assert alamat, f"{berkas.name}: pagar kosong"
        for a in alamat:
            assert a.startswith(("127.0.0.1:", "localhost:")), (
                f"{berkas.name} berpagar ke alamat bukan-lokal: {a}")
    for berkas in (akar / "scripts").rglob("*.sql"):
        assert False, f"{berkas.name} — SQL tempel-jalan tak lagi disimpan di sini"


def test_dokumen_deploy_tak_lagi_menyuruh_mengosongkan_db_bersama():
    """Dokumen yang menyuruh perbuatan berbahaya sama berbahayanya dengan
    kodenya — ia dibaca orang yang justru sedang tidak yakin.

    Yang diperiksa PERINTAHNYA, bukan penyebutan katanya. Dokumen barunya
    memang menyebut `TRUNCATE ... CASCADE` dan `reset_data.sql` — untuk
    menerangkan kenapa keduanya dibuang, berikut daftar apa saja yang dulu
    ikut terhapus. Uji yang menolak penyebutan itu menghukum penjelasan yang
    baik, dan itu pelajaran yang sudah dibayar sekali di repo ini lewat
    `tests/bantu.py::kode_saja`.

    Jadi baris kutipan (`>`, tempat peringatan tinggal) dan baris bernomor
    yang menerangkan Mode Uji dibuang dulu; sisanya yang menjadi perintah.
    """
    import pathlib

    doc = (pathlib.Path(__file__).resolve().parents[1]
           / "docs/DEPLOY-RAILWAY.md").read_text()

    perintah = "\n".join(
        b for b in doc.splitlines()
        if not b.lstrip().startswith(">")
        and "**`DELETE`, bukan" not in b
    )
    assert "reset_data.sql" not in perintah
    assert "TRUNCATE" not in perintah.upper()
    assert "RESTART IDENTITY" not in perintah.upper()
    # Menambah Postgres baru memecah basis data yang justru harus satu:
    # produksi, timbangan, dan Kantor saling membaca tabel yang sama.
    assert "Postgres baru" not in perintah
    # Dan pembacanya diarahkan ke jalan yang aman.
    assert "Mode Uji" in doc
    # Peringatannya sendiri HARUS ada — skrip yang hilang tanpa keterangan
    # akan ditulis ulang oleh orang berikutnya yang mencarinya.
    assert "reset_data.sql" in doc, "kenapa ia dibuang tak diterangkan"


def test_tiket_sungguhan_yang_belum_dibukukan_tak_menghalangi(monkeypatch):
    """Keadaan pabrik ini pada 25 September 2026, dan sebab perubahannya.

    Basis data produksi memuat 133 tiket timbang sungguhan — dan TAK SATU PUN
    tertaut ke Pos Produksi: `purchase_batch_id` dan `pk_purchase_batch_id`
    kosong di seluruh baris. Penghapusan di sini karena itu tidak menyentuh
    jembatan sama sekali: tak ada tanda "sudah dibukukan" yang bisa hilang.

    Penjaga lama menolaknya dengan kalimat tentang kerusakan yang tidak
    mungkin terjadi, dan pemilik yang memang berhak mengosongkannya berhenti
    di layar itu. Pagar yang menolak pekerjaan yang harus boleh dilakukan
    akhirnya dilangkahi lewat jalan yang tak berpagar sama sekali.
    """
    pesan, jejak = _jalankan_kosongkan(monkeypatch, tiket_sungguhan=0)

    assert pesan is None, pesan
    assert [s for s in jejak if s.startswith("DELETE FROM")]
    assert "COMMIT" in jejak


def test_penjaga_bertanya_pada_KOLOM_penautnya_bukan_pada_tiketnya(monkeypatch):
    """Pertanyaannya "adakah tautan yang akan dilepas", jadi ia harus benar
    ketika kolom penautnya sendiri tak ada — basis data uji murni, yang tak
    pernah dipakai Timbangan sama sekali."""
    pesan, jejak = _jalankan_kosongkan(monkeypatch, tiket_sungguhan=7,
                                       ada_tautan=False)

    # Tujuh tiket sungguhan, TETAPI tak ada kolom yang menaut: tak ada yang
    # bisa rusak, jadi tak ada alasan menolak.
    assert pesan is None, pesan
    assert "COMMIT" in jejak


def test_mengisi_data_uji_tetap_ditolak_oleh_penjaga_yang_lebih_lebar():
    """Dua pertanyaan berbeda, dan yang satu TIDAK ikut dilonggarkan.

    Mengisi data uji melahirkan tiket KARANGAN, dan tiket karangan muncul di
    layar petugas timbang di antara truk yang benar-benar datang. Bahaya itu
    tak bergantung pada ada tidaknya tautan — jadi penjaganya tetap
    `jembatan_sungguhan`, yang menolak begitu jembatannya dipakai sungguhan.
    """
    from tests.bantu import kode_saja

    from app.services import data_uji

    kode = kode_saja(data_uji.isi)
    assert "jembatan_sungguhan" in kode
    assert "tiket_sungguhan_tertaut" not in kode, \
        "penjaga pengisian ikut dilonggarkan — tiket karangan akan lahir di " \
        "basis data yang melayani jembatan sungguhan"
