"""Bot Gudang 1 (Operator Selepan) — fitur: input pembelian gabah natural."""
from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.ai.nlp_parser import (
    ParsedPurchase,
    apply_correction,
    parse_milling,
    parse_pengeringan,
    parse_purchase,
    parse_silo,
    parse_undo,
)
from app.bots.common import (
    CANCEL_WORDS,
    CONFIRM_WORDS,
    UNDO_PHRASES,
    authenticate,
    can_see_financials,
    get_session,
    handle_shared_contact,
    reset_draft,
    unregistered_reply,
)
from app.ai.fast_route import fast_domain
from app.ai.router import route_domain
from app.bots.agent_flow import agent_confirm_pending, maybe_answer_agent

_G1_DOMAINS = {"pembelian_gabah", "pengeringan", "silo_g1", "milling", "undo"}
from app.bots.detail_flow import maybe_answer_detail
from app.bots.jam_flow import maybe_answer_jam
from app.bots.notify import notify_roles
from app.services.analytics import biaya_produksi_detail
from app.bots.lookup_flow import maybe_answer_lookup
from app.bots.pending_flow import maybe_answer_pending
from app.bots.report_flow import maybe_answer_report
from app.bots.status_flow import maybe_answer_status
from app.bots.transfer_flow import maybe_answer_transfer
from app.database import BackdateError, SessionLocal
from app.gudang1.services.drying import (
    DryingError,
    active_drying_lot,
    add_batches_to_lot,
    create_drying_lot,
    finish_drying,
    laporan_pengeringan,
    log_cooling,
    log_moisture,
    resolve_batch_kodes,
    sole_active_lot_kode,
    sole_cooling_lot_kode,
    sole_dryer_lot_kode,
    start_drying,
)
from app.services.undo import UndoError, undo_last
from app.gudang1.services.purchase import (
    DailyLimitReached,
    create_purchase_batch,
)
from app.gudang1.services.milling import (
    MillingError,
    finish_milling,
    laporan_milling,
    log_progress,
    sole_active_milling_kode,
    start_milling,
    stok_pk_gudang1,
)
from app.gudang1.services.silo import (
    SiloError,
    keluar_silo,
    laporan_silo,
    masuk_silo,
    moving_finished,
    moving_started,
)

router = Router(name="gudang1")
log = logging.getLogger("bots.gudang1")

AI_ERROR_MSG = (
    "⚠️ Maaf, layanan AI sedang tidak bisa dihubungi (mungkin kredit API habis "
    "atau gangguan sementara). Coba lagi beberapa saat, atau hubungi admin."
)

WELCOME = (
    "🏭 *Bot Gudang 1 — Selepan*\n\n"
    "Catat pembelian gabah cukup dengan pesan biasa, contoh:\n"
    "• `gabah masuk dari pak budi 8 ton plat B 1234 XY`\n"
    "• `gabah kering dari pak hasan 8 ton, kadar air 13%`\n\n"
    "Saya akan merangkum & minta konfirmasi sebelum menyimpan."
)


def _fmt_berat(kg: float | None) -> str:
    if kg is None:
        return "-"
    return f"{kg:,.0f} kg".replace(",", ".")


def _missing_fields(d: ParsedPurchase) -> list[str]:
    missing = []
    if not d.nama_supplier:
        missing.append("nama supplier")
    if not d.berat_kg:
        missing.append("berat gabah")
    # Kondisi WAJIB dipastikan (menentukan proses & jenis PK KS/KL). Bila
    # operator tak menyebut basah/kering, bot menanyakannya — bukan menebak.
    if d.kondisi_gabah not in ("basah", "kering"):
        missing.append("kondisi gabah")
    if not d.no_polisi_truk:
        missing.append("plat truk")
    return missing


def _summary(d: ParsedPurchase) -> str:
    jns = {"basah": "KS", "kering": "KL"}.get(d.kondisi_gabah or "")
    kondisi = f"{d.kondisi_gabah}" + (f"  →  PK {jns}" if jns else "")
    lines = [
        "Oke, saya catat:",
        f"• Supplier: *{d.nama_supplier}*",
        f"• Kondisi: {kondisi}",
        f"• Berat: {_fmt_berat(d.berat_kg)}",
    ]
    if d.kadar_air_awal_persen is not None:
        lines.append(f"• Kadar air awal: {d.kadar_air_awal_persen:g}%")
    lines.append(f"• No. Polisi: {d.no_polisi_truk or '-'}")
    if d.tanggal is not None or d.jam is not None:
        tg = f"{d.tanggal:%d-%m-%Y}" if d.tanggal else "hari ini"
        jm = f" jam {d.jam:%H:%M}" if d.jam else ""
        lines.append(f"• 📅 Dicatat untuk: *{tg}{jm}*")
    lines.append("\nKonfirmasi simpan? (ketik *ya* / *batal*)")
    return "\n".join(lines)


def _ask_missing(missing: list[str]) -> str:
    if missing == ["kondisi gabah"]:
        return (
            "Gabah yang masuk ini *basah* atau *kering*?\n"
            "_(menentukan proses & jenis PK: basah → KS, kering → KL)_"
        )
    if len(missing) == 1:
        return f"Baik. {missing[0].capitalize()} berapa/siapa ya?"
    labels = [
        f"{m} (basah/kering)" if m == "kondisi gabah" else m for m in missing
    ]
    return "Data belum lengkap. Mohon sebutkan: " + ", ".join(labels) + "."


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    async with SessionLocal() as db:
        user = await authenticate(db, message.from_user.id)
    if not user:
        await _reject_unregistered(message)
        return
    await message.answer(WELCOME, parse_mode="Markdown")


