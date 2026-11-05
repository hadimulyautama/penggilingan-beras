"""Daftar bertiket: saring/hitung di PostgreSQL, hidrasi hanya satu halaman.

Tidak menerima barang, mengubah saldo, atau menentukan izin tindakan. Kartu
halaman tetap dibuat pembaca operasional lama dari tiket yang sudah dibatasi.
"""
from sqlalchemy import text
from app.penggilingan.peta_jenis import PETA_MASUK
from app.penggilingan.gudang1.services import timbang_link as timbang
from app.services import barang_masuk as masuk, berjalan, penerimaan_historis

UKURAN_HALAMAN = 25


def _jenis_sql():
    # Peta yang sama dengan jenis_tiket; kode berasal dari katalog kode,
    # bukan masukan pengguna. Parameter pencarian selalu dibind terpisah.
    pairs = {k: ('gabah_' + v.kondisi if v.model == 'gabah' else 'pk')
             for k, v in PETA_MASUK.items()}
    return "CASE upper(t.jenis_kode) " + ' '.join(
        "WHEN '" + k.replace("'", "''") + "' THEN '" + v + "'" for k, v in pairs.items()) + " ELSE CASE t.jenis_kode WHEN 'BERAS_MASUK' THEN 'beras' WHEN 'BROKEN_MASUK' THEN 'broken' ELSE 'lain' END END"



_JASA = '(coalesce(t.jasa,false) OR t.pelanggan_id IS NOT NULL OR t.jasa_id IS NOT NULL)'
_NAMA = "coalesce(nullif(btrim(coalesce(nullif(p.nama_pelanggan,''),t.pihak_nama,'')),''),'Pelanggan belum tercatat')"
_JOINS = '''LEFT JOIN timbangan_jenis j ON j.kode=t.jenis_kode
 LEFT JOIN suppliers s ON s.id=t.supplier_id
 LEFT JOIN pelanggan p ON p.id=t.pelanggan_id LEFT JOIN jasa ja ON ja.id=t.jasa_id'''


def sumber_diterima(g1, g2, terbatas=False):
    sumber=[]
    specs=[]
    if g1:specs.append(('purchase_batches','timbangan_transaksi_id',"timbangan_transaksi_id IS NOT NULL AND dibatalkan_pada IS NULL",'g1'))
    if g2:
        specs += [('pk_purchase_batches','timbangan_transaksi_id',"timbangan_transaksi_id IS NOT NULL AND dibatalkan_pada IS NULL",'g2'),('finished_goods_stock','source_id',"source_type='timbangan'",'g2'),('byproduct_stock','source_id',"source_type='timbangan'",'g2')]
    for table,tid,where,old in specs:
        lokasi=f"coalesce(warehouse_id,(SELECT id FROM warehouses WHERE kode_fungsi='{old}'))"
        if table=='purchase_batches':
            lokasi="coalesce(warehouse_id,(SELECT warehouse_id FROM dryers WHERE id=purchase_batches.dryer_id),(SELECT d.warehouse_id FROM dryers d JOIN drying_lots dl ON dl.dryer_id=d.id JOIN drying_lot_batches lb ON lb.drying_lot_id=dl.id WHERE lb.purchase_batch_id=purchase_batches.id LIMIT 1),(SELECT id FROM warehouses WHERE kode_fungsi='g1'))"
        if terbatas:where+=' AND '+lokasi+'=:lokasi_id'
        sumber.append(f'SELECT {tid} AS tid,jasa_id,{lokasi} AS warehouse_id FROM {table} WHERE {where}')
    return ' UNION ALL '.join(sumber) or 'SELECT NULL::integer AS tid,NULL::integer AS jasa_id,NULL::integer AS warehouse_id WHERE false'


