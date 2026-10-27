"""Layar Stok — PK yang masih ada, dan gudangnya mengikuti VIEW pembacanya.

Satu alamat, dua isi. Operator selepan melihat lot giling Gudang 1; operator
polesan melihat silo dan tumpukan Gudang 2; Admin ke atas melihat keduanya,
Gudang 1 lebih dulu. Sebelum ini semua orang melihat Gudang 1 — termasuk
operator yang bekerja di Gudang 2, yang halaman Stoknya seluruhnya berisi
barang gudang sebelah.

Operator hanya membaca. Yang boleh mengoreksi hanya Admin ke atas, dan yang
dikoreksi adalah HASIL GILINGNYA — bukan angka stoknya.

Bedanya penting. Stok = hasil − dikirim − dijual; membolehkan orang mengetik
stok berarti membolehkan salah satu dari ketiganya dibengkokkan tanpa jejak,
dan selisih yang ditutupi berhenti jadi pertanyaan. Yang dibuka di sini justru
aksi yang sudah ada dan sudah tercatat: verifikasi output giling. Ia menulis
`berat_output_final_kg`, masuk log aktivitas, bisa dibatalkan lewat List audit,
dan karena rendemen serta stok adalah TURUNAN dari angka itu, keduanya berubah
sendiri — tak ada angka kedua yang bisa berselisih.
"""
from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request

from app.database import SessionLocal
from app.services import stok as svc
from app.web.security import butuh_akun
from app.web.tampilan import render_laci

router = APIRouter(tags=["webapp"])


