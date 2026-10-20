"""Deklarasi skema milik Produksi yang telah dibuat migrasi lintas paket.

Indeks ini milik aplikasi, sehingga tidak ditambahkan ke salinan hmu_core.
Menjaga metadata lengkap mencegah autogenerate mengusulkan penghapusan
indeks dan kolom historis yang masih diperlukan.
"""
from sqlalchemy import Index,DateTime,func,text
from sqlalchemy.orm import mapped_column

def pasang(metadata):
    indeks=[
        ('ix_beras_ke_silo_polishing_process_id','beras_ke_silo',['polishing_process_id'],None),
        ('ix_beras_ke_silo_silo_id','beras_ke_silo',['silo_id'],None),
        ('ix_beras_ke_silo_source','beras_ke_silo',['source_type','source_id'],None),
        ('ix_customer_return_items_return','customer_return_items',['customer_return_id'],None),
        ('ix_hasil_samping_ke_silo_owner_jenis','hasil_samping_ke_silo',['jasa_id','jenis'],None),
        ('ix_internal_transfers_silo','internal_transfers',['silo_id'],None),
        ('ix_jasa_digabung_ke_id','jasa',['digabung_ke_id'],'digabung_ke_id IS NOT NULL'),
        ('ix_outgoing_items_gabah_kering_lot','outgoing_items',['gabah_kering_lot_id'],None),
        ('ix_outgoing_items_jasa','outgoing_items',['jasa_id'],'jasa_id IS NOT NULL'),
        ('ix_outgoing_items_silo','outgoing_items',['silo_id'],None),
        ('ix_outgoing_records_pelanggan_id','outgoing_records',['pelanggan_id'],None),
        ('ix_packaging_losses_pelanggan','packaging_losses',['pelanggan_id'],'pelanggan_id IS NOT NULL'),
        ('ix_packaging_purchases_pelanggan','packaging_purchases',['pelanggan_id'],'pelanggan_id IS NOT NULL'),
        ('ix_pk_purchase_batches_armada_id','pk_purchase_batches',['armada_id'],None),
        ('ix_purchase_batches_armada_id','purchase_batches',['armada_id'],None),
        ('uq_permintaan_pk_hidup','permintaan_pk',['milling_process_id'],"status IN ('diminta','disetujui','dikirim')"),
    ]
    for nama,tabel,kolom,predikat in indeks:
        t=metadata.tables[tabel]
        if any(i.name==nama for i in t.indexes):continue
        opsi=dict(postgresql_where=text(predikat),sqlite_where=text(predikat)) if predikat else {}
        Index(nama,*(t.c[k] for k in kolom),unique=nama.startswith('uq_'),**opsi)
    from hmu_core.proses_db import ArusProsesTerpadu
    for kolom in ('created_at','updated_at'):
        if kolom not in ArusProsesTerpadu.__table__.c:
            setattr(ArusProsesTerpadu,kolom,mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now()))