def dasar_diterima(g1, g2, terbatas=False):
    # Semua catatan pada tiket tetap ikut menentukan pemilik; filter pelanggan
    # memakai EXISTS, bukan memangkas catatan pemilik lain dari tiket staf.
    arsip = ('SELECT * FROM ('+penerimaan_historis.SQL+") old WHERE :lokasi_id=(SELECT id FROM warehouses WHERE kode_fungsi='g2')" if terbatas else penerimaan_historis.SQL) if g2 else 'SELECT NULL::integer AS tid WHERE false'
    return f'''WITH sumber AS ({sumber_diterima(g1,g2,terbatas)}),
 arsip AS ({arsip}),
 kelompok AS (SELECT tid,bool_or(jasa_id IS NULL) AS pabrik,bool_or(jasa_id IS NOT NULL) AS jasa
              FROM sumber GROUP BY tid UNION ALL
 SELECT DISTINCT a.tid,false,false FROM arsip a
 WHERE NOT EXISTS(SELECT 1 FROM sumber src WHERE src.tid=a.tid)),
 dasar AS (SELECT t.id,t.kode,t.nomor_polisi,t.jenis_kode,j.nama AS jenis_nama,
 {_jenis_sql()} AS jenis,
 CASE WHEN {_JASA} THEN {_NAMA} ELSE coalesce(nullif(s.nama_supplier,''),nullif(t.pihak_nama,''),'?') END AS nama,
 CASE WHEN k.pabrik AND k.jasa THEN 'campuran' WHEN k.jasa THEN 'jasa' WHEN k.pabrik THEN 'pabrik' ELSE 'periksa' END AS kepemilikan,
 coalesce((SELECT min(coalesce(w.kode_fungsi,'wh:'||w.id)) FROM sumber src JOIN warehouses w ON w.id=src.warehouse_id WHERE src.tid=t.id),CASE WHEN {_jenis_sql()} LIKE 'gabah_%' THEN 'g1' ELSE 'g2' END) AS gudang,
 concat_ws(' ',t.kode,s.nama_supplier,p.nama_pelanggan,t.pihak_nama,t.nomor_polisi,t.nama_sopir,j.nama,t.jenis_kode,ja.kode) AS cari,
 EXISTS(SELECT 1 FROM sumber src JOIN jasa js ON js.id=src.jasa_id
        WHERE src.tid=t.id AND js.pelanggan_id=:pid) AS pelanggan_cocok
 FROM timbangan_transaksi t JOIN kelompok k ON k.tid=t.id {_JOINS}
 WHERE t.arah='MASUK')'''


def dasar_belum(g1, g2, admin):
    # Pertahankan eligibilitas antrean (termasuk jendela tiket susulan), dan
    # produk hanya bagi peran yang lama memang mendapat kartu produk.
    allowed = []
    if g1: allowed.append("jenis LIKE 'gabah_%'")
    if g2: allowed.append("jenis='pk'")
    if admin: allowed.append("jenis IN ('beras','broken','lain')")
    return f'''WITH tiket AS ({timbang.SQL_MASUK_BELUM_DITAUT}),
 bernama AS (SELECT t.*, {timbang.SQL_BERAT_TIKET} AS berat_cari, {timbang.SQL_SUMBER_BERAT} AS sumber_cari, {_jenis_sql()} AS jenis,
 CASE WHEN {_JASA} THEN 'JASA · ' || CASE WHEN nullif(btrim(ja.kode),'') IS NOT NULL THEN btrim(ja.kode)||' ' ELSE '' END ||
 coalesce(nullif(btrim(coalesce(nullif(p.nama_pelanggan,''),t.pihak_nama,'')),''),'pelanggan')
 ELSE coalesce(nullif(t.nama_supplier,''),nullif(t.pihak_nama,''),'?') END AS nama,
 CASE WHEN {_JASA} THEN 'jasa' ELSE 'pabrik' END AS kepemilikan,
 (t.jasa_id IN (SELECT id FROM jasa WHERE pelanggan_id=:pid)
 OR (t.jasa AND t.pelanggan_id=:pid)) AS pelanggan_cocok
 FROM tiket t LEFT JOIN pelanggan p ON p.id=t.pelanggan_id LEFT JOIN jasa ja ON ja.id=t.jasa_id),
 dasar AS (SELECT bernama.*, coalesce((SELECT coalesce(w.kode_fungsi,'wh:'||w.id) FROM warehouses w WHERE w.id=:lokasi_id),nullif(:gudang,''),CASE WHEN jenis LIKE 'gabah_%' THEN 'g1' WHEN jenis!='lain' THEN 'g2' END) AS gudang,
 concat_ws(' ',kode,nama,jenis_nama,jenis_kode,nomor_polisi,nama_sopir,jasa_kode,
 CASE WHEN kepemilikan='jasa' THEN 'jasa' ELSE 'bukan jasa' END,
 CASE WHEN status_tiket='SELESAI' THEN 'susulan' ELSE '' END,
 CASE WHEN jenis='pk' THEN 'PK luar' ELSE '' END,
 CASE WHEN berat_cari IS NOT NULL THEN replace(to_char(berat_cari,'FM999,999,999,990'),',','.') || ' kg (' || sumber_cari || ')' ELSE '' END,
 CASE WHEN sumber_cari='timbangan' AND coalesce(berat_acuan_kg,0)>0 THEN
 'nota '||replace(to_char(berat_acuan_kg,'FM999,999,999,990'),',','.')||' kg, kurang '||replace(to_char(berat_acuan_kg-berat_cari,'FM999,999,999,990'),',','.')||' kg > batas' ELSE '' END) AS cari
 FROM bernama WHERE {' OR '.join(allowed) or 'false'})'''