@router.get("/stok")
async def halaman_stok(request: Request, akun=Depends(butuh_akun)):
    # Satu pintu navigasi, tetapi tetap memakai pembaca dan gerbang lama.
    tab = request.query_params.get("tab", "bahan")
    pemilik = request.query_params.get("pemilik", "pabrik")
    if tab not in {"bahan", "produk", "karung"} or pemilik not in {"pabrik", "jasa"}:
        raise HTTPException(422, "Pilihan stok tidak dikenal.")
    if tab != "bahan":
        from app.web import layar_produk
        tujuan = {
            ("produk", "pabrik"): layar_produk.halaman_stok_produk,
            ("produk", "jasa"): layar_produk.halaman_stok_produk_jasa,
            ("karung", "pabrik"): layar_produk.halaman_stok_karung,
            ("karung", "jasa"): layar_produk.halaman_stok_karung_jasa,
        }[tab, pemilik]
        return await tujuan(request, akun=akun)
    if pemilik == "jasa":
        return await halaman_stok_pk_jasa(request, akun=akun)
    from app.services.setelan import fitur_mutu

    from app.web.layar import GUDANG, MEJA, NAMA_GUDANG, POLESAN, SUPER, gudang1, gudang2

    view = getattr(request.state, "view", "tamu")
    # Susunan filter sama untuk semua pengguna. Tiap pembaca di bawah
    # tetap memeriksa cakupan gudang sebelum menanyakan data.
    saring = GUDANG
    gudang = request.query_params.get("gudang") or ""
    if gudang not in {g for g, _, _ in saring}:
        gudang = ""                       # nilai karangan dari URL diabaikan
    async with SessionLocal() as db:
        # PK milik pabrik saja di halaman ini: PK jasa punya halaman khusus
        # `/stok-pk-jasa`, seperti produk jasa dipisah dari Stok Produk.
        # Layanan tetap membaca semua pemilik agar picker proses dan halaman
        # khusus bisa memakai sumber data yang sama.
        #
        # ── PK Gudang 1 TERLIHAT oleh operator Gudang 2 ──
        #
        # Keputusan pemilik 24 September 2026, dan hanya di layar Stok. Dulu
        # syaratnya `gudang1(view)` saja, dengan alasan tertulis: "operator
        # hanya menerima gudangnya sendiri; halaman Stok yang menampilkan silo
        # gudang sebelah menjawab pertanyaan yang tak ia ajukan."
        #
        # Kalimat itu tetap BENAR untuk silo dan dryer Gudang 1 — dan SALAH
        # untuk PK yang sudah jadi. PK itulah BAHAN BAKU orang ini: yang
        # memutuskan "hari ini menyosoh apa" perlu tahu ada KS atau KL berapa
        # di sebelah, mutunya bagaimana, dan dari gabah siapa. Selama ia tak
        # bisa melihatnya, satu-satunya cara mengetahuinya adalah bertanya
        # lewat telepon — dan yang ditanya lewat telepon tak pernah tercatat.
        #
        # Yang TETAP tertutup untuknya, dan sengaja: silo & dryer Gudang 1
        # (blok `tempat` di bawah punya gerbangnya sendiri), stok karung
        # Gudang 1 (`_karung`), dan halaman `/gudang/g1` (403 di rutenya).
        # Melihat bahan bukan memegang gudangnya.
        #
        # Blok ini berjudul "PK di Gudang 1" dan totalnya hanya menjumlah lot
        # ini — bukan menyatu dengan stok Gudang 2. Operator yang mengira
        # barang ini sudah ada di gudangnya akan menghitung stok yang tak ia
        # pegang.
        #
        # Penyaringnya ikut menentukan apa yang dibaca, bukan menyembunyikan
        # yang sudah dibaca: kueri stok gudang sebelah mahal, dan membayarnya
        # untuk angka yang tak akan tampil tak ada gunanya. Hari ini operator
        # tak ditawari pil gudang sama sekali (`saring` kosong baginya), jadi
        # `gudang` selalu "" dan syarat di bawah lolos. KALAU kelak pil itu
        # diberikan kepada operator, syarat ini harus ditinjau ulang: bagi
        # operator polesan, "Gudang 1" berarti melihat BAHAN, bukan melihat
        # gudang orang lain.
        lot = ([l for l in await svc.pk_gudang1(db) if not l.pemilik]
               if (gudang1(view) or gudang2(view)) and gudang in ("", "g1") else [])
        tempat = ([t for t in await svc.pk_gudang2(db) if not t.pemilik]
                  if gudang2(view) and gudang in ("", "g2") else [])
        mutu_aktif = await fitur_mutu(db)
        # ── Barang jadi & hasil samping ──
        # Gerbang yang SAMA dengan stok karung tepat di bawahnya: barang jadi
        # lahir di Gudang 2, jadi operator selepan tak melihatnya. Sampai 23
        # September 2026 layar ini tak punya bloknya sama sekali — hitungannya
        # terkunci di `gudang2_api.stok`, dan Pos Produksi yang memegang KEDUA
        # gudang justru buta terhadap apa yang sudah jadi.
        # Barang jadi milik Gudang 2, jadi ia ikut penyaring di kepala halaman —
        # membuka "Gudang 1" lalu melihat barang jadi Gudang 2 di bawahnya
        # membuat penyaringnya berbohong (kalimat yang sama di Meja).
        bj = (await svc.barang_jadi_g2(db) if gudang2(view) and gudang in ("", "g2")
              else svc.BarangJadiG2(produk=[], samping=[]))
    return await render_laci(
        request, "stok.html", layar="stok",
        lot=lot, tempat=tempat,
        # `SARING_GUDANG` = nama kontrak templat bersama (Tahap 2). Kosong untuk
        # operator: ia sudah diberi satu gudang lewat view-nya, dan pil tunggal
        # bernama "Semua" tak membedakan apa pun.
        SARING_GUDANG=saring, gudang=gudang,
        produk=bj.produk, samping=bj.samping,
        total=sum(l.tersedia for l in lot),
        # `is_admin` sudah memakai peran EFEKTIF: saat admin memakai "Lihat
        # sebagai operator", `akun.user.role` diganti, jadi tombolnya ikut
        # hilang — samaran yang masih memegang wewenangnya bukan samaran.
        # Penjagaan sungguhannya tetap di rute aksinya sendiri; ini hanya
        # menyembunyikan tombol yang memang tak akan berhasil ditekan.
        # Koreksi hasil giling milik Gudang 1. Operator polesan tak punya
        # hasil giling untuk dikoreksi, dan tombolnya pun tak ada di
        # kartunya — tetapi `boleh_ubah` juga yang memasang `aksi.js` di
        # kaki halaman, jadi ia dimatikan di view yang tak memuat kartunya.
        boleh_ubah=akun.is_admin and view != POLESAN,
        # ── "Minta lot ini" — hanya view yang memegang Gudang 2 ──
        #
        # Operator selepan tak boleh melihatnya (bukan pekerjaannya), dan Admin
        # tak membutuhkannya — ia bisa memindahkan langsung. Menyembunyikan
        # tombolnya BUKAN penjagaan: rutenya dijaga sendiri
        # (`api.act_minta_pk_g1` menuntut operator Gudang 2), dan yang di sini
        # cuma menghindari menawarkan pintu yang akan ditolak.
        boleh_minta=view in (POLESAN, SUPER),
        # ── "Masukkan ke silo" di tiap kartu Tumpukan — operator Gudang 2
        #    ATAU Super Admin (keputusan pemilik 5 Oktober 2026) ──
        #
        # Admin biasa TETAP tak ditawari: "yang memindahkan barang adalah
        # yang memegang barang" (catatan `act_pindah_tumpukan_silo`,
        # keputusan 4 Oktober). Super Admin ditambahkan sebagai jaring
        # pengaman yang sama dengan `is_operator_gudang2` — peran tertinggi
        # tak boleh kehilangan aksi gudang mana pun. Menyembunyikan tombolnya
        # BUKAN penjagaan; gerbangnya sendiri di `api.act_pindah_tumpukan_silo`.
        boleh_pindah_tumpukan=view in (POLESAN, SUPER),
        # Mutu bisa dimatikan seluruhnya di Pengaturan — termasuk barisnya di
        # kartu ini. Setengah mati adalah yang terburuk: kartu yang masih
        # menyebut "belum dinilai" sementara borangnya tak ada menagih
        # pekerjaan yang tak bisa dikerjakan siapa pun.
        mutu_aktif=mutu_aktif,
        # Lembarnya terbuka DI SINI, bukan melemparkan orang ke layar aksi:
        # yang sedang dibaca adalah kartu ini, dan berpindah layar berarti
        # kehilangan tempatnya.
        buka=request.query_params.get("buka") or "",
        nilai=request.query_params.get("nilai") or "",
    )


