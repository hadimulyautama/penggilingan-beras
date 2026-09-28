"""Logika bisnis proses milling / pecah kulit (Gudang 1)."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.angka import AngkaError, angka_wajar
from app.database import input_time, now_local
from app.models import (
    DryingLot,
    DryingLotBatch,
    InternalTransfer,
    MillingProcess,
    MillingProcessSource,
    MillingProcessVerification,
    MillingProgressLog,
    MillingQcLog,
    PurchaseBatch,
    PurchaseBatchVerification,
    Silo,
    SiloStorage,
    Supplier,
)
from app.services.activity_log import log_activity
from app.services.codegen import next_drying_lot_code, next_milling_code
from app.penggilingan.gudang1.services.bobot import (
    NOL, PASTI, TAK_DIKETAHUI, Bobot, dari_batch, dari_batches)
from app.penggilingan.gudang1.services.bobot import jumlah as jumlah_bobot
from app.penggilingan.gudang1.services.silo import (
    _silo_active_rows, get_g1_silo, giling_berjalan_untuk_silo, silo_ids_proses)


class MillingError(Exception):
    """Kesalahan proses milling dengan pesan siap-tampil (args[0])."""


async def get_process_by_kode(db: AsyncSession, kode: str) -> MillingProcess | None:
    return (
        await db.execute(select(MillingProcess).where(MillingProcess.kode_proses == kode))
    ).scalars().first()


async def sole_active_milling_kode(db: AsyncSession) -> str | None:
    """Kode proses bila TEPAT ADA SATU milling yang sedang 'proses'; else None.

    Memungkinkan 'giling selesai' / 'progress 5 ton' tanpa menyebut kode.
    """
    rows = (
        await db.execute(
            select(MillingProcess.kode_proses).where(MillingProcess.status == "proses")
        )
    ).scalars().all()
    return rows[0] if len(rows) == 1 else None


async def _storage_bobot(db: AsyncSession, st: SiloStorage) -> Bobot:
    """Bobot isi satu baris silo SEKARANG — lot pengeringan atau batch lepas —
    berikut kepastiannya (pasti / perkiraan / tak diketahui). Lihat `bobot.py`."""
    if st.drying_lot_id:
        batches = (await db.execute(
            select(PurchaseBatch)
            .join(DryingLotBatch, DryingLotBatch.purchase_batch_id == PurchaseBatch.id)
            .where(DryingLotBatch.drying_lot_id == st.drying_lot_id)
        )).scalars().all()
        return dari_batches(batches)
    if st.purchase_batch_id:
        return dari_batch(await db.get(PurchaseBatch, st.purchase_batch_id))
    return NOL


async def _storage_kg(db: AsyncSession, st: SiloStorage) -> float:
    """Angka yang DIKETAHUI saja — untuk penjumlah lama. Yang butuh kepastian
    memakai `_storage_bobot`; "belum diketahui" di sini terbaca 0, dan itulah
    sebabnya ia tak boleh dipakai sebagai pagar (QA P6)."""
    return (await _storage_bobot(db, st)).angka()


async def _active_storage(db: AsyncSession, silo_id: int) -> SiloStorage | None:
    return (
        await db.execute(
            select(SiloStorage).where(
                SiloStorage.silo_id == silo_id, SiloStorage.status == "terisi"
            )
        )
    ).scalars().first()


# ─────────────────────────── Mulai ───────────────────────────
@dataclass
class StartResult:
    proc: MillingProcess
    #: Silo yang ikut, sudah dirangkai untuk dibaca: "A" atau "A + B".
    nama_silo: str
    berat_masuk: float
    #: Berapa dan seberapa pasti — untuk kalimat di layar.
    bobot: Bobot | None = None


def _rangkai(nama: list[str]) -> str:
    """"A" · "A + B" · "A + B + C" — untuk kalimat, bukan untuk disimpan."""
    return " + ".join(nama)


async def start_milling(
    db: AsyncSession, *, user, nama_silo: str | list[str] | tuple | None,
    tanggal=None, jam=None
) -> StartResult:
    """Mulai satu giling dari SATU ATAU BEBERAPA silo — hasilnya SATU lot.

    Keputusan pemilik 24 September 2026: menggiling dari beberapa silo
    sekaligus "sering", dan "hasilnya 1 lot". Satu lot berarti satu rendemen
    dan satu HPP atas SELURUH bahan yang masuk — bukan dua lot yang harus
    dijumlah orang di kepalanya.

    Bentuknya sudah ada: tiap sumber punya barisnya sendiri di
    `milling_process_sources`, dan `berat_gabah_masuk_kg` memang dijumlah atas
    seluruh baris. Yang berubah di sini hanya: barisnya boleh datang dari
    beberapa silo, dan SELURUH silo itu diperiksa sebelum satu pun ditulis.
    """
    pilihan = ([nama_silo] if isinstance(nama_silo, str)
               else list(nama_silo or []))
    # Dirapikan, bukan ditolak: orang yang mencentang silo yang sama dua kali
    # bermaksud satu kali. Urutannya dipertahankan supaya kalimat balasannya
    # menyebutnya dalam urutan yang ia pilih.
    nama_pilih: list[str] = []
    for n in pilihan:
        n = str(n or "").strip()
        if n and n not in nama_pilih:
            nama_pilih.append(n)
    if not nama_pilih:
        raise MillingError("Sebutkan silo mana, contoh: `giling silo A`")

    # ── SEMUA silo diperiksa DULU, baru satu pun ditulis ──
    #
    # Lot separuh lebih buruk daripada lot yang gagal dimulai: ia berdiri di
    # layar sebagai giling yang berjalan, rendemennya dihitung atas bahan yang
    # tak lengkap, dan tak ada satu pun kalimat yang menyebutkan silo mana yang
    # tertinggal.
    silo_pilih: list = []
    rows: list[SiloStorage] = []
    for nama in nama_pilih:
        silo = await get_g1_silo(db, nama)
        if silo is None:
            raise MillingError(f"Silo {nama} Gudang 1 tidak ditemukan.")
        baris = await _silo_active_rows(db, silo.id)
        if not baris:
            raise MillingError(f"Silo {nama} kosong — tidak ada yang bisa digiling.")
        # Pertanyaannya "silo ini ada di antara sumber proses yang berjalan?",
        # bukan "silo ini yang tercatat di kolom silo_id?". Lihat catatan pada
        # `giling_berjalan_untuk_silo`.
        jalan = await giling_berjalan_untuk_silo(db, silo.id)
        if jalan is not None:
            raise MillingError(f"Silo {nama} sedang digiling ({jalan.kode_proses}).")
        silo_pilih.append(silo)
        rows += baris

    silo = silo_pilih[0]
    nama_silo = _rangkai(nama_pilih)
    # Dipegang sebagai ANGKA, bukan sebagai objek: sesudah `rollback()` di
    # bawah, objek Silo lepas dari sesi dan membaca `.id`-nya memicu pemuatan
    # ulang — yang di sesi async berbunyi "MissingGreenlet", galat yang
    # terbacanya seperti kerusakan pustaka, bukan seperti kode yang salah
    # urutan. Jebakan yang sama pernah muncul di `permintaan_pk.minta`.
    id_silo = [(s.id, n) for s, n in zip(silo_pilih, nama_pilih)]
    now = input_time(tanggal, jam)

    # SELURUH isi silo masuk ke satu proses giling — bukan satu baris saja.
    #
    # Dulu di sini dipilih SATU baris: kalau ada lot hasil pengeringan, itu
    # yang diambil; kalau tidak, batch-batch lepas dikonsolidasi jadi lot baru.
    # Selama satu silo hanya boleh berisi satu hal, keduanya cukup. Begitu silo
    # boleh dicampur, cabang pertama diam-diam mengabaikan batch lepas yang ada
    # di silo yang sama: gabahnya ikut tergiling, tetapi tidak ikut tercatat.
    #
    # `drying_lots` sekarang berarti satu PROSES PENGERINGAN, dan apa yang
    # digiling bersama didaftar di `milling_process_sources`.
    #
    # Tiap baris dibaca berikut KEPASTIANNYA (QA P6-01). Bahan yang belum
    # punya angka — truk belum ditimbang kedua, tanpa tara — dicatat NULL,
    # bukan 0: nol ditolak CHECK berat_positif, dan memang nol itu bohong.
    # Yang perkiraan ikut sebagai angka. Keduanya menandai prosesnya "bobot
    # masuk belum final"; poller membetulkannya begitu timbangnya ada, walau
    # giling ini sudah selesai (P6-03).
    bobot_per_baris: list[tuple[SiloStorage, Bobot]] = []
    for r in rows:
        bobot_per_baris.append((r, await _storage_bobot(db, r)))
    total = jumlah_bobot(b for _, b in bobot_per_baris)
    berat = total.kg

    # ── Penunjuk tunggal: PENINGGALAN, bukan wewenang ──
    #
    # `silo_id`, `silo_storage_id`, `drying_lot_id`, `purchase_batch_id` tetap
    # diisi supaya laporan dan data lama yang membacanya tidak mati sekaligus.
    # Yang dipilih: silo PERTAMA yang dicentang, dan baris lot bila ada.
    #
    # TETAPI tak boleh lagi ada keputusan PERILAKU yang bergantung padanya.
    # Sejak satu lot boleh datang dari beberapa silo, kolom-kolom ini hanya
    # menyebut salah satu — dan tiga tempat yang dulu memercayainya masing-
    # masing melahirkan kerusakan yang sama: silo kedua ditawarkan lagi,
    # dikosongkan tidak, dikembalikan tidak. Yang benar selalu
    # `milling_process_sources`. Kolom yang terlihat berwibawa padahal tinggal
    # peninggalan adalah kolom yang akan dipakai lagi oleh orang berikutnya.
    st = next((r for r in rows if r.drying_lot_id), rows[0])
    proc = MillingProcess(
        kode_proses=await next_milling_code(db),
        silo_id=silo.id,
        silo_storage_id=st.id,
        drying_lot_id=st.drying_lot_id,
        purchase_batch_id=st.purchase_batch_id,
        berat_gabah_masuk_kg=berat,
        bobot_masuk_final=total.pasti,
        waktu_mulai=now,
        status="proses",
        created_by=user.id,
    )
    db.add(proc)
    try:
        await db.flush()
        # ── KLAIM barisnya, dan biarkan BASIS DATA yang memutuskan ──
        #
        # Pemeriksaan "sedang digiling?" di atas dilewati dua operator yang
        # menekan pada detik yang sama: keduanya membaca "belum", keduanya
        # menulis. Yang memutuskan di sini satu `UPDATE` bersyarat — Postgres
        # mengunci barisnya lalu MENGUJI ULANG syaratnya sesudah kunci didapat,
        # jadi yang kedua menerima nol baris dan ditolak. Lihat catatan panjang
        # pada `SiloStorage.milling_process_id`.
        ids_baris = [r.id for r in rows]
        dikunci = (await db.execute(
            update(SiloStorage)
            .where(SiloStorage.id.in_(ids_baris),
                   SiloStorage.milling_process_id.is_(None))
            .values(milling_process_id=proc.id)
        )).rowcount or 0
        if dikunci != len(ids_baris):
            await db.rollback()
            # Namanya dicari SESUDAH rollback: yang menang sudah ter-commit,
            # jadi sekarang bisa disebut kode prosesnya — kalimat "silo sedang
            # digiling" tanpa menyebut oleh apa menyuruh orang mencari sendiri.
            sibuk = []
            for sid, nm in id_silo:
                j = await giling_berjalan_untuk_silo(db, sid)
                if j is not None:
                    sibuk.append(f"Silo {nm} ({j.kode_proses})")
            raise MillingError(
                "Giling tidak dimulai — " + (
                    " dan ".join(sibuk) + " sedang digiling." if sibuk
                    else "silonya baru saja dipakai proses lain.")
                + " Tidak ada yang tercatat; pilih silo lain atau tunggu.")
        for r, bb in bobot_per_baris:
            db.add(MillingProcessSource(
                milling_process_id=proc.id, silo_storage_id=r.id,
                drying_lot_id=r.drying_lot_id, purchase_batch_id=r.purchase_batch_id,
                berat_kg=bb.kg,
            ))
        await db.flush()
        await log_activity(
            db, table_name="milling_process", record_id=proc.id, action="INSERT",
            changed_by=user.id,
            new_value=f"{proc.kode_proses} <- Silo {nama_silo} ({total.teks()})",
        )
        await db.commit()
    except IntegrityError as e:
        # Seperti R-T-01 di timbangan: aturan basis data yang ditolak tak
        # boleh sampai ke layar sebagai teks Postgres. Yang lengkap ke log.
        await db.rollback()
        raise MillingError(
            f"Giling Silo {nama_silo} tidak bisa dimulai karena aturan basis data "
            f"menolak bahannya ({total.teks()}). Coba sekali lagi; bila berulang, "
            "sebutkan pesan ini ke Super Admin."
        ) from e
    await db.refresh(proc)
    return StartResult(proc=proc, nama_silo=nama_silo, berat_masuk=total.angka(), bobot=total)


# ─────────────────────────── Progress ───────────────────────────
@dataclass
class ProgressResult:
    proc: MillingProcess
    berat_kumulatif: float
    rendemen_persen: float | None
    jenis: str | None = None  # KS (dibeli basah) / KL (dibeli kering) / MIX (dua-duanya)
    peringatan: str | None = None


def hitung_rendemen(hasil: float | None, masuk: float | None) -> float | None:
    """Berapa persen gabah yang keluar jadi PK. None bila bahannya tak diketahui.

    Rumusnya sepele; yang tidak sepele adalah PENYEBUTNYA selalu sama.
    `berat_gabah_masuk_kg` adalah cuplikan berat bahan saat giling dimulai, dan
    ia disinkronkan ulang ketika timbangan membetulkan tiketnya. Kalau ada
    layar yang memakai penyebut lain — berat batch, isi silo — dua layar akan
    menyebut rendemen berbeda untuk lot yang sama, dan yang melihatnya akan
    mencari sebabnya di mesin, bukan di catatan.
    """
    masuk = float(masuk or 0)
    if not masuk or hasil is None:
        return None
    return float(hasil) / masuk * 100


async def stok_pk_g1(db: AsyncSession) -> float:
    """PK yang MENUMPUK di Gudang 1 — belum dikirim, belum dijual.

    Tidak disimpan sebagai keadaan tersendiri, dan itu disengaja. "Ditumpuk"
    dan "langsung dibawa ke penyosohan" bukan dua jalan yang perlu dinyatakan
    operator: yang membedakan keduanya hanya ADA TIDAKNYA transfer, dan itu
    sudah tercatat. Menyuruh orang menyatakannya lagi berarti dua sumber untuk
    satu fakta — dan yang salah selalu yang diketik manual, karena orang lupa
    memperbaruinya setelah barangnya benar-benar pindah.
    """
    total = 0.0
    for proc in (await db.execute(select(MillingProcess))).scalars().all():
        bd = await _pk_breakdown(db, proc.id)
        if bd.tersedia > 0:
            total += bd.tersedia
    return total


async def log_progress(
    db: AsyncSession, *, user, kode_proses: str | None, berat_kumulatif: float | None,
    tanggal=None, jam=None,
) -> ProgressResult:
    if not kode_proses:
        raise MillingError("Sebutkan kode proses, contoh: `progress giling LOT-20260702-01 5 ton`")
    proc = await get_process_by_kode(db, kode_proses)
    if proc is None:
        raise MillingError(f"Proses {kode_proses} tidak ditemukan.")
    if proc.status == "selesai":
        raise MillingError(f"Proses {kode_proses} sudah selesai.")
    if berat_kumulatif is None:
        raise MillingError("Sebutkan berat PK kumulatifnya, mis. `LOT-... sudah 5 ton`.")
    # Dijaga DI SINI juga, bukan cuma di model permintaan: lapisan AI dan
    # sebagian rute memanggil layanan ini langsung, dan NaN yang lolos di satu
    # tempat akan menular ke seluruh kolom yang menjumlahkannya.
    try:
        berat_kumulatif = angka_wajar(berat_kumulatif, "Berat PK kumulatif")
    except AngkaError as e:
        raise MillingError(str(e)) from None

    db.add(
        MillingProgressLog(
            milling_process_id=proc.id,
            waktu_update=input_time(tanggal, jam),
            berat_kumulatif_kg=berat_kumulatif,
            input_by=user.id,
        )
    )
    await log_activity(
        db, table_name="milling_progress_logs", record_id=proc.id, action="INSERT",
        changed_by=user.id, new_value=f"kumulatif {berat_kumulatif:.0f}kg",
    )
    await db.commit()
    rendemen = hitung_rendemen(berat_kumulatif, proc.berat_gabah_masuk_kg)
    jenis = await pk_jenis(db, proc)

    # Lantainya penuh — DIBERITAHU, bukan ditolak.
    #
    # PK ini sudah keluar dari mesin sebelum siapa pun mengetiknya. Menolak
    # mencatatnya tidak membuatnya lenyap; ia hanya membuat catatan berbohong,
    # dan justru menyembunyikan keadaan yang paling perlu dilihat. Beda dengan
    # tumpukan Gudang 2 yang MENOLAK: di sana yang dijaga adalah keputusan
    # penempatan, dan keputusan masih bisa dialihkan ke silo.
    peringatan = None

    # ── Beras tak pernah lebih berat daripada gabahnya ──
    #
    # Rendemen giling SELALU di bawah 100%: sekamnya terbuang. Angka di atas
    # itu berarti salah ketik — satu digit, oleh orang yang sedang berdiri di
    # depan mesin. "18000" untuk maksud "8000" diterima apa adanya sampai 25
    # September 2026, dan kartu Stok lalu menggambar rendemen 164% tanpa satu
    # pun tanda; HPP lot itu ikut bohong sampai ada yang kebetulan
    # memperhatikan. Temuan QA.
    #
    # DIBERITAHU, BUKAN DITOLAK — alasannya sama dengan lantai penuh di bawah:
    # PK-nya sudah keluar dari mesin sebelum siapa pun mengetiknya, dan angka
    # kumulatif memang boleh MUNDUR. Justru begitulah salah ketik ini
    # dibetulkan: mengetik angka yang benar. Menolaknya berarti menutup
    # satu-satunya jalan perbaikan yang dipunyai operator.
    #
    # Yang menutup pintu adalah `finish_milling`, dan di sana memang benar
    # menolak: menutup proses adalah tindakan terakhir, bukan catatan berjalan.
    #
    # Batas 100% batas FISIKA, bukan selera — jadi ia tak bersetelan. Dan ia
    # SENDIRIAN: peringatan yang menumpuk berhenti dibaca, dan yang ini jauh
    # lebih jarang serta lebih mendesak daripada kabar tumpukan.
    bahan = float(proc.berat_gabah_masuk_kg or 0)
    if rendemen is not None and rendemen > 100:
        sementara = ("" if proc.bobot_masuk_final
                     else " — dan bobot masuknya sendiri masih sementara")
        return ProgressResult(
            proc=proc, berat_kumulatif=berat_kumulatif, rendemen_persen=rendemen,
            jenis=jenis,
            peringatan=(
                f"⚠️ Rendemen {rendemen:.0f}% — beras tak bisa lebih berat "
                f"daripada gabahnya ({_kg(bahan)}){sementara}. Periksa "
                "angkanya; kalau memang benar, beri tahu Admin."),
        )

    stok = await stok_pk_g1(db)
    cap = settings.g1_pk_tumpukan_maks_kg
    if stok > cap:
        peringatan = (
            f"⚠️ Tumpukan PK Gudang 1 {stok / 1000:g} ton — melewati batas lantai "
            f"{cap / 1000:g} ton. Kirim ke gudang penyosohan."
        )
    elif stok > cap * 0.9:
        peringatan = (
            f"⚠️ Tumpukan PK Gudang 1 {stok / 1000:g} ton dari {cap / 1000:g} ton "
            f"— sisa {(cap - stok) / 1000:g} ton."
        )
    return ProgressResult(
        proc=proc, berat_kumulatif=berat_kumulatif, rendemen_persen=rendemen,
        jenis=jenis, peringatan=peringatan,
    )


# ─────────────────────────── Selesai (auto-kosongkan silo) ───────────────────────────
@dataclass
class FinishResult:
    proc: MillingProcess
    nama_silo: str | None
    produced: float
    siap_kirim: float
    jenis: str | None = None  # KS / KL / MIX


async def _tutup_jeda_terbuka(db: AsyncSession, proc, saat) -> None:
    """Tutup jeda proses yang masih menganga saat prosesnya selesai.

    Ditutup, bukan ditolak. Menolak menutup proses yang sedang dijeda memaksa
    operator melanjutkan dulu baru menyelesaikan — dua ketukan untuk keadaan
    yang sudah jelas: mesinnya berhenti, dan selesai berarti selesai.
    """
    from app.models import JedaProses

    terbuka = (await db.execute(
        select(JedaProses).where(
            JedaProses.milling_process_id == proc.id,
            JedaProses.selesai.is_(None),
        )
    )).scalars().all()
    for j in terbuka:
        j.selesai = saat


async def finish_milling(
    db: AsyncSession, *, user, kode_proses: str | None, berat_akhir: float | None = None,
    tanggal=None, jam=None,
) -> FinishResult:
    """Tutup giling. Hasil akhir PK WAJIB — tanpa itu prosesnya tidak ditutup.

    Keputusan pemilik. Sebelumnya aksi ini hanya menutup prosesnya, jadi giling
    bisa berakhir tanpa satu pun angka hasil: PK-nya ada di lantai, tetapi tak
    ada yang tahu berapa. Lot itu lalu jatuh dari layar Stok, dan kelalaiannya
    tak punya satu tempat pun untuk kelihatan.

    Yang ditolak adalah PENUTUPANNYA, bukan pencatatannya. Prosesnya tak
    disentuh sama sekali sebelum angkanya ada, jadi kartunya tetap berada di
    Sedang berjalan — keadaan yang benar: mesinnya memang belum tuntas
    dilaporkan. Kartu yang hilang tanpa penjelasan lebih buruk daripada kartu
    yang bertahan sampai dilengkapi.

    Angkanya masuk sebagai progres KUMULATIF terakhir — catatan operator.
    Verifikasi admin (`berat_output_final_kg`) tetap langkah tersendiri, dan
    tetap menang atas angka ini bila kelak berbeda.
    """
    if not kode_proses:
        raise MillingError("Sebutkan kode proses, contoh: `LOT-20260702-01 selesai`")
    proc = await get_process_by_kode(db, kode_proses)
    if proc is None:
        raise MillingError(f"Proses {kode_proses} tidak ditemukan.")
    if proc.status == "selesai":
        raise MillingError(f"Proses {kode_proses} sudah selesai.")

    # Diperiksa SEBELUM apa pun diubah. Kalau ditolak, prosesnya harus tetap
    # utuh berstatus "proses" — itulah yang membuat kartunya kembali sendiri.
    sudah = await _latest_progress(db, proc.id)
    if berat_akhir is None:
        if sudah is None:
            raise MillingError(
                "Sebutkan hasil akhir PK-nya dulu (kg). Giling tidak bisa "
                "ditutup tanpa angka hasil — PK-nya ada, dan yang tak tercatat "
                "tak akan muncul di Stok."
            )
        berat_akhir = sudah          # sudah pernah dicatat: pakai yang terakhir
    berat_akhir = float(berat_akhir)
    if berat_akhir <= 0:
        raise MillingError("Hasil akhir PK harus lebih dari nol.")
    masuk = float(proc.berat_gabah_masuk_kg or 0)
    # Pagar fisiknya benar — PK tak mungkin melebihi gabah — tetapi hanya
    # bila PEMBANDINGNYA pasti. Bahan yang masih perkiraan atau belum
    # diketahui membuat pagar ini menolak hasil yang benar (QA P6-03a): yang
    # begitu dibiarkan lewat, tetap bertanda belum final, dan pembandingnya
    # dibetulkan poller begitu truknya ditimbang.
    if proc.bobot_masuk_final and masuk and berat_akhir > masuk:
        raise MillingError(
            f"Hasil PK {berat_akhir:,.0f} kg lebih besar daripada gabah yang "
            f"masuk ({masuk:,.0f} kg). Periksa angkanya."
            .replace(",", ".")
        )

    now = input_time(tanggal, jam)
    if now < proc.waktu_mulai:
        raise MillingError(
            f"Tanggal selesai lebih awal dari mulai giling "
            f"({proc.waktu_mulai:%d-%m-%Y %H:%M})."
        )

    # Dicatat sebagai progres kumulatif, bukan kolom baru: `_produced_pk` sudah
    # membacanya, dan kolom kedua untuk fakta yang sama akan berselisih.
    if sudah is None or berat_akhir != sudah:
        db.add(MillingProgressLog(
            milling_process_id=proc.id, waktu_update=now,
            berat_kumulatif_kg=berat_akhir, input_by=user.id,
        ))
        await log_activity(
            db, table_name="milling_progress_logs", record_id=proc.id, action="INSERT",
            changed_by=user.id, new_value=f"hasil akhir {berat_akhir:.0f}kg",
        )
        await db.flush()

    proc.status = "selesai"
    proc.waktu_selesai = now

    # Silo dianggap kosong saat milling selesai (bukan saat gabah keluar fisik).
    #
    # Dikosongkan dari SELURUH sumbernya, bukan dari `proc.silo_storage_id`.
    # Penunjuk tunggal itu diisi `start_milling` dengan SALAH SATU baris silo
    # saja — "baris lot bila ada" — padahal satu giling boleh memakan beberapa
    # baris sekaligus sejak silo boleh dicampur. Baris yang tak ikut
    # dikosongkan tetap berstatus "terisi", dan silo yang isinya sudah habis
    # tergiling muncul kembali sebagai "Transit di silo kering": gabah yang
    # sama ditawarkan untuk digiling dua kali.
    nama_silo = None
    ids = [s for s in (await db.execute(
        select(MillingProcessSource.silo_storage_id).where(
            MillingProcessSource.milling_process_id == proc.id)
    )).scalars().all() if s]
    if not ids and proc.silo_storage_id:
        ids = [proc.silo_storage_id]      # proses lama, sebelum ada tabel sumber
    for sid in ids:
        st = await db.get(SiloStorage, sid)
        if st:
            if st.status == "terisi":
                st.status = "kosong"
                st.tanggal_keluar = now
            # Klaimnya dilepas bersama isinya. Baris kosong takkan pernah jadi
            # sumber lagi, jadi klaim yang tertinggal tak menghalangi apa-apa —
            # tapi klaim yang tertinggal juga tak bisa dibaca sebagai apa pun,
            # dan kolom yang artinya tergantung kolom lain adalah kolom yang
            # dibaca salah suatu hari.
            st.milling_process_id = None
    # ── SELURUH silo sumber dikosongkan, bukan `proc.silo_id` saja ──
    #
    # Sejak satu lot boleh datang dari beberapa silo (keputusan pemilik 24
    # September 2026), `proc.silo_id` menyebut silo PERTAMA. Menandai hanya ia
    # meninggalkan silo kedua berstatus "terisi" padahal isinya sudah jadi PK:
    # layar Gudang menunjukkan gabah yang tidak ada, dan orang mencari-carinya.
    # Baris `SiloStorage`-nya sendiri sudah dikosongkan seluruhnya di atas —
    # yang tertinggal `Silo.status`.
    #
    # ⚠ Kalimat ini dulu menyebut `Silo.status` "kolom yang paling sering
    # dibaca", dan itu TIDAK BENAR (temuan QA 28 September 2026): tak satu pun
    # layar membacanya. Yang menggambar isi silo membaca stoknya —
    # `hitung_stok_silo` di Gudang 2, dan `dashboard._silo_status` menurunkan
    # "terisi" dari baris `SiloStorage`, bukan dari kolom ini. Komentar yang
    # memberi wibawa kepada kolom yang tak dibaca siapa pun akan membuat orang
    # berikutnya memercayainya — dan kolom yang dipercaya tanpa dibaca adalah
    # kolom yang dipakai mengambil keputusan tanpa pernah diverifikasi.
    #
    # Ia tetap ditulis, dan sekarang juga ditulis Gudang 2 (`segarkan_status_
    # silo`), supaya isinya tak bertentangan dengan kenyataan. Bukan karena ada
    # yang membutuhkannya hari ini.
    if ids:
        nama: list[str] = []
        for silo_id in await silo_ids_proses(db, proc):
            silo = await db.get(Silo, silo_id)
            if silo:
                silo.status = "kosong"
                nama.append(silo.nama_silo.replace("Silo ", ""))
        # Kalimatnya menyebut SEMUANYA. "Silo A kosong" atas giling yang
        # memakan A dan B adalah kabar yang benar separuh, dan separuhnya yang
        # hilang justru yang akan dicari orang.
        nama_silo = _rangkai(nama) or None
    # ── SELURUH sumber ditandai "digiling", bukan hanya yang utama ──
    #
    # Dulu hanya `proc.drying_lot_id` ATAU `proc.purchase_batch_id` — dua
    # penunjuk tunggal peninggalan masa ketika satu giling berarti satu lot.
    # Sejak silo boleh dicampur, sumber sesungguhnya ada di
    # `milling_process_sources`, dan batch yang ikut tergiling lewat jalur
    # lain tetap berstatus lama. Akibatnya ia DITAWARKAN LAGI untuk digiling
    # kedua kalinya — gabah yang sudah jadi PK muncul kembali sebagai gabah.
    # Temuan QA P-K-18, dan ini kali ketiga penunjuk tunggal itu menyesatkan.
    bids: set[int] = set()
    if proc.drying_lot_id:
        bids |= set((await db.execute(
            select(DryingLotBatch.purchase_batch_id).where(
                DryingLotBatch.drying_lot_id == proc.drying_lot_id)
        )).scalars().all())
    if proc.purchase_batch_id:
        bids.add(proc.purchase_batch_id)
    # Sumber sesungguhnya — termasuk gabah yang masuk saat giling berjalan.
    for lot_id, batch_id in (await db.execute(
        select(MillingProcessSource.drying_lot_id,
               MillingProcessSource.purchase_batch_id)
        .where(MillingProcessSource.milling_process_id == proc.id)
    )).all():
        if batch_id:
            bids.add(batch_id)
        if lot_id:
            bids |= set((await db.execute(
                select(DryingLotBatch.purchase_batch_id).where(
                    DryingLotBatch.drying_lot_id == lot_id)
            )).scalars().all())
    for bid in {b for b in bids if b}:
        b = await db.get(PurchaseBatch, bid)
        if b:
            b.status_batch = "digiling"

    # ── Jeda yang masih terbuka ikut ditutup ──
    #
    # Temuan QA P-K-17. Menutup proses yang sedang dijeda meninggalkan baris
    # jeda tanpa waktu selesai, dan laporan waktu henti terus bertambah untuk
    # mesin yang sudah berhenti berhari-hari lalu. Angka itu dipakai menilai
    # kinerja shift, jadi yang rusak bukan cuma tampilannya.
    await _tutup_jeda_terbuka(db, proc, now)

    bd = await _pk_breakdown(db, proc.id)
    await log_activity(
        db, table_name="milling_process", record_id=proc.id, action="UPDATE",
        changed_by=user.id, field_name="status", new_value="selesai",
    )
    jenis = await pk_jenis(db, proc)
    await db.commit()
    return FinishResult(
        proc=proc, nama_silo=nama_silo, produced=bd.produced, siap_kirim=bd.tersedia,
        jenis=jenis,
    )


# ─────────────────────────── Laporan ───────────────────────────
async def _latest_progress(db: AsyncSession, proc_id: int) -> float | None:
    v = (
        await db.execute(
            select(MillingProgressLog.berat_kumulatif_kg)
            .where(MillingProgressLog.milling_process_id == proc_id)
            .order_by(MillingProgressLog.waktu_update.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return float(v) if v is not None else None


async def _produced_pk(db: AsyncSession, proc_id: int) -> float:
    """PK dihasilkan. Angka TERVERIFIKASI menang atas progres operator.

    Progres kumulatif diketik operator sambil mesin jalan — ia perkiraan yang
    berguna selama proses, tetapi bukan angka final. Yang final ditetapkan
    admin di `milling_process_verifications.berat_output_final_kg`, dan itulah
    yang sudah dipakai HPP.

    Sebelumnya fungsi ini hanya membaca progres. Akibatnya: giling yang ditutup
    TANPA operator pernah mencatat hasilnya, lalu outputnya diverifikasi admin
    sebesar 6.300 kg, tetap berstok NOL — hilang dari layar Stok dan tak bisa
    dikirim ke Gudang 2. Angka yang sudah diverifikasi tetapi tak dipakai
    adalah pekerjaan verifikasi yang dibuang.
    """
    v = (await db.execute(
        select(MillingProcessVerification.berat_output_final_kg).where(
            MillingProcessVerification.milling_process_id == proc_id)
    )).scalars().first()
    if v is not None:
        return float(v)
    v = await _latest_progress(db, proc_id)
    return float(v) if v is not None else 0.0


async def _transferred_pk(db: AsyncSession, proc_id: int) -> float:
    """Total PK yang SUDAH dikirim (transfer) dari sebuah proses."""
    r = (
        await db.execute(
            select(func.coalesce(func.sum(InternalTransfer.berat_kg), 0)).where(
                InternalTransfer.milling_process_id == proc_id,
                InternalTransfer.status == "terkirim",
            )
        )
    ).scalar_one()
    return float(r)


@dataclass
class PkBreakdown:
    produced: float     # total PK dihasilkan (hasil yang di-update operator)
    transferred: float  # sudah dikirim ke Gudang 2
    tersedia: float     # siap kirim (stok) = produced - transferred


async def _sold_pk_langsung(db: AsyncSession, proc_id: int) -> float:
    """PK yang sudah dijual langsung dari Gudang 1 (barang keluar pk_langsung)."""
    from app.models import OutgoingItem
    r = (
        await db.execute(
            select(func.coalesce(func.sum(OutgoingItem.berat_kg), 0)).where(
                OutgoingItem.item_type == "pk_langsung",
                OutgoingItem.milling_process_id == proc_id,
            )
        )
    ).scalar_one()
    return float(r)


async def _pk_breakdown(db: AsyncSession, proc_id: int) -> PkBreakdown:
    """Stok PK siap kirim = hasil − dikirim (transfer) − dijual langsung."""
    produced = await _produced_pk(db, proc_id)
    transferred = await _transferred_pk(db, proc_id)
    sold = await _sold_pk_langsung(db, proc_id)
    return PkBreakdown(produced, transferred, max(produced - transferred - sold, 0.0))


async def _milling_supplier_names(db: AsyncSession, proc: MillingProcess) -> list[str]:
    """Supplier asal bahan sebuah proses giling — dari SELURUH isinya.

    Dulu dibaca dari `proc.drying_lot_id`/`purchase_batch_id`, penunjuk tunggal
    peninggalan masa ketika satu silo hanya boleh berisi satu hal. Sejak silo
    boleh dicampur, penunjuk itu menyebut salah satu sumber dan mendiamkan
    sisanya: silo berisi pengeringan DAN gabah kering langsung akan melaporkan
    supplier yang pertama saja. Yang kedua hilang dari laporan tanpa jejak —
    padahal gabahnya ikut tergiling dan ikut dibayar.

    `sumber_batch` sudah menjawab pertanyaan yang sama untuk HPP; laporan
    memakai sumber yang sama supaya keduanya tak mungkin berselisih.
    """
    nama: list[str] = []
    for b, _harga, _lewat in await sumber_batch(db, proc):
        sup = await db.get(Supplier, b.supplier_id)
        if sup and sup.nama_supplier not in nama:
            nama.append(sup.nama_supplier)
    return nama


async def asal_isi(db: AsyncSession, proc: MillingProcess) -> list[str]:
    """Baris "asal-usul" satu lot giling: tiap sumber, tiap batch, tiap tiket.

    Inilah yang menjawab "beras ini dari gabah siapa" tanpa membuka basis
    data. Dikelompokkan per sumber karena itulah bentuk fisiknya: gabah yang
    dikeringkan bersama tak bisa lagi dipisahkan di dalam silo.
    """
    baris = list((await db.execute(
        select(MillingProcessSource)
        .where(MillingProcessSource.milling_process_id == proc.id)
        .order_by(MillingProcessSource.id)
    )).scalars().all())
    if not baris:
        return []

    # Kode tiket timbang milik aplikasi Timbangan — dibaca lewat SQL mentah di
    # basis data bersama. Kalau tabelnya tak ada (pemasangan tanpa timbangan),
    # asal-usulnya tetap tampil, hanya tanpa nomor tiket.
    async def kode_tiket(ids: list[int]) -> dict[int, str]:
        if not ids:
            return {}
        try:
            rows = (await db.execute(
                text("SELECT id, kode FROM timbangan_transaksi WHERE id = ANY(:ids)"),
                {"ids": ids},
            )).all()
            return {r[0]: r[1] for r in rows}
        except Exception:
            return {}

    out: list[str] = []
    for s_ in baris:
        if s_.drying_lot_id:
            lot = await db.get(DryingLot, s_.drying_lot_id)
            judul = f"  ‣ {lot.kode_lot if lot else 'pengeringan'} · {_kg(float(s_.berat_kg))}"
            batches = list((await db.execute(
                select(PurchaseBatch)
                .join(DryingLotBatch, DryingLotBatch.purchase_batch_id == PurchaseBatch.id)
                .where(DryingLotBatch.drying_lot_id == s_.drying_lot_id)
                .order_by(PurchaseBatch.id)
            )).scalars().all())
        else:
            judul = f"  ‣ tanpa pengeringan · {_kg(float(s_.berat_kg))}"
            b = await db.get(PurchaseBatch, s_.purchase_batch_id)
            batches = [b] if b else []
        out.append(judul)
        tiket = await kode_tiket([b.timbangan_transaksi_id for b in batches
                                 if b.timbangan_transaksi_id])
        for b in batches:
            sup = await db.get(Supplier, b.supplier_id)
            tk = tiket.get(b.timbangan_transaksi_id or -1)
            out.append(
                f"     – {b.kode_batch} · {b.kondisi_gabah} "
                f"{_kg(float(b.berat_total_kg or 0))} · {sup.nama_supplier if sup else '-'}"
                + (f" · tiket {tk}" if tk else "")
            )
    return out


#: Kondisi gabah saat DIBELI → kelas PK yang keluar darinya.
KELAS_PK = {"basah": "KS", "kering": "KL"}

#: Lot yang bahannya dua-duanya. Bukan "campuran" — satu kata yang meringkas
#: dua asal-usul terbaca seperti nama varietas, dan yang membacanya akan
#: mencari gabah bernama itu.
KELAS_PK_CAMPUR = "MIX"


def kelas_pk(kondisi: list[str]) -> str | None:
    """KS / KL / MIX dari daftar kondisi beli bahannya. None bila tak diketahui."""
    kode = [KELAS_PK[k] for k in kondisi if k in KELAS_PK]
    if not kode:
        return None
    return kode[0] if len(set(kode)) == 1 else KELAS_PK_CAMPUR


async def _source_kondisi(db: AsyncSession, proc: MillingProcess) -> list[str]:
    """Kondisi beli gabah sumber proses — dari SELURUH isinya.

    Dulu dibaca dari `proc.drying_lot_id`/`purchase_batch_id`, penunjuk tunggal
    peninggalan masa ketika satu silo hanya boleh berisi satu hal, dengan
    catatan "satu lot tidak boleh campur basah & kering, jadi cukup satu batch
    sumber". Catatan itu tidak lagi benar: silo Gudang 1 boleh berisi gabah
    yang KAMI keringkan (dibeli basah) bersama gabah yang datang sudah kering.
    Keduanya sama-sama kering saat digiling — yang membedakan adalah kelas PK
    yang keluar, dan itu justru yang dijual.

    Akibat bentuk lama: lot bercampur mengaku KS saja, diam-diam, dan PK KL di
    dalamnya hilang dari laporan, dari transfer, dan dari catatan QC.

    `sumber_batch` sudah menjawab pertanyaan "apa isi proses ini" untuk HPP;
    di sini dipakai sumber yang sama supaya keduanya tak mungkin berselisih.
    """
    kondisi: list[str] = []
    for b, _harga, _lewat in await sumber_batch(db, proc):
        k = (b.kondisi_gabah or "").strip().lower()
        if k and k not in kondisi:
            kondisi.append(k)
    return [k for k in ("basah", "kering") if k in kondisi]


async def pk_jenis(db: AsyncSession, proc: MillingProcess) -> str | None:
    """Kelas PK hasil Gudang 1: KS (dari gabah basah), KL (kering), MIX (dua-duanya)."""
    return kelas_pk(await _source_kondisi(db, proc))


def _kg(kg: float) -> str:
    return f"{kg:,.0f} kg".replace(",", ".")


async def laporan_milling(db: AsyncSession, kode_proses: str | None = None) -> str:
    now = now_local()
    if kode_proses:
        proc = await get_process_by_kode(db, kode_proses)
        if proc is None:
            return f"Proses {kode_proses} tidak ditemukan."
        masuk = float(proc.berat_gabah_masuk_kg or 0)
        prog = await _latest_progress(db, proc.id)
        bd = await _pk_breakdown(db, proc.id)
        suppliers = await _milling_supplier_names(db, proc)
        nama = ", ".join(suppliers) if suppliers else "-"
        jenis = await pk_jenis(db, proc)
        jenis_lbl = f" ({jenis})" if jenis else ""
        lines = [
            f"⚙️ Giling {proc.kode_proses} — bahan dari {nama}",
            f"• Status: {proc.status}",
            f"• Jenis PK: {jenis or '-'}",
            f"• Gabah masuk: {_kg(masuk)}",
            f"• PK dihasilkan: {_kg(bd.produced)}{jenis_lbl}",
            f"• Siap kirim (stok): {_kg(bd.tersedia)}",
        ]
        asal = await asal_isi(db, proc)
        if asal:
            lines.append("• Asal gabah:")
            lines += asal
        if bd.transferred > 0:
            lines.append(f"• Sudah dikirim: {_kg(bd.transferred)}")
        r = hitung_rendemen(prog, proc.berat_gabah_masuk_kg)
        if r is not None:
            lines.append(f"• Rendemen sementara: {r:.1f}%")
        return "\n".join(lines)

    procs = (
        await db.execute(
            select(MillingProcess).where(MillingProcess.status == "proses").order_by(MillingProcess.id)
        )
    ).scalars().all()
    if not procs:
        return "⚙️ Tidak ada proses giling yang sedang berjalan."
    lines = [f"⚙️ Giling berjalan ({len(procs)} proses):"]
    for proc in procs:
        prog = await _latest_progress(db, proc.id)
        jam = (now - proc.waktu_mulai).total_seconds() / 3600
        jenis = await pk_jenis(db, proc)
        jlbl = f" {jenis}" if jenis else ""
        lines.append(
            f"• {proc.kode_proses}: PK{jlbl} {_kg(prog) if prog is not None else '0 kg'} — {jam:.1f} jam"
        )
    return "\n".join(lines)


async def stok_pk_gudang1(db: AsyncSession) -> str:
    """Stok PK siap kirim di Gudang 1 = hasil produksi tiap proses − yang sudah dikirim."""
    procs = (
        await db.execute(
            select(MillingProcess).order_by(MillingProcess.kode_proses)
        )
    ).scalars().all()
    items: list[tuple[str, str | None, PkBreakdown]] = []
    for proc in procs:
        bd = await _pk_breakdown(db, proc.id)
        if bd.tersedia > 0:
            items.append((proc.kode_proses, await pk_jenis(db, proc), bd))
    if not items:
        return "📦 Stok PK Gudang 1 kosong."
    total = sum(bd.tersedia for _, _, bd in items)
    sub: dict[str, float] = {}
    for _, jenis, bd in items:
        sub[jenis or "?"] = sub.get(jenis or "?", 0.0) + bd.tersedia
    ringkas = " · ".join(f"{j} {_kg(v)}" for j, v in sorted(sub.items()))
    lines = [f"📦 Stok PK siap kirim Gudang 1: {_kg(total)}  ({ringkas})"]
    for kode, jenis, bd in items:
        detail = f"• {jenis or '-'} dari {kode}: {_kg(bd.tersedia)}"
        if bd.transferred > 0:
            detail += f" (dari {_kg(bd.produced)}, terkirim {_kg(bd.transferred)})"
        lines.append(detail)
    return "\n".join(lines)


# ─────────────────────── QC & Verifikasi (staff/admin) ───────────────────────
@dataclass
class QcResult:
    proc: MillingProcess
    kadar_air: float | None
    broken: float | None
    susut: float | None
    kondisi: str | None
    qc_count: int
    #: Rata-rata SESUDAH catatan ini masuk — yang dibaca orang di kalimat
    #: balasannya. Angka yang baru saja ia ketik sudah ia tahu; yang belum ia
    #: tahu adalah ke mana angka itu menggeser rata-ratanya.
    rata: "QcRata | None" = None


@dataclass(frozen=True)
class QcRata:
    """Rata-rata QC satu proses giling, berikut berapa catatan yang menyusunnya.

    Mutu dicatat BERULANG selama proses berjalan (keputusan pemilik 24 September
    2026: "pencatatan juga bisa dilakukan saat proses berlangsung dari kartu
    proses yang sedang berlangsung; nanti hasilnya di rata-rata"). Satu tusukan
    di awal giling dan satu di akhir menggambarkan muatan yang sama lebih jujur
    daripada satu angka yang kebetulan diambil di menit terakhir.

    Tiap kolom dirata-rata SENDIRI, dan hanya dari catatan yang mengisinya:
    borangnya memang menerima "isi minimal salah satu", jadi catatan yang cuma
    menyebut broken tak boleh menyeret rata-rata kadar air ke bawah. Karena itu
    `n` per kolom, bukan satu jumlah untuk semuanya.
    """

    kadar_air: float | None = None
    broken: float | None = None
    susut: float | None = None
    n_kadar_air: int = 0
    n_broken: int = 0
    n_susut: int = 0
    #: Berapa catatan QC seluruhnya — termasuk yang cuma mengisi satu kolom.
    n: int = 0

    @property
    def ada(self) -> bool:
        return self.n > 0

    def teks(self) -> str:
        """Satu baris untuk kartu. Kosong bila belum ada catatan sama sekali."""
        bagian = [f"{nama} {nilai:.1f}%".replace(".", ",")
                  for nama, nilai in (("KA", self.kadar_air), ("broken", self.broken),
                                      ("susut", self.susut)) if nilai is not None]
        if not bagian:
            return ""
        # Jumlah catatannya ikut disebut: rata-rata dari satu tusukan dan
        # rata-rata dari lima tusukan sama-sama berupa satu angka di layar, dan
        # yang membacanya berhak tahu bedanya.
        return " · ".join(bagian) + f" (rata-rata {self.n} catatan)"


async def qc_rata(db: AsyncSession, proc_id: int) -> QcRata:
    """Rata-rata QC satu proses giling."""
    return (await qc_rata_banyak(db, [proc_id])).get(proc_id, QcRata())


async def qc_rata_banyak(db: AsyncSession, proc_ids) -> dict[int, QcRata]:
    """Rata-rata QC beberapa proses sekaligus — SATU kueri.

    Kartu giling digambar untuk tiap proses yang menyala, dan kartu itu ikut
    disusun ulang tiap kali lencana laci dihitung, yaitu di tiap halaman. Satu
    kueri per proses di tempat seperti itu adalah pola yang sudah pernah
    membuat layar Stok mengeluarkan ribuan kueri (QA P-S-02).
    """
    ids = [int(x) for x in proc_ids]
    if not ids:
        return {}
    baris = (await db.execute(
        select(
            MillingQcLog.milling_process_id,
            func.avg(MillingQcLog.kadar_air), func.count(MillingQcLog.kadar_air),
            func.avg(MillingQcLog.broken_persen), func.count(MillingQcLog.broken_persen),
            func.avg(MillingQcLog.susut_persen), func.count(MillingQcLog.susut_persen),
            func.count(),
        ).where(MillingQcLog.milling_process_id.in_(ids))
        .group_by(MillingQcLog.milling_process_id)
    )).all()
    return {r[0]: QcRata(
        kadar_air=float(r[1]) if r[1] is not None else None,
        broken=float(r[3]) if r[3] is not None else None,
        susut=float(r[5]) if r[5] is not None else None,
        n_kadar_air=int(r[2]), n_broken=int(r[4]), n_susut=int(r[6]), n=int(r[7]),
    ) for r in baris}


async def log_qc_milling(
    db: AsyncSession,
    *,
    user,
    kode_proses: str | None,
    kadar_air: float | None,
    broken: float | None,
    susut: float | None,
    kondisi: str | None,
) -> QcResult:
    if not kode_proses:
        raise MillingError(
            "Sebutkan kode proses, contoh: `QC LOT-20260702-01 kadar air 13 broken 5 kondisi KS`"
        )
    proc = await get_process_by_kode(db, kode_proses)
    if proc is None:
        raise MillingError(f"Proses {kode_proses} tidak ditemukan.")
    if all(v is None for v in (kadar_air, broken, susut)):
        raise MillingError("Sebutkan hasil QC-nya (kadar air / broken / susut).")
    # Proses yang MASIH BERJALAN boleh dicatat mutunya (pemilik 24 September
    # 2026) — dan memang di situlah contohnya diambil: dari beras yang baru
    # keluar mesin, bukan dari tumpukan yang sudah ditutup. Tak ada syarat
    # status di sini; yang menolak hanya proses yang tak ada.
    # Jenis PK TIDAK diisi manual — ditentukan otomatis dari kondisi gabah
    # SELURUH sumbernya: basah → KS, kering → KL, dua-duanya → MIX. Input
    # manual diabaikan.
    kondisi = await pk_jenis(db, proc) or kondisi

    db.add(
        MillingQcLog(
            milling_process_id=proc.id,
            kadar_air=kadar_air,
            broken_persen=broken,
            susut_persen=susut,
            kondisi=kondisi,
            waktu=now_local(),
            input_by=user.id,
        )
    )
    await log_activity(
        db, table_name="milling_qc_logs", record_id=proc.id, action="INSERT",
        changed_by=user.id,
        new_value=f"ka={kadar_air} broken={broken} susut={susut} kondisi={kondisi}",
    )
    await db.commit()
    rata = await qc_rata(db, proc.id)
    return QcResult(
        proc=proc, kadar_air=kadar_air, broken=broken, susut=susut,
        kondisi=kondisi, qc_count=rata.n, rata=rata,
    )


@dataclass
class VerifyOutputResult:
    proc: MillingProcess
    berat_output: float
    rendemen_persen: float | None
    re_verified: bool


async def verify_milling_output(
    db: AsyncSession, *, user, kode_proses: str | None, berat_output: float | None
) -> VerifyOutputResult:
    if not kode_proses:
        raise MillingError(
            "Sebutkan kode proses, contoh: `verifikasi output LOT-20260702-01 14 ton`"
        )
    proc = await get_process_by_kode(db, kode_proses)
    if proc is None:
        raise MillingError(f"Proses {kode_proses} tidak ditemukan.")
    if berat_output is None:
        raise MillingError("Sebutkan berat output PK final-nya, mis. `... 14 ton`.")
    # Rendemen final dan HPP berdiri di atas bahan masuk. Selama bahannya
    # belum final, verifikasi ditahan — dengan menyebut truk mana yang
    # ditunggu, bukan diam-diam menghitung dari angka yang kurang.
    if not proc.bobot_masuk_final:
        raise MillingError(await _pesan_belum_final(db, proc))

    verif = (
        await db.execute(
            select(MillingProcessVerification).where(
                MillingProcessVerification.milling_process_id == proc.id
            )
        )
    ).scalars().first()
    re_verified = verif is not None
    if verif is None:
        verif = MillingProcessVerification(milling_process_id=proc.id)
        db.add(verif)
    verif.berat_output_final_kg = berat_output
    verif.verified_by = user.id
    verif.waktu_verifikasi = now_local()
    verif.status_verifikasi = "terverifikasi"

    await log_activity(
        db,
        table_name="milling_process_verifications",
        record_id=proc.id,
        action="UPDATE" if re_verified else "INSERT",
        changed_by=user.id,
        field_name="berat_output_final_kg",
        new_value=f"{berat_output:.0f}",
    )
    await db.commit()
    rendemen = hitung_rendemen(berat_output, proc.berat_gabah_masuk_kg)
    return VerifyOutputResult(
        proc=proc, berat_output=berat_output, rendemen_persen=rendemen, re_verified=re_verified
    )


async def _pesan_belum_final(db: AsyncSession, proc: MillingProcess) -> str:
    """Kalimat yang menyebut BAHAN MANA yang belum final — itulah yang bisa
    ditindaklanjuti: dahulukan truk itu di antrean timbang."""
    bagian = []
    for b, _h, _lewat in await sumber_batch(db, proc):
        bb = dari_batch(b)
        if bb.pasti:
            continue
        sup = await db.get(Supplier, b.supplier_id)
        nama = sup.nama_supplier if sup else "?"
        bagian.append(f"{b.kode_batch} ({nama}) "
                      + ("masih perkiraan dari tara truk" if bb.keadaan != TAK_DIKETAHUI
                         else "belum ditimbang kedua"))
    return (f"Bahan giling {proc.kode_proses} belum final: " + "; ".join(bagian)
            + ". Verifikasi output menunggu bobot pasti — angkanya dibetulkan "
              "otomatis begitu truknya ditimbang.")


async def sumber_batch(
    db: AsyncSession, proc: MillingProcess
) -> list[tuple[PurchaseBatch, float | None, bool]]:
    """Batch gabah yang benar-benar masuk sebuah proses giling.

    Kembalian: (batch, harga_per_kg | None, lewat_dryer).

    SATU tempat untuk pertanyaan "apa isi proses ini", dipakai HPP maupun
    analitik. Dulu keduanya menjawabnya sendiri-sendiri dari penunjuk tunggal
    di `MillingProcess`, dan jawaban itu hanya benar selama satu silo tak
    boleh dicampur. Begitu boleh, keduanya akan menghitung sebagian isi saja —
    dan pada HPP, "sebagian" berarti angka uang yang salah tanpa ada yang tahu.

    `lewat_dryer` ditentukan per batch, bukan per proses: satu silo bisa berisi
    gabah yang dikeringkan DAN gabah kering yang langsung masuk. Menagihkan
    satu tarif pengeringan untuk keduanya salah ke dua arah sekaligus.
    """
    baris = list((await db.execute(
        select(MillingProcessSource).where(
            MillingProcessSource.milling_process_id == proc.id
        )
    )).scalars().all())

    # Proses lama yang tak punya baris silo (sebelum penautan timbang) tidak
    # ikut terisi migrasi. Penunjuk tunggalnya masih satu-satunya yang ada.
    pasangan: list[tuple[int | None, int | None]] = (
        [(b.drying_lot_id, b.purchase_batch_id) for b in baris] if baris
        else [(proc.drying_lot_id, proc.purchase_batch_id)]
    )

    harga = dict((await db.execute(
        select(PurchaseBatchVerification.purchase_batch_id,
               PurchaseBatchVerification.harga_per_kg)
    )).all())

    hasil: list[tuple[PurchaseBatch, float | None, bool]] = []
    terlihat: set[int] = set()
    for lot_id, batch_id in pasangan:
        if lot_id:
            lot = await db.get(DryingLot, lot_id)
            lewat = lot is not None and lot.dryer_id is not None
            batches = (await db.execute(
                select(PurchaseBatch)
                .join(DryingLotBatch,
                      DryingLotBatch.purchase_batch_id == PurchaseBatch.id)
                .where(DryingLotBatch.drying_lot_id == lot_id)
            )).scalars().all()
        elif batch_id:
            lewat = False
            b = await db.get(PurchaseBatch, batch_id)
            batches = [b] if b else []
        else:
            continue
        for b in batches:
            if b.id in terlihat:      # satu batch tak boleh terhitung dua kali
                continue
            terlihat.add(b.id)
            h = harga.get(b.id)
            hasil.append((b, float(h) if h is not None else None, lewat))
    return hasil


async def resinkron_bahan_berjalan(db: AsyncSession) -> list[str]:
    """Samakan bahan giling dengan bobot batchnya SEKARANG.

    `berat_gabah_masuk_kg` dan `milling_process_sources.berat_kg` diambil
    sebagai cuplikan saat giling dimulai. Cuplikan itu benar pada detik itu —
    tetapi begitu timbangan membetulkan (atau baru MELENGKAPI) berat sebuah
    tiket, ia jadi salinan yang tak pernah dibaca ulang, dan salinan yang tak
    pernah dibaca ulang adalah cara paling umum dua aplikasi mulai berbeda
    tanpa ada yang menyadarinya.

    Akibatnya bukan satu angka meleset: `berat_gabah_masuk_kg` adalah penyebut
    rendemen. Bahan yang tercatat lebih kecil daripada yang sungguh masuk
    membuat rendemen terbaca melambung — dan yang melihatnya akan mencari
    sebabnya di mesin, bukan di catatan.

    Dua golongan proses dijangkau:

      * yang masih `proses` — apa pun sebab bobotnya berubah;
      * yang sudah `selesai` TETAPI `bobot_masuk_final` masih false — giling
        yang ditutup sebelum truknya ditimbang kedua (QA P6-03). Dulu yang
        selesai tak pernah disentuh, dengan alasan angkanya sudah masuk
        laporan; untuk bahan yang sejak awal belum final, alasan itu justru
        terbalik: laporannya berdiri di atas bobot yang kurang, selamanya.
        Yang selesai dengan bahan yang memang sudah final tetap tak disentuh.

    → daftar kode proses yang berubah (kosong = semuanya sudah cocok).
    """
    berubah: list[str] = []
    procs = (await db.execute(
        select(MillingProcess).where(or_(
            MillingProcess.status == "proses",
            MillingProcess.bobot_masuk_final.is_(False),
        ))
    )).scalars().all()
    for proc in procs:
        sumber = (await db.execute(
            select(MillingProcessSource).where(
                MillingProcessSource.milling_process_id == proc.id)
        )).scalars().all()
        if not sumber:
            continue
        bagian: list[Bobot] = []
        ada_geser = False
        for src in sumber:
            st = await db.get(SiloStorage, src.silo_storage_id)
            if st is None:
                bagian.append(Bobot(float(src.berat_kg), PASTI) if src.berat_kg is not None
                              else Bobot(None, TAK_DIKETAHUI, 1))
                continue
            bb = await _storage_bobot(db, st)
            lama_src = float(src.berat_kg) if src.berat_kg is not None else None
            if lama_src != bb.kg:
                src.berat_kg = bb.kg
                ada_geser = True
            bagian.append(bb)
        total = jumlah_bobot(bagian)
        lama = float(proc.berat_gabah_masuk_kg) if proc.berat_gabah_masuk_kg is not None else None
        if ada_geser or lama != total.kg or proc.bobot_masuk_final != total.pasti:
            proc.berat_gabah_masuk_kg = total.kg
            proc.bobot_masuk_final = total.pasti
            await log_activity(
                db, table_name="milling_process", record_id=proc.id,
                action="UPDATE", changed_by=proc.created_by,
                field_name="berat_gabah_masuk_kg",
                old_value=f"{lama:.0f}" if lama is not None else "belum diketahui",
                new_value=total.teks(),
                alasan="bobot tiket direvisi atau dilengkapi di aplikasi timbangan",
            )
            berubah.append(proc.kode_proses)
    if berubah:
        await db.commit()
    return berubah


# ══════════════════ Versi BANYAK-SEKALIGUS (temuan QA P-S-02) ══════════════════
#
# Fungsi-fungsi di atas menjawab satu proses giling per panggilan, dan tiap
# jawaban memakan 2–4 kueri. Layar yang menampilkan seluruh proses karenanya
# mengeluarkan ribuan kueri: dengan data setahun, Beranda 7.482 kueri (5,2
# detik), /stok 6.261, /api/dashboard 6.633. Bukan satu kueri yang lambat —
# melainkan ribuan kueri yang masing-masing cepat.
#
# Yang di bawah menjawab pertanyaan yang SAMA untuk sekumpulan proses
# sekaligus, satu kueri per pertanyaan. Bentuknya sengaja dibuat mengembalikan
# kamus berkunci id, supaya pemanggilnya berubah sesedikit mungkin: yang tadinya
# `await _pk_breakdown(db, p.id)` di dalam gelung menjadi `bd[p.id]` di luarnya.
#
# Yang satuan TIDAK dihapus: ia masih dipakai jalur yang memang hanya
# menyangkut satu proses (layar rincian, laporan satu kode), dan di sana ia
# memang bentuk yang benar.


async def progress_banyak(db: AsyncSession, proc_ids) -> dict[int, float | None]:
    """Progres kumulatif TERAKHIR tiap proses. Satu kueri."""
    ids = list(proc_ids)
    if not ids:
        return {}
    # Baris terakhir per proses: nomor urut menurut waktu, ambil yang pertama.
    urut = func.row_number().over(
        partition_by=MillingProgressLog.milling_process_id,
        order_by=MillingProgressLog.waktu_update.desc(),
    ).label("urut")
    sub = select(
        MillingProgressLog.milling_process_id.label("pid"),
        MillingProgressLog.berat_kumulatif_kg.label("kg"),
        urut,
    ).where(MillingProgressLog.milling_process_id.in_(ids)).subquery()
    baris = (await db.execute(
        select(sub.c.pid, sub.c.kg).where(sub.c.urut == 1)
    )).all()
    return {pid: (float(kg) if kg is not None else None) for pid, kg in baris}


async def pk_breakdown_banyak(db: AsyncSession, proc_ids) -> dict[int, PkBreakdown]:
    """`_pk_breakdown` untuk banyak proses. Empat kueri, bukan 4×N."""
    from app.models import OutgoingItem

    ids = list(proc_ids)
    if not ids:
        return {}

    verif = dict((await db.execute(
        select(MillingProcessVerification.milling_process_id,
               MillingProcessVerification.berat_output_final_kg)
        .where(MillingProcessVerification.milling_process_id.in_(ids))
    )).all())
    progres = await progress_banyak(db, ids)

    terkirim = dict((await db.execute(
        select(InternalTransfer.milling_process_id,
               func.coalesce(func.sum(InternalTransfer.berat_kg), 0))
        .where(InternalTransfer.milling_process_id.in_(ids),
               InternalTransfer.status == "terkirim")
        .group_by(InternalTransfer.milling_process_id)
    )).all())

    terjual = dict((await db.execute(
        select(OutgoingItem.milling_process_id,
               func.coalesce(func.sum(OutgoingItem.berat_kg), 0))
        .where(OutgoingItem.milling_process_id.in_(ids),
               OutgoingItem.item_type == "pk_langsung")
        .group_by(OutgoingItem.milling_process_id)
    )).all())

    hasil: dict[int, PkBreakdown] = {}
    for pid in ids:
        # Angka TERVERIFIKASI menang atas progres operator — urutan yang sama
        # persis dengan `_produced_pk`, dan sengaja: dua jalur yang menjawab
        # berbeda untuk proses yang sama adalah bug yang tak terlihat.
        v = verif.get(pid)
        produced = float(v) if v is not None else float(progres.get(pid) or 0.0)
        dikirim = float(terkirim.get(pid, 0) or 0)
        dijual = float(terjual.get(pid, 0) or 0)
        hasil[pid] = PkBreakdown(
            produced, dikirim, max(produced - dikirim - dijual, 0.0))
    return hasil


async def pk_jenis_banyak(db: AsyncSession, procs) -> dict[int, str | None]:
    """`pk_jenis` untuk banyak proses. Tiga kueri, bukan 3×N."""
    daftar = list(procs)
    if not daftar:
        return {}
    ids = [p.id for p in daftar]

    sumber = (await db.execute(
        select(MillingProcessSource.milling_process_id,
               MillingProcessSource.drying_lot_id,
               MillingProcessSource.purchase_batch_id)
        .where(MillingProcessSource.milling_process_id.in_(ids))
    )).all()
    per_proses: dict[int, list[tuple[int | None, int | None]]] = {}
    for pid, lot_id, batch_id in sumber:
        per_proses.setdefault(pid, []).append((lot_id, batch_id))

    # Proses lama tanpa baris silo masih memakai penunjuk tunggalnya.
    for p in daftar:
        per_proses.setdefault(p.id, [(p.drying_lot_id, p.purchase_batch_id)])

    lot_ids = {l for pasangan in per_proses.values() for l, _ in pasangan if l}
    batch_ids = {b for pasangan in per_proses.values() for _, b in pasangan if b}

    # Batch di balik tiap lot pengeringan.
    lot_batch: dict[int, list[int]] = {}
    if lot_ids:
        for lot_id, batch_id in (await db.execute(
            select(DryingLotBatch.drying_lot_id, DryingLotBatch.purchase_batch_id)
            .where(DryingLotBatch.drying_lot_id.in_(lot_ids))
        )).all():
            lot_batch.setdefault(lot_id, []).append(batch_id)
            batch_ids.add(batch_id)

    kondisi_batch = dict((await db.execute(
        select(PurchaseBatch.id, PurchaseBatch.kondisi_gabah)
        .where(PurchaseBatch.id.in_(batch_ids))
    )).all()) if batch_ids else {}

    hasil: dict[int, str | None] = {}
    for pid, pasangan in per_proses.items():
        kondisi: list[str] = []
        for lot_id, batch_id in pasangan:
            ids_batch = lot_batch.get(lot_id, []) if lot_id else (
                [batch_id] if batch_id else [])
            for bid in ids_batch:
                k = (kondisi_batch.get(bid) or "").strip().lower()
                if k and k not in kondisi:
                    kondisi.append(k)
        hasil[pid] = kelas_pk([k for k in ("basah", "kering") if k in kondisi])
    return hasil
