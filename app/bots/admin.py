"""Bot Admin (Staff & Admin) — kerangka Fase 1.

Auth aktif + utilitas /whoami & /daftar untuk mendaftarkan operator baru.
Verifikasi harga, analitik, dsb. menyusul di fase berikutnya.
"""
from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

from app.ai.nlp_parser import (
    ParsedVerification,
    parse_analitik,
    parse_gudang2,
    parse_milling_admin,
    parse_transfer,
    parse_undo,
    parse_user_admin,
    parse_verification,
)
from app.bots.common import (
    CANCEL_WORDS,
    CONFIRM_WORDS,
    authenticate,
    can_see_financials,
    can_transfer_pk,
    get_session,
    handle_shared_contact,
    reset_verif,
    unregistered_reply,
)
from app.ai.fast_route import fast_domain
from app.ai.router import route_domain
from app.bots.agent_flow import agent_confirm_pending, maybe_answer_agent

# Domain yang relevan untuk Bot Admin (fast-path hanya kembalikan ini).
_ADMIN_DOMAINS = {
    "transfer_pk", "milling", "gudang2", "kemasan", "barang_jadi",
    "barang_keluar", "kelola_user", "undo", "verifikasi_harga_gabah",
}
from app.bots.detail_flow import maybe_answer_detail
from app.bots.jam_flow import maybe_answer_jam
from app.bots.lookup_flow import maybe_answer_lookup
from app.bots.pending_flow import maybe_answer_pending
from app.bots.report_flow import maybe_answer_report
from app.bots.status_flow import maybe_answer_status
from app.bots.silo_flow import maybe_answer_silo_report
from app.database import BackdateError, SessionLocal
from app.penggilingan.gudang2.service import (
    Gudang2Error,
    laporan_stok_gudang2,
    log_pk_qc,
    norm_jenis_pk,
    verify_pk_price,
)
from app.penggilingan.inventory.nlp import parse_barang_jadi, parse_kemasan, parse_keluar
from app.penggilingan.inventory.packaging import (
    InventoryError,
    beli_kemasan,
    laporan_stok_kemasan,
)
from app.penggilingan.inventory.finished_goods import (
    laporan_hpp_beras,
    laporan_stok_barang_jadi,
    set_harga_byproduct,
)
from app.penggilingan.inventory.outgoing import (
    jual_pk_langsung,
    kirim_bekatul,
    kirim_finished_goods,
    laporan_barang_keluar,
)
from app.models import User, Warehouse
from app.penggilingan.gudang1.services.milling import (
    MillingError,
    log_qc_milling,
    verify_milling_output,
)
from app.services.transfer import (
    TransferError,
    create_internal_transfer,
    laporan_pk_siap_transfer,
    laporan_transfer,
    pending_transfer_kg,
)
from app.services.analytics import (
    analisa_musiman,
    biaya_produksi_detail,
    biaya_proses_ringkas,
    hpp_trend,
    rekap_produksi_bulanan,
    simulasi_hpp,
    supplier_scorecard,
)
from app.services.dashboard import dashboard_data, render_dashboard_text
from app.services.report import resolve_batch_kode_ref
from app.services.undo import UndoError, resolve_actor_ids, undo_last
from app.services.user_admin import (
    UserAdminError,
    list_users,
    register_user,
    set_user_status,
)
from app.services.verification import (
    compute_price,
    get_batch_by_kode,
    verify_gabah_price,
)

router = Router(name="admin")
log = logging.getLogger("bots.admin")

AI_ERROR_MSG = (
    "⚠️ Layanan AI sedang tidak bisa dihubungi. Coba lagi sebentar lagi."
)


def _rp(n: float) -> str:
    return "Rp " + f"{n:,.0f}".replace(",", ".")


# Jaring pengaman: kenali kode batch GB-YYYYMMDD-NN meski Claude ragu / meleset.
_GB_RE = re.compile(r"GB[-\s]?(\d{8})[-\s]?(\d{2})", re.IGNORECASE)
# LOT- sejak istilahnya dibakukan; MIL- tetap dikenali demi kode lama.
_MIL_RE = re.compile(r"(LOT|MIL)[-\s]?(\d{8})[-\s]?(\d{2})", re.IGNORECASE)


def _extract_kode(text: str) -> str | None:
    m = _GB_RE.search(text)
    return f"GB-{m.group(1)}-{m.group(2)}" if m else None


