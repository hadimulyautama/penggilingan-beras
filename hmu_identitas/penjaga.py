"""Penjaga paket — dipakai uji di tiap repo aplikasi.

  1. `vendor_selaras(repo)` — folder vendored `hmu_identitas/` disunting
     tangan atau basi terhadap repo `core/` di sebelah.
  2. `peran_harfiah(akar)` — pemeriksa AST: peran dibandingkan dengan teks
     harfiah (`role == "admin"`, `peran not in ("admin", "staff")`,
     `u.role = "admin"`, `.startswith("admin")`). Dikembangkan dari
     kantor/tests/test_peran.py (QA UJI-03), kini untuk kelima repo.
  3. `definisi_ganda(akar)` — aplikasi mendefinisikan sendiri `hash_sandi`,
     `buat_token`, dst. padahal paket ini sudah menyediakannya.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from . import AKAR_PAKET

NAMA_PAKET = "hmu_identitas"
MANIFEST = "MANIFEST.sha256"
_ABAIKAN = {".venv", "node_modules", "__pycache__", ".git", "graphify-out", NAMA_PAKET, "hmu_core", "core"}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def isi_manifest(akar_paket: Path) -> dict[str, str]:
    keluar = {}
    for p in sorted(akar_paket.rglob("*")):
        if p.is_file() and p.name != MANIFEST and "__pycache__" not in p.parts:
            keluar[str(p.relative_to(akar_paket))] = _sha(p)
    return keluar


def tulis_manifest(akar_paket: Path) -> Path:
    m = akar_paket / MANIFEST
    m.write_text("".join(f"{h}  {n}\n" for n, h in isi_manifest(akar_paket).items()))
    return m


def baca_manifest(akar_paket: Path) -> dict[str, str]:
    m = akar_paket / MANIFEST
    if not m.exists():
        return {}
    keluar = {}
    for baris in m.read_text().splitlines():
        h, _, n = baris.partition("  ")
        keluar[n] = h
    return keluar


def vendor_selaras(akar_repo: Path, nama_paket: str = NAMA_PAKET, repo_sumber: str = "core") -> list[str]:
    """Selisih vendored vs manifest, plus vs repo sumber di sebelah bila ada."""
    vend = akar_repo / nama_paket
    if not vend.exists():
        return [f"folder {nama_paket}/ tidak ada — jalankan scripts/sinkron.py di repo {repo_sumber}"]
    dicatat, nyata = baca_manifest(vend), isi_manifest(vend)
    selisih = [f"{n}: {'hilang' if n not in nyata else 'berubah'}"
               for n in dicatat if nyata.get(n) != dicatat[n]]
    selisih += [f"{n}: tak ada di manifest" for n in nyata if n not in dicatat]
    sumber = akar_repo.parent / repo_sumber / nama_paket
    if sumber.exists() and isi_manifest(sumber) != nyata:
        selisih.append(f"basi terhadap repo {repo_sumber}/ — jalankan scripts/sinkron.py")
    return selisih


# ───────────────────────── Peran harfiah (AST) ─────────────────────────

NAMA_PERAN = {"admin", "superadmin", "staff", "staf", "operator",
              "PETUGAS", "ADMIN", "SUPERADMIN"}


_KUNCI_PERAN = ("role", "peran")


def _soal_peran(s: ast.AST) -> bool:
    """`user.role`, `peran`, `saya.get("peran")`, `saya["peran"]` — bentuk
    dict-nya yang dulu lolos, dan persis itu gerbang Meja (QA M-06)."""
    if isinstance(s, ast.Attribute):
        return s.attr in _KUNCI_PERAN
    if isinstance(s, ast.Name):
        return s.id in (*_KUNCI_PERAN, "coarse")
    if isinstance(s, ast.Call) and isinstance(s.func, ast.Attribute) and s.func.attr == "get":
        return bool(s.args) and isinstance(s.args[0], ast.Constant) and s.args[0].value in _KUNCI_PERAN
    if isinstance(s, ast.Subscript):
        return isinstance(s.slice, ast.Constant) and s.slice.value in _KUNCI_PERAN
    return False


def _literal_peran(s: ast.AST) -> bool:
    if isinstance(s, ast.Constant):
        return s.value in NAMA_PERAN
    if isinstance(s, (ast.Tuple, ast.List, ast.Set)):
        return any(_literal_peran(x) for x in s.elts)
    return False


class _Pengintai(ast.NodeVisitor):
    def __init__(self, berkas: str):
        self.berkas, self.temuan = berkas, []

    def _catat(self, n, apa):
        self.temuan.append(f"{self.berkas}:{n.lineno}: {apa}")

    def visit_Compare(self, n):
        sisi = [n.left] + list(n.comparators)
        if any(_soal_peran(x) for x in sisi) and any(_literal_peran(x) for x in sisi):
            self._catat(n, "peran dibandingkan dengan teks harfiah")
        self.generic_visit(n)

    def visit_Assign(self, n):
        for t in n.targets:
            if isinstance(t, ast.Attribute) and _soal_peran(t) and _literal_peran(n.value):
                self._catat(n, "peran DITIMPA dengan teks harfiah")
        self.generic_visit(n)

    def visit_Call(self, n):
        f = n.func
        if (isinstance(f, ast.Attribute) and f.attr in ("startswith", "endswith")
                and _soal_peran(f.value) and any(_literal_peran(a) for a in n.args)):
            self._catat(n, f"peran diperiksa dengan .{f.attr}()")
        self.generic_visit(n)


def peran_harfiah_dalam_teks(teks: str, nama: str) -> list[str]:
    p = _Pengintai(nama)
    p.visit(ast.parse(teks))
    return p.temuan


def peran_harfiah(akar: Path, kecuali: tuple[str, ...] = ("peran.py",)) -> list[str]:
    """Semua .py di bawah `akar` (biasanya `<repo>/app`), kecuali nama berkas
    di `kecuali` dan folder paket vendored."""
    temuan: list[str] = []
    for b in sorted(akar.rglob("*.py")):
        if b.name in kecuali or any(bag in _ABAIKAN for bag in b.relative_to(akar).parts[:-1]):
            continue
        temuan += peran_harfiah_dalam_teks(b.read_text(), str(b.relative_to(akar)))
    return temuan


# ───────────────────────── Definisi ganda ─────────────────────────

FUNGSI_PAKET = ("hash_sandi", "cek_sandi", "cek_sandi_async", "sandi_acak")


def definisi_ganda(akar: Path) -> list[str]:
    """Aplikasi mendefinisikan ulang fungsi yang sudah ada di paket."""
    temuan = []
    for b in sorted(akar.rglob("*.py")):
        if any(bag in _ABAIKAN for bag in b.relative_to(akar).parts[:-1]):
            continue
        for n in ast.walk(ast.parse(b.read_text())):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in FUNGSI_PAKET:
                temuan.append(f"{b.relative_to(akar)}:{n.lineno}: {n.name}() didefinisikan ulang")
    return temuan
