"""Bot 'Kantor AI' — asisten eksekutif Direksi (dokumen / arsip / HR).

Persona TERPISAH dari bot operasional pabrik (gudang1/gudang2/admin). Tanya-jawab
& panduan dijawab agent langsung; setiap AKSI KONSEKUENSIAL (terbitkan nomor
surat, susun naskah) lewat pola usul→konfirmasi→eksekusi deterministik.

Akses: Direksi/Staff kantor (role admin/staff). Operator diarahkan ke bot pabrik.
"""
from __future__ import annotations

import logging
from datetime import date
from io import BytesIO

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bots.common import (
    CANCEL_WORDS,
    CONFIRM_WORDS,
    authenticate,
    get_session,
    handle_shared_contact,
    unregistered_reply,
)
from app.database import SessionLocal
from app.kantor import riwayat as riwayat_mod
from app.kantor.agent import run_kantor_agent
from app.kantor.triage import triage
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


@router.message(Command("lupakan"))
async def cmd_lupakan(message: Message) -> None:
    """Hapus ingatan percakapan pengguna ini (mulai obrolan dari awal)."""
    async with SessionLocal() as db:
        user = await authenticate(db, message.from_user.id)
    if not user or user.role not in {"admin", "staff"}:
        await unregistered_reply(message)
        return
    n = await riwayat_mod.lupakan(message.from_user.id)
    await message.answer(f"🧹 Ingatan percakapan dihapus ({n} baris). Kita mulai segar.")


@router.message(F.contact)
async def on_contact(message: Message) -> None:
    await handle_shared_contact(message)


@router.callback_query(F.data.startswith("kaksi:"))
async def on_persetujuan(cb: CallbackQuery) -> None:
    """Gerbang manusia: pemilik menekan ✅/❌ pada aksi Drive yang diajukan agen.

    Hanya Direksi/Staff kantor yang boleh memutuskan. Eksekusi DETERMINISTIK
    (tanpa LLM) lewat app.kantor.persetujuan — agen tak bisa menekan tombol ini.
    """
    from app.kantor import persetujuan as pst

    try:
        _, aksi, sid = cb.data.split(":", 2)
        aksi_id = int(sid)
    except Exception:
        await cb.answer("Data tombol tak valid.")
        return

    async with SessionLocal() as db:
        user = await authenticate(db, cb.from_user.id)
    if not user or user.role not in {"admin", "staff"}:
        await cb.answer("⛔ Hanya Direksi/Staff kantor yang boleh memutuskan.", show_alert=True)
        return

    if aksi == "ok":
        ok, hasil = await pst.eksekusi_pending(aksi_id, diputus_oleh=user.id)
        tanda = "✅ Disetujui & dijalankan" if ok else "⚠️ Gagal"
    else:
        ok, hasil = await pst.tolak_pending(aksi_id, diputus_oleh=user.id)
        tanda = "❌ Ditolak" if ok else "⚠️"

    asal = cb.message.text if cb.message else ""
    # Edit pesan tombol (buang tombol, tandai keputusan)…
    try:
        await cb.message.edit_text(f"{asal}\n\n— — —\n{tanda} oleh {user.nama}")
    except Exception:
        pass
    # …DAN kirim laporan JELAS sebagai pesan baru di chat (bukan sekadar edit tombol).
    try:
        await cb.message.answer(f"{tanda}.\n{hasil}" if hasil else f"{tanda}.")
    except Exception:
        pass
    await cb.answer((hasil or "Selesai.")[:190], show_alert=not ok)


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


async def _teks_dari_suara(message: Message) -> str | None:
    """Unduh voice note → transkrip via Gemini. None (sudah dibalas) bila gagal."""
    from app.kantor import suara
    if not suara.terkonfigurasi():
        await message.answer(
            "🎤 Fitur suara belum aktif di server (GROQ_API_KEY belum diset). "
            "Ketik saja dulu ya.")
        return None
    voice = message.voice or message.audio
    await message.answer("🎤 Sebentar, aku dengarkan…")
    try:
        buf = BytesIO()
        await message.bot.download(voice, destination=buf)
        teks = (await suara.transkrip(
            buf.getvalue(), getattr(voice, "mime_type", None) or "audio/ogg")).strip()
    except Exception:  # noqa: BLE001
        log.exception("transkrip voice gagal")
        await message.answer("Maaf, gagal memproses suara. Coba lagi atau ketik ya.")
        return None
    if not teks:
        await message.answer("Maaf, suaranya kurang jelas. Coba ulangi ya. 🎤")
        return None
    await message.answer(f'🎤 Kudengar: "{teks}"')
    return teks


@router.message()
async def handle_message(message: Message) -> None:
    tg_id = message.from_user.id

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

    # Teks dari pesan ketik ATAU transkrip voice note.
    if message.text:
        text = message.text.strip()
    elif message.voice or message.audio:
        text = await _teks_dari_suara(message)
        if not text:
            return  # sudah dibalas di helper
    else:
        await message.answer("Kirim pesan teks atau voice note ya. 🎤")
        return
    lower = text.lower()

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

    # Ingatan percakapan: muat konteks lalu, jalankan agen, simpan giliran.
    hist = await riwayat_mod.muat(tg_id)

    # ── Lapis TRIAGE murah (Haiku): pesan sepele dijawab langsung, hemat Sonnet.
    #    Konservatif — ragu/butuh data/tool → eskalasi ke agen di bawah.
    ditangani, balasan_triage = await triage(text, nama_user=user.nama, riwayat=hist)
    if ditangani:
        await riwayat_mod.simpan(tg_id, "user", text)
        await riwayat_mod.simpan(tg_id, "assistant", balasan_triage)
        await message.answer(balasan_triage)
        return

    try:
        reply = await run_kantor_agent(
            text=text, role=user.role, nama_user=user.nama, riwayat=hist
        )
    except Exception:
        log.exception("run_kantor_agent gagal")
        await message.answer("⚠️ Maaf, ada kendala saat memproses. Coba ulangi ya.")
        return

    asisten_isi = (
        f"(mengusulkan: {reply.aksi['ringkasan']})" if reply.aksi else (reply.text or "")
    )
    await riwayat_mod.simpan(tg_id, "user", text)
    await riwayat_mod.simpan(tg_id, "assistant", asisten_isi)

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
