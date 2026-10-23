"""Bobot karung per partai; ukuran surat jalan bukan bobot bahan mesin."""
from decimal import Decimal

from sqlalchemy import Numeric, cast, func


def bobot_per_karung(batch, *, jumlah=1) -> Decimal | None:
    """Satu pembagi untuk pembaca Python dan SQL, tanpa menyimpan R.

    Tanpa argumen tambahan jawabannya R. `jumlah` mengalikan pembilang
    SEBELUM pembagian: sisa memakai N − ΣK agar hanya ada satu pembagian
    di ujung, bukan menjumlah pecahan pemindahan yang pernah dibulatkan.

    Perkiraan tetap mengikuti tangga bobot batch yang sudah ada. Pemanggil
    wajib membawa keadaan bobot itu ke layar, bukan mengeraskannya menjadi
    bobot pasti hanya karena perkaliannya berhasil.
    """
    if isinstance(batch, type):
        return (cast(batch.berat_total_kg, Numeric()) * jumlah) / func.nullif(batch.jumlah_karung, 0)
    if batch is None or not batch.jumlah_karung or batch.berat_total_kg is None:
        return None
    return (Decimal(str(batch.berat_total_kg)) * jumlah) / Decimal(batch.jumlah_karung)


def teks_kg(nilai) -> str:
    return f"{float(nilai):,.1f}".replace(",", "_").replace(".", ",").replace("_", ".") + " kg"


def selisih_kiriman(batch, pemasok: str) -> str | None:
    if not batch.jumlah_karung or not batch.ukuran_karung_kg or batch.berat_total_kg is None:
        return None
    if batch.sumber_berat == "perkiraan":
        return None
    nota = Decimal(batch.jumlah_karung) * Decimal(str(batch.ukuran_karung_kg))
    beda = nota - Decimal(str(batch.berat_total_kg))
    dasar = f"{pemasok} · surat jalan {teks_kg(nota)} − timbang {teks_kg(batch.berat_total_kg)}"
    if abs(beda) <= 5:
        return dasar + " · masih dalam keraguan pembacaan timbangan (±5 kg)"
    arah = "kurang" if beda > 0 else "lebih"
    persen = f"{abs(beda) / nota * 100:.2f}".replace(".", ",")
    return dasar + f" · {arah} terbaca {teks_kg(abs(beda))} ({persen}%), keraguan ±5 kg"


def peringatan_karung(batch) -> str | None:
    r = bobot_per_karung(batch)
    if r is None or not batch.ukuran_karung_kg:
        return None
    # Bandingkan dengan satu karung salah hitung, bukan ambang kekurangan
    # usaha yang belum ditetapkan pemilik. Ini ajakan memeriksa surat jalan,
    # tidak pernah penolakan maupun tuntutan menimbang sisa lot.
    nominal = Decimal(str(batch.ukuran_karung_kg))
    if abs(r - nominal) * batch.jumlah_karung > nominal + 5:
        return (f"Periksa jumlah karung pada surat jalan: bobot per karung {teks_kg(r)}, "
                f"ukuran nominal {teks_kg(nominal)}. Pencatatan tetap diterima.")
    return None


def teks_sisa_karung(batch, sisa_kg, sisa_karung=None):
    r = bobot_per_karung(batch)
    if r is not None and sisa_kg is not None:
        k = Decimal(str(sisa_kg)) / r
        satuan = "kurang dari 1 karung — " if 0 < k < 1 else f"sisa {k:.0f} karung ~ "
        angka = teks_kg(sisa_kg)
        if batch.sumber_berat == "perkiraan":
            angka = "± " + angka + " (bobot truk belum final)"
        return satuan + angka
    return f"sisa {sisa_karung if sisa_karung is not None else batch.jumlah_karung} karung (bobot truk belum final)"


def bobot_pemakaian(pemakaian):
    """Bawa kepastian sumber sampai laporan, termasuk campuran kg dan karung.

    Angka parsial tetap berguna bagi operasi, tetapi karung yang belum punya
    W bukan nol kg. Tangga Bobot yang sama dengan penerimaan memastikan
    angka parsial tidak disajikan sebagai neraca akhir yang pasti.
    """
    from app.penggilingan.gudang1.services.bobot import Bobot, PASTI, dari_batch, jumlah
    bagian = []
    for u in pemakaian:
        if not u.bobot_karung_dinamis:
            bagian.append(Bobot(float(u.berat_terpakai_kg or 0), PASTI))
            continue
        bagian.append(Bobot(float(u.awal_tetap_kg or 0) + float(u.masuk_tetap_kg or 0)
                            - float(u.berat_akhir_kg or 0), PASTI))
        for m in u.pemindahan_karung:
            if m.dibatalkan_pada is not None:
                continue
            sumber = dari_batch(m.batch)
            kg = m.berat_kg
            bagian.append(Bobot(None if kg is None else float(kg), sumber.keadaan,
                                sumber.tak_diketahui, sumber.asal))
    return jumlah(bagian)