def _filter():
    return '''(:jenis='' OR jenis=:jenis)
 AND (:pemilik='' OR kepemilikan IN (:pemilik,'campuran'))
 AND (:gudang='' OR gudang=:gudang) AND (:pid IS NULL OR pelanggan_cocok)'''


def _pola(q):
    return '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


async def daftar(db, *, g1, g2, admin, status, jenis='', pemilik='', gudang='', pid=None,
                 cari='', pemasok='', halaman=1, user=None):
    from app.services import setelan
    tol=await setelan.toleransi_nota_persen(db)
    p = dict(tol_persen=tol,jenis=jenis,pemilik=pemilik,gudang=gudang,pid=pid,
             hari=timbang.HARI_SUSULAN,cari=_pola(cari.strip()),pemasok=pemasok)
    from hmu_identitas import peran as P
    terbatas=user is not None and not P.admin_keatas(user.role)
    p['lokasi_id']=user.default_warehouse_id if terbatas else None
    bases = {'belum':dasar_belum(g1,g2,admin),'diterima':dasar_diterima(g1,g2,terbatas)}
    totals = {}
    for key,base in bases.items():
        totals[key] = await db.scalar(text(base + ' SELECT count(*) FROM dasar WHERE '+_filter()),p)
    base = bases[status]
    # Pilihan nama dari seluruh cakupan filter, tidak dari halaman/kata cari.
    names = list((await db.scalars(text(base + ' SELECT DISTINCT nama FROM dasar WHERE '+_filter()+' ORDER BY nama'),p)).all())
    where = _filter() + " AND (:pemasok='' OR nama=:pemasok) AND cari ILIKE :cari ESCAPE '\\'"
    count = await db.scalar(text(base + ' SELECT count(*) FROM dasar WHERE '+where),p)
    last=max(1,(count+UKURAN_HALAMAN-1)//UKURAN_HALAMAN)
    try: page=min(last,max(1,int(halaman)))
    except (ValueError,TypeError): page=1
    p.update(limit=UKURAN_HALAMAN,offset=(page-1)*UKURAN_HALAMAN)
    order="(status_tiket='TERBUKA') DESC,tanggal DESC,id DESC" if status=='belum' else 'id DESC'
    rows=(await db.execute(text(base+' SELECT * FROM dasar WHERE '+where+' ORDER BY '+order+' LIMIT :limit OFFSET :offset'),p)).all()
    cards=[];history=[];meta={}
    if status=='diterima':
        history=await masuk.riwayat(db,g1=g1,g2=g2,ids_tiket=[r.id for r in rows],user=user)
        arsip=await penerimaan_historis.baca(db,[r.id for r in rows if r.id not in {t['id'] for t in history}]) if g2 else []
        history+=arsip
        history.sort(key=lambda t:t['id'],reverse=True)
    else:
        from app.services.identitas_pekerjaan import lengkapi
        tickets=[timbang._row(r,tol) for r in rows]
        if g1:
            group=await berjalan._tiket_belum_ditaut(db,tiket=tickets)
            for c in group:c.gudang='g1'
            cards+=group
        if g2:
            group=await berjalan._tiket_pk_luar(db,boleh_catat=admin,tiket=tickets)
            for c in group:c.gudang='g2'
            cards+=group
        if admin:
            group=await berjalan._tiket_jenis_tak_dikenal(db,jenis_diizinkan={'BERAS_MASUK','BROKEN_MASUK'},tiket=tickets)
            for c in group:c.gudang='g2'
            cards+=group+await berjalan._tiket_jenis_tak_dikenal(db,tiket=tickets)
        await lengkapi(db,cards)
        rank={r.kode:i for i,r in enumerate(rows)}
        cards.sort(key=lambda c:rank[c.kode])
        meta={r.kode:dict(r._mapping) for r in rows}
        for c in cards:c.gudang=meta.get(c.kode,{}).get('gudang',c.gudang)
    return dict(menunggu=cards,riwayat=history,meta_tiket=meta,nama_saring=names,
                total_belum=totals['belum'],total_diterima=totals['diterima'],
                jumlah=count,halaman=page,halaman_akhir=last)
