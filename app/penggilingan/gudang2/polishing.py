"""Proses penyosohan Gudang 2 (PK silo → beras putih + hasil samping).

Acuan: MASTER_RULES_AND_LOGIC.md §12.
- Bahan WAJIB dari silo (bukan tumpukan).
- berat_awal silo = snapshot OTOMATIS saat mulai; berat_akhir = input MANUAL
  saat selesai; terpakai = awal + ditambah selama proses − akhir (silo yang
  dipoles boleh diisi lagi — keputusan pemilik 12 September 2026).
- Log output KUMULATIF (ambil terbaru; tak boleh turun).
- HPP per kg beras = biaya konversi (bahan/kemasan − nilai byproduct) — di modul
  produk-jadi. Di sini fokus: run + konsumsi PK + output + rendemen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import input_time
from app.models import (
    PolishingOutputLog,
    PolishingProcess,
    PolishingSiloUsage,
    Silo,
)
from app.services.activity_log import log_activity
from app.services.codegen import next_polishing_code
from app.services.notification import create_notification
from app.penggilingan.gudang2.service import Gudang2Error, get_g2_silo, hitung_stok_silo

# Jenis output yang dikenal.
GRADES = ["sayur", "medium", "medsuper", "premium", "beras_b"]
BYPRODUCTS = ["menir", "broken", "bekatul", "reject"]
_ALL_JENIS = set(GRADES) | set(BYPRODUCTS)


# ─────────────────────────── Mulai ───────────────────────────
@dataclass
class MulaiPenyosohanResult:
    proc: PolishingProcess
    silos: list[str]
    berat_awal_total: float


async def mulai_penyosohan(
    db: AsyncSession, *, user, nama_silos: list[str] | None, tanggal=None, jam=None,
) -> MulaiPenyosohanResult:
    """Mulai penyosohan dari satu/lebih silo Gudang 2 (snapshot berat awal)."""
    letters = [s.upper() for s in (nama_silos or []) if s]
    if not letters:
        raise Gudang2Error("Sebutkan silo bahannya, contoh: `mulai penyosohan silo A`")

    silos: list[Silo] = []
    for letter in dict.fromkeys(letters):  # dedupe, jaga urutan
        silo = await get_g2_silo(db, letter)
        if silo is None:
            # ── Halaman lama yang masih memegang pilihan "AB" ──
            #
            # Sebelum 24 September 2026 borangnya menawarkan A / B / A+B, dan
            # "AB" satu nilai. Halaman di ponsel operator berumur panjang
            # (`pindah.js` menjaganya tetap hidup), jadi yang belum memuat
            # ulang masih mengirimkannya — dan "Silo AB tidak ditemukan"
            # menyebut nama silo yang tak pernah ada, seolah pabriknya yang
            # kehilangan silo. Temuan QA 24 September.
            if len(letter) > 1:
                raise Gudang2Error(
                    "Pilih silo dari daftar — borangnya sudah berubah. "
                    "Muat ulang halamannya, lalu centang silo bahannya.")
            raise Gudang2Error(f"Silo {letter} Gudang 2 tidak ditemukan.")
        # V4: penyosohan hanya dari silo yang ADA isinya.
        if await hitung_stok_silo(db, silo.id) <= 0:
            raise Gudang2Error(
                f"Silo {letter} kosong. Pindahkan PK dari tumpukan ke silo dulu."
            )
        # Silo tak boleh sedang dipakai proses lain yang belum selesai.
        aktif = (
            await db.execute(
                select(PolishingSiloUsage.id)
                .join(PolishingProcess, PolishingProcess.id == PolishingSiloUsage.polishing_process_id)
                .where(
                    PolishingSiloUsage.silo_id == silo.id,
                    PolishingProcess.status == "proses",
                )
            )
        ).first()
        if aktif:
            raise Gudang2Error(f"Silo {letter} sedang dipakai penyosohan lain.")
        silos.append(silo)

    now = input_time(tanggal, jam)
    proc = PolishingProcess(
        kode_proses=await next_polishing_code(db),
        waktu_mulai=now, status="proses", created_by=user.id,
    )
    db.add(proc)
    await db.flush()
    total_awal = 0.0
    for silo in silos:
        awal = await hitung_stok_silo(db, silo.id)
        total_awal += awal
        db.add(PolishingSiloUsage(
            polishing_process_id=proc.id, silo_id=silo.id, berat_awal_kg=awal,
        ))
    await log_activity(
        db, table_name="polishing_process", record_id=proc.id, action="INSERT",
        changed_by=user.id,
        new_value=f"{proc.kode_proses} <- silo {'+'.join(letters)} ({total_awal:.0f}kg)",
    )
    await db.commit()
    await db.refresh(proc)
    return MulaiPenyosohanResult(
        proc=proc, silos=[s.nama_silo.replace("Silo ", "") for s in silos],
        berat_awal_total=total_awal,
    )


# ─────────────────────────── Output (kumulatif) ───────────────────────────
async def _get_proc(db: AsyncSession, kode: str | None) -> PolishingProcess:
    if not kode:
        # Bila hanya satu proses 'proses' berjalan, pakai itu.
        rows = (
            await db.execute(
                select(PolishingProcess).where(PolishingProcess.status == "proses")
            )
        ).scalars().all()
        if len(rows) == 1:
            return rows[0]
        raise Gudang2Error("Sebutkan kode prosesnya, contoh: `hasil premium 2 ton POL-...`")
    proc = (
        await db.execute(
            select(PolishingProcess).where(PolishingProcess.kode_proses == kode)
        )
    ).scalars().first()
    if proc is None:
        raise Gudang2Error(f"Proses {kode} tidak ditemukan.")
    return proc


async def _total_output(db: AsyncSession, proc_id: int, jenis: str) -> float:
    """Total satu jenis pada satu proses — JUMLAH seluruh entrinya.

    Menggantikan `_latest_output`, yang mengambil baris terbaru karena angkanya
    dulu kumulatif (migrasi 0060). Yang mengambil "terbaru" atas entri yang
    bertambah akan menyebut prosesan terakhir sebagai seluruh hasil.
    """
    from sqlalchemy import func

    return float((await db.execute(
        select(func.coalesce(func.sum(PolishingOutputLog.berat_kg), 0))
        .where(PolishingOutputLog.polishing_process_id == proc_id,
               PolishingOutputLog.jenis == jenis)
    )).scalar_one())


@dataclass
class OutputResult:
    proc: PolishingProcess
    jenis: str
    #: Total seluruh entri jenis ini pada proses ini — dihitung, bukan disimpan.
    berat_kumulatif: float
    #: Yang baru saja dicatat, dan speknya.
    berat_kg: float = 0.0
    spek: str | None = None


async def catat_output(
    db: AsyncSession, *, user, kode: str | None, jenis: str | None,
    berat_kg: float | None = None, spek: str | None = None,
    berat_kumulatif: float | None = None, tanggal=None, jam=None,
) -> OutputResult:
    """Catat hasil SATU PROSESAN — yang keluar sekarang, bukan total sejak awal.

    ⚠ ARTINYA BERUBAH 28 September 2026 atas permintaan operator: dalam satu
    penyosohan mereka berganti spek, dan tiap spek punya hasilnya sendiri.
    Dengan kumulatif, mencatat 200 kg broken yang baru — sesudah 300 kg pada
    spek sebelumnya — menuntut mereka mengetik 500, angka yang dijumlah sendiri
    di kepala sambil berdiri di mesin.

    `berat_kumulatif` MASIH DITERIMA dan diperlakukan sebagai entri biasa:
    lembar yang sudah terbuka di layar orang saat versi baru terbit akan
    mengirim nama lama, dan yang menekan Simpan tak punya cara tahu borangnya
    basi. Yang berhenti cuma menawarkannya.

    ⚠ YANG HILANG BERSAMA KUMULATIF, dan penggantinya wajib ada: kumulatif
    TAHAN SALAH KETIK — salah ketik dibetulkan dengan mengetik ulang, nilai
    terakhir menang. Begitu entri bertambah, satu ketukan ganda menambah dua
    kali tanpa terlihat, dan angka salah tak bisa dibetulkan dengan mengetik
    ulang. Karena itu tiap entri kini BISA DIBATALKAN sendiri-sendiri
    (`undo._undo_output_sosoh`), dan `log_activity` menyimpan id BARISNYA —
    bukan id prosesnya seperti dulu, yang membuat pembatalan per entri
    mustahil.
    """
    if not jenis or jenis.lower() not in _ALL_JENIS:
        raise Gudang2Error(
            "Jenis hasil harus salah satu: " + ", ".join(sorted(_ALL_JENIS)) + "."
        )
    jenis = jenis.lower()
    berat = berat_kg if berat_kg is not None else berat_kumulatif
    if berat is None:
        raise Gudang2Error(
            "Sebutkan berat hasil prosesan ini, mis. `premium 2 ton`.")
    if float(berat) <= 0:
        raise Gudang2Error(
            "Berat hasil harus lebih dari 0. Yang keliru dibatalkan lewat "
            "'Batalkan input terakhir', bukan dicatat sebagai angka minus.")
    proc = await _get_proc(db, kode)
    if proc.status == "selesai":
        raise Gudang2Error(f"Proses {proc.kode_proses} sudah selesai.")
    spek = (spek or "").strip() or None
    baris = PolishingOutputLog(
        polishing_process_id=proc.id, jenis=jenis, berat_kg=berat, spek=spek,
        waktu_update=input_time(tanggal, jam), input_by=user.id,
    )
    db.add(baris)
    await db.flush()
    await log_activity(
        db, table_name="polishing_output_logs", record_id=baris.id, action="INSERT",
        changed_by=user.id,
        new_value=f"{jenis} {float(berat):.0f}kg"
                  + (f" · spek {spek}" if spek else ""),
    )
    await db.commit()
    total = await _total_output(db, proc.id, jenis)
    return OutputResult(proc=proc, jenis=jenis, berat_kumulatif=total,
                        berat_kg=float(berat), spek=spek)


# ─────────────────────────── Selesai + rendemen ───────────────────────────
async def _output_map(db: AsyncSession, proc_id: int) -> dict[str, float]:
    """Output terbaru per jenis (kumulatif) — lewat `stok.output_sosoh`.

    Satu corong untuk tiga pembaca: pembanding di sini, layar Stok Produk, dan
    laporan Riwayat produksi. Lihat catatan di sana.
    """
    from app.services.stok import output_sosoh

    return await output_sosoh(db, proc_id)


async def _sebut_silo(db: AsyncSession, usages) -> str:
    """"Silo A dan Silo B" — dibaca dari master, bukan ditulis "A/B" tetap.

    Pesan yang menyebut A/B pada pabrik yang silonya kelak bernama lain adalah
    pesan yang menyuruh orang mencari sesuatu yang tak ada di layarnya.
    """
    nama = []
    for u in usages:
        silo = await db.get(Silo, u.silo_id)
        nama.append(silo.nama_silo if silo else f"silo #{u.silo_id}")
    if len(nama) <= 1:
        return nama[0] if nama else "belum ada silo"
    return ", ".join(nama[:-1]) + " dan " + nama[-1]


@dataclass
class SelesaiResult:
    proc: PolishingProcess
    selesai: bool
    silo: str
    terpakai_silo: float
    pk_terpakai_total: float
    beras_total: float
    rendemen: float | None
    outputs: dict = field(default_factory=dict)


async def selesai_penyosohan(
    db: AsyncSession, *, user, kode: str | None, nama_silo: str | None,
    sisa_kg: float | None, tanggal=None, jam=None,
) -> SelesaiResult:
    """Tandai sisa 1 silo (berat akhir). Bila semua silo sudah, proses SELESAI +
    hitung rendemen."""
    proc = await _get_proc(db, kode)
    if proc.status == "selesai":
        raise Gudang2Error(f"Proses {proc.kode_proses} sudah selesai.")

    # ── PAGAR: tak boleh ditutup tanpa satu pun catatan hasil ──
    #
    # Laporan operator Gudang 2, 28 September 2026: "jika operator tidak
    # sengaja terpencet selesai penyosohan, tetapi belum memasukkan hasil beras
    # dll, hasilnya akan hilang."
    #
    # Direproduksi QA, dan lebih buruk daripada "hilang": 6 ton PK tercatat
    # habis terpakai, nol baris hasil. Berasnya berdiri di lantai tanpa satu
    # baris pun di pembukuan — dan penutupan penyosohan BELUM BISA DIBATALKAN,
    # jadi satu ketukan salah tak punya jalan kembali.
    #
    # ⚠ SENGAJA MENOLAK, bukan "peringatkan tapi terima" seperti rendemen
    # mustahil di Gudang 1. Alasannya berlawanan, dan itu yang menentukan:
    # di sana menolak akan menutup satu-satunya jalan perbaikan (angka
    # kumulatif boleh diketik ulang). Di sini MENERIMA-lah yang menutup jalan
    # perbaikannya.
    if not await _output_map(db, proc.id):
        raise Gudang2Error(
            f"{proc.kode_proses} belum punya satu pun catatan hasil. Catat "
            "hasil penyosohan dulu — beras, menir, broken — baru prosesnya "
            "bisa ditutup.")
    # ── Barisnya DIKUNCI sebelum dibaca ──
    #
    # Pemeriksaan "silo ini masih terbuka?" di bawah dilewati dua permintaan
    # yang datang bersamaan: keduanya membaca "masih terbuka", keduanya
    # menulis, dan yang kedua menimpa sisa yang sudah dicatat yang pertama.
    # Dua operator Gudang 2 di dua HP adalah keadaan sehari-hari, jadi ini
    # bukan kasus tepi.
    #
    # `FOR UPDATE` membuat yang kedua MENUNGGU sampai yang pertama commit,
    # lalu membaca ulang barisnya — kini bersisa — dan ditolak dengan kalimat
    # yang menyebut sisa itu. Pola yang sama dipakai `masukkan_pk_luar` dan
    # `pindah_tumpukan_ke_silo` (P-K-04/05/06).
    usages = (
        await db.execute(
            select(PolishingSiloUsage).where(
                PolishingSiloUsage.polishing_process_id == proc.id
            ).with_for_update()
        )
    ).scalars().all()
    # Pilih usage silo yang dimaksud.
    #
    # Tanpa nama silo, yang dipakai adalah satu-satunya silo yang MASIH terbuka.
    # Proses satu silo karenanya tak perlu menyebutnya sama sekali — dan proses
    # dua silo yang satunya sudah bersisa juga tidak, sebab tinggal satu
    # kemungkinan. "Sebutkan silo mana" hanya berarti bila memang ada lebih
    # dari satu yang bisa dimaksud (keluhan pemilik 24 September 2026 07:14).
    target = None
    terbuka = [u for u in usages if u.berat_akhir_kg is None]
    if nama_silo:
        silo = await get_g2_silo(db, nama_silo.upper())
        # Dipilih dari yang MASIH TERBUKA, bukan dari seluruh baris.
        #
        # Sampai 25 September 2026 di sini tertulis `usages`, dan akibatnya
        # satu silo bisa ditandai selesai DUA KALI: yang kedua menimpa sisa
        # yang sudah dicatat operator pertama, dan selisihnya berpindah
        # diam-diam dari stok ke "terpakai" — penyebut rendemen. 500 jadi 100
        # menggeser 400 kg tanpa jejak di layar mana pun. Temuan QA.
        #
        # Bukan kesalahan yang perlu niat buruk: dua operator Gudang 2 di dua
        # HP, atau satu orang yang borangnya dibiarkan terbuka sebentar
        # (`pindah.js` membuat halaman berumur panjang), lalu menekan simpan
        # atas silo yang barusan ditutup rekannya.
        #
        # Daftar borangnya SUDAH menyaring yang bersisa (`/actions/sosoh-silo`)
        # dan komentarnya menjanjikan tepat ini — yang belum, rutenya.
        target = next((u for u in terbuka if silo and u.silo_id == silo.id), None)
        if target is None:
            sudah = next((u for u in usages if silo and u.silo_id == silo.id), None)
            if sudah is not None:
                # Kalimatnya menyebut sisa yang SUDAH tercatat: yang menekan
                # tombol kedua kalinya biasanya tak tahu yang pertama masuk.
                raise Gudang2Error(
                    f"Silo {nama_silo.upper()} sudah ditandai selesai (sisa "
                    f"{float(sudah.berat_akhir_kg):.0f} kg) — sisanya tak bisa "
                    "dicatat dua kali. Kalau angkanya keliru, mintakan koreksi "
                    "ke Admin.")
            raise Gudang2Error(
                f"Proses {proc.kode_proses} tidak memakai Silo {nama_silo.upper()} — "
                f"yang dipakai: {await _sebut_silo(db, usages)}.")
    elif len(terbuka) == 1:
        target = terbuka[0]
    if target is None:
        if terbuka:
            raise Gudang2Error(
                f"Proses {proc.kode_proses} memakai {await _sebut_silo(db, terbuka)} — "
                "sebutkan mana yang selesai, berikut sisa beratnya.")
        raise Gudang2Error(f"Semua silo proses {proc.kode_proses} sudah ditandai selesai.")
    if sisa_kg is None:
        raise Gudang2Error("Sebutkan sisa berat di silo, mis. `sisa 500 kg`.")
    # Isi silo selama proses = awal + yang DITAMBAHKAN sesudah mulai. Silo
    # yang dipoles boleh diisi lagi (keputusan pemilik 12 September 2026),
    # dan yang ditambahkan itu ikut jadi bahan — bukan sisa.
    masuk = float(target.berat_masuk_kg or 0)
    tersedia = float(target.berat_awal_kg) + masuk
    if float(sisa_kg) > tersedia:
        raise Gudang2Error(
            f"Sisa ({float(sisa_kg):.0f} kg) melebihi isi silo selama proses "
            f"({tersedia:.0f} kg = awal {float(target.berat_awal_kg):.0f}"
            + (f" + ditambah {masuk:.0f}" if masuk else "") + ")."
        )
    target.berat_akhir_kg = sisa_kg
    target.berat_terpakai_kg = max(tersedia - float(sisa_kg), 0.0)
    silo_obj = await db.get(Silo, target.silo_id)
    silo_letter = silo_obj.nama_silo.replace("Silo ", "") if silo_obj else "-"

    semua_selesai = all(u.berat_akhir_kg is not None for u in usages)
    pk_terpakai = sum(float(u.berat_terpakai_kg or 0) for u in usages)
    outputs = await _output_map(db, proc.id)
    beras_total = sum(v for k, v in outputs.items() if k in GRADES)
    rendemen = None

    if semua_selesai:
        proc.status = "selesai"
        proc.waktu_selesai = input_time(tanggal, jam)
        # Jeda yang masih terbuka ikut ditutup: prosesnya sudah tak ada, dan
        # jam tertahan yang terus berjalan akan dipakai menilai shift
        # (temuan QA P-K-17 pada giling; aturan yang sama di sini).
        from app.penggilingan.gudang1.services.jeda import jeda_terbuka
        jeda = await jeda_terbuka(db, "penyosohan", proc.id)
        if jeda is not None:
            jeda.selesai = proc.waktu_selesai
        rendemen = (beras_total / pk_terpakai * 100) if pk_terpakai else None
        await log_activity(
            db, table_name="polishing_process", record_id=proc.id, action="UPDATE",
            changed_by=user.id, field_name="status", new_value="selesai",
        )
        await create_notification(
            db, tipe="verifikasi_penyosohan",
            pesan=(
                f"🟡 Penyosohan {proc.kode_proses} selesai — perlu verifikasi output "
                f"& konfirmasi byproduct. PK terpakai {pk_terpakai:.0f} kg, beras "
                f"{beras_total:.0f} kg"
                + (f" (rendemen {rendemen:.1f}%)" if rendemen is not None
                   else " — rendemen belum bisa dihitung: PK terpakai belum "
                        "tercatat")
            ),
            target_role="admin", prioritas="kuning",
            table_name="polishing_process", record_id=proc.id,
        )
    # ── SATU baris bertanda, ditulis TERAKHIR — inilah yang dibatalkan ──
    #
    # Laporan operator Gudang 2, 28 September 2026: "jika operator tidak sengaja
    # terpencet selesai penyosohan ... hasilnya akan hilang." Pagar di atas
    # menolak penutupan yang belum punya hasil sama sekali; yang ini menjawab
    # separuh keluhan yang lain — penutupan yang sudah berhasil, tetapi salah.
    #
    # Sampai hari ini penutupan mencatat DUA bentuk audit yang berbeda: baris
    # `polishing_process` bila seluruh silo sudah bersisa, `polishing_silo_usage`
    # bila belum. Bentuk pertama TAK BISA dibatalkan walau tabelnya didukung,
    # dan sebabnya bukan kemauan: `record_id`-nya prosesnya, bukan silonya, jadi
    # pembatalan tak punya cara mengetahui SILO MANA yang barusan ditutup. Pada
    # proses dua silo ia akan membuka yang salah.
    #
    # Karena itu barisnya kini SELALU `polishing_silo_usage` dan selalu
    # bertanda. Baris `polishing_process` di atas tetap ditulis — layar audit
    # membacanya sebagai "prosesnya selesai", kejadian yang memang terjadi — dan
    # sengaja ditulis LEBIH DULU: pratinjau undo memilih baris TERBARU, jadi
    # urutan inilah yang menentukan tombol undo menawarkan yang benar.
    await log_activity(
        db, table_name="polishing_silo_usage", record_id=target.id, action="UPDATE",
        changed_by=user.id, field_name="berat_akhir_kg", new_value=f"{sisa_kg:.0f}",
        aksi="tutup_silo_sosoh",
    )
    # Silo yang baru dibebaskan bisa SUDAH berisi PK baru — orang menuangnya
    # selagi prosesnya berjalan. Statusnya diturunkan ulang dari isinya yang
    # sebenarnya, bukan dicap "kosong" karena prosesnya selesai (temuan QA 28
    # September 2026).
    from app.penggilingan.gudang2.service import segarkan_status_silo
    await segarkan_status_silo(db, target.silo_id)
    await db.commit()
    await db.refresh(proc)
    return SelesaiResult(
        proc=proc, selesai=semua_selesai, silo=silo_letter,
        terpakai_silo=float(target.berat_terpakai_kg or 0),
        pk_terpakai_total=pk_terpakai, beras_total=beras_total,
        rendemen=rendemen, outputs=outputs,
    )


# ─────────────────────────── Laporan ───────────────────────────
def _kg(kg: float) -> str:
    return f"{kg:,.0f} kg".replace(",", ".")


async def laporan_penyosohan(db: AsyncSession, kode: str | None = None) -> str:
    if kode:
        proc = await _get_proc(db, kode)
        usages = (
            await db.execute(
                select(PolishingSiloUsage).where(
                    PolishingSiloUsage.polishing_process_id == proc.id
                )
            )
        ).scalars().all()
        terpakai = sum(float(u.berat_terpakai_kg or 0) for u in usages)
        outputs = await _output_map(db, proc.id)
        beras = sum(v for k, v in outputs.items() if k in GRADES)
        lines = [f"⚙️ Penyosohan {proc.kode_proses} — {proc.status}"]
        for u in usages:
            silo = await db.get(Silo, u.silo_id)
            nm = silo.nama_silo.replace("Silo ", "") if silo else "-"
            tambah = (f" + ditambah {_kg(float(u.berat_masuk_kg))}"
                      if float(u.berat_masuk_kg or 0) else "")
            if u.berat_akhir_kg is not None:
                lines.append(
                    f"• Silo {nm}: awal {_kg(float(u.berat_awal_kg))}{tambah} → sisa "
                    f"{_kg(float(u.berat_akhir_kg))} = terpakai {_kg(float(u.berat_terpakai_kg or 0))}"
                )
            else:
                lines.append(f"• Silo {nm}: awal {_kg(float(u.berat_awal_kg))}{tambah} (belum selesai)")
        if outputs:
            lines.append("• Hasil:")
            for jenis in GRADES + BYPRODUCTS:
                if jenis in outputs:
                    lines.append(f"   - {jenis}: {_kg(outputs[jenis])}")
        if terpakai and beras:
            lines.append(f"• Rendemen: {beras / terpakai * 100:.1f}% (beras {_kg(beras)} / PK {_kg(terpakai)})")
        return "\n".join(lines)

    procs = (
        await db.execute(
            select(PolishingProcess).where(PolishingProcess.status == "proses")
            .order_by(PolishingProcess.id)
        )
    ).scalars().all()
    if not procs:
        return "⚙️ Tidak ada penyosohan yang sedang berjalan."
    lines = [f"⚙️ Penyosohan berjalan ({len(procs)}):"]
    for p in procs:
        lines.append(f"• {p.kode_proses}")
    return "\n".join(lines)