async def _reject_unregistered(message: Message) -> None:
    await unregistered_reply(message)


@router.message(F.contact)
async def on_contact(message: Message) -> None:
    """Aktivasi akun via kontak (untuk user yang didaftarkan pakai nomor HP)."""
    await handle_shared_contact(message)


@router.message()
async def handle_message(message: Message) -> None:
    if not message.text:
        await message.answer("Untuk saat ini kirim pesan teks ya. (Suara menyusul.)")
        return

    tg_id = message.from_user.id
    text = message.text.strip()
    lower = text.lower()

    async with SessionLocal() as db:
        user = await authenticate(db, tg_id)
        if not user:
            await _reject_unregistered(message)
            return

        session = get_session(message.bot.id, tg_id)

        # ── Undo tindakan terakhir (kata kunci cepat) ──
        if any(p in lower for p in UNDO_PHRASES):
            try:
                msg = await undo_last(db, actor=user, actor_ids=[user.id], scope_label=None)
                await message.answer(msg)
            except UndoError as e:
                await message.answer(str(e.args[0]) if e.args else "Tidak bisa di-undo.")
            session.last_batch_id = None
            session.last_batch_kode = None
            return

        # ── Konfirmasi override (admin/staff mengerjakan tugas operator) ──
        if session.stage == "awaiting_override":
            if lower in CONFIRM_WORDS:
                txt = session.override_text or ""
                session.stage = "idle"
                session.override_text = None
                session.override_active = True
                try:
                    await _process_fresh(message, db, user, txt, session)
                finally:
                    session.override_active = False
                return
            if lower in CANCEL_WORDS:
                session.stage = "idle"
                session.override_text = None
                await message.answer("Baik, dibatalkan.")
                return
            # Bukan ya/batal: batalkan override, proses sebagai pesan baru.
            session.stage = "idle"
            session.override_text = None

        # ── Konfirmasi gabung batch ke lot yang masih di dryer ──
        if session.stage == "awaiting_merge":
            if lower in CONFIRM_WORDS:
                lot_kode = session.merge_lot
                kodes = session.merge_kodes or []
                session.stage = "idle"
                session.merge_lot = None
                session.merge_kodes = None
                try:
                    res = await add_batches_to_lot(
                        db, user=user, kode_lot=lot_kode, kode_batch_list=kodes
                    )
                except DryingError as e:
                    await message.answer(str(e.args[0]) if e.args else "Gagal menggabung.")
                    return
                session.ctx_lot = res.lot.kode_lot
                session.ctx_last = "lot"
                total = f"{res.total_kg:,.0f}".replace(",", ".")
                await message.answer(
                    f"✓ Digabung ke *{res.lot.kode_lot}*.\n"
                    f"• Batch sekarang: {', '.join(res.batch_kodes)}\n"
                    f"• Total: {total} kg",
                    parse_mode="Markdown",
                )
                return
            if lower in CANCEL_WORDS:
                session.stage = "idle"
                session.merge_lot = None
                session.merge_kodes = None
                await message.answer(
                    "Baik, tidak digabung. Kosongkan dryer dulu (pindahkan ke silo) "
                    "sebelum membentuk lot baru."
                )
                return
            # Bukan ya/tidak: batalkan pending, proses sebagai pesan baru.
            session.stage = "idle"
            session.merge_lot = None
            session.merge_kodes = None

        # ── Sedang menunggu konfirmasi ──
        if session.stage == "awaiting_confirmation" and session.draft:
            if lower in CONFIRM_WORDS:
                await _save(message, db, user, session)
                return
            if lower in CANCEL_WORDS:
                reset_draft(message.bot.id, tg_id)
                await message.answer("Baik, dibatalkan. Tidak ada yang disimpan.")
                return
            # selain itu: anggap koreksi terhadap draft
            try:
                session.draft = await apply_correction(session.draft, text)
            except Exception:
                log.exception("apply_correction gagal")
                await message.answer(AI_ERROR_MSG)
                return
            await _prompt_next(message, tg_id, session)
            return

        # ── Sedang melengkapi data yang kurang (jawaban atas _ask_missing) ──
        if session.stage == "collecting" and session.draft:
            if lower in CANCEL_WORDS:
                reset_draft(message.bot.id, tg_id)
                await message.answer("Baik, dibatalkan. Tidak ada yang disimpan.")
                return
            # Jawaban ini melengkapi field yang kurang, bukan pembelian baru.
            try:
                session.draft = await apply_correction(session.draft, text)
            except Exception:
                log.exception("apply_correction gagal")
                await message.answer(AI_ERROR_MSG)
                return
            await _prompt_next(message, tg_id, session)
            return

        # ── Gabah kering menunggu tujuan: dryer / silo A / silo B ──
        if session.stage == "awaiting_kering_tujuan" and session.kering_batch:
            bk = session.kering_batch
            if lower in CANCEL_WORDS:
                session.stage = "idle"
                session.kering_batch = None
                await message.answer("Baik. Gabah tersimpan, penempatan bisa nanti.")
                return
            if any(w in lower for w in ("dryer", "pengering", "oven", "keringkan")):
                session.stage = "idle"
                session.kering_batch = None
                lot_kode, note = await _auto_masuk_dryer(db, user, bk)
                if lot_kode:
                    session.ctx_lot = lot_kode
                    session.ctx_last = "lot"
                    await message.answer(
                        f"🌫️ {bk} masuk dryer ({note}).\n"
                        f"⏸️ Ketik `mulai pengeringan {lot_kode}` saat dipanaskan.",
                        parse_mode="Markdown",
                    )
                else:
                    await message.answer(f"⚠️ Belum bisa masuk dryer: {note}.")
                return
            sm = re.search(r"silo\s*([ab])\b", lower) or re.search(r"^\s*([ab])\s*$", lower)
            if sm:
                session.stage = "idle"
                session.kering_batch = None
                try:
                    res = await masuk_silo(
                        db, user=user, nama_silo=sm.group(1).upper(),
                        kode_lot=None, kode_batch=bk,
                    )
                    session.ctx_silo = res.nama_silo
                    session.ctx_last = "lot"
                    total = f"{res.kg:,.0f}".replace(",", ".")
                    gab = " (digabung)" if res.digabung else ""
                    await message.answer(
                        f"✓ {bk} masuk *Silo {res.nama_silo}*{gab} (kering langsung).\n"
                        f"• Berat: {total} kg",
                        parse_mode="Markdown",
                    )
                except SiloError as e:
                    await message.answer(str(e.args[0]) if e.args else "Gagal masukkan silo.")
                return
            await message.answer("Balas `dryer`, `silo A`, atau `silo B` ya.")
            return

        # ── Konfirmasi usulan tulis dari agent (pola agentic) ──
        if session.stage == "awaiting_agent_write":
            async def _dispatch(cmd: str) -> bool:
                return await _try_operator_commands(message, db, user, cmd, session)
            if await agent_confirm_pending(message, lower, session, dispatch=_dispatch):
                return
            # bukan ya/batal → proses sebagai pesan baru di bawah.

        # ── Pesan baru ──
        await _process_fresh(message, db, user, text, session)


