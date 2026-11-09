"""Sampel → sesi garapan menurut waktu → estimasi pembagian total per jenis.

Waktu sampel adalah bukti pengamatan jenis beras di mesin; waktu input lab
dan waktu timbang bukan waktu pergantian garapan. Pemetaan adalah turunan,
bukan perubahan identitas sampel, dan masih sementara selama proses berjalan.
"""
from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from fractions import Fraction

from sqlalchemy import select

from app.services.spesifikasi_beras import daftar, jenis_beras, adalah_spek, nama_spek
from app.database import now_local
from app.models import JedaProses, PolishingOutputLog, PolishingProcess, SampelQcSosoh, User
from app.services.activity_log import log_activity

JENIS = {"premium": "Premium", "medsuper": "Medium Super", "medium": "Medium",
         "sayur": "Ekonomis", "beras_b": "Beras B"}

def label_jenis(jenis):
    return nama_spek(jenis) or JENIS.get(jenis, jenis)

ANGKA = {"kadar_air": "Kadar air", "broken_persen": "Broken", "md": "MD",
         "transparant": "Transparant", "whiteness": "Whiteness"}
PERSEN = frozenset({'kadar_air', 'broken_persen'})
BATAS_ANGKA = Decimal('9999999999.99')  # Batas penyimpanan Numeric(12,2), bukan ambang mutu.


def label_komponen(k):
    return ANGKA[k] + (' (%)' if k in PERSEN else '')


def angka_qc(k, nilai):
    """Koma adalah pemisah desimal; pembulatan desimal dilakukan sekali di server.

    MD dapat melebihi 100. Batas persentase hanya berlaku untuk kadar air dan
    broken. Decimal menghindari kesalahan float pada nilai seperti 1,005.
    """
    if nilai is None or isinstance(nilai, str) and not nilai.strip():
        return None
    try:
        n = Decimal(str(nilai).strip().replace(',', '.'))
    except InvalidOperation:
        raise QcSosohError(f'{ANGKA[k]} harus berupa angka.') from None
    batas = Decimal(100) if k in PERSEN else BATAS_ANGKA
    if not n.is_finite() or n < 0 or n > batas:
        pesan = 'antara 0 dan 100%.' if k in PERSEN else 'angka tidak negatif dalam batas penyimpanan.'
        raise QcSosohError(f'{ANGKA[k]} harus {pesan}')
    return n.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


class QcSosohError(ValueError):
    pass


