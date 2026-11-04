import json
from pathlib import Path
from types import SimpleNamespace as N
from urllib.parse import urlsplit
import pytest
from jinja2 import Environment,ChoiceLoader,DictLoader,FileSystemLoader
from playwright.sync_api import sync_playwright,expect

R=Path(__file__).resolve().parents[1]

def document():
    env=Environment(loader=ChoiceLoader([DictLoader({'base.html':'{% block isi %}{% endblock %}',
        '_retur_supplier_navigasi.html':"{% extends 'base.html' %}"}),FileSystemLoader(R/'app/web/templates')]),autoescape=True)
    html=env.get_template('pk_kepemilikan_baru.html').render(VERSI='513',akun=N(user=N(id=1)),VIEW='super',LIHAT_SEBAGAI='',kembali='/kepemilikan?kind=pk')
    css=''.join((R/'hmu_tampilan/static'/f).read_text() for f in ['app.css','komponen-portal.css','padiflow-brand.css'])
    return '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>'+css+'</style><body class="padiflow-ui terik"><style>body{padding-left:0!important}</style><div id="formulir-sesi" data-token="csrf-uji"></div><main class="isi">'+html+'</main></body>'

@pytest.mark.parametrize('width',[320,390,1440])
@pytest.mark.parametrize('owner',[None,7])
def test_formulir_gudang_baru_dua_arah_review_draf_dan_hasil_tidak_pasti(width,owner):
    with sync_playwright() as p:
        b=p.chromium.launch();page=b.new_page(viewport=dict(width=width,height=1000));errors=[];calls=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        options=dict(gudang=[dict(id=1,nama='Selepan'),dict(id=9,nama='Cabang baru')],pemilik=[dict(value=7,label='Pak Pras · JAS/007')],sumber=[dict(sumber='tumpukan:13',warehouse_id=9,gudang='Cabang baru',label='PK/0013',owner=owner,pemilik='Pabrik' if owner is None else 'Pak Pras · JAS/007',tersedia='1000')])
        def route(r):
            path=urlsplit(r.request.url).path
            if path=='/static/pk-kepemilikan.js':r.fulfill(path=R/'app/web/static/pk-kepemilikan.js');return
            if path.startswith('/static/'):
                f=path.rsplit('/',1)[1];target=R/('hmu_tampilan/static' if f=='stok-seragam.css' else 'app/web/static')/f
                r.fulfill(path=target,content_type='text/css');return
            if path.startswith('/api/'):
                payload=r.request.post_data_json if r.request.method=='POST' else None
                calls.append((path,payload))
                if payload:assert r.request.headers['x-csrf-token']=='csrf-uji'
                if path.endswith('/pilihan'):r.fulfill(json=options)
                elif path.endswith('/periksa'):
                    r.fulfill(json=dict(baseline='baseline',review='proof',plan=dict(gudang='Cabang baru',sumber='PK/0013',physical_before='1000',physical_after='1000',balances_before={'None':{'kg':'1000'},'7':{'kg':'0'}},balances_after={'None':{'kg':'750'},'7':{'kg':'250'}})))
                elif path.endswith('/simpan'):r.abort('failed')
                elif '/status/' in path:r.fulfill(json=dict(recorded=True,id=128))
                else:raise AssertionError(path)
                return
            if path=='/kepemilikan/128':r.fulfill(body='<h1>AM-PK-128</h1>',content_type='text/html');return
            r.fulfill(body=document(),content_type='text/html')
        page.route('**/*',route);page.goto('https://uji.local/kepemilikan/pk/baru')
        expect(page.locator('[data-pk-form]')).to_be_visible()
        page.get_by_role('combobox',name='Gudang',exact=True).select_option('9')
        if owner is None:page.get_by_role('combobox',name='Pemilik tujuan',exact=True).select_option('7')
        else:expect(page.get_by_role('combobox',name='Pemilik tujuan',exact=True)).to_have_value('')
        page.get_by_label('Bobot yang dialihkan (kg)').fill('250')
        page.get_by_label('Alasan pengalihan',exact=True).fill('Kesepakatan pemilik')
        page.reload();expect(page.get_by_label('Bobot yang dialihkan (kg)')).to_have_value('250')
        expect(page.get_by_role('combobox',name='Gudang',exact=True)).to_have_value('9')
        page.get_by_role('button',name='Periksa dampak',exact=True).click()
        expect(page.locator('[data-pk-review]')).to_be_visible()
        expect(page.get_by_role('button',name='Simpan pengalihan PK')).to_be_disabled()
        assert not any(path.endswith('/simpan') for path,_ in calls)
        request=next(payload for path,payload in calls if path.endswith('/periksa'))
        assert request['warehouse_id']==9 and request['sumber']=='tumpukan:13'
        assert request['dari']==owner and request['ke']==(7 if owner is None else None)
        page.get_by_role('button',name='Ubah isian').click()
        expect(page.get_by_label('Alasan pengalihan',exact=True)).to_have_value('Kesepakatan pemilik')
        page.get_by_role('button',name='Periksa dampak',exact=True).click()
        page.get_by_role('checkbox',name='Saya sudah memeriksa gudang, sumber, pemilik, jumlah, dan dampak stok.').check()
        page.get_by_role('button',name='Simpan pengalihan PK').click()
        expect(page.locator('[data-pk-error]')).to_contain_text('Hasil penyimpanan belum pasti')
        expect(page.get_by_role('button',name='Simpan pengalihan PK')).to_be_disabled()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert page.locator('[data-pk-baru]').evaluate('(e)=>e.scrollWidth<=e.clientWidth')
        assert len([x for x,_ in calls if x.endswith('/simpan')])==1
        page.get_by_role('button',name='Baca status terbaru').click()
        page.wait_for_url('**/kepemilikan/128?*')
        assert len([x for x,_ in calls if x.endswith('/simpan')])==1
        assert not errors
        b.close()
