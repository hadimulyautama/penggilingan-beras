"""Rincian proses aktif. Angka dan tindakan memakai sumber yang sama dengan antrean.

Catatan panjang dibagi per halaman; ringkasan hasil dan nilai QC tetap memakai
SELURUH catatan. Hasil giling kumulatif, sedangkan hasil sosoh per entri.
"""
from __future__ import annotations

from math import ceil
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.config import settings
from app.database import now_local
from app.models import (Dryer, DryingCoolingLog, DryingLot, DryingMoistureLog,
                        JedaProses, MillingProcessSource, MillingProgressLog,
                        MillingQcLog, PurchaseBatch, Silo, SiloStorage, Supplier, User)
from app.penggilingan.gudang2.models import PolishingOutputLog, PolishingSiloUsage
from app.penggilingan.gudang1.services.bobot import dari_batch, dari_batches
from app.services import berjalan as svc
from app.services.jasa import nama_pemilik_banyak
from app.services.mutu_pk import penilaian_dari_log, rincian_kualitatif

JENIS = {"pengeringan": "Pengeringan", "pendinginan": "Pendinginan",
         "giling": "Penggilingan", "sosoh": "Penyosohan"}
SEKALI = 20


def alamat_detail(b):
    jenis = ("sosoh" if b.fase == "sosoh" else "giling" if b.fase == "giling"
             else "pendinginan" if b.fase == "dryer" and b.aksi == "selesai_pendinginan"
             else "pengeringan" if b.fase == "dryer" else None)
    return f"/proses-aktif/{jenis}/{b.kode}" if jenis else None


def _waktu(w):
    if w is None:
        return "Belum tercatat"
    return w.astimezone(ZoneInfo(settings.app_timezone)).strftime("%d/%m/%Y %H:%M")


def _persen(n):
    return f"{float(n):.1f}%".replace(".", ",") if n is not None else "Belum diisi"


def _bagian(judul, kolom, baris, *, keterangan=""):
    return dict(judul=judul, kolom=kolom, baris=baris, keterangan=keterangan,
                jumlah=len(baris), halaman=1, halaman_total=1, parameter=None)


def kelompok_bahan_silo(rows, pemakaian=()):
    """Pertahankan satu kelompok per pemakaian; jangan gabung nama silo ulang."""
    hasil = []
    for r in rows:
        nama, berat, ket = r[:3]
        peran = r[3] if len(r) > 3 else ""
        if peran in ("silo", "dibebaskan"):
            status = ("Dilepaskan pada pemakaian ini · " + ket.split(" · ", 1)[-1]
                      if peran == "dibebaskan" else "Masih terikat proses")
            status = status.replace("kosong, siap diisi", "sisa 0 kg")
            hasil.append(dict(nama=nama, berat=berat, status=status,
                              bahan=[], sumber=[]))
        elif hasil:
            tujuan = "bahan" if peran == "sosoh-bahan" else "sumber"
            hasil[-1][tujuan].append(dict(nama=nama.strip(), berat=berat, ket=ket))
    if pemakaian:
        # Urutan kedua sumber wajib mengikuti ID pemakaian, bukan nama silo.
        # Nama yang sama dapat muncul lagi dengan isi serta sisa berbeda.
        if len(hasil) != len(pemakaian):
            raise ValueError("Rincian pemakaian silo tidak selaras")
        for g, (u, nama) in zip(hasil, pemakaian):
            if g["nama"] != nama:
                raise ValueError("Urutan pemakaian silo tidak selaras")
            from app.services.bahan_silo import kg_rinci
            g["total_kg"] = float(u.berat_awal_kg or 0) + float(u.berat_masuk_kg or 0)
            g["berat"] = kg_rinci(g["total_kg"])
            g["tambahan_kg"] = float(u.berat_masuk_kg or 0)
            g["angka"] = [
                ("Awal", kg_rinci(u.berat_awal_kg)),
                ("Tambahan", kg_rinci(u.berat_masuk_kg)),
                ("Sisa akhir", kg_rinci(u.berat_akhir_kg) if u.berat_akhir_kg is not None else "Belum dicatat"),
                ("Terpakai", kg_rinci(u.berat_terpakai_kg) if u.berat_akhir_kg is not None else "Belum final"),
            ]
    return hasil


