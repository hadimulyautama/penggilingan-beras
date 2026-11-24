"""Dua blueprint dryer publik dari label native; tidak mengimpor app/DB."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader, Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ("kerangka-pengeringan-ui.js", "kerangka-pengeringan-ui.meta.json")


def build():
    module_path = ROOT / "app/web/pengeringan_native_html.py"
    inputs = {Path(__file__).resolve(), module_path,
              ROOT / "app/web/static/kerangka-pengeringan-ui-runtime.js"}
    spec = importlib.util.spec_from_file_location("drying_native_public_metadata", module_path)
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    crumb_path = ROOT / 'app/web/breadcrumb.py'
    inputs.add(crumb_path)
    spec = importlib.util.spec_from_file_location('drying_native_breadcrumb', crumb_path)
    breadcrumb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(breadcrumb)
    meta = native.metadata()
    inputs.update(ROOT / path for path in meta["inputs"])
    roots = [ROOT / "app/web", ROOT / "hmu_tampilan"]

    class SourceLoader(FileSystemLoader):
        def get_source(self, environment, template):
            result = super().get_source(environment, template)
            inputs.add(Path(result[1]))
            return result

    env = Environment(loader=ChoiceLoader([SourceLoader(str(p / "templates")) for p in roots]),
                      autoescape=True, undefined=StrictUndefined)

    def asset(url, depth=0, seen=()):
        parsed = urlsplit(url)
        name = parsed.path.removeprefix("/static/")
        if parsed.scheme or parsed.netloc or not parsed.path.startswith("/static/") or not name or "/" in name or "\\" in name or depth > 8 or name in seen:
            raise ValueError("Aset dryer wajib program lokal native")
        path = next(p / "static" / name for p in roots if (p / "static" / name).is_file())
        inputs.add(path)
        text = path.read_text()
        if name.endswith(".css"):
            text = re.sub(r"@import\s+url\(['\"](/static/[^'\"]+)['\"]\);",
                          lambda m: asset(m[1], depth + 1, (*seen, name)), text)
            if "@import" in text or "</style" in text.lower():
                raise ValueError("Import gaya dryer perlu review")
        return text

    variants = {}
    for phase in native.FASE:
        state = native.deskripsi(f"/proses-aktif/{phase}/PADI-KODE")
        state.update(meta)
        state["stamp"] = "__PADI_STAMP__"
        t = env.get_template("pengeringan_native_html.html")
        html = "".join(t.blocks["isi"](t.new_context(dict(
            DRYER_KERANGKA=state, VERSI="__PADI_CAP__", kembali="/pekerjaan?tab=berjalan"))))
        doc = BeautifulSoup(html, "html.parser")
        if doc.select("form,input,select,textarea,[name],[data-post],[data-kirim]"):
            raise ValueError("Blueprint dryer tidak boleh mempunyai field transaksi")
        for node in doc.select('link[rel="stylesheet"]'):
            style = doc.new_tag("style")
            style.string = asset(node["href"])
            node.replace_with(style)
        for node in doc.select("script[src]"):
            text = asset(node["src"])
            if "document.currentScript" in text:
                raise ValueError("Binding skrip dryer perlu review")
            node.attrs.clear()
            node.string = text.replace("</script", "<\\/script")
        crumb = env.get_template('_breadcrumb.html').render(rantai=breadcrumb.susun(
            state['alamat'], dict(kembali='/pekerjaan?tab=berjalan', breadcrumb_detail='PADI-KODE'), phase.title() + ' aktif'))
        variants[phase] = dict(html=str(doc), breadcrumb=crumb)
        if len(variants[phase]["html"].encode()) > 262144:
            raise ValueError("Blueprint fase dryer melebihi batas")
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(inputs)}
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    data = dict(versi=1, sumber=digest, variants=variants)
    payload = ("/* Struktur dryer publik; tanpa akun, izin, angka lot atau transaksi. */\n"
               "window.PadiKerangkaPengeringanData=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n"
               + (ROOT / "app/web/static/kerangka-pengeringan-ui-runtime.js").read_text()).encode()
    if len(payload) > 600000:
        raise ValueError("Paket dua fase dryer melebihi batas")
    manifest = dict(versi=1, sumber=digest, variants=list(native.FASE),
                    aset_sha256=hashlib.sha256(payload).hexdigest(), inputs=hashes)
    return payload, (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args()
    for name, payload in zip(OUTPUTS, build()):
        target = ROOT / "app/web/static" / name
        if options.check:
            if target.read_bytes() != payload:
                raise AssertionError("Paket dryer basi: " + name)
        else:
            target.write_bytes(payload)
        print(name, len(payload))
