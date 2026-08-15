"""Agent Kantor AI — asisten eksekutif (dokumen, arsip, HR) di atas mesin Kantor.

Pola agentic (mirip app/ai/agent.py): model (Sonnet) BOLEH memanggil tool READ
(panduan arsip, cek nama file) untuk menjawab, ATAU MENGUSULKAN aksi
KONSEKUENSIAL (terbitkan nomor surat + susun naskah). Aksi tulis TIDAK
dieksekusi agent — diusulkan, dikonfirmasi pengguna, lalu dijalankan
deterministik di app/kantor/bot.py. Sesuai prinsip: semua aksi konsekuensial
butuh persetujuan.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.ai.base import _date_context
from app.ai import guard
from app.config import settings
from app.services import analytics
from app.kantor import arsip_fisik
from app.kantor import aturan
from app.kantor import gajihub
from app.kantor import kendali
from app.kantor import it_aset
from app.kantor import kledo
from app.kantor import produksi
from app.kantor import rbac
from app.kantor import router as domain_router
from app.kantor import mail_gmail
from app.kantor import ocr
from app.kantor import pengetahuan
from app.kantor.dokumen import konsistensi
from app.kantor.drive import aksi as drive_aksi
from app.kantor.drive import operasi as drive_ops
from app.kantor.drive import taksonomi as tx

log = logging.getLogger("kantor.agent")


@dataclass
class KantorReply:
    """Hasil satu giliran agent Kantor."""

    text: str | None = None    # jawaban final untuk ditampilkan
    aksi: dict | None = None    # {"jenis","params","ringkasan"} — perlu konfirmasi


def _hari_ini() -> date:
    return datetime.now(ZoneInfo(settings.app_timezone)).date()


def _daftar_kategori() -> str:
    """Baris 'kode — nama: isi' untuk kategori digital berkode angka (00–11)."""
    return "\n".join(
        f"  {k.kode} — {k.nama}: {k.isi}"
        for k in tx.KATEGORI if k.kode.isdigit()
    )


# ─────────────────────────── Definisi tool ───────────────────────────

_TOOLS = [
    {
        "name": "panduan_arsip",
        "description": (
            "Beri panduan pengarsipan sebuah dokumen: folder DIGITAL mana (kode "
            "00–11) DAN ordner FISIK mana (warna/golongan/retensi). Pakai bila "
            "pengguna bertanya 'dokumen X disimpan/diarsip di mana'. Pilih "
            "kode_kategori digital paling cocok dari daftar kategori di system prompt."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "kode_kategori": {
                    "type": "string",
                    "description": "Kode kategori digital 00–11 yang paling cocok.",
                }
            },
            "required": ["kode_kategori"],
        },
    },
    {
        "name": "cek_nama_file",
        "description": (
            "Periksa satu nama file terhadap aturan penamaan baku; kembalikan "
            "temuan (error/peringatan) + usulan nama yang sudah dirapikan. Pakai "
            "bila pengguna minta cek/koreksi nama file, atau menyebut nama file "
            "yang berantakan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nama_file": {
                    "type": "string",
                    "description": "Nama file lengkap beserta ekstensi.",
                }
            },
            "required": ["nama_file"],
        },
    },
    {
        "name": "siapkan_surat_tugas",
        "description": (
            "USULKAN penerbitan Surat Tugas resmi (kode ST, divisi HR). JANGAN "
            "panggil sebelum data lengkap: nama, jabatan, uraian tugas, tempat, "
            "dan waktu pelaksanaan. Bila ada yang kurang, TANYAKAN dulu — jangan "
            "mengarang. Ini AKSI KONSEKUENSIAL (menerbitkan nomor resmi ke "
            "register): sistem akan minta konfirmasi pengguna sebelum dijalankan. "
            "Jangan mengaku sudah menerbitkan."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nama": {"type": "string", "description": "Nama orang yang ditugaskan."},
                "jabatan": {"type": "string", "description": "Jabatan yang bersangkutan."},
                "tugas": {"type": "string", "description": "Uraian tugas yang diberikan."},
                "tempat": {"type": "string", "description": "Tempat pelaksanaan tugas."},
                "waktu": {
                    "type": "string",
                    "description": "Kapan tugas dilaksanakan, mis. '5 Agustus 2026'.",
                },
                "tanggal_surat": {
                    "type": "string",
                    "description": "Tanggal surat diterbitkan (YYYY-MM-DD). Kosongkan → hari ini.",
                },
                "no_pegawai": {
                    "type": "string",
                    "description": "Nomor pegawai bila ada; '-' bila tidak diketahui.",
                },
            },
            "required": ["nama", "jabatan", "tugas", "tempat", "waktu"],
        },
    },
    {
        "name": "daftar_transit",
        "description": (
            "Lihat isi folder _TRANSIT (INBOX file baru) di Google Drive. Read-only. "
            "Pakai bila pengguna tanya 'apa saja file di transit/inbox'."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "daftar_folder",
        "description": (
            "Lihat isi 1 folder kategori di Drive (read-only). Pakai untuk 'apa isi "
            "folder Keuangan/SDM/kategori 03'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "kategori": {
                    "type": "string",
                    "description": "Kode kategori '00'–'11'/'99' ATAU sebagian nama folder (mis. 'SDM').",
                }
            },
            "required": ["kategori"],
        },
    },
    {
        "name": "buka_folder",
        "description": (
            "Lihat isi folder mana pun via PATH — BISA masuk subfolder sedalam apa "
            "pun (read-only). Pakai bila pengguna menyebut subfolder, mis. "
            "'00/KONTRAK', '03/01 - Data & Identitas Karyawan/04 - Staff'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Jalur folder dipisah '/'. Segmen-1 = kode/nama kategori root.",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "cari_file",
        "description": (
            "Cari file/folder di Drive yang namanya mengandung kata tertentu "
            "(read-only, sampai 50 hasil). Pakai untuk 'cari file X'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "kata": {"type": "string", "description": "Kata/sebagian nama yang dicari."}
            },
            "required": ["kata"],
        },
    },
    {
        "name": "baca_dokumen",
        "description": (
            "Baca ISI teks sebuah dokumen di Drive (read-only) — untuk memahami isi "
            "file. Mendukung Google Docs/Sheets/Slides, docx, PDF. Gambar/scan tak "
            "terekstrak. CATATAN: untuk Google Sheet, ini hanya membaca tab PERTAMA dan "
            "bisa terpotong. Untuk Sheet ber-banyak-tab atau isi besar, pakai "
            "daftar_tab_sheet lalu baca_sheet (per-tab, tak kepotong dini)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nama": {"type": "string", "description": "Nama file (persis lebih baik) yang dibaca."}
            },
            "required": ["nama"],
        },
    },
    {
        "name": "baca_gambar",
        "description": (
            "Baca teks dari FILE GAMBAR (.jpg/.png) atau PDF hasil SCAN via OCR "
            "(pengenalan teks dari gambar). Pakai bila baca_dokumen mengembalikan "
            "kosong / 'kemungkinan gambar/scan', atau saat file jelas berupa foto/"
            "scan (mis. KTP, BPJS, surat berstempel yang di-scan). Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nama": {"type": "string", "description": "Nama file gambar/scan (persis lebih baik)."},
            },
            "required": ["nama"],
        },
    },
    {
        "name": "daftar_tab_sheet",
        "description": (
            "Daftar semua TAB (worksheet) dalam sebuah Google Sheet + ukuran tiap tab. "
            "Pakai LEBIH DULU sebelum baca_sheet bila belum tahu nama tab-nya, atau saat "
            "pengguna menyebut data yang mungkin ada di tab lain (mis. Keamanan, Akses, "
            "Perbankan, Offboarding)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nama_sheet": {"type": "string", "description": "Nama Google Sheet (persis lebih baik)."},
            },
            "required": ["nama_sheet"],
        },
    },
    {
        "name": "baca_sheet",
        "description": (
            "Baca isi sebuah TAB Google Sheet (read-only) — BUKAN cuma tab pertama, dan "
            "tanpa terpotong 3000 karakter seperti baca_dokumen. Sebutkan `tab` (nama "
            "worksheet, mis. 'Keamanan'); kosong = tab pertama. `rentang` opsional (mis. "
            "'A18:Z60') untuk membaca sebagian saat tab sangat besar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nama_sheet": {"type": "string", "description": "Nama Google Sheet (persis lebih baik)."},
                "tab": {"type": "string", "description": "Nama tab/worksheet yang dibaca (mis. 'Perbankan'). Kosong = tab pertama."},
                "rentang": {"type": "string", "description": "Opsional, notasi A1 (mis. 'A18:Z60') untuk baca sebagian tab besar."},
            },
            "required": ["nama_sheet"],
        },
    },
    {
        "name": "audit_draft_nyasar",
        "description": (
            "Pindai SELURUH Google Drive (semua folder & subfolder, sekali jalan) dan "
            "kembalikan daftar file 'draft' yang berada DI LUAR _TRANSIT. Pakai bila "
            "pengguna minta AUDIT menyeluruh draft nyasar / cek ke seluruh subfolder — "
            "JANGAN menelusuri folder satu per satu untuk ini."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "pindah_item",
        "description": (
            "USULKAN memindahkan sebuah FILE **atau FOLDER** ke folder lain. Untuk "
            "FOLDER, seluruh isinya ikut. AKSI KONSEKUENSIAL: tidak langsung jalan — "
            "diajukan ke pemilik lewat tombol persetujuan di Telegram. JANGAN mengaku "
            "sudah memindah. Bila nama ambigu (banyak yang cocok), TANYAKAN nama persis."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nama": {"type": "string", "description": "Nama file/folder yang dipindah (persis lebih baik)."},
                "tujuan": {
                    "type": "string",
                    "description": "PATH folder tujuan, mis. '02', '05/Invoice/PT Rajawali'.",
                },
            },
            "required": ["nama", "tujuan"],
        },
    },
    {
        "name": "rename_item",
        "description": (
            "USULKAN mengganti nama sebuah FILE **atau FOLDER**. AKSI KONSEKUENSIAL: "
            "diajukan ke pemilik lewat tombol persetujuan — tidak langsung jalan. "
            "JANGAN mengaku sudah mengganti. Ambigu → tanyakan nama persis."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nama_lama": {"type": "string", "description": "Nama file/folder saat ini (persis lebih baik)."},
                "nama_baru": {"type": "string", "description": "Nama baru yang diinginkan."},
            },
            "required": ["nama_lama", "nama_baru"],
        },
    },
    {
        "name": "hapus_item",
        "description": (
            "USULKAN menghapus sebuah FILE **atau FOLDER** (→ Sampah Drive, reversible "
            "~30 hari). Untuk FOLDER, isinya ikut ke Sampah. AKSI KONSEKUENSIAL: "
            "diajukan ke pemilik lewat tombol persetujuan — tidak langsung jalan. "
            "JANGAN mengaku sudah menghapus. Ambigu → tanyakan nama persis."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nama": {"type": "string", "description": "Nama file/folder yang dihapus (persis lebih baik)."},
            },
            "required": ["nama"],
        },
    },
    {
        "name": "buat_folder",
        "description": (
            "USULKAN membuat FOLDER baru. ATURAN: harus di dalam kategori inti "
            "(00–11/99) atau subfolder-nya (bukan di root), maksimal 4 level, induk "
            "harus sudah ada. AKSI KONSEKUENSIAL → diajukan ke pemilik lewat tombol. "
            "JANGAN mengaku sudah membuat."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Lokasi folder baru, mis. '09/Company Profile' atau "
                                   "'00/KONTRAK/PT Vendor Baru'. Segmen terakhir = nama folder baru.",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "buat_dokumen",
        "description": (
            "USULKAN membuat dokumen resmi .docx berkop PT HMU → disimpan ke _TRANSIT "
            "sebagai DRAFT. Untuk SEMUA jenis (Surat Tugas, Surat Keterangan, SK, "
            "Kontrak PKWT/PKWTT, Perjanjian, dll). Kamu menyusun `isi`; tool membungkus "
            "dengan kop resmi + tanda tangan Direktur Utama. AKSI KONSEKUENSIAL → "
            "diajukan ke pemilik lewat tombol. JANGAN mengaku sudah membuat. Bila data "
            "dokumen belum lengkap, TANYAKAN dulu."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "judul": {"type": "string", "description": "Judul dokumen, mis. 'Surat Tugas'."},
                "isi": {
                    "type": "string",
                    "description": "Badan dokumen (multi-baris). Markup: '[[C]]Teks' = sub-judul "
                                   "tengah; '[[TABEL]]' = titik sisip tabel (via tabel_json).",
                },
                "nomor": {"type": "string", "description": "Nomor surat resmi (opsional)."},
                "nama_file": {"type": "string", "description": "Nama file tanpa ekstensi (opsional; default=judul)."},
                "tembusan": {"type": "string", "description": "Daftar tembusan, pisah baris-baru atau ';' (opsional)."},
                "tabel_json": {
                    "type": "string",
                    "description": "JSON list-of-rows utk tabel, mis. '[[\"No\",\"Nama\"],[\"1\",\"Budi\"]]' "
                                   "(baris-1=header). Opsional.",
                },
            },
            "required": ["judul", "isi"],
        },
    },
    {
        "name": "buat_sheet",
        "description": (
            "USULKAN membuat Google Sheet BARU dari nol (native, bisa langsung diisi "
            "baris awal). Pakai bila pengguna minta sheet/tabel/database baru yang BELUM "
            "ada. Default lokasi _TRANSIT (draft); sebut `folder` (path kategori, mis. "
            "'07/Aset') bila ingin di tempat lain. AKSI KONSEKUENSIAL → diajukan ke pemilik "
            "lewat tombol. JANGAN mengaku sudah membuat. (Untuk mengisi sheet yang SUDAH "
            "ada, pakai update_sheet.)"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "judul": {"type": "string", "description": "Nama file Sheet baru, mis. 'Database Vendor Teknisi'."},
                "folder": {"type": "string", "description": "Opsional: path folder tujuan (mis. '07/Aset'). Kosong = _TRANSIT."},
                "isi_json": {"type": "string", "description": "Opsional: JSON array-of-array baris awal, mis. '[[\"Nama\",\"Nomor\"],[\"Budi\",\"08xx\"]]'. Baris pertama biasanya header."},
            },
            "required": ["judul"],
        },
    },
    {
        "name": "update_sheet",
        "description": (
            "USULKAN mengisi/mengubah sebuah SEL di Google Sheet yang SUDAH ADA. Sebelum memakai ini, "
            "BACA dulu sheet-nya (baca_dokumen) untuk memastikan sel yang tepat "
            "(notasi A1, mis. 'Register!D5'). AKSI KONSEKUENSIAL → diajukan ke pemilik "
            "lewat tombol. JANGAN mengaku sudah mengubah."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nama_sheet": {"type": "string", "description": "Nama Google Sheet (persis lebih baik)."},
                "sel": {"type": "string", "description": "Sel/rentang notasi A1, mis. 'Register!D5' atau 'D5'."},
                "nilai": {"type": "string", "description": "Nilai baru untuk sel itu."},
            },
            "required": ["nama_sheet", "sel", "nilai"],
        },
    },
    {
        "name": "tambah_baris_sheet",
        "description": (
            "USULKAN menambah satu/lebih BARIS data ke Google Sheet yang sudah ada — "
            "TIAP kolom terpecah otomatis ke kolomnya sendiri (bukan tumpuk di satu sel). "
            "Pakai ini untuk 'tambahkan vendor/kontak/entri baru'. `baris_json` = JSON "
            "array-of-array: tiap baris satu list, tiap KOLOM elemen terpisah. Cocokkan "
            "urutan kolom dengan header sheet (baca_dokumen dulu bila perlu). PENTING: "
            "nomor telepon/ID dengan angka 0 di depan → beri awalan tanda kutip satu ('),"
            " mis. \"'082233633330\", agar nol depan tak hilang. AKSI KONSEKUENSIAL → "
            "tombol pemilik; JANGAN mengaku sudah menambah."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nama_sheet": {"type": "string", "description": "Nama Google Sheet tujuan (persis lebih baik)."},
                "baris_json": {"type": "string", "description": "JSON array-of-array, mis. '[[\"Teknisi\",\"Budi\",\"Montir dinamo\",\"\\'0812xxxx\"]]'. Satu inner-array = satu baris; tiap kolom elemen terpisah."},
            },
            "required": ["nama_sheet", "baris_json"],
        },
    },
    {
        "name": "edit_google_docs",
        "description": (
            "USULKAN mengganti teks di sebuah Google Doc (cari & ganti semua kemunculan). "
            "Sebelum memakai, BACA dulu dokumennya (baca_dokumen) agar teks 'cari' persis. "
            "AKSI KONSEKUENSIAL → diajukan ke pemilik lewat tombol. JANGAN mengaku sudah mengubah."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nama_doc": {"type": "string", "description": "Nama Google Doc (persis lebih baik)."},
                "cari": {"type": "string", "description": "Teks yang dicari (persis)."},
                "ganti": {"type": "string", "description": "Teks pengganti."},
            },
            "required": ["nama_doc", "cari", "ganti"],
        },
    },
    {
        "name": "daftar_kalender",
        "description": (
            "Lihat daftar kalender yang bisa dikelola (milik pemilik + yang dibagikan "
            "akun lain). Pakai untuk tahu kalender apa saja & 'id'-nya sebelum lihat/buat/"
            "ubah/hapus acara di kalender tertentu. Read-only."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "lihat_agenda",
        "description": (
            "Lihat acara Google Calendar dalam rentang tanggal (read-only). Hasil "
            "menyertakan [id] tiap acara — pakai id itu untuk ubah_acara/hapus_acara. "
            "Isi tanggal dari rujukan tanggal di system prompt."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dari": {"type": "string", "description": "Tanggal mulai ISO YYYY-MM-DD."},
                "sampai": {"type": "string", "description": "Tanggal akhir ISO YYYY-MM-DD (kosong = sama dgn 'dari')."},
                "kalender": {"type": "string", "description": "Target kalender: 'primary' (default) atau id/email dari daftar_kalender."},
            },
            "required": ["dari"],
        },
    },
    {
        "name": "buat_acara",
        "description": (
            "USULKAN membuat acara di Google Calendar. AKSI KONSEKUENSIAL → diajukan ke "
            "pemilik lewat tombol. JANGAN mengaku sudah membuat. Bila waktu/detail belum "
            "jelas, TANYAKAN dulu. Waktu memakai zona Asia/Jakarta."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "judul": {"type": "string", "description": "Judul/ringkasan acara."},
                "mulai": {"type": "string", "description": "Waktu mulai 'YYYY-MM-DDTHH:MM:SS' (mis. '2026-08-11T09:00:00')."},
                "selesai": {"type": "string", "description": "Waktu selesai 'YYYY-MM-DDTHH:MM:SS'."},
                "deskripsi": {"type": "string", "description": "Catatan/deskripsi acara (opsional)."},
                "lokasi": {"type": "string", "description": "Lokasi acara (opsional)."},
                "kalender": {"type": "string", "description": "Target kalender: 'primary' (default) atau id/email."},
            },
            "required": ["judul", "mulai", "selesai"],
        },
    },
    {
        "name": "ubah_acara",
        "description": (
            "USULKAN mengubah acara yang ada (reschedule/ubah judul/lokasi). Ambil "
            "event_id dari lihat_agenda dulu. Field yang kosong TIDAK diubah. AKSI "
            "KONSEKUENSIAL → tombol pemilik. JANGAN mengaku sudah mengubah."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "ID acara (dari [id] di lihat_agenda)."},
                "judul": {"type": "string", "description": "Judul baru (opsional)."},
                "mulai": {"type": "string", "description": "Waktu mulai baru 'YYYY-MM-DDTHH:MM:SS' (opsional)."},
                "selesai": {"type": "string", "description": "Waktu selesai baru (opsional)."},
                "deskripsi": {"type": "string", "description": "Deskripsi baru (opsional)."},
                "lokasi": {"type": "string", "description": "Lokasi baru (opsional)."},
                "kalender": {"type": "string", "description": "Target kalender: 'primary' (default) atau id/email."},
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "hapus_acara",
        "description": (
            "USULKAN menghapus acara dari Google Calendar. Ambil event_id dari "
            "lihat_agenda dulu. AKSI KONSEKUENSIAL → tombol pemilik. JANGAN mengaku "
            "sudah menghapus."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "ID acara (dari [id] di lihat_agenda)."},
                "ringkasan_acara": {"type": "string", "description": "Judul acara (untuk konfirmasi jelas)."},
                "kalender": {"type": "string", "description": "Target kalender: 'primary' (default) atau id/email."},
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "baca_email",
        "description": (
            "Lihat email TERBARU di sebuah mailbox (read-only, ADMIN). Kelola 3 mailbox: "
            "finance@, admin@, wahidnurhani@. Hasil menyertakan [id] tiap email — pakai "
            "untuk baca_email_isi/draft/arsip. 🔵 = belum dibaca. Bisa 'kueri' gaya "
            "pencarian Gmail (mis. 'is:unread', 'from:bank')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mailbox": {"type": "string", "description": "Mailbox: finance / admin / wahidnurhani (atau alamat lengkapnya). WAJIB sebutkan yang mana."},
                "kueri": {"type": "string", "description": "Opsional: filter gaya Gmail (mis. 'is:unread', 'from:xxx', 'subject:invoice'). Default inbox."},
                "maks": {"type": "integer", "description": "Jumlah email (default 12)."},
            },
            "required": ["mailbox"],
        },
    },
    {
        "name": "cari_email",
        "description": (
            "Cari email di sebuah mailbox (read-only, ADMIN). Memakai pencarian Gmail "
            "penuh (pengirim, subjek, isi). Hasil menyertakan [id]."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mailbox": {"type": "string", "description": "Mailbox: finance / admin / wahidnurhani."},
                "kata": {"type": "string", "description": "Kata/kueri pencarian (Gmail search)."},
                "maks": {"type": "integer", "description": "Batas hasil (default 12)."},
            },
            "required": ["mailbox", "kata"],
        },
    },
    {
        "name": "baca_email_isi",
        "description": (
            "Baca ISI lengkap satu email (read-only, ADMIN). Pakai id dari "
            "baca_email/cari_email + mailbox-nya."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mailbox": {"type": "string", "description": "Mailbox: finance / admin / wahidnurhani."},
                "uid": {"type": "string", "description": "id email (dari [id] di baca_email/cari_email)."},
            },
            "required": ["mailbox", "uid"],
        },
    },
    {
        "name": "draft_email",
        "description": (
            "Buat DRAF balasan/email baru di mailbox (ADMIN). Tersimpan sebagai draft "
            "Gmail untuk direview pemilik — TIDAK mengirim. Untuk membalas, isi "
            "'balas_ke_id' (id email asal); ke/subjek terisi otomatis dari email itu."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mailbox": {"type": "string", "description": "Mailbox pengirim: finance / admin / wahidnurhani."},
                "ke": {"type": "string", "description": "Penerima (opsional bila balas_ke_id diisi)."},
                "subjek": {"type": "string", "description": "Subjek (opsional bila balas)."},
                "isi": {"type": "string", "description": "Isi/badan email."},
                "balas_ke_id": {"type": "string", "description": "id email yang dibalas (opsional)."},
            },
            "required": ["mailbox", "isi"],
        },
    },
    {
        "name": "kirim_email",
        "description": (
            "USULKAN mengirim email dari salah satu mailbox. AKSI KONSEKUENSIAL → "
            "diajukan ke pemilik lewat tombol; JANGAN mengaku sudah terkirim. Susun isi "
            "rapi & sopan. Bila penerima/maksud belum jelas, TANYAKAN dulu. Untuk balasan, "
            "boleh isi balas_ke_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mailbox": {"type": "string", "description": "Mailbox pengirim: finance / admin / wahidnurhani. WAJIB."},
                "ke": {"type": "string", "description": "Alamat email penerima."},
                "subjek": {"type": "string", "description": "Subjek email."},
                "isi": {"type": "string", "description": "Isi/badan email (teks)."},
                "balas_ke_id": {"type": "string", "description": "Opsional: id email yang dibalas (subjek/penerima ikut otomatis)."},
            },
            "required": ["mailbox", "isi"],
        },
    },
    {
        "name": "atur_email",
        "description": (
            "SIMPAN aturan pemilahan email yang diajarkan pemilik (belajar dari koreksi, "
            "permanen & deterministik). Pakai saat pemilik bilang mis. 'email dari X "
            "selalu penting', 'laporan Y arsip saja', 'jangan arsip dari Z'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cocok": {"type": "string", "description": "Nilai yang dicocokkan: alamat/nama pengirim, domain, atau kata pada subjek."},
                "jenis": {"type": "string", "enum": ["from", "domain", "subjek"], "description": "Cocokkan berdasar pengirim (from), domain, atau kata subjek."},
                "verdikt": {"type": "string", "enum": ["rutin", "penting"], "description": "rutin = arsip otomatis (diam); penting = selalu dilaporkan, tak diarsip."},
                "catatan": {"type": "string", "description": "Opsional: instruksi asli pemilik."},
            },
            "required": ["cocok", "verdikt"],
        },
    },
    {
        "name": "lihat_aturan_email",
        "description": "Tampilkan daftar aturan pemilahan email yang sudah diajarkan.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "batalkan_arsip_email",
        "description": (
            "UNDO: kembalikan email yang baru diarsip OTOMATIS ke Inbox (3 hari terakhir). "
            "Pakai saat pemilik bilang 'kembalikan email yang tadi diarsip'. ADMIN."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mailbox": {"type": "string", "description": "Mailbox: finance/admin/wahidnurhani@hadimulya.com/pribadi/alamat lengkap."},
                "n": {"type": "integer", "description": "Berapa email terakhir dikembalikan (default 5)."},
            },
            "required": ["mailbox"],
        },
    },
    {
        "name": "arsip_email",
        "description": (
            "Arsipkan email (keluarkan dari Inbox; tetap ada & bisa dicari). Reversibel. "
            "ADMIN. Pakai id + mailbox."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mailbox": {"type": "string", "description": "Mailbox: finance / admin / wahidnurhani."},
                "uid": {"type": "string", "description": "id email."},
            },
            "required": ["mailbox", "uid"],
        },
    },
    {
        "name": "tandai_dibaca_email",
        "description": "Tandai email sudah/belum dibaca (ADMIN). Reversibel. Pakai id + mailbox.",
        "input_schema": {
            "type": "object",
            "properties": {
                "mailbox": {"type": "string", "description": "Mailbox: finance / admin / wahidnurhani."},
                "uid": {"type": "string", "description": "id email."},
                "dibaca": {"type": "boolean", "description": "true = tandai dibaca (default); false = tandai belum dibaca."},
            },
            "required": ["mailbox", "uid"],
        },
    },
    {
        "name": "label_email",
        "description": (
            "Tempel label ke email untuk merapikan (ADMIN). Label dibuat otomatis bila "
            "belum ada. Reversibel. Pakai id + mailbox + nama label."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mailbox": {"type": "string", "description": "Mailbox: finance / admin / wahidnurhani."},
                "uid": {"type": "string", "description": "id email."},
                "label": {"type": "string", "description": "Nama label (mis. 'Bank', 'Perlu Tindak Lanjut')."},
            },
            "required": ["mailbox", "uid", "label"],
        },
    },
    {
        "name": "karyawan_gajihub",
        "description": (
            "Ambil DAFTAR KARYAWAN dari GajiHub (HR resmi) — nama, kode, status aktif. "
            "Read-only. Pakai untuk pertanyaan 'siapa saja karyawan', 'berapa jumlah "
            "pegawai aktif', cek nama. Data SENSITIF → hanya berfungsi untuk admin."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "termasuk_nonaktif": {"type": "boolean", "description": "true = ikut yang sudah nonaktif/resign. Default false (aktif saja)."},
            },
        },
    },
    {
        "name": "payroll_gajihub",
        "description": (
            "Ambil REKAP SLIP GAJI / periode payroll dari GajiHub (read-only). Pakai untuk "
            "'ada berapa periode gaji', 'rekap payroll'. Angka BERSUMBER dari GajiHub — "
            "rangkum saja, jangan hitung ulang. Data SENSITIF → hanya admin."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "cuti_gajihub",
        "description": (
            "Ambil data CUTI karyawan dari GajiHub (read-only). Bisa saring dengan `nama`. "
            "Pakai untuk 'data cuti si X'. Data SENSITIF → hanya admin."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nama": {"type": "string", "description": "Opsional: saring untuk nama karyawan tertentu."},
            },
        },
    },
    {
        "name": "pengajuan_gajihub",
        "description": (
            "Ambil DAFTAR approval PRESENSI/LEMBUR yang MENUNGGU persetujuan di GajiHub "
            "(Mulai/Selesai Lembur & koreksi presensi). Tiap baris berisi [id] jenis — "
            "karyawan · waktu. Pakai bila pengguna tanya 'ada pengajuan lembur?' / 'apa "
            "yang perlu disetujui?'. Read-only. Khusus admin."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "semua": {"type": "boolean", "description": "true = tampilkan juga yang sudah diputus. Default false (menunggu saja)."},
            },
        },
    },
    {
        "name": "setujui_pengajuan",
        "description": (
            "USULKAN MENYETUJUI sebuah pengajuan HR (lembur/cuti) di GajiHub berdasarkan "
            "`id` (dari pengajuan_gajihub). AKSI KONSEKUENSIAL (mengubah data & payroll) → "
            "diajukan ke pemilik lewat tombol ✅/❌. JANGAN mengaku sudah disetujui. Khusus admin."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "id pengajuan PERSIS dari daftar pengajuan_gajihub (angka dalam kurung, mis. 4702)."},
                "alasan": {"type": "string", "description": "Opsional: catatan persetujuan."},
            },
            "required": ["id"],
        },
    },
    {
        "name": "tolak_pengajuan",
        "description": (
            "USULKAN MENOLAK sebuah pengajuan HR (lembur/cuti) di GajiHub berdasarkan `id`. "
            "AKSI KONSEKUENSIAL → tombol ✅/❌ pemilik. Sertakan `alasan` bila ada. "
            "JANGAN mengaku sudah ditolak. Khusus admin."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "id pengajuan PERSIS dari daftar pengajuan_gajihub (angka dalam kurung, mis. 4702)."},
                "alasan": {"type": "string", "description": "Alasan penolakan (disarankan)."},
            },
            "required": ["id"],
        },
    },
    {
        "name": "cari_pengetahuan",
        "description": (
            "Cari 'otak perusahaan' — SOP, kebijakan, keputusan, fakta, catatan yang "
            "PERNAH DISIMPAN (read-only). Pakai LEBIH DULU bila pengguna bertanya soal "
            "aturan/prosedur/keputusan/data internal perusahaan, sebelum menjawab dari "
            "dugaan. Kalau kosong, jawab apa adanya + tawarkan menyimpan bila itu fakta baru."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Pertanyaan/kata kunci yang dicari."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "simpan_pengetahuan",
        "description": (
            "Simpan fakta/catatan/keputusan ke 'otak perusahaan' agar bisa dicari & "
            "dipakai lagi nanti (bot makin paham seiring waktu). Pakai bila pengguna "
            "minta 'ingat/catat …', atau saat muncul fakta durable yang layak disimpan "
            "(mis. PIC pemasok, kebijakan, keputusan rapat). Judul ringkas & khas. "
            "Set rahasia=true untuk data SENSITIF (mis. IT Accounts, perbankan, akses, "
            "kredensial) — pengetahuan rahasia HANYA bisa dimunculkan admin, tak pernah staff."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "judul": {"type": "string", "description": "Judul singkat & khas (mis. 'PIC Vendor PT Rajawali')."},
                "isi": {"type": "string", "description": "Isi fakta/catatan lengkap yang disimpan."},
                "rahasia": {"type": "boolean", "description": "true bila data sensitif (perbankan/akses/kredensial/IT Accounts) → khusus admin. Default false."},
            },
            "required": ["judul", "isi"],
        },
    },
]
_TOOLS.extend(kendali.TOOLS)
_TOOLS.extend(produksi.TOOLS)
_TOOLS.extend(kledo.TOOLS)
_TOOLS.extend(it_aset.TOOLS)
_TOOLS.append({
    "name": "simulasi_hpp",
    "description": (
        "Hitung HPP (Harga Pokok Produksi) beras SECARA RESMI memakai tarif biaya "
        "pabrik terkini: bahan baku gabah + bongkar + pengeringan + operator (flat/tonase) "
        "+ rubber roll + listrik + tenaga giling. WAJIB pakai tool ini untuk pertanyaan "
        "'HPP'/'simulasi HPP' — JANGAN hitung manual (hasil manual pasti tak lengkap & "
        "tak konsisten dengan sistem pabrik). Beri harga_gabah + tonase bahan & hasil "
        "(atau rendemen). kondisi: 'basah' (dikeringkan, mahal) / 'kering' (tetap "
        "dikeringkan, murah); langsung_silo=true bila gabah kering langsung silo (tanpa "
        "pengeringan)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "harga_gabah": {"type": "number", "description": "Harga beli gabah, Rp/kg."},
            "berat_bahan": {"type": "number", "description": "Tonase gabah masuk (kg) — WAJIB (biaya operator flat dibagi tonase)."},
            "berat_hasil": {"type": "number", "description": "Tonase beras/PK hasil (kg). Untuk hitung rendemen."},
            "rendemen_persen": {"type": "number", "description": "Rendemen (%). Alternatif berat_hasil bila tonase hasil tak ada."},
            "kondisi": {"type": "string", "enum": ["basah", "kering"], "description": "Kondisi gabah masuk. Default basah."},
            "langsung_silo": {"type": "boolean", "description": "true = gabah kering langsung silo (tanpa pengeringan)."},
        },
        "required": ["harga_gabah", "berat_bahan"],
    },
})


def _system_stabil(*, role: str) -> str:
    """Bagian system prompt yang STABIL (tanpa tanggal) → aman di-cache.

    Rujukan tanggal (yang berubah harian) sengaja DIPISAH ke blok terpisah di
    run_kantor_agent, di LUAR titik cache, agar prefix (tools + prompt ini) tak
    pernah batal karena tanggal — menekan biaya kredit (prompt caching)."""
    return (
        "Kamu 'Kantor AI', asisten eksekutif PT Hadi Mulya Utama (penggilingan "
        "beras, Sragen). Tugasmu membantu urusan kantor: pembuatan surat resmi, "
        "penomoran, pengarsipan (digital + fisik), dan administrasi HR. "
        f"Peran pengguna: {role}. "
        "Jawab RINGKAS, sopan, bahasa Indonesia. Jangan mengarang — pakai tool "
        "bila perlu data/aturan.\n\n"
        "Kamu BISA menjelajah Google Drive perusahaan (read-only): lihat isi "
        "_TRANSIT (daftar_transit), buka folder/subfolder via path (buka_folder), "
        "lihat 1 kategori (daftar_folder), cari file (cari_file), dan baca isi "
        "dokumen (baca_dokumen). Pakai tool ini bila pengguna menanyakan isi folder, "
        "mencari file, atau ingin tahu isi dokumen — jangan menebak.\n"
        "Untuk Google Sheet ber-banyak-TAB atau berdata besar: baca_dokumen HANYA "
        "membaca tab pertama & bisa terpotong — pakai daftar_tab_sheet (lihat semua tab) "
        "lalu baca_sheet(nama_sheet, tab[, rentang]) untuk membaca tab tertentu penuh. "
        "Bila data yang dicari tak ada di tab pertama, CEK tab lain dulu sebelum bilang "
        "tak ada.\n"
        "Untuk FILE GAMBAR (.jpg/.png) atau PDF hasil SCAN (mis. KTP, BPJS, surat "
        "berstempel): baca_dokumen tak bisa — pakai baca_gambar (OCR). Bila baca_dokumen "
        "balik kosong/'gambar/scan', coba baca_gambar.\n"
        "Untuk AUDIT menyeluruh (mis. 'cek draft nyasar di seluruh subfolder'), pakai "
        "audit_draft_nyasar (sekali panggil, memindai seluruh Drive) — JANGAN membuka "
        "folder satu per satu untuk itu.\n"
        "Kamu MENGELOLA Google Calendar (bisa lebih dari 1 kalender — milik pemilik + "
        "yang dibagikan): daftar_kalender (lihat kalender & id-nya), lihat_agenda (baca "
        "jadwal; hasilnya menyertakan [id] acara), lalu MENGUSULKAN buat_acara / "
        "ubah_acara / hapus_acara (konsekuensial, lewat tombol pemilik). Untuk ubah/hapus, "
        "ambil event_id dari lihat_agenda dulu. Waktu zona Asia/Jakarta.\n"
        "Kamu PUNYA AKSES PENUH ke 5 mailbox berikut (via kredensial resmi yang sudah "
        "terpasang) — JANGAN PERNAH menolak dengan alasan 'tidak punya akses'/'hanya "
        "email kantor'; langsung panggil tool baca_email/cari_email dengan mailbox yang "
        "diminta.\n"
        "Kamu MENGELOLA 5 MAILBOX (khusus admin):\n"
        "  KANTOR (Workspace): finance@hadimulya.com, admin@hadimulya.com, "
        "wahidnurhani@hadimulya.com.\n"
        "  PRIBADI (Gmail): wahidnurhani20@gmail.com (alias 'pribadi'), "
        "wahidnurhani@gmail.com.\n"
        "PENTING soal mailbox: 'email pribadi' = akun GMAIL pribadi. Kalau pengguna "
        "bilang 'email pribadi' tanpa menyebut spesifik, cek KEDUA gmail pribadi "
        "(wahidnurhani20@gmail.com DAN wahidnurhani@gmail.com) — JANGAN wahidnurhani@"
        "hadimulya.com. 'wahidnurhani@' saja / 'email kantor saya' = wahidnurhani@"
        "hadimulya.com. SELALU pakai ALAMAT LENGKAP di argumen mailbox untuk akun "
        "'wahidnurhani' (jangan nama pendek, ambigu). JANGAN pernah mengarsipkan/"
        "menyentuh email OTP, kode login, atau keamanan akun — selalu penting. "
        "Baca/triage: "
        "baca_email (inbox/terbaru; 'kueri' gaya Gmail spt 'is:unread'), cari_email, "
        "baca_email_isi (pakai [id]). Merapikan (langsung, reversibel): arsip_email, "
        "tandai_dibaca_email, label_email. Draf (aman, tak mengirim): draft_email — "
        "tersimpan di Draft Gmail untuk direview; untuk membalas isi balas_ke_id. "
        "MENGIRIM: MENGUSULKAN kirim_email (konsekuensial → tombol pemilik; JANGAN "
        "mengaku sudah terkirim). TIDAK ADA hapus permanen email. Kalau staff (bukan "
        "admin) menyentuh email, tolak halus — isi mailbox itu sensitif.\n"
        "Kamu terhubung ke GajiHub (HR/payroll resmi, read-only): karyawan_gajihub "
        "(daftar karyawan aktif), payroll_gajihub (periode slip gaji), cuti_gajihub. "
        "Angka gaji BERSUMBER dari GajiHub — rangkum saja, jangan hitung ulang. Data ini "
        "SENSITIF (gaji/PII) → hanya berfungsi untuk admin; kalau staff bertanya, tolak halus.\n"
        "PERSETUJUAN LEMBUR/PRESENSI: di GajiHub, lembur tercatat sebagai approval "
        "presensi (Mulai/Selesai Lembur). pengajuan_gajihub menampilkan yang MENUNGGU "
        "(tiap baris ada [id]). Untuk memutus, USULKAN setujui_pengajuan(id) atau "
        "tolak_pengajuan(id, alasan) — KONSEKUENSIAL, lewat tombol ✅/❌ pemilik; jangan "
        "mengaku sudah diputus. Ambil id dari pengajuan_gajihub dulu.\n"
        "Kamu punya OTAK PERUSAHAAN (ingatan PERMANEN — beda dari riwayat chat yang "
        "cuma 8 giliran terakhir): cari_pengetahuan (cari SOP/keputusan/fakta tersimpan "
        "— pakai LEBIH DULU untuk pertanyaan aturan/data internal) & simpan_pengetahuan.\n"
        "BELAJAR DARI KOREKSI (LINTAS PERAN — HR, Arsip, Finance, Aset, email, dll): "
        "setiap kali pemilik MENGOREKSI kamu atau menyatakan preferensi/kebijakan tetap, "
        "SIMPAN agar konsisten selamanya. Koreksi soal PEMILAHAN EMAIL (mis. 'dari X "
        "selalu penting', 'laporan Y arsip saja') → pakai tool atur_email. Koreksi/"
        "kebijakan/preferensi peran LAIN → simpan_pengetahuan. Untuk membatalkan email "
        "yang salah diarsip otomatis → batalkan_arsip_email.\n"
        "PROAKTIF menyimpan: begitu di obrolan muncul FAKTA DURABLE yang berguna dipakai "
        "lagi — keputusan rapat, kebijakan/aturan baru, PIC/kontak pemasok & klien, "
        "angka/target penting, struktur & jabatan, preferensi tetap pemilik — LANGSUNG "
        "simpan tanpa menunggu diminta, lalu beri tahu singkat (mis. '📝 kucatat: …'). "
        "JANGAN simpan hal sepele/sekali pakai: obrolan santai, pertanyaan, data yang "
        "berubah tiap hari (stok, saldo, agenda harian). JANGAN PERNAH menyimpan "
        "kredensial mentah (password, PIN, token, kunci API). Kalau ragu apakah durable, "
        "cenderung SIMPAN — mudah dihapus nanti. Hindari duplikat: bila mungkin sudah "
        "pernah tersimpan, cari_pengetahuan dulu.\n"
        "DATA SENSITIF (IT Accounts, perbankan, akses, data pribadi karyawan): boleh "
        "disimpan TAPI set rahasia=true → hanya admin yang bisa memunculkannya, staff tak "
        "pernah. Untuk data yang tinggal di Google Sheet (mis. IT Accounts), SHEET ADALAH "
        "SUMBER KEBENARAN: bila ada perubahan, USULKAN update sheet-nya (update_sheet/"
        "tambah_baris_sheet) lebih dulu, dan untuk nilai terkini baca langsung dari sheet "
        "(baca_sheet) daripada mengandalkan salinan pengetahuan yang bisa usang.\n"
        "Kamu juga BISA MENGUSULKAN aksi tulis Drive: pindah FILE/FOLDER (pindah_item), "
        "ganti nama (rename_item), hapus→Sampah (hapus_item), buat FOLDER baru "
        "(buat_folder), BUAT DOKUMEN resmi .docx berkop → _TRANSIT draft "
        "(buat_dokumen — untuk surat tugas/keterangan/SK/kontrak/perjanjian; kamu "
        "menyusun isinya), BUAT Google Sheet BARU dari nol (buat_sheet — bila diminta "
        "sheet/tabel/database yang belum ada; bisa langsung diisi baris awal), TAMBAH "
        "BARIS data ke Sheet yang ada (tambah_baris_sheet — tiap kolom otomatis terpisah; "
        "untuk 'tambahkan vendor/kontak/entri baru'), EDIT satu sel "
        "Google Sheet yang sudah ada (update_sheet), dan GANTI teks Google "
        "Doc (edit_google_docs). Untuk edit Sheet/Doc, BACA dulu isinya (baca_dokumen) "
        "agar sel A1 / teks yang dicari persis. Semua aksi ini KONSEKUENSIAL — tidak langsung jalan; sistem "
        "mengajukannya ke pemilik lewat tombol persetujuan di Telegram. Setelah "
        "memanggil tool, sampaikan bahwa aksi MENUNGGU persetujuan pemilik — JANGAN "
        "mengaku sudah selesai. Bila nama target ambigu atau data dokumen kurang, "
        "TANYAKAN dulu.\n\n"
        "Kategori arsip DIGITAL (kode → kategori):\n"
        f"{_daftar_kategori()}\n\n"
        "Aturan penting:\n"
        "- Penomoran surat & pembuatan dokumen adalah AKSI KONSEKUENSIAL — "
        "usulkan lewat tool, JANGAN mengaku sudah menerbitkan; sistem yang minta "
        "konfirmasi ke pengguna.\n"
        "- Bila data untuk membuat surat belum lengkap, TANYAKAN dulu.\n"
        "- Setiap file baru berstatus draft dan masuk folder _TRANSIT dulu "
        "(aturan arsip perusahaan)."
    )


# ─────────────────────────── Eksekutor tool READ ───────────────────────────


def _run_read_tool(name: str, args: dict) -> str:
    if name == "panduan_arsip":
        kode = (args.get("kode_kategori") or "").strip()
        p = arsip_fisik.panduan(kode)
        baris = [f"📁 Digital: folder {p.digital_kode} — {p.digital_nama}"]
        if p.fisik:
            f = p.fisik
            baris.append(
                f"🗄️ Fisik: ordner {f.kode} — {f.nama} "
                f"(warna {f.warna}, golongan {f.golongan}, retensi {f.retensi})"
            )
        else:
            baris.append("🗄️ Fisik: tidak ada ordner khusus → ordner 09 Umum.")
        if p.catatan:
            baris.append(f"ℹ️ {p.catatan}")
        return "\n".join(baris)

    if name == "cek_nama_file":
        nama = (args.get("nama_file") or "").strip()
        if not nama:
            return "Nama file kosong."
        h = konsistensi.validasi_nama_file(nama)
        if not h.temuan and not h.nama_usulan:
            return f"✅ '{nama}' sudah sesuai aturan penamaan."
        baris = []
        for t in h.temuan:
            tanda = "❌" if t.level == "error" else "⚠️"
            saran = f" → {t.saran}" if t.saran else ""
            baris.append(f"{tanda} {t.pesan}{saran}")
        if h.nama_usulan:
            baris.append(f"💡 Usulan nama: {h.nama_usulan}")
        return "\n".join(baris)

    return f"(tool '{name}' tidak dikenal)"


# ─────────────────────────── Usulan aksi (write) ───────────────────────────


def _aksi_surat_tugas(inp: dict) -> KantorReply:
    """Bentuk usulan Surat Tugas dari argumen tool (belum dieksekusi)."""
    tgl = (inp.get("tanggal_surat") or "").strip()
    try:
        date.fromisoformat(tgl)
    except ValueError:
        tgl = _hari_ini().isoformat()
    params = {
        "nama": inp.get("nama", "").strip(),
        "jabatan": inp.get("jabatan", "").strip(),
        "tugas": inp.get("tugas", "").strip(),
        "tempat": inp.get("tempat", "").strip(),
        "waktu": inp.get("waktu", "").strip(),
        "tanggal_surat": tgl,
        "no_pegawai": (inp.get("no_pegawai") or "-").strip() or "-",
    }
    ringkas = (
        f"terbitkan *Surat Tugas* (nomor resmi ST/HR) untuk *{params['nama']}* "
        f"({params['jabatan']}) — {params['tugas']} di {params['tempat']}, "
        f"{params['waktu']}"
    )
    return KantorReply(aksi={"jenis": "surat_tugas", "params": params, "ringkasan": ringkas})


# ─────────────────────────── Loop agent ───────────────────────────


async def run_kantor_agent(
    *, text: str, role: str, nama_user: str, riwayat: list[dict] | None = None,
    user_id: int | None = None,
) -> KantorReply:
    """Jalankan agent Kantor untuk satu permintaan. Aksi tulis → usulan (aksi).

    `riwayat`: giliran percakapan sebelumnya ({"role","content"}) untuk konteks —
    membuat bot 'ingat' obrolan lalu. Sudah dibatasi pemanggil (app/kantor/riwayat.py).
    """
    # Prompt caching: cache tools + system STABIL (prefix identik tiap panggilan &
    # tiap iterasi); blok tanggal (volatile harian) sengaja DI LUAR cache. Memotong
    # biaya kredit pada bagian berulang TANPA menurunkan kualitas.
    system = [
        {"type": "text", "text": _system_stabil(role=role),
         "cache_control": {"type": "ephemeral"}},
        {"type": "text",
         "text": "Rujukan tanggal (jangan menghitung sendiri):\n" + _date_context()},
    ]
    messages: list[dict] = [*(riwayat or []), {"role": "user", "content": text}]

    # Router domain (opsional, flag): pangkas tool ke domain relevan → agen lebih
    # tajam. Deterministik (0 token). Default OFF = bundel penuh + prompt-cache utuh.
    tools_aktif = _TOOLS
    if settings.router_aktif:
        tools_aktif = domain_router.bundel(domain_router.pilih_domain(text), _TOOLS)

    for _ in range(settings.agent_max_iterations):
        resp = await guard.panggil(
            pemanggil="agent_kantor",
            model=settings.agent_model,
            max_tokens=1500,
            system=system,
            tools=tools_aktif,
            messages=messages,
        )
        u = resp.usage
        log.info(
            "agen kantor token: in=%d cache_baca=%d cache_tulis=%d out=%d",
            u.input_tokens, getattr(u, "cache_read_input_tokens", 0) or 0,
            getattr(u, "cache_creation_input_tokens", 0) or 0, u.output_tokens,
        )
        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        if not tool_uses:
            final = "".join(b.text for b in resp.content if b.type == "text").strip()
            return KantorReply(text=final or "Maaf, saya belum bisa menjawab itu.")

        # Aksi tulis → hentikan loop, kembalikan usulan untuk dikonfirmasi bot.
        for tu in tool_uses:
            if tu.name == "siapkan_surat_tugas":
                return _aksi_surat_tugas(tu.input or {})

        # Eksekusi semua tool READ, umpankan hasilnya kembali. Tool Drive melakukan
        # I/O jaringan → jalankan di thread agar tak memblok event loop.
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for tu in tool_uses:
            _tolak = await rbac.cek_tool_akses(user_id, tu.name, tu.input or {})
            if _tolak is not None:
                out = _tolak
            elif tu.name in pengetahuan.NAMA_TOOL:
                out = await pengetahuan.jalankan(
                    tu.name, tu.input or {}, role=role,
                    larang_domain=await rbac.knowledge_larang(user_id))
            elif tu.name in kendali.NAMA_TOOL:
                out = await kendali.jalankan(tu.name, tu.input or {}, role)
            elif tu.name in produksi.NAMA_TOOL:
                out = await produksi.jalankan(tu.name, tu.input or {}, user_id, role)
            elif tu.name in kledo.NAMA_TOOL:
                out = await kledo.jalankan(tu.name, tu.input or {}, user_id, role)
            elif tu.name in it_aset.NAMA_TOOL:
                out = await it_aset.jalankan(tu.name, tu.input or {}, user_id, role)
            elif tu.name == "simulasi_hpp":
                a = tu.input or {}
                out = analytics.simulasi_hpp(
                    a.get("harga_gabah"), a.get("rendemen_persen"),
                    kondisi=a.get("kondisi", "basah"),
                    langsung_silo=bool(a.get("langsung_silo")),
                    berat_bahan=a.get("berat_bahan"), berat_hasil=a.get("berat_hasil"),
                )
            elif tu.name in ocr.NAMA_TOOL:
                out = await ocr.jalankan(tu.name, tu.input or {})
            elif tu.name in gajihub.NAMA_TOOL:
                out = await asyncio.to_thread(gajihub.jalankan, tu.name, tu.input or {}, role)
            elif tu.name in gajihub.NAMA_USUL:
                out = await gajihub.jalankan_usul(tu.name, tu.input or {}, role)
            elif mail_gmail.terkonfigurasi() and tu.name in mail_gmail.NAMA_USUL:
                # KIRIM email (Gmail) → gerbang tombol pemilik
                out = await mail_gmail.usul_kirim(tu.input or {}, role)
            elif tu.name in aturan.NAMA_TOOL:
                out = await aturan.jalankan(tu.name, tu.input or {}, role)
            elif mail_gmail.terkonfigurasi() and tu.name in mail_gmail.NAMA_TOOL:
                # baca/cari/isi/draft/arsip/tandai/label/undo (Gmail, admin-only)
                out = await asyncio.to_thread(mail_gmail.jalankan, tu.name, tu.input or {}, role)
            elif tu.name in drive_aksi.NAMA_TOOL:
                # Aksi tulis (pindah/rename/hapus file/folder) → ajukan ke gerbang
                # tombol pemilik; kembalikan status "diajukan" ke agen untuk diteruskan.
                out = await drive_aksi.jalankan_usul(tu.name, tu.input or {})
            elif tu.name in drive_ops.NAMA_TOOL:
                out = await asyncio.to_thread(drive_ops.jalankan, tu.name, tu.input or {})
            else:
                out = _run_read_tool(tu.name, tu.input or {})
            results.append({
                "type": "tool_result", "tool_use_id": tu.id, "content": out,
            })
        messages.append({"role": "user", "content": results})

    return KantorReply(
        text="Permintaannya cukup kompleks — coba persempit atau pecah jadi beberapa langkah."
    )
