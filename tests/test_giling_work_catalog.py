"""Pure parse of native-shaped HTML strings; no business records or DB."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("giling_work_catalog", ROOT / "app/web/giling_work_catalog.py")
emitter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(emitter)
BINDING = dict(source_address="/pekerjaan?tab=berjalan", cap="cap-fixture",
               context="context-fixture", session="session-fixture")


def row(code="GL-FIXTURE", href=None, kind="giling", attrs="", legacy=False):
    href = href or "/proses-aktif/giling/" + code
    body = '<span><a class="proses-aktif-list__detail" href="' + href + '"><strong>' + code + '</strong></a></span>'
    body += '<span>PRIVATE OWNER · PRIVATE STOCK 12345</span><a class="proses-aktif-list__detail" href="' + href + '">Detail</a>'
    if legacy:
        value = '<a class="proses-aktif-list__row" data-proses="' + kind + '" href="' + href + '" ' + attrs + '><strong>' + code + '</strong><span>PRIVATE OWNER</span></a>'
    else:
        value = '<div class="proses-aktif-list__row" data-proses="' + kind + '" ' + attrs + '>' + body + '</div>'
    return '<section data-blok aria-label="Proses aktif"><div class="proses-aktif-list">' + value + '</div></section>'


def test_catalog_is_exact_native_links_only_and_deduplicated():
    html = row() + row("SS-FIXTURE", kind="sosoh") + '<a href="/proses-aktif/giling/NOT-IN-ROW">Injected outside</a>'
    result = emitter.catalog(html, **BINDING)
    assert result["entries"] == [dict(alamat="/proses-aktif/giling/GL-FIXTURE", kode="GL-FIXTURE", label="Penggilingan aktif")]
    assert result["cap"] == BINDING["cap"] and result["konteks"] == BINDING["context"] and result["sesi"] == BINDING["session"]
    assert set(result) == {"versi", "cap", "konteks", "sesi", "sumber_sha256", "entries"}
    assert "PRIVATE" not in str(result)
    assert "12345" not in str(result)


def test_native_template_selectors_are_source_pinned():
    for file in ("_pekerjaan_berjalan_ringkas.html", "berjalan.html"):
        source = (ROOT / "app/web/templates" / file).read_text()
        assert "proses-aktif-list__row" in source
        assert 'data-proses="{{ visual.jenis(b) }}"' in source
        assert "alamat_detail_proses(b)" in source
        assert "<strong>{{ b.kode }}</strong>" in source


@pytest.mark.parametrize("wrapper", [
    lambda h: '<div hidden>' + h + '</div>',
    lambda h: '<div aria-hidden="true">' + h + '</div>',
    lambda h: '<template>' + h + '</template>',
    lambda h: '<div inert>' + h + '</div>',
    lambda h: '<div style="display: none">' + h + '</div>',
    lambda h: '<div style="visibility: hidden">' + h + '</div>',
])
def test_structurally_hidden_work_is_not_catalogued(wrapper):
    assert emitter.catalog(wrapper(row()), **BINDING)["entries"] == []


@pytest.mark.parametrize("href", [
    "/proses-aktif/sosoh/GL-FIXTURE", "/proses-aktif/giling/OTHER",
    "//external.invalid/proses-aktif/giling/GL-FIXTURE",
    "https://external.invalid/proses-aktif/giling/GL-FIXTURE",
    "/proses-aktif/giling/GL-FIXTURE?buka=hasil_giling",
    "/proses-aktif/giling/GL-FIXTURE?nilai=1",
    "/proses-aktif/giling/GL-FIXTURE?tenant_id=1",
    "/proses-aktif/giling/GL-FIXTURE#hasil",
    "/proses-aktif/giling/GL-FIXTURE?tab_detail=hasil&tab_detail=qc",
])
def test_action_other_context_or_unproved_link_declines(href):
    assert emitter.catalog(row(href=href), **BINDING)["entries"] == []


def test_legacy_row_anchor_and_visible_query_are_preserved():
    href = "/proses-aktif/giling/GL-FIXTURE?tab_detail=hasil&kembali_kerja=%2Fpekerjaan%3Ftab%3Dberjalan"
    value = emitter.catalog(row(href=href, legacy=True), **BINDING)
    assert value["entries"][0]["alamat"] == href
    assert emitter.catalog(row(attrs="hidden"), **BINDING)["entries"] == []


def test_50_limit_is_bound_not_a_route_id_matcher():
    html = "".join(row("GL-" + str(i)) for i in range(50))
    assert len(emitter.catalog(html, **BINDING)["entries"]) == 50
    assert emitter.catalog(html + row("GL-51"), **BINDING) is None
    assert emitter.catalog("", **BINDING)["entries"] == []


def test_similar_row_outside_native_work_block_cannot_be_catalogued():
    assert emitter.catalog(row().replace('data-blok aria-label="Proses aktif"', 'aria-label="Other"'), **BINDING)["entries"] == []


def test_one_visible_row_has_at_most_one_record_even_if_second_link_differs():
    html = row().replace('>Detail</a>', '>Detail</a>').replace(
        'href="/proses-aktif/giling/GL-FIXTURE">Detail',
        'href="/proses-aktif/giling/GL-FIXTURE?tab_detail=qc">Detail')
    assert len(emitter.catalog(html, **BINDING)["entries"]) == 1


@pytest.mark.parametrize("patch", [
    {"source_address": "/pengaturan/akun"}, {"source_address": "//external.invalid/pekerjaan"},
    {"source_address": "https://["}, {"source_address": "/pekerjaan#hidden"},
    {"cap": ""}, {"context": ""}, {"session": ""}, {"session": "x" * 513},
])
def test_invalid_source_or_binding_fails_closed(patch):
    assert emitter.catalog(row(), **{**BINDING, **patch}) is None
