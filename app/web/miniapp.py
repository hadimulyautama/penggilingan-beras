"""Router Mini App Telegram: identitas + dashboard + AKSI CEPAT role-aware.

Tiap endpoint memakai `require_miniapp_user` → tahu SIAPA & role-nya (server-side).
Data & aksi memakai Service yang sama dengan bot (satu sumber kebenaran). Menu
aksi ditentukan SERVER per role: operator G1 (gabah masuk / kadar air / hasil
giling), staff-admin (verifikasi harga / pemindahan PK). Operator tak dapat aksi
keuangan.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.bots.common import can_see_financials, can_transfer_pk
from app.database import SessionLocal
from app.models import User
from app.web.aksi_umum import galat as _err
from app.web.aksi_umum import kabar_chat as _chat_confirm
from app.web.aksi_umum import rp as _rp
from app.web.aksi_umum import wajib as _require
from app.web.deps import pengguna_aksi

router = APIRouter(prefix="/miniapp", tags=["miniapp"])




# ─────────────────────────── Identitas ───────────────────────────

@router.get("/me")
async def me(user: User = Depends(pengguna_aksi)) -> dict:
    """Profil + izin user (menentukan tampilan front-end)."""
    return {
        "id": user.id, "nama": user.nama, "role": user.role,
        "default_warehouse_id": user.default_warehouse_id,
        "permissions": {
            "see_financials": can_see_financials(user),
            "transfer_pk": can_transfer_pk(user),
        },
    }


# ─────────────────────────── Dashboard ───────────────────────────

def _clean(s: str) -> str:
    return (s or "").replace("*", "").replace("_", "")


async def _hpp_terkini(db) -> str:
    from sqlalchemy import select
    from app.models import PolishingProcess
    from app.penggilingan.inventory.finished_goods import laporan_hpp_beras
    from app.penggilingan.inventory.packaging import InventoryError
    kode = (
        await db.execute(
            select(PolishingProcess.kode_proses).order_by(PolishingProcess.id.desc()).limit(1)
        )
    ).scalars().first()
    if not kode:
        return "Belum ada penyosohan."
    try:
        return _clean(await laporan_hpp_beras(db, kode))
    except InventoryError:
        return "Belum tersedia (menunggu data lengkap)."


@router.get("/dashboard")
async def dashboard(user: User = Depends(pengguna_aksi)) -> dict:
    """Snapshot dashboard sesuai role. Keuangan (HPP/tugas) hanya staff/admin."""
    fin = can_see_financials(user)
    from app.bots.common import user_wh_scope
    from app.services.report import status_gudang1, pending_verifikasi
    from app.services.transfer import laporan_pk_siap_transfer
    from app.penggilingan.gudang2.service import laporan_stok_gudang2
    from app.penggilingan.inventory.finished_goods import laporan_stok_barang_jadi, hitung_stok_bekatul
    from app.penggilingan.inventory.packaging import laporan_stok_kemasan
    from app.services.pemantau import pemantau_nyangkut

    sections: list[dict] = []
    async with SessionLocal() as db:
        # Operator hanya lihat gudangnya; staff/admin lihat semua.
        scope = await user_wh_scope(db, user)
        see_g1 = scope in ("all", "g1")
        see_g2 = scope in ("all", "g2")
        sections.append({"icon": "⚠️", "title": "Perlu tindakan (nyangkut)", "body": _clean(
            await pemantau_nyangkut(db, financial=fin, scope=scope))})
        if see_g1:
            sections.append({"icon": "🌾", "title": "Gudang 1 — Selepan", "body": _clean(
                await status_gudang1(db) + "\n\n" + await laporan_pk_siap_transfer(db))})
        if see_g2:
            sections.append({"icon": "🏭", "title": "Gudang 2 — Penyosohan", "body": _clean(
                await laporan_stok_gudang2(db, financial=fin))})
            bekatul = float(await hitung_stok_bekatul(db))
            sections.append({"icon": "📦", "title": "Barang jadi & bekatul", "body": _clean(
                await laporan_stok_barang_jadi(db) + f"\n\n🌾 Bekatul curah: {_rp(bekatul)} kg")})
            sections.append({"icon": "🧺", "title": "Kemasan", "body": _clean(
                await laporan_stok_kemasan(db))})
        if fin:
            sections.append({"icon": "✅", "title": "Tugas verifikasi & QC", "body": _clean(
                await pending_verifikasi(db))})
            sections.append({"icon": "💰", "title": "HPP beras terkini",
                             "body": await _hpp_terkini(db)})
    return {"user": {"nama": user.nama, "role": user.role, "see_financials": fin},
            "sections": sections}


# ─────────────────────── Aksi cepat: role helper ───────────────────────

async def _is_wh_operator(user: User, like: str) -> bool:
    """Admin selalu boleh; operator hanya bila gudang default cocok `like`."""
    if user.role == "admin":
        return True
    if user.role != "operator":
        return False
    from sqlalchemy import select
    from app.models import Warehouse
    async with SessionLocal() as db:
        wid = (
            await db.execute(
                select(Warehouse.id).where(Warehouse.nama_gudang.like(like))
            )
        ).scalars().first()
    return wid is not None and user.default_warehouse_id == wid


async def _is_g1_operator(user: User) -> bool:
    """Admin selalu boleh; operator hanya bila gudang default = Gudang 1."""
    return await _is_wh_operator(user, "Gudang 1%")


async def _is_g2_operator(user: User) -> bool:
    """Admin selalu boleh; operator hanya bila gudang default = Gudang 2."""
    return await _is_wh_operator(user, "Gudang 2%")


async def _pilihan_tujuan_gabah(kondisi: str) -> list[list[str]]:
    """Daftar tujuan yang sah untuk gabah, mesinnya disebut satu per satu.

    Mesin tidak digabung jadi satu pilihan "Dryer" lalu ditanya lagi mesin
    mana: itu dua ketukan untuk satu keputusan, dan yang menekannya sedang
    berdiri memegang layar dengan satu tangan.
    """
    from app.penggilingan.gudang1.services.drying import dryers_g1
    from app.penggilingan.peta_jenis import intake_dari_jenis

    jenis = "GABAH_BASAH" if kondisi == "basah" else "GABAH_KERING"
    sah = intake_dari_jenis(jenis).tujuan_pilihan
    opsi: list[list[str]] = [["", "— belum ditentukan —"]]
    if "dryer" in sah:
        async with SessionLocal() as db:
            mesin = await dryers_g1(db)
        for d in mesin:
            mati = "" if d.status == "aktif" else f" ({d.status})"
            opsi.append([f"dryer:{d.id}", f"{d.nama}{mati}"])
    if "silo" in sah:
        from app.penggilingan.gudang1.services.silo import silos_g1
        async with SessionLocal() as db:
            for si in await silos_g1(db):
                opsi.append([f"silo:{si.id}", f"{si.nama_silo} (gabah kering)"])
    if "tumpuk" in sah:
        opsi.append(["tumpuk", f"Tumpukan {kondisi}"])
    return opsi


def _urai_tujuan(nilai: str | None) -> tuple[str, int | None]:
    """Pisahkan jenis tujuan dari mesin yang disebut: 'dryer:3' → ('dryer', 3).

    Jenisnya yang diadu dengan aturan komoditas (`peta_jenis`); nomor mesin
    hanya menentukan mesin mana, dan itu bukan urusan aturan.
    """
    nilai = (nilai or "").strip()
    for awalan in ("dryer:", "silo:"):
        if nilai.startswith(awalan):
            ekor = nilai.split(":", 1)[1]
            return awalan[:-1], int(ekor) if ekor.isdigit() else None
    return nilai, None


@router.get("/actions/menu")
async def actions_menu(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Daftar aksi cepat + spesifikasi field, ditentukan SERVER per role."""
    fin = can_see_financials(user)
    g1 = await _is_g1_operator(user)
    g2 = await _is_g2_operator(user)
    KONDISI = [["", "— belum ditentukan —"], ["basah", "Basah (→ PK KS)"],
               ["kering", "Kering (→ PK KL)"]]
    TUJUAN = [["", "— belum ditentukan —"], ["silo_a", "Silo A"],
              ["silo_b", "Silo B"], ["ditumpuk", "Tumpukan"]]
    METODE = [["", "— belum ditentukan —"], ["total", "Total (Rp)"], ["per_kg", "Per kg (Rp)"]]
    SILO_BAHAN = [["", "— belum ditentukan —"], ["A", "Silo A"], ["B", "Silo B"],
                  ["AB", "Silo A + B"]]
    JENIS_HASIL = [["", "— belum ditentukan —"],
                   ["premium", "Beras Premium"], ["medsuper", "Beras Medium Super"],
                   ["medium", "Beras Medium"], ["sayur", "Beras Sayur"],
                   ["beras_b", "Beras B (olah ulang)"], ["menir", "Menir"],
                   ["broken", "Broken"], ["bekatul", "Bekatul"], ["reject", "Reject"]]
    TUJUAN_PK = [["", "— belum ditentukan —"], ["silo_a", "Silo A"],
                 ["silo_b", "Silo B"], ["ditumpuk", "Tumpukan"]]
    actions: list[dict] = []
    if g1:
        # Dibangkitkan per permintaan: mesin bisa bertambah lewat Pengaturan,
        # dan daftar tujuan yang ditulis tetap akan diam-diam ketinggalan.
        TUJUAN_BASAH = await _pilihan_tujuan_gabah("basah")
        TUJUAN_KERING = await _pilihan_tujuan_gabah("kering")
        # Urut sesuai alur kerja operator Gudang 1: terima → keringkan →
        # dinginkan/pindah silo → giling.
        actions += [
            {"id": "gabah_masuk", "label": "🌾 Gabah masuk",
             "post": "/miniapp/actions/gabah-masuk",
             "hint": "Pilih tiket timbang yang masih aktif — supplier, bobot, & plat "
                     "otomatis dari timbangan (tak perlu diketik ulang). "
                     "Partai kecil ikut di sini: satu kode timbang, berapa pun "
                     "kali ditimbang.",
             "fields": [
                 {"name": "timbangan_transaksi_id", "label": "Tiket timbang (gabah masuk)",
                  "type": "remote", "source": "/miniapp/actions/timbang-masuk-aktif",
                  "kosong": "Tidak ada tiket timbang gabah yang aktif 7 hari terakhir. Gabah dicatat dari tiket timbang — bukan diketik manual."},
                 {"name": "tujuan", "label": "Tujuan (wajib pilih)", "type": "select",
                  # Gabungan basah & kering: jenis gabahnya baru diketahui dari
                  # tiket yang dipilih, jadi keduanya ditawarkan dan server
                  # menolak yang tak sah untuk jenis itu — dengan menyebut
                  # yang boleh, bukan sekadar bahwa ia ditolak.
                  "options": TUJUAN_BASAH + [o for o in TUJUAN_KERING
                                             if o not in TUJUAN_BASAH]},
             ]},
            {"id": "pindah_tumpukan", "label": "📦 Tempatkan gabah",
             "post": "/miniapp/actions/pindah-tumpukan",
             "hint": "Gabah yang belum ada di dryer maupun silo — yang sedang "
                     "menumpuk, dan yang penempatannya gagal. Gabah basah "
                     "belum boleh ke silo.",
             "fields": [
                 {"name": "kode_batch", "label": "Gabah yang menunggu tempat",
                  "type": "remote", "source": "/miniapp/actions/tumpukan",
                  "kosong": "Tidak ada gabah yang menunggu tempat. Semua gabah masuk sudah berada di dryer atau silo."},
                 {"name": "tujuan", "label": "Tujuan (wajib pilih)", "type": "select",
                  "options": TUJUAN_BASAH + [o for o in TUJUAN_KERING
                                             if o not in TUJUAN_BASAH]},
             ]},
            {"id": "mulai_pengeringan", "label": "🔥 Mulai pengeringan",
             "post": "/miniapp/actions/mulai-pengeringan",
             "hint": "Bentuk 1 lot dari SEMUA gabah yang menunggu di mesin itu. "
                     "Gabah di mesin lain tidak ikut.",
             "fields": [
                 {"name": "dryer_id", "label": "Mesin pengering", "type": "remote",
                  "source": "/miniapp/actions/dryer-menunggu",
                  "kosong": "Belum ada gabah yang menunggu di mesin pengering mana pun. Mesinnya ada — yang belum ada gabahnya. Catat gabah masuk lebih dulu."},
             ]},
            {"id": "kadar_air", "label": "💧 Update kadar air",
             "post": "/miniapp/actions/kadar-air", "fields": [
                 {"name": "kode_lot", "label": "Lot pengeringan", "type": "remote",
                  "source": "/miniapp/actions/drying-active",
                  "kosong": "Tidak ada lot yang sedang dikeringkan."},
                 {"name": "kadar_air", "label": "Kadar air (%)", "type": "number"},
             ]},
            {"id": "selesai_pengeringan", "label": "🌡️ Selesai pengeringan",
             "post": "/miniapp/actions/selesai-pengeringan",
             "hint": "Lot masuk fase pendinginan otomatis (gabah tetap di dryer).",
             "fields": [
                 {"name": "kode_lot", "label": "Lot pengeringan", "type": "remote",
                  "source": "/miniapp/actions/drying-active",
                  "kosong": "Tidak ada lot yang sedang dikeringkan."},
             ]},
            {"id": "selesai_pendinginan", "label": "❄️ Pendinginan selesai",
             "post": "/miniapp/actions/selesai-pendinginan",
             "hint": "Nyatakan gabah sudah dingin & dryer idle — gabah boleh tetap "
                     "di dryer menunggu silo kosong. (Basis analisa downtime dryer.)",
             "fields": [
                 {"name": "kode_lot", "label": "Lot didinginkan", "type": "remote",
                  "source": "/miniapp/actions/cooling-active",
                  "kosong": "Tidak ada lot yang sedang didinginkan."},
             ]},
            {"id": "pindah_silo", "label": "🏗️ Pindah dryer → silo",
             "post": "/miniapp/actions/pindah-silo",
             "hint": "Hanya lot yang sudah dinyatakan selesai pendinginan.", "fields": [
                 {"name": "kode_lot", "label": "Lot siap dipindah", "type": "remote",
                  "source": "/miniapp/actions/drying-done",
                  "kosong": "Tidak ada lot yang sudah selesai didinginkan. Selesaikan pendinginan dulu sebelum memindahkannya ke silo."},
                 {"name": "silo", "label": "Silo tujuan (wajib pilih)",
                  "type": "remote", "source": "/miniapp/actions/silo-g1",
                  "kosong": "Tidak ada silo gabah kering. Tambahkan silo di Pengaturan → Alat."},
             ]},
            {"id": "mulai_giling", "label": "⚙️ Mulai giling",
             "post": "/miniapp/actions/mulai-giling", "fields": [
                 {"name": "silo", "label": "Silo yang digiling", "type": "remote",
                  "source": "/miniapp/actions/silo-siap-giling",
                  "kosong": "Tidak ada silo berisi gabah kering yang siap digiling."},
             ]},
            {"id": "hasil_giling", "label": "📈 Update hasil giling",
             "post": "/miniapp/actions/hasil-giling", "fields": [
                 {"name": "kode_proses", "label": "Proses giling", "type": "remote",
                  "source": "/miniapp/actions/milling-active",
                  "kosong": "Tidak ada proses giling yang sedang berjalan."},
                 {"name": "berat_kumulatif", "label": "PK kumulatif (kg)", "type": "number"},
             ]},
            {"id": "selesai_giling", "label": "🏁 Selesai giling",
             "post": "/miniapp/actions/selesai-giling", "fields": [
                 {"name": "kode_proses", "label": "Proses giling", "type": "remote",
                  "source": "/miniapp/actions/milling-active",
                  "kosong": "Tidak ada proses giling yang sedang berjalan."},
             ]},
        ]
    if g2:
        actions += [
            {"id": "masukkan_pk", "label": "📥 Masukkan PK diterima",
             "post": "/miniapp/actions/masukkan-pk", "fields": [
                 {"name": "kode_batch", "label": "PK diterima", "type": "remote",
                  "source": "/miniapp/actions/pk-intake-pending",
                  "kosong": "Tidak ada PK masuk yang menunggu."},
                 {"name": "tujuan", "label": "Tujuan (wajib pilih)", "type": "select",
                  "options": TUJUAN_PK},
             ]},
            {"id": "mulai_penyosohan", "label": "🏭 Mulai penyosohan",
             "post": "/miniapp/actions/mulai-penyosohan", "fields": [
                 {"name": "silo", "label": "Silo bahan (wajib pilih)", "type": "select",
                  "options": SILO_BAHAN},
             ]},
            {"id": "hasil_penyosohan", "label": "⚙️ Catat hasil penyosohan",
             "post": "/miniapp/actions/hasil-penyosohan", "fields": [
                 {"name": "kode_proses", "label": "Proses penyosohan", "type": "remote",
                  "source": "/miniapp/actions/polishing-active",
                  "kosong": "Tidak ada penyosohan yang sedang berjalan."},
                 {"name": "jenis", "label": "Jenis hasil (wajib pilih)", "type": "select",
                  "options": JENIS_HASIL},
                 {"name": "berat_kumulatif", "label": "Berat kumulatif (kg)", "type": "number"},
             ]},
            {"id": "selesai_penyosohan", "label": "🏁 Selesai penyosohan (per silo)",
             "post": "/miniapp/actions/selesai-penyosohan", "fields": [
                 {"name": "kode_proses", "label": "Proses penyosohan", "type": "remote",
                  "source": "/miniapp/actions/polishing-active",
                  "kosong": "Tidak ada penyosohan yang sedang berjalan."},
                 {"name": "silo", "label": "Silo yang selesai (wajib pilih)", "type": "select",
                  "options": [["", "— belum ditentukan —"], ["A", "Silo A"], ["B", "Silo B"]]},
                 {"name": "sisa", "label": "Sisa di silo (kg)", "type": "number"},
             ]},
        ]
    BUTIR = [["", "— tidak dinilai —"], ["bersih", "Bersih"],
             ["sedang", "Sedang"], ["banyak", "Banyak"]]
    JENIS_PK = [["", "— belum ditentukan —"], ["ks", "KS"], ["kl", "KL"],
                ["campuran", "Campuran"], ["semi_ks", "Semi KS"]]
    if fin:
        # Tugas pokok staff (keuangan & QC lintas gudang).
        actions += [
            {"id": "rekonsiliasi_timbang", "label": "🔎 Rekonsiliasi timbang ↔ intake",
             "post": "/miniapp/actions/rekonsiliasi-timbang",
             "hint": "Tiket timbang yang belum jadi batch, selisih nota vs timbang, "
                     "batch menunggu bobot.", "fields": []},
            {"id": "verify_gabah", "label": "✅ Verifikasi harga gabah",
             "post": "/miniapp/actions/verify-gabah", "fields": [
                 {"name": "kode_batch", "label": "Batch gabah", "type": "remote",
                  "source": "/miniapp/actions/gabah-unverified",
                  "kosong": "Tidak ada gabah masuk yang menunggu verifikasi."},
                 {"name": "metode", "label": "Metode", "type": "select", "options": METODE},
                 {"name": "nilai", "label": "Nilai (Rp)", "type": "number"},
             ]},
            {"id": "verify_output", "label": "⚙️ Verifikasi output giling",
             "post": "/miniapp/actions/verify-output",
             "hint": "Catat berat PK final → rendemen terhitung.", "fields": [
                 {"name": "kode_proses", "label": "Proses giling selesai", "type": "remote",
                  "source": "/miniapp/actions/milling-unverified",
                  "kosong": "Tidak ada hasil giling yang menunggu verifikasi."},
                 {"name": "berat_output", "label": "Berat PK final (kg)", "type": "number"},
             ]},
            {"id": "qc_giling", "label": "🔬 QC hasil giling",
             "post": "/miniapp/actions/qc-giling",
             "hint": "Isi minimal salah satu: kadar air / broken / susut.", "fields": [
                 {"name": "kode_proses", "label": "Proses giling", "type": "remote",
                  "source": "/miniapp/actions/milling-noqc",
                  "kosong": "Tidak ada hasil giling yang belum dinilai mutunya."},
                 {"name": "kadar_air", "label": "Kadar air (%)", "type": "number"},
                 {"name": "broken", "label": "Broken (%)", "type": "number"},
                 {"name": "susut", "label": "Susut (%)", "type": "number"},
             ]},
            {"id": "catat_pk_luar", "label": "📦 Catat PK luar datang",
             "post": "/miniapp/actions/catat-pk-luar",
             "hint": "Pilih tiket timbang PK yang masih aktif — supplier, bobot & plat "
                     "otomatis dari timbangan. Selanjutnya di-QC & dinilai harga.",
             "fields": [
                 {"name": "timbangan_transaksi_id", "label": "Tiket timbang (PK masuk)",
                  "type": "remote", "source": "/miniapp/actions/timbang-pk-aktif",
                  "kosong": "Tidak ada tiket timbang PK yang aktif."},
                 {"name": "jenis_pk", "label": "Jenis PK (wajib pilih)", "type": "select",
                  "options": JENIS_PK},
                 {"name": "kadar_air", "label": "Kadar air (%) — opsional", "type": "number"},
             ]},
            {"id": "qc_pk_luar", "label": "🔬 Input kualitas PK luar",
             "post": "/miniapp/actions/qc-pk-luar",
             "hint": "PK yang masuk sudah pasti diterima — ini hanya mencatat "
                     "kualitasnya sebagai properti batch. Isi minimal salah satu.",
             "fields": [
                 {"name": "kode_batch", "label": "PK luar (belum ada kualitas)", "type": "remote",
                  "source": "/miniapp/actions/pk-luar-qc",
                  "kosong": "Tidak ada PK luar yang menunggu penilaian mutu."},
                 {"name": "kadar_air", "label": "Kadar air (%)", "type": "number"},
                 {"name": "broken", "label": "Broken (%)", "type": "number"},
                 {"name": "penyusutan", "label": "Penyusutan/bekatul lab (%)", "type": "number"},
                 {"name": "butir_kuning", "label": "Butir kuning", "type": "select",
                  "options": BUTIR, "optional": True},
                 {"name": "catatan_lab", "label": "Catatan lab", "type": "text"},
             ]},
            {"id": "harga_pk_luar", "label": "💰 Verifikasi harga PK luar",
             "post": "/miniapp/actions/harga-pk-luar",
             "hint": "Terpisah dari kualitas — kapan saja. Isi metode & nilai; "
                     "potongan opsional.", "fields": [
                 {"name": "kode_batch", "label": "PK luar (harga belum diverifikasi)",
                  "type": "remote", "source": "/miniapp/actions/pk-luar-harga",
                  "kosong": "Tidak ada PK luar yang menunggu penetapan harga."},
                 {"name": "metode", "label": "Metode harga (wajib pilih)", "type": "select",
                  "options": METODE},
                 {"name": "nilai", "label": "Nilai (Rp)", "type": "number"},
                 {"name": "potongan_kg", "label": "Potongan (kg) — opsional", "type": "number"},
                 {"name": "potongan_alasan", "label": "Alasan potongan — opsional", "type": "text"},
             ]},
            {"id": "transfer_pk", "label": "🚚 Pemindahan PK G1 → G2",
             "post": "/miniapp/actions/transfer-pk", "fields": [
                 {"name": "kode_proses", "label": "PK dari proses", "type": "remote",
                  "source": "/miniapp/actions/pk-transfer",
                  "kosong": "Tidak ada PK yang siap dipindah."},
                 {"name": "berat", "label": "Berat kg (kosong = semua)", "type": "number"},
                 {"name": "tujuan", "label": "Tujuan", "type": "select", "options": TUJUAN},
             ]},
        ]

    # Aksi inventory tinggal di modulnya sendiri, tetapi menunya tetap SATU
    # daftar dari satu tempat: perangkat tidak perlu tahu bahwa ia dirakit
    # dari beberapa berkas.
    from app.web import aksi_inventory, aksi_undo
    actions += aksi_inventory.spesifikasi(g2=g2, fin=fin)
    # Siapa pun yang boleh mencatat sesuatu boleh membatalkan catatannya
    # sendiri — termasuk operator, yang justru paling sering salah ketik.
    actions += aksi_undo.spesifikasi(boleh=g1 or g2 or fin)

    # Tandai gudang tiap aksi → dipakai Mini App memisah tab G1/G2 (admin/staff).
    for a in actions:
        a["wh"] = _ACTION_WH.get(a["id"], "g1")
    return actions