# Aksi fisik yang domainnya operator (admin/staff perlu override).
async def _require_operator(message: Message, user, session, text: str, label: str) -> bool:
    """True bila boleh lanjut (operator, atau override sedang aktif).

    Untuk admin/staff: kirim pengarahan ke operator + minta konfirmasi override.
    """
    if user.role == "operator" or session.override_active:
        return True
    session.stage = "awaiting_override"
    session.override_text = text
    await message.answer(
        f"ℹ️ *{label}* biasanya dikerjakan **Operator Gudang 1**.\n"
        "Kalau operator sedang berhalangan dan Anda ingin mengerjakannya "
        "sendiri (fallback), balas *ya* untuk lanjut, atau *batal*.",
        parse_mode="Markdown",
    )
    return False


async def _handle_undo(message: Message, db, user, text: str) -> bool:
    """Operator membatalkan tindakan TERAKHIR miliknya sendiri. True jika ditangani."""
    try:
        p = await parse_undo(text)
    except Exception:
        log.exception("parse_undo gagal")
        return False
    if not p.is_undo:
        return False
    try:
        msg = await undo_last(db, actor=user, actor_ids=[user.id], scope_label=None)
        await message.answer(msg)
    except UndoError as e:
        await message.answer(str(e.args[0]) if e.args else "Tidak bisa di-undo.")
    return True


async def _try_operator_commands(message: Message, db, user, text: str, session) -> bool:
    """Handler PERINTAH operator G1 (tulis): pembelian, pengeringan, silo, milling.

    True bila ditangani (termasuk saat menampilkan error/prompt). Dipakai jalur
    normal maupun saat menjalankan usulan tulis agent (butuh nilai balik bool)."""
    tg_id = message.from_user.id
    try:
        parsed = await parse_purchase(text)
    except Exception:
        log.exception("parse_purchase gagal")
        await message.answer(AI_ERROR_MSG)
        return True
    if parsed.is_pembelian_gabah:
        # Pembelian gabah = aksi fisik operator.
        if not await _require_operator(message, user, session, text, "Mencatat pembelian gabah"):
            return True
        session.draft = parsed
        await _prompt_next(message, tg_id, session)
        return True
    # Undo tindakan terakhir (frasa kaya: "batalkan lot terakhir").
    if await _handle_undo(message, db, user, text):
        return True
    # "selesai" ambigu (drying & milling bisa berbarengan) — tangani dulu.
    if await _handle_bare_finish(message, db, user, text, session):
        return True
    if await _handle_pengeringan(message, db, user, text, session):
        return True
    if await _handle_silo(message, db, user, text, session):
        return True
    if await _handle_milling(message, db, user, text, session):
        return True
    return False


