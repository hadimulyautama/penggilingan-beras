"""Laporan aktivitas per tahap; tanggal transaksi, bukan tanggal entri ulang.

Satu tahap berdiri sendiri: penerimaan dan transfer tidak dijumlah menjadi
produksi baru. Bobot kosong tetap belum tercatat, bukan dianggap nol.
"""
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import DateTime, select
from app import models as m
from app.config import settings

# Nama kolom dinyatakan di sini agar bobot sisa stok tidak tersamar sebagai
# hasil periode. Pengeringan dan sosoh hanya menghitung proses yang dimulai.
TAHAP = {
    "gabah_masuk": ("Penerimaan gabah", m.PurchaseBatch, "tanggal_pembelian", "kode_batch", "status_batch", "berat_total_kg", "Bobot masuk"),
    "pk_masuk": ("Penerimaan PK luar", m.PkPurchaseBatch, "tanggal_pembelian", "kode_batch", "status_batch", "berat_total_kg", "Bobot masuk"),
    "pengeringan": ("Pengeringan", m.DryingLot, "waktu_mulai_pengeringan", "kode_lot", "status", None, None),
    "penggilingan": ("Penggilingan", m.MillingProcess, "waktu_mulai", "kode_proses", "status", "berat_gabah_masuk_kg", "Gabah masuk proses"),
    "penyosohan": ("Penyosohan", m.PolishingProcess, "waktu_mulai", "kode_proses", "status", None, None),
    "transfer_pk": ("Transfer PK", m.InternalTransfer, "waktu", "kode_transfer", "status", "berat_kg", "Bobot transfer"),
    "pemasukan_pk": ("Pemasukan PK Gudang 2", m.PkGudang2Intake, "tanggal_masuk", None, None, "berat_kg", "Bobot masuk Gudang 2"),
    "pindah_pk": ("Pindah PK ke silo", m.PkTumpukanToSilo, "tanggal", "kode_pindah", None, "berat_timbang_kg", "Bobot timbang"),
    "pengemasan": ("Pengemasan", m.FinishedGoodsStock, "waktu", None, None, "berat_total_kg", "Bobot batch tercatat"),
    "kemas_ulang": ("Kemas ulang", m.KemasUlang, "waktu", None, None, "berat_baru_kg", "Bobot kemasan baru"),
    "barang_keluar": ("Barang keluar", m.OutgoingRecord, "tanggal", "kode", "status", None, None),
    "retur_pelanggan": ("Retur pelanggan", m.CustomerReturn, "waktu", "kode", None, "berat_rincian_kg", "Bobot diterima"),
    "retur_pk": ("Retur PK pemasok", m.PkRejection, "tanggal", "kode", None, "berat_kg", "Bobot dikembalikan"),
}


def kueri(kode, dari, sampai):
    _, model, tanggal, identitas, status, bobot, _ = TAHAP[kode]
    kolom = [model.id, getattr(model, tanggal)]
    nama = ["id", "tanggal"]
    for label, atribut in (("kode", identitas), ("status", status), ("bobot", bobot),
                           ("jasa_id", "jasa_id" if hasattr(model, "jasa_id") else None)):
        if atribut:
            kolom.append(getattr(model, atribut).label(label))
            nama.append(label)
    if hasattr(model, "timbangan_transaksi_id"):
        kolom.append(model.timbangan_transaksi_id.label("tiket_id"))
        nama.append("tiket_id")
    waktu = getattr(model, tanggal)
    if isinstance(waktu.type, DateTime):
        zona = ZoneInfo(settings.app_timezone)
        awal = datetime.combine(dari, time.min, zona)
        akhir = datetime.combine(sampai + timedelta(days=1), time.min, zona)
        batas = (waktu >= awal, waktu < akhir)
    else:
        batas = (waktu >= dari, waktu <= sampai)
    q = select(*kolom).where(*batas)
    if status:
        q = q.where(getattr(model, status).notin_(("batal", "dibatalkan", "ditolak")))
    if kode == "pengemasan":
        q = q.where(model.source_type == "polishing", model.jumlah_karung > 0)
    return q.order_by(waktu, model.id), nama


