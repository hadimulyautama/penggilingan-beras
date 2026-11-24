"""Compile seven public native History structures, never actors/records/DB."""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path

from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader, Environment, FileSystemLoader, StrictUndefined
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[1]
CAP = "__PADI_CAP__"
OUTPUTS = ("kerangka-riwayat-ui.js", "kerangka-riwayat-ui.meta.json")


def pure_module(name, path, inputs):
    inputs.add(path)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def native_navigation_literals():
    source = ROOT / "app/web/laporan_navigasi.py"
    result = {}
    for node in ast.parse(source.read_text()).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {"TAB", "PROSES", "QC"}:
                    result[target.id] = ast.literal_eval(node.value)
    if set(result) != {"TAB", "PROSES", "QC"}:
        raise ValueError("Native navigation constants changed")
    return result


def public_navigation(path, meta, literals):
    family = meta["family"]
    first = {"proses": literals["PROSES"][0][2], "qc": literals["QC"][0][2],
             "laporan": "/laporan", "audit": "/audit"}
    allowed = {"proses": [row[2] for row in literals["PROSES"]],
               "qc": [row[2] for row in literals["QC"]],
               "laporan": ["/laporan"], "audit": ["/audit"]}
    return dict(aktif=family, judul="Riwayat proses" if family == "proses" else "Riwayat QC",
                jenis=meta["kind"], detail=False, panduan="rpd-panduan" if family == "proses" else "rqd-panduan",
                pakai_jumlah=False,
                tab=[dict(kunci=key, nama=name, href=first[key], boleh=True, alamat=allowed[key])
                     for key, name in literals["TAB"] if key != "laporan"],
                pilihan=literals["PROSES"] if family == "proses" else literals["QC"],
                boleh_alamat=allowed[family])


class SourceLoader(FileSystemLoader):
    def __init__(self, root, inputs):
        super().__init__(str(root)); self.inputs = inputs
    def get_source(self, environment, template):
        result = super().get_source(environment, template)
        self.inputs.add(Path(result[1]))
        return result


