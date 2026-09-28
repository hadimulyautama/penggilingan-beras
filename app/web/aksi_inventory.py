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

router = APIRouter(prefix="/api", tags=["api"])

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
    """Kombinasi produk × karung yang sah — satu pilihan, bukan tiga.

    ⚠ BUKAN KODE MATI, meski sejak 28 September 2026 tak ada satu pun
    spesifikasi borang yang menyebutnya. Ia melayani LEMBAR YANG SUDAH TERBUKA
    di layar orang saat versi baru terbit: borangnya memuat daftar lewat
    alamat ini, dan yang memegang telepon tak punya cara tahu bahwa borangnya
    sudah basi. Menghapusnya membuat daftar itu kosong tanpa satu pun galat,
    dan yang terbaca orang bukan "layarnya basi" melainkan "stoknya habis".

    Dihapus bersama `mutu-beras` dan cabang bentuk-lama di `PackingReq` /
    `KirimBarangJadiReq` — bertiga, sesudah cukup lama untuk yakin tak ada
    lagi lembar lama yang terbuka.
    """
    async with SessionLocal() as db:
        nama = await _nama_material(db)
    return [
        {"value": _triple(kat, m, u),
         "label": f"{KATEGORI_LABEL.get(kat, kat)} · {nama.get(m, m).lower()} {u} kg"}
        for kat, m, u in kombinasi_kemasan()
        if kat != "pk"        # PK tak dipacking di sini; ia dijual dari Gudang 1
    ]


