"""Bahasa status pengiriman dari catatan baca; tidak memverifikasi transaksi."""

def ringkasan(statuses, tiket=None, *, tertaut=False, dibatasi=False, cepat=False):
    aktif=[s for s in statuses if s!='batal']
    if dibatasi:timbang='Tidak ditampilkan pada rincian pelanggan'
    elif not tiket:timbang='Tiket belum dapat dibaca' if tertaut else 'Tanpa tiket tertaut'
    elif tiket.get('status_transaksi')=='VOID':timbang='Tiket dibatalkan'
    else:timbang={'SELESAI':'Selesai timbang','TERBUKA':'Menunggu timbang kedua','DITUTUP_PAKSA':'Ditutup tanpa timbang kedua'}.get(tiket.get('status_tiket'),'Status timbang belum dapat dipastikan')
    if not aktif:
        verifikasi='Pengiriman dibatalkan';berikut='Pengiriman ini dibatalkan. Catatan timbang dan jejak pengiriman tetap dapat ditelusuri.'
    elif all(s=='selesai' for s in aktif):
        verifikasi='Pengiriman terverifikasi';berikut='Verifikasi pengiriman sudah tercatat di PadiFlow. Metode dan petugas mengikuti jejak verifikasi yang tersimpan.'
    elif any(s=='perintah' for s in aktif):
        verifikasi='Menunggu selesai muat'
        berikut='Admin memeriksa jumlah aktual dan mengonfirmasi penyerahan melalui jalur pengiriman kecil.' if cepat else 'Operator gudang menyelesaikan catatan muatan. Verifikasi pengiriman di PadiFlow belum selesai.'
    elif all(s in ('selesai','dimuat') for s in aktif):
        verifikasi='Sebagian terverifikasi' if any(s=='selesai' for s in aktif) else 'Menunggu verifikasi pengiriman'
        if tiket and tiket.get('status_transaksi')=='VOID':berikut='Admin memeriksa tiket yang dibatalkan dan pengiriman terkait sebelum melanjutkan verifikasi.'
        elif tiket and tiket.get('status_tiket')=='TERBUKA':berikut='Petugas timbang menyelesaikan penimbangan. Verifikasi pengiriman di PadiFlow belum selesai.'
        else:berikut='Admin memeriksa verifikasi pengiriman di PadiFlow. Selesai timbang saja bukan bukti pengiriman terverifikasi.'
    else:verifikasi='Status verifikasi belum dapat dipastikan';berikut='Periksa catatan pengiriman terbaru sebelum melanjutkan.'
    return dict(timbang=timbang,verifikasi=verifikasi,berikut=berikut)