def _extract_mil(text: str) -> str | None:
    m = _MIL_RE.search(text)
    return f"{m.group(1).upper()}-{m.group(2)}-{m.group(3)}" if m else None


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    async with SessionLocal() as db:
        user = await authenticate(db, message.from_user.id)
    if not user:
        await message.answer(
            "⛔ Belum terdaftar sebagai admin/staff. ID Telegram Anda: "
            f"`{message.from_user.id}`",
            parse_mode="Markdown",
        )
        return
    await message.answer(
        "👤 *Bot Admin / Staff*\n\n"
        "*Verifikasi harga gabah* — cukup ketik natural, contoh:\n"
        "• `verifikasi GB-20260702-01 total 42 juta`\n"
        "• `verifikasi harga GB-20260702-01 5.250 per kg`\n\n"
        "*Milling* (QC & output PK):\n"
        "• `QC LOT-20260702-01 kadar air 13 broken 5 susut 2`\n"
        "• `verifikasi output LOT-20260702-01 14 ton`\n\n"
        "*Kelola pengguna* (admin) — ketik natural:\n"
        "• `daftarkan operator Budi id 12345678 gudang 1`\n"
        "• `tambah staff Sari hp 081234567890`\n"
        "• `daftar user` · `nonaktifkan Budi`\n"
        "  (via HP: orangnya tekan tombol *Bagikan Nomor HP* untuk aktivasi)\n\n"
        "Perintah lain:\n"
        "• `/whoami` — lihat identitas Anda",
        parse_mode="Markdown",
    )


@router.message(Command("whoami"))
async def cmd_whoami(message: Message) -> None:
    async with SessionLocal() as db:
        user = await authenticate(db, message.from_user.id)
    if not user:
        await message.answer(f"Belum terdaftar. ID: `{message.from_user.id}`", parse_mode="Markdown")
        return
    await message.answer(
        f"Nama: {user.nama}\nRole: {user.role}\nAkses: {user.access_level}",
    )


async def _send_dashboard(message: Message, db, user) -> None:
    """Kirim dashboard produksi (staff/admin). Berisi data uang (HPP)."""
    if not can_see_financials(user):
        await message.answer("🔒 Dashboard produksi khusus staff/admin.")
        return
    data = await dashboard_data(db)
    await message.answer(render_dashboard_text(data), parse_mode="Markdown")


@router.message(Command("dashboard"))
async def cmd_dashboard(message: Message) -> None:
    async with SessionLocal() as db:
        user = await authenticate(db, message.from_user.id)
        if not user:
            await unregistered_reply(message)
            return
        await _send_dashboard(message, db, user)


@router.message(Command("daftar"))
async def cmd_daftar(message: Message) -> None:
    """Daftarkan pengguna baru. Hanya admin. Format: /daftar <tg_id> <nama> <role>."""
    async with SessionLocal() as db:
        actor = await authenticate(db, message.from_user.id)
        if not actor or actor.role != "admin":
            await message.answer("⛔ Hanya admin yang bisa mendaftarkan pengguna.")
            return

        parts = (message.text or "").split(maxsplit=3)
        if len(parts) < 4:
            await message.answer(
                "Format: `/daftar <telegram_id> <nama> <role>`\n"
                "Contoh: `/daftar 12345678 Budi operator`",
                parse_mode="Markdown",
            )
            return
        _, tg_id_str, nama, role = parts
        if role not in {"operator", "staff", "admin"}:
            await message.answer("Role harus: operator | staff | admin")
            return
        try:
            tg_id = int(tg_id_str)
        except ValueError:
            await message.answer("telegram_id harus angka.")
            return

        exists = (
            await db.execute(select(User).where(User.telegram_user_id == tg_id))
        ).scalars().first()
        if exists:
            await message.answer(f"ID {tg_id} sudah terdaftar sebagai {exists.nama}.")
            return

        # Operator Gudang 1 default ke gudang pertama (Selepan).
        g1 = (
            await db.execute(select(Warehouse).order_by(Warehouse.id))
        ).scalars().first()
        db.add(
            User(
                nama=nama,
                role=role,
                telegram_user_id=tg_id,
                default_warehouse_id=g1.id if g1 else None,
                access_level="full" if role in {"admin", "staff"} else "operational",
            )
        )
        await db.commit()
        await message.answer(f"✓ {nama} terdaftar sebagai {role} (ID {tg_id}).")


@router.message(F.contact)
async def on_contact(message: Message) -> None:
    """Aktivasi akun via kontak (untuk user yang didaftarkan pakai nomor HP)."""
    await handle_shared_contact(message)


def _merge_verif(cur: ParsedVerification, new: ParsedVerification) -> ParsedVerification:
    """Isi field yang masih kosong dari jawaban lanjutan staff."""
    return ParsedVerification(
        is_verifikasi_harga=True,
        kode_batch=new.kode_batch or cur.kode_batch,
        metode_harga=new.metode_harga or cur.metode_harga,
        nilai_rupiah=new.nilai_rupiah if new.nilai_rupiah is not None else cur.nilai_rupiah,
    )


def _pct(v: float | None) -> str:
    return f"{v:g}%" if v is not None else "-"


def _kg(kg: float) -> str:
    return f"{kg:,.0f} kg".replace(",", ".")