async def _dispatch_operator(message: Message, db, user, text: str, session) -> bool:
    """Router SATU-panggilan → handler domainnya saja; fallback ke cascade penuh.

    Memangkas 'coba semua parser' (mahal, apalagi dgn Sonnet) jadi ~1 klasifikasi
    + 1 handler. Bila router meleset/domain tak dipetakan → cascade penuh (aman)."""
    domain = fast_domain(text, valid=_G1_DOMAINS) or await route_domain(text)
    direct = {
        "pengeringan": lambda: _handle_pengeringan(message, db, user, text, session),
        "silo_g1": lambda: _handle_silo(message, db, user, text, session),
        "milling": lambda: _handle_milling(message, db, user, text, session),
        "undo": lambda: _handle_undo(message, db, user, text),
    }
    h = direct.get(domain)
    if h is not None and await h():
        return True
    # pembelian_gabah, 'selesai' ambigu, domain lain, atau handler menolak →
    # cascade penuh (mencakup pembelian & bare-finish).
    return await _try_operator_commands(message, db, user, text, session)


async def _process_fresh(message: Message, db, user, text: str, session) -> None:
    """Proses pesan baru: pembelian, pengeringan, silo, milling, atau tanya-data."""
    if await _dispatch_operator(message, db, user, text, session):
        return
    fin = can_see_financials(user)
    if await maybe_answer_transfer(message, text, financial=fin):
        return
    if await maybe_answer_status(message, text):
        return
    if await maybe_answer_pending(message, text):
        return
    if await maybe_answer_jam(message, text):
        return
    if await maybe_answer_detail(message, text, session, financial=fin):
        return
    if await maybe_answer_lookup(message, text, session):
        return
    if await maybe_answer_report(message, text, session):
        return
    # ── Jaring terakhir: agent (pertanyaan bebas / analitik / usulan tulis) ──
    await maybe_answer_agent(
        message, role=user.role, financial=fin, allow_write=True, session=session,
    )


async def _prompt_next(message: Message, tg_id: int, session) -> None:
    """Minta data yang kurang, atau tampilkan ringkasan + minta konfirmasi."""
    missing = _missing_fields(session.draft)
    if missing:
        session.stage = "collecting"
        await message.answer(_ask_missing(missing))
        return
    session.stage = "awaiting_confirmation"
    await message.answer(_summary(session.draft), parse_mode="Markdown")


async def _save(message: Message, db, user, session) -> None:
    d = session.draft
    try:
        result = await create_purchase_batch(
            db,
            user=user,
            nama_supplier=d.nama_supplier,
            berat_kg=float(d.berat_kg),
            kondisi_gabah=d.kondisi_gabah,
            no_polisi_truk=d.no_polisi_truk,
            kadar_air_awal_persen=d.kadar_air_awal_persen,
            tanggal=d.tanggal, jam=d.jam,
        )
    except BackdateError as e:
        reset_draft(message.bot.id, message.from_user.id)
        await message.answer(f"⛔ {e.args[0] if e.args else 'Tanggal tidak valid.'}")
        return
    except DailyLimitReached as e:
        reset_draft(message.bot.id, message.from_user.id)
        tgl = f"{d.tanggal:%d-%m-%Y}" if d.tanggal else "hari ini"
        await message.answer(
            f"⛔ Sudah mencapai batas {e.args[0]} batch pembelian ({tgl}). "
            "Hubungi staff/admin bila perlu pengecualian."
        )
        return

    batch = result.batch
    session.stage = "idle"
    session.draft = None
    session.last_batch_id = batch.id
    session.last_batch_kode = batch.kode_batch
    session.last_batch_time = batch.waktu_pembelian
    session.ctx_batch = batch.kode_batch

    extra = ""
    if result.supplier_created:
        extra = f"\n_Supplier baru '{result.supplier.nama_supplier}' ditambahkan._"
    note_kering = ""
    if d.kondisi_gabah == "kering":
        note_kering = "\nℹ️ Gabah kering — penempatan silo/pengeringan dicatat di langkah berikutnya."

    if d.tanggal is not None or d.jam is not None:
        _tg = f"{d.tanggal:%d-%m-%Y}" if d.tanggal else f"{batch.waktu_pembelian:%d-%m-%Y}"
        _jm = f" jam {d.jam:%H:%M}" if d.jam else ""
        tgl_note = f"\n📅 Dicatat untuk *{_tg}{_jm}*."
    else:
        tgl_note = ""
    base = (
        f"✓ Tersimpan. Kode batch: *{batch.kode_batch}*{tgl_note}\n"
        f"Menunggu verifikasi harga oleh staff/admin.{extra}"
    )

    if d.kondisi_gabah == "basah":
        # Gabah BASAH → OTOMATIS masuk dryer (belum mulai pengeringan).
        lot_kode, note = await _auto_masuk_dryer(db, user, batch.kode_batch)
        if lot_kode:
            session.ctx_lot = lot_kode
            session.ctx_last = "lot"
            await message.answer(
                base + f"\n\n🌫️ *Otomatis masuk dryer* ({note}).\n"
                f"⏸️ Belum mulai pengeringan — ketik `mulai pengeringan {lot_kode}` "
                "saat pemanasan dijalankan.",
                parse_mode="Markdown",
            )
        else:
            await message.answer(
                base + f"\n\n⚠️ Belum bisa auto-masuk dryer: {note}.\n"
                f"Masukkan manual: `keringkan {batch.kode_batch}`.",
                parse_mode="Markdown",
            )
        return

    # Gabah KERING → bot TANYA tujuan (dryer atau silo A/B).
    session.stage = "awaiting_kering_tujuan"
    session.kering_batch = batch.kode_batch
    await message.answer(
        base + "\n\n🌾 Gabah *kering*. Mau *masuk dryer* atau langsung ke "
        "*Silo A / Silo B*?\n_(balas: `dryer` / `silo A` / `silo B`)_",
        parse_mode="Markdown",
    )


