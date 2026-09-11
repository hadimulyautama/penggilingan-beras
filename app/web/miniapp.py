"""API aksi Pos Produksi: identitas, dashboard, dan katalog AKSI per peran.

Prefiksnya masih `/miniapp` dari masa ketika layar pencatatan memang Mini App
Telegram. Halaman itu sendiri sudah dibuang bersama botnya — yang memanggil
endpoint ini sekarang Pos Produksi di peramban, dengan sesi webapp.

Menu aksi ditentukan SERVER per peran, bukan disalin ke klien: menambah aksi
tak perlu layar baru, dan peran yang tak berhak tak pernah menerima bentuk
formulirnya.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from typing import Annotated

from pydantic import BaseModel, Field

from app.services.angka import (Persen, PersenOpsional, Positif,
                                PositifOpsional)

from app.peran import PERAN_ADMIN_KEATAS, can_see_financials, can_transfer_pk
from app.penggilingan.gudang1.services.drying import MODE_DRYER
from app.penggilingan.gudang1.services.jeda import SEBAB_LAIN as SEBAB_LAIN_JEDA
from app.database import SessionLocal
from app.models import User
from app.web.aksi_umum import galat as _err
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


# ──────────────────────── Penanda keadaan ────────────────────────

@router.get("/keadaan")
async def keadaan(user: User = Depends(pengguna_aksi)) -> dict:
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

    async with SessionLocal() as db:
        n = (await db.execute(select(func.max(ActivityLog.id)))).scalar() or 0
        t = (await db.execute(text(
            "select coalesce(max(id), 0), "
            "coalesce(cast(extract(epoch from max(updated_at)) as bigint), 0) "
            "from timbangan_transaksi"
        ))).first()
    return {"n": f"{n}.{t[0]}.{t[1]}"}


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
            sections.append({"icon": "💰", "title": "HPP beras terkini",
                             "body": await _hpp_terkini(db)})
    return {"user": {"nama": user.nama, "role": user.role, "see_financials": fin},
            "sections": sections}


# ─────────────────────── Aksi cepat: role helper ───────────────────────

async def _is_wh_operator(user: User, like: str) -> bool:
    """Admin KE ATAS selalu boleh; operator hanya bila gudang defaultnya cocok.

    Dulu berbunyi `if user.role == "admin"` lalu menolak apa pun yang bukan
    `"operator"` — sehingga SUPERADMIN jatuh ke penolakan dan kehilangan
    SELURUH aksi gudang. Terlihat saat pemilik membandingkan tampilan: peran
    tertinggi menampilkan 14 aksi, admin di bawahnya 30.

    Ini kali keempat pola yang sama dalam dua hari (delapan gerbang produksi,
    sembilan gerbang Kantor, penjaga akun tertinggi, dan di sini) — peran baru
    ditambahkan di puncak, gerbang lama menyebut nama peran satu per satu.
    """
    peran = (user.role or "").strip().lower()
    if peran in PERAN_ADMIN_KEATAS:
        return True
    if peran != "operator":
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
AKSI_MUTU = {"qc_giling", "qc_pk_luar"}


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
        # Setelan dibaca sekali per permintaan menu — daftar sebab dan
        # target bawaan sama-sama bisa diubah admin, dan spesifikasi aksi yang
        # membekukannya akan menampilkan pilihan yang sudah dibuang.
        from app.services.setelan import sebab_jeda, target_kadar_air

        async with SessionLocal() as db:
            SEBAB_AKTIF = await sebab_jeda(db)
            TARGET_BAWAAN = await target_kadar_air(db)
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
             "post": "/miniapp/actions/gabah-masuk",
             "hint": "Pilih tiket timbang yang masih aktif — supplier, bobot, & plat "
                     "otomatis dari timbangan (tak perlu diketik ulang). "
                     "Partai kecil ikut di sini: satu kode timbang, berapa pun "
                     "kali ditimbang.",
             "fields": [
                 {"name": "timbangan_transaksi_id", "label": "Tiket timbang gabah yang masih aktif",
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
             "hint": "Gabungkan SEMUA gabah yang menunggu di mesin itu menjadi 1 "
                     "pengeringan (PGR-…). Gabah di mesin lain tidak ikut. "
                     "Lot belum terbentuk di sini — lot lahir saat mulai giling.",
             "fields": [
                 {"name": "dryer_id", "label": "Mesin yang ada gabahnya", "type": "remote",
                  "source": "/miniapp/actions/dryer-menunggu",
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
             "post": "/miniapp/actions/kadar-air",
             "hint": "Beberapa titik dengan alat tes — yang dipakai rata-ratanya. "
                     "Satu titik saja bisa kebetulan mengenai bagian paling basah. "
                     "Angka mesin dicatat terpisah, bukan dirata-ratakan bersamanya.",
             "fields": [
                 {"name": "kode_lot", "label": "Pengeringan yang sedang berjalan", "type": "remote",
                  "source": "/miniapp/actions/drying-active",
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
             "post": "/miniapp/actions/ubah-target",
             "hint": "Garis selesai pengeringan. Menggesernya mengubah kapan "
                     "mesin dimatikan — dan itu ikut menentukan gabah ini "
                     "dijual sebagai apa. Perubahannya tercatat berikut angka "
                     "lamanya.",
             "fields": [
                 {"name": "kode_lot", "label": "Pengeringan yang sedang berjalan",
                  "type": "remote", "source": "/miniapp/actions/drying-active",
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
             "post": "/miniapp/actions/selesai-pengeringan",
             "hint": "Isikan kadar air yang TERTERA DI MESIN saat dimatikan — "
                     "angka itu tak bisa dicari lagi setelah gabahnya pindah. "
                     "Lalu pengeringan masuk fase pendinginan otomatis (gabah "
                     "tetap di mesin).",
             "fields": [
                 {"name": "kode_lot", "label": "Pengeringan yang sedang berjalan", "type": "remote",
                  "source": "/miniapp/actions/drying-active",
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
            {"id": "selesai_pendinginan", "label": "❄️ Pendinginan selesai",
             "post": "/miniapp/actions/selesai-pendinginan",
             "hint": "Nyatakan gabah sudah dingin & mesin bebas dipakai lagi — gabah "
                     "boleh tetap di dalamnya menunggu silo kosong. Dari sinilah "
                     "lama mesin menganggur dihitung.",
             "fields": [
                 {"name": "kode_lot", "label": "Pengeringan yang sedang didinginkan", "type": "remote",
                  "source": "/miniapp/actions/cooling-active",
                  "kosong": "Tidak ada pengeringan yang sedang didinginkan."},
             ]},
            {"id": "pindah_silo", "label": "🏗️ Pindah dari mesin pengering ke silo",
             "post": "/miniapp/actions/pindah-silo",
             "hint": "Hanya pengeringan yang sudah dinyatakan selesai pendinginan.", "fields": [
                 {"name": "kode_lot", "label": "Pengeringan yang sudah selesai didinginkan", "type": "remote",
                  "source": "/miniapp/actions/drying-done",
                  "kosong": "Tidak ada pengeringan yang sudah selesai didinginkan. Selesaikan pendinginan dulu sebelum memindahkannya ke silo."},
                 {"name": "silo", "label": "Silo tujuan (wajib pilih)",
                  "type": "remote", "source": "/miniapp/actions/silo-g1",
                  "kosong": "Tidak ada silo gabah kering. Tambahkan silo di Pengaturan → Alat."},
             ]},
            {"id": "mulai_giling", "label": "⚙️ Mulai giling",
             "post": "/miniapp/actions/mulai-giling",
             "hint": "Bentuk 1 LOT (LOT-…) dari SELURUH isi silo — boleh berisi "
                     "beberapa pengeringan sekaligus, dan semuanya ikut. "
                     "Di sinilah lot terbentuk.",
             "fields": [
                 {"name": "silo", "label": "Silo berisi gabah kering", "type": "remote",
                  "source": "/miniapp/actions/silo-siap-giling",
                  "kosong": "Tidak ada silo berisi gabah kering yang siap digiling."},
             ]},
            {"id": "hasil_giling", "label": "📈 Perbarui hasil giling",
             "post": "/miniapp/actions/hasil-giling", "fields": [
                 {"name": "kode_proses", "label": "Giling yang sedang berjalan", "type": "remote",
                  "source": "/miniapp/actions/milling-active",
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
             "hint": "Hasil akhir PK wajib. Tanpa angkanya, gilingnya belum "
                     "bisa ditutup dan kartunya tetap berjalan.",
             "post": "/miniapp/actions/selesai-giling", "fields": [
                 {"name": "kode_proses", "label": "Proses giling", "type": "remote",
                  "source": "/miniapp/actions/milling-active",
                  "kosong": "Tidak ada proses giling yang sedang berjalan."},
                 {"name": "berat_akhir", "label": "Hasil akhir PK (kg)",
                  "type": "number"},
             ]},
            # ── Berhenti sementara ──
            # Prosesnya TIDAK ditutup: bahan, target, dan catatannya tetap.
            # Tanpa aksi ini, operator yang mesinnya rusak hanya punya dua
            # pilihan yang sama-sama merusak catatan — membiarkannya
            # "berjalan" padahal mati, atau menutupnya lalu memulai proses
            # baru, yang membuat satu muatan terhitung dua kali.
            {"id": "hentikan_proses", "label": "⏸️ Hentikan sementara",
             "post": "/miniapp/actions/hentikan-proses",
             "hint": "Mesin rusak, listrik padam, jam kerja habis. Prosesnya tidak "
                     "ditutup — bisa dilanjutkan nanti atau besok, dan jam "
                     "tertahannya dihitung terpisah dari jam berjalan.",
             "fields": [
                 {"name": "proses", "label": "Proses yang sedang berjalan", "type": "remote",
                  "source": "/miniapp/actions/proses-berjalan",
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
             "post": "/miniapp/actions/lanjutkan-proses",
             "hint": "Mesin jalan lagi. Lama tertahannya tercatat berikut sebabnya.",
             "fields": [
                 {"name": "proses", "label": "Proses yang sedang berhenti", "type": "remote",
                  "source": "/miniapp/actions/proses-berhenti",
                  "kosong": "Tidak ada proses yang sedang berhenti."},
             ]},
        ]
    if g2:
        actions += [
            {"id": "masukkan_pk", "label": "📥 Masukkan PK diterima",
             "post": "/miniapp/actions/masukkan-pk", "fields": [
                 {"name": "kode_batch", "label": "PK yang menunggu dimasukkan", "type": "remote",
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
                 {"name": "kode_proses", "label": "Penyosohan yang sedang berjalan", "type": "remote",
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
            {"id": "rekonsiliasi_timbang", "label": "🔎 Cocokkan tiket timbang dengan catatan",
             "post": "/miniapp/actions/rekonsiliasi-timbang",
             "hint": "Tiket timbang yang belum tercatat, selisih nota dengan hasil "
                     "timbang, dan catatan yang masih menunggu bobot.", "fields": []},
            {"id": "verify_gabah", "label": "✅ Verifikasi harga gabah",
             "post": "/miniapp/actions/verify-gabah", "fields": [
                 {"name": "kode_batch", "label": "Gabah yang harganya belum diverifikasi", "type": "remote",
                  "source": "/miniapp/actions/gabah-unverified",
                  "kosong": "Tidak ada gabah masuk yang menunggu verifikasi."},
                 {"name": "metode", "label": "Metode", "type": "select", "options": METODE},
                 {"name": "nilai", "label": "Nilai (Rp)", "type": "number"},
             ]},
            {"id": "verify_output", "label": "⚙️ Verifikasi output giling",
             "post": "/miniapp/actions/verify-output",
             "hint": "Catat berat PK final → rendemen terhitung.", "fields": [
                 {"name": "kode_proses", "label": "Giling yang sudah selesai", "type": "remote",
                  "source": "/miniapp/actions/milling-unverified",
                  "kosong": "Belum ada giling yang selesai."},
                 {"name": "berat_output", "label": "Berat PK final (kg)", "type": "number"},
             ]},
            {"id": "qc_giling", "label": "🔬 QC hasil giling",
             "post": "/miniapp/actions/qc-giling",
             "hint": "Isi minimal salah satu: kadar air / broken / susut. Yang "
                     "dikosongkan mempertahankan nilai sebelumnya.", "fields": [
                 {"name": "kode_proses", "label": "Giling yang sudah selesai", "type": "remote",
                  "source": "/miniapp/actions/milling-noqc",
                  "kosong": "Belum ada giling yang selesai."},
                 {"name": "kadar_air", "label": "Kadar air (%)", "type": "number"},
                 {"name": "broken", "label": "Butir patah (%)", "type": "number"},
                 {"name": "susut", "label": "Susut (%)", "type": "number"},
             ]},
            {"id": "catat_pk_luar", "label": "📦 Catat PK luar datang",
             "post": "/miniapp/actions/catat-pk-luar",
             "hint": "Pilih tiket timbang PK yang masih aktif — supplier, bobot & plat "
                     "otomatis dari timbangan. Selanjutnya di-QC & dinilai harga.",
             "fields": [
                 {"name": "timbangan_transaksi_id", "label": "Tiket timbang PK yang masih aktif",
                  "type": "remote", "source": "/miniapp/actions/timbang-pk-aktif",
                  "kosong": "Tidak ada tiket timbang PK yang aktif."},
                 {"name": "jenis_pk", "label": "Jenis PK (wajib pilih)", "type": "select",
                  "options": JENIS_PK},
                 {"name": "kadar_air", "label": "Kadar air (%) — opsional", "type": "number"},
             ]},
            {"id": "qc_pk_luar", "label": "🔬 Catat kualitas PK luar",
             "post": "/miniapp/actions/qc-pk-luar",
             "hint": "PK yang masuk sudah pasti diterima — ini hanya mencatat "
                     "kualitasnya sebagai properti batch. Isi minimal salah satu.",
             "fields": [
                 {"name": "kode_batch", "label": "PK luar yang belum dinilai mutunya", "type": "remote",
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
                 {"name": "kode_batch", "label": "PK luar yang harganya belum ditetapkan",
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
        a["grup"] = _GRUP_AKSI.get(a["id"], GRUP_LAIN)
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
            actions = [a for a in actions if a["id"] not in AKSI_MUTU]
    # Urutan kelompok dititipkan pada aksi pertama: menu inilah satu-satunya
    # yang dikirim ke layar, dan menaruh urutannya di tempat lain berarti dua
    # tempat yang harus sepakat.
    if actions:
        actions[0]["urut_grup"] = URUT_GRUP
    return actions


#: Kelompok katalog. Daftar datar 30 kata kerja menuntut orang membacanya
#: seluruhnya untuk menemukan satu — persis keadaan yang sudah dibuang dari
#: layar antrean. Kelompoknya mengikuti PEKERJAAN, bukan tabel.
GRUP_KARTU = "Biasanya dikerjakan dari kartu"
GRUP_LAIN = "Lain-lain"

_GRUP_AKSI = {
    # Gudang 2 — kini punya kartunya sendiri, tetapi tetap dicantumkan
    # supaya yang bendanya belum ada pun bisa dimulai dari sini.
    "mulai_penyosohan": "Gudang 2 · penyosohan",
    "hasil_penyosohan": "Gudang 2 · penyosohan",
    "selesai_penyosohan": "Gudang 2 · penyosohan",
    "transfer_pk": "Gudang 2 · penyosohan",
    # PK yang datang dari luar, bukan hasil giling sendiri.
    "catat_pk_luar": "PK dari luar",
    "masukkan_pk": "PK dari luar",
    "harga_pk_luar": "PK dari luar",
    "qc_pk_luar": "PK dari luar",
    # Yang keluar dari pabrik, dan yang bukan beras putih.
    "catat_bekatul": "Hasil samping & barang jadi",
    "kirim_bekatul": "Hasil samping & barang jadi",
    "catat_packing": "Hasil samping & barang jadi",
    "kirim_barang_jadi": "Hasil samping & barang jadi",
    "harga_byproduct": "Hasil samping & barang jadi",
    "jual_pk": "Hasil samping & barang jadi",
    # Pembelian & pencocokan.
    "beli_kemasan": "Pembelian & pencocokan",
    "rekonsiliasi_timbang": "Pembelian & pencocokan",
}
for _a in ("gabah_masuk", "pindah_tumpukan", "mulai_pengeringan", "kadar_air",
           "selesai_pengeringan", "selesai_pendinginan", "pindah_silo",
           "ubah_target",
           "mulai_giling", "hasil_giling", "selesai_giling", "hentikan_proses",
           "lanjutkan_proses", "verify_gabah", "verify_output", "qc_giling"):
    _GRUP_AKSI[_a] = GRUP_KARTU

#: Urutan kelompok di layar — yang paling sering dipakai lebih dulu, dan yang
#: sudah punya kartu paling akhir: ia di sini hanya sebagai jalan cadangan.
URUT_GRUP = [
    "Gudang 2 · penyosohan", "PK dari luar", "Hasil samping & barang jadi",
    "Pembelian & pencocokan", GRUP_LAIN, GRUP_KARTU,
]


# Pemetaan aksi → gudang. Aksi keuangan/QC dikelompokkan ke gudang yang relevan:
# harga & QC gabah/giling = G1; PK luar (catat/kualitas/harga) = G2; transfer PK
# berasal dari proses G1 → G1.
_ACTION_WH = {
    # Gudang 1 (Selepan)
    "gabah_masuk": "g1", "pindah_tumpukan": "g1", "mulai_pengeringan": "g1", "kadar_air": "g1",
    "ubah_target": "g1",
    "selesai_pengeringan": "g1", "selesai_pendinginan": "g1", "pindah_silo": "g1",
    "mulai_giling": "g1", "hasil_giling": "g1", "selesai_giling": "g1",
    "hentikan_proses": "g1", "lanjutkan_proses": "g1",
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
        _loose_dryer_batches, dryers_g1, mode_disarankan)
    out = []
    async with SessionLocal() as db:
        for d in await dryers_g1(db):
            batches = await _loose_dryer_batches(db, d.id)
            if not batches:
                continue
            kg = sum(float(b.berat_total_kg or 0) for b in batches)
            # Mode yang seharusnya disebut DI SINI — di baris tempat tonasenya
            # diketahui. Operator tak perlu menghitung 23 ton itu lebih dekat
            # ke 25T atau 20T sambil berdiri di depan mesin.
            out.append({"value": d.id,
                        "label": (f"{d.nama} · {len(batches)} batch · {_rp(kg)} kg"
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
            select(JedaProses).where(JedaProses.selesai.is_(None))
            .order_by(JedaProses.mulai)
        )).scalars().all():
            if j.jenis == "pengeringan":
                o = await db.get(DryingLot, j.drying_lot_id)
                kode = o.kode_lot if o else "?"
            else:
                o = await db.get(MillingProcess, j.milling_process_id)
                kode = o.kode_proses if o else "?"
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
    """Milling SELESAI — yang belum dinilai mutunya lebih dulu, sisanya menyusul.

    Dulu hanya yang belum punya catatan QC sama sekali. Itu menutup KOREKSI:
    mutu yang salah ketik tak bisa dibetulkan lewat daftar ini, dan — sama
    persis dengan `milling_unverified` — penguncian penunjuk dari kartu Stok
    ikut terlepas begitu satu lot punya QC, karena `aksi.js` melepas kunci bila
    nilainya tak ada di daftarnya.
    """
    _require(can_see_financials(user))
    await _wajib_mutu()
    from sqlalchemy import case, exists, select
    from app.models import MillingProcess, MillingQcLog
    async with SessionLocal() as db:
        ada_qc = exists().where(MillingQcLog.milling_process_id == MillingProcess.id)
        baris = (
            await db.execute(
                select(MillingProcess.kode_proses, ada_qc.label("ada"))
                .where(MillingProcess.status == "selesai")
                .order_by(case((ada_qc, 1), else_=0),
                          MillingProcess.kode_proses.desc())
            )
        ).all()
    return [{"value": k, "label": k} for k, _ in baris]


@router.get("/actions/pk-luar-qc")
async def pk_luar_qc(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """PK luar (sudah masuk) yang BELUM diinput kualitasnya."""
    _require(can_see_financials(user))
    await _wajib_mutu()
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
        # PRA-PERIKSA sebelum batch dibuat.
        #
        # Penempatan berjalan SETELAH batch tercatat, dan penolakannya di sana
        # hanya jadi peringatan: gabahnya sudah turun dari truk, jadi
        # catatannya memang harus tetap ada. Tetapi menolak lebih awal untuk
        # hal yang sudah pasti salah menghemat satu pembersihan manual — dan
        # gabah kering yang dikirim ke mesin berisi gabah basah adalah hal
        # yang sudah pasti salah, bukan kebetulan yang bisa jadi benar.
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

    pesan = f"✓ Gabah *{kode}* ({kondisi}) tercatat" + (f".\n{tempat}." if tempat else ".") + warn
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


class HentikanReq(BaseModel):
    #: "pengeringan:PGR-…" atau "giling:LOT-…" — jenis dan kodenya sekaligus,
    #: supaya operator tak perlu memilih jenis proses lebih dulu.
    proses: str
    sebab: str
    sebab_lain: str | None = None


class LanjutkanReq(BaseModel):
    proses: str


def _urai_proses(nilai: str) -> tuple[str, str]:
    jenis, _, kode = (nilai or "").partition(":")
    return jenis.strip(), kode.strip()


@router.post("/actions/hentikan-proses")
async def act_hentikan_proses(req: HentikanReq,
                              user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g1_operator(user))
    from app.penggilingan.gudang1.services.jeda import JedaError, hentikan
    jenis, kode = _urai_proses(req.proses)
    if not kode:
        raise HTTPException(400, "Pilih proses yang mau dihentikan dulu.")
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await hentikan(db, user=u, jenis=jenis, kode=kode,
                               sebab=req.sebab, sebab_lain=req.sebab_lain)
        except JedaError as e:
            raise _err(e, "Gagal menghentikan proses.")
    pesan = (f"⏸ *{r.kode}* dihentikan sementara — {r.sebab}.\n"
             f"Prosesnya tidak ditutup; bahan & catatannya tetap. "
             f"Berhenti ke-{r.kali} untuk proses ini.")
    return {"ok": True, "pesan": pesan}


@router.post("/actions/lanjutkan-proses")
async def act_lanjutkan_proses(req: LanjutkanReq,
                               user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g1_operator(user))
    from app.penggilingan.gudang1.services.jeda import JedaError, lanjutkan
    jenis, kode = _urai_proses(req.proses)
    if not kode:
        raise HTTPException(400, "Pilih proses yang mau dilanjutkan dulu.")
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await lanjutkan(db, user=u, jenis=jenis, kode=kode)
        except JedaError as e:
            raise _err(e, "Gagal melanjutkan proses.")
    jam = (r.tertahan_detik or 0) / 3600
    pesan = (f"▶️ *{r.kode}* dilanjutkan — tertahan {jam:.1f} jam "
             f"({r.sebab}).")
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
    return {"ok": True, "pesan": pesan}


class KodeProsesReq(BaseModel):
    kode_proses: str


class SelesaiGilingReq(BaseModel):
    kode_proses: str
    #: Hasil akhir PK (kg). Boleh kosong HANYA bila operator sudah pernah
    #: mencatat hasilnya lewat "Perbarui hasil giling"; layanan yang memutuskan,
    #: bukan di sini — satu aturan, satu tempat.
    berat_akhir: PositifOpsional = None


@router.post("/actions/selesai-giling")
async def act_selesai_giling(req: SelesaiGilingReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(await _is_g1_operator(user))
    if not (req.kode_proses or "").strip():
        raise HTTPException(400, "Pilih proses giling dulu.")
    from app.penggilingan.gudang1.services.milling import finish_milling, MillingError
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await finish_milling(db, user=u, kode_proses=req.kode_proses,
                                     berat_akhir=req.berat_akhir)
        except MillingError as e:
            raise _err(e, "Gagal menyelesaikan giling.")
    jns = (r.jenis + " ") if r.jenis else ""
    pesan = (f"✓ Giling *{req.kode_proses}* selesai — PK {jns}{r.produced:g} kg "
             f"(siap kirim {r.siap_kirim:g} kg).")
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


class QcGilingReq(BaseModel):
    kode_proses: str
    kadar_air: PersenOpsional = None
    broken: PersenOpsional = None
    susut: PersenOpsional = None


@router.post("/actions/qc-giling")
async def act_qc_giling(req: QcGilingReq, user: User = Depends(pengguna_aksi)) -> dict:
    _require(can_see_financials(user))
    await _wajib_mutu()
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
    return {"ok": True, "pesan": pesan}


class CatatPkLuarReq(BaseModel):
    # Pilih TIKET TIMBANG PK aktif — supplier/bobot/nopol dari timbang.
    timbangan_transaksi_id: int
    jenis_pk: str
    kadar_air: PersenOpsional = None


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
    return {"ok": True, "pesan": pesan}


class QcPkLuarReq(BaseModel):
    kode_batch: str
    kadar_air: PersenOpsional = None
    broken: PersenOpsional = None
    penyusutan: PersenOpsional = None
    butir_kuning: str | None = None
    catatan_lab: str | None = None


@router.post("/actions/qc-pk-luar")
async def act_qc_pk_luar(req: QcPkLuarReq, user: User = Depends(pengguna_aksi)) -> dict:
    """Input kualitas PK luar (properti batch) — bukan keputusan terima/tolak."""
    _require(can_see_financials(user))
    await _wajib_mutu()
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
    return {"ok": True, "pesan": pesan}


class HargaPkLuarReq(BaseModel):
    kode_batch: str
    metode: str
    nilai: PositifOpsional = None
    potongan_kg: PositifOpsional = None
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
    return {"ok": True, "pesan": pesan}


class TransferReq(BaseModel):
    kode_proses: str
    tujuan: str
    berat: PositifOpsional = None


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
    return {"ok": True, "pesan": pesan}


class HasilPenyosohanReq(BaseModel):
    kode_proses: str
    jenis: str
    berat_kumulatif: Positif


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
    return {"ok": True, "pesan": pesan}


class SelesaiPenyosohanReq(BaseModel):
    kode_proses: str
    silo: str  # A / B
    sisa: Annotated[float, Field(ge=0, allow_inf_nan=False)]


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
    return {"ok": True, "pesan": pesan}


# ─────────────────────────── Halaman Mini App ───────────────────────────

