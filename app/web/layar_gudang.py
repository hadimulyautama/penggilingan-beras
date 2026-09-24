"""Layar "Satu gudang" — ringkasan SATU gudang, dibuka dari Beranda.

Lahir di Meja Administrasi (12 September 2026) sebagai sasaran baris gudang:
keputusan pemilik hari itu menjadikan gudang sebuah DAFTAR, bukan tata letak,
sebab Beranda yang menumpuk satu blok per gudang jadi tiga layar begitu
gudangnya dua — "jika punya banyak gudang pasti bingung".

Dipindah ke Pos Produksi 24 September 2026. Sebabnya bukan kerapian: app meja
dan app gudang2 akan DIHAPUS, dan halaman ini salah satu dari lima hal yang
hanya ada di sana. Yang hilang tanpa penggantinya bukan halaman melainkan
kemampuan menjawab "bagaimana keadaan gudang sebelah" tanpa berjalan ke sana.

Gerbangnya bukan `butuh_admin` melainkan VIEW yang berurusan dengan gudang itu
(`layar.boleh_lihat_gudang`). Dua alasan:

  • Operator tidak dilarang membuka gudangnya SENDIRI — petaknya sama dengan
    yang sudah ada di Beranda-nya, jadi melarangnya cuma membuat tautan yang
    tak boleh ditekan. Yang dilarang adalah gudang SEBELAH: angka gudang lain
    bukan pekerjaannya, dan layar yang menawarkannya mengajari orang membaca
    kabar yang tak bisa ia tindaklanjuti.
  • Peran EFEKTIF yang ditanya, bukan peran tersimpan. Admin yang sedang
    memakai "Lihat sebagai operator Gudang 2" harus kehilangan Gudang 1 di
    sini juga — samaran yang masih menyisakan gudang sebelah bukan samaran.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.database import SessionLocal
from app.services import berjalan as svc
from app.web.layar import (FUNGSI_GUDANG, NAMA_GUDANG, _petak_g1, _petak_g2,
                           boleh_lihat_gudang)
from app.web.nav import JUDUL
from app.web.security import AksesDitolak, butuh_akun
from app.web.tampilan import render

router = APIRouter(tags=["webapp"])


@router.get("/gudang/{gid}")
async def halaman_gudang(request: Request, gid: str, akun=Depends(butuh_akun)):
    if gid not in NAMA_GUDANG:
        raise HTTPException(404, "Gudang tidak dikenal.")
    view = getattr(request.state, "view", "tamu")
    if not boleh_lihat_gudang(view, gid):
        raise AksesDitolak(f"{NAMA_GUDANG[gid]} bukan gudang Anda.")

    async with SessionLocal() as db:
        # Kartunya dari daftar yang SAMA dengan layar Sedang berjalan, bukan
        # disusun ulang di sini. Halaman yang menghitung sendiri apa yang
        # berjalan adalah halaman yang cepat atau lambat menyebut angka
        # berbeda dari layar sebelahnya — dan bedanya tak akan ada yang
        # menyadari, sebab tak ada yang membuka keduanya berdampingan.
        if gid == "g1":
            from app.services.dashboard import dashboard_data

            b = await svc.untuk_gudang1(db)
            petak = _petak_g1((await dashboard_data(db)).get("operasional", {}) or {})
        else:
            b = await svc.untuk_gudang2(db)
            petak = await _petak_g2(db)
        # Lencana bilah atas tetap milik ORANG yang membaca, bukan gudang yang
        # dibaca: "3 menunggu" yang berubah-ubah menurut halaman membuat angka
        # itu berhenti berarti.
        milik = await svc.untuk(db, akun.user)

    return render(
        request, "gudang.html", layar="gudang", kembali="/",
        JUDUL={**JUDUL, "gudang": NAMA_GUDANG[gid]},
        gid=gid, nama_gudang=NAMA_GUDANG[gid], fungsi=FUNGSI_GUDANG[gid],
        petak=petak, berjalan=b.berjalan, transit=b.transit, lama=svc._lama,
        # Pos Produksi MEMPUNYAI rute aksinya, jadi tombol di kartu benar-benar
        # bisa ditekan dari sini — beda dengan Meja, yang menggambar kartu yang
        # sama tanpa memuat `aksi.js`.
        blok_aksi=True,
        buka=request.query_params.get("buka") or "",
        nilai=request.query_params.get("nilai") or "",
        **milik.lencana(),
    )
