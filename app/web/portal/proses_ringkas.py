"""Proyeksi ringkas proses pelanggan; angka dan kejadian tetap dari pembaca native."""
import re


def angka(teks):
    """Hanya buang nol desimal akhir pada nilai terformat, tanpa membulatkan."""
    if not isinstance(teks,str):return teks
    return re.sub(r'(\d[\d.]*),(\d+)(?=\s*(?:kg|%)(?:$|\s))',
        lambda m:m[1]+(','+m[2].rstrip('0') if m[2].rstrip('0') else ''),teks)


def status_tahap(jenis,status):
    if status!='Sedang berjalan':return status
    return {'pengeringan':'Sedang dikeringkan','pendinginan':'Menunggu dingin',
        'giling':'Sedang digiling','sosoh':'Sedang disosoh','transfer':'Sedang dipindahkan'}.get(jenis,status)


def bobot(rows):
    return [dict(e,ditimbang_pada=waktu_timbang(e),**{k:angka(e.get(k)) for k in ('basah','kering','terukur')}) for e in rows or []]


def waktu_timbang(e):
    """Hanya waktu milik hasil timbang sah; tidak memakai waktu proses/buka."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from app.config import settings
    if not e.get('terukur'):return None
    value=e.get('timbang_waktu')
    try:dt=datetime.fromisoformat(value) if isinstance(value,str) else value
    except ValueError:return None
    if not isinstance(dt,datetime):return None
    return dt if dt.tzinfo else dt.replace(tzinfo=ZoneInfo(settings.app_timezone))


def indikator_hasil(kartu,jenis):
    """Hanya angka untuk visual bersama; tidak membawa aksi atau data aktor."""
    if jenis not in ('giling','sosoh') or kartu is None:return None
    return dict(fase=jenis,aksi=None,
        rendemen_sementara=getattr(kartu,'rendemen_sementara',None),
        neraca=getattr(kartu,'neraca',None))


def siapkan(r):
    """DTO baru saja; tidak mengubah Baris produksi atau dasar estimasi."""
    r['status_tampil']=r.get('status_tampil') or status_tahap(r['jenis'],r['status'])
    fakta=dict(r.get('fakta') or [])
    # Progres native memakai indikator mesin terakhir, bukan alat tes.
    acuan=fakta.get('Acuan progres','').removeprefix('Indikator mesin ')
    r['kadar_air']=acuan or None
    r['target_air']=fakta.get('Target kadar air')
    r['fakta_ringkas']=[(k,angka(v.partition(' · rasio hasil')[0]))
        for k,v in r.get('fakta',[]) if k in ('Bahan masuk','Hasil sementara')]
    if r.get('neraca'):
        from app.services.jasa_pelanggan import kg_rinci
        beras=r['neraca'][0]
        r['fakta_ringkas'].append((beras['nama']+' · sementara',angka(kg_rinci(beras['kg']))))
    if r.get('angka'):r['angka']=(r['angka'][0],angka(r['angka'][1]))
    r['bobot_pengeringan']=bobot(r.get('bobot_pengeringan'))
    return r


def detail(content,r,ctx,env):
    """Ringkasan di depan, catatan sumber dan tab native tetap bisa dibuka."""
    from bs4 import BeautifulSoup
    s=BeautifulSoup(content,'html.parser');root=s.select_one('.pelanggan-detail')
    hero=root.select_one('.riwayat-detail__hero, .rhs-header') if root else None
    if not hero:return content
    baru=BeautifulSoup(env.get_template('portal/_inti_proses_ringkas.html').render(r=r),'html.parser')
    for el in list(baru.contents):hero.insert_before(el.extract())
    hero.decompose()
    if r.get('angka') or r.get('bobot_pengeringan'):
        for grid in root.select('.proses-detail__statistik'):
            first=grid.find('article',recursive=False)
            if first:first.decompose()
            for card in list(grid.find_all('article',recursive=False)):
                label=card.find('span',recursive=False)
                text=label.get_text(' ',strip=True) if label else ''
                if text=='Total hasil giling':label.string='Hasil giling sementara'
                if text.startswith(('Rasio hasil','Rendemen')):
                    fold=s.new_tag('details',attrs={'class':'pelanggan-detail-lipat pelanggan-rasio-hasil'})
                    summary=s.new_tag('summary');summary.string='Perbandingan bahan dan hasil'
                    card.wrap(fold);fold.insert(0,summary)
                    label.string='Persentase hasil sementara'
                    note=s.new_tag('p',attrs={'class':'pelanggan-redup'})
                    note.string='Persentase hasil terhadap bahan, bukan persentase proses selesai.'
                    fold.append(note)
    # Rincian bobot telah diproyeksikan beserta semua keterangan ke ringkasan.
    # Hindari angka ganda dari komponen operator pada tab Ringkasan.
    if r.get('bobot_pengeringan'):
        for el in list(root.select('.bobot-pengeringan')):
            parent=el.parent;el.decompose()
            if parent.name=='section' and not parent.get_text(strip=True):parent.decompose()
    wrapper=s.new_tag('details',attrs={'class':'pelanggan-detail-lipat pelanggan-proses-lanjutan'})
    summary=s.new_tag('summary');summary.string='Bahan dan riwayat'
    wrapper.append(summary)
    catatan=root.select_one('[data-portal-ringkas=catatan]')
    if catatan:wrapper.append(catatan.extract())
    berat=root.select_one('.pelanggan-berat-lanjutan')
    if berat and r['jenis'] in ('giling','sosoh'):
        for grid in list(root.select('.proses-detail__statistik')):berat.append(grid.extract())
    if r.get('tab_aktif') not in (None,'ringkasan'):wrapper['open']=''
    for el in list(root.children):
        if getattr(el,'name',None) and not el.get('data-portal-ringkas') and 'riwayat-detail__back' not in el.get('class',[]):
            wrapper.append(el.extract())
    if len(wrapper.contents)>1:root.append(wrapper)
    root['class']=[*root.get('class',[]),'pelanggan-proses-detail-ringkas']
    return str(s)