async def _auto_masuk_dryer(db, user, batch_kode: str) -> tuple[str | None, str]:
    """Masukkan batch ke dryer otomatis: gabung ke lot 'di_dryer' sekondisi bila
    ada, else buat lot baru. Kembalikan (kode_lot, catatan) atau (None, alasan)."""
    try:
        active = await active_drying_lot(db)
        if active is not None and active.status == "di_dryer":
            res = await add_batches_to_lot(
                db, user=user, kode_lot=active.kode_lot, kode_batch_list=[batch_kode]
            )
            return res.lot.kode_lot, f"digabung ke {res.lot.kode_lot}"
        if active is not None:
            return None, f"dryer masih dipakai {active.kode_lot}"
        res = await create_drying_lot(db, user=user, kode_batch_list=[batch_kode])
        return res.lot.kode_lot, f"lot baru {res.lot.kode_lot}"
    except DryingError as e:
        return None, str(e.args[0]) if e.args else "tak bisa masuk dryer otomatis"


# ─────────────────────────── Pengeringan ───────────────────────────
_GB_RE = re.compile(r"GB[-\s]?(\d{8})[-\s]?(\d{2})", re.IGNORECASE)
_LOT_RE = re.compile(r"LOT[-\s]?(\d{8})[-\s]?(\d{2})", re.IGNORECASE)
_MIL_RE = re.compile(r"MIL[-\s]?(\d{8})[-\s]?(\d{2})", re.IGNORECASE)


def _mil_code(text: str) -> str | None:
    m = _MIL_RE.search(text)
    return f"MIL-{m.group(1)}-{m.group(2)}" if m else None


def _gb_list(text: str) -> list[str]:
    return [f"GB-{m.group(1)}-{m.group(2)}" for m in _GB_RE.finditer(text)]


def _lot_code(text: str) -> str | None:
    m = _LOT_RE.search(text)
    return f"LOT-{m.group(1)}-{m.group(2)}" if m else None


def _mentions_drying(text: str) -> bool:
    """Teks jelas menyebut pengeringan (bukan milling)?"""
    low = text.lower()
    return any(w in low for w in ("kering", "oven", "dryer", "pengering", "jemur"))


def _mentions_milling(text: str) -> bool:
    """Teks jelas menyebut milling/giling?"""
    low = text.lower()
    return any(w in low for w in ("selep", "giling", "milling", "husking", "pecah kulit"))


def _mentions_moving(text: str) -> bool:
    """Teks tentang pemindahan gabah dryer→silo (punya alur selesai sendiri)?"""
    low = text.lower()
    return any(w in low for w in ("pindah", "pemindahan"))


def _is_bare_finish(text: str) -> bool:
    """'selesai/beres/kelar' tanpa kode & tanpa penanda domain (ambigu).

    Pemindahan (pindah dryer→silo) punya alur 'pindah_selesai' sendiri di
    _handle_silo, jadi JANGAN ditangkap sebagai bare-finish."""
    low = text.lower()
    if not any(w in low for w in ("selesai", "beres", "kelar", "rampung")):
        return False
    if _lot_code(text) or _mil_code(text):
        return False
    if _mentions_moving(text):
        return False
    return not (_mentions_drying(text) or _mentions_milling(text))


async def _handle_bare_finish(message: Message, db, user, text: str, session) -> bool:
    """Tangani 'selesai' ambigu: pengeringan & milling bisa berjalan bersamaan.

    Pakai konteks terakhir; bila dua-duanya aktif tanpa konteks jelas, tanya.
    """
    if not _is_bare_finish(text):
        return False
    if not await _require_operator(message, user, session, text, "Menandai proses selesai"):
        return True

    lot = await sole_active_lot_kode(db)      # satu-satunya drying 'proses', else None
    mill = await sole_active_milling_kode(db)  # satu-satunya milling 'proses', else None

    target = None  # ("drying"|"milling", kode)
    if lot and mill:
        if session.ctx_last == "lot":
            target = ("drying", lot)
        elif session.ctx_last == "mil":
            target = ("milling", mill)
        else:
            await message.answer(
                "Yang mana yang selesai?\n"
                f"• Pengeringan *{lot}*\n"
                f"• Giling *{mill}*\n"
                "Sebutkan, mis. `pengeringan selesai` / `giling selesai`.",
                parse_mode="Markdown",
            )
            return True
    elif lot:
        target = ("drying", lot)
    elif mill:
        target = ("milling", mill)
    else:
        await message.answer(
            "Tidak ada proses tunggal yang bisa diselesaikan. Sebutkan kodenya, "
            "mis. `LOT-... selesai` atau `MIL-... selesai`."
        )
        return True

    try:
        if target[0] == "drying":
            lotobj, dur = await finish_drying(db, user=user, kode_lot=target[1])
            session.ctx_lot = lotobj.kode_lot
            session.ctx_last = "lot"
            await message.answer(
                f"✓ {lotobj.kode_lot} selesai dikeringkan. Durasi {dur:.1f} jam.\n"
                "Berikutnya: pendinginan (gabah tetap di dryer)."
            )
        else:
            res = await finish_milling(db, user=user, kode_proses=target[1])
            session.ctx_mil = res.proc.kode_proses
            session.ctx_last = "mil"
            silo = f" Silo {res.nama_silo} otomatis dikosongkan." if res.nama_silo else ""
            jn = f" ({res.jenis})" if res.jenis else ""
            await message.answer(
                f"✓ {res.proc.kode_proses} selesai giling.{silo}\n"
                f"• PK dihasilkan: {_fmt_berat(res.produced)}{jn} — semua *siap kirim*.",
                parse_mode="Markdown",
            )
    except (DryingError, MillingError) as e:
        await message.answer(str(e.args[0]) if e.args else "Terjadi kesalahan.")
    return True


