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
from app.models import OutgoingItem, User
from app.penggilingan.inventory import finished_goods as bj
from app.penggilingan.inventory import outgoing as keluar
from app.penggilingan.inventory import packaging as kms
from app.services import barang_keluar as bk
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


@router.get("/actions/karung-pabrik-tersedia")
async def karung_pabrik_tersedia(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Kombinasi karung milik PABRIK yang stoknya > 0 — sumber "Pindah
    kepemilikan karung" (`act_pindah_kepemilikan_karung`).

    Nilainya `kode|ukuran|merk` (merk boleh kosong) — KODE/nama, bukan id
    mentah, pola yang sama dengan `kemasan-jenis` (dipakai "Beli karung").
    Tombol per-baris di `/stok-karung` (`hmu_tampilan/_stok.html`'s
    `karung_blok`) membangun `nilai=` dari field yang SAMA (`kode`, `ukuran`,
    `merk`) yang sudah ada di baris `stok_kemasan_rinci` — keduanya WAJIB
    menunjuk kombinasi yang sama persis, sebab `isiDariBaris` (`aksi.js`)
    mencocokkan nilai APA ADANYA terhadap pilihan picker ini.
    """
    wajib(can_see_financials(user))
    async with SessionLocal() as db:
        baris = await kms.stok_kemasan_rinci(db, pelanggan_id=None)
    return [{"value": f"{b['kode']}|{b['ukuran']}|{b['merk'] or ''}",
             "label": f"{b['merk'] + ' ' if b['merk'] else ''}{b['nama']} "
                      f"{b['ukuran']}kg · sisa {b['lembar']} lembar"}
            for b in baris if b["lembar"] > 0]


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

    Yang ditawarkan di sini hanya yang berkarung lebih dari nol — dan sejak 28
    September 2026 kalimat itu memikul lebih banyak daripada dulu.

    Bekatul kini punya DUA jalan (keputusan pemilik): sebagian dijual curah,
    sebagian dikarungi 40 kg. Saringan "berkarung > 0" memilah keduanya dengan
    sendirinya — baris karungnya ikut ke daftar ini, baris curahnya tidak,
    sebab ia bernilai `karung: 0` dan punya aksinya sendiri ("Bekatul keluar").
    Itu bukan kebetulan yang beruntung: menawarkan yang curah di daftar
    berkarung akan membuat orang mengirim "0 karung bekatul".

    Nilainya `sku_id|std_id` — pasangan id, sebab merk & mutu yang sama bisa
    punya dua kemasan, dan kemasan yang sama bisa punya dua merk.
    """
    wajib(can_see_financials(user))
    from app.services.stok import barang_jadi_g2

    async with SessionLocal() as db:
        bj_ = await barang_jadi_g2(db)
    # ⚠ BARANG TITIPAN (pesanan jasa) TIDAK DITAWARKAN. Barangnya milik
    # pelanggan; yang boleh mengeluarkannya pemiliknya lewat pengambilan
    # jasa — bukan pabrik lewat penjualan. `barang_jadi_g2()` kini
    # mendaftar keduanya (keputusan pemilik 6 Oktober 2026), jadi
    # penyaringnya WAJIB di sini, sama seperti `barang_bisa_keluar`.
    return [{"value": f"{k['sku_id']}|{k['std_id'] or ''}",
             "label": f"{k['nama']} · {k['kemasan']} · {k['karung']} karung"}
            for k in bj_.produk + bj_.samping
            if k.get("karung") and k.get("jasa_id") is None]


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
                jumlah=int(req.jumlah), brand_nama=(req.merk or None))
        except kms.InventoryError as e:
            raise galat(e, "Gagal mencatat pembelian karung.")

    merk = f"{r.brand_nama} " if r.brand_nama else ""
    pesan = (f"✓ Beli karung *{merk}{r.material_nama} {r.ukuran}kg* × "
             f"{rp(r.purchase.jumlah_lembar)} lembar ({r.purchase.kode}).\n"
             f"• Stok kini: {rp(r.stok_baru)} lembar")
    return {"ok": True, "pesan": pesan}


class PindahKepemilikanKarungReq(BaseModel):
    karung: str                       # "material_kode|ukuran|merk_or_kosong"
    pelanggan: str                    # pelanggan_id
    jumlah: int


@router.post("/actions/pindah-kepemilikan-karung")
async def act_pindah_kepemilikan_karung(req: PindahKepemilikanKarungReq,
                                        user: User = Depends(pengguna_aksi)) -> dict:
    """Pindah SEBAGIAN stok karung pabrik ke milik satu KONTAK pelanggan —
    arah kebalikan "Pindah kepemilikan produk" (lihat catatan panjang di
    `packaging.pindah_kepemilikan_karung`)."""
    wajib(can_see_financials(user))
    bagian = (req.karung or "").split("|")
    if len(bagian) != 3 or not bagian[1].isdigit():
        raise HTTPException(400, "Pilih kombinasi karung pabrik dulu.")
    material_kode, ukuran, merk = bagian[0], int(bagian[1]), (bagian[2] or None)
    if not (req.pelanggan or "").isdigit():
        raise HTTPException(400, "Pilih pelanggan tujuan dulu.")
    if int(req.jumlah or 0) <= 0:
        raise HTTPException(400, "Isi jumlah lembar yang dipindah lebih dari 0.")

    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            jumlah = await kms.pindah_kepemilikan_karung(
                db, user=u, material_kode=material_kode, ukuran=ukuran,
                brand_nama=merk, pelanggan_id=int(req.pelanggan),
                jumlah_lembar=int(req.jumlah))
        except kms.InventoryError as e:
            raise galat(e, "Gagal memindahkan kepemilikan karung.")
    pesan = f"✓ {jumlah} lembar karung kini milik pelanggan."
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


class BrokenReq(BaseModel):
    kode_pol: str
    berat_kg: float


@router.post("/actions/catat-broken")
async def act_catat_broken(req: BrokenReq,
                           user: User = Depends(pengguna_aksi)) -> dict:
    """Catat broken curah — sebangun `act_catat_bekatul`. Keputusan pemilik
    6 Oktober 2026: ini langkah WAJIB sebelum broken bisa dipindah ke silo
    broken (`pindah_broken_silo`) — baris yang lahir di sini SUMBER-nya."""
    from app.web.api import _is_g2_operator
    wajib(await _is_g2_operator(user) or can_see_financials(user))
    if float(req.berat_kg or 0) <= 0:
        raise HTTPException(400, "Isi berat broken lebih dari 0.")
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            berat = await bj.catat_broken(
                db, user=u, kode_pol=req.kode_pol, berat_kg=float(req.berat_kg))
        except bj.InventoryError as e:
            raise galat(e, "Gagal mencatat broken.")
    pesan = (f"✓ Broken {kg(berat)} tercatat (curah) — pindahkan ke silo "
             "broken untuk disosoh ulang, lewat 'Pindah broken ke silo'.")
    return {"ok": True, "pesan": pesan}