async def _handle_analitik(message: Message, db, user, text: str) -> bool:
    """Analitik strategis: supplier scorecard & tren HPP. True jika ditangani."""
    try:
        p = await parse_analitik(text)
    except Exception:
        log.exception("parse_analitik gagal")
        return False
    if p.intent != "bukan_analitik" and not can_see_financials(user):
        await message.answer("🔒 Analitik biaya & HPP khusus staff/admin.")
        return True
    if p.intent == "supplier_scorecard":
        await message.answer(await supplier_scorecard(db), parse_mode="Markdown")
        return True
    if p.intent == "hpp_tren":
        await message.answer(await hpp_trend(db), parse_mode="Markdown")
        return True
    if p.intent == "rincian_biaya":
        kode = p.kode_proses or _extract_kode(text)
        await message.answer(await biaya_produksi_detail(db, kode), parse_mode="Markdown")
        return True
    if p.intent == "simulasi_hpp":
        await message.answer(
            simulasi_hpp(
                p.harga_gabah, p.rendemen,
                kondisi=p.kondisi or "basah", langsung_silo=p.langsung_silo,
                berat_bahan=p.berat_bahan, berat_hasil=p.berat_hasil,
            ),
            parse_mode="Markdown",
        )
        return True
    if p.intent == "biaya_proses":
        await message.answer(await biaya_proses_ringkas(db), parse_mode="Markdown")
        return True
    if p.intent == "produksi_bulanan":
        await message.answer(await rekap_produksi_bulanan(db), parse_mode="Markdown")
        return True
    if p.intent == "analisa_musiman":
        await message.answer(await analisa_musiman(db), parse_mode="Markdown")
        return True
    return False


async def _handle_undo_admin(message: Message, db, user, text: str) -> bool:
    """Admin undo tindakan terakhir (bisa dibatasi per orang/role). True jika ditangani."""
    try:
        p = await parse_undo(text)
    except Exception:
        log.exception("parse_undo gagal")
        return False
    if not p.is_undo:
        return False
    if user.role != "admin":
        await message.answer("⛔ Hanya admin yang bisa membatalkan input pengguna lain.")
        return True
    try:
        ids, label = await resolve_actor_ids(
            db, scope=p.scope, nama=p.nama, self_id=user.id
        )
        msg = await undo_last(db, actor=user, actor_ids=ids, scope_label=label)
        await message.answer(msg)
    except UndoError as e:
        await message.answer(str(e.args[0]) if e.args else "Tidak bisa di-undo.")
    return True


async def _handle_user_admin(message: Message, db, user, text: str) -> bool:
    """Kelola pengguna (admin): daftar/list/aktif/nonaktif. True jika ditangani."""
    try:
        p = await parse_user_admin(text)
    except Exception:
        log.exception("parse_user_admin gagal")
        return False
    if p.intent == "bukan_user":
        return False
    try:
        if p.intent == "daftar_user":
            teks = await register_user(
                db, actor=user, nama=p.nama, role=p.role, gudang=p.gudang,
                telegram_id=p.telegram_id, no_hp=p.no_hp,
            )
        elif p.intent == "list_user":
            teks = await list_users(db)
        elif p.intent == "aktifkan_user":
            teks = await set_user_status(db, actor=user, ref=p.ref or p.nama, aktif=True)
        elif p.intent == "nonaktifkan_user":
            teks = await set_user_status(db, actor=user, ref=p.ref or p.nama, aktif=False)
        else:
            return False
    except UserAdminError as e:
        await message.answer(str(e.args[0]) if e.args else "Kesalahan kelola user.", parse_mode="Markdown")
        return True
    await message.answer(teks, parse_mode="Markdown")
    return True


async def _handle_transfer(message: Message, db, user, text: str, session) -> bool:
    """Buat transfer G1->G2 / laporan (staff/admin). True jika ditangani."""
    try:
        p = await parse_transfer(text)
    except Exception:
        log.exception("parse_transfer gagal")
        return False
    if p.intent == "bukan_transfer":
        return False

    try:
        if p.intent == "buat_transfer":
            if not can_transfer_pk(user):
                await message.answer(
                    "🔒 Pengiriman PK ke Gudang 2 hanya bisa dilakukan oleh "
                    "*staff* (atau admin)."
                    "\n_Laporan PK siap kirim/riwayat tetap bisa Anda lihat._",
                    parse_mode="Markdown",
                )
                return True
            kode = p.kode_proses or _extract_mil(text) or session.ctx_mil
            if not kode:
                await message.answer(
                    "Sebutkan proses milling sumbernya, contoh:\n"
                    "`transfer PK LOT-20260702-01 ke silo A`",
                    parse_mode="Markdown",
                )
                return True
            if p.lokasi_tujuan not in ("silo_a", "silo_b", "ditumpuk"):
                await message.answer(
                    "Ditransfer ke mana di Gudang 2 — *Silo A*, *Silo B*, atau "
                    "*tumpukan*?",
                    parse_mode="Markdown",
                )
                return True
            r = await create_internal_transfer(
                db, user=user, kode_proses=kode, lokasi_tujuan=p.lokasi_tujuan,
                berat=p.berat_kg,
            )
            session.ctx_mil = r.kode_proses
            sisa = await pending_transfer_kg(db, r.transfer.milling_process_id)
            if not can_see_financials(user):
                hpp = ""
            elif r.hpp_per_kg is not None:
                hpp = f"\n• HPP snapshot: {_rp(float(r.hpp_per_kg))}/kg"
            else:
                hpp = "\n• HPP: belum tersedia (output milling belum diverifikasi)"
            jn = f" {r.jenis}" if r.jenis else ""
            await message.answer(
                f"✓ Transfer *{r.transfer.kode_transfer}*: "
                f"{_kg(float(r.transfer.berat_kg))} PK{jn} dari {r.kode_proses} "
                f"*langsung masuk* {r.lokasi_label} Gudang 2 "
                "_(operator G2 tak perlu menerima manual)_.\n"
                f"• Sisa stok siap kirim {r.kode_proses}: {_kg(sisa)}{hpp}",
                parse_mode="Markdown",
            )
        elif p.intent == "laporan_siap_transfer":
            await message.answer(await laporan_pk_siap_transfer(db))
        elif p.intent == "laporan_transfer":
            await message.answer(await laporan_transfer(db))
        else:
            return False
    except TransferError as e:
        await message.answer(str(e.args[0]) if e.args else "Terjadi kesalahan transfer.")
    return True


