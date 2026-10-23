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
from datetime import datetime, time
from decimal import Decimal
import math

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from hmu_core import ArusProses, JenisProses, StatusProses, buat_produk

from app.database import input_time
from app.models import (
    BrokenKeSilo,
    ByproductStock,
    PolishingOutputLog,
    PolishingProcess,
    PolishingSiloUsage,
    PkTumpukanToSilo,
    Silo,
)
from app.services.activity_log import log_activity
from app.services.codegen import next_polishing_code
from app.services.jasa import (
    JasaError,
    pastikan_satu_pemilik,
    pemilik_silo_g2,
    kunci_silo,
)
from app.penggilingan.gudang2.service import (
    Gudang2Error, get_g2_silo, hitung_stok_silo, komposisi_bahan_silo,
)

# Jenis output yang dikenal.
GRADES = ["sayur", "medium", "medsuper", "premium", "beras_b"]
BYPRODUCTS = ["menir", "broken", "bekatul", "reject"]
_ALL_JENIS = set(GRADES) | set(BYPRODUCTS)
_KODE_ARUS_BAHAN = {
    "pk": "beras_pk", "beras_putih": "beras_olah_ulang",
    "broken": "broken", "menir": "menir", "reject": "reject",
}


def _arus_dari_komposisi(silo: Silo, komposisi: dict[str, float]) -> list[ArusProses]:
    """Satu arus proses untuk setiap bahan nyata, bukan jenis metadata silo."""
    hasil = []
    for jenis, kg in komposisi.items():
        if kg <= 0.01:
            continue
        komoditas = _KODE_ARUS_BAHAN.get(jenis)
        if not komoditas:
            continue
        hasil.append(ArusProses(
            produk=buat_produk(komoditas), berat_kg=Decimal(str(kg)),
            referensi=f"{silo.nama_silo} · {jenis}", lokasi_id=silo.id,
        ))
    return hasil


async def sinkron_bahan_karung(db, proses_id=None):
    """Segarkan proyeksi lintas aplikasi dari sumber karung yang masih hidup.

    Berlaku juga setelah intake final: koreksi W berikutnya tetap mengubah
    bahan, sedangkan hasil dan snapshot penutupan tidak boleh ditulis ulang.
    Proses tanpa sumber karung tidak disentuh, termasuk seluruh PK G1.
    """
    from hmu_core.proses_db import ProsesTerpadu
    from sqlalchemy.orm import selectinload
    from app.services.proses_bersama import perbarui_bahan_proses_bersama
    from app.penggilingan.gudang2.karung import bobot_pemakaian
    ids = select(PolishingSiloUsage.polishing_process_id).where(
        PolishingSiloUsage.bobot_karung_dinamis.is_(True))
    if proses_id is not None:
        ids = ids.where(PolishingSiloUsage.polishing_process_id == proses_id)
    for pid in (await db.scalars(ids.distinct())).all():
        proc = await db.get(PolishingProcess, pid)
        proyeksi = (await db.execute(select(ProsesTerpadu)
            .options(selectinload(ProsesTerpadu.arus)).where(
                ProsesTerpadu.aplikasi == "produksi",
                ProsesTerpadu.tabel_sumber == "polishing_process",
                ProsesTerpadu.id_sumber == str(pid)).with_for_update())).scalar_one_or_none()
        if proyeksi is None:
            continue
        rows = (await db.execute(select(PolishingSiloUsage, Silo).join(Silo)
            .where(PolishingSiloUsage.polishing_process_id == pid)
            .order_by(PolishingSiloUsage.id))).all()
        bobot = bobot_pemakaian([u for u, _ in rows])
        dasar = [[u.id, str(u.berat_awal_kg), str(u.berat_masuk_kg),
                  str(u.berat_akhir_kg), [[m.id, str(m.berat_kg),
                  m.batch.sumber_berat if m.batch else None]
                  for m in u.pemindahan_karung if m.dibatalkan_pada is None]] for u, _ in rows]
        metadata = dict(proyeksi.metadata_domain or {})
        if metadata.get("dasar_bobot_karung") == dasar:
            continue
        # Simpan angka yang pernah diterbitkan sebelum mengganti proyeksinya.
        # Snapshot domain terpakai_lama_kg juga tetap utuh untuk kartu/PDF.
        if proc.waktu_selesai is not None:
            metadata.setdefault("catatan_penutupan", {
                "bahan": [{"komoditas": a.komoditas, "berat_kg": str(a.berat_kg),
                           "lokasi_id": a.lokasi_id} for a in proyeksi.arus if a.arah == "bahan"],
                "berat_pk_terpakai_kg": sum(float(u.terpakai_lama_kg or 0) for u, _ in rows),
                "rendemen_beras_persen": metadata.get("rendemen_beras_persen"),
                "kepastian_bahan": metadata.get("kepastian_bahan"),
            })
        total_silo = {}
        for u, silo in rows:
            total_silo[silo.id] = total_silo.get(silo.id, 0) + float(u.berat_awal_kg) + float(u.berat_masuk_kg)
        arus, komposisi = [], {}
        for sid, total in total_silo.items():
            silo = next(s for _, s in rows if s.id == sid)
            rincian = await komposisi_bahan_silo(db, sid,
                sampai=proc.waktu_selesai or input_time(None),
                kecuali_proses_id=pid, target_kg=total)
            komposisi[silo.nama_silo] = rincian
            arus.extend(_arus_dari_komposisi(silo, rincian))
        await perbarui_bahan_proses_bersama(db, tabel_sumber="polishing_process",
            id_sumber=pid, bahan=tuple(arus))
        metadata.update(dasar_bobot_karung=dasar, komposisi_bahan=komposisi,
            kepastian_bahan=bobot.keadaan, bahan_belum_final=not bobot.pasti)
        if proc.waktu_selesai is not None:
            metadata["berat_pk_terpakai_kg"] = bobot.kg
            hasil = await _output_map(db, pid)
            metadata["rendemen_beras_persen"] = rendemen(
                sum(hasil.get(j, 0) for j in GRADES), bobot.angka()) if bobot.pasti else None
        proyeksi.metadata_domain = metadata
    await db.flush()


