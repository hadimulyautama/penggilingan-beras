"""Penyajian laporan proses: angka utuh, waktu, dan audit tanpa mutasi."""
from app.services.bahan_silo import kg_rinci


def angka(n):
    return kg_rinci(n).removesuffix(' kg') if n is not None else 'Belum dicatat'


def persen(n, digits=1):
    return f'{float(n):.{digits}f}%'.replace('.', ',') if n is not None else 'Belum dapat dihitung'


def teks_angka(value):
    import re
    return re.sub(r'(?<=\d)\.(?=\d+%)', ',', str(value))


def durasi(detik):
    detik = max(0, int(detik))
    if detik < 60:
        return f'{detik} detik'
    hari, sisa = divmod(detik, 86400)
    jam, sisa = divmod(sisa, 3600)
    menit = sisa // 60
    return ' '.join(([f'{hari} hari'] if hari else []) + ([f'{jam} jam'] if jam else []) + ([f'{menit} menit'] if menit else []))


def laju_kadar_air(awal, kini, waktu_awal, waktu_kini):
    """Tampilkan pengamatan nyata; jangan ekstrapolasi hitungan detik ke per jam."""
    if awal is None or kini is None or not waktu_awal or not waktu_kini:
        return 'Belum dapat dihitung'
    detik = (waktu_kini - waktu_awal).total_seconds()
    if detik <= 0:
        return 'Belum dapat dihitung'
    delta = float(awal) - float(kini)
    arah = 'Turun' if delta >= 0 else 'Naik'
    perubahan = f'{abs(delta):.2f}'.replace('.', ',')
    amatan = f'{arah} {perubahan} poin dalam {durasi(detik)}'
    if detik < 3600:
        return amatan + ' (belum 1 jam)'
    laju = f'{abs(delta) * 3600 / detik:.2f}'.replace('.', ',')
    return f'{arah} {laju} poin persentase/jam · selang {durasi(detik)}'


async def jeda_laporan(db, *, jenis, id_, mulai, selesai):
    from app.services.riwayat_jeda import riwayat_jeda
    from app.models import JedaProses
    from app.penggilingan.gudang1.services.jeda import _kolom
    from sqlalchemy import select
    data = await riwayat_jeda(db, jenis=jenis, id_=id_, semua=True)
    total = max(0, (selesai - mulai).total_seconds()) if mulai and selesai else None
    intervals = []
    if total is not None:
        for j in (await db.scalars(select(JedaProses).where(_kolom(jenis)==id_, JedaProses.dibatalkan_pada.is_(None)))).all():
            a, b = max(mulai, j.mulai), min(selesai, j.selesai or selesai)
            if b > a:
                intervals.append((a, b))
    merged = []
    for a, b in sorted(intervals):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    tertahan = sum((b-a).total_seconds() for a,b in merged)
    data.update(kalender=durasi(total) if total is not None else 'Belum tercatat',
                tertahan=durasi(tertahan), efektif=durasi(total-tertahan) if total is not None else 'Belum tercatat')
    return data


def bagian_jeda(story, data, p, grid, style):
    from reportlab.lib.units import mm
    if not data:
        return
    story.append(p('Durasi dan riwayat jeda', style))
    story.append(grid([['Durasi kalender', 'Total jeda', 'Durasi efektif'],
                       [data['kalender'], data['tertahan'], data['efektif']]], [56*mm, 56*mm, 56*mm]))
    rows = [['Kejadian / petugas', 'Waktu kejadian / pencatatan', 'Sebab / catatan']]
    for e in data['items']:
        rows.append([e['aksi'] + (' · Dibatalkan' if e['dibatalkan'] else '') + ' · ' + e['petugas'],
                     e['waktu'] + ' · Dicatat: ' + e['dicatat'],
                     e['sebab'] + (' · ' + e['catatan'] if e['catatan'] else '') + (' · Alasan terlambat: ' + e['alasan'] if e['alasan'] else '')])
    if len(rows)==1:
        rows.append(['Tidak ada jeda tercatat', '—', '—'])
    story.append(grid(rows, [56*mm, 56*mm, 56*mm]))


def bagian_silo(story, groups, p, grid, style):
    from reportlab.lib.units import mm
    if not groups:
        return
    def nilai(label, text):
        return 'Kosong' if label=='Sisa akhir' and text=='0 kg' else 'Tanpa tambahan' if label=='Tambahan' and text=='0 kg' else text
    silos = {}
    for g in groups:
        silos.setdefault(g['nama'], []).append(g)
    rows = [['Silo', 'Total masuk', 'Tambahan', 'Sisa terakhir', 'Status']]
    details = [['Silo / catatan', 'Awal', 'Tambahan', 'Sisa', 'Terpakai', 'Status']]
    for nama, uses in sorted(silos.items()):
        last = uses[-1]
        a = dict(last['angka'])
        total = sum(g['total_kg'] for g in uses) if all(g['total_kg'] is not None for g in uses) else None
        tambahan = sum(g['tambahan_kg'] for g in uses) if all(g['tambahan_kg'] is not None for g in uses) else None
        rows.append([nama, angka(total)+' kg' if total is not None else 'Belum diketahui',
                     'Tidak dipisahkan' if tambahan is None else 'Tanpa tambahan' if tambahan==0 else '+'+angka(tambahan)+' kg',
                     nilai('Sisa akhir',last.get('ringkasan_sisa',a.get('Sisa akhir','Belum dicatat'))),
                     last.get('ringkasan_status',last['status'])])
        for i,g in enumerate(uses,1):
            a=dict(g['angka'])
            details.append([nama+' · '+str(i),a.get('Awal','Belum diketahui'),nilai('Tambahan',a.get('Tambahan','Tidak dipisahkan')),
                            nilai('Sisa akhir',a.get('Sisa akhir','Belum dicatat')),a.get('Terpakai','Belum tercatat'),g['status']])
    story.append(p('Bahan & pemakaian silo', style))
    story.append(grid(rows,[34*mm,34*mm,34*mm,32*mm,34*mm]))
    story.append(p('Riwayat tiap pemakaian / catatan sumber', style))
    story.append(grid(details,[34*mm,27*mm,27*mm,27*mm,27*mm,26*mm]))