def bagi_proporsional(jumlah, bobot):
    """Bagi unit bulat (sen kilogram); sisa terbesar menang, seri ke sesi awal.

    Fraction menjaga perbandingan persis. Seluruh sampel dibagikan sekali,
    tanpa menggandakan kilogram atau membuang sisa pembulatan.
    """
    berat = [Fraction(Decimal(str(x))) for x in bobot]
    if jumlah < 0 or any(x < 0 for x in berat):
        raise ValueError("Jumlah sampel dan bobot harus tidak negatif.")
    total = sum(berat)
    if not total:
        return [0] * len(berat)
    jatah = [jumlah * b / total for b in berat]
    hasil = [q.numerator // q.denominator for q in jatah]
    urut = sorted(range(len(berat)), key=lambda i: (-(jatah[i] - hasil[i]), i))
    for i in urut[:jumlah - sum(hasil)]:
        hasil[i] += 1
    return hasil


def _detik_aktif(awal, akhir, jeda):
    """Kurangi gabungan jeda, termasuk jeda tumpang tindih, tepat sekali."""
    interval = sorted((max(awal, a), min(akhir, b)) for a, b in jeda if a < akhir and b > awal)
    tertahan, ujung = 0, awal
    for a, b in interval:
        a = max(a, ujung)
        if b > a:
            tertahan += (b-a).total_seconds()
            ujung = b
    return max(0, (akhir-awal).total_seconds()-tertahan)


def petakan(sampel, hasil, *, sampai=None, mulai=None, jeda=()):
    """QC menentukan sesi; tiap selisih hasil mempunyai cakupan waktunya sendiri.

    QC langsung diambil saat ganti garapan (keputusan pemilik 4 November):
    sampel pertama menjadi perkiraan awal sesi, bukan titik tengah sampel.
    Sesi terakhir sampai akhir proses atau waktu pembacaan untuk proses aktif.
    Semua batas dan bobot sesi adalah ESTIMASI;
    hanya jumlah hasil per jenis merupakan berat aktual. Jeda tidak produktif
    dikeluarkan dari pembobotan durasi.
    """
    sampel = sorted((q for q in sampel if not getattr(q, 'dibatalkan_pada', None)),
                    key=lambda r: (r.waktu_sampel, r.id))
    sampai = sampai or (sampel[-1].waktu_sampel if sampel else None)
    jenis_labels = {**JENIS, **{r.jenis: label_jenis(r.jenis) for r in [*sampel, *hasil] if adalah_spek(r.jenis)}}
    sesi = []
    for q in sampel:
        pisah = None
        if sesi:
            sebelumnya = sesi[-1]["sampel"][-1].waktu_sampel
            pisah = next(((a, b) for a, b in reversed(sorted(jeda)) if sebelumnya < a < b <= q.waktu_sampel), None)
        if not sesi or sesi[-1]["jenis"] != q.jenis or pisah:
            sesi.append(dict(nomor=len(sesi)+1, jenis=q.jenis, sampel=[]))
        sesi[-1]["sampel"].append(q)
    for i, s in enumerate(sesi):
        awal, akhir = s["sampel"][0].waktu_sampel, s["sampel"][-1].waktu_sampel
        a = awal
        b = sesi[i+1]['sampel'][0].waktu_sampel if i+1 < len(sesi) else sampai
        s.update(teramati_mulai=awal, teramati_sampai=akhir, estimasi_mulai=a, estimasi_sampai=b,
                 durasi_detik=_detik_aktif(a, b, jeda), berat_estimasi_kg=None, rata=rata_rata(s["sampel"]),
                 batas_awal=(sesi[i-1]["sampel"][-1].waktu_sampel, awal) if i else None,
                 batas_akhir=(akhir, sesi[i+1]["sampel"][0].waktu_sampel) if i+1 < len(sesi) else None)

    total, sesi_jenis = defaultdict(Decimal), defaultdict(list)
    for s in sesi:
        sesi_jenis[s["jenis"]].append(s)
    # Kumulatif 5/6/8 ton dan tambahan 5/1/2 ton sudah sama-sama berupa
    # delta di OutputLog. Jangan kumpulkan seluruh delta lalu membaginya ke
    # semua sesi: itu akan memindahkan hasil pukul 12 ke sesi yang baru mulai 15.
    # Baris pada waktu yang sama satu cuplikan, termasuk penambahan berturut-
    # turut di akhir. Rentangnya tidak boleh menjadi nol setelah baris pertama.
    kelompok = defaultdict(Decimal)
    for r in hasil:
        if r.jenis in jenis_labels:
            kg = Decimal(str(r.berat_kg or 0)).quantize(Decimal('0.01'))
            total[r.jenis] += kg
            kelompok[(r.jenis, r.waktu_update)] += kg
    for jenis in jenis_labels:
        sebelumnya = mulai or (sampel[0].waktu_sampel if sampel else None)
        for (_, waktu), kg in sorted(((k, v) for k, v in kelompok.items() if k[0] == jenis), key=lambda r: r[0][1]):
            if sebelumnya is None:
                sebelumnya = waktu
            kandidat = sesi_jenis[jenis]
            bobot = [_detik_aktif(max(sebelumnya, s['estimasi_mulai']),
                        min(waktu, s['estimasi_sampai']), jeda)
                     if max(sebelumnya, s['estimasi_mulai']) < min(waktu, s['estimasi_sampai']) else 0
                     for s in kandidat]
            if sum(bobot):
                jatah = bagi_proporsional(abs(int(kg*100)), bobot)
                for s, sen in zip(kandidat, jatah):
                    if sen or (kg == 0 and s['berat_estimasi_kg'] is not None):
                        s['berat_estimasi_kg'] = (s['berat_estimasi_kg'] or Decimal(0)) + Decimal(sen if kg >= 0 else -sen)/100
            sebelumnya = max(sebelumnya, waktu)
    rekap, alokasi, catatan = [], {}, []
    for jenis in jenis_labels:
        ss = sesi_jenis[jenis]
        kg = total.get(jenis, Decimal(0)).quantize(Decimal('0.01'))
        if not ss and not kg:
            continue
        rekap.append(dict(jenis=jenis, berat_kg=kg if jenis in total else None, sesi=[s['nomor'] for s in ss], belum_dipetakan_kg=kg))
        if not ss:
            catatan.append(f"{jenis_labels[jenis]}: hasil timbang ada, tetapi belum ada sampel untuk mengestimasi waktu garapannya.")
            continue
        for s in ss:
            if s['berat_estimasi_kg'] is None:
                continue
            sen = int(s['berat_estimasi_kg']*100)
            # Tiap QC tetap tinggal di sesi asal. Di dalam sesi, periode yang
            # paling dekat dengan tiap waktu sampel dibobot dengan durasi aktif.
            qs = s["sampel"]
            batas = [s["estimasi_mulai"], *[a.waktu_sampel+(b.waktu_sampel-a.waktu_sampel)/2 for a, b in zip(qs, qs[1:])], s["estimasi_sampai"]]
            bobot = [_detik_aktif(a, b, jeda) for a, b in zip(batas, batas[1:])]
            bagian = bagi_proporsional(abs(sen), bobot if sum(bobot) else [1]*len(qs))
            for i, (q, berat) in enumerate(zip(qs, bagian)):
                alokasi[q.id] = dict(sesi=s["nomor"], berat_estimasi_kg=Decimal(berat if sen >= 0 else -berat)/100,
                                    estimasi_mulai=batas[i], estimasi_sampai=batas[i+1])
        rekap[-1]['belum_dipetakan_kg'] = kg-sum(s['berat_estimasi_kg'] or 0 for s in ss)
        if rekap[-1]['belum_dipetakan_kg']:
            catatan.append(f"{jenis_labels[jenis]}: {rekap[-1]['belum_dipetakan_kg']} kg belum dapat dipetakan; belum ada durasi QC yang sesuai dalam rentang pencatatannya.")
    return dict(sesi=sesi, hasil=rekap, alokasi=alokasi,
                belum_dipetakan=[q.id for q in sampel if q.id not in alokasi], catatan=catatan)


def ringkasan(q):
    nilai = [f"{label} {format(angka_qc(k, getattr(q, k)), '.2f').replace('.', ',')}{'%' if k in PERSEN else ''}"
             for k, label in ANGKA.items() if getattr(q, k) is not None]
    if q.catatan_lab:
        nilai.append(q.catatan_lab)
    return " · ".join(nilai) if q.hasil_pada else "Menunggu hasil QC"


def rata_rata(sampel):
    hasil = []
    for k, label in ANGKA.items():
        nilai = [Decimal(str(getattr(q, k))) for q in sampel if q.hasil_pada and getattr(q, k) is not None]
        if nilai:
            hasil.append((label, angka_qc(k, sum(nilai) / len(nilai)), len(nilai), '%' if k in PERSEN else ''))
    return hasil


async def ambil_sampel(db, *, user, kode_proses, jenis, waktu_sampel, kunci_kiriman=None):
    from sqlalchemy import text
    await db.execute(text("SELECT pg_advisory_xact_lock_shared(861274003)"))
    if jenis not in await jenis_beras(db):
        raise QcSosohError("Pilih jenis beras yang diambil sampelnya.")
    if waktu_sampel.tzinfo is None:
        raise QcSosohError("Waktu pengambilan sampel harus menyertakan zona waktu.")
    proc = await db.scalar(select(PolishingProcess).where(PolishingProcess.kode_proses == kode_proses)
                           .with_for_update().execution_options(populate_existing=True))
    if proc is None:
        raise QcSosohError("Proses sosoh tidak ditemukan.")
    if kunci_kiriman:
        if len(kunci_kiriman) > 80:
            raise QcSosohError("Kunci pengiriman sampel tidak valid.")
        lama = await db.scalar(select(SampelQcSosoh).where(
            SampelQcSosoh.polishing_process_id == proc.id, SampelQcSosoh.kunci_kiriman == kunci_kiriman))
        if lama:
            if lama.jenis != jenis:
                raise QcSosohError("Kiriman ini sudah digunakan untuk sampel jenis lain.")
            return lama
    if proc.status != 'proses':
        raise QcSosohError("Proses sosoh sudah ditutup. Hasil sampel yang sudah ada tetap dapat dilengkapi.")
    sekarang = now_local()
    if waktu_sampel > sekarang:
        raise QcSosohError("Waktu pengambilan sampel tidak boleh di masa depan.")
    if waktu_sampel < proc.waktu_mulai or (proc.waktu_selesai and waktu_sampel > proc.waktu_selesai):
        raise QcSosohError("Waktu sampel harus berada dalam waktu proses sosoh.")
    q = SampelQcSosoh(polishing_process_id=proc.id, jenis=jenis, kunci_kiriman=kunci_kiriman, waktu_sampel=waktu_sampel,
                      dicatat_pada=sekarang, pengambil_id=user.id)
    db.add(q)
    await db.flush()
    await log_activity(db, table_name=q.__tablename__, record_id=q.id, action="INSERT", changed_by=user.id,
                       gudang="g2", new_value=f"Sampel #{q.id} · {kode_proses} · {label_jenis(jenis)} · {waktu_sampel.isoformat()}")
    await db.commit()
    return q


async def isi_hasil(db, *, user, sampel_id, **nilai):
    q = await db.scalar(select(SampelQcSosoh).where(SampelQcSosoh.id == sampel_id).with_for_update().execution_options(populate_existing=True))
    if q is None:
        raise QcSosohError("Sampel QC sosoh tidak ditemukan.")
    if q.dibatalkan_pada:
        raise QcSosohError("Sampel ini sudah dibatalkan; hasil QC tidak dapat ditambahkan.")
    if q.hasil_pada is not None:
        raise QcSosohError("Hasil sampel ini sudah dicatat. Pengiriman kedua tidak menimpa hasil sebelumnya.")
    kunci = {*ANGKA, "catatan_lab"}
    if set(nilai) - kunci:
        raise QcSosohError("Identitas sampel tidak dapat diganti saat mengisi hasil QC.")
    bersih = {}
    for k, v in nilai.items():
        if k in ANGKA:
            v = angka_qc(k, v)
        elif k == "catatan_lab":
            v = (v or "").strip() or None
            if v and len(v) > 500:
                raise QcSosohError("Catatan lab maksimal 500 karakter.")
        bersih[k] = v
    if not any(v is not None for v in bersih.values()):
        raise QcSosohError("Isi minimal satu hasil pemeriksaan QC.")
    for k, v in bersih.items():
        setattr(q, k, v)
    q.hasil_pada, q.pemeriksa_id = now_local(), user.id
    await log_activity(db, table_name=q.__tablename__, record_id=q.id, action="UPDATE", changed_by=user.id,
                       gudang="g2", field_name="hasil_qc", new_value=ringkasan(q))
    await db.commit()
    return q


async def data_proses(db, proc):
    labels = {r["kode"]: r["nama"] for r in await daftar(db, termasuk_nonaktif=True)}
    labels["beras_b"] = "Beras B"
    sampel = list((await db.scalars(select(SampelQcSosoh).where(SampelQcSosoh.polishing_process_id == proc.id)
                 .order_by(SampelQcSosoh.waktu_sampel, SampelQcSosoh.id))).all())
    hasil = list((await db.scalars(select(PolishingOutputLog).where(PolishingOutputLog.polishing_process_id == proc.id)
                .order_by(PolishingOutputLog.waktu_update, PolishingOutputLog.id))).all())
    nama = dict((await db.execute(select(User.id, User.nama).where(User.id.in_(
        {q.pengambil_id for q in sampel} | {q.pemeriksa_id for q in sampel if q.pemeriksa_id})))).all()) if sampel else {}
    sampai = proc.waktu_selesai or now_local()
    jeda = [(j.mulai, j.selesai or sampai) for j in (await db.scalars(select(JedaProses).where(
        JedaProses.polishing_process_id == proc.id, JedaProses.dibatalkan_pada.is_(None)))).all()]
    aktif = [q for q in sampel if not q.dibatalkan_pada]
    data = petakan(aktif, hasil, mulai=proc.waktu_mulai, sampai=sampai, jeda=jeda)
    sesi_sampel = {q.id: s['nomor'] for s in data['sesi'] for q in s['sampel']}
    data.update(sampel=[dict(q=q, nomor=i+1, nilai=ringkasan(q),
                            pengambil=nama.get(q.pengambil_id, "Tidak tercatat"),
                            pemeriksa=nama.get(q.pemeriksa_id, "Belum dicatat"),
                            sesi=sesi_sampel.get(q.id),
                            alokasi=data['alokasi'].get(q.id))
                        for i, q in enumerate(sampel)],
                sementara=proc.status != "selesai", jenis_label=labels,
                komponen=[dict(nama=k, label=label_komponen(k)) for k in ANGKA],
                menunggu=sum(q.hasil_pada is None for q in aktif))
    return data


async def rekap_proses(db, proses_ids):
    """Hitung QC hanya untuk proses yang sudah diizinkan pembaca halaman."""
    from sqlalchemy import func
    if not proses_ids:
        return {}
    q = SampelQcSosoh
    rows = (await db.execute(select(q.polishing_process_id, func.count(q.id),
        func.count(q.id).filter(q.hasil_pada.is_(None), q.dibatalkan_pada.is_(None)))
        .where(q.polishing_process_id.in_(proses_ids)).group_by(q.polishing_process_id))).all()
    return {pid: dict(jumlah=n, menunggu=m) for pid, n, m in rows}


async def kartu_menunggu(db):
    from app.services.berjalan import Baris
    from sqlalchemy import func
    q = SampelQcSosoh
    rows = (await db.execute(select(PolishingProcess,
        func.count(q.id).filter(q.dibatalkan_pada.is_(None)),
        func.count(q.id).filter(q.hasil_pada.is_(None), q.dibatalkan_pada.is_(None)))
        .outerjoin(q, q.polishing_process_id == PolishingProcess.id)
        .where(PolishingProcess.status == 'proses')
        .group_by(PolishingProcess.id).order_by(PolishingProcess.waktu_mulai, PolishingProcess.id))).all()
    baris = []
    for p, jumlah, menunggu in rows:
        baris.append(Baris(kode=p.kode_proses, isi=f"{jumlah} sampel · {menunggu} menunggu hasil lab",
                  keadaan="QC selama proses sosoh berjalan", aksi="sampel_qc_sosoh", nilai=p.kode_proses, fase="sosoh",
                  judul="QC penyosohan", sub=f"{p.kode_proses} · {jumlah} sampel",
                  fakta=[('Hasil lab', f'{menunggu} menunggu' if menunggu else 'Seluruhnya tercatat' if jumlah else 'Belum ada sampel')],
                  nota="Tetap aktif sampai proses sosoh ditutup.",
                  sejak=p.waktu_mulai, jasa_id=p.jasa_id, gudang="g2"))
    return baris


async def batalkan_sampel(db, *, user, sampel_id, alasan):
    alasan = (alasan or '').strip()
    if not alasan or len(alasan) > 500:
        raise QcSosohError("Isi alasan pembatalan, maksimal 500 karakter.")
    q = await db.scalar(select(SampelQcSosoh).where(SampelQcSosoh.id == sampel_id)
                        .with_for_update().execution_options(populate_existing=True))
    if q is None or q.dibatalkan_pada:
        raise QcSosohError("Sampel tidak ditemukan atau sudah dibatalkan.")
    q.dibatalkan_pada, q.dibatalkan_oleh_id, q.alasan_batal = now_local(), user.id, alasan
    await log_activity(db, table_name=q.__tablename__, record_id=q.id, action="UPDATE", changed_by=user.id,
                       gudang="g2", field_name="dibatalkan_pada", alasan=alasan,
                       new_value=f"Sampel #{q.id} dibatalkan; data awal dan hasil lab tetap tersimpan.")
    await db.commit()
    return q