async def _ikat_sumber_karung(db, proc, silo, awal):
    """Pisahkan sumber karung dinamis dari bahan tetap pada proses BARU.

    Sisa ukur proses sebelumnya tetap kg. Satu pemindahan hanya diikat ke
    proses pertama yang memakainya; koreksi W tidak boleh memindahkan kg
    dari sisa ukur itu ke proses berikutnya dan menghitung koreksi dua kali.
    """
    sumber = list((await db.execute(select(PkTumpukanToSilo).where(
        PkTumpukanToSilo.silo_id == silo.id,
        PkTumpukanToSilo.jumlah_karung.is_not(None),
        PkTumpukanToSilo.pemakaian_silo_id.is_(None),
    ).with_for_update(of=PkTumpukanToSilo))).scalars().all())
    dinamis = sum((m.berat_kg or Decimal(0) for m in sumber), Decimal(0))
    usage = PolishingSiloUsage(
        polishing_process_id=proc.id, silo_id=silo.id,
        berat_awal_kg=Decimal(str(awal)) - dinamis,
        bobot_karung_dinamis=bool(sumber), pemindahan_karung=sumber)
    db.add(usage)
    await db.flush()
    return usage


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
        await kunci_silo(db, silo.id)
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
                    PolishingSiloUsage.berat_akhir_kg.is_(None),
                )
            )
        ).first()
        if aktif:
            raise Gudang2Error(f"Silo {letter} sedang dipakai penyosohan lain.")
        silos.append(silo)

    # ── SELURUH SILO HARUS SEPEMILIK ──
    #
    # Sampai migrasi 0065 baris di sini MENOLAK silo berisi PK jasa sama sekali:
    # `polishing_process` belum punya `jasa_id`, jadi beras pelanggan akan
    # terbukukan sebagai barang jadi PABRIK. Penolakan itu DICABUT sekarang —
    # prosesnya sudah bisa memikul pemilik — dan diganti penjaga yang sama yang
    # berdiri di giling: boleh beberapa silo, asal sepemilik.
    #
    # Satu proses sosoh = satu rendemen atas seluruh bahannya. Bahan dua pemilik
    # membuat angka itu tak bisa dipertanggungjawabkan ke siapa pun, dan beras
    # yang keluar tak bisa dibagi kembali — tak ada lapisan di dalam mesin.
    pemilik_silo: list[int | None] = []
    for s_ in silos:
        isi = await pemilik_silo_g2(db, s_.id)
        # Himpunan HAMPA berarti silonya kosong — sudah ditolak di atas. Yang
        # sampai sini selalu punya pemilik, walau pemiliknya "pabrik" (None).
        pemilik_silo.extend(isi or [None])
    try:
        pemilik_sosoh = await pastikan_satu_pemilik(db, user=user, jasa_ids=pemilik_silo)
    except JasaError as e:
        raise Gudang2Error(f"❌ {e.args[0]}") from None

    now = input_time(tanggal, jam)
    proc = PolishingProcess(
        kode_proses=await next_polishing_code(db),
        waktu_mulai=now, status="proses", created_by=user.id,
        # Dari sinilah hasilnya mewarisi pemilik — lewat `jasa.pemilik_hasil()`.
        # Dan ini juga jejak ASAL bekatul: bekatulnya beralih milik ke pabrik,
        # tetapi pemilik barang berhak tahu berapa yang keluar dari prosesnya.
        jasa_id=pemilik_sosoh,
    )
    db.add(proc)
    await db.flush()
    total_awal = 0.0
    for silo in silos:
        awal = await hitung_stok_silo(db, silo.id)
        total_awal += awal
        await _ikat_sumber_karung(db, proc, silo, awal)
    from app.services.proses_bersama import bentuk_proses, simpan_proses_bersama
    bahan_bersama_list = []
    rincian_bahan: dict[str, dict[str, float]] = {}
    for silo in silos:
        berat_silo = await hitung_stok_silo(db, silo.id)
        komposisi = await komposisi_bahan_silo(
            db, silo.id, sampai=now, target_kg=berat_silo,
        )
        rincian_bahan[silo.nama_silo] = komposisi
        bahan_bersama_list.extend(_arus_dari_komposisi(silo, komposisi))
    bahan_bersama = tuple(bahan_bersama_list)
    await simpan_proses_bersama(
        db,
        bentuk_proses(
            id=proc.id, kode=proc.kode_proses, jenis=JenisProses.PENYOSOHAN,
            status=StatusProses.BERJALAN, jasa_id=proc.jasa_id,
            waktu_mulai=proc.waktu_mulai, pelaksana_id=proc.created_by,
            bahan=bahan_bersama,
            referensi_asal=tuple(a.referensi for a in bahan_bersama),
        ),
        tabel_sumber="polishing_process", id_sumber=proc.id,
        metadata_domain={"silo_ids": [s.id for s in silos],
                         "komposisi_bahan": rincian_bahan},
    )
    await sinkron_bahan_karung(db, proc.id)
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


@dataclass
class TambahSiloResult:
    proc: PolishingProcess
    silos: list[str]
    berat_awal_total: float