@router.get("/actions/produk-jasa-tersedia")
async def produk_jasa_tersedia(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Barang milik pesanan jasa yang BISA dipindah kepemilikannya ke pabrik.

    Hanya yang SUDAH TERCATAT: barang jadi berkarung (`finished_goods_stock`,
    lewat `barang_jadi_g2`) dan broken/bekatul yang sudah dicatat curah
    (`byproduct_stock`, lewat `hitung_stok_broken_curah`/`hitung_stok_
    bekatul`). Hasil mesin yang masih mentah tak punya baris untuk dipindah —
    lihat catatan panjang di `pindah_kepemilikan_barang_jadi`.

    Nilainya BERAWALAN `bj:`/`cr:`, pola yang sama dengan `barang-bisa-keluar`:
    awalan menentukan jalur (karung atau kg) dan tabel yang disentuh
    `act_pindah_kepemilikan_produk`. Bekatul IKUT di sini sejak 6 Oktober
    2026 — PEMBALIKAN keputusan pemilik 12 (bekatul dulu otomatis milik
    pabrik, sekarang mengikuti pola broken: tetap milik pesanan sampai
    dipindah). Baris `cr:bekatul|...`-nya sebangun persis `cr:broken|...`,
    cuma jenisnya beda — lihat `act_pindah_kepemilikan_produk` untuk
    dispatch-nya.

    ⚠ Baris `cr:` DIKELOMPOKKAN PER PELANGGAN (`jasa_ids_per_pelanggan_
    dengan_hasil`), bukan per pesanan — sama seperti `/stok-produk-jasa`.
    Baris `bj:` TETAP per pesanan: kartu kemasannya (`barang_jadi_g2`)
    sendiri tak pernah menyatukan dua pesanan jadi satu baris, jadi tak ada
    yang perlu disatukan di sini.
    """
    wajib(can_see_financials(user))
    from app.models import Pelanggan
    from app.penggilingan.inventory.finished_goods import (hitung_stok_bekatul,
                                                            hitung_stok_broken_curah)
    from app.services.jasa import jasa_ids_per_pelanggan_dengan_hasil
    from app.services.stok import barang_jadi_g2

    out: list[dict] = []
    async with SessionLocal() as db:
        bj_ = await barang_jadi_g2(db)
        for k in bj_.produk + bj_.samping:
            jid = k.get("jasa_id")
            if jid is None or not k.get("karung"):
                continue
            out.append({
                "value": f"bj:{k['sku_id']}|{k['std_id'] or ''}|{jid}",
                "label": f"{k.get('pemilik') or '?'} · {k['nama']} · "
                         f"sisa {k['karung']} karung (isi dalam karung)"})

        # Broken & bekatul curah DIKELOMPOKKAN PER PELANGGAN, bukan per
        # pesanan — sama dengan `/stok-produk-jasa` (lihat docstring fungsi
        # di atas serta `jasa_ids_per_pelanggan_dengan_hasil`): nilainya
        # harus COCOK PERSIS dengan `nilai=cr:broken|...`/`cr:bekatul|...`
        # yang dikirim tombol per-kartu halaman itu, sebab `aksi.js`
        # mencocokkannya apa adanya, bukan menguraikannya.
        jasa_per_pelanggan = await jasa_ids_per_pelanggan_dengan_hasil(db)
        nama_pelanggan = {pid: n for pid, n in (await db.execute(
            select(Pelanggan.id, Pelanggan.nama_pelanggan)
            .where(Pelanggan.id.in_(jasa_per_pelanggan or {0}))
        )).all()}
        for pelanggan_id, jasa_ids in jasa_per_pelanggan.items():
            nama = nama_pelanggan.get(pelanggan_id) or "?"
            for jenis, hitung, label in (
                ("broken", hitung_stok_broken_curah, "Broken"),
                ("bekatul", hitung_stok_bekatul, "Bekatul"),
            ):
                sisa = await hitung(db, jasa_id=jasa_ids)
                if sisa > 0.5:
                    out.append({
                        "value": f"cr:{jenis}|{','.join(map(str, jasa_ids))}",
                        "label": f"{nama} · {label} (curah) · "
                                 f"sisa {kg(sisa)} kg (isi dalam kg)"})
    return out


class PindahKepemilikanProdukReq(BaseModel):
    item: str
    jumlah: float


@router.post("/actions/pindah-kepemilikan-produk")
async def act_pindah_kepemilikan_produk(req: PindahKepemilikanProdukReq,
                                        user: User = Depends(pengguna_aksi)) -> dict:
    """Pindah kepemilikan barang milik pesanan jasa ke pabrik — boleh
    sebagian. Lihat catatan panjang di `pindah_kepemilikan_barang_jadi` &
    `pindah_kepemilikan_broken_curah` untuk kenapa ini aman dilakukan
    sebagian walau sebagian sisa pesanan sudah diambil atau dipindah silo."""
    wajib(can_see_financials(user))
    if float(req.jumlah or 0) <= 0:
        raise HTTPException(400, "Isi jumlah yang dipindah lebih dari 0.")
    tipe, _, sisa = (req.item or "").partition(":")
    bagian = sisa.split("|")
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            if tipe == "bj" and len(bagian) == 3:
                sku_id_s, std_id_s, jasa_id_s = bagian
                berat = await bj.pindah_kepemilikan_barang_jadi(
                    db, user=u, sku_id=int(sku_id_s),
                    standard_id=(int(std_id_s) if std_id_s else None),
                    jasa_id=int(jasa_id_s), karung=int(req.jumlah))
                pesan = f"✓ {int(req.jumlah)} karung ({kg(berat)}) kini milik pabrik."
            elif tipe == "cr" and len(bagian) == 2:
                # `jasa_id_s` boleh satu id (dari picker katalog umum, per
                # pesanan) atau beberapa id dipisah koma (dari tombol per
                # KARTU PELANGGAN di /stok-produk-jasa, yang menjumlah
                # beberapa pesanan satu pelanggan — lihat `layar_produk.
                # halaman_stok_produk_jasa`). `pindah_kepemilikan_broken_
                # curah`/`pindah_kepemilikan_bekatul_curah` menerima keduanya.
                #
                # `jenis` DIBACA sekarang, bukan dibuang — sejak bekatul ikut
                # jalur curah ini (6 Oktober 2026) dua fungsi berbeda perlu
                # dipilih, sebangun pola `tipe` di atas (bj vs cr).
                jenis, jasa_id_s = bagian
                id_list = [int(x) for x in jasa_id_s.split(",") if x]
                jid = id_list[0] if len(id_list) == 1 else id_list
                if jenis == "broken":
                    berat = await bj.pindah_kepemilikan_broken_curah(
                        db, user=u, jasa_id=jid, berat_kg=float(req.jumlah))
                elif jenis == "bekatul":
                    berat = await bj.pindah_kepemilikan_bekatul_curah(
                        db, user=u, jasa_id=jid, berat_kg=float(req.jumlah))
                else:
                    raise HTTPException(400, f"Jenis curah tak dikenal: {jenis}.")
                pesan = f"✓ {kg(berat)} {jenis} curah kini milik pabrik."
            else:
                raise HTTPException(400, "Pilih barang yang mau dipindah dulu.")
        except bj.InventoryError as e:
            raise galat(e, "Gagal memindahkan kepemilikan.")
    return {"ok": True, "pesan": pesan}


# ─────────────────────────── Barang keluar ───────────────────────────
#
# ⚠ TIGA AKSI DIBUANG 28 September 2026 — `kirim_barang_jadi`, `kirim_bekatul`,
# `jual_pk`. Keputusan pemilik, atas usul QA, dan sebabnya bukan kerapian:
#
# Ketiganya mengerjakan hal yang SAMA dengan rantai barang keluar berperintah,
# tetapi tanpa perintah dan tanpa verifikasi. Dibiarkan hidup, rantai itu jadi
# SUKARELA: barang bisa keluar lewat pintu belakang, dan angka barang keluar
# berhenti bisa dipercaya — sebagian lewat perintah, sebagian tidak, dan tak
# ada yang tahu mana yang mana. Itu persis yang dilarang "satu pekerjaan, satu
# pintu".
#
# Dan ketiganya juga yang membuat satu truk berisi beras + broken + menir
# melahirkan TIGA kode OUT- yang berbeda: masing-masing memanggil pembuat
# record sendiri untuk SATU jenis barang. Skemanya sudah satu-ke-banyak sejak
# awal; yang tak pernah memakainya adalah layarnya.
#
# Mengirim satu barang saja tetap bisa: perintah dengan satu baris.
# Layanannya di `app.services.barang_keluar`.

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


# ── Daftar untuk medan `remote` rantai barang keluar ──

def _ringkas_perintah(rec, items) -> str:
    macam = len(items)
    total = sum(float(i.berat_perintah_kg or 0) for i in items)
    sudah = sum(float(i.berat_kg or 0) for i in items)
    label = f"{rec.kode} · {rec.nama_pembeli or '?'} · {macam} macam · {kg(total)}"
    if sudah > 0.5:
        label += f" · sudah dimuat {kg(sudah)}"
    if rec.no_polisi:
        label += f" · {rec.no_polisi}"
    return label


@router.get("/actions/perintah-terbuka")
async def perintah_terbuka(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Perintah yang menunggu dimuat — dibaca operator DAN Admin.

    Satu daftar untuk dua peran, sebab yang ditanyakan sama: perintah mana yang
    belum berangkat. Dua daftar yang disusun terpisah akan berselisih isinya
    pada perubahan berikutnya, dan yang berselisih adalah daftar pekerjaan.
    """
    from app.penggilingan.inventory.models import OUT_PERINTAH

    async with SessionLocal() as db:
        baris = await bk.daftar(db, status=(OUT_PERINTAH,))
    return [{"value": str(r.id), "label": _ringkas_perintah(r, it)}
            for r, it in baris]


@router.get("/actions/perintah-bisa-ditambah")
async def perintah_bisa_ditambah(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Transaksi yang BELUM DIVERIFIKASI — `perintah` maupun `dimuat`.

    Keputusan pemilik 29 September 2026: "selagi belum diverifikasi dan
    dianggap selesai, kartu barang keluar masih bisa ditambahkan."

    Berbeda dari `/actions/perintah-terbuka`, yang hanya memuat yang belum
    dimuat — itu daftar PEKERJAAN operator, dan perintah yang truknya sudah
    berangkat bukan pekerjaan siapa pun lagi. Yang ini daftar transaksi yang
    angkanya masih boleh berubah, dan keduanya sengaja tak disatukan: satu
    daftar untuk dua pertanyaan yang berbeda akan menawarkan pekerjaan yang
    sudah selesai kepada orang yang mencari pekerjaan.

    Keadaannya ikut tertulis di label — yang menambah barang ke muatan yang
    SUDAH berangkat perlu tahu bahwa stoknya berkurang sekarang juga.
    """
    wajib(can_see_financials(user))
    from app.penggilingan.inventory.models import OUT_DIMUAT, OUT_HIDUP

    async with SessionLocal() as db:
        baris = await bk.daftar(db, status=OUT_HIDUP)
    out = []
    for r, it in baris:
        label = _ringkas_perintah(r, it)
        if r.status == OUT_DIMUAT:
            label += " · SUDAH DIMUAT, tambahan ikut keluar"
        out.append({"value": str(r.id), "label": label})
    return out


@router.get("/actions/keluar-dimuat")
async def keluar_dimuat(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Muatan yang sudah berangkat dan menunggu verifikasi Admin."""
    wajib(can_see_financials(user))
    from app.penggilingan.inventory.models import OUT_DIMUAT

    async with SessionLocal() as db:
        baris = await bk.daftar(db, status=(OUT_DIMUAT,))
    out = []
    for r, it in baris:
        total = sum(float(i.berat_kg or 0) for i in it)
        kurang = sum(max(float(i.berat_perintah_kg or 0) - float(i.berat_kg or 0), 0)
                     for i in it)
        label = f"{r.kode} · {r.nama_pembeli or '?'} · dimuat {kg(total)}"
        # Selisihnya disebut DI DAFTAR, bukan cuma di dalam kartunya: yang
        # memilih dari daftar inilah yang memutuskan mana yang perlu diperiksa
        # lebih dulu.
        if kurang > 0.5:
            label += f" · kurang {kg(kurang)} dari perintah"
        out.append({"value": str(r.id), "label": label})
    return out


@router.get("/actions/baris-perintah")
async def baris_perintah(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Tiap BARANG di tiap perintah yang belum berangkat.

    Satuannya ikut tertulis di label — karung untuk yang berkarung, kg untuk
    yang curah — sebab kotak isiannya satu dan operator yang menentukan
    artinya. Label tanpa satuan mengundang 200 kg diketik sebagai 200 karung.
    """
    from app.penggilingan.inventory.models import OUT_PERINTAH

    async with SessionLocal() as db:
        baris = await bk.daftar(db, status=(OUT_PERINTAH,))
        out = []
        for r, items in baris:
            for it in items:
                b = bk.BarisPerintah(
                    tipe=it.item_type, sku_id=it.product_sku_id,
                    std_id=it.rice_quality_standard_id, jenis=it.jenis_byproduct,
                    milling_process_id=it.milling_process_id)
                _, nama = await bk.tersedia(db, b, abaikan_pesanan=True)
                if it.item_type == "finished_goods":
                    minta = f"{it.jumlah_karung_perintah or 0} karung"
                else:
                    minta = kg(float(it.berat_perintah_kg or 0))
                sudah = (f" · sudah {kg(float(it.berat_kg))}"
                         if float(it.berat_kg or 0) > 0.5 else "")
                out.append({"value": str(it.id),
                            "label": f"{r.kode} · {nama} · perintah {minta}{sudah}"})
    return out


@router.get("/actions/barang-bisa-keluar")
async def barang_bisa_keluar(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """SATU daftar berisi seluruh yang bisa keluar pabrik — barang jadi DAN PK.

    Permintaan pemilik 29 September 2026: "admin bisa memilih barang yang akan
    keluar beserta jumlahnya. lalu bisa klik tambah item lalu keluar field baru
    untuk memilih item lain beserta jumlahnya, karena barang keluar bisa multi
    item."

    Satu daftar, bukan dua medan bergantian: yang dipikirkan Admin "apa yang
    naik truk ini", bukan "barang jadi atau PK". Dua daftar terpisah menuntut ia
    menerjemahkan dulu pertanyaannya sendiri sebelum bisa menjawabnya.

    Nilainya BERAWALAN — `bj:`, `cr:`, atau `pk:` — dan awalan itu yang
    menentukan SATUAN jumlahnya: barang jadi dihitung per karung, curah dan PK
    per kilogram. Tanpa awalan, "100" pada satu baris berarti 100 karung dan
    pada baris lain 100 kg, dan yang membedakan cuma ingatan orang yang
    mengetiknya.

    Satuannya ikut tertulis di tiap label, sebab kotak jumlahnya satu dan tak
    bisa berganti tulisan mengikuti pilihan.

    ⛔ CURAH SEMPAT TERLEWAT SELURUHNYA, dan ini kelas kesalahan yang layak
    diingat: dua perubahan yang masing-masing benar bisa membuka lubang di
    antaranya. Aksi lama "Bekatul keluar" dibuang 28 September (pintu lama
    ditutup), dan daftar ini melewati barang tanpa karung dengan alasan "curah
    punya jalur sendiri" (pintu baru melewatinya) — padahal jalur sendiri itu
    sudah tidak ada. Akibatnya bekatul curah masuk terus dan TAK PERNAH BISA
    KELUAR: angka stoknya hanya bisa naik, tanpa satu pun pesan galat.
    Sisa sistemnya tak pernah rusak — `byproduct_curah` tetap sah, layar
    barang keluar masih menggambarnya, stoknya masih dikurangi. Yang hilang
    cuma pintunya. Laporan operator, 30 September 2026.
    """
    wajib(can_see_financials(user))
    from app.services.stok import barang_jadi_g2, pk_gudang1

    out: list[dict] = []
    async with SessionLocal() as db:
        bj_ = await barang_jadi_g2(db)
        for k in bj_.produk + bj_.samping:
            # ⚠ BARANG TITIPAN (pesanan jasa) TIDAK DITAWARKAN — sama
            # seperti PK jasa di bawah. `barang_jadi_g2()` kini mendaftar
            # keduanya (keputusan pemilik 6 Oktober 2026); borang penjualan
            # ini WAJIB menyaringnya sendiri. Disembunyikan di sini, bukan
            # ditolak di akhir — lihat alasannya pada PK jasa di bawah.
            if k.get("jasa_id") is not None:
                continue
            # Yang membedakan curah dari berkarung `sku_id`, BUKAN jumlah
            # karungnya. Kartu berkarung yang kebetulan tinggal nol karung
            # masih punya SKU dan tak boleh berubah jadi baris curah —
            # satuannya akan berganti diam-diam, dan "40" berarti 40 kg.
            if k.get("sku_id") is None:
                if float(k.get("kg") or 0) <= 0:
                    continue
                out.append({
                    "value": f"cr:{k['jenis']}",
                    "label": (f"{k['nama']} curah · {kg(k['kg'])} tersedia"
                              " (isi dalam kg)")})
                continue
            if not k.get("karung"):
                continue
            out.append({
                "value": f"bj:{k['sku_id']}|{k['std_id'] or ''}",
                "label": f"{k['nama']} · {k['kemasan']} · {k['karung']} karung"})
        for l in await pk_gudang1(db):
            if l.tersedia <= 0:
                continue
            # ⚠ PK JASA TIDAK DITAWARKAN. Barangnya milik pelanggan; yang boleh
            # mengeluarkannya pemiliknya, lewat pengambilan — bukan pabrik, lewat
            # penjualan. Disembunyikan DI SINI, bukan ditolak di akhir: pilihan
            # yang tak boleh dipilih sebaiknya tak muncul, sebab Admin yang sudah
            # mengisi seluruh borang lalu ditolak akan mencari jalan lain.
            #
            # Penolakannya tetap ada di `barang_keluar.tersedia` — borang ini
            # menerima kode yang DIKETIK juga, dan daftar yang menyaring tanpa
            # penjaga di belakangnya cuma menyaring yang patuh.
            if l.jasa_id is not None:
                continue
            out.append({"value": f"pk:{l.kode}",
                        "label": (f"PK {l.kode} · {kg(l.tersedia)}"
                                  + (f" · {l.kelas}" if l.kelas else "")
                                  + " (isi dalam kg)")})
        # ── Gabah kering ditimbang (pesan kerja 12) — PABRIK saja ──
        #
        # Sebangun PK di atas: lot jasa TIDAK ditawarkan di sini (pengambilan
        # pemiliknya lewat `/actions/barang-jasa`, picker `gk:`) — disembunyikan
        # DI SINI, penjaganya tetap di `barang_keluar.tersedia`.
        from app.models import GabahKeringLot
        from app.penggilingan.gudang1.services.gabah_kering import (
            pending_gabah_kering_kg)

        for lot in (await db.execute(
            select(GabahKeringLot).where(GabahKeringLot.jasa_id.is_(None))
        )).scalars().all():
            sisa_gkr = await pending_gabah_kering_kg(db, lot.id)
            if sisa_gkr > 0.5:
                out.append({"value": f"gk:{lot.kode_lot}",
                            "label": f"Gabah kering {lot.kode_lot} · "
                                     f"{kg(sisa_gkr)} (isi dalam kg)"})
    return out


@router.get("/actions/pk-siap-keluar")
async def pk_siap_keluar(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Lot PK Gudang 1 yang masih bersisa — untuk dijual keluar pabrik.

    Keputusan pemilik 29 September 2026: "pk juga bisa dijual dan mengurangi
    stock pk". Yang berpindah barangnya; harganya urusan keuangan dan tak
    disebut satu kali pun di sini.

    Bedanya dengan `/actions/pk-g1-tersedia`: yang itu untuk operator Gudang 2
    yang MEMINTA lot dipindah ke penyosohan, jadi ia menyembunyikan lot yang
    sudah diminta orang. Yang ini untuk Admin yang mengeluarkannya dari pabrik —
    lot yang sedang diminta Gudang 2 tetap ditawarkan, sebab permintaan bukan
    penguncian: Admin boleh memutuskan lot itu dijual, dan permintaannya gugur
    dengan sendirinya saat lotnya habis.
    """
    wajib(can_see_financials(user))
    from app.services.stok import pk_gudang1

    async with SessionLocal() as db:
        lot = await pk_gudang1(db)
    # PK jasa tak ditawarkan — lihat catatan di `barang_bisa_keluar`.
    return [{"value": l.kode,
             "label": (f"{l.kode} · {kg(l.tersedia)}"
                       + (f" · {l.kelas}" if l.kelas else ""))}
            for l in lot if l.tersedia > 0 and l.jasa_id is None]


@router.get("/actions/timbang-keluar-aktif")
async def timbang_keluar_aktif(induk: str = "",
                               user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Tiket timbang KELUAR yang belum tertaut transaksi mana pun.

    `induk` = id muatan ("perintah") yang sedang diverifikasi, dikirim klien
    dari medan di atasnya. Muatan di bawah `MUATAN_KECIL_TANPA_TIKET_KG`
    (keputusan pemilik 5 Oktober 2026) menjawab daftar KOSONG — bukan
    larangan, cuma tak ditawarkan: kalimat `kosong` pada medannya sendiri
    yang menjelaskan sebabnya, dan tiket tetap bisa ditautkan kalau memang
    ada (lihat catatan panjang di `barang_keluar.MUATAN_KECIL_TANPA_TIKET_KG`).

    `induk` kosong ATAU muatannya tak ditemukan → daftar penuh, apa adanya:
    borang yang dibuka lewat katalog (bukan lewat kartu per-muatan) harus
    tetap bisa menawarkan seluruh tiket sebelum "perintah"-nya sendiri
    sempat dipilih.
    """
    wajib(can_see_financials(user))
    from app.models import OutgoingRecord
    from app.penggilingan.gudang1.services.timbang_link import tiket_keluar_aktif

    async with SessionLocal() as db:
        rec_id = int(induk) if induk.strip().isdigit() else None
        if rec_id is not None and await db.get(OutgoingRecord, rec_id) is not None:
            total = sum(float(i.berat_kg or 0) for i in (await db.execute(
                select(OutgoingItem).where(OutgoingItem.outgoing_record_id == rec_id)
            )).scalars().all())
            if total < bk.MUATAN_KECIL_TANPA_TIKET_KG:
                return []
        tk = await tiket_keluar_aktif(db)
    out = []
    for t in tk:
        nama = t.get("jenis_nama") or t.get("kategori") or t.get("jenis_kode") or "?"
        berat = float(t.get("berat_kg") or 0)
        bstr = kg(berat) if berat else "⚠️ bobot belum ada"
        pihak = t.get("pihak") or "?"
        out.append({"value": str(t["id"]),
                    "label": f"{t['kode']} · {nama} · {bstr} · {pihak}"})
    return out


@router.get("/actions/pelanggan-kledo")
async def pelanggan_kledo(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Pelanggan Kledo — dari CERMIN LOKALNYA, bukan dari panggilan ke Kledo.

    Dua sebab, dan yang pertama menentukan:

    · borang ini dibuka di gudang, seringnya pagi-pagi saat truk sudah datang.
      Kledo yang lambat atau mati akan membuat perintah muat tak bisa
      diterbitkan sama sekali — pabrik berhenti karena layanan akuntansi pihak
      ketiga, harga yang tak sepadan untuk sebuah daftar nama;
    · kuncinya memang tak perlu ada di sini. `KLEDO_API_KEY` hidup di layanan
      Kantor, yang menyegarkan tabel `pelanggan` sekali seminggu dari
      `type_id = 3`. Satu kunci di satu tempat: kunci yang disalin ke layanan
      kedua adalah kunci yang harus diputar dua kali kelak, dan yang kedua akan
      terlupa.

    Karena mingguan, pembeli yang baru dibuat di Kledo hari ini bisa BELUM
    muncul — itu sebabnya borangnya tetap menerima nama yang diketik, dan
    medan ini `optional`.

    Syaratnya sama persis dengan yang dipakai `_pembeli` saat menerima
    kiriman: yang ditawarkan dan yang diterima wajib himpunan yang sama.
    """
    wajib(can_see_financials(user))
    from app.models import Pelanggan

    async with SessionLocal() as db:
        baris = (await db.execute(
            select(Pelanggan.id, Pelanggan.nama_pelanggan)
            .where(Pelanggan.deleted_at.is_(None), Pelanggan.status == "aktif")
            .order_by(Pelanggan.nama_pelanggan))).all()
    return [{"value": str(i), "label": n} for i, n in baris]


# ────────────────── Rantai barang keluar: rute & daftarnya ──────────────────
#
# Gerbangnya di RUTE, bukan cuma pada tombolnya: menyembunyikan pintu bukan
# penjagaan — alamatnya bisa diketik, dan lembar yang masih terbuka di layar
# orang lain masih bisa mengirim.

class BarisReq(BaseModel):
    """Satu baris borang bertabel: barang mana, berapa banyak."""

    pilih: str = ""
    jumlah: float | None = None


class PerintahKeluarReq(BaseModel):
    #: Bentuk BARU sejak 29 September 2026 — daftar pasangan dari medan
    #: `ulang_barang`. Satu transaksi memuat beberapa macam barang.
    barang: list[BarisReq] | None = None
    #: Bentuk LAMA — satu barang per perintah. Dipertahankan sebentar sebab
    #: lembar yang sudah terbuka di layar orang saat versi baru terbit masih
    #: mengirim bentuk ini, dan halaman di ponsel berumur panjang. Yang berhenti
    #: cuma MENAWARKANNYA.
    stok: str | None = None
    jumlah_karung: int | None = None
    #: Pilihan dari daftar pelanggan Kledo. Dikirim sebagai teks (isi
    #: `<select>`), diubah jadi id di rutenya.
    pelanggan: str | None = None
    #: Nama yang DIKETIK, untuk pembeli yang belum ada di Kledo. Salah satu
    #: dari keduanya wajib terisi — yang menentukan mana yang menang
    #: `bk._pembeli`, bukan rute ini, sebab jalur bot memakai fungsi yang sama.
    nama_pembeli: str = ""
    metode: str | None = None
    no_polisi: str | None = None
    nama_ekspedisi: str | None = None


async def _satu_baris(db, pilih: str, jumlah) -> "bk.BarisPerintah":
    """Satu pilihan berawalan + jumlahnya → baris perintah.

    Awalannya yang menentukan SATUAN: `bj:` per karung, `cr:`, `pk:`, dan
    `g2:` per kilogram. Tanpa awalan, "100" pada satu baris berarti 100
    karung dan pada baris lain 100 kg — dan yang membedakan cuma ingatan
    orang yang mengetiknya.
    """
    from app.models import MillingProcess

    pilih = (pilih or "").strip()
    if float(jumlah or 0) <= 0:
        raise HTTPException(400, f"Isi jumlah untuk '{pilih}' lebih dari 0.")
    if pilih.startswith("cr:"):
        # Curah DIKETIK DALAM KG. Jumlahnya tak pernah diturunkan dari karung
        # sebab ia memang tak berkarung; `tersedia()` yang menjaga batasnya,
        # dan penolakannya menyebut angkanya.
        return bk.BarisPerintah(tipe="byproduct_curah", jenis=pilih[3:].strip(),
                                berat_kg=float(jumlah))
    if pilih.startswith("pk:"):
        kode = pilih[3:].strip()
        proc = (await db.execute(select(MillingProcess).where(
            MillingProcess.kode_proses == kode))).scalars().first()
        if proc is None:
            raise HTTPException(400, f"Lot {kode} tidak ditemukan.")
        return bk.BarisPerintah(tipe="pk_langsung", milling_process_id=proc.id,
                                berat_kg=float(jumlah))
    if pilih.startswith("gk:"):
        from app.models import GabahKeringLot
        kode = pilih[3:].strip()
        lot = (await db.execute(select(GabahKeringLot).where(
            GabahKeringLot.kode_lot == kode))).scalars().first()
        if lot is None:
            raise HTTPException(400, f"Gabah kering {kode} tidak ditemukan.")
        return bk.BarisPerintah(tipe="gabah_langsung", gabah_kering_lot_id=lot.id,
                                berat_kg=float(jumlah))
    if pilih.startswith("g2:"):
        # PK Gudang 2 — DIKETIK DALAM KG, sama seperti `pk:`/`cr:`. Tempatnya
        # `silo:<id>` atau `tumpukan` persis; `tersedia()` yang menjaga
        # pagarnya (pemilik tempat vs pemilik perintah).
        tempat = pilih[3:].strip()
        if tempat == "tumpukan":
            return bk.BarisPerintah(tipe="pk_g2", silo_id=None,
                                    berat_kg=float(jumlah))
        if tempat.startswith("silo:") and tempat[5:].isdigit():
            return bk.BarisPerintah(tipe="pk_g2", silo_id=int(tempat[5:]),
                                    berat_kg=float(jumlah))
        raise HTTPException(400, f"Tempat PK Gudang 2 tak dikenal: {tempat}.")
    nilai = pilih[3:] if pilih.startswith("bj:") else pilih
    bagian = nilai.split("|")
    if not bagian or not bagian[0].isdigit():
        raise HTTPException(400, "Pilih barangnya dulu.")
    std = int(bagian[1]) if len(bagian) > 1 and bagian[1].isdigit() else None
    return bk.BarisPerintah(tipe="finished_goods", sku_id=int(bagian[0]),
                            std_id=std, jumlah_karung=int(jumlah))


async def _baris_dari_borang(db, req) -> list["bk.BarisPerintah"]:
    """Seluruh baris perintah dari borangnya — bentuk baru maupun lama."""
    if req.barang:
        # Baris yang kosong SELURUHNYA sudah dibuang layar; yang terisi separuh
        # sampai ke sini dan ditolak dengan menyebut barangnya — bukan dibuang
        # diam-diam, yang akan membuat perintah kurang satu barang tanpa sebab.
        return [await _satu_baris(db, b.pilih, b.jumlah) for b in req.barang
                if (b.pilih or "").strip() or b.jumlah]
    if (req.stok or "").strip():
        return [await _satu_baris(db, req.stok, req.jumlah_karung)]
    raise HTTPException(400, "Pilih dulu barang yang akan keluar.")


@router.post("/actions/perintah-keluar")
async def act_perintah_keluar(req: PerintahKeluarReq,
                              user: User = Depends(pengguna_aksi)) -> dict:
    """LANGKAH 1 — Admin menerbitkan perintah muat. Stok BELUM berkurang."""
    wajib(can_see_financials(user))
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        baris = await _baris_dari_borang(db, req)
        try:
            r = await bk.buat_perintah(
                db, user=u, baris=baris, nama_pembeli=req.nama_pembeli,
                pelanggan_id=_pelanggan_id(req.pelanggan),
                metode=req.metode, no_polisi=(req.no_polisi or None),
                nama_ekspedisi=(req.nama_ekspedisi or None))
        except bk.BarangKeluarError as e:
            raise galat(e, "Gagal membuat perintah barang keluar.")
        kode, pembeli = r.rec.kode, r.rec.nama_pembeli
    # Namanya dari BARISNYA, bukan dari yang diketik: kalau Admin memilih dari
    # daftar Kledo, yang diketik memang kosong — dan kalimat "terbit untuk"
    # yang berakhir tanpa nama membuat orang mengira pembelinya tak tersimpan.
    return {"ok": True,
            "pesan": f"✓ Perintah *{kode}* terbit untuk {pembeli}. "
                     "Tambahkan barang lain bila muatannya lebih dari satu macam — "
                     "operator melihatnya di Antrian tunggu."}


class TambahBarangKeluarReq(PerintahKeluarReq):
    perintah: str = ""


@router.post("/actions/tambah-barang-keluar")
async def act_tambah_barang_keluar(req: TambahBarangKeluarReq,
                                   user: User = Depends(pengguna_aksi)) -> dict:
    """Satu macam barang lagi ke perintah yang belum dimuat.

    SATU TRANSAKSI BANYAK BARANG — dan itu seluruh sebab halaman ini diminta:
    satu truk berisi beras + broken + menir dulu melahirkan tiga kode OUT- yang
    berbeda, tiga baris di kartu Stok Produk, dan tiga pencocokan untuk satu
    tiket timbang.
    """
    wajib(can_see_financials(user))
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        baris = await _baris_dari_borang(db, req)
        try:
            for b in baris:
                r = await bk.tambah_baris(db, user=u, rec_id=_id(req.perintah),
                                          baris=b)
        except bk.BarangKeluarError as e:
            raise galat(e, "Gagal menambah barang ke perintah.")
        kode, n = r.rec.kode, len(r.baris)
    return {"ok": True, "pesan": f"✓ Ditambahkan ke *{kode}* — kini {n} macam barang."}


def _pelanggan_id(nilai: str | None) -> int | None:
    """Pilihan pelanggan → id, atau None bila tak dipilih.

    Kosong BUKAN kesalahan: pembeli yang belum ada di Kledo diketik namanya.
    Yang ditolak cuma isi yang bukan angka — itu berarti borangnya mengirim
    sesuatu yang bukan dari daftar, dan menerimanya berarti menautkan ke baris
    yang tak pernah ada.
    """
    v = (nilai or "").strip()
    if not v:
        return None
    if not v.isdigit():
        raise HTTPException(400, "Pembeli yang mana? Pilih dari daftarnya.")
    return int(v)


def _id(nilai: str | None) -> int:
    try:
        return int((nilai or "").strip())
    except ValueError:
        raise HTTPException(400, "Perintah yang mana?") from None


class BatalPerintahReq(BaseModel):
    perintah: str = ""
    sebab: str = ""


@router.post("/actions/batal-perintah-keluar")
async def act_batal_perintah_keluar(req: BatalPerintahReq,
                                    user: User = Depends(pengguna_aksi)) -> dict:
    wajib(can_see_financials(user))
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            rec = await bk.batalkan(db, user=u, rec_id=_id(req.perintah),
                                    sebab=req.sebab)
        except bk.BarangKeluarError as e:
            raise galat(e, "Gagal membatalkan perintah.")
        kode = rec.kode
    return {"ok": True, "pesan": f"✓ Perintah {kode} dibatalkan — sebabnya terbaca operator."}


class MuatReq(BaseModel):
    perintah: str = ""


@router.post("/actions/muat-semua")
async def act_muat_semua(req: MuatReq, user: User = Depends(pengguna_aksi)) -> dict:
    """LANGKAH 2 — operator memuat seluruhnya sesuai perintah. Stok berkurang.

    Wewenangnya TIDAK datang dari peran melainkan dari BARIS PERINTAHNYA: tak
    seorang operator pun bisa mengeluarkan barang atas kehendak sendiri, dan
    layanan yang dipanggil memeriksa keadaan perintahnya sambil menguncinya.
    """
    from app.web.api import _is_g1_operator, _is_g2_operator

    # Gudang MANA pun yang memegang barangnya: barang jadi di Gudang 2, tetapi
    # perintah bisa memuat barang dari keduanya, dan operator memang saling
    # menggantikan (keputusan pemilik 13 September). Yang menjaga bukan peran
    # melainkan BARIS PERINTAHNYA, yang diperiksa layanan sambil menguncinya.
    wajib(await _is_g2_operator(user) or await _is_g1_operator(user))
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await bk.muat_semua(db, user=u, rec_id=_id(req.perintah))
        except bk.BarangKeluarError as e:
            raise galat(e, "Gagal mencatat muatan.")
        kode = r.rec.kode
        total = sum(float(i.berat_kg or 0) for i in r.baris)
    return {"ok": True,
            "pesan": f"✓ {kode} dimuat {kg(total)} — Admin memverifikasinya "
                     "sambil menempelkan kode timbang keluar."}


class MuatBarisReq(BaseModel):
    baris: str = ""
    jumlah: float | None = None


@router.post("/actions/muat-barang")
async def act_muat_barang(req: MuatBarisReq,
                          user: User = Depends(pengguna_aksi)) -> dict:
    """Satu barang yang dimuat KURANG dari perintahnya."""
    from app.web.api import _is_g1_operator, _is_g2_operator

    # Gudang MANA pun yang memegang barangnya: barang jadi di Gudang 2, tetapi
    # perintah bisa memuat barang dari keduanya, dan operator memang saling
    # menggantikan (keputusan pemilik 13 September). Yang menjaga bukan peran
    # melainkan BARIS PERINTAHNYA, yang diperiksa layanan sambil menguncinya.
    wajib(await _is_g2_operator(user) or await _is_g1_operator(user))
    if float(req.jumlah or 0) <= 0:
        raise HTTPException(400, "Isi jumlah yang dimuat lebih dari 0.")
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        it = await db.get(OutgoingItem, _id(req.baris))
        if it is None:
            raise HTTPException(400, "Barang itu tidak ada lagi di perintahnya.")
        # Yang berkarung diketik dalam KARUNG, yang curah dalam kg — sama dengan
        # satuan yang tertulis di kartunya. Menuntut operator mengubah karung
        # jadi kilogram sambil berdiri di truk adalah mengundang salah kali.
        karung = int(req.jumlah) if it.item_type == "finished_goods" else None
        berat = None if karung is not None else float(req.jumlah)
        try:
            rec, pesan = await bk.catat_muatan(db, user=u, item_id=it.id,
                                               jumlah_karung=karung, berat_kg=berat)
        except bk.BarangKeluarError as e:
            raise galat(e, "Gagal mencatat muatan.")
    return {"ok": True, "pesan": pesan}


@router.post("/actions/selesai-muat")
async def act_selesai_muat(req: MuatReq, user: User = Depends(pengguna_aksi)) -> dict:
    from app.web.api import _is_g1_operator, _is_g2_operator

    # Gudang MANA pun yang memegang barangnya: barang jadi di Gudang 2, tetapi
    # perintah bisa memuat barang dari keduanya, dan operator memang saling
    # menggantikan (keputusan pemilik 13 September). Yang menjaga bukan peran
    # melainkan BARIS PERINTAHNYA, yang diperiksa layanan sambil menguncinya.
    wajib(await _is_g2_operator(user) or await _is_g1_operator(user))
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await bk.selesai_muat(db, user=u, rec_id=_id(req.perintah))
        except bk.BarangKeluarError as e:
            raise galat(e, "Gagal menutup muatan.")
        kode = r.rec.kode
        total = sum(float(i.berat_kg or 0) for i in r.baris)
    return {"ok": True,
            "pesan": f"✓ {kode} berangkat dengan {kg(total)} — menunggu "
                     "verifikasi Admin."}


class VerifikasiKeluarReq(BaseModel):
    perintah: str = ""
    tiket: str | None = None
    #: Wajib hanya bila selisih timbang melewati ambang — yang memutuskan
    #: `bk.verifikasi`, bukan rute ini. Jalur mana pun memakai layanan yang
    #: sama, jadi pagarnya cukup berdiri sekali di sana.
    sebab_selisih: str | None = None


@router.post("/actions/verifikasi-keluar")
async def act_verifikasi_keluar(req: VerifikasiKeluarReq,
                                user: User = Depends(pengguna_aksi)) -> dict:
    """LANGKAH 3 — Admin menutup sambil menempelkan kode timbang keluarnya."""
    wajib(can_see_financials(user))
    tid = None
    if (req.tiket or "").strip():
        try:
            tid = int(req.tiket.strip())
        except ValueError:
            raise HTTPException(400, "Kode timbang yang mana?") from None
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            rec, catatan = await bk.verifikasi(
                db, user=u, rec_id=_id(req.perintah), timbangan_transaksi_id=tid,
                sebab_selisih=req.sebab_selisih)
        except bk.BarangKeluarError as e:
            raise galat(e, "Gagal memverifikasi barang keluar.")
        kode = rec.kode
    return {"ok": True,
            "pesan": f"✓ {kode} ditutup." + (f" {catatan}" if catatan else "")}


@router.post("/actions/auto-taut-keluar")
async def act_auto_taut_keluar(user: User = Depends(pengguna_aksi)) -> dict:
    """Tautkan otomatis tiket timbang keluar yang menganggur — lihat
    `bk.auto_tautkan` untuk aturan pencocokannya (pembeli+tanggal+berat,
    tak pernah menebak yang ambigu). Tanpa medan: satu tombol, jalankan."""
    wajib(can_see_financials(user))
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        hasil = await bk.auto_tautkan(db, user=u)
    return {"ok": True, "pesan": f"✓ {hasil.ringkas}."}


# ─────────────────────────── Spesifikasi aksi ───────────────────────────

#: Nama pembeli dst. dipakai berulang di tiga aksi keluar — ditulis sekali.
def _bidang_pengiriman() -> list[dict]:
    return [
        # ── PEMBELINYA DIPILIH DARI DAFTAR KLEDO, dan tetap bisa diketik ──
        #
        # Permintaan pemilik 29 September 2026: "nama pembeli di barang keluar
        # sinkronkan dengan pelanggan di kledo". Sebabnya terlihat setelah
        # sepekan dipakai: teks bebas melahirkan "Toko Makmur", "toko makmur",
        # dan "TK Makmur" untuk satu pembeli, dan tak satu pun laporan bisa
        # menjumlahkannya.
        #
        # DUA MEDAN, bukan satu, dan bukan karena paket tampilan tak punya
        # kotak gabungan. Yang kedua adalah PINTU DARURAT yang harus terlihat:
        # penyegaran kontak Kledo mingguan, jadi pembeli yang dibuat pagi ini
        # bisa belum ada di daftar. Satu medan yang "boleh diketik bebas kalau
        # tak ada di daftar" menyembunyikan pintu itu di dalam kebiasaan, dan
        # yang tak terlihat tak dipakai — orang akan memilih nama yang MIRIP.
        #
        # `optional` pada keduanya: yang memastikan salah satunya terisi adalah
        # `bk._pembeli`, di layanan. Menaruhnya di sini saja berarti jalur bot
        # dan lembar yang sudah terbuka di layar orang lolos tanpa pembeli.
        {"name": "pelanggan", "label": "Pembeli (daftar Kledo)",
         "type": "remote", "source": "/api/actions/pelanggan-kledo",
         "optional": True,
         "kosong": "Daftar pelanggan Kledo belum tersinkron — tulis nama "
                   "pembelinya di kotak bawah."},
        {"name": "nama_pembeli", "label": "Pembeli baru (belum di Kledo)",
         "type": "text"},
        {"name": "metode", "label": "Cara kirim", "type": "select", "optional": True,
         "options": [["", "— belum ditentukan —"], ["diantar", "Diantar"],
                     ["diambil", "Diambil sendiri"], ["ekspedisi", "Ekspedisi"]]},
        {"name": "no_polisi", "label": "Plat truk (bila ada)", "type": "text"},
        {"name": "nama_ekspedisi", "label": "Ekspedisi (bila ada)", "type": "text"},
        # ⚠ HARGA DICABUT 28 September 2026. Keputusan pemilik, dua kali:
        # "HARGA & HPP KELUAR DARI POS PRODUKSI", lalu — saat PK dikeluarkan
        # dari rantai ini — "pk dijual tetapi itu urusan keuangan".
        #
        # Yang dicatat di sini PERPINDAHAN FISIK: berapa karung naik ke truk
        # mana, milik siapa. Berapa rupiahnya ditetapkan di tempat uang
        # dicatat, dan angka harga yang diketik di dua sistem akan berbeda di
        # salah satunya tanpa ada yang tahu mana yang benar.
        #
        # `outgoing_items.harga_per_kg` TIDAK dihapus: baris lama memuatnya, dan
        # menghapus kolom berarti menghapus sejarah. Yang berhenti cuma
        # MENANYAKANNYA.
    ]


def spesifikasi(*, g2: bool, fin: bool) -> list[dict]:
    """Aksi inventory yang boleh dilihat pemakai ini.

    Dipanggil `api.actions_menu` supaya seluruh menu tetap satu daftar
    dari satu tempat, meski isinya dirakit dari beberapa modul.
    """
    aksi: list[dict] = []

    if g2:
        aksi += [
            # ── Operator: menerima tugas muat ──
            #
            # "Muat semua sesuai perintah" berdiri PALING ATAS dan itu disengaja:
            # ia keadaan yang paling sering, dan borang yang menuntut operator
            # mengetik ulang angka yang sudah tertulis di kartunya akan diketik
            # asal-asalan sambil berdiri di samping truk. Yang berselisih dicatat
            # per barang lewat aksi di bawahnya.
            {"id": "muat_semua", "label": "\U0001F69A Muat semua sesuai perintah",
             "post": "/api/actions/muat-semua",
             "hint": "Seluruh barang dimuat persis seperti diperintahkan. Kalau "
                     "ada yang berselisih, catat per barang dulu.",
             "fields": [
                 {"name": "perintah", "label": "Perintah muat", "type": "remote",
                  "source": "/api/actions/perintah-terbuka",
                  "kosong": "Tidak ada perintah muat yang menunggu."},
             ]},
            {"id": "muat_barang", "label": "\U0001F4E6 Catat muatan per barang",
             "post": "/api/actions/muat-barang",
             "hint": "Untuk yang dimuat KURANG dari perintahnya. Sesudah semua "
                     "tercatat, tekan 'Selesai muat'.",
             "fields": [
                 {"name": "baris", "label": "Barang yang dimuat", "type": "remote",
                  "source": "/api/actions/baris-perintah",
                  "kosong": "Tidak ada barang yang menunggu dimuat."},
                 {"name": "jumlah", "label": "Yang benar-benar dimuat",
                  "type": "number", "wajib": True},
             ]},
            {"id": "selesai_muat", "label": "\u2714\uFE0F Selesai muat — truk berangkat",
             "post": "/api/actions/selesai-muat",
             "hint": "Sisa perintah yang tak dimuat HANGUS, dan selisihnya "
                     "terbaca Admin saat verifikasi.",
             "fields": [
                 {"name": "perintah", "label": "Perintah yang sudah dimuat",
                  "type": "remote", "source": "/api/actions/perintah-terbuka",
                  "kosong": "Tidak ada perintah muat yang menunggu."},
             ]},
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
             # ⚠ Kalimat lamanya berbunyi "ia tidak dipacking" dan sudah BASI
             # sejak 28 September 2026: bekatul boleh dikarungi (karung bekas
             # 40 kg & 20 kg). Keterangan yang basi lebih buruk daripada tak
             # ada — orang mempercayainya lalu berhenti mencari jalan yang
             # sebenarnya ada.
             "hint": "Bekatul yang dijual CURAH, per kg. Yang dikarungi dicatat "
                     "lewat packing — keduanya mengambil dari tumpukan yang "
                     "sama dan saling mengurangi.",
             "fields": [
                 {"name": "kode_pol", "label": "Proses penyosohan", "type": "remote",
                  "source": "/api/actions/polishing-terkini"},
                 {"name": "berat_kg", "label": "Berat (kg)", "type": "number"},
             ]},
            # ⚠ SEMPAT DICABUT 7 Oktober 2026, DIKEMBALIKAN hari yang sama —
            # bukan digantikan "Masukkan broken ke silo"
            # (`masukkan_broken_silo`, katalog operator Gudang 2 di
            # `api.py`), melainkan BERDAMPINGAN: keduanya menjawab
            # pertanyaan yang berbeda. Ini mencatat hasil mesin SEBAGAI
            # curah (belum punya tujuan); itu memindahkan curah yang SUDAH
            # tercatat ke silo (sumbernya otomatis, curah dulu lalu karung
            # dibongkar bila kurang — menggantikan "Pindah broken ke silo"
            # yang lama, bukan langkah ini). Laporan lapangan susulan hari
            # yang sama ("ada tombol sisa dicurah" di kartu Tunggu packing)
            # justru BUTUH langkah ini tetap ada & terjangkau lewat katalog
            # (`MENU["catat_broken"]`, dibuka kartu lewat `?buka=` — lihat
            # `_kartu_beras_curah`).
            {"id": "catat_broken", "label": "🌾 Catat broken (curah)",
             "post": "/api/actions/catat-broken",
             "hint": "Langkah WAJIB sebelum broken bisa dimasukkan ke silo "
                     "broken untuk disosoh ulang. Yang dikarungi (dijual "
                     "apa adanya) dicatat lewat packing — keduanya mengambil "
                     "dari hasil mesin yang sama dan saling mengurangi.",
             "fields": [
                 {"name": "kode_pol", "label": "Proses penyosohan", "type": "remote",
                  "source": "/api/actions/polishing-terkini"},
                 {"name": "berat_kg", "label": "Berat (kg)", "type": "number"},
             ]},
        ]

    if fin:
        aksi += [
            # ── Pindah kepemilikan — titipan jadi milik pabrik ──
            #
            # Keputusan pemilik 6 Oktober 2026: "nanti bisa berpindah
            # kepemilikan menjadi milik kita ... karna bisa jadi produk
            # ataupun hasil samping jadi milik kita ataupun kita beli."
            # Admin/Super Admin saja (gerbangnya di `produk_jasa_tersedia` &
            # `act_pindah_kepemilikan_produk`) — sejalan dengan "harga keluar
            # dari Pos Produksi": keputusan kepemilikan berdekatan dengan
            # uang, bukan pekerjaan operator.
            {"id": "pindah_kepemilikan_produk",
             "label": "⇄ Pindah kepemilikan ke pabrik",
             "post": "/api/actions/pindah-kepemilikan-produk",
             "hint": "Boleh sebagian. Satuannya mengikuti pilihan — karung "
                     "untuk barang berkarung, kg untuk broken/bekatul curah. "
                     "Hanya yang SUDAH TERCATAT (dikemas atau dicatat curah) "
                     "yang bisa dipindah — catat dulu hasil yang masih mentah.",
             "fields": [
                 {"name": "item", "label": "Barang milik pesanan jasa",
                  "type": "remote", "source": "/api/actions/produk-jasa-tersedia",
                  "kosong": "Tidak ada barang tercatat milik pesanan jasa "
                            "yang bisa dipindah."},
                 {"name": "jumlah", "label": "Jumlah yang dipindah",
                  "type": "number"},
             ]},
            # ── Pindah kepemilikan karung — ARAH KEBALIKAN yang di atas ──
            #
            # Karung tak punya tiket timbang: `beli_kemasan` selalu menulis
            # milik pabrik, jadi satu-satunya jalan sebuah lembar jadi milik
            # pelanggan adalah dipindah SESUDAH dibeli, bukan diturunkan
            # saat masuk. Keputusan pemilik 7 Oktober 2026 ("ubah jadi stok
            # terpisah per pemilik"), lalu koreksi susulan hari yang sama:
            # "jalur masuk karung untuk jasa bukan berdasarkan proses jasa.
            # tetapi berdasarkan kontak pelanggan" — jadi tujuannya KONTAK
            # (`pelanggan-kledo`, picker yang SAMA dengan "Buat perintah
            # barang keluar"), BUKAN `jasa-berjalan`. Lihat `packaging.
            # pindah_kepemilikan_karung` untuk catatan arahnya.
            #
            # Medan "pelanggan" berjenis `kombo` (bukan `remote` biasa) —
            # keluhan pemilik atas daftar jatuh `<select>` di kartu Stok
            # Karung: "harus bisa diketik sambil memfilter dari list
            # pelanggan yang ada di database." `kombo` kotak teks yang
            # menyaring daftar `pelanggan-kledo` yang SAMA sambil diketik —
            # lihat catatan panjangnya di `aksi.js` (`f.type === "kombo"`).
            {"id": "pindah_kepemilikan_karung",
             "label": "⇄ Pindah kepemilikan ke pelanggan",
             "post": "/api/actions/pindah-kepemilikan-karung",
             "hint": "Boleh sebagian — FIFO dari pembelian pabrik yang "
                     "paling lama, lembar per lembar.",
             "fields": [
                 {"name": "karung", "label": "Karung pabrik", "type": "remote",
                  "source": "/api/actions/karung-pabrik-tersedia",
                  "kosong": "Tidak ada stok karung pabrik yang bisa dipindah."},
                 {"name": "pelanggan", "label": "Pelanggan tujuan", "type": "kombo",
                  "source": "/api/actions/pelanggan-kledo",
                  "placeholder": "Ketik nama pelanggan…",
                  "kosong": "Tidak ada pelanggan terdaftar."},
                 {"name": "jumlah", "label": "Jumlah lembar", "type": "number"},
             ]},
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
                 # Harga DICABUT 29 September 2026 — keputusan pemilik:
                 # "sistem produksi tidak boleh ada sangkut paut dengan harga.
                 # semua yang berhubungan dengan harga tolong dihapus."
                 #
                 # Ini medan harga TERAKHIR di seluruh Pos Produksi. Yang
                 # dicatat di sini berapa lembar karung masuk gudang; berapa
                 # rupiahnya dicatat di tempat uang dicatat, dan angka yang
                 # diketik di dua sistem akan berbeda di salah satunya tanpa ada
                 # yang tahu mana yang benar.
             ]},
            # ── Rantai barang keluar: perintah · muat · verifikasi ──
            #
            # Perintah dibuat dengan SATU baris barang; barang berikutnya
            # ditambahkan lewat aksinya sendiri. Bukan satu borang bertabel:
            # medan `ulang` yang sudah ada hanya mengulang SATU kotak, dan
            # memperluasnya jadi sepasang (barang + jumlah) menyentuh paket
            # tampilan yang dipakai seluruh layar lain. Bentuk ini sudah
            # terbukti di app ini; borang bertabel bisa menyusul kelak tanpa
            # mengubah satu kolom pun.
            {"id": "perintah_keluar", "label": "\U0001F4CB Buat perintah barang keluar",
             "post": "/api/actions/perintah-keluar",
             "hint": "Perintah BELUM mengurangi stok — barangnya berpindah saat "
                     "operator memuatnya. Barang lain ditambahkan setelah ini.",
             # ── BORANG BERTABEL: pilih barang + jumlahnya, lalu tambah item ──
             #
             # Permintaan pemilik 29 September 2026: "admin bisa memilih barang
             # yang akan keluar beserta jumlahnya. lalu bisa klik tambah item
             # lalu keluar field baru untuk memilih item lain beserta jumlahnya,
             # karena barang keluar bisa multi item."
             #
             # `ulang_barang` LAHIR untuk ini (paket tampilan): medan `ulang`
             # yang sudah ada hanya mengulang SATU kotak, sedangkan yang perlu
             # diulang di sini SEPASANG — barang dan jumlahnya.
             #
             # SATU daftar berisi barang jadi DAN PK mentah. Yang dipikirkan
             # Admin "apa yang naik truk ini", bukan "barang jadi atau PK".
             "fields": [
                 {"name": "barang", "label": "Barang yang keluar",
                  "type": "ulang_barang", "maks": 12,
                  "source": "/api/actions/barang-bisa-keluar",
                  "label_angka": "Jumlah", "tambah": "+ Tambah item",
                  "kosong": "Tidak ada barang jadi berkarung maupun PK yang "
                            "bisa dikeluarkan."},
             ] + _bidang_pengiriman()},
            # ── PENGAMBILAN BARANG JASA ──
            #
            # Aksinya SENDIRI, bukan pilihan di dalam "Buat perintah barang
            # keluar" — dan bedanya bukan kerapian. Perintah penjualan bertanya
            # "kepada siapa dijual"; perintah pengambilan tidak bertanya sama
            # sekali, sebab barang titipan kembali kepada yang menitipkannya.
            # Satu borang yang memuat keduanya akan menyodorkan medan pembeli
            # pada pengambilan — kesempatan mengetik nama yang salah di atas
            # surat jalan barang orang lain.
            #
            # Daftar barangnya bergantung pada PESANAN yang dipilih, dan
            # kosong sampai ada yang dipilih: daftar yang menawarkan barang
            # seluruh pelanggan sekali salah pilih menyerahkan barang ke orang
            # lain.
            {"id": "ambil_jasa", "label": "\u25C7 Pengambilan barang jasa",
             "post": "/api/actions/ambil-jasa",
             "hint": "Barang titipan kembali ke pemiliknya — pembelinya tak "
                     "ditanya. Satu truk satu perintah; pengambilan bertahap "
                     "berarti beberapa perintah.",
             "fields": [
                 {"name": "jasa", "label": "Pesanan jasa", "type": "remote",
                  "source": "/api/actions/jasa-berjalan",
                  "kosong": "Tidak ada pesanan jasa yang berjalan."},
                 {"name": "barang", "label": "Barang yang diambil",
                  "type": "ulang_barang", "maks": 12,
                  "source": "/api/actions/barang-jasa",
                  "label_angka": "Jumlah", "tambah": "+ Tambah item",
                  "kosong": "Pilih pesanannya dulu — daftar barangnya mengikuti "
                            "pemiliknya."},
             ] + _bidang_pengiriman()},
            {"id": "tutup_jasa", "label": "\u25C7 Tutup pesanan jasa",
             "post": "/api/actions/tutup-jasa",
             "hint": "Hanya bila tak ada lagi barang pesanan itu di pabrik — "
                     "dan pesanan yang belum pernah menerima barang tak bisa "
                     "ditutup, ia dibatalkan.",
             "fields": [
                 {"name": "jasa", "label": "Pesanan yang ditutup",
                  "type": "remote", "source": "/api/actions/jasa-berjalan",
                  "kosong": "Tidak ada pesanan jasa yang berjalan."},
             ]},
            {"id": "batalkan_jasa", "label": "\U0001F6AB Batalkan pesanan jasa",
             "post": "/api/actions/batalkan-jasa",
             "hint": "Hanya pesanan yang BELUM pernah menerima barang. Yang "
                     "barangnya sudah ada diselesaikan lewat pengambilan.",
             "fields": [
                 {"name": "jasa", "label": "Pesanan yang dibatalkan",
                  "type": "remote", "source": "/api/actions/jasa-berjalan",
                  "kosong": "Tidak ada pesanan jasa yang berjalan."},
                 {"name": "sebab", "label": "Sebab membatalkan", "type": "text",
                  "wajib": True},
             ]},
            {"id": "tambah_barang_keluar", "label": "\u2795 Tambah barang ke transaksi",
             "post": "/api/actions/tambah-barang-keluar",
             "fields": [
                 # Sampai SEBELUM diverifikasi, bukan cuma selagi belum
                 # dimuat (keputusan pemilik 29 September 2026): truk dimuat
                 # bertahap, dan barang yang menyusul bukan transaksi baru.
                 {"name": "perintah", "label": "Transaksi yang belum diverifikasi",
                  "type": "remote",
                  "source": "/api/actions/perintah-bisa-ditambah",
                  "kosong": "Tidak ada transaksi yang masih bisa ditambah."},
                 {"name": "barang", "label": "Barang yang ditambahkan",
                  "type": "ulang_barang", "maks": 12,
                  "source": "/api/actions/barang-bisa-keluar",
                  "label_angka": "Jumlah", "tambah": "+ Tambah item",
                  "kosong": "Tidak ada barang yang bisa dikeluarkan."},
             ]},
            {"id": "batal_perintah_keluar", "label": "\U0001F6AB Batalkan perintah keluar",
             "post": "/api/actions/batal-perintah-keluar",
             "fields": [
                 {"name": "perintah", "label": "Perintah yang dibatalkan",
                  "type": "remote", "source": "/api/actions/perintah-terbuka",
                  "kosong": "Tidak ada perintah yang menunggu dimuat."},
                 {"name": "sebab", "label": "Sebab membatalkan", "type": "text",
                  "wajib": True},
             ]},
            {"id": "verifikasi_keluar", "label": "\u2705 Verifikasi barang keluar",
             "post": "/api/actions/verifikasi-keluar",
             "hint": "Tempelkan kode timbang keluarnya. Beda bobot tidak "
                     "menolak apa pun — selisihnya disebutkan supaya ditelusuri. "
                     "Kalau bedanya BESAR, sebabnya wajib ditulis di kotak "
                     "paling bawah; kartunya lalu ditandai.",
             "fields": [
                 {"name": "perintah", "label": "Muatan yang menunggu verifikasi",
                  "type": "remote", "source": "/api/actions/keluar-dimuat",
                  "kosong": "Tidak ada muatan yang menunggu diverifikasi."},
                 # `induk` — keputusan pemilik 5 Oktober 2026: muatan di bawah
                 # `barang_keluar.MUATAN_KECIL_TANPA_TIKET_KG` tak perlu tiket
                 # timbang keluar, jadi medan ini TAK DITAWARKAN untuk muatan
                 # sekecil itu (`/api/actions/timbang-keluar-aktif?induk=`
                 # menjawab daftar kosong, dan kalimat `kosong` di bawah
                 # berdiri sebagai keterangannya — BUKAN larangan, tiket tetap
                 # bisa ditautkan kalau kebetulan ada).
                 #
                 # ⚠ Daftar ini baru termuat SESUDAH "perintah" dipilih — dan
                 # kartu yang membuka borang ini lewat `?buka=&nilai=` mengisi
                 # "perintah" tanpa memicu event `change` apa pun (lihat
                 # perbaikan `isiDariBaris` di `aksi.js`). Tanpa perbaikan itu
                 # medan ini akan diam kosong selamanya pada jalur BUKAAN
                 # PALING UMUM — kartu "Verifikasi & tutup" per baris.
                 {"name": "tiket", "label": "Kode timbang keluar", "type": "remote",
                  "optional": True, "induk": "perintah",
                  "source": "/api/actions/timbang-keluar-aktif",
                  "kosong": "Tidak ada tiket timbang keluar untuk ditautkan — "
                           "kalau muatan ini di bawah 200 kg, tiket timbang "
                           "memang tidak diperlukan."},
                 # OPSIONAL di borang, WAJIB di layanan — dan hanya ketika
                 # selisihnya melewati ambang. `aksi.js` tak bisa mewajibkan
                 # satu medan menurut isi medan lain, dan memaksa medan ini
                 # wajib akan membuat tiap penutupan normal menuntut alasan
                 # atas selisih yang tak ada. Yang menjaga layanannya, dan
                 # penolakannya menyebut kedua angkanya.
                 {"name": "sebab_selisih",
                  "label": "Sebab selisih (bila bedanya besar)", "type": "text"},
             ]},
            {"id": "auto_taut_keluar", "label": "\U0001f517 Tautkan otomatis barang keluar",
             "post": "/api/actions/auto-taut-keluar",
             "hint": "Mencocokkan tiket timbang keluar yang menganggur ke "
                     "pesanan yang menunggu verifikasi — pembeli, tanggal, "
                     "dan berat yang sama (dalam ambang wajar). Pasangan "
                     "yang tidak jelas (cocok dengan lebih dari satu, atau "
                     "tak cocok sama sekali) DILEWATI, bukan ditebak — tetap "
                     "perlu ditautkan manual lewat Verifikasi barang keluar.",
             "fields": [
                 # Tak ada parameter yang sungguh dibutuhkan — pencocokannya
                 # otomatis sepenuhnya. Medan ini TETAP ada (opsional) karena
                 # lembar tanpa satu pun medan melewati jeda "lihat dulu,
                 # baru kirim" yang seluruh aksi lain di sini punya; satu
                 # kotak catatan opsional cukup untuk itu tanpa memaksa orang
                 # mengisi sesuatu yang memang tak perlu diisi.
                 {"name": "catatan", "label": "Catatan (opsional)", "type": "text"},
             ]},
        ]
    return aksi


# ══════════════════ PENGAMBILAN BARANG JASA ══════════════════
#
# Barang pelanggan keluar lewat rantai yang SAMA dengan penjualan — perintah,
# muat, verifikasi, satu truk satu perintah — dan itu bukan kebetulan: "boleh
# ambil bertahap" tak butuh perubahan apa pun di situ, sebab tiap pengambilan
# memang satu perintah, satu truk, satu tiket timbang.
#
# Yang membedakannya DUA hal saja: perintahnya bertanda `jasa_id`, dan daftar
# barangnya sudah tersaring menurut PEMILIK. Pilihan yang tak boleh dipilih
# sebaiknya tak muncul, bukan ditolak di akhir — dan penjaganya tetap berdiri
# di `barang_keluar.tersedia` sebab borang menerima yang diketik juga.


@router.get("/actions/jasa-berjalan")
async def jasa_berjalan(user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Pesanan jasa yang masih berjalan — untuk memilih pesanan mana diambil."""
    wajib(can_see_financials(user))
    from app.services.jasa import FASE_JASA, daftar_jasa

    async with SessionLocal() as db:
        kartu = await daftar_jasa(db)
    return [{"value": str(k.id),
             "label": (f"{k.kode} · {k.pelanggan} · "
                       f"{FASE_JASA.get(k.fase, k.fase)}")}
            for k in kartu]


@router.get("/actions/barang-jasa")
async def barang_jasa(jasa: str = "", user: User = Depends(pengguna_aksi)) -> list[dict]:
    """Barang pesanan jasa ini yang belum diambil pemiliknya.

    Tanpa `jasa` daftarnya KOSONG, bukan berisi semua: daftar yang menawarkan
    barang seluruh pelanggan saat pesanannya belum dipilih adalah daftar yang
    sekali salah pilih menyerahkan barang ke orang lain.
    """
    wajib(can_see_financials(user))
    if not jasa.isdigit():
        return []
    from app.models import FinishedGoodsStock, MillingProcess, ProductSku
    from app.penggilingan.gudang1.services.milling import pk_breakdown_banyak
    from app.penggilingan.inventory.finished_goods import hitung_stok_finished_goods
    from app.services.stok import jenis_produk, nama_produk

    jid = int(jasa)
    out: list[dict] = []
    async with SessionLocal() as db:
        # Barang jadi: dikelompokkan per SKU+mutu, persis seperti stok pabrik —
        # satu rumus, dua pemilik (lihat `hitung_stok_finished_goods`).
        combo = (await db.execute(
            select(FinishedGoodsStock.product_sku_id,
                   FinishedGoodsStock.rice_quality_standard_id)
            .where(FinishedGoodsStock.jasa_id == jid).distinct()
        )).all()
        for sku_id, std_id in combo:
            stok = await hitung_stok_finished_goods(db, sku_id, std_id, jasa_id=jid)
            if float(stok["kg"]) <= 0.5:
                continue
            sku = await db.get(ProductSku, sku_id)
            nm = nama_produk(jenis_produk(sku.kategori if sku else "-", None))
            out.append({
                "value": f"bj:{sku_id}|{std_id or ''}",
                "label": (f"{nm} · {int(stok['karung'])} karung "
                          f"({kg(stok['kg'])})")})
        # PK Gudang 1 — untuk pesanan yang berhenti di PK: pelanggan membawa
        # gabah, mengambil PK-nya. Keadaan yang SAH menurut kedalaman fleksibel.
        proses = (await db.execute(
            select(MillingProcess).where(MillingProcess.jasa_id == jid)
        )).scalars().all()
        if proses:
            rincian = await pk_breakdown_banyak(db, [p.id for p in proses])
            for p in proses:
                sisa = rincian[p.id].tersedia
                if sisa > 0.5:
                    out.append({"value": f"pk:{p.kode_proses}",
                                "label": f"PK {p.kode_proses} · {kg(sisa)} "
                                         "(isi dalam kg)"})
        # ── Hasil samping CURAH — pesan kerja 11, Lubang terbesar ──
        #
        # Sebelum ini picker TAK PERNAH menawarkan baris `cr:`, jadi menir/
        # broken/reject/bekatul curah milik pesanan ini TAK ADA jalan
        # keluarnya sama sekali — pesanan bisa ditutup (sebelum `sisa_jasa`
        # dibetulkan juga) sementara barangnya masih di gudang. `_satu_baris`
        # (dipanggil `_baris_dari_borang`) SUDAH mengenal awalan `cr:`; yang
        # kurang cuma picker ini menawarkannya.
        from app.penggilingan.inventory.finished_goods import hitung_stok_byproduct_curah
        from app.services.stok import nama_produk

        for jenis_curah in ("broken", "menir", "reject", "bekatul"):
            sisa_curah = await hitung_stok_byproduct_curah(db, jenis_curah, jasa_id=jid)
            if sisa_curah > 0.5:
                out.append({"value": f"cr:{jenis_curah}",
                            "label": f"{nama_produk(jenis_curah)} (curah) · "
                                     f"{kg(sisa_curah)} (isi dalam kg)"})
        # ── PK Gudang 2 — pesan kerja 11, Lubang kedua ──
        #
        # Sebelum ini PK yang sudah berdiri di silo/tumpukan Gudang 2 tak
        # punya jalan keluar sama sekali: pesanan yang berhenti di tahap ini
        # tak bisa pernah ditutup. Dicek LANGSUNG lewat pemilik tempatnya
        # (bukan cuma "ada stok jasa"), sebab satu silo satu pemilik — kalau
        # pemiliknya pesanan LAIN, silo ini bukan untuk pesanan ini walau
        # stok "jasa"-nya sendiri positif.
        from app.penggilingan.gudang2.service import (_g2_warehouse_id,
                                                       hitung_stok_silo,
                                                       hitung_stok_tumpukan)
        from app.services.jasa import pemilik_silo_g2, pemilik_tumpukan_g2
        from app.models import Silo as _Silo

        g2_wid = await _g2_warehouse_id(db)
        for silo in (await db.execute(
            select(_Silo).where(_Silo.warehouse_id == g2_wid, _Silo.jenis_isi == "pk")
            .order_by(_Silo.nama_silo)
        )).scalars().all():
            if jid not in await pemilik_silo_g2(db, silo.id):
                continue
            sisa_silo = await hitung_stok_silo(db, silo.id, pemilik="jasa")
            if sisa_silo > 0.5:
                out.append({"value": f"g2:silo:{silo.id}",
                            "label": f"PK Gudang 2 · Silo {silo.nama_silo} · "
                                     f"{kg(sisa_silo)} (isi dalam kg)"})
        if jid in await pemilik_tumpukan_g2(db):
            sisa_tumpukan = await hitung_stok_tumpukan(db, pemilik="jasa")
            if sisa_tumpukan > 0.5:
                out.append({"value": "g2:tumpukan",
                            "label": f"PK Gudang 2 · Tumpukan · "
                                     f"{kg(sisa_tumpukan)} (isi dalam kg)"})
        # ── Gabah kering ditimbang (pesan kerja 12/12A) — tumpukan Gudang 1 ──
        from app.models import GabahKeringLot
        from app.penggilingan.gudang1.services.gabah_kering import (
            pending_gabah_kering_kg)

        for lot in (await db.execute(
            select(GabahKeringLot).where(GabahKeringLot.jasa_id == jid)
        )).scalars().all():
            sisa_gkr = await pending_gabah_kering_kg(db, lot.id)
            if sisa_gkr > 0.5:
                out.append({"value": f"gk:{lot.kode_lot}",
                            "label": f"Gabah kering {lot.kode_lot} · "
                                     f"{kg(sisa_gkr)} (isi dalam kg)"})
    return out


class JasaReq(BaseModel):
    jasa: str = ""


class JasaBatalReq(JasaReq):
    sebab: str = ""


class AmbilJasaReq(BaseModel):
    jasa: str = ""
    barang: list[BarisReq] | None = None
    no_polisi: str = ""
    nama_ekspedisi: str = ""
    catatan: str = ""


@router.post("/actions/ambil-jasa")
async def act_ambil_jasa(req: AmbilJasaReq,
                         user: User = Depends(pengguna_aksi)) -> dict:
    """Terbitkan perintah PENGAMBILAN barang jasa oleh pemiliknya.

    Pembelinya tidak ditanya: barang titipan kembali kepada yang menitipkannya,
    dan medan nama di sini cuma kesempatan mengetiknya salah. `buat_perintah`
    yang menurunkannya dari pesanannya.
    """
    wajib(can_see_financials(user))
    if not (req.jasa or "").isdigit():
        raise HTTPException(400, "Pilih pesanan jasa yang barangnya diambil.")
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        baris = await _baris_dari_borang(db, req)
        try:
            r = await bk.buat_perintah(
                db, user=u, baris=baris, jasa_id=int(req.jasa),
                metode=None, no_polisi=(req.no_polisi or None),
                nama_ekspedisi=(req.nama_ekspedisi or None),
                catatan=(req.catatan or None))
        except bk.BarangKeluarError as e:
            raise galat(e, "Gagal membuat perintah pengambilan.")
        kode, pembeli = r.rec.kode, r.rec.nama_pembeli
    return {"ok": True,
            "pesan": f"✓ Perintah pengambilan *{kode}* terbit untuk {pembeli}. "
                     "Operator memuatnya dari Antrian tunggu, lalu Admin "
                     "memverifikasi dengan tiket timbang keluar."}


@router.post("/actions/tutup-jasa")
async def act_tutup_jasa(req: JasaReq,
                         user: User = Depends(pengguna_aksi)) -> dict:
    """Tutup pesanan jasa — aturan "selesai" diperiksa di layanan."""
    wajib(can_see_financials(user))
    from app.services.jasa import JasaError, tutup_pesanan

    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            pesan = await tutup_pesanan(db, user=u, jasa_id=int(req.jasa))
        except (JasaError, ValueError) as e:
            raise galat(e, "Gagal menutup pesanan jasa.")
    return {"ok": True, "pesan": pesan}


@router.post("/actions/batalkan-jasa")
async def act_batalkan_jasa(req: JasaBatalReq,
                            user: User = Depends(pengguna_aksi)) -> dict:
    """Batalkan pesanan jasa yang BELUM pernah menerima barang."""
    wajib(can_see_financials(user))
    from app.services.jasa import JasaError, batalkan_pesanan

    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            pesan = await batalkan_pesanan(db, user=u, jasa_id=int(req.jasa),
                                           sebab=req.sebab)
        except (JasaError, ValueError) as e:
            raise galat(e, "Gagal membatalkan pesanan jasa.")
    return {"ok": True, "pesan": pesan}
