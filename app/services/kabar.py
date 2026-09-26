"""Layar Kabar — yang membacakan `notifications` kepada orangnya.

LAHIR 26 September 2026, atas keputusan pemilik sesudah satu temuan yang tak
enak dibaca: aplikasi ini sudah LIMA TEMPAT menulis notifikasi — harga gabah
belum diverifikasi, pengeringan telat, penyosohan selesai & perlu verifikasi
output, packing, dan rantai permintaan PK — dan TAK SATU PUN layar membacanya
untuk ditampilkan. Tabel itu dibaca hanya untuk menutup barisnya sendiri.

Jadi selama berbulan-bulan kalimat-kalimat itu ditulis rapi lalu dimasukkan ke
lemari yang tak pernah dibuka siapa pun. Notifikasi "Penyosohan POL-… selesai —
perlu verifikasi output" yang dikeluhkan QA bukan hilang; ia memang tak pernah
punya pembaca.

YANG DIPILIH DI SINI, dan sebabnya:

· BERUMUR, bukan menunggu dikosongkan. Daftar yang harus dipencet supaya
  bersih akan menumpuk di layar orang yang bekerja dengan satu tangan, lalu
  berhenti dibuka. Yang lewat `HARI` berhenti tampil sendiri.

· DIBACA = SUDAH LEWAT DI MATANYA, bukan "sudah dikerjakan". Membuka layar ini
  menandai yang tergambar sebagai `dibaca`, jadi lencananya bisa kembali nol.
  Yang menagih pekerjaan tetap kartunya di Antrian tunggu dan Menunggu
  keputusan — lencana kabar yang tak pernah nol akan mengajari orang
  mengabaikan lencana, dan itu membunuh kegunaan seluruh laci.

· ⚠ DIALAMATKAN KE PERAN, BUKAN KE ORANG. `notifications` tak punya kolom
  orang; yang ada `target_role` ("admin"/"operator"). Akibatnya kabar untuk
  satu orang tak bisa dialamatkan, dan pesannya yang menyebut siapa yang
  dituju. Menambah kolomnya perlu migrasi — pemilik sudah diberi tahu, dan itu
  keputusan tersendiri.

· Karena "operator" dipakai KEDUA gudang, kabar Gudang 2 akan mampir ke layar
  operator Gudang 1 kalau tak disaring. Saringannya `TIPE_GUDANG` di bawah —
  peta kecil dari jenis kabar ke gudang yang berkepentingan. Ia peta dan
  peta bisa basi; karena itu jenis yang TIDAK terdaftar dianggap milik kedua
  gudang, bukan disembunyikan. Kabar yang salah alamat cuma mengganggu; kabar
  yang hilang membuat orang menunggu sesuatu yang tak akan datang.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import now_local
from app.models import Notification, User

#: Berapa lama satu kabar tetap tergambar. Seminggu: cukup panjang untuk orang
#: yang libur dua hari, cukup pendek supaya daftarnya masih bisa dibaca sampai
#: habis dalam satu gulir.
HARI = 7

#: Peran yang membaca kabar mana. Kosakatanya `notifications.target_role` yang
#: sudah dipakai lima penulisnya — bukan kosakata baru, supaya baris lama ikut
#: terbaca tanpa disentuh.
ADMIN, OPERATOR = "admin", "operator"

#: Jenis kabar yang HANYA berkepentingan bagi satu gudang. Lihat catatan di
#: docstring modul: yang tak terdaftar dianggap milik keduanya.
TIPE_GUDANG = {
    # `permintaan_pk` SENGAJA TIDAK di sini, dan itu perubahan 27 September
    # 2026: rantainya melibatkan KEDUA gudang — Gudang 2 yang meminta, Gudang 1
    # yang memuat dan mengirim sesudah Admin menyetujui. Sehari sebelumnya ia
    # tercatat milik "g2" saja, dan dengan tangan yang sekarang itu akan
    # menyembunyikan kabar "ada yang harus Anda kirim" dari orang yang harus
    # mengirimnya.
    # Lot yang telat diperbarui berdiri di dryer Gudang 1.
    "pengeringan_telat": "g1",
}


@dataclass
class Kabar:
    """Satu baris kabar, siap digambar."""

    id: int
    tipe: str
    pesan: str
    prioritas: str
    #: Belum pernah tergambar di mata orang ini.
    baru: bool
    waktu: object
    #: Tabel & baris yang diceritakannya — dipakai kelak kalau kabar hendak
    #: bisa ditekan langsung ke bendanya.
    table_name: str | None = None
    record_id: int | None = None


async def keranjang(user: User) -> tuple[str, str | None]:
    """Kabar mana yang milik orang ini: (peran, gudang).

    `gudang` None berarti tak disaring — Admin ke atas memegang kedua gudang,
    dan kabar yang disembunyikan dari orang yang bertanggung jawab atas
    keduanya adalah kabar yang hilang.
    """
    from app.peran import can_see_financials
    from app.web.api import _is_g1_operator, _is_g2_operator

    if can_see_financials(user):
        return ADMIN, None
    if await _is_g2_operator(user):
        return OPERATOR, "g2"
    if await _is_g1_operator(user):
        return OPERATOR, "g1"
    # Operator tanpa gudang (belum ditautkan): perannya sudah benar, gudangnya
    # belum diketahui. Diberi semuanya — lihat catatan tentang kabar yang
    # hilang di docstring modul.
    return OPERATOR, None


def _boleh(tipe: str, gudang: str | None) -> bool:
    if gudang is None:
        return True
    milik = TIPE_GUDANG.get(tipe)
    return milik is None or milik == gudang


async def daftar(db: AsyncSession, user: User, *, hari: int = HARI) -> list[Kabar]:
    """Kabar untuk orang ini, yang terbaru lebih dulu.

    Yang MERAH didahulukan meski lebih tua: kabar yang menyebut ada barang
    dibukukan tanpa pernah diproduksi tak boleh terdorong ke bawah oleh tiga
    kabar kuning yang lahir sesudahnya.
    """
    peran, gudang = await keranjang(user)
    batas = now_local() - timedelta(days=hari)
    baris = (await db.execute(
        select(Notification)
        .where(Notification.created_at >= batas,
               # `target_role` kosong = belum dialamatkan siapa pun. Ikut
               # dibacakan: kabar tanpa alamat yang tak pernah tampil adalah
               # kabar yang ditulis untuk tak dibaca.
               (Notification.target_role == peran)
               | (Notification.target_role.is_(None)))
        .order_by(Notification.created_at.desc())
    )).scalars().all()
    urut = {"merah": 0, "kuning": 1, "hijau": 2}
    keluar = [
        Kabar(id=n.id, tipe=n.tipe, pesan=n.pesan, prioritas=n.prioritas,
              baru=n.status == "baru", waktu=n.created_at,
              table_name=n.table_name, record_id=n.record_id)
        for n in baris if _boleh(n.tipe, gudang)]
    keluar.sort(key=lambda k: (urut.get(k.prioritas, 1), -k.id))
    return keluar


async def jumlah_baru(db: AsyncSession, user: User, *, hari: int = HARI) -> int:
    """Lencana laci. Dihitung dengan SARINGAN YANG SAMA dengan daftarnya.

    Dua hitungan untuk satu angka akan berselisih, dan yang salah adalah yang
    lebih jarang dibuka orang: lencana berangka 3 di atas layar yang memuat
    satu baris membuat orang berhenti mempercayai keduanya.
    """
    peran, gudang = await keranjang(user)
    batas = now_local() - timedelta(days=hari)
    if gudang is None:
        return int((await db.execute(
            select(func.count(Notification.id))
            .where(Notification.status == "baru",
                   Notification.created_at >= batas,
                   (Notification.target_role == peran)
                   | (Notification.target_role.is_(None)))
        )).scalar_one())
    # Dengan saringan gudang, penyaringnya Python (peta `TIPE_GUDANG`), jadi
    # yang dihitung jenisnya dulu — bukan barisnya satu per satu.
    return sum(n for tipe, n in (await db.execute(
        select(Notification.tipe, func.count(Notification.id))
        .where(Notification.status == "baru",
               Notification.created_at >= batas,
               (Notification.target_role == peran)
               | (Notification.target_role.is_(None)))
        .group_by(Notification.tipe)
    )).all() if _boleh(tipe, gudang))


async def ada_merah(db: AsyncSession, user: User, *, hari: int = HARI) -> bool:
    """Apakah di antara yang belum dibaca ada yang MERAH.

    Dipakai lencana laci untuk memilih warnanya, dan itu bukan hiasan. Aturan
    warna di aplikasi ini menyimpan warna penagih untuk pekerjaan yang harus
    dikerjakan — kabar biasanya bukan itu, jadi lencananya netral seperti
    "Sedang berjalan". Tetapi kabar merah menyebut hal seperti "ada yang
    dibukukan tanpa pernah diproduksi", dan itu memang menagih seseorang.

    Pemilik memintanya "angka merah di menu"; keduanya dijawab dengan
    membedakan: merah kalau ada yang merah, netral kalau tidak. Lencana yang
    selalu merah membuat merah berhenti berarti apa pun.
    """
    peran, gudang = await keranjang(user)
    batas = now_local() - timedelta(days=hari)
    tipe = [t for t, in (await db.execute(
        select(Notification.tipe)
        .where(Notification.status == "baru",
               Notification.prioritas == "merah",
               Notification.created_at >= batas,
               (Notification.target_role == peran)
               | (Notification.target_role.is_(None)))
        .distinct()
    )).all()]
    return any(_boleh(t, gudang) for t in tipe)


async def tandai_terbaca(db: AsyncSession, ids) -> int:
    """Tandai kabar yang baru saja tergambar sebagai `dibaca`.

    HANYA yang masih `baru`: baris yang sudah `selesai` (perkaranya beres,
    ditutup penulisnya sendiri) tak boleh dikembalikan jadi `dibaca` — itu
    memutar mundur keadaan yang lebih maju.
    """
    ids = [int(i) for i in ids]
    if not ids:
        return 0
    n = (await db.execute(
        update(Notification)
        .where(Notification.id.in_(ids), Notification.status == "baru")
        .values(status="dibaca"))).rowcount or 0
    if n:
        await db.commit()
    return n
