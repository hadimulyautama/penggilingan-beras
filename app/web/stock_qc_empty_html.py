"""Keep a native QC table for an actually-empty fresh, authorized DTO only."""
from functools import lru_cache
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[2]
_SECTION=re.compile(rb'<section\b[^>]*\baria-labelledby="riwayat-qc-pk"[^>]*>.*?</section>',re.S)
_EMPTY=re.compile(rb'<p\b[^>]*>\s*Belum ada pemeriksaan QC untuk stok PK ini\.\s*</p>')


@lru_cache(maxsize=1)
def template():
    from jinja2 import Environment,FileSystemLoader,StrictUndefined
    return Environment(loader=FileSystemLoader(ROOT/'app/web/templates'),autoescape=True,undefined=StrictUndefined).get_template('stock_qc_empty_table.html')


def finish(response,request,*,qc,mutu):
    """No row inference: off/unknown/nonempty/error/non-native stays byte exact.

    Only the source-pinned native empty paragraph inside its specific existing
    QC section is changed. All other bytes, controllers, forms and keys remain.
    The caller already performed native guards and read this actual DTO once.
    """
    if (request.method!='GET' or response.status_code!=200 or mutu is not True
            or not isinstance(qc,dict) or type(qc.get('rows')) is not list or qc['rows']
            or type(qc.get('hasil_terbaru_saja')) is not bool
            or 'text/html' not in response.headers.get('content-type','')):
        return response
    body=getattr(response,'body',b'')
    if not body or len(body)>8*1024*1024:return response
    matches=list(_SECTION.finditer(body))
    if len(matches)!=1 or len(matches[0][0])>32768:return response
    section=matches[0][0]
    from bs4 import BeautifulSoup
    doc=BeautifulSoup(section,'html.parser')
    if doc.select('table') or len(doc.select('#riwayat-qc-pk'))!=1:return response
    empty=list(_EMPTY.finditer(section))
    if len(empty)!=1:return response
    from app.web.stock_detail_native import native_table_headers
    headers=native_table_headers()
    columns=headers['qc']+[headers['qc_latest'] if qc['hasil_terbaru_saja'] else headers['qc_history']]
    fragment=template().render(columns=columns).encode()
    replacement=section[:empty[0].start()]+fragment+section[empty[0].end():]
    response.body=body[:matches[0].start()]+replacement+body[matches[0].end():]
    response.headers['Content-Length']=str(len(response.body))
    response.headers['Cache-Control']='private, no-store'
    return response
