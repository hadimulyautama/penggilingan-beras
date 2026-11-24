"""Fresh actual-DTO empty presentation contract; no query/score calculation."""
from types import SimpleNamespace
from pathlib import Path
import re
import pytest
from bs4 import BeautifulSoup
from jinja2 import Environment,FileSystemLoader
from starlette.responses import HTMLResponse
from app.web.stock_qc_empty_html import finish
from app.web.stock_detail_native import native_table_headers
ROOT=Path(__file__).resolve().parents[1]


def native(qc):
    env=Environment(loader=FileSystemLoader(ROOT/'hmu_tampilan/templates'))
    env.filters['jam']=lambda x,y:str(x)
    body=env.get_template('_stok_pk_qc.html').render(riwayat_qc=qc,ATURAN_RATA_QC_PK='Native guide')
    return '<html><body><form action="/existing" method="post"><input value="PRIVATE DRAFT"></form><script>window.nativeKey="PRIVATE EXISTING";</script>'+body+'<div>PRIVATE OTHER BODY</div></body></html>'


def dto(**kw):
    return dict(rows=[],hasil_terbaru_saja=False,ada_data_lama=False,detail_href=None,**kw)


@pytest.mark.parametrize('latest',[False,True])
def test_true_empty_keeps_actual_native_headers_message_and_all_other_bytes(latest):
    qc=dto();qc['hasil_terbaru_saja']=latest;html=native(qc);response=HTMLResponse(html)
    result=finish(response,SimpleNamespace(method='GET'),qc=qc,mutu=True)
    doc=BeautifulSoup(result.body,'html.parser');table=doc.select_one('#riwayat-qc-pk').find_parent('section').select_one('table[data-stock-qc-empty]')
    assert table and table['aria-label']=='Riwayat QC stok PK'
    headers=native_table_headers();expected=headers['qc']+[headers['qc_latest'] if latest else headers['qc_history']]
    assert [th.text for th in table.select('thead th')]==expected
    assert table.select_one('tbody td')['colspan']=='8'
    assert table.select_one('tbody td').text=='Belum ada pemeriksaan QC untuk stok PK ini.'
    assert not table.select('[data-kirim],[data-post],input,button')
    old=b'<p class="bantu">Belum ada pemeriksaan QC untuk stok PK ini.</p>'
    before,after=html.encode().split(old)
    assert result.body.startswith(before) and result.body.endswith(after)
    assert int(result.headers['content-length'])==len(result.body)
    assert result.headers['cache-control']=='private, no-store'


@pytest.mark.parametrize('mutu,qc,method,status,ctype',[
    (False,dto(),'GET',200,'text/html'),(None,dto(),'GET',200,'text/html'),
    (True,{},'GET',200,'text/html'),(True,dict(rows=None,hasil_terbaru_saja=False),'GET',200,'text/html'),
    (True,dict(rows=[{'PRIVATE':'record'}],hasil_terbaru_saja=False),'GET',200,'text/html'),
    (True,dict(rows=[]),'GET',200,'text/html'),(True,dict(rows=[],hasil_terbaru_saja=0),'GET',200,'text/html'),
    (True,dto(),'POST',200,'text/html'),(True,dto(),'GET',403,'text/html'),(True,dto(),'GET',200,'application/json'),
])
def test_off_unknown_nonempty_or_error_stays_exact_bytes(mutu,qc,method,status,ctype):
    html=native(dto());response=HTMLResponse(html,status_code=status,media_type=ctype)
    before=response.body;headers=dict(response.headers)
    assert finish(response,SimpleNamespace(method=method),qc=qc,mutu=mutu) is response
    assert response.body==before and dict(response.headers)==headers


@pytest.mark.parametrize('change',[
    lambda h:h.replace('riwayat-qc-pk','other-qc'),
    lambda h:h+h,
    lambda h:h.replace('Belum ada pemeriksaan QC untuk stok PK ini.','Unexpected source shape'),
    lambda h:h.replace('</section>','<table><thead><tr><th>Native existing</th></tr></thead></table></section>'),
])
def test_missing_duplicate_or_existing_table_is_not_guessed(change):
    html=change(native(dto()));response=HTMLResponse(html);before=response.body
    assert finish(response,SimpleNamespace(method='GET'),qc=dto(),mutu=True).body==before


def test_route_presentation_uses_actual_fresh_dto_after_render_without_new_reader():
    source=(ROOT/'app/web/layar_stok.py').read_text()
    assert source.index('response = finish_qc_empty(response, request, qc=riwayat_qc, mutu=mutu_aktif)')>source.index('response = await render_laci(',source.index('async def halaman_detail_stok_pk'))
    module=(ROOT/'app/web/stock_qc_empty_html.py').read_text()
    for forbidden in ['SessionLocal','db.','commit(','.flush(', 'penilaian_dari_log(', 'create_all','sessionStorage']:
        assert forbidden not in module