# Pemetaan aksi → gudang. Aksi keuangan/QC dikelompokkan ke gudang yang relevan:
# harga & QC gabah/giling = G1; PK luar (catat/kualitas/harga) = G2; transfer PK
# berasal dari proses G1 → G1.
_ACTION_WH = {
    # Gudang 1 (Selepan)
    "gabah_masuk": "g1", "pindah_tumpukan": "g1", "mulai_pengeringan": "g1", "kadar_air": "g1",
    "selesai_pengeringan": "g1", "selesai_pendinginan": "g1", "pindah_silo": "g1",
    "mulai_giling": "g1", "hasil_giling": "g1", "selesai_giling": "g1",
    "verify_gabah": "g1", "verify_output": "g1", "qc_giling": "g1", "transfer_pk": "g1",
    "rekonsiliasi_timbang": "g1",
    # Gudang 2 (Penyosohan)
    "masukkan_pk": "g2", "mulai_penyosohan": "g2", "hasil_penyosohan": "g2",
    "selesai_penyosohan": "g2", "catat_pk_luar": "g2", "qc_pk_luar": "g2",
    "harga_pk_luar": "g2",
    # Inventory: packing & bekatul lahir di Gudang 2. Pembelian karung, harga
    # hasil samping, dan seluruh barang keluar dikelompokkan ke G2 pula —
    # barang jadi memang berdiri di sana, dan dari sanalah ia berangkat.
    "catat_packing": "g2", "catat_bekatul": "g2", "beli_kemasan": "g2",
    "kirim_barang_jadi": "g2", "kirim_bekatul": "g2", "harga_byproduct": "g2",
    # Kecuali PK: ia dijual mentah dari Gudang 1, sebelum disosoh.
    "jual_pk": "g1",
    # Undo tidak milik gudang mana pun; ia ikut G1 karena di situlah
    # tab pertama terbuka, dan aksinya sama isinya di kedua tab.
    "undo": "g1",
}


