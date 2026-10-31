"""Read-only projection of native templates; query authorization lives upstream.

Jinja's overlay is local to this request. Staff rendering and template globals
are never mutated. Native data, tables, process detail and PDFs remain shared.
"""
import copy
import re
from urllib.parse import urljoin, urlsplit, urlunsplit
from bs4 import BeautifulSoup
from fastapi.responses import HTMLResponse
from jinja2 import ChoiceLoader, DictLoader
from markupsafe import Markup
from .auth import csrf_context
from .navigation import MENU, portal_url, active_menu


def tujuan_kembali(base):
    path=urlsplit(base).path.removeprefix('/pelanggan')
    if path.startswith(('/riwayat-giling','/riwayat-pengeringan','/riwayat-sosoh','/riwayat-transfer')):
        return '/riwayat-proses','Riwayat proses'
    if path.startswith(('/riwayat-qc','/stok','/barang-saya')):return '/barang-saya','Barang Saya'
    if path.startswith('/barang-masuk'):return '/barang-masuk','Barang masuk'
    if path.startswith(('/barang-keluar','/retur')):return '/barang-keluar','Pengambilan barang'
    if '/nota' in path:return '/laporan','Dokumen'
    return '/jasa-saya','Proses Berjalan'


def bahasa_pelanggan(s,base=''):
    """Ubah label antarmuka saja, tanpa menyunting isi catatan atau angka."""
    labels={'Pekerjaan':'Perkembangan proses','Perlu tindakan':'Menunggu petugas',
        'Status & informasi':'Informasi barang','Riwayat QC':'Pemeriksaan mutu',
        'QC':'Pemeriksaan mutu','Audit':'Riwayat perubahan','Kode lot':'Kode proses',
        'Bahan dalam lot':'Bahan dalam proses','Pemilik bahan':'Pelanggan',
        'Bobot belum final':'Berat sementara','Saldo per pelanggan':'Jumlah barang Anda',
        'PK luar':'Bahan masuk (PK)','PK hasil giling':'Hasil giling (PK)',
        'Perintah barang keluar':'Pengambilan & pengiriman','Perintah':'Rencana',
        'Barang Keluar':'Pengambilan barang',
        'Total perintah':'Rencana pengiriman','Sisa perintah':'Belum dimuat',
        'Sumber bobot':'Cara penimbangan','Ikatan silo aktif':'Silo yang sedang dipakai',
        'Tidak ada pekerjaan perlu tindakan':'Tidak ada barang menunggu penanganan'}
    for el in s.select('h1,h2,h3,h4,summary,dt,th,label,nav a,nav span,.kirim-detail__label'):
        for node in list(el.find_all(string=True)):
            value=str(node);key=value.strip()
            if key in labels:node.replace_with(value.replace(key,labels[key]))
            elif key in ('Hasil & QC','Lihat hasil & QC','Nilai kualitas QC PK','QC hasil penyosohan'):
                node.replace_with(value.replace('QC','pemeriksaan mutu'))
    for a in s.select('a.riwayat-detail__back,a.jasa-kembali'):
        target,label=tujuan_kembali(base)
        a['href']='/pelanggan'+target
        a.string='← Kembali ke '+label
    kembali=set()
    for a in s.select('a[href]'):
        if a.get_text(strip=True).startswith('← Kembali'):
            if a['href'] in kembali:a.decompose()
            else:kembali.add(a['href'])
    for a in s.select('a[href]'):
        if a.get_text(strip=True)=='Buka Pekerjaan':
            a.string='Lihat perkembangan proses';a['href']='/pelanggan/jasa-saya'
    for el in s.select('.penerimaan-tindakan'):
        el.decompose()
    for el in s.select('.giling-pengelolaan,.pengeringan-pengelolaan,.proses-detail__aksi'):
        el.decompose()
    for bagian in s.select('section#tindakan-proses'):
        judul=bagian.find('h2');petunjuk=bagian.find('p')
        if judul and judul.get_text(strip=True)=='Tindakan saat ini':
            judul.string='Status proses'
            if petunjuk:petunjuk.string='Lihat status dan hasil yang sudah dicatat pada halaman ini.'
        elif judul and judul.get_text(strip=True)=='Mesin sedang dijeda':
            if petunjuk:petunjuk.string='Proses dijeda. Menunggu petugas melanjutkan.'
    for p in s.select('p.bantu'):
        teks=p.get_text(' ',strip=True)
        if teks.startswith(('Sesudah proses ditutup, halaman ini membuka detail riwayat penggilingan.',
            'Catatan pada Status & informasi tidak dihitung sebagai pekerjaan wajib.',
            'Alur cepat · di bawah 200 kg.')):
            p.decompose()
        elif re.match(r'^\d+ pekerjaan perlu tindakan\.',teks):
            p.string='Barang berikut menunggu penanganan petugas.'
    for p in s.select('.kirim-detail p'):
        if p.get_text(strip=True).startswith('Satu armada dan satu tiket untuk seluruh pelanggan.'):
            p.decompose()
    panel=s.select_one('#panel-permintaan')
    if panel:
        dipilih=not panel.has_attr('hidden');panel.decompose()
        for a in s.select('a[role=tab][aria-controls=panel-permintaan]'):a.decompose()
        if dipilih:
            utama=s.select_one('#panel-ringkasan')
            if utama:utama.attrs.pop('hidden',None)
            for a in s.select('a[role=tab]'):a['aria-selected']='true' if a.get('aria-controls')=='panel-ringkasan' else 'false'
    for h in s.select('h2'):
        if h.get_text(strip=True)=='Jejak tahapan':
            bagian=h.find_parent('section')
            if bagian:bagian.decompose()
    return s