def susun(kode, dari, sampai, baris):
    judul, _, tanggal, _, _, bobot, label = TAHAP[kode]
    lines = [f"📋 {judul}:", f"Periode: {dari:%d/%m/%Y} s/d {sampai:%d/%m/%Y}",
             f"Dasar periode: {tanggal.replace('_', ' ')}.",
             f"• Jumlah transaksi: {len(baris)}"]
    if bobot:
        total = sum((Decimal(str(r["bobot"])) for r in baris if r["bobot"] is not None), Decimal(0))
        kosong = sum(r["bobot"] is None for r in baris)
        lines.append(f"• {label}: {total:,.2f} kg")
        if kosong:
            lines.append(f"• Bobot belum tercatat: {kosong} transaksi")
    if baris and "jasa_id" in baris[0]:
        jasa = sum(r["jasa_id"] is not None for r in baris)
        lines.extend((f"• Milik pabrik: {len(baris)-jasa} transaksi", f"• Milik jasa: {jasa} transaksi"))
    if kode in ("pengeringan", "penggilingan", "penyosohan"):
        lines.append("Proses dikelompokkan berdasarkan waktu mulai; status adalah keadaan saat laporan dibuka.")
    if kode == "pengemasan":
        lines.append("Batch hasil sosoh berkarung yang masih tercatat; perubahan kemas ulang dapat mengubah bobot batch lama. Bukan rekonstruksi hasil kemas historis.")
    if kode == "barang_keluar":
        lines.append("Mencakup perintah, dimuat, dan selesai; perintah belum menjadi bukti pengeluaran aktual.")
    if not baris:
        lines.append("Tidak ada transaksi pada periode ini.")
    else:
        lines.append("📋 Rincian:")
        for r in baris:
            t = r["tanggal"]
            if isinstance(t, datetime) and t.tzinfo:
                t = t.astimezone(ZoneInfo(settings.app_timezone))
            isi = [str(r.get("kode") or f"#{r['id']}"), t.strftime("%d/%m/%Y")]
            if "status" in r:
                isi.append(r["status"].replace("_", " "))
            if "jasa_id" in r:
                isi.append(f"Jasa #{r['jasa_id']}" if r["jasa_id"] is not None else "Pabrik")
            if bobot:
                isi.append(f"{r['bobot']:,.2f} kg" if r["bobot"] is not None else "bobot belum tercatat")
            lines.append("• " + " · ".join(isi))
    return "\n".join(lines)


async def buat(db, kode, dari, sampai):
    q, nama = kueri(kode, dari, sampai)
    hasil = (await db.execute(q)).all()
    return susun(kode, dari, sampai, [dict(zip(nama, r)) for r in hasil])