async def _handle_milling_admin(message: Message, db, user, text: str, session) -> bool:
    """QC / verifikasi output milling (staff/admin). True jika ditangani."""
    try:
        p = await parse_milling_admin(text)
    except Exception:
        log.exception("parse_milling_admin gagal")
        return False
    if p.intent == "bukan_milling_admin":
        return False

    kode = p.kode_proses or _extract_mil(text) or session.ctx_mil
    try:
        if p.intent == "qc_milling":
            r = await log_qc_milling(
                db, user=user, kode_proses=kode, kadar_air=p.kadar_air,
                broken=p.broken_persen, susut=p.susut_persen, kondisi=p.kondisi,
            )
            session.ctx_mil = r.proc.kode_proses
            await message.answer(
                f"✓ QC {r.proc.kode_proses} tercatat (QC ke-{r.qc_count}).\n"
                f"• Kadar air: {_pct(r.kadar_air)} | Broken: {_pct(r.broken)} | "
                f"Susut: {_pct(r.susut)} | Jenis PK: {r.kondisi or '-'} (otomatis)"
            )
        elif p.intent == "verifikasi_output":
            r = await verify_milling_output(
                db, user=user, kode_proses=kode, berat_output=p.berat_output_kg
            )
            session.ctx_mil = r.proc.kode_proses
            rend = f"\n• Rendemen: {r.rendemen_persen:.1f}%" if r.rendemen_persen else ""
            tag = "diperbarui" if r.re_verified else "tersimpan"
            total = f"{r.berat_output:,.0f}".replace(",", ".")
            await message.answer(
                f"✓ Verifikasi output {tag}. *{r.proc.kode_proses}*\n"
                f"• Output PK final: {total} kg{rend}",
                parse_mode="Markdown",
            )
        else:
            return False
    except MillingError as e:
        await message.answer(str(e.args[0]) if e.args else "Terjadi kesalahan milling.")
    return True


_PK_REQ_LABEL = {
    "nama_supplier": "supplier", "berat_kg": "berat",
    "no_polisi": "plat truk", "jenis_pk": "jenis PK (KS/KL/Campuran/Semi KS)",
}


_JENIS_PK_LABEL_ADMIN = {"ks": "KS", "kl": "KL", "campuran": "Campuran", "semi_ks": "Semi KS"}


async def _handle_gudang2_admin(message: Message, db, user, text: str, session) -> bool:
    """Beli PK luar + QC/verifikasi PK luar (staff/admin). True jika ditangani."""
    try:
        p = await parse_gudang2(text)
    except Exception:
        log.exception("parse_gudang2 gagal")
        return False
    if p.intent not in ("beli_pk_luar", "verifikasi_pk_luar", "laporan_stok_g2"):
        return False
    try:
        if p.intent == "laporan_stok_g2":
            # Pertanyaan stok = jawaban DETERMINISTIK (bukan agent/LLM).
            await message.answer(
                await laporan_stok_gudang2(
                    db, p.nama_silo, financial=can_see_financials(user)
                )
            )
        elif p.intent == "beli_pk_luar":
            # DITUTUP 3 September 2026 (keputusan Direksi). PK masuk tidak
            # boleh dicatat manual — ia tetap lewat proses timbang, sama
            # seperti gabah. Mencatatnya lewat percakapan berarti bobotnya
            # diketik orang, bukan ditimbang.
            #
            # Balasannya menunjuk jalan, bukan sekadar menolak: yang mengetik
            # kalimat ini sedang berdiri di depan truk.
            await message.answer(
                "PK luar tidak lagi dicatat lewat chat.\n\n"
                "Timbang truknya di aplikasi Timbangan seperti biasa, lalu buka "
                "*Pos Produksi → Catat pekerjaan → Catat PK luar datang* dan "
                "pilih tiketnya. Supplier, bobot, dan plat ikut sendiri dari "
                "tiket itu.",
                parse_mode="Markdown",
            )
        elif p.intent == "verifikasi_pk_luar":
            # PK masuk = pasti diterima. Intent ini mencatat KUALITAS &/atau HARGA
            # (dua hal terpisah); penolakan sudah tak berlaku.
            if (p.keputusan or "").lower() == "tolak":
                await message.answer(
                    "ℹ️ PK yang masuk selalu diterima — penolakan tak berlaku lagi. "
                    "Catat *kualitas* dan/atau *harga*-nya saja.",
                    parse_mode="Markdown",
                )
            else:
                did: list[str] = []
                harga_res = None
                if any(v is not None for v in (
                    p.kadar_air, p.broken_persen, p.penyusutan_persen,
                    p.butir_kuning, p.catatan_lab,
                )):
                    await log_pk_qc(
                        db, user=user, kode=p.kode, kadar_air=p.kadar_air,
                        broken=p.broken_persen, penyusutan_persen=p.penyusutan_persen,
                        butir_kuning=p.butir_kuning, catatan_lab=p.catatan_lab,
                    )
                    did.append("kualitas")
                if p.harga_per_kg is not None or p.total_harga is not None:
                    metode = "total" if p.total_harga is not None else "per_kg"
                    nilai = p.total_harga if p.total_harga is not None else p.harga_per_kg
                    harga_res = await verify_pk_price(
                        db, user=user, kode=p.kode, metode=metode, nilai=nilai,
                        potongan_kg=p.potongan_kg,
                    )
                    did.append("harga")
                if not did:
                    await message.answer(
                        "Sebutkan kualitas (kadar air/broken/…) dan/atau harga PK-nya."
                    )
                else:
                    msg = f"✓ PK luar {p.kode}: {' & '.join(did)} tercatat."
                    if harga_res is not None:
                        msg += (f"\nBersih {_kg(harga_res.berat_bersih_kg)} · "
                                f"HPP {_rp(harga_res.hpp_per_kg)}/kg.")
                    await message.answer(msg, parse_mode="Markdown")
    except (Gudang2Error, BackdateError) as e:
        await message.answer(str(e.args[0]) if e.args else "Terjadi kesalahan.")
    return True