def read_only(html, base, *, origin=None):
    def destination(value):
        parsed=urlsplit(urljoin(base,value))
        if parsed.netloc or parsed.scheme:
            trusted=urlsplit(origin or '')
            if not trusted.netloc or (parsed.scheme,parsed.netloc)!=(trusted.scheme,trusted.netloc):
                return None
            value=urlunsplit(('', '', parsed.path, parsed.query, parsed.fragment))
        else:
            value=urlunsplit(('', '', parsed.path, parsed.query, parsed.fragment))
        return portal_url(value)
    s=BeautifulSoup(html,'html.parser')
    # Shell pelanggan menyediakan satu landmark utama. Halaman native yang
    # memakai <main> menjadi bagian di dalamnya, bukan landmark bersarang.
    for el in s.find_all('main'):el.name='div'
    for el in s.select('dialog,form.stok-nav__filter,.produk-aksi,.saring-kepemilikan,[data-post],[data-kirim]'):
        el.decompose()
    for script in list(s.find_all('script')):
        source=urlsplit(script.get('src',''))
        if source.netloc or source.scheme or source.path not in ('/static/saring-kerja.js','/static/pdf-penerimaan.js'):script.decompose()
    for form in list(s.find_all('form')):
        action=urlsplit(form.get('action') or base).path
        if form.get('method','get').lower()=='get':
            target=destination(form.get('action') or base)
            if not target:form.decompose();continue
            form['action']=target
            for field in form.select('[name=pelanggan_id],[name=kepemilikan],[name=pemilik],[name=kembali_jasa]'):field.decompose()
        elif action=='/kabar/status':
            form['action']='/pelanggan/kabar/status'
        elif re.fullmatch(r'/kabar/\d+/buka',action):
            form['action']='/pelanggan'+action
        elif re.fullmatch(r'/barang-keluar/\d+/retur',action):
            # This form also contains the native shipping/return comparison.
            # Keep its recorded values, remove only transaction inputs/actions.
            for control in list(form.select('input,select,textarea,button')):
                if control.name=='button' or control.get('type')=='hidden' or control.get('name')=='alasan':
                    control.decompose();continue
                option=control.find('option',selected=True) if control.name=='select' else None
                value=(control.get('value','') if control.name=='input' else option.get_text(' ',strip=True) if option else control.get_text(' ',strip=True) if control.name=='textarea' else '')
                span=s.new_tag('span',attrs={'class':'readonly-value'});span.string=value or '—';control.replace_with(span)
            for fieldset in form.select('fieldset'):fieldset.attrs.pop('disabled',None)
            form.unwrap()
        else:form.decompose()
    for el in list(s.select('th,td')):
        if el.get_text(strip=True)=='Aksi' or 'produk-kemasan__aksi' in el.get('class',[]):el.decompose()
    for detail in list(s.find_all('details')):
        summary=detail.find('summary')
        if summary and 'Batalkan pengajuan' in summary.get_text():detail.decompose()
    for a in list(s.find_all('a',href=True)):
        href=a['href']
        if a.get_text(strip=True)=='Semua pelanggan':a.decompose();continue
        if href.startswith('#'):continue
        target=destination(href)
        if not target:
            # Keep factual labels even where the staff destination is not a read.
            if a.get('class') and any(c in a['class'] for c in ('btn','pil','tbl')):a.decompose()
            else:a.unwrap()
        else:a['href']=target
    for el in s.find_all(True):
        for attr in list(el.attrs):
            if attr.startswith(('on','hx-')) or attr in ('data-aksi','data-buka','formaction'):del el[attr]
    for row in s.select('[data-detail-keluar]'):
        target=destination(row['data-detail-keluar'])
        if target:
            row['data-detail-keluar']=target
            row['tabindex']='0'
        else:row.attrs.pop('data-detail-keluar',None)
    for button in list(s.find_all('button')):
        if not button.find_parent('form') and button.get('id')!='bagikan-pdf':button.decompose()
    for table in list(s.find_all('table')):
        if not table.find_parent(class_='production-table-scroll'):
            table.wrap(s.new_tag('div',attrs={'class':'production-table-scroll','tabindex':'0'}))
    for frame in s.find_all('iframe',src=True):
        target=destination(frame['src'])
        if target:frame['src']=target
        else:frame.decompose()
    # Let the safe portal script preserve native PDF share/download behavior.
    share=s.find(id='bagikan-pdf')
    if share and share.get('data-penerimaan-share'):
        target=destination(share['data-penerimaan-share'])
        if target and re.fullmatch(r'/pelanggan/barang-masuk/\d+/laporan\.pdf',target):
            share['data-penerimaan-share']=target
        else:share.decompose();share=None
    if share and s.find('iframe'):
        share['data-pdf-share']=s.find('iframe')['src'];share.attrs.pop('disabled',None)
        status=s.find(id='status-bagikan')
        if status:status.string='PDF tersedia untuk dibaca, dibagikan, atau diunduh.'
    return str(bahasa_pelanggan(s,base))