async def _handle_pengeringan(message: Message, db, user, text: str, session) -> bool:
    """Tangani intent pengeringan. Kembalikan True jika sudah ditangani."""
    try:
        p = await parse_pengeringan(text)
    except Exception:
        log.exception("parse_pengeringan gagal")
        return False
    if p.intent == "bukan_pengeringan":
        return False

    _WRITE = {
        "bentuk_lot": "Memasukkan gabah ke dryer",
        "mulai_pengeringan": "Memulai pengeringan",
        "log_kadar_air": "Mencatat kadar air",
        "log_pendinginan": "Mencatat pendinginan",
        "selesai_pengeringan": "Menandai pengeringan selesai",
    }
    if p.intent in _WRITE and not await _require_operator(
        message, user, session, text, _WRITE[p.intent]
    ):
        return True

    # Kode lot dari pesan, konteks, atau satu-satunya lot yang relevan.
    lot_kode = p.kode_lot or _lot_code(text) or session.ctx_lot
    if not lot_kode and p.intent in ("log_kadar_air", "selesai_pengeringan"):
        lot_kode = await sole_active_lot_kode(db)
    if not lot_kode and p.intent == "mulai_pengeringan":
        lot_kode = await sole_dryer_lot_kode(db)
    if not lot_kode and p.intent == "log_pendinginan":
        lot_kode = await sole_cooling_lot_kode(db)
    try:
        if p.intent == "bentuk_lot":
            kodes = p.kode_batch_list or _gb_list(text)
            if not kodes and p.semua_batch:
                kodes = await resolve_batch_kodes(
                    db, kode_list=None, urutan_list=None, semua=True
                )
            elif not kodes and p.batch_urutan_list:
                kodes = await resolve_batch_kodes(
                    db, kode_list=None, urutan_list=p.batch_urutan_list
                )
            # Dryer belum kosong? Tawarkan gabung ke lot yang sedang dikeringkan.
            active = await active_drying_lot(db) if kodes else None
            if active is not None:
                session.merge_lot = active.kode_lot
                session.merge_kodes = kodes
                session.stage = "awaiting_merge"
                await message.answer(
                    f"⚠️ Dryer belum kosong — masih ada *{active.kode_lot}* di dalamnya.\n"
                    f"Gabungkan {', '.join(kodes)} ke {active.kode_lot}? "
                    "(*ya* untuk gabung / *tidak* untuk batal)",
                    parse_mode="Markdown",
                )
                return True
            res = await create_drying_lot(
                db, user=user, kode_batch_list=kodes, tanggal=p.tanggal, jam=p.jam
            )
            session.ctx_lot = res.lot.kode_lot
            session.ctx_last = "lot"
            total = f"{res.total_kg:,.0f}".replace(",", ".")
            await message.answer(
                f"✓ Lot *{res.lot.kode_lot}* masuk dryer ({res.kondisi}).\n"
                f"• Batch: {', '.join(res.batch_kodes)}\n"
                f"• Total: {total} kg\n"
                "⏸️ *Belum mulai pengeringan.* Ketik `mulai pengeringan "
                f"{res.lot.kode_lot}` saat pemanasan dijalankan.",
                parse_mode="Markdown",
            )
        elif p.intent == "mulai_pengeringan":
            lot = await start_drying(
                db, user=user, kode_lot=lot_kode, tanggal=p.tanggal, jam=p.jam
            )
            session.ctx_lot = lot.kode_lot
            session.ctx_last = "lot"
            await message.answer(
                f"🔥 Pengeringan *{lot.kode_lot}* dimulai.\n"
                "ℹ️ Update kadar air minimal tiap 5 jam. "
                "Ketik `pengeringan selesai` bila sudah kering.",
                parse_mode="Markdown",
            )
        elif p.intent == "log_kadar_air":
            res = await log_moisture(
                db,
                user=user,
                kode_lot=lot_kode,
                indikator=p.kadar_air_indikator,
                tes_manual=p.kadar_air_tes_manual,
                tanggal=p.tanggal, jam=p.jam,
            )
            session.ctx_lot = res.lot.kode_lot
            session.ctx_last = "lot"
            jeda = (
                f" (jeda {res.jam_sejak_log_sebelumnya:.1f} jam dari log sebelumnya)"
                if res.jam_sejak_log_sebelumnya is not None
                else ""
            )
            await message.answer(
                f"✓ Kadar air {res.lot.kode_lot} tercatat{jeda}.\n"
                f"{res.jam_sejak_mulai:.1f} jam sejak mulai pengeringan."
            )
        elif p.intent == "log_pendinginan":
            lot, cnt, first = await log_cooling(
                db, user=user, kode_lot=lot_kode, catatan=p.catatan, tanggal=p.tanggal, jam=p.jam
            )
            session.ctx_lot = lot.kode_lot
            session.ctx_last = "lot"
            note = f" — {p.catatan}" if p.catatan else ""
            mulai = " (mulai)" if first else f" (log ke-{cnt})"
            await message.answer(
                f"✓ Pendinginan {lot.kode_lot} tercatat{mulai}{note}.\n"
                "Gabah tetap di dryer (sirkulasi udara) sampai dipindah ke silo."
            )
        elif p.intent == "selesai_pengeringan":
            lot, dur = await finish_drying(
                db, user=user, kode_lot=lot_kode, tanggal=p.tanggal, jam=p.jam
            )
            session.ctx_lot = lot.kode_lot
            session.ctx_last = "lot"
            await message.answer(
                f"✓ {lot.kode_lot} selesai dikeringkan (pemanasan berhenti). "
                f"Durasi {dur:.1f} jam.\n"
                "❄️ *Otomatis masuk fase pendinginan* (gabah tetap di dryer). "
                "Saat dipindah ke silo, pendinginan otomatis ditandai selesai.",
                parse_mode="Markdown",
            )
        elif p.intent == "laporan_pengeringan":
            # Laporan: pakai kode eksplisit; tanpa kode -> tampilkan semua.
            teks = await laporan_pengeringan(db, p.kode_lot or _lot_code(text))
            await message.answer(teks)
        else:
            return False
    except (DryingError, BackdateError) as e:
        await message.answer(str(e.args[0]) if e.args else "Terjadi kesalahan pengeringan.")
    return True