@router.get("/actions/beras-belum-dikemas")
async def beras_belum_dikemas(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Beras yang sudah keluar mesin dan BELUM dikemas — per lot × jenis.

    Ia penunjuk borang packing, dan bentuknya menjawab keluhan pemilik 28
    September 2026: "kartu beras menunggu dipacking sudah menunjukkan mutu
    berasnya. di catat barang jadinya untuk apa mutu juga dipilih?"

    Betul, dan bukan cuma mutunya: kartu itu tahu LOT dan JENIS sekaligus.
    Dulu penunjuknya cuma kode proses, jadi jenisnya hilang di perjalanan dan
    borang menanyakannya lagi lewat dua daftar — "Produk & kemasan" yang
    menyebut beras putih/menir/reject, dan "Mutu" yang menyebut premium/medium.
    Dua pertanyaan atas satu hal yang sudah ia tunjuk, dan dua kesempatan untuk
    salah pilih.

    Nilainya `POL-…|jenis`, jadi satu pilihan membawa keduanya.

    Yang MASIH BERJALAN tak ditawarkan: angkanya belum final, dan mengemas atas
    angka yang masih bertambah membuat orang mengemas dua kali. Sama dengan
    kartu antreannya — satu aturan, dan keduanya membaca `beras_curah`.
    """
    from app.services.stok import beras_curah, nama_produk

    async with SessionLocal() as db:
        curah = await beras_curah(db, termasuk_berjalan=False)
    return [{"value": f"{b.kode_proses}|{b.jenis}",
             "label": (f"{b.kode_proses} · {nama_produk(b.jenis)} · "
                       f"{kg(b.sisa_kg)} belum dikemas")}
            for b in curah if b.sisa_kg > 0.5]


@router.get("/actions/stok-barang-jadi")
async def stok_barang_jadi(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Barang jadi yang BENAR-BENAR ada di gudang — satu baris, sekali pilih.

    Keputusan pemilik 28 September 2026, sejalan dengan borang packing yang
    dibetulkan hari yang sama. Borang "Barang jadi keluar" dulu bertanya TIGA
    kali untuk satu barang: produk+kemasan, merk, lalu mutu. Ketiganya
    pertanyaan tentang benda yang SUDAH ADA di gudang — dan daftar tiga tingkat
    atas benda yang bisa dilihat sendiri adalah tiga kesempatan untuk memilih
    kombinasi yang stoknya nol.

    Yang ditawarkan di sini hanya yang berkarung lebih dari nol. Bekatul tak
    ikut: ia curah dan punya aksinya sendiri ("Bekatul keluar"); menawarkannya
    di daftar berkarung akan membuat orang mengirim "0 karung bekatul".

    Nilainya `sku_id|std_id` — pasangan id, sebab merk & mutu yang sama bisa
    punya dua kemasan, dan kemasan yang sama bisa punya dua merk.
    """
    wajib(can_see_financials(user))
    from app.services.stok import barang_jadi_g2

    async with SessionLocal() as db:
        bj_ = await barang_jadi_g2(db)
    return [{"value": f"{k['sku_id']}|{k['std_id'] or ''}",
             "label": f"{k['nama']} · {k['kemasan']} · {k['karung']} karung"}
            for k in bj_.produk + bj_.samping if k.get("karung")]


@router.get("/actions/kemasan-untuk")
async def kemasan_untuk(induk: str = "",
                        user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Karung yang sah UNTUK BARANG YANG SUDAH DIPILIH — jenis dan ukurannya.

    "cukup jenis kemasannya dan ukuran kemasannya" (pemilik, 28 September
    2026). Daftar lamanya mengulang nama barangnya di tiap baris ("Beras putih
    · karung laminasi 25 kg", delapan kali) padahal barangnya sudah ditunjuk —
    dan daftar yang mengulang hal yang sama di tiap baris memaksa mata membaca
    bagian yang berbeda saja, yang justru tercetak paling belakang.

    Bergantung pada penunjuknya (`induk`), bukan berdiri sendiri: karung 5 kg
    sah untuk beras B dan tidak untuk sebagian yang lain, dan daftar yang
    menawarkan seluruh kemungkinan adalah persis kesalahan yang medan ini
    menggantikan.
    """
    from app.services.stok import kategori_dan_mutu

    jenis = (induk or "").split("|")[-1].strip().lower()
    if not jenis:
        return []
    kategori, _ = kategori_dan_mutu(jenis)
    async with SessionLocal() as db:
        nama = await _nama_material(db)
    return [{"value": f"{m}|{u}", "label": f"{nama.get(m, m)} {u} kg"}
            for _kat, m, u in kombinasi_kemasan(kategori)]


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
    """Standar mutu beras putih. Beras B sengaja tidak punya — jangan diisi.

    ⚠ BUKAN KODE MATI — lihat catatan di `produk_kemasan`. Sejak 28 September
    2026 mutu tak lagi ditanyakan borang mana pun (ia terbawa penunjuknya),
    tetapi lembar lama yang masih terbuka memuat daftarnya dari sini.
    """
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
    """Bentuk BARU sejak 28 September 2026: `sumber` + `kemasan`.

    Bentuk lama (`kode_pol` + `produk` + `grade`) tetap diterima dan tidak
    dibuang. Halaman di ponsel berumur panjang: lembar yang sudah terbuka di
    layar orang saat versi baru terbit akan mengirim bentuk lama, dan yang
    menekan Simpan tak punya cara mengetahui bahwa borangnya sudah basi. Yang
    berhenti cuma MENAWARKANNYA.
    """

    jumlah_karung: int
    sumber: str | None = None         # "POL-…|jenis"
    kemasan: str | None = None        # "material|ukuran"
    merk: str | None = None
    # ── bentuk lama ──
    kode_pol: str | None = None
    produk: str | None = None         # "kategori|material|ukuran"
    grade: str | None = None


def _urai_packing(req: PackingReq) -> tuple[str, str, str | None, str, int]:
    """(kode_pol, kategori, mutu, material, ukuran) dari kedua bentuk kiriman."""
    from app.services.stok import kategori_dan_mutu

    if req.sumber:
        bagian = req.sumber.split("|")
        if len(bagian) != 2 or not bagian[0].strip():
            raise HTTPException(400, "Pilih dulu beras yang dikemas.")
        kode_pol, jenis = bagian[0].strip(), bagian[1].strip().lower()
        kategori, mutu = kategori_dan_mutu(jenis)
        pasang = (req.kemasan or "").split("|")
        if len(pasang) != 2 or not pasang[1].isdigit():
            raise HTTPException(400, "Pilih karung dan ukurannya.")
        material, ukuran = pasang[0], int(pasang[1])
        # Diperiksa ulang meski daftarnya berasal dari server: yang mengirim
        # POST adalah perangkat, dan isian perangkat tak pernah jadi alasan
        # untuk melewati pemeriksaan.
        try:
            kms._validate_kemasan(kategori, material, ukuran)
        except kms.InventoryError as e:
            raise galat(e, "Kombinasi kemasan tidak sah.")
        return kode_pol, kategori, mutu, material, ukuran

    if not req.kode_pol:
        raise HTTPException(400, "Pilih dulu beras yang dikemas.")
    kategori, material, ukuran = _urai_triple(req.produk or "")
    mutu = (req.grade or None) if kategori == "beras_putih" else None
    return req.kode_pol, kategori, mutu, material, ukuran


@router.post("/actions/catat-packing")
async def act_catat_packing(req: PackingReq,
                            user: User = Depends(pengguna_aksi)) -> dict:
    from app.web.api import _is_g2_operator
    wajib(await _is_g2_operator(user) or can_see_financials(user))
    kode_pol, kategori, mutu, material, ukuran = _urai_packing(req)
    if int(req.jumlah_karung or 0) <= 0:
        raise HTTPException(400, "Isi jumlah karung lebih dari 0.")

    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await bj.catat_packing(
                db, user=u, kode_pol=kode_pol, kategori=kategori,
                grade=mutu,
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
    from app.web.api import _is_g2_operator
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
    """Bentuk BARU sejak 28 September 2026: `stok` = `sku_id|std_id`.

    Bentuk lama (`produk` + `merk` + `grade`) tetap diterima — halaman di ponsel
    berumur panjang, dan lembar yang sudah terbuka saat versi baru terbit akan
    mengirimnya tanpa pemakainya tahu.
    """

    jumlah_karung: int
    nama_pembeli: str
    stok: str | None = None           # "sku_id|std_id"
    metode: str | None = None
    # ── bentuk lama ──
    produk: str | None = None         # "kategori|material|ukuran"
    merk: str | None = None
    grade: str | None = None
    no_polisi: str | None = None
    nama_ekspedisi: str | None = None
    harga_per_kg: float | None = None


async def _urai_stok_bj(nilai: str) -> tuple[str, str | None, str | None, str, int]:
    """(kategori, mutu, merk, material, ukuran) dari satu pilihan `sku_id|std_id`.

    Dibongkar kembali jadi lima bagian — bukan diteruskan sebagai id — supaya
    `keluar.kirim_finished_goods` tetap satu pintu untuk kedua bentuk kiriman
    dan tak perlu jalur kedua yang bisa berbeda perlakuan.
    """
    from app.penggilingan.inventory.models import (Brand, PackageSize,
                                                   PackagingMaterial, ProductSku,
                                                   RiceQualityStandard)

    bagian = (nilai or "").split("|")
    if not bagian[0].isdigit():
        raise HTTPException(400, "Pilih dulu barang yang keluar.")
    sku_id = int(bagian[0])
    std_id = int(bagian[1]) if len(bagian) > 1 and bagian[1].isdigit() else None
    async with SessionLocal() as db:
        baris = (await db.execute(
            select(ProductSku.kategori, PackagingMaterial.kode,
                   PackageSize.ukuran_kg, Brand.nama)
            .join(PackagingMaterial,
                  PackagingMaterial.id == ProductSku.packaging_material_id)
            .join(PackageSize, PackageSize.id == ProductSku.package_size_id)
            .join(Brand, Brand.id == ProductSku.brand_id, isouter=True)
            .where(ProductSku.id == sku_id))).first()
        if baris is None:
            raise HTTPException(400, "Barang itu tidak ada lagi di daftar.")
        kategori, material, ukuran, merk = baris
        mutu = None
        if std_id is not None:
            mutu = (await db.execute(select(RiceQualityStandard.kode).where(
                RiceQualityStandard.id == std_id))).scalar_one_or_none()
    return kategori, mutu, merk, material, int(ukuran)


@router.post("/actions/kirim-barang-jadi")
async def act_kirim_barang_jadi(req: KirimBarangJadiReq,
                                user: User = Depends(pengguna_aksi)) -> dict:
    wajib(can_see_financials(user))
    if req.stok:
        kategori, mutu, merk, material, ukuran = await _urai_stok_bj(req.stok)
    else:
        # Bentuk lama — lembar yang sudah terbuka di layar orang saat versi
        # baru terbit. Yang berhenti cuma MENAWARKANNYA.
        kategori, material, ukuran = _urai_triple(req.produk or "")
        mutu = (req.grade or None) if kategori == "beras_putih" else None
        merk = req.merk or None
    if int(req.jumlah_karung or 0) <= 0:
        raise HTTPException(400, "Isi jumlah karung lebih dari 0.")
    if not (req.nama_pembeli or "").strip():
        raise HTTPException(400, "Isi nama pembeli.")

    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await keluar.kirim_finished_goods(
                db, user=u, kategori=kategori,
                grade=mutu if kategori == "beras_putih" else None,
                brand_nama=merk if kategori in KATEGORI_BERMERK else None,
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

    Dipanggil `api.actions_menu` supaya seluruh menu tetap satu daftar
    dari satu tempat, meski isinya dirakit dari beberapa modul.
    """
    aksi: list[dict] = []

    if g2:
        aksi += [
            {"id": "catat_packing", "label": "📦 Catat packing barang jadi",
             "post": "/api/actions/catat-packing",
             "hint": "Mengurangi stok karung dan menambah stok barang jadi. "
                     "Pilih prosesnya dulu — packing boleh dicatat setelah "
                     "penyosohan ditutup.",
             "fields": [
                 # ── SATU penunjuk yang membawa lot DAN jenisnya ──
                 #
                 # Keluhan pemilik 28 September 2026: "kartu beras menunggu
                 # dipacking sudah menunjukkan mutu berasnya. di catat barang
                 # jadinya untuk apa mutu juga dipilih? di bagian pemilihan
                 # produk dan kemasan pun ada keterangan beras putih, menir,
                 # reject, dll. cukup jenis kemasannya dan ukuran kemasannya."
                 #
                 # Borang ini dulu bertanya EMPAT kali untuk satu pekerjaan:
                 # prosesnya, produk+kemasannya, merknya, dan mutunya. Tiga
                 # dari empat sudah terjawab oleh kartu yang ditekan orangnya.
                 # Sekarang penunjuknya satu dan membawa keduanya (`POL-…|jenis`),
                 # jadi dari kartu ia terkunci dan tak ada yang perlu dipilih
                 # lagi selain kemasan dan jumlahnya.
                 {"name": "sumber", "label": "Beras yang dikemas", "type": "remote",
                  "source": "/api/actions/beras-belum-dikemas",
                  "kosong": "Tidak ada beras yang menunggu dipacking. Catat "
                            "hasil penyosohannya dulu."},
                 {"name": "kemasan", "label": "Karung & ukurannya", "type": "remote",
                  "induk": "sumber", "source": "/api/actions/kemasan-untuk",
                  "kosong": "Tak ada kemasan yang sah untuk barang ini."},
                 {"name": "merk", "label": "Merk (beras saja)", "type": "remote",
                  "optional": True, "source": "/api/actions/merk"},
                 {"name": "jumlah_karung", "label": "Jumlah karung", "type": "number"},
             ]},
            {"id": "catat_bekatul", "label": "🌾 Catat bekatul (curah)",
             "post": "/api/actions/catat-bekatul",
             "hint": "Bekatul dicatat per kg, bukan per karung — ia tidak dipacking.",
             "fields": [
                 {"name": "kode_pol", "label": "Proses penyosohan", "type": "remote",
                  "source": "/api/actions/polishing-terkini"},
                 {"name": "berat_kg", "label": "Berat (kg)", "type": "number"},
             ]},
        ]

    if fin:
        aksi += [
            {"id": "beli_kemasan", "label": "🛒 Beli karung",
             "post": "/api/actions/beli-kemasan",
             "hint": "Harga per lembar dipakai menghitung HPP kemasan "
                     "(rata-rata tertimbang) — isi bila diketahui.",
             "fields": [
                 {"name": "karung", "label": "Jenis & ukuran karung", "type": "remote",
                  "source": "/api/actions/kemasan-jenis"},
                 {"name": "merk", "label": "Merk (karung beras wajib bermerk)",
                  "type": "remote", "optional": True, "source": "/api/actions/merk"},
                 {"name": "jumlah", "label": "Jumlah lembar", "type": "number"},
                 {"name": "harga_per_lembar", "label": "Harga per lembar (Rp)",
                  "type": "number"},
             ]},
            {"id": "kirim_barang_jadi", "label": "🚚 Barang jadi keluar",
             "post": "/api/actions/kirim-barang-jadi",
             "hint": "Stok yang kurang tidak menghalangi pencatatan — barangnya "
                     "sudah berangkat. Kekurangannya diberi peringatan supaya "
                     "selisihnya ditelusuri, bukan disembunyikan.",
             "fields": [
                 # SATU pilihan, dari stok yang benar-benar ada (28 September
                 # 2026). Tiga daftar bertingkat — produk+kemasan, merk, mutu —
                 # adalah tiga kesempatan memilih kombinasi yang stoknya nol,
                 # atas benda yang sebenarnya bisa dilihat sendiri di gudang.
                 {"name": "stok", "label": "Barang yang keluar", "type": "remote",
                  "source": "/api/actions/stok-barang-jadi",
                  "kosong": "Tidak ada barang jadi berkarung di gudang. "
                            "Bekatul curah keluar lewat 'Bekatul keluar'."},
                 {"name": "jumlah_karung", "label": "Jumlah karung", "type": "number"},
             ] + _bidang_pengiriman()},
            {"id": "kirim_bekatul", "label": "🚚 Bekatul keluar",
             "post": "/api/actions/kirim-bekatul",
             "fields": [
                 {"name": "berat_kg", "label": "Berat (kg)", "type": "number"},
             ] + _bidang_pengiriman()},
            {"id": "jual_pk", "label": "💰 Jual PK langsung (Gudang 1)",
             "post": "/api/actions/jual-pk",
             "hint": "PK dijual tanpa disosoh. Karung PK dihitung 50 kg, "
                     "dibulatkan ke atas.",
             "fields": [
                 {"name": "kode_mil", "label": "Proses giling asal", "type": "remote",
                  "source": "/api/actions/milling-terkini"},
                 {"name": "berat_kg", "label": "Berat PK (kg)", "type": "number"},
             ] + _bidang_pengiriman()},
            {"id": "harga_byproduct", "label": "🏷️ Setel harga hasil samping",
             "post": "/api/actions/harga-byproduct",
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