def render_customer(request, name, *, status_code=200, **ctx):
    from app.web.tampilan import templates, VERSI
    scope=request.state.portal_scope
    account=request.state.akun
    ctx.update(request=request,akun=account,AKUN=account,VIEW='pelanggan',CSRF=csrf_context(request),
               VERSI=VERSI,BOLEH_PINDAH=False,boleh_koreksi=False,boleh_perintah=False,
               boleh_muat=False,boleh_ubah=False,boleh_minta=False,boleh_pindah_tumpukan=False,
               boleh_verifikasi=False,boleh_batal=False, MUTU_AKTIF=True, PORTAL_READ_ONLY=True)
    # Defense in depth before HTML creation. No foreign collections enter the DOM.
    for key in ('lot','tempat'):
        if key in ctx:ctx[key]=[x for x in ctx[key] if x.jasa_id in scope.jasa_ids]
    if 'lot' in ctx:ctx['total']=sum(x.tersedia for x in ctx['lot'])
    if name in ('stok_produk_jasa.html','stok_karung_jasa.html'):
        ctx['daftar']=[x for x in ctx.get('daftar',[]) if x['pelanggan_id']==scope.reader.pelanggan_id]
    for key in ('proses','k'):
        if ctx.get(key) is not None:
            obj=copy.copy(ctx[key]);ctx[key]=obj
            for attr,value in [('pilihan',[]),('tombol',[]),('boleh_ubah',False)]:
                if isinstance(obj,dict):obj[attr]=value
                elif hasattr(obj,attr):object.__setattr__(obj,attr,value)
    if name=='pengiriman.html' and ctx.get('detail'):
        ctx['PORTAL_READ_ONLY']=True
    if name=='pengiriman.html' and not ctx.get('detail'):
        name='portal/pengambilan.html'
        ctx['page_title']='Pengambilan barang'
    if name=='jasa_pelanggan_detail.html':
        d=copy.deepcopy(ctx['d']);ctx['d']=d
        # Ringkasan dan tab pengambilan wajib memakai cakupan yang sama
        # dengan detail native. Header pelanggan tidak mengesahkan item
        # milik pihak lain atau catatan campuran yang ditolak own_outgoing.
        from app.models import OutgoingRecord,CustomerReturn
        d['pengiriman']=[r for r in d['pengiriman'] if r['id'] in scope.ids(OutgoingRecord)]
        retur_diizinkan={f'/retur/{ident}' for ident in scope.ids(CustomerReturn)}
        d['retur']=[r for r in d['retur'] if r.get('href') in retur_diizinkan]
        for r in d['retur']:
            r['asal']=[a for a in r.get('asal',[]) if a['id'] in scope.ids(OutgoingRecord)]
        d['proses']=[r for r in d['proses'] if r['kode'] in scope.codes]
        for t in d['penerimaan']:
            if t.get('proses'):t['proses']=[(code,href) for code,href in t['proses'] if code in scope.codes]
        d['berjalan']=sum(r['status']=='proses' for r in d['proses'])
        for j in d['pesanan']:j['boleh_tutup']=j['boleh_batal']=False
    env=templates.env.overlay(loader=ChoiceLoader([DictLoader({'base.html':"""{% if STOK_NAV %}{% include 'portal/_navigasi_stok.html' %}<div class="stok-isi">{% endif %}
{% if LAPORAN_NAV %}<div class="laporan-riwayat"><link rel="stylesheet" href="/static/laporan-riwayat.css?v={{ VERSI }}">{% include 'portal/_navigasi_riwayat.html' %}<div class="laporan-isi">{% endif %}
{% if portal_scope_note %}<p class="bantu">{{ portal_scope_note }}</p>{% endif %}{% block isi %}{% endblock %}{% if LAPORAN_NAV %}</div></div>{% endif %}{% if STOK_NAV %}</div>{% endif %}"""}),templates.env.loader]))
    # Native stock-navigation computes visible groups from these already scoped rows.
    body=env.get_template(name).render(**ctx)
    path=request.url.path+('?' +request.url.query if request.url.query else '')
    content=read_only(body,path,origin=str(request.base_url))
    return shell(request,content,status_code=status_code,title=ctx.get('page_title') or ctx.get('breadcrumb_detail') or 'Portal pelanggan')


