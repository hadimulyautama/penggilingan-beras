"""Pure compilation of public stock shape; no actor/ORM/DB/browser/requests."""
import importlib.util
import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from jinja2 import Environment, ChoiceLoader, FileSystemLoader, StrictUndefined
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("stock_blueprint", ROOT / "scripts/stock_ui_blueprint.py")
blueprint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(blueprint)


def raw(tab, mutu=False, owner=False):
    env = Environment(loader=ChoiceLoader([
        FileSystemLoader(str(ROOT / "app/web/templates")),
        FileSystemLoader(str(ROOT / "hmu_tampilan/templates")),
    ]), autoescape=True, undefined=StrictUndefined)
    context = blueprint.context(tab, mutu=mutu, ownership_layout=owner)
    # Public request has no account, headers, entity IDs or scope. Same pattern
    # as the existing root compiler; this is NOT a synthetic business record.
    context.update(VERSI="__PADI_CAP__", request=Request({
        "type": "http", "method": "GET", "path": "/stok", "scheme": "http",
        "server": ("ui.invalid", 80), "headers": [], "query_string": b"",
    }))
    template = env.get_template("halaman_bertahap.html")
    return "".join(template.blocks["isi"](template.new_context(context)))


@pytest.mark.parametrize("tab", ["bahan", "produk", "karung"])
@pytest.mark.parametrize("mutu", [False, True])
@pytest.mark.parametrize("owner", [False, True])
def test_variants_keep_native_structure_without_entity_options(tab, mutu, owner):
    first = blueprint.prepare_markup(raw(tab, mutu, owner))
    assert first == blueprint.prepare_markup(raw(tab, mutu, owner))
    doc = BeautifulSoup(first, "html.parser")
    controls = doc.select_one("[data-stok-controls]")
    assert controls
    assert [n.get_text(" ", strip=True) for n in doc.select("thead th")] == blueprint.native_columns(tab, mutu)
    assert len(doc.select("tbody tr")) == 1
    assert "Memuat data" in doc.select_one("tbody tr").get_text()
    assert not doc.select("form[method=post],input[name=_csrf],[data-editor-perintah],[data-kemas-ulang]")
    assert all(form.get("method") == "get" for form in doc.select("form"))
    assert not doc.select("[data-stok-controls] a.kontrol-tab__item[href]")
    assert len(doc.select("[data-ui-stock-tab][aria-disabled=true]")) == 3
    assert [tab["data-ui-stock-tab"] for tab in doc.select("[data-ui-stock-tab]")] == ["bahan", "produk", "karung"]
    assert not doc.select("[data-sk-cetak]:not([disabled])")
    for name, reason in [("gudang", blueprint.WAREHOUSE_REASON), ("pelanggan_id", blueprint.CUSTOMER_REASON)]:
        select = controls.select_one('select[name="' + name + '"]')
        assert select.has_attr("disabled")
        assert select.find_parent("label").get("hidden") is None
        assert [o.get("value") for o in select.select("option")] == [""]
        assert doc.find(id=select["aria-describedby"]).get_text() == reason
    assert controls.select_one('input[type=search][name=cari][data-ui-stock-search]')
    assert controls.select_one('select[name=pemilik][data-ui-stock-owner]')
    assert bool(doc.select(".sk-riwayat-link")) == owner
    assert not doc.select(".sk-riwayat-link[href]")
    assert [s["src"].split("?")[0] for s in doc.select("script[src]")] == ["/static/halaman-bertahap.js"]
    assert "ui.invalid" not in first
    assert "wh:" not in first and "tenant_id" not in first and "company_id" not in first


def test_column_function_is_native_not_an_imported_app_reader():
    assert len(blueprint.native_columns("bahan", False)) == 7
    assert len(blueprint.native_columns("bahan", True)) == 11
    assert blueprint.native_columns("produk", False) == blueprint.native_columns("produk", True)
    assert blueprint.native_columns("karung", False) == ["No.", "Merek", "Jenis karung", "Ukuran", "Jumlah", "Status / tindakan"]
    source = (ROOT / "scripts/stock_ui_blueprint.py").read_text()
    assert "from app." not in source and "import app." not in source
    assert "SessionLocal" not in source


@pytest.mark.parametrize("kwargs", [
    {"tab": "private"}, {"tab": "bahan", "mutu": 1},
    {"tab": "bahan", "ownership_layout": 1},
])
def test_unknown_layout_fails_closed(kwargs):
    with pytest.raises(ValueError):
        blueprint.context(**kwargs)


def test_context_contains_only_public_literals_and_placeholders():
    value = blueprint.context("bahan")
    nav = value["SHELL"]["stock_nav"]
    assert nav["gudang"] == nav["pelanggan_id"] == ""
    assert nav["lokasi_pil"] == nav["pelanggan"] == []
    assert value["SHELL"]["stock_owner_allowed"] is False
    assert set(value) == {"SHELL", "LAPORAN_NAV"}
    json.dumps(value)  # No actor, Request, model, session object.
    assert set(value["SHELL"]["stock_nav"]["tab"][0]) == {"nama", "kunci", "href", "boleh"}


@pytest.mark.parametrize("poison", [
    lambda h: h.replace('data-stamp="__PADI_STAMP__"', 'data-stamp="private-session"'),
    lambda h: h.replace('<select class="fld" name="gudang">', '<select class="fld" name="gudang"><option value="wh:42">PRIVATE</option>'),
    lambda h: h.replace('name="gudang" value=""', 'name="gudang" value="wh:42"'),
    lambda h: h.replace('name="cari" value=""', 'name="cari" value="PRIVATE SEARCH"'),
    lambda h: h.replace("Cakupan mengikuti akses Anda", "PRIVATE COMPANY"),
    lambda h: h + '<section data-halaman-bertahap data-kind="stok"></section>',
    lambda h: h.replace('</section>', '<form method="post"></form></section>', 1),
    lambda h: h.replace('</section>', '<script src="/static/stok-seragam.js"></script></section>', 1),
])
def test_source_scoped_html_is_rejected_instead_of_imported(poison):
    with pytest.raises(ValueError):
        blueprint.prepare_markup(poison(raw("bahan")))


def test_changed_native_column_dependency_requires_compiler_review(tmp_path, monkeypatch):
    path = tmp_path / "app/web"
    path.mkdir(parents=True)
    (path / "halaman_bertahap.py").write_text("def kolom_daftar(jenis, mutu=False):\n return load_private_names()\n")
    monkeypatch.setattr(blueprint, "ROOT", tmp_path)
    with pytest.raises(ValueError):
        blueprint.native_columns("bahan")
