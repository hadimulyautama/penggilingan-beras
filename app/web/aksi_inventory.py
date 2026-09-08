"""Aksi cepat inventory: kemasan, barang jadi, barang keluar.

Tiga lubang terakhir yang menahan pematian bot pabrik. Layanannya sudah ada
sejak lama (`app/penggilingan/inventory/`); yang belum ada hanya jalan
memanggilnya dari layar, dan itulah isi berkas ini.

**Perubahan bentuk yang disengaja terhadap jalur bot.** Di bot, kemasan
disebut sebagai tiga hal terpisah dalam satu kalimat bebas — kategori, jenis
karung, ukuran — lalu `_validate_kemasan` menolak kombinasi yang mustahil
SESUDAH orang selesai mengetik. Di layar itu tidak perlu terjadi: kombinasi
yang sah sudah diketahui server, jadi yang ditawarkan hanya kombinasi yang
sah. Satu pilihan, bukan tiga yang bisa bertabrakan. Aturan kemasannya sendiri
tetap satu sumber di `packaging.KEMASAN_VALID` — di sini ia dibaca, tidak
disalin.

**Yang tetap di server.** Hak akses tidak ditentukan oleh tombol yang tampak:
menu disaring per peran demi kenyamanan, tetapi tiap POST memeriksa sendiri.
Operator Gudang 2 boleh mencatat packing dan bekatul (barang berpindah wujud
di depan matanya); harga, pembelian, dan pengiriman keluar milik staff/admin.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.peran import can_see_financials
from app.database import SessionLocal
from app.models import User
from app.penggilingan.inventory import finished_goods as bj
from app.penggilingan.inventory import outgoing as keluar
from app.penggilingan.inventory import packaging as kms
from app.web.aksi_umum import galat, kg, rp, wajib
from app.web.deps import pengguna_aksi

router = APIRouter(prefix="/miniapp", tags=["miniapp"])

#: Nama kategori produk di layar. Kunci = `ProductSku.kategori`.
KATEGORI_LABEL = {
    "beras_putih": "Beras putih",
    "beras_b": "Beras B",
    "broken": "Broken",
    "menir": "Menir",
    "reject": "Reject",
    "pk": "PK",
}

#: Kategori yang memakai merk. Sisanya (hasil samping & PK) tidak bermerk sama
#: sekali — bukan "boleh kosong", melainkan tidak punya kolomnya.
KATEGORI_BERMERK = ("beras_putih", "beras_b")


def _triple(kategori: str, material: str, ukuran: int) -> str:
    return f"{kategori}|{material}|{ukuran}"


def _urai_triple(nilai: str) -> tuple[str, str, int]:
    """Balikkan pilihan kemasan jadi tiga bagiannya, atau tolak dengan jelas."""
    bagian = (nilai or "").split("|")
    if len(bagian) != 3 or not bagian[2].isdigit():
        raise HTTPException(400, "Pilih kemasannya dulu.")
    kategori, material, ukuran = bagian[0], bagian[1], int(bagian[2])
    # Diperiksa ulang di sini meski daftar pilihannya berasal dari server:
    # yang mengirim POST adalah perangkat, dan isian perangkat tidak pernah
    # jadi alasan untuk melewati pemeriksaan.
    try:
        kms._validate_kemasan(kategori, material, ukuran)
    except kms.InventoryError as e:
        raise galat(e, "Kombinasi kemasan tidak sah.")
    return kategori, material, ukuran


def kombinasi_kemasan(kategori: str | None = None) -> list[tuple[str, str, int]]:
    """Semua (kategori, jenis karung, ukuran) yang sah menurut aturan kemasan.

    Diturunkan dari `KEMASAN_VALID`, tidak ditulis ulang: menambah kemasan baru
    cukup di satu tempat, dan daftar di layar ikut berubah dengan sendirinya.
    """
    hasil: list[tuple[str, str, int]] = []
    for kat, aturan in kms.KEMASAN_VALID.items():
        if kategori and kat != kategori:
            continue
        for material, ukuran in sorted(aturan):
            ukuran_sah = [ukuran] if ukuran is not None else sorted(kms._BERAS_SIZES)
            for u in ukuran_sah:
                hasil.append((kat, material, u))
    return hasil


# ─────────────────────────── Sumber pilihan ───────────────────────────

async def _nama_material(db) -> dict[str, str]:
    rows = (await db.execute(
        select(kms.PackagingMaterial.kode, kms.PackagingMaterial.nama)
    )).all()
    return {k: n for k, n in rows}


@router.get("/actions/kemasan-jenis")
async def kemasan_jenis(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Karung yang benar-benar dipakai pabrik — untuk dibeli.

    Bukan hasil kali seluruh jenis × seluruh ukuran: karung yang tak dipakai
    produk mana pun tidak boleh dibeli lewat layar ini, karena stoknya lalu
    mengendap tanpa pernah terpakai dan ikut menghitung HPP kemasan.
    """
    wajib(can_see_financials(user))
    async with SessionLocal() as db:
        nama = await _nama_material(db)
    pasang = sorted({(m, u) for _, m, u in kombinasi_kemasan()})
    return [{"value": f"{m}|{u}", "label": f"{nama.get(m, m)} {u} kg"} for m, u in pasang]


