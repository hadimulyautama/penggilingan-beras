"""Kerangka tampilan webapp: Jinja, render, dan pengalihan.

Dipisah dari rutenya supaya modul rute tidak saling mengimpor hanya untuk
memakai `render`.
"""
from __future__ import annotations

from pathlib import Path

import hmu_tampilan
from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import settings

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
from app.services.mutu_pk import ATURAN_RATA_QC_PK, JUMLAH_KOMPONEN_QC_PK
templates.env.globals["ATURAN_RATA_QC_PK"] = ATURAN_RATA_QC_PK
templates.env.globals["JUMLAH_KOMPONEN_QC_PK"] = JUMLAH_KOMPONEN_QC_PK

#: VERSI aset kini SATU nomor di paket `hmu_tampilan` (Tahap 1 rancang ulang,
#: 13 September 2026), bukan tiga nomor di tiga repo. Naikkan di repo
#: `tampilan/`, lalu sinkronkan. Tanpa cap versi, perangkat yang sudah pernah
#: membuka aplikasi memakai berkas lama tanpa ada yang menyadarinya.
VERSI = hmu_tampilan.VERSI

# ⚠ PERBAIKAN YANG HANYA MENYENTUH `hmu_tampilan/` PERNAH TAK PERNAH TERBIT.
#
# 28 September 2026: laci tak bisa digulir, perbaikannya satu aturan CSS, dan
# commit-nya di-push. Railway MELEWATINYA — `skippedReason: "No changes to
# watched files"` — sebab layanannya memakai Watch Paths yang tak memuat
# `hmu_tampilan/**`. Tak ada galat, tak ada build gagal; deploy-nya cuma tidak
# pernah terjadi, dan /health tetap menjawab "ok" atas versi lama. Pemilik yang
# menunggu perbaikannya tak punya cara mengetahui bedanya.
#
# Tak ketahuan berbulan-bulan karena SETIAP commit sebelumnya kebetulan ikut
# menyentuh `app/`. Yang pertama tidak — langsung tenggelam.
#
# Obatnya `watchPatterns: ["**"]` di `railway.json`, yaitu: bangun pada tiap
# push. Itu menukar beberapa menit build dengan kepastian bahwa yang sudah
# di-push memang terbit — dan daftar pengecualian apa pun akan mengulang
# jebakan yang sama pada berkas yang kebetulan tak terpikir hari ini.
#
# Cara memeriksa bahwa sesuatu benar-benar terbit: bandingkan `?v=` pada
# halaman masuk dengan VERSI di sini. `/health` TIDAK menjawabnya — ia cuma
# menyebut revisi skema, dan skema tak berubah saat yang berubah cuma tampilan.

# `base.html` & `_benda.html` datang dari paket; templat layar tetap di sini.
# Pita "MODE UJI": orang yang tak tahu ia sedang menguji akan memperlakukan
# angka uji sebagai angka pabrik.
# `zona` DIKIRIM, tidak dibiarkan memakai bawaannya: saringan `jam` di paket
# yang membetulkan jam di Kabar & List audit, dan setelan zona pabrik hidup di
# sini. Bawaan yang kebetulan sama hari ini adalah bawaan yang salah pada hari
# setelan itu diubah.
hmu_tampilan.pasang_jinja(templates, app_nama="Pos Produksi", pwa_nama="Pos Produksi",
                          mode_uji=settings.mode_uji, zona=settings.app_timezone)

from app.web.layar import MEJA, NAMA_VIEW, POLESAN, SELEPAN, SUPER  # noqa: E402
from app.web.nav import JUDUL, TAB   # noqa: E402  (butuh `templates` di atas)

templates.env.globals["TAB"] = TAB
templates.env.globals["TAB_KUNCI"] = {k for k, _, _, _, _, _ in TAB}
# Nama view dipakai kepala laci: orang yang sedang memakai "Lihat sebagai"
# harus bisa membaca layar SIAPA yang sedang ia lihat, dan "operator" saja
# tak menjawabnya di pabrik yang punya dua gudang.
templates.env.globals["NAMA_VIEW"] = NAMA_VIEW
# Dipakai templat untuk membedakan isi yang tak punya pintunya sendiri —
# mis. petak Beranda dan blok Orang & alat di Pengaturan.
templates.env.globals["V_MEJA"] = MEJA
templates.env.globals["V_SUPER"] = SUPER
templates.env.globals["V_SELEPAN"] = SELEPAN
templates.env.globals["V_POLESAN"] = POLESAN
# Judul layar naik ke bilah atas — laci menyembunyikan posisi orang,
# dan layar tanpa nama membuat orang menekan menu hanya untuk memastikan
# ia sedang di mana.
templates.env.globals["JUDUL"] = JUDUL

