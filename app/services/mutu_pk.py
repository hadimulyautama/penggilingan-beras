"""Komponen kualitatif QC PK, sama untuk hasil giling dan PK luar."""
from decimal import Decimal
from math import isfinite

# Kode, label, skala untuk rata-rata, skor kualitas. Pilihan formulir dan
# kedua perhitungan membaca daftar yang sama agar perubahan tetap selaras.
KLASIFIKASI_QC_PK = (
    ("bersih", "Bersih", 0, 100),
    ("sedikit", "Sedikit", 1, 80),
    ("sedang", "Sedang", 2, 70),
    ("banyak", "Banyak", 3, 60),
    ("parah", "Parah", 4, 10),
)
LABEL_KUALITATIF = {kode:label for kode,label,_,_ in KLASIFIKASI_QC_PK}
NILAI_KUALITATIF = {kode:skala for kode,_,skala,_ in KLASIFIKASI_QC_PK}
SKOR_KUALITATIF = {kode:skor for kode,_,_,skor in KLASIFIKASI_QC_PK}
ATURAN_RATA_QC_PK = ("Skala: " + " · ".join(f"{LABEL_KUALITATIF[k]} {n}" for k,n in NILAI_KUALITATIF.items())
                     + ". Rata-rata mengikuti kategori terdekat; nilai tengah ke kategori lebih kotor.")
KOMPONEN_KUALITATIF = (("Butir kuning", "butir_kuning"),
                       ("Gabah", "gabah"), ("Merang", "merang"))
NILAI_MEDAN_KUALITATIF = {medan for _, medan in KOMPONEN_KUALITATIF}
JUMLAH_KOMPONEN_QC_PK = 3 + len(KOMPONEN_KUALITATIF)

# Batas atas, termasuk batas, skor, rentang yang dibaca pengguna. Perhitungan
# dan penjelasan layar membaca aturan yang sama, agar keduanya tidak hanyut.
ATURAN_ANGKA = {
    "Kadar air": ((11, False, 0, "< 11%"), (12, False, 50, "11–<12%"),
        (13, False, 90, "12–<13%"), (14, False, 100, "13–<14%"),
        (14.5, False, 90, "14–<14,5%"), (15, False, 80, "14,5–<15%"),
        (15.5, False, 70, "15–<15,5%"), (16, False, 60, "15,5–<16%"),
        (16.5, True, 50, "16–16,5%"), (None, True, 10, "> 16,5%")),
    "Butir patah": ((20, False, 100, "< 20%"), (25, False, 90, "20–<25%"),
        (30, False, 80, "25–<30%"), (35, False, 70, "30–<35%"),
        (40, True, 60, "35–40%"), (50, True, 50, ">40–50%"),
        (None, True, 10, "> 50%")),
    "Susut": ((12, True, 100, "≤ 12%"), (13, True, 90, ">12–13%"),
        (14, True, 80, ">13–14%"), (15, True, 70, ">14–15%"),
        (16, True, 60, ">15–16%"), (17, True, 50, ">16–17%"),
        (None, True, 10, "> 17%")),
}
KELAS_KUALITAS = ((96, "A1"), (91, "A2"), (86, "B1"), (80, "B2"),
                  (76, "C1"), (70, "C2"), (50, "D"), (0, "F"))
KOMPONEN_ANGKA = (("Kadar air", "kadar_air"), ("Butir patah", "broken_persen"),
                  ("Susut", "susut_persen"))


def kategori_terdekat(angka):
    if angka is None:
        return None
    return min(NILAI_KUALITATIF, key=lambda k: (
        abs(Decimal(NILAI_KUALITATIF[k])-angka), -NILAI_KUALITATIF[k]))


def _angka(nilai):
    try:
        angka = float(str(nilai).strip().replace("%", "").replace(",", "."))
        return angka if isfinite(angka) else None
    except (TypeError, ValueError):
        return None


def aturan_angka(label, nilai):
    angka = _angka(nilai)
    if angka is not None:
        for batas, termasuk, skor, rentang in ATURAN_ANGKA.get(label, ()):
            if batas is None or angka < batas or (termasuk and angka == batas):
                return skor, rentang
    return None, None


def skor_komponen(label, nilai):
    if label in dict(KOMPONEN_KUALITATIF):
        return skor_kualitatif(nilai)
    return aturan_angka(label, nilai)[0]


def nilai_kualitas(mutu):
    nama = {label.lower(): label for label in (*ATURAN_ANGKA, *dict(KOMPONEN_KUALITATIF))}
    nama["broken"] = "Butir patah"
    skor = [skor_komponen(nama.get(label.strip().lower(), label), nilai)
            for label, nilai in mutu]
    skor = [s for s in skor if s is not None]
    return (sum(skor)/len(skor), len(skor)) if skor else (None, 0)


def kelas_kualitas(nilai):
    if nilai is None:
        return None
    return next((kelas for batas, kelas in KELAS_KUALITAS if nilai >= batas), "F")