def shell(request,content,*,title='Portal pelanggan',status_code=200):
    from app.web.tampilan import templates,VERSI
    scope=request.state.portal_scope
    html=templates.env.get_template('portal/shell.html').render(request=request,
        title=title,content=Markup(content),reader=scope.reader,MENU=MENU,
        active=active_menu(request.url.path),CSRF=csrf_context(request),VERSI=VERSI,
        light=request.cookies.get('produksi_terik','1')=='1')
    return HTMLResponse(html,status_code=status_code,headers={'Cache-Control':'no-store, private','Vary':'Cookie','X-Robots-Tag':'noindex, nofollow'})


async def prepare_context(request,name,ctx):
    scope=request.state.portal_scope
    for key in ('lot','tempat'):
        if key in ctx:ctx[key]=[x for x in ctx[key] if x.jasa_id in scope.jasa_ids]
    if name in ('stok_produk_jasa.html','stok_karung_jasa.html'):
        ctx['daftar']=[x for x in ctx.get('daftar',[]) if x['pelanggan_id']==scope.reader.pelanggan_id]
    if name=='pengiriman.html' and not ctx.get('detail'):
        from app.database import SessionLocal
        from app.models import CustomerReturn
        from sqlalchemy import select
        async with SessionLocal() as db:
            ctx['portal_retur']=(await db.scalars(select(CustomerReturn).where(
                CustomerReturn.id.in_(scope.ids(CustomerReturn))).order_by(CustomerReturn.id.desc()))).all()
    from app.web.stok_navigasi import siapkan
    await siapkan(request,name,ctx)

    if ctx.get('STOK_NAV'):
        ctx['STOK_NAV']['milik']=[x for x in ctx['STOK_NAV']['milik'] if x['kunci']=='jasa']
    from app.web.laporan_navigasi import siapkan as siapkan_laporan
    await siapkan_laporan(request,ctx)
