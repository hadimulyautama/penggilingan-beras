"""Komponen kualitatif QC PK, sama untuk hasil giling dan PK luar."""
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
JUMLAH_KOMPONEN_QC_PK = 3 + len(KOMPONEN_KUALITATIF)


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
    from decimal import Decimal
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
    def terdekat(angka):
        if angka is None:
            return None
        return min(NILAI_KUALITATIF, key=lambda k: (
            abs(Decimal(NILAI_KUALITATIF[k])-angka), -NILAI_KUALITATIF[k]))
    return {r[0]: dict(kadar_air=float(r[1]) if r[1] is not None else None,
                      broken=float(r[3]) if r[3] is not None else None,
                      susut=float(r[5]) if r[5] is not None else None,
                      n_kadar_air=int(r[2]), n_broken=int(r[4]), n_susut=int(r[6]), n=int(r[7]),
                      **dict(zip(medan_mutu, map(terdekat, r[8:11]))),
                      catatan_lab=r[11]) for r in baris}