@router.get("/actions/produk-kemasan")
async def produk_kemasan(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Kombinasi produk × karung yang sah — satu pilihan, bukan tiga."""
    async with SessionLocal() as db:
        nama = await _nama_material(db)
    return [
        {"value": _triple(kat, m, u),
         "label": f"{KATEGORI_LABEL.get(kat, kat)} · {nama.get(m, m).lower()} {u} kg"}
        for kat, m, u in kombinasi_kemasan()
        if kat != "pk"        # PK tak dipacking di sini; ia dijual dari Gudang 1
    ]


@router.get("/actions/merk")
async def daftar_merk(user: User = Depends(pengguna_aksi)) -> list[dict]:
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(kms.Brand.nama).where(kms.Brand.aktif.is_(True),
                                         kms.Brand.deleted_at.is_(None))
            .order_by(kms.Brand.tipe.desc(), kms.Brand.nama)
        )).scalars().all()
    return [{"value": n, "label": n} for n in rows]


@router.get("/actions/mutu-beras")
async def mutu_beras(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Standar mutu beras putih. Beras B sengaja tidak punya — jangan diisi."""
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(kms.RiceQualityStandard.kode, kms.RiceQualityStandard.nama)
            .where(kms.RiceQualityStandard.aktif.is_(True))
            .order_by(kms.RiceQualityStandard.urutan.desc())
        )).all()
    return [{"value": k, "label": n} for k, n in rows]


