"""Mode uji — menghapus data percobaan setelah fase uji selesai.

DUA JAMINAN, dan keduanya struktural, bukan sekadar kehati-hatian.

**Tiket timbang tak mungkin ikut terhapus.** Basis datanya dipakai bersama
aplikasi Timbangan, dan tiket adalah miliknya.

Versi pertama fitur ini memakai `TRUNCATE ... CASCADE` dan bersandar pada
kenyataan bahwa `Base.metadata` produksi tidak memuat satu pun tabel
`timbangan_*`. Alasan itu SALAH, dan ujinya menangkapnya: CASCADE tidak
berhenti di tabel yang disebut — ia merambat KELUAR lewat foreign key yang
MASUK. `timbangan_transaksi` menunjuk ke `suppliers`, `purchase_batches`, dan
`pk_purchase_batches`; sekali truncate, seluruh tiket ikut lenyap. Terbukti:
2 tiket menjadi 0.

Jadi sekarang: TANPA CASCADE, dan jalan keluarnya diperiksa pada basis data
yang HIDUP, bukan pada asumsi. Tiap foreign key yang masuk dari luar daftar
hapus ditangani lebih dulu — dilepas bila kolomnya boleh kosong, dan kalau
wajib isi, seluruh penghapusan DITOLAK sambil menyebut tabelnya. Tak ada
jalan ketiga.

**Tak bisa dijalankan setelah pabrik berjalan.** Seluruh fitur ini mati
kecuali `MODE_UJI` dinyalakan di environment. Mematikannya bukan sekadar
menyembunyikan tombol: endpointnya ikut menolak.

Gerbangnya **Admin ke atas**, bukan Super Admin. Bukan pelonggaran asal:
`superadmin` belum bisa dipakai di sini. Kantor — layanan lain di basis data
yang sama — punya DELAPAN pemeriksaan `role == "admin"` yang persis (Gmail,
GajiHub, IT aset, pengetahuan, keuangan), jadi menaikkan peran pemilik ke
`superadmin` justru mematikan aksesnya di sana. Sampai Kantor ikut
disesuaikan, `admin` adalah peran tertinggi yang benar-benar berlaku.

Yang menjaga fitur ini tetap tiga lapis dan tak berkurang: `MODE_UJI` harus
menyala di environment (padam secara bawaan), harus Admin ke atas, dan
kalimatnya harus diketik persis.

Yang DIPERTAHANKAN: akun & orang (supaya masih bisa masuk sesudahnya), alat
(gudang, silo, mesin pengering), dan daftar acuan (merk, ukuran karung,
standar mutu, jenis karung). Yang lain — seluruh catatan pekerjaan — dihapus.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text

from app.config import settings
from app.database import Base, SessionLocal
from app.models import ProduksiAkun
from app.web.security import butuh_akun
from app.web.tampilan import render

router = APIRouter()

#: Bertahan melewati penghapusan.
#:
#: Akun ikut bertahan dengan sengaja: menghapusnya berarti mengunci diri
#: sendiri di luar aplikasi, dan memulihkannya menuntut `ADMIN_SANDI_AWAL`
#: dipasang ulang di Railway. Alat & daftar acuan bertahan karena ia
#: menggambarkan pabriknya, bukan pekerjaannya.
DIPERTAHANKAN = frozenset({
    "users", "produksi_akun",                       # orang & akun
    "warehouses", "silos", "dryers",                # alat
    "brands", "package_sizes", "packaging_materials",
    "rice_quality_standards",                       # daftar acuan
    # Setelan pabrik — target kadar air bawaan, daftar sebab berhenti. Ia
    # segolongan dengan alat: menggambarkan PABRIKNYA, bukan pekerjaannya.
    # Menghapusnya berarti diam-diam mengembalikan setelan yang sudah diubah
    # admin ke nilai bawaan, dan tak ada satu layar pun yang menyebutkan itu
    # terjadi.
    "setelan_pabrik",
    # ── Tiga tabel di bawah ini DIPAKAI BERSAMA aplikasi lain di basis data
    #    yang sama. Ketiganya ketahuan hanya karena diuji sungguhan; tak satu
    #    pun terlihat "milik orang lain" dari nama atau dari kode produksi.
    #
    # Vendor & pelanggan: DIPERTAHANKAN SELURUHNYA, atas keputusan pemilik.
    #
    # Keduanya master BERSAMA yang disinkronkan dari Kledo, dan Timbangan
    # sengaja tak membuat salinan sendiri: tiket hanya MENUNJUK ke sini dan
    # tidak menyimpan nama pengirimnya. Menghapus satu vendor saja membuat
    # tiket yang menunjuknya kehilangan nama — dan tiket adalah hal yang
    # justru dijaga.
    #
    # Sempat dirancang penyaring "buang yang bukan dari Kledo dan tak lagi
    # dipakai". Dibuang seluruhnya, bukan sekadar dimatikan: pada fitur yang
    # menghapus data, cabang yang tak terpakai adalah jalan salah yang
    # menunggu dipilih.
    "suppliers", "pelanggan",
    # Konfigurasi & jejak pemakaian LLM: dipakai bersama layanan Kantor —
    # kill-switch dan BATAS BIAYA. Mengosongkannya bukan menghapus data uji,
    # melainkan mereset pengaman biaya kedua aplikasi. Namanya "kantor_*"
    # peninggalan saat kedua sistem masih satu repo.
    "kantor_config", "kantor_llm_usage",
})

KALIMAT = "HAPUS DATA UJI"


def _tabel_dihapus() -> list[str]:
    return sorted(set(Base.metadata.tables) - DIPERTAHANKAN)


_SQL_TAUTAN_MASUK = """
SELECT c.conrelid::regclass::text AS dari,
       a.attname                  AS kolom,
       c.confrelid::regclass::text AS ke,
       a.attnotnull               AS wajib