def data_laporan(kode, dari, sampai, baris):
    """Satu cuplikan untuk layar dan pembuat PDF, tanpa angka uang."""
    from collections import Counter
    from app.web.pdf_proses import angka

    judul, _, tanggal, _, _, bobot, label = TAHAP[kode]
    rincian = []
    for r in baris:
        t = r['tanggal']
        if isinstance(t, datetime) and t.tzinfo:
            t = t.astimezone(ZoneInfo(settings.app_timezone))
        rincian.append(dict(
            kode=str(r.get('kode') or f"#{r['id']}"), tanggal=t.strftime('%d/%m/%Y'),
            status=(r.get('status') or '-').replace('_', ' '),
            pemilik=(f"Jasa #{r['jasa_id']}" if r['jasa_id'] is not None else 'Pabrik') if 'jasa_id' in r else 'Lihat transaksi asal',
            bobot=angka(r['bobot']) + ' kg' if bobot and r['bobot'] is not None else 'Belum tercatat' if bobot else '-',
            nota=angka(r.get('nota')) + ' kg' if r.get('nota') is not None else 'Belum tercatat',
            timbangan=angka(r.get('timbangan')) + ' kg' if r.get('timbangan') is not None else 'Belum tercatat',
            selisih=angka(r['nota']-r['timbangan']) + ' kg' if r.get('nota') is not None and r.get('timbangan') is not None else 'Belum dapat dihitung',
            sumber_nota='Mengikuti timbangan' if r.get('nota_mengikuti_timbangan') else 'Nota' if r.get('nota') is not None else '',
            tiket=r.get('kode_tiket') or '-',
        ))
    ringkasan = [dict(nama='Jumlah transaksi', nilai=str(len(baris)))]
    if bobot:
        total = sum((Decimal(str(r['bobot'])) for r in baris if r['bobot'] is not None), Decimal(0))
        ringkasan.append(dict(nama=label, nilai=angka(total) + ' kg'))
        kosong = sum(r['bobot'] is None for r in baris)
        if kosong:
            ringkasan.append(dict(nama='Bobot belum tercatat', nilai=f'{kosong} transaksi'))
    if baris and 'jasa_id' in baris[0]:
        jasa = sum(r['jasa_id'] is not None for r in baris)
        ringkasan.extend([dict(nama='Milik pabrik', nilai=f'{len(baris)-jasa} transaksi'),
                          dict(nama='Milik jasa', nilai=f'{jasa} transaksi')])
    # Satu armada bisa menaut beberapa perintah; ringkasan bobot tiket
    # dihitung sekali, sementara tiap rincian tetap menyebut tiket yang sama.
    tiket_unik = {r['tiket_id']: r for r in baris if r.get('tiket_id') is not None}
    if tiket_unik:
        for key, label_tiket in [('nota', 'Bobot menurut nota'), ('timbangan', 'Bobot menurut timbangan')]:
            values = [r[key] for r in tiket_unik.values() if r.get(key) is not None]
            ringkasan.append(dict(nama=label_tiket, nilai=angka(sum(values, Decimal(0))) + ' kg' if values else 'Belum tercatat'))
    status = Counter(r['status'] for r in rincian if r['status'] != '-')
    catatan = ['Transaksi batal dan penerimaan ditolak tidak disertakan. Status mengikuti keadaan saat laporan dibuka.']
    catatan.append('Bobot nota mengikuti timbangan bila nota tidak tersedia. Bobot timbangan adalah bobot barang setelah tara; netto dipakai sebagai cadangan tiket lama. Selisih = nota dikurangi timbangan. Bobot tiket bersama hanya dijumlah sekali dalam ringkasan.')
    if kode in ('pengeringan', 'penggilingan', 'penyosohan'):
        catatan.append('Periode mengikuti waktu mulai proses; proses yang mulai sebelumnya tidak disertakan. Laporan ini adalah aktivitas proses, bukan rekap output mesin per tanggal.')
    if kode == 'pengemasan':
        catatan.append('Bobot batch hasil sosoh berkarung yang masih tercatat. Kemas ulang dapat mengubah batch lama; angka ini bukan rekonstruksi pengemasan historis.')
    if kode == 'barang_keluar':
        catatan.append('Perintah belum membuktikan pengeluaran aktual. Perintah, dimuat, dan selesai ditampilkan terpisah melalui status.')
    from app.services.laporan_isi_tahap import atur
    return atur(dict(kode=kode, nama=judul, dari=dari.isoformat(), sampai=sampai.isoformat(),
                periode=f'{dari:%d/%m/%Y} - {sampai:%d/%m/%Y}',
                dasar=tanggal.replace('_', ' '),
                ringkasan=ringkasan, status=[dict(nama=k, nilai=str(v)) for k,v in sorted(status.items())],
                rincian=rincian, catatan=catatan), kode, baris)


async def ambil(db, kode, dari, sampai):
    q, nama = kueri(kode, dari, sampai)
    rows = (await db.execute(q)).all()
    baris = [dict(zip(nama, r)) for r in rows]
    if kode in ('gabah_masuk','pk_masuk','barang_keluar'):
        await lengkapi_bobot_tiket(db, baris)
    from app.services.laporan_isi_tahap import lengkapi
    await lengkapi(db,kode,baris)
    return data_laporan(kode, dari, sampai, baris)


async def lengkapi_bobot_tiket(db, baris):
    """Baca nota dan hasil alat terpisah; bobot efektif produksi bukan nota.

    Pengukuran pertama truk belum menghasilkan bobot barang. Karena itu
    hasil timbangan baru dibuka setelah timbang kedua tersedia. Pembaca ini
    tidak menyinkronkan atau mengubah transaksi apa pun.
    """
    from sqlalchemy import bindparam, text
    from app.penggilingan.gudang1.services.timbang_link import SQL_REAL_TIKET
    ids = sorted({r['tiket_id'] for r in baris if r.get('tiket_id') is not None})
    if not ids:
        return
    q = text(f"""SELECT t.id, t.kode, NULLIF(t.berat_acuan_kg, 0) AS nota,
                      CASE WHEN t.timbang2_kg IS NOT NULL
                           THEN NULLIF({SQL_REAL_TIKET}, 0) END AS timbangan
                 FROM timbangan_transaksi t WHERE t.id IN :ids""").bindparams(bindparam('ids', expanding=True))
    tickets = {r['id']: r for r in (await db.execute(q, {'ids':ids})).mappings()}
    for r in baris:
        t = tickets.get(r.get('tiket_id'))
        if t is None:
            continue
        timbang = Decimal(str(t['timbangan'])) if t['timbangan'] is not None else None
        nota = Decimal(str(t['nota'])) if t['nota'] is not None else None
        r.update(nota=nota if nota is not None else timbang, timbangan=timbang,
                 nota_mengikuti_timbangan=nota is None and timbang is not None,
                 kode_tiket=t['kode'])
