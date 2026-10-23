"""API aksi Pos Produksi: identitas, dashboard, dan katalog AKSI per peran.

Dulu bernama `/miniapp` — dari masa ketika layar pencatatan memang Mini App
Telegram. Halaman dan botnya sudah dibuang (8 Sep 2026), dan sejak 14 Sep
namanya ikut dibuang: yang memanggil endpoint ini adalah Pos Produksi di
peramban (dan Meja/Gudang 2 lewat proxy), dengan sesi webapp. Alamat lama
masih dilayani sebagai alias peralihan di `main.py` sampai Tahap A rasa
native selesai.

Menu aksi ditentukan SERVER per peran, bukan disalin ke klien: menambah aksi
tak perlu layar baru, dan peran yang tak berhak tak pernah menerima bentuk
formulirnya.
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from typing import Annotated

from pydantic import BaseModel, Field

from app.services.mutu_pk import LABEL_KUALITATIF, NILAI_KUALITATIF, ATURAN_RATA_QC_PK

from app.services.angka import (Persen, PersenOpsional, Positif,
                                PositifOpsional)

from app.peran import PERAN_ADMIN_KEATAS, can_see_financials, can_transfer_pk
from app.penggilingan.gudang1.services.drying import MODE_DRYER
from app.penggilingan.gudang1.services.jeda import SEBAB_LAIN as SEBAB_LAIN_JEDA
from app.database import SessionLocal
from app.models import User
from app.web.aksi_umum import galat as _err

log = logging.getLogger("web.api")
from app.penggilingan.gudang1.services.bobot import dari_batch, dari_batches
from app.web.aksi_umum import rp as _rp, kg as _kg
from app.web.aksi_umum import wajib as _require
from app.web.deps import pengguna_aksi

router = APIRouter(prefix="/api", tags=["api"])




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


# ──────────────────────── Data acuan saat sinyal hilang ────────────────────────

#: Jenis barang yang dikenal timbang & produksi — label untuk manusia.
_LABEL_JENIS = {
    "GABAH_BASAH": "Gabah basah", "GABAH_KERING": "Gabah kering", "BERAS_PK": "Beras PK",
    "BERAS": "Beras", "BROKEN": "Broken", "MENIR": "Menir", "BEKATUL": "Bekatul", "REJECT": "Reject",
}


@router.get("/acuan")
async def acuan(user: User = Depends(pengguna_aksi)) -> dict:
    """Daftar acuan yang boleh dilihat ponsel saat sinyal hilang.

    Disimpan pindah.js di ponsel selagi jaringan ada, ditampilkan di /luring
    saat putus, di bawah baris cap waktu selebar layar. Persetujuan pemilik
    14 Sep 2026 atas usulan Tahap A — dan batasnya mutlak: HANYA yang berubah
    mingguan, NAMA saja. Pemasok & pelanggan, jenis barang & kondisi gabah,
    nama silo & pengering. Tidak ada isi silo, antrean timbang, PK belum
    transfer, stok — angka yang berubah tiap jam lebih berbahaya basi
    daripada tidak ada.
    """
    from sqlalchemy import select

    from app.database import now_local
    from app.models import Dryer, Pelanggan, Silo, Supplier, Warehouse
    from app.penggilingan.peta_jenis import PETA_KELUAR, PETA_MASUK

    async with SessionLocal() as db:
        pemasok = (await db.execute(
            select(Supplier.nama_supplier).where(Supplier.deleted_at.is_(None), Supplier.status == "aktif")
            .order_by(Supplier.nama_supplier))).scalars().all()
        pelanggan = (await db.execute(
            select(Pelanggan.nama_pelanggan).where(Pelanggan.deleted_at.is_(None), Pelanggan.status == "aktif")
            .order_by(Pelanggan.nama_pelanggan))).scalars().all()
        silo = (await db.execute(
            select(Warehouse.nama_gudang, Silo.nama_silo).join(Warehouse, Silo.warehouse_id == Warehouse.id)
            .order_by(Warehouse.id, Silo.nama_silo))).all()
        dryer = (await db.execute(
            select(Warehouse.nama_gudang, Dryer.nama).join(Warehouse, Dryer.warehouse_id == Warehouse.id)
            .where(Dryer.status != "maintenance").order_by(Warehouse.id, Dryer.nama))).all()

    def _gudang(nama: str) -> str:
        return nama.split(" - ")[0].split(" — ")[0].strip()

    jenis = [_LABEL_JENIS.get(k, k) for k in (*PETA_MASUK, *PETA_KELUAR)]
    return {
        "pukul": now_local().strftime("%H:%M"),
        "daftar": [
            {"judul": "Pemasok", "isi": list(pemasok)},
            {"judul": "Pelanggan", "isi": list(pelanggan)},
            {"judul": "Jenis barang", "isi": jenis},
            {"judul": "Silo", "isi": [f"{_gudang(g)} · {s}" for g, s in silo]},
            {"judul": "Pengering", "isi": [f"{_gudang(g)} · {d}" for g, d in dryer]},
        ],
    }


# ──────────────────────── Penanda keadaan ────────────────────────

async def _penanda() -> dict:
    """Satu penanda: APAKAH ada yang berubah — bukan apa yang berubah.

    Dipanggil tiap sepuluh detik oleh tiap perangkat yang layarnya menyala.
    Sebelum ini, denyut penyegaran mengunduh SELURUH halaman (14–26 KB) hanya
    untuk menyimpulkan "tak ada yang berubah" di hampir semua denyutnya —
    sekitar 17 MB kuota per perangkat per sif, dan operator memakai kuotanya
    sendiri.

    Sekarang yang ditanya cuma ini. Halamannya baru diambil kalau jawabannya
    berbeda dari yang terakhir dilihat.

    **Isinya dua bagian, dan yang kedua mudah terlupa.** `activity_logs`
    mencatat hampir seluruh perubahan di aplikasi ini — 67 tempat memanggil
    pencatatnya, dan pencatat itu tidak commit sendiri melainkan ikut
    transaksi pemanggilnya, jadi barisnya muncul TEPAT saat perubahannya jadi.
    Tetapi tiket timbang dibuat aplikasi TIMBANGAN, yang menulis ke basis data
    yang sama tanpa lewat catatan aktivitas ini — padahal tiket yang belum
    ditaut berdiri sebagai kartu di Antrian tunggu. Tanpa bagian kedua, truk
    yang baru masuk tak akan pernah muncul sendiri di layar.

    Yang dipakai NOMOR yang selalu naik, bukan cap waktu: jam server yang
    bergeser sedikit bisa membuat satu perubahan terlewat selamanya. Untuk
    tabel timbangan, `updated_at` ikut karena tiket DIUBAH saat timbang kedua
    — nomornya sendiri tak bergerak di situ.
    """
    from sqlalchemy import func, select, text

    from app.models import ActivityLog
    from app.web.tampilan import VERSI

    async with SessionLocal() as db:
        n = (await db.execute(select(func.max(ActivityLog.id)))).scalar() or 0
        # Cap waktunya MIKRODETIK, bukan detik. Dibulatkan ke detik, tiket
        # yang dibuat lalu ditimbang kedua pada detik yang sama menghasilkan
        # penanda yang sama — perubahan kedua hilang selamanya, tanpa galat.
        # Ketahuan di uji Postgres yang menyimpan dua langkah berturut-turut.
        t = (await db.execute(text(
            "select coalesce(max(id), 0), "
            "coalesce(cast(extract(epoch from max(updated_at)) * 1000000 as bigint), 0) "
            "from timbangan_transaksi"
        ))).first()
    # `versi` (syarat N-A-03): ponsel yang memegang berkas lama tahu dari
    # kanal yang sama, tanpa menunggu navigasi penuh.
    return {"n": f"{n}.{t[0]}.{t[1]}", "versi": VERSI}


@router.get("/keadaan")
async def keadaan(user: User = Depends(pengguna_aksi)) -> dict:
    """Jalur kedua: denyut 10 detik dari perangkat bila kanal dorong putus."""
    return await _penanda()


async def aliran_penanda(jeda: float = 2.0):
    """Kanal dorong (SSE): penanda dikirim seketika saat tersambung, lalu
    hanya ketika bergerak. Di antaranya komentar `: hidup` tiap ~15 detik
    supaya proxy Railway tidak menganggap sambungannya mati.

    Penandanya SAMA dengan /api/keadaan — satu rumus, dua kanal. Yang
    dipantau tetap basis data (bukan peristiwa dalam proses), jadi tiket yang
    ditulis aplikasi timbangan ikut terdorong.
    """
    import asyncio
    import json

    terakhir = None
    hidup = 0.0
    while True:
        p = await _penanda()
        if p != terakhir:            # n ATAU versi — versi baru pun terdorong
            terakhir = p
            hidup = 0.0
            yield "data: " + json.dumps(p) + "\n\n"
        else:
            hidup += jeda
            if hidup >= 15:
                hidup = 0.0
                yield ": hidup\n\n"
        await asyncio.sleep(jeda)


@router.get("/aliran", include_in_schema=False)
async def aliran(user: User = Depends(pengguna_aksi)):
    from fastapi.responses import StreamingResponse

    return StreamingResponse(
        aliran_penanda(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _id_jejak(user_id: int) -> int | None:
    """Id jejak yang barusan ditulis — dipakai tombol BATALKAN di kabar.

    Aksi satu-ketuk menyimpan tanpa konfirmasi, dan itu memang gunanya:
    operator memegang telepon satu tangan sambil mengarahkan truk. Yang
    ditambahkan jalan mundurnya, bukan penghalang di depannya.
    """
    from app.services.undo import id_log_terakhir

    async with SessionLocal() as db:
        return await id_log_terakhir(db, user_id)


# ─────────────────────────── Dashboard ───────────────────────────

def _clean(s: str) -> str:
    return (s or "").replace("*", "").replace("_", "")


# `_hpp_terkini` DIBUANG 28 September 2026 bersama blok "HPP beras terkini" di
# Dashboard: harga keluar dari Pos Produksi (keputusan pemilik). Dibiarkan, ia
# akan berbunyi "Belum tersedia (menunggu data lengkap)" SELAMANYA — dan blok
# yang selalu kosong mengajari orang berhenti membaca dasbornya.


@router.get("/dashboard")
async def dashboard(user: User = Depends(pengguna_aksi)) -> dict:
    """Snapshot dashboard sesuai role. Keuangan (HPP/tugas) hanya staff/admin."""
    fin = can_see_financials(user)
    from app.peran import user_wh_scope
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

    return {"user": {"nama": user.nama, "role": user.role, "see_financials": fin},
            "sections": sections}


# ─────────────────────── Aksi cepat: role helper ───────────────────────

async def _is_wh_operator(user: User, kode_fungsi: str) -> bool:
    """Admin KE ATAS selalu boleh; operator hanya bila gudang yang SEDANG
    dikerjakannya cocok.

    `default_warehouse_id` pada objek pengguna di sini adalah gudang AKTIF
    sesi ini, bukan profilnya: `akun_opsional` menimpanya dari kuki "Kerja di
    gudang" sesudah sesi basis data ditutup (operator saling menggantikan,
    pemilik 13 Sep 2026). Satu sesi satu gudang — yang di seberang ditolak
    sampai ia berpindah, supaya tak ada catatan jatuh ke gudang yang salah.

    Dulu berbunyi `if user.role == "admin"` lalu menolak apa pun yang bukan
    `"operator"` — sehingga SUPERADMIN jatuh ke penolakan dan kehilangan
    SELURUH aksi gudang. Terlihat saat pemilik membandingkan tampilan: peran
    tertinggi menampilkan 14 aksi, admin di bawahnya 30.

    Ini kali keempat pola yang sama dalam dua hari (delapan gerbang produksi,
    sembilan gerbang Kantor, penjaga akun tertinggi, dan di sini) — peran baru
    ditambahkan di puncak, gerbang lama menyebut nama peran satu per satu.
    """
    from hmu_identitas import peran as P

    if P.admin_keatas(user.role):
        return True
    if not P.operator_saja(user.role):
        return False
    from sqlalchemy import select
    from app.models import Warehouse
    async with SessionLocal() as db:
        wid = (
            await db.execute(
                select(Warehouse.id).where(Warehouse.kode_fungsi == kode_fungsi,
                                           Warehouse.aktif.is_(True))
            )
        ).scalars().first()
    return wid is not None and user.default_warehouse_id == wid


async def _is_g1_operator(user: User) -> bool:
    """Admin selalu boleh; operator hanya bila Gudang 1 yang sedang dikerjakannya."""
    return await _is_wh_operator(user, "g1")


async def _is_g2_operator(user: User) -> bool:
    """Admin selalu boleh; operator hanya bila Gudang 2 yang sedang dikerjakannya."""
    return await _is_wh_operator(user, "g2")


async def _pilihan_tujuan_gabah(kondisi: str) -> list[list[str]]:
    """Daftar tujuan yang sah untuk gabah, mesinnya disebut satu per satu.

    Mesin tidak digabung jadi satu pilihan "Dryer" lalu ditanya lagi mesin
    mana: itu dua ketukan untuk satu keputusan, dan yang menekannya sedang
    berdiri memegang layar dengan satu tangan.
    """
    from app.penggilingan.gudang1.services.drying import dryers_g1, isi_dryer
    from app.penggilingan.peta_jenis import intake_dari_jenis

    jenis = "GABAH_BASAH" if kondisi == "basah" else "GABAH_KERING"
    sah = intake_dari_jenis(jenis).tujuan_pilihan
    opsi: list[list[str]] = [["", "— belum ditentukan —"]]
    if "dryer" in sah:
        async with SessionLocal() as db:
            mesin = await dryers_g1(db)
            # ISI mesin ikut disebut. Larangan mencampur gabah basah dengan
            # gabah kering ditegakkan di `masuk_dryer`, tetapi penolakan di
            # sana datang SESUDAH batch-nya tercatat. Yang menekan layar perlu
            # melihat isinya sebelum memilih — dan isi itu tetap menghalangi
            # walau pengeringan & pendinginannya sudah selesai, selama
            # gabahnya belum keluar ke silo.
            #
            # Kalimatnya sengaja tidak bergantung pada kondisi gabah yang
            # masuk: daftar ini dibangun dua kali (basah & kering) lalu
            # digabung, dan label yang berbeda akan memunculkan mesin yang
            # sama dua kali.
            isi = {d.id: await isi_dryer(db, d.id) for d in mesin}
        for d in mesin:
            mati = "" if d.status == "aktif" else f" ({d.status})"
            ada = isi.get(d.id)
            berisi = (f" — berisi gabah {ada[0]} {ada[1]:,.0f} kg".replace(",", ".")
                      if ada else " — kosong")
            opsi.append([f"dryer:{d.id}", f"{d.nama}{mati}{berisi}"])
    if "silo" in sah:
        from app.penggilingan.gudang1.services.silo import silos_g1
        async with SessionLocal() as db:
            for si in await silos_g1(db):
                opsi.append([f"silo:{si.id}", f"{si.nama_silo} (gabah kering)"])
    if "tumpuk" in sah:
        opsi.append(["tumpuk", f"Ditumpuk di lantai (gabah {kondisi})"])
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


#: Aksi yang lenyap begitu fitur mutu dimatikan di Pengaturan.
AKSI_MUTU = {"qc_giling", "qc_pk_luar", "qc_gabah_basah", "qc_gabah_kering"}


async def _wajib_mutu() -> None:
    """Tolak aksi mutu saat fiturnya padam.

    Menyembunyikan tombolnya saja tidak cukup: alamatnya bisa diketik, dan
    lembar yang masih tersimpan di layar orang lain masih bisa mengirim.
    Penjagaan yang hanya ada di tampilan bukan penjagaan.
    """
    from app.services.setelan import fitur_mutu

    async with SessionLocal() as db:
        if not await fitur_mutu(db):
            raise HTTPException(
                400, "Pencatatan mutu sedang dimatikan di Pengaturan.")


@router.get("/actions/menu")
async def actions_menu(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Daftar aksi cepat + spesifikasi field, ditentukan SERVER per role."""
    from hmu_identitas import peran as P

    fin = can_see_financials(user)
    g1 = await _is_g1_operator(user)
    g2 = await _is_g2_operator(user)
    #: Jaring pengaman Super Admin untuk `pindah_tumpukan_silo` (keputusan
    #: pemilik 5 Oktober 2026) — lihat catatan panjang di blok itu, di bawah.
    super_ = P.super_saja(user.role)
    KONDISI = [["", "— belum ditentukan —"], ["basah", "Basah (→ PK KS)"],
               ["kering", "Kering (→ PK KL)"]]
    METODE = [["", "— belum ditentukan —"], ["total", "Total (Rp)"], ["per_kg", "Per kg (Rp)"]]
    JENIS_HASIL = [["", "— belum ditentukan —"],
                   ["premium", "Beras Premium"], ["medsuper", "Beras Medium Super"],
                   ["medium", "Beras Medium"], ["sayur", "Beras Sayur"],
                   ["beras_b", "Beras B (olah ulang)"], ["menir", "Menir"],
                   ["broken", "Broken"], ["bekatul", "Bekatul"], ["reject", "Reject"]]
    actions: list[dict] = []
    # Setelan dibaca sekali per permintaan menu — daftar sebab dan target
    # bawaan sama-sama bisa diubah admin, dan spesifikasi aksi yang
    # membekukannya akan menampilkan pilihan yang sudah dibuang. Dibaca untuk
    # KEDUA gudang: sejak 12 September 2026 penyosohan pun punya sebab
    # berhenti, dan operator Gudang 2 yang tak punya blok G1 dulu menemukan
    # SEBAB_AKTIF tak pernah terisi.
    SEBAB_AKTIF, TARGET_BAWAAN = {}, None
    if g1 or g2:
        from app.services.setelan import sebab_jeda, target_kadar_air

        async with SessionLocal() as db:
            SEBAB_AKTIF = await sebab_jeda(db)
            TARGET_BAWAAN = await target_kadar_air(db)
    if g1:
        # Dibangkitkan per permintaan: mesin bisa bertambah lewat Pengaturan,
        # dan daftar tujuan yang ditulis tetap akan diam-diam ketinggalan.
        TUJUAN_BASAH = await _pilihan_tujuan_gabah("basah")
        TUJUAN_KERING = await _pilihan_tujuan_gabah("kering")
        # Urut sesuai alur kerja operator Gudang 1: terima → keringkan →
        # dinginkan/pindah silo → giling.
        # ATURAN PENAMAAN — label menyebut ISI DAFTARNYA, bukan nama bendanya.
        #
        # "Mesin pengering" menjanjikan seluruh mesin, padahal daftarnya hanya
        # berisi mesin yang ADA GABAHNYA (sengaja: menawarkan mesin kosong
        # cuma menghasilkan penolakan setelah orang memilihnya). Pemilik
        # membacanya sebagai "pabrik ini tak punya mesin pengering" dan
        # bertanya mengapa alatnya belum ada. Daftar yang tersaring HARUS
        # menyebut saringannya: "Mesin yang ada gabahnya", "Lot yang sedang
        # dikeringkan", "Giling yang belum dinilai mutunya".
        #
        # `kosong` melengkapinya untuk keadaan nol — lihat aksi_umum. Tanpa
        # keduanya, aksi.js menebak kalimat dari nama field, dan tebakan itu
        # bisa keliru berat.
        actions += [
            {"id": "gabah_masuk", "label": "🌾 Gabah masuk",
             "post": "/api/actions/gabah-masuk",
             "hint": "Pilih tiket timbang yang masih aktif — supplier, bobot, & plat "
                     "otomatis dari timbangan (tak perlu diketik ulang). "
                     "Partai kecil ikut di sini: satu kode timbang, berapa pun "
                     "kali ditimbang.",
             "fields": [
                 {"name": "timbangan_transaksi_id", "label": "Tiket timbang gabah yang masih aktif",
                  "type": "remote", "source": "/api/actions/timbang-masuk-aktif",
                  "kosong": "Tidak ada tiket timbang gabah yang aktif 7 hari terakhir. Gabah dicatat dari tiket timbang — bukan diketik manual."},
                 {"name": "tujuan", "label": "Tujuan (wajib pilih)", "type": "remote",
                  "induk": "timbangan_transaksi_id", "source": "/api/actions/tujuan-gabah",
                  "kosong": "Belum ada tujuan yang tersedia untuk tiket ini."},
             ]},
            *[
                {
                    "id": f"qc_gabah_{kondisi}",
                    "label": f"🔬 QC gabah {kondisi}",
                    "post": "/api/actions/qc-gabah/" + kondisi,
                    "hint": "Satu simpan adalah satu pemeriksaan lengkap. Catat 5 kali untuk truk ini; "
                            "setiap catatan memakai dua pembacaan kadar air. Kadar air truk adalah "
                            "rata-rata 10 pembacaan dari kelima catatan."
                            + (" Jika tidak ada Lamur, isi jumlah sak 0." if kondisi == "basah" else ""),
                    "fields": ([{
                        "name": "kode_batch", "label": f"Truk gabah {kondisi} yang belum di-QC",
                        "type": "remote", "source": f"/api/actions/gabah-qc/{kondisi}",
                        "kosong": f"Tidak ada truk gabah {kondisi} yang menunggu QC.",
                    }] + ([
                        {"name": "lamur", "label": "Ada Lamur?", "type": "select",
                         "options": [["iya", "Iya"], ["tidak", "Tidak"]], "wajib": True},
                        {"name": "jumlah_sak_lamur", "label": "Jumlah sak yang Lamur", "type": "number", "wajib": True},
                    ] if kondisi == "basah" else []) + [
                        {"name": "biji_hijau", "label": "Biji hijau", "type": "select", "wajib": True,
                         "options": [["hampir_tidak_ada", "Hampir tidak ada"], ["sedikit", "Sedikit"],
                                     ["sedang", "Sedang"], ["banyak", "Banyak"]]},
                        {"name": "densiti", "label": "Densiti gabah", "type": "select", "wajib": True,
                         "options": [["padat", "Padat · sedikit gabah hampa"], ["sedang", "Sedang"],
                                     ["empuk", "Empuk · banyak gabah hampa"]]},
                    ] + [
                        {"name": "kadar_air_1", "label": "Pembacaan kadar air 1 (%)", "type": "number", "wajib": True},
                        {"name": "kadar_air_2", "label": "Pembacaan kadar air 2 (%)", "type": "number", "wajib": True},
                    ])
                }
                for kondisi in ("basah", "kering")
            ],
            {"id": "qc_gabah_tutup", "label": "🔒 Tutup proses QC gabah",
             "post": "/api/actions/tutup-qc-gabah", "pratinjau_qc": True,
             "hint": "Tutup setelah minimal satu catatan QC tersimpan. Setelah ditutup, data QC truk ini tidak bisa ditambah lagi.",
             "fields": [{"name": "kode_batch", "label": "Proses QC yang belum lengkap",
                         "type": "remote", "source": "/api/actions/gabah-qc-bisa-ditutup",
                         "kosong": "Belum ada proses QC yang bisa ditutup."},
                        {"name": "alasan", "label": "Alasan menutup sebelum lima pemeriksaan",
                         "type": "text", "wajib": True}]},
            {"id": "pindah_tumpukan", "label": "📦 Tempatkan gabah",
             "post": "/api/actions/pindah-tumpukan",
             "hint": "Gabah yang belum ada di dryer maupun silo — yang sedang "
                     "menumpuk, dan yang penempatannya gagal. Gabah basah "
                     "belum boleh ke silo.",
             "fields": [
                 {"name": "kode_batch", "label": "Gabah yang menunggu tempat",
                  "type": "remote", "source": "/api/actions/tumpukan",
                  "kosong": "Tidak ada gabah yang menunggu tempat. Semua gabah masuk sudah berada di dryer atau silo."},
                 {"name": "tujuan", "label": "Tujuan (wajib pilih)", "type": "select",
                  "options": TUJUAN_BASAH + [o for o in TUJUAN_KERING
                                             if o not in TUJUAN_BASAH]},
             ]},
            {"id": "mulai_pengeringan", "label": "🔥 Mulai pengeringan",
             "post": "/api/actions/mulai-pengeringan",
             "hint": "Gabungkan SEMUA gabah yang menunggu di mesin itu menjadi 1 "
                     "pengeringan (PGR-…). Gabah di mesin lain tidak ikut. "
                     "Lot belum terbentuk di sini — lot lahir saat mulai giling.",
             "fields": [
                 {"name": "dryer_id", "label": "Mesin yang ada gabahnya", "type": "remote",
                  "source": "/api/actions/dryer-menunggu",
                  "kosong": "Tidak ada mesin pengering yang sedang berisi gabah. Mesinnya ada — isinya yang belum. Catat gabah masuk, lalu tempatkan ke mesin pengering."},
                 {"name": "target_kadar_air",
                  "label": f"Target kadar air (%) — biasanya {TARGET_BAWAAN:g}",
                  "type": "number", "wajib": True},
                 # Mode disebutkan di LABEL mesinnya juga ("· pakai mode 25T"),
                 # karena di situlah tonasenya diketahui. Menaruh saran di
                 # tempat lain berarti operator harus mengingat angka dari
                 # baris sebelumnya sambil memilih.
                 {"name": "mode_dryer", "label": "Mode yang disetel di mesin",
                  "type": "select",
                  "options": [["", "— pilih —"]] + [[m, m] for m in MODE_DRYER]},
             ],
             # Satu-satunya aksi yang menyalakan MESIN, dan satu-satunya yang
             # dua isiannya tidak dikerjakan oleh aplikasi ini: target kadar
             # air dan mode disetel di panel dryer, dengan tangan. Yang
             # dicatat di sini hanya salinannya — dan salinan yang berbeda dari
             # setelan aslinya adalah kebohongan yang baru ketahuan berjam-jam
             # kemudian, saat gabahnya terlanjur kelewat kering atau masih
             # basah.
             #
             # Teksnya mengulang ANGKA YANG BARU DIKETIK, bukan bertanya
             # "yakin?". "Yakin?" tidak menanyakan apa pun; ia cuma melatih
             # orang menekan Ya. Angka yang diulang bisa dibandingkan dengan
             # panel mesin yang sedang berdiri di depannya.
             "konfirmasi": {
                 "judul": "Sudah disetel di mesinnya?",
                 "teks": "Periksa panel {dryer_id} sekarang: mode {mode_dryer}, "
                         "dikeringkan sampai {target_kadar_air}%. "
                         "Aplikasi ini hanya mencatat — yang menentukan hasilnya "
                         "adalah setelan di mesin.",
                 "ya": "Sudah disetel — nyalakan",
             }},
            {"id": "kadar_air", "label": "💧 Perbarui kadar air",
             "post": "/api/actions/kadar-air",
             "hint": "Beberapa titik dengan alat tes — yang dipakai rata-ratanya. "
                     "Satu titik saja bisa kebetulan mengenai bagian paling basah. "
                     "Angka mesin dicatat terpisah, bukan dirata-ratakan bersamanya.",
             "fields": [
                 {"name": "kode_lot", "label": "Pengeringan yang sedang berjalan", "type": "remote",
                  "source": "/api/actions/drying-active",
                  "kosong": "Tidak ada pengeringan yang sedang berjalan."},
                 # SATU kotak, lalu tombol yang menambah kotak — bukan empat
                 # kotak yang selalu tergambar. Berapa titik yang diukur
                 # berbeda tiap kali: tumpukan kecil cukup satu tusukan, yang
                 # besar perlu empat. Borang yang sebagian besarnya kosong
                 # terbaca seperti borang yang belum selesai diisi.
                 #
                 # `maks` 4 karena hanya empat titik yang punya kolom
                 # tersimpan. Menaikkannya menuntut migrasi — jangan naikkan
                 # angka ini sendirian, atau titik kelima hilang diam-diam.
                 {"name": "tes", "label": "Alat tes — kadar air tiap titik (%)",
                  "type": "ulang", "maks": 4, "tambah": "+ Tambah titik tes",
                  "wajib": True},
                 {"name": "indikator", "label": "Terbaca di mesin dryer (%)",
                  "type": "number", "optional": True},
                 # Target TIDAK lagi jadi medan di sini. Ia dulu menumpang
                 # sebagai isian sampingan di borang ini, dengan alasan yang
                 # masuk akal: operator menilai kembali "sudah cukup atau
                 # belum" justru saat melihat angkanya.
                 #
                 # Tetapi bobot keduanya tidak sama. Mencatat kadar air
                 # MELAPORKAN apa yang terbaca; mengubah target MENETAPKAN
                 # kapan mesin dimatikan, dan itu ikut menentukan gabah ini
                 # dijual sebagai apa. Dua hal sebesar itu berbagi satu tombol
                 # Simpan berarti yang berat ikut tertekan bersama yang
                 # ringan — dan tak ada satu pun titik di mana orangnya
                 # ditanya apakah ia sungguh bermaksud menggesernya.
                 #
                 # Jadi ia jadi TOMBOL ke lembarnya sendiri, yang menuntut
                 # konfirmasi. Tetap satu ketukan dari sini, jadi penilaian
                 # tak terpisah dari angka yang mendasarinya — tapi tak lagi
                 # bisa berubah tanpa disengaja.
                 {"name": "buka_ubah_target", "type": "tombol_aksi",
                  "aksi": "ubah_target", "label": "Ubah target kadar air",
                  "bawa": "kode_lot"},
             ]},
            {"id": "ubah_target", "label": "🎯 Ubah target kadar air",
             "post": "/api/actions/ubah-target",
             "hint": "Garis selesai pengeringan. Menggesernya mengubah kapan "
                     "mesin dimatikan — dan itu ikut menentukan gabah ini "
                     "dijual sebagai apa. Perubahannya tercatat berikut angka "
                     "lamanya.",
             "fields": [
                 {"name": "kode_lot", "label": "Pengeringan yang sedang berjalan",
                  "type": "remote", "source": "/api/actions/drying-active",
                  "kosong": "Tidak ada pengeringan yang sedang berjalan."},
                 {"name": "target", "label": "Target kadar air baru (%)",
                  "type": "number", "wajib": True},
             ],
             # Angkanya diulang, bukan ditanya "yakin?". "Yakin?" tak
             # menanyakan apa pun — ia cuma melatih orang menekan Ya. Yang
             # berguna adalah menyebut kembali angka yang baru diketik,
             # berikut akibatnya: mesin akan dimatikan di situ.
             "konfirmasi": {
                 "judul": "Geser garis selesainya?",
                 "teks": "Pengeringan {kode_lot} akan dihentikan di {target}%. "
                         "Angka ini yang menentukan kapan mesin dimatikan, dan "
                         "ikut menentukan gabahnya dijual sebagai apa.",
                 "ya": "Ya, ubah targetnya",
             }},
            {"id": "selesai_pengeringan", "label": "🌡️ Selesai pengeringan",
             "post": "/api/actions/selesai-pengeringan",
             "hint": "Isikan kadar air yang TERTERA DI MESIN saat dimatikan — "
                     "angka itu tak bisa dicari lagi setelah gabahnya pindah. "
                     "Lalu pengeringan masuk fase pendinginan otomatis (gabah "
                     "tetap di mesin).",
             "fields": [
                 {"name": "kode_lot", "label": "Pengeringan yang sedang berjalan", "type": "remote",
                  "source": "/api/actions/drying-active",
                  "kosong": "Tidak ada pengeringan yang sedang berjalan."},
                 # WAJIB. Kadar air akhir satu-satunya jawaban atas "kenapa
                 # pengeringan ini dihentikan di sini", dan satu-satunya yang
                 # menghubungkan lama pengeringan dengan hasilnya. Sebelum ini
                 # ia hanya bisa masuk lewat aksi TERPISAH selama proses
                 # berjalan — jadi lot yang tak sekali pun diperbarui selesai
                 # tanpa satu angka pun, tanpa satu layar pun memberitahu.
                 {"name": "kadar_air", "label": "Kadar air di mesin (%)",
                  "type": "number", "wajib": True},
             ]},
            {"id": "mulai_pendinginan_ulang", "label": "❄️ Dinginkan lagi",
             "post": "/api/actions/mulai-pendinginan-ulang",
             "hint": "Mulai pendinginan ulang. Gabah belum boleh dipindah ke silo sampai dinyatakan dingin lagi.",
             "konfirmasi": {"judul": "Mulai pendinginan ulang?",
                 "teks": "{kode_lot}: mulai pendinginan lagi. Status siap pindah ke silo dicabut sampai operator menyatakan gabah sudah dingin.",
                 "ya": "Mulai pendinginan ulang"},
             "fields": [{"name": "kode_lot", "label": "Lot yang sudah dinyatakan dingin",
                 "type": "remote", "source": "/api/actions/drying-done"}]},
            {"id": "selesai_pendinginan", "label": "❄️ Pendinginan selesai",
             "post": "/api/actions/selesai-pendinginan",
             "hint": "Nyatakan gabah sudah dingin & mesin bebas dipakai lagi — gabah "
                     "boleh tetap di dalamnya menunggu silo kosong. Dari sinilah "
                     "lama mesin menganggur dihitung.",
             "fields": [
                 {"name": "kode_lot", "label": "Pengeringan yang sedang didinginkan", "type": "remote",
                  "source": "/api/actions/cooling-active",
                  "kosong": "Tidak ada pengeringan yang sedang didinginkan."},
             ]},
            {"id": "pindah_silo", "label": "🏗️ Pindah dari mesin pengering ke silo",
             "post": "/api/actions/pindah-silo",
             "hint": "Hanya pengeringan yang sudah dinyatakan selesai pendinginan.", "fields": [
                 {"name": "kode_lot", "label": "Pengeringan yang sudah selesai didinginkan", "type": "remote",
                  "source": "/api/actions/drying-done",
                  "kosong": "Tidak ada pengeringan yang sudah selesai didinginkan. Selesaikan pendinginan dulu sebelum memindahkannya ke silo."},
                 {"name": "silo", "label": "Silo tujuan (wajib pilih)",
                  "type": "remote", "source": "/api/actions/silo-g1",
                  "kosong": "Tidak ada silo gabah kering. Tambahkan silo di Pengaturan → Alat."},
             ]},
            # BEBERAPA silo boleh dicentang sekaligus, dan hasilnya TETAP satu
            # lot — keputusan pemilik 24 September 2026 ("sering", dan
            # "hasilnya 1 lot"). Karena itu `remote_banyak`, bukan daftar
            # pilihan tunggal, dan bukan pula tupel tertulis-tangan A/B/AB
            # seperti penyosohan: silo Gudang 1 lebih dari dua dan bisa
            # bertambah lewat Pengaturan → Alat. Daftarnya dari master.
            {"id": "mulai_giling", "label": "⚙️ Mulai giling",
             "post": "/api/actions/mulai-giling",
             "hint": "Bentuk 1 LOT (LOT-…) dari SELURUH isi silo yang dicentang "
                     "— boleh beberapa silo sekaligus, dan semuanya jadi SATU "
                     "lot dengan satu rendemen. Di sinilah lot terbentuk.",
             "fields": [
                 {"name": "silo", "label": "Silo berisi gabah kering (boleh lebih dari satu)",
                  "type": "remote_banyak",
                  "source": "/api/actions/silo-siap-giling",
                  "kosong": "Tidak ada silo berisi gabah kering yang siap digiling."},
             ]},
            {"id": "hasil_giling", "label": "📈 Perbarui hasil giling",
             "post": "/api/actions/hasil-giling", "fields": [
                 {"name": "kode_proses", "label": "Giling yang sedang berjalan", "type": "remote",
                  "source": "/api/actions/milling-active",
                  "kosong": "Tidak ada proses giling yang sedang berjalan."},
                 {"name": "berat_kumulatif", "label": "PK kumulatif (kg)", "type": "number"},
             ]},
            # Hasil akhir WAJIB di sini. Dulu aksi ini hanya menutup prosesnya,
            # jadi giling bisa berakhir tanpa satu pun angka hasil — PK-nya ada
            # di lantai, tak ada yang tahu berapa, dan lotnya jatuh dari layar
            # Stok. Yang ditolak penutupannya, bukan pencatatannya: prosesnya
            # tak disentuh sampai angkanya ada, jadi kartunya tetap di Sedang
            # berjalan sampai dilengkapi.
            {"id": "selesai_giling", "label": "🏁 Selesai giling",
             "hint": "Catat sisa setiap silo melalui Bebaskan silo terlebih dahulu. "
                     "Isi 0 hanya jika benar-benar kosong. Penyelesaian tidak mengosongkan silo.",
             "post": "/api/actions/selesai-giling", "pratinjau_proses": "giling", "fields": [
                 {"name": "kode_proses", "label": "Proses giling", "type": "remote",
                  "source": "/api/actions/milling-active",
                  "kosong": "Tidak ada proses giling yang sedang berjalan."},
                 {"name": "berat_akhir", "label": "Hasil akhir PK (kg)",
                  "type": "number"},
             ]},
            # ── Bebaskan silo (boleh sebagian) — keputusan pemilik 5 Oktober
            #    2026 ──
            #
            # "silo yang kosong langsung diisi gabah lagi walau tidak langsung
            # diproses." Giling dari beberapa silo sering tak menghabiskan
            # semuanya bersamaan — pintu ini membebaskan SATU silo supaya
            # bisa diisi gabah baru, TANPA menutup prosesnya: yang menutup
            # tetap "Selesai giling", di sanalah hasil akhir & pagar
            # rendemen berdiri. Sebangun "Selesai penyosohan" Gudang 2.
            {"id": "tutup_silo_giling", "label": "📤 Bebaskan silo (boleh sebagian)",
             "hint": "Mesin lanjut dari silo lain — proses TIDAK ditutup. "
                     "Isi 0 jika silo sudah kosong. "
                     "Hanya silo dengan sisa 0 kg yang kosong dan siap diisi ulang; "
                     "gabah itu tak akan tercampur ke lot yang sedang digiling.",
             "post": "/api/actions/tutup-silo-giling", "pratinjau_silo": "giling", "fields": [
                 {"name": "kode_proses", "label": "Proses giling", "type": "remote",
                  "source": "/api/actions/milling-active",
                  "kosong": "Tidak ada proses giling yang sedang berjalan."},
                 # Silo milik PROSES yang dipilih di atasnya — `induk`, sama
                 # polanya dengan "Selesai penyosohan": borang yang dulu
                 # menawarkan silo mati A/B lepas dari prosesnya menjawab 400
                 # yang tak masuk akal bagi orang yang baru saja memilih
                 # prosesnya (keluhan pemilik 24 September 2026 07:14, sisi
                 # Gudang 2 — pola yang sama dihindari di sini sejak awal).
                 {"name": "silo", "label": "Silo yang dibebaskan", "type": "remote",
                  "induk": "kode_proses", "source": "/api/actions/silo-giling-terbuka",
                  "kosong": "Semua silo proses ini sudah ditandai bebas."},
                 {"name": "sisa", "label": "Sisa berat di silo (kg)",
                  "type": "number", "wajib": True},
             ]},
            # ── Tambah silo ke giling yang berjalan — mix bahan ──
            #
            # Laporan lapangan 7 Oktober 2026: "jika awalnya hanya
            # menggunakan 1 silo, tidak bisa menambahkan silo lainnya
            # sebagai sumber bahan baku. pada prakteknya di tengah-tengah
            # proses, silo lainnya juga dipergunakan untuk mix bahan baku
            # jika dibutuhkan." `start_milling` menerima beberapa silo,
            # tetapi hanya saat MULAI — pintu ini membuka jalan mid-proses.
            {"id": "tambah_silo_giling", "label": "➕ Tambah silo (mix bahan)",
             "hint": "Silo lain ikut jadi bahan proses ini — harus silo yang "
                     "belum dipakai proses lain, dan sepemilik dengan bahan "
                     "yang sudah berjalan.",
             "post": "/api/actions/tambah-silo-giling", "fields": [
                 {"name": "kode_proses", "label": "Proses giling", "type": "remote",
                  "source": "/api/actions/milling-active",
                  "kosong": "Tidak ada proses giling yang sedang berjalan."},
                 {"name": "silo", "label": "Silo yang ditambahkan", "type": "remote",
                  "induk": "kode_proses", "source": "/api/actions/silo-g1-tambah",
                  "kosong": "Tidak ada silo lain yang bisa ditambahkan."},
             ]},
            # ── Berhenti sementara ──
            # Prosesnya TIDAK ditutup: bahan, target, dan catatannya tetap.
            # Tanpa aksi ini, operator yang mesinnya rusak hanya punya dua
            # pilihan yang sama-sama merusak catatan — membiarkannya
            # "berjalan" padahal mati, atau menutupnya lalu memulai proses
            # baru, yang membuat satu muatan terhitung dua kali.
            {"id": "hentikan_proses", "label": "⏸️ Hentikan sementara",
             "post": "/api/actions/hentikan-proses",
             "hint": "Mesin rusak, listrik padam, jam kerja habis. Prosesnya tidak "
                     "ditutup — bisa dilanjutkan nanti atau besok, dan jam "
                     "tertahannya dihitung terpisah dari jam berjalan.",
             "fields": [
                 {"name": "proses", "label": "Proses yang sedang berjalan", "type": "remote",
                  "source": "/api/actions/proses-berjalan",
                  "kosong": "Tidak ada pengeringan atau giling yang sedang berjalan."},
                 {"name": "sebab", "label": "Sebab berhenti", "type": "select",
                  # Dari setelan, bukan dari konstanta: daftar sebab memang
                  # bertambah di lapangan, dan yang ditambahkan admin harus
                  # langsung muncul di sini tanpa menunggu kode berubah.
                  "options": [["", "— pilih —"]]
                             + [[s, s] for s in sorted(
                                 set(SEBAB_AKTIF["pengeringan"])
                                 | set(SEBAB_AKTIF["giling"]))]
                             + [[SEBAB_LAIN_JEDA, "Lainnya — tulis sendiri"]]},
                 # Daftar sebab tak akan pernah lengkap, dan daftar yang tak
                 # lengkap memaksa orang memilih yang paling mirip — lalu
                 # angkanya berbohong dengan rapi.
                 {"name": "sebab_lain", "label": "Bila 'Lainnya': tulis sebabnya",
                  "type": "text", "optional": True},
             ]},
            {"id": "lanjutkan_proses", "label": "▶️ Lanjutkan proses",
             "post": "/api/actions/lanjutkan-proses",
             "hint": "Mesin jalan lagi. Lama tertahannya tercatat berikut sebabnya.",
             "fields": [
                 {"name": "proses", "label": "Proses yang sedang berhenti", "type": "remote",
                  "source": "/api/actions/proses-berhenti",
                  "kosong": "Tidak ada proses yang sedang berhenti."},
             ]},
            # ── "Kirim ke Gudang 2" — LANGKAH 3, dan tangannya Gudang 1 ──
            #
            # Keputusan pemilik 27 September 2026, menjawab pertanyaan yang
            # ditinggalkan QA sebagai skenario B1 ("di lapangan siapa yang
            # sebenarnya mengangkat karungnya?"): "gudang 1 yang mengirim",
            # "jika sudah disetujui", "jadi gudang 1 mulai proses kirim".
            #
            # Sehari sebelumnya tombol ini sempat berpindah ke Gudang 2, dengan
            # alasan yang masih berlaku dan sekarang justru menguatkan
            # penempatannya di sini: yang mencatat "berat yang dimuat" harus
            # orang yang melihat karungnya naik. Jawaban pemilik menyebut
            # orang itu Gudang 1. Jadi yang berubah bukan aturannya melainkan
            # keterangan lapangannya — dan aturannya tetap SATU TANGAN. Kalau
            # keduanya bisa menekan, cepat atau lambat ada hari di mana yang
            # satu mengetik angka atas muatan yang diangkat yang lain, dan
            # selisih yang muncul kemudian tak punya orang untuk ditanya.
            #
            # Ia TIDAK melebarkan `can_transfer_pk`: yang memberi izin adalah
            # BARIS PERMINTAANNYA, yang sudah disetujui Admin. Operator Gudang
            # 1 tetap tak bisa memindahkan apa pun atas kehendak sendiri.
            #
            # Gudang 2 yang meminta tetap DIBERI TAHU — kartunya di Transit
            # layarnya, tanpa tombol: ia menunggu barang, bukan mengerjakan
            # sesuatu.
            {"id": "kirim_permintaan_pk", "label": "🚚 Kirim PK ke Gudang 2",
             "post": "/api/actions/kirim-permintaan-pk",
             "hint": "Catat yang BENAR-BENAR dimuat. Barangnya berpindah "
                     "sekarang juga, dan Admin yang menutup catatannya.",
             "fields": [
                 {"name": "permintaan", "label": "Permintaan yang mana",
                  "type": "remote", "source": "/api/actions/permintaan-disetujui",
                  "kosong": "Tidak ada permintaan yang sudah disetujui Admin."},
                 {"name": "berat", "label": "Berat yang dimuat (kg)",
                  "type": "number", "wajib": True},
             ]},
        ]
    if g2 and (not fin or super_):
        # ⚠ Pindah tumpukan → silo bukan pekerjaan Admin (keputusan pemilik
        # 4 Oktober 2026) — gerbang yang sama bentuknya dengan `minta_pk_g1`
        # di bawah: Admin bisa memindahkan PK lewat jalur lain, dan tombol
        # ini di tangannya cuma pintu kedua ke pekerjaan yang sama. Spesifikasi
        # ini DIPISAH dari blok `g2` di bawah justru supaya Admin TIDAK
        # menerimanya sama sekali — termasuk lewat deep-link `?buka=`, bukan
        # cuma lewat kartu/katalog yang memang sudah tak menawarkannya.
        #
        # ⚠⚠ Super Admin DIKECUALIKAN dari "Admin" di atas sejak 5 Oktober
        # 2026: kartu PK di layar Stok kini menawarkan tombol "Masukkan ke
        # silo" langsung dari kartunya (keputusan pemilik — operator memilih
        # bahan dari situ, bukan dari Antrian tunggu), dan tombol Stok itu
        # dipegang `view in (POLESAN, SUPER)`. Tanpa `super_` di sini, Super
        # Admin melihat tombolnya lalu menekannya ke MENU yang tak pernah
        # memuat aksinya — tombol yang tak melakukan apa-apa, lebih buruk
        # daripada tombol yang tak ada. `fin` tetap menolak Admin BIASA:
        # `can_see_financials` tak membedakan Admin dari Super Admin, jadi
        # yang menyempitkannya kembali ke Super Admin saja adalah `super_`.
        actions += [
            {"id": "pindah_tumpukan_silo", "label": "📤 Pindah tumpukan ke silo",
             "post": "/api/actions/pindah-tumpukan-silo",
             "hint": "Boleh sebagian — sisanya tetap di tumpukan. KOSONGKAN kotak "
                     "beratnya untuk memindahkan SELURUH sisa tumpukan; tak perlu "
                     "mengetik ulang angka dari layar. Silo yang sedang dipoles "
                     "boleh diisi lagi; yang ditambahkan ikut dihitung sebagai "
                     "bahan proses itu.",
             "fields": [
                 {"name": "tumpukan", "label": "PK di tumpukan", "type": "remote",
                  "source": "/api/actions/tumpukan-sisa",
                  "kosong": "Tumpukan kosong — tak ada yang perlu dipindah."},
                 # Tanpa "Tumpukan": PK ini memang sedang DIPINDAH dari
                 # tumpukan. Daftarnya tetap dari master.
                 {"name": "silo", "label": "Silo tujuan (wajib pilih)", "type": "remote",
                  "source": "/api/actions/silo-g2", "induk": "tumpukan",
                  "kosong": "Belum ada silo Gudang 2. Tambahkan di Pengaturan → Alat."},
                 # ⭐ BOLEH DIKOSONGKAN = SELURUH SISANYA, dan itu yang
                 # menghapus seluruh kelas masalahnya, bukan menggesernya satu
                 # desimal. Pemindahan terakhir adalah satu-satunya yang
                 # menuntut operator mengetik angka PERSIS dari layar — dan
                 # angka di layar selalu hasil pembulatan. Yang tak perlu
                 # diketik tak bisa salah ketik.
                 #
                 # Layanannya memang sudah menerima `berat=None` sejak lama
                 # ("`berat` None = pindah semua"); yang tak pernah ada cuma
                 # tawarannya di layar.
                 # ⚠ Keterangannya di `hint` aksi, BUKAN di medan ini:
                 # `aksi.js` tak mengenal keterangan per-medan, dan kunci yang
                 # tak dikenalnya hilang tanpa jejak — tawaran yang tak pernah
                 # terbaca sama saja dengan tawaran yang tak ada.
                 {"name": "berat_kg", "label": "Berat yang dipindah (kg)",
                  "type": "number"},
             ]},
            # Broken (patah hasil sosoh) punya silonya SENDIRI (keputusan
            # pemilik 6 Oktober 2026), supaya ia bisa disosoh ulang sebagai
            # bahan baku. Gerbangnya SAMA dengan pindah tumpukan di atas —
            # pekerjaan operator, bukan Admin biasa; Super Admin dikecualikan
            # untuk alasan yang sama (lihat komentar panjang di atas blok ini).
            #
            # ⚠⚠ SATU AKSI, bukan dua — keputusan pemilik 7 Oktober 2026.
            # Dulu "Catat broken (curah)" (lihat `aksi_inventory.py`) lalu
            # "Masukkan broken ke silo" dua langkah terpisah. Aksi ini kini
            # dibuka dari kartu Stok Produk, bukan katalog Catat pekerjaan lain.
            # Jalurnya menghindari operator menjawab pertanyaan
            # yang salah — "berapa yang MASIH BELUM TERCATAT" — padahal yang
            # ingin ia katakan cuma "berapa yang masuk silo sekarang".
            # Sumbernya kini OTOMATIS: curah dulu, lalu karung dibongkar bila
            # kurang — lihat `gudang2.service.masukkan_broken_ke_silo`.
            {"id": "masukkan_broken_silo", "label": "📤 Masukkan broken ke silo",
             "post": "/api/actions/masukkan-broken-silo",
             "hint": "Sumbernya otomatis: curah dulu, lalu karung dibongkar bila "
                     "kurang — sisanya tetap jadi curah di stok.",
             "fields": [
                 {"name": "proses", "label": "Pemilik stok broken", "type": "remote",
                  "source": "/api/actions/broken-proses-tersedia",
                  "auto_satu": True,
                  "kosong": "Belum ada stok broken yang tersedia."},
                 {"name": "silo", "label": "Silo broken tujuan", "type": "remote",
                  "source": "/api/actions/silo-broken-g2",
                  "auto_satu": True,
                  "kosong": "Belum ada silo broken. Tambahkan di Pengaturan → Alat."},
                 {"name": "berat_kg", "label": "Berat yang masuk silo (kg)",
                  "type": "number"},
             ]},
            {"id": "masukkan_menir_silo", "label": "📤 Masukkan menir ke silo",
             "post": "/api/actions/masukkan-menir-silo",
             "hint": "Hanya stok menir yang tersedia; pemilik stok dibawa ke silo.",
             "fields": [
                 {"name": "pemilik", "label": "Pemilik stok menir", "type": "remote",
                  "source": "/api/actions/hasil-samping-pemilik-tersedia?jenis=menir",
                  "auto_satu": True, "kosong": "Belum ada stok menir yang tersedia."},
                 {"name": "silo", "label": "Silo tujuan", "type": "remote",
                  "source": "/api/actions/silo-hasil-samping-g2?jenis=menir",
                  "auto_satu": True, "kosong": "Belum ada silo yang menerima menir."},
                 {"name": "berat_kg", "label": "Berat yang masuk silo (kg)", "type": "number"},
             ]},
            {"id": "masukkan_reject_silo", "label": "📤 Masukkan reject ke silo",
             "post": "/api/actions/masukkan-reject-silo",
             "hint": "Hanya stok reject yang tersedia; pemilik stok dibawa ke silo.",
             "fields": [
                 {"name": "pemilik", "label": "Pemilik stok reject", "type": "remote",
                  "source": "/api/actions/hasil-samping-pemilik-tersedia?jenis=reject",
                  "auto_satu": True, "kosong": "Belum ada stok reject yang tersedia."},
                 {"name": "silo", "label": "Silo tujuan", "type": "remote",
                  "source": "/api/actions/silo-hasil-samping-g2?jenis=reject",
                  "auto_satu": True, "kosong": "Belum ada silo yang menerima reject."},
                 {"name": "berat_kg", "label": "Berat yang masuk silo (kg)", "type": "number"},
             ]},
            # ── Beras jadi bahan silo — dua pintu (keputusan pemilik 8 Oktober 2026) ──
            #
            # "Silo Beras... bisa diisi beras premium, super, maupun medium...
            # untuk campuran seperti silo broken" + "silo A dan silo B juga
            # bisa dimasuki beras putih untuk disosoh ulang" — "beras putih"
            # di sini kalimat APA ADANYA pemilik (beras yang sudah digiling),
            # bukan bucket teknis "mutu belum ditetapkan" (lihat docstring
            # `masukkan_beras_ke_silo` untuk kenapa bucket itu tak pernah
            # punya baris nyata). KEDUA tujuan menerima grade yang SAMA. SATU
            # satu aksi melayani kedua tujuan. Jenis beras menjadi pilihan
            # pertama dan dikunci otomatis bila aksi dibuka dari kartu stok;
            # sumbernya kemudian dipilih berdasarkan merek dan kemasan.
            # Daftar silo tetap gabungan, lalu server menolak kombinasi
            # komoditas yang tidak sesuai.
            {"id": "masukkan_beras_silo", "label": "📤 Masukkan beras ke silo",
             "post": "/api/actions/masukkan-beras-silo",
             "hint": "Jenis beras dan pemilik mengikuti kartu yang dipilih. "
                     "Pilih merek dan kemasan stok yang ingin dipindahkan, lalu masukkan beratnya. "
                     "Untuk kemasan, berat harus kelipatan ukuran karung.",
             "fields": [
                 {"name": "jenis", "label": "Jenis beras", "type": "remote",
                  "source": "/api/actions/beras-jenis-silo",
                  "kosong": "Belum ada jenis beras yang bisa dipindahkan."},
                 {"name": "sumber_stok", "label": "Merek dan kemasan", "type": "remote",
                  "source": "/api/actions/beras-sumber-tersedia", "induk": "jenis",
                  "kosong": "Tidak ada stok dengan pemilik dan jenis beras ini."},
                 {"name": "berat_kg", "label": "Berat yang masuk silo (kg)",
                  "type": "number", "wajib": True},
                 {"name": "silo", "label": "Silo tujuan (Beras atau PK)", "type": "remote",
                  "source": "/api/actions/silo-beras-tujuan-g2",
                  "kosong": "Belum ada Silo Beras atau silo PK. Tambahkan di "
                           "Pengaturan → Alat."},
             ]},
        ]
    if g2:
        # Pekerjaan OPERATOR Gudang 2 (keputusan pemilik 12 September 2026):
        # menjalankan mesin sosoh. Menempatkan PK yang datang (tumpuk /
        # langsung silo) adalah entry Admin — `masukkan_pk` ada di blok `fin`
        # di bawah. `pindah_tumpukan_silo` PINDAH ke blok tersendiri di atas
        # (4 Oktober 2026) — satu-satunya di sini yang Admin TIDAK boleh.
        actions += [
            # BEBERAPA silo boleh dicentang, sama seperti "Mulai giling".
            # Dulu daftarnya tupel tertulis-tangan A / B / A+B: layanannya
            # SUDAH menerima berapa pun silo, borangnya yang mengurungnya jadi
            # tiga kemungkinan. Silo Gudang 2 bisa bertambah lewat Pengaturan →
            # Alat, dan silo ketiga itu tak akan pernah muncul di tupel yang
            # diketik seseorang bertahun lalu — juga tak ikut dalam "A+B".
            {"id": "mulai_penyosohan", "label": "🏭 Mulai penyosohan",
             "post": "/api/actions/mulai-penyosohan",
             "hint": "Boleh beberapa silo sekaligus — hasilnya satu proses "
                     "penyosohan, dan sisanya dicatat per silo saat selesai.",
             "fields": [
                 {"name": "silo", "label": "Silo bahan (boleh lebih dari satu)",
                  "type": "remote_banyak",
                  "source": "/api/actions/silo-bahan-g2",
                  "kosong": "Tidak ada silo Gudang 2 berisi PK yang siap disosoh."},
             ]},
            {"id": "hasil_penyosohan", "label": "⚙️ Catat hasil penyosohan",
             "post": "/api/actions/hasil-penyosohan",
             "hint": "Isi total hasil jenis yang dipilih sejak awal proses, bukan tambahan. "
                     "Contoh: sudah 300 kg, bertambah 200 kg → isi 500 kg.",
             "fields": [
                 {"name": "kode_proses", "label": "Penyosohan yang sedang berjalan", "type": "remote",
                  "source": "/api/actions/polishing-active",
                  "kosong": "Tidak ada penyosohan yang sedang berjalan."},
                 {"name": "jenis", "label": "Jenis hasil (wajib pilih)", "type": "select",
                  "options": JENIS_HASIL},
                 # Total aktual per jenis, sama dengan pencatatan hasil giling.
                 # Selisih terhadap catatan sebelumnya dihitung layanan agar
                 # input 500 sesudah 300 tidak menghasilkan 800 kg.
                 {"name": "berat_kumulatif", "label": "Total hasil sampai sekarang (kg)",
                  "type": "number", "wajib": True},
             ]},
            # ── Tambah silo ke penyosohan yang berjalan — mix bahan ──
            #
            # Laporan lapangan 7 Oktober 2026, sejajar giling: "proses yang
            # berjalan baik itu proses giling atau proses penyosohan, jika
            # awalnya hanya menggunakan 1 silo, tidak bisa menambahkan silo
            # lainnya." `mulai_penyosohan` menerima beberapa silo, tetapi
            # hanya saat MULAI.
            {"id": "tambah_silo_penyosohan", "label": "➕ Tambah silo (mix bahan)",
             "hint": "Silo yang dibebaskan bisa dipakai lagi, termasuk saat kosong. "
                     "Bahan boleh diisi setelah silo ditambahkan kembali. Pilih silo yang "
                     "belum dipakai proses lain, dan sepemilik dengan bahan "
                     "yang sudah berjalan.",
             "post": "/api/actions/tambah-silo-penyosohan", "fields": [
                 {"name": "kode", "label": "Proses penyosohan", "type": "remote",
                  "source": "/api/actions/polishing-active",
                  "kosong": "Tidak ada penyosohan yang sedang berjalan."},
                 {"name": "silo", "label": "Silo yang ditambahkan (boleh lebih dari satu)",
                  "type": "remote_banyak", "induk": "kode",
                  "source": "/api/actions/silo-bahan-g2",
                  "kosong": "Tidak ada silo yang bisa ditambahkan atau digunakan kembali."},
             ]},
            {"id": "hentikan_penyosohan", "label": "⏸️ Hentikan sementara",
             "post": "/api/actions/hentikan-proses",
             "hint": "Mesin rusak, listrik padam, jam kerja habis. Prosesnya tidak "
                     "ditutup — bisa dilanjutkan nanti atau besok, dan jam "
                     "tertahannya dihitung terpisah dari jam berjalan.",
             "fields": [
                 {"name": "proses", "label": "Penyosohan yang sedang berjalan",
                  "type": "remote", "source": "/api/actions/sosoh-berjalan",
                  "kosong": "Tidak ada penyosohan yang sedang berjalan."},
                 {"name": "sebab", "label": "Sebab berhenti", "type": "select",
                  "options": [["", "— pilih —"]]
                             + [[s, s] for s in SEBAB_AKTIF.get("penyosohan", [])]
                             + [[SEBAB_LAIN_JEDA, "Lainnya — tulis sendiri"]]},
                 {"name": "sebab_lain", "label": "Bila 'Lainnya': tulis sebabnya",
                  "type": "text", "optional": True},
             ]},
            {"id": "lanjutkan_penyosohan", "label": "▶️ Lanjutkan penyosohan",
             "post": "/api/actions/lanjutkan-proses",
             "hint": "Mesin jalan lagi. Lama tertahannya tercatat berikut sebabnya.",
             "fields": [
                 {"name": "proses", "label": "Penyosohan yang sedang berhenti",
                  "type": "remote", "source": "/api/actions/sosoh-berhenti",
                  "kosong": "Tidak ada penyosohan yang sedang berhenti."},
             ]},
            {"id": "selesai_penyosohan", "label": "📤 Bebaskan silo penyosohan",
             "post": "/api/actions/selesai-penyosohan", "pratinjau_silo": "sosoh",
             "hint": "Lepas ikatan silo dari proses; sisanya tetap tercatat. Penyosohan dan pencatatan hasil tetap berjalan. Hanya silo dengan sisa 0 kg yang kosong dan siap diisi ulang.",
             "konfirmasi": {"judul": "Bebaskan silo?", "teks": "{kode_proses} · Silo {silo}: sisa {sisa} kg. Silo dibebaskan; penyosohan tetap berjalan. Gunakan Selesaikan penyosohan saat seluruh bahan di mesin benar-benar selesai.", "ya": "Bebaskan silo, lanjutkan sosoh"},
             "fields": [
                 {"name": "kode_proses", "label": "Proses penyosohan", "type": "remote",
                  "source": "/api/actions/polishing-active",
                  "kosong": "Tidak ada penyosohan yang sedang berjalan."},
                 # Silo milik PROSES yang dipilih di atasnya — `induk`, bukan
                 # daftar mati A/B.
                 #
                 # Borang ini dulu menuliskan pilihan silonya dengan tangan,
                 # padahal medan di atasnya sudah menyebut prosesnya. Jadi ia
                 # menawarkan Silo A kepada orang yang menyosoh di Silo B; yang
                 # menekannya dijawab 400 "Sebutkan silo mana yang selesai
                 # (A/B)" — pesan yang tak masuk akal bagi orang yang BARU SAJA
                 # menyebutkan silonya. Keluhan pemilik 24 September 2026 07:14.
                 #
                 # Daftar sepanjang satu (prosesnya memakai satu silo) terisi
                 # sendiri di klien: tak ada pilihan yang bisa dibuat di sana,
                 # jadi tak ada pilihan yang bisa salah.
                 {"name": "silo", "label": "Silo yang dibebaskan", "type": "remote",
                  "induk": "kode_proses", "source": "/api/actions/sosoh-silo",
                  "kosong": "Semua silo proses ini sudah ditandai selesai."},
                 {"name": "sisa", "label": "Sisa di silo (kg) — isi 0 jika kosong", "type": "number", "wajib": True},
             ]},
            {"id": "akhiri_penyosohan", "label": "🏁 Selesaikan penyosohan",
             "post": "/api/actions/akhiri-penyosohan", "pratinjau_proses": "sosoh",
             "hint": "Nyatakan seluruh bahan selesai melewati mesin dan semua hasil sudah dicatat. Bebaskan setiap silo dan catat sisanya terlebih dahulu.",
             "fields": [{"name": "kode_proses", "label": "Proses penyosohan",
                "type": "remote", "source": "/api/actions/polishing-active"}]},
        ]
        # "Minta lot ini" — permintaan, bukan izin (pemilik 24 September 2026).
        #
        # SESUDAH pekerjaan harian, bukan sebelumnya: yang memimpin daftar
        # seharusnya yang paling sering dikerjakan. Dan hanya untuk OPERATOR —
        # Admin yang juga memegang Gudang 2 tak membutuhkannya, sebab ia bisa
        # memindahkan langsung; permintaan kepada diri sendiri cuma satu baris
        # tambahan yang harus ditutup sendiri. Rutenya menjaga hal yang sama;
        # yang di sini cuma berhenti menawarkan.
        #
        # PUNYA DAFTARNYA SENDIRI sejak 26 September 2026. Kalimat di sini
        # dulu berbunyi "tak punya daftar pilihan sendiri: ia SELALU dibuka
        # dari kartu lot di layar Stok, yang sudah menyebut lot mana" — dan
        # alasan itu salah dua kali. Penguncian-dari-kartu di `aksi.js` hanya
        # berlaku untuk isian bertipe PILIHAN, jadi isian teksnya tak pernah
        # terisi walau kartunya mengirim `nilai`; dan katalog "Catat pekerjaan
        # lain" membuka aksi yang sama tanpa membawa apa pun. Akibatnya
        # orangnya harus MENGETIK kode lot sambil berdiri memegang telepon
        # satu tangan — laporan pemilik, dengan fotonya.
        if not fin:
            actions += [
                {"id": "minta_pk_g1", "label": "🙋 Minta lot PK Gudang 1",
                 "post": "/api/actions/minta-pk-g1",
                 "hint": "Memberitahu Admin bahwa bahan ini Anda perlukan. "
                         "Admin yang menyetujui dan menetapkan tujuannya.",
                 "fields": [
                     {"name": "kode_proses", "label": "Lot PK yang Anda perlukan",
                      "type": "remote", "source": "/api/actions/pk-g1-tersedia",
                      "kosong": "Tidak ada lot PK Gudang 1 yang masih bersisa "
                                "dan belum diminta."},
                     # Satu isian, dan ia menghapus satu percakapan WhatsApp:
                     # tanpa angka ini Admin menebak batas atas muatan, atau
                     # bertanya di luar aplikasi (temuan QA 28 September 2026).
                     {"name": "berat", "label": "Berapa kg yang Anda perlukan",
                      "type": "number", "wajib": True},
                 ]},
                # Aksi "Muat & kirim PK" DIPINDAH ke blok `if g1:` pada 27
                # September 2026 — lihat komentar di sana. Gudang 2 yang
                # MEMINTA, Gudang 1 yang MENGIRIM sesudah Admin menyetujui.
            ]
    BUTIR = [["", "— pilih penilaian —"]] + [
        [k,f"{label} ({NILAI_KUALITATIF[k]})"] for k,label in LABEL_KUALITATIF.items()]
    JENIS_PK = [["", "— belum ditentukan —"], ["ks", "KS"], ["kl", "KL"],
                ["campuran", "Campuran"], ["semi_ks", "Semi KS"]]
    if fin:
        # Tugas pokok staff (keuangan & QC lintas gudang).
        actions += [
            {"id": "rekonsiliasi_timbang", "label": "🔎 Cocokkan tiket timbang dengan catatan",
             "post": "/api/actions/rekonsiliasi-timbang",
             "hint": "Tiket timbang yang belum tercatat, selisih nota dengan hasil "
                     "timbang, dan catatan yang masih menunggu bobot.", "fields": []},
            # Namanya KOREKSI, bukan verifikasi (24 September 2026, keputusan
            # pemilik: "yang mencatat hasil giling hanya operator. jika ada
            # kesalahan sudah ada di perbaiki hasil giling").
            #
            # Aksinya tetap, dan kalimatnya yang berubah — sebab itulah
            # pekerjaannya sekarang: membetulkan angka yang keliru, bukan
            # mengesahkan angka yang sudah benar. Nama tombolnya disamakan
            # dengan tombol di kartu layar Stok, yang memanggil aksi yang SAMA;
            # dua nama untuk satu pekerjaan membuat orang mengira ada dua.
            {"id": "verify_output", "label": "🩹 Perbaiki hasil giling",
             "post": "/api/actions/verify-output",
             "hint": "Untuk membetulkan berat PK yang salah catat. Yang mencatat "
                     "hasil giling operator, lewat \"Perbarui hasil giling\"; "
                     "rendemen & HPP terhitung ulang dari angka yang dibetulkan.",
             "fields": [
                 {"name": "kode_proses", "label": "Giling yang sudah selesai", "type": "remote",
                  "source": "/api/actions/milling-unverified",
                  "kosong": "Belum ada giling yang selesai."},
                 {"name": "berat_output", "label": "Berat PK yang benar (kg)", "type": "number"},
             ]},
            # Korban lama P6-03 atau revisi tiket yang disengaja: keduanya
            # tampak sama dari data, jadi yang memutuskan admin, per proses.
            {"id": "betulkan_bobot_giling", "label": "🩹 Betulkan bobot masuk giling",
             "post": "/api/actions/betulkan-bobot-giling",
             "hint": "Giling selesai yang bobot masuknya tak cocok dengan bobot bahannya "
                     "sekarang. Dibetulkan ke bobot bahan, rendemen dihitung ulang — "
                     "tercatat di jejak audit dan bisa dibatalkan.", "fields": [
                 {"name": "kode_proses", "label": "Giling yang bobot masuknya tak cocok",
                  "type": "remote", "source": "/api/actions/giling-tak-cocok",
                  "kosong": "Tak ada giling yang bobot masuknya tak cocok."},
             ]},
            {"id": "qc_giling", "label": "🔬 QC hasil giling",
             "post": "/api/actions/qc-giling",
             "hint": "Boleh dicatat berulang selama giling berjalan — contoh dari "
                     "beras yang baru keluar mesin. Angka dirata-rata; butir kuning, "
                     "gabah, dan merang juga dirata-rata. "
                     "Butir kuning, gabah, dan merang wajib dipilih. " + ATURAN_RATA_QC_PK, "fields": [
                 {"name": "kode_proses",
                  "label": "Giling yang sedang berjalan atau sudah selesai",
                  "type": "remote",
                  "source": "/api/actions/milling-noqc",
                  "kosong": "Belum ada giling yang bisa dinilai mutunya."},
                 {"name": "kadar_air", "label": "Kadar air (%)", "type": "number"},
                 {"name": "broken", "label": "Butir patah (%)", "type": "number"},
                 {"name": "susut", "label": "Susut (%)", "type": "number"},
                 {"name": "butir_kuning", "label": "Butir kuning", "type": "select",
                  "options": BUTIR},
                 {"name": "gabah", "label": "Gabah", "type": "select",
                  "options": BUTIR},
                 {"name": "merang", "label": "Merang", "type": "select",
                  "options": BUTIR},
                 {"name": "catatan_lab", "label": "Catatan lab", "type": "text"},
             ]},
            {"id": "catat_pk_luar", "label": "📦 Catat PK luar datang",
             "post": "/api/actions/catat-pk-luar",
             "hint": "Pilih tiket timbang PK yang masih aktif — supplier, bobot & plat "
                     "otomatis dari timbangan. Langsung tertumpuk. Mutunya dicatat "
                     "TERPISAH, lewat kartu \"Mutu PK luar belum dicatat\" di halaman "
                     "Mutu & QC — begitu PK ini tercatat, kartunya akan muncul di sana.",
             "fields": [
                 {"name": "timbangan_transaksi_id", "label": "Tiket timbang PK yang masih aktif",
                  "type": "remote", "source": "/api/actions/timbang-pk-aktif",
                  "kosong": "Tidak ada tiket timbang PK yang aktif."},
                 {"name": "jenis_pk", "label": "Jenis PK (wajib pilih)", "type": "select",
                  "options": JENIS_PK},
                 # ── Mutu TIDAK lagi di sini (keputusan pemilik 5 Oktober 2026,
                 #    membatalkan penyatuan hari yang sama) ──
                 #
                 # "QC Pk bukan di borang Catat PK luar datang. tetapi buat di
                 # kartu di halaman Mutu & QC." Borang ini sempat menanyakan
                 # kadar air/broken/penyusutan/butir kuning/gabah/merang/catatan
                 # lab SEKALIGUS wajib — dicabut lagi di sini. Jalur mutunya
                 # `qc_pk_luar`, yang TETAP tinggal di `b.meja` (lihat
                 # `berjalan.untuk_gudang2`, blok "Kerja meja: MUTU PK luar")
                 # dan tak pernah dihapus — selama penyatuan ini berlaku ia
                 # cuma tak pernah PUNYA kartu untuk dibuka, sebab QC-nya sudah
                 # selalu lengkap di sini. Mencabut medan ini saja sudah cukup
                 # mengembalikan kartunya: setiap batch baru lagi-lagi lahir
                 # tanpa `PkPurchaseVerification`.
                 #
                 # ── Tombol KEDUA, di borang yang SAMA — Aturan 1 & 2, 4
                 # Oktober 2026 (keputusan pemilik 5 Oktober: bukan menu
                 # terpisah, tombol DI SINI). Membawa tiket yang sudah
                 # dipilih (`bawa`) supaya tak ditanya dua kali; borang
                 # tujuannya cuma mewajibkan alasan — lihat `act_tolak_pk_luar`.
                 # TAK menanyakan mutu sama sekali: PK ditolak tak jadi stok.
                 {"type": "tombol_aksi", "aksi": "tolak_pk_luar",
                  "bawa": "timbangan_transaksi_id", "label": "⛔ Tolak PK luar"},
             ]},
            {"id": "catat_beras_timbang_masuk", "label": "📦 Terima beras sebagai stok",
             "post": "/api/actions/catat-produk-timbang-masuk",
             "hint": "Masuk ke stok bertumpuk sebagai Beras Medium, karung putih polos tanpa merek 50 kg.",
             "fields": [{"name": "timbangan_transaksi_id", "label": "Tiket timbang beras",
                         "type": "remote", "source": "/api/actions/produk-timbang-masuk-aktif?jenis=BERAS_MASUK",
                         "kosong": "Tidak ada tiket beras masuk yang menunggu."}]},
            {"id": "catat_broken_timbang_masuk", "label": "📦 Terima broken sebagai stok",
             "post": "/api/actions/catat-produk-timbang-masuk",
             "hint": "Masuk ke stok bertumpuk dan otomatis dikemas dalam karung putih polos tanpa merek 50 kg.",
             "fields": [{"name": "timbangan_transaksi_id", "label": "Tiket timbang broken",
                         "type": "remote", "source": "/api/actions/produk-timbang-masuk-aktif?jenis=BROKEN_MASUK",
                         "kosong": "Tidak ada tiket broken masuk yang menunggu."}]},
            # ⚠⚠ TIDAK ADA PINTU SENDIRI DI "Catat pekerjaan lain" (keputusan
            # pemilik 5 Oktober 2026) — satu-satunya jalan masuk adalah tombol
            # di borang `catat_pk_luar` di atas (`tombol_aksi`). Spesifikasi
            # ini TETAP terkirim (GRUP_KARTU, lihat daftar di bawah) supaya
            # `bukaAksi` masih bisa membukanya dari sana; yang hilang cuma
            # baris katalognya sendiri.
            {"id": "tolak_pk_luar", "label": "⛔ Tolak PK luar",
             "post": "/api/actions/tolak-pk-luar",
             "hint": "PK yang datang tidak diterima — kembali ke truknya. Satu-satunya "
                     "yang wajib diisi alasannya; jenis PK & kadar air tak ditanya, "
                     "sebab PK yang ditolak tak pernah jadi stok. Tiket timbangnya "
                     "ikut ditutup otomatis sebagai \"truk pergi\", dengan alasan ini.",
             "fields": [
                 {"name": "timbangan_transaksi_id", "label": "Tiket timbang PK yang masih aktif",
                  "type": "remote", "source": "/api/actions/timbang-pk-aktif",
                  "kosong": "Tidak ada tiket timbang PK yang aktif."},
                 {"name": "alasan", "label": "Alasan menolak (wajib)", "type": "text"},
             ]},
            {"id": "qc_pk_luar", "label": "🔬 Catat kualitas PK luar",
             "post": "/api/actions/qc-pk-luar",
             "hint": "PK yang masuk sudah pasti diterima — ini hanya mencatat "
                     "kualitasnya. Setiap simpan menjadi putaran baru tanpa batas. "
                     "Butir kuning, gabah, dan merang wajib dipilih. " + ATURAN_RATA_QC_PK,
             "fields": [
                 {"name": "kode_batch", "label": "PK luar yang diperiksa", "type": "remote",
                  "source": "/api/actions/pk-luar-qc",
                  "kosong": "Belum ada PK luar yang bisa diperiksa."},
                 {"name": "kadar_air", "label": "Kadar air (%)", "type": "number"},
                 {"name": "broken", "label": "Broken (%)", "type": "number"},
                 {"name": "penyusutan", "label": "Penyusutan/bekatul lab (%)", "type": "number"},
                 {"name": "butir_kuning", "label": "Butir kuning", "type": "select",
                  "options": BUTIR},
                 {"name": "gabah", "label": "Gabah", "type": "select",
                  "options": BUTIR},
                 {"name": "merang", "label": "Merang", "type": "select",
                  "options": BUTIR},
                 {"name": "catatan_lab", "label": "Catatan lab", "type": "text"},
             ]},
            # Mencatat PK yang datang — ENTRY ADMIN (keputusan pemilik 12
            # September 2026); dulu ada di blok operator Gudang 2.
            #
            # ⚠ Medan "Tujuan" DIBUANG 4 Oktober 2026 (Aturan 1): PK yang
            # baru masuk selalu ke tumpukan sekarang, tanpa pertanyaan —
            # pindah ke silo adalah langkah terpisah milik operator
            # (`pindah_tumpukan_silo`). Jangan pasang lagi medan ini di sini;
            # lihat catatan panjang di `masukkan_pk_luar`.
            {"id": "masukkan_pk", "label": "📥 Masukkan PK diterima",
             "post": "/api/actions/masukkan-pk", "fields": [
                 {"name": "kode_batch", "label": "PK yang menunggu dimasukkan", "type": "remote",
                  "source": "/api/actions/pk-intake-pending",
                  "kosong": "Tidak ada PK masuk yang menunggu."},
             ]},
            {"id": "transfer_pk", "label": "🚚 Pemindahan PK G1 → G2",
             "post": "/api/actions/transfer-pk", "fields": [
                 {"name": "kode_proses", "label": "PK dari proses", "type": "remote",
                  "source": "/api/actions/pk-transfer",
                  "kosong": "Tidak ada PK yang siap dipindah."},
                 {"name": "berat", "label": "Berat kg (kosong = semua)", "type": "number"},
                 {"name": "tujuan", "label": "Tujuan", "type": "remote",
                  "source": "/api/actions/tujuan-pk-g2",
                  "kosong": "Belum ada silo Gudang 2. Tambahkan di Pengaturan → Alat."},
             ]},
            # Menolak permintaan operator Gudang 2. Tak punya daftar sendiri:
            # ia SELALU dibuka dari kartunya di Antrian tunggu, yang sudah
            # menyebut lot dan pemintanya — medan tersembunyi `permintaan`
            # dikunci nilainya oleh kartu itu (`aksi.js`).
            # ACC, kirim, dan tutup: ketiganya SELALU dibuka dari kartunya,
            # yang sudah menyebut lot dan pemintanya. Medan `permintaan`
            # dikunci nilainya oleh kartu itu (`aksi.js`).
            {"id": "acc_permintaan_pk", "label": "✅ Setujui permintaan PK",
             "post": "/api/actions/acc-permintaan-pk",
             "hint": "Tujuan ditetapkan sekarang, bukan nanti: yang tahu gudang "
                     "mana yang kosong adalah Anda, bukan yang memuat. "
                     "Bobotnya batas atas — Gudang 1 boleh memuat kurang.",
             "fields": [
                 {"name": "permintaan", "label": "Permintaan yang mana",
                     "type": "remote", "source": "/api/actions/permintaan-diminta",
                     "kosong": "Tidak ada permintaan yang menunggu keputusan."},
                 {"name": "tujuan", "label": "Tujuan di Gudang 2", "type": "remote",
                  "source": "/api/actions/tujuan-pk-g2",
                  "kosong": "Belum ada silo Gudang 2. Tambahkan di Pengaturan → Alat."},
                 {"name": "berat", "label": "Berat yang disetujui (kg)",
                  "type": "number", "wajib": True},
             ]},
            {"id": "tutup_permintaan_pk", "label": "🔒 Tutup permintaan PK",
             "post": "/api/actions/tutup-permintaan-pk",
             "hint": "Angka Anda yang berlaku. Bila berbeda dari yang dicatat "
                     "Gudang 1, perpindahannya ikut dibetulkan — dan angka "
                     "Gudang 1 tetap tersimpan sebagai catatan asal.",
             "fields": [
                 {"name": "permintaan", "label": "Permintaan yang mana",
                     "type": "remote", "source": "/api/actions/permintaan-dikirim",
                     "kosong": "Tidak ada kiriman yang menunggu ditutup."},
                 {"name": "berat", "label": "Berat akhir (kg)", "type": "number",
                  "wajib": True},
             ]},
            {"id": "tolak_permintaan_pk", "label": "🚫 Tolak permintaan PK",
             "post": "/api/actions/tolak-permintaan-pk",
             "hint": "Sebabnya terbaca operator yang meminta. Permintaan yang "
                     "hilang tanpa kabar akan diajukan lagi besok.",
             "fields": [
                 {"name": "permintaan", "label": "Permintaan yang mana",
                     "type": "remote", "source": "/api/actions/permintaan-diminta",
                     "kosong": "Tidak ada permintaan yang menunggu keputusan."},
                 {"name": "sebab", "label": "Sebab menolak", "type": "text"},
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

    _lengkapi_formulir_jeda(actions)

    # Tandai gudang tiap aksi → dipakai layar Catat memisah tab G1/G2 (admin/staff).
    for a in actions:
        a["wh"] = _ACTION_WH.get(a["id"], "g1")
        a["grup"] = _GRUP_AKSI.get(a["id"], GRUP_LAIN)
        # Aksi yang sudah punya kartu TETAP dikirim — lembarnya dibuka dari
        # kartu di Antrian, Sedang berjalan, Keputusan, dan Stok lewat MENU
        # ini — tetapi TIDAK digambar di katalog Catat pekerjaan lain (21
        # September 2026, permintaan pemilik). Dua pintu untuk satu pekerjaan
        # membuat orang bertanya yang mana yang benar; dan katalog memang
        # untuk yang tak berwujud benda di gudang.
        a["kartu"] = a["grup"] == GRUP_KARTU
    # `undo` dibuang dari katalog HANYA bagi yang punya List audit — di sana
    # ia lengkap dengan daftar apa yang akan hilang, dan dua pintu untuk satu
    # pekerjaan berarti yang satu tak pernah ikut diperbarui.
    #
    # Operator TIDAK punya List audit (jejak lengkap berikut tombol
    # pembatalnya bukan miliknya), jadi bagi mereka katalog inilah satu-
    # satunya jalan. Membuangnya untuk semua orang berarti yang paling sering
    # salah ketik justru kehilangan cara memperbaikinya — dan itu ketahuan
    # hanya karena simulasi memeriksanya sebagai operator.
    if fin:
        actions = [a for a in actions if a["id"] != "undo"]
    # Mutu bisa dimatikan seluruhnya lewat Pengaturan. Disaring DI SINI, di
    # satu tempat, bukan di tiap cabang yang menyusun daftarnya: aksi QC
    # bertambah lebih sering daripada penyaringnya diperiksa ulang.
    from app.services.setelan import fitur_mutu

    async with SessionLocal() as db:
        if not await fitur_mutu(db):
            actions = [a for a in actions
                       if a["id"] not in (*AKSI_MUTU, "qc_gabah_tutup")]
    # Urutan kelompok dititipkan pada aksi pertama: menu inilah satu-satunya
    # yang dikirim ke layar, dan menaruh urutannya di tempat lain berarti dua
    # tempat yang harus sepakat.
    if actions:
        actions[0]["urut_grup"] = URUT_GRUP
    return actions



def _lengkapi_formulir_jeda(actions):
    """Empat pintu memakai waktu dan pemeriksaan yang sama, termasuk dari kartu."""
    import copy
    tambahan = []
    for aksi in list(actions):
        id_ = aksi['id']
        if id_ not in ('hentikan_proses','hentikan_penyosohan','lanjutkan_proses','lanjutkan_penyosohan'):
            continue
        berhenti = id_.startswith('hentikan')
        aksi['pratinjau_jeda'] = 'hentikan' if berhenti else 'lanjutkan'
        if berhenti:
            aksi['fields'] = [f if f['name'] != 'sebab' else {
                'name':'sebab','label':'Sebab berhenti sesuai proses','type':'remote',
                'induk':'proses','source':'/api/actions/sebab-jeda'} for f in aksi['fields']]
            aksi['fields'].append({'name':'catatan','label':'Catatan kondisi (opsional)','type':'text','optional':True})
        aksi['fields'] += [
            {'name':'waktu_mode','label':'Waktu kejadian','type':'select','bawaan':'sekarang',
             'options':[['sekarang','Sekarang'],['aktual','Waktu aktual — terlambat mencatat']]},
            {'name':'waktu_kejadian','label':'Tanggal dan jam kejadian aktual (WIB)',
             'type':'datetime-local','wajib':True,'waktu_aktual':True},
            {'name':'alasan_terlambat','label':'Alasan terlambat mencatat',
             'type':'text','wajib':True,'waktu_aktual':True},
        ]
        aksi['hint'] += ' Waktu sekarang menjadi bawaan. Jika terlambat, isi waktu kejadian aktual dan alasannya.'
        if berhenti:
            kondisi = copy.deepcopy(aksi)
            kondisi['id'] = 'ubah_kondisi_penyosohan' if id_ == 'hentikan_penyosohan' else 'ubah_kondisi_proses'
            kondisi['label'] = '⏸️ Perbarui kondisi jeda'
            kondisi['post'] = '/api/actions/ubah-kondisi-jeda'
            kondisi['pratinjau_jeda'] = 'kondisi'
            kondisi['hint'] = 'Perbarui sebab atau kondisi tanpa melanjutkan mesin. Riwayat sebelumnya tetap tersimpan. Gunakan waktu aktual jika terlambat mencatat.'
            kondisi['fields'][0]['source'] = '/api/actions/sosoh-berhenti' if id_ == 'hentikan_penyosohan' else '/api/actions/proses-berhenti'
            kondisi['fields'][0]['label'] = 'Proses yang sedang dijeda'
            tambahan.append(kondisi)
    actions.extend(tambahan)

#: Kelompok katalog. Daftar datar 30 kata kerja menuntut orang membacanya
#: seluruhnya untuk menemukan satu — persis keadaan yang sudah dibuang dari
#: layar antrean. Kelompoknya mengikuti PEKERJAAN, bukan tabel.
#:
#: GRUP_KARTU bukan kelompok yang tampil: ia PENANDA bahwa aksi itu dikerjakan
#: dari kartu (`a["kartu"]`), jadi katalog melewatkannya. Aksinya tetap ada di
#: menu karena lembar kartu dibangun dari spesifikasi yang sama.
GRUP_KARTU = "Biasanya dikerjakan dari kartu"
GRUP_LAIN = "Lain-lain"

_GRUP_AKSI = {
    # Yang BENAR-BENAR digambar di katalog: aksi yang tak punya kartu, jadi
    # katalog satu-satunya pintunya. Yang berkartu ada di daftar di bawah.
    "transfer_pk": "Pemindahan bahan",
    # Yang keluar dari pabrik, dan yang bukan beras putih.
    #
    # `kirim_bekatul`, `kirim_barang_jadi` dan `jual_pk` DIBUANG 28 September
    # 2026 (keputusan pemilik): barang keluar kini berperintah, dan pintu kedua
    # tanpa perintah membuat rantainya sukarela.
    # Masukkan beras ke silo dibuka dari Stok; spesifikasinya tetap dikirim.
    "masukkan_beras_silo": "Hasil samping & barang jadi",
    "perintah_keluar": "Barang keluar",
    "tambah_barang_keluar": "Barang keluar",
    "ubah_item_perintah": "Barang keluar", "hapus_item_perintah": "Barang keluar",
    "batal_perintah_keluar": "Barang keluar",
    # Tutup/batalkan dibuka dari detail Pesanan Jasa, bukan katalog umum.
    "tutup_jasa": "Jasa (titipan pelanggan)",
    "batalkan_jasa": "Jasa (titipan pelanggan)",
    "verifikasi_keluar": "Barang keluar", "keluar_cepat": "Barang keluar",
    "muat_semua": "Barang keluar",
    "muat_barang": "Barang keluar",
    "selesai_muat": "Barang keluar",
    # Pembelian & pencocokan.
    "beli_kemasan": "Stok & kemasan",
    "rekonsiliasi_timbang": "Pencocokan data",
    "auto_taut_keluar": "Pencocokan data",
    "qc_gabah_basah": "Pembelian & pencocokan",
    "qc_gabah_kering": "Pembelian & pencocokan",
}

# ── Aksi yang dikerjakan DARI KARTU — katalog melewatkannya ──
#
# Sebelum 28 September 2026 daftar ini hampir seluruhnya Gudang 1, dan
# kembaran Gudang 2-nya tertinggal: `mulai_giling` disembunyikan,
# `mulai_penyosohan` tidak. Tak ada yang memutuskan itu — ia menumpuk sendiri,
# dan hasilnya 12 pekerjaan berpintu ganda (ukuran QA lewat `/api/actions/menu`
# untuk lima peran).
#
# ⚠ ALASAN LAMA YANG DIBUANG, dan ini yang paling penting bagi pembaca
# berikutnya: kalimat di sini dulu berbunyi "kini punya kartunya sendiri,
# tetapi tetap dicantumkan supaya yang bendanya belum ada pun bisa dimulai
# dari sini". Alasan itu TIDAK BERLAKU, dan diperiksa satu per satu: medan
# pertama tiap borang katalog adalah daftar jarak jauh ke endpoint yang SAMA
# dengan yang menentukan kartunya muncul. Borangnya kosong persis saat
# kartunya tak ada — jadi ia tak pernah bisa jadi jalan darurat; ia cuma pintu
# kedua ke pintu yang sama.
#
# Yang paling patut dicurigai `catat_pk_luar` — PK yang datang tanpa lewat Pos
# Timbang. Borang katalognya pun menuntut tiket timbang aktif
# (`timbang-pk-aktif`), jadi ia tidak terkecuali.
#
# Aksinya TETAP dikirim di menu: lembar kartu dibangun dari spesifikasi yang
# sama. Yang berubah cuma `a["kartu"]`, dan katalog melewatkannya.
for _a in (
    # Spesifikasi tetap dikirim untuk Stok dan detail Pesanan Jasa.
    "masukkan_beras_silo", "tutup_jasa", "batalkan_jasa",
    # Gudang 1
    "gabah_masuk", "pindah_tumpukan", "mulai_pengeringan", "kadar_air",
    "selesai_pengeringan", "selesai_pendinginan", "mulai_pendinginan_ulang", "pindah_silo", "ubah_target",
    "mulai_giling", "hasil_giling", "selesai_giling", "tutup_silo_giling",
    "tambah_silo_giling",
    "hentikan_proses", "lanjutkan_proses", "ubah_kondisi_proses", "ubah_kondisi_penyosohan", "verify_output", "qc_giling",
    "qc_gabah_basah", "qc_gabah_kering", "qc_gabah_tutup",
    # Rantai permintaan PK
    "minta_pk_g1", "tolak_permintaan_pk", "acc_permintaan_pk",
    "kirim_permintaan_pk", "tutup_permintaan_pk",
    # Gudang 2 — menyusul 28 September 2026, pekerjaan yang sama bentuknya
    # dengan Gudang 1 dan selama ini beraturan berlawanan.
    "mulai_penyosohan", "hasil_penyosohan", "hentikan_penyosohan",
    "lanjutkan_penyosohan", "selesai_penyosohan", "akhiri_penyosohan", "pindah_tumpukan_silo",
    "tambah_silo_penyosohan", "catat_packing", "catat_broken",
    # Catat broken curah dan masukkan broken ke silo sama-sama dibuka dari
    # kartu Stok Produk; jangan tampilkan pintu kedua di katalog.
    "masukkan_broken_silo", "masukkan_menir_silo", "masukkan_reject_silo",
    "catat_beras_timbang_masuk",
    "catat_broken_timbang_masuk",
    # Formulir kepemilikan dibuka dari kartu stok terkait; pengambilan jasa
    # dibuka dari halaman Barang Keluar.
    "pindah_kepemilikan_produk", "pindah_kepemilikan_karung", "ambil_jasa",
    # PK dari luar & pencocokan — berkartu di Menunggu keputusan / Mutu & QC.
    "masukkan_pk", "catat_pk_luar", "tolak_pk_luar", "qc_pk_luar",
    "betulkan_bobot_giling",
    # Bekatul curah — tombolnya di kartu bekatul pada Stok Produk sejak 30
    # September 2026, tepat di sebelah angka "belum dicatat" yang menagihnya.
    # Pemakainya seluruhnya bisa membuka halaman itu (operator Gudang 2 &
    # Admin; operator selepan tak boleh mencatat bekatul sama sekali), jadi
    # mencabutnya dari katalog tidak menutup pintu siapa pun.
    "catat_bekatul",
    # ── Rantai barang keluar — dicabut dari katalog 29 September 2026 ──
    #
    # Permintaan pemilik: "saya tidak suka proses barang keluar prosesnya
    # dilakukan di catat pekerjaan lain. buat tombol di barang keluar ... lalu
    # hapus tombol yang ada di catat pekerjaan lain."
    #
    # Ketujuhnya punya pintunya sendiri sekarang, dan tiga bentuk yang berbeda:
    #   · `perintah_keluar`, `tambah_barang_keluar`, `batal_perintah_keluar`
    #     → TOMBOL di kaki halaman Barang Keluar (Admin & Super Admin);
    #   · `muat_semua`, `muat_barang`, `selesai_muat`
    #     → KARTU "Muat barang keluar" di Antrian tunggu operator;
    #   · `verifikasi_keluar`
    #     → KARTU di Menunggu keputusan Admin.
    #
    # Aksinya TETAP dikirim di menu — lembar yang dibuka dari tombol maupun
    # kartu dibangun dari spesifikasi yang sama. Yang berubah cuma katalognya
    # berhenti menggambarnya.
    "perintah_keluar", "tambah_barang_keluar", "ubah_item_perintah", "hapus_item_perintah", "batal_perintah_keluar",
    "koreksi_plat_pengiriman", "pilih_tiket_armada", "lepas_tiket_armada", "muat_semua", "muat_barang", "selesai_muat", "verifikasi_keluar", "keluar_cepat",
):
    _GRUP_AKSI[_a] = GRUP_KARTU

#: Urutan kelompok di layar — yang paling sering dipakai lebih dulu. Yang
#: sudah punya kartu tak ada di sini: ia tak digambar di katalog sama sekali.
URUT_GRUP = [
    "Stok & kemasan", "Pemindahan bahan", "Pencocokan data", GRUP_LAIN,
]


# Pemetaan aksi → gudang. Aksi keuangan/QC dikelompokkan ke gudang yang relevan:
# harga & QC gabah/giling = G1; PK luar (catat/kualitas/harga) = G2; transfer PK
# berasal dari proses G1 → G1.
_ACTION_WH = {
    # Gudang 1 (Selepan)
    "gabah_masuk": "g1", "pindah_tumpukan": "g1", "mulai_pengeringan": "g1", "kadar_air": "g1",
    "qc_gabah_basah": "g1", "qc_gabah_kering": "g1", "qc_gabah_tutup": "g1",
    "ubah_target": "g1",
    "selesai_pengeringan": "g1", "selesai_pendinginan": "g1", "mulai_pendinginan_ulang": "g1", "pindah_silo": "g1",
    "mulai_giling": "g1", "hasil_giling": "g1", "selesai_giling": "g1",
    "tutup_silo_giling": "g1", "tambah_silo_giling": "g1",
    "hentikan_proses": "g1", "lanjutkan_proses": "g1", "ubah_kondisi_proses": "g1", "ubah_kondisi_penyosohan": "g2",
    "verify_output": "g1", "qc_giling": "g1", "transfer_pk": "g1",
    # Barangnya di Gudang 1, peminatnya Gudang 2 — dicap g1, sama dengan
    # `transfer_pk`: yang dikerjakan orang atasnya adalah memindahkan dari G1.
    "minta_pk_g1": "g1", "tolak_permintaan_pk": "g1",
    "acc_permintaan_pk": "g1", "kirim_permintaan_pk": "g1",
    "tutup_permintaan_pk": "g1",
    "betulkan_bobot_giling": "g1",
    "rekonsiliasi_timbang": "g1",
    # Gudang 2 (Penyosohan)
    "masukkan_pk": "g2", "mulai_penyosohan": "g2", "hasil_penyosohan": "g2",
    "selesai_penyosohan": "g2", "akhiri_penyosohan": "g2", "pindah_tumpukan_silo": "g2",
    "tambah_silo_penyosohan": "g2",
    "hentikan_penyosohan": "g2", "lanjutkan_penyosohan": "g2",
    "catat_pk_luar": "g2", "tolak_pk_luar": "g2", "qc_pk_luar": "g2",
    # Inventory: packing & bekatul lahir di Gudang 2. Pembelian karung, harga
    # hasil samping, dan seluruh barang keluar dikelompokkan ke G2 pula —
    # barang jadi memang berdiri di sana, dan dari sanalah ia berangkat.
    "catat_packing": "g2", "catat_bekatul": "g2", "catat_broken": "g2",
    "masukkan_broken_silo": "g2", "masukkan_beras_silo": "g2",
    "masukkan_menir_silo": "g2", "masukkan_reject_silo": "g2",
    "pindah_kepemilikan_produk": "g2",
    "beli_kemasan": "g2", "pindah_kepemilikan_karung": "g2",
    # Rantai barang keluar berperintah. SELURUHNYA g2, termasuk yang dikerjakan
    # Admin: gudangnya milik CATATAN, bukan milik orang yang menekannya, dan
    # barang jadi memang berdiri di Gudang 2 — dari sanalah ia berangkat.
    # PK mentah tak lagi punya jalur di sini (keputusan pemilik: "pk dijual
    # tetapi itu urusan keuangan"), jadi tak ada lagi yang bergudang g1.
    "perintah_keluar": "g2", "tambah_barang_keluar": "g2",
    "ubah_item_perintah": "g2", "hapus_item_perintah": "g2",
    "batal_perintah_keluar": "g2", "verifikasi_keluar": "g2", "keluar_cepat": "g2",
    "koreksi_plat_pengiriman": "g2", "pilih_tiket_armada": "g2", "lepas_tiket_armada": "g2",
    "auto_taut_keluar": "g2",
    "muat_semua": "g2", "muat_barang": "g2", "selesai_muat": "g2",
    # ── Jasa: g2, dengan satu alasan yang sama seperti barang keluar ──
    #
    # Gudangnya milik CATATAN, bukan milik orang yang menekannya. Pengambilan
    # barang jasa mengeluarkan barang jadi, dan barang jadi berdiri di Gudang 2
    # — dari sanalah ia berangkat. Penutupan & pembatalan pesanan menyusul
    # pengambilannya, jadi ia tak boleh terpisah tab darinya: aksi yang
    # berpasangan tetapi beda tab membuat orang mencari separuhnya.
    "ambil_jasa": "g2", "tutup_jasa": "g2", "batalkan_jasa": "g2",
    # Undo tidak milik gudang mana pun; ia ikut G1 karena di situlah
    # tab pertama terbuka, dan aksinya sama isinya di kedua tab.
    "undo": "g1",
}


# ─────────────────────── Aksi cepat: daftar pilihan (remote) ───────────────────────

async def _pemilik_isi_silo(db, silo_id: int) -> str | None:
    """Sebutan pemilik isi satu silo Gudang 1 — None bila kosong/milik pabrik.

    Satu silo tak pernah berisi dua pemilik (dijaga `silo.masuk_silo`), jadi
    jawabannya tunggal bila ada.
    """
    from sqlalchemy import select

    from app.models import SiloStorage
    from app.services.jasa import nama_pemilik

    jid = (await db.execute(
        select(SiloStorage.jasa_id).where(
            SiloStorage.silo_id == silo_id, SiloStorage.status == "terisi",
            SiloStorage.jasa_id.is_not(None)).limit(1)
    )).scalars().first()
    return await nama_pemilik(db, jid) if jid is not None else None


@router.get("/actions/silo-g1")
async def silo_g1(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Silo gabah kering Gudang 1, beserta isinya sekarang.

    Isinya ikut ditampilkan karena silo yang sudah berisi TETAP boleh
    menerima — tetapi orang berhak tahu sebelum memilih, bukan diberi tahu
    lewat peringatan sesudahnya.
    """
    _require(await _is_g1_operator(user))
    from app.penggilingan.gudang1.services.silo import (
        _silo_content_kg, isi_silo, silos_g1)
    out = []
    async with SessionLocal() as db:
        for si in await silos_g1(db):
            kg = await _silo_content_kg(db, si.id)
            isi = f"berisi {_rp(kg)} kg" if kg else "kosong"
            # Pemilik isinya ikut disebut. Operator yang memilih silo perlu tahu
            # SEBELUM memilih bahwa isinya barang orang — bukan diberi tahu lewat
            # penolakan sesudahnya, dengan gabah sudah di tangan.
            if kg:
                rinci = await isi_silo(db, si.id)
                pemilik = {x.pemilik for x in rinci if x.pemilik}
                if len(pemilik) == 1:
                    isi += f" · {pemilik.pop()}"
            out.append({"value": si.nama_silo.replace("Silo ", ""),
                        "label": f"{si.nama_silo} · {isi}"})
    return out


@router.get("/actions/gabah-qc/{kondisi}")
async def gabah_qc(kondisi: str, user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Truk gabah dengan kurang dari lima pencatatan QC."""
    _require(await _is_g1_operator(user))
    if kondisi not in {"basah", "kering"}:
        raise HTTPException(404, "Kondisi gabah tidak dikenali.")
    await _wajib_mutu()
    from sqlalchemy import func, select
    from app.models import PurchaseBatch, PurchaseBatchQc, PurchaseBatchQcSample
    async with SessionLocal() as db:
        jumlah_qc = (select(func.count(PurchaseBatchQcSample.id))
                     .select_from(PurchaseBatchQcSample)
                     .join(PurchaseBatchQc, PurchaseBatchQc.id ==
                           PurchaseBatchQcSample.purchase_batch_qc_id)
                     .where(PurchaseBatchQc.purchase_batch_id == PurchaseBatch.id)
                     .correlate(PurchaseBatch).scalar_subquery())
        rows = (await db.execute(
            select(PurchaseBatch, jumlah_qc.label("jumlah_qc")).where(
                PurchaseBatch.kondisi_gabah == kondisi,
                PurchaseBatch.dibatalkan_pada.is_(None),
                jumlah_qc < 5,
                ~select(PurchaseBatchQc.id).where(
                    PurchaseBatchQc.purchase_batch_id == PurchaseBatch.id,
                    PurchaseBatchQc.ditutup_pada.isnot(None)).exists(),
            ).order_by(PurchaseBatch.id.desc()).limit(100)
        )).all()
    return [{"value": b.kode_batch,
             "label": f"QC {int(count)}/5 · {b.kode_batch} · {b.no_polisi_truk or 'tanpa plat'} · "
                      f"{float(b.berat_total_kg or 0):,.0f} kg".replace(",", ".")}
            for b, count in rows]


@router.get("/actions/gabah-qc-bisa-ditutup")
async def gabah_qc_bisa_ditutup(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """QC yang sudah memiliki catatan dan dapat ditutup sebelum 5/5."""
    _require(await _is_g1_operator(user))
    await _wajib_mutu()
    from sqlalchemy import func, select
    from app.models import PurchaseBatch, PurchaseBatchQc, PurchaseBatchQcSample
    async with SessionLocal() as db:
        jumlah_qc = (select(func.count(PurchaseBatchQcSample.id))
                     .select_from(PurchaseBatchQcSample)
                     .join(PurchaseBatchQc, PurchaseBatchQc.id ==
                           PurchaseBatchQcSample.purchase_batch_qc_id)
                     .where(PurchaseBatchQc.purchase_batch_id == PurchaseBatch.id)
                     .correlate(PurchaseBatch).scalar_subquery())
        rows = (await db.execute(
            select(PurchaseBatch, jumlah_qc.label("jumlah_qc"))
            .join(PurchaseBatchQc, PurchaseBatchQc.purchase_batch_id == PurchaseBatch.id)
            .where(PurchaseBatch.dibatalkan_pada.is_(None),
                   PurchaseBatchQc.ditutup_pada.is_(None),
                   jumlah_qc.between(1, 4))
            .order_by(PurchaseBatch.id.desc()).limit(100)
        )).all()
    return [{"value": batch.kode_batch,
             "label": f"{batch.kode_batch} · QC {count}/5 · {batch.no_polisi_truk or 'tanpa plat'}"}
            for batch, count in rows]


@router.post("/actions/qc-gabah/{kondisi}")
async def act_qc_gabah(kondisi: str, payload: dict = Body(...),
                       user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g1_operator(user))
    await _wajib_mutu()
    if kondisi not in {"basah", "kering"}:
        raise HTTPException(404, "Kondisi gabah tidak dikenali.")
    kode = str(payload.get("kode_batch") or "").strip()
    if not kode:
        raise HTTPException(400, "Pilih truk gabah yang akan diperiksa.")
    try:
        lamur = None
        jumlah_sak = None
        if kondisi == "basah":
            pilihan_lamur = payload.get("lamur")
            if pilihan_lamur not in {"iya", "tidak"}:
                raise ValueError("Pilih status Lamur: iya atau tidak.")
            lamur = pilihan_lamur == "iya"
            try:
                nilai_sak = float(payload.get("jumlah_sak_lamur"))
            except (TypeError, ValueError):
                raise ValueError("Isi jumlah sak yang Lamur.")
            if not nilai_sak.is_integer():
                raise ValueError("Jumlah sak harus berupa bilangan bulat.")
            jumlah_sak = int(nilai_sak)
        from app.penggilingan.gudang1.services.qc_gabah import catat_qc_gabah
        async with SessionLocal() as db:
            u = await db.get(User, user.id)
            qc, rata, jumlah = await catat_qc_gabah(
                db, user=u, kode_batch=kode,
                kadar_air_1=payload.get("kadar_air_1"),
                kadar_air_2=payload.get("kadar_air_2"),
                biji_hijau=payload.get("biji_hijau"), densiti=payload.get("densiti"),
                lamur=lamur, jumlah_sak_lamur=jumlah_sak,
            )
    except ValueError as e:
        raise HTTPException(400, str(e))
    ringkasan_lamur = (f" · Lamur total {qc.jumlah_sak_lamur or 0} sak"
                       if kondisi == "basah" else "")
    return {"ok": True, "pesan": f"✓ QC *{kode}* tercatat · pencatatan {jumlah}/5 · "
                                  f"rata-rata kadar air {rata:.2f}%{ringkasan_lamur}"}


@router.get("/actions/pratinjau-tutup-qc")
async def pratinjau_tutup_qc(kode_batch: str, user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g1_operator(user))
    await _wajib_mutu()
    from app.penggilingan.gudang1.services.qc_gabah import ringkasan_tutup_qc
    async with SessionLocal() as db:
        try:
            return await ringkasan_tutup_qc(db, kode_batch=kode_batch)
        except ValueError as e:
            raise HTTPException(409, str(e))


@router.post("/actions/tutup-qc-gabah")
async def act_tutup_qc_gabah(payload: dict = Body(...),
                             user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g1_operator(user))
    await _wajib_mutu()
    kode = str(payload.get("kode_batch") or "").strip()
    if not kode:
        raise HTTPException(400, "Pilih proses QC gabah yang akan ditutup.")
    try:
        from app.penggilingan.gudang1.services.qc_gabah import tutup_qc_gabah
        async with SessionLocal() as db:
            u = await db.get(User, user.id)
            dasar = str(payload.get("dasar") or "")
            if not dasar:
                raise HTTPException(409, "Periksa ringkasan QC terbaru sebelum konfirmasi.")
            _, jumlah = await tutup_qc_gabah(
                db, user=u, kode_batch=kode,
                alasan=str(payload.get("alasan") or ""), dasar=dasar)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "pesan": f"✓ Proses QC *{kode}* ditutup · {jumlah}/5 pencatatan"}


@router.get("/actions/dryer-menunggu")
async def dryer_menunggu(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Mesin pengering yang ADA gabahnya menunggu dinyalakan.

    Bukan seluruh mesin: menawarkan mesin kosong hanya menghasilkan penolakan
    "tidak ada gabah di mesin itu" setelah orang memilihnya.
    """
    _require(await _is_g1_operator(user))
    from app.penggilingan.gudang1.services.drying import (
        _loose_dryer_batches, dryers_g1, mode_disarankan)
    out = []
    async with SessionLocal() as db:
        for d in await dryers_g1(db):
            batches = await _loose_dryer_batches(db, d.id)
            if not batches:
                continue
            bb = dari_batches(batches)
            kg = bb.angka()
            # Mode yang seharusnya disebut DI SINI — di baris tempat tonasenya
            # diketahui. Operator tak perlu menghitung 23 ton itu lebih dekat
            # ke 25T atau 20T sambil berdiri di depan mesin.
            out.append({"value": d.id,
                        "label": (f"{d.nama} · {len(batches)} batch · {bb.teks()}"
                                  f" · pakai mode {mode_disarankan(kg)}")})
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
    from app.services.jasa import nama_pemilik_banyak

    async with SessionLocal() as db:
        peta = await nama_pemilik_banyak(db, {b.jasa_id for b in batches})
    return [{
        "value": b.kode_batch,
        # Pemiliknya di DEPAN label, bukan di belakang: daftar ini dibaca
        # sambil mencari satu baris, dan yang membedakan baris jasa dari baris
        # pabrik adalah pemiliknya — bukan kode batchnya.
        "label": ((f"{peta[b.jasa_id]} · " if b.jasa_id in peta else "")
                  + f"{b.kode_batch} · {b.kondisi_gabah} · "
                  f"{dari_batch(b).teks()} · "
                  + ("menunggu giliran giling" if b.jasa_id is not None
                     else "di tumpukan" if b.status_batch == DITUMPUK
                     else "belum ditempatkan")),
    } for b in batches]


# ══════════════════════════════════════════════════════════════════════════
# DAFTAR UNTUK RANTAI PERMINTAAN PK — supaya tak ada yang perlu DIKETIK
#
# Sampai 26 September 2026 kelima aksi rantai ini beriaian penunjuk bertipe
# `text`, dengan alasan yang tertulis di spesifikasinya: "ia SELALU dibuka dari
# kartu, yang sudah menyebut lot mana". Alasan itu salah dua kali.
#
# Pertama, penguncian-dari-kartu di `aksi.js` HANYA berlaku untuk isian bertipe
# pilihan (`select`/`remote`/`remote_banyak`) — isian teks tak pernah terisi
# apa pun. Jadi kartu memang mengirim `nilai`, dan borangnya tetap kosong.
# Pemilik menemukannya sambil berdiri memegang telepon: "kalau harus mengetik
# lot tentu sangat repot."
#
# Kedua, "selalu dari kartu" tak pernah benar: katalog "Catat pekerjaan lain"
# membuka aksi yang sama tanpa membawa apa-apa.
#
# Yang ketiga, dan paling buruk, tak terlihat dari layar operator: tiga aksi
# Admin meminta `permintaan` — ID BARIS BASIS DATA, angka yang tak pernah
# ditampilkan di mana pun. Admin tak punya cara mengetahuinya selain menebak.
# ══════════════════════════════════════════════════════════════════════════


def _label_permintaan(kode_lot: str, baris, lok: str = "") -> str:
    """Satu bentuk label untuk keempat daftar di bawah.

    Yang dibaca orang LOT-nya, bukan nomor barisnya — nomor baris cuma nilai
    yang dikirim. Daftar yang menampilkan "#7" menyuruh orang menghafal angka
    yang tak pernah ia lihat di tempat lain.
    """
    # Urutannya mengikuti umur angkanya: yang PALING AKHIR diketahui menang,
    # sebab itulah yang berlaku pada langkah ini. Yang belum diputuskan jatuh
    # ke `berat_minta_kg`, dan itu justru keadaan yang paling butuh angkanya —
    # daftar Admin untuk menyetujui. Tanpa itu barisnya cuma menyebut LOT, dan
    # Admin menebak batas atasnya (temuan QA 28 September 2026).
    kg = float(baris.berat_kirim_kg or baris.berat_setuju_kg
               or baris.berat_minta_kg or 0)
    diminta = (baris.berat_kirim_kg is None and baris.berat_setuju_kg is None
               and baris.berat_minta_kg is not None)
    bagian = [kode_lot]
    if kg:
        bagian.append(f"diminta {_rp(kg)} kg" if diminta else f"{_rp(kg)} kg")
    if lok:
        bagian.append(f"ke {lok}")
    return " · ".join(bagian)


async def _daftar_permintaan(keadaan, *, dengan_tujuan: bool = False) -> list[dict]:
    from sqlalchemy import select

    from app.models import MillingProcess, PermintaanPk

    async with SessionLocal() as db:
        baris = (await db.execute(
            select(PermintaanPk, MillingProcess.kode_proses)
            .join(MillingProcess,
                  MillingProcess.id == PermintaanPk.milling_process_id)
            .where(PermintaanPk.status.in_(keadaan))
            .order_by(PermintaanPk.waktu_minta)
        )).all()
        out = []
        for b, kode in baris:
            lok = ""
            if dengan_tujuan and b.tujuan:
                from app.penggilingan.gudang2.service import label_tujuan
                lok = await label_tujuan(db, b.tujuan, b.silo_id)
            out.append({"value": str(b.id),
                        "label": _label_permintaan(kode, b, lok)})
    return out


@router.get("/actions/pk-g1-tersedia")
async def pk_g1_tersedia(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Lot PK Gudang 1 yang masih ada sisanya, untuk operator Gudang 2.

    Yang sudah diminta orang lain TIDAK ditawarkan lagi: satu permintaan
    terbuka per lot dijaga indeks, dan menawarkan lot yang sudah diminta cuma
    melahirkan penolakan yang bisa dihindari sebelum orangnya menekan.

    ⚠ PK JASA JUSTRU DITAWARKAN — dan itu kebalikan dari dua picker PENJUALAN
    (`barang-bisa-keluar`, `pk-siap-keluar`) yang membuangnya. Bedanya bukan
    kelalaian: menyosoh barang pelanggan adalah PEKERJAAN YANG DIPESAN, dan
    jasa memang hidup sampai beras putih sejak migrasi 0065. Yang dilarang
    menjualnya, bukan memindahkannya.

    Tetapi pemiliknya DISEBUT di labelnya. Operator yang memindahkan tujuh ton
    tanpa tahu itu barang titipan akan memperlakukannya seperti stok pabrik di
    Gudang 2 — dan keputusan paling mahal di jalur ini (dijual atau
    dikembalikan) diambil berdasarkan label yang dibacanya di sini.
    """
    _require(await _is_g2_operator(user))
    from app.services.stok import pk_gudang1

    async with SessionLocal() as db:
        lot = await pk_gudang1(db)
    return [{"value": l.kode,
             "label": (f"{l.kode} · {_kg(l.tersedia)}"
                       + (f" · {l.kelas}" if l.kelas else "")
                       + (f" · {l.lama}" if l.lama else "")
                       + (f" · TITIPAN {l.pemilik}" if l.jasa_id else ""))}
            for l in lot if l.tersedia > 0 and not l.diminta_oleh]


@router.get("/actions/permintaan-diminta")
async def permintaan_menunggu_keputusan(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Permintaan yang menunggu keputusan Admin — untuk Setujui dan Tolak."""
    _require(can_transfer_pk(user))
    from app.models.permintaan import DIMINTA

    return await _daftar_permintaan((DIMINTA,))


@router.get("/actions/permintaan-disetujui")
async def permintaan_siap_dimuat(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Yang sudah disetujui dan tinggal dimuat — untuk operator Gudang 1.

    Pemiliknya berpindah bersama tombolnya (keputusan pemilik 27 September
    2026). Daftar yang tertinggal di tangan lama akan tetap menjawab, dan yang
    membacanya adalah orang yang pintunya justru menolak dia.
    """
    _require(await _is_g1_operator(user))
    from app.models.permintaan import DISETUJUI

    return await _daftar_permintaan((DISETUJUI,), dengan_tujuan=True)


@router.get("/actions/permintaan-dikirim")
async def permintaan_menunggu_ditutup(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Yang barangnya sudah berpindah dan tinggal ditutup Admin."""
    _require(can_transfer_pk(user))
    from app.models.permintaan import DIKIRIM

    return await _daftar_permintaan((DIKIRIM,), dengan_tujuan=True)


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
            batch, tempat, peringatan = await tempatkan(
                db, user=u, kode_batch=req.kode_batch, tujuan=jenis,
                dryer_id=mesin_id if jenis == "dryer" else None,
                silo_id=mesin_id if jenis == "silo" else None)
        except TumpukanError as e:
            raise _err(e, "Gagal menempatkan gabah.")
    pesan = f"✓ *{batch.kode_batch}* ditempatkan → {tempat}."
    if peringatan:
        pesan += "\n" + peringatan
    return {"ok": True, "pesan": pesan, "log_id": await _id_jejak(user.id)}


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


@router.get("/actions/proses-berjalan")
async def proses_berjalan(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Pengeringan & giling yang sedang jalan DAN belum berhenti.

    Digabung dalam satu daftar supaya operator tak perlu memilih jenis proses
    lebih dulu: yang berdiri di depan mesin tahu mesin mana yang berhenti,
    bukan istilah apa yang dipakai aplikasi untuknya.
    """
    _require(await _is_g1_operator(user))
    from sqlalchemy import select
    from app.models import DryingLot, MillingProcess
    from app.penggilingan.gudang1.services.jeda import jeda_terbuka
    keluar = []
    async with SessionLocal() as db:
        for lot in (await db.execute(
            select(DryingLot).where(DryingLot.status == "proses")
            .order_by(DryingLot.id.desc())
        )).scalars().all():
            if await jeda_terbuka(db, "pengeringan", lot.id) is None:
                keluar.append({"value": f"pengeringan:{lot.kode_lot}",
                               "label": f"{lot.kode_lot} · pengeringan"})
        for p in (await db.execute(
            select(MillingProcess).where(MillingProcess.status == "proses")
            .order_by(MillingProcess.id.desc())
        )).scalars().all():
            if await jeda_terbuka(db, "giling", p.id) is None:
                keluar.append({"value": f"giling:{p.kode_proses}",
                               "label": f"{p.kode_proses} · giling"})
    return keluar


@router.get("/actions/proses-berhenti")
async def proses_berhenti(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Yang sedang berhenti, berikut sebab & sejak kapan."""
    _require(await _is_g1_operator(user))
    from sqlalchemy import select
    from app.database import now_local
    from app.models import DryingLot, JedaProses, MillingProcess
    keluar = []
    async with SessionLocal() as db:
        kini = now_local()
        for j in (await db.execute(
            select(JedaProses).where(JedaProses.selesai.is_(None),
                JedaProses.dibatalkan_pada.is_(None),
                JedaProses.jenis.in_(("pengeringan", "giling")))
            .order_by(JedaProses.mulai)
        )).scalars().all():
            if j.jenis == "pengeringan":
                o = await db.get(DryingLot, j.drying_lot_id)
                kode = o.kode_lot if o else "?"
            else:
                o = await db.get(MillingProcess, j.milling_process_id)
                kode = o.kode_proses if o else "?"
            if o is None or o.status != "proses":
                continue
            jam = (kini - j.mulai).total_seconds() / 3600
            keluar.append({"value": f"{j.jenis}:{kode}",
                           "label": f"{kode} · {j.sebab} · {jam:.1f} jam"})
    return keluar


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


@router.get("/actions/silo-giling-terbuka")
async def silo_giling_terbuka(induk: str = "", user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Silo yang dipakai satu proses giling dan BELUM dibebaskan.

    `induk` = kode proses, dikirim klien dari medan di atasnya (`data-induk`).
    Kosong → daftar kosong, bukan seluruh silo — daftar yang menjawab tanpa
    tahu prosesnya menawarkan silo yang tak pernah dipakainya. Pola yang
    sama dengan `/actions/sosoh-silo` di Gudang 2.

    ⚠ Satu silo di SINI bisa punya BANYAK baris sumber (tiap pengisian
    melahirkan baris baru — beda dari Gudang 2, satu baris per silo), jadi
    labelnya MENJUMLAH seluruh baris yang masih terbuka untuk silo itu:
    membebaskannya nanti memang menutup semuanya sekaligus (lihat
    `milling.tutup_silo_giling`), jadi angka yang ditawarkan di sini harus
    sudah menjumlahkannya — bukan baris pertama yang kebetulan ditemukan.
    """
    _require(await _is_g1_operator(user))
    kode = (induk or "").strip()
    if not kode:
        return []
    from sqlalchemy import select

    from app.models import MillingProcess, MillingProcessSource, Silo, SiloStorage
    async with SessionLocal() as db:
        proc = (await db.execute(select(MillingProcess).where(
            MillingProcess.kode_proses == kode))).scalars().first()
        if proc is None:
            return []
        baris = (await db.execute(
            select(MillingProcessSource, Silo)
            .join(SiloStorage, SiloStorage.id == MillingProcessSource.silo_storage_id)
            .join(Silo, Silo.id == SiloStorage.silo_id)
            .where(MillingProcessSource.milling_process_id == proc.id,
                  MillingProcessSource.berat_akhir_kg.is_(None))
            .order_by(Silo.nama_silo)
        )).all()
    jumlah: dict[str, float] = {}
    tahu: dict[str, bool] = {}
    for s, silo in baris:
        huruf = (silo.nama_silo or "").replace("Silo ", "").strip()
        jumlah[huruf] = jumlah.get(huruf, 0.0) + float(s.berat_kg or 0)
        tahu[huruf] = tahu.get(huruf, True) and s.berat_kg is not None
    return [{"value": h, "label": (f"Silo {h} · {_rp(jumlah[h])} kg" if tahu[h]
                                   else f"Silo {h} · ⚠️ bobot belum ada")}
           for h in sorted(jumlah)]


@router.get("/actions/silo-g1-tambah")
async def silo_g1_tambah(induk: str = "", user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Silo Gudang 1 yang BISA ditambahkan ke proses giling `induk` —
    kebalikan `/actions/silo-giling-terbuka` (yang menawarkan silo yang
    SUDAH jadi sumber). Berisi, dan belum jadi sumber proses mana pun yang
    sedang berjalan (termasuk proses ini sendiri).

    ⚠ Gerbang "berisi" memakai `_silo_active_rows` (baris ADA atau tidak),
    BUKAN `_silo_content_kg(...) <= 0` (keputusan pemilik kedua, 9 Oktober
    2026 — laporan lapangan "gabah yang baru datang tidak bisa ditambahkan
    ke giling yang berjalan"). `_silo_content_kg` cuma angka yang DIKETAHUI
    saja (lihat docstringnya): gabah yang baru dituang dan belum sempat
    ditimbang kedua kalinya punya bobot `tak_diketahui`, bukan nol — tapi
    `_silo_content_kg`-nya tetap 0 sampai timbangan kedua itu ada. Memakainya
    sebagai PAGAR (bukan cuma label) membuat silo yang genuinely berisi
    gabah segar terlihat kosong dan hilang dari daftar ini, persis gejala
    yang dilaporkan. Sebangun `/actions/silo-siap-giling`, yang sudah benar
    sejak awal — picker ini satu-satunya yang salah meniru pola `<= 0`.
    """
    _require(await _is_g1_operator(user))
    kode = (induk or "").strip()
    if not kode:
        return []
    from sqlalchemy import select

    from app.models import MillingProcess
    from app.penggilingan.gudang1.services.silo import (
        _silo_active_rows, _silo_content_kg, giling_berjalan_untuk_silo, silos_g1)
    async with SessionLocal() as db:
        proc = (await db.execute(select(MillingProcess).where(
            MillingProcess.kode_proses == kode))).scalars().first()
        if proc is None:
            return []
        out = []
        for si in await silos_g1(db):
            if not await _silo_active_rows(db, si.id):
                continue
            jalan = await giling_berjalan_untuk_silo(db, si.id)
            if jalan is not None:
                continue
            huruf = si.nama_silo.replace("Silo ", "")
            kg = await _silo_content_kg(db, si.id)
            out.append({"value": huruf,
                        "label": (f"Silo {huruf} · {_rp(kg)} kg" if kg > 0
                                 else f"Silo {huruf} · ⚠️ bobot belum ada")})
    return out


class TambahSiloGilingReq(BaseModel):
    kode_proses: str
    silo: str


@router.post("/actions/tambah-silo-giling")
async def act_tambah_silo_giling(req: TambahSiloGilingReq,
                                 user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g1_operator(user))
    if not (req.kode_proses or "").strip():
        raise HTTPException(400, "Pilih proses gilingnya dulu.")
    if not (req.silo or "").strip():
        raise HTTPException(400, "Pilih silo yang ditambahkan dulu.")
    from app.penggilingan.gudang1.services.milling import MillingError, tambah_silo_giling
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await tambah_silo_giling(db, user=u, kode_proses=req.kode_proses,
                                         nama_silo=req.silo.upper())
        except MillingError as e:
            raise _err(e, "Gagal menambah silo.")
    pesan = (f"✓ Silo {r.nama_silo} ditambahkan ke *{r.proc.kode_proses}* "
             f"(+{r.bertambah:,.0f} kg) — bahan kini {r.proc.berat_gabah_masuk_kg:,.0f} kg."
             .replace(",", "."))
    return {"ok": True, "pesan": pesan}


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
    from app.models import Silo
    from app.penggilingan.gudang1.services.silo import (
        _g1_warehouse_id, _silo_active_rows, _silo_content_kg,
        giling_berjalan_untuk_silo)
    out: list[dict] = []
    async with SessionLocal() as db:
        wid = await _g1_warehouse_id(db)
        silos = (
            await db.execute(
                select(Silo).where(Silo.warehouse_id == wid, Silo.aktif.is_(True)).order_by(Silo.nama_silo)
            )
        ).scalars().all()
        for s in silos:
            rows = await _silo_active_rows(db, s.id)
            if not rows:
                continue
            # "Ada di antara sumber proses yang berjalan" — bukan `silo_id`.
            # Borang yang menawarkan silo yang gabahnya sudah di mesin adalah
            # borang yang mengizinkan giling kedua atas muatan yang sama.
            if await giling_berjalan_untuk_silo(db, s.id) is not None:
                continue
            letter = s.nama_silo.replace("Silo ", "")
            kg = await _silo_content_kg(db, s.id)
            # Pemiliknya disebut: menggiling silo berisi barang pelanggan sah
            # (pesanannya memang harus digiling) tetapi ia keputusan yang berbeda
            # dari menggiling gabah pabrik — rendemennya akan ditunjukkan kepada
            # orang yang membawa barangnya.
            pemilik = await _pemilik_isi_silo(db, s.id)
            out.append({"value": letter,
                        "label": f"Silo {letter} · {_rp(kg)} kg"
                                 + (f" · {pemilik}" if pemilik else "")})
    return out


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
    from app.models import FinishedGoodsStock, PolishingProcess, ProductSku
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
    """PK luar yang sudah tercatat MASUK tapi belum punya baris intake.

    ⚠ "Diterima" BUKAN "sudah di-QC" — `status_batch="diterima"` disetel
    `catat_pk_luar` saat PK dicatat datang, bukan oleh QC. Jadi batch ini bisa
    (dan biasa) muncul di sini SEBELUM lab mengisi kualitasnya. Itu disengaja,
    bukan cacat: PK yang sudah turun dari truk harus punya tempat; menahannya
    sampai lab selesai berarti PK menginap di truk. Lihat `log_pk_qc` untuk
    bagaimana potongan QC yang menyusul tetap sampai ke stok."""
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
             "label": f"{b.kode_batch} · {dari_batch(b).teks()}"}
            for b in rows]


@router.get("/actions/giling-tak-cocok")
async def giling_tak_cocok_pilihan(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Giling selesai yang bobot masuknya tak cocok dengan bahannya sekarang —
    daftar yang sama dengan rekonsiliasi butir ⑪, supaya yang dibaca admin
    dan yang bisa ia betulkan tak pernah berbeda."""
    _require(can_see_financials(user))
    from app.penggilingan.gudang1.services.koreksi_bobot import giling_tak_cocok
    async with SessionLocal() as db:
        rows = await giling_tak_cocok(db)
    return [{"value": r["kode_proses"],
             "label": (f"{r['kode_proses']} · tercatat {_rp(float(r['tercatat_kg'] or 0))} kg"
                       f" → bahannya {_rp(float(r['seharusnya_kg'] or 0))} kg"
                       f" ({float(r['kurang_persen'] or 0):+.1f}%)")}
            for r in rows]


@router.get("/actions/milling-unverified")
async def milling_unverified(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Milling SELESAI — yang belum diverifikasi lebih dulu, sisanya menyusul.

    Dulu hanya yang BELUM diverifikasi. Itu bertentangan dengan aksinya sendiri:
    `verify_milling_output` memang mendukung verifikasi ulang (`re_verified`),
    dan labelnya pun berbunyi "Giling yang sudah selesai".

    Akibatnya bukan cuma daftar yang kurang. Kartu Stok membuka aksi ini dengan
    penunjuk TERKUNCI, dan `aksi.js` melepas kuncinya bila nilainya tak ada di
    daftar — perlindungan yang benar untuk baris antrean yang sudah basi. Lot
    yang baru saja diverifikasi langsung keluar dari daftar, jadi koreksi kedua
    justru disuguhi tarik-turun: "mengapa harus memilih lagi?" Yang sudah
    ditunjuk kartunya tak boleh ditanyakan lagi.

    Yang belum diverifikasi tetap di ATAS, karena itu yang biasanya dicari.
    Tanpa penanda pada labelnya: `aksi.js` memakai label yang sama untuk teks
    TERKUNCI di dalam lembar, dan di sana "· sudah diverifikasi" cuma
    kebisingan pada benda yang sudah jadi pokok bahasannya.
    """
    _require(can_see_financials(user))
    from sqlalchemy import case, exists, select
    from app.models import MillingProcess, MillingProcessVerification
    async with SessionLocal() as db:
        sudah = exists().where(
            (MillingProcessVerification.milling_process_id == MillingProcess.id)
            & (MillingProcessVerification.berat_output_final_kg.is_not(None))
        )
        baris = (
            await db.execute(
                select(MillingProcess.kode_proses, sudah.label("sudah"))
                .where(MillingProcess.status == "selesai")
                .order_by(case((sudah, 1), else_=0),
                          MillingProcess.kode_proses.desc())
            )
        ).all()
    return [{"value": k, "label": k} for k, _ in baris]


@router.get("/actions/milling-noqc")
async def milling_noqc(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Giling yang bisa dinilai mutunya — yang SEDANG BERJALAN lebih dulu.

    Dulu hanya yang belum punya catatan QC sama sekali. Itu menutup KOREKSI:
    mutu yang salah ketik tak bisa dibetulkan lewat daftar ini, dan — sama
    persis dengan `milling_unverified` — penguncian penunjuk dari kartu Stok
    ikut terlepas begitu satu lot punya QC, karena `aksi.js` melepas kunci bila
    nilainya tak ada di daftarnya.

    Dan dulu hanya yang SELESAI. Keputusan pemilik 24 September 2026: mutu juga
    dicatat selagi mesin jalan, dari kartu prosesnya, lalu hasilnya dirata-rata —
    contohnya memang diambil dari beras yang baru keluar mesin, bukan dari
    tumpukan yang sudah ditutup berjam-jam sebelumnya.

    Urutannya: yang sedang berjalan di atas (di situlah orangnya berdiri saat
    mencatat), lalu yang selesai tetapi belum dinilai, lalu sisanya.
    """
    _require(can_see_financials(user))
    await _wajib_mutu()
    from sqlalchemy import case, exists, func, select
    from app.models import MillingProcess, MillingQcLog
    async with SessionLocal() as db:
        ada_qc = exists().where(MillingQcLog.milling_process_id == MillingProcess.id)
        jalan = MillingProcess.status == "proses"
        n_qc = (select(func.count()).select_from(MillingQcLog)
                .where(MillingQcLog.milling_process_id == MillingProcess.id)
                .scalar_subquery())
        baris = (
            await db.execute(
                select(MillingProcess.kode_proses, jalan.label("jalan"), n_qc.label("n"))
                .where(MillingProcess.status.in_(("proses", "selesai")))
                .order_by(case((jalan, 0), (ada_qc, 2), else_=1),
                          MillingProcess.kode_proses.desc())
            )
        ).all()
    return [{"value": k,
             "label": k + (" · sedang digiling" if j else "")
                        + (f" · {n} catatan mutu" if n else "")}
            for k, j, n in baris]


@router.get("/actions/pk-luar-qc")
async def pk_luar_qc(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """PK luar boleh dicatat berulang; batch yang sudah punya QC tetap ditawarkan."""
    _require(can_see_financials(user))
    await _wajib_mutu()
    from sqlalchemy import case, func, select
    from app.models import PkPurchaseBatch, PkPurchaseQcLog
    n = (select(func.count()).select_from(PkPurchaseQcLog)
         .where(PkPurchaseQcLog.pk_purchase_batch_id == PkPurchaseBatch.id).scalar_subquery())
    async with SessionLocal() as db:
        rows = (await db.execute(select(PkPurchaseBatch, n.label("n"))
            .where(PkPurchaseBatch.status_batch.in_(("diterima", "di_silo", "ditumpuk", "disosoh")))
            .order_by(case((n == 0, 0), else_=1), PkPurchaseBatch.id.desc()))).all()
    return [{"value": b.kode_batch,
             "label": f"{b.kode_batch} · {dari_batch(b).teks()}" + (f" · {jumlah} putaran QC" if jumlah else " · belum ada QC")}
            for b,jumlah in rows]


# ─────────────────────── Aksi cepat: eksekusi (POST) ───────────────────────

class GabahMasukReq(BaseModel):
    # Operator hanya memilih TIKET TIMBANG aktif — supplier/bobot/nopol dari timbang.
    timbangan_transaksi_id: int
    tujuan: str | None = None       # dryer / silo_a / silo_b
    kondisi: str | None = None      # opsional; diturunkan dari jenis timbang bila kosong
    #: Kunci kiriman (Tahap 3): klien yang mengirim ulang kiriman yang sama
    #: mendapat batch yang sama, bukan galat. Opsional — klien lama tak
    #: mengirimnya dan tetap dilayani.
    kunci_kiriman: str | None = None


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


@router.get("/actions/tujuan-gabah")
async def tujuan_gabah(induk: str = "", user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Pilihan mengikuti jenis tiket, sehingga gabah basah tidak ditawari silo."""
    _require(await _is_g1_operator(user))
    if not induk:
        return []
    from app.penggilingan.gudang1.services.timbang_link import ambil_tiket
    from app.penggilingan.peta_jenis import intake_dari_jenis

    try:
        tiket_id = int(induk)
    except ValueError:
        raise HTTPException(400, "Pilih tiket timbang gabah yang sah.")
    async with SessionLocal() as db:
        tiket = await ambil_tiket(db, tiket_id)
    info = intake_dari_jenis(tiket.get("jenis_kode", "")) if tiket else None
    if info is None or info.model != "gabah":
        raise HTTPException(400, "Tiket ini bukan gabah masuk.")
    tujuan_sah = {"dryer"} if info.kondisi == "basah" else {"dryer", "silo"}
    return [{"value": nilai, "label": nama}
            for nilai, nama in await _pilihan_tujuan_gabah(info.kondisi)
            if _urai_tujuan(nilai)[0] in tujuan_sah]


@router.post("/actions/gabah-masuk")
async def act_gabah_masuk(req: GabahMasukReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g1_operator(user))

    from app.penggilingan.peta_jenis import intake_dari_jenis
    from app.penggilingan.gudang1.services.purchase import create_purchase_batch_dari_timbang
    from app.penggilingan.gudang1.services.timbang_link import ambil_tiket
    from app.penggilingan.gudang1.services.drying import masuk_dryer, DryingError
    from app.penggilingan.gudang1.services.silo import masuk_silo, SiloError, silo_g1_by_id
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
        # Tiket JASA dikenali lewat satu penolong (`adalah_jasa`, dasarnya
        # `t.jasa`) — bukan dengan memeriksa kolomnya sendiri di sini.
        from app.penggilingan.gudang1.services.timbang_link import adalah_jasa
        _tiket_jasa = adalah_jasa(tiket)
        mesin_id = None
        if info.tujuan_wajib:
            tujuan = info.tujuan_wajib
        else:
            tujuan, mesin_id = _urai_tujuan(req.tujuan)
            if tujuan not in info.tujuan_pilihan:
                # Pesannya menyebut yang SAH untuk gabah ini, bukan daftar
                # umum: operator yang memilih Silo untuk gabah basah perlu
                # tahu kenapa ditolak, bukan sekadar bahwa ia ditolak.
                # Kuncinya JENIS tujuannya ("dryer" / "silo" / "tumpuk"),
                # bukan nama silo. Dua kunci lama (`silo_a`, `silo_b`) tak
                # pernah bisa cocok — `tujuan_pilihan` tak memuatnya — jadi
                # gabah kering yang ditolak berbunyi "hanya boleh ke: silo /
                # Dryer / Tumpukan", satu kata kecil di antara dua kata besar.
                nama = {"dryer": "Dryer", "silo": "Silo gabah kering",
                        "tumpuk": "Tumpukan"}
                boleh = " / ".join(nama.get(t, t) for t in info.tujuan_pilihan)
                raise HTTPException(400, f"Gabah {kondisi} hanya boleh ke: {boleh}.")
        # PRA-PERIKSA sebelum batch dibuat.
        #
        # Penempatan berjalan SETELAH batch tercatat, dan penolakannya di sana
        # hanya jadi peringatan: gabahnya sudah turun dari truk, jadi
        # catatannya memang harus tetap ada. Tetapi menolak lebih awal untuk
        # hal yang sudah pasti salah menghemat satu pembersihan manual — dan
        # gabah kering yang dikirim ke mesin berisi gabah basah adalah hal
        # yang sudah pasti salah, bukan kebetulan yang bisa jadi benar.
        # Gabah basah JASA tak boleh ditumpuk — ditolak SEBELUM batch dibuat,
        # sebab sesudahnya penempatan cuma jadi peringatan dan gabahnya
        # tertinggal di lantai. Penjaga sungguhannya di `masuk_tumpukan`; yang
        # di sini membuat penolakannya datang saat masih bisa dialihkan.
        if tujuan == "tumpuk" and kondisi == "basah" and _tiket_jasa:
            raise HTTPException(
                400,
                "Gabah basah JASA tidak boleh menumpuk — harus langsung ke "
                "pengering. Basah yang menunggu akan rusak, dan ini barang "
                "titipan pelanggan.")
        if tujuan == "dryer" and mesin_id:
            from app.penggilingan.gudang1.services.drying import isi_dryer
            ada = await isi_dryer(db, mesin_id)
            if ada and ada[0] != kondisi:
                raise HTTPException(
                    400,
                    f"❌ Mesin itu berisi gabah {ada[0]} ({ada[1]:,.0f} kg)"
                    .replace(",", ".")
                    + f" — gabah {kondisi} tidak boleh dicampur ke dalamnya. "
                    "Kosongkan mesinnya ke silo dulu, atau pilih tujuan lain.",
                )
        # Pemeriksaan tujuan yang sama harus mendahului commit penerimaan.
        # Silo yang hilang/nonaktif tidak boleh menghasilkan HTTP gagal dengan
        # batch yang sudah tercatat. Kegagalan penempatan sesudah penerimaan
        # tetap mengikuti penanganan peringatan lama.
        if tujuan == "silo":
            si = await silo_g1_by_id(db, mesin_id) if mesin_id else None
            if si is None:
                raise HTTPException(400, "Pilih silo tujuannya dulu.")
        try:
            r = await create_purchase_batch_dari_timbang(
                db, user=u, timbangan_transaksi_id=req.timbangan_transaksi_id,
                kondisi_gabah=kondisi, kunci_kiriman=(req.kunci_kiriman or "")[:120] or None,
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
                # ⚠ Dulu 🌫️ (kabut) — ikon yang sah di Unicode tapi tak
                # bergambar di sebagian ponsel (ketahuan lapangan 5 Oktober
                # 2026: kotak kosong di antara dua baris pesan, bukan galat
                # logika). Diganti 🔥, sudah terbukti aman — dipakai juga
                # di label "Mulai pengeringan" tanpa keluhan.
                tempat = (f"🔥 masuk {nama_mesin} (menunggu — tekan "
                          "`Mulai pengeringan` saat dipanaskan)")
            else:  # silo (kering langsung)
                r_silo = await masuk_silo(
                    db, user=u, nama_silo=si.nama_silo.replace("Silo ", ""),
                    kode_lot=None, kode_batch=kode)
                tempat = (f"🏗️ masuk {si.nama_silo} (kering menunggu — "
                          "lot terbentuk saat digiling)")
                # Arah sebaliknya dari `pindah_silo`, dan sampai sekarang
                # DIAM: gabah beli kering menyusul masuk ke silo yang sudah
                # berisi hasil pengeringan sendiri, tanpa satu kalimat pun.
                if r_silo.campur_asal:
                    warn += ("\n⚠️ Silo itu berisi hasil pengeringan sendiri "
                             f"({r_silo.isi_sebelumnya}) — kini tercampur "
                             "dengan gabah beli kering, dan digiling sebagai "
                             "SATU proses.")
                elif r_silo.digabung:
                    warn += (f"\n⚠️ Silo itu sudah berisi {r_silo.isi_sebelumnya} "
                             "— isinya kini tercampur.")
                if r_silo.giling_berjalan:
                    warn += (f"\n⚠️ {si.nama_silo} sedang digiling "
                             f"({r_silo.giling_berjalan}) — gilingnya tetap "
                             "jalan, dan gabah ini masuk sebagai bahan "
                             f"tambahannya (+{r_silo.kg_baris:,.0f} kg)."
                             .replace(",", "."))
        except (DryingError, SiloError) as e:
            warn = f"\n⚠️ Belum ditempatkan: {e.args[0] if e.args else 'gagal'}. Tempatkan manual."

    # Pesanan jasa DISEBUT, dan kodenya disebut terutama saat ia baru lahir:
    # nomor itulah yang pelanggan tanyakan nanti, dan satu-satunya kesempatan
    # operator membacanya tanpa membuka layar lain adalah di kalimat ini.
    milik = ""
    if r.jasa is not None:
        milik = (f" — JASA, pesanan baru *{r.jasa.kode}*" if r.jasa_baru
                 else f" — JASA, masuk pesanan *{r.jasa.kode}*")
    # ⚠ `tempat` SENGAJA tak ikut kabar ini — cacat lapangan 10 Oktober 2026:
    # kabar aksi satu-ketuk (`kabarBisaBatal`, beda dari `kabar()` biasa)
    # membawa kalimat PENUH apa adanya, dan `tempat` ("🔥 masuk Dryer 1
    # (menunggu — tekan `Mulai pengeringan` saat dipanaskan)") membuatnya
    # cukup panjang untuk melipat jadi satu-kata-per-baris di layar sempit —
    # masalah tata letak, bukan logika. `tempat` sendiri redundan di sini:
    # ke mana gabahnya masuk sudah terbaca di kartu Antrian tunggu begitu
    # layarnya digambar ulang (`muat()`, dipanggil SEBELUM kabar ini
    # tampil) — sama seperti alasan `kabar()` biasa tak pernah menumpahkan
    # kalimat server. `warn` TETAP ikut: itu bukan rute normal, dan
    # operator perlu tahu SEGERA, bukan menebak dari kartu.
    pesan = f"✓ Gabah *{kode}* ({kondisi}) tercatat{milik}." + warn
    return {"ok": True, "pesan": pesan, "log_id": await _id_jejak(user.id)}


class KadarAirReq(BaseModel):
    kode_lot: str
    #: Empat titik alat tes. Hanya titik 1 yang wajib — kalau alatnya rusak
    #: atau muatannya kecil, memaksa empat angka berarti memaksa operator
    #: mengarang tiga di antaranya, dan catatan karangan lebih buruk daripada
    #: catatan yang kurang lengkap.
    #: Bentuk BARU — daftar, sebanyak titik yang benar-benar diukur.
    tes: list[Persen] | None = None
    #: Bentuk LAMA — empat kolom bernomor. Dipertahankan karena skrip dan
    #: tautan tersimpan masih mengirimnya; keduanya digabung di endpoint.
    tes_1: PersenOpsional = None
    tes_2: PersenOpsional = None
    tes_3: PersenOpsional = None
    tes_4: PersenOpsional = None
    #: Yang terbaca di mesin. Tidak ikut dirata-ratakan.
    indikator: PersenOpsional = None
    #: Target boleh diubah sambil mencatat kadar air.
    target_baru: PersenOpsional = None
    #: Bentuk LAMA — satu angka. Dipertahankan supaya pemanggil lama (bot,
    #: tautan tersimpan) tidak patah; diperlakukan sebagai bacaan mesin,
    #: persis seperti dulu.
    kadar_air: PersenOpsional = None


@router.post("/actions/kadar-air")
async def act_kadar_air(req: KadarAirReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g1_operator(user))
    if not (req.kode_lot or "").strip():
        raise HTTPException(400, "Pilih pengeringan dulu.")
    from app.penggilingan.gudang1.services.drying import log_moisture
    # Daftar baru menang bila ada; kalau tidak, empat kolom lama dipakai.
    # Keduanya tak pernah digabung — dua sumber untuk satu angka berarti satu
    # kiriman bisa menghasilkan delapan titik dari empat tusukan.
    sampel = ([x for x in req.tes if x is not None] if req.tes
              else [req.tes_1, req.tes_2, req.tes_3, req.tes_4])
    indikator = req.indikator if req.indikator is not None else req.kadar_air
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await log_moisture(db, user=u, kode_lot=req.kode_lot,
                                   indikator=indikator, sampel=sampel,
                                   target_baru=req.target_baru)
        except Exception as e:  # noqa: BLE001
            raise _err(e, "Gagal update kadar air.")

    bagian = []
    if r.rata_tes is not None:
        n = len([x for x in sampel if x is not None])
        bagian.append(f"alat tes {r.rata_tes:.1f}% (rata-rata {n} titik)")
    if r.indikator is not None:
        bagian.append(f"mesin {r.indikator:g}%")
    pesan = f"✓ Kadar air *{req.kode_lot}*: " + " · ".join(bagian) + "."
    # Sebaran & selisih disebut hanya bila ADA artinya — angka tambahan yang
    # selalu muncul cepat berubah jadi latar yang tak dibaca siapa pun.
    from app.penggilingan.gudang1.services.drying import (
        AMBANG_SEBAR, AMBANG_SELISIH_MESIN)

    if r.sebar is not None and r.sebar >= AMBANG_SEBAR:
        pesan += (f"\n⚠️ Sebaran {r.sebar:.1f}% antara titik terendah & tertinggi "
                  f"— gabah belum kering merata.")
    if r.target_lama is not None:
        pesan += (f"\n↻ Target diubah {r.target_lama:g}% → {r.target_kini:g}%.")
    elif r.target_kini is not None:
        pesan += f" Target {r.target_kini:g}%."
    if r.selisih_mesin is not None and abs(r.selisih_mesin) >= AMBANG_SELISIH_MESIN:
        pesan += (f"\n⚠️ Mesin membaca {r.selisih_mesin:+.1f}% dari alat tes "
                  f"— periksa sensor dryer bila terus begini.")
    return {"ok": True, "pesan": pesan}


class HasilGilingReq(BaseModel):
    kode_proses: str
    berat_kumulatif: Positif


@router.post("/actions/hasil-giling")
async def act_hasil_giling(req: HasilGilingReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g1_operator(user))
    if not (req.kode_proses or "").strip():
        raise HTTPException(400, "Pilih proses giling dulu.")
    from app.penggilingan.gudang1.services.milling import log_progress
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await log_progress(db, user=u, kode_proses=req.kode_proses,
                                   berat_kumulatif=req.berat_kumulatif)
        except Exception as e:  # noqa: BLE001
            raise _err(e, "Gagal update hasil giling.")
    pesan = f"✓ Hasil giling *{req.kode_proses}*: {req.berat_kumulatif:g} kg (kumulatif)."
    if r.peringatan:
        pesan += "\n" + r.peringatan
    return {"ok": True, "pesan": pesan}


class MulaiPengeringanReq(BaseModel):
    dryer_id: int | None = None
    #: Sampai berapa muatan ini dikeringkan. Bisa berbeda antar muatan, jadi
    #: ditanyakan tiap kali — bukan diambil diam-diam dari setelan aplikasi.
    target_kadar_air: PersenOpsional = None
    #: Mode yang DISETEL DI MESIN. Konfirmasi, bukan perintah: aplikasi ini
    #: tidak tersambung ke dryer.
    mode_dryer: str | None = None


@router.post("/actions/mulai-pengeringan")
async def act_mulai_pengeringan(req: MulaiPengeringanReq | None = None,
                                user: User = Depends(pengguna_aksi)) -> dict:
    """Gabungkan gabah yang menunggu di SATU mesin jadi 1 pengeringan."""
    _require(await _is_g1_operator(user))
    from app.penggilingan.gudang1.services.drying import start_drying, DryingError
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await start_drying(
                db, user=u,
                dryer_id=(req.dryer_id if req else None),
                target_kadar_air=(req.target_kadar_air if req else None),
                mode_dryer=(req.mode_dryer if req else None),
            )
        except DryingError as e:
            raise _err(e, "Gagal mulai pengeringan.")
    pesan = (f"✓ Pengeringan *{r.lot.kode_lot}* mulai — {r.kondisi}, "
             f"{len(r.batch_kodes)} batch ({r.total_kg:g} kg).")
    setelan = []
    if r.lot.mode_dryer:
        setelan.append(f"mode {r.lot.mode_dryer}")
    if r.lot.target_kadar_air is not None:
        setelan.append(f"target {float(r.lot.target_kadar_air):g}%")
    if setelan:
        pesan += "\n" + " · ".join(setelan) + "."
    if r.peringatan:
        pesan += f"\n{r.peringatan}"
    return {"ok": True, "pesan": pesan}


class KodeLotReq(BaseModel):
    kode_lot: str


class SelesaiPengeringanReq(BaseModel):
    """Model sendiri, bukan `KodeLotReq` yang dipakai bersama aksi lain.

    `kadar_air` wajib di sini dan tidak di sana, jadi menumpangkannya pada
    model bersama akan membuat aksi-aksi lain diam-diam menerima medan yang
    tak berlaku bagi mereka.
    """

    kode_lot: str
    kadar_air: PersenOpsional = None


class UbahTargetReq(BaseModel):
    kode_lot: str
    target: float | None = None


@router.post("/actions/ubah-target")
async def act_ubah_target(req: UbahTargetReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g1_operator(user))
    if not (req.kode_lot or "").strip():
        raise HTTPException(400, "Pilih pengeringan dulu.")
    from app.penggilingan.gudang1.services.drying import ubah_target, DryingError
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            lot, lama = await ubah_target(db, user=u, kode_lot=req.kode_lot,
                                          target=req.target)
        except DryingError as e:
            raise _err(e, "Gagal mengubah target kadar air.")
    # Angka LAMA ikut disebut. "Target jadi 15%" tak memberi tahu apakah
    # garisnya bergeser jauh atau sedikit — dan yang baru menggesernya berhak
    # melihat seberapa jauh ia baru saja bergeser.
    dari = f" (dari {lama:g}%)" if lama is not None else ""
    return {"ok": True,
            "pesan": (f"✓ Target *{req.kode_lot}* jadi "
                      f"{float(lot.target_kadar_air):g}%{dari}.")}


@router.post("/actions/selesai-pengeringan")
async def act_selesai_pengeringan(
    req: SelesaiPengeringanReq, user: User = Depends(pengguna_aksi)
) -> dict:
    _require(await _is_g1_operator(user))
    if not (req.kode_lot or "").strip():
        raise HTTPException(400, "Pilih pengeringan dulu.")
    from app.penggilingan.gudang1.services.drying import finish_drying, DryingError
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            lot, jam = await finish_drying(db, user=u, kode_lot=req.kode_lot,
                                           kadar_air_akhir=req.kadar_air)
        except DryingError as e:
            raise _err(e, "Gagal menyelesaikan pengeringan.")
    # Angkanya diulang di balasan. Yang baru mengetiknya sedang berdiri di
    # depan mesin dan bisa membandingkan langsung dengan layar dryer — salah
    # ketik satu digit paling murah ketahuannya justru pada detik ini.
    ka = f" · kadar air {req.kadar_air:g}%" if req.kadar_air is not None else ""
    pesan = (f"✓ Pengeringan *{req.kode_lot}* selesai ({jam:.0f} jam{ka}) → "
             "fase pendinginan. Nyatakan pendinginan selesai saat sudah dingin.")
    return {"ok": True, "pesan": pesan}


@router.post("/actions/mulai-pendinginan-ulang")
async def act_mulai_pendinginan_ulang(req: KodeLotReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g1_operator(user))
    from app.penggilingan.gudang1.services.drying import mulai_pendinginan_ulang, DryingError
    async with SessionLocal() as db:
        try:
            await mulai_pendinginan_ulang(db, user=await db.get(User, user.id), kode_lot=req.kode_lot)
        except DryingError as e:
            raise _err(e, "Gagal memulai pendinginan ulang.")
    return {"ok": True, "pesan": "Pendinginan ulang dimulai. Nyatakan sudah dingin sebelum pindah ke silo."}


@router.post("/actions/selesai-pendinginan")
async def act_selesai_pendinginan(req: KodeLotReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g1_operator(user))
    if not (req.kode_lot or "").strip():
        raise HTTPException(400, "Pilih pengeringan yang didinginkan dulu.")
    from app.penggilingan.gudang1.services.drying import finish_cooling, DryingError
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            lot, jam = await finish_cooling(db, user=u, kode_lot=req.kode_lot)
        except DryingError as e:
            raise _err(e, "Gagal menyatakan pendinginan selesai.")
    pesan = (f"✓ Pendinginan *{req.kode_lot}* selesai ({jam:.0f} jam) — dryer idle. "
             "Pindahkan ke silo saat ada silo kosong.")
    return {"ok": True, "pesan": pesan}


class PindahSiloReq(BaseModel):
    kode_lot: str
    silo: str  # A / B


@router.post("/actions/pindah-silo")
async def act_pindah_silo(req: PindahSiloReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g1_operator(user))
    if not (req.kode_lot or "").strip():
        raise HTTPException(400, "Pilih pengeringan yang mau dipindah dulu.")
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
    pesan = (f"✓ Pengeringan *{req.kode_lot}* dipindah → Silo {r.nama_silo} ({r.kg:g} kg). "
             "Dryer kosong, siap digiling.")
    if r.digabung:
        # Bukan penolakan: gabahnya harus keluar dari dryer, dan menahannya
        # sampai silo kosong justru memacetkan pengeringan berikutnya. Tetapi
        # isinya kini campuran, dan itu harus terbaca — bukan diketahui
        # belakangan saat angka giling tidak seperti yang diingat orang.
        pesan += (f"\n⚠️ Silo sudah berisi {r.isi_sebelumnya} — "
                  "isinya kini tercampur. Semuanya digiling sebagai SATU proses.")
    if r.campur_asal:
        # Beda derajat, bukan beda jenis: dua lot pengeringan yang menumpuk
        # masih satu asal, sedangkan hasil pengeringan sendiri yang bertemu
        # gabah beli kering menghapus batas yang paling ingin dilihat pemilik.
        pesan += ("\n⚠️ Hasil pengeringan sendiri kini satu silo dengan gabah "
                  "yang DIBELI kering. Pastikan itu memang yang dikehendaki.")
    if r.giling_berjalan:
        pesan += (f"\n⚠️ Silo {r.nama_silo} sedang digiling ({r.giling_berjalan}) — "
                  "gilingnya tetap jalan, dan gabah ini masuk sebagai bahan "
                  f"tambahannya (+{r.kg_baris:,.0f} kg).".replace(",", "."))
    return {"ok": True, "pesan": pesan}


# ═════════════ Gabah kering dikemas & ditimbang (pesan kerja 7 Oktober 2026
# butir 6) — jalan keluar KEEMPAT dari silo Gudang 1, sebangun `pk_langsung`.
# Gabah TETAP bahan: tanpa SKU, tanpa ukuran karung, satu angka bobot global
# dari timbangan. Lihat `gabah_kering.py` untuk alasan lengkapnya. ═════════

@router.get("/actions/silo-g1-isi-untuk-kemasan")
async def silo_g1_isi_untuk_kemasan(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Baris isi silo Gudang 1 yang masih punya sisa untuk dikemas+ditimbang.

    Per BARIS (`silo_storage_id`), bukan per silo — satu silo bisa punya
    beberapa baris aktif (gabah kering yang menumpuk, tiap batch satu
    baris), dan operator perlu memilih YANG MANA, bukan cuma silo mana.
    """
    _require(await _is_g1_operator(user))
    from app.penggilingan.gudang1.services.silo import (
        _row_kg, _silo_active_rows, silos_g1)
    from app.services.jasa import nama_pemilik

    out = []
    async with SessionLocal() as db:
        for si in await silos_g1(db):
            for row in await _silo_active_rows(db, si.id):
                kg = await _row_kg(db, row)
                if kg <= 0.5:
                    continue
                pemilik = await nama_pemilik(db, row.jasa_id)
                out.append({
                    "value": str(row.id),
                    "label": (f"{si.nama_silo} · {_rp(kg)} kg"
                              + (f" · {pemilik}" if pemilik else ""))})
    return out


class GabahKeringKeluarkanReq(BaseModel):
    silo_storage_id: int
    berat_kg: Positif
    jumlah_karung: int | None = None


@router.post("/actions/gabah-kering-keluarkan")
async def act_gabah_kering_keluarkan(
    req: GabahKeringKeluarkanReq, user: User = Depends(pengguna_aksi)) -> dict:
    """Keluarkan gabah dari silo, TIMBANG — jalan keluar baru selain giling."""
    _require(await _is_g1_operator(user))
    from app.penggilingan.gudang1.services.gabah_kering import (
        GabahKeringError, keluarkan_untuk_kemasan)
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await keluarkan_untuk_kemasan(
                db, user=u, silo_storage_id=req.silo_storage_id,
                berat_kg=float(req.berat_kg), jumlah_karung=req.jumlah_karung)
        except GabahKeringError as e:
            raise _err(e, "Gagal mengeluarkan gabah kering.")
    pesan = (f"✓ {r.lot.kode_lot} ditimbang {req.berat_kg:,.0f} kg dari "
             f"Silo {r.nama_silo} (sisa silo {r.sisa_silo_kg:,.0f} kg)."
             .replace(",", "."))
    return {"ok": True, "pesan": pesan}


@router.get("/actions/gabah-kering-berjalan")
async def gabah_kering_berjalan(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Lot gabah kering ditumpuk yang masih bersisa — untuk timbang ulang
    atau dibongkar kembali ke silo."""
    _require(await _is_g1_operator(user))
    from sqlalchemy import select

    from app.models import GabahKeringLot
    from app.penggilingan.gudang1.services.gabah_kering import pending_gabah_kering_kg
    from app.services.jasa import nama_pemilik

    out = []
    async with SessionLocal() as db:
        for lot in (await db.execute(select(GabahKeringLot))).scalars().all():
            sisa = await pending_gabah_kering_kg(db, lot.id)
            if sisa <= 0.5:
                continue
            pemilik = await nama_pemilik(db, lot.jasa_id)
            out.append({
                "value": lot.kode_lot,
                "label": (f"{lot.kode_lot} · {_rp(sisa)} kg"
                          + (f" · {pemilik}" if pemilik else ""))})
    return out


class GabahKeringTimbangUlangReq(BaseModel):
    kode_lot: str
    berat_kg: Positif


@router.post("/actions/gabah-kering-timbang-ulang")
async def act_gabah_kering_timbang_ulang(
    req: GabahKeringTimbangUlangReq, user: User = Depends(pengguna_aksi)) -> dict:
    """Timbang ULANG satu lot (sesudah dikeringkan lagi) — bobot lama DIGANTI."""
    _require(await _is_g1_operator(user))
    from app.penggilingan.gudang1.services.gabah_kering import (
        GabahKeringError, timbang_ulang)
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            lot = await timbang_ulang(db, user=u, kode_lot=req.kode_lot,
                                      berat_kg=float(req.berat_kg))
        except GabahKeringError as e:
            raise _err(e, "Gagal menimbang ulang.")
    return {"ok": True,
            "pesan": f"✓ {lot.kode_lot} ditimbang ulang: {req.berat_kg:,.0f} kg."
                     .replace(",", ".")}


class GabahKeringBongkarReq(BaseModel):
    kode_lot: str
    silo: str  # A / B


@router.post("/actions/gabah-kering-bongkar-silo")
async def act_gabah_kering_bongkar_silo(
    req: GabahKeringBongkarReq, user: User = Depends(pengguna_aksi)) -> dict:
    """Bongkar SELURUH sisa satu lot gabah kering kembali ke silo."""
    _require(await _is_g1_operator(user))
    from app.penggilingan.gudang1.services.silo import SiloError, masuk_silo
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await masuk_silo(db, user=u, nama_silo=req.silo.upper(),
                                 kode_lot=None, kode_batch=None,
                                 kode_gkr=req.kode_lot)
        except SiloError as e:
            raise _err(e, "Gagal membongkar ke silo.")
    pesan = (f"✓ {req.kode_lot} dibongkar → Silo {r.nama_silo} ({r.kg_baris:,.0f} kg)."
             .replace(",", "."))
    if r.digabung:
        pesan += (f"\n⚠️ Silo sudah berisi {r.isi_sebelumnya} — isinya kini tercampur.")
    if r.giling_berjalan:
        pesan += (f"\n⚠️ Silo {r.nama_silo} sedang digiling ({r.giling_berjalan}) — "
                  "gilingnya tetap jalan, dan gabah ini masuk sebagai bahan "
                  f"tambahannya (+{r.kg_baris:,.0f} kg).".replace(",", "."))
    return {"ok": True, "pesan": pesan}


class WaktuJedaReq(BaseModel):
    proses: str
    waktu_mode: str = "sekarang"
    waktu_kejadian: datetime | None = None
    alasan_terlambat: str = ""
    dasar: str = ""
    kunci_kiriman: Annotated[str, Field(max_length=64)] = ""


class HentikanReq(WaktuJedaReq):
    sebab: str
    sebab_lain: str | None = None
    catatan: str = ""


class LanjutkanReq(WaktuJedaReq):
    pass


def _waktu_jeda(req):
    if not req.dasar or not req.kunci_kiriman:
        raise HTTPException(409, "Periksa keadaan jeda terbaru sebelum menyimpan.")
    if req.waktu_mode not in ("sekarang", "aktual"):
        raise HTTPException(400, "Pilih waktu sekarang atau waktu aktual.")
    if req.waktu_mode == "aktual" and req.waktu_kejadian is None:
        raise HTTPException(400, "Isi tanggal dan jam kejadian aktual.")
    return dict(waktu_kejadian=req.waktu_kejadian if req.waktu_mode == "aktual" else None,
                alasan_terlambat=req.alasan_terlambat if req.waktu_mode == "aktual" else "",
                dasar=req.dasar, kunci_kiriman=req.kunci_kiriman)


def _urai_proses(nilai: str) -> tuple[str, str]:
    jenis, _, kode = (nilai or "").partition(":")
    return jenis.strip(), kode.strip()


@router.post("/actions/hentikan-proses")
async def act_hentikan_proses(req: HentikanReq,
                              user: User = Depends(pengguna_aksi)) -> dict:
    from app.penggilingan.gudang1.services.jeda import JedaError, hentikan
    jenis, kode = _urai_proses(req.proses)
    # Penyosohan milik operator Gudang 2; pengeringan & giling milik Gudang 1.
    _require(await (_is_g2_operator if jenis == "penyosohan" else _is_g1_operator)(user))
    if not kode:
        raise HTTPException(400, "Pilih proses yang mau dihentikan dulu.")
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await hentikan(db, user=u, jenis=jenis, kode=kode,
                               sebab=req.sebab, sebab_lain=req.sebab_lain,
                               catatan=req.catatan, **_waktu_jeda(req))
        except JedaError as e:
            raise HTTPException(409, str(e))
    pesan = (f"⏸ *{r.kode}* dihentikan sementara — {r.sebab}.\n"
             f"Prosesnya tidak ditutup; bahan & catatannya tetap. "
             f"Berhenti ke-{r.kali} untuk proses ini.")
    return {"ok": True, "pesan": pesan}


@router.post("/actions/lanjutkan-proses")
async def act_lanjutkan_proses(req: LanjutkanReq,
                               user: User = Depends(pengguna_aksi)) -> dict:
    from app.penggilingan.gudang1.services.jeda import JedaError, lanjutkan
    jenis, kode = _urai_proses(req.proses)
    _require(await (_is_g2_operator if jenis == "penyosohan" else _is_g1_operator)(user))
    if not kode:
        raise HTTPException(400, "Pilih proses yang mau dilanjutkan dulu.")
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await lanjutkan(db, user=u, jenis=jenis, kode=kode, **_waktu_jeda(req))
        except JedaError as e:
            raise HTTPException(409, str(e))
    jam = (r.tertahan_detik or 0) / 3600
    pesan = (f"▶️ *{r.kode}* dilanjutkan — tertahan {jam:.1f} jam "
             f"({r.sebab}).")
    return {"ok": True, "pesan": pesan}


@router.get("/actions/acuan-jeda")
async def acuan_jeda(proses: str, user: User = Depends(pengguna_aksi)):
    from app.penggilingan.gudang1.services.jeda import ringkasan_jeda, JedaError
    jenis,kode = _urai_proses(proses)
    _require(await (_is_g2_operator if jenis == "penyosohan" else _is_g1_operator)(user))
    async with SessionLocal() as db:
        try:
            return await ringkasan_jeda(db, jenis=jenis, kode=kode)
        except JedaError as e:
            raise HTTPException(409,str(e))


@router.get("/actions/sebab-jeda")
async def pilihan_sebab_jeda(induk: str = "", user: User = Depends(pengguna_aksi)):
    from app.services.setelan import sebab_jeda
    from app.penggilingan.gudang1.services.jeda import SEBAB, SEBAB_LAIN
    jenis,kode = _urai_proses(induk)
    if not kode or jenis not in SEBAB:
        return []
    _require(await (_is_g2_operator if jenis == "penyosohan" else _is_g1_operator)(user))
    async with SessionLocal() as db:
        daftar = (await sebab_jeda(db))[jenis]
    return [{'value':v,'label':v} for v in daftar] + [{'value':SEBAB_LAIN,'label':'Lainnya — tulis sendiri'}]


@router.post("/actions/ubah-kondisi-jeda")
async def act_ubah_kondisi_jeda(req: HentikanReq, user: User = Depends(pengguna_aksi)):
    from app.penggilingan.gudang1.services.jeda import perbarui_kondisi, JedaError
    jenis,kode = _urai_proses(req.proses)
    _require(await (_is_g2_operator if jenis == "penyosohan" else _is_g1_operator)(user))
    async with SessionLocal() as db:
        try:
            await perbarui_kondisi(db, user=await db.get(User,user.id), jenis=jenis, kode=kode,
                sebab=req.sebab, sebab_lain=req.sebab_lain, catatan=req.catatan, **_waktu_jeda(req))
        except JedaError as e:
            raise HTTPException(409,str(e))
    return {'ok':True,'pesan':'Kondisi jeda diperbarui. Mesin tetap dijeda; riwayat penyebab sebelumnya tersimpan.'}


class TutupSiloGilingReq(BaseModel):
    kode_proses: str
    #: Boleh KOSONG bila prosesnya hanya menyisakan satu silo yang masih
    #: terbuka — `milling.tutup_silo_giling` yang memilihnya. Pola yang
    #: sama dengan `SelesaiPenyosohanReq.silo` di Gudang 2.
    silo: str = ""
    sisa: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    dasar: str = ""


@router.post("/actions/tutup-silo-giling")
async def act_tutup_silo_giling(req: TutupSiloGilingReq,
                                user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g1_operator(user))
    if not (req.kode_proses or "").strip():
        raise HTTPException(400, "Pilih proses giling dulu.")
    if not req.dasar:
        raise HTTPException(409, "Periksa ringkasan sisa silo terlebih dahulu.")
    silo = (req.silo or "").strip().upper() or None
    from app.penggilingan.gudang1.services.milling import MillingError, tutup_silo_giling
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            # Silo kosong DITERUSKAN, tidak dihadang: yang tahu berapa silo
            # yang masih terbuka untuk proses ini adalah layanannya, bukan
            # borangnya — pola yang sama dengan `act_selesai_penyosohan`.
            r = await tutup_silo_giling(db, user=u, kode_proses=req.kode_proses,
                                        nama_silo=silo, sisa_kg=req.sisa, dasar=req.dasar)
        except MillingError as e:
            raise _err(e, "Gagal membebaskan silo.")
    terpakai = f"{r.terpakai_kg:g} kg terpakai" if r.terpakai_kg is not None else "berat terpakai menunggu timbang"
    keadaan = "Silo dinyatakan kosong dan boleh diisi ulang." if r.sisa_kg == 0 else "Sisa tetap berada di silo; statusnya terisi."
    pesan = (f"✓ Silo {r.nama_silo} pada *{req.kode_proses}* dibebaskan dari proses — "
             f"{terpakai}, sisa {r.sisa_kg:g} kg. {keadaan} Giling TETAP berjalan.")
    return {"ok": True, "pesan": pesan}


class MulaiGilingReq(BaseModel):
    #: Satu huruf, atau beberapa — satu lot boleh datang dari beberapa silo
    #: (keputusan pemilik 24 September 2026). Bentuk tunggal tetap diterima:
    #: ia yang dikirim borang lama dan tombol pada kartu silo.
    silo: str | list[str]


@router.post("/actions/mulai-giling")
async def act_mulai_giling(req: MulaiGilingReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g1_operator(user))
    # ── Tak ada lagi daftar huruf tertulis-tangan ──
    #
    # Dulu di sini `not in ("A", "B")`. Silo Gudang 1 bisa ditambah lewat
    # Pengaturan → Alat, jadi silo ketiga yang baru dibeli ditolak di pintu
    # oleh dua huruf yang diketik seseorang bertahun lalu — dan pesannya
    # berbunyi "Pilih silo yang digiling dulu", padahal ia sudah memilih.
    # Yang memeriksa keberadaan silonya `start_milling`, lewat master.
    pilih = [req.silo] if isinstance(req.silo, str) else list(req.silo or [])
    pilih = [str(x).strip().upper() for x in pilih if str(x or "").strip()]
    if not pilih:
        raise HTTPException(400, "Pilih dulu silo yang digiling.")
    from sqlalchemy.exc import IntegrityError

    from app.penggilingan.gudang1.services.milling import start_milling, MillingError
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await start_milling(db, user=u, nama_silo=pilih)
        except MillingError as e:
            raise _err(e, "Gagal mulai giling.")
        except IntegrityError:
            # Seperti R-T-01 di timbangan: aturan basis data yang ditolak tak
            # boleh sampai ke layar sebagai teks Postgres (QA P6-01). Yang
            # lengkap ada di log lewat penangan global; di sini kalimatnya.
            log.exception("Mulai giling ditolak aturan basis data")
            raise HTTPException(
                400, "Giling tidak bisa dimulai karena aturan basis data menolak "
                     "bahannya. Coba sekali lagi; bila berulang, sebutkan ke Super Admin.")
    bobot = r.bobot.teks() if r.bobot is not None else f"{r.berat_masuk:g} kg"
    pesan = (f"✓ Giling *{r.proc.kode_proses}* mulai — Silo {r.nama_silo} "
             f"({bobot} gabah).")
    return {"ok": True, "pesan": pesan}


class KodeProsesReq(BaseModel):
    kode_proses: str


class SelesaiGilingReq(BaseModel):
    kode_proses: str
    #: Hasil akhir PK (kg). Boleh kosong HANYA bila operator sudah pernah
    #: mencatat hasilnya lewat "Perbarui hasil giling"; layanan yang memutuskan,
    #: bukan di sini — satu aturan, satu tempat.
    berat_akhir: PositifOpsional = None
    dasar: str = ""


@router.post("/actions/selesai-giling")
async def act_selesai_giling(req: SelesaiGilingReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g1_operator(user))
    if not (req.kode_proses or "").strip():
        raise HTTPException(400, "Pilih proses giling dulu.")
    if not req.dasar:
        raise HTTPException(409, "Periksa ringkasan penyelesaian giling terlebih dahulu.")
    from app.penggilingan.gudang1.services.milling import finish_milling, MillingError
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await finish_milling(db, user=u, kode_proses=req.kode_proses,
                                     berat_akhir=req.berat_akhir, dasar=req.dasar)
        except MillingError as e:
            raise _err(e, "Gagal menyelesaikan giling.")
    jns = (r.jenis + " ") if r.jenis else ""
    pesan = (f"✓ Giling *{req.kode_proses}* selesai — PK {jns}{r.produced:g} kg "
             f"(siap kirim {r.siap_kirim:g} kg).")
    return {"ok": True, "pesan": pesan}


class VerifyOutputReq(BaseModel):
    kode_proses: str
    berat_output: PositifOpsional = None


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
    return {"ok": True, "pesan": pesan}


@router.post("/actions/betulkan-bobot-giling")
async def act_betulkan_bobot_giling(req: KodeProsesReq, user: User = Depends(pengguna_aksi)) -> dict:
    """Admin ke atas. Menandai belum final lalu menyamakan lewat jalur poller."""
    _require(can_see_financials(user))
    if not (req.kode_proses or "").strip():
        raise HTTPException(400, "Pilih giling yang mau dibetulkan dulu.")
    from app.penggilingan.gudang1.services.koreksi_bobot import (
        KoreksiError, betulkan_bobot_masuk)
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await betulkan_bobot_masuk(db, user=u, kode_proses=req.kode_proses.strip())
        except KoreksiError as e:
            raise _err(e, "Gagal membetulkan bobot masuk.")
    dari = f"{r.tercatat_kg:,.0f}".replace(",", ".") if r.tercatat_kg is not None else "belum diketahui"
    ke = f"{r.sekarang_kg:,.0f}".replace(",", ".") if r.sekarang_kg is not None else "belum diketahui"
    pesan = (f"✓ Bobot masuk *{r.proc.kode_proses}* dibetulkan: {dari} → {ke} kg"
             + ("" if r.final else " (sebagian bahan masih menunggu timbang)")
             + ". Rendemen dihitung ulang.")
    return {"ok": True, "pesan": pesan}


class QcGilingReq(BaseModel):
    kode_proses: str
    kadar_air: PersenOpsional = None
    broken: PersenOpsional = None
    susut: PersenOpsional = None
    butir_kuning: str | None = None
    gabah: str | None = None
    merang: str | None = None
    catatan_lab: str | None = None


@router.post("/actions/qc-giling")
async def act_qc_giling(req: QcGilingReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(can_see_financials(user))
    await _wajib_mutu()
    if not (req.kode_proses or "").strip():
        raise HTTPException(400, "Pilih proses giling dulu.")
    if all(v is None for v in (req.kadar_air, req.broken, req.susut)) and not any(
            (v or "").strip() for v in (req.butir_kuning, req.gabah, req.merang, req.catatan_lab)):
        raise HTTPException(400, "Isi minimal salah satu komponen QC.")
    from app.penggilingan.gudang1.services.milling import log_qc_milling, MillingError
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await log_qc_milling(db, user=u, kode_proses=req.kode_proses,
                                     kadar_air=req.kadar_air, broken=req.broken,
                                     susut=req.susut, kondisi=None,
                                     butir_kuning=req.butir_kuning, gabah=req.gabah,
                                     merang=req.merang, catatan_lab=req.catatan_lab)
        except MillingError as e:
            raise _err(e, "Gagal mencatat QC.")
    det = ", ".join(
        f"{lbl} {v:g}%" for lbl, v in
        (("KA", r.kadar_air), ("broken", r.broken), ("susut", r.susut)) if v is not None
    )
    jns = f" [{r.kondisi}]" if r.kondisi else ""
    kualitatif = ", ".join(f"{label} {nilai}" for label, nilai in r.kualitatif)
    det = " · ".join(x for x in (det, kualitatif,
                                  "Catatan lab tersimpan" if r.catatan_lab else "") if x)
    # Angka yang baru saja diketik sudah diketahui orangnya; yang belum ia tahu
    # adalah ke mana angka itu menggeser rata-ratanya. Disebut hanya bila sudah
    # ada lebih dari satu catatan — "rata-rata 1 catatan" cuma mengulang.
    ekor = (f" Ringkasan QC kini: {r.rata.teks()}."
            if r.rata is not None and r.rata.n > 1 else "")
    pesan = f"✓ QC *{req.kode_proses}*{jns}: {det}.{ekor}"
    return {"ok": True, "pesan": pesan}


class CatatPkLuarReq(BaseModel):
    # Pilih TIKET TIMBANG PK aktif — supplier/bobot/nopol dari timbang.
    timbangan_transaksi_id: int
    jenis_pk: str
    #: Kunci kiriman (Tahap 3), opsional — lihat `GabahMasukReq`.
    kunci_kiriman: str | None = None


class CatatProdukTimbangMasukReq(BaseModel):
    timbangan_transaksi_id: int


@router.get("/actions/produk-timbang-masuk-aktif")
async def produk_timbang_masuk_aktif(jenis: str, user: User = Depends(pengguna_aksi)) -> list[dict]:
    _require(can_see_financials(user))
    if jenis not in ("BERAS_MASUK", "BROKEN_MASUK"):
        raise HTTPException(400, "Jenis barang masuk tidak dikenal.")
    from app.penggilingan.gudang1.services.timbang_link import tiket_masuk_aktif
    async with SessionLocal() as db:
        tickets = await tiket_masuk_aktif(db, jenis)
    out = []
    for t in tickets:
        berat = t.get("berat_hpp_kg")
        pemilik = (t.get("nama_supplier") or t.get("nama_pelanggan")
                   or t.get("pihak_nama") or "Tanpa nama")
        label = f"{t['kode']} · {pemilik} · {t.get('nomor_polisi') or 'tanpa plat'}"
        if berat:
            label += f" · {_rp(float(berat))} kg"
        out.append({"value": t["id"], "label": label})
    return out


@router.post("/actions/catat-produk-timbang-masuk")
async def act_catat_produk_timbang_masuk(
    req: CatatProdukTimbangMasukReq, user: User = Depends(pengguna_aksi),
) -> dict:
    """Terima beras/broken dari tiket sebagai stok bertumpuk, dengan asal tiket."""
    _require(can_see_financials(user))
    from sqlalchemy import select
    from app.database import input_time
    from app.models import FinishedGoodsStock
    from app.penggilingan.gudang1.services.timbang_link import (
        TiketSudahDipakai, ambil_tiket, bobot_awal_dari_tiket,
        kunci_tiket_untuk_ditaut)
    from app.penggilingan.inventory.models import ByproductStock
    from app.penggilingan.inventory.packaging import find_or_create_sku, get_standard
    from app.penggilingan.gudang2.service import _g2_warehouse_id
    from app.services.activity_log import log_activity

    async with SessionLocal() as db:
        try:
            await kunci_tiket_untuk_ditaut(db, req.timbangan_transaksi_id)
        except TiketSudahDipakai as e:
            raise HTTPException(409, str(e))
        ticket = await ambil_tiket(db, req.timbangan_transaksi_id)
        if ticket is None or ticket.get("arah") != "MASUK":
            raise HTTPException(404, "Tiket masuk tidak ditemukan atau sudah tidak aktif.")
        kind = ticket.get("jenis_kode")
        if kind not in ("BERAS_MASUK", "BROKEN_MASUK"):
            raise HTTPException(400, "Tiket ini bukan beras atau broken masuk.")
        if kind == "BERAS_MASUK":
            sudah_dicatat = await db.scalar(select(FinishedGoodsStock.id).where(
                FinishedGoodsStock.source_type == "timbangan",
                FinishedGoodsStock.source_id == ticket["id"]))
        else:
            sudah_dicatat = await db.scalar(select(ByproductStock.id).where(
                ByproductStock.source_type == "timbangan",
                ByproductStock.source_id == ticket["id"]))
        if sudah_dicatat:
            raise HTTPException(409, "Tiket ini sudah tercatat sebagai stok.")
        weight, _, _ = await bobot_awal_dari_tiket(db, ticket)
        if weight is None or weight <= 0:
            raise HTTPException(400, "Berat barang belum tersedia dari Timbangan.")
        jasa_id = None
        if ticket.get("jasa"):
            from app.penggilingan.gudang1.services.purchase import pesanan_jasa_dari_tiket
            order, _ = await pesanan_jasa_dari_tiket(db, user=user, tiket=ticket)
            jasa_id = order.id
        now = input_time(None)
        if kind == "BERAS_MASUK":
            medium = await get_standard(db, "medium")
            if medium is None:
                raise HTTPException(500, "Standar mutu Medium belum tersedia.")
            sku = await find_or_create_sku(
                db, kategori="beras_putih", material_kode="putih", ukuran=50)
            row = FinishedGoodsStock(
                product_sku_id=sku.id, rice_quality_standard_id=medium.id,
                source_type="timbangan", source_id=ticket["id"],
                jumlah_karung=max(1, int((float(weight) + 49.999) // 50)),
                berat_total_kg=float(weight), warehouse_id=await _g2_warehouse_id(db),
                waktu=now, input_by=user.id, jasa_id=jasa_id,
                kemasan_mengurangi_stok=False)
            db.add(row)
            table, target = "finished_goods_stock", "Beras Medium · karung putih polos tanpa merek 50 kg"
        else:
            row = ByproductStock(
                jenis_produk="broken", source_type="timbangan", source_id=ticket["id"],
                berat_kg=float(weight), tanggal=now.date(), waktu=now,
                input_by=user.id, jasa_id=jasa_id)
            db.add(row)
            table, target = "byproduct_stock", "Broken · karung putih polos tanpa merek 50 kg"
        await db.flush()
        await log_activity(db, table_name=table, record_id=row.id, action="INSERT",
                           changed_by=user.id,
                           new_value=f"{ticket['kode']} · {float(weight):.2f} kg · {target}")
        await db.commit()
    return {"ok": True, "pesan": f"✓ {ticket['kode']} dicatat di stok bertumpuk: "
            f"{_rp(float(weight))} kg · {target}."}


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
    """Catat PK luar datang — langsung tertumpuk. Mutu BUKAN di sini.

    ⚠⚠ RIWAYAT, supaya tak diulang: sempat menyatukan `catat_pk_luar` +
    `masukkan_pk` + mutu lengkap jadi SATU aksi (keputusan pemilik 4-5
    Oktober 2026) — lalu DIBATALKAN pada hari yang sama: *"QC Pk bukan di
    borang Catat PK luar datang. tetapi buat di kartu di halaman Mutu &
    QC."* Penyatuan `masukkan_pk` (Aturan 1 — PK baru selalu ke tumpukan,
    tanpa pertanyaan tujuan) TETAP berlaku; yang dicabut cuma mutunya.

    Mutu dicatat lewat `qc_pk_luar`, yang tak pernah berhenti ada — selama
    penyatuan berlaku ia cuma tak pernah punya kartu untuk dibuka, sebab
    tiap batch baru lahir dengan QC yang sudah lengkap. Mencabut mutu dari
    sini sudah cukup mengembalikan kartunya (`berjalan.untuk_gudang2`,
    blok "Kerja meja: MUTU PK luar" — menyaring batch yang belum punya
    `PkPurchaseVerification.kadar_air`).

    Lihat `act_tolak_pk_luar` untuk jalur SEBALIKNYA: PK yang ditolak, bukan
    diterima — tombolnya ada di borang yang sama (`tombol_aksi` di
    spesifikasi katalog), bukan di "Catat pekerjaan lain", dan TAK menanyakan
    mutu sama sekali: PK yang ditolak tak pernah jadi stok yang perlu
    diklasifikasi."""
    _require(can_see_financials(user))
    if req.jenis_pk not in ("ks", "kl", "campuran", "semi_ks"):
        raise HTTPException(400, "Pilih jenis PK dulu: KS / KL / Campuran / Semi KS.")
    from app.penggilingan.gudang2.service import (
        create_pk_purchase_dari_timbang, masukkan_pk_luar, Gudang2Error)
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await create_pk_purchase_dari_timbang(
                db, user=u, timbangan_transaksi_id=req.timbangan_transaksi_id,
                jenis_pk=req.jenis_pk,
                kunci_kiriman=(req.kunci_kiriman or "")[:120] or None,
            )
        except Gudang2Error as e:
            raise _err(e, "Gagal mencatat PK luar.")
        berat = r.batch.berat_total_kg
        nopol = r.batch.no_polisi_truk or "-"
        # ── Langkah kedua, DI DALAM aksi yang sama (Aturan 1) ──
        #
        # Kiriman ulang (kunci_kiriman sama) mengembalikan batch yang SAMA
        # dari `create_pk_purchase_dari_timbang` di atas — dan baris intake-
        # nya pun sudah ada dari percobaan pertama. `masukkan_pk_luar`
        # sendiri menolak batch yang sudah punya intake ("sudah dimasukkan
        # sebelumnya"), jadi percobaan kedua di sini ditelan diam-diam,
        # bukan dianggap galat: pesan sukses yang sama tetap tampil.
        tertumpuk = True
        try:
            await masukkan_pk_luar(db, user=u, kode=r.batch.kode_batch)
        except Gudang2Error as e:
            if "sudah dimasukkan" not in str(e):
                # Gagal karena sebab LAIN — batch-nya tetap tercatat (sudah
                # commit di atas), tapi belum tertumpuk. Kartu "PK luar yang
                # menunggu dimasukkan" (`masukkan_pk`, lihat `berjalan.
                # untuk_gudang2`) tetap berdiri sebagai jalan penyelesaiannya
                # — bukan jalan darurat yang baru, melainkan yang sudah ada
                # sejak sebelum penyatuan ini.
                tertumpuk = False
    jl = {"ks": "KS", "kl": "KL", "campuran": "Campuran", "semi_ks": "Semi KS"}.get(
        r.batch.jenis_pk, r.batch.jenis_pk or "-")
    baru = " (supplier baru)" if r.supplier_created else ""
    bstr = f"{float(berat):g} kg" if berat is not None else "menunggu bobot"
    ekor = (" Tertumpuk — catat mutunya lewat kartu \"Mutu PK luar belum "
           "dicatat\" di halaman Mutu & QC."
           if tertumpuk else
           " Diterima, tapi BELUM tertumpuk — selesaikan lewat kartu \"PK "
           "luar yang menunggu dimasukkan\".")
    pesan = (f"✓ PK luar *{r.batch.kode_batch}* tercatat — {r.supplier_nama}{baru}, "
             f"{jl} {bstr}, truk {nopol}.{ekor}")
    return {"ok": True, "pesan": pesan}


class TolakPkLuarReq(BaseModel):
    timbangan_transaksi_id: int
    alasan: str
    #: Kunci kiriman (Tahap 3), opsional — lihat `GabahMasukReq`.
    kunci_kiriman: str | None = None


@router.post("/actions/tolak-pk-luar")
async def act_tolak_pk_luar(req: TolakPkLuarReq, user: User = Depends(pengguna_aksi)) -> dict:
    """Tolak PK luar SAAT DATANG — tombol kedua di borang yang sama dengan
    `catat_pk_luar` (keputusan pemilik 4 Oktober 2026). Satu-satunya yang
    wajib: alasannya — jenis PK & kadar air tak ditanya, sebab PK yang
    ditolak tak pernah jadi stok yang perlu diklasifikasi.

    ⚠ Tiket timbangnya ikut ditutup paksa, MENGESAMPINGKAN Temuan QA T-15 di
    repo timbangan (truk yang ditolak biasanya tetap wajib ditimbang keluar
    untuk kontrol masuk−keluar) — keputusan pemilik, khusus kasus ini. Lihat
    `gudang2.service.create_pk_rejection_dari_timbang`."""
    _require(can_see_financials(user))
    if not (req.alasan or "").strip():
        raise HTTPException(400, "Sebutkan alasan menolaknya.")
    from app.penggilingan.gudang2.service import create_pk_rejection_dari_timbang, Gudang2Error
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await create_pk_rejection_dari_timbang(
                db, user=u, timbangan_transaksi_id=req.timbangan_transaksi_id,
                alasan=req.alasan,
            )
        except Gudang2Error as e:
            raise _err(e, "Gagal mencatat penolakan PK luar.")
    bstr = f"{float(r.rejection.berat_kg):g} kg" if r.rejection.berat_kg else "bobot belum diketahui"
    nopol = r.rejection.no_polisi_truk or "-"
    ekor = ("" if r.tiket_ditutup else
           " (tiket timbangnya sudah selesai sendiri — tak disentuh)")
    pesan = (f"⛔ PK luar *{r.rejection.kode}* ditolak — {r.pihak_nama}, {bstr}, "
             f"truk {nopol}. {req.alasan.strip()}{ekor}")
    return {"ok": True, "pesan": pesan}


class QcPkLuarReq(BaseModel):
    kode_batch: str
    kadar_air: PersenOpsional = None
    broken: PersenOpsional = None
    penyusutan: PersenOpsional = None
    butir_kuning: str | None = None
    gabah: str | None = None
    merang: str | None = None
    catatan_lab: str | None = None


@router.post("/actions/qc-pk-luar")
async def act_qc_pk_luar(req: QcPkLuarReq, user: User = Depends(pengguna_aksi)) -> dict:
    """Input kualitas PK luar (properti batch) — bukan keputusan terima/tolak.

    ⚠ POTONGAN BOBOT DIHAPUS 4 Oktober 2026 (keputusan pemilik): basis data
    produksi tak pernah memuat satu baris pun berisi `potongan_kg`/`potongan_
    alasan` (keduanya 0 dari 0 baris saat diperiksa) — tak ada riwayat yang
    hilang. Bobot PK yang masuk Gudang 2 kini SELALU sama dengan bobot
    tiket timbangnya; borang ini murni mencatat MUTU, tak pernah mengubah
    stok. Kalau bobot memang perlu dikoreksi, tempatnya revisi tiket di Pos
    Timbang (`jumlah_revisi`, `terkunci`) — bukan potongan diam-diam di sini.
    """
    _require(can_see_financials(user))
    await _wajib_mutu()
    if not (req.kode_batch or "").strip():
        raise HTTPException(400, "Pilih PK luar dulu.")
    if all(v is None for v in (req.kadar_air, req.broken, req.penyusutan)) \
            and not (req.butir_kuning or req.gabah or req.merang or req.catatan_lab):
        raise HTTPException(400, "Isi minimal salah satu: kadar air / broken / "
                                 "penyusutan / butir kuning / gabah / merang / catatan.")
    from app.penggilingan.gudang2.service import log_pk_qc, Gudang2Error
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await log_pk_qc(
                db, user=u, kode=req.kode_batch, kadar_air=req.kadar_air,
                broken=req.broken, penyusutan_persen=req.penyusutan,
                butir_kuning=(req.butir_kuning or None),
                gabah=(req.gabah or None), merang=(req.merang or None),
                catatan_lab=(req.catatan_lab or None),
            )
        except Gudang2Error as e:
            raise _err(e, "Gagal input kualitas PK.")
    det = ", ".join(
        f"{lbl} {v:g}%" for lbl, v in
        (("KA", r.kadar_air), ("broken", r.broken), ("susut", r.penyusutan)) if v is not None
    )
    kual = ", ".join(
        f"{lbl} {v}" for lbl, v in
        (("butir kuning", r.butir_kuning), ("gabah", r.gabah), ("merang", r.merang)) if v
    )
    bk = f" · {kual}" if kual else ""
    pesan = f"✓ QC *{req.kode_batch}* putaran {r.qc_count} tercatat: {det or '—'}{bk}."
    return {"ok": True, "pesan": pesan}


class MintaPkReq(BaseModel):
    kode_proses: str
    berat: Positif | None = None


@router.post("/actions/minta-pk-g1")
async def act_minta_pk_g1(req: MintaPkReq, user: User = Depends(pengguna_aksi)) -> dict:
    """Operator Gudang 2 meminta satu lot PK Gudang 1 dipindah kepadanya.

    Gerbangnya di RUTE, bukan cuma pada tombolnya: menyembunyikan pintu bukan
    penjagaan — alamatnya bisa diketik, dan lembar yang masih terbuka di layar
    orang lain masih bisa mengirim.

    Yang boleh: operator yang sedang bekerja di Gudang 2. Admin tidak — ia bisa
    memindahkan langsung, dan permintaan kepada diri sendiri cuma satu baris
    tambahan yang harus ditutup sendiri.
    """
    _require(await _is_g2_operator(user) and not can_see_financials(user))
    if not (req.kode_proses or "").strip():
        raise HTTPException(400, "Pilih lot PK dulu.")
    from app.services.permintaan_pk import PermintaanError, minta
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            await minta(db, user=u, kode_proses=req.kode_proses,
                        berat=req.berat)
        except PermintaanError as e:
            raise _err(e, "Gagal meminta lot PK.")
    # Kalimat ini dua kali menyebut hal yang salah, dan keduanya ketahuan
    # bersama (temuan QA 28 September 2026): Admin melihatnya di MENUNGGU
    # KEPUTUSAN — bukan Antrian tunggu, yang memuat pekerjaan fisik — dan yang
    # memindahkan GUDANG 1, bukan Admin (keputusan pemilik 27 September).
    #
    # Dua kalimat sekerabatnya sudah dibetulkan lebih dulu; yang ini tertinggal
    # karena ia satu-satunya yang dibaca operator Gudang 2, dan tak seorang pun
    # dari kami membuka layar itu sesudah tangannya berpindah.
    return {"ok": True,
            "pesan": f"✓ Lot *{req.kode_proses}* diminta {_rp(float(req.berat or 0))} "
                     "kg — Admin memutuskannya di Menunggu keputusan. Kalau "
                     "disetujui, Gudang 1 yang memuat dan mengirimnya."}


class AccPermintaanReq(BaseModel):
    permintaan: str
    tujuan: str
    berat: Positif | None = None


@router.post("/actions/acc-permintaan-pk")
async def act_acc_permintaan_pk(req: AccPermintaanReq,
                                user: User = Depends(pengguna_aksi)) -> dict:
    """LANGKAH 2 — Admin menyetujui, sambil menetapkan tujuan dan bobotnya.

    Tujuannya ditetapkan di sini, bukan saat barangnya berangkat: yang tahu
    gudang mana yang sedang kosong adalah Admin, dan yang memuat tak boleh
    disuruh menebaknya sambil berdiri di samping tumpukan.
    """
    _require(can_transfer_pk(user))
    try:
        pid = int((req.permintaan or "").strip())
    except ValueError:
        raise HTTPException(400, "Permintaan yang mana?")
    from app.services.permintaan_pk import PermintaanError, setujui
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            b = await setujui(db, user=u, permintaan_id=pid, tujuan=req.tujuan,
                              berat=req.berat)
        except PermintaanError as e:
            raise _err(e, "Gagal menyetujui permintaan.")
        from app.penggilingan.gudang2.service import label_tujuan

        lok = await label_tujuan(db, b.tujuan, b.silo_id)
        kg = float(b.berat_setuju_kg or 0)
    # Kalimat ini sudah dua kali salah menyebut gudang, jadi aturannya ditulis
    # di sini: ia harus mengatakan hal yang SAMA dengan kartu-kartunya. Yang
    # memuat Gudang 1 (keputusan pemilik 27 September 2026), kartunya bertombol
    # di Antrian tunggu Gudang 1, dan Gudang 2 menunggu di Transit-nya.
    # `test_kalimat_persetujuan_menyebut_gudang_yang_benar` menjaganya pada
    # kalimat yang DIKEMBALIKAN, bukan pada sumbernya.
    return {"ok": True,
            "pesan": f"✓ Disetujui {_rp(kg)} kg ke {lok} — Gudang 1 yang "
                     "memuat dan mengirimnya, kartunya sudah berdiri di "
                     "Antrian tunggu mereka."}


class KirimPermintaanReq(BaseModel):
    permintaan: str
    berat: Positif | None = None


@router.post("/actions/kirim-permintaan-pk")
async def act_kirim_permintaan_pk(req: KirimPermintaanReq,
                                  user: User = Depends(pengguna_aksi)) -> dict:
    """LANGKAH 3 — operator Gudang 1 memuat dan mengirim. Barangnya berpindah.

    WEWENANGNYA TIDAK DATANG DARI PERAN. `can_transfer_pk` tak disentuh sama
    sekali: tak seorang operator pun bisa memindahkan PK atas kehendak sendiri.
    Yang memberi izin adalah BARIS PERMINTAANNYA — yang sudah disetujui Admin —
    dan layanan yang dipanggil memeriksa keadaan itu sambil mengunci barisnya.

    YANG MENEKANNYA OPERATOR GUDANG 1, dan hanya dia (keputusan pemilik 27
    September 2026): "gudang 1 yang mengirim", "jika sudah disetujui", "jadi
    gudang 1 mulai proses kirim". Kartunya bertombol di Antrian tunggu Gudang
    1, dan hanya muncul untuk permintaan berstatus `disetujui`.

    Satu tangan, bukan dua — dan alasannya bukan wewenang melainkan siapa yang
    memegang barangnya saat angka itu diketik. Yang mencatat "berat yang
    dimuat" harus orang yang melihat karungnya naik; pemilik menyebut orang itu
    Gudang 1. Tombol ini sempat berpindah ke Gudang 2 pada 26 September dengan
    aturan yang SAMA — yang berubah keterangan lapangannya, bukan aturannya.

    Gudang 2 yang meminta tetap diberi tahu lewat kartu tanpa tombol di
    Transit: ia menunggu barang, bukan mengerjakan sesuatu. Permintaan yang
    lenyap tanpa kabar membuat orangnya menekannya lagi besok.
    """
    _require(await _is_g1_operator(user))
    try:
        pid = int((req.permintaan or "").strip())
    except ValueError:
        raise HTTPException(400, "Permintaan yang mana?")
    from app.services.permintaan_pk import PermintaanError, kirim
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            b = await kirim(db, user=u, permintaan_id=pid, berat=req.berat)
        except PermintaanError as e:
            raise _err(e, "Gagal mengirim PK.")
        from app.penggilingan.gudang2.service import label_tujuan

        lok = await label_tujuan(db, b.tujuan, b.silo_id)
        kg = float(b.berat_kirim_kg or 0)
    return {"ok": True,
            "pesan": f"✓ {_rp(kg)} kg dikirim ke {lok} — Gudang 2 sudah bisa "
                     "memakainya. Admin menutup catatannya."}


class TutupPermintaanReq(BaseModel):
    permintaan: str
    berat: Positif | None = None


@router.post("/actions/tutup-permintaan-pk")
async def act_tutup_permintaan_pk(req: TutupPermintaanReq,
                                  user: User = Depends(pengguna_aksi)) -> dict:
    """LANGKAH 4 — Admin menutup, dan boleh membetulkan bobotnya.

    Bobot yang berbeda BUKAN suntingan satu kolom: barangnya sudah berpindah,
    jadi koreksinya membatalkan perpindahan lamanya lalu mencatat yang baru —
    keduanya lewat buku peristiwa. Lihat `permintaan_pk.tutup_admin`.
    """
    _require(can_transfer_pk(user))
    try:
        pid = int((req.permintaan or "").strip())
    except ValueError:
        raise HTTPException(400, "Permintaan yang mana?")
    from app.services.permintaan_pk import PermintaanError, tutup_admin
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            b, catatan = await tutup_admin(db, user=u, permintaan_id=pid,
                                           berat_final=req.berat)
        except PermintaanError as e:
            raise _err(e, "Gagal menutup permintaan.")
        kg = float(b.berat_final_kg or 0)
    return {"ok": True,
            "pesan": f"✓ Permintaan ditutup pada {_rp(kg)} kg."
                     + (f" {catatan}" if catatan else "")}


class TolakPermintaanReq(BaseModel):
    permintaan: str
    sebab: str = ""


@router.post("/actions/tolak-permintaan-pk")
async def act_tolak_permintaan_pk(req: TolakPermintaanReq,
                                  user: User = Depends(pengguna_aksi)) -> dict:
    """Admin menolak permintaan, DENGAN sebabnya.

    Sebab wajib, dan itu bukan formalitas: permintaan yang lenyap tanpa kabar
    membuat operator mengajukannya lagi besok, dan Admin menolaknya lagi —
    keduanya mengira pihak satunya yang lalai.
    """
    _require(can_transfer_pk(user))
    try:
        pid = int((req.permintaan or "").strip())
    except ValueError:
        raise HTTPException(400, "Permintaan yang mana?")
    from app.services.permintaan_pk import PermintaanError, tolak
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            await tolak(db, user=u, permintaan_id=pid, sebab=req.sebab)
        except PermintaanError as e:
            raise _err(e, "Gagal menolak permintaan.")
    return {"ok": True, "pesan": "✓ Permintaan ditolak — sebabnya terbaca operator."}


class TransferReq(BaseModel):
    kode_proses: str
    tujuan: str
    berat: PositifOpsional = None
    #: Kunci kiriman (Tahap 3), opsional — lihat `GabahMasukReq`.
    kunci_kiriman: str | None = None


@router.post("/actions/transfer-pk")
async def act_transfer_pk(req: TransferReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(can_transfer_pk(user))
    if not (req.kode_proses or "").strip():
        raise HTTPException(400, "Pilih proses PK dulu.")
    # Nama silonya TIDAK diperiksa di sini: daftarnya tumbuh bersama master,
    # dan penjaga yang menyebut dua silo akan menolak silo ketiga dengan
    # kalimat yang membuat orang mengira ia salah menekan. Yang memeriksa
    # keberadaannya `_tujuan_and_silo`, lewat master.
    if not (req.tujuan or "").strip():
        raise HTTPException(400, "Pilih tujuan dulu.")
    from app.services.transfer import create_internal_transfer, TransferError
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await create_internal_transfer(
                db, user=u, kode_proses=req.kode_proses,
                lokasi_tujuan=req.tujuan, berat=req.berat,
                kunci_kiriman=(req.kunci_kiriman or "")[:120] or None,
            )
        except TransferError as e:
            raise _err(e, "Gagal pemindahan PK.")
    jns = (r.jenis + " ") if r.jenis else ""
    pesan = (f"✓ Pemindahan PK *{r.transfer.kode_transfer}*: {jns}langsung masuk "
             f"{r.lokasi_label} Gudang 2. (Operator G2 tak perlu menerima manual.)")
    return {"ok": True, "pesan": pesan}


# ─────────────────────── Aksi cepat: Gudang 2 (operator) ───────────────────────

class MasukkanPkReq(BaseModel):
    kode_batch: str
    #: Kunci kiriman (Tahap 3), opsional — lihat `GabahMasukReq`.
    kunci_kiriman: str | None = None


@router.post("/actions/masukkan-pk")
async def act_masukkan_pk(req: MasukkanPkReq, user: User = Depends(pengguna_aksi)) -> dict:
    """PK luar yang baru masuk — langsung tertumpuk, tanpa pertanyaan tujuan.

    ⚠⚠ MEDAN `tujuan` DIBUANG (keputusan pemilik 4 Oktober 2026, Aturan 1):
    "apa yang bisa dijawab cuma satu jawaban" bukan pertanyaan. PK yang baru
    masuk selalu ke tumpukan sekarang — pindah ke silo adalah langkah
    TERPISAH (`pindah_tumpukan_silo`), pekerjaan operator, sesudah barangnya
    berdiri di lantai. `masukkan_pk_luar` sendiri menolak tujuan apa pun
    selain tumpukan — pagar di sini cuma mencegah borang lama (yang masih
    menyimpan medan itu di layarnya) mengirimkan sesuatu yang akan ditolak
    dengan pesan yang membingungkan.
    """
    # Entry Admin, bukan operator (keputusan pemilik 12 September 2026).
    _require(can_see_financials(user))
    if not (req.kode_batch or "").strip():
        raise HTTPException(400, "Pilih PK yang mau dimasukkan dulu.")
    from sqlalchemy.exc import IntegrityError

    from app.penggilingan.gudang2.service import masukkan_pk_luar, Gudang2Error
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await masukkan_pk_luar(db, user=u, kode=req.kode_batch,
                                       kunci_kiriman=(req.kunci_kiriman or "")[:120] or None)
        except Gudang2Error as e:
            raise _err(e, "Gagal memasukkan PK.")
        except IntegrityError:
            # Galat mentah Postgres tak boleh sampai ke layar (QA P6-02).
            log.exception("Masukkan PK ditolak aturan basis data")
            raise HTTPException(
                400, "PK tidak bisa dimasukkan karena aturan basis data menolaknya. "
                     "Coba sekali lagi; bila berulang, sebutkan ke Super Admin.")
    pesan = f"✓ PK *{req.kode_batch}* dimasukkan → {r.lokasi_label}."
    return {"ok": True, "pesan": pesan}


class MulaiPenyosohanReq(BaseModel):
    #: Satu huruf, atau beberapa. Bentuk tunggal tetap diterima: ia yang
    #: dikirim tombol pada kartu silo.
    silo: str | list[str]


@router.post("/actions/mulai-penyosohan")
async def act_mulai_penyosohan(req: MulaiPenyosohanReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g2_operator(user))
    # ── Tak ada lagi tupel A / B / AB ──
    #
    # Peta itu bisa menjawab tiga kemungkinan saja, dan ketiganya menyebut silo
    # yang namanya diketik di kode. Silo Gudang 2 bisa bertambah lewat
    # Pengaturan → Alat: silo ketiga ditolak di pintu dengan kalimat "Pilih
    # silo bahan dulu", padahal orangnya sudah memilih. Yang memeriksa
    # keberadaan, isi, dan kesibukan silonya `mulai_penyosohan`, lewat master.
    silos = [req.silo] if isinstance(req.silo, str) else list(req.silo or [])
    silos = [str(x).strip().upper() for x in silos if str(x or "").strip()]
    if not silos:
        raise HTTPException(400, "Pilih dulu silo bahannya.")
    from app.penggilingan.gudang2.polishing import mulai_penyosohan, Gudang2Error
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await mulai_penyosohan(db, user=u, nama_silos=silos)
        except Gudang2Error as e:
            raise _err(e, "Gagal mulai penyosohan.")
    pesan = (f"✓ Penyosohan *{r.proc.kode_proses}* mulai — silo "
             f"{'+'.join(r.silos)} ({r.berat_awal_total:g} kg).")
    return {"ok": True, "pesan": pesan}


class TambahSiloPenyosohanReq(BaseModel):
    kode: str
    silo: str | list[str]


@router.post("/actions/tambah-silo-penyosohan")
async def act_tambah_silo_penyosohan(req: TambahSiloPenyosohanReq,
                                     user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g2_operator(user))
    silos = [req.silo] if isinstance(req.silo, str) else list(req.silo or [])
    silos = [str(x).strip().upper() for x in silos if str(x or "").strip()]
    if not silos:
        raise HTTPException(400, "Pilih dulu silo yang ditambahkan.")
    if not (req.kode or "").strip():
        raise HTTPException(400, "Pilih proses penyosohannya dulu.")
    from app.penggilingan.gudang2.polishing import Gudang2Error, tambah_silo_penyosohan
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await tambah_silo_penyosohan(db, user=u, kode=req.kode, nama_silos=silos)
        except Gudang2Error as e:
            raise _err(e, "Gagal menambah silo.")
    pesan = (f"✓ Silo {'+'.join(r.silos)} ditambahkan ke *{r.proc.kode_proses}* "
             f"(+{r.berat_awal_total:,.0f} kg).".replace(",", "."))
    return {"ok": True, "pesan": pesan}


class HasilPenyosohanReq(BaseModel):
    kode_proses: str
    jenis: str
    #: Layar baru mengirim total aktual. `berat_kg` tetap berupa tambahan
    #: untuk lembar lama yang masih terbuka; maknanya tidak diubah diam-diam.
    berat_kg: Positif | None = None
    berat_kumulatif: Positif | None = None


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
                                   jenis=req.jenis, berat_kg=req.berat_kg,
                                   berat_kumulatif=req.berat_kumulatif)
        except Gudang2Error as e:
            raise _err(e, "Gagal catat hasil penyosohan.")
    pesan = (f"✓ Hasil *{req.kode_proses}*: total {r.jenis} "
             f"{r.berat_kumulatif:g} kg (tambahan {r.berat_kg:g} kg).")
    return {"ok": True, "pesan": pesan}


class SelesaiPenyosohanReq(BaseModel):
    kode_proses: str
    #: Boleh KOSONG bila prosesnya hanya menyisakan satu silo — `polishing.
    #: selesai_penyosohan` yang memilihnya. Dulu wajib di sini, dan gerbang itu
    #: menghadang jalur yang sudah lama ada di layanannya (`elif len(usages)
    #: == 1`), jadi orang yang menyosoh satu silo tetap harus menyebut silo.
    silo: str = ""
    sisa: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    dasar: str = ""


@router.post("/actions/selesai-penyosohan")
async def act_selesai_penyosohan(req: SelesaiPenyosohanReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g2_operator(user))
    if not (req.kode_proses or "").strip():
        raise HTTPException(400, "Pilih proses penyosohan dulu.")
    if not req.dasar:
        raise HTTPException(409, "Periksa ringkasan sisa silo terlebih dahulu.")
    silo = (req.silo or "").strip().upper() or None
    from app.penggilingan.gudang2.polishing import selesai_penyosohan, Gudang2Error
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            # Silo kosong DITERUSKAN, tidak dihadang: yang tahu berapa silo
            # yang dipakai proses ini adalah layanannya, bukan borangnya.
            r = await selesai_penyosohan(db, user=u, kode=req.kode_proses,
                                         nama_silo=silo, sisa_kg=req.sisa, dasar=req.dasar)
        except Gudang2Error as e:
            raise _err(e, "Gagal menandai selesai penyosohan.")
    return {"ok": True, "pesan": f"Silo {r.silo} dibebaskan (sisa {req.sisa:g} kg). Penyosohan tetap berjalan; hasil masih bisa dicatat."}


@router.get("/actions/pratinjau-bebaskan-silo")
async def pratinjau_bebaskan_silo(jenis: str, kode_proses: str, sisa: float,
        silo: str = "", user: User = Depends(pengguna_aksi)) -> dict:
    _require(await (_is_g1_operator(user) if jenis == "giling" else _is_g2_operator(user)))
    from app.services.penyelesaian_proses import ringkasan_bebaskan
    async with SessionLocal() as db:
        try:
            return await ringkasan_bebaskan(db, jenis=jenis, kode=kode_proses, silo=silo, sisa=sisa)
        except ValueError as e:
            raise HTTPException(409, str(e))


class AkhiriPenyosohanReq(BaseModel):
    kode_proses: str
    dasar: str


@router.get("/actions/pratinjau-selesai-proses")
async def pratinjau_selesai_proses(jenis: str, kode_proses: str,
        berat_akhir: float | None = None, user: User = Depends(pengguna_aksi)) -> dict:
    _require(await (_is_g1_operator(user) if jenis == "giling" else _is_g2_operator(user)))
    from app.services.penyelesaian_proses import ringkasan_selesai
    async with SessionLocal() as db:
        try:
            return await ringkasan_selesai(db, jenis=jenis, kode=kode_proses, berat_akhir=berat_akhir)
        except ValueError as e:
            raise HTTPException(409, str(e))


@router.post("/actions/akhiri-penyosohan")
async def act_akhiri_penyosohan(req: AkhiriPenyosohanReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g2_operator(user))
    if not req.dasar:
        raise HTTPException(409, "Periksa ringkasan penyelesaian penyosohan terlebih dahulu.")
    from app.penggilingan.gudang2.polishing import akhiri_penyosohan, Gudang2Error
    async with SessionLocal() as db:
        try:
            r = await akhiri_penyosohan(db, user=await db.get(User,user.id),
                                      kode=req.kode_proses, dasar=req.dasar)
        except (Gudang2Error, ValueError) as e:
            raise HTTPException(409, str(e))
    return {"ok": True, "pesan": f"Penyosohan {req.kode_proses} selesai. Hasil tercatat {r.beras_total:g} kg beras."}


@router.get("/actions/tumpukan-sisa")
async def tumpukan_sisa(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """PK di tumpukan Gudang 2 yang masih bersisa, per intake — untuk dipindah."""
    _require(await _is_g2_operator(user))
    from app.services.berjalan import _kartu_tumpukan_g2
    async with SessionLocal() as db:
        kartu = await _kartu_tumpukan_g2(db)
    return [{"value": b.nilai, "label": f"{b.judul} · {b.kode} · sisa {b.utama[0]} kg"}
            for b in kartu]


@router.get("/actions/sosoh-berjalan")
async def sosoh_berjalan(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Penyosohan yang berjalan DAN belum berhenti."""
    _require(await _is_g2_operator(user))
    from sqlalchemy import select
    from app.penggilingan.gudang1.services.jeda import jeda_terbuka
    from app.penggilingan.gudang2.models import PolishingProcess
    keluar = []
    async with SessionLocal() as db:
        for p in (await db.execute(
            select(PolishingProcess).where(PolishingProcess.status == "proses")
            .order_by(PolishingProcess.id.desc())
        )).scalars().all():
            if await jeda_terbuka(db, "penyosohan", p.id) is None:
                keluar.append({"value": f"penyosohan:{p.kode_proses}",
                               "label": f"{p.kode_proses} · sosoh"})
    return keluar


@router.get("/actions/silo-g2")
async def silo_g2_daftar(komoditas: str = "pk", induk: str = "",
                         user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Silo Gudang 2 campuran dari master, berisi atau tidak.

    Berbeda dari `silo-bahan-g2`, yang hanya menawarkan silo yang siap
    DISOSOH: ini daftar TUJUAN — silo kosong justru tujuan yang paling wajar.

    Semua silo Gudang 2 dapat menampung bahan campuran; pemanggil tetap
    memvalidasi kepemilikan dan saldo sebelum mencatat perpindahan.
    """
    _require(await _is_g2_operator(user) or can_see_financials(user))
    from sqlalchemy import select

    from app.models import Silo
    from app.penggilingan.gudang2.service import _g2_warehouse_id, hitung_stok_silo
    from app.penggilingan.silo_policy import boleh_masuk
    from app.penggilingan.gudang2.models import PkGudang2Intake
    from app.services.jasa import cocok_pemilik, pemilik_silo_g2

    keluar: list[dict] = []
    async with SessionLocal() as db:
        wid = await _g2_warehouse_id(db)
        intake = None
        if induk.strip().isdigit():
            intake = await db.get(PkGudang2Intake, int(induk.strip()))
        if induk.strip() and (not induk.strip().isdigit() or intake is None):
            return []
        for s in (await db.execute(
            select(Silo).where(Silo.warehouse_id == wid, Silo.aktif.is_(True))
            .order_by(Silo.nama_silo)
        )).scalars().all():
            if not boleh_masuk(s, komoditas, "g2"):
                continue
            if intake is not None:
                pemilik = await pemilik_silo_g2(db, s.id)
                if pemilik and not all(
                    [await cocok_pemilik(db, intake.jasa_id, p) for p in pemilik]
                ):
                    continue
            kg = await hitung_stok_silo(db, s.id)
            huruf = s.nama_silo.replace("Silo ", "")
            # Isinya ikut disebut: menuang ke silo yang sudah berisi bercampur
            # dengan isi lamanya, dan yang memilih berhak tahu itu sebelum
            # menekan, bukan sesudah.
            keluar.append({"value": huruf,
                           "label": f"{s.nama_silo} · {_rp(kg)} kg" if kg
                                    else f"{s.nama_silo} · kosong"})
    return keluar


@router.get("/actions/tujuan-pk-g2")
async def tujuan_pk_g2(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Ke mana PK bisa ditaruh di Gudang 2: tiap silo dari master, atau lantai."""
    daftar = await silo_g2_daftar(komoditas="pk", user=user)
    # Tumpukan di BAWAH: ia tempat menunggu, bukan tujuan yang dipilih lebih
    # dulu. Yang di atas dibaca lebih sering.
    return daftar + [{"value": "ditumpuk", "label": "Tumpukan (lantai)"}]


@router.get("/actions/silo-bahan-g2")
async def silo_bahan_g2(induk: str = "", user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Silo berisi atau silo kosong yang dibebaskan oleh proses yang dipilih.

    Daftarnya dari MASTER, bukan tupel huruf yang diketik di kode: silo Gudang
    2 bisa bertambah lewat Pengaturan → Alat, dan silo ketiga yang baru dibeli
    tak akan pernah muncul di "A / B / A+B".

    ⚠ SENGAJA tak menyaring `jenis_isi` — silo PK, broken, maupun Beras
    (keputusan pemilik 6 & 8 Oktober 2026) sama-sama bisa jadi bahan sosoh:
    `PolishingSiloUsage` SILO-AGNOSTIK (lihat CLAUDE.md "Silo broken"), dan
    `hitung_stok_silo` sudah bercabang sendiri menurut jenisnya. Menambah
    syarat `jenis_isi == 'pk'` di sini akan membuang silo broken/Beras yang
    genuinely berisi — kelas kerusakan yang sama dengan menyaring stok lewat
    kata tujuannya.

    Saringannya sama persis dengan pagar `mulai_penyosohan` — ada isinya, dan
    tak ada baris pemakaian pada proses yang berstatus 'proses'. Borang yang
    menawarkan silo yang kemudian ditolak layanannya membuat orang mengira
    aplikasinya rusak, padahal keduanya benar sendiri-sendiri — termasuk
    pagar "proses tak boleh memakan broken sendiri" di
    `tambah_silo_penyosohan` tetap diperiksa saat simpan. Bila picker
    dipanggil dengan `induk`, pilihan juga disaring ke pemilik proses itu.
    """
    _require(await _is_g2_operator(user))
    from sqlalchemy import select

    from app.models import Silo
    from app.penggilingan.gudang2.models import PolishingProcess, PolishingSiloUsage
    from app.penggilingan.gudang2.service import _g2_warehouse_id, hitung_stok_silo
    from app.services.jasa import cocok_pemilik, pemilik_silo_g2

    keluar: list[dict] = []
    async with SessionLocal() as db:
        pemilik_target = None
        dibebaskan = set()
        if induk.strip():
            proc = (await db.execute(select(PolishingProcess).where(
                PolishingProcess.kode_proses == induk.strip(),
                PolishingProcess.status == "proses",
            ))).scalars().first()
            if proc is None:
                return []
            pemilik_target = proc.jasa_id
            dibebaskan = set((await db.execute(select(PolishingSiloUsage.silo_id).where(
                PolishingSiloUsage.polishing_process_id == proc.id,
                PolishingSiloUsage.berat_akhir_kg.is_not(None)
            ))).scalars().all())
        dipakai = set((await db.execute(
            select(PolishingSiloUsage.silo_id)
            .join(PolishingProcess,
                  PolishingProcess.id == PolishingSiloUsage.polishing_process_id)
            .where(PolishingProcess.status == "proses",
                   PolishingSiloUsage.berat_akhir_kg.is_(None))
        )).scalars().all())
        wid = await _g2_warehouse_id(db)
        for s in (await db.execute(
            select(Silo).where(Silo.warehouse_id == wid, Silo.aktif.is_(True)).order_by(Silo.nama_silo)
        )).scalars().all():
            if s.id in dipakai:
                continue
            kg = await hitung_stok_silo(db, s.id)
            if kg <= 0 and s.id not in dibebaskan:
                continue
            if induk.strip():
                pemilik = await pemilik_silo_g2(db, s.id)
                if pemilik and not all(
                    [await cocok_pemilik(db, pemilik_target, p) for p in pemilik]
                ):
                    continue
            huruf = s.nama_silo.replace("Silo ", "")
            label = (f"{s.nama_silo} · kosong, gunakan kembali lalu isi bahan"
                     if kg <= 0 else f"{s.nama_silo} · {_rp(kg)} kg")
            keluar.append({"value": huruf, "label": label})
    return keluar


@router.get("/actions/silo-broken-g2")
async def silo_broken_g2(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Semua silo Gudang 2 dapat menjadi tujuan pemindahan broken campuran."""
    _require(await _is_g2_operator(user))
    from sqlalchemy import select

    from app.models import Silo
    from app.penggilingan.gudang2.service import _g2_warehouse_id, hitung_stok_silo
    from app.penggilingan.silo_policy import boleh_masuk

    keluar: list[dict] = []
    async with SessionLocal() as db:
        wid = await _g2_warehouse_id(db)
        for s in (await db.execute(
            select(Silo).where(Silo.warehouse_id == wid, Silo.aktif.is_(True))
            .order_by(Silo.nama_silo)
        )).scalars().all():
            if not boleh_masuk(s, "broken", "g2"):
                continue
            kg = await hitung_stok_silo(db, s.id)
            keluar.append({"value": s.nama_silo.replace("Silo ", ""),
                           "label": f"{s.nama_silo} · {_rp(kg)} kg" if kg
                                    else f"{s.nama_silo} · kosong"})
    return keluar


@router.get("/actions/broken-tersedia")
async def broken_tersedia(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Broken curah (`byproduct_stock`, lahir dari `catat_broken`) yang masih
    bersisa — belum habis dipindah ke silo. Sebangun `tumpukan-sisa`.
    """
    _require(await _is_g2_operator(user))
    from sqlalchemy import select

    from app.models import ByproductStock, PolishingProcess
    from app.penggilingan.gudang2.service import _sisa_broken_row
    from app.services.jasa import nama_pemilik

    keluar: list[dict] = []
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(ByproductStock, PolishingProcess.kode_proses)
            .join(PolishingProcess,
                  PolishingProcess.id == ByproductStock.source_id,
                  isouter=True)
            .where(ByproductStock.jenis_produk == "broken",
                   ByproductStock.source_type == "polishing")
            .order_by(ByproductStock.id.desc())
        )).all()
        for row, kode in rows:
            sisa = await _sisa_broken_row(db, row.id)
            if sisa <= 0:
                continue
            milik = await nama_pemilik(db, row.jasa_id)
            label = f"{kode or '-'} · sisa {_rp(sisa)} kg"
            if milik:
                label += f" · titipan {milik}"
            keluar.append({"value": str(row.id), "label": label})
    return keluar


@router.get("/actions/sosoh-silo")
async def sosoh_silo(induk: str = "", user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Silo yang dipakai satu proses penyosohan dan BELUM ditandai selesai.

    `induk` = kode proses, dikirim klien dari medan di atasnya (`data-induk`).
    Kosong → daftar kosong, bukan seluruh silo: daftar yang menjawab tanpa
    tahu prosesnya adalah daftar yang menawarkan silo yang tak pernah dipakai —
    dan itulah kesalahan yang medan ini menggantikan.

    Yang sudah bersisa (`berat_akhir_kg` terisi) tidak ditawarkan lagi:
    menandainya dua kali menimpa angka yang sudah dicatat operator.
    """
    _require(await _is_g2_operator(user))
    kode = (induk or "").strip()
    if not kode:
        return []
    from sqlalchemy import select

    from app.models import Silo
    from app.penggilingan.gudang2.models import PolishingProcess, PolishingSiloUsage
    async with SessionLocal() as db:
        proc = (await db.execute(select(PolishingProcess).where(
            PolishingProcess.kode_proses == kode))).scalars().first()
        if proc is None:
            return []
        baris = (await db.execute(
            select(PolishingSiloUsage, Silo)
            .join(Silo, Silo.id == PolishingSiloUsage.silo_id)
            .where(PolishingSiloUsage.polishing_process_id == proc.id)
            .order_by(Silo.nama_silo)
        )).all()
    keluar = []
    for u, silo in baris:
        if u.berat_akhir_kg is not None:
            continue
        huruf = (silo.nama_silo or "").replace("Silo ", "").strip()
        masuk = float(u.berat_masuk_kg or 0)
        isi = float(u.berat_awal_kg or 0) + masuk
        keluar.append({"value": huruf,
                       "label": f"{silo.nama_silo} · bahan {_rp(isi)} kg"
                                + (f" (awal {_rp(u.berat_awal_kg)} + ditambah {_rp(masuk)})"
                                   if masuk else "")})
    return keluar


@router.get("/actions/sosoh-berhenti")
async def sosoh_berhenti(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Penyosohan yang sedang berhenti, berikut sebab & sejak kapan."""
    _require(await _is_g2_operator(user))
    from sqlalchemy import select
    from app.database import now_local
    from app.models import JedaProses
    from app.penggilingan.gudang2.models import PolishingProcess
    keluar = []
    async with SessionLocal() as db:
        kini = now_local()
        for j, kode in (await db.execute(
            select(JedaProses, PolishingProcess.kode_proses)
            .join(PolishingProcess, PolishingProcess.id == JedaProses.polishing_process_id)
            .where(JedaProses.jenis == "penyosohan", JedaProses.selesai.is_(None),
                   JedaProses.dibatalkan_pada.is_(None),
                   PolishingProcess.status == "proses")
            .order_by(JedaProses.mulai)
        )).all():
            jam = (kini - j.mulai).total_seconds() / 3600
            keluar.append({"value": f"penyosohan:{kode}",
                           "label": f"{kode} · {j.sebab} · {jam:.1f} jam"})
    return keluar


class PindahTumpukanSiloReq(BaseModel):
    tumpukan: str    # id intake tumpukan (dari /actions/tumpukan-sisa)
    silo: str        # nama silo dari master Gudang 2
    #: Kosong = SELURUH sisa tumpukan. Bukan kelalaian: satu-satunya angka
    #: yang sulit diketik benar adalah sisa terakhir, dan yang tak perlu
    #: diketik tak bisa salah ketik.
    berat_kg: float | None = None
    #: Kunci kiriman (Tahap 3), opsional — lihat `GabahMasukReq`.
    kunci_kiriman: str | None = None


@router.post("/actions/pindah-tumpukan-silo")
async def act_pindah_tumpukan_silo(req: PindahTumpukanSiloReq,
                                   user: User = Depends(pengguna_aksi)) -> dict:
    """Operator Gudang 2 memindahkan PK dari lantai ke silo — boleh sebagian.

    Fungsinya sudah lama ada (`pindah_tumpukan_ke_silo`, kode PTS) tetapi tak
    punya pintu di layar; sejak 12 September 2026 ia pekerjaan operator
    (keputusan pemilik). Silo yang sedang dipoles boleh menerima — yang
    dituang ikut dihitung sebagai bahan proses itu.

    ⚠ Gerbangnya BUKAN cuma `_is_g2_operator` (lihat catatan panjang pada
    `minta_pk_g1`) — nama itu menyesatkan: artinya "admin, ATAU operator yang
    sedang di Gudang 2", bukan "operator Gudang 2 saja". `and not
    can_see_financials` DI SINILAH yang menyempitkannya — keputusan pemilik
    4 Oktober 2026: yang memindahkan barang adalah yang memegang barang, dan
    PK yang menumpuk saat tak ada operator Gudang 2 bertugas memang TETAP di
    lantai sampai ada operator. Jangan menghapus klausa ini karena mengira
    `_is_g2_operator` saja sudah cukup sempit.

    ⚠⚠ `or super_saja` ditambahkan 5 Oktober 2026: kartu PK di layar Stok
    kini menawarkan tombol ini langsung per kode bahan, dan pemilik memintanya
    untuk "operator atau super admin" — Super Admin TETAP boleh walau ia juga
    `can_see_financials`. Admin biasa tidak; klausa yang menyempitkannya di
    atas tak berubah, ini cuma jaring pengaman di atasnya. Katalog aksi
    (`actions_menu`) punya carve-out YANG SAMA (`super_`) — tanpanya tombol di
    kartu Stok akan tampil untuk Super Admin lalu tak berbuat apa-apa, sebab
    `MENU[id]` tak pernah terisi baginya.
    """
    from hmu_identitas import peran as P

    _require((await _is_g2_operator(user) and not can_see_financials(user))
             or P.super_saja(user.role))
    if not str(req.tumpukan or "").strip().isdigit():
        raise HTTPException(400, "Pilih PK di tumpukan yang mau dipindah dulu.")
    if not (req.silo or "").strip():
        raise HTTPException(400, "Pilih silo tujuan dulu.")
    # KOSONG dan NOL dua hal berbeda: kosong berarti "seluruh sisanya", nol
    # berarti salah ketik. Menyamakan keduanya membuat satu ketukan Enter di
    # kotak kosong memindahkan seluruh tumpukan tanpa diminta.
    if req.berat_kg is not None and float(req.berat_kg) <= 0:
        raise HTTPException(
            400, "Isi berat yang dipindah lebih dari 0 — atau kosongkan "
                 "kotaknya untuk memindahkan seluruh sisanya.")
    from app.penggilingan.gudang2.service import Gudang2Error, pindah_tumpukan_ke_silo
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await pindah_tumpukan_ke_silo(
                db, user=u, intake_id=int(req.tumpukan), nama_silo=req.silo.strip(),
                berat=(None if req.berat_kg is None else float(req.berat_kg)),
                kunci_kiriman=(req.kunci_kiriman or "")[:120] or None)
        except Gudang2Error as e:
            raise _err(e, "Gagal memindahkan PK dari tumpukan.")
    sisa = (f"sisa di tumpukan {r.sisa_tumpukan_intake:g} kg"
            if r.sisa_tumpukan_intake > 0 else "tumpukan itu habis")
    ekor = f" — ikut dihitung di {r.ke_proses}" if r.ke_proses else ""
    return {"ok": True,
            "pesan": f"✓ *{r.kode_pindah}* · {r.berat_kg:g} kg ke {r.nama_silo} "
                     f"({sisa}){ekor}."}


class PindahBrokenSiloReq(BaseModel):
    broken: str      # id baris byproduct_stock (dari /actions/broken-tersedia)
    silo: str        # nama silo broken, mis. "C"
    #: Kosong = SELURUH sisa baris broken itu — lihat PindahTumpukanSiloReq.
    berat_kg: float | None = None


@router.post("/actions/pindah-broken-silo")
async def act_pindah_broken_silo(req: PindahBrokenSiloReq,
                                 user: User = Depends(pengguna_aksi)) -> dict:
    """Operator Gudang 2 memindahkan broken curah ke silo broken — boleh
    sebagian. Sebangun `act_pindah_tumpukan_silo` (gerbang & bentuk borang
    sama); lihat catatan panjangnya di sana untuk alasan gerbangnya.

    ⚠ Silo BUKAN "A" atau "B" tetap: berbeda dari pindah tumpukan PK (yang
    masih menyimpan dua huruf itu secara harfiah — peninggalan lama, bukan
    pola yang ditiru di sini), silo broken BOLEH bernama apa pun dari master.
    """
    from hmu_identitas import peran as P

    _require((await _is_g2_operator(user) and not can_see_financials(user))
             or P.super_saja(user.role))
    if not str(req.broken or "").strip().isdigit():
        raise HTTPException(400, "Pilih broken curah yang mau dipindah dulu.")
    if not (req.silo or "").strip():
        raise HTTPException(400, "Pilih silo broken tujuan dulu.")
    if req.berat_kg is not None and float(req.berat_kg) <= 0:
        raise HTTPException(
            400, "Isi berat yang dipindah lebih dari 0 — atau kosongkan "
                 "kotaknya untuk memindahkan seluruh sisanya.")
    from app.penggilingan.gudang2.service import Gudang2Error, pindah_broken_ke_silo
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await pindah_broken_ke_silo(
                db, user=u, byproduct_stock_id=int(req.broken), nama_silo=req.silo.strip(),
                berat=(None if req.berat_kg is None else float(req.berat_kg)))
        except Gudang2Error as e:
            raise _err(e, "Gagal memindahkan broken ke silo.")
    sisa = (f"sisa broken curah {r.sisa_broken:g} kg"
            if r.sisa_broken > 0 else "broken curah itu habis")
    ekor = f" — ikut dihitung di {r.ke_proses}" if r.ke_proses else ""
    return {"ok": True,
            "pesan": f"✓ *{r.kode_pindah}* · {r.berat_kg:g} kg ke Silo {r.nama_silo} "
                     f"({sisa}){ekor}."}


@router.get("/actions/broken-proses-tersedia")
async def broken_proses_tersedia(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Proses penyosohan (berikut pemiliknya) yang masih punya broken untuk
    dimasukkan ke silo — curah MAUPUN berkarung dijumlah jadi SATU angka,
    sebab `masukkan_broken_ke_silo` sendiri yang memutuskan sumbernya.

    Satu baris per (proses, pemilik) — dua pemilik pada proses yang sama
    (sebagian sudah pindah kepemilikan) tampil sebagai dua pilihan terpisah,
    sebab keduanya tak boleh tercampur dalam SATU pemindahan ke silo.

    ⚠ Curah dijumlah PER-PROSES lewat `_sisa_broken_row` atas baris
    `byproduct_stock` proses itu SAJA — BUKAN `hitung_stok_broken_curah()`
    (itu GLOBAL atas seluruh pemilik, tak menerima `source_id`/proses sama
    sekali). Dua proses pemilik yang sama dulu menampilkan angka curah yang
    SAMA PERSIS (keduanya membaca total global yang sama), sampai-sampai
    proses yang curahnya sendiri sudah nol tetap tampil seolah masih
    berbobot — lalu ditolak saat disubmit, sebab `masukkan_broken_ke_silo`
    sendiri SUDAH benar menyaring per-`source_id`. Borang yang menawarkan
    sesuatu yang kemudian ditolak layanannya membuat orang mengira
    aplikasinya rusak — laporan lapangan 10 Oktober 2026.

    Proses `proses` dan `selesai` ditawarkan bila masih ada stok broken.
    Hasil yang belum dibuat menjadi baris ledger juga ikut dihitung karena
    broken otomatis tersedia sebagai stok/kemasan setelah keluar mesin.

    Angka hasil mesin yang belum dialokasikan (`output_sosoh −
    _broken_dibukukan`) hanya ditambahkan untuk PEMILIK BAWAAN proses
    (`pemilik_hasil_proses`). Pemilik yang menerima sebagian lewat "Pindah
    kepemilikan" tak ikut memiliki hasil mentah yang belum dialokasikan.
    """
    _require(await _is_g2_operator(user))
    from sqlalchemy import func, select

    from app.models import ByproductStock, FinishedGoodsStock, PolishingProcess, ProductSku
    from app.penggilingan.gudang2.service import _sisa_broken_row
    from app.services.jasa import nama_pemilik, pemilik_hasil_proses
    from app.services.stok import output_sosoh

    keluar: list[dict] = []
    async with SessionLocal() as db:
        proses_sumber = {p.id: p for p in (await db.execute(
            select(PolishingProcess).where(
                PolishingProcess.status.in_(("proses", "selesai")))
        )).scalars().all()}

        # Broken hasil penerimaan tiket tetap stok bertumpuk dan harus bisa
        # dipilih dari kartu stok untuk dipindahkan ke silo.
        stok_timbangan = (await db.execute(
            select(ByproductStock.id, ByproductStock.jasa_id)
            .where(ByproductStock.jenis_produk == "broken",
                   ByproductStock.source_type == "timbangan")
        )).all()
        for stock_id, owner_id in stok_timbangan:
            available = await _sisa_broken_row(db, stock_id)
            if available > 0.5:
                keluar.append({"pemilik": owner_id, "kg": available})

        pasangan: set[tuple[int, int | None]] = set()
        if proses_sumber:
            pasangan |= set((await db.execute(
                select(ByproductStock.source_id, ByproductStock.jasa_id)
                .where(ByproductStock.jenis_produk == "broken",
                       ByproductStock.source_type == "polishing",
                       ByproductStock.source_id.in_(proses_sumber))
            )).all())
            pasangan |= set((await db.execute(
                select(FinishedGoodsStock.source_id, FinishedGoodsStock.jasa_id)
                .join(ProductSku, ProductSku.id == FinishedGoodsStock.product_sku_id)
                .where(ProductSku.kategori == "broken",
                       FinishedGoodsStock.source_type == "polishing",
                       FinishedGoodsStock.source_id.in_(proses_sumber))
            )).all())
        pemilik_bawaan: dict[int, int | None] = {}
        for proc_id, proc in proses_sumber.items():
            pb = await pemilik_hasil_proses(db, proc.jasa_id, "broken")
            pemilik_bawaan[proc_id] = pb
            # Broken hasil mesin otomatis tersedia setelah proses ditutup
            # juga, walau belum punya baris stok terpisah.
            pasangan.add((proc_id, pb))

        for proc_id, jasa_id in sorted(pasangan, key=lambda x: (x[0], x[1] or 0)):
            proc = proses_sumber.get(proc_id)
            if proc is None:
                continue
            baris_curah = (await db.execute(
                select(ByproductStock.id)
                .where(ByproductStock.jenis_produk == "broken",
                       ByproductStock.source_type == "polishing",
                       ByproductStock.source_id == proc_id,
                       (ByproductStock.jasa_id.is_(None) if jasa_id is None
                        else ByproductStock.jasa_id == jasa_id))
            )).scalars().all()
            curah = sum([await _sisa_broken_row(db, rid) for rid in baris_curah]) \
                if baris_curah else 0.0
            karung = float((await db.execute(
                select(func.coalesce(func.sum(FinishedGoodsStock.berat_total_kg), 0))
                .join(ProductSku, ProductSku.id == FinishedGoodsStock.product_sku_id)
                .where(ProductSku.kategori == "broken",
                       FinishedGoodsStock.source_type == "polishing",
                       FinishedGoodsStock.source_id == proc_id,
                       (FinishedGoodsStock.jasa_id.is_(None) if jasa_id is None
                        else FinishedGoodsStock.jasa_id == jasa_id))
            )).scalar_one())
            belum_dicatat = 0.0
            if jasa_id == pemilik_bawaan.get(proc_id):
                keluar_mesin = (await output_sosoh(db, proc_id)).get("broken") or 0.0
                curah_tercatat = float((await db.execute(
                    select(func.coalesce(func.sum(ByproductStock.berat_kg), 0))
                    .where(ByproductStock.jenis_produk == "broken",
                           ByproductStock.source_type == "polishing",
                           ByproductStock.source_id == proc_id,
                           (ByproductStock.jasa_id.is_(None) if jasa_id is None
                            else ByproductStock.jasa_id == jasa_id))
                )).scalar_one())
                belum_dicatat = max(
                    0.0, float(keluar_mesin) - curah_tercatat - karung)
            total = curah + karung + belum_dicatat
            if total <= 0.5:
                continue
            kode = proc.kode_proses
            milik = await nama_pemilik(db, jasa_id)
            label = f"{kode} · {_kg(total)} (curah {_kg(curah)} + kemasan {_kg(karung)}"
            if belum_dicatat > 0.5:
                label += f" + hasil otomatis {_kg(belum_dicatat)}"
            label += ")"
            if milik:
                label += f" · titipan {milik}"
            keluar.append({"pemilik": jasa_id, "kg": total})
        grouped: dict[int | None, float] = {}
        for item in keluar:
            owner = item["pemilik"]
            grouped[owner] = grouped.get(owner, 0.0) + item["kg"]
        keluar = []
        for owner, total in sorted(grouped.items(), key=lambda x: (x[0] is not None, x[0] or 0)):
            owner_name = await nama_pemilik(db, owner)
            label = f"{'Pabrik' if owner is None else owner_name} · {_kg(total)} tersedia"
            keluar.append({"value": f"pemilik|{'pabrik' if owner is None else owner}",
                           "label": label})
    return keluar


class MasukkanBrokenSiloReq(BaseModel):
    proses: str      # "<kode_pol>|<jasa_id atau kosong>", dari picker di atas
    silo: str        # nama silo broken, mis. "C"
    berat_kg: Positif


class MasukkanHasilSampingSiloReq(BaseModel):
    pemilik: str
    silo: str
    berat_kg: Positif


@router.get("/actions/hasil-samping-pemilik-tersedia")
async def hasil_samping_pemilik_tersedia(jenis: str = "menir",
                                         user: User = Depends(pengguna_aksi)) -> list[dict]:
    _require(await _is_g2_operator(user))
    jenis = jenis.strip().lower()
    if jenis not in {"menir", "reject"}:
        raise HTTPException(400, "Jenis stok harus Menir atau Reject.")
    from sqlalchemy import select
    from app.models import FinishedGoodsStock, PolishingProcess, ProductSku
    from app.services.jasa import nama_pemilik
    from app.services.stok import stok_produk

    async with SessionLocal() as db:
        owners = set((await db.execute(select(PolishingProcess.jasa_id))).scalars().all())
        owners.update((await db.execute(
            select(FinishedGoodsStock.jasa_id).join(
                ProductSku, ProductSku.id == FinishedGoodsStock.product_sku_id)
            .where(ProductSku.kategori == jenis)
        )).scalars().all())
        options = []
        for owner in owners:
            cards = await stok_produk(db, jasa_id=owner)
            card = next((c for c in cards if c.jenis == jenis), None)
            available = float(card.sisa_kg) if card else 0.0
            if available <= 0.5:
                continue
            owner_name = await nama_pemilik(db, owner)
            label = "Pabrik" if owner is None else owner_name or f"Pemilik #{owner}"
            options.append({"value": f"pabrik" if owner is None else str(owner),
                            "label": f"{label} · {_kg(available)} tersedia"})
    return sorted(options, key=lambda x: (x["value"] != "pabrik", x["label"]))


@router.get("/actions/silo-hasil-samping-g2")
async def silo_hasil_samping_g2(jenis: str = "menir",
                                user: User = Depends(pengguna_aksi)) -> list[dict]:
    _require(await _is_g2_operator(user))
    jenis = jenis.strip().lower()
    if jenis not in {"menir", "reject"}:
        raise HTTPException(400, "Jenis silo tidak valid.")
    from sqlalchemy import select
    from app.models import Silo
    from app.penggilingan.gudang2.service import _g2_warehouse_id, hitung_stok_silo
    from app.penggilingan.silo_policy import boleh_masuk

    async with SessionLocal() as db:
        wid = await _g2_warehouse_id(db)
        silos = (await db.execute(
            select(Silo).where(Silo.warehouse_id == wid, Silo.aktif.is_(True))
            .order_by(Silo.nama_silo))).scalars().all()
        options = []
        for silo in silos:
            if not boleh_masuk(silo, jenis, "g2"):
                continue
            kg = await hitung_stok_silo(db, silo.id)
            options.append({"value": silo.nama_silo.replace("Silo ", ""),
                            "label": f"{silo.nama_silo} · {_rp(kg)} kg" if kg
                                     else f"{silo.nama_silo} · kosong"})
    return options


async def _act_masukkan_hasil_samping(req: MasukkanHasilSampingSiloReq,
                                      jenis: str, user: User) -> dict:
    from hmu_identitas import peran as P
    _require((await _is_g2_operator(user) and not can_see_financials(user))
             or P.super_saja(user.role))
    owner = (req.pemilik or "").strip()
    if owner != "pabrik" and not owner.isdigit():
        raise HTTPException(422, "Pilih pemilik stok yang valid.")
    from app.penggilingan.gudang2.service import Gudang2Error, masukkan_hasil_samping_ke_silo
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            result = await masukkan_hasil_samping_ke_silo(
                db, user=u, jenis=jenis,
                jasa_id=None if owner == "pabrik" else int(owner),
                nama_silo=req.silo.strip(), berat_kg=float(req.berat_kg))
        except Gudang2Error as e:
            raise _err(e, f"Gagal memasukkan {jenis} ke silo.")
    return {"ok": True, "pesan": f"✓ {result['moved_kg']:,.2f} kg {jenis} masuk "
            f"ke {result['nama_silo']}.".replace(",", ".")}


@router.post("/actions/masukkan-menir-silo")
async def act_masukkan_menir_silo(req: MasukkanHasilSampingSiloReq,
                                 user: User = Depends(pengguna_aksi)) -> dict:
    return await _act_masukkan_hasil_samping(req, "menir", user)


@router.post("/actions/masukkan-reject-silo")
async def act_masukkan_reject_silo(req: MasukkanHasilSampingSiloReq,
                                   user: User = Depends(pengguna_aksi)) -> dict:
    return await _act_masukkan_hasil_samping(req, "reject", user)


@router.post("/actions/masukkan-broken-silo")
async def act_masukkan_broken_silo(req: MasukkanBrokenSiloReq,
                                   user: User = Depends(pengguna_aksi)) -> dict:
    """SATU aksi: masukkan broken ke silo — mengganti "Catat broken (curah)"
    + "Pindah broken ke silo" (laporan pemilik 7 Oktober 2026). Sumbernya
    otomatis: curah dulu, lalu karung dibongkar bila kurang — lihat
    `gudang2.service.masukkan_broken_ke_silo`.

    Gerbangnya SAMA dengan `act_pindah_broken_silo` yang digantikannya.
    """
    from hmu_identitas import peran as P

    _require((await _is_g2_operator(user) and not can_see_financials(user))
             or P.super_saja(user.role))
    pilihan = (req.proses or "").strip()
    if not pilihan:
        raise HTTPException(400, "Pilih pemilik stok broken dulu.")
    if not (req.silo or "").strip():
        raise HTTPException(400, "Pilih silo broken tujuan dulu.")
    from app.penggilingan.gudang2.service import (Gudang2Error,
        masukkan_broken_ke_silo, masukkan_stok_broken_pemilik_ke_silo)
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            if pilihan.startswith("pemilik|"):
                owner = pilihan.partition("|")[2]
                if owner != "pabrik" and not owner.isdigit():
                    raise HTTPException(422, "Pilihan pemilik stok tidak valid.")
                r = await masukkan_stok_broken_pemilik_ke_silo(
                    db, user=u, jasa_id=None if owner == "pabrik" else int(owner),
                    nama_silo=req.silo.strip(), berat_kg=float(req.berat_kg))
            else:
                kode_pol, _, jasa_txt = pilihan.partition("|")
                jasa_id = int(jasa_txt) if jasa_txt.isdigit() else None
                r = await masukkan_broken_ke_silo(
                    db, user=u, kode_pol=kode_pol, nama_silo=req.silo.strip(),
                    berat_kg=float(req.berat_kg), jasa_id=jasa_id)
        except Gudang2Error as e:
            raise _err(e, "Gagal memasukkan broken ke silo.")
    ekor = (f" (termasuk {r.dibongkar_dari_karung_kg:,.0f} kg dibongkar dari karung)"
           .replace(",", ".") if r.dibongkar_dari_karung_kg else "")
    return {"ok": True,
            "pesan": f"✓ {r.moved_kg:,.0f} kg masuk Silo {r.nama_silo}{ekor}."
                     .replace(",", ".")}


@router.get("/actions/silo-beras-tujuan-g2")
async def silo_beras_tujuan_g2(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Semua silo Gudang 2 dapat menerima beras putih sebagai bahan campuran."""
    _require(await _is_g2_operator(user))
    from sqlalchemy import select

    from app.models import Silo
    from app.penggilingan.gudang2.service import _g2_warehouse_id, hitung_stok_silo
    from app.penggilingan.silo_policy import boleh_masuk

    keluar: list[dict] = []
    async with SessionLocal() as db:
        wid = await _g2_warehouse_id(db)
        for s in (await db.execute(
            select(Silo).where(Silo.warehouse_id == wid, Silo.aktif.is_(True))
            .order_by(Silo.nama_silo)
        )).scalars().all():
            if not boleh_masuk(s, "beras_putih", "g2"):
                continue
            kg = await hitung_stok_silo(db, s.id)
            keluar.append({"value": s.nama_silo.replace("Silo ", ""),
                           "label": f"{s.nama_silo} · {_rp(kg)} kg"
                                    if kg else f"{s.nama_silo} · kosong"})
    return keluar


@router.get("/actions/beras-jenis-silo")
async def beras_jenis_silo(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Pilihan internal jenis+lingkup stok; tautan kartu mengunci pilihannya."""
    _require(await _is_g2_operator(user))
    from app.services.stok import BERAS_JENIS, nama_produk
    return [
        {"value": f"{jenis}|{scope}",
         "label": f"{nama_produk(jenis)} · {'stok pabrik' if scope == 'pabrik' else 'stok jasa'}"}
        for jenis in BERAS_JENIS for scope in ("pabrik", "jasa")
    ]


@router.get("/actions/beras-sumber-tersedia")
async def beras_sumber_tersedia(induk: str | None = None,
                                user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Daftar curah/kemasan untuk grade dan lingkup pemilik pada kartu."""
    _require(await _is_g2_operator(user))
    from sqlalchemy import select

    from app.models import FinishedGoodsStock, PolishingProcess, ProductSku
    from app.penggilingan.gudang2.models import PolishingOutputLog
    from app.penggilingan.inventory.finished_goods import (
        _packed_kg, get_standard, sisa_karung_per_sumber)
    from app.services.jasa import nama_pemilik
    from app.services.stok import BERAS_JENIS, _dipindah_silo_proc, output_sosoh
    from hmu_core import Brand, PackageSize, PackagingMaterial

    try:
        jenis, scope = (induk or "").split("|", 1)
    except ValueError:
        return []
    jenis, scope = jenis.strip().lower(), scope.strip().lower()
    if jenis not in BERAS_JENIS or scope not in {"pabrik", "jasa"}:
        return []

    keluar: list[dict] = []
    async with SessionLocal() as db:
        kategori_sku = "beras_b" if jenis == "beras_b" else "beras_putih"
        std = await get_standard(db, jenis)
        std_filter = (FinishedGoodsStock.rice_quality_standard_id.is_(None)
                      if std is None else
                      FinishedGoodsStock.rice_quality_standard_id == std.id)
        if scope == "pabrik":
            owners = [None]
        else:
            owners = set((await db.execute(
                select(PolishingProcess.jasa_id)
                .join(PolishingOutputLog,
                      PolishingOutputLog.polishing_process_id == PolishingProcess.id)
                .where(PolishingProcess.jasa_id.is_not(None),
                       PolishingOutputLog.jenis == jenis)
                .distinct()
            )).scalars().all())
            owners.update((await db.execute(
                select(FinishedGoodsStock.jasa_id)
                .join(ProductSku, ProductSku.id == FinishedGoodsStock.product_sku_id)
                .where(ProductSku.kategori == kategori_sku,
                       FinishedGoodsStock.jasa_id.is_not(None),
                       std_filter)
                .distinct()
            )).scalars().all())
            owners = sorted(owners)

        for owner in owners:
            owner_token = "pabrik" if owner is None else str(owner)
            owner_label = "" if owner is None else (await nama_pemilik(db, owner) or "Jasa")
            owner_suffix = f" · {owner_label}" if owner_label else ""

            proc_rows = (await db.execute(
                select(PolishingProcess.id)
                .join(PolishingOutputLog,
                      PolishingOutputLog.polishing_process_id == PolishingProcess.id)
                .where(PolishingOutputLog.jenis == jenis,
                       PolishingProcess.jasa_id.is_(None) if owner is None
                       else PolishingProcess.jasa_id == owner)
                .distinct()
            )).scalars().all()
            curah_total = 0.0
            for proc_id in proc_rows:
                hasil = (await output_sosoh(db, proc_id)).get(jenis, 0.0)
                dikemas = await _packed_kg(
                    db, proc_id, kategori_sku, std.id if std else None)
                dipindah = (await _dipindah_silo_proc(db, [proc_id])).get(
                    (proc_id, jenis), 0.0)
                curah_total += max(0.0, float(hasil) - dikemas - dipindah)
            if curah_total > 0.5:
                keluar.append({"value": f"curah|{owner_token}",
                               "label": f"Curah{owner_suffix} · "
                                        f"{_kg(curah_total)} tersedia"})

            milik = (FinishedGoodsStock.jasa_id.is_(None) if owner is None
                     else FinishedGoodsStock.jasa_id == owner)
            skus = (await db.execute(
                select(ProductSku.id, Brand.nama, PackagingMaterial.nama,
                       PackageSize.ukuran_kg)
                .join(FinishedGoodsStock,
                      FinishedGoodsStock.product_sku_id == ProductSku.id)
                .join(Brand, Brand.id == ProductSku.brand_id, isouter=True)
                .join(PackagingMaterial,
                      PackagingMaterial.id == ProductSku.packaging_material_id)
                .join(PackageSize, PackageSize.id == ProductSku.package_size_id)
                .where(ProductSku.kategori == kategori_sku,
                       std_filter, milik)
                .group_by(ProductSku.id, Brand.nama, PackagingMaterial.nama,
                          PackageSize.ukuran_kg)
                .order_by(Brand.nama, PackagingMaterial.nama,
                          PackageSize.ukuran_kg)
            )).all()
            for sku_id, brand, material, ukuran in skus:
                sisa = await sisa_karung_per_sumber(
                    db, sku_id, std.id if std else None, jasa_id=owner,
                    source_type=None)
                karung = sum(jumlah for _, jumlah, _ in sisa)
                if karung <= 0:
                    continue
                label = " · ".join(x for x in (brand or "Tanpa merek", material,
                                                f"{ukuran} kg") if x)
                keluar.append({
                    "value": f"sku:{sku_id}|{owner_token}",
                    "label": (f"{label}{owner_suffix} · {karung} karung · "
                              f"{_kg(karung * float(ukuran))} tersedia"),
                })
    return keluar


class MasukkanBerasSiloReq(BaseModel):
    jenis: str       # grade|pabrik atau grade|jasa, otomatis dari kartu stok
    sumber_stok: str # curah|pemilik atau sku:<id>|pemilik
    silo: str        # nama silo Beras atau PK, mis. "C"
    berat_kg: Positif


@router.post("/actions/masukkan-beras-silo")
async def act_masukkan_beras_silo(req: MasukkanBerasSiloReq,
                                  user: User = Depends(pengguna_aksi)) -> dict:
    """SATU aksi: masukkan beras ke silo — grade ke Silo Beras (campuran),
    `beras_putih` ke silo PK (bahan sosoh ulang). Lihat `gudang2.service.
    masukkan_beras_ke_silo`. Gerbangnya SAMA dengan `act_masukkan_broken_silo`.
    """
    from hmu_identitas import peran as P

    _require((await _is_g2_operator(user) and not can_see_financials(user))
             or P.super_saja(user.role))
    try:
        jenis, scope = (req.jenis or "").strip().lower().split("|", 1)
    except ValueError:
        raise HTTPException(400, "Jenis beras dan lingkup pemilik tidak terbaca.") from None
    if scope not in {"pabrik", "jasa"}:
        raise HTTPException(400, "Lingkup stok beras tidak valid.")
    if not jenis:
        raise HTTPException(400, "Jenis beras dari kartu stok tidak terbaca.")
    if not (req.silo or "").strip():
        raise HTTPException(400, "Pilih silo tujuan dulu.")
    if not (req.sumber_stok or "").strip():
        raise HTTPException(400, "Pilih bentuk stok yang akan dipindahkan.")
    sumber, _, owner_token = req.sumber_stok.partition("|")
    if not owner_token or ((scope == "pabrik") != (owner_token == "pabrik")):
        raise HTTPException(400, "Pemilik stok tidak cocok dengan kartu yang dipilih.")
    jasa_id = None
    if owner_token != "pabrik":
        if scope != "jasa" or not owner_token.isdigit():
            raise HTTPException(400, "Pemilik stok jasa tidak valid.")
        jasa_id = int(owner_token)
    from app.penggilingan.gudang2.service import Gudang2Error, masukkan_beras_ke_silo
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await masukkan_beras_ke_silo(
                db, user=u, jenis=jenis, nama_silo=req.silo.strip(),
                berat_kg=float(req.berat_kg), jasa_id=jasa_id,
                sumber_stok=sumber)
        except Gudang2Error as e:
            raise _err(e, "Gagal memasukkan beras ke silo.")
    ekor = (f" (termasuk {r.dibongkar_dari_karung_kg:,.0f} kg dibongkar dari karung)"
           .replace(",", ".") if r.dibongkar_dari_karung_kg else "")
    return {"ok": True,
            "pesan": f"✓ {r.moved_kg:,.0f} kg masuk Silo {r.nama_silo}{ekor}."
                     .replace(",", ".")}


# ─────────────────────────── Halaman aksi ───────────────────────────

