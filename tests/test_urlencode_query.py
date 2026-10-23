"""Tautan konteks menerima QueryParams, termasuk spasi, Unicode dan kunci ulang."""
from html import unescape
from urllib.parse import parse_qs
from starlette.datastructures import QueryParams
from app.web.tampilan import templates


def test_query_params_dirender_sebagai_tautan_konteks():
    query=QueryParams('cari=beras+putih%26gabah&jenis=pendinginan&jenis=giling&catatan=mutu+%C3%A9')
    hasil=templates.env.from_string('{{ query|urlencode }}').render(query=query)
    assert parse_qs(unescape(hasil))=={'cari':['beras putih&gabah'], 'jenis':['pendinginan','giling'], 'catatan':['mutu é']}


def test_string_dan_dict_urlencode_tetap_sama():
    from jinja2.filters import do_urlencode
    for nilai in ['beras putih/jasa', {'tab':'berjalan','cari':'gabah & beras'}]:
        assert templates.env.filters['urlencode'](nilai)==do_urlencode(nilai)