# ─────────────────────── Aksi cepat: daftar pilihan (remote) ───────────────────────

@router.get("/actions/silo-g1")
async def silo_g1(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Silo gabah kering Gudang 1, beserta isinya sekarang.

    Isinya ikut ditampilkan karena silo yang sudah berisi TETAP boleh
    menerima — tetapi orang berhak tahu sebelum memilih, bukan diberi tahu
    lewat peringatan sesudahnya.
    """
    _require(await _is_g1_operator(user))
    from app.penggilingan.gudang1.services.silo import _silo_content_kg, silos_g1
    out = []
    async with SessionLocal() as db:
        for si in await silos_g1(db):
            kg = await _silo_content_kg(db, si.id)
            isi = f"berisi {_rp(kg)} kg" if kg else "kosong"
            out.append({"value": si.nama_silo.replace("Silo ", ""),
                        "label": f"{si.nama_silo} · {isi}"})
    return out


@router.get("/actions/dryer-menunggu")
async def dryer_menunggu(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Mesin pengering yang ADA gabahnya menunggu dinyalakan.

    Bukan seluruh mesin: menawarkan mesin kosong hanya menghasilkan penolakan
    "tidak ada gabah di mesin itu" setelah orang memilihnya.
    """
    _require(await _is_g1_operator(user))
    from app.penggilingan.gudang1.services.drying import (
        _loose_dryer_batches, dryers_g1)
    out = []
    async with SessionLocal() as db:
        for d in await dryers_g1(db):
            batches = await _loose_dryer_batches(db, d.id)
            if not batches:
                continue
            kg = sum(float(b.berat_total_kg or 0) for b in batches)
            out.append({"value": d.id,
                        "label": f"{d.nama} · {len(batches)} batch · {_rp(kg)} kg"})
    return out


@router.get("/actions/tumpukan")
async def gabah_menunggu_tempat(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Gabah yang belum ada di dryer maupun silo.

    Dua keadaan sekaligus: yang sedang menumpuk, dan yang tercatat tetapi
    penempatan otomatisnya gagal. Keduanya butuh tindakan yang sama, jadi
    keduanya ditawarkan lewat satu aksi — bukan dua yang mirip.
    """
    _require(await _is_g1_operator(user))
    from app.penggilingan.gudang1.services.tumpukan import DITUMPUK, menunggu_tempat
    async with SessionLocal() as db:
        batches = await menunggu_tempat(db)
    return [{
        "value": b.kode_batch,
        "label": (f"{b.kode_batch} · {b.kondisi_gabah} · "
                  f"{_rp(float(b.berat_total_kg or 0))} kg · "
                  + ("di tumpukan" if b.status_batch == DITUMPUK
                     else "belum ditempatkan")),
    } for b in batches]


class PindahTumpukanReq(BaseModel):
    kode_batch: str
    tujuan: str


@router.post("/actions/pindah-tumpukan")
async def act_tempatkan_gabah(req: PindahTumpukanReq,
                              user: User = Depends(pengguna_aksi)) -> dict:
    """Tempatkan gabah: dryer, silo, atau tumpukan.

    Tujuan yang sah ditentukan kondisi gabahnya, dan diperiksa di layanan —
    bukan di sini dan bukan di layar: gabah basah belum boleh ke silo, dari
    mana pun ia datang.
    """
    _require(await _is_g1_operator(user))
    from app.penggilingan.gudang1.services.tumpukan import TumpukanError, tempatkan
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            jenis, mesin_id = _urai_tujuan(req.tujuan)
            batch, tempat = await tempatkan(
                db, user=u, kode_batch=req.kode_batch, tujuan=jenis,
                dryer_id=mesin_id if jenis == "dryer" else None,
                silo_id=mesin_id if jenis == "silo" else None)
        except TumpukanError as e:
            raise _err(e, "Gagal menempatkan gabah.")
    pesan = f"✓ *{batch.kode_batch}* ditempatkan → {tempat}."
    await _chat_confirm(user, pesan)
    return {"ok": True, "pesan": pesan}


@router.get("/actions/drying-active")
async def drying_active(user: User = Depends(pengguna_aksi)) -> list[dict]:
    _require(await _is_g1_operator(user))
    from sqlalchemy import select
    from app.models import DryingLot
    async with SessionLocal() as db:
        lots = (
            await db.execute(
                select(DryingLot.kode_lot).where(DryingLot.status == "proses")
                .order_by(DryingLot.id.desc())
            )
        ).scalars().all()
    return [{"value": k, "label": k} for k in lots]


@router.get("/actions/milling-active")
async def milling_active(user: User = Depends(pengguna_aksi)) -> list[dict]:
    _require(await _is_g1_operator(user))
    from sqlalchemy import select
    from app.models import MillingProcess
    async with SessionLocal() as db:
        procs = (
            await db.execute(
                select(MillingProcess.kode_proses).where(MillingProcess.status == "proses")
                .order_by(MillingProcess.id.desc())
            )
        ).scalars().all()
    return [{"value": k, "label": k} for k in procs]


@router.get("/actions/cooling-active")
async def cooling_active(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Lot selesai dikeringkan, masih DIDINGINKAN (belum dinyatakan selesai
    pendinginan) & masih di dryer."""
    _require(await _is_g1_operator(user))
    from sqlalchemy import exists, select
    from app.models import DryingLot, SiloStorage
    async with SessionLocal() as db:
        belum_silo = ~exists().where(SiloStorage.drying_lot_id == DryingLot.id)
        lots = (
            await db.execute(
                select(DryingLot.kode_lot).where(
                    DryingLot.status == "selesai",
                    DryingLot.dryer_id.is_not(None),
                    DryingLot.waktu_selesai_pendinginan.is_(None),
                    belum_silo,
                ).order_by(DryingLot.id.desc())
            )
        ).scalars().all()
    return [{"value": k, "label": k} for k in lots]


@router.get("/actions/drying-done")
async def drying_done(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Lot yang sudah SELESAI PENDINGINAN (dryer idle) tapi belum dipindah ke
    silo — siap dipindah."""
    _require(await _is_g1_operator(user))
    from sqlalchemy import exists, select
    from app.models import DryingLot, SiloStorage
    async with SessionLocal() as db:
        belum_silo = ~exists().where(SiloStorage.drying_lot_id == DryingLot.id)
        lots = (
            await db.execute(
                select(DryingLot.kode_lot).where(
                    DryingLot.status == "selesai",
                    DryingLot.dryer_id.is_not(None),  # kering-langsung sudah di silo
                    DryingLot.waktu_selesai_pendinginan.is_not(None),
                    belum_silo,
                ).order_by(DryingLot.id.desc())
            )
        ).scalars().all()
    return [{"value": k, "label": k} for k in lots]


@router.get("/actions/silo-siap-giling")
async def silo_siap_giling(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Silo Gudang 1 yang ADA isinya & tak sedang digiling."""
    _require(await _is_g1_operator(user))
    from sqlalchemy import select
    from app.models import MillingProcess, Silo
    from app.penggilingan.gudang1.services.silo import _g1_warehouse_id, _silo_active_rows, _silo_content_kg
    out: list[dict] = []
    async with SessionLocal() as db:
        wid = await _g1_warehouse_id(db)
        silos = (
            await db.execute(
                select(Silo).where(Silo.warehouse_id == wid).order_by(Silo.nama_silo)
            )
        ).scalars().all()
        for s in silos:
            rows = await _silo_active_rows(db, s.id)
            if not rows:
                continue
            busy = (
                await db.execute(
                    select(MillingProcess.id).where(
                        MillingProcess.silo_id == s.id, MillingProcess.status == "proses"
                    )
                )
            ).first()
            if busy:
                continue
            letter = s.nama_silo.replace("Silo ", "")
            kg = await _silo_content_kg(db, s.id)
            out.append({"value": letter, "label": f"Silo {letter} · {_rp(kg)} kg"})
    return out


@router.get("/actions/gabah-unverified")
async def gabah_unverified(user: User = Depends(pengguna_aksi)) -> list[dict]:
    _require(can_see_financials(user))
    from sqlalchemy import select
    from app.models import PurchaseBatch, Supplier
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(PurchaseBatch, Supplier.nama_supplier)
                .join(Supplier, Supplier.id == PurchaseBatch.supplier_id)
                .where(PurchaseBatch.flag_unverified.is_(True))
                .order_by(PurchaseBatch.id.desc()).limit(30)
            )
        ).all()
    return [{"value": b.kode_batch,
             "label": f"{b.kode_batch} · {s} · {_rp(float(b.berat_total_kg or 0))} kg"}
            for b, s in rows]


@router.get("/actions/pk-transfer")
async def pk_transfer_list(user: User = Depends(pengguna_aksi)) -> list[dict]:
    _require(can_transfer_pk(user))
    from sqlalchemy import select
    from app.models import MillingProcess
    from app.services.transfer import pending_transfer_kg
    from app.penggilingan.gudang1.services.milling import pk_jenis
    out: list[dict] = []
    async with SessionLocal() as db:
        procs = (
            await db.execute(select(MillingProcess).order_by(MillingProcess.kode_proses))
        ).scalars().all()
        for p in procs:
            avail = await pending_transfer_kg(db, p.id)
            if avail > 0:
                jns = await pk_jenis(db, p)
                out.append({"value": p.kode_proses,
                            "label": f"{p.kode_proses} · {jns or '-'} · {_rp(avail)} kg"})
    return out


@router.get("/actions/polishing-active")
async def polishing_active(user: User = Depends(pengguna_aksi)) -> list[dict]:
    _require(await _is_g2_operator(user))
    from sqlalchemy import select
    from app.models import PolishingProcess
    async with SessionLocal() as db:
        procs = (
            await db.execute(
                select(PolishingProcess.kode_proses).where(PolishingProcess.status == "proses")
                .order_by(PolishingProcess.id.desc())
            )
        ).scalars().all()
    return [{"value": k, "label": k} for k in procs]


@router.get("/actions/pk-intake-pending")
async def pk_intake_pending(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """PK luar SUDAH diterima (QC) tapi belum dimasukkan ke silo/tumpukan."""
    _require(await _is_g2_operator(user))
    from sqlalchemy import exists, select
    from app.models import PkGudang2Intake, PkPurchaseBatch
    async with SessionLocal() as db:
        ada_intake = ~exists().where(
            PkGudang2Intake.pk_purchase_batch_id == PkPurchaseBatch.id)
        rows = (
            await db.execute(
                select(PkPurchaseBatch).where(
                    PkPurchaseBatch.status_batch == "diterima", ada_intake
                ).order_by(PkPurchaseBatch.id.desc()).limit(30)
            )
        ).scalars().all()
    return [{"value": b.kode_batch,
             "label": f"{b.kode_batch} · {_rp(float(b.berat_total_kg or 0))} kg"}
            for b in rows]


@router.get("/actions/milling-unverified")
async def milling_unverified(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Milling SELESAI yang output PK-nya belum diverifikasi (berat final)."""
    _require(can_see_financials(user))
    from sqlalchemy import exists, select
    from app.models import MillingProcess, MillingProcessVerification
    async with SessionLocal() as db:
        sudah = exists().where(
            (MillingProcessVerification.milling_process_id == MillingProcess.id)
            & (MillingProcessVerification.berat_output_final_kg.is_not(None))
        )
        procs = (
            await db.execute(
                select(MillingProcess.kode_proses).where(
                    MillingProcess.status == "selesai", ~sudah
                ).order_by(MillingProcess.kode_proses.desc())
            )
        ).scalars().all()
    return [{"value": k, "label": k} for k in procs]


@router.get("/actions/milling-noqc")
async def milling_noqc(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Milling SELESAI yang belum ada catatan QC sama sekali."""
    _require(can_see_financials(user))
    from sqlalchemy import select
    from app.models import MillingProcess, MillingQcLog
    async with SessionLocal() as db:
        qc_ids = select(MillingQcLog.milling_process_id).distinct()
        procs = (
            await db.execute(
                select(MillingProcess.kode_proses).where(
                    MillingProcess.status == "selesai",
                    MillingProcess.id.not_in(qc_ids),
                ).order_by(MillingProcess.kode_proses.desc())
            )
        ).scalars().all()
    return [{"value": k, "label": k} for k in procs]


@router.get("/actions/pk-luar-qc")
async def pk_luar_qc(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """PK luar (sudah masuk) yang BELUM diinput kualitasnya."""
    _require(can_see_financials(user))
    from sqlalchemy import exists, or_, select
    from app.models import PkPurchaseBatch, PkPurchaseVerification
    async with SessionLocal() as db:
        qc_ada = exists().where(
            (PkPurchaseVerification.pk_purchase_batch_id == PkPurchaseBatch.id)
            & or_(
                PkPurchaseVerification.kadar_air.is_not(None),
                PkPurchaseVerification.broken_persen.is_not(None),
                PkPurchaseVerification.penyusutan_persen.is_not(None),
                PkPurchaseVerification.butir_kuning.is_not(None),
                PkPurchaseVerification.catatan_lab.is_not(None),
            )
        )
        rows = (
            await db.execute(
                select(PkPurchaseBatch).where(
                    PkPurchaseBatch.status_batch.in_(("diterima", "di_silo", "ditumpuk")),
                    ~qc_ada,
                ).order_by(PkPurchaseBatch.id.desc()).limit(30)
            )
        ).scalars().all()
    return [{"value": b.kode_batch,
             "label": f"{b.kode_batch} · {_rp(float(b.berat_total_kg or 0))} kg"}
            for b in rows]


@router.get("/actions/pk-luar-harga")
async def pk_luar_harga(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """PK luar yang HARGA-nya belum diverifikasi (flag_unverified)."""
    _require(can_see_financials(user))
    from sqlalchemy import select
    from app.models import PkPurchaseBatch
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(PkPurchaseBatch).where(
                    PkPurchaseBatch.flag_unverified.is_(True),
                ).order_by(PkPurchaseBatch.id.desc()).limit(30)
            )
        ).scalars().all()
    return [{"value": b.kode_batch,
             "label": f"{b.kode_batch} · {_rp(float(b.berat_total_kg or 0))} kg"}
            for b in rows]


# ─────────────────────── Aksi cepat: eksekusi (POST) ───────────────────────

class GabahMasukReq(BaseModel):
    # Operator hanya memilih TIKET TIMBANG aktif — supplier/bobot/nopol dari timbang.
    timbangan_transaksi_id: int
    tujuan: str | None = None       # dryer / silo_a / silo_b
    kondisi: str | None = None      # opsional; diturunkan dari jenis timbang bila kosong


@router.get("/actions/timbang-masuk-aktif")
async def timbang_masuk_aktif(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Daftar tiket timbang MASUK gabah yang masih AKTIF & belum tertaut batch."""
    _require(await _is_g1_operator(user))
    from app.penggilingan.gudang1.services.timbang_link import tiket_masuk_aktif
    async with SessionLocal() as db:
        tk = await tiket_masuk_aktif(db)
    out = []
    from app.penggilingan.peta_jenis import intake_dari_jenis
    for t in tk:
        # Dibaca dari peta jenis, bukan ditebak dari awalan kodenya — lihat
        # alasannya di `services.berjalan._tiket_belum_ditaut`.
        info = intake_dari_jenis(t.get("jenis_kode", ""))
        if info is None or info.model != "gabah":
            continue  # gabah saja (PK punya aksi sendiri)
        nm = t.get("nama_supplier") or t.get("pihak_nama") or "?"
        b = t.get("berat_hpp_kg")
        bstr = f"{_rp(float(b))} kg ({t['sumber_berat']})" if b else "⚠️ bobot belum ada"
        tanda = " · SUSULAN (tiket sudah ditutup)" if t.get("susulan") else ""
        komoditas = t.get("jenis_nama") or t.get("jenis_kode") or "?"
        out.append({"value": t["id"],
                    "label": f"{t['kode']} · {komoditas} · {nm} · "
                             f"{t.get('nomor_polisi') or '-'} · {bstr}{tanda}"})
    return out


@router.post("/actions/gabah-masuk")
async def act_gabah_masuk(req: GabahMasukReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g1_operator(user))

    from app.penggilingan.peta_jenis import intake_dari_jenis
    from app.penggilingan.gudang1.services.purchase import create_purchase_batch_dari_timbang
    from app.penggilingan.gudang1.services.timbang_link import ambil_tiket
    from app.penggilingan.gudang1.services.drying import masuk_dryer, DryingError
    from app.penggilingan.gudang1.services.silo import masuk_silo, SiloError
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        tiket = await ambil_tiket(db, req.timbangan_transaksi_id)
        if tiket is None:
            raise HTTPException(400, "Tiket timbang tak ditemukan.")
        # Peta jenis → produksi langsung tahu kondisi & tujuan yang sah.
        info = intake_dari_jenis(tiket.get("jenis_kode", ""))
        if info is None or info.model != "gabah":
            raise HTTPException(400, "Tiket ini bukan gabah masuk.")
        kondisi = info.kondisi
        mesin_id = None
        if info.tujuan_wajib:
            tujuan = info.tujuan_wajib
        else:
            tujuan, mesin_id = _urai_tujuan(req.tujuan)
            if tujuan not in info.tujuan_pilihan:
                # Pesannya menyebut yang SAH untuk gabah ini, bukan daftar
                # umum: operator yang memilih Silo untuk gabah basah perlu
                # tahu kenapa ditolak, bukan sekadar bahwa ia ditolak.
                nama = {"dryer": "Dryer", "silo_a": "Silo A", "silo_b": "Silo B",
                        "tumpuk": "Tumpukan"}
                boleh = " / ".join(nama.get(t, t) for t in info.tujuan_pilihan)
                raise HTTPException(400, f"Gabah {kondisi} hanya boleh ke: {boleh}.")
        try:
            r = await create_purchase_batch_dari_timbang(
                db, user=u, timbangan_transaksi_id=req.timbangan_transaksi_id,
                kondisi_gabah=kondisi,
            )
        except ValueError as e:
            raise HTTPException(400, str(e))
        except Exception as e:  # noqa: BLE001
            raise _err(e, "Gagal mencatat gabah.")
        kode = r.batch.kode_batch

        # PENEMPATAN (agar tak nyangkut sebagai 'baru').
        tempat, warn = "", ""
        try:
            if tujuan == "tumpuk":
                from app.penggilingan.gudang1.services.tumpukan import masuk_tumpukan
                await masuk_tumpukan(db, user=u, kode_batch=kode)
                tempat = (f"📦 ditumpuk (tumpukan {kondisi}) — muncul di Berjalan "
                          "sampai dipindah")
            elif tujuan == "dryer":
                r_dryer = await masuk_dryer(db, user=u, kode_batch_list=[kode],
                                            dryer_id=mesin_id)
                nama_mesin = r_dryer.nama_dryer or "dryer"
                tempat = (f"🌫️ masuk {nama_mesin} (menunggu — tekan "
                          "`Mulai pengeringan` saat dipanaskan)")
            else:  # silo (kering langsung)
                from app.penggilingan.gudang1.services.silo import silo_g1_by_id
                si = await silo_g1_by_id(db, mesin_id) if mesin_id else None
                if si is None:
                    raise HTTPException(400, "Pilih silo tujuannya dulu.")
                await masuk_silo(db, user=u,
                                 nama_silo=si.nama_silo.replace("Silo ", ""),
                                 kode_lot=None, kode_batch=kode)
                tempat = (f"🏗️ masuk {si.nama_silo} (kering menunggu — "
                          "lot terbentuk saat digiling)")
        except (DryingError, SiloError) as e:
            warn = f"\n⚠️ Belum ditempatkan: {e.args[0] if e.args else 'gagal'}. Tempatkan manual."

    pesan = f"✓ Gabah *{kode}* ({kondisi}) tercatat" + (f".\n{tempat}." if tempat else ".") + warn
    await _chat_confirm(user, pesan)
    return {"ok": True, "pesan": pesan}


class KadarAirReq(BaseModel):
    kode_lot: str
    kadar_air: float


@router.post("/actions/kadar-air")
async def act_kadar_air(req: KadarAirReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g1_operator(user))
    if not (req.kode_lot or "").strip():
        raise HTTPException(400, "Pilih lot pengeringan dulu.")
    from app.penggilingan.gudang1.services.drying import log_moisture
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            await log_moisture(db, user=u, kode_lot=req.kode_lot,
                               indikator=req.kadar_air, tes_manual=None)
        except Exception as e:  # noqa: BLE001
            raise _err(e, "Gagal update kadar air.")
    pesan = f"✓ Kadar air *{req.kode_lot}*: {req.kadar_air:g}%."
    await _chat_confirm(user, pesan)
    return {"ok": True, "pesan": pesan}


class HasilGilingReq(BaseModel):
    kode_proses: str
    berat_kumulatif: float


@router.post("/actions/hasil-giling")
async def act_hasil_giling(req: HasilGilingReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g1_operator(user))
    if not (req.kode_proses or "").strip():
        raise HTTPException(400, "Pilih proses giling dulu.")
    from app.penggilingan.gudang1.services.milling import log_progress
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            await log_progress(db, user=u, kode_proses=req.kode_proses,
                               berat_kumulatif=req.berat_kumulatif)
        except Exception as e:  # noqa: BLE001
            raise _err(e, "Gagal update hasil giling.")
    pesan = f"✓ Hasil giling *{req.kode_proses}*: {req.berat_kumulatif:g} kg (kumulatif)."
    await _chat_confirm(user, pesan)
    return {"ok": True, "pesan": pesan}


class MulaiPengeringanReq(BaseModel):
    dryer_id: int | None = None


@router.post("/actions/mulai-pengeringan")
async def act_mulai_pengeringan(req: MulaiPengeringanReq | None = None,
                                user: User = Depends(pengguna_aksi)) -> dict:
    """Bentuk 1 lot dari gabah yang menunggu di SATU mesin, mulai proses."""
    _require(await _is_g1_operator(user))
    from app.penggilingan.gudang1.services.drying import start_drying, DryingError
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await start_drying(db, user=u,
                                   dryer_id=(req.dryer_id if req else None))
        except DryingError as e:
            raise _err(e, "Gagal mulai pengeringan.")
    pesan = (f"✓ Pengeringan *{r.lot.kode_lot}* mulai — {r.kondisi}, "
             f"{len(r.batch_kodes)} batch ({r.total_kg:g} kg).")
    if r.peringatan:
        pesan += f"\n{r.peringatan}"
    await _chat_confirm(user, pesan)
    return {"ok": True, "pesan": pesan}


class KodeLotReq(BaseModel):
    kode_lot: str


@router.post("/actions/selesai-pengeringan")
async def act_selesai_pengeringan(req: KodeLotReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g1_operator(user))
    if not (req.kode_lot or "").strip():
        raise HTTPException(400, "Pilih lot pengeringan dulu.")
    from app.penggilingan.gudang1.services.drying import finish_drying, DryingError
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            lot, jam = await finish_drying(db, user=u, kode_lot=req.kode_lot)
        except DryingError as e:
            raise _err(e, "Gagal menyelesaikan pengeringan.")
    pesan = (f"✓ Pengeringan *{req.kode_lot}* selesai ({jam:.0f} jam) → "
             "fase pendinginan. Nyatakan pendinginan selesai saat sudah dingin.")
    await _chat_confirm(user, pesan)
    return {"ok": True, "pesan": pesan}


@router.post("/actions/selesai-pendinginan")
async def act_selesai_pendinginan(req: KodeLotReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g1_operator(user))
    if not (req.kode_lot or "").strip():
        raise HTTPException(400, "Pilih lot yang didinginkan dulu.")
    from app.penggilingan.gudang1.services.drying import finish_cooling, DryingError
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            lot, jam = await finish_cooling(db, user=u, kode_lot=req.kode_lot)
        except DryingError as e:
            raise _err(e, "Gagal menyatakan pendinginan selesai.")
    pesan = (f"✓ Pendinginan *{req.kode_lot}* selesai ({jam:.0f} jam) — dryer idle. "
             "Pindahkan ke silo saat ada silo kosong.")
    await _chat_confirm(user, pesan)
    return {"ok": True, "pesan": pesan}


class PindahSiloReq(BaseModel):
    kode_lot: str
    silo: str  # A / B


@router.post("/actions/pindah-silo")
async def act_pindah_silo(req: PindahSiloReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g1_operator(user))
    if not (req.kode_lot or "").strip():
        raise HTTPException(400, "Pilih lot yang mau dipindah dulu.")
    if not (req.silo or "").strip():
        raise HTTPException(400, "Pilih silo tujuannya dulu.")
    from app.penggilingan.gudang1.services.silo import masuk_silo, SiloError
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await masuk_silo(db, user=u, nama_silo=req.silo.upper(),
                                 kode_lot=req.kode_lot, kode_batch=None)
        except SiloError as e:
            raise _err(e, "Gagal memindahkan ke silo.")
    pesan = (f"✓ Lot *{req.kode_lot}* dipindah → Silo {r.nama_silo} ({r.kg:g} kg). "
             "Dryer kosong, siap digiling.")
    if r.digabung:
        # Bukan penolakan: gabahnya harus keluar dari dryer, dan menahannya
        # sampai silo kosong justru memacetkan pengeringan berikutnya. Tetapi
        # isinya kini campuran, dan itu harus terbaca — bukan diketahui
        # belakangan saat angka giling tidak seperti yang diingat orang.
        pesan += ("\n⚠️ Silo sudah berisi sebelumnya — isinya kini tercampur. "
                  "Semuanya akan digiling sebagai SATU proses.")
    await _chat_confirm(user, pesan)
    return {"ok": True, "pesan": pesan}


class MulaiGilingReq(BaseModel):
    silo: str  # A / B


@router.post("/actions/mulai-giling")
async def act_mulai_giling(req: MulaiGilingReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g1_operator(user))
    if (req.silo or "").upper() not in ("A", "B"):
        raise HTTPException(400, "Pilih silo yang digiling dulu.")
    from app.penggilingan.gudang1.services.milling import start_milling, MillingError
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await start_milling(db, user=u, nama_silo=req.silo.upper())
        except MillingError as e:
            raise _err(e, "Gagal mulai giling.")
    pesan = (f"✓ Giling *{r.proc.kode_proses}* mulai — Silo {r.nama_silo} "
             f"({r.berat_masuk:g} kg gabah).")
    await _chat_confirm(user, pesan)
    return {"ok": True, "pesan": pesan}


class KodeProsesReq(BaseModel):
    kode_proses: str


@router.post("/actions/selesai-giling")
async def act_selesai_giling(req: KodeProsesReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g1_operator(user))
    if not (req.kode_proses or "").strip():
        raise HTTPException(400, "Pilih proses giling dulu.")
    from app.penggilingan.gudang1.services.milling import finish_milling, MillingError
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await finish_milling(db, user=u, kode_proses=req.kode_proses)
        except MillingError as e:
            raise _err(e, "Gagal menyelesaikan giling.")
    jns = (r.jenis + " ") if r.jenis else ""
    pesan = (f"✓ Giling *{req.kode_proses}* selesai — PK {jns}{r.produced:g} kg "
             f"(siap kirim {r.siap_kirim:g} kg).")
    await _chat_confirm(user, pesan)
    return {"ok": True, "pesan": pesan}


class VerifyGabahReq(BaseModel):
    kode_batch: str
    metode: str
    nilai: float


@router.post("/actions/verify-gabah")
async def act_verify_gabah(req: VerifyGabahReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(can_see_financials(user))
    if not (req.kode_batch or "").strip():
        raise HTTPException(400, "Pilih batch gabah dulu.")
    if req.metode not in ("per_kg", "total"):
        raise HTTPException(400, "Pilih metode dulu: Total atau Per kg.")
    from app.services.verification import get_batch_by_kode, verify_gabah_price
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        batch = await get_batch_by_kode(db, req.kode_batch)
        if batch is None:
            raise HTTPException(404, f"Batch {req.kode_batch} tidak ditemukan.")
        try:
            await verify_gabah_price(db, user=u, batch=batch,
                                     metode=req.metode, nilai_rupiah=req.nilai)
        except Exception as e:  # noqa: BLE001
            raise _err(e, "Gagal verifikasi harga.")
    pesan = f"✓ Harga gabah *{req.kode_batch}* diverifikasi & tersimpan."
    await _chat_confirm(user, pesan, "admin")
    return {"ok": True, "pesan": pesan}


class VerifyOutputReq(BaseModel):
    kode_proses: str
    berat_output: float | None = None


@router.post("/actions/verify-output")
async def act_verify_output(req: VerifyOutputReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(can_see_financials(user))
    if not (req.kode_proses or "").strip():
        raise HTTPException(400, "Pilih proses giling dulu.")
    if req.berat_output is None:
        raise HTTPException(400, "Isi berat PK final dulu.")
    from app.penggilingan.gudang1.services.milling import verify_milling_output, MillingError
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await verify_milling_output(db, user=u, kode_proses=req.kode_proses,
                                            berat_output=req.berat_output)
        except MillingError as e:
            raise _err(e, "Gagal verifikasi output.")
    rnd = f" (rendemen {r.rendemen_persen:.1f}%)" if r.rendemen_persen is not None else ""
    pesan = f"✓ Output *{req.kode_proses}* diverifikasi: {r.berat_output:g} kg{rnd}."
    await _chat_confirm(user, pesan, "admin")
    return {"ok": True, "pesan": pesan}


class QcGilingReq(BaseModel):
    kode_proses: str
    kadar_air: float | None = None
    broken: float | None = None
    susut: float | None = None


@router.post("/actions/qc-giling")
async def act_qc_giling(req: QcGilingReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(can_see_financials(user))
    if not (req.kode_proses or "").strip():
        raise HTTPException(400, "Pilih proses giling dulu.")
    if all(v is None for v in (req.kadar_air, req.broken, req.susut)):
        raise HTTPException(400, "Isi minimal salah satu: kadar air / broken / susut.")
    from app.penggilingan.gudang1.services.milling import log_qc_milling, MillingError
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await log_qc_milling(db, user=u, kode_proses=req.kode_proses,
                                     kadar_air=req.kadar_air, broken=req.broken,
                                     susut=req.susut, kondisi=None)
        except MillingError as e:
            raise _err(e, "Gagal mencatat QC.")
    det = ", ".join(
        f"{lbl} {v:g}%" for lbl, v in
        (("KA", r.kadar_air), ("broken", r.broken), ("susut", r.susut)) if v is not None
    )
    jns = f" [{r.kondisi}]" if r.kondisi else ""
    pesan = f"✓ QC *{req.kode_proses}*{jns}: {det}."
    await _chat_confirm(user, pesan, "admin")
    return {"ok": True, "pesan": pesan}


class CatatPkLuarReq(BaseModel):
    # Pilih TIKET TIMBANG PK aktif — supplier/bobot/nopol dari timbang.
    timbangan_transaksi_id: int
    jenis_pk: str
    kadar_air: float | None = None


@router.get("/actions/timbang-pk-aktif")
async def timbang_pk_aktif(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Daftar tiket timbang PK (BERAS_PK) MASUK yang masih AKTIF & belum tertaut."""
    _require(can_see_financials(user))
    from app.penggilingan.gudang1.services.timbang_link import tiket_masuk_aktif
    from app.penggilingan.peta_jenis import is_pk
    async with SessionLocal() as db:
        tk = await tiket_masuk_aktif(db)
    out = []
    for t in tk:
        if not is_pk(t.get("jenis_kode", "")):
            continue
        nm = t.get("nama_supplier") or t.get("pihak_nama") or "?"
        b = t.get("berat_hpp_kg")
        bstr = f"{_rp(float(b))} kg ({t['sumber_berat']})" if b else "⚠️ bobot belum ada"
        out.append({"value": t["id"],
                    "label": f"{t['kode']} · {nm} · {t.get('nomor_polisi') or '-'} · {bstr}"})
    return out


@router.post("/actions/rekonsiliasi-timbang")
async def act_rekonsiliasi_timbang(user: User = Depends(pengguna_aksi)) -> dict:
    """Laporan rekonsiliasi timbangan ↔ intake (staff/admin)."""
    _require(can_see_financials(user))
    from app.penggilingan.gudang1.services.rekonsiliasi import rekonsiliasi, format_rekonsiliasi
    async with SessionLocal() as db:
        d = await rekonsiliasi(db)
    return {"ok": True, "pesan": format_rekonsiliasi(d)}


@router.post("/actions/catat-pk-luar")
async def act_catat_pk_luar(req: CatatPkLuarReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(can_see_financials(user))
    if req.jenis_pk not in ("ks", "kl", "campuran", "semi_ks"):
        raise HTTPException(400, "Pilih jenis PK dulu: KS / KL / Campuran / Semi KS.")
    from app.penggilingan.gudang2.service import create_pk_purchase_dari_timbang, Gudang2Error
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await create_pk_purchase_dari_timbang(
                db, user=u, timbangan_transaksi_id=req.timbangan_transaksi_id,
                jenis_pk=req.jenis_pk, kadar_air=req.kadar_air,
            )
        except Gudang2Error as e:
            raise _err(e, "Gagal mencatat PK luar.")
        berat = r.batch.berat_total_kg
        nopol = r.batch.no_polisi_truk or "-"
    jl = {"ks": "KS", "kl": "KL", "campuran": "Campuran", "semi_ks": "Semi KS"}.get(
        r.batch.jenis_pk, r.batch.jenis_pk or "-")
    baru = " (supplier baru)" if r.supplier_created else ""
    bstr = f"{float(berat):g} kg" if berat is not None else "menunggu bobot"
    pesan = (f"✓ PK luar *{r.batch.kode_batch}* tercatat — {r.supplier_nama}{baru}, "
             f"{jl} {bstr}, truk {nopol}. "
             "Diterima — menunggu input kualitas & verifikasi harga.")
    await _chat_confirm(user, pesan, "admin")
    return {"ok": True, "pesan": pesan}


class QcPkLuarReq(BaseModel):
    kode_batch: str
    kadar_air: float | None = None
    broken: float | None = None
    penyusutan: float | None = None
    butir_kuning: str | None = None
    catatan_lab: str | None = None


@router.post("/actions/qc-pk-luar")
async def act_qc_pk_luar(req: QcPkLuarReq, user: User = Depends(pengguna_aksi)) -> dict:
    """Input kualitas PK luar (properti batch) — bukan keputusan terima/tolak."""
    _require(can_see_financials(user))
    if not (req.kode_batch or "").strip():
        raise HTTPException(400, "Pilih PK luar dulu.")
    if all(v is None for v in (req.kadar_air, req.broken, req.penyusutan)) \
            and not (req.butir_kuning or req.catatan_lab):
        raise HTTPException(400, "Isi minimal salah satu: kadar air / broken / "
                                 "penyusutan / butir kuning / catatan.")
    from app.penggilingan.gudang2.service import log_pk_qc, Gudang2Error
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await log_pk_qc(
                db, user=u, kode=req.kode_batch, kadar_air=req.kadar_air,
                broken=req.broken, penyusutan_persen=req.penyusutan,
                butir_kuning=(req.butir_kuning or None),
                catatan_lab=(req.catatan_lab or None),
            )
        except Gudang2Error as e:
            raise _err(e, "Gagal input kualitas PK.")
    det = ", ".join(
        f"{lbl} {v:g}%" for lbl, v in
        (("KA", r.kadar_air), ("broken", r.broken), ("susut", r.penyusutan)) if v is not None
    )
    bk = f" · butir kuning {r.butir_kuning}" if r.butir_kuning else ""
    pesan = f"✓ Kualitas PK *{req.kode_batch}* tercatat: {det or '—'}{bk}."
    await _chat_confirm(user, pesan, "admin")
    return {"ok": True, "pesan": pesan}


class HargaPkLuarReq(BaseModel):
    kode_batch: str
    metode: str
    nilai: float | None = None
    potongan_kg: float | None = None
    potongan_alasan: str | None = None


@router.post("/actions/harga-pk-luar")
async def act_harga_pk_luar(req: HargaPkLuarReq, user: User = Depends(pengguna_aksi)) -> dict:
    """Verifikasi harga PK luar — terpisah dari kualitas, kapan saja."""
    _require(can_see_financials(user))
    if not (req.kode_batch or "").strip():
        raise HTTPException(400, "Pilih PK luar dulu.")
    if req.metode not in ("per_kg", "total"):
        raise HTTPException(400, "Pilih metode harga dulu: Total atau Per kg.")
    if req.nilai is None:
        raise HTTPException(400, "Isi nilai harga dulu.")
    from app.penggilingan.gudang2.service import verify_pk_price, Gudang2Error
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await verify_pk_price(
                db, user=u, kode=req.kode_batch, metode=req.metode, nilai=req.nilai,
                potongan_kg=req.potongan_kg,
                potongan_alasan=(req.potongan_alasan or None),
            )
        except Gudang2Error as e:
            raise _err(e, "Gagal verifikasi harga PK.")
    hpp = f" · HPP {_rp(r.hpp_per_kg)}/kg" if r.hpp_per_kg else ""
    pesan = f"✓ Harga PK *{req.kode_batch}* terverifikasi (bersih {r.berat_bersih_kg:g} kg){hpp}."
    await _chat_confirm(user, pesan, "admin")
    return {"ok": True, "pesan": pesan}


class TransferReq(BaseModel):
    kode_proses: str
    tujuan: str
    berat: float | None = None


@router.post("/actions/transfer-pk")
async def act_transfer_pk(req: TransferReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(can_transfer_pk(user))
    if not (req.kode_proses or "").strip():
        raise HTTPException(400, "Pilih proses PK dulu.")
    if req.tujuan not in ("silo_a", "silo_b", "ditumpuk"):
        raise HTTPException(400, "Pilih tujuan dulu: Silo A / Silo B / Tumpukan.")
    from app.services.transfer import create_internal_transfer, TransferError
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await create_internal_transfer(
                db, user=u, kode_proses=req.kode_proses,
                lokasi_tujuan=req.tujuan, berat=req.berat,
            )
        except TransferError as e:
            raise _err(e, "Gagal pemindahan PK.")
    jns = (r.jenis + " ") if r.jenis else ""
    pesan = (f"✓ Pemindahan PK *{r.transfer.kode_transfer}*: {jns}langsung masuk "
             f"{r.lokasi_label} Gudang 2. (Operator G2 tak perlu menerima manual.)")
    await _chat_confirm(user, pesan, "admin")
    return {"ok": True, "pesan": pesan}


# ─────────────────────── Aksi cepat: Gudang 2 (operator) ───────────────────────

class MasukkanPkReq(BaseModel):
    kode_batch: str
    tujuan: str  # silo_a / silo_b / ditumpuk


@router.post("/actions/masukkan-pk")
async def act_masukkan_pk(req: MasukkanPkReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g2_operator(user))
    if not (req.kode_batch or "").strip():
        raise HTTPException(400, "Pilih PK yang mau dimasukkan dulu.")
    if req.tujuan not in ("silo_a", "silo_b", "ditumpuk"):
        raise HTTPException(400, "Pilih tujuan dulu: Silo A / Silo B / Tumpukan.")
    from app.penggilingan.gudang2.service import masukkan_pk_luar, Gudang2Error
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await masukkan_pk_luar(db, user=u, kode=req.kode_batch, tujuan=req.tujuan)
        except Gudang2Error as e:
            raise _err(e, "Gagal memasukkan PK.")
    pesan = f"✓ PK *{req.kode_batch}* dimasukkan → {r.lokasi_label}."
    await _chat_confirm(user, pesan)
    return {"ok": True, "pesan": pesan}


class MulaiPenyosohanReq(BaseModel):
    silo: str  # A / B / AB


@router.post("/actions/mulai-penyosohan")
async def act_mulai_penyosohan(req: MulaiPenyosohanReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g2_operator(user))
    silos = {"A": ["A"], "B": ["B"], "AB": ["A", "B"]}.get((req.silo or "").upper())
    if not silos:
        raise HTTPException(400, "Pilih silo bahan dulu: Silo A / Silo B / A+B.")
    from app.penggilingan.gudang2.polishing import mulai_penyosohan, Gudang2Error
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await mulai_penyosohan(db, user=u, nama_silos=silos)
        except Gudang2Error as e:
            raise _err(e, "Gagal mulai penyosohan.")
    pesan = (f"✓ Penyosohan *{r.proc.kode_proses}* mulai — silo "
             f"{'+'.join(r.silos)} ({r.berat_awal_total:g} kg).")
    await _chat_confirm(user, pesan)
    return {"ok": True, "pesan": pesan}


class HasilPenyosohanReq(BaseModel):
    kode_proses: str
    jenis: str
    berat_kumulatif: float


@router.post("/actions/hasil-penyosohan")
async def act_hasil_penyosohan(req: HasilPenyosohanReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g2_operator(user))
    if not (req.kode_proses or "").strip():
        raise HTTPException(400, "Pilih proses penyosohan dulu.")
    if not (req.jenis or "").strip():
        raise HTTPException(400, "Pilih jenis hasil dulu.")
    from app.penggilingan.gudang2.polishing import catat_output, Gudang2Error
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await catat_output(db, user=u, kode=req.kode_proses,
                                   jenis=req.jenis, berat_kumulatif=req.berat_kumulatif)
        except Gudang2Error as e:
            raise _err(e, "Gagal catat hasil penyosohan.")
    pesan = f"✓ Hasil *{req.kode_proses}*: {r.jenis} {r.berat_kumulatif:g} kg (kumulatif)."
    await _chat_confirm(user, pesan)
    return {"ok": True, "pesan": pesan}


class SelesaiPenyosohanReq(BaseModel):
    kode_proses: str
    silo: str  # A / B
    sisa: float


@router.post("/actions/selesai-penyosohan")
async def act_selesai_penyosohan(req: SelesaiPenyosohanReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g2_operator(user))
    if not (req.kode_proses or "").strip():
        raise HTTPException(400, "Pilih proses penyosohan dulu.")
    if (req.silo or "").upper() not in ("A", "B"):
        raise HTTPException(400, "Pilih silo yang selesai dulu: A atau B.")
    from app.penggilingan.gudang2.polishing import selesai_penyosohan, Gudang2Error
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await selesai_penyosohan(db, user=u, kode=req.kode_proses,
                                         nama_silo=req.silo.upper(), sisa_kg=req.sisa)
        except Gudang2Error as e:
            raise _err(e, "Gagal menandai selesai penyosohan.")
    if r.selesai:
        ekor = " — proses SELESAI" + (
            f", rendemen {r.rendemen:.1f}%." if r.rendemen else ".")
    else:
        ekor = " (menunggu silo lain)."
    pesan = f"✓ Silo {req.silo.upper()} selesai (sisa {req.sisa:g} kg){ekor}"
    await _chat_confirm(user, pesan)
    return {"ok": True, "pesan": pesan}


# ─────────────────────────── Halaman Mini App ───────────────────────────

_HTML = """<!doctype html>
<html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Penggilingan Beras</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
 :root{--bg:var(--tg-theme-bg-color,#f4f5f7);--card:var(--tg-theme-secondary-bg-color,#fff);
   --tx:var(--tg-theme-text-color,#16181c);--mut:var(--tg-theme-hint-color,#8a8f98);
   --ac:var(--tg-theme-button-color,#2c7be5);--acx:var(--tg-theme-button-text-color,#fff);--bd:rgba(128,128,128,.18)}
 *{box-sizing:border-box}
 body{margin:0;padding:14px;font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--tx);font-size:15px;line-height:1.5}
 .top{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:2px 2px 14px}
 .hi{font-size:18px;font-weight:600} .role{font-size:12px;color:var(--mut)}
 .pill{display:inline-block;padding:2px 9px;border-radius:999px;background:var(--ac);color:var(--acx);font-size:11px;font-weight:600;text-transform:capitalize}
 .btn{border:1px solid var(--bd);background:var(--card);color:var(--ac);border-radius:10px;padding:8px 12px;font-size:13px;font-weight:600}
 .btn.pri{background:var(--ac);color:var(--acx);border-color:var(--ac)}
 .card{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:13px 15px;margin-bottom:11px}
 .ct{font-size:13px;font-weight:600;color:var(--mut);margin:0 0 7px;letter-spacing:.02em}
 .cb{white-space:pre-wrap;word-break:break-word;margin:0;font-size:14px}
 .act{display:block;width:100%;text-align:left;background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:12px 13px;margin-bottom:9px;font-size:14px;font-weight:500;color:var(--tx)}
 .tabs{display:flex;gap:5px;background:var(--card);border:1px solid var(--bd);border-radius:12px;padding:4px;margin:0 2px 14px}
 .tab{flex:1;text-align:center;padding:9px 6px;border-radius:9px;font-size:14px;font-weight:600;color:var(--mut);border:none;background:transparent}
 .tab.on{background:var(--ac);color:var(--acx)}
 .muted{color:var(--mut);text-align:center;padding:30px 0}
 .err{color:#d93025;text-align:center;padding:24px 0}
 #modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);align-items:flex-end;justify-content:center;z-index:20}
 .sheet{background:var(--bg);width:100%;max-width:520px;border-radius:16px 16px 0 0;padding:18px 16px 24px;max-height:90vh;overflow:auto}
 .sheet h3{margin:0 0 12px;font-size:16px}
 .sheet .hint{margin:-6px 0 12px;font-size:12px;color:var(--mut);line-height:1.4}
 .sheet label{font-size:12px;color:var(--mut);display:block;margin-top:6px}
 .sheet select,.sheet input{width:100%;padding:10px;margin:4px 0 6px;border:1px solid var(--bd);border-radius:9px;background:var(--card);color:var(--tx);font-size:16px}
 .row{display:flex;gap:10px;margin-top:12px} .row .btn{flex:1;text-align:center;padding:11px}
 #toast{display:none;position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:#16181c;color:#fff;padding:10px 16px;border-radius:10px;font-size:13px;z-index:30;max-width:90%;text-align:center}
</style></head>
<body>
 <div class="top">
   <div><div class="hi" id="hi">Memuat…</div><div class="role" id="ts"></div></div>
   <button class="btn" onclick="load()">↻ Segarkan</button>
 </div>
 <div class="tabs" id="tabs" style="display:none"></div>
 <div id="app"><div class="muted">Memuat data…</div></div>
 <div id="modal" onclick="if(event.target.id==='modal')closeModal()"></div>
 <div id="toast"></div>
<script>
 const tg = window.Telegram && window.Telegram.WebApp;
 if (tg){ tg.ready(); tg.expand(); }
 const H = {Authorization: "tma " + ((tg && tg.initData) || "")};
 let MENU = {};
 let DATA = null;      // {sections, menu}
 let TAB = "acts";     // acts | g1 | g2 | dash
 function esc(s){const d=document.createElement("div");d.textContent=s==null?"":s;return d.innerHTML;}
 function val(id){const e=document.getElementById(id);return e?e.value:"";}
 function toast(m){const t=document.getElementById("toast");t.textContent=m;t.style.display="block";clearTimeout(t._t);t._t=setTimeout(()=>t.style.display="none",2600);}
 async function getJSON(u){const r=await fetch(u,{headers:H});if(!r.ok){const e=await r.json().catch(()=>({}));throw (e.detail||("HTTP "+r.status));}return r.json();}
 async function post(u,b){const r=await fetch(u,{method:"POST",headers:{...H,"Content-Type":"application/json"},body:JSON.stringify(b)});const j=await r.json().catch(()=>({}));if(!r.ok)throw (j.detail||("HTTP "+r.status));return j;}
 function closeModal(){document.getElementById("modal").style.display="none";}

 async function load(){
   const app=document.getElementById("app");
   try{
     const d = await getJSON("/miniapp/dashboard");
     document.getElementById("hi").textContent="Halo, "+d.user.nama;
     document.getElementById("ts").innerHTML='<span class="pill">'+esc(d.user.role)+'</span>';
     let menu=[]; try{ menu = await getJSON("/miniapp/actions/menu"); }catch(e){}
     MENU={}; menu.forEach(a=>MENU[a.id]=a);
     DATA={sections:d.sections, menu:menu};
     buildTabs();
     render();
   }catch(err){
     document.getElementById("hi").textContent="Gagal masuk";
     document.getElementById("tabs").style.display="none";
     app.innerHTML='<div class="err">'+esc(String(err))+'</div>';
   }
 }

 // Susun tab dinamis. Admin/staff (punya aksi G1 & G2) → tab dipisah
 // 'Aksi G1' & 'Aksi G2'; operator (satu gudang) → 'Aksi Cepat' tunggal.
 function buildTabs(){
   const menu=DATA.menu;
   const hasG1=menu.some(a=>a.wh==="g1");
   const hasG2=menu.some(a=>a.wh==="g2");
   let btns=[];
   if(hasG1 && hasG2){ btns.push(["g1","🌾 Aksi G1"]); btns.push(["g2","🏭 Aksi G2"]); }
   else if(menu.length){ btns.push(["acts","⚡ Aksi Cepat"]); }
   btns.push(["dash","📊 Dashboard"]);
   const keys=btns.map(b=>b[0]);
   if(!keys.includes(TAB)) TAB=keys[0];
   const tabs=document.getElementById("tabs");
   tabs.style.display = btns.length>1 ? "flex" : "none";
   tabs.innerHTML = btns.map(b=>'<button class="tab" data-tab="'+b[0]+'" onclick="showTab(\\''+b[0]+'\\')">'+esc(b[1])+'</button>').join('');
 }

 function showTab(t){ TAB=t; render(); }

 function render(){
   const app=document.getElementById("app");
   document.querySelectorAll("#tabs .tab").forEach(b=>b.classList.toggle("on", b.dataset.tab===TAB));
   if(!DATA){ return; }
   if(TAB==="dash"){
     app.innerHTML = DATA.sections.length
       ? DATA.sections.map(s=>'<div class="card"><p class="ct">'+esc(s.icon+" "+s.title)+'</p><pre class="cb">'+esc(s.body)+'</pre></div>').join("")
       : '<div class="muted">Belum ada data.</div>';
   }else{
     const list = TAB==="acts" ? DATA.menu : DATA.menu.filter(a=>a.wh===TAB);
     app.innerHTML = list.length
       ? list.map(a=>'<button class="act" onclick="openAction(\\''+a.id+'\\')">'+esc(a.label)+'</button>').join('')
       : '<div class="muted">Tidak ada aksi cepat untuk peran Anda.</div>';
   }
 }

 function openAction(id){
   const a=MENU[id]; if(!a)return;
   let inner="";
   a.fields.forEach(f=>{
     inner+='<label>'+esc(f.label)+'</label>';
     if(f.type==="select"){
       // Auto '— pilih —' bila belum diawali opsi kosong. Field opsional TIDAK
       // dipaksa (tanpa data-choice); field wajib dipaksa pilih (tanpa default).
       const opts=(f.options.length && f.options[0][0]==="")?f.options:[["","— pilih —"]].concat(f.options);
       const dc=f.optional?"":' data-choice="1"';
       inner+='<select data-name="'+f.name+'"'+dc+' data-label="'+esc(f.label)+'">'+opts.map(o=>'<option value="'+esc(o[0])+'">'+esc(o[1])+'</option>').join('')+'</select>';
     }else if(f.type==="remote"){
       inner+='<select data-name="'+f.name+'" data-choice="1" data-label="'+esc(f.label)+'" id="rem_'+f.name+'"><option>memuat…</option></select>';
     }else{
       inner+='<input data-name="'+f.name+'" type="'+(f.type==="number"?"number":"text")+'" inputmode="'+(f.type==="number"?"decimal":"text")+'">';
     }
   });
   const m=document.getElementById("modal");
   const hint=a.hint?'<p class="hint">'+esc(a.hint)+'</p>':'';
   m.innerHTML='<div class="sheet"><h3>'+esc(a.label)+'</h3>'+hint+inner+
     '<div class="row"><button class="btn" onclick="closeModal()">Batal</button><button class="btn pri" id="ok">Simpan</button></div></div>';
   m.style.display="flex";
   a.fields.forEach(f=>{ if(f.type==="remote"){ getJSON(f.source).then(list=>{
       const s=document.getElementById("rem_"+f.name);
       const head='<option value="">'+(list.length?"— pilih —":"(tidak ada pilihan)")+'</option>';
       s.innerHTML = head + list.map(o=>'<option value="'+esc(o.value)+'">'+esc(o.label)+'</option>').join('');
     }).catch(()=>{}); }});
   document.getElementById("ok").onclick=async()=>{
     const btn=document.getElementById("ok"); btn.disabled=true;
     try{
       // Semua field pilihan WAJIB dipilih (tanpa default) — hindari salah input.
       const miss=[];
       m.querySelectorAll("select[data-choice]").forEach(el=>{ if(!el.value) miss.push(el.getAttribute("data-label")||el.getAttribute("data-name")); });
       if(miss.length){ toast("Wajib dipilih: "+miss.join(", ")); btn.disabled=false; return; }
       const body={};
       m.querySelectorAll("[data-name]").forEach(el=>{ let v=el.value; if(el.type==="number") v=(v===""?null:parseFloat(v)); body[el.getAttribute("data-name")]=v; });
       const res=await post(a.post, body);
       closeModal(); toast(res.pesan||"Berhasil ✓"); load();
     }catch(e){ toast(String(e)); btn.disabled=false; }
   };
 }
 load();
</script></body></html>"""


@router.get("", response_class=HTMLResponse)
async def launch() -> HTMLResponse:
    """Halaman Mini App (dari tombol menu bot). Login otomatis via initData."""
    return HTMLResponse(_HTML)
