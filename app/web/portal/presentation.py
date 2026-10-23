"""Read-only projection of native templates; query authorization lives upstream.

Jinja's overlay is local to this request. Staff rendering and template globals
are never mutated. Native data, tables, process detail and PDFs remain shared.
"""
import copy
import re
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
from fastapi.responses import HTMLResponse
from jinja2 import ChoiceLoader, DictLoader
from markupsafe import Markup
from .auth import csrf_context
from .navigation import MENU, portal_url, active_menu


def read_only(html, base):
    s=BeautifulSoup(html,'html.parser')
    for el in s.select('dialog,form.stok-nav__filter,.produk-aksi,.saring-kepemilikan,[data-post],[data-kirim]'):
        el.decompose()
    for script in list(s.find_all('script')):
        source=urlsplit(script.get('src',''))
        if source.netloc or source.scheme or source.path!='/static/saring-kerja.js':script.decompose()
    for form in list(s.find_all('form')):
        action=urlsplit(form.get('action') or base).path
        if form.get('method','get').lower()=='get':
            target=portal_url(urljoin(base,form.get('action') or base))
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
        target=portal_url(urljoin(base,href))
        if not target:
            # Keep factual labels even where the staff destination is not a read.
            if a.get('class') and any(c in a['class'] for c in ('btn','pil','tbl')):a.decompose()
            else:a.unwrap()
        else:a['href']=target
    for el in s.find_all(True):
        for attr in list(el.attrs):
            if attr.startswith(('on','hx-')) or attr in ('data-aksi','data-buka','formaction'):del el[attr]
    for button in list(s.find_all('button')):
        if not button.find_parent('form') and button.get('id')!='bagikan-pdf':button.decompose()
    for table in list(s.find_all('table')):
        if not table.find_parent(class_='production-table-scroll'):
            table.wrap(s.new_tag('div',attrs={'class':'production-table-scroll','tabindex':'0'}))
    for frame in s.find_all('iframe',src=True):
        target=portal_url(frame['src'])
        if target:frame['src']=target
        else:frame.decompose()
    # Let the safe portal script preserve native PDF share/download behavior.
    share=s.find(id='bagikan-pdf')
    if share and s.find('iframe'):
        share['data-pdf-share']=s.find('iframe')['src'];share.attrs.pop('disabled',None)
        status=s.find(id='status-bagikan')
        if status:status.string='PDF tersedia untuk dibaca, dibagikan, atau diunduh.'
    return str(s)


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
    if name=='jasa_pelanggan_detail.html':
        d=copy.deepcopy(ctx['d']);ctx['d']=d
        d['proses']=[r for r in d['proses'] if r['kode'] in scope.codes]
        for t in d['penerimaan']:
            if t.get('proses'):t['proses']=[(code,href) for code,href in t['proses'] if code in scope.codes]
        d['berjalan']=sum(r['status']=='proses' for r in d['proses'])
        for j in d['pesanan']:j['boleh_tutup']=j['boleh_batal']=False
    env=templates.env.overlay(loader=ChoiceLoader([DictLoader({'base.html':"""{% if STOK_NAV %}{% include '_stok_navigasi.html' %}<div class="stok-isi">{% endif %}
{% if LAPORAN_NAV %}<div class="laporan-riwayat"><link rel="stylesheet" href="/static/laporan-riwayat.css?v={{ VERSI }}">{% include '_laporan_navigasi.html' %}<div class="laporan-isi">{% endif %}
{% if portal_scope_note %}<p class="bantu">{{ portal_scope_note }}</p>{% endif %}{% block isi %}{% endblock %}{% if LAPORAN_NAV %}</div></div>{% endif %}{% if STOK_NAV %}</div>{% endif %}"""}),templates.env.loader]))
    # Native stock-navigation computes visible groups from these already scoped rows.
    body=env.get_template(name).render(**ctx)
    path=request.url.path+('?' +request.url.query if request.url.query else '')
    content=read_only(body,path)
    return shell(request,content,status_code=status_code,title=ctx.get('breadcrumb_detail') or 'Portal pelanggan')


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
    from app.web.stok_navigasi import siapkan
    await siapkan(request,name,ctx)

    if ctx.get('STOK_NAV'):
        ctx['STOK_NAV']['milik']=[x for x in ctx['STOK_NAV']['milik'] if x['kunci']=='jasa']
    from app.web.laporan_navigasi import siapkan as siapkan_laporan
    await siapkan_laporan(request,ctx)
