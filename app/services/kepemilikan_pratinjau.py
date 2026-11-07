"""Pemeriksaan baca pengalihan lama; pemilik asal selalu diturunkan dari stok."""
import hashlib
import json
from decimal import Decimal
from app.services import kepemilikan as s
from app.penggilingan.inventory import packaging
from app.penggilingan.gudang2.rencana_beras import berat_karung_nyata


def angka(value):
    return format(Decimal(str(value)).normalize(), 'f')


async def periksa(db, *, aksi, req):
    amount=Decimal(str(req.jumlah))
    if not amount.is_finite() or amount<=0:
        raise s.InventoryError('Jumlah harus lebih dari nol.')
    try:
        if aksi=='pindah_kepemilikan_karung':
            material_kode,ukuran,merk=req.karung.split('|')
            material=await packaging.get_material(db,material_kode)
            size=await packaging.get_size(db,int(ukuran))
            brand=await packaging.get_brand(db,merk) if merk else None
            if not material or not size or merk and not brand:raise ValueError()
            kind='karung';identity=dict(material=material.id,size=size.id,brand=brand.id if brand else None)
            owners=[None];destination=int(req.pelanggan)
            if destination<=0:raise ValueError()
        elif aksi=='pindah_kepemilikan_produk':
            prefix,rest=req.item.split(':',1);parts=rest.split('|')
            destination=None
            if prefix=='bj' and len(parts)==3:
                kind='barang';identity=dict(sku=int(parts[0]),std=int(parts[1]) if parts[1] else None);owners=[int(parts[2])]
            elif prefix=='cr' and len(parts)==2 and parts[0] in ('broken','bekatul'):
                kind='curah';identity=dict(jenis=parts[0]);owners=sorted(set(int(x) for x in parts[1].split(',') if x))
            else:raise ValueError()
            if not owners or any(o<=0 for o in owners):raise ValueError()
        else:raise ValueError()
    except (ValueError,TypeError,AttributeError):
        raise s.InventoryError('Pilih stok dan tujuan pengalihan yang sah.')
    unit='lembar' if kind=='karung' else 'karung' if kind=='barang' else 'kg'
    if kind!='curah' and amount!=amount.to_integral_value():raise s.InventoryError('Jumlah karung dan lembar harus bilangan bulat.')
    if kind=='curah' and amount.as_tuple().exponent < -2 and amount!=amount.quantize(Decimal('.01')):raise s.InventoryError('Bobot maksimal dua angka desimal kg.')
    if len(owners)>1 and len(await s.pelanggan_ids(db,kind,owners))!=1:raise s.InventoryError('Pesanan sumber harus milik pelanggan yang sama.')
    names={str(o):await s.pihak(db,o,kind) for o in owners+[destination]}
    before={str(o):{k:angka(v) for k,v in (await s.balance(db,kind,identity,o)).items()} for o in owners+[destination]}
    if amount>sum(Decimal(before[str(o)][unit]) for o in owners):raise s.InventoryError('Jumlah melebihi saldo sumber yang tersedia.')
    candidates=[]
    for o in owners:candidates.extend(await s.free_rows(db,kind,identity,o,allocating=True))
    candidates.sort(key=lambda x:(x[0].tanggal,x[0].waktu,x[0].id) if kind=='karung' else (x[0].waktu,x[0].id))
    after={o:dict(b) for o,b in before.items()};left=amount;weight=Decimal(0)
    for row,available in candidates:
        take=min(left,available)
        if take<=0:continue
        who=str(s.owner(row,kind));w=Decimal(str(berat_karung_nyata(row,int(take)))) if kind=='barang' else take if kind=='curah' else None
        after[who][unit]=angka(Decimal(after[who][unit])-take)
        after[str(destination)][unit]=angka(Decimal(after[str(destination)][unit])+take)
        if kind=='barang':
            after[who]['kg']=angka(Decimal(after[who]['kg'])-w)
            after[str(destination)]['kg']=angka(Decimal(after[str(destination)]['kg'])+w)
        if w is not None:weight+=w
        left-=take
        if left<=0:break
    if left>0:raise s.InventoryError('Bagian stok bebas tidak mencukupi. Periksa pemakaian dan alokasi terbaru.')
    warehouses=await s.warehouse_ids(db,kind,identity,[r for r,_ in candidates])
    description=await s.describe(db,dict(kind=kind,identity=identity,warehouses=warehouses))
    plan=dict(label=description['label'],unit=unit,quantity=angka(amount),kg=None if kind=='karung' else angka(weight),
              owners=[names[str(o)] for o in owners],destination=names[str(destination)],warehouses=description['warehouses'],
              names=names,balances_before=before,balances_after=after,capacity_note=description['capacity_note'])
    evidence=dict(aksi=aksi,identity=identity,owners=owners,destination=destination,plan=plan,
                  sources=[dict(row=s.raw(r),available=angka(n)) for r,n in candidates])
    proof=hashlib.sha256(json.dumps(evidence,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
    return dict(plan=plan,review=proof)


async def pastikan(db, *, aksi, req):
    """Kontrak lama tetap diterima; formulir baru wajib memeriksa ulang data berubah."""
    if req.review is None:return
    if not req.confirm:raise s.InventoryError('Periksa dampak dan konfirmasi pengalihan terlebih dahulu.')
    await s.lock(db)
    latest=await periksa(db,aksi=aksi,req=req)
    if latest['review']!=req.review:raise s.InventoryError('Stok atau pemilik berubah. Kembali ke isian dan periksa dampak terbaru sebelum menyimpan.')