# ─────────────────────────── Silo ───────────────────────────
async def _handle_silo(message: Message, db, user, text: str, session) -> bool:
    """Tangani intent silo Gudang 1. Kembalikan True jika sudah ditangani."""
    try:
        p = await parse_silo(text)
    except Exception:
        log.exception("parse_silo gagal")
        return False
    if p.intent == "bukan_silo":
        return False

    _WRITE = {
        "masuk_silo": "Memasukkan gabah ke silo",
        "pindah_mulai": "Mencatat mulai pemindahan ke silo",
        "pindah_selesai": "Mencatat pemindahan ke silo selesai",
        "keluar_silo": "Mengosongkan silo",
    }
    if p.intent in _WRITE and not await _require_operator(
        message, user, session, text, _WRITE[p.intent]
    ):
        return True

    nama_silo = p.nama_silo or session.ctx_silo
    try:
        if p.intent == "masuk_silo":
            kode_lot = p.kode_lot or _lot_code(text)
            kode_batch = None if kode_lot else (p.kode_batch or (_gb_list(text) or [None])[0])
            # Tanpa lot/batch eksplisit -> pakai lot dari konteks ("masukkan ke silo A").
            if not kode_lot and not kode_batch:
                kode_lot = session.ctx_lot
            res = await masuk_silo(
                db, user=user, nama_silo=nama_silo, kode_lot=kode_lot,
                kode_batch=kode_batch, tanggal=p.tanggal, jam=p.jam,
            )
            session.ctx_silo = res.nama_silo
            session.ctx_lot = res.isi  # isi selalu kode lot (termasuk kering langsung)
            session.ctx_last = "lot"
            asal = "dari pengeringan" if res.tipe == "dari_pengeringan" else "kering langsung"
            total = f"{res.kg:,.0f}".replace(",", ".")
            if res.digabung:
                await message.answer(
                    f"✓ Digabung ke *{res.isi}* di Silo {res.nama_silo} (kering langsung).\n"
                    f"• Total di silo kini: {total} kg",
                    parse_mode="Markdown",
                )
            else:
                dingin = (
                    "\n❄️ Pendinginan otomatis ditandai selesai."
                    if res.tipe == "dari_pengeringan" else ""
                )
                await message.answer(
                    f"✓ {res.isi} masuk *Silo {res.nama_silo}* ({asal}).\n"
                    f"• Berat: {total} kg{dingin}",
                    parse_mode="Markdown",
                )
        elif p.intent == "pindah_mulai":
            kode_lot = (
                p.kode_lot or _lot_code(text) or session.ctx_lot
                or await sole_cooling_lot_kode(db)
            )
            lot_kode, silo = await moving_started(
                db, user=user, nama_silo=nama_silo, kode_lot=kode_lot
            )
            session.ctx_lot = lot_kode
            session.ctx_last = "lot"
            tujuan = f" ke *Silo {silo}*" if silo else ""
            await message.answer(
                f"✓ Dicatat: mulai pindah {lot_kode}{tujuan}.\n"
                "❄️ Pendinginan otomatis ditandai selesai.\n"
                "_Bila sudah sampai di silo, ketik `pemindahan selesai`._",
                parse_mode="Markdown",
            )
        elif p.intent == "pindah_selesai":
            kode_lot = (
                p.kode_lot or _lot_code(text) or session.ctx_lot
                or await sole_cooling_lot_kode(db)
            )
            res = await moving_finished(
                db, user=user, nama_silo=nama_silo, kode_lot=kode_lot
            )
            session.ctx_silo = res.nama_silo
            session.ctx_lot = res.kode_lot
            session.ctx_last = "lot"
            if res.kondisi == "intake":
                total = f"{res.kg:,.0f}".replace(",", ".") if res.kg else "-"
                await message.answer(
                    f"✓ {res.kode_lot} selesai dipindah ke *Silo {res.nama_silo}*.\n"
                    f"• Tercatat di silo, dryer kini kosong.\n"
                    f"• Berat: {total} kg",
                    parse_mode="Markdown",
                )
            else:
                await message.answer(
                    f"✓ Dicatat: pemindahan {res.kode_lot} ke *Silo {res.nama_silo}* "
                    "selesai (gabah sudah tercatat di silo sebelumnya).",
                    parse_mode="Markdown",
                )
        elif p.intent == "keluar_silo":
            nama = await keluar_silo(
                db, user=user, nama_silo=nama_silo, tanggal=p.tanggal, jam=p.jam
            )
            session.ctx_silo = nama
            await message.answer(f"✓ Silo {nama} dikosongkan.")
        elif p.intent == "laporan_silo":
            await message.answer(await laporan_silo(db, p.nama_silo))
        else:
            return False
    except (SiloError, BackdateError) as e:
        await message.answer(str(e.args[0]) if e.args else "Terjadi kesalahan silo.")
    return True