async def _log(db, model, fk, pid, waktu, pembuat, judul, kolom, format_baris,
               params, parameter, keterangan=""):
    jumlah = await db.scalar(select(func.count()).select_from(model).where(fk == pid))
    terakhir = max(1, ceil(jumlah / SEKALI))
    try:
        halaman = min(terakhir, max(1, int(params.get(parameter, "1"))))
    except (ValueError, TypeError):
        halaman = 1
    q = (select(model, User.nama).outerjoin(User, User.id == pembuat)
         .where(fk == pid).order_by(waktu.desc(), model.id.desc())
         .offset((halaman - 1) * SEKALI).limit(SEKALI))
    baris = [format_baris(r, nama or "Tidak tercatat") for r, nama in (await db.execute(q)).all()]
    return dict(judul=judul, kolom=kolom, baris=baris, jumlah=jumlah,
                halaman=halaman, halaman_total=terakhir, parameter=parameter,
                keterangan=keterangan)


async def rincian(db, *, jenis, model, kartu, params):
    pemilik = await nama_pemilik_banyak(db, [model.jasa_id])
    pencatat = await db.get(User, model.created_by)
    mulai = (model.waktu_mulai_pengeringan if jenis in ("pengeringan", "pendinginan")
             else model.waktu_mulai)
    awal_fase = (model.waktu_mulai_pendinginan or model.waktu_selesai_pengeringan
                 if jenis == "pendinginan" else mulai)
    jeda_jenis = "penyosohan" if jenis == "sosoh" else "pengeringan" if jenis == "pendinginan" else jenis
    from app.penggilingan.gudang1.services.jeda import tertahan_detik, jeda_terbuka
    tertahan = await tertahan_detik(db, jeda_jenis, model.id)
    macet = await jeda_terbuka(db, jeda_jenis, model.id)
    durasi = max(0, (now_local() - awal_fase).total_seconds()) if awal_fase else 0
    efektif = max(0, durasi - (0 if jenis == "pendinginan" else tertahan))
    d = dict(jenis=jenis, judul=JENIS[jenis], kode=kartu.kode, proses=kartu,
             pemilik=pemilik.get(model.jasa_id, "Pemilik belum tercatat") if model.jasa_id else "Milik pabrik",
             jasa=model.jasa_id is not None, status="Dijeda" if macet and jenis != "pendinginan" else "Sedang berjalan",
             fakta=[("Gudang", "Gudang 2 · Penyosohan" if jenis == "sosoh" else "Gudang 1 · Selepan"),
                    ("Mulai proses", _waktu(mulai)), ("Mulai fase ini", _waktu(awal_fase)),
                    ("Dicatat oleh", pencatat.nama if pencatat else "Tidak tercatat"),
                    ("Waktu berlalu", svc.lama_kata(durasi)),
                    ("Durasi efektif" if jenis != "pendinginan" else "Lama pendinginan", svc.lama_kata(efektif)),
                    ("Total jeda pengeringan" if jenis == "pendinginan" else "Total jeda", svc.lama_kata(tertahan) if tertahan else "Tidak ada jeda")],
             statistik=[], bagian=[], penilaian=None, qc_kosong=None)
    if jenis in ("pengeringan", "pendinginan"):
        from app.penggilingan.gudang1.services.drying import _lot_batches
        batches = await _lot_batches(db, model.id)
        bobot = dari_batches(batches)
        dryer = await db.get(Dryer, model.dryer_id) if model.dryer_id else None
        # Catatan penutupan bisa hanya memuat indikator mesin. Angka alat tes
        # terakhir tetap berasal dari pengukuran yang mengisinya, bukan NULL
        # pada catatan sesudahnya.
        log = await db.scalar(select(DryingMoistureLog).where(
            DryingMoistureLog.drying_lot_id == model.id,
            DryingMoistureLog.kadar_air_tes_manual.is_not(None)
        ).order_by(DryingMoistureLog.waktu_update.desc(), DryingMoistureLog.id.desc()).limit(1))
        d["fakta"] += [("Mesin pengering", dryer.nama if dryer else "Belum tercatat"),
                       ("Mode dryer", model.mode_dryer or "Belum tercatat"),
                       ("Berat bahan", bobot.teks()),
                       ("Waktu ukur terakhir · alat tes", _waktu(log.waktu_update) if log else "Belum diukur"),
                       ("Selesai pengeringan", _waktu(model.waktu_selesai_pengeringan))]
        d["statistik"] = [("Bahan dalam lot", bobot.teks()),
                          ("Kadar air terakhir · alat tes", _persen(log.kadar_air_tes_manual) if log else "Belum diukur"),
                          ("Target kadar air", next((v for k, v in kartu.fakta if k == "Target"), _persen(model.target_kadar_air)))]
        d["bagian"].append(await _bahan_gabah(db, batches))
        d["bagian"].append(await _log(
            db, DryingMoistureLog, DryingMoistureLog.drying_lot_id, model.id,
            DryingMoistureLog.waktu_update, DryingMoistureLog.input_by,
            "Riwayat pengukuran kadar air", ["Waktu", "Alat tes rata-rata", "Empat sampel alat tes", "Indikator mesin", "Pencatat"],
            lambda r, nama: [_waktu(r.waktu_update), _persen(r.kadar_air_tes_manual),
                            " · ".join(_persen(getattr(r, f"kadar_air_tes_{i}")) for i in range(1, 5)),
                            _persen(r.kadar_air_indikator), nama], params, "halaman_ukur"))
        d["bagian"].append(await _log(
            db, DryingCoolingLog, DryingCoolingLog.drying_lot_id, model.id,
            DryingCoolingLog.waktu, DryingCoolingLog.input_by,
            "Catatan pendinginan", ["Waktu", "Catatan", "Pencatat"],
            lambda r, nama: [_waktu(r.waktu), r.catatan or "Pendinginan dicatat", nama],
            params, "halaman_dingin"))
    elif jenis == "giling":
        from app.penggilingan.gudang1.services.milling import _latest_progress
        hasil = await _latest_progress(db, model.id)
        bahan = model.berat_gabah_masuk_kg
        d["statistik"] = [("Gabah masuk", svc._kg(bahan) + (" · belum final" if not model.bobot_masuk_final else "") if bahan is not None else "Belum diketahui"),
                          ("Hasil PK kumulatif", svc._kg(hasil) if hasil is not None else "Belum dicatat"),
                          ("Rendemen sementara", _persen(float(hasil) / float(bahan) * 100) if bahan and hasil is not None else "Belum dapat dihitung")]
        sumber = (await db.execute(select(MillingProcessSource, Silo.nama_silo)
                  .join(SiloStorage, SiloStorage.id == MillingProcessSource.silo_storage_id)
                  .join(Silo, Silo.id == SiloStorage.silo_id)
                  .where(MillingProcessSource.milling_process_id == model.id)
                  .order_by(MillingProcessSource.id))).all()
        batches, ids = [], set()
        rows = []
        for s, silo in sumber:
            asal = await db.get(DryingLot, s.drying_lot_id) if s.drying_lot_id else await db.get(PurchaseBatch, s.purchase_batch_id) if s.purchase_batch_id else None
            rows.append([silo, getattr(asal, "kode_lot", None) or getattr(asal, "kode_batch", None) or "Asal belum tercatat",
                         svc._kg(s.berat_kg) if s.berat_kg is not None else "Belum diketahui",
                         "Masih terikat proses" if s.berat_akhir_kg is None else f"Dibebaskan · sisa {svc._kg(s.berat_akhir_kg)}"])
            if s.drying_lot_id:
                from app.penggilingan.gudang1.services.drying import _lot_batches
                kandidat = await _lot_batches(db, s.drying_lot_id)
            else:
                kandidat = [asal] if asal else []
            for b in kandidat:
                if b.id not in ids:
                    ids.add(b.id)
                    batches.append(b)
        if not sumber:
            # Proses warisan belum memiliki tabel sumber; jangan menghilangkan asalnya.
            silo = await db.get(Silo, model.silo_id)
            rows.append([silo.nama_silo if silo else "Silo tidak tercatat", "Data proses lama", d["statistik"][0][1], "Rincian sumber belum tersedia"])
            if model.drying_lot_id:
                from app.penggilingan.gudang1.services.drying import _lot_batches
                batches = await _lot_batches(db, model.drying_lot_id)
            elif model.purchase_batch_id:
                b = await db.get(PurchaseBatch, model.purchase_batch_id)
                batches = [b] if b else []
        from app.services.bahan_silo import sumber_giling_banyak
        kelompok = (await sumber_giling_banyak(db, [model.id])).get(model.id, [])
        if kelompok:
            bagian = _bagian("Bahan & pemakaian silo", [], [])
            bagian.update(kelompok_silo=kelompok, jumlah=len(kelompok), satuan="catatan sumber")
            d["bagian"].append(bagian)
        else:
            d["bagian"].append(_bagian("Sumber bahan per silo", ["Silo", "Asal bahan", "Berat masuk", "Status sumber"], rows,
                                     keterangan="Data proses lama: rincian pemakaian silo belum tersedia."))
        d["bagian"].append(await _bahan_gabah(db, batches))
        d["bagian"].append(await _log(
            db, MillingProgressLog, MillingProgressLog.milling_process_id, model.id,
            MillingProgressLog.waktu_update, MillingProgressLog.input_by,
            "Riwayat hasil giling", ["Waktu", "PK kumulatif", "Pencatat"],
            lambda r, nama: [_waktu(r.waktu_update), svc._kg(r.berat_kumulatif_kg), nama], params, "halaman_hasil",
            "Setiap baris adalah total PK sejak awal proses. Baris-baris ini tidak dijumlahkan; ringkasan mengikuti catatan terbaru."))
        qc = list((await db.scalars(select(MillingQcLog).where(MillingQcLog.milling_process_id == model.id).order_by(MillingQcLog.waktu, MillingQcLog.id))).all())
        d["penilaian"] = penilaian_dari_log(qc)
        nomor = {q.id: i + 1 for i, q in enumerate(qc)}
        d["bagian"].append(await _log(
            db, MillingQcLog, MillingQcLog.milling_process_id, model.id,
            MillingQcLog.waktu, MillingQcLog.input_by,
            "Riwayat QC hasil PK", ["Putaran / waktu", "Hasil pemeriksaan", "Nilai kualitas", "Kondisi / catatan lab", "Pencatat"],
            lambda r, nama: [f"QC {nomor[r.id]} · {_waktu(r.waktu)}",
                " · ".join([f"Kadar air {_persen(r.kadar_air)}", f"Butir patah {_persen(r.broken_persen)}", f"Susut {_persen(r.susut_persen)}"] +
                           [f"{k}: {v}" for k, v in rincian_kualitatif(r, termasuk_kosong=True)]),
                _nilai_qc(r), " · ".join(x for x in (r.kondisi, r.catatan_lab) if x) or "Belum diisi", nama], params, "halaman_qc"))
    else:
        d["statistik"] = [("Total bahan proses", svc._kg(kartu.neraca.bahan_kg) if kartu.neraca else "Belum diketahui"),
                          ("Hasil beras sementara", svc._kg(kartu.neraca.beras.kg) if kartu.neraca else "Belum dicatat"),
                          ("Rendemen beras sementara", _persen(kartu.neraca.beras.persen) if kartu.neraca else "Belum dapat dihitung")]
        d["fakta"] += kartu.fakta
        silos = (await db.execute(select(PolishingSiloUsage, Silo.nama_silo).join(Silo, Silo.id == PolishingSiloUsage.silo_id)
                 .where(PolishingSiloUsage.polishing_process_id == model.id).order_by(PolishingSiloUsage.id))).all()
        for judul, rows in kartu.anak_grup:
            if judul == "Bahan baku masuk per silo":
                kelompok = kelompok_bahan_silo(rows, silos)
                bagian = _bagian("Bahan & pemakaian silo", [], [])
                bagian.update(kelompok_silo=kelompok, jumlah=len(kelompok))
                d["bagian"].append(bagian)
            else:
                d["bagian"].append(_bagian(judul, ["Rincian", "Berat", "Keterangan"],
                                          [[r[0].strip(), r[1] or "—", r[2] or "—"] for r in rows]))
        d["bagian"].append(await _log(
            db, PolishingOutputLog, PolishingOutputLog.polishing_process_id, model.id,
            PolishingOutputLog.waktu_update, PolishingOutputLog.input_by,
            "Riwayat pencatatan hasil sosoh", ["Waktu", "Jenis hasil", "Spek", "Pertambahan hasil", "Pencatat"],
            lambda r, nama: [_waktu(r.waktu_update), r.jenis.replace("_", " ").title(), r.spek or "Belum diisi", svc._kg(r.berat_kg), nama],
            params, "halaman_hasil", "Formulir menggunakan total kumulatif per jenis hasil sejak awal proses. Riwayat ini menampilkan pertambahan hasil dari setiap pembaruan total: dari 300 kg menjadi 500 kg, pertambahannya 200 kg. Angka masih sementara sampai proses ditutup."))
        d["qc_kosong"] = "Pencatatan QC beras hasil sosoh belum tersedia. Catatan hasil di atas adalah hasil produksi, bukan pengukuran QC."
    from app.services.riwayat_jeda import riwayat_jeda
    d["jeda_riwayat"] = await riwayat_jeda(db, jenis=jeda_jenis, id_=model.id, params=params)
    return d