async def tambah_silo_penyosohan(
    db: AsyncSession, *, user, kode: str | None, nama_silos: list[str] | None,
    tanggal=None, jam=None,
) -> TambahSiloResult:
    """Tambahkan silo lain ke penyosohan yang SEDANG BERJALAN — mix bahan.

    Laporan lapangan 7 Oktober 2026: *"jika awalnya hanya menggunakan 1 silo,
    tidak bisa menambahkan silo lainnya sebagai sumber bahan baku. pada
    prakteknya di tengah-tengah proses, silo lainnya juga dipergunakan untuk
    mix bahan baku jika dibutuhkan."* `mulai_penyosohan` menerima BEBERAPA
    silo, tetapi hanya pada SAAT MULAI — sesudah itu daftarnya terkunci.

    Bentuknya SEBANGUN `mulai_penyosohan`: satu baris `PolishingSiloUsage`
    baru per silo yang ditambahkan, `berat_awal_kg` = snapshot stok silo itu
    SEKARANG (bukan 0 — isinya ikut jadi bahan sejak detik ini, sama seperti
    `_silo_content_bobot` menjawab isi silo G1 apa adanya saat giling baru
    dimulai darinya). `rendemen_proses` (jumlah `berat_terpakai_kg` SELURUH
    baris usage) otomatis menjumlah baris baru ini tanpa kode tambahan di
    sana — itulah gunanya bahan dilacak PER BARIS, bukan per proses.
    """
    proc = await _get_proc(db, kode)
    await db.refresh(proc, with_for_update=True)
    if proc.status != "proses":
        raise Gudang2Error(
            f"{proc.kode_proses} sudah {proc.status} — tak bisa menambah silo."
        )
    letters = [s.upper() for s in (nama_silos or []) if s]
    if not letters:
        raise Gudang2Error("Sebutkan silo yang ditambahkan, contoh: `tambah silo B`")

    sudah = set((await db.execute(
        select(PolishingSiloUsage.silo_id)
        .where(PolishingSiloUsage.polishing_process_id == proc.id,
               PolishingSiloUsage.berat_akhir_kg.is_(None))
    )).scalars().all())

    dibebaskan = set((await db.execute(
        select(PolishingSiloUsage.silo_id).where(
            PolishingSiloUsage.polishing_process_id == proc.id,
            PolishingSiloUsage.berat_akhir_kg.is_not(None))
    )).scalars().all())
    silos: list[Silo] = []
    for letter in dict.fromkeys(letters):
        silo = await get_g2_silo(db, letter)
        if silo is None:
            raise Gudang2Error(f"Silo {letter} Gudang 2 tidak ditemukan.")
        await kunci_silo(db, silo.id)
        if silo.id in sudah:
            raise Gudang2Error(
                f"Silo {letter} masih menjadi bahan aktif {proc.kode_proses}."
            )
        stok = await hitung_stok_silo(db, silo.id)
        if stok <= 0 and silo.id not in dibebaskan:
            raise Gudang2Error(f"Silo {letter} kosong — tidak ada yang bisa ditambahkan.")
        aktif = (await db.execute(
            select(PolishingSiloUsage.id)
            .join(PolishingProcess,
                  PolishingProcess.id == PolishingSiloUsage.polishing_process_id)
            .where(PolishingSiloUsage.silo_id == silo.id,
                   PolishingProcess.status == "proses",
                   PolishingSiloUsage.berat_akhir_kg.is_(None))
        )).first()
        if aktif:
            raise Gudang2Error(f"Silo {letter} sedang dipakai penyosohan lain.")

        if stok <= 0:
            # Silo yang sudah dibebaskan boleh disambungkan kembali sebelum
            # diisi. Awalnya nol; input berikutnya masuk ke siklus BARU.
            silos.append(silo)
            continue

        # ── PAGAR: proses TAK BOLEH memakan broken yang ia hasilkan sendiri ──
        #
        # Sebangun pagar `pindah_broken_ke_silo` (lihat CLAUDE.md "Silo
        # broken" dan `tests/pg/test_silo_broken.py::
        # test_proses_tak_boleh_memakan_broken_sendiri`), tapi dari ARAH
        # SEBALIKNYA. Di sana broken yang BARU KELUAR ditolak masuk ke silo
        # yang SEDANG dipakai proses yang sama — tapi urutan itu tak
        # menghadang urutan TERBALIK: broken proses ini dipindah ke silo X
        # SEBELUM silo X jadi bahan proses ini (saat itu X belum jadi sumber,
        # jadi pagar `pindah_broken_ke_silo` diam), lalu BARU SEKARANG `tambah
        # silo` mencoba memakai X sebagai bahan. Fisiknya tetap mustahil:
        # broken yang keluar dari proses P tak bisa disosoh ulang oleh P
        # SENDIRI selagi P masih berjalan — mesinnya sama, dan rendemen P
        # akan menghitung berat yang sama dua kali (sekali sebagai hasil,
        # sekali lagi sebagai bahan). Diperiksa lewat `broken_ke_silo`
        # (bukan "stok silo saat ini"): begitu ada SATU baris yang menunjuk
        # balik ke proses ini, silonya ditolak UTUH — sama konservatifnya
        # dengan `pastikan_satu_pemilik`, yang juga menolak campuran utuh,
        # bukan mencoba memisah bagian yang "aman".
        sendiri = (await db.execute(
            select(BrokenKeSilo.id)
            .join(ByproductStock,
                  ByproductStock.id == BrokenKeSilo.byproduct_stock_id)
            .where(BrokenKeSilo.silo_id == silo.id,
                   ByproductStock.source_type == "polishing",
                   ByproductStock.source_id == proc.id)
        )).first()
        if sendiri:
            raise Gudang2Error(
                f"❌ Silo {letter} berisi broken hasil {proc.kode_proses} "
                "sendiri — tak bisa dipakai lagi sebagai bahan sebelum "
                "prosesnya ditutup."
            )
        from app.models import BerasKeSilo, HasilSampingKeSilo
        for model in (BerasKeSilo, HasilSampingKeSilo):
            asal_sendiri = (await db.execute(select(model.id).where(
                model.silo_id == silo.id,
                model.polishing_process_id == proc.id).limit(1))).first()
            if asal_sendiri:
                raise Gudang2Error(
                    f"Silo {letter} berisi hasil {proc.kode_proses} sendiri — "
                    "tidak bisa menjadi bahan proses yang sama.")
        silos.append(silo)

    # ── Pemilik silo baru HARUS SAMA dengan pemilik proses ini ──
    #
    # Sejajar dengan penjaga di `mulai_penyosohan` — tapi di sini pembandingnya
    # bukan sesama silo baru, melainkan silo baru LAWAN proses yang sudah
    # berjalan (`proc.jasa_id`). Mencampur pemilik di tengah jalan sama
    # berbahayanya dengan mencampurnya di awal: rendemen & hasilnya tak bisa
    # dibagi kembali.
    #
    # ⚠ `proc.jasa_id` BISA berubah di sini (keputusan pemilik 10 Oktober
    # 2026): pelanggan yang sama tapi dua pesanan administratif digabung
    # OTOMATIS — lihat `jasa.pastikan_satu_pemilik`. `proc` tak perlu dimuat
    # ulang: `gabung_jasa()` memutasi lewat ORM, dan `proc` yang sama persis
    # (identity map sesi ini) ikut termutakhirkan bila ia yang diserap.
    pemilik_baru: list[int | None] = [proc.jasa_id]
    for s_ in silos:
        isi = await pemilik_silo_g2(db, s_.id)
        if isi or await hitung_stok_silo(db, s_.id) > 0:
            pemilik_baru.extend(isi or [None])
    try:
        owner = await pastikan_satu_pemilik(db, user=user, jasa_ids=pemilik_baru)
    except JasaError as e:
        raise Gudang2Error(f"❌ {e.args[0]}") from None
    proc.jasa_id = owner

    now = input_time(tanggal, jam)
    total_awal = 0.0
    for silo in silos:
        awal = await hitung_stok_silo(db, silo.id)
        total_awal += awal
        await _ikat_sumber_karung(db, proc, silo, awal)
    semua_bahan = (await db.execute(
        select(PolishingSiloUsage, Silo)
        .join(Silo, Silo.id == PolishingSiloUsage.silo_id)
        .where(PolishingSiloUsage.polishing_process_id == proc.id)
        .order_by(PolishingSiloUsage.id)
    )).all()
    from app.services.proses_bersama import perbarui_bahan_proses_bersama
    rincian_bahan = {}
    arus_bahan = []
    # Satu silo dapat punya beberapa siklus. Hitung komposisinya sekali atas
    # total semua siklus agar bahan baru tidak mengulang komposisi siklus lama.
    total_silo = {}
    for usage, silo in semua_bahan:
        total_silo[silo.id] = total_silo.get(silo.id, 0) + float(
            usage.berat_awal_kg or 0) + float(usage.berat_masuk_kg or 0)
    dilihat = set()
    for usage, silo in semua_bahan:
        if silo.id in dilihat:
            continue
        dilihat.add(silo.id)
        total = total_silo[silo.id]
        komposisi = await komposisi_bahan_silo(
            db, silo.id, sampai=now, kecuali_proses_id=proc.id,
            target_kg=total,
        )
        rincian_silo = rincian_bahan.setdefault(silo.nama_silo, {})
        for jenis, kg in komposisi.items():
            rincian_silo[jenis] = rincian_silo.get(jenis, 0) + kg
        arus_bahan.extend(_arus_dari_komposisi(silo, komposisi))
    await perbarui_bahan_proses_bersama(
        db, tabel_sumber="polishing_process", id_sumber=proc.id,
        bahan=tuple(arus_bahan),
    )
    from hmu_core.proses_db import ProsesTerpadu
    proyeksi = (await db.execute(select(ProsesTerpadu).where(
        ProsesTerpadu.aplikasi == "produksi",
        ProsesTerpadu.tabel_sumber == "polishing_process",
        ProsesTerpadu.id_sumber == str(proc.id),
    ).with_for_update())).scalar_one_or_none()
    if proyeksi is not None:
        proyeksi.metadata_domain = {
            **(proyeksi.metadata_domain or {}), "komposisi_bahan": rincian_bahan,
        }
    await log_activity(
        db, table_name="polishing_process", record_id=proc.id, action="UPDATE",
        changed_by=user.id, field_name="silo",
        new_value=f"{proc.kode_proses} + silo {'+'.join(letters)} ({total_awal:.0f}kg)",
    )
    await db.commit()
    await db.refresh(proc)
    return TambahSiloResult(
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
    """Catat total aktual per jenis tanpa mengubah log tambahan yang sudah ada.

    Keputusan pemilik 18 Oktober 2026: input 500 sesudah 300 berarti total
    500 kg. Simpan hanya selisih 200 agar stok, riwayat, dan pembatalan tetap
    membaca log tambahan. `berat_kg` menjaga kompatibilitas lembar lama yang
    masih mengirim tambahan; kedua bentuk tidak boleh dikirim bersamaan.
    """
    if not jenis or jenis.lower() not in _ALL_JENIS:
        raise Gudang2Error(
            "Jenis hasil harus salah satu: " + ", ".join(sorted(_ALL_JENIS)) + "."
        )
    jenis = jenis.lower()
    if berat_kg is not None and berat_kumulatif is not None:
        raise Gudang2Error("Kirim total hasil atau tambahan, jangan keduanya.")
    berat = berat_kg if berat_kg is not None else berat_kumulatif
    if berat is None:
        raise Gudang2Error(
            "Isi total hasil sampai sekarang dalam kg.")
    if float(berat) <= 0:
        raise Gudang2Error(
            "Berat hasil harus lebih dari 0. Yang keliru dibatalkan lewat "
            "'Batalkan input terakhir', bukan dicatat sebagai angka minus.")
    proc = await _get_proc(db, kode)
    # Serialkan pembacaan total dan penambahan selisih. Dua kiriman total
    # 500 yang bersamaan harus tetap berakhir 500, bukan masing-masing
    # menghitung tambahan 200 dari total lama 300.
    proc = (await db.execute(
        select(PolishingProcess).where(PolishingProcess.id == proc.id)
        .with_for_update().execution_options(populate_existing=True)
    )).scalars().one()
    if proc.status == "selesai":
        raise Gudang2Error(f"Proses {proc.kode_proses} sudah selesai.")
    if berat_kumulatif is not None:
        sebelumnya = await _total_output(db, proc.id, jenis)
        berat = float(berat_kumulatif) - sebelumnya
        if berat < -0.000001:
            raise Gudang2Error(
                f"Total {jenis} sudah {sebelumnya:g} kg. Total baru tidak boleh "
                "lebih kecil; gunakan pembatalan atau koreksi hasil.")
        if abs(berat) <= 0.000001:
            await db.commit()
            return OutputResult(proc=proc, jenis=jenis,
                                berat_kumulatif=sebelumnya, berat_kg=0)
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


async def alasan_koreksi_hasil(db: AsyncSession, process_id: int) -> str | None:
    """Koreksi output hanya sebelum hasil dipakai proses berikutnya."""
    from app.penggilingan.gudang2.models import BerasKeSilo, HasilSampingKeSilo
    from app.penggilingan.inventory.models import ByproductStock, FinishedGoodsStock

    pemeriksaan = (
        (select(FinishedGoodsStock.id).where(
            FinishedGoodsStock.source_type == "polishing",
            FinishedGoodsStock.source_id == process_id),
         "hasilnya sudah dikemas"),
        (select(ByproductStock.id).where(
            ByproductStock.source_type == "polishing",
            ByproductStock.source_id == process_id),
         "hasil sampingnya sudah dicatat sebagai stok"),
        (select(BerasKeSilo.id).where(
            BerasKeSilo.polishing_process_id == process_id),
         "berasnya sudah dipindahkan ke silo lain"),
        (select(HasilSampingKeSilo.id).where(
            HasilSampingKeSilo.polishing_process_id == process_id),
         "hasil sampingnya sudah dipindahkan ke silo"),
    )
    for q, pesan in pemeriksaan:
        if (await db.execute(q.limit(1))).first():
            return f"Koreksi ditahan: {pesan}. Batalkan atau sesuaikan catatan turunannya dulu."
    return None


async def koreksi_hasil_sosoh(
    db: AsyncSession, *, user, process_id: int,
    perubahan: dict[str, float], dasar: dict[str, float], alasan: str,
) -> PolishingProcess:
    """Ubah catatan hasil selesai dengan audit dan sinkronkan neraca lintas-app.

    Hasil yang sudah dikemas atau dipindah tidak boleh dikoreksi dari sini:
    stok lanjutannya harus dibalik lebih dulu agar angka asal dan turunannya
    tidak berpisah.
    """
    proc = (await db.execute(
        select(PolishingProcess).where(PolishingProcess.id == process_id)
        .with_for_update()
    )).scalar_one_or_none()
    if proc is None or proc.status != "selesai":
        raise Gudang2Error("Koreksi hanya tersedia untuk proses sosoh yang selesai.")
    penghalang = await alasan_koreksi_hasil(db, proc.id)
    if penghalang:
        raise Gudang2Error(penghalang)
    alasan = (alasan or "").strip()
    if not alasan:
        raise Gudang2Error("Tuliskan alasan koreksi hasil.")
    nilai_berat = tuple(float(v) for v in perubahan.values())
    if any(not math.isfinite(v) or v < 0 for v in nilai_berat):
        raise Gudang2Error("Berat hasil harus berupa angka yang valid dan tidak negatif.")
    if set(perubahan) != _ALL_JENIS or set(dasar) != _ALL_JENIS:
        raise Gudang2Error("Ada jenis hasil yang tidak dikenal.")

    baris = (await db.execute(
        select(PolishingOutputLog)
        .where(PolishingOutputLog.polishing_process_id == proc.id)
        .order_by(PolishingOutputLog.id)
        .with_for_update()
    )).scalars().all()
    berubah = False
    per_jenis: dict[str, list[PolishingOutputLog]] = {jenis: [] for jenis in _ALL_JENIS}
    for row in baris:
        if row.jenis in per_jenis:
            per_jenis[row.jenis].append(row)

    if any(not math.isfinite(float(v)) or float(v) < 0 for v in dasar.values()):
        raise Gudang2Error("Data hasil di halaman tidak valid. Muat ulang halaman.")
    if any(abs(round(sum(float(row.berat_kg) for row in per_jenis[jenis]), 2)
                   - round(float(dasar[jenis]), 2)) >= 0.005
           for jenis in _ALL_JENIS):
        raise Gudang2Error(
            "Catatan hasil berubah sejak halaman dibuka. Muat ulang lalu coba lagi.")

    for jenis, nilai in perubahan.items():
        target = round(float(nilai), 2)
        rows = per_jenis[jenis]
        total = sum(float(row.berat_kg) for row in rows)
        delta = round(target - total, 2)
        if abs(delta) < 0.005:
            continue
        if not rows and target > 0:
            row = PolishingOutputLog(
                polishing_process_id=proc.id, jenis=jenis, berat_kg=target,
                waktu_update=proc.waktu_selesai, input_by=user.id,
            )
            db.add(row)
            await db.flush()
            await log_activity(
                db, table_name="polishing_output_logs", record_id=row.id,
                action="INSERT", changed_by=user.id,
                new_value=f"{jenis} {target:.2f} kg · koreksi: {alasan}",
                alasan=alasan, aksi="koreksi_hasil_sosoh",
            )
            berubah = True
            continue

        # Pertahankan rincian prosesan yang sudah ada. Tambah selisih ke
        # catatan pertama, atau kurangi dari catatan terakhir ke awal tanpa
        # membuat nilai negatif.
        sisa = abs(delta)
        sasaran = rows if delta > 0 else list(reversed(rows))
        for row in sasaran:
            lama = float(row.berat_kg)
            if delta > 0:
                baru = round(lama + sisa, 2)
                sisa = 0
            else:
                pengurangan = min(lama, sisa)
                baru = round(lama - pengurangan, 2)
                sisa = round(sisa - pengurangan, 2)
            if abs(baru - lama) < 0.005:
                continue
            row.berat_kg = baru
            await log_activity(
                db, table_name="polishing_output_logs", record_id=row.id,
                action="UPDATE", changed_by=user.id, field_name="berat_kg",
                old_value=f"{lama:.2f}", new_value=f"{baru:.2f}", alasan=alasan,
                aksi="koreksi_hasil_sosoh",
            )
            berubah = True
            if sisa < 0.005:
                break
    if not berubah:
        raise Gudang2Error("Tidak ada perubahan hasil yang dimasukkan.")

    outputs = await _output_map(db, proc.id)
    rendemen = await rendemen_proses(db, proc.id)
    pk_terpakai = float((await db.execute(
        select(func.coalesce(func.sum(PolishingSiloUsage.berat_terpakai_kg), 0))
        .where(PolishingSiloUsage.polishing_process_id == proc.id)
    )).scalar_one())
    komoditas_hasil = {
        "sayur": ("beras_putih", {"kualitas": "sayur"}),
        "medium": ("beras_putih", {"kualitas": "medium"}),
        "medsuper": ("beras_putih", {"kualitas": "medsuper"}),
        "premium": ("beras_putih", {"kualitas": "premium"}),
        "beras_b": ("beras_olah_ulang", {}),
        "broken": ("broken", {}), "menir": ("menir", {}),
        "bekatul": ("bekatul", {}), "reject": ("reject", {}),
    }
    arus_hasil = tuple(
        ArusProses(
            produk=buat_produk(komoditas_hasil[jenis][0],
                               **komoditas_hasil[jenis][1]),
            berat_kg=Decimal(str(berat)), referensi=proc.kode_proses,
        )
        for jenis, berat in outputs.items()
        if berat > 0 and jenis in komoditas_hasil
    )
    from app.services.proses_bersama import tutup_proses_bersama
    await tutup_proses_bersama(
        db, tabel_sumber="polishing_process", id_sumber=proc.id,
        waktu_selesai=proc.waktu_selesai, hasil=arus_hasil,
        metadata_tambahan={"rendemen_beras_persen": rendemen,
                           "berat_pk_terpakai_kg": pk_terpakai},
    )
    await db.commit()
    return proc


# ─────────────────────────── Selesai + rendemen ───────────────────────────
async def _output_map(db: AsyncSession, proc_id: int) -> dict[str, float]:
    """Output terbaru per jenis (kumulatif) — lewat `stok.output_sosoh`.

    Satu corong untuk tiga pembaca: pembanding di sini, layar Stok Produk, dan
    laporan Riwayat produksi. Lihat catatan di sana.
    """
    from app.services.stok import output_sosoh

    return await output_sosoh(db, proc_id)


def beras_dari_output(outputs: dict[str, float]) -> float:
    """Berapa kg dari sebuah peta hasil yang terhitung BERAS.

    Pembandingnya `GRADES` — termasuk `beras_b` (beras olah ulang), sebab ia
    memang keluar dari mesin sebagai beras. Jangan menggantinya dengan
    `stok.GRADES_BERAS`, yang SENGAJA tak memuat `beras_b` untuk urusan lain
    (pembagian blok di layar Stok Produk). Dua daftar itu berbeda bukan karena
    salah satunya lupa — dan menukarnya di sini menggeser penyebut rendemen
    seluruh pabrik tanpa satu pun galat.
    """
    return sum(v for k, v in outputs.items() if k in GRADES)


def rendemen(beras_kg: float, pk_terpakai_kg: float) -> float | None:
    """Rendemen = beras / PK terpakai, dalam persen. None bila tak bisa dihitung.

    RUMUSNYA MURNI, tanpa basis data — supaya pembaca yang sudah memegang
    kedua angkanya (kartu riwayat, yang membacanya borongan) memakai rumus
    yang SAMA PERSIS dengan yang memegang `proc_id` saja. Angka ini menilai
    pekerjaan orang; dua rumus untuk satu angka berarti dua penilaian.

    Penyebutnya PK TERPAKAI, bukan PK masuk: yang tersisa di silo belum
    disosoh, dan memasukkannya ke penyebut membuat rendemen tiap proses
    terbaca lebih rendah daripada yang sebenarnya.
    """
    if not pk_terpakai_kg:
        return None
    return beras_kg / pk_terpakai_kg * 100


async def rendemen_proses(db: AsyncSession, proc_id: int) -> float | None:
    """Rendemen satu penyosohan, atau None bila belum bisa dihitung.

    Dibaca penutupan (kalimat untuk operator & kabar untuk Admin) dan kartu
    "penyosohan selesai" di layar operator. Keduanya cuma punya `proc_id`;
    yang sudah memegang angkanya memakai `rendemen()` langsung.
    """
    usages = (await db.execute(
        select(PolishingSiloUsage)
        .where(PolishingSiloUsage.polishing_process_id == proc_id)
    )).scalars().all()
    from app.penggilingan.gudang2.karung import bobot_pemakaian
    if not bobot_pemakaian(usages).pasti:
        return None
    pk_terpakai = sum(float(u.berat_terpakai_kg or 0) for u in usages)
    return rendemen(beras_dari_output(await _output_map(db, proc_id)), pk_terpakai)


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
    sisa_kg: float | None, tanggal=None, jam=None, dasar: str | None = None,
) -> SelesaiResult:
    """Bebaskan satu pemakaian silo; mesin dan pencatatan hasil tetap berjalan."""
    proc = await _get_proc(db, kode)
    await db.refresh(proc, with_for_update=True)
    if proc.status == "selesai":
        raise Gudang2Error(f"Proses {proc.kode_proses} sudah selesai.")

    silo_ids = (await db.scalars(select(PolishingSiloUsage.silo_id).where(
        PolishingSiloUsage.polishing_process_id == proc.id))).all()
    for sid in sorted(set(silo_ids)):
        await kunci_silo(db, sid)
    usages = (
        await db.execute(
            select(PolishingSiloUsage).where(
                PolishingSiloUsage.polishing_process_id == proc.id
            ).with_for_update().execution_options(populate_existing=True)
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
        raise Gudang2Error("Isi sisa berat di silo. Isi 0 jika silo sudah kosong.")
    if not math.isfinite(float(sisa_kg)) or float(sisa_kg) < 0:
        raise Gudang2Error("Sisa harus angka nol atau lebih.")
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
    if dasar is not None:
        from app.services.penyelesaian_proses import ringkasan_bebaskan
        try:
            kini = await ringkasan_bebaskan(db, jenis="sosoh", kode=kode, silo=nama_silo or "", sisa=float(sisa_kg))
        except ValueError as e:
            raise Gudang2Error(str(e)) from e
        if kini["dasar"] != dasar:
            raise Gudang2Error("Isi atau pemakaian silo berubah sejak diperiksa. Periksa ulang sisanya.")

    target.berat_akhir_kg = sisa_kg
    target.berat_terpakai_kg = max(tersedia - float(sisa_kg), 0.0)
    silo_obj = await db.get(Silo, target.silo_id)
    silo_letter = silo_obj.nama_silo.replace("Silo ", "") if silo_obj else "-"

    pk_terpakai = sum(float(u.berat_terpakai_kg or 0) for u in usages)
    outputs = await _output_map(db, proc.id)
    await log_activity(
        db, table_name="polishing_silo_usage", record_id=target.id, action="UPDATE",
        changed_by=user.id, field_name="berat_akhir_kg", new_value=f"{sisa_kg:g}",
        aksi="tutup_silo_sosoh",
    )
    from app.penggilingan.gudang2.service import segarkan_status_silo
    await segarkan_status_silo(db, target.silo_id)
    await db.commit()
    return SelesaiResult(proc=proc, selesai=False, silo=silo_letter,
        terpakai_silo=float(target.berat_terpakai_kg or 0),
        pk_terpakai_total=pk_terpakai,
        beras_total=sum(outputs.get(j, 0) for j in GRADES),
        rendemen=None, outputs=outputs)


async def akhiri_penyosohan(db: AsyncSession, *, user, kode: str,
                           dasar: str | None = None, tanggal=None, jam=None) -> SelesaiResult:
    """Pernyataan eksplisit operator: seluruh proses di mesin benar-benar selesai.

    Semua silo boleh sudah kosong jauh sebelum langkah ini. Bahan yang masih
    berada di mesin bukan isi silo dan tidak boleh menutup hasil secara otomatis.
    """
    proc = await _get_proc(db, kode)
    await db.refresh(proc, with_for_update=True)
    if proc.status != "proses":
        raise Gudang2Error(f"Proses {kode} sudah selesai.")
    usages = (await db.scalars(select(PolishingSiloUsage).where(
        PolishingSiloUsage.polishing_process_id == proc.id).with_for_update()
        .execution_options(populate_existing=True))).all()
    if not usages or any(u.berat_akhir_kg is None for u in usages):
        raise Gudang2Error("Bebaskan setiap silo dan isi sisanya dulu. Proses tetap berjalan.")
    outputs = await _output_map(db, proc.id)
    if not outputs:
        raise Gudang2Error(f"{kode} belum punya catatan hasil. Catat hasil penyosohan dulu.")
    if dasar is not None:
        from app.services.penyelesaian_proses import ringkasan_selesai
        kini = await ringkasan_selesai(db, jenis="sosoh", kode=kode)
        if dasar != kini["dasar"]:
            raise Gudang2Error("Data proses berubah sejak diperiksa. Periksa ulang sebelum menyelesaikan.")
    pk_terpakai = sum(float(u.berat_terpakai_kg or 0) for u in usages)
    if sum(outputs.values()) > pk_terpakai + 0.001:
        raise Gudang2Error("Total hasil melebihi bahan yang benar-benar terpakai setelah sisa silo dikurangkan. Periksa hasil dan sisa yang dicatat.")
    selesai_pada = input_time(tanggal, jam)
    # Jeda yang masih terbuka ikut ditutup: prosesnya sudah tak ada, dan
    # jam tertahan yang terus berjalan akan dipakai menilai shift
    # (temuan QA P-K-17 pada giling; aturan yang sama di sini).
    from app.penggilingan.gudang1.services.jeda import tutup_bersama_proses, JedaError
    try:
        await tutup_bersama_proses(db, jenis="penyosohan", obj=proc,
                                  saat=selesai_pada, user=user)
    except JedaError as e:
        raise Gudang2Error(str(e)) from e
    await sinkron_bahan_karung(db, proc.id)
    proc.status = "selesai"
    proc.waktu_selesai = selesai_pada
    # Lewat `rendemen_proses`, bukan dihitung di sini: angka ini juga
    # dibaca kartu "penyosohan selesai", dan dua rumus atas satu angka
    # akan berselisih tanpa satu pun pesan galat.
    rendemen = await rendemen_proses(db, proc.id)
    from app.services.proses_bersama import tutup_proses_bersama
    komoditas_hasil = {
        "sayur": ("beras_putih", {"kualitas": "sayur"}),
        "medium": ("beras_putih", {"kualitas": "medium"}),
        "medsuper": ("beras_putih", {"kualitas": "medsuper"}),
        "premium": ("beras_putih", {"kualitas": "premium"}),
        "beras_b": ("beras_olah_ulang", {}),
        "broken": ("broken", {}), "menir": ("menir", {}),
        "bekatul": ("bekatul", {}), "reject": ("reject", {}),
    }
    arus_hasil = tuple(
        ArusProses(
            produk=buat_produk(komoditas_hasil[jenis_hasil][0],
                               **komoditas_hasil[jenis_hasil][1]),
            berat_kg=Decimal(str(berat_hasil)),
            referensi=proc.kode_proses,
        )
        for jenis_hasil, berat_hasil in outputs.items()
        if berat_hasil > 0 and jenis_hasil in komoditas_hasil
    )
    await tutup_proses_bersama(
        db, tabel_sumber="polishing_process", id_sumber=proc.id,
        waktu_selesai=proc.waktu_selesai, hasil=arus_hasil,
        metadata_tambahan={"rendemen_beras_persen": rendemen,
                           "berat_pk_terpakai_kg": pk_terpakai},
    )
    await sinkron_bahan_karung(db, proc.id)
    await log_activity(
        db, table_name="polishing_process", record_id=proc.id, action="UPDATE",
        changed_by=user.id, field_name="status", new_value="selesai",
        aksi="akhiri_penyosohan",
    )
    await db.commit()
    return SelesaiResult(proc=proc, selesai=True, silo="-", terpakai_silo=0,
        pk_terpakai_total=pk_terpakai,
        beras_total=sum(outputs.get(j, 0) for j in GRADES),
        rendemen=rendemen, outputs=outputs)


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
        from app.penggilingan.gudang2.karung import bobot_pemakaian
        bobot = bobot_pemakaian(usages)
        if not bobot.pasti:
            lines.append(f"• Bahan: {bobot.teks()} · bobot truk belum final; rendemen belum dapat dipastikan.")
        if bobot.pasti and terpakai and beras:
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


# ══════════════════ RIWAYAT SOSOH & NERACA BOBOTNYA ══════════════════
#
# Keputusan pemilik 2 Oktober 2026: *"berisi kartu proses sosoh yang selesai
# berikut seluruh informasinya dan hasilnya. terkhusus berapa persen yang jadi
# beras, berapa persen broken, berapa persen menir, berapa persen bekatul, lalu
# berapa persen susut debu/bobot."*
#
# Dan rumus susutnya ia sebut sendiri, lengkap dengan contohnya: *"jika yang
# disosoh bahan bakunya termasuk campurannya adalah 10 ton lalu dari beras dan
# semua produk samping hasilnya totalnya hanya 9900 kg. maka persentase susut
# adalah 100 dibagi 10000"* — 1%.
#
#     bahan  = PK TERPAKAI, seluruh silo (awal + ditambah − sisa)
#     keluar = beras + SELURUH hasil samping
#     susut  = bahan − keluar
#     persen = bagian / bahan × 100
#
# ⚠ "termasuk campurannya" itu yang membuat penyebutnya `berat_terpakai_kg` dan
# bukan `berat_awal_kg`: silo yang sedang dipoles boleh diisi lagi (keputusan
# pemilik 12 September 2026), dan PK yang ditambah di tengah proses ikut jadi
# bahan baku. Memakai berat awal akan membuat susut terbaca jauh lebih besar
# daripada yang sebenarnya — dan angka susut dipakai menilai mesin dan orang.
#
# ⚠ SELURUH persennya berpenyebut SAMA, dan itu bukan kebetulan: ia yang
# membuat jumlahnya TEPAT 100%. Identitas itu sendiri yang menjaga kartunya —
# satu entri hasil yang salah ketik langsung menggeser susutnya, dan susut yang
# bergeser terbaca di kartu tanpa perlu seseorang mencurigainya lebih dulu.

#: Hasil samping yang pemilik minta disebut persennya SATU PER SATU, dalam
#: urutan ini. `reject` tak ia sebut — tetapi ia tetap ikut DIJUMLAH (ia
#: barang yang sungguh keluar dari mesin), dan disebut sebagai barisnya sendiri
#: hanya bila memang ada. Membuangnya dari jumlah akan memindahkan beratnya ke
#: "susut", dan susut adalah angka yang dipakai menuduh mesin bocor.
SAMPING_DISEBUT = ("broken", "menir", "bekatul")


@dataclass(frozen=True)
class Bagian:
    """Satu baris neraca: apa, berapa kg, berapa persen dari bahan bakunya."""

    jenis: str
    nama: str
    kg: float
    #: Persen dari PK terpakai. `None` bila bahan bakunya nol — dan itu BUKAN
    #: 0%: nol persen adalah pernyataan bahwa tak ada yang jadi, sedangkan yang
    #: benar adalah "tak bisa dihitung". Kartunya menyebut bedanya.
    persen: float | None


@dataclass(frozen=True)
class NeracaSosoh:
    """Ke mana perginya bahan baku satu penyosohan — kg dan persen.

    Dipisah dari kartunya supaya ia bisa diuji sendiri atas angka telanjang,
    tanpa basis data: rumus yang hanya bisa diuji lewat layar adalah rumus yang
    tak pernah diuji pada kasus tepinya.
    """

    bahan_kg: float
    beras: Bagian
    samping: tuple[Bagian, ...]
    susut: Bagian

    @property
    def keluar_kg(self) -> float:
        """Seluruh yang keluar dari mesin — beras + hasil samping."""
        return self.beras.kg + sum(b.kg for b in self.samping)

    @property
    def bisa_dihitung(self) -> bool:
        return self.bahan_kg > 0

    @property
    def timpang(self) -> bool:
        """Hasilnya MELEBIHI bahan bakunya — mustahil secara fisik.

        Dilaporkan, tidak disembunyikan dan tidak dipangkas jadi nol: susut
        negatif selalu berarti salah catat (hasil dicatat ke proses yang keliru,
        atau satuan tertukar), dan itu kabar yang seseorang harus tindak
        lanjuti. Susut yang dipangkas jadi 0% membuat kesalahannya tak pernah
        terbaca di mana pun.

        Tak ada ambang "susut terlalu besar" di sini. Pemilik belum menetapkan
        angkanya, dan pagar yang ditebak sendiri akan menuduh mesin yang sehat.
        """
        return self.bisa_dihitung and self.susut.kg < -0.5


def neraca_sosoh(pk_terpakai_kg: float, outputs: dict[str, float]) -> NeracaSosoh:
    """Neraca bobot satu penyosohan. MURNI — tanpa basis data, bisa diuji sendiri.

    `outputs` = peta jenis → kg seperti yang diberi `stok.output_sosoh`.
    """
    from app.services.stok import nama_produk

    bahan = float(pk_terpakai_kg or 0)

    def bagian(jenis: str, nama: str, kg: float) -> Bagian:
        return Bagian(jenis=jenis, nama=nama, kg=kg,
                      persen=(kg / bahan * 100) if bahan else None)

    beras_kg = beras_dari_output(outputs)
    # Urutannya: yang pemilik sebut lebih dulu, lalu samping lain yang memang
    # ada. `BYPRODUCTS` dipakai sebagai daftar sisanya supaya jenis samping
    # yang kelak ditambahkan ikut terjumlah tanpa menyunting berkas ini —
    # kalau tidak, ia akan mengalir ke "susut" diam-diam.
    sisa_jenis = [j for j in BYPRODUCTS if j not in SAMPING_DISEBUT]
    samping = []
    for jenis in (*SAMPING_DISEBUT, *sisa_jenis):
        kg = float(outputs.get(jenis, 0) or 0)
        # Yang pemilik minta disebut TETAP tampil walau nol — "bekatul 0%"
        # adalah kabar (mesinnya tak mengeluarkan bekatul? belum dicatat?),
        # sedangkan baris yang hilang cuma membuat orang mengira tak ditanyakan.
        if jenis in SAMPING_DISEBUT or kg:
            samping.append(bagian(jenis, nama_produk(jenis), kg))

    keluar = beras_kg + sum(b.kg for b in samping)
    return NeracaSosoh(
        bahan_kg=bahan,
        beras=bagian("beras", "Beras", beras_kg),
        samping=tuple(samping),
        susut=bagian("susut", "Susut debu & bobot", bahan - keluar),
    )


@dataclass(frozen=True)
class PemakaianSilo:
    """Satu silo dalam satu penyosohan — dari mana angka bahan bakunya datang."""

    nama: str
    awal_kg: float
    masuk_kg: float
    sisa_kg: float | None
    terpakai_kg: float
    #: Rincian asal lot PK / penambahan broken — (judul, kg) — sebangun kartu
    #: "Sedang berjalan" (keluhan pemilik 11 Oktober 2026: riwayat berhenti
    #: di tingkat silo, tak merinci lot/pemasoknya). Diisi borongan lewat
    #: `berjalan._isian_silo_banyak`, bukan per silo — lihat `riwayat_sosoh`.
    asal: tuple[tuple[str, str], ...] = ()
    #: Berapa baris asal yang tak ditampilkan karena `BATAS_ASAL`.
    asal_lebih: int = 0


@dataclass(frozen=True)
class KartuSosoh:
    """Satu proses sosoh yang SUDAH SELESAI, berikut seluruh keterangannya."""

    id: int
    kode: str
    mulai: datetime
    selesai: datetime | None
    lama: str
    oleh: str
    jasa: bool
    kode_jasa: str | None
    nama_pemilik: str | None
    #: "JAS-2610-001 Pak Budi" bila bahannya barang titipan; None = milik pabrik.
    pemilik: str | None
    silo: tuple[PemakaianSilo, ...]
    neraca: NeracaSosoh
    beras: tuple[Bagian, ...]
    #: Spek yang dijalankan selama proses ini, urut kemunculannya.
    spek: tuple[str, ...]
    neraca_tercatat: NeracaSosoh | None = None
    bahan_pasti: bool = True
    bahan_teks: str = ""

    @property
    def rendemen(self) -> float | None:
        """Lewat rumus bersama — BUKAN `neraca.beras.persen`.

        Keduanya hari ini menghasilkan angka yang sama persis, dan justru itu
        sebabnya: dua jalan yang kebetulan sepakat akan berselisih begitu salah
        satunya disentuh, dan yang berselisih di sini adalah angka yang menilai
        pekerjaan orang. Rendemen punya satu rumah (`rendemen()`).
        """
        return rendemen(self.neraca.beras.kg, self.neraca.bahan_kg) if self.bahan_pasti else None


async def riwayat_sosoh(db: AsyncSession, *, batas: int = 30,
                        sebelum: int | None = None,
                        process_id: int | None = None) -> tuple[list[KartuSosoh], bool]:
    """Kartu penyosohan SELESAI, terbaru lebih dulu. → (kartu, ada lanjutannya)

    Hanya yang selesai, dan itu keputusan pemilik ("kartu proses sosoh yang
    selesai"). Yang masih berjalan sudah punya pintunya sendiri di `/berjalan`,
    dan angkanya di sana memang belum final — mendaftarnya di sini berarti
    halaman riwayat yang separuh isinya masih akan berubah, lalu persennya
    dibaca sebagai hasil akhir.

    ⚠ JUMLAH KUERINYA TETAP, berapa pun banyak kartunya — bukan satu angka
    tetap, tapi TAK PERNAH tumbuh bersama jumlah kartu. Dasarnya enam (tujuh
    bila ada kartu jasa, sebab `nama_pemilik_banyak` tak bertanya apa-apa
    saat tak ada pesanan yang perlu dinamai); asal lot (`_isian_silo_banyak`,
    11 Oktober 2026) menambah sampai tujuh lagi — langsung+tumpukan PK,
    penambahan broken, pengurang, dua label (lot giling/beli luar), dan
    pemiliknya — masing-masing SATU kueri borongan `IN (...)` atas SELURUH
    kartu di halaman, bukan satu per kartu. Layar Stok Produk pernah
    mengeluarkan satu kueri per penyosohan dan halamannya 1,77 detik pada
    500 proses (temuan QA P-S-02); halaman ini membaca hal yang sama —
    pemakaian silo, hasil, spek, orangnya, pemiliknya, asal lotnya — dan
    akan menumpuk dengan cara yang sama kalau sampai lupa.

    Dijaga sebagai PERBANDINGAN, bukan atas satu langit-langit: satu kartu
    dibanding enam kartu, dan angkanya wajib sama persis
    (`tests/pg/test_riwayat_sosoh.py`). Langit-langit masih bisa dilewati oleh
    N+1 yang kebetulan kecil; selisih yang tumbuh bersama jumlah kartu tidak.

    `sebelum` = id proses terakhir yang sudah digambar (kursor), BUKAN nomor
    halaman: riwayat bertambah di ujung yang sama dengan arah bacanya, dan
    nomor halaman akan menggeser satu kartu tiap kali ada sosoh baru ditutup —
    kartu yang terlewat justru karena orang menekan "muat lagi".
    """
    from app.models import Jasa, Pelanggan, User
    from app.services.berjalan import lama_kata
    from app.services.stok import nama_produk, output_sosoh_banyak

    # 1) Prosesnya. Diambil `batas + 1` untuk mengetahui ada lanjutannya atau
    #    tidak tanpa satu kueri hitung tersendiri.
    q = (select(PolishingProcess)
         .where(PolishingProcess.status == "selesai")
         .order_by(PolishingProcess.id.desc())
         .limit(batas + 1))
    if process_id is not None:
        q = q.where(PolishingProcess.id == process_id)
    if sebelum:
        q = q.where(PolishingProcess.id < sebelum)
    procs = (await db.execute(q)).scalars().all()
    lagi = len(procs) > batas
    procs = procs[:batas]
    if not procs:
        return [], False
    ids = [p.id for p in procs]

    # 2) Pemakaian silonya, 3) nama silonya, 4) hasilnya, 5) spek, 6) orangnya,
    #    7) pemilik barangnya — semuanya BORONGAN.
    usages = (await db.execute(
        select(PolishingSiloUsage)
        .where(PolishingSiloUsage.polishing_process_id.in_(ids))
        .order_by(PolishingSiloUsage.id)
    )).scalars().all()
    # Nama DAN jenis isi satu tarikan — `jenis_isi` menentukan sumber asal
    # lotnya (PK lewat intake, broken lewat `broken_ke_silo`), dibaca
    # `_isian_silo_banyak` di bawah.
    silo_info = {i: (n, j) for i, n, j in (await db.execute(
        select(Silo.id, Silo.nama_silo, Silo.jenis_isi)
        .where(Silo.id.in_({u.silo_id for u in usages} or {0})))).all()}
    nama_silo = {i: n for i, (n, _) in silo_info.items()}
    hasil = await output_sosoh_banyak(db, ids)
    # Spek dibaca dari log hasilnya — satu baris per (proses, spek), bukan per
    # entri: satu proses bisa punya dua puluh entri dengan spek yang sama.
    spek_baris = (await db.execute(
        select(PolishingOutputLog.polishing_process_id, PolishingOutputLog.spek)
        .where(PolishingOutputLog.polishing_process_id.in_(ids),
               PolishingOutputLog.spek.isnot(None))
        .group_by(PolishingOutputLog.polishing_process_id, PolishingOutputLog.spek)
        .order_by(PolishingOutputLog.polishing_process_id,
                  PolishingOutputLog.spek))).all()
    nama_orang = {i: n for i, n in (await db.execute(
        select(User.id, User.nama)
        .where(User.id.in_({p.created_by for p in procs} or {0})))).all()}
    jasa_ids = {p.jasa_id for p in procs if p.jasa_id is not None}
    pemilik = {
        jid: (kode, nama) for jid, kode, nama in (await db.execute(
            select(Jasa.id, Jasa.kode, Pelanggan.nama_pelanggan)
            .join(Pelanggan, Pelanggan.id == Jasa.pelanggan_id)
            .where(Jasa.id.in_(jasa_ids or {0}))
        )).all()
    }

    per_proses: dict[int, list] = {}
    for u in usages:
        per_proses.setdefault(u.polishing_process_id, []).append(u)
    spek_per: dict[int, list[str]] = {}
    for pid, sp in spek_baris:
        spek_per.setdefault(pid, []).append(sp)

    # 8) Asal lot PK / penambahan broken — BORONGAN atas seluruh kartu×silo
    # sekaligus (keluhan pemilik 11 Oktober 2026: riwayat berhenti di
    # tingkat silo, tak merinci lot/pemasoknya). `_isian_silo_banyak`
    # menjaga kueri ini TETAP jumlahnya berapa pun banyak kartu — memanggil
    # versi satuan per silo di sini akan mengulang P-S-02.
    from app.services.berjalan import _isian_silo_banyak

    def _broken(silo_id: int) -> bool:
        return silo_info.get(silo_id, (None, "pk"))[1] == "broken"

    permintaan = [
        (u.silo_id, _broken(u.silo_id), p.waktu_mulai)
        for p in procs for u in per_proses.get(p.id, [])
    ]
    isian_map = await _isian_silo_banyak(db, permintaan)

    kartu = []
    for p in procs:
        pakai = per_proses.get(p.id, [])
        silo = []
        for u in pakai:
            isian = isian_map[(u.silo_id, _broken(u.silo_id), p.waktu_mulai)]
            silo.append(PemakaianSilo(
                nama=nama_silo.get(u.silo_id) or f"Silo #{u.silo_id}",
                awal_kg=float(u.berat_awal_kg or 0),
                masuk_kg=float(u.berat_masuk_kg or 0),
                sisa_kg=(None if u.berat_akhir_kg is None else float(u.berat_akhir_kg)),
                terpakai_kg=float(u.berat_terpakai_kg or 0),
                asal=tuple((judul, kg) for judul, kg, _ in isian.baris),
                asal_lebih=isian.lebih,
            ))
        silo = tuple(silo)
        keluar = hasil.get(p.id, {})
        neraca = neraca_sosoh(sum(s.terpakai_kg for s in silo), keluar)
        bahan_tercatat = sum(float(u.terpakai_lama_kg or 0) for u in pakai)
        hitung_ulang = (any(u.bobot_karung_dinamis for u in pakai)
                       and abs(bahan_tercatat - neraca.bahan_kg) > 0.001)
        neraca_tercatat = neraca_sosoh(bahan_tercatat,keluar) if hitung_ulang else None
        # Beras dirinci per grade, urut `GRADES` — bukan urut abjad: pemilik
        # membacanya dari mutu tertinggi ke terendah, dan abjad menaruh
        # "beras_b" di puncak daftar mutu.
        beras = tuple(Bagian(
            jenis=j, nama=nama_produk(j), kg=float(keluar.get(j, 0) or 0),
            persen=((float(keluar[j]) / neraca.bahan_kg * 100)
                    if neraca.bahan_kg else None),
        ) for j in reversed(GRADES) if float(keluar.get(j, 0) or 0))
        from app.penggilingan.gudang2.karung import bobot_pemakaian
        bobot = bobot_pemakaian(pakai)
        kartu.append(KartuSosoh(
            id=p.id, kode=p.kode_proses, mulai=p.waktu_mulai,
            selesai=p.waktu_selesai,
            lama=(lama_kata((p.waktu_selesai - p.waktu_mulai).total_seconds())
                  if p.waktu_selesai else ""),
            oleh=nama_orang.get(p.created_by) or "—",
            jasa=p.jasa_id is not None,
            kode_jasa=(pemilik[p.jasa_id][0] if p.jasa_id in pemilik else None),
            nama_pemilik=(pemilik[p.jasa_id][1] if p.jasa_id in pemilik else None),
            pemilik=(f"{pemilik[p.jasa_id][0]} {pemilik[p.jasa_id][1]}".strip()
                     if p.jasa_id in pemilik else
                     f"pesanan #{p.jasa_id}" if p.jasa_id is not None else None),
            silo=silo, neraca=neraca, beras=beras, neraca_tercatat=neraca_tercatat,
            spek=tuple(spek_per.get(p.id, [])),
            bahan_pasti=bobot.pasti, bahan_teks=bobot.teks(),
        ))
    return kartu, lagi