# ─────────────────────────── Milling ───────────────────────────
async def _handle_milling(message: Message, db, user, text: str, session) -> bool:
    """Tangani intent milling / pecah kulit. Kembalikan True jika ditangani."""
    try:
        p = await parse_milling(text)
    except Exception:
        log.exception("parse_milling gagal")
        return False
    if p.intent == "bukan_milling":
        return False

    _WRITE = {
        "mulai_milling": "Memulai giling",
        "progress_milling": "Mencatat hasil giling",
        "selesai_milling": "Menandai giling selesai",
    }
    if p.intent in _WRITE and not await _require_operator(
        message, user, session, text, _WRITE[p.intent]
    ):
        return True

    # Kode proses dari pesan, konteks, atau satu-satunya giling yang berjalan.
    kode = p.kode_proses or _mil_code(text) or session.ctx_mil
    if not kode and p.intent in ("progress_milling", "selesai_milling"):
        kode = await sole_active_milling_kode(db)
    try:
        if p.intent == "mulai_milling":
            res = await start_milling(
                db, user=user, nama_silo=p.nama_silo or session.ctx_silo, tanggal=p.tanggal, jam=p.jam
            )
            session.ctx_mil = res.proc.kode_proses
            session.ctx_last = "mil"
            await message.answer(
                f"✓ Mulai giling *{res.proc.kode_proses}* dari Silo {res.nama_silo}.\n"
                f"• Gabah masuk: {_fmt_berat(res.berat_masuk)}\n"
                "Catat progress PK berkala, mis. `progress giling "
                f"{res.proc.kode_proses} 5 ton`.",
                parse_mode="Markdown",
            )
        elif p.intent == "progress_milling":
            res = await log_progress(
                db, user=user, kode_proses=kode, berat_kumulatif=p.berat_kg, tanggal=p.tanggal, jam=p.jam
            )
            session.ctx_mil = res.proc.kode_proses
            session.ctx_last = "mil"
            rend = f" · rendemen ~{res.rendemen_persen:.1f}%" if res.rendemen_persen else ""
            jn = f" *{res.jenis}*" if res.jenis else ""
            await message.answer(
                f"✓ Hasil PK{jn} {res.proc.kode_proses}: "
                f"{_fmt_berat(res.berat_kumulatif)}{rend}.\n"
                "_Otomatis jadi stok siap kirim._",
                parse_mode="Markdown",
            )
        elif p.intent == "selesai_milling":
            res = await finish_milling(db, user=user, kode_proses=kode, tanggal=p.tanggal, jam=p.jam)
            session.ctx_mil = res.proc.kode_proses
            session.ctx_last = "mil"
            silo = f" Silo {res.nama_silo} otomatis dikosongkan." if res.nama_silo else ""
            jn = f" ({res.jenis})" if res.jenis else ""
            await message.answer(
                f"✓ {res.proc.kode_proses} selesai giling.{silo}\n"
                f"• PK dihasilkan: {_fmt_berat(res.produced)}{jn} — semua *siap kirim*.\n"
                "_QC & verifikasi output oleh staff/admin menyusul._",
                parse_mode="Markdown",
            )
            # Laporan HPP otomatis ke admin/staff (angka sementara bila output
            # PK belum diverifikasi).
            try:
                laporan = await biaya_produksi_detail(db, res.proc.kode_proses)
                await notify_roles(
                    f"✅ *{res.proc.kode_proses} selesai giling* — laporan HPP:\n\n"
                    f"{laporan}\n\n_Angka sementara sampai output PK diverifikasi._"
                )
            except Exception:
                log.exception("gagal kirim laporan HPP")
        elif p.intent == "laporan_milling":
            # Laporan: kode eksplisit saja; tanpa kode -> semua proses.
            await message.answer(await laporan_milling(db, p.kode_proses or _mil_code(text)))
        elif p.intent == "stok_pk":
            await message.answer(await stok_pk_gudang1(db))
        else:
            return False
    except (MillingError, BackdateError) as e:
        await message.answer(str(e.args[0]) if e.args else "Terjadi kesalahan milling.")
    return True