# Jenis karung beras yang WAJIB bermerk (kalau tak disebut, bot tanya).
_KARUNG_MERK_WAJIB = {"biasa", "laminasi", "putih", "bekas"}


async def _reply_beli_kemasan(message: Message, r) -> None:
    jml = f"{r.purchase.jumlah_lembar:,}".replace(",", ".")
    stok = f"{r.stok_baru:,}".replace(",", ".")
    merk = f"{r.brand_nama} " if r.brand_nama else ""
    await message.answer(
        f"✓ Beli karung *{merk}{r.material_nama} {r.ukuran}kg* × {jml} lembar "
        f"({r.purchase.kode}).\n• Stok kini: {stok} lembar",
        parse_mode="Markdown",
    )


def _kemasan_missing(p) -> list[str]:
    missing = []
    if not p.material:
        missing.append("jenis karung (biasa/laminasi/putih/bekas)")
    if not p.ukuran_kg:
        missing.append("ukuran (kg)")
    if not p.jumlah_lembar:
        missing.append("jumlah lembar")
    if p.material and p.material in _KARUNG_MERK_WAJIB and not p.brand:
        missing.append("merk (atau polos)")
    return missing


async def _finish_or_ask_kemasan(message: Message, db, user, session, p, accumulated: str) -> None:
    """Simpan beli karung bila lengkap; kalau belum, minta field yang kurang."""
    missing = _kemasan_missing(p)
    if missing:
        session.kemasan_text = accumulated
        session.stage = "awaiting_kemasan"
        await message.answer(
            "📝 Data karung belum lengkap. Sebutkan: *" + ", ".join(missing) + "*.\n"
            "_Contoh: `beli karung LosPulen laminasi 25kg 1000 lembar`._",
            parse_mode="Markdown",
        )
        return
    session.stage = "idle"
    session.kemasan_text = None
    r = await beli_kemasan(
        db, user=user, material_kode=p.material, ukuran=p.ukuran_kg,
        jumlah=p.jumlah_lembar, brand_nama=p.brand,
        harga_per_lembar=p.harga_per_lembar, tanggal=p.tanggal, jam=p.jam,
    )
    await _reply_beli_kemasan(message, r)


async def _handle_kemasan(message: Message, db, user, text: str, session) -> bool:
    """Beli karung + tanya stok kemasan (staff/admin). True jika ditangani."""
    try:
        p = await parse_kemasan(text)
    except Exception:
        log.exception("parse_kemasan gagal")
        return False
    if p.intent == "bukan_kemasan":
        return False
    try:
        if p.intent == "beli_kemasan":
            await _finish_or_ask_kemasan(message, db, user, session, p, text)
        elif p.intent == "laporan_kemasan":
            await message.answer(await laporan_stok_kemasan(db))
    except InventoryError as e:
        await message.answer(str(e.args[0]) if e.args else "Terjadi kesalahan kemasan.")
    return True