@router.get("/stok-pk-jasa")
async def halaman_stok_pk_jasa(request: Request, akun=Depends(butuh_akun)):
    """PK milik pesanan jasa saja — padanan `/stok-produk-jasa` untuk BAHAN.

    Permintaan pemilik 6 Oktober 2026: *"tambah satu sub-menu lagi di stok
    yaitu Stok PK Jasa. semua kartu PK Jasa nanti disitu. sama seperti stok
    pk yaitu dibagi blok menjadi di gudang 1 atau gudang 2."*

    PK jasa hanya ditampilkan di halaman ini. `/stok` hanya menampilkan PK
    milik pabrik, sedangkan data layanan tetap mencakup kedua pemilik untuk
    dipakai picker proses dan tampilan ini menyaring `pemilik`.

    MERENDER `stok_pk_jasa.html` — templat BERISI SATU BARIS, `{% extends
    "stok.html" %}` tanpa satu pun blok ditimpa, jadi keluarannya PERSIS
    sama dengan `/stok`, cuma dilayani lewat berkas sendiri (kontrak yang
    dijaga `test_tiap_layar_berlaci_membawa_ketiga_lencana`: tiap pintu di
    `nav.TAB` wajib punya `{kunci}.html`-nya). `JASA_SAJA` cuma mengubah
    kalimat kepala blok & keadaan kosong — lihat `stok.html`.

    TANPA TOMBOL AKSI (koreksi/minta lot/masukkan silo) — pola yang sama
    dengan "Produk Jasa": halaman INFORMASI, jalan KEDUA ke barang yang
    sudah punya rumahnya di `/stok`. Mengoreksi atau memindahkan PK titipan
    tetap lewat `/stok` — menawarkan aksi yang sama dari dua alamat berarti
    dua tempat yang bisa berselisih memutuskan "siapa yang berhak", dan itu
    belum diminta pemilik.

    `mutu_aktif` TETAP dibaca sungguhan (bukan dipaksa `False` seperti
    tombol lain): ia menggerbangi TAMPILAN nilai mutu di kartu
    (`{% if mutu_aktif %}`), bukan cuma tombolnya — memaksanya mati akan
    menyembunyikan mutu yang SUDAH dinilai, bukan sekadar mematikan aksi.

    Penyaring gudang & gerbang per-blok SAMA PERSIS dengan `/stok`; isi kartu
    dibatasi ke PK jasa agar tidak muncul ganda di dua halaman.
    """
    from app.services.setelan import fitur_mutu
    from app.web.layar import GUDANG, MEJA, POLESAN, SUPER, gudang1, gudang2

    view = getattr(request.state, "view", "tamu")
    saring = GUDANG
    gudang = request.query_params.get("gudang") or ""
    if gudang not in {g for g, _, _ in saring}:
        gudang = ""
    async with SessionLocal() as db:
        lot = ([l for l in await svc.pk_gudang1(db) if l.pemilik]
               if (gudang1(view) or gudang2(view)) and gudang in ("", "g1") else [])
        tempat = ([t for t in await svc.pk_gudang2(db) if t.pemilik]
                  if gudang2(view) and gudang in ("", "g2") else [])
        mutu_aktif = await fitur_mutu(db)
    return await render_laci(
        request, "stok_pk_jasa.html", layar="stok_pk_jasa",
        lot=lot, tempat=tempat,
        SARING_GUDANG=saring, gudang=gudang,
        produk=[], samping=[], total=sum(l.tersedia for l in lot),
        # Halaman ini tetap informatif untuk PK jasa, tetapi operator Gudang 2
        # harus bisa meminta PK jasa yang masih menumpuk di Gudang 1. Aksi
        # permintaan tidak memindahkan stok; persetujuan dan pengiriman tetap
        # mengikuti alur empat langkah yang sama.
        boleh_ubah=False, boleh_minta=view in (POLESAN, SUPER),
        # PK jasa yang berdiri sebagai tumpukan di Gudang 2 juga harus bisa
        # dimasukkan ke silo melalui alur yang sama dengan PK pabrik. Aksi
        # tetap dibatasi pada operator Gudang 2 dan Super Admin; Admin biasa
        # tidak mendapat tombol, dan gerbang server tetap berlaku.
        boleh_pindah_tumpukan=view in (POLESAN, SUPER),
        mutu_aktif=mutu_aktif,
        buka=request.query_params.get("buka") or "",
        nilai=request.query_params.get("nilai") or "",
        # Kalimat kepala blok & keadaan kosong menyebut "PK Jasa", bukan
        # "PK" polos — tanpa ini orang yang sampai di sini lewat tautan
        # langsung (bukan lewat sub-menu "Stok") tak tahu ia sedang melihat
        # irisan, bukan daftar utuh.
        JASA_SAJA=True,
    )


