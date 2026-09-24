"""API internal untuk Meja Administrasi (repo `meja/`, service `meja`).

Kenapa ada: pemilik memutuskan 12 September 2026 bahwa seluruh pekerjaan
staf administrasi pindah ke aplikasi sendiri, dan (RANCANGAN meja §3)
aplikasi itu TIPIS di atas Pos Produksi — tabel dan aturan bisnis tetap
milik repo ini, Meja hanya menggambar dan meneruskan. Maka yang ada di sini
bukan logika baru melainkan BUNGKUS JSON atas layanan yang sudah dipakai
layar admin Pos Produksi: `services.berjalan`, `stok`, `audit`, `undo`,
`setelan`, `user_admin`, dan pengelolaan alat. Aksi tulis (`/api/*`)
serta laporan (`/api/laporan/*`) TIDAK dibungkus ulang: Meja memanggilnya
langsung, karena `akun_opsional` sudah mengenali token Meja + header akun.

Keamanan:
  · Aktif hanya bila env `MEJA_API_TOKEN` diisi (kosong → 404).
  · Setiap permintaan wajib `X-Internal-Token`; selain `/masuk`, wajib pula
    `X-Meja-Akun` + `X-Meja-Versi` — akun yang diwakili, diperiksa dengan
    aturan sesi yang SAMA dengan cookie (`security.akun_opsional`).
  · Gerbang peran memakai properti akun yang sama dengan layar
    (`is_admin`, `is_super`), bukan daftar nama peran baru.

Saat layar admin Pos Produksi dipensiunkan (satu rilis pindahan, keputusan
pemilik), router inilah yang tersisa sebagai pintu meja — jadi jangan
menaruh aturan di sini yang tidak ada di layanannya.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select

from app.config import settings
from app.database import SessionLocal, now_local
from app.models import ProduksiAkun, User
from app.web import csrf as _csrf
from app.web.security import ada_superadmin, akun_opsional, hash_sandi
from hmu_identitas import masuk as identitas
from hmu_identitas import peran as P
from hmu_identitas import pintu

router = APIRouter(prefix="/internal/meja", tags=["internal-meja"])
log = logging.getLogger("web.meja_api")

#: Gudang sebagai DATA (RANCANGAN meja §7): kunci pendek → (awalan nama di
#: master `warehouses`, fungsi). Menambah gudang = menambah baris di master;
#: kunci di sini hanya menautkan penyusun kartu yang memang per gudang
#: (`berjalan.untuk_gudang1/2`).
#: Daftar gudang hidup di `app.web.layar` sejak Pos Produksi memakainya juga
#: (24 Sep 2026). Diimpor, bukan disalin.
from app.web.layar import GUDANG, NAMA_GUDANG  # noqa: E402


# ─────────────────────────── Penjaga ───────────────────────────

def _pastikan_token(request: Request) -> None:
    if not settings.meja_api_token:
        raise HTTPException(status_code=404, detail="API Meja tidak aktif.")
    if not _csrf.dari_meja(request.headers):
        raise HTTPException(status_code=403, detail="Token Meja tidak valid.")


async def akun_meja(request: Request) -> ProduksiAkun:
    """Akun yang diwakili Meja — lewat jalur yang sama dengan cookie."""
    _pastikan_token(request)
    akun = await akun_opsional(request)
    if akun is None:
        raise HTTPException(status_code=401, detail="Sesi Meja tidak berlaku — masuk lagi.")
    return akun


async def akun_admin(akun: ProduksiAkun = Depends(akun_meja)) -> ProduksiAkun:
    if not akun.is_admin:
        raise HTTPException(status_code=403, detail="Hanya untuk staf administrasi.")
    return akun


async def akun_super(akun: ProduksiAkun = Depends(akun_meja)) -> ProduksiAkun:
    # Aturan yang sama dengan `security.butuh_super`, termasuk jaring
    # pengaman "belum ada Super Admin → Admin diterima".
    if not akun.is_super and not (akun.is_admin and not await ada_superadmin()):
        raise HTTPException(status_code=403, detail="Hanya untuk Super Admin.")
    return akun


# ─────────────────────────── Bentuk JSON ───────────────────────────

def _ser(o):
    """Dataclass/datetime/Decimal → bentuk JSON. Tupel jadi daftar."""
    if is_dataclass(o) and not isinstance(o, type):
        return _ser(asdict(o))
    if isinstance(o, datetime):
        return o.isoformat()
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, dict):
        return {k: _ser(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_ser(x) for x in o]
    return o


def _akun_json(akun: ProduksiAkun, request: Request | None = None) -> dict:
    return {
        "akun_id": akun.id, "username": akun.username, "nama": akun.nama,
        "peran": akun.peran, "versi": akun.token_version or 1,
        "harus_ganti_sandi": bool(akun.harus_ganti_sandi),
        "sesi_pendek": akun.sesi_pendek,
        "is_admin": akun.is_admin, "is_super": akun.is_super,
        "lingkup": getattr(akun, "_lingkup", None),
        "peran_asli": getattr(request.state, "peran_asli", None) if request else None,
        "lihat_sebagai": getattr(request.state, "lihat_sebagai", None) if request else None,
        "view": getattr(request.state, "view", None) if request else None,
    }


# ─────────────────────────── Masuk & akun ───────────────────────────

class MasukIn(BaseModel):
    username: str
    sandi: str
    ip: str = ""
    #: Aplikasi yang meminta: "meja" atau "gudang2" (pintu per aplikasi,
    #: keputusan pemilik 13 Sep 2026). Kosong = tanpa pemeriksaan pintu
    #: (klien lama) — pintu di sisi klien tetap menjaga.
    aplikasi: str = ""


async def _lingkup(db, akun: ProduksiAkun) -> str:
    """Lingkup gudang orang ini, dari nama gudang bawaannya di master."""
    nama = None
    if P.operator_saja(akun.peran) and akun.user.default_warehouse_id:
        from app.models import Warehouse
        nama = (await db.execute(select(Warehouse.nama_gudang).where(
            Warehouse.id == akun.user.default_warehouse_id))).scalar()
    return P.lingkup(akun.peran, nama)


@router.post("/masuk")
async def masuk(body: MasukIn, request: Request) -> dict:
    """Periksa kredensial atas nama Meja. Aturannya persis `auth.proses_masuk`:
    pembatas percobaan per nama+alamat, waktu jawab yang sama untuk nama yang
    tak ada, status master ikut diperiksa."""
    _pastikan_token(request)
    from app.web import gerbang_masuk as gerbang

    uname = body.username.strip().lower()
    ip = body.ip or (request.client.host if request.client else "")
    sisa = gerbang.boleh_coba(uname, ip)
    if sisa is not None:
        raise HTTPException(429, f"Terlalu banyak percobaan. Coba lagi {int(sisa // 60) + 1} "
                                 "menit lagi, atau hubungi Super Admin bila lupa sandi.")
    async with SessionLocal() as db:
        try:
            akun = await identitas.periksa_kredensial(db, uname, body.sandi)
        except identitas.Tolak as e:
            gerbang.catat_gagal(uname, ip)
            raise HTTPException(e.kode, e.pesan)
        akun._lingkup = await _lingkup(db, akun)
        if body.aplikasi:
            sebab = pintu.sebab_tolak(akun.peran, body.aplikasi, akun._lingkup)
            if sebab:
                # Pintu peran BUKAN tebakan sandi: sandinya baru saja terbukti
                # benar. Dulu penolakan ini ikut dihitung, dan hitungannya satu
                # untuk seluruh pabrik (satu proses, kunci nama+IP) — jadi
                # operator yang lima kali salah membuka app Meja terkunci lima
                # menit dari Pos Produksi DAN app Gudang 2, kedua app yang sah
                # baginya, dengan pesan yang tak menyebut sebabnya. QA 24 Sep
                # 2026 (c) butir 1.
                gerbang.catat_sandi_benar(uname, ip)
                raise HTTPException(403, sebab)
        gerbang.catat_berhasil(uname, ip)
        akun.terakhir_login = now_local()
        await db.commit()
        await db.refresh(akun)
        return _akun_json(akun)


@router.get("/saya")
async def saya(request: Request, akun: ProduksiAkun = Depends(akun_meja)) -> dict:
    return _akun_json(akun, request)


class NamaIn(BaseModel):
    nama: str


@router.post("/akun/nama")
async def ganti_nama(body: NamaIn, akun: ProduksiAkun = Depends(akun_meja)) -> dict:
    """Cermin `pengaturan.ganti_nama`: nama kembar ditolak — nama ini pelaku
    di seluruh catatan."""
    nama = " ".join(body.nama.split())
    if len(nama) < 3:
        raise HTTPException(400, "Nama minimal 3 huruf.")
    async with SessionLocal() as db:
        orang = await db.get(User, akun.user_id)
        kembar = (await db.execute(
            select(User).where(func.lower(User.nama) == nama.lower(), User.id != orang.id)
        )).scalars().first()
        if kembar is not None:
            raise HTTPException(400, "Nama itu sudah dipakai orang lain. Nama Anda tertulis "
                                     "sebagai pelaku di setiap catatan, jadi dua orang bernama "
                                     "sama membuat catatan keduanya tak bisa dibedakan lagi.")
        orang.nama = nama
        await db.commit()
    return {"ok": True, "pesan": "Nama Anda sudah diperbarui.", "nama": nama}


class SandiIn(BaseModel):
    sandi_lama: str = ""
    sandi_baru: str
    ulangi: str


@router.post("/akun/ganti-sandi")
async def ganti_sandi(body: SandiIn, akun: ProduksiAkun = Depends(akun_meja)) -> dict:
    """Cermin `auth.proses_ganti_sandi`. Versi token naik → Meja menerima
    versi baru dan memperbarui sesinya sendiri."""
    if body.sandi_baru != body.ulangi:
        raise HTTPException(400, "Kata sandi baru dan ulangannya tidak sama.")
    async with SessionLocal() as db:
        try:
            versi = await identitas.ganti_sandi(
                db, akun, sandi_lama=body.sandi_lama, sandi_baru=body.sandi_baru,
                wajib_lama=not akun.harus_ganti_sandi)
        except identitas.Tolak as e:
            raise HTTPException(e.kode, e.pesan)
    return {"ok": True, "pesan": "Kata sandi berhasil diganti.", "versi": versi}


@router.post("/akun/keluar-semua")
async def keluar_semua(akun: ProduksiAkun = Depends(akun_meja)) -> dict:
    from app.web.auth import naikkan_versi_token

    await naikkan_versi_token(akun.id, sebab="keluar dari semua perangkat (Meja)")
    return {"ok": True}


# ─────────────────────────── Kartu & layar ───────────────────────────

def _beri_gudang(daftar, gid: str) -> list[dict]:
    """Serialisasi kartu + tanda gudang; subjudul menyebut gudangnya supaya
    daftar lintas gudang tak menuntut pembacanya menebak."""
    keluar = []
    nama = NAMA_GUDANG.get(gid, "")
    for b in daftar:
        d = _ser(b)
        d["gudang"] = gid
        if nama and nama not in (d.get("sub") or "") and nama not in (d.get("judul") or ""):
            d["sub"] = f"{d['sub']} · {nama}" if d.get("sub") else nama
        keluar.append(d)
    return keluar


async def _susun(db, akun: ProduksiAkun) -> dict:
    """Seluruh kartu meja, per golongan, sudah bertanda gudang."""
    from app.services import berjalan as svc

    g1 = await svc.untuk_gudang1(db)
    g2 = await svc.untuk_gudang2(db)
    s = await svc.untuk_staff(db)
    # Kedua pemancar tiket (PK luar & jenis tak dikenal) PINDAH ke
    # `services.berjalan` pada 24 September 2026, sebab tiket PK harus sampai ke
    # antrean POS PRODUKSI juga — jaring yang hanya dipanggil Meja tak pernah
    # menyentuh keluhan pemiliknya. Di sini ia tak dipanggil lagi: `g2.menunggu`
    # sudah membawa tiket PK, `s.menunggu` membawa yang jenisnya tak dikenal.
    # Memanggilnya lagi berarti tiket yang sama terangkut DUA KALI.
    #
    # Tiket jenis tak dikenal TIDAK diberi tanda gudang: jenis yang belum
    # dipetakan belum punya gudang, dan menebaknya berarti mengarahkan orang ke
    # gudang yang mungkin salah.
    menunggu = _ser(s.menunggu) + _beri_gudang(g2.menunggu, "g2")
    berjalan = _beri_gudang(g1.berjalan, "g1") + _beri_gudang(g2.berjalan, "g2")
    transit = _beri_gudang(g1.transit, "g1") + _beri_gudang(g2.transit, "g2")
    meja = _beri_gudang(s.meja, "g1") + _beri_gudang(g2.meja, "g2")
    return {"menunggu": menunggu, "berjalan": berjalan, "transit": transit, "meja": meja,
            # KEPUTUSAN di sini sengaja menghitung SELURUH kerja meja, termasuk
            # golongan mutu. Pos Produksi memecahnya jadi dua layar & dua
            # lencana 24 September 2026; app Meja tidak ikut dipecah — ia sedang
            # dipensiunkan, dan layar /keputusan-nya memang menggambar semuanya.
            # Memakai `jumlah_keputusan` di sini akan membuat lencananya
            # menjanjikan lebih sedikit daripada yang digambarnya.
            "lencana": {"MENUNGGU": len(menunggu), "BERJALAN": len(berjalan) + len(transit),
                        "KEPUTUSAN": len(meja)}}


@router.get("/beranda")
async def beranda(akun: ProduksiAkun = Depends(akun_meja)) -> dict:
    """Papan Beranda Meja. Perhitungannya PINDAH ke `services.beranda` pada 24
    September 2026, saat Beranda Pos Produksi memerlukannya juga: dua Beranda
    yang menghitung penyimpangan sendiri-sendiri akan menyebut angka berbeda
    tentang pabrik yang sama, dan tak ada yang menyadarinya sebab tak ada yang
    membuka keduanya berdampingan."""
    from app.services import beranda as svc_beranda

    async with SessionLocal() as db:
        kartu = await _susun(db, akun)
        p = await svc_beranda.papan(db, kartu["berjalan"], kartu["meja"])
        a = await svc_beranda.angka_gudang(db)
    return {
        "lencana": kartu["lencana"], "perhatian": p.perhatian,
        "petak": svc_beranda.petak_pabrik(a, kartu["berjalan"]), "gudang": p.gudang,
        "n_harga": p.n_harga, "n_output": p.n_output, "n_mutu": p.n_mutu,
    }


@router.get("/gudang")
async def daftar_gudang(akun: ProduksiAkun = Depends(akun_meja)) -> list[dict]:
    return [{"id": g, "nama": n, "fungsi": f} for g, n, f in GUDANG]


@router.get("/gudang/{gid}")
async def satu_gudang(gid: str, akun: ProduksiAkun = Depends(akun_meja)) -> dict:
    if gid not in NAMA_GUDANG:
        raise HTTPException(404, "Gudang tidak dikenal.")
    from app.services.dashboard import dashboard_data
    from app.web.layar import _petak_g1, _petak_g2

    async with SessionLocal() as db:
        kartu = await _susun(db, akun)
        if gid == "g1":
            o = (await dashboard_data(db)).get("operasional", {}) or {}
            petak = _petak_g1(o)
        else:
            petak = await _petak_g2(db)
    fungsi = next(f for g, _, f in GUDANG if g == gid)
    return {"id": gid, "nama": NAMA_GUDANG[gid], "fungsi": fungsi, "petak": petak,
            "berjalan": [b for b in kartu["berjalan"] if b["gudang"] == gid],
            "transit": [b for b in kartu["transit"] if b["gudang"] == gid],
            "lencana": kartu["lencana"]}


@router.get("/kartu")
async def kartu(akun: ProduksiAkun = Depends(akun_meja)) -> dict:
    """Seluruh kartu sekaligus — dipakai Antrian, Sedang berjalan, Keputusan."""
    async with SessionLocal() as db:
        return await _susun(db, akun)


@router.get("/stok")
async def stok(akun: ProduksiAkun = Depends(akun_meja)) -> dict:
    from app.penggilingan.inventory import packaging as kms
    from app.services import stok as svc
    from app.services.setelan import fitur_mutu

    async with SessionLocal() as db:
        lot = await svc.pk_gudang1(db)
        tempat = await svc.pk_gudang2(db)
        mutu = await fitur_mutu(db)
        # Barang jadi & hasil samping: hitungan yang SAMA dengan yang dipakai
        # layar Pos Produksi dan aplikasi Gudang 2 (`services.stok.
        # barang_jadi_g2`). Sampai 23 September 2026 Meja menerima rupa TEKS-nya
        # dari laporan `stok_barang_jadi` — bentuk yang tak bisa menyebut asal
        # per proses sosoh, padahal itu yang ditanya orang saat ada keluhan mutu.
        bjg2 = await svc.barang_jadi_g2(db)
        # Stok karung (keputusan pemilik 23 September 2026). Meja memegang
        # KEDUA gudang, jadi ia melihat seluruh barisnya — termasuk karung PK
        # di Gudang 1, karena Meja-lah yang memesannya.
        #
        # Kunci pendek gudangnya ikut dikirim, diterjemahkan dari tabel yang
        # SUDAH ada di modul ini (`GUDANG`). Penyaring "gudang mana" di kepala
        # halaman Meja memakai kunci itu; membiarkan Meja menerjemahkan sendiri
        # nama gudang berarti menaruh aturan di aplikasi yang sengaja tak
        # memegang aturan — dan nama gudang hidup di master, bisa berubah.
        _kunci = {n: k for k, n in NAMA_GUDANG.items()}
        karung = [{**k, "gudang_id": _kunci.get(k["gudang"], "")}
                  for k in await kms.stok_kemasan_rinci(db)]
        kartu_ = await _susun(db, akun)
    return {"lot": _ser(lot), "tempat": _ser(tempat), "mutu_aktif": mutu,
            "produk": bjg2.produk, "samping": bjg2.samping, "karung": karung,
            "lencana": kartu_["lencana"]}


@router.get("/laporan")
async def daftar_laporan(akun: ProduksiAkun = Depends(akun_meja)) -> dict:
    from app.web.laporan import PERIODE, daftar_untuk

    return {"daftar": [{"kode": l.kode, "nama": l.nama, "arti": l.arti,
                        "berperiode": l.berperiode, "uang": l.uang}
                       for l in daftar_untuk(akun.user)],
            "periode": list(PERIODE)}


@router.get("/audit")
async def audit(rentang: str = "48j", kelompok: str = "semua", cari: str = "",
                akun: ProduksiAkun = Depends(akun_admin)) -> dict:
    from app.services import audit as svc
    from app.services import undo as undo_svc

    async with SessionLocal() as db:
        catatan, semua = await svc.daftar(db, rentang=rentang, kelompok=kelompok, cari=cari)
        pratinjau = await undo_svc.pratinjau_terakhir(db, cakupan=None)
        kartu_ = await _susun(db, akun)
    return {"catatan": _ser(catatan), "semua": semua, "pratinjau": _ser(pratinjau),
            "RENTANG": [[k, n] for k, n, _ in svc.RENTANG],
            "KELOMPOK": [[k, n] for k, n, _ in svc.KELOMPOK],
            "JAM_BATAS": int(svc.BATAS_UBAH.total_seconds() // 3600),
            "lencana": kartu_["lencana"]}


class BatalkanIn(BaseModel):
    log_id: int | None = None


@router.post("/audit/batalkan")
async def audit_batalkan(body: BatalkanIn, akun: ProduksiAkun = Depends(akun_admin)) -> dict:
    from app.services import undo as undo_svc

    async with SessionLocal() as db:
        try:
            hasil = await undo_svc.undo_last(db, actor=akun.user, cakupan=None,
                                             log_id=body.log_id)
        except undo_svc.UndoError as e:
            raise HTTPException(400, e.args[0] if e.args else "Gagal membatalkan.")
    return {"ok": True, "pesan": hasil}


# ─────────────────────────── Pengaturan ───────────────────────────

@router.get("/pengaturan")
async def pengaturan(akun: ProduksiAkun = Depends(akun_meja)) -> dict:
    from app.services.setelan import fitur_mutu, sebab_jeda, target_kadar_air
    from app.services.undo import BATAS_UNDO

    boleh = akun.is_admin
    async with SessionLocal() as db:
        target = await target_kadar_air(db) if boleh else None
        sebab = await sebab_jeda(db) if boleh else {}
        mutu = await fitur_mutu(db) if boleh else False
    return {"boleh_setelan": boleh,
            "boleh_kelola": akun.is_super or (akun.is_admin and not await ada_superadmin()),
            "ada_super": await ada_superadmin(),
            "target_bawaan": target, "sebab_jeda": sebab, "mutu_aktif": mutu,
            "JAM_BATAS": int(BATAS_UNDO.total_seconds() // 3600)}


class TargetIn(BaseModel):
    nilai: float


@router.post("/pengaturan/target-kadar-air")
async def set_target(body: TargetIn, akun: ProduksiAkun = Depends(akun_admin)) -> dict:
    from app.services.setelan import set_target_kadar_air

    async with SessionLocal() as db:
        u = await db.get(User, akun.user.id)
        try:
            await set_target_kadar_air(db, body.nilai, user=u)
        except ValueError as e:
            raise HTTPException(400, str(e))
    return {"ok": True, "pesan": "Target kadar air bawaan sudah diperbarui."}


class MutuIn(BaseModel):
    aktif: bool


@router.post("/pengaturan/fitur-mutu")
async def set_mutu(body: MutuIn, akun: ProduksiAkun = Depends(akun_admin)) -> dict:
    from app.services.setelan import set_fitur_mutu

    async with SessionLocal() as db:
        u = await db.get(User, akun.user.id)
        await set_fitur_mutu(db, body.aktif, user=u)
    return {"ok": True, "pesan": ("Pencatatan mutu dinyalakan." if body.aktif else
                                 "Pencatatan mutu dimatikan — borang QC dan baris mutu "
                                 "disembunyikan dari semua layar.")}


class SebabIn(BaseModel):
    jenis: str
    tambah: str = ""
    buang: str = ""


@router.post("/pengaturan/sebab-jeda")
async def set_sebab(body: SebabIn, akun: ProduksiAkun = Depends(akun_admin)) -> dict:
    from app.services.setelan import sebab_jeda, set_sebab_jeda

    async with SessionLocal() as db:
        u = await db.get(User, akun.user.id)
        daftar = await sebab_jeda(db)
        if body.jenis not in daftar:
            raise HTTPException(400, "Jenis proses tak dikenal.")
        isi = list(daftar[body.jenis])
        tambah, buang = body.tambah.strip(), body.buang.strip()
        if tambah:
            if tambah in isi:
                raise HTTPException(400, "Sebab itu sudah ada.")
            isi.append(tambah[:120])
        elif buang:
            if buang not in isi:
                raise HTTPException(400, "Sebab itu sudah tak ada.")
            isi.remove(buang)
        else:
            return {"ok": True, "pesan": ""}
        daftar[body.jenis] = isi
        try:
            await set_sebab_jeda(db, daftar, user=u)
        except ValueError as e:
            raise HTTPException(400, str(e))
    return {"ok": True, "pesan": "Daftar sebab berhenti sudah diperbarui."}


# ─────────────────────────── Pengguna (Super Admin) ───────────────────────────

@router.get("/pengguna")
async def pengguna(akun: ProduksiAkun = Depends(akun_super)) -> dict:
    from app.web.pengguna import PERAN, _muat

    d = await _muat()
    return {"PERAN": [list(p) for p in PERAN], "belum": d["belum"],
            "akun_list": [{"id": a.id, "nama": a.nama, "username": a.username,
                           "peran": a.peran, "mode_perangkat": a.mode_perangkat,
                           "status": a.status, "harus_ganti_sandi": a.harus_ganti_sandi,
                           "gudang": None}
                          for a in d["akun_list"]]}


class OrangBaruIn(BaseModel):
    nama: str
    peran: str
    gudang: str = ""


@router.post("/pengguna/orang-baru")
async def orang_baru(body: OrangBaruIn, akun: ProduksiAkun = Depends(akun_super)) -> dict:
    from app.services.user_admin import UserAdminError, register_user
    from app.web.pengguna import PERAN

    nama = " ".join(body.nama.split())
    if len(nama) < 3:
        raise HTTPException(400, "Nama minimal 3 huruf.")
    if body.peran not in {p[0] for p in PERAN}:
        raise HTTPException(400, "Peran tidak dikenal.")
    if P.terlalu_tinggi(akun.peran, body.peran):
        raise HTTPException(400, "Peran itu lebih tinggi daripada peran Anda.")
    async with SessionLocal() as db:
        kembar = (await db.execute(
            select(User).where(User.nama == nama, User.status != "nonaktif")
        )).scalars().first()
        if kembar is not None:
            raise HTTPException(400, f"'{nama}' sudah terdaftar sebagai {kembar.role}. "
                                     "Bila ini orang lain, bedakan namanya.")
        try:
            pesan = await register_user(
                db, actor=akun.user, nama=nama, role=body.peran,
                gudang=int(body.gudang) if body.gudang in ("1", "2") else None,
                telegram_id=None, no_hp=None, lewat_sandi=True)
        except UserAdminError as e:
            raise HTTPException(400, str(e.args[0] if e.args else e))
    return {"ok": True, "pesan": pesan}


class BuatAkunIn(BaseModel):
    user_id: int
    username: str


@router.post("/pengguna/buat")
async def buat_akun(body: BuatAkunIn, akun: ProduksiAkun = Depends(akun_super)) -> dict:
    from app.models.akun import mode_bawaan
    from app.web.pengguna import _catat, _terlalu_tinggi
    from app.web.security import sandi_acak

    uname = body.username.strip().lower()
    if not uname or " " in uname or len(uname) < 3:
        raise HTTPException(400, "Nama pengguna minimal 3 huruf, tanpa spasi.")
    sandi = sandi_acak()
    async with SessionLocal() as db:
        orang = await db.get(User, body.user_id)
        if orang is None:
            raise HTTPException(400, "Orang itu tidak ada di daftar pengguna.")
        if _terlalu_tinggi(akun, orang.role):
            raise HTTPException(400, "Orang itu berperan lebih tinggi daripada Anda.")
        if (await db.execute(select(ProduksiAkun).where(ProduksiAkun.username == uname))
                ).scalars().first() is not None:
            raise HTTPException(400, f"Nama pengguna '{uname}' sudah dipakai.")
        baru = ProduksiAkun(user_id=orang.id, username=uname, password_hash=hash_sandi(sandi),
                            mode_perangkat=mode_bawaan(orang.role), harus_ganti_sandi=True)
        db.add(baru)
        await db.flush()
        await _catat(db, baru.id, "buat login", f"{orang.nama} ({uname})", akun,
                     f"peran {orang.role}")
        await db.commit()
        nama = orang.nama
    return {"ok": True, "sandi_awal": {"nama": nama, "username": uname, "sandi": sandi,
                                       "judul": "Akun dibuat"}}


class AkunIdIn(BaseModel):
    akun_id: int
    mode: str = ""


@router.post("/pengguna/reset")
async def reset_sandi(body: AkunIdIn, akun: ProduksiAkun = Depends(akun_super)) -> dict:
    from app.web.pengguna import _catat, _terlalu_tinggi
    from app.web.security import sandi_acak

    sandi = sandi_acak()
    async with SessionLocal() as db:
        a = await db.get(ProduksiAkun, body.akun_id)
        if a is None:
            raise HTTPException(404, "Akun tidak ditemukan.")
        if _terlalu_tinggi(akun, a.peran):
            raise HTTPException(400, "Akun itu berperan lebih tinggi daripada Anda.")
        a.password_hash = hash_sandi(sandi)
        a.harus_ganti_sandi = True
        a.token_version = (a.token_version or 1) + 1
        uname, nama = a.username, a.nama
        await _catat(db, a.id, "reset sandi", f"{nama} ({uname})", akun)
        await db.commit()
    return {"ok": True, "sandi_awal": {"nama": nama, "username": uname, "sandi": sandi,
                                       "judul": "Sandi disetel ulang"}}


@router.post("/pengguna/status")
async def ubah_status(body: AkunIdIn, akun: ProduksiAkun = Depends(akun_super)) -> dict:
    from app.web.pengguna import _catat, _terlalu_tinggi

    async with SessionLocal() as db:
        a = await db.get(ProduksiAkun, body.akun_id)
        if a is None:
            raise HTTPException(404, "Akun tidak ditemukan.")
        if _terlalu_tinggi(akun, a.peran):
            raise HTTPException(400, "Akun itu berperan lebih tinggi daripada Anda.")
        aktifkan = a.status != "aktif"
        try:
            # SATU saklar (paket identitas): users.status + cermin di akun +
            # versi naik → putus di produksi, timbangan, Meja, Gudang 2, Kantor.
            await identitas.nonaktifkan(db, a.user_id, aktif=aktifkan)
        except identitas.Tolak as e:
            raise HTTPException(e.kode, e.pesan)
        await db.refresh(a)
        pesan = (f"Akun '{a.username}' sekarang {a.status} — berlaku juga di Kantor dan Timbangan.")
        await _catat(db, a.id, f"status → {a.status}", a.username, akun, "termasuk users.status")
        await db.commit()
    return {"ok": True, "pesan": pesan}


@router.post("/pengguna/mode")
async def ubah_mode(body: AkunIdIn, akun: ProduksiAkun = Depends(akun_super)) -> dict:
    if body.mode not in ("pribadi", "bersama"):
        raise HTTPException(400, "Jenis perangkat tidak dikenal.")
    async with SessionLocal() as db:
        a = await db.get(ProduksiAkun, body.akun_id)
        if a is None:
            raise HTTPException(404, "Akun tidak ditemukan.")
        a.mode_perangkat = body.mode
        await db.commit()
        pesan = (f"Perangkat '{a.username}' disetel ke "
                 f"{'milik gudang (sesi pendek)' if body.mode == 'bersama' else 'milik sendiri (sesi panjang)'}.")
    return {"ok": True, "pesan": pesan}


# ─────────────────────────── Alat (Super Admin) ───────────────────────────

# ─────────────────────────── Versi & skema ───────────────────────────

@router.get("/versi")
async def versi() -> dict:
    """Keadaan MIGRASI layanan ini — untuk baris versi di Meja & Gudang 2.

    Keduanya tak punya alembic sendiri (tak punya basis data sama sekali), dan
    baris versi mereka harus tetap menjawab pertanyaan yang baris itu dibuat
    untuk menjawab: "apakah perbaikannya sudah sampai?". VERSI aset dan commit
    adalah milik mereka sendiri; revisi migrasi hanya ada di sini.

    Yang dikirim cuma tiga nama revisi. Tak ada nilai variabel, tak ada commit
    — commit tiap app dibaca app itu sendiri dari image-nya sendiri, dan
    mengirim commit produksi ke layar Meja justru akan menyesatkan.

    Tanpa gerbang peran: angka ini dibacakan operator ke QA lewat telepon, dan
    ia sudah di balik `X-Internal-Token`.
    """
    from app.web import versi as _versi
    from app.web.skema import keadaan

    k = await keadaan()
    return {"revisi": k["revisi"], "head": k["head"],
            "keadaan": _versi.banding(k["revisi"], k["head"])}


@router.get("/alat")
async def alat(akun: ProduksiAkun = Depends(akun_super)) -> dict:
    from app.penggilingan.gudang1.services.drying import dryers_g1
    from app.penggilingan.gudang1.services.silo import _silo_content_kg, silos_g1
    from app.web.pengaturan import MAKS_ALAT

    async with SessionLocal() as db:
        mesin = [{"id": d.id, "nama": d.nama, "kapasitas": float(d.kapasitas_kg or 0),
                  "status": d.status} for d in await dryers_g1(db)]
        silo = [{"id": s.id, "nama_silo": s.nama_silo,
                 "kg": float(await _silo_content_kg(db, s.id))} for s in await silos_g1(db)]
    return {"mesin": mesin, "silo": silo, "maks": MAKS_ALAT}


class DryerIn(BaseModel):
    nama: str
    kapasitas_kg: int


@router.post("/alat/dryer")
async def tambah_dryer(body: DryerIn, akun: ProduksiAkun = Depends(akun_super)) -> dict:
    from app.models import Dryer
    from app.penggilingan.gudang1.services.drying import dryers_g1
    from app.penggilingan.gudang1.services.silo import _g1_warehouse_id
    from app.web.pengaturan import MAKS_ALAT

    nama = " ".join(body.nama.split())
    if len(nama) < 3:
        raise HTTPException(400, "Nama alat minimal 3 huruf.")
    if body.kapasitas_kg <= 0:
        raise HTTPException(400, "Kapasitas harus lebih dari 0 kg.")
    async with SessionLocal() as db:
        ada = await dryers_g1(db)
        if len(ada) >= MAKS_ALAT:
            raise HTTPException(400, f"Sudah ada {MAKS_ALAT} alat — nonaktifkan dulu.")
        if any(d.nama.lower() == nama.lower() for d in ada):
            raise HTTPException(400, "Sudah ada alat dengan nama itu.")
        db.add(Dryer(warehouse_id=await _g1_warehouse_id(db), nama=nama,
                     kapasitas_kg=body.kapasitas_kg, status="aktif"))
        await db.commit()
    return {"ok": True, "pesan": "Alat baru ditambahkan."}


class SiloIn(BaseModel):
    nama: str


@router.post("/alat/silo")
async def tambah_silo(body: SiloIn, akun: ProduksiAkun = Depends(akun_super)) -> dict:
    from app.models import Silo
    from app.penggilingan.gudang1.services.silo import _g1_warehouse_id, silos_g1
    from app.web.pengaturan import MAKS_ALAT

    nama = " ".join(body.nama.split())
    if nama.lower().startswith("silo "):
        nama = nama[5:].strip()
    if len(nama) < 1:
        raise HTTPException(400, "Nama silo wajib diisi.")
    penuh = f"Silo {nama}"
    async with SessionLocal() as db:
        ada = await silos_g1(db)
        if len(ada) >= MAKS_ALAT:
            raise HTTPException(400, f"Sudah ada {MAKS_ALAT} alat.")
        if any(s.nama_silo.lower() == penuh.lower() for s in ada):
            raise HTTPException(400, "Sudah ada alat dengan nama itu.")
        db.add(Silo(warehouse_id=await _g1_warehouse_id(db), nama_silo=penuh, kapasitas_ton=0))
        await db.commit()
    return {"ok": True, "pesan": "Alat baru ditambahkan."}


class DryerStatusIn(BaseModel):
    dryer_id: int


@router.post("/alat/dryer/status")
async def status_dryer(body: DryerStatusIn, akun: ProduksiAkun = Depends(akun_super)) -> dict:
    from app.models import Dryer
    from app.penggilingan.gudang1.services.drying import active_drying_lot

    async with SessionLocal() as db:
        d = await db.get(Dryer, body.dryer_id)
        if d is None:
            raise HTTPException(404, "Mesin tidak ditemukan.")
        if d.status == "aktif":
            if await active_drying_lot(db, d.id) is not None:
                raise HTTPException(400, "Alat itu masih ada isinya — kosongkan dulu.")
            d.status = "nonaktif"
        else:
            d.status = "aktif"
        await db.commit()
    return {"ok": True, "pesan": "Alat diperbarui."}
