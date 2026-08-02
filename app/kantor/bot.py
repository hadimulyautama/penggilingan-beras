"""Bot 'Kantor AI' — asisten eksekutif Direksi (dokumen / arsip / HR).

Persona TERPISAH dari bot operasional pabrik (gudang1/gudang2/admin). Tanya-jawab
& panduan dijawab agent langsung; setiap AKSI KONSEKUENSIAL (terbitkan nomor
surat, susun naskah) lewat pola usul→konfirmasi→eksekusi deterministik.

Akses: Direksi/Staff kantor (role admin/staff). Operator diarahkan ke bot pabrik.
"""
from __future__ import annotations

import logging
from datetime import date

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bots.common import (
    CANCEL_WORDS,
    CONFIRM_WORDS,
    authenticate,
    get_session,
    handle_shared_contact,
    unregistered_reply,
)
from app.database import SessionLocal
from app.kantor.agent import run_kantor_agent
from app.kantor.dokumen import penomoran
from app.kantor.dokumen import surat as surat_mod

router = Router(name="kantor")
log = logging.getLogger("bots.kantor")

_START = (
    "👔 *Kantor AI* — asisten eksekutif PT HMU\n\n"
    "Saya bantu Anda urus:\n"
    "• 📄 *Buat surat resmi* (mis. Surat Tugas) — otomatis dengan nomor resmi\n"
    "• 🗂️ *Panduan arsip* — dokumen ini disimpan di folder & ordner mana\n"
    "• ✅ *Cek nama file* — sudah sesuai aturan penamaan atau belum\n\n"
    "Contoh:\n"
    "• `buatkan surat tugas untuk Budi, sopir, antar sparepart ke Solo, 5 Agustus`\n"
    "• `kontrak kerja karyawan disimpan di mana?`\n"
    "• `cek nama file: Copy of laporan FINAL (1).xlsx`\n\n"
    "Ketik natural saja. Untuk aksi penting, saya minta konfirmasi dulu."
)


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    async with SessionLocal() as db:
        user = await authenticate(db, message.from_user.id)
    if not user:
        await unregistered_reply(message)
        return
    if user.role not in {"admin", "staff"}:
        await message.answer("⛔ Kantor AI khusus Direksi/Staff kantor.")
        return
    await message.answer(_START, parse_mode="Markdown")


@router.message(Command("whoami"))
async def cmd_whoami(message: Message) -> None:
    async with SessionLocal() as db:
        user = await authenticate(db, message.from_user.id)
    if not user:
        await message.answer(f"Belum terdaftar. ID: `{message.from_user.id}`", parse_mode="Markdown")
        return
    await message.answer(f"Nama: {user.nama}\nRole: {user.role}\nAkses: {user.access_level}")


@router.message(F.contact)
async def on_contact(message: Message) -> None:
    await handle_shared_contact(message)


async def _jalankan_aksi(aksi: dict, *, pembuat: str) -> str:
    """Eksekusi aksi yang sudah dikonfirmasi. Kembalikan teks hasil."""
    if aksi.get("jenis") == "surat_tugas":
        p = aksi["params"]
        tgl = date.fromisoformat(p["tanggal_surat"])
        async with SessionLocal() as db:
            row = await penomoran.terbitkan_nomor_surat(
                db,
                kode="ST",
                divisi="HR",
                bulan=tgl.month,
                tahun=tgl.year,
                perihal=f"Surat Tugas — {p['nama']}",
                pihak=p["nama"],
                pembuat=pembuat,
            )
        naskah = surat_mod.surat_tugas(
            nomor=row.nomor_lengkap,
            nama=p["nama"],
            jabatan=p["jabatan"],
            tugas=p["tugas"],
            tempat=p["tempat"],
            waktu=p["waktu"],
            tanggal=tgl,
            no_pegawai=p.get("no_pegawai") or "-",
        )
        return (
            f"✅ Surat Tugas terbit.\nNomor resmi: {row.nomor_lengkap}\n"
            "(tersimpan di register nomor — anti-bentrok)\n\n"
            "— — — — — — — — — —\n"
            f"{naskah}"
        )
    return "Aksi tidak dikenal."


@router.message()
async def handle_message(message: Message) -> None:
    if not message.text:
        await message.answer("Kirim pesan teks ya.")
        return

    tg_id = message.from_user.id
    text = message.text.strip()
    lower = text.lower()

    async with SessionLocal() as db:
        user = await authenticate(db, tg_id)
    if not user:
        await unregistered_reply(message)
        return
    if user.role not in {"admin", "staff"}:
        await message.answer(
            "⛔ Kantor AI khusus *Direksi/Staff kantor*.\n"
            "Untuk input operasional pabrik, gunakan bot gudang.",
            parse_mode="Markdown",
        )
        return

    session = get_session(message.bot.id, tg_id)

    # ── Konfirmasi aksi konsekuensial yang tertunda ──
    if session.stage == "awaiting_kantor" and session.kantor_pending:
        if lower in CONFIRM_WORDS:
            aksi = session.kantor_pending
            session.stage = "idle"
            session.kantor_pending = None
            try:
                hasil = await _jalankan_aksi(aksi, pembuat=user.nama)
            except Exception:
                log.exception("jalankan aksi kantor gagal")
                await message.answer("⚠️ Gagal menjalankan aksi. Coba lagi sebentar.")
                return
            await message.answer(hasil)
            return
        if lower in CANCEL_WORDS:
            session.stage = "idle"
            session.kantor_pending = None
            await message.answer("Baik, dibatalkan. 👍")
            return
        # Selain ya/batal → batalkan usulan, proses sebagai pesan baru.
        session.stage = "idle"
        session.kantor_pending = None

    try:
        reply = await run_kantor_agent(text=text, role=user.role, nama_user=user.nama)
    except Exception:
        log.exception("run_kantor_agent gagal")
        await message.answer("⚠️ Maaf, ada kendala saat memproses. Coba ulangi ya.")
        return

    if reply.aksi:
        session.kantor_pending = reply.aksi
        session.stage = "awaiting_kantor"
        await message.answer(
            f"📝 Saya akan {reply.aksi['ringkasan']}.\n\n"
            "Balas *ya* untuk lanjut, atau *batal* untuk urungkan.",
            parse_mode="Markdown",
        )
        return

    await message.answer(reply.text or "Maaf, saya belum bisa menjawab itu.")
