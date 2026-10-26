"""Pratinjau baca saja. Tidak menjalankan pemindahan lalu melakukan rollback.

Alokasi per pemilik berasal dari bagian baca layanan lama; angka sumber
mesin memakai pembukuan domain, bukan total global atau angka tampilan.
"""
from sqlalchemy import select
from app.models import (ByproductStock,FinishedGoodsStock,ProductSku,PackageSize,
                        PolishingProcess,PolishingSiloUsage)
from app.penggilingan.gudang2 import service as g2


def urai(value):
    a,_,b=str(value or '').strip().partition('|')
    if not a:raise ValueError('Pilih pemilik stok broken.')
    if a=='pemilik':
        if b!='pabrik' and not b.isdigit():raise ValueError('Pemilik stok tidak sah.')
        return None,None if b=='pabrik' else int(b)
    return a,int(b) if b.isdigit() else None


async def rincian(db,pilihan,berat=None,silo=''):
    from app.services.jasa import nama_pemilik,pemilik_hasil_proses
    from app.services.stok import output_sosoh
    from app.penggilingan.inventory.finished_goods import _broken_dibukukan
    kode,owner=urai(pilihan)
    def milik(c):return c.is_(None) if owner is None else c==owner
    if kode:
        proc=await db.scalar(select(PolishingProcess).where(PolishingProcess.kode_proses==kode))
        if proc is None:raise ValueError('Proses sumber tidak ditemukan.')
        direct=[];procs=[(proc,None)]
    else:
        direct,procs,_=await g2.rencana_broken_pemilik(db,jasa_id=owner,berat_kg=None)
    rows=[]
    for rid,_ in direct:
        r=await db.get(ByproductStock,rid);avail=await g2._sisa_broken_row(db,rid)
        rows.append(dict(id=rid,kode=f'Penerimaan timbang #{rid}',tipe='timbangan',curah=avail,mesin=0,packs=[],total=avail))
    for proc,_ in procs:
        curah=0;curah_rows=[]
        for rid in (await db.scalars(select(ByproductStock.id).where(ByproductStock.jenis_produk=='broken',ByproductStock.source_type=='polishing',ByproductStock.source_id==proc.id,milik(ByproductStock.jasa_id)).order_by(ByproductStock.waktu,ByproductStock.id))).all():
            w=await g2._sisa_broken_row(db,rid)
            if w>0.5:curah+=w;curah_rows.append(w)
        packs=[]
        for r,ukuran in (await db.execute(select(FinishedGoodsStock,PackageSize.ukuran_kg).join(ProductSku,ProductSku.id==FinishedGoodsStock.product_sku_id).outerjoin(PackageSize,PackageSize.id==ProductSku.package_size_id).where(ProductSku.kategori=='broken',FinishedGoodsStock.source_type=='polishing',FinishedGoodsStock.source_id==proc.id,milik(FinishedGoodsStock.jasa_id)).order_by(FinishedGoodsStock.waktu,FinishedGoodsStock.id))).all():
            packs.append(dict(id=r.id,n=int(r.jumlah_karung or 0),ukuran=float(ukuran) if ukuran else None,kg=float(r.berat_total_kg)))
        mesin=0
        if owner==await pemilik_hasil_proses(db,proc.jasa_id,'broken'):
            mesin=max(0,float((await output_sosoh(db,proc.id)).get('broken') or 0)-await _broken_dibukukan(db,proc.id))
        if mesin<=0.5:mesin=0
        total=curah+mesin+sum(p['kg'] for p in packs)
        if total>0.5:rows.append(dict(id=proc.id,kode=proc.kode_proses,tipe='polishing',curah=curah,curah_rows=curah_rows,mesin=mesin,packs=packs,total=total))
    def saldo(rs):return dict(curah=sum(r['curah']for r in rs),mesin=sum(r['mesin']for r in rs),karung=sum(p['n']for r in rs for p in r['packs']),kemasan=sum(p['kg']for r in rs for p in r['packs']),total=sum(r['total']for r in rs))
    awal=saldo(rows);out=dict(pilihan=pilihan,pemilik=await nama_pemilik(db,owner) if owner else 'Milik pabrik',cakupan=kode or 'Seluruh sumber pemilik',sumber=rows,saldo=awal,rencana=None,pesan='',proses_penerima=[])
    if berat is None:return out
    from app.services.angka import angka_wajar
    want=angka_wajar(berat,'Berat yang masuk silo')
    if want>awal['total']+0.5:raise ValueError(f"Stok broken tersedia {awal['total']:g} kg; tidak cukup untuk {want:g} kg.")
    # Pemilihan lintas sumber selalu memakai rencana FIFO layanan, bukan
    # menghabiskan seluruh curah lintas proses sebelum membuka karung.
    if kode:takes={('polishing',rows[0]['id']):want} if rows else {}
    else:
        dp,pp,left=await g2.rencana_broken_pemilik(db,jasa_id=owner,berat_kg=want)
        if left>0.5:raise ValueError('Saldo telah berubah; periksa ulang sumber terbaru.')
        takes={('timbangan',i):w for i,w in dp};takes.update({('polishing',p.id):w for p,w in pp})
    import copy
    akhir=copy.deepcopy(rows);used=[];uc=um=ub=okg=on=0
    for r in akhir:
        take=takes.get((r['tipe'],r['id']),0)
        if not take:continue
        c=min(r['curah'],take);need=take-c;m=0
        if need>0.5:m=min(r['mesin'],need);need-=m
        opened=0;n=0;detail=[]
        if need>0.5:
            for p in r['packs']:
                if need-opened<=0.5:break
                if not p['ukuran'] or not p['n']:continue
                k=g2.jumlah_bongkar_broken(need-opened,p['ukuran'],p['n']);w=k*p['ukuran']
                opened+=w;n+=k;p['n']-=k;p['kg']-=w;detail.append(dict(karung=k,ukuran=p['ukuran'],kg=w))
            if opened+0.5<need:raise ValueError('Rincian kemasan tidak mencukupi; periksa stok terbaru.')
        # Perulangan pemindahan lama berhenti pada sisa <=0,5 kg.
        # Ambang tetap berlaku per baris, bukan hanya pada total.
        remaining=take;c_used=m_used=bag_use=0
        pool=[('curah',w) for w in r.get('curah_rows',[r['curah']])]
        pool += [('mesin',m),('karung',opened)]
        for kind,w in pool:
            if remaining<=0.5:break
            diambil=min(w,remaining);remaining-=diambil
            if kind=='curah':c_used+=diambil
            elif kind=='mesin':m_used+=diambil
            else:bag_use+=diambil
        c=c_used;actual=take-remaining;extra=max(0,opened-bag_use)
        r['curah']=r['curah']-c+(m-m_used)+extra;r['mesin']-=m;r['total']=r['curah']+r['mesin']+sum(p['kg']for p in r['packs'])
        uc+=c;um+=m_used;ub+=bag_use;okg+=opened;on+=n
        used.append(dict(kode=r['kode'],id=r['id'],tipe=r['tipe'],kg=actual,curah=c,mesin=m_used,mesin_dibukukan=m,isi_karung=bag_use,karung=n,bongkar_kg=opened,kemasan=detail))
    if not used and want>0.5:raise ValueError('Tidak ada stok broken yang dapat digunakan.')
    if silo:
        dest=await g2.get_g2_silo(db,silo)
        if dest:
            q=select(PolishingProcess.kode_proses).join(PolishingSiloUsage).where(
                PolishingSiloUsage.silo_id==dest.id,
                PolishingSiloUsage.berat_akhir_kg.is_(None),PolishingProcess.status=='proses')
            out['proses_penerima']=list((await db.scalars(q)).all())
    out['rencana']=dict(kg=sum(u['kg']for u in used),diminta_kg=want,silo=silo,curah=uc,mesin=um,isi_karung=ub,karung=on,bongkar_kg=okg,kelebihan=max(0,okg-ub),sisa=saldo(akhir),urutan=used)
    return out