async def _handle_barang_jadi_admin(message: Message, db, user, text: str) -> bool:
    """Harga byproduct + HPP beras + stok barang jadi (staff/admin)."""
    try:
        p = await parse_barang_jadi(text)
    except Exception:
        log.exception("parse_barang_jadi gagal")
        return False
    if p.intent not in ("harga_byproduct", "laporan_hpp", "laporan_barang_jadi"):
        return False
    try:
        if p.intent == "harga_byproduct":
            j = await set_harga_byproduct(db, user=user, jenis=p.jenis_byproduct, harga=p.harga)
            await message.answer(f"✓ Harga acuan *{j}* = {_rp(p.harga)}/kg tersimpan.", parse_mode="Markdown")
        elif p.intent == "laporan_hpp":
            if not can_see_financials(user):
                await message.answer("🔒 HPP khusus staff/admin.")
                return True
            await message.answer(await laporan_hpp_beras(db, p.kode), parse_mode="Markdown")
        elif p.intent == "laporan_barang_jadi":
            await message.answer(await laporan_stok_barang_jadi(db))
    except InventoryError as e:
        await message.answer(str(e.args[0]) if e.args else "Terjadi kesalahan.")
    return True


async def _handle_keluar(message: Message, db, user, text: str) -> bool:
    """Barang keluar / dikirim + jual PK langsung (staff/admin). True jika ditangani."""
    try:
        p = await parse_keluar(text)
    except Exception:
        log.exception("parse_keluar gagal")
        return False
    if p.intent == "bukan_keluar":
        return False
    try:
        if p.intent == "kirim_barang_jadi":
            r = await kirim_finished_goods(
                db, user=user, kategori=p.kategori, grade=p.grade, brand_nama=p.brand,
                material_kode=p.material, ukuran=p.ukuran_kg, jumlah_karung=p.jumlah_karung,
                nama_pembeli=p.nama_pembeli, metode=p.metode, no_polisi=p.no_polisi,
                nama_ekspedisi=p.nama_ekspedisi, harga_per_kg=p.harga_per_kg,
                tanggal=p.tanggal, jam=p.jam,
            )
        elif p.intent == "kirim_bekatul":
            r = await kirim_bekatul(
                db, user=user, berat_kg=p.berat_kg, nama_pembeli=p.nama_pembeli,
                metode=p.metode, no_polisi=p.no_polisi, nama_ekspedisi=p.nama_ekspedisi,
                harga_per_kg=p.harga_per_kg, tanggal=p.tanggal, jam=p.jam,
            )
        elif p.intent == "jual_pk_langsung":
            r = await jual_pk_langsung(
                db, user=user, kode_mil=p.kode, berat_kg=p.berat_kg,
                nama_pembeli=p.nama_pembeli, metode=p.metode, no_polisi=p.no_polisi,
                nama_ekspedisi=p.nama_ekspedisi, harga_per_kg=p.harga_per_kg,
                tanggal=p.tanggal, jam=p.jam,
            )
        elif p.intent == "laporan_keluar":
            await message.answer(await laporan_barang_keluar(db))
            return True
        else:
            return False
        karung = f" ({r.jumlah_karung} karung)" if r.jumlah_karung else ""
        warn = f"\n{r.warning}" if r.warning else ""
        pembeli = f" → {p.nama_pembeli}" if p.nama_pembeli else ""
        await message.answer(
            f"✓ Barang keluar *{r.kode}*: {r.label} {_kg(r.berat_kg)}{karung}{pembeli}.{warn}",
            parse_mode="Markdown",
        )
    except InventoryError as e:
        await message.answer(str(e.args[0]) if e.args else "Terjadi kesalahan barang keluar.")
    return True


