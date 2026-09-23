"""Isi ulang data uji — dipakai skrip DAN tombol di layar Mode Uji.

Menghapus saja tidak cukup. Sesudah "Hapus data uji", tiap layar kosong dan
tak ada satu pun yang bisa dicoba; data dummy-nya harus diisi lagi, dan
sampai sekarang itu hanya bisa dilakukan dari laptop. Jadi yang berguna
bukan tombol hapus melainkan tombol KEMBALI KE AWAL.

**Datanya dibuat lewat endpoint aplikasi ini sendiri**, bukan lewat INSERT
dan bukan pula dengan memanggil layanan satu per satu. Baris yang disuntikkan
langsung bisa saja mustahil menurut aturan aplikasinya sendiri — gabah basah
di silo, lot tanpa target kadar air — dan data uji yang mustahil membuat
layarnya terlihat benar padahal menampilkan keadaan yang tak pernah bisa
terjadi. Memanggil layanannya satu per satu lebih baik, tetapi menuntut
menyalin ulang cara endpoint menerjemahkan tujuan jadi tindakan — dan salinan
itu akan berselisih dengan aslinya cepat atau lambat.

Jadi ia memanggil aplikasinya sendiri lewat ASGI, di dalam proses yang sama:
tak ada jaringan, tak ada aturan yang disalin, dan apa pun yang ditolak
aplikasi untuk operator sungguhan ditolak juga di sini.

Satu-satunya yang disuntikkan langsung adalah TIKET TIMBANG, karena ia memang
datang dari aplikasi lain dan tak ada layar di sini yang membuatnya.
"""
from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import SessionLocal
from app.models import ProduksiAkun, Supplier

#: Awalan pada tiap pemasok karangan. Siapa pun yang membuka basis data ini
#: harus tahu dalam sekali lihat bahwa isinya bukan pekerjaan sungguhan.
AWALAN = "(UJI) "

#: Awalan kode tiket timbang yang MEMANG buatan pembuat data uji — satu per
#: pembuatnya. Dipakai `jembatan_sungguhan` untuk memisahkan tiket karangan
#: dari tiket truk yang sungguh datang; daftar inilah satu-satunya tempat
#: awalan itu ditulis, supaya penambahan pembuat baru tak perlu menyentuh
#: penjaganya.
AWALAN_TIKET_UJI = ("TRX-UJI-", "TRX-SIM-")

PEMASOK = [
    "H. Karyo", "Bu Sri", "Pak Tarno", "H. Sulaiman Abdurrahman",
    "Kelompok Tani Sumber Rejeki", "Mbah Wagimin", "Hj. Rohmah",
    "Pak Darto", "CV Tani Makmur Sentosa", "Bu Painem",
]

#: Tiket timbang: (indeks pemasok, jenis, plat, kg, berapa hari yang lalu).
#:
#: Riwayat beberapa hari dibuat dengan sengaja. Layar Laporan dan List audit
#: yang hanya berisi hari ini tak bisa dipakai menilai apa pun — yang ingin
#: dilihat orang di sana justru perbandingan antar hari.
TIKET = [
    # ── 4 hari lalu ──
    (0, "GABAH_BASAH",  "AD 1234 XY",  9_850, 4),
    (1, "GABAH_BASAH",  "AD 88 KK",   10_400, 4),
    (5, "GABAH_BASAH",  "AD 3 QQ",     8_900, 4),
    # ── 3 hari lalu ──
    (2, "GABAH_KERING", "AD 21 LM",    8_600, 3),
    (6, "GABAH_KERING", "AD 45 RT",   10_150, 3),
    (3, "GABAH_BASAH",  "AD 9 PP",    11_000, 3),
    # ── 2 hari lalu ──
    (4, "GABAH_BASAH",  "AD 7 CC",     9_200, 2),
    (7, "GABAH_BASAH",  "AD 12 DD",   10_600, 2),
    (8, "GABAH_KERING", "AD 77 SS",    9_400, 2),
    # ── kemarin ──
    (9, "GABAH_BASAH",  "AD 2 MM",     8_750, 1),
    (0, "GABAH_KERING", "AD 1234 XY", 10_700, 1),
    (1, "GABAH_BASAH",  "AD 88 KK",    9_980, 1),
    # ── hari ini: sebagian ditindak, sebagian ditinggal di antrean ──
    (2, "GABAH_BASAH",  "AD 21 LM",   10_250, 0),
    (5, "GABAH_BASAH",  "AD 3 QQ",     9_600, 0),
    (3, "GABAH_KERING", "AD 9 PP",    11_200, 0),
    (6, "GABAH_KERING", "AD 45 RT",    8_300, 0),
    (7, "GABAH_BASAH",  "AD 12 DD",    9_050, 0),
    (8, "GABAH_KERING", "AD 77 SS",   10_900, 0),
    (9, "GABAH_BASAH",  "AD 2 MM",     8_480, 0),
    (4, "GABAH_KERING", "AD 7 CC",     9_770, 0),
]


