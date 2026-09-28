"""Layar Kabar — pembaca `notifications`, yang selama ini tak ada.

Keputusan pemilik 26 September 2026 sesudah satu temuan yang tak enak dibaca:
aplikasi ini sudah LIMA TEMPAT menulis notifikasi — harga gabah belum
diverifikasi, pengeringan telat, penyosohan selesai & perlu verifikasi output,
packing, dan rantai permintaan PK — dan tak satu pun layar membacanya untuk
ditampilkan. Tabel itu dibaca hanya untuk menutup barisnya sendiri.

Pagar di berkas ini menjaga dua hal yang paling mudah rusak diam-diam:
lencananya harus menyebut angka yang sama dengan daftarnya, dan kabar yang
jelas milik satu gudang tak boleh mampir ke layar gudang sebelah.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def orang(pg, pemakai):
    """Satu Admin, satu operator Gudang 1, satu operator Gudang 2."""
    from sqlalchemy import select

    from app.models import User, Warehouse
    from app.services.seed import seed_master

    await seed_master()
    async with pg() as db:
        wh = {}
        for nama, pola in (("g1", "Gudang 1%"), ("g2", "Gudang 2%")):
            w = (await db.execute(select(Warehouse).where(
                Warehouse.nama_gudang.like(pola)))).scalars().first()
            if w is None:
                w = Warehouse(nama_gudang=f"Gudang {nama[-1]} - Uji")
                db.add(w)
                await db.flush()
            wh[nama] = w.id
        adm = User(nama="Admin Kabar", role="admin", status="aktif")
        op1 = User(nama="Operator Selepan", role="operator", status="aktif",
                   default_warehouse_id=wh["g1"])
        op2 = User(nama="Operator Polesan", role="operator", status="aktif",
                   default_warehouse_id=wh["g2"])
        db.add_all([adm, op1, op2])
        await db.commit()
        for u in (adm, op1, op2):
            await db.refresh(u)
        return {"admin": adm.id, "op1": op1.id, "op2": op2.id}


async def _tulis(pg, *, tipe, pesan, untuk, prioritas="kuning", umur_hari=0):
    from datetime import timedelta

    from app.database import now_local
    from app.models import Notification

    async with pg() as db:
        n = Notification(tipe=tipe, pesan=pesan, target_role=untuk,
                         prioritas=prioritas)
        db.add(n)
        await db.flush()
        if umur_hari:
            from sqlalchemy import update
            await db.execute(update(Notification).where(Notification.id == n.id)
                             .values(created_at=now_local() - timedelta(days=umur_hari)))
        await db.commit()
        return n.id


async def test_kabar_akhirnya_punya_pembaca(pg, orang):
    """Inti keputusannya. Sebelum ini: notifikasi ditulis lima tempat dan tak
    satu pun layar membacanya — kalimatnya ditulis rapi lalu masuk lemari yang
    tak pernah dibuka siapa pun."""
    from app.models import User
    from app.services.kabar import daftar

    await _tulis(pg, tipe="verifikasi_penyosohan", untuk="admin",
                 pesan="🟡 Penyosohan POL-01 selesai — perlu verifikasi output")

    async with pg() as db:
        k = await daftar(db, await db.get(User, orang["admin"]))
    assert len(k) == 1 and "perlu verifikasi output" in k[0].pesan
    assert k[0].baru, "kabar baru tak bertanda baru"


async def test_lencana_menyebut_angka_yang_sama_dengan_daftarnya(pg, orang):
    """Dua hitungan untuk satu angka akan berselisih, dan yang salah adalah
    yang lebih jarang dibuka orang. Lencana berangka 3 di atas layar yang memuat
    satu baris membuat orang berhenti mempercayai keduanya."""
    from app.models import User
    from app.services.kabar import daftar, jumlah_baru

    await _tulis(pg, tipe="verifikasi_penyosohan", untuk="admin", pesan="a")
    await _tulis(pg, tipe="permintaan_pk", untuk="admin", pesan="b")
    await _tulis(pg, tipe="pengeringan_telat", untuk="operator", pesan="c")

    async with pg() as db:
        for kunci in ("admin", "op1", "op2"):
            u = await db.get(User, orang[kunci])
            assert await jumlah_baru(db, u) == \
                len([x for x in await daftar(db, u) if x.baru]), kunci


async def test_kabar_satu_gudang_tak_mampir_ke_gudang_sebelah(pg, orang):
    """`notifications` tak punya kolom orang, dan "operator" dipakai KEDUA
    gudang. Tanpa saringan, operator polesan akan membaca kabar dryer yang tak
    pernah ia sentuh — dan kabar yang jelas bukan urusannya mengajari orang
    melewatkan seluruh daftar.

    ⚠ `permintaan_pk` SENGAJA tidak disaring, dan pagar ini dulu menuntut
    sebaliknya: ia memeriksa bahwa kabar permintaan hanya sampai ke Gudang 2.
    Itu benar selama satu hari — 26 September 2026, ketika seluruh rantai
    sesudah "Minta" disangka milik Gudang 2. Sejak pemilik menjawab skenario B1
    pada 27 September ("gudang 1 yang mengirim"), rantai itu melibatkan KEDUA
    gudang: yang satu meminta, yang lain memuat. Menyaringnya ke "g2" akan
    menyembunyikan kabar "ada yang harus Anda kirim" dari orang yang harus
    mengirimnya — persis kesalahan yang paling mahal di antara dua-duanya.

    Jadi aturannya tidak dilunakkan, cuma dipakai pada jenis yang memang milik
    satu gudang.
    """
    from app.models import User
    from app.services.kabar import TIPE_GUDANG, daftar

    await _tulis(pg, tipe="permintaan_pk", untuk="operator",
                 pesan="🟢 Permintaan lot LOT-01 DISETUJUI — Gudang 1 memuat")
    await _tulis(pg, tipe="pengeringan_telat", untuk="operator",
                 pesan="🟡 Lot G-01 telat diperbarui")

    async with pg() as db:
        k1 = [x.tipe for x in await daftar(db, await db.get(User, orang["op1"]))]
        k2 = [x.tipe for x in await daftar(db, await db.get(User, orang["op2"]))]
        kadm = [x.tipe for x in await daftar(db, await db.get(User, orang["admin"]))]
    assert TIPE_GUDANG.get("pengeringan_telat") == "g1"
    assert "permintaan_pk" not in TIPE_GUDANG, \
        "kabar rantai permintaan disaring ke satu gudang — yang lain buta"
    # Dryer milik Gudang 1 saja; permintaan milik keduanya.
    assert sorted(k1) == ["pengeringan_telat", "permintaan_pk"], k1
    assert k2 == ["permintaan_pk"], k2
    # Admin memegang KEDUA gudang; kabar yang disembunyikan dari orang yang
    # bertanggung jawab atas keduanya adalah kabar yang hilang. Yang ia lihat
    # tetap hanya yang dialamatkan kepadanya.
    assert kadm == []


async def test_jenis_yang_belum_terdaftar_dianggap_milik_keduanya(pg, orang):
    """`TIPE_GUDANG` peta, dan peta bisa basi. Jenis kabar baru yang lupa
    didaftarkan harus TETAP tampil di kedua gudang — kabar yang salah alamat
    cuma mengganggu; kabar yang hilang membuat orang menunggu sesuatu yang tak
    akan datang."""
    from app.models import User
    from app.services.kabar import TIPE_GUDANG, daftar

    assert "jenis_baru_yang_belum_didaftar" not in TIPE_GUDANG
    await _tulis(pg, tipe="jenis_baru_yang_belum_didaftar", untuk="operator",
                 pesan="kabar dari masa depan")

    async with pg() as db:
        for kunci in ("op1", "op2"):
            k = await daftar(db, await db.get(User, orang[kunci]))
            assert [x.pesan for x in k] == ["kabar dari masa depan"], kunci


async def test_yang_merah_didahulukan_meski_lebih_tua(pg, orang):
    """Kabar yang menyebut ada barang dibukukan tanpa pernah diproduksi tak
    boleh terdorong ke bawah oleh tiga kabar kuning yang lahir sesudahnya."""
    from app.models import User
    from app.services.kabar import daftar

    await _tulis(pg, tipe="permintaan_pk", untuk="admin", prioritas="merah",
                 pesan="MERAH", umur_hari=2)
    await _tulis(pg, tipe="verifikasi_penyosohan", untuk="admin", pesan="kuning 1")
    await _tulis(pg, tipe="verifikasi_penyosohan", untuk="admin", pesan="kuning 2")

    async with pg() as db:
        k = await daftar(db, await db.get(User, orang["admin"]))
    assert k[0].pesan == "MERAH", [x.pesan for x in k]
    # Di antara yang sederajat, yang terbaru lebih dulu.
    assert [x.pesan for x in k[1:]] == ["kuning 2", "kuning 1"]


async def test_kabar_berumur_dan_berhenti_sendiri(pg, orang):
    """Daftar yang harus dipencet supaya bersih akan menumpuk di layar orang
    yang bekerja dengan satu tangan, lalu berhenti dibuka."""
    from app.models import User
    from app.services.kabar import HARI, daftar, jumlah_baru

    await _tulis(pg, tipe="verifikasi_penyosohan", untuk="admin", pesan="lama",
                 umur_hari=HARI + 1)
    await _tulis(pg, tipe="verifikasi_penyosohan", untuk="admin", pesan="baru")

    async with pg() as db:
        u = await db.get(User, orang["admin"])
        assert [x.pesan for x in await daftar(db, u)] == ["baru"]
        assert await jumlah_baru(db, u) == 1, "yang kedaluwarsa masih menagih lencana"


async def test_membuka_layarnya_menandai_terbaca_dan_lencananya_nol(pg, orang):
    """DIBUKA = DIBACA. Tombol "tandai sudah dibaca" sengaja tak ada: ia ketukan
    kedua untuk pekerjaan yang sudah selesai saat mata sampai ke barisnya.

    Yang sudah dibaca TETAP tergambar sampai umurnya habis — ini riwayat tujuh
    hari, bukan kotak masuk yang harus dikosongkan.
    """
    import httpx

    from app.main import app
    from app.models import ProduksiAkun, User
    from app.services.berjalan import untuk
    from app.services.kabar import jumlah_baru
    from app.web import csrf, security
    from hmu_identitas import sandi as S
    from hmu_identitas.model import mode_bawaan

    await _tulis(pg, tipe="verifikasi_penyosohan", untuk="admin",
                 pesan="🟡 Penyosohan POL-09 selesai — perlu verifikasi output")
    async with pg() as db:
        u = await db.get(User, orang["admin"])
        # Lencananya terlihat dari layar LAIN — di situlah gunanya.
        assert (await untuk(db, u)).lencana()["KABAR"] == 1
        a = ProduksiAkun(user_id=u.id, username="uji_kabar",
                         password_hash=S.hash_sandi("rahasia123"), status="aktif",
                         mode_perangkat=mode_bawaan("admin"))
        db.add(a)
        await db.commit()
        token = security.buat_token(a)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://uji") as c:
        c.cookies.set(security.NAMA_COOKIE, token)
        c.cookies.set(csrf.NAMA_COOKIE, csrf.terbitkan_baru())
        r = await c.get("/kabar")
    assert r.status_code == 200, r.text[:400]
    assert "perlu verifikasi output" in r.text
    # Kepala layar menyebut berapa yang baru. Bunyinya berubah 28 September
    # 2026: semula satu kalimat di dalam `.nota--hati` — yang ternyata grid dua
    # kolom, jadi kalimatnya patah satu kata per baris di kolom ikon selebar
    # 15px ("informasi di kartu pertama jelek sekali", pemilik, dengan fotonya).
    # Kini bentuknya SAMA dengan kepala Stok dan Stok Produk. Yang dijaga tetap
    # sama: angkanya tergambar, dan halaman menyebut kabar itu sudah ditandai
    # terbaca.
    assert "Belum dibaca" in r.text, "kepala layar tak menyebut yang belum dibaca"
    assert ">1<" in r.text, "halaman tak menyebut berapa yang baru"
    assert "sudah ditandai terbaca" in r.text

    async with pg() as db:
        u = await db.get(User, orang["admin"])
        assert await jumlah_baru(db, u) == 0, "lencana tak kembali nol"
        # Dan barisnya TETAP ada, cuma tak lagi bertanda baru.
        from app.services.kabar import daftar
        k = await daftar(db, u)
        assert len(k) == 1 and not k[0].baru


async def test_yang_sudah_selesai_tak_diputar_mundur_jadi_dibaca(pg, orang):
    """Baris `selesai` ditutup penulisnya sendiri karena perkaranya beres.
    Menandainya `dibaca` memutar mundur keadaan yang lebih maju — dan
    penulisnya memakai `status != "selesai"` untuk tahu apa yang masih
    tertunda."""
    from sqlalchemy import select, update

    from app.models import Notification, User
    from app.services.kabar import tandai_terbaca

    nid = await _tulis(pg, tipe="verifikasi_harga_gabah", untuk="admin",
                       pesan="harga belum diverifikasi")
    async with pg() as db:
        await db.execute(update(Notification).where(Notification.id == nid)
                         .values(status="selesai"))
        await db.commit()

    async with pg() as db:
        assert await tandai_terbaca(db, [nid]) == 0
        assert (await db.execute(select(Notification.status).where(
            Notification.id == nid))).scalar_one() == "selesai"
    assert orang["admin"]


async def test_pintu_kabar_ditawarkan_ke_semua_peran(pg, orang):
    """Kabar bukan kerja meja: operator pun perlu tahu lotnya telat diperbarui
    atau permintaannya ditolak. Pintunya tak boleh padam untuk siapa pun."""
    from app.models import User
    from app.services.berjalan import untuk
    from app.web.nav import TAB

    kunci = {k: view for k, _, _, _, view in TAB}
    assert "kabar" in kunci and kunci["kabar"] is None, \
        "pintu Kabar dibatasi peran tertentu"
    async with pg() as db:
        for nama in ("admin", "op1", "op2"):
            b = await untuk(db, await db.get(User, orang[nama]))
            assert "kabar" not in b.lencana()["PINTU_MATI"], nama