async def _try_command_handlers(message, db, user, text: str, session) -> bool:
    """Rangkaian handler PERINTAH deterministik (tulis). True bila salah satu
    menangani. Dipakai jalur normal maupun saat menjalankan usulan agent."""
    if await _handle_analitik(message, db, user, text):
        return True
    if await _handle_undo_admin(message, db, user, text):
        return True
    if await _handle_user_admin(message, db, user, text):
        return True
    if await _handle_transfer(message, db, user, text, session):
        return True
    if await _handle_milling_admin(message, db, user, text, session):
        return True
    if await _handle_gudang2_admin(message, db, user, text, session):
        return True
    if await _handle_kemasan(message, db, user, text, session):
        return True
    if await _handle_barang_jadi_admin(message, db, user, text):
        return True
    if await _handle_keluar(message, db, user, text):
        return True
    return False


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
                "⛔ Bot Admin khusus *Staff/Admin* (verifikasi harga, QC, output PK).\n"
                "Sebagai *Operator*, gunakan `@selepan_bot` untuk input fisik Gudang 1 "
                "(pembelian, pengeringan, silo, milling).",
                parse_mode="Markdown",
            )
            return

        session = get_session(message.bot.id, tg_id)

        # ── Dashboard produksi (kata kunci) ──
        if lower in ("dashboard", "dasbor", "dashboard produksi", "ringkasan produksi"):
            await _send_dashboard(message, db, user)
            return

        # ── Menunggu konfirmasi verifikasi ──
        if session.stage == "awaiting_verif_confirmation" and session.verif_draft:
            if lower in CONFIRM_WORDS:
                await _save_verification(message, db, user, session)
                return
            if lower in CANCEL_WORDS:
                reset_verif(message.bot.id, tg_id)
                await message.answer("Baik, verifikasi dibatalkan.")
                return
            # anggap koreksi/pelengkap
            try:
                new = await parse_verification(text)
            except Exception:
                log.exception("parse_verification gagal")
                await message.answer(AI_ERROR_MSG)
                return
            session.verif_draft = _merge_verif(session.verif_draft, new)
            await _advance_verif(message, db, tg_id, session)
            return

        # ── Sedang melengkapi data verifikasi ──
        if session.stage == "collecting_verif" and session.verif_draft:
            try:
                new = await parse_verification(text)
            except Exception:
                log.exception("parse_verification gagal")
                await message.answer(AI_ERROR_MSG)
                return
            session.verif_draft = _merge_verif(session.verif_draft, new)
            await _advance_verif(message, db, tg_id, session)
            return

        # ── Melengkapi data beli KARUNG (kumpulkan field kurang) ──
        if session.stage == "awaiting_kemasan" and session.kemasan_text:
            if lower in CANCEL_WORDS:
                session.stage = "idle"
                session.kemasan_text = None
                await message.answer("Baik, pembelian karung dibatalkan.")
                return
            accumulated = (session.kemasan_text + " " + text).strip()
            try:
                p = await parse_kemasan(accumulated)
                await _finish_or_ask_kemasan(message, db, user, session, p, accumulated)
            except (InventoryError, BackdateError) as e:
                session.stage = "idle"
                session.kemasan_text = None
                await message.answer(str(e.args[0]) if e.args else "Gagal simpan karung.")
            except Exception:
                log.exception("parse_kemasan lanjutan gagal")
                await message.answer(AI_ERROR_MSG)
            return

        # ── Konfirmasi usulan tulis dari agent (pola agentic) ──
        async def _dispatch(cmd: str) -> bool:
            return await _try_command_handlers(message, db, user, cmd, session)

        if session.stage == "awaiting_agent_write":
            if await agent_confirm_pending(message, lower, session, dispatch=_dispatch):
                return
            # bukan ya/batal → lanjut proses sebagai pesan baru di bawah.

        # ── Router niat: pre-router deterministik (0 LLM) dulu, baru router LLM
        #    bila ragu → handler domainnya saja. Fallback aman ke chain penuh. ──
        domain = fast_domain(text, valid=_ADMIN_DOMAINS) or await route_domain(text)
        # Analitik (simulasi HPP / rincian biaya / tren) sering memakai kata 'hpp'
        # sehingga router mengira 'barang_jadi' (laporan HPP batch → minta kode).
        # Beri analitik kesempatan LEBIH DULU untuk domain HPP-ambigu; parser balik
        # 'bukan_analitik' → False bila memang bukan, jadi aman.
        if domain in ("barang_jadi", "lainnya") and await _handle_analitik(
            message, db, user, text
        ):
            return
        _CMD = {
            "transfer_pk": lambda: _handle_transfer(message, db, user, text, session),
            "milling": lambda: _handle_milling_admin(message, db, user, text, session),
            "gudang2": lambda: _handle_gudang2_admin(message, db, user, text, session),
            "kemasan": lambda: _handle_kemasan(message, db, user, text, session),
            "barang_jadi": lambda: _handle_barang_jadi_admin(message, db, user, text),
            "barang_keluar": lambda: _handle_keluar(message, db, user, text),
            "kelola_user": lambda: _handle_user_admin(message, db, user, text),
            "undo": lambda: _handle_undo_admin(message, db, user, text),
        }
        handler = _CMD.get(domain)
        if handler is not None:
            if await handler():
                return
            # Router pilih domain perintah tapi handler menolak (klasifikasi
            # meleset) → coba chain penuh sekali sebagai jaring pengaman.
            if await _try_command_handlers(message, db, user, text, session):
                return
        # domain 'lainnya'/'verifikasi_harga_gabah'/domain operator → lanjut ke
        # blok verifikasi harga + jalur baca + agent di bawah.

        # ── Verifikasi/penetapan harga gabah — cek SEBELUM detail, karena
        #    "gabah pertama harganya 7500/kg" itu PERINTAH, bukan pertanyaan ──
        try:
            parsed = await parse_verification(text)
        except Exception:
            log.exception("parse_verification gagal")
            await message.answer(AI_ERROR_MSG)
            return
        # Jaring pengaman: lengkapi kode bila terlewat. Paksa jadi verifikasi
        # HANYA bila ada NILAI harga (perintah) — jangan untuk pertanyaan
        # seperti "berapa harga GB-..." (itu biar ditangani modul detail).
        kode_regex = _extract_kode(text)
        if kode_regex:
            parsed.kode_batch = parsed.kode_batch or kode_regex
            if parsed.nilai_rupiah is not None:
                parsed.is_verifikasi_harga = True

        if parsed.is_verifikasi_harga and not can_see_financials(user):
            await message.answer("🔒 Verifikasi & penetapan harga khusus staff/admin.")
            return

        if parsed.is_verifikasi_harga:
            # Resolusi rujukan batch: kode > deskriptif (urutan/supplier/
            # terbaru) > konteks percakapan.
            if not parsed.kode_batch:
                if parsed.urutan or parsed.supplier_nama or parsed.terbaru:
                    kodes = await resolve_batch_kode_ref(
                        db, urutan=parsed.urutan, supplier=parsed.supplier_nama,
                        terbaru=parsed.terbaru,
                    )
                    if len(kodes) == 1:
                        parsed.kode_batch = kodes[0]
                    elif len(kodes) > 1:
                        await message.answer(
                            "Batch mana yang dimaksud? " + ", ".join(kodes[:10])
                            + "\nSebutkan kodenya, mis. `" + kodes[0] + " 7500 per kg`.",
                            parse_mode="Markdown",
                        )
                        return
                    # 0 -> biarkan _advance_verif menanyakan kode.
                else:
                    parsed.kode_batch = session.ctx_batch
            session.verif_draft = parsed
            await _advance_verif(message, db, tg_id, session)
            return

        # ── Status/isi silo ("status silo A", "silo A gabah dari siapa") ──
        if await maybe_answer_silo_report(message, text):
            return

        # ── Status proses berjalan ("proses apa yang sedang berlangsung") ──
        if await maybe_answer_status(message, text):
            return

        # ── Pertanyaan tugas tertunda ("ada yang perlu diverifikasi?") ──
        if await maybe_answer_pending(message, text):
            return

        # ── Pola jam kedatangan gabah ("jam berapa biasanya gabah masuk") ──
        if await maybe_answer_jam(message, text):
            return

        # ── Detail/atribut entitas ("berapa harga gabah pertama") ──
        if await maybe_answer_detail(
            message, text, session, financial=can_see_financials(user)
        ):
            return

        # ── Mencari kode batch/lot ("batch dari budi kodenya apa")? ──
        if await maybe_answer_lookup(message, text, session):
            return

        # ── Pertanyaan laporan ("berapa gabah masuk hari ini")? ──
        if await maybe_answer_report(message, text, session):
            return

        # ── Jaring terakhir: agent (pertanyaan bebas / analitik / usulan tulis) ──
        await maybe_answer_agent(
            message, role=user.role, financial=can_see_financials(user),
            allow_write=True, session=session,
        )