def penilaian_dari_log(log):
    """Rincian enam komponen, sama untuk stok, riwayat dan setiap putaran.

    Log sudah dimuat oleh kedua layar. Rata-rata memakai nilai asli setiap
    isian; kategori kosong tidak menggeser penyebut. Persentase dinilai pada
    satu desimal seperti kartu stok yang sudah dipakai operator.
    """
    log = list(log)
    rows = []
    for label, medan in (*KOMPONEN_ANGKA, *KOMPONEN_KUALITATIF):
        fisik = medan in NILAI_MEDAN_KUALITATIF
        nilai = [getattr(qc, medan, None) for qc in log]
        angka = ([Decimal(NILAI_KUALITATIF[v]) for v in nilai if v in NILAI_KUALITATIF]
                 if fisik else [Decimal(str(v)) for v in nilai if v is not None])
        rata = sum(angka)/len(angka) if angka else None
        kategori = kategori_terdekat(rata) if fisik else None
        hasil = (LABEL_KUALITATIF[kategori] if fisik else
                 f"{float(rata):.1f}%".replace(".", ",")) if rata is not None else "Belum dinilai"
        skor = skor_komponen(label, kategori if fisik else hasil)
        aturan = (f"{hasil} → {skor}" if fisik else aturan_angka(label, hasil)[1]) if skor is not None else None
        rows.append(dict(label=label, hasil=hasil, skor=skor, n=len(angka), aturan=aturan,
                         skala=f"{rata:.2f}".replace(".", ",") if fisik and rata is not None else None,
                         kategori=NILAI_KUALITATIF[kategori] if kategori else None))
    skor = [r['skor'] for r in rows if r['skor'] is not None]
    nilai = sum(skor)/len(skor) if skor else None
    return dict(rows=rows, nilai=nilai, kelas=kelas_kualitas(nilai), n=len(skor),
                total=sum(skor), putaran=len(log), lengkap=len(skor)==JUMLAH_KOMPONEN_QC_PK,
                rumus=" + ".join(str(s) for s in skor),
                aturan_angka={label: [(rentang, skor) for _, _, skor, rentang in aturan]
                              for label, aturan in ATURAN_ANGKA.items()},
                klasifikasi=KLASIFIKASI_QC_PK, kelas_aturan=KELAS_KUALITAS)


def skor_kualitatif(nilai):
    """Skala putaran 0–4 terpisah dari skor kualitas yang ditetapkan pemilik."""
    kode = str(nilai or "").strip().lower()
    return SKOR_KUALITATIF.get(kode)


def rincian_kualitatif(qc, *, termasuk_kosong=False):
    return [(label, LABEL_KUALITATIF.get(getattr(qc, medan, None), getattr(qc, medan, None)) or "Belum dinilai")
            for label, medan in KOMPONEN_KUALITATIF
            if termasuk_kosong or getattr(qc, medan, None)]


def wajib_kualitatif(*, butir_kuning, gabah, merang):
    masukan = {"butir_kuning": butir_kuning, "gabah": gabah, "merang": merang}
    hasil = {}
    for label, medan in KOMPONEN_KUALITATIF:
        nilai = (masukan[medan] or "").strip().lower()
        if not nilai:
            raise ValueError(f"{label} wajib diisi saat QC PK.")
        if nilai not in LABEL_KUALITATIF:
            raise ValueError(f"{label} harus: {', '.join(LABEL_KUALITATIF)}.")
        hasil[medan] = nilai
    return hasil


async def ringkasan_banyak(db, model, kunci, ids):
    """Satu aturan untuk kedua asal PK, termasuk rata-rata klasifikasi."""
    from sqlalchemy import case, func, select
    from sqlalchemy.dialects.postgresql import aggregate_order_by, array_agg
    ids = list(ids)
    if not ids:
        return {}
    medan_mutu = ("butir_kuning", "gabah", "merang")
    rata_kategori = [func.avg(case(NILAI_KUALITATIF, value=getattr(model, medan)))
                     for medan in medan_mutu]
    catatan = array_agg(aggregate_order_by(model.catatan_lab, model.waktu.desc(), model.id.desc()
                   )).filter(model.catatan_lab.is_not(None), model.catatan_lab != "")[1]
    baris = (await db.execute(select(
        kunci, func.avg(model.kadar_air), func.count(model.kadar_air),
        func.avg(model.broken_persen), func.count(model.broken_persen),
        func.avg(model.susut_persen), func.count(model.susut_persen), func.count(),
        *rata_kategori, catatan,
    ).where(kunci.in_(ids)).group_by(kunci))).all()
    return {r[0]: dict(kadar_air=float(r[1]) if r[1] is not None else None,
                      broken=float(r[3]) if r[3] is not None else None,
                      susut=float(r[5]) if r[5] is not None else None,
                      n_kadar_air=int(r[2]), n_broken=int(r[4]), n_susut=int(r[6]), n=int(r[7]),
                      **dict(zip(medan_mutu, map(kategori_terdekat, r[8:11]))),
                      catatan_lab=r[11]) for r in baris}
