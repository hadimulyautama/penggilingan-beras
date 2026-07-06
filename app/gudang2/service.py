"""Logika Gudang 2 (Penyosohan) — PK masuk, silo/tumpukan, pindah tumpukan→silo.

Acuan WAJIB: LOGIKA_SILO_GUDANG2.md.
- Silo G2 = KOLAM CAMPURAN (banyak sumber).
- Stok silo/tumpukan DITURUNKAN (bukan kolom saldo).
- Tumpukan WAJIB masuk silo dulu sebelum disosoh.
- Pindah tumpukan→silo HANYA operator Gudang 2 (admin fallback), bisa parsial, cap 60t.
- HPP silo = weighted-average bahan yang SUDAH di silo (kecuali HPP belum tersedia).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import input_time
from app.models import (
    InternalTransfer,
    PkGudang2Intake,
    PkPurchaseBatch,
    PkPurchaseVerification,
    PkRejection,
    PkTumpukanToSilo,
    PolishingSiloUsage,
    Silo,
    User,
    Warehouse,
)
from app.services.activity_log import log_activity
from app.services.codegen import (
    next_pk_purchase_code,
    next_rejection_code,
    next_tumpukan_move_code,
)
from app.services.notification import create_notification
from app.gudang1.services.purchase import find_or_create_supplier

_TUJUAN_SILO = {"silo_a": "A", "silo_b": "B"}


class Gudang2Error(Exception):
    """Kesalahan Gudang 2 dengan pesan siap-tampil (args[0])."""


# ─────────────────────────── Master helpers ───────────────────────────
async def _g2_warehouse_id(db: AsyncSession) -> int:
    wid = (
        await db.execute(
            select(Warehouse.id).where(Warehouse.nama_gudang.like("Gudang 2%"))
        )
    ).scalars().first()
    if wid is None:
        raise Gudang2Error("Data Gudang 2 belum ada.")
    return wid


async def get_g2_silo(db: AsyncSession, letter: str) -> Silo | None:
    wid = await _g2_warehouse_id(db)
    return (
        await db.execute(
            select(Silo).where(
                Silo.warehouse_id == wid, Silo.nama_silo == f"Silo {letter}"
            )
        )
    ).scalars().first()


def is_operator_gudang2(user: User, g2_wid: int) -> bool:
    """Operator Gudang 2 (admin sebagai fallback selalu boleh)."""
    if user.role == "admin":
        return True
    return user.role == "operator" and user.default_warehouse_id == g2_wid


# ─────────────────────────── Formula stok ───────────────────────────
async def hitung_stok_silo(db: AsyncSession, silo_id: int) -> float:
    """Stok PK sebuah silo G2 = masuk langsung + masuk dari tumpukan − terpakai."""
    masuk_langsung = (
        await db.execute(
            select(func.coalesce(func.sum(PkGudang2Intake.berat_kg), 0)).where(
                PkGudang2Intake.silo_id == silo_id,
                PkGudang2Intake.tujuan.in_(["silo_a", "silo_b"]),
            )
        )
    ).scalar_one()
    masuk_dari_tumpukan = (
        await db.execute(
            select(func.coalesce(func.sum(PkTumpukanToSilo.berat_kg), 0)).where(
                PkTumpukanToSilo.silo_id == silo_id
            )
        )
    ).scalar_one()
    # Terpakai penyosohan (hanya proses yang berat_akhir-nya sudah diisi).
    terpakai = (
        await db.execute(
            select(func.coalesce(func.sum(PolishingSiloUsage.berat_terpakai_kg), 0)).where(
                PolishingSiloUsage.silo_id == silo_id,
                PolishingSiloUsage.berat_akhir_kg.isnot(None),
            )
        )
    ).scalar_one()
    return float(masuk_langsung) + float(masuk_dari_tumpukan) - float(terpakai)


async def hitung_stok_tumpukan(db: AsyncSession) -> float:
    """Stok tumpukan G2 = total masuk sbg tumpukan − total sudah dipindah ke silo."""
    masuk = (
        await db.execute(
            select(func.coalesce(func.sum(PkGudang2Intake.berat_kg), 0)).where(
                PkGudang2Intake.tujuan == "ditumpuk"
            )
        )
    ).scalar_one()
    sudah_dipindah = (
        await db.execute(
            select(func.coalesce(func.sum(PkTumpukanToSilo.berat_kg), 0))
        )
    ).scalar_one()
    return float(masuk) - float(sudah_dipindah)


async def _sisa_tumpukan_intake(db: AsyncSession, intake_id: int) -> float:
    """Sisa PK sebuah intake tumpukan yang belum dipindah ke silo."""
    intake = await db.get(PkGudang2Intake, intake_id)
    if intake is None:
        raise Gudang2Error("Data tumpukan tidak ditemukan.")
    dipindah = (
        await db.execute(
            select(func.coalesce(func.sum(PkTumpukanToSilo.berat_kg), 0)).where(
                PkTumpukanToSilo.pk_gudang2_intake_id == intake_id
            )
        )
    ).scalar_one()
    return float(intake.berat_kg) - float(dipindah)


async def hitung_hpp_wavg_silo(db: AsyncSession, silo_id: int) -> float | None:
    """HPP rata-rata tertimbang bahan yang SUDAH di silo (kecuali HPP belum tersedia)."""
    n1, b1 = (
        await db.execute(
            select(
                func.coalesce(func.sum(PkGudang2Intake.berat_kg * PkGudang2Intake.hpp_per_kg), 0),
                func.coalesce(func.sum(PkGudang2Intake.berat_kg), 0),
            ).where(
                PkGudang2Intake.silo_id == silo_id,
                PkGudang2Intake.tujuan.in_(["silo_a", "silo_b"]),
                PkGudang2Intake.flag_hpp_belum_tersedia.is_(False),
            )
        )
    ).one()
    n2, b2 = (
        await db.execute(
            select(
                func.coalesce(func.sum(PkTumpukanToSilo.berat_kg * PkGudang2Intake.hpp_per_kg), 0),
                func.coalesce(func.sum(PkTumpukanToSilo.berat_kg), 0),
            )
            .select_from(PkTumpukanToSilo)
            .join(PkGudang2Intake, PkGudang2Intake.id == PkTumpukanToSilo.pk_gudang2_intake_id)
            .where(
                PkTumpukanToSilo.silo_id == silo_id,
                PkGudang2Intake.flag_hpp_belum_tersedia.is_(False),
            )
        )
    ).one()
    total_berat = float(b1) + float(b2)
    if total_berat <= 0:
        return None
    return (float(n1) + float(n2)) / total_berat


# ─────────────────────────── Beli PK luar ───────────────────────────
@dataclass
class PkPurchaseResult:
    batch: PkPurchaseBatch
    supplier_nama: str
    supplier_created: bool


JENIS_PK_LUAR = {"ks", "kl", "campuran", "semi_ks"}
_JENIS_PK_LABEL = {"ks": "KS", "kl": "KL", "campuran": "Campuran", "semi_ks": "Semi KS"}


def norm_jenis_pk(v: str | None) -> str | None:
    """Normalisasi jenis PK luar → ks/kl/campuran/semi_ks; None bila tak dikenali."""
    if not v:
        return None
    s = v.lower().strip().replace("-", " ").replace("_", " ")
    if s in ("semi ks", "semi", "semiks"):
        return "semi_ks"
    if s in ("campuran", "campur", "mix", "mixed"):
        return "campuran"
    if s == "ks":
        return "ks"
    if s == "kl":
        return "kl"
    return None


async def create_pk_purchase(
    db: AsyncSession, *, user: User, nama_supplier: str | None, berat_kg: float | None,
    jenis_pk: str | None = None, kadar_air: float | None = None,
    no_polisi: str | None = None, tanggal: date | None = None, jam: time | None = None,
) -> PkPurchaseResult:
    """Catat pembelian PK dari luar (Gudang 2). Menunggu QC + verifikasi harga.

    Master §2: input PK dari luar + QC = STAFF/ADMIN saja (bukan operator).
    Wajib: supplier, berat, plat truk, jenis PK (ks/kl/campuran/semi_ks).
    """
    if user.role not in ("staff", "admin"):
        raise Gudang2Error(
            "🔒 Input PK dari luar (+ QC) hanya bisa dilakukan oleh Staff/Admin."
        )
    if not nama_supplier:
        raise Gudang2Error("Sebutkan supplier PK-nya, contoh: `beli PK dari pak andi 5 ton`")
    if not berat_kg:
        raise Gudang2Error("Sebutkan berat PK-nya (mis. `5 ton`).")
    if not no_polisi:
        raise Gudang2Error("Sebutkan plat nomor truk pengirim PK.")
    jenis = norm_jenis_pk(jenis_pk)
    if jenis is None:
        raise Gudang2Error("Sebutkan jenis PK: KS, KL, Campuran, atau Semi KS.")
    now = input_time(tanggal, jam)  # BackdateError bila di masa depan
    supplier, created = await find_or_create_supplier(db, nama_supplier)
    kode = await next_pk_purchase_code(db, now.date())
    batch = PkPurchaseBatch(
        kode_batch=kode, supplier_id=supplier.id, berat_total_kg=berat_kg,
        no_polisi_truk=no_polisi, jenis_pk=jenis, kadar_air_awal_persen=kadar_air,
        tanggal_pembelian=now.date(), waktu_pembelian=now, input_by=user.id,
        status_batch="baru", flag_unverified=True,
    )
    db.add(batch)
    await db.flush()
    await log_activity(
        db, table_name="pk_purchase_batches", record_id=batch.id, action="INSERT",
        changed_by=user.id,
        new_value=f"{kode} | {supplier.nama_supplier} | {berat_kg:.0f}kg PK luar",
    )
    await create_notification(
        db, tipe="verifikasi_pk_luar",
        pesan=(
            f"🟡 PK luar {kode} ({supplier.nama_supplier}, {berat_kg:.0f} kg) "
            "menunggu QC + verifikasi harga."
        ),
        target_role="staff", prioritas="kuning",
        table_name="pk_purchase_batches", record_id=batch.id,
    )
    await db.commit()
    await db.refresh(batch)
    return PkPurchaseResult(batch=batch, supplier_nama=supplier.nama_supplier,
                            supplier_created=created)


@dataclass
class PkVerifyResult:
    batch: PkPurchaseBatch
    keputusan: str
    berat_bersih_kg: float
    total_biaya: float | None
    hpp_per_kg: float | None
    rejection_kode: str | None = None


_BUTIR_KUNING = {"bersih", "sedang", "banyak"}


async def verify_pk_purchase(
    db: AsyncSession, *, user: User, kode: str, keputusan: str | None,
    kadar_air: float | None = None, broken: float | None = None,
    penyusutan_persen: float | None = None, butir_kuning: str | None = None,
    catatan_lab: str | None = None, alasan_tolak: str | None = None,
    potongan_kg: float | None = None, potongan_alasan: str | None = None,
    harga_per_kg: float | None = None, total: float | None = None,
) -> PkVerifyResult:
    """QC uji lab + harga PK luar (staff/admin). keputusan: terima/tolak.

    Uji lab: kadar air, broken%, penyusutan (% bekatul lab), butir kuning
    (bersih/sedang/banyak), catatan. Bila `tolak`: catat REJ- (dikembalikan
    ke supplier) + notif; PK tidak pernah jadi stok.
    """
    batch = (
        await db.execute(select(PkPurchaseBatch).where(PkPurchaseBatch.kode_batch == kode))
    ).scalars().first()
    if batch is None:
        raise Gudang2Error(f"PK luar {kode} tidak ditemukan.")
    keputusan = (keputusan or "terima").lower()
    if keputusan not in ("terima", "tolak"):
        raise Gudang2Error("Keputusan QC harus: terima atau tolak.")
    if butir_kuning:
        butir_kuning = butir_kuning.lower().strip()
        if butir_kuning not in _BUTIR_KUNING:
            raise Gudang2Error("Butir kuning harus: bersih, sedang, atau banyak.")

    berat_bersih = float(batch.berat_total_kg) - float(potongan_kg or 0)
    total_biaya = None
    hpp = None
    metode = None
    if keputusan == "terima":
        if total is not None:
            total_biaya = float(total)
            hpp = total_biaya / berat_bersih if berat_bersih else None
            metode = "total"
        elif harga_per_kg is not None:
            hpp = float(harga_per_kg)
            total_biaya = hpp * berat_bersih
            metode = "per_kg"
        else:
            raise Gudang2Error("Sebutkan harga PK (per kg atau total) untuk keputusan terima.")

    verif = (
        await db.execute(
            select(PkPurchaseVerification).where(
                PkPurchaseVerification.pk_purchase_batch_id == batch.id
            )
        )
    ).scalars().first()
    if verif is None:
        verif = PkPurchaseVerification(pk_purchase_batch_id=batch.id)
        db.add(verif)
    verif.kadar_air = kadar_air
    verif.broken_persen = broken
    verif.penyusutan_persen = penyusutan_persen
    verif.butir_kuning = butir_kuning
    verif.catatan_lab = catatan_lab
    verif.keputusan = keputusan
    verif.alasan_tolak = alasan_tolak if keputusan == "tolak" else None
    verif.potongan_kg = potongan_kg
    verif.potongan_alasan = potongan_alasan
    verif.harga_per_kg = hpp
    verif.total_biaya = total_biaya
    verif.metode_harga = metode
    verif.verified_by = user.id
    now = input_time(None)
    verif.waktu_verifikasi = now
    verif.status_verifikasi = "terverifikasi"

    batch.flag_unverified = False
    batch.status_batch = "diterima" if keputusan == "terima" else "ditolak"
    await log_activity(
        db, table_name="pk_purchase_verifications", record_id=batch.id, action="INSERT",
        changed_by=user.id,
        new_value=f"{keputusan} | potongan={potongan_kg} | hpp={hpp}",
    )

    rejection_kode = None
    if keputusan == "tolak":
        rej = PkRejection(
            kode=await next_rejection_code(db, now.date()),
            pk_purchase_batch_id=batch.id,
            berat_kg=float(batch.berat_total_kg),
            no_polisi_truk=batch.no_polisi_truk,
            alasan=alasan_tolak,
            tanggal=now.date(), waktu=now, created_by=user.id,
        )
        db.add(rej)
        await db.flush()
        rejection_kode = rej.kode
        truk = f" (truk {batch.no_polisi_truk})" if batch.no_polisi_truk else ""
        sebab = f" — {alasan_tolak}" if alasan_tolak else ""
        await create_notification(
            db, tipe="pk_ditolak",
            pesan=(
                f"⛔ PK {batch.kode_batch} ({float(batch.berat_total_kg):.0f} kg) DITOLAK "
                f"& dikembalikan ke supplier{truk}. Ref {rej.kode}{sebab}."
            ),
            target_role="staff", prioritas="kuning",
            table_name="pk_rejections", record_id=rej.id,
        )

    await db.commit()
    await db.refresh(batch)
    return PkVerifyResult(batch=batch, keputusan=keputusan, berat_bersih_kg=berat_bersih,
                          total_biaya=total_biaya, hpp_per_kg=hpp,
                          rejection_kode=rejection_kode)


# ─────────────────────────── Intake ke silo/tumpukan ───────────────────────────
@dataclass
class IntakeResult:
    intake: PkGudang2Intake
    lokasi_label: str
    hpp_per_kg: float | None


async def _tujuan_and_silo(db: AsyncSession, tujuan: str | None):
    """Normalisasi tujuan → (tujuan, silo_id|None). tujuan: silo_a/silo_b/ditumpuk."""
    tujuan = (tujuan or "").lower()
    if tujuan == "ditumpuk":
        return "ditumpuk", None
    if tujuan in _TUJUAN_SILO:
        silo = await get_g2_silo(db, _TUJUAN_SILO[tujuan])
        if silo is None:
            raise Gudang2Error(f"Silo {_TUJUAN_SILO[tujuan]} Gudang 2 tidak ditemukan.")
        return tujuan, silo.id
    raise Gudang2Error("Tujuan harus: Silo A, Silo B, atau ditumpuk.")


async def _guard_kapasitas_tumpukan(db: AsyncSession, tambahan_kg: float) -> None:
    stok = await hitung_stok_tumpukan(db)
    cap = settings.g2_tumpukan_maks_kg
    if stok + tambahan_kg > cap:
        sisa = max(cap - stok, 0)
        raise Gudang2Error(
            f"❌ Kapasitas tumpukan Gudang 2 penuh (maks {cap / 1000:g} ton). "
            f"Terisi {stok / 1000:g} ton (sisa {sisa / 1000:g} ton), "
            f"tambahan {tambahan_kg / 1000:g} ton."
        )


async def _add_intake(
    db: AsyncSession, *, user: User, sumber_tipe: str, tujuan: str,
    berat_kg: float, hpp_per_kg: float | None, tanggal, jam,
    pk_purchase_batch_id: int | None = None, internal_transfer_id: int | None = None,
) -> IntakeResult:
    tujuan_norm, silo_id = await _tujuan_and_silo(db, tujuan)
    if tujuan_norm == "ditumpuk":
        await _guard_kapasitas_tumpukan(db, berat_kg)
    now = input_time(tanggal, jam)
    intake = PkGudang2Intake(
        sumber_tipe=sumber_tipe,
        pk_purchase_batch_id=pk_purchase_batch_id,
        internal_transfer_id=internal_transfer_id,
        tujuan=tujuan_norm, silo_id=silo_id, berat_kg=berat_kg,
        hpp_per_kg=hpp_per_kg, flag_hpp_belum_tersedia=hpp_per_kg is None,
        tanggal_masuk=now.date(), waktu_masuk=now, input_by=user.id,
    )
    db.add(intake)
    await db.flush()
    await log_activity(
        db, table_name="pk_gudang2_intakes", record_id=intake.id, action="INSERT",
        changed_by=user.id,
        new_value=f"{sumber_tipe} | {berat_kg:.0f}kg → {tujuan_norm} | hpp={hpp_per_kg}",
    )
    await db.commit()
    await db.refresh(intake)
    label = {"silo_a": "Silo A", "silo_b": "Silo B", "ditumpuk": "tumpukan"}[tujuan_norm]
    return IntakeResult(intake=intake, lokasi_label=label, hpp_per_kg=hpp_per_kg)


async def terima_transfer_g1(
    db: AsyncSession, *, user: User, kode_transfer: str | None, tujuan: str | None = None,
    tanggal=None, jam=None,
) -> IntakeResult:
    """Terima PK kiriman Gudang 1 (InternalTransfer) → intake stok Gudang 2."""
    if not kode_transfer:
        raise Gudang2Error("Sebutkan kode transfernya, contoh: `terima TRF-20260704-01 ke silo A`")
    trf = (
        await db.execute(
            select(InternalTransfer).where(InternalTransfer.kode_transfer == kode_transfer)
        )
    ).scalars().first()
    if trf is None:
        raise Gudang2Error(f"Transfer {kode_transfer} tidak ditemukan.")
    dup = (
        await db.execute(
            select(PkGudang2Intake.id).where(
                PkGudang2Intake.internal_transfer_id == trf.id
            )
        )
    ).first()
    if dup:
        raise Gudang2Error(f"Transfer {kode_transfer} sudah diterima sebelumnya.")
    # Tujuan default ikut lokasi_tujuan transfer bila operator tak menyebut.
    return await _add_intake(
        db, user=user, sumber_tipe="transfer_internal",
        tujuan=tujuan or trf.lokasi_tujuan, berat_kg=float(trf.berat_kg),
        hpp_per_kg=float(trf.hpp_per_kg) if trf.hpp_per_kg is not None else None,
        tanggal=tanggal, jam=jam, internal_transfer_id=trf.id,
    )


async def masukkan_pk_luar(
    db: AsyncSession, *, user: User, kode: str | None, tujuan: str | None = None,
    tanggal=None, jam=None,
) -> IntakeResult:
    """Masukkan PK luar yang SUDAH diterima (QC terima) ke silo/tumpukan G2."""
    if not kode:
        raise Gudang2Error("Sebutkan kode PK luarnya, contoh: `masukkan PKL-... ke silo B`")
    batch = (
        await db.execute(select(PkPurchaseBatch).where(PkPurchaseBatch.kode_batch == kode))
    ).scalars().first()
    if batch is None:
        raise Gudang2Error(f"PK luar {kode} tidak ditemukan.")
    if batch.status_batch == "ditolak":
        raise Gudang2Error(f"PK luar {kode} ditolak saat QC — tidak bisa dimasukkan.")
    if batch.flag_unverified:
        raise Gudang2Error(f"PK luar {kode} belum di-QC/verifikasi — proses itu dulu.")
    dup = (
        await db.execute(
            select(PkGudang2Intake.id).where(
                PkGudang2Intake.pk_purchase_batch_id == batch.id
            )
        )
    ).first()
    if dup:
        raise Gudang2Error(f"PK luar {kode} sudah dimasukkan sebelumnya.")
    verif = (
        await db.execute(
            select(PkPurchaseVerification).where(
                PkPurchaseVerification.pk_purchase_batch_id == batch.id
            )
        )
    ).scalars().first()
    berat = float(batch.berat_total_kg) - float(verif.potongan_kg or 0 if verif else 0)
    hpp = float(verif.harga_per_kg) if verif and verif.harga_per_kg is not None else None
    res = await _add_intake(
        db, user=user, sumber_tipe="beli_luar", tujuan=tujuan, berat_kg=berat,
        hpp_per_kg=hpp, tanggal=tanggal, jam=jam, pk_purchase_batch_id=batch.id,
    )
    batch.status_batch = "di_silo" if res.intake.tujuan != "ditumpuk" else "ditumpuk"
    await db.commit()
    return res


# ─────────────────────────── Pindah tumpukan → silo ───────────────────────────
@dataclass
class PindahResult:
    kode_pindah: str
    nama_silo: str
    berat_kg: float
    sisa_tumpukan_intake: float


async def pindah_tumpukan_ke_silo(
    db: AsyncSession, *, user: User, intake_id: int, nama_silo: str | None,
    berat: float | None = None, tanggal=None, jam=None,
) -> PindahResult:
    """Pindah PK dari tumpukan ke silo. HANYA operator Gudang 2 (admin fallback)."""
    g2_wid = await _g2_warehouse_id(db)
    if not is_operator_gudang2(user, g2_wid):
        raise Gudang2Error(
            "🔒 Pemindahan tumpukan ke silo hanya bisa dilakukan oleh "
            "Operator Gudang 2 (atau admin)."
        )
    if not nama_silo:
        raise Gudang2Error("Sebutkan silo tujuannya (A atau B).")
    silo = await get_g2_silo(db, nama_silo)
    if silo is None:
        raise Gudang2Error(f"Silo {nama_silo} Gudang 2 tidak ditemukan.")
    intake = await db.get(PkGudang2Intake, intake_id)
    if intake is None:
        raise Gudang2Error("Tumpukan sumber tidak ditemukan.")
    if intake.tujuan != "ditumpuk":
        raise Gudang2Error("Sumber bukan tumpukan — hanya PK di tumpukan yang bisa dipindah.")

    sisa = await _sisa_tumpukan_intake(db, intake_id)
    if sisa <= 0:
        raise Gudang2Error("Tumpukan ini sudah habis dipindah.")
    kirim = sisa if berat is None else min(float(berat), sisa)
    if berat is not None and float(berat) > sisa:
        raise Gudang2Error(
            f"Berat pindah ({float(berat):.0f} kg) melebihi sisa tumpukan ({sisa:.0f} kg)."
        )

    now = input_time(tanggal, jam)
    move = PkTumpukanToSilo(
        kode_pindah=await next_tumpukan_move_code(db),
        pk_gudang2_intake_id=intake_id, silo_id=silo.id, berat_kg=kirim,
        tanggal=now.date(), waktu=now, input_by=user.id,
    )
    db.add(move)
    await db.flush()
    await log_activity(
        db, table_name="pk_tumpukan_to_silo", record_id=move.id, action="INSERT",
        changed_by=user.id,
        new_value=f"{move.kode_pindah} | {kirim:.0f}kg → Silo {nama_silo}",
    )
    await db.commit()
    await db.refresh(move)
    return PindahResult(
        kode_pindah=move.kode_pindah, nama_silo=nama_silo, berat_kg=kirim,
        sisa_tumpukan_intake=sisa - kirim,
    )


@dataclass
class PindahPoolResult:
    nama_silo: str
    moved_kg: float
    kodes: list[str]
    sisa_tumpukan: float


async def pindah_tumpukan(
    db: AsyncSession, *, user: User, nama_silo: str | None, berat: float | None = None,
    tanggal=None, jam=None,
) -> PindahPoolResult:
    """Pindahkan PK dari tumpukan ke silo (FIFO antar intake tumpukan).

    HANYA operator Gudang 2 (admin fallback). `berat` None = pindah semua tumpukan.
    """
    g2_wid = await _g2_warehouse_id(db)
    if not is_operator_gudang2(user, g2_wid):
        raise Gudang2Error(
            "🔒 Pemindahan tumpukan ke silo hanya bisa dilakukan oleh "
            "Operator Gudang 2 (atau admin)."
        )
    if not nama_silo:
        raise Gudang2Error("Sebutkan silo tujuannya (A atau B).")
    silo = await get_g2_silo(db, nama_silo)
    if silo is None:
        raise Gudang2Error(f"Silo {nama_silo} Gudang 2 tidak ditemukan.")

    intakes = (
        await db.execute(
            select(PkGudang2Intake)
            .where(PkGudang2Intake.tujuan == "ditumpuk")
            .order_by(PkGudang2Intake.id)
        )
    ).scalars().all()
    pool: list[tuple[PkGudang2Intake, float]] = []
    for it in intakes:
        sisa = await _sisa_tumpukan_intake(db, it.id)
        if sisa > 0:
            pool.append((it, sisa))
    total_sisa = sum(s for _, s in pool)
    if total_sisa <= 0:
        raise Gudang2Error("Tumpukan Gudang 2 kosong — tidak ada yang bisa dipindah.")
    if berat is not None and float(berat) > total_sisa:
        raise Gudang2Error(
            f"Berat pindah ({float(berat):.0f} kg) melebihi total tumpukan "
            f"({total_sisa:.0f} kg)."
        )
    target = total_sisa if berat is None else float(berat)

    now = input_time(tanggal, jam)
    moved = 0.0
    kodes: list[str] = []
    remaining = target
    for it, sisa in pool:
        if remaining <= 0:
            break
        take = min(sisa, remaining)
        move = PkTumpukanToSilo(
            kode_pindah=await next_tumpukan_move_code(db),
            pk_gudang2_intake_id=it.id, silo_id=silo.id, berat_kg=take,
            tanggal=now.date(), waktu=now, input_by=user.id,
        )
        db.add(move)
        await db.flush()
        await log_activity(
            db, table_name="pk_tumpukan_to_silo", record_id=move.id, action="INSERT",
            changed_by=user.id,
            new_value=f"{move.kode_pindah} | {take:.0f}kg → Silo {nama_silo}",
        )
        kodes.append(move.kode_pindah)
        moved += take
        remaining -= take
    await db.commit()
    return PindahPoolResult(
        nama_silo=nama_silo, moved_kg=moved, kodes=kodes,
        sisa_tumpukan=total_sisa - moved,
    )


# ─────────────────────────── Laporan stok ───────────────────────────
def _kg(kg: float) -> str:
    return f"{kg:,.0f} kg".replace(",", ".")


def _rp(n: float | None) -> str:
    return "Rp " + f"{n:,.0f}".replace(",", ".") if n is not None else "-"


async def laporan_stok_gudang2(
    db: AsyncSession, nama_silo: str | None = None, financial: bool = True
) -> str:
    """Stok PK Gudang 2: silo A/B (+ HPP wavg bila boleh) + tumpukan."""
    lines = ["🏭 Stok PK Gudang 2:"]
    letters = [nama_silo.upper()] if nama_silo else ["A", "B"]
    for letter in letters:
        silo = await get_g2_silo(db, letter)
        if silo is None:
            lines.append(f"• Silo {letter}: (tidak ditemukan)")
            continue
        stok = await hitung_stok_silo(db, silo.id)
        cap = (
            f" / maks {float(silo.kapasitas_ton):g} ton"
            if silo.kapasitas_ton is not None else ""
        )
        baris = f"• Silo {letter}: {_kg(stok)}{cap}"
        if financial:
            hpp = await hitung_hpp_wavg_silo(db, silo.id)
            if hpp is not None:
                baris += f" · HPP rata2 {_rp(hpp)}/kg"
        lines.append(baris)
    if not nama_silo:
        tump = await hitung_stok_tumpukan(db)
        lines.append(
            f"• Tumpukan: {_kg(tump)} / maks {settings.g2_tumpukan_maks_kg / 1000:g} ton"
        )
    return "\n".join(lines)