async def _advance_verif(message: Message, db, tg_id: int, session) -> None:
    """Cek kelengkapan draft verifikasi, tanya yang kurang, atau tampilkan ringkasan."""
    d = session.verif_draft

    if not d.kode_batch:
        session.stage = "collecting_verif"
        await message.answer("Sebutkan kode batch, contoh: `GB-20260702-01`", parse_mode="Markdown")
        return

    batch = await get_batch_by_kode(db, d.kode_batch)
    if batch is None:
        session.stage = "collecting_verif"
        await message.answer(f"Batch *{d.kode_batch}* tidak ditemukan. Cek lagi kodenya.", parse_mode="Markdown")
        return

    if d.nilai_rupiah is None:
        session.stage = "collecting_verif"
        await message.answer("Berapa harganya? (mis. `total 42 juta` atau `5.250 per kg`)", parse_mode="Markdown")
        return

    if d.metode_harga not in {"total", "per_kg"}:
        session.stage = "collecting_verif"
        await message.answer("Nilai itu *total biaya* atau *harga per kg*?", parse_mode="Markdown")
        return

    # Lengkap → ringkasan + konfirmasi.
    berat = float(batch.berat_total_kg or 0)
    total, per_kg = compute_price(berat, d.metode_harga, d.nilai_rupiah)
    session.stage = "awaiting_verif_confirmation"
    warn = ""
    if not batch.flag_unverified:
        warn = "\n_⚠️ Batch ini sudah pernah diverifikasi — akan ditimpa._"
    await message.answer(
        f"Verifikasi *{batch.kode_batch}*:\n"
        f"• Berat: {berat:,.0f} kg\n".replace(",", ".")
        + f"• Total biaya: {_rp(total)}\n"
        f"• Harga per kg: {_rp(per_kg)}\n"
        f"Konfirmasi? (ketik *ya* / *batal*){warn}",
        parse_mode="Markdown",
    )


async def _save_verification(message: Message, db, user, session) -> None:
    d = session.verif_draft
    batch = await get_batch_by_kode(db, d.kode_batch)
    if batch is None:
        reset_verif(message.bot.id, message.from_user.id)
        await message.answer("Batch tidak ditemukan lagi. Ulangi dari awal.")
        return
    result = await verify_gabah_price(
        db, user=user, batch=batch, metode=d.metode_harga, nilai_rupiah=d.nilai_rupiah
    )
    session.ctx_batch = batch.kode_batch
    reset_verif(message.bot.id, message.from_user.id)
    tag = "diperbarui" if result.re_verified else "tersimpan"
    await message.answer(
        f"✓ Verifikasi {tag}. *{batch.kode_batch}* ({result.supplier_nama})\n"
        f"• Total: {_rp(result.total_biaya)} | Per kg: {_rp(result.harga_per_kg)}\n"
        "Flag menunggu-verifikasi dihapus.",
        parse_mode="Markdown",
    )