@router.get("/actions/polishing-terkini")
async def polishing_terkini(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Proses penyosohan terakhir — termasuk yang sudah selesai.

    Packing sering dikerjakan setelah prosesnya ditutup, jadi daftar ini TIDAK
    boleh disaring ke yang berstatus proses saja seperti daftar aksi lain.
    """
    from app.models import PolishingProcess
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(PolishingProcess.kode_proses, PolishingProcess.status)
            .order_by(PolishingProcess.id.desc()).limit(15)
        )).all()
    return [{"value": k, "label": k + ("" if s == "proses" else f" ({s})")}
            for k, s in rows]


@router.get("/actions/milling-terkini")
async def milling_terkini(user: User = Depends(pengguna_aksi)) -> list[dict]:
    wajib(can_see_financials(user))
    from app.models import MillingProcess
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(MillingProcess.kode_proses, MillingProcess.status)
            .order_by(MillingProcess.id.desc()).limit(15)
        )).all()
    return [{"value": k, "label": k + ("" if s == "proses" else f" ({s})")}
            for k, s in rows]


# ─────────────────────────── Kemasan ───────────────────────────

class BeliKemasanReq(BaseModel):
    karung: str                       # "material|ukuran"
    jumlah: int
    merk: str | None = None
    harga_per_lembar: float | None = None


@router.post("/actions/beli-kemasan")
async def act_beli_kemasan(req: BeliKemasanReq,
                           user: User = Depends(pengguna_aksi)) -> dict:
    wajib(can_see_financials(user))
    bagian = (req.karung or "").split("|")
    if len(bagian) != 2 or not bagian[1].isdigit():
        raise HTTPException(400, "Pilih jenis karung dan ukurannya dulu.")
    material, ukuran = bagian[0], int(bagian[1])
    if int(req.jumlah or 0) <= 0:
        raise HTTPException(400, "Isi jumlah lembar lebih dari 0.")

    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await kms.beli_kemasan(
                db, user=u, material_kode=material, ukuran=ukuran,
                jumlah=int(req.jumlah), brand_nama=(req.merk or None),
                harga_per_lembar=req.harga_per_lembar,
            )
        except kms.InventoryError as e:
            raise galat(e, "Gagal mencatat pembelian karung.")

    merk = f"{r.brand_nama} " if r.brand_nama else ""
    pesan = (f"✓ Beli karung *{merk}{r.material_nama} {r.ukuran}kg* × "
             f"{rp(r.purchase.jumlah_lembar)} lembar ({r.purchase.kode}).\n"
             f"• Stok kini: {rp(r.stok_baru)} lembar")
    return {"ok": True, "pesan": pesan}


# ─────────────────────────── Barang jadi ───────────────────────────

class PackingReq(BaseModel):
    kode_pol: str
    produk: str                       # "kategori|material|ukuran"
    jumlah_karung: int
    merk: str | None = None
    grade: str | None = None


@router.post("/actions/catat-packing")
async def act_catat_packing(req: PackingReq,
                            user: User = Depends(pengguna_aksi)) -> dict:
    from app.web.miniapp import _is_g2_operator
    wajib(await _is_g2_operator(user) or can_see_financials(user))
    kategori, material, ukuran = _urai_triple(req.produk)
    if int(req.jumlah_karung or 0) <= 0:
        raise HTTPException(400, "Isi jumlah karung lebih dari 0.")

    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await bj.catat_packing(
                db, user=u, kode_pol=req.kode_pol, kategori=kategori,
                grade=(req.grade or None) if kategori == "beras_putih" else None,
                brand_nama=(req.merk or None) if kategori in KATEGORI_BERMERK else None,
                material_kode=material, ukuran=ukuran,
                jumlah_karung=int(req.jumlah_karung),
            )
        except bj.InventoryError as e:
            raise galat(e, "Gagal mencatat packing.")

    grade = f" {r.grade}" if r.grade else ""
    warn = f"\n{r.warning}" if r.warning else ""
    pesan = (f"✓ Packing {KATEGORI_LABEL.get(r.kategori, r.kategori)}{grade}: "
             f"{r.jumlah_karung} karung ({kg(r.berat_total_kg)}).{warn}")
    return {"ok": True, "pesan": pesan}


class BekatulReq(BaseModel):
    kode_pol: str
    berat_kg: float


@router.post("/actions/catat-bekatul")
async def act_catat_bekatul(req: BekatulReq,
                            user: User = Depends(pengguna_aksi)) -> dict:
    from app.web.miniapp import _is_g2_operator
    wajib(await _is_g2_operator(user) or can_see_financials(user))
    if float(req.berat_kg or 0) <= 0:
        raise HTTPException(400, "Isi berat bekatul lebih dari 0.")
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            berat = await bj.catat_bekatul(
                db, user=u, kode_pol=req.kode_pol, berat_kg=float(req.berat_kg))
        except bj.InventoryError as e:
            raise galat(e, "Gagal mencatat bekatul.")
    pesan = f"✓ Bekatul {kg(berat)} tercatat (curah)."
    return {"ok": True, "pesan": pesan}


class HargaByproductReq(BaseModel):
    jenis: str
    harga: float


@router.post("/actions/harga-byproduct")
async def act_harga_byproduct(req: HargaByproductReq,
                              user: User = Depends(pengguna_aksi)) -> dict:
    wajib(can_see_financials(user))
    if float(req.harga or 0) <= 0:
        raise HTTPException(400, "Isi harga per kg lebih dari 0.")
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            jenis = await bj.set_harga_byproduct(
                db, user=u, jenis=req.jenis, harga=float(req.harga))
        except bj.InventoryError as e:
            raise galat(e, "Gagal menyimpan harga.")
    pesan = f"✓ Harga {jenis} disetel Rp {rp(float(req.harga))}/kg."
    return {"ok": True, "pesan": pesan}


# ─────────────────────────── Barang keluar ───────────────────────────

class KirimBarangJadiReq(BaseModel):
    produk: str                       # "kategori|material|ukuran"
    jumlah_karung: int
    nama_pembeli: str
    metode: str | None = None
    merk: str | None = None
    grade: str | None = None
    no_polisi: str | None = None
    nama_ekspedisi: str | None = None
    harga_per_kg: float | None = None


@router.post("/actions/kirim-barang-jadi")
async def act_kirim_barang_jadi(req: KirimBarangJadiReq,
                                user: User = Depends(pengguna_aksi)) -> dict:
    wajib(can_see_financials(user))
    kategori, material, ukuran = _urai_triple(req.produk)
    if int(req.jumlah_karung or 0) <= 0:
        raise HTTPException(400, "Isi jumlah karung lebih dari 0.")
    if not (req.nama_pembeli or "").strip():
        raise HTTPException(400, "Isi nama pembeli.")

    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await keluar.kirim_finished_goods(
                db, user=u, kategori=kategori,
                grade=(req.grade or None) if kategori == "beras_putih" else None,
                brand_nama=(req.merk or None) if kategori in KATEGORI_BERMERK else None,
                material_kode=material, ukuran=ukuran,
                jumlah_karung=int(req.jumlah_karung),
                nama_pembeli=req.nama_pembeli.strip(), metode=req.metode,
                no_polisi=(req.no_polisi or None), nama_ekspedisi=(req.nama_ekspedisi or None),
                harga_per_kg=req.harga_per_kg,
            )
        except keluar.InventoryError as e:
            raise galat(e, "Gagal mencatat barang keluar.")
    return {"ok": True, "pesan": await _pesan_keluar(user, r)}


class KirimBekatulReq(BaseModel):
    berat_kg: float
    nama_pembeli: str
    metode: str | None = None
    no_polisi: str | None = None
    nama_ekspedisi: str | None = None
    harga_per_kg: float | None = None


@router.post("/actions/kirim-bekatul")
async def act_kirim_bekatul(req: KirimBekatulReq,
                            user: User = Depends(pengguna_aksi)) -> dict:
    wajib(can_see_financials(user))
    if float(req.berat_kg or 0) <= 0:
        raise HTTPException(400, "Isi berat bekatul lebih dari 0.")
    if not (req.nama_pembeli or "").strip():
        raise HTTPException(400, "Isi nama pembeli.")
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await keluar.kirim_bekatul(
                db, user=u, berat_kg=float(req.berat_kg),
                nama_pembeli=req.nama_pembeli.strip(), metode=req.metode,
                no_polisi=(req.no_polisi or None), nama_ekspedisi=(req.nama_ekspedisi or None),
                harga_per_kg=req.harga_per_kg,
            )
        except keluar.InventoryError as e:
            raise galat(e, "Gagal mencatat bekatul keluar.")
    return {"ok": True, "pesan": await _pesan_keluar(user, r)}


class JualPkReq(BaseModel):
    kode_mil: str
    berat_kg: float
    nama_pembeli: str
    metode: str | None = None
    no_polisi: str | None = None
    nama_ekspedisi: str | None = None
    harga_per_kg: float | None = None


@router.post("/actions/jual-pk")
async def act_jual_pk(req: JualPkReq, user: User = Depends(pengguna_aksi)) -> dict:
    wajib(can_see_financials(user))
    if float(req.berat_kg or 0) <= 0:
        raise HTTPException(400, "Isi berat PK lebih dari 0.")
    if not (req.nama_pembeli or "").strip():
        raise HTTPException(400, "Isi nama pembeli.")
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await keluar.jual_pk_langsung(
                db, user=u, kode_mil=req.kode_mil, berat_kg=float(req.berat_kg),
                nama_pembeli=req.nama_pembeli.strip(), metode=req.metode,
                no_polisi=(req.no_polisi or None), nama_ekspedisi=(req.nama_ekspedisi or None),
                harga_per_kg=req.harga_per_kg,
            )
        except keluar.InventoryError as e:
            raise galat(e, "Gagal mencatat penjualan PK.")
    return {"ok": True, "pesan": await _pesan_keluar(user, r)}


async def _pesan_keluar(user: User, r) -> str:
    karung = f" ({r.jumlah_karung} karung)" if r.jumlah_karung else ""
    warn = f"\n{r.warning}" if r.warning else ""
    pesan = f"✓ Keluar *{r.kode}*: {r.label} {kg(r.berat_kg)}{karung}.{warn}"
    return pesan


# ─────────────────────────── Spesifikasi aksi ───────────────────────────

#: Nama pembeli dst. dipakai berulang di tiga aksi keluar — ditulis sekali.
def _bidang_pengiriman() -> list[dict]:
    return [
        {"name": "nama_pembeli", "label": "Nama pembeli", "type": "text"},
        {"name": "metode", "label": "Cara kirim", "type": "select", "optional": True,
         "options": [["", "— belum ditentukan —"], ["diantar", "Diantar"],
                     ["diambil", "Diambil sendiri"], ["ekspedisi", "Ekspedisi"]]},
        {"name": "no_polisi", "label": "Plat truk (bila ada)", "type": "text"},
        {"name": "nama_ekspedisi", "label": "Ekspedisi (bila ada)", "type": "text"},
        {"name": "harga_per_kg", "label": "Harga per kg (Rp, bila ada)", "type": "number"},
    ]


def spesifikasi(*, g2: bool, fin: bool) -> list[dict]:
    """Aksi inventory yang boleh dilihat pemakai ini.

    Dipanggil `miniapp.actions_menu` supaya seluruh menu tetap satu daftar
    dari satu tempat, meski isinya dirakit dari beberapa modul.
    """
    aksi: list[dict] = []

    if g2:
        aksi += [
            {"id": "catat_packing", "label": "📦 Catat packing barang jadi",
             "post": "/miniapp/actions/catat-packing",
             "hint": "Mengurangi stok karung dan menambah stok barang jadi. "
                     "Pilih prosesnya dulu — packing boleh dicatat setelah "
                     "penyosohan ditutup.",
             "fields": [
                 {"name": "kode_pol", "label": "Proses penyosohan", "type": "remote",
                  "source": "/miniapp/actions/polishing-terkini"},
                 {"name": "produk", "label": "Produk & kemasan", "type": "remote",
                  "source": "/miniapp/actions/produk-kemasan"},
                 {"name": "merk", "label": "Merk (beras saja)", "type": "remote",
                  "optional": True, "source": "/miniapp/actions/merk"},
                 {"name": "grade", "label": "Mutu (beras putih saja)", "type": "remote",
                  "optional": True, "source": "/miniapp/actions/mutu-beras"},
                 {"name": "jumlah_karung", "label": "Jumlah karung", "type": "number"},
             ]},
            {"id": "catat_bekatul", "label": "🌾 Catat bekatul (curah)",
             "post": "/miniapp/actions/catat-bekatul",
             "hint": "Bekatul dicatat per kg, bukan per karung — ia tidak dipacking.",
             "fields": [
                 {"name": "kode_pol", "label": "Proses penyosohan", "type": "remote",
                  "source": "/miniapp/actions/polishing-terkini"},
                 {"name": "berat_kg", "label": "Berat (kg)", "type": "number"},
             ]},
        ]

    if fin:
        aksi += [
            {"id": "beli_kemasan", "label": "🛒 Beli karung",
             "post": "/miniapp/actions/beli-kemasan",
             "hint": "Harga per lembar dipakai menghitung HPP kemasan "
                     "(rata-rata tertimbang) — isi bila diketahui.",
             "fields": [
                 {"name": "karung", "label": "Jenis & ukuran karung", "type": "remote",
                  "source": "/miniapp/actions/kemasan-jenis"},
                 {"name": "merk", "label": "Merk (karung beras wajib bermerk)",
                  "type": "remote", "optional": True, "source": "/miniapp/actions/merk"},
                 {"name": "jumlah", "label": "Jumlah lembar", "type": "number"},
                 {"name": "harga_per_lembar", "label": "Harga per lembar (Rp)",
                  "type": "number"},
             ]},
            {"id": "kirim_barang_jadi", "label": "🚚 Barang jadi keluar",
             "post": "/miniapp/actions/kirim-barang-jadi",
             "hint": "Stok yang kurang tidak menghalangi pencatatan — barangnya "
                     "sudah berangkat. Kekurangannya diberi peringatan supaya "
                     "selisihnya ditelusuri, bukan disembunyikan.",
             "fields": [
                 {"name": "produk", "label": "Produk & kemasan", "type": "remote",
                  "source": "/miniapp/actions/produk-kemasan"},
                 {"name": "merk", "label": "Merk (beras saja)", "type": "remote",
                  "optional": True, "source": "/miniapp/actions/merk"},
                 {"name": "grade", "label": "Mutu (beras putih saja)", "type": "remote",
                  "optional": True, "source": "/miniapp/actions/mutu-beras"},
                 {"name": "jumlah_karung", "label": "Jumlah karung", "type": "number"},
             ] + _bidang_pengiriman()},
            {"id": "kirim_bekatul", "label": "🚚 Bekatul keluar",
             "post": "/miniapp/actions/kirim-bekatul",
             "fields": [
                 {"name": "berat_kg", "label": "Berat (kg)", "type": "number"},
             ] + _bidang_pengiriman()},
            {"id": "jual_pk", "label": "💰 Jual PK langsung (Gudang 1)",
             "post": "/miniapp/actions/jual-pk",
             "hint": "PK dijual tanpa disosoh. Karung PK dihitung 50 kg, "
                     "dibulatkan ke atas.",
             "fields": [
                 {"name": "kode_mil", "label": "Proses giling asal", "type": "remote",
                  "source": "/miniapp/actions/milling-terkini"},
                 {"name": "berat_kg", "label": "Berat PK (kg)", "type": "number"},
             ] + _bidang_pengiriman()},
            {"id": "harga_byproduct", "label": "🏷️ Setel harga hasil samping",
             "post": "/miniapp/actions/harga-byproduct",
             "hint": "Dipakai menilai stok hasil samping. Harga baru tidak "
                     "menghapus yang lama — riwayatnya tersimpan.",
             "fields": [
                 {"name": "jenis", "label": "Jenis", "type": "select", "options": [
                     ["", "— belum ditentukan —"], ["bekatul", "Bekatul"],
                     ["broken", "Broken"], ["menir", "Menir"], ["reject", "Reject"]]},
                 {"name": "harga", "label": "Harga per kg (Rp)", "type": "number"},
             ]},
        ]
    return aksi