@router.get("/stok/pk/detail")
async def halaman_detail_stok_pk(request: Request, akun=Depends(butuh_akun)):
    """Detail satu stok PK, memakai komponen yang sama untuk pabrik dan jasa."""
    from app.services.setelan import fitur_mutu
    from app.web.layar import POLESAN, SUPER, gudang1, gudang2

    gudang = request.query_params.get("gudang", "")
    jasa_saja = request.query_params.get("jasa") == "1"
    if gudang not in {"g1", "g2"}:
        raise HTTPException(404, "Lokasi stok PK tidak dikenal.")

    view = getattr(request.state, "view", "tamu")
    async with SessionLocal() as db:
        if gudang == "g1" and (gudang1(view) or gudang2(view)):
            daftar = await svc.pk_gudang1(db)
            identitas = request.query_params.get("kode", "")
            kartu = next((x for x in daftar
                          if x.kode == identitas
                          and bool(x.jasa_id) == jasa_saja), None)
        elif gudang == "g2" and gudang2(view):
            daftar = await svc.pk_gudang2(db)
            try:
                intake_id = int(request.query_params.get("id", ""))
            except (TypeError, ValueError):
                raise HTTPException(404, "Kode stok PK tidak dikenal.")
            kartu = next((x for x in daftar
                          if x.intake_id == intake_id
                          and bool(x.jasa_id) == jasa_saja), None)
        else:
            raise HTTPException(404, "Stok PK tidak tersedia untuk gudang ini.")

        if kartu is None:
            raise HTTPException(404, "Stok PK tidak ditemukan atau sudah habis.")
        from app.services.qc_gabah_asal import dari_pk
        qc_gabah_asal = await dari_pk(db, kode=kartu.kode if gudang == "g1" else None,
                                     intake_id=kartu.intake_id if gudang == "g2" else None)
        mutu_aktif = await fitur_mutu(db)
        riwayat_qc = (await svc.riwayat_qc_pk(
            db, kode=kartu.kode if gudang == "g1" else None,
            intake_id=kartu.intake_id if gudang == "g2" else None,
        )) if mutu_aktif else {"rows": [], "hasil_terbaru_saja": False}

    kembali = "/stok-pk-jasa" if jasa_saja else "/stok"
    params_detail = {
        "gudang": gudang,
        "jasa": "1" if jasa_saja else "0",
    }
    if gudang == "g1":
        params_detail["kode"] = kartu.kode
    else:
        params_detail["id"] = str(kartu.intake_id)
    gudang_filter = request.query_params.get("gudang_filter")
    if gudang_filter in {"g1", "g2"}:
        kembali += "?gudang=" + gudang_filter
        params_detail["gudang_filter"] = gudang_filter
    detail_href = "/stok/pk/detail?" + urlencode(params_detail)
    template_stok_lama = "stok_pk_karung.html" if gudang == "g2" and kartu.jumlah_karung else ("stok_pk_jasa.html" if jasa_saja else "stok.html")
    return await render_laci(
        request, "stok_pk_dengan_qc_asal.html", template_stok_lama=template_stok_lama,
        qc_gabah_asal=qc_gabah_asal,
        layar="stok_pk_jasa" if jasa_saja else "stok",
        detail=True, detail_gudang=gudang, detail_kartu=kartu,
        riwayat_qc=riwayat_qc,
        SARING_GUDANG=(), gudang="", lot=[], tempat=[], produk=[], samping=[],
        total=0, JASA_SAJA=jasa_saja, mutu_aktif=mutu_aktif,
        boleh_ubah=akun.is_admin and view != POLESAN,
        boleh_minta=view in (POLESAN, SUPER),
        boleh_pindah_tumpukan=view in (POLESAN, SUPER),
        buka=request.query_params.get("buka") or "",
        nilai=request.query_params.get("nilai") or "",
        breadcrumb_detail="Detail PK", kembali=kembali,
        detail_href=detail_href,
    )
