"""Pengelompokan tampilan saja; tidak menghitung konsumsi atau menulis saldo."""
MENUNGGU = 'menunggu'
DALAM_PROSES = 'dalam_proses'
HASIL = 'hasil'

TAHAP = (
    (MENUNGGU, 'Bahan menunggu proses',
     'Bahan di tumpukan, mesin atau silo yang menunggu tahap berikutnya.'),
    (DALAM_PROSES, 'Bahan dalam proses',
     'Jumlah bahan masuk yang terikat ke proses. Sisa aktual dikonfirmasi saat silo atau mesin diselesaikan.'),
    (HASIL, 'Hasil tercatat',
     'Saldo hasil setelah pemindahan dan pengeluaran yang tercatat. Hasil dari proses berjalan masih sementara.'),
)


def kelompok_baris(rows):
    """Setiap saldo muncul sekali pada tahapnya; tanpa total lintas tahap."""
    return [dict(kunci=k, judul=j, keterangan=ket,
                 baris=[r for r in rows if r['tahap'] == k])
            for k, j, ket in TAHAP]


def untuk_stok(bahan, lot, tempat):
    groups = kelompok_baris(bahan)
    for g in groups:
        g['lot'] = list(lot) if g['kunci'] == HASIL else []
        g['tempat'] = list(tempat) if g['kunci'] == MENUNGGU else []
    return groups