FROM pg_constraint c
JOIN unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord) ON true
JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
WHERE c.contype = 'f'
  AND c.confrelid::regclass::text = ANY(:hapus)
  AND NOT (c.conrelid::regclass::text = ANY(:hapus))
"""


async def tautan_masuk(db) -> list[dict]:
    """Foreign key dari LUAR daftar hapus yang menunjuk KE DALAMNYA.

    Inilah jalan keluar yang membuat CASCADE berbahaya, dan ia tidak bisa
    dihitung dari kode produksi: yang menunjuk justru tabel milik aplikasi
    lain di basis data yang sama. Jadi ditanyakan langsung ke basis datanya.
    """
    hapus = _tabel_dihapus()
    rows = (await db.execute(text(_SQL_TAUTAN_MASUK), {"hapus": hapus})).all()
    return [{"dari": r[0], "kolom": r[1], "ke": r[2], "wajib": bool(r[3])}
            for r in rows]


def _wajib_mode_uji() -> None:
    if not settings.mode_uji:
        raise HTTPException(404, "Mode uji tidak aktif.")


async def _jumlah_baris() -> list[tuple[str, int]]:
    out = []
    async with SessionLocal() as db:
        for nama in _tabel_dihapus():
            n = (await db.execute(text(f'SELECT count(*) FROM "{nama}"'))).scalar_one()
            if n:
                out.append((nama, int(n)))
    return sorted(out, key=lambda x: -x[1])


async def _konteks(akun, **tambahan):
    async with SessionLocal() as db:
        tautan = await tautan_masuk(db)
    return dict(akun=akun, kembali="/pengaturan", baris=await _jumlah_baris(),
                dipertahankan=sorted(DIPERTAHANKAN), kalimat=KALIMAT,
                kalimat_ulang=KALIMAT_ULANG,
                dilepas=[t for t in tautan if not t["wajib"]],
                penghalang=[t for t in tautan if t["wajib"]], **tambahan)


@router.get("/pengaturan/mode-uji", response_class=HTMLResponse)
async def halaman(request: Request, akun: ProduksiAkun = Depends(butuh_akun)):
    _wajib_mode_uji()
    if not akun.is_admin:
        raise HTTPException(403, "Hanya Admin ke atas.")
    return render(request, "mode_uji.html", **await _konteks(akun))


async def _kosongkan() -> str | None:
    """Hapus seluruh catatan pekerjaan. → kalimat galat, atau None bila beres.

    Dipisah dari rutenya karena DUA tombol memakainya: "Hapus data uji" dan
    "Kembalikan data uji". Yang kedua menghapus lalu mengisi lagi — kalau
    penghapusannya disalin, cepat atau lambat salah satunya akan menyisakan
    tabel yang dilupakan yang lain.
    """
    tabel = _tabel_dihapus()
    async with SessionLocal() as db:
        tautan = await tautan_masuk(db)
        wajib = [t for t in tautan if t["wajib"]]
        if wajib:
            # Menolak, bukan memaksa. Kolom wajib isi berarti tabel di luar
            # sana akan rusak — dan tabel itu milik aplikasi lain.
            sebut = ", ".join(f"{t['dari']}.{t['kolom']} → {t['ke']}" for t in wajib)
            return ("Dibatalkan: ada tautan wajib isi dari luar — "
                    f"{sebut}. Tabel tujuannya harus dipertahankan.")

        # Lepas dulu tautan dari luar. Untuk tiket timbang inilah justru hasil
        # yang diinginkan: tiketnya kembali bebas dan bisa dicatat ulang.
        for t in tautan:
            await db.execute(
                text(f'UPDATE "{t["dari"]}" SET "{t["kolom"]}" = NULL '
                     f'WHERE "{t["kolom"]}" IS NOT NULL')
            )

        # DELETE, bukan TRUNCATE.
        #
        # TRUNCATE ditolak Postgres selama ada foreign key yang menunjuk ke
        # sasaran — SEKALIPUN barisnya sudah dilepas; keberadaan constraint-nya
        # saja sudah cukup. Satu-satunya jalan keluarnya CASCADE, dan CASCADE
        # itulah yang tadi menyapu seluruh tiket. DELETE menghormati constraint
        # baris demi baris, dan seluruh tautan masuk ber-ON DELETE NO ACTION,
        # jadi ia tak bisa merambat ke luar.
        #
        # Urutan anak-dulu diambil dari metadata, bukan ditulis tangan: daftar
        # tangan akan basi pada tabel berikutnya yang ditambahkan.
        urut = [t.name for t in reversed(Base.metadata.sorted_tables)
                if t.name in set(tabel)]
        for nama in urut:
            await db.execute(text(f'DELETE FROM "{nama}"'))
        # Nomor urut dikembalikan ke 1 supaya fase berikutnya benar-benar mulai
        # dari bersih, bukan melanjutkan nomor bekas percobaan.
        #
        # HANYA tabel yang benar-benar punya kolom `id`. Penjaga
        # `pg_get_serial_sequence(...) IS NOT NULL` tidak cukup: Postgres
        # sudah menyerah lebih dulu saat mencari kolomnya, jadi tabel
        # berkunci lain — `setelan_pabrik` berkunci `kunci` — menjatuhkan
        # seluruh penghapusan dengan Internal Server Error, sesudah DELETE-nya
        # terlanjur berjalan. Daftarnya dibaca dari metadata, bukan ditulis
        # tangan, supaya tabel berikutnya yang berkunci lain tak mengulanginya.
        berid = {t.name for t in Base.metadata.sorted_tables if "id" in t.columns}
        for nama in [n for n in urut if n in berid]:
            await db.execute(text(
                "SELECT setval(pg_get_serial_sequence(:t, 'id'), 1, false) "
                "WHERE pg_get_serial_sequence(:t, 'id') IS NOT NULL"
            ), {"t": nama})
        await db.commit()

    # Daftar acuan & alat dipulihkan kalau ada yang belum ada; idempoten.
    from app.services.seed import seed_master
    await seed_master()
    return None


@router.post("/pengaturan/mode-uji")
async def hapus(request: Request, akun: ProduksiAkun = Depends(butuh_akun)):
    _wajib_mode_uji()
    if not akun.is_admin:
        raise HTTPException(403, "Hanya Admin ke atas.")
    form = await request.form()
    if (form.get("kalimat") or "").strip() != KALIMAT:
        return render(request, "mode_uji.html",
                      **await _konteks(akun, galat=f"Ketik persis: {KALIMAT}"))

    tertahan = await _kosongkan()
    if tertahan:
        return render(request, "mode_uji.html", **await _konteks(akun, galat=tertahan))
    return RedirectResponse("/pengaturan?uji=bersih", status_code=303)


#: Kalimat kedua, dan sengaja BERBEDA dari yang pertama. Dua tombol yang
#: menuntut kalimat sama adalah dua tombol yang bisa tertukar justru saat
#: orangnya sudah hafal mengetiknya.
KALIMAT_ULANG = "ULANGI DATA UJI"


@router.post("/pengaturan/mode-uji/ulangi")
async def ulangi(request: Request, akun: ProduksiAkun = Depends(butuh_akun)):
    """Kosongkan, lalu isi lagi dengan data dummy — kembali ke keadaan awal.

    Menghapus saja meninggalkan setiap layar kosong, dan sesudah itu tak ada
    yang bisa dicoba sampai seseorang mengisinya lagi dari laptop. Yang
    berguna saat menguji bukan tombol hapus melainkan tombol kembali ke awal.
    """
    _wajib_mode_uji()
    if not akun.is_admin:
        raise HTTPException(403, "Hanya Admin ke atas.")
    form = await request.form()
    if (form.get("kalimat") or "").strip() != KALIMAT_ULANG:
        return render(request, "mode_uji.html",
                      **await _konteks(akun, galat=f"Ketik persis: {KALIMAT_ULANG}"))

    tertahan = await _kosongkan()
    if tertahan:
        return render(request, "mode_uji.html", **await _konteks(akun, galat=tertahan))

    from app.services import data_uji
    langkah = await data_uji.isi(akun)
    return render(request, "mode_uji.html", **await _konteks(akun, langkah=langkah))
