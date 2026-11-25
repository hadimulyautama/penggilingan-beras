"""Public stock UI blueprint inputs; never imports app, actor, models or DB.

Root compiler owns rendering, manifest, permission flags and fresh native GET.
All values here are product labels/finite route literals or UI placeholders.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABS = (("bahan", "Bahan & PK"), ("produk", "Produk"), ("karung", "Karung"))
OWNERS = (("semua", "Semua kepemilikan"), ("pabrik", "Pabrik"), ("jasa", "Titipan jasa"))
WAREHOUSE_REASON = "Pilihan gudang tersedia setelah stok selesai dibaca."
CUSTOMER_REASON = "Pilihan pelanggan tersedia setelah stok selesai dibaca."


def compiler_inputs() -> tuple[Path, ...]:
    """Add these to root manifest in addition to its template/asset loader."""
    return (Path(__file__).resolve(), ROOT / "app/web/halaman_bertahap.py")


def native_columns(tab: str, mutu: bool = False) -> list[str]:
    """Compile only the pure native columns function, not its app module.

    Fail on new calls/imports/attributes or unknown names rather than importing
    the runtime or maintaining a second set of stock column labels.
    """
    if tab not in dict(TABS) or type(mutu) is not bool:
        raise ValueError("Varian struktur stok tidak dikenal.")
    path = ROOT / "app/web/halaman_bertahap.py"
    function = next(node for node in ast.parse(path.read_text()).body
                    if isinstance(node, ast.FunctionDef) and node.name == "kolom_daftar")
    allowed = (ast.FunctionDef, ast.arguments, ast.arg, ast.If, ast.Compare,
               ast.Eq, ast.Name, ast.Load, ast.Constant, ast.Return, ast.List,
               ast.BinOp, ast.Add, ast.IfExp)
    if any(not isinstance(node, allowed) for node in ast.walk(function)):
        raise ValueError("Fungsi kolom native memerlukan review compiler.")
    if any(isinstance(node, ast.Name) and node.id not in {"jenis", "mutu", "str", "bool"}
           for node in ast.walk(function)):
        raise ValueError("Kolom native bergantung konteks runtime.")
    for argument in function.args.args:
        argument.annotation = None
    function.returns = None
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    namespace = {"__builtins__": {}}
    exec(compile(module, str(path), "exec"), namespace)
    return namespace["kolom_daftar"](tab, mutu)


def context(tab: str, *, mutu: bool = False,
            ownership_layout: bool = False) -> dict:
    """Exact compiler context except Request/CAP supplied publicly by root.

    ownership_layout is a visual variant selector, NOT authority. Root must
    choose it from fresh native flags and never from a source-page actor record.
    The returned tab links are rendered then locked by prepare_markup().
    """
    if type(ownership_layout) is not bool:
        raise ValueError("Pilihan layout harus boolean.")
    columns = native_columns(tab, mutu)
    url = "/stok?tab=" + tab + "&pemilik=semua"
    nav = dict(
        url=url, jenis=tab, pemilik="semua", pelanggan_id="", pelanggan=[],
        gudang="", label=dict(TABS)[tab], nama_pemilik="Semua kepemilikan",
        cakupan="Cakupan mengikuti akses Anda", lokasi="Pilihan gudang belum dibaca",
        tab=[dict(nama=label, kunci=key, href="/stok?tab=" + key + "&pemilik=semua",
                  boleh=True) for key, label in TABS],
        milik=[dict(nama=label, kunci=key,
                    href="/stok?tab=" + tab + "&pemilik=" + key)
               for key, label in OWNERS],
        lokasi_pil=[],
    )
    shell = dict(
        kind="stok", title="Stok", stamp="__PADI_STAMP__",
        data_url="__PADI_DATA_URL__", tab=tab, columns=columns,
        scope="Cakupan mengikuti akses Anda",
        stock_nav=nav, stock_owner_allowed=ownership_layout,
        filtered=False,
    )
    return dict(SHELL=shell, LAPORAN_NAV=False)


def prepare_markup(html: str) -> str:
    """Specific, public-only adapter over the REAL native stock partial.

    No source document, role, records, IDs or query values accepted. No effect
    on vendor/native HTML outside the separately compiled public blueprint.
    """
    from bs4 import BeautifulSoup

    doc = BeautifulSoup(html, "html.parser")
    roots = doc.select('[data-halaman-bertahap][data-kind="stok"]')
    if len(roots) != 1:
        raise ValueError("Satu root struktur Stok native diperlukan.")
    root = roots[0]
    if root.get("data-stamp") != "__PADI_STAMP__" or root.get("data-url") != "__PADI_DATA_URL__":
        raise ValueError("Hanya hasil compiler publik yang boleh diadaptasi.")
    controls = root.select_one("[data-stok-controls]")
    if controls is None or root.select("form[method='post'],[data-editor-perintah],[data-kemas-ulang]"):
        raise ValueError("Blueprint Stok tidak boleh berisi writer/editor.")
    if root.select("script[src*='stok-seragam'],script[src*='aksi.'],script[src*='editor']"):
        raise ValueError("Controller transaksi tidak termasuk blueprint publik.")
    scope = controls.select_one(".sk-cakupan")
    if scope is None or " ".join(scope.get_text(" ", strip=True).split()) != (
            "Cakupan mengikuti akses Anda · Pilihan gudang belum dibaca"):
        raise ValueError("Cakupan asset publik harus berupa label, bukan scope sumber.")
    if controls.select('input[name="gudang"][value]:not([value=""]),input[name="pelanggan_id"][value]:not([value=""])'):
        raise ValueError("Filter entitas tidak boleh berasal dari dokumen sumber.")
    if controls.select('select[name="gudang"] option[value]:not([value=""]),select[name="pelanggan_id"] option[value]:not([value=""])'):
        raise ValueError("Pilihan entitas tidak boleh berasal dari dokumen sumber.")
    if any(field.get("value", "") not in {"", "__PADI_SEARCH__"}
           for field in controls.select('[name="cari"]')):
        raise ValueError("Pencarian di asset publik hanya boleh placeholder.")

    for name, reason in (("gudang", WAREHOUSE_REASON), ("pelanggan_id", CUSTOMER_REASON)):
        selects = controls.select('form.sk-form-filter select[name="' + name + '"]')
        if len(selects) != 1:
            raise ValueError("Field native " + name + " tidak ditemukan.")
        select = selects[0]
        select.clear()
        option = doc.new_tag("option", value="")
        option.string = "Menunggu pilihan " + ("gudang" if name == "gudang" else "pelanggan")
        select.append(option)
        select["disabled"] = ""
        select["data-ui-stock-options"] = name
        reason_id = "ui-stock-" + name + "-reason"
        select["aria-describedby"] = reason_id
        label = select.find_parent("label")
        label.attrs.pop("hidden", None)
        note = doc.new_tag("p", attrs={"id": reason_id, "class": "bantu", "role": "status"})
        note.string = reason
        label.insert_after(note)
    # Native choice-status is not allowed to suggest remote options are ready.
    status = controls.select_one("[data-stok-pelanggan-status]")
    if status:
        status.attrs.pop("hidden", None)
        status.string = "Pilihan belum dibaca. Filter kepemilikan dan pencarian tidak mencatat transaksi."

    for tab in controls.select(".kontrol-tab__item"):
        href = tab.attrs.pop("href", None)
        key = next((key for key, _ in TABS
                    if href == "/stok?tab=" + key + "&pemilik=semua"), None)
        if key is None:
            raise ValueError("Tautan tab publik tidak sesuai katalog native.")
        tab["data-ui-stock-href"] = href
        tab["data-ui-stock-tab"] = key
        tab["aria-disabled"] = "true"
        tab["tabindex"] = "-1"
    # All native/overflow print doors are present but require actual read data.
    for button in controls.select("[data-sk-cetak]"):
        button["disabled"] = ""
        button["aria-describedby"] = "shell-cetak-alasan"
    for field in controls.select('[name="pemilik"]'):
        field["data-ui-stock-owner"] = ""
    for field in controls.select('[name="cari"]'):
        field["data-ui-stock-search"] = ""
    # Entity filters are blank in public bytes, never copied from source HTML.
    for field in controls.select('input[name="gudang"],input[name="pelanggan_id"]'):
        field["value"] = ""
    for link in controls.select(".sk-riwayat-link"):
        link["data-ui-stock-ownership-href"] = link.attrs.pop("href")
        link["aria-disabled"] = "true"
        link["tabindex"] = "-1"
    if root.select('select[name="gudang"] option[value]:not([value=""]),select[name="pelanggan_id"] option[value]:not([value=""])'):
        raise ValueError("Pilihan entitas tidak boleh masuk asset publik.")
    return str(doc)