async def _pemasok(db: AsyncSession) -> dict[str, int]:
    keluar: dict[str, int] = {}
    for nama in PEMASOK:
        penuh = AWALAN + nama
        s = (await db.execute(
            select(Supplier).where(Supplier.nama_supplier == penuh))).scalars().first()
        if s is None:
            await db.execute(
                text("INSERT INTO suppliers (nama_supplier) VALUES (:n)"), {"n": penuh})
            await db.flush()
            s = (await db.execute(
                select(Supplier).where(Supplier.nama_supplier == penuh))).scalars().first()
        keluar[nama] = s.id
    return keluar


class JembatanDipakai(Exception):
    """Basis datanya melayani jembatan timbang yang sungguh dipakai."""


async def jembatan_sungguhan(db: AsyncSession) -> int:
    """Berapa tiket timbang di sini yang BUKAN buatan pembuat data uji.

    Tanpa garis bawah: sejak 11 September 2026 ia dipakai DUA modul — di sini
    sebelum mengisi, dan di `mode_uji._kosongkan` sebelum menghapus. Aturannya
    satu, jadi tempatnya pun harus satu; disalin ke dua tempat, keduanya akan
    berbeda pada perubahan berikutnya.

    `timbangan_transaksi` milik aplikasi Timbangan, dan aplikasi itu membaca
    basis data yang sama. Tiket karangan yang ditulis ke sini tidak berhenti
    di layar Produksi — ia muncul di layar petugas timbang, di antara tiket
    truk yang sungguh datang hari itu. Sekali ini terjadi, dan pemiliknya
    yang menemukannya.

    Jadi keberadaan tiket ORANG LAIN dipakai sebagai tanda: kalau jembatannya
    sudah dipakai sungguhan, tak ada satu pun tiket karangan yang boleh lahir
    di sini.

    Yang dihitung sebagai "orang lain" adalah tiket yang awalan kodenya bukan
    salah satu dari `AWALAN_TIKET_UJI`. Awalannya lebih dari satu karena
    pembuat tiket karangan lebih dari satu: `data_uji` menulis `TRX-UJI-…`,
    dan simulasi hari kerja (`scripts/simulasi_gabah.py`, yang biasanya
    membangun basis data uji itu sejak kosong) menulis `TRX-SIM-…`. Selama
    hanya satu yang dikenali, basis data uji yang dibuat simulasi terlihat
    seperti basis data pabrik yang sedang dipakai — dan penjaga ini menolak
    pekerjaan yang justru harus boleh dilakukan di sana, termasuk tombol
    "Kembali ke awal" di layar Mode Uji.
    """
    syarat = " AND ".join(f"kode NOT LIKE '{a}%'" for a in AWALAN_TIKET_UJI)
    return (await db.execute(text(
        f"SELECT count(*) FROM timbangan_transaksi WHERE {syarat}"
    ))).scalar_one()


async def _tiket(db: AsyncSession, pemasok: dict[str, int]) -> int:
    """Tiket timbang, disuntikkan langsung — ia milik aplikasi Timbangan.

    `timbang1_waktu` yang mundur beberapa hari BUKAN hiasan: dari situlah
    tanggal batch diambil (`purchase.create_purchase_batch_dari_timbang`),
    jadi riwayat beberapa harinya terbentuk lewat jalur yang sama dengan
    hari biasa — bukan dengan menambal tanggal sesudahnya.
    """
    dibuat = 0
    for i, (idx, jenis, plat, kg, lalu) in enumerate(TIKET, start=1):
        kode = f"TRX-UJI-{i:03d}"
        ada = (await db.execute(
            text("SELECT 1 FROM timbangan_transaksi WHERE kode = :k"), {"k": kode})).first()
        if ada:
            continue
        await db.execute(text("""
            INSERT INTO timbangan_transaksi
              (kode, tanggal, arah, jenis_kode, nomor_polisi, nama_sopir,
               supplier_id, timbang1_kg, timbang2_kg, netto_timbangan_kg,
               berat_barang_kg, berat_acuan_kg, status_kontrol, status_tiket,
               timbang1_waktu, timbang2_waktu)
            VALUES (:k, CURRENT_DATE - CAST(:lalu AS int), 'MASUK', :j, :p,
                    'Sopir Uji', :s, :t1, :t2, :n, :n, :n, 'NORMAL', 'TERBUKA',
                    now() - make_interval(days => CAST(:lalu AS int), hours => 3),
                    now() - make_interval(days => CAST(:lalu AS int), hours => 2))
        """), {"k": kode, "j": jenis, "p": plat, "s": pemasok[PEMASOK[idx]],
               "t1": kg + 4200, "t2": 4200, "n": kg, "lalu": lalu})
        dibuat += 1
    return dibuat