from app.web.lihat_sebagai import PILIHAN as _LIHAT_PILIHAN  # noqa: E402
from hmu_identitas import peran as _P  # noqa: E402
templates.env.globals["LIHAT_PILIHAN"] = _LIHAT_PILIHAN
#: Operator memilih GUDANG kerja (bukan peran) — pemilik 13 Sep 2026.
templates.env.globals["PILIHAN_GUDANG"] = (("", "Gudang utama saya"), *_P.PILIHAN_GUDANG)
templates.env.globals["admin_keatas"] = _P.admin_keatas
templates.env.globals["boleh_ganti_gudang"] = _P.boleh_ganti_gudang

#: Nama fase barang di layar. Urutannya mengikuti perjalanan barang sendiri —
#: menunggu orang, panas di mesin, tersimpan di silo, menghasilkan — dan
#: warnanya di app.css mengikuti urutan yang sama, jadi posisinya terbaca
#: sekilas tanpa membaca hurufnya.
templates.env.globals["FASE"] = {
    "baru": "Belum ada tindakan",
    # Gabah yang menumpuk SUDAH ditindak — ia sengaja ditaruh di lantai karena
    # mesin dan silo tak siap menerimanya. Sebelum ini ia memakai fase "baru",
    # jadi kepingannya berbunyi "Belum ada tindakan" tepat di bawah judul blok
    # "Menumpuk di lantai" — dua kalimat yang saling membantah pada kartu yang
    # sama. Kepingan yang berbohong lebih buruk daripada kepingan yang tak ada,
    # karena ia dipercaya.
    "tumpuk": "Menumpuk di lantai",
    "dryer": "Di mesin pengering",
    "silo": "Transit di silo kering",
    "giling": "Proses giling",
    # ── Gudang 2 memakai KATA sendiri, warna yang sama ──
    #
    # Kunci fase memikul DUA tugas: warna kartu (urutannya mengikuti perjalanan
    # barang, dan app.css mengikuti urutan yang sama) dan katanya. Warnanya
    # netral antar gudang; katanya tidak.
    #
    # Kartu Gudang 2 dulu meminjam "silo" dan "giling" apa adanya, jadi silo
    # bahan PK berkeping "Transit di silo kering" — padahal ia bukan silo
    # pengering — dan kartu berjudul "Penyosohan" berkeping "Proses giling",
    # membantah judulnya sendiri. Laporan pemilik 24 September 2026.
    #
    # Istilah "silo bahan" dari pemilik. Kelas warnanya ada di app.css
    # (`.benda--silo_g2`, `.padat--sosoh`, dst.) — kunci tanpa kelas warna
    # tampil polos tanpa ada yang memberi tahu.
    "silo_g2": "Di silo bahan",
    "sosoh": "Proses sosoh",
    # ── Rantai permintaan PK: kunci baru, warna lama ──
    #
    # Aturan yang sama sekali lagi, dan sekali lagi ketahuan dari foto pemilik
    # (28 September 2026): kartu berjudul "Kirim PK ke Gudang 2" berkeping
    # "PROSES GILING". Kartunya memindahkan PK; yang digiling sudah selesai
    # digiling. Kelima kartu rantai ini meminjam fase "giling" demi WARNANYA,
    # dan ikut membawa KATANYA.
    #
    # Warnanya sengaja tetap sama dengan giling (`--fase-giling` di app.css):
    # barangnya memang PK hasil giling, dan posisinya dalam perjalanan barang
    # tak berubah. Yang berubah cuma katanya.
    "pindah_pk": "Pindah PK",
    # ── Barang keluar: kunci SENDIRI, bukan pinjaman ──
    #
    # Ini keempat kalinya aturan yang sama diuji, dan tiga yang pertama
    # ketahuan dari foto pemilik. Kartu muat dan kartu verifikasi barang keluar
    # bisa saja meminjam "sosoh" demi warnanya — barangnya memang hasil
    # penyosohan — lalu berkeping "PROSES SOSOH" di atas judul "Muat barang
    # keluar". Kepingan yang membantah judulnya sendiri lebih buruk daripada
    # kepingan yang tak ada, sebab ia dipercaya.
    #
    # Warnanya juga sendiri (`--fase-keluar`): barangnya sedang MENINGGALKAN
    # pabrik, keadaan yang tak dimiliki fase mana pun. Warna yang sama dengan
    # penyosohan akan membuat truk yang sudah berangkat terbaca seperti mesin
    # yang sedang menyala.
    "keluar": "Barang keluar",
}