def build():
    inputs = {Path(__file__).resolve(), ROOT / "app/web/static/kerangka-riwayat-ui-runtime.js",
              ROOT / "app/web/laporan_navigasi.py"}
    primary = pure_module("public_history_compiler_helpers", ROOT / "scripts/buat_kerangka_ui.py", inputs)
    metadata = pure_module("public_history_list_metadata", ROOT / "app/web/riwayat_daftar_metadata.py", inputs)
    breadcrumb = pure_module("public_history_breadcrumb", ROOT / "app/web/breadcrumb.py", inputs)
    literals = native_navigation_literals()
    roots = [ROOT / "app/web", ROOT / "hmu_tampilan"]
    env = Environment(loader=ChoiceLoader([SourceLoader(root / "templates", inputs) for root in roots]),
                      undefined=StrictUndefined, autoescape=True)
    def no_record_format(*args, **kwargs):
        raise AssertionError("Public history blueprint must not format records")
    env.filters["jam"] = no_record_format

    def asset(url):
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc or not parsed.path.startswith("/static/"):
            raise ValueError("History blueprint assets must be native local program")
        name = parsed.path.removeprefix("/static/")
        if not name or "/" in name or "\\" in name:
            raise ValueError("History asset path changed")
        path = next((root / "static" / name for root in roots if (root / "static" / name).is_file()), None)
        if path is None:
            raise ValueError("History asset unavailable")
        inputs.add(path)
        return path.read_text()

    variants = {}
    paths = [*metadata.PROCESS, *sorted("/riwayat-qc/" + kind for kind in metadata.QC)]
    for path in paths:
        meta = metadata.metadata(path)
        inputs.add(ROOT / "app/web/templates" / meta["source_template"])
        if meta["family"] == "qc":
            inputs.add(ROOT / "app/web/layar_riwayat.py")
        request = Request(dict(type="http", method="GET", path=path, raw_path=path.encode(),
                               scheme="http", server=("ui.invalid", 80), headers=[], query_string=b""))
        context = dict(request=request, VERSI=CAP, PORTAL_READ_ONLY=False,
                       TAMPILAN_INDUK=True, RIWAYAT_META=meta, RIWAYAT_STATE=metadata.keadaan("loading"),
                       RIWAYAT_URL=path, RIWAYAT_STAMP="__PADI_STAMP__",
                       LAPORAN_NAV=public_navigation(path, meta, literals), jenis=meta["kind"])
        if meta["family"] == "proses":
            # Render the REAL parent's isi with exactly the child's two
            # metadata-only overrides. Do not render native row loops with
            # invented/empty ORM records and fabricate "zero" summaries.
            parent = env.get_template("_daftar_riwayat_proses.html")
            child = env.get_template("riwayat_proses_daftar_kerangka.html")
            context["rh"] = env.get_template("_riwayat.html").make_module(context)
            ctx = parent.new_context(context)
            for name in ("daftar_isi", "daftar_skrip"):
                ctx.blocks[name] = [child.blocks[name]]
            native = "".join(parent.blocks["isi"](ctx))
        else:
            template = env.get_template("riwayat_qc_daftar_kerangka.html")
            native = "".join(template.blocks["isi"](template.new_context(context)))
        wrapper = env.get_template("laporan_katalog_blueprint.html")
        html = wrapper.render(**context, KATALOG_NATIVE=native)
        doc = BeautifulSoup(html, "html.parser")
        if (not doc.select_one(".laporan-riwayat > .laporan-isi [data-riwayat-daftar-native]")
                or doc.select("form,input,[name],[data-post],[data-kirim],#formulir-sesi")):
            raise ValueError("Public History structure must contain no transaction/identity input")
        for button in doc.select("[data-lk-cetak],[data-rpd-print]"):
            button["disabled"] = ""
            button["aria-describedby"] = "riwayat-native-cetak-alasan"
        for link in doc.select('link[rel="stylesheet"]'):
            css = asset(link["href"])
            if "@import" in css or "</style" in css.lower():
                raise ValueError("History style import needs explicit review")
            style = doc.new_tag("style", attrs={"data-history-ui-style": link["href"].split("?")[0]})
            style.string = primary.compact_css_comments(css)
            link.replace_with(style)
        for node in doc.select("script[src]"):
            program = asset(node["src"])
            if "document.currentScript" in program:
                raise ValueError("Readonly History script requires review")
            node.attrs.clear()
            node.string = program.replace("</script", "<\\/script")
        crumb = env.get_template("_breadcrumb.html").render(rantai=breadcrumb.susun(
            path, {"LAPORAN_NAV": context["LAPORAN_NAV"]}, meta["title"]))
        variants[path] = dict(title=meta["title"], html=str(doc), breadcrumb=crumb)

    styles, scripts, style_refs, script_refs = {}, {}, {}, {}
    for variant in variants.values():
        doc = BeautifulSoup(variant["html"], "html.parser")
        for selector, pool, refs, attribute in [
            ("style", styles, style_refs, "data-history-style-ref"),
            ("script:not([type])", scripts, script_refs, "data-history-script-ref"),
        ]:
            for node in doc.select(selector):
                text = node.string or ""
                key = primary.intern_text(pool, refs, text)
                node.clear(); node[attribute] = key
        variant["html"] = str(doc)
    hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sorted(inputs)}
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    data = dict(versi=1, sumber=digest, variants=variants, styles=styles, scripts=scripts)
    runtime = (ROOT / "app/web/static/kerangka-riwayat-ui-runtime.js").read_text()
    payload = ("/* Public native History structure only; generated by scripts/buat_kerangka_riwayat.py. */\n"
               + "window.PadiKerangkaRiwayatData="
               + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n" + runtime).encode()
    if len(payload) > 1572864:
        raise ValueError("Separate History public asset exceeds structural bound")
    manifest = dict(versi=1, sumber=digest, aset_sha256=hashlib.sha256(payload).hexdigest(),
                    variants=list(variants), inputs=hashes)
    return payload, (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for name, payload in zip(OUTPUTS, build()):
        path = ROOT / "app/web/static" / name
        if args.check:
            if path.read_bytes() != payload:
                raise AssertionError("Generated History asset differs: " + name)
        else:
            path.write_bytes(payload)
        print(name, len(payload), "bytes")


if __name__ == "__main__":
    main()
