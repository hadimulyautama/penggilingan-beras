"""Komponen kualitatif QC PK, sama untuk hasil giling dan PK luar."""
LABEL_KUALITATIF = {"bersih": "Bersih", "sedikit": "Sedikit",
                    "sedang": "Sedang", "banyak": "Banyak"}
KOMPONEN_KUALITATIF = (("Butir kuning", "butir_kuning"),
                       ("Gabah", "gabah"), ("Merang", "merang"))


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
            raise ValueError(f"{label} harus: bersih, sedikit, sedang, atau banyak.")
        hasil[medan] = nilai
    return hasil
