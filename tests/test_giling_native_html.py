"""Kontrak murni descriptor/markup; bukan proof PG, izin, browser atau rilis."""
import ast
from html.parser import HTMLParser
from pathlib import Path

import pytest
from jinja2 import DictLoader, Environment, FileSystemLoader, ChoiceLoader, select_autoescape

from app.web.giling_native_html import TAB, deskripsi

ROOT = Path(__file__).resolve().parents[1]


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def render(query=""):
    spec = deskripsi("/proses-aktif/giling/GILING-FIXTURE", query)
    spec["stamp"] = "fixture-only"
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": "{% block isi %}{% endblock %}",
                    "_panduan.html": "{% macro panel(id,judul,penutup) %}<dialog id=\"{{id}}\"><h2>{{judul}}</h2>{{caller()}}<button type=\"button\" data-gk-panduan-tutup>Tutup panduan</button></dialog>{% endmacro %}"}),
        FileSystemLoader(str(ROOT / "app/web/templates")),
    ]), autoescape=select_autoescape())
    return env.get_template("giling_native_html.html").render(
        GILING_KERANGKA=spec, VERSI="fixture-cap", kembali="/pekerjaan?tab=berjalan")


@pytest.mark.parametrize("path,query", [
    ("/proses-aktif/sosoh/FIXTURE", ""),
    ("/proses-aktif/giling/", ""),
    ("/proses-aktif/giling/a/b", ""),
    ("/proses-aktif/giling/<script>", ""),
    ("/proses-aktif/giling/" + "x" * 81, ""),
    ("/proses-aktif/giling/X", "buka=hasil_giling"),
    ("/proses-aktif/giling/X", "nilai=123"),
    ("/proses-aktif/giling/X", "tab_detail=hasil&tab_detail=qc"),
    ("/proses-aktif/giling/X", "tenant_id=99"),
    ("/proses-aktif/giling/X", "x=" + "a" * 3001),
])
def test_url_di_luar_irisan_diserahkan_native(path, query):
    assert deskripsi(path, query) is None


@pytest.mark.parametrize("key,label", TAB)
def test_tab_native_dan_field_muncul_tanpa_angka_atau_model(key, label):
    html = render("tab_detail=" + key)
    tags = Tags()
    tags.feed(html)
    tabs = [attrs for tag, attrs in tags.tags if attrs.get("role") == "tab"]
    panels = [attrs for tag, attrs in tags.tags if attrs.get("role") == "tabpanel"]
    assert [t["data-gk-tab-pilih"] for t in tabs] == [x[0] for x in TAB]
    assert [p["data-gk-panel"] for p in panels if "hidden" not in p] == [key]
    assert [t["data-gk-tab-pilih"] for t in tabs if t["aria-selected"] == "true"] == [key]
    inputs = [attrs for tag, attrs in tags.tags if tag == "input"]
    assert inputs and all("disabled" in attrs and "value" not in attrs for attrs in inputs)
    assert "Total PK sampai sekarang (kg)" in html
    assert "Periksa &amp; catat PK" in html
    assert "data-editor-perintah" in html
    assert "data-giling-ringkas" not in html  # Tidak memulai core dengan awal palsu.
    assert 'id="giling-awal"' not in html
    assert "<form" not in html
    assert "0 kg" not in html and "Belum ada hasil" not in html
    assert "Menunggu data" in html


def test_descriptor_tidak_membawa_angka_identitas_atau_token_rencana():
    spec = deskripsi("/proses-aktif/giling/FIXTURE", "tab_detail=hasil")
    assert set(spec) == {"kode", "tab", "tabs", "fakta", "stok", "alamat", "data_url"}
    assert not any(k in spec for k in ("status", "pemilik", "stok_kg", "dasar", "kunci", "awal"))
    assert deskripsi("/proses-aktif/giling/FIXTURE", "tab_detail=asing")["tab"] == "ringkasan"


def test_label_dan_urutan_tab_tetap_sesuai_native_yang_dipin():
    native = (ROOT / "app/web/static/giling-desain.js").read_text()
    for key, label in TAB:
        assert "['" + key + "','" + label + "']" in native
    for label in ("Total PK sampai sekarang (kg)", "Periksa & catat PK"):
        assert label in (ROOT / "app/web/static/giling-ringkas.js").read_text()


def test_builder_mendelegasikan_izin_dan_tidak_membaca_agregat_atau_commit():
    source = (ROOT / "app/web/giling_native_html.py").read_text()
    ast.parse(source)
    assert source.index('await izin(akun.user, spec["kode"])') < source.index("select(MillingProcess.status)")
    assert "batas(akun.user, MillingProcess)" in source
    assert 'if status != "proses":' in source
    assert 'is_customer_read(request)' in source
    for forbidden in ("await baca(", "await db.commit(", "await db.flush(", "SimpleNamespace", "create_all", "APIRouter"):
        assert forbidden not in source


def test_asset_tidak_fetch_post_storage_atau_mengganti_guard():
    import re
    source = (ROOT / "app/web/static/giling-native-html.js").read_text()
    code = re.sub(r"/\*[\s\S]*?\*/|//[^\n]*", "", source)
    for forbidden in ("fetch(", "sessionStorage", "localStorage", "PadiKoreksiBahan",
                      "giling-awal", "beforeunload", "preventDefault();location"):
        assert forbidden not in code
    assert "afterInstall({content})" in source
    assert "show(tabFromAddress(address,location.origin))" in source
    assert "core.mount({address" in source
    assert "history.replaceState" not in source
    assert "history.pushState" not in source


def test_data_url_is_exact_native_route_and_no_api_is_proposed():
    value = deskripsi("/proses-aktif/giling/FIXTURE", "tab_detail=hasil&kembali_kerja=%2Fpekerjaan%3Ftab%3Dberjalan")
    assert value["data_url"] == value["alamat"]
    assert "/api/" not in value["data_url"]
    html = render("tab_detail=hasil")
    assert 'data-url="/proses-aktif/giling/GILING-FIXTURE?tab_detail=hasil"' in html
    assert "Status simpan sebelumnya belum diperiksa" in html
    assert "jangan kirim ulang" in html


def test_x_pindah_native_read_declines_before_actor_or_database():
    import asyncio
    from starlette.requests import Request
    from app.web.giling_native_html import kerangka
    request = Request(dict(type="http", method="GET", path="/proses-aktif/giling/FIXTURE",
        raw_path=b"/proses-aktif/giling/FIXTURE", query_string=b"",
        headers=[(b"x-pindah", b"1")], scheme="http", server=("ui.invalid", 80)))
    assert asyncio.run(kerangka(request, None, {})) is None
