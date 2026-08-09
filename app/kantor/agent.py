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
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.ai.base import _date_context
from app.ai.claude_client import get_client
from app.config import settings
from app.kantor import arsip_fisik
from app.kantor.dokumen import konsistensi
from app.kantor.drive import aksi as drive_aksi
from app.kantor.drive import operasi as drive_ops
from app.kantor.drive import taksonomi as tx


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
            "terekstrak."
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
]


def _system_prompt(*, role: str) -> str:
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
        "Kamu juga BISA MENGUSULKAN aksi tulis Drive untuk FILE atau FOLDER: pindah "
        "(pindah_item), ganti nama (rename_item), hapus→Sampah (hapus_item). Aksi ini "
        "KONSEKUENSIAL — tidak langsung jalan; sistem mengajukannya ke pemilik lewat "
        "tombol persetujuan di Telegram. Setelah memanggil tool, sampaikan ke pengguna "
        "bahwa aksi MENUNGGU persetujuan pemilik — JANGAN mengaku sudah selesai. Bila "
        "nama target ambigu, tanyakan nama persis dulu.\n\n"
        "Kategori arsip DIGITAL (kode → kategori):\n"
        f"{_daftar_kategori()}\n\n"
        "Aturan penting:\n"
        "- Penomoran surat & pembuatan dokumen adalah AKSI KONSEKUENSIAL — "
        "usulkan lewat tool, JANGAN mengaku sudah menerbitkan; sistem yang minta "
        "konfirmasi ke pengguna.\n"
        "- Bila data untuk membuat surat belum lengkap, TANYAKAN dulu.\n"
        "- Setiap file baru berstatus draft dan masuk folder _TRANSIT dulu "
        "(aturan arsip perusahaan).\n\n"
        "Rujukan tanggal (jangan menghitung sendiri):\n" + _date_context()
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
    *, text: str, role: str, nama_user: str, riwayat: list[dict] | None = None
) -> KantorReply:
    """Jalankan agent Kantor untuk satu permintaan. Aksi tulis → usulan (aksi).

    `riwayat`: giliran percakapan sebelumnya ({"role","content"}) untuk konteks —
    membuat bot 'ingat' obrolan lalu. Sudah dibatasi pemanggil (app/kantor/riwayat.py).
    """
    client = get_client()
    system = _system_prompt(role=role)
    messages: list[dict] = [*(riwayat or []), {"role": "user", "content": text}]

    for _ in range(settings.agent_max_iterations):
        resp = await client.messages.create(
            model=settings.agent_model,
            max_tokens=1500,
            system=system,
            tools=_TOOLS,
            messages=messages,
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
            if tu.name in drive_aksi.NAMA_TOOL:
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