async def _mundurkan(hari: int, kode_lot: str | None, kode_proses: str | None) -> None:
    """Geser jam satu siklus yang sudah selesai ke belakang.

    Bentuk datanya tetap dibuat aplikasi lewat jalurnya sendiri; yang digeser
    hanya JAMNYA. Tanpa ini seluruh riwayat bertanggal hari ini, dan laporan
    per hari — satu-satunya alasan riwayat itu dibuat — jadi tak menunjukkan
    apa pun. Hanya dipakai pada siklus yang SUDAH ditutup: yang masih berjalan
    dibiarkan apa adanya supaya "sudah berapa lama" tetap jujur.
    """
    async with SessionLocal() as db:
        if kode_lot:
            await db.execute(text("""
                UPDATE drying_lots SET
                    waktu_mulai_pengeringan = waktu_mulai_pengeringan - make_interval(days => CAST(:h AS int)),
                    waktu_selesai_pengeringan = waktu_selesai_pengeringan - make_interval(days => CAST(:h AS int)),
                    waktu_selesai_pendinginan = waktu_selesai_pendinginan - make_interval(days => CAST(:h AS int))
                 WHERE kode_lot = :k
            """), {"h": hari, "k": kode_lot})
        if kode_proses:
            await db.execute(text("""
                UPDATE milling_process SET
                    waktu_mulai = waktu_mulai - make_interval(days => CAST(:h AS int)),
                    waktu_selesai = waktu_selesai - make_interval(days => CAST(:h AS int))
                 WHERE kode_proses = :k
            """), {"h": hari, "k": kode_proses})
        await db.commit()


async def isi(akun: ProduksiAkun) -> list[str]:
    """Isi data uji: pemasok & TIKET TIMBANG, tidak lebih.

    Dulu ia ikut menjalankan sehari kerja penuh — gabah masuk, pengeringan,
    giling, verifikasi — supaya tiap layar ada isinya. Pemilik memutuskan
    sebaliknya: cukup tiketnya, prosesnya dia sendiri yang menjalankan. Dan
    memang itu yang lebih berguna untuk MENGUJI: proses yang dijalankan skrip
    membuktikan skripnya jalan, bukan membuktikan layarnya bisa dipakai.

    Akibat sampingannya justru diminta: karena tak ada satu aksi pun yang
    dijalankan, tak ada satu baris pun masuk List audit. Yang muncul di sana
    nanti hanya pekerjaan yang sungguh dilakukan orangnya.

    `akun` tetap diterima — pemanggilnya sudah menyebutkannya, dan mengubah
    bentuk panggilan hanya untuk membuang satu argumen berarti setiap
    pemanggil ikut berubah tanpa sebab.

    Akun uji karangan (`uji_admin`, `uji_operator`) TIDAK dibuat lagi sejak
    21 September 2026: app uji coba memakai akun yang sudah ada, sama dengan
    yang dipakai orang sungguhan. Data yang diuji boleh karangan; orang yang
    mengujinya tidak.
    """
    async with SessionLocal() as db:
        dipakai = await jembatan_sungguhan(db)
        if dipakai:
            raise JembatanDipakai(
                f"Dibatalkan: basis data ini melayani jembatan timbang yang "
                f"sedang dipakai — ada {dipakai} tiket timbang sungguhan di "
                "dalamnya. Tiket karangan yang dibuat di sini akan muncul di "
                "layar petugas timbang, di antara truk yang benar-benar "
                "datang. Data uji hanya boleh diisi di basis data yang khusus "
                "untuk menguji."
            )
        pemasok = await _pemasok(db)
        n = await _tiket(db, pemasok)
        await db.commit()

    return [
        f"{len(PEMASOK)} pemasok · {n} tiket timbang",
        "Tersebar 5 hari — tiket lama tetap bisa ditindak sebagai susulan.",
        "Tak ada proses yang dijalankan, jadi List audit pun masih kosong.",
    ]
