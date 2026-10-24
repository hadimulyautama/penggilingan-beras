"""Rekap Barang Jasa: data layar produksi dengan gaya dokumen perusahaan bersama."""
from reportlab.lib.units import mm
from reportlab.platypus import Spacer, TableStyle

from app.services.jasa import JUDUL_REKAP
from app.services.bahan_silo import kg_rinci
from app.web.pdf_dokumen import PenyajiDokumen


def buat_pdf(data: dict) -> bytes:
    view = PenyajiDokumen()
    p = view.p

    def table(headers, rows, widths, numbered=False, empty=False):
        cells = [[p(value, view.right if i == len(row) - 1 else view.normal)
                  for i, value in enumerate(row)] for row in rows]
        if numbered:
            cells = [[p('—' if empty else n, view.small_centered)] + row
                     for n, row in enumerate(cells, 1)]
            headers, widths = ['No.'] + headers, [8 * mm] + widths
        t = view.grid(headers, cells, widths, numeric=True)
        if numbered:
            t.setStyle(TableStyle([('LEFTPADDING', (0, 0), (0, -1), 3),
                                   ('RIGHTPADDING', (0, 0), (0, -1), 3)]))
        return t

    story = [p(JUDUL_REKAP.upper(), view.title),
             p('Nomor pesanan utama: ' + data['kode'], view.centered),
             Spacer(1, 6 * mm),
             view.identitas([('Nama pelanggan', data['pelanggan']),
                             ('Status pesanan', data['status'])])]
    if data['pesanan_asal']:
        story += [Spacer(1, 3 * mm),
                  p('Pesanan yang digabung: ' + ', '.join(j['kode'] for j in data['pesanan_asal'])),
                  p('Nomor asal tetap disimpan. Seluruh hasil dan pengambilan dihitung satu kali pada pesanan utama.', view.small)]
    story += [Spacer(1, 4 * mm), view.grid(
        ['Bahan diterima', 'Sudah diambil'],
        [[p(kg_rinci(data['masuk_kg']), view.bold),
          p(kg_rinci(data['kembali_kg']), view.bold)]], [87 * mm, 87 * mm])]

    for key, heading, labels in [
        ('dibawa', 'Penerimaan bahan', ['Bahan', 'Referensi penerimaan', 'Berat']),
        ('kembali', 'Pengambilan hasil', ['Barang', 'Referensi pengambilan', 'Berat']),
    ]:
        rows = [[r['nama'], r['kode'], kg_rinci(r['kg'])] for r in data[key]]
        story += [p(heading, view.section), table(
            labels, rows or [['Belum ada catatan.', '—', '—']],
            [67 * mm, 60 * mm, 39 * mm], numbered=True, empty=not rows)]

    remaining = [[r['nama'], kg_rinci(r['kg'])] for r in data['sisa']]
    story += [p('Masih di pabrik', view.section),
              table(['Barang / tahap', 'Berat'],
                    remaining or [['Tidak ada sisa barang tercatat.', '—']],
                    [127 * mm, 39 * mm], numbered=True, empty=not remaining),
              Spacer(1, 2 * mm),
              p('Bobot ditampilkan per tahap; saldo antar tahap tidak dijumlahkan sebagai stok siap diambil.', view.small)]

    balance = [['Bahan diterima', kg_rinci(data['masuk_kg'])],
               ['Sudah diambil', kg_rinci(data['kembali_kg'])]] + remaining
    if data['selisih_kg'] > 0:
        balance.append(['Selisih', kg_rinci(data['selisih_kg'])])
    story += [p('Neraca bobot', view.section),
              table(['Keterangan', 'Berat'], balance, [135 * mm, 39 * mm]),
              Spacer(1, 2 * mm),
              p('Susut pengeringan, sekam & susut proses tidak diukur terpisah. Bobot selama proses berlangsung belum final.', view.small)]
    if data['bekatul']:
        story += [p('Bekatul per proses sosoh', view.section),
                  p('Informasi hasil proses. Pengambilan hanya dihitung pada bagian Pengambilan hasil.', view.small),
                  Spacer(1, 2 * mm),
                  table(['Proses', 'Berat'],
                        [[r['kode'], kg_rinci(r['kg'])] for r in data['bekatul']],
                        [127 * mm, 39 * mm], numbered=True)]
    return view.pdf(story, judul=JUDUL_REKAP, referensi=data['kode'])