def render(request: Request, nama: str, *, status_code: int = 200, **konteks):
    """Render template dengan konteks bawaan (akun yang sedang masuk).

    `layar` diturunkan dari nama template, bukan dikirim tiap pemanggil: bilah
    navigasi harus menyala di tab yang benar, dan satu pemanggil yang lupa
    mengirimnya berarti satu layar yang tabnya mati tanpa ada yang menyadari.
    """
    konteks.setdefault("akun", getattr(request.state, "akun", None))
    konteks.setdefault("LIHAT_SEBAGAI", getattr(request.state, "lihat_sebagai", None))
    konteks.setdefault("PERAN_ASLI", getattr(request.state, "peran_asli", None))
    konteks.setdefault("PITA_SAMAR", getattr(request.state, "pita_samar", None))
    konteks.setdefault("layar", nama.replace(".html", ""))
    # View ditetapkan `akun_opsional`, satu kali per permintaan. Layar tak
    # pernah menghitungnya sendiri — lihat `app.web.layar`.
    konteks.setdefault("VIEW", getattr(request.state, "view", "tamu"))
    konteks.setdefault("MENUNGGU", 0)
    from app.web.jasa_navigasi import kembali_aman
    konteks['JASA_KEMBALI'] = kembali_aman(request.query_params.get('kembali_jasa'))
    # ── Token CSRF, satu per peramban ──
    #
    # Dibaca dari cookie bila sudah ada; kalau belum, diterbitkan di sini dan
    # dititipkan ke `request.state` supaya middleware memasang cookie yang
    # SAMA. Kalau keduanya menerbitkan sendiri-sendiri, formulir yang baru
    # dirender akan membawa nilai yang berbeda dari cookie-nya — dan setiap
    # kiriman pertama ditolak.
    from app.web import csrf as _csrf

    nilai = (request.cookies.get(_csrf.NAMA_COOKIE)
             or getattr(request.state, "csrf", None))
    if not nilai:
        nilai = _csrf.terbitkan_baru()
        try:
            request.state.csrf = nilai
        except Exception:  # noqa: BLE001 — permintaan tiruan tanpa state
            pass
    from app.web.security import baca_token, NAMA_COOKIE
    konteks.setdefault("CSRF_NONCE", nilai)
    konteks.setdefault("CSRF", _csrf.untuk_sesi(nilai, baca_token(request.cookies.get(NAMA_COOKIE)), request.cookies.get("produksi_lihat", "")))
    # Mode terik: layar terang untuk kerja di bawah matahari. Per perangkat,
    # lewat kuki — lihat catatan di base.html. Temuan QA UI-04.
    # Mode terang adalah bawaan untuk perangkat baru. Cookie "0" berarti
    # pengguna memang memilih tampilan gelap; "1" tetap berarti terang.
    konteks.setdefault("TERIK", request.cookies.get("produksi_terik", "1") == "1")
    return templates.TemplateResponse(request, nama, konteks, status_code=status_code)


async def render_laci(request: Request, nama: str, **konteks):
    """`render` untuk layar yang tak menyusun daftar `Berjalan` sendiri.

    Laci itu satu benda di seluruh aplikasi. Kalau angkanya ada di Beranda
    tapi hilang di List audit, yang dibaca orang bukan "layar ini tidak
    menghitung" melainkan "pekerjaannya sudah habis" — dan lencana yang
    kadang bohong lebih buruk daripada lencana yang tak pernah ada.

    Layar yang SUDAH memegang `Berjalan` tetap mengirim angkanya sendiri:
    memanggil ini di sana berarti menyusun ulang seluruh daftar dua kali
    hanya demi tiga angka.
    """
    from app.web.nav import lencana

    from app.web.stok_navigasi import siapkan
    await siapkan(request, nama, konteks)
    from app.web.layar_pekerjaan import konteks_aman
    kembali_kerja = konteks_aman(request.query_params.get("kembali_kerja"))
    if kembali_kerja:
        konteks["kembali"] = kembali_kerja

    akun = getattr(request.state, "akun", None)
    return render(request, nama,
                  **{**await lencana(akun.user if akun else None), **konteks})


def redirect(tujuan: str) -> RedirectResponse:
    """Pengalihan setelah POST — 303 supaya peramban beralih ke GET."""
    return RedirectResponse(tujuan, status_code=303)