def _nilai_qc(r):
    p = penilaian_dari_log([r])
    return (f"{p['nilai']:.2f} / 100 · {p['kelas']} · {p['n']}/6 komponen".replace(".", ",")
            if p["nilai"] is not None else "Belum dapat dinilai")


async def _bahan_gabah(db, batches):
    suppliers = {s.id: s.nama_supplier for s in (await db.scalars(
        select(Supplier).where(Supplier.id.in_({b.supplier_id for b in batches if b.supplier_id})))).all()}
    owners = await nama_pemilik_banyak(db, [b.jasa_id for b in batches])
    tickets = await svc._metadata_tiket(db, [b.timbangan_transaksi_id for b in batches])
    return _bagian("Asal bahan gabah", ["Kode batch", "Pemasok / pemilik", "Kondisi / berat batch", "Tiket timbang", "Masuk / kendaraan"],
                   [[b.kode_batch, owners.get(b.jasa_id, "Pemilik belum tercatat") if b.jasa_id else suppliers.get(b.supplier_id, "Pemasok belum tercatat"),
                     f"{b.kondisi_gabah} · {dari_batch(b).teks()}",
                     tickets.get(b.timbangan_transaksi_id, {}).get("kode") or "Tidak tertaut tiket",
                     f"{_waktu(b.waktu_pembelian)} · {b.no_polisi_truk or tickets.get(b.timbangan_transaksi_id, {}).get('nomor_polisi') or 'Nopol belum tercatat'}"] for b in batches],
                   keterangan="Berat ini adalah berat batch asal, bukan pembagian sisa per batch di dalam silo.")
